"""Install LOKI's optional extras on this machine, one command each (macOS and Windows).

    python tools/setup_extras.py list            what is installed and what is not
    python tools/setup_extras.py media           yt-dlp (+ checks ffmpeg and a JS runtime)
    python tools/setup_extras.py imagegen        torch + diffusers + Z-Image Turbo weights (~20 GB)
    python tools/setup_extras.py vision          object tracking: Roboflow trackers + supervision + RF-DETR
    python tools/setup_extras.py mlx             mlx-lm (Mac with Apple Silicon only)
    python tools/setup_extras.py agent-reach     Agent Reach CLI (from GitHub, not PyPI)
    python tools/setup_extras.py opencode        OpenCode CLI (npm)
    python tools/setup_extras.py all             everything above that fits this machine

Opt-in add-ons (never part of `all`; each one only when you ask for it by name):
    python tools/setup_extras.py scrapling       Scrapling + its browsers (scrape / crawl sites)
    python tools/setup_extras.py openhands       OpenHands CLI (uv tool install, Python 3.12)
    python tools/setup_extras.py penecho         PenEcho drawing canvas (npm; AGPL-3.0, separate program)
    python tools/setup_extras.py openhuman       how to get OpenHuman (GPL-3.0; no installer here)
    python tools/setup_extras.py cadcraft        CADCraft CAD drafting (MIT/Apache-2.0 release build, checksum-checked)
    python tools/setup_extras.py remotion        checks Node/npx for Remotion videos (custom licence)
    python tools/setup_extras.py wechaty         Wechaty + the WeChat puppet (npm, Apache-2.0) into harness_data/addons/wechaty
    python tools/setup_extras.py nanocoder       Nanocoder coding agent CLI (npm, MIT)
    python tools/setup_extras.py 9router         9Router model router (npm, MIT) into harness_data/addons/9router
    python tools/setup_extras.py local-image     stable-diffusion.cpp + Z-Image Turbo GGUF (PC), mflux (Mac)
    python tools/setup_extras.py local-video     Wan2GP in its own venv (PC with an NVIDIA GPU)

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
from pathlib import Path

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


def torch_for_this_machine() -> bool:
    if nvidia():
        # CUDA build of torch (the default PyPI wheel on Windows is CPU-only).
        return pip("torch", "torchvision", index="https://download.pytorch.org/whl/cu128")
    return pip("torch", "torchvision")      # macOS wheels include MPS; elsewhere CPU


def imagegen() -> bool:
    ok = torch_for_this_machine()
    ok = ok and pip("diffusers>=0.36", "transformers", "accelerate", "safetensors", "huggingface_hub")
    if ok:
        print("  downloading %s (about 20 GB, once)" % ZIMAGE)
        ok = run([sys.executable, "-c", "from huggingface_hub import snapshot_download; "
                  "print(snapshot_download(%r))" % ZIMAGE])
    if ok:
        print("  done. Test: echo '{\"prompt\":\"a red fox, studio light\"}' | %s engine/runners/imagegen.py" % sys.executable)
    return ok


def vision() -> bool:
    """vision-track: Roboflow trackers (Apache-2.0) + supervision (MIT) + RF-DETR (rfdetr,
    Apache-2.0) as the detector. torch first, so an NVIDIA PC gets the CUDA build and a Mac
    uses MPS. Ultralytics YOLO also works with `trackers` but is AGPL-3.0, so it is not the
    default. The detector downloads its weights (~100 MB) on first use."""
    if sys.version_info < (3, 10):
        print("  trackers needs Python 3.10 or newer; this is %d.%d" % sys.version_info[:2])
        return False
    ok = torch_for_this_machine()
    ok = ok and pip("trackers", "supervision", "rfdetr", "opencv-python-headless")
    if ok:
        print("  done. Turn on vision-track in Settings > Capabilities, then ask LOKI:")
        print("    \"track the cars in clips/street.mp4\"")
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


def scrapling() -> bool:
    """Scrapling (D4Vinci/Scrapling, BSD-3-Clause): the "rag" extra adds markdown output; then
    `scrapling install` downloads the browsers DynamicFetcher uses (a few hundred MB)."""
    ok = pip("scrapling[rag]")
    exe = shutil.which("scrapling")
    if not exe:
        folder = Path(sys.executable).parent
        exe = next((str(folder / n) for n in ("scrapling", "scrapling.exe") if (folder / n).is_file()), "")
    if ok and exe:
        ok = run([exe, "install"])
    elif ok:
        print("  run `scrapling install` once to download its browsers (needed for dynamic pages)")
    if ok:
        print("  done. Turn on scrapling in Settings > Add-ons, then ask LOKI to scrape or crawl a site.")
    return ok


def openhands() -> bool:
    """OpenHands CLI (MIT). It wants Python 3.12, so it gets its own tool environment through uv
    (or pipx), never LOKI's venv. The standalone CLI is no longer actively maintained."""
    uv = shutil.which("uv")
    if uv:
        ok = run([uv, "tool", "install", "openhands", "--python", "3.12"])
    elif shutil.which("pipx"):
        ok = run([shutil.which("pipx"), "install", "--python", "3.12", "openhands"])
    else:
        print("  uv is missing. Install it first, then run this again:")
        print("    macOS: brew install uv        Windows: winget install astral-sh.uv")
        return False
    if ok:
        print("  done. LOKI points it at your local Ollama model (LLM_MODEL=openai/<model>,")
        print("  LLM_BASE_URL=http://localhost:11434/v1). Turn on openhands in Settings > Add-ons.")
    return ok


def penecho() -> bool:
    """PenEcho (AGPL-3.0) runs as its own program; LOKI only talks to it over MCP / localhost."""
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        print("  npm is missing: install Node 20+ first (https://nodejs.org)")
        return False
    ok = run([npm, "i", "-g", "penecho"])
    if ok:
        print("  done. Start it with `penecho` (http://localhost:3888), then turn on penecho in Settings > Add-ons.")
    return ok


def openhuman() -> bool:
    print("  OpenHuman (GPL-3.0) has no installer here. Get it from")
    print("    https://github.com/tinyhumansai/openhuman/releases")
    print("  so that `openhuman-core` is on PATH, then turn on openhuman in Settings > Add-ons.")
    found = bool(shutil.which("openhuman-core"))
    print("  openhuman-core is %s" % ("on PATH" if found else "not on PATH yet"))
    return True


def cadcraft() -> bool:
    """CADCraft (MIT OR Apache-2.0): the official build for this machine into <data>/addons/cadcraft."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
    import cad  # pylint: disable=import-outside-toplevel
    if cad.cli_path():
        print("  CADCraft is already here: %s" % cad.cli_path())
        return True
    result = cad.install(say=lambda line: print("  " + line))
    if result.get("ok"):
        print("  done. Turn on cadcraft in Settings > Add-ons; LOKI's agents can then draw in CAD.")
    else:
        print("  " + result.get("error", "failed"))
    return bool(result.get("ok"))


# Pinned versions (checked 2026-10-17): wechaty 1.20.2 and its default WeChat puppet.
WECHATY_PACKAGES = ["wechaty@1.20.2", "wechaty-puppet-wechat4u@1.14.14", "file-box@1.4.15"]
NANOCODER_PACKAGE = "@nanocollective/nanocoder@1.31.0"


def _npm() -> str:
    return shutil.which("npm") or shutil.which("npm.cmd") or ""


def wechaty_argv(npm: str, prefix: Path) -> list:
    """npm into LOKI's data folder (never global, never the repo); --ignore-scripts: no package's install
    script runs (wechaty and the wechat4u puppet are plain JavaScript and need none)."""
    return [npm, "install", "--prefix", str(prefix), "--ignore-scripts", "--no-fund", "--no-audit", *WECHATY_PACKAGES]


def wechaty() -> bool:
    """Wechaty (Apache-2.0), a separate npm package LOKI's sidecar engine/wechaty_sidecar.mjs loads."""
    npm = _npm()
    if not npm:
        print("  npm is missing: install Node 18+ first (https://nodejs.org)")
        return False
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
    import channel_wechaty  # pylint: disable=import-outside-toplevel
    prefix = channel_wechaty.package_dir()
    prefix.mkdir(parents=True, exist_ok=True)
    ok = run(wechaty_argv(npm, prefix))
    if ok:
        print("  done. Turn on wechaty in Settings > Add-ons, then Settings > General shows the WeChat login.")
    return ok


def nanocoder_argv(npm: str) -> list:
    return [npm, "i", "-g", NANOCODER_PACKAGE]


def nanocoder() -> bool:
    """Nanocoder (MIT): a coding agent CLI LOKI runs for background jobs (`nanocoder run`)."""
    npm = _npm()
    if not npm:
        print("  npm is missing: install Node 20+ first (https://nodejs.org)")
        return False
    ok = run(nanocoder_argv(npm))
    if ok:
        print("  done. Run `nanocoder` once to pick a provider (or set LOKI_NANOCODER_PROVIDER / _MODEL),")
        print("  then turn on nanocoder in Settings > Add-ons.")
    return ok


def ninerouter_argv(npm: str, prefix: Path) -> list:
    """npm into LOKI's data folder (never global, never the repo), at LOKI's pinned version (engine/ninerouter.py)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
    import ninerouter  # pylint: disable=import-outside-toplevel
    return [npm, "install", "--prefix", str(prefix), "--no-fund", "--no-audit", ninerouter.PACKAGE]


def ninerouter_install() -> bool:
    """9Router (MIT): one local OpenAI endpoint for subscriptions, free tiers and keys. LOKI starts it on 127.0.0.1."""
    npm = _npm()
    if not npm:
        print("  npm is missing: install Node 20+ first (https://nodejs.org)")
        return False
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
    import ninerouter  # pylint: disable=import-outside-toplevel
    ninerouter.prefix().mkdir(parents=True, exist_ok=True)
    ok = run(ninerouter_argv(npm, ninerouter.prefix()))
    if ok:
        print("  done. Restart LOKI (it starts 9Router on 127.0.0.1:%d), open %s, connect your accounts," % (
            ninerouter.port(), ninerouter.dashboard_url()))
        print("  make a combo named 'loki', copy the API key and paste it in Settings > Connections > 9Router.")
    return ok


def remotion() -> bool:
    print("  Remotion licence: free for individuals and companies with up to 3 employees;")
    print("  larger companies need a company licence (https://www.remotion.dev/license).")
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        print("  npx is missing: install Node 18+ (https://nodejs.org). Nothing else is installed globally;")
        print("  each video project gets Remotion through npx.")
        return False
    print("  npx found (%s). Turn on remotion in Settings > Add-ons; LOKI's video_project and" % npx)
    print("  render_video tools then scaffold and render videos in the workspace (they ask first).")
    return True


def listing() -> None:
    rows = [("media (yt-dlp)", has("yt_dlp")), ("ffmpeg", bool(shutil.which("ffmpeg"))),
            ("imagegen (diffusers)", has("diffusers") and has("torch")),
            ("vision (trackers)", has("trackers") and has("supervision") and has("rfdetr")),
            ("mlx-lm", bool(shutil.which("mlx_lm.server")) or has("mlx_lm")),
            ("agent-reach", bool(shutil.which("agent-reach"))), ("opencode", bool(shutil.which("opencode"))),
            ("scrapling", has("scrapling")), ("openhands", bool(shutil.which("openhands"))),
            ("penecho", bool(shutil.which("penecho"))), ("openhuman", bool(shutil.which("openhuman-core"))),
            ("remotion (npx)", bool(shutil.which("npx") or shutil.which("npx.cmd")))]
    for name, ok in rows:
        print("  %-22s %s" % (name, "installed" if ok else "not installed"))


def _creative_install(name: str) -> bool:
    """local-image / local-video through engine/creative.py (the same code as Settings > Add-ons)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
    import creative  # pylint: disable=import-outside-toplevel
    plan = creative.install_plan(name)
    if not plan.get("supported"):
        print("  " + str(plan.get("why") or "not available on this machine"))
        return False
    for line in plan["steps"]:
        print("  - " + line)
    out = creative.start_install(name, thread=False)
    print("  " + ("installed" if out.get("ok") else "failed: %s" % out.get("error")))
    return bool(out.get("ok"))


def local_image() -> bool:
    return _creative_install("local-image")


def local_video() -> bool:
    return _creative_install("local-video")


STEPS = {"media": media, "imagegen": imagegen, "vision": vision, "mlx": mlx, "agent-reach": agent_reach, "opencode": opencode}
# Installed only when named: licences that need a decision (AGPL/GPL/custom), separate programs,
# or big downloads. `all` never includes them.
OPT_IN = {"scrapling": scrapling, "openhands": openhands, "penecho": penecho, "openhuman": openhuman, "cadcraft": cadcraft,
          "remotion": remotion, "local-image": local_image, "local-video": local_video,
          "wechaty": wechaty, "nanocoder": nanocoder, "9router": ninerouter_install}


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
        step = STEPS.get(name) or OPT_IN.get(name)
        if step is None:
            print(__doc__)
            return 2
        print("== %s" % name)
        if not step():
            failed.append(name)
    print("failed: " + ", ".join(failed) if failed else "all done")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
