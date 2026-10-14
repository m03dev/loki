"""Install LOKI's optional extras on this machine, one command each (macOS and Windows).

    python tools/setup_extras.py list            what is installed and what is not
    python tools/setup_extras.py media           yt-dlp (+ checks ffmpeg and a JS runtime)
    python tools/setup_extras.py imagegen        torch + diffusers + Z-Image Turbo weights (~20 GB)
    python tools/setup_extras.py mlx             mlx-lm (Mac with Apple Silicon only)
    python tools/setup_extras.py agent-reach     Agent Reach CLI (from GitHub, not PyPI)
    python tools/setup_extras.py opencode        OpenCode CLI (npm)
    python tools/setup_extras.py all             everything that fits this machine

Use LOKI's own Python (harness_data/.venv) so the engine finds what you install:
    macOS:   harness_data/.venv/bin/python tools/setup_extras.py all
    Windows: harness_data\\.venv\\Scripts\\python.exe tools\\setup_extras.py all
Nothing here runs a shell string; every step is shown before it runs.
"""
from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys

ZIMAGE = "Tongyi-MAI/Z-Image-Turbo"
AGENT_REACH = "https://github.com/Panniantong/agent-reach/archive/main.zip"
MLX_MODEL = "mlx-community/Qwen3-4B-4bit"


def run(argv: list) -> bool:
    print("  $ " + " ".join(argv), flush=True)
    try:
        return subprocess.run(argv).returncode == 0
    except OSError as exc:
        print("    could not run: %s" % exc)
        return False


def pip(*packages: str, index: str = "") -> bool:
    argv = [sys.executable, "-m", "pip", "install", "-U", *packages]
    if index:
        argv += ["--index-url", index]
    return run(argv)


def has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def nvidia() -> bool:
    return bool(shutil.which("nvidia-smi"))


def media() -> bool:
    ok = pip("yt-dlp[default]")
    if not shutil.which("ffmpeg"):
        print("  ffmpeg is missing (needed to merge video+audio and convert audio):")
        print("    macOS: brew install ffmpeg      Windows: winget install Gyan.FFmpeg")
    if not (shutil.which("deno") or shutil.which("node")):
        print("  YouTube needs Deno or Node:  macOS: brew install deno   Windows: winget install DenoLand.Deno")
    return ok


def imagegen() -> bool:
    if nvidia():
        # CUDA build of torch (the default PyPI wheel on Windows is CPU-only).
        ok = pip("torch", "torchvision", index="https://download.pytorch.org/whl/cu128")
    else:
        ok = pip("torch", "torchvision")
    ok = ok and pip("diffusers>=0.36", "transformers", "accelerate", "safetensors", "huggingface_hub")
    if ok:
        print("  downloading %s (about 20 GB, once)" % ZIMAGE)
        ok = run([sys.executable, "-c", "from huggingface_hub import snapshot_download; "
                  "print(snapshot_download(%r))" % ZIMAGE])
    if ok:
        print("  done. Test: echo '{\"prompt\":\"a red fox, studio light\"}' | %s engine/runners/imagegen.py" % sys.executable)
    return ok


def mlx() -> bool:
    if not apple_silicon():
        print("  MLX needs a Mac with Apple Silicon; skipped.")
        return True
    ok = pip("mlx-lm")
    if ok:
        print("  start it (keep it running):  mlx_lm.server --model %s --port 8082" % MLX_MODEL)
        print("  LOKI then shows MLX as connected in Settings > Connections.")
    return ok


def agent_reach() -> bool:
    if shutil.which("pipx"):
        ok = run(["pipx", "install", "--force", AGENT_REACH])
    else:
        ok = pip(AGENT_REACH)
    exe = shutil.which("agent-reach")
    if ok and exe:
        run([exe, "install", "--env=auto"])     # checks only; never changes the system
        run([exe, "doctor"])
    return ok


def opencode() -> bool:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        print("  npm is missing: install Node 20+ first (https://nodejs.org)")
        return False
    return run([npm, "i", "-g", "opencode-ai@latest"])


def listing() -> None:
    rows = [("media (yt-dlp)", has("yt_dlp")), ("ffmpeg", bool(shutil.which("ffmpeg"))),
            ("imagegen (diffusers)", has("diffusers") and has("torch")),
            ("mlx-lm", bool(shutil.which("mlx_lm.server")) or has("mlx_lm")),
            ("agent-reach", bool(shutil.which("agent-reach"))), ("opencode", bool(shutil.which("opencode")))]
    for name, ok in rows:
        print("  %-22s %s" % (name, "installed" if ok else "not installed"))


STEPS = {"media": media, "imagegen": imagegen, "mlx": mlx, "agent-reach": agent_reach, "opencode": opencode}


def main(argv: list) -> int:
    what = argv[0] if argv else "list"
    if what == "list":
        listing()
        return 0
    names = list(STEPS) if what == "all" else [what]
    if what == "all" and not (nvidia() or apple_silicon()):
        names.remove("imagegen")
    failed = []
    for name in names:
        if name not in STEPS:
            print(__doc__)
            return 2
        print("== %s" % name)
        if not STEPS[name]():
            failed.append(name)
    print("failed: " + ", ".join(failed) if failed else "all done")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
