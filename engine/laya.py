"""Laya - the open-source, Jev-compatible System-1 decision model.

Laya (https://github.com/receptron/laya; weights by Convai Innovations, Apache-2.0) does not
generate text. You hand it a state and typed questions, and it returns every answer with
calibrated probabilities in one forward pass - the same choice / score / noul shape as
TypeSafe Jev's system_one. It runs entirely locally, which is why the project vision names it
as the preferred local-first decision provider.

Two backends, tried in order:
  1. HTTP  - LAYA_BASE_URL names a Jev-compatible system_one endpoint (a hosted Laya, or any
             server that speaks the shape).
  2. local - Node 20+ runs laya_server.mjs, which loads the real @receptron/laya package
             (ONNX Runtime) ONCE and then answers many decisions over stdin/stdout. Loki asks
             Laya about every request (first_layer.py), so the model must stay warm. The model
             head is NEVER reimplemented here. tools/setup_laya.py installs the package and
             downloads the weights into harness_data/laya, after which it works offline.

Optional and non-fatal, exactly like jev.py: with no backend - or on any network, process or
HTTP error - every call returns None/{} and the caller keeps its own heuristic.

Config (read from harness_data/.env like everything else):
  LAYA_BASE_URL       HTTP backend endpoint (optional)
  LAYA_API_KEY        bearer token for the HTTP backend (optional)
  LOKI_LAYA_LOCAL     "1" (default) allows the local Node backend; "0" disables it
  LOKI_LAYA_NODE      node executable (default "node" on PATH)
  LOKI_LAYA_PACKAGE_DIR folder whose node_modules holds @receptron/laya (default harness_data/laya)
  LOKI_LAYA_MODEL_DIR local ONNX export (else the weights cached in harness_data/laya/cache)
  LOKI_LAYA_TIMEOUT   seconds per decision (default 30)
  LOKI_LAYA_LOAD_TIMEOUT seconds to load the model into memory (default 180)
  LOKI_LAYA_IDLE      seconds without a decision before the warm process exits (default 1800)
  LOKI_LAYA_CACHE     cache identical decisions (default on)
  LOKI_LAYA_RISK      risk-gate threshold, 0..1 (default 0.15)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, "laya_server.mjs")

STATS = {"calls": 0, "errors": 0, "last_ms": 0.0, "backend": ""}
_cache: dict = {}
_lock = threading.Lock()


def base_url() -> str:
    return str(os.getenv("LAYA_BASE_URL") or "").strip().rstrip("/")


def api_key() -> str:
    return str(os.getenv("LAYA_API_KEY") or "").strip()


def node_exe() -> str:
    return str(os.getenv("LOKI_LAYA_NODE") or "").strip() or "node"


def data_dir() -> str:
    explicit = str(os.getenv("LOKI_DATA") or "").strip()
    return explicit or os.path.join(os.path.dirname(HERE), "harness_data")


def package_dir() -> str:
    """Directory whose node_modules holds @receptron/laya (default: harness_data/laya)."""
    return str(os.getenv("LOKI_LAYA_PACKAGE_DIR") or "").strip() or os.path.join(data_dir(), "laya")


def cache_dir() -> str:
    """Where the ONNX weights are cached, so Laya works offline once downloaded."""
    return str(os.getenv("LAYA_CACHE") or "").strip() or os.path.join(package_dir(), "cache")


def _candidate_roots():
    roots = []
    explicit = package_dir()
    if explicit:
        roots.append(explicit)
    parts = os.path.abspath(os.path.dirname(DRIVER)).split(os.sep)
    for i in range(len(parts), 0, -1):
        roots.append(os.sep.join(parts[:i]))
    for base in str(os.getenv("NODE_PATH") or "").split(os.pathsep):
        if base:
            roots.append(base)
    return roots


def weights_cached() -> bool:
    """True when the ONNX bundle is on disk (so Laya can load with no network)."""
    if str(os.getenv("LOKI_LAYA_MODEL_DIR") or "").strip():
        return os.path.isfile(os.path.join(os.getenv("LOKI_LAYA_MODEL_DIR"), "laya.onnx"))
    for root, _dirs, files in os.walk(cache_dir()):
        if "laya.onnx" in files and "laya.onnx.data" in files:
            return True
    return False


def package_installed() -> bool:
    """True when @receptron/laya can be resolved from a candidate node_modules tree."""
    for root in _candidate_roots():
        if os.path.isfile(os.path.join(root, "node_modules", "@receptron", "laya", "package.json")):
            return True
    return False


def local_allowed() -> bool:
    if str(os.getenv("LOKI_LAYA_LOCAL", "1")).strip().lower() in ("0", "false", "off", "no"):
        return False
    return (bool(shutil.which(node_exe())) and os.path.isfile(DRIVER)
            and package_installed())


def backend() -> str:
    """Which backend will be used: 'http', 'node', or '' when Laya is unavailable."""
    if base_url():
        return "http"
    if local_allowed():
        return "node"
    return ""


def enabled() -> bool:
    return backend() != ""


def available() -> bool:
    return enabled()


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def timeout_s() -> float:
    return _float_env("LOKI_LAYA_TIMEOUT", 30.0)


def load_timeout_s() -> float:
    return _float_env("LOKI_LAYA_LOAD_TIMEOUT", 180.0)


def node_env() -> dict:
    env = dict(os.environ, LOKI_LAYA_PACKAGE_DIR=package_dir(), LAYA_CACHE=cache_dir())
    return env


class Server:
    """One warm laya_server.mjs process: started on first use, restarted if it dies, and
    stopped after LOKI_LAYA_IDLE seconds without a decision (the model holds ~2 GB)."""

    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.lines: list = []
        self.cond = threading.Condition()
        self.state = "stopped"          # stopped | loading | ready | failed
        self.error = ""
        self.load_ms = 0
        self.last_used = 0.0
        self.failed_at = 0.0
        self.seq = 0

    def _reader(self, proc) -> None:
        for raw in iter(proc.stdout.readline, b""):
            try:
                msg = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            with self.cond:
                if msg.get("ready"):
                    self.state, self.load_ms = "ready", int(msg.get("ms") or 0)
                elif msg.get("fatal"):
                    self.state, self.error = "failed", str(msg["fatal"])[:300]
                    self.failed_at = time.monotonic()
                elif "id" in msg:
                    self.lines.append(msg)
                self.cond.notify_all()
        with self.cond:
            if self.proc is proc:
                if self.state != "failed":
                    self.state = "stopped"
                self.proc = None
            self.cond.notify_all()

    def start(self) -> None:
        with self.cond:
            if self.proc is not None and self.proc.poll() is None:
                return
            # A model that failed to load is not retried on every request (it is heavy).
            if self.state == "failed" and time.monotonic() - self.failed_at < _float_env("LOKI_LAYA_RETRY", 600.0):
                return
            self.state, self.error, self.lines = "loading", "", []
            try:
                self.proc = subprocess.Popen(
                    [node_exe(), DRIVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, env=node_env())
            except OSError as exc:
                self.proc, self.state, self.error = None, "failed", str(exc)[:300]
                self.failed_at = time.monotonic()
                return
            proc = self.proc
        threading.Thread(target=self._reader, args=(proc,), daemon=True).start()
        threading.Thread(target=self._idle_watch, args=(proc,), daemon=True).start()

    def _idle_watch(self, proc) -> None:
        idle = _float_env("LOKI_LAYA_IDLE", 1800.0)
        while proc.poll() is None:
            time.sleep(min(30.0, max(1.0, idle / 4)))
            if self.last_used and time.monotonic() - self.last_used > idle:
                self.stop()
                return

    def stop(self) -> None:
        with self.cond:
            proc, self.proc = self.proc, None
            self.state = "stopped" if self.state != "failed" else self.state
        if proc is not None:
            try:
                proc.stdin.close()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    def wait_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self.cond:
            while self.state == "loading" and time.monotonic() < deadline:
                self.cond.wait(timeout=max(0.05, deadline - time.monotonic()))
            return self.state == "ready"

    def ask(self, state, questions: dict, timeout: float) -> dict:
        self.start()
        if not self.wait_ready(load_timeout_s()):
            raise RuntimeError(self.error or "laya did not load in time")
        with self.lock:  # one request in flight at a time, answered in order
            with self.cond:
                self.seq += 1
                rid = str(self.seq)
                proc = self.proc
            if proc is None:
                raise RuntimeError("laya process stopped")
            proc.stdin.write((json.dumps({"id": rid, "state": state, "questions": questions}) + "\n").encode("utf-8"))
            proc.stdin.flush()
            deadline = time.monotonic() + timeout
            with self.cond:
                while True:
                    for i, msg in enumerate(self.lines):
                        if msg.get("id") == rid:
                            self.lines.pop(i)
                            self.last_used = time.monotonic()
                            if msg.get("error"):
                                raise RuntimeError(str(msg["error"])[:200])
                            return msg
                    if self.proc is None or time.monotonic() >= deadline:
                        break
                    self.cond.wait(timeout=max(0.05, deadline - time.monotonic()))
        self.stop()  # a stuck request means a stuck process: start fresh next time
        raise RuntimeError("laya timed out after %ss" % timeout)

    def snapshot(self) -> dict:
        return {"state": self.state, "error": self.error, "load_ms": self.load_ms}


SERVER = Server()


def warm() -> None:
    """Start loading the model in the background (the engine calls this at startup)."""
    if backend() == "node":
        SERVER.start()


def ready() -> bool:
    """True when a decision can be answered right now without waiting for a model load."""
    which = backend()
    return which == "http" or (which == "node" and SERVER.state == "ready")


def _http_decide(payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base_url(), data=data, method="POST")
    if api_key():
        request.add_header("Authorization", "Bearer " + api_key())
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "Loki/1.0 (+https://github.com/m03dev/loki)")
    with urllib.request.urlopen(request, timeout=timeout_s()) as response:
        return json.loads(response.read().decode("utf-8"))


def _node_decide(payload: dict, timeout: float | None = None) -> dict:
    return SERVER.ask(payload.get("state"), payload.get("questions") or {},
                      timeout if timeout is not None else timeout_s())


def decide(questions: dict, state, timeout: float | None = None) -> dict:
    """Evaluate typed questions against ONE state. Returns the answers map.

    Never raises: on any failure this returns {} so the caller keeps its own heuristic.
    Questions are answered in one forward pass, so a risk gate can ask 'destructive?' and
    'action?' in a single round trip.
    """
    which = backend()
    if not which or not questions:
        return {}
    payload = {"model": "laya", "state": state, "questions": questions}
    cache_key = ""
    if str(os.getenv("LOKI_LAYA_CACHE", "1")).strip().lower() not in ("0", "false", "off"):
        cache_key = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        with _lock:
            if cache_key in _cache:
                return _cache[cache_key]
    started = time.monotonic()
    try:
        body = _http_decide(payload) if which == "http" else _node_decide(payload, timeout)
    except Exception as exc:  # network, process, HTTP, JSON - all non-fatal
        with _lock:
            STATS["errors"] += 1
        print("  [laya] decision unavailable: %s" % str(exc)[:120])
        return {}
    with _lock:
        STATS["calls"] += 1
        STATS["backend"] = which
        STATS["last_ms"] = (time.monotonic() - started) * 1000.0
        answers = body.get("answers") or {}
        if cache_key:
            _cache[cache_key] = answers
    return answers


def noul(question: str, state, criteria: dict | None = None):
    """Probability the answer is YES (0..1), or None when Laya is unavailable."""
    spec = {"type": "noul", "instructions": question}
    if criteria:
        spec["criteria"] = criteria
    answer = (decide({"q": spec}, state).get("q")) or {}
    value = answer.get("noul")
    return float(value) if isinstance(value, (int, float)) else None


def choice(question: str, criteria: dict, state):
    """The winning option key and its confidence, or None when unavailable."""
    answers = decide({"q": {"type": "choice", "instructions": question, "criteria": criteria}}, state)
    answer = answers.get("q") or {}
    picked = answer.get("choice")
    if not isinstance(picked, str):
        return None
    confidence = answer.get("confidence")
    return picked, (float(confidence) if isinstance(confidence, (int, float)) else 0.0)


def risk_threshold() -> float:
    try:
        return float(os.getenv("LOKI_LAYA_RISK", "0.15"))
    except ValueError:
        return 0.15


def risk_gate(kind: str, detail: str):
    """Gate one risky action: 'allow' when confidently safe, else 'confirm'.

    Returns None when Laya is off, so the caller keeps its own approval path. The human path
    stays AUTHORITATIVE: 'confirm' means ask, never a silent 'block'.
    """
    if not enabled():
        return None
    state = ("The agent is about to run tool '%s' with these arguments: %s"
             % (kind, str(detail)[:600]))
    answers = decide({
        "destructive": {
            "type": "noul",
            "instructions": ("Is this action destructive, irreversible, or able to affect "
                             "anything outside the project workspace?")},
        "action": {
            "type": "choice",
            "instructions": "Should this action run without asking a human first?",
            "criteria": {"allow": "clearly safe to run now",
                         "confirm": "ask the human before running"}},
    }, state)
    destructive = (answers.get("destructive") or {}).get("noul")
    action = (answers.get("action") or {}).get("choice")
    if not isinstance(destructive, (int, float)):
        return None
    if action == "allow" and destructive < risk_threshold():
        return "allow"
    return "confirm"


def status() -> dict:
    """A JSON-safe snapshot for the doctor, the bridge and the dock."""
    return {
        "enabled": enabled(),
        "backend": backend(),
        "endpoint": base_url() or (("node " + DRIVER) if local_allowed() else ""),
        "node": bool(shutil.which(node_exe())),
        "package": package_installed(),
        "weights": weights_cached(),
        "server": SERVER.snapshot(),
        "risk_threshold": risk_threshold(),
        "calls": STATS["calls"],
        "errors": STATS["errors"],
        "last_ms": round(STATS["last_ms"], 1),
    }
