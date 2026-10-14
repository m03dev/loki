"""Offline-first model setup: find what this computer can run, and get it running.

Loki's goal is to be fast and smart with no internet and no account. This module:

  * measures the machine (RAM, Apple Silicon unified memory, NVIDIA VRAM),
  * finds local model servers that are already running (Ollama, LM Studio, llama.cpp
    server, Jan) and the models they hold,
  * asks Ollama which installed models can call tools (`/api/show` capabilities), and
    picks the best one that fits,
  * recommends a model to download when there is none, and downloads it through
    Ollama's own `/api/pull` with live progress, falling back to the next candidate
    when a tag does not exist,
  * installs Ollama itself when the user asks (macOS: the official DMG; Windows: the
    official installer; Linux: shows the official one-line command - never piped
    through a shell by Loki),
  * prepares a "loki-<model>" variant with a larger context window (`/api/create` with
    `num_ctx`) - Ollama's default window is far too small for an agent prompt with
    tools, which is the main reason local models looked dumb in Loki,
  * keeps the chosen model loaded (`keep_alive`) so replies start fast.

Standard library only. Every network call is to localhost or to ollama.com downloads
the user asked for, with timeouts.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434").rstrip("/")
# Other OpenAI-compatible local servers Loki connects to automatically.
LOCAL_SERVERS = (
    ("lmstudio", "LM Studio", "http://127.0.0.1:1234/v1"),
    ("llamacpp", "llama.cpp server", "http://127.0.0.1:8080/v1"),
    ("jan", "Jan", "http://127.0.0.1:1337/v1"),
)
# Download candidates, best first within each memory budget. `need` is the memory the
# model needs to run comfortably (weights + an agent-sized context), in GB. Tags are
# verified at pull time; a missing tag falls through to the next candidate.
CATALOG = [
    {"tag": "qwen3:30b", "size": 19.0, "need": 24, "score": 92, "why": "MoE (3B active): big-model quality at small-model speed"},
    {"tag": "gpt-oss:20b", "size": 14.0, "need": 16, "score": 88, "why": "MoE (3.6B active), strong tool use, fast"},
    {"tag": "qwen3:14b", "size": 9.3, "need": 12, "score": 85, "why": "reliable tool calling, good reasoning"},
    {"tag": "qwen3.5:9b", "size": 6.6, "need": 9, "score": 82, "why": "newest small Qwen, tool calling"},
    {"tag": "qwen3:8b", "size": 5.2, "need": 7, "score": 78, "why": "the proven 8 GB agent model"},
    {"tag": "qwen3:4b", "size": 2.6, "need": 4, "score": 68, "why": "fast on modest hardware"},
    {"tag": "llama3.2:3b", "size": 2.0, "need": 3, "score": 55, "why": "smallest that still calls tools"},
]
# Quality hints for models already installed (substring of the tag -> score).
KNOWN_SCORES = [("qwen3:30b", 92), ("qwen3.8", 90), ("gpt-oss:20b", 88), ("gemma4:26b", 90),
                ("qwen3:32b", 90), ("qwen3:14b", 85), ("gemma4", 84), ("qwen3.5:9b", 82),
                ("qwen3.5", 80), ("qwen3:8b", 78), ("qwen2.5-coder:14b", 76), ("llama3.1:8b", 72),
                ("hermes3", 70), ("qwen3:4b", 68), ("qwen2.5", 65), ("llama3.2", 55)]
DERIVED_PREFIX = "loki-"
TIMEOUT = 3.0


# --------------------------------------------------------------------- hardware
def hardware(runner=subprocess.run) -> dict:
    """{os, arch, ram_gb, gpu, vram_gb, unified, budget_gb, chip}."""
    info = {"os": sys.platform, "arch": platform.machine().lower(), "ram_gb": 0.0, "gpu": "",
            "vram_gb": 0.0, "unified": False, "chip": platform.processor() or ""}
    try:
        if sys.platform == "darwin":
            out = runner(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout
            info["ram_gb"] = round(int(out.strip()) / 2**30, 1)
            chip = runner(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True,
                          timeout=5).stdout.strip()
            info["chip"] = chip or info["chip"]
            if info["arch"] in ("arm64", "aarch64"):
                info.update(unified=True, gpu="Apple Silicon (unified memory)")
        elif sys.platform == "win32":
            class _Mem(ctypes.Structure):  # MEMORYSTATUSEX
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            mem = _Mem()
            mem.dwLength = ctypes.sizeof(_Mem)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):  # type: ignore[attr-defined]
                info["ram_gb"] = round(mem.ullTotalPhys / 2**30, 1)
        else:
            text = Path("/proc/meminfo").read_text(encoding="utf-8")
            match = re.search(r"MemTotal:\s+(\d+)", text)
            if match:
                info["ram_gb"] = round(int(match.group(1)) / 2**20, 1)
    except Exception:
        pass
    if shutil.which("nvidia-smi"):
        try:
            out = runner(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=8).stdout.strip().splitlines()
            if out:
                name, mib = [p.strip() for p in out[0].split(",")[:2]]
                info.update(gpu=name, vram_gb=round(float(mib) / 1024, 1))
        except Exception:
            pass
    info["budget_gb"] = memory_budget(info)
    return info


def memory_budget(info: dict) -> float:
    """GB a model may use without making the computer crawl."""
    ram = float(info.get("ram_gb") or 0)
    if info.get("vram_gb"):
        return max(float(info["vram_gb"]) - 1.0, 0.0) + (0.25 * ram if ram >= 32 else 0.0)
    if info.get("unified"):
        return round(ram * 0.65, 1)       # macOS keeps ~1/3 for itself and your apps
    return round(ram * 0.5, 1)            # CPU only: slower, keep headroom


def context_for(info: dict) -> int:
    budget = float(info.get("budget_gb") or memory_budget(info))
    return 32768 if budget >= 24 else 16384 if budget >= 10 else 8192


# --------------------------------------------------------------------- local servers
def _get_json(url: str, timeout: float = TIMEOUT, opener=urllib.request.urlopen):
    with opener(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _post_json(url: str, body: dict, timeout: float = 30.0, opener=urllib.request.urlopen):
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    with opener(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def ollama_installed(which=shutil.which) -> bool:
    if which("ollama"):
        return True
    if sys.platform == "darwin":
        return any(Path(p).exists() for p in ("/Applications/Ollama.app",
                                               str(Path.home() / "Applications" / "Ollama.app")))
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        return bool(local) and Path(local, "Programs", "Ollama", "ollama.exe").exists()
    return False


def ollama_models(opener=urllib.request.urlopen) -> list[dict] | None:
    """[{name, size_gb, family, params}] or None when Ollama is not answering."""
    try:
        data = _get_json(OLLAMA + "/api/tags", opener=opener)
    except Exception:
        return None
    out = []
    for m in data.get("models", []) if isinstance(data, dict) else []:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        details = m.get("details") or {}
        out.append({"name": m["name"], "size_gb": round(float(m.get("size") or 0) / 2**30, 1),
                    "family": details.get("family", ""), "params": details.get("parameter_size", "")})
    return out


_CAPS: dict[str, list[str]] = {}


def capabilities(model: str, opener=urllib.request.urlopen) -> list[str]:
    """Ollama's own capability list for an installed model (cached)."""
    if model in _CAPS:
        return _CAPS[model]
    try:
        caps = _post_json(OLLAMA + "/api/show", {"model": model}, timeout=TIMEOUT, opener=opener).get("capabilities")
        caps = [str(c) for c in caps] if isinstance(caps, list) else []
    except Exception:
        caps = []
    _CAPS[model] = caps
    return caps


def other_servers(opener=urllib.request.urlopen) -> list[dict]:
    """Running LM Studio / llama.cpp / Jan servers and their models."""
    found = []
    for key, label, base in LOCAL_SERVERS:
        try:
            data = _get_json(base + "/models", timeout=1.0, opener=opener)
        except Exception:
            continue
        models = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
        if models:
            found.append({"key": key, "label": label, "base_url": base, "models": models})
    return found


def score(name: str) -> int:
    low = name.lower()
    if low.startswith(DERIVED_PREFIX):
        low = low[len(DERIVED_PREFIX):]
    for needle, value in KNOWN_SCORES:
        if needle in low:
            return value
    return 50


def best_installed(models: list[dict], budget_gb: float, caps=capabilities) -> dict | None:
    """The best installed Ollama model that calls tools and fits. Derived loki-* variants
    are preferred over their base (same weights, bigger window)."""
    ranked = []
    for m in models:
        name = m["name"]
        if "embed" in name.lower():
            continue
        tools = "tools" in caps(name)
        fits = not budget_gb or not m.get("size_gb") or m["size_gb"] <= budget_gb * 0.9
        ranked.append((tools, fits, score(name), name.lower().startswith(DERIVED_PREFIX), name, m))
    ranked.sort(key=lambda r: (r[0], r[1], r[2], r[3]), reverse=True)
    if not ranked:
        return None
    tools, fits, value, _derived, name, m = ranked[0]
    return {**m, "tools": tools, "fits": fits, "score": value}


def recommend(info: dict, installed: list[str] | None = None) -> list[dict]:
    """Download candidates that fit this machine, best first."""
    budget = float(info.get("budget_gb") or memory_budget(info))
    installed = installed or []
    picks = [dict(c, installed=any(n == c["tag"] or n.startswith(c["tag"] + "-") for n in installed))
             for c in CATALOG if c["need"] <= max(budget * 1.15, 3)]
    return picks or [dict(CATALOG[-1], installed=False)]


def derived_name(model: str) -> str:
    return DERIVED_PREFIX + re.sub(r"[^a-z0-9._-]+", "-", model.lower()).strip("-")


def ensure_context(model: str, num_ctx: int, models: list[dict], opener=urllib.request.urlopen) -> str:
    """Return a model name with a context window of at least `num_ctx`: an existing
    loki-<model> variant, or a new one made with /api/create (metadata only - no
    download, no copy of the weights)."""
    if model.startswith(DERIVED_PREFIX):
        return model
    target = derived_name(model)
    if any(m["name"].split(":")[0] == target or m["name"] == target for m in models):
        return target
    try:
        _post_json(OLLAMA + "/api/create", {"model": target, "from": model,
                                            "parameters": {"num_ctx": int(num_ctx)}, "stream": False},
                   timeout=120, opener=opener)
        _CAPS.pop(target, None)
        return target
    except Exception:
        return model  # older Ollama: keep the base model rather than fail


_WARMED: dict[str, float] = {}


def keep_warm(model: str, minutes: int = 30, opener=urllib.request.urlopen) -> bool:
    """Load the model now and keep it loaded, so the first reply is not a cold start.
    At most once every two minutes per model."""
    if time.time() - _WARMED.get(model, 0.0) < 120:
        return True
    _WARMED[model] = time.time()
    try:
        _post_json(OLLAMA + "/api/generate", {"model": model, "keep_alive": "%dm" % minutes},
                   timeout=180, opener=opener)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------- downloads
class Progress:
    """Shared state for one long operation (pull or install), read by the UI."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = {"op": "", "target": "", "status": "idle", "completed": 0, "total": 0,
                      "message": "", "error": "", "done": False, "started": 0.0}

    def update(self, **fields) -> None:
        with self.lock:
            self.state.update(fields)

    def snapshot(self) -> dict:
        with self.lock:
            snap = dict(self.state)
        total = snap.get("total") or 0
        snap["percent"] = round(100.0 * snap.get("completed", 0) / total, 1) if total else 0.0
        return snap

    def busy(self) -> bool:
        with self.lock:
            return bool(self.state.get("op")) and not self.state.get("done")


PROGRESS = Progress()


def pull(tags: list[str], progress: Progress = PROGRESS, opener=urllib.request.urlopen) -> str:
    """Pull the first tag that exists; stream progress. Returns the pulled tag or ""."""
    for tag in tags:
        progress.update(op="pull", target=tag, status="starting", completed=0, total=0,
                        message="Downloading %s" % tag, error="", done=False, started=time.time())
        request = urllib.request.Request(OLLAMA + "/api/pull", data=json.dumps({"model": tag, "stream": True}).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            with opener(request, timeout=60) as response:
                failed = ""
                for raw in response:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("error"):
                        failed = str(event["error"])
                        break
                    progress.update(status=str(event.get("status", "")),
                                    completed=int(event.get("completed") or 0) or progress.state["completed"],
                                    total=int(event.get("total") or 0) or progress.state["total"])
                    if event.get("status") == "success":
                        progress.update(done=True, status="success", message="%s is ready" % tag)
                        return tag
                if failed:
                    progress.update(error=failed, message="%s: %s - trying the next model" % (tag, failed))
                    continue
        except Exception as exc:  # noqa: BLE001 - reported to the UI, then next tag
            progress.update(error=str(exc)[:200], message="%s failed: %s" % (tag, str(exc)[:120]))
            continue
    progress.update(done=True, status="failed",
                    message="Could not download any model. Check the internet connection and try again.")
    return ""


def install_ollama(progress: Progress = PROGRESS, opener=urllib.request.urlopen, runner=subprocess.run) -> bool:
    """Download and install Ollama from ollama.com (user-initiated only)."""
    progress.update(op="install", target="Ollama", status="starting", completed=0, total=0, error="",
                    done=False, started=time.time(), message="Downloading Ollama")
    if sys.platform.startswith("linux"):
        progress.update(done=True, status="manual", message="On Linux run the official installer in a "
                        "terminal: curl -fsSL https://ollama.com/install.sh | sh  (Loki does not pipe "
                        "downloads into a shell for you).")
        return False
    url = "https://ollama.com/download/Ollama.dmg" if sys.platform == "darwin" else \
        "https://ollama.com/download/OllamaSetup.exe"
    target = Path(tempfile.mkdtemp(prefix="loki-ollama-")) / url.rsplit("/", 1)[-1]
    try:
        with opener(url, timeout=60) as response, open(target, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            progress.update(total=total, status="downloading")
            done = 0
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                progress.update(completed=done)
        progress.update(status="installing", message="Installing Ollama")
        if sys.platform == "darwin":
            mount = Path(tempfile.mkdtemp(prefix="loki-dmg-"))
            runner(["hdiutil", "attach", "-nobrowse", "-quiet", "-mountpoint", str(mount), str(target)],
                   check=True, timeout=120)
            try:
                dest = Path("/Applications") if os.access("/Applications", os.W_OK) else Path.home() / "Applications"
                dest.mkdir(parents=True, exist_ok=True)
                runner(["ditto", str(mount / "Ollama.app"), str(dest / "Ollama.app")], check=True, timeout=300)
            finally:
                runner(["hdiutil", "detach", "-quiet", str(mount)], timeout=60)
            runner(["open", "-a", str(dest / "Ollama.app")], timeout=30)
        else:
            # The official installer shows its own window (and asks Windows for permission).
            subprocess.Popen([str(target)])
        progress.update(status="starting Ollama", message="Waiting for Ollama to start")
        for _ in range(90):
            if ollama_models(opener=opener) is not None:
                progress.update(done=True, status="success", message="Ollama is running")
                return True
            time.sleep(2)
        progress.update(done=True, status="installed", message="Ollama is installed - open it once, then "
                        "come back to finish setup.")
        return True
    except Exception as exc:  # noqa: BLE001
        progress.update(done=True, status="failed", error=str(exc)[:200],
                        message="Could not install Ollama automatically: %s" % str(exc)[:120])
        return False


# --------------------------------------------------------------------- the whole picture
def status(env: dict | None = None, opener=urllib.request.urlopen, info: dict | None = None) -> dict:
    """Everything the first-run screen needs, in one call."""
    env = env if env is not None else os.environ
    info = info or hardware()
    models = ollama_models(opener=opener)
    best = best_installed(models, info["budget_gb"], caps=lambda n: capabilities(n, opener=opener)) if models else None
    servers = other_servers(opener=opener)
    cloud_keys = sorted(k for k, v in env.items() if k.endswith("_API_KEY") and str(v).strip())
    ready = bool(best and best.get("tools")) or bool(servers)
    return {
        "hardware": info,
        "ollama": {"installed": ollama_installed() or models is not None, "running": models is not None,
                   "models": models or []},
        "best": best,
        "servers": servers,
        "recommend": recommend(info, [m["name"] for m in models or []]),
        "context": context_for(info),
        "cloud_keys": cloud_keys,
        "ready_offline": ready,
        "progress": PROGRESS.snapshot(),
    }


def start_in_background(fn, *args) -> bool:
    if PROGRESS.busy():
        return False
    threading.Thread(target=fn, args=args, daemon=True, name="loki-model-setup").start()
    return True
