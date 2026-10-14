"""Laya - the open-source, Jev-compatible System-1 decision model.

Laya (https://github.com/receptron/laya; weights by Convai Innovations, Apache-2.0) does not
generate text. You hand it a state and typed questions, and it returns every answer with
calibrated probabilities in one forward pass - the same choice / score / noul shape as
TypeSafe Jev's system_one. It runs entirely locally, which is why the project vision names it
as the preferred local-first decision provider.

Two backends, tried in order:
  1. HTTP  - LAYA_BASE_URL names a Jev-compatible system_one endpoint (a hosted Laya, or any
             server that speaks the shape).
  2. local - Node 20+ runs laya_driver.mjs, which delegates to the real @receptron/laya package
             (ONNX Runtime). The model head is NEVER reimplemented here; the driver is a thin
             shim so behaviour matches the reference implementation exactly.

Optional and non-fatal, exactly like jev.py: with no backend - or on any network, process or
HTTP error - every call returns None/{} and the caller keeps its own heuristic.

Config (read from harness_data/.env like everything else):
  LAYA_BASE_URL       HTTP backend endpoint (optional)
  LAYA_API_KEY        bearer token for the HTTP backend (optional)
  LOKI_LAYA_LOCAL     "1" (default) allows the local Node backend; "0" disables it
  LOKI_LAYA_NODE      node executable (default "node" on PATH)
  LOKI_LAYA_MODEL_DIR local ONNX export for the driver (else it downloads from Hugging Face)
  LOKI_LAYA_TIMEOUT   seconds per decision (default 60; the first call downloads the model)
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

DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "laya_driver.mjs")

STATS = {"calls": 0, "errors": 0, "last_ms": 0.0, "backend": ""}
_cache: dict = {}
_lock = threading.Lock()


def base_url() -> str:
    return str(os.getenv("LAYA_BASE_URL") or "").strip().rstrip("/")


def api_key() -> str:
    return str(os.getenv("LAYA_API_KEY") or "").strip()


def node_exe() -> str:
    return str(os.getenv("LOKI_LAYA_NODE") or "").strip() or "node"


def package_dir() -> str:
    """Directory whose node_modules holds @receptron/laya (default: harness_data/laya)."""
    return str(os.getenv("LOKI_LAYA_PACKAGE_DIR") or "").strip()


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


def timeout_s() -> float:
    try:
        return float(os.getenv("LOKI_LAYA_TIMEOUT", "60"))
    except ValueError:
        return 60.0


def _http_decide(payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base_url(), data=data, method="POST")
    if api_key():
        request.add_header("Authorization", "Bearer " + api_key())
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "Loki/1.0 (+https://github.com/m03dev/loki)")
    with urllib.request.urlopen(request, timeout=timeout_s()) as response:
        return json.loads(response.read().decode("utf-8"))


def _node_decide(payload: dict) -> dict:
    request = {"state": payload.get("state"), "questions": payload.get("questions")}
    model_dir = str(os.getenv("LOKI_LAYA_MODEL_DIR") or "").strip()
    if model_dir:
        request["modelDir"] = model_dir
    package = package_dir()
    if package:
        request["packageDir"] = package
    try:
        proc = subprocess.run(
            [node_exe(), DRIVER],
            input=json.dumps(request).encode("utf-8"),
            capture_output=True, timeout=timeout_s())
    except subprocess.TimeoutExpired:
        raise RuntimeError("laya driver timed out after %ss" % timeout_s())
    text = (proc.stdout or b"").decode("utf-8", "replace").strip()
    if not text:
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise RuntimeError(detail or "laya driver produced no output")
    body = json.loads(text.splitlines()[-1])
    if body.get("error"):
        raise RuntimeError(str(body["error"])[:200])
    return body


def decide(questions: dict, state) -> dict:
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
        body = _http_decide(payload) if which == "http" else _node_decide(payload)
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
        "risk_threshold": risk_threshold(),
        "calls": STATS["calls"],
        "errors": STATS["errors"],
        "last_ms": round(STATS["last_ms"], 1),
    }
