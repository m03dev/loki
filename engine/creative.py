"""Creative pipelines: pictures and videos made on the owner's own hardware.

Session 28. The owner loved the fox picture LOKI made and asked for "more of that stuff". This
module adds what the image specialist (runners/imagegen.py) and Settings > Creations need to
make pictures and short videos LOCALLY, free and private, on the two machines LOKI runs on:

  the PC   (Windows, RTX 3070 Ti 8 GB)  stable-diffusion.cpp (leejet, MIT) - one C++ binary,
           CUDA 12 build (Vulkan for a non-NVIDIA GPU), running Z-Image Turbo as GGUF:
           z_image_turbo-Q4_K.gguf (3.9 GB) + Qwen3-4B-Instruct-2507-Q4_K_M.gguf (text encoder,
           2.5 GB) + the FLUX VAE ae.safetensors (335 MB), with --offload-to-cpu --diffusion-fa so
           it fits 8 GB (sd.cpp's own wiki runs it on a 4 GB card). Q3_K below 6 GB, Q6_K at 12+ GB.
           Video: Wan2GP (deepbeepmeep, "GPU poor") headless with `wgp.py --process <settings.json>`,
           profile 4 (parts loaded as needed) - LTX-Video distilled by default, image-to-video
           from a creation ("animate this").
  the Mac  (Apple Silicon, 16 GB)  mflux (filipstrand, MIT, MLX) running the pre-quantized
           filipstrand/Z-Image-Turbo-mflux-4bit (9 steps). Diffusers Z-Image filled the 16 GB M4's
           swap and crashed (session 22); 4-bit MLX weights are ~6 GB in all. No local video on
           the Mac (Wan2GP is CUDA-only): video falls back to Higgsfield when its key is set.

Everything that touches the outside (nvidia-smi, downloads, pip, git, the generators) is passed
in, so tests/test_creative.py runs all of it with fakes: no download, no GPU.

Install (Settings > Add-ons > local-image / local-video > Install, or
`python tools/setup_extras.py local-image|local-video`): downloads into harness_data/tools and
harness_data/models (never into the repo), runs in a background thread, progress in
harness_data/app/creative.json (shown in Settings > Creations).

Settings (environment / LOKI's .env):
    LOKI_IMAGE_BACKEND       auto | sdcpp | mflux | zimage | qwen | pollinations
    LOKI_SDCPP_MODEL         zimage-q3 | zimage-q4 | zimage-q6 (default: by VRAM)
    LOKI_SDCPP_TAG           a stable-diffusion.cpp release tag to install (default: latest)
    LOKI_MFLUX_MODEL         an mflux model id (default filipstrand/Z-Image-Turbo-mflux-4bit)
    LOKI_WAN2GP_MODEL        Wan2GP model_type (default ltxv_distilled), LOKI_WAN2GP_PROFILE (4)
    LOKI_WAN2GP_PYTHON       the Python Wan2GP's venv is made with (default: py -3.11 on Windows)
    LOKI_HIGGSFIELD_VIDEO_APP  Higgsfield application id for the video fallback
    LOKI_DAILY_CREATION      on | off | auto (default auto: on for a machine with an NVIDIA GPU,
                             off on the Mac) - the autopilot's one picture a day
"""
from __future__ import annotations

import json
import os
import platform as _platform
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
HF = "https://huggingface.co/%s/resolve/main/%s"
SDCPP_REPO = "leejet/stable-diffusion.cpp"
SDCPP_PINNED = "master-920-2f88688"          # known good (2026-09-25); assets checked 2026-10-17
WAN2GP_GIT = "https://github.com/deepbeepmeep/Wan2GP.git"
MFLUX_DEFAULT = "filipstrand/Z-Image-Turbo-mflux-4bit"

# ----------------------------------------------------------------------------- where things live

def data_dir(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("LOKI_DATA") or (ROOT / "harness_data"))


def tools_dir(env: dict | None = None) -> Path:
    return data_dir(env) / "tools"


def models_dir(env: dict | None = None) -> Path:
    return data_dir(env) / "models" / "imagegen"


def state_file(env: dict | None = None) -> Path:
    return data_dir(env) / "app" / "creative.json"


_STATE_LOCK = threading.Lock()


def load_state(env: dict | None = None) -> dict:
    try:
        data = json.loads(state_file(env).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(update: dict, env: dict | None = None) -> dict:
    """Merge `update` (one level deep) into creative.json."""
    with _STATE_LOCK:
        data = load_state(env)
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key] = {**data[key], **value}
            else:
                data[key] = value
        path = state_file(env)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass
        return data


# ----------------------------------------------------------------------------- this machine
_MACHINE: dict = {}


def total_ram_gb() -> float:
    try:   # the image runner's own (standard library, both platforms)
        import importlib.util  # pylint: disable=import-outside-toplevel
        spec = importlib.util.spec_from_file_location("loki_imagegen_runner",
                                                      Path(__file__).resolve().parent / "runners" / "imagegen.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return float(mod.total_ram_gb())
    except Exception:  # noqa: BLE001
        return 0.0


def machine(run: Callable = subprocess.run, which: Callable = shutil.which, platform: str | None = None,
            arch: str | None = None, ram_gb: float | None = None, fresh: bool = False) -> dict:
    """What this computer can run: {os, apple_silicon, nvidia, gpu, vram_gb, ram_gb}. Cached."""
    injected = platform is not None or arch is not None or ram_gb is not None or run is not subprocess.run
    if _MACHINE and not fresh and not injected:
        return dict(_MACHINE)
    plat = platform or sys.platform
    cpu = (arch or _platform.machine() or "").lower()
    info = {"os": plat, "apple_silicon": plat == "darwin" and cpu in ("arm64", "aarch64"), "nvidia": False,
            "gpu": "", "vram_gb": 0.0, "ram_gb": float(total_ram_gb() if ram_gb is None else ram_gb)}
    smi = which("nvidia-smi") if plat != "darwin" else None
    if smi:
        try:
            proc = run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=10)
            first = (proc.stdout or "").strip().splitlines()[0] if (proc.stdout or "").strip() else ""
            name, _, mem = first.rpartition(",")
            if name.strip():
                info.update(nvidia=True, gpu=name.strip(), vram_gb=round(float(mem.strip()) / 1024, 1))
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            pass
    if not injected:
        _MACHINE.clear()
        _MACHINE.update(info)
    return info


# ----------------------------------------------------------------------------- image models
# sd.cpp presets: Z-Image Turbo as GGUF (leejet/Z-Image-Turbo-GGUF), Qwen3-4B as its text encoder
# (unsloth GGUF), the FLUX VAE (Comfy-Org's ungated copy). Sizes from the HF listings, 2026-10-17.
_ZIMAGE_LLM = ("unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", 2.5)
_ZIMAGE_VAE = ("Comfy-Org/z_image_turbo", "split_files/vae/ae.safetensors", 0.34)
SDCPP_MODELS: dict = {
    "zimage-q3": {"label": "Z-Image Turbo Q3_K (4-6 GB GPUs)", "min_vram": 0,
                  "diffusion": ("leejet/Z-Image-Turbo-GGUF", "z_image_turbo-Q3_K.gguf", 3.14)},
    "zimage-q4": {"label": "Z-Image Turbo Q4_K (8 GB GPUs, the PC)", "min_vram": 6,
                  "diffusion": ("leejet/Z-Image-Turbo-GGUF", "z_image_turbo-Q4_K.gguf", 3.86)},
    "zimage-q6": {"label": "Z-Image Turbo Q6_K (12 GB+)", "min_vram": 12,
                  "diffusion": ("leejet/Z-Image-Turbo-GGUF", "z_image_turbo-Q6_K.gguf", 5.26)},
}
for _m in SDCPP_MODELS.values():
    _m.update(llm=_ZIMAGE_LLM, vae=_ZIMAGE_VAE, steps=8, cfg=1.0)


def pick_sdcpp_model(info: dict, env: dict | None = None) -> str:
    env = os.environ if env is None else env
    want = str(env.get("LOKI_SDCPP_MODEL", "")).strip()
    if want in SDCPP_MODELS:
        return want
    vram = float(info.get("vram_gb") or 0)
    if info.get("apple_silicon"):     # unified memory: by RAM
        vram = float(info.get("ram_gb") or 0) / 2
    best = "zimage-q3"
    for key, spec in SDCPP_MODELS.items():
        if vram >= spec["min_vram"] and spec["min_vram"] >= SDCPP_MODELS[best]["min_vram"]:
            best = key
    return best


def model_files(key: str, env: dict | None = None) -> list:
    """[(role, url, local path, approx GB)] for one sd.cpp preset."""
    spec = SDCPP_MODELS[key]
    out = []
    for role in ("diffusion", "llm", "vae"):
        repo, name, gb = spec[role]
        out.append((role, HF % (repo, name), models_dir(env) / Path(name).name, gb))
    return out


def mflux_model(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    return str(env.get("LOKI_MFLUX_MODEL", "") or MFLUX_DEFAULT).strip()


# ----------------------------------------------------------------------------- which local backend
def local_image_backend(info: dict) -> str:
    """'mflux' on Apple Silicon, 'sdcpp' everywhere else (CUDA, Vulkan or CPU build)."""
    return "mflux" if info.get("apple_silicon") else "sdcpp"


def sdcpp_asset_patterns(info: dict) -> list:
    """Regexes for the release assets this machine needs (the binary zip first)."""
    plat = info.get("os")
    if plat == "win32":
        if info.get("nvidia"):
            return [r"^sd-.*-bin-win-cuda12-x64\.zip$", r"^cudart-sd-bin-win-cu12-x64\.zip$"]
        return [r"^sd-.*-bin-win-vulkan-x64\.zip$"]
    if plat == "darwin":
        return [r"^sd-.*-bin-Darwin-macOS-.*-arm64\.zip$"]
    if info.get("nvidia"):
        return [r"^sd-.*-bin-Linux-.*-x86_64-vulkan\.zip$"]
    return [r"^sd-.*-bin-Linux-Ubuntu-[0-9.]+-x86_64\.zip$"]


def find_binary(folder: Path, names=("sd-cli", "sd")) -> Path | None:
    """sd.cpp's CLI is `sd-cli` in new releases and `sd` in old ones (.exe on Windows)."""
    folder = Path(folder)
    if not folder.is_dir():
        return None
    for name in names:
        for candidate in sorted(folder.rglob(name + ".exe")) + sorted(folder.rglob(name)):
            if candidate.is_file():
                return candidate
    return None


def local_image_status(env: dict | None = None, info: dict | None = None, which: Callable = shutil.which) -> dict:
    """{backend, ready, why, model, label} for the local image backend of this machine."""
    info = info if info is not None else machine()
    state = load_state(env)
    backend = local_image_backend(info)
    if backend == "mflux":
        record = state.get("mflux") or {}
        cmd = record.get("cmd") or which("mflux-generate-z-image-turbo") or ""
        if not cmd or not (Path(cmd).is_file() or which(cmd)):
            return {"backend": "mflux", "ready": False, "model": mflux_model(env),
                    "why": "mflux is not installed (Settings > Add-ons > local-image > Install)"}
        return {"backend": "mflux", "ready": True, "why": "", "cmd": cmd, "model": mflux_model(env),
                "label": "Z-Image Turbo 4-bit on MLX"}
    record = state.get("sdcpp") or {}
    binary = record.get("bin") or ""
    key = record.get("model") or pick_sdcpp_model(info, env)
    if key not in SDCPP_MODELS:
        key = pick_sdcpp_model(info, env)
    if not binary or not Path(binary).is_file():
        return {"backend": "sdcpp", "ready": False, "model": key,
                "why": "stable-diffusion.cpp is not installed (Settings > Add-ons > local-image > Install)"}
    missing = [p.name for _r, _u, p, _g in model_files(key, env) if not p.is_file()]
    if missing:
        return {"backend": "sdcpp", "ready": False, "model": key, "why": "model files missing: " + ", ".join(missing)}
    return {"backend": "sdcpp", "ready": True, "why": "", "bin": binary, "model": key,
            "label": SDCPP_MODELS[key]["label"]}


# ----------------------------------------------------------------------------- command lines
def sdcpp_argv(binary: str, key: str, prompt: str, negative: str, width: int, height: int, seed: int,
               out: Path, count: int = 1, info: dict | None = None, env: dict | None = None) -> list:
    spec = SDCPP_MODELS[key]
    files = {role: str(path) for role, _u, path, _g in model_files(key, env)}
    argv = [str(binary), "--diffusion-model", files["diffusion"], "--vae", files["vae"], "--llm", files["llm"],
            "-p", prompt, "--cfg-scale", str(spec["cfg"]), "--steps", str(spec["steps"]),
            "-W", str(int(width)), "-H", str(int(height)), "-s", str(int(seed)), "-o", str(out),
            "--diffusion-fa"]
    if negative:
        argv += ["-n", negative]
    if int(count) > 1:
        argv += ["-b", str(int(count))]
    vram = float((info or {}).get("vram_gb") or 0)
    if not (info or {}).get("apple_silicon") and vram < 12:
        argv.append("--offload-to-cpu")     # 8 GB: weights wait in RAM, each stage goes to the GPU in turn
    if width * height > 1024 * 1024:
        argv.append("--vae-tiling")
    return argv


def mflux_argv(cmd: str, model: str, prompt: str, width: int, height: int, seed: int, out: Path,
               steps: int = 9, low_ram: bool = False) -> list:
    argv = [str(cmd), "--model", model, "--prompt", prompt, "--width", str(int(width)), "--height", str(int(height)),
            "--seed", str(int(seed)), "--steps", str(int(steps)), "--output", str(out)]
    if low_ram:
        argv.append("--low-ram")
    return argv


def batch_files(out: Path, count: int) -> list:
    """Where sd.cpp writes a batch: out, then out_2.png, out_3.png ... (also accepts out_1)."""
    out = Path(out)
    found = [out] if out.is_file() else []
    for i in range(1, int(count) + 2):
        candidate = out.with_name("%s_%d%s" % (out.stem, i, out.suffix))
        if candidate.is_file() and candidate not in found:
            found.append(candidate)
    return found[:int(count)]


def run_local_image(prompt: str, negative: str, width: int, height: int, seed: int, count: int, out_dir: Path,
                    run: Callable = subprocess.run, env: dict | None = None, info: dict | None = None,
                    status: dict | None = None, out_path: Callable | None = None) -> dict:
    """Make `count` pictures with this machine's local backend. {"files", "seeds", "backend", "model"}."""
    info = info if info is not None else machine()
    status = status if status is not None else local_image_status(env, info)
    if not status.get("ready"):
        raise RuntimeError(status.get("why") or "no local image backend")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:48] or "image"
    path_of = out_path or (lambda i: out_dir / ("%s-%s%s.png" % (stamp, slug, "" if i == 0 else "-%d" % (i + 1))))
    started = time.time()
    files, seeds = [], []
    if status["backend"] == "sdcpp":
        out = path_of(0)
        argv = sdcpp_argv(status["bin"], status["model"], prompt, negative, width, height, seed, out, count, info, env)
        proc = run(argv, capture_output=True, text=True, timeout=1800)
        made = batch_files(out, count)
        if getattr(proc, "returncode", 1) != 0 or not made:
            tail = ((getattr(proc, "stderr", "") or "") + (getattr(proc, "stdout", "") or "")).strip()[-400:]
            raise RuntimeError("sd.cpp failed (exit %s): %s" % (getattr(proc, "returncode", "?"), tail))
        for i, p in enumerate(made):         # sd.cpp's out_2.png -> LOKI's names
            target = path_of(i)
            if p != target:
                os.replace(p, target)
            files.append(str(target))
            seeds.append(int(seed) + i)
    else:
        low_ram = float(info.get("ram_gb") or 0) <= 16
        for i in range(int(count)):          # MLX: one at a time (weights stay in the page cache)
            out = path_of(i)
            argv = mflux_argv(status["cmd"], status["model"], prompt, width, height, int(seed) + i, out,
                              low_ram=low_ram)
            proc = run(argv, capture_output=True, text=True, timeout=1800)
            if getattr(proc, "returncode", 1) != 0 or not Path(out).is_file():
                tail = ((getattr(proc, "stderr", "") or "") + (getattr(proc, "stdout", "") or "")).strip()[-400:]
                if files:
                    break
                raise RuntimeError("mflux failed (exit %s): %s" % (getattr(proc, "returncode", "?"), tail))
            files.append(str(out))
            seeds.append(int(seed) + i)
    return {"files": files, "file": files[0], "seeds": seeds, "seed": seeds[0], "backend": status["backend"],
            "model": status["model"], "seconds": round(time.time() - started, 1)}


# ----------------------------------------------------------------------------- installing
def _download(url: str, target: Path, progress: Callable[[int, int], None] | None = None,
              opener: Callable = urllib.request.urlopen) -> Path:
    """Stream an https URL to target (via .part). Skips a file that is already there."""
    target = Path(target)
    if target.is_file() and target.stat().st_size > 0:
        return target
    if not url.startswith("https://"):
        raise ValueError("refusing a non-https download: %s" % url)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Loki/1.0"})
    with opener(req, timeout=120) as resp, part.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0) if getattr(resp, "headers", None) else 0
        got = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    os.replace(part, target)
    return target


def safe_extract(archive: Path, dest: Path) -> list:
    """Unzip, refusing absolute paths and '..'; marks binaries executable on macOS/Linux."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    names = []
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            name = member.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/") or re.match(r"^[A-Za-z]:", name):
                raise ValueError("unsafe path in archive: %s" % member.filename)
            target = (dest / name).resolve()
            target.relative_to(root)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            if os.name != "nt" and ((member.external_attr >> 16) & 0o111 or Path(name).stem in ("sd", "sd-cli")):
                try:
                    target.chmod(target.stat().st_mode | 0o755)
                except OSError:
                    pass
            names.append(name)
    return names


def release_assets(tag: str = "", fetch: Callable | None = None) -> tuple:
    """(tag, {asset name: download url}) of a stable-diffusion.cpp release (latest by default)."""
    def default_fetch(url):
        req = urllib.request.Request(url, headers={"User-Agent": "Loki/1.0", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    fetch = fetch or default_fetch
    api = "https://api.github.com/repos/%s/releases/%s" % (SDCPP_REPO, ("tags/" + tag) if tag else "latest")
    data = fetch(api)
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])
              if isinstance(a, dict) and a.get("name") and str(a.get("browser_download_url", "")).startswith("https://")}
    return str(data.get("tag_name") or tag), assets


INSTALLERS = ("local-image", "local-video")


def install_plan(name: str, info: dict | None = None, env: dict | None = None) -> dict:
    """What installing an add-on does here, in words: {"steps": [...], "installed": bool, "supported": bool}."""
    info = info if info is not None else machine()
    if name == "local-image":
        status = local_image_status(env, info)
        if status["backend"] == "mflux":
            steps = ["pip install -U mflux (MLX, Apple Silicon) into LOKI's venv",
                     "the first picture downloads %s (about 6 GB) into the Hugging Face cache" % mflux_model(env)]
            return {"steps": steps, "installed": status["ready"], "supported": True, "backend": "mflux"}
        key = status["model"]
        steps = ["download stable-diffusion.cpp (%s) from github.com/%s/releases into harness_data/tools/sdcpp"
                 % (" + ".join(p.strip("^$").replace("\\", "") for p in sdcpp_asset_patterns(info)), SDCPP_REPO)]
        steps += ["download %s (%.1f GB) into harness_data/models/imagegen" % (path.name, gb)
                  for _r, _u, path, gb in model_files(key, env)]
        return {"steps": steps, "installed": status["ready"], "supported": True, "backend": "sdcpp", "model": key}
    if name == "local-video":
        status = video_status(env, info)
        if not info.get("nvidia"):
            return {"steps": [], "installed": False, "supported": False, "backend": "wan2gp",
                    "why": "Wan2GP needs an NVIDIA GPU (the PC); on this machine video uses Higgsfield"}
        steps = ["git clone %s into harness_data/tools/Wan2GP" % WAN2GP_GIT,
                 "make its own Python venv (Python 3.10/3.11: %s)" % wan2gp_python_hint(env),
                 "pip install torch (CUDA 12.8 wheels) + Wan2GP's requirements.txt (about 5 GB)",
                 "the first video downloads its model (LTX-Video distilled, several GB) into Wan2GP's ckpts/"]
        return {"steps": steps, "installed": status["ready"], "supported": True, "backend": "wan2gp"}
    return {"steps": [], "installed": False, "supported": False}


def wan2gp_python_hint(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    return str(env.get("LOKI_WAN2GP_PYTHON") or ("py -3.11" if sys.platform == "win32" else "python3.11"))


def _progress(name: str, env: dict | None, **fields: Any) -> None:
    save_state({"install": {name: {**(load_state(env).get("install", {}).get(name) or {}), **fields,
                                   "t": time.time()}}}, env)


def install_local_image(info: dict, env: dict | None = None, download: Callable = _download,
                        fetch: Callable | None = None, run: Callable = subprocess.run,
                        python: str = "", extract: Callable = safe_extract) -> dict:
    """Do the whole local-image install for this machine. Returns {"ok", ...}."""
    env = os.environ if env is None else env
    backend = local_image_backend(info)
    if backend == "mflux":
        _progress("local-image", env, step="pip install mflux", done=False)
        argv = [python or sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-U", "mflux"]
        proc = run(argv, capture_output=True, text=True, timeout=3600)
        if getattr(proc, "returncode", 1) != 0:
            tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-300:]
            raise RuntimeError("pip install mflux failed: " + tail)
        bindir = Path(python or sys.executable).parent
        cmd = next((str(bindir / n) for n in ("mflux-generate-z-image-turbo", "mflux-generate-z-image-turbo.exe")
                    if (bindir / n).is_file()), "") or shutil.which("mflux-generate-z-image-turbo") or \
            str(bindir / "mflux-generate-z-image-turbo")
        save_state({"mflux": {"cmd": cmd, "model": mflux_model(env), "at": time.time()}}, env)
        return {"ok": True, "backend": "mflux", "cmd": cmd}
    tag, assets = release_assets(str(env.get("LOKI_SDCPP_TAG", "")).strip(), fetch)
    wanted = []
    for pattern in sdcpp_asset_patterns(info):
        match = sorted(n for n in assets if re.match(pattern, n))
        if not match:
            raise RuntimeError("release %s has no asset like %s" % (tag, pattern))
        wanted.append(match[-1])
    folder = tools_dir(env) / "sdcpp" / re.sub(r"[^A-Za-z0-9._-]+", "-", tag or "latest")
    binary = None
    for asset in wanted:
        _progress("local-image", env, step="download " + asset, done=False)
        archive = download(assets[asset], tools_dir(env) / "downloads" / asset,
                           lambda got, total, a=asset: _progress("local-image", env, step="download " + a,
                                                                 got=got, total=total))
        # the binary zip first; the CUDA runtime DLLs go next to the binary so Windows finds them
        extract(archive, binary.parent if binary is not None else folder)
        binary = binary or find_binary(folder)
        if binary is None:
            raise RuntimeError("no sd-cli/sd binary inside %s" % asset)
    key = pick_sdcpp_model(info, env)
    for role, url, path, _gb in model_files(key, env):
        _progress("local-image", env, step="download " + path.name, done=False)
        download(url, path, lambda got, total, n=path.name: _progress("local-image", env, step="download " + n,
                                                                       got=got, total=total))
    save_state({"sdcpp": {"bin": str(binary), "model": key, "tag": tag, "at": time.time()}}, env)
    return {"ok": True, "backend": "sdcpp", "bin": str(binary), "model": key, "tag": tag}


def install_local_video(info: dict, env: dict | None = None, run: Callable = subprocess.run,
                        which: Callable = shutil.which) -> dict:
    env = os.environ if env is None else env
    if not info.get("nvidia"):
        raise RuntimeError("Wan2GP needs an NVIDIA GPU; this machine makes videos with Higgsfield instead")
    git = which("git")
    if not git:
        raise RuntimeError("git is missing (install Git for Windows, then try again)")
    folder = tools_dir(env) / "Wan2GP"

    def step(text, argv, cwd=None, timeout=3600):
        _progress("local-video", env, step=text, done=False)
        proc = run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        if getattr(proc, "returncode", 1) != 0:
            tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-300:]
            raise RuntimeError("%s failed: %s" % (text, tail))

    if not (folder / "wgp.py").is_file():
        folder.parent.mkdir(parents=True, exist_ok=True)
        step("git clone Wan2GP", [git, "clone", "--depth", "1", WAN2GP_GIT, str(folder)])
    base = str(env.get("LOKI_WAN2GP_PYTHON", "")).strip()
    if base:
        maker = [base]
    elif sys.platform == "win32" and which("py"):
        maker = [which("py"), "-3.11"]
    else:
        maker = [which("python3.11") or which("python3.10") or sys.executable]
    venv = folder / ".venv"
    py = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not py.is_file():
        step("make Wan2GP's venv", [*maker, "-m", "venv", str(venv)])
    index = str(env.get("LOKI_WAN2GP_TORCH_INDEX", "") or "https://download.pytorch.org/whl/cu128")
    step("pip install torch", [str(py), "-m", "pip", "install", "--disable-pip-version-check", "torch",
                               "torchvision", "torchaudio", "--index-url", index])
    step("pip install Wan2GP requirements", [str(py), "-m", "pip", "install", "--disable-pip-version-check",
                                             "-r", str(folder / "requirements.txt")], cwd=str(folder))
    save_state({"wan2gp": {"dir": str(folder), "python": str(py), "at": time.time()}}, env)
    return {"ok": True, "backend": "wan2gp", "dir": str(folder)}


_INSTALLING: dict = {}


def start_install(name: str, env: dict | None = None, info: dict | None = None, worker: Callable | None = None,
                  thread: bool = True) -> dict:
    """Start installing local-image / local-video in the background. Returns at once."""
    info = info if info is not None else machine()
    plan = install_plan(name, info, env)
    if not plan.get("supported"):
        return {"ok": False, "error": plan.get("why") or "%s is not available on this machine" % name, "specs": [],
                "log": []}
    if _INSTALLING.get(name) and _INSTALLING[name].is_alive():
        return {"ok": True, "started": False, "specs": [], "log": ["already installing"],
                "message": "%s is already being installed" % name}
    job = worker or (install_local_image if name == "local-image" else install_local_video)

    def work():
        _progress(name, env, step="starting", done=False, ok=None, error="")
        try:
            result = job(info, env)
            _progress(name, env, step="done", done=True, ok=True, result=result)
        except Exception as exc:  # noqa: BLE001 - shown in Settings > Creations
            _progress(name, env, step="failed", done=True, ok=False, error="%s: %s" % (type(exc).__name__, str(exc)[:300]))

    if not thread:
        work()
        state = (load_state(env).get("install") or {}).get(name) or {}
        return {"ok": bool(state.get("ok")), "started": True, "specs": [], "log": plan["steps"],
                "error": state.get("error", "")}
    t = threading.Thread(target=work, daemon=True, name="loki-install-" + name)
    _INSTALLING[name] = t
    t.start()
    return {"ok": True, "started": True, "specs": [], "log": plan["steps"],
            "message": "Installing %s in the background - Settings > Creations shows the progress" % name}


# ----------------------------------------------------------------------------- video
VIDEO_DEFAULT_MODEL = "ltxv_distilled"


def video_status(env: dict | None = None, info: dict | None = None) -> dict:
    """{backend, ready, why} for making a video here: Wan2GP, then Higgsfield."""
    env = os.environ if env is None else env
    info = info if info is not None else machine()
    record = load_state(env).get("wan2gp") or {}
    folder = Path(record.get("dir") or (tools_dir(env) / "Wan2GP"))
    py = Path(record.get("python") or "")
    if info.get("nvidia") and (folder / "wgp.py").is_file() and py.is_file():
        return {"backend": "wan2gp", "ready": True, "why": "", "dir": str(folder), "python": str(py),
                "model": str(env.get("LOKI_WAN2GP_MODEL", "") or VIDEO_DEFAULT_MODEL)}
    try:
        import higgsfield  # pylint: disable=import-outside-toplevel
        if higgsfield.configured(env):
            return {"backend": "higgsfield", "ready": True, "why": "",
                    "app": str(env.get("LOKI_HIGGSFIELD_VIDEO_APP", "") or "higgsfield-ai/dop/standard")}
    except Exception:  # noqa: BLE001
        pass
    why = ("install local video: Settings > Add-ons > local-video > Install (Wan2GP)" if info.get("nvidia") else
           "no local video on this machine (Wan2GP needs an NVIDIA GPU); paste a Higgsfield key in Settings > General")
    return {"backend": "", "ready": False, "why": why}


def wan2gp_settings(prompt: str, seed: int, seconds: float, image: str = "", env: dict | None = None,
                    template: dict | None = None) -> dict:
    """The settings JSON Wan2GP's `--process` takes. A template exported from Wan2GP's own UI
    ("Export Settings", saved as harness_data/app/wan2gp_template.json) wins: LOKI only fills in
    the prompt, the seed, the length and the start image."""
    env = os.environ if env is None else env
    if template is None:
        try:
            template = json.loads((data_dir(env) / "app" / "wan2gp_template.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            template = {}
    model = str(template.get("model_type") or env.get("LOKI_WAN2GP_MODEL", "") or VIDEO_DEFAULT_MODEL)
    ltx = "ltx" in model
    fps = 24 if ltx else 16
    step = 8 if ltx else 4
    frames = max(step + 1, int(round(float(seconds) * fps / step)) * step + 1)
    settings = {"model_type": model, "resolution": "832x480", "num_inference_steps": 8 if ltx else 20,
                "negative_prompt": "blurry, distorted, low quality, watermark", **template}
    settings.update({"prompt": prompt, "seed": int(seed), "video_length": frames, "model_type": model})
    if image:   # image-to-video: the picture is the first frame ("S" = start image)
        settings.update({"image_start": image, "image_prompt_type": "S"})
    else:
        settings.pop("image_start", None)
        settings.pop("image_prompt_type", None)
    return settings


def wan2gp_argv(python: str, folder: str, settings_file: Path, out_dir: Path, env: dict | None = None) -> list:
    env = os.environ if env is None else env
    return [python, str(Path(folder) / "wgp.py"), "--process", str(settings_file), "--output-dir", str(out_dir),
            "--profile", str(env.get("LOKI_WAN2GP_PROFILE", "") or "4"), "--attention", "sdpa"]


def make_video(prompt: str, workspace: Path, image: str = "", seconds: float = 3.0, seed: int = 0,
               env: dict | None = None, info: dict | None = None, run: Callable = subprocess.run,
               higgs: Callable | None = None) -> dict:
    """A short video into videos/: Wan2GP on the PC (image-to-video when `image` is given),
    else Higgsfield. {"ok", "file" (workspace-relative), "backend", "seed", "seconds"}."""
    env = os.environ if env is None else env
    workspace = Path(workspace)
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "say what the video should show"}
    seconds = max(1.0, min(float(seconds or 3), 10.0))
    seed = int(seed) or random.randint(1, 2**31 - 1)
    status = video_status(env, info)
    if not status["ready"]:
        return {"ok": False, "error": status["why"]}
    videos = workspace / "videos"
    videos.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:48] or "video"
    target = videos / ("%s-%s.mp4" % (time.strftime("%Y%m%d-%H%M%S"), slug))
    started = time.time()
    if status["backend"] == "wan2gp":
        work = videos / ".wan2gp"
        work.mkdir(parents=True, exist_ok=True)
        image_path = str((workspace / image).resolve()) if image else ""
        settings_file = work / ("job-%d.json" % int(started * 1000))
        settings_file.write_text(json.dumps(wan2gp_settings(prompt, seed, seconds, image_path, env), indent=1),
                                 encoding="utf-8")
        before = {p.name for p in work.glob("*.mp4")}
        proc = run(wan2gp_argv(status["python"], status["dir"], settings_file, work, env), cwd=status["dir"],
                   capture_output=True, text=True, timeout=int(env.get("LOKI_VIDEO_TIMEOUT", "3600") or 3600))
        made = sorted((p for p in work.glob("*.mp4") if p.name not in before), key=lambda p: p.stat().st_mtime)
        if getattr(proc, "returncode", 1) != 0 or not made:
            tail = ((getattr(proc, "stderr", "") or "") + (getattr(proc, "stdout", "") or "")).strip()[-400:]
            return {"ok": False, "error": "Wan2GP did not make a video (exit %s): %s" % (getattr(proc, "returncode", "?"), tail)}
        os.replace(made[-1], target)
        try:
            settings_file.unlink()
        except OSError:
            pass
        return {"ok": True, "file": target.relative_to(workspace).as_posix(), "backend": "wan2gp",
                "model": status["model"], "seed": seed, "seconds": round(time.time() - started, 1)}
    import higgsfield  # pylint: disable=import-outside-toplevel
    call = higgs or higgsfield.generate
    extra = {"duration": int(round(seconds))}
    result = call(prompt, kind="video", application=status["app"], workspace=workspace, aspect_ratio="16:9",
                  extra=extra, env=env)
    if not result.get("ok"):
        return {"ok": False, "error": "Higgsfield: %s" % result.get("error")}
    files = [f for f in result.get("files") or [] if f.endswith((".mp4", ".webm", ".mov"))]
    if not files:
        return {"ok": False, "error": "Higgsfield finished but sent no video file"}
    note = "Higgsfield got the prompt only (not the picture)" if image else ""
    return {"ok": True, "file": files[0], "backend": "higgsfield", "seed": seed, "note": note,
            "seconds": round(time.time() - started, 1)}


# ----------------------------------------------------------------------------- the daily creation
DAILY_SUBJECTS = ["a red fox", "a fox cub", "a sleepy fox", "a fox and a rabbit", "a fox explorer"]
DAILY_SCENES = ["curled up in fresh snow at dawn", "in a mossy forest with fireflies", "on a floating island at dusk",
                "reading a tiny book by lantern light", "running through tall golden grass",
                "watching the northern lights", "in a cosy workshop full of little robots",
                "on a lighthouse balcony in the rain", "among autumn leaves", "under a cherry tree in spring"]
DAILY_STYLES = ["photograph", "pixel art", "digital art", "fantasy art", "anime", "cinematic", "craft clay"]


def daily_enabled(env: dict | None = None, info: dict | None = None) -> bool:
    """LOKI_DAILY_CREATION on/off; auto (default): on for a machine with an NVIDIA GPU, off on the Mac."""
    env = os.environ if env is None else env
    value = str(env.get("LOKI_DAILY_CREATION", "auto") or "auto").strip().lower()
    if value in ("1", "on", "true", "yes"):
        return True
    if value in ("0", "off", "false", "no"):
        return False
    info = info if info is not None else machine()
    return bool(info.get("nvidia")) and info.get("os") != "darwin"


def daily_idea(liked: list, day: str, styles_known: list | None = None) -> dict:
    """{prompt, style} for `day` ('2026-10-17'): a liked subject/style most days, else a fox.
    `liked` = creations' metadata the owner starred ({idea|prompt, style})."""
    rng = random.Random("loki-daily-" + day)
    styles = [s for s in (styles_known or DAILY_STYLES)]
    liked_styles = [m.get("style") for m in liked if m.get("style")]
    liked_ideas = [str(m.get("idea") or m.get("prompt") or "").strip() for m in liked]
    liked_ideas = [i for i in liked_ideas if i]
    if liked_ideas and rng.random() < 0.6:
        base = rng.choice(liked_ideas)
        prompt = "%s, %s" % (base.split(",")[0][:120], rng.choice(DAILY_SCENES))
    else:
        prompt = "%s %s" % (rng.choice(DAILY_SUBJECTS), rng.choice(DAILY_SCENES))
    style = rng.choice(liked_styles) if liked_styles and rng.random() < 0.7 else rng.choice(styles or [""])
    return {"prompt": prompt, "style": style or ""}


def daily_creation(make: Callable[..., dict], liked: list, env: dict | None = None, info: dict | None = None,
                   clock: Callable[[], float] = time.time) -> str:
    """The autopilot's duty: one picture a day. `make(prompt, style=..., enhance=True, daily=True)`."""
    if not daily_enabled(env, info):
        return ""
    day = time.strftime("%Y-%m-%d", time.localtime(clock()))
    record = load_state(env).get("daily") or {}
    if record.get("day") == day:
        return ""
    idea = daily_idea(liked, day)
    started = make(idea["prompt"], style=idea["style"], enhance=True, daily=True)
    if not started.get("ok"):
        return "daily creation could not start: %s" % started.get("error")
    save_state({"daily": {"day": day, "prompt": idea["prompt"], "style": idea["style"], "id": started.get("id")}}, env)
    return "started today's picture: %s (%s)" % (idea["prompt"], idea["style"] or "no style")


# ----------------------------------------------------------------------------- summary for the UI
def summary(env: dict | None = None, info: dict | None = None) -> dict:
    """For Settings > Creations: what makes pictures/videos here and any install in progress."""
    info = info if info is not None else machine()
    img = local_image_status(env, info)
    vid = video_status(env, info)
    installs = load_state(env).get("install") or {}
    return {"machine": {k: info.get(k) for k in ("os", "apple_silicon", "nvidia", "gpu", "vram_gb", "ram_gb")},
            "image": {k: img.get(k) for k in ("backend", "ready", "why", "model", "label")},
            "video": {k: vid.get(k) for k in ("backend", "ready", "why", "model")},
            "install": {k: {f: v.get(f) for f in ("step", "done", "ok", "error", "got", "total")}
                        for k, v in installs.items() if isinstance(v, dict)},
            "daily": daily_enabled(env, info)}
