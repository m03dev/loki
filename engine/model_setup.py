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
import importlib.util
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
# Download candidates, best first. `size` is the download (and disk) size in GB, `need` the
# memory the model needs to run comfortably (weights + an agent-sized context), `score` a
# quality estimate for agent work (tool calling, following instructions), `roles` what it
# is good for ("agent", "fast", "code"), `moe` = mixture-of-experts (only a few billion
# parameters active per token, so it runs much faster than its size suggests). Tags were
# checked on ollama.com/library (October 2026); a tag that disappears falls through to the
# next candidate at pull time.
CATALOG = [
    {"tag": "qwen3.8:27b", "size": 18.0, "need": 22, "score": 94, "roles": ["agent", "code"],
     "why": "the newest Qwen: the strongest open agent and coding model a home computer can run"},
    {"tag": "qwen3.5:35b-a3b", "size": 22.0, "need": 26, "score": 91, "roles": ["agent", "code"], "moe": True,
     "why": "big-model quality, but only 3B active so it answers quickly"},
    {"tag": "gemma4:26b", "size": 17.0, "need": 21, "score": 89, "roles": ["agent"], "moe": True,
     "why": "Google's Gemma 4: strong tool use, sees images"},
    {"tag": "qwen3-coder:30b", "size": 19.0, "need": 23, "score": 88, "roles": ["code"], "moe": True,
     "why": "built for coding agents, 256K context, 3B active so it is quick"},
    {"tag": "gpt-oss:20b", "size": 14.0, "need": 16, "score": 88, "roles": ["agent", "code"], "moe": True,
     "why": "OpenAI's open model: dependable tool calls, fast for its size"},
    {"tag": "qwen3:14b", "size": 9.3, "need": 12, "score": 85, "roles": ["agent", "code"],
     "why": "reliable tool calling and good reasoning"},
    {"tag": "qwen3.5:9b", "size": 6.6, "need": 8.5, "score": 84, "roles": ["agent", "code"],
     "why": "the best small all-rounder: tools, coding, 256K context"},
    {"tag": "gemma4:12b", "size": 8.0, "need": 10, "score": 83, "roles": ["agent"],
     "why": "Gemma 4 mid-size: good tool use, sees images"},
    # Bonsai 2 (PrismML, Apache-2.0): Qwen3.5 with ternary weights - near the original's quality at a
    # fraction of the size, with tool calling. Pulled straight from Hugging Face by Ollama. Name the
    # Q2_0 FILE in the tag (":Ternary-Bonsai-2-9B-Q2_0"): the short ":Q2_0" tag also matches the
    # "-PQ2_0" pack, whose Prism ternary type (ggml 142) Ollama cannot load at all. The Q2_0 files
    # (ggml type 42) run on Ollama 0.40.6+ / llama.cpp b11669+; verify_runs checks it really runs.
    {"tag": "hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Ternary-Bonsai-2-9B-Q2_0", "size": 2.6, "need": 4.5, "score": 83, "roles": ["agent", "fast"],
     "family": "bonsai", "why": "Bonsai 2 9B: Qwen3.5-9B quality in 2.6 GB (ternary weights), calls tools - the most model per GB"},
    {"tag": "hf.co/prism-ml/Ternary-Bonsai-2-4B-gguf:Ternary-Bonsai-2-4B-Q2_0", "size": 1.2, "need": 2.5, "score": 71, "roles": ["fast", "agent"],
     "family": "bonsai", "why": "Bonsai 2 4B: a capable agent model in 1.2 GB"},
    {"tag": "hf.co/prism-ml/Ternary-Bonsai-2-2B-gguf:Ternary-Bonsai-2-2B-Q2_0", "size": 0.6, "need": 1.5, "score": 57, "roles": ["fast"],
     "family": "bonsai", "why": "Bonsai 2 2B: 0.6 GB, for the smallest machines and quick replies"},
    {"tag": "qwen3:8b", "size": 5.2, "need": 7, "score": 78, "roles": ["agent", "code"],
     "why": "the proven 8 GB agent model"},
    {"tag": "granite4.1:8b", "size": 5.3, "need": 7, "score": 74, "roles": ["agent", "code"],
     "why": "IBM Granite 4.1: steady tool calls and clean JSON"},
    {"tag": "qwen3.5:4b", "size": 3.4, "need": 5, "score": 72, "roles": ["fast", "agent"],
     "why": "small and quick, still calls tools well"},
    {"tag": "granite4.1:3b", "size": 2.1, "need": 3, "score": 60, "roles": ["fast"],
     "why": "tiny and very fast, calls tools"},
    {"tag": "qwen3.5:2b", "size": 2.7, "need": 3.5, "score": 58, "roles": ["fast"],
     "why": "tiny and fast, for quick answers on modest hardware"},
    {"tag": "llama3.2:3b", "size": 2.0, "need": 3, "score": 55, "roles": ["fast"],
     "why": "smallest that still calls tools"},
]
# MLX alternatives on Apple Silicon (served by mlx_lm.server on port 8082, provider "mlx").
# Bonsai 2's MLX packs need mlx-vlm >= 0.7.8 (mlx-lm 0.32 cannot load them yet).
MLX_CATALOG = [
    {"repo": "prism-ml/Ternary-Bonsai-2-9B-mlx-2bit", "size": 3.5, "need": 5.5, "score": 83, "server": "mlx-vlm",
     "why": "Bonsai 2 9B for Apple Silicon (mlx-vlm >= 0.7.8), sees images too"},
    {"repo": "mlx-community/Qwen3.5-9B-OptiQ-4bit", "size": 6.6, "need": 9, "score": 84,
     "why": "Qwen3.5 9B tuned for Apple Silicon"},
    {"repo": "mlx-community/Qwen3.5-4B-MLX-4bit", "size": 3.0, "need": 4.5, "score": 72,
     "why": "Qwen3.5 4B, quick on any Apple Silicon Mac"},
    {"repo": "mlx-community/Qwen3-4B-4bit", "size": 2.3, "need": 4, "score": 68,
     "why": "the small model LOKI's MLX setup started with"},
]
# Quality hints for models already installed (first substring of the tag that matches).
KNOWN_SCORES = [("bonsai-2-27b", 90), ("bonsai-2-9b", 83), ("bonsai-2-4b", 71), ("bonsai-2-2b", 57), ("qwen3.8", 94), ("qwen3.5:122b", 93), ("qwen3.5:35b", 91), ("qwen3.5:27b", 91),
                ("gemma4:31b", 90), ("gemma4:26b", 89), ("qwen3-coder", 88), ("gpt-oss:20b", 88),
                ("qwen3:30b", 87), ("qwen3:32b", 87), ("qwen3:14b", 85), ("qwen3.5:9b", 84),
                ("gemma4:12b", 83), ("gemma4", 80), ("qwen3.5:4b", 72), ("qwen3.5:2b", 58),
                ("qwen3.5", 80), ("qwen3:8b", 78), ("qwen2.5-coder:14b", 76), ("granite4.1:8b", 74),
                ("granite4.1:3b", 60), ("granite4", 70), ("llama3.1:8b", 72), ("hermes3", 70),
                ("qwen3:4b", 68), ("qwen2.5", 65), ("llama3.2", 55)]
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
            out = runner(["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version",
                          "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=8).stdout.strip().splitlines()
            if out:
                parts = [p.strip() for p in out[0].split(",")]
                info.update(gpu=parts[0], vram_gb=round(float(parts[1]) / 1024, 1))
                if len(parts) > 2 and re.match(r"^[\d.]+$", parts[2]):
                    info["vram_free_gb"] = round(float(parts[2]) / 1024, 1)
                if len(parts) > 3:
                    info["driver"] = parts[3]
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


def pull(tags: list[str], progress: Progress = PROGRESS, opener=urllib.request.urlopen,
         final: bool = True, op: str = "pull") -> str:
    """Pull the first tag that exists; stream progress. Returns the pulled tag or "".
    `final=False` leaves the progress open for the steps that follow (one-click setup)."""
    for tag in tags:
        progress.update(op=op, target=tag, status="starting", completed=0, total=0,
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
                        progress.update(done=final, status="success" if final else "downloaded",
                                        message=("%s is ready" if final else "%s is downloaded") % tag)
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


# --------------------------------------------------------------------- the richer scan
DISK_MARGIN_GB = 2.0  # always leave this much free: a full disk once broke an install on the Mac
MLX_URL = os.environ.get("MLX_BASE_URL", "http://127.0.0.1:8082/v1").rstrip("/")
_UNSET = object()


def models_dir(env: dict | None = None) -> Path:
    """Where Ollama keeps its models: $OLLAMA_MODELS, else ~/.ollama/models (on Windows
    %USERPROFILE%\\.ollama\\models, which is the same path)."""
    env = env if env is not None else os.environ
    custom = str(env.get("OLLAMA_MODELS", "") or "").strip()
    return Path(custom).expanduser() if custom else Path.home() / ".ollama" / "models"


def disk_space(path: Path) -> dict:
    """{path, free_gb, total_gb} for the disk that holds `path` (or its nearest existing
    parent, e.g. your home folder before Ollama ever ran). free_gb is None when unknown."""
    probe = Path(path)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(str(probe))
        return {"path": str(path), "free_gb": round(usage.free / 2**30, 1), "total_gb": round(usage.total / 2**30, 1)}
    except OSError:
        return {"path": str(path), "free_gb": None, "total_gb": None}


def os_name() -> str:
    """'macOS 15.3', 'Windows 11 (build 26100)', 'Ubuntu 24.04 LTS'."""
    try:
        if sys.platform == "darwin":
            ver = platform.mac_ver()[0]
            return ("macOS " + ver) if ver else "macOS"
        if sys.platform == "win32":
            release, version = platform.release(), platform.version()
            last = version.split(".")[-1]
            build = int(last) if last.isdigit() else 0
            name = "11" if release == "10" and build >= 22000 else release
            return "Windows %s%s" % (name, " (build %d)" % build if build else "")
        try:
            return platform.freedesktop_os_release().get("PRETTY_NAME") or "Linux"
        except (OSError, AttributeError):
            return "Linux " + platform.release()
    except Exception:  # noqa: BLE001 - a name is a nicety
        return sys.platform


def mlx_status(opener=urllib.request.urlopen, which=shutil.which, find_spec=importlib.util.find_spec) -> dict:
    """MLX (Apple Silicon): is mlx_lm installed, and is mlx_lm.server answering on 8082?"""
    installed = False
    if sys.platform == "darwin":
        try:
            installed = find_spec("mlx_lm") is not None
        except (ImportError, ValueError):
            installed = False
        installed = installed or bool(which("mlx_lm.server"))
    try:
        data = _get_json(MLX_URL + "/models", timeout=1.0, opener=opener)
        models = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
        running = True
    except Exception:  # noqa: BLE001 - not running
        models, running = [], False
    return {"installed": installed or running, "running": running, "models": models, "base_url": MLX_URL}


def scan(info: dict | None = None, opener=urllib.request.urlopen, servers=_UNSET, models=_UNSET,
         env: dict | None = None, which=shutil.which) -> dict:
    """Everything worth knowing about this computer for local models, in a second or two:
    the hardware() fields plus OS version, CPU cores, free disk where models go, MLX and
    llama.cpp presence, and which local servers run which models."""
    info = dict(info or hardware())
    models = ollama_models(opener=opener) if models is _UNSET else models
    servers = other_servers(opener=opener) if servers is _UNSET else servers
    disk = disk_space(models_dir(env))
    mlx = mlx_status(opener=opener, which=which)
    running = []
    if models is not None:
        running.append({"label": "Ollama", "base_url": OLLAMA,
                        "models": [m["name"] for m in models if not m["name"].startswith(DERIVED_PREFIX)]})
    if mlx["running"]:
        running.append({"label": "MLX", "base_url": MLX_URL, "models": mlx["models"]})
    for server in servers or []:
        running.append({"label": server["label"], "base_url": server["base_url"], "models": server["models"]})
    accel = "nvidia" if info.get("vram_gb") else "apple" if info.get("unified") else "cpu"
    return {**info,
            "os_name": os_name(), "cpu_cores": os.cpu_count() or 0, "chip": str(info.get("chip") or "").strip(),
            "accel": accel, "vram_free_gb": info.get("vram_free_gb"), "driver": info.get("driver", ""),
            "disk": disk, "disk_free_gb": disk["free_gb"],
            "mlx": mlx, "mlx_installed": mlx["installed"],
            "llamacpp": {"installed": bool(which("llama-server") or which("llama-cli")),
                         "running": any(s.get("key") == "llamacpp" for s in servers or [])},
            "ollama_installed": ollama_installed(which) or models is not None,
            "running": running}


# --------------------------------------------------------------------- suggestions
SPEED_PENALTY = {"fast": 0, "good": 6, "slow": 14}
INSTALLED_BONUS = 6


def _gb(n: float) -> str:
    n = float(n)
    return ("%d" % round(n)) if n >= 10 or n.is_integer() else ("%.1f" % n)


def fit(entry: dict, machine: dict) -> dict | None:
    """How a catalog entry runs on this machine: {speed, reason}, or None when it does not
    fit in memory. GPU memory is fastest, Apple unified memory next, plain RAM slowest."""
    ram = float(machine.get("ram_gb") or 0)
    vram = float(machine.get("vram_gb") or 0)
    need = float(entry["need"])
    moe = bool(entry.get("moe"))
    if vram:
        room = max(vram - 1.0, 0.0)
        if need <= room:
            return {"speed": "fast", "reason": "Fits your %s GB GPU fully, so it runs fast" % _gb(vram)}
        if need <= room + ram * 0.4:
            return {"speed": "good" if moe else "slow",
                    "reason": "Bigger than your %s GB GPU, so part of it runs on the processor%s"
                              % (_gb(vram), " - it only uses a few billion parameters at a time, so it stays usable"
                                 if moe else " and replies are slower")}
        return None
    if machine.get("unified"):
        if need <= ram * 0.65:
            return {"speed": "fast", "reason": "Fits in your Mac's %s GB of unified memory with room to spare, so "
                                               "it runs smoothly" % _gb(ram)}
        return None
    if ram and need <= ram * 0.5:
        quick = need <= 4 or moe
        return {"speed": "good" if quick else "slow",
                "reason": "There is no graphics card for AI, so it runs on the processor%s"
                          % (" - small enough to stay responsive" if quick else ", which is slow")}
    return None


def _disk(size_gb: float, machine: dict) -> tuple[bool, float]:
    """(fits, GB to free) for a download of `size_gb`, keeping DISK_MARGIN_GB free."""
    free = machine.get("disk_free_gb")
    if free is None:
        return True, 0.0
    short = round(float(size_gb) + DISK_MARGIN_GB - float(free), 1)
    return short <= 0, max(short, 0.0)


def is_installed(tag: str, installed: list[str]) -> bool:
    derived = derived_name(tag)
    return any(n == tag or n.startswith(tag + "-") or n.split(":")[0] == derived or n.startswith(derived + "-")
               for n in installed)


def plan(machine: dict, installed: list[str] | None = None) -> dict:
    """Per-role picks for this machine: {rows, picks: {agent, fast, code, mlx}, blocked, auto}.
    Nothing that does not fit the free disk is ever picked; `blocked` says how much to free."""
    installed = installed or []
    rows = []
    for entry in CATALOG:
        how = fit(entry, machine)
        if not how:
            continue
        fits_disk, short = _disk(entry["size"], machine)
        rows.append({**entry, **how, "fit": entry["score"] - SPEED_PENALTY[how["speed"]],
                     "fits_disk": fits_disk, "free_up_gb": short, "installed": is_installed(entry["tag"], installed)})
    ok = [r for r in rows if r["fits_disk"] or r["installed"]]

    def pick(role: str, cands: list[dict], key, title: str) -> dict | None:
        if not cands:
            return None
        cands = sorted(cands, key=key, reverse=True)
        top = cands[0]
        return {"role": role, "title": title, "tag": top["tag"], "size_gb": top["size"], "need_gb": top["need"],
                "speed": top["speed"], "score": top["score"], "fit": top["fit"], "installed": top["installed"],
                "why": "%s. %s." % (top["reason"], top["why"][0].upper() + top["why"][1:]),
                "tags": [c["tag"] for c in cands[:3]]}

    def by_fit(r: dict) -> tuple:
        # an installed model within a few points beats a download: no nagging for a small gain
        return (r["fit"] + (INSTALLED_BONUS if r["installed"] else 0), r["installed"], -r["size"])

    agent = pick("agent", [r for r in ok if "agent" in r["roles"]] or ok, by_fit, "Best overall agent model")
    fast = pick("fast", [r for r in ok if "fast" in r["roles"]] or ok,
                lambda r: (-SPEED_PENALTY[r["speed"]], r["score"]), "Fastest")
    code = pick("code", [r for r in ok if "code" in r["roles"]], by_fit, "Coding")
    picks = {"agent": agent, "fast": fast, "code": code, "mlx": None}
    if machine.get("unified") and machine.get("mlx_installed"):
        ram = float(machine.get("ram_gb") or 0)
        for entry in MLX_CATALOG:
            if entry["need"] <= ram * 0.65 and _disk(entry["size"], machine)[0]:
                picks["mlx"] = {"role": "mlx", "title": "Apple MLX alternative", "repo": entry["repo"],
                                "size_gb": entry["size"],
                                "why": "MLX is installed on this Mac: %s." % entry["why"],
                                "command": ("python -m mlx_vlm.server --model %s --port 8082" if entry.get("server") == "mlx-vlm"
                                            else "mlx_lm.server --model %s --port 8082") % entry["repo"]}
                break
    blocked = None
    better = sorted([r for r in rows if not r["fits_disk"] and not r["installed"]
                     and (not agent or r["fit"] > agent["fit"])], key=by_fit, reverse=True)
    if better:
        top = better[0]
        blocked = {"tag": top["tag"], "size_gb": top["size"], "free_up_gb": top["free_up_gb"],
                   "message": "Free up %s GB of disk space first to get %s, the best model for this computer."
                              % (_gb(top["free_up_gb"]), top["tag"])}
    if agent:
        auto = {"tag": agent["tag"], "size_gb": agent["size_gb"], "installed": agent["installed"],
                "tags": agent["tags"], "error": ""}
    else:
        free = machine.get("disk_free_gb")
        if rows and free is not None:
            smallest = min(r["size"] for r in rows)
            error = ("There is not enough free disk space for a model (%s GB free). Free up %s GB first, then try "
                     "again." % (_gb(float(free)), _gb(max(round(smallest + DISK_MARGIN_GB - float(free), 1), 0.1))))
        else:
            error = "This computer does not have enough memory for a local model. Use a cloud provider instead."
        auto = {"tag": "", "size_gb": 0, "installed": False, "tags": [], "error": error}
    return {"rows": rows, "picks": picks, "blocked": blocked, "auto": auto}


def upgrade_for(best: dict | None, picks: dict) -> dict | None:
    """A clearly better model that fits (score gap >= 8) than the best installed one."""
    agent = (picks or {}).get("agent")
    if not best or not agent or agent["installed"]:
        return None
    name = str(best.get("name", ""))
    current = name[len(DERIVED_PREFIX):] if name.startswith(DERIVED_PREFIX) else name
    gain = int(agent["fit"] - int(best.get("score") or 0))
    if gain < 8:
        return None
    return {"tag": agent["tag"], "why": agent["why"], "size_gb": agent["size_gb"], "current": current, "gain": gain}


# --------------------------------------------------------------------- one click
def start_ollama(runner=subprocess.run) -> None:
    """Open the installed Ollama app (best effort, both platforms)."""
    try:
        if sys.platform == "darwin":
            runner(["open", "-a", "Ollama"], timeout=30)
        elif sys.platform == "win32":
            app = Path(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama app.exe")
            if app.exists():
                subprocess.Popen([str(app)])
            elif shutil.which("ollama"):
                subprocess.Popen([shutil.which("ollama") or "ollama", "serve"])
        elif shutil.which("ollama"):
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001 - the caller waits and reports
        pass


def _wait_for_ollama(opener, seconds: float) -> list[dict] | None:
    end = time.time() + seconds
    while True:
        models = ollama_models(opener=opener)
        if models is not None or time.time() >= end:
            return models
        time.sleep(2)


def run_auto(tags: list[str], machine: dict, use, progress: Progress = PROGRESS, opener=urllib.request.urlopen,
             install=None, start=None, wait_s: float = 60.0) -> str:
    """One click: get Ollama running (install it if missing), download the best fitting model
    (falling back through `tags`), give it a long context window, switch LOKI to it and keep
    it loaded. Plain-English progress throughout. Returns the model name LOKI now uses."""
    progress.update(op="auto", target=tags[0] if tags else "", status="starting", completed=0, total=0,
                    error="", done=False, started=time.time(), message="Checking this computer")

    def fail(message: str, error: str = "") -> str:
        progress.update(done=True, status="failed", error=error or message, message=message)
        return ""

    if not tags:
        return fail("No model fits this computer right now.")
    try:
        models = ollama_models(opener=opener)
        if models is None:
            if not ollama_installed():
                progress.update(message="Installing Ollama, the free app that runs models on this computer")
                if not (install or install_ollama)(progress=progress, opener=opener):
                    snap = progress.snapshot()
                    progress.update(op="auto")
                    return fail(snap.get("message") or "Could not install Ollama.", snap.get("error", ""))
                progress.update(op="auto", target=tags[0], done=False, error="")
            else:
                progress.update(status="starting Ollama", message="Starting Ollama")
                (start or start_ollama)()
            models = _wait_for_ollama(opener, wait_s)
            if models is None:
                return fail("Ollama is installed but not running yet. Open the Ollama app once, then click the "
                            "button again.")
        names = [m["name"] for m in models]
        tag = next((t for t in tags if is_installed(t, names)), "")
        if tag:
            progress.update(target=tag, status="installed", message="%s is already on this computer" % tag)
        else:
            tag = pull(tags, progress=progress, opener=opener, final=False, op="auto")
            if not tag:
                return ""  # pull() already said what went wrong
            models = ollama_models(opener=opener) or models
        names = [m["name"] for m in models]
        base = next((n for n in names if n == tag), next((n for n in names if n.startswith(tag + "-")), tag))
        if "bonsai" in tag.lower():
            progress.update(status="checking", message="Checking this computer's Ollama can run %s" % tag)
            ok, why = verify_runs(base, opener=opener)
            if not ok:
                return fail("Downloaded %s, but this Ollama cannot run it yet: %s Update Ollama (it needs "
                            "0.40.6 or newer for Bonsai 2's Q2_0 weights), then click again." % (tag, why), why)
        progress.update(op="auto", target=tag, status="preparing",
                        message="Giving %s a long memory for big tasks" % tag)
        name = ensure_context(base, context_for(machine), models, opener=opener)
        progress.update(status="switching", message="Switching LOKI to %s" % tag)
        use(name)
        progress.update(status="warming", message="Loading %s so the first reply is quick" % tag)
        keep_warm(name, opener=opener)
        progress.update(done=True, status="success", completed=0, total=0,
                        message="All set: LOKI now runs %s on this computer - offline, free and private." % tag)
        return name
    except Exception as exc:  # noqa: BLE001 - reported to the UI
        return fail("Setup stopped: %s" % str(exc)[:160], str(exc)[:200])


def verify_runs(model: str, opener=urllib.request.urlopen) -> tuple:
    """(True, "") when the model gives a sane short answer. New weight formats (Bonsai 2's
    ternary Q2_0) load on an older runtime but print gibberish; this catches that."""
    try:
        reply = _post_json(OLLAMA + "/api/generate", {"model": model, "stream": False, "think": False,
                                                       "prompt": "What colour is a clear daytime sky? Answer with one word.",
                                                       "options": {"num_predict": 12, "temperature": 0}},
                           timeout=180.0, opener=opener)
    except Exception as exc:  # noqa: BLE001
        return False, "it did not answer (%s)." % str(exc)[:120]
    text = str((reply or {}).get("response", "")).strip().lower()
    if "blue" in text:
        return True, ""
    letters = sum(ch.isalpha() or ch.isspace() for ch in text) / max(1, len(text))
    return False, ("it answered %r instead of a word." % text[:40]) if text and letters < 0.7 else \
        ("its answer did not make sense (%r)." % text[:40])


# --------------------------------------------------------------------- the whole picture
def status(env: dict | None = None, opener=urllib.request.urlopen, info: dict | None = None) -> dict:
    """Everything the first-run screen needs, in one call."""
    env = env if env is not None else os.environ
    info = info or hardware()
    models = ollama_models(opener=opener)
    best = best_installed(models, info["budget_gb"], caps=lambda n: capabilities(n, opener=opener)) if models else None
    servers = other_servers(opener=opener)
    machine = scan(info, opener=opener, servers=servers, models=models, env=env)
    names = [m["name"] for m in models or []]
    advice = plan(machine, names)
    cloud_keys = sorted(k for k, v in env.items() if k.endswith("_API_KEY") and str(v).strip())
    ready = bool(best and best.get("tools")) or bool(servers)
    recs = recommend(info, names)
    fitting = {r["tag"] for r in advice["rows"]}
    recs = [r for r in recs if r["tag"] in fitting] or recs
    for rec in recs:
        rec["fits_disk"], rec["free_up_gb"] = _disk(rec["size"], machine)
    return {
        "hardware": info,
        "scan": machine,
        "ollama": {"installed": ollama_installed() or models is not None, "running": models is not None,
                   "models": models or []},
        "best": best,
        "servers": servers,
        "recommend": recs,
        "picks": advice["picks"],
        "blocked": advice["blocked"],
        "auto": advice["auto"],
        "upgrade": upgrade_for(best, advice["picks"]) if best and best.get("tools") else None,
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
