"""Make one image. stdin/stdout JSON, like every runner.

    {"prompt": "...", "width": 1024, "height": 1024, "out_dir": "<workspace>/images",
     "backend": "auto" | "sdcpp" | "mflux" | "zimage" | "qwen" | "nvidia" | "huggingface" | "pollinations", "seed": 0,
     "count": 1-4, "negative": "..."}
    -> {"ok", "file", "files", "seed", "seeds", "backend", ...}   (seed 0 = a random one, reported)

Backends, in "auto" order:
  sdcpp / mflux this machine's own local backend once installed (engine/creative.py, session 28):
                stable-diffusion.cpp with Z-Image Turbo GGUF on the PC (8 GB), mflux with
                Z-Image Turbo 4-bit on the Mac (MLX). A batch of 4 is one run.
  zimage        Z-Image Turbo (Tongyi-MAI/Z-Image-Turbo, Apache-2.0, 6B, 8-9 steps) through
                diffusers on CUDA or Apple MPS. On a GPU with less than 12 GB (the RTX 3070 Ti
                has 8 GB) the model is offloaded to system RAM piece by piece: slower, but it
                fits. Needs `python tools/setup_imagegen.py` once (torch + diffusers + the
                weights, about 20 GB).
  qwen          Qwen-Image 2.1 through ModelScope's free API-Inference (about 250 images a day
                once the ModelScope account is bound to a verified Alibaba Cloud account). Used
                when MODELSCOPE_API_KEY is set. Asynchronous: submit, then poll the task.
  nvidia        FLUX.2 [klein] / FLUX.1 [dev] / [schnell] on NVIDIA's hosted API (build.nvidia.com), with the
                NVIDIA_API_KEY the chat already uses.
  huggingface   FLUX.1 [dev] / [schnell] through Hugging Face Inference (HF_TOKEN, free monthly credits).
  pollinations  image.pollinations.ai: free, no account, the weakest - only when nothing else is there.
"""
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ZIMAGE_ID = os.environ.get("LOKI_ZIMAGE_MODEL", "Tongyi-MAI/Z-Image-Turbo")
QWEN_IMAGE_ID = os.environ.get("LOKI_QWEN_IMAGE_MODEL", "Qwen/Qwen-Image-2.1")
MODELSCOPE_BASE = os.environ.get("LOKI_MODELSCOPE_IMAGE_BASE", "https://api-inference.modelscope.ai/").rstrip("/") + "/"


def _out_path(out_dir, prompt, ext="png"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:48] or "image"
    return out / ("%s-%s.%s" % (time.strftime("%Y%m%d-%H%M%S"), slug, ext))


def total_ram_gb():
    """Physical memory in GB (0 when unknown). Standard library only, both platforms."""
    try:
        if sys.platform == "darwin":
            import subprocess
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout
            return round(int(out.strip()) / 2**30, 1)
        if sys.platform == "win32":
            import ctypes

            class _Mem(ctypes.Structure):  # MEMORYSTATUSEX
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            mem = _Mem()
            mem.dwLength = ctypes.sizeof(_Mem)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):  # type: ignore[attr-defined]
                return round(mem.ullTotalPhys / 2**30, 1)
            return 0.0
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
        match = re.search(r"MemTotal:\s+(\d+)", text)
        return round(int(match.group(1)) / 2**20, 1) if match else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def memory_gate(ram_gb=None, nvidia=None):
    """(ok, why not): can this machine hold Z-Image Turbo? With an NVIDIA GPU the model is
    offloaded piece by piece and 16 GB of RAM is enough (verified on the PC). Without one
    (Apple MPS or CPU) the whole pipeline sits in memory: a 16 GB M4 filled its swap to 100%
    and crashed every plan, so ask for LOKI_ZIMAGE_MIN_RAM_GB (default 24)."""
    import shutil
    ram = total_ram_gb() if ram_gb is None else float(ram_gb)
    has_nvidia = bool(shutil.which("nvidia-smi")) if nvidia is None else bool(nvidia)
    if has_nvidia or not ram:
        return True, ""
    need = float(os.environ.get("LOKI_ZIMAGE_MIN_RAM_GB", "24") or 24)
    if ram < need:
        return False, ("this computer has %.0f GB of memory and no NVIDIA GPU; local Z-Image needs about "
                       "%.0f GB here, so images go to the next backend (set LOKI_IMAGE_BACKEND=zimage "
                       "to force it)" % (ram, need))
    return True, ""


def zimage_status():
    """(ready, why not) for local Z-Image on this machine."""
    try:
        import importlib.util
        if not (importlib.util.find_spec("torch") and importlib.util.find_spec("diffusers")):
            return False, "torch/diffusers are not installed (tools/setup_extras.py adds them)"
        fits, why = memory_gate()
        if not fits:
            print("[imagegen] local Z-Image skipped: " + why, file=sys.stderr, flush=True)
            return False, why
        try:
            record = json.loads(_plan_file().read_text(encoding="utf-8"))
            if record.get("works") is None and time.time() - float(record.get("failed_at") or 0) < 7 * 86400:
                # every plan crashed here recently (LOKI_IMAGE_BACKEND=zimage forces it)
                last = "; ".join(record.get("failures") or [])[:300]
                return False, "it crashed on this machine recently%s; skipped for a week" % ((": " + last) if last else "")
        except (OSError, ValueError):
            pass
        import diffusers
        if not hasattr(diffusers, "ZImagePipeline"):
            return False, "this diffusers has no ZImagePipeline (update diffusers)"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, str(exc)[:160])


def zimage_ready():
    return zimage_status()[0]


def _creative():
    """engine/creative.py (session 28: stable-diffusion.cpp on the PC, mflux on the Mac). The
    runner starts with `python -I`, so the engine folder is added to the path by hand."""
    engine_dir = str(Path(__file__).resolve().parents[1])
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    import creative  # pylint: disable=import-outside-toplevel
    return creative


def local_status():
    """(name, ready, why) of this machine's own local backend: sdcpp (PC) or mflux (Mac)."""
    try:
        status = _creative().local_image_status()
        return status["backend"], bool(status["ready"]), status.get("why", "")
    except Exception as exc:  # noqa: BLE001
        return "sdcpp", False, "%s: %s" % (type(exc).__name__, str(exc)[:160])


def plan_order(backend=None):
    """Which backends an image request tries here, in order, and why any are skipped.
    No image is made and nothing is sent anywhere (LOKI's System check uses this)."""
    backend = str(backend or os.environ.get("LOKI_IMAGE_BACKEND", "auto")).lower()
    if backend != "auto":
        return {"order": [backend], "skipped": {}, "forced": True}
    local, local_ready, local_why = local_status()
    skipped = {} if local_ready else {local: local_why}
    ready, why = zimage_status()     # diffusers Z-Image stays the next try (the PC has it from session 22)
    if not ready:
        skipped["zimage"] = why
    if not os.environ.get("MODELSCOPE_API_KEY"):
        skipped["qwen"] = "MODELSCOPE_API_KEY is not set"
    if not os.environ.get("NVIDIA_API_KEY"):
        skipped["nvidia"] = "NVIDIA_API_KEY is not set"
    hf = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY")
    if not hf:
        skipped["huggingface"] = "HF_TOKEN is not set"
    # this machine's own model first (free, private), then the strongest hosted ones, Pollinations only last
    order = ([local] if local_ready else []) + (["zimage"] if ready else []) + \
        (["qwen"] if os.environ.get("MODELSCOPE_API_KEY") else []) + \
        (["nvidia"] if os.environ.get("NVIDIA_API_KEY") else []) + (["huggingface"] if hf else []) + ["pollinations"]
    return {"order": order, "skipped": skipped, "forced": False}


# Ways to run Z-Image on a small GPU, safest last. A native crash (segfault / access
# violation) kills the whole process, so each attempt runs in its own child process and the
# next one is tried when it dies. The first one that works is remembered per machine.
ZIMAGE_PLANS = [
    {"name": "offload-bf16", "offload": "model", "dtype": "bfloat16", "sdpa": "default"},
    {"name": "offload-bf16-math-attn", "offload": "model", "dtype": "bfloat16", "sdpa": "math"},
    # Loading memory-mapped safetensors is a known access-violation source on Windows when
    # RAM + page file are tight; read the weights into memory instead.
    {"name": "offload-bf16-math-attn-nommap", "offload": "model", "dtype": "bfloat16", "sdpa": "math",
     "mmap": False},
    {"name": "sequential-bf16-math-attn", "offload": "sequential", "dtype": "bfloat16", "sdpa": "math"},
    {"name": "sequential-fp16-math-attn", "offload": "sequential", "dtype": "float16", "sdpa": "math"},
]


def _plan_file():
    base = Path(os.environ.get("LOKI_DATA") or (Path(__file__).resolve().parents[2] / "harness_data"))
    return base / "app" / "imagegen_plan.json"


def _stage(name):
    """Breadcrumb on stderr: when a native crash kills the child, the parent reports the last stage."""
    try:
        sys.stderr.write("stage: %s\n" % name)
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass


def _last_stage(stderr):
    stages = [l.strip()[7:] for l in (stderr or "").splitlines() if l.strip().startswith("stage: ")]
    return stages[-1] if stages else ""


def _crash_frame(stderr):
    """The innermost frame faulthandler printed ('File "...attention.py", line 88 in forward')."""
    frames = [l.strip() for l in (stderr or "").splitlines() if l.strip().startswith('File "')]
    if not frames:
        return ""
    frame = frames[0]          # faulthandler lists the most recent call first
    match = re.match(r'File "(.+)", line (\d+) in (\S+)', frame)
    return ("%s:%s in %s" % (re.split(r"[\\/]", match.group(1))[-1], match.group(2), match.group(3))) if match else frame[:120]


def _zimage_once(prompt, width, height, out_dir, seed, plan):
    """One generation with one plan, in THIS process (called in a child by zimage())."""
    _stage("import torch")
    import torch
    _stage("import diffusers")
    from diffusers import ZImagePipeline
    dtype = getattr(torch, plan.get("dtype", "bfloat16"))
    if torch.cuda.is_available():
        device = "cuda"
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 2 ** 30
        if plan.get("sdpa") == "math":
            # The fused attention kernels are the usual source of native crashes on Windows.
            torch.backends.cuda.enable_flash_sdp(False)
            torch.backends.cuda.enable_mem_efficient_sdp(False)
            torch.backends.cuda.enable_math_sdp(True)
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        device, vram_gb = "mps", 0.0
    else:
        device, dtype, vram_gb = "cpu", torch.float32, 0.0
    _stage("load weights (%s, mmap %s)" % (plan.get("dtype"), "off" if plan.get("mmap") is False else "on"))
    load = {"torch_dtype": dtype}
    if plan.get("mmap") is False:
        load["disable_mmap"] = True
    try:
        pipe = ZImagePipeline.from_pretrained(ZIMAGE_ID, **load)
    except TypeError:                      # an older diffusers without disable_mmap
        load.pop("disable_mmap", None)
        pipe = ZImagePipeline.from_pretrained(ZIMAGE_ID, **load)
    _stage("place on %s (%s offload)" % (device, plan.get("offload")))
    if device == "cuda" and vram_gb < 12:
        if plan.get("offload") == "sequential":
            pipe.enable_sequential_cpu_offload()   # lowest VRAM: one layer on the GPU at a time
        else:
            pipe.enable_model_cpu_offload()        # 8 GB cards: whole models move as needed
    else:
        pipe.to(device)
    generator = torch.Generator("cpu").manual_seed(int(seed)) if seed else None
    _stage("denoise")
    image = pipe(prompt=prompt, width=width, height=height, num_inference_steps=9,
                 guidance_scale=0.0, generator=generator).images[0]
    _stage("save")
    path = _out_path(out_dir, prompt)
    image.save(path)
    return {"file": str(path), "backend": "zimage", "device": device, "plan": plan["name"]}


def zimage(prompt, width, height, out_dir, seed, run=None):
    """Try each plan in its own child process; remember the first that works on this machine."""
    import subprocess
    run = run or subprocess.run
    plans = list(ZIMAGE_PLANS)
    try:
        known = json.loads(_plan_file().read_text(encoding="utf-8")).get("works")
        plans.sort(key=lambda p: p["name"] != known)
    except (OSError, ValueError, AttributeError):
        pass
    failures = []
    for plan in plans:
        job = {"prompt": prompt, "width": width, "height": height, "out_dir": out_dir, "seed": seed, "plan": plan}
        try:
            proc = run([sys.executable, "-I", os.path.abspath(__file__), "--zimage-child"], input=json.dumps(job),
                       capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            failures.append("%s: timed out" % plan["name"])
            continue
        lines = [l for l in (proc.stdout or "").splitlines() if l.strip().startswith("{")]
        result = json.loads(lines[-1]) if lines else {}
        if result.get("ok"):
            try:
                _plan_file().parent.mkdir(parents=True, exist_ok=True)
                _plan_file().write_text(json.dumps({"works": plan["name"], "at": time.time()}), encoding="utf-8")
            except OSError:
                pass
            result.pop("ok", None)
            if failures:
                result["note"] = "earlier plans failed: " + "; ".join(failures)
            return result
        why = result.get("error") or ("crashed (exit %s)" % proc.returncode)
        stage = _last_stage(getattr(proc, "stderr", ""))
        if stage and not result.get("error"):
            why += " during " + stage
        frame = _crash_frame(getattr(proc, "stderr", ""))
        if frame and not result.get("error"):
            why += " at " + frame
        failures.append("%s: %s" % (plan["name"], str(why)[:160]))
    try:   # every plan failed: skip local Z-Image for a week (auto goes straight to the next backend)
        _plan_file().parent.mkdir(parents=True, exist_ok=True)
        _plan_file().write_text(json.dumps({"works": None, "failed_at": time.time(), "failures": failures}),
                                encoding="utf-8")
    except OSError:
        pass
    raise RuntimeError("Z-Image did not run here: " + " | ".join(failures))


def _json_request(url, key, body=None, headers=None, timeout=60):  # noqa: D401
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                          "User-Agent": "Loki/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def qwen(prompt, width, height, out_dir, seed, sleep=time.sleep, request=None):
    """Qwen-Image via ModelScope API-Inference: POST the task, poll it, download the image."""
    key = os.environ.get("MODELSCOPE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("MODELSCOPE_API_KEY is not set")
    call = request or _json_request
    body = {"model": QWEN_IMAGE_ID, "prompt": prompt[:2000], "size": "%dx%d" % (width, height)}
    if seed:
        body["seed"] = int(seed)
    task = call(MODELSCOPE_BASE + "v1/images/generations", key, body, {"X-ModelScope-Async-Mode": "true"})
    task_id = task.get("task_id")
    if not task_id:
        raise RuntimeError("ModelScope did not start a task: %s" % json.dumps(task)[:200])
    deadline = time.time() + 300
    while time.time() < deadline:
        sleep(4)
        state = call(MODELSCOPE_BASE + "v1/tasks/" + task_id, key, None, {"X-ModelScope-Task-Type": "image_generation"})
        status = str(state.get("task_status", "")).upper()
        if status == "SUCCEED":
            urls = state.get("output_images") or []
            if not urls:
                raise RuntimeError("the task finished without an image")
            with urllib.request.urlopen(urllib.request.Request(urls[0], headers={"User-Agent": "Loki/1.0"}), timeout=120) as resp:
                data = resp.read()
            path = _out_path(out_dir, prompt)
            path.write_bytes(data)
            return {"file": str(path), "backend": "qwen", "model": QWEN_IMAGE_ID}
        if status in ("FAILED", "CANCELED", "CANCELLED"):
            raise RuntimeError("ModelScope task %s: %s" % (status.lower(), json.dumps(state)[:200]))
    raise RuntimeError("ModelScope took longer than 5 minutes")


# NVIDIA's hosted FLUX (build.nvidia.com; the same NVIDIA_API_KEY LOKI's chat already uses, free credits): newest first,
# the next one when a model is not offered on the key (404/422). Owner 2026-10-25: "this poli img gen is bad... it
# should be professional" - Pollinations is now only the last resort.
NVIDIA_IMAGE_BASE = os.environ.get("LOKI_NVIDIA_IMAGE_BASE", "https://ai.api.nvidia.com/v1/genai").rstrip("/")
NVIDIA_IMAGE_MODELS = [m.strip() for m in os.environ.get(
    "LOKI_NVIDIA_IMAGE_MODELS",
    "black-forest-labs/flux.2-klein-4b,black-forest-labs/flux.1-dev,black-forest-labs/flux.1-schnell").split(",") if m.strip()]
# FLUX.1 on NVIDIA takes only these sizes; the nearest aspect is used (FLUX.2 takes the size asked)
FLUX1_SIZES = [(1024, 1024), (768, 1344), (1344, 768), (832, 1216), (1216, 832), (896, 1152), (1152, 896)]


def nearest_size(width, height, sizes=FLUX1_SIZES):
    want = width / float(height)
    return min(sizes, key=lambda s: abs((s[0] / float(s[1])) - want))


def _b64_image(data):
    """The picture in an NVIDIA genai answer: artifacts[0].base64 (or b64_json / image)."""
    import base64
    arts = data.get("artifacts") or []
    if arts:
        reason = str(arts[0].get("finishReason") or arts[0].get("finish_reason") or "").upper()
        if "FILTER" in reason:
            raise RuntimeError("NVIDIA's content filter refused this picture")
        raw = arts[0].get("base64") or ""
    else:
        raw = data.get("b64_json") or data.get("image") or ""
        if not raw and data.get("data"):
            raw = (data["data"][0] or {}).get("b64_json") or ""
    if not raw:
        raise RuntimeError("no picture in the answer: %s" % json.dumps(data)[:160])
    return base64.b64decode(raw.split(",", 1)[-1])


def nvidia(prompt, width, height, out_dir, seed, request=None):
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("NVIDIA_API_KEY is not set")
    call = request or _json_request
    errors = []
    for model in NVIDIA_IMAGE_MODELS:
        flux1 = "flux.1" in model
        w, h = nearest_size(width, height) if flux1 else (width, height)
        body = {"prompt": prompt[:2000], "width": w, "height": h, "seed": int(seed) % 2**32,
                "steps": 4 if "schnell" in model or "klein" in model else 30}
        if "dev" in model:
            body.update(cfg_scale=3.5, mode="base")
        try:
            data = call("%s/%s" % (NVIDIA_IMAGE_BASE, model), key, body, {"Accept": "application/json"}, 180)
        except urllib.error.HTTPError as exc:
            errors.append("%s: HTTP %s" % (model, exc.code))
            if exc.code in (401, 403, 429):
                break            # the key or the quota, not the model: the next model would fail the same way
            continue
        path = _out_path(out_dir, prompt)
        path.write_bytes(_b64_image(data))
        return {"file": str(path), "backend": "nvidia", "model": model, "width": w, "height": h}
    raise RuntimeError("NVIDIA image models: " + "; ".join(errors))


HF_IMAGE_MODELS = [m.strip() for m in os.environ.get(
    "LOKI_HF_IMAGE_MODELS", "black-forest-labs/FLUX.1-dev,black-forest-labs/FLUX.1-schnell").split(",") if m.strip()]


def huggingface(prompt, width, height, out_dir, seed, opener=None):
    """Hugging Face Inference (HF_TOKEN; its free monthly credits): the picture comes back as image bytes."""
    key = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("HF_TOKEN is not set")
    opener = opener or urllib.request.urlopen
    errors = []
    for model in HF_IMAGE_MODELS:
        body = {"inputs": prompt[:2000], "parameters": {"width": width, "height": height, "seed": int(seed) % 2**32,
                                                        "num_inference_steps": 4 if "schnell" in model.lower() else 28}}
        req = urllib.request.Request("https://router.huggingface.co/hf-inference/models/" + model,
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                              "Accept": "image/png", "User-Agent": "Loki/1.0"})
        try:
            with opener(req, timeout=180) as resp:
                data, kind = resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            errors.append("%s: HTTP %s" % (model, exc.code))
            if exc.code in (401, 402, 403, 429):
                break
            continue
        if not kind.startswith("image/"):
            errors.append("%s: no picture" % model)
            continue
        path = _out_path(out_dir, prompt, "jpg" if "jpeg" in kind else "png")
        path.write_bytes(data)
        return {"file": str(path), "backend": "huggingface", "model": model}
    raise RuntimeError("Hugging Face image models: " + "; ".join(errors))


POLLINATIONS_IMAGE = "https://image.pollinations.ai/prompt/"


def pollinations_request(prompt, width, height, seed, key=None):
    """The Pollinations request, built in one place so every call asks for no logo.
    nologo=true removes Pollinations' mark, but their docs say that needs an account: with
    POLLINATIONS_API_KEY set (a free token from auth.pollinations.ai) it goes as a Bearer token and
    the picture has no mark; anonymous pictures may still carry it - LOKI never paints over it.
    private=true keeps the prompt off Pollinations' public feed."""
    params = {"width": width, "height": height, "nologo": "true", "private": "true", "referrer": "loki"}
    if seed:
        params["seed"] = int(seed)
    url = POLLINATIONS_IMAGE + "%s?%s" % (urllib.parse.quote(prompt[:1500]), urllib.parse.urlencode(params))
    key = os.environ.get("POLLINATIONS_API_KEY", "").strip() if key is None else key
    headers = {"User-Agent": "Loki/1.0"}
    if key and key != "pollinations":     # "pollinations" is the text endpoint's placeholder, not a token
        headers["Authorization"] = "Bearer " + key
    return urllib.request.Request(url, headers=headers), bool(headers.get("Authorization"))


def pollinations(prompt, width, height, out_dir, seed):
    req, signed_in = pollinations_request(prompt, width, height, seed)
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
        kind = resp.headers.get("Content-Type", "image/jpeg")
    if not data or not kind.startswith("image/"):
        raise RuntimeError("Pollinations returned no image")
    path = _out_path(out_dir, prompt, "png" if "png" in kind else "jpg")
    path.write_bytes(data)
    note = "made by a free third-party service" + ("" if signed_in else
                                                    "; may carry Pollinations' mark - set POLLINATIONS_API_KEY to remove it")
    return {"file": str(path), "backend": "pollinations", "note": note, "watermark_free": signed_in}


def local(prompt, width, height, out_dir, seed, count=1, negative=""):
    """sd.cpp (PC) or mflux (Mac) through engine/creative.py; a whole batch in one go."""
    return _creative().run_local_image(prompt, negative, width, height, seed, count, Path(out_dir))


def one_by_one(fn, prompt, width, height, out_dir, seed, count):
    """A batch from a backend that makes one picture per call: seeds seed, seed+1, ..."""
    files, seeds, first = [], [], {}
    for i in range(count):
        try:
            result = fn(prompt, width, height, out_dir, seed + i)
        except Exception:  # noqa: BLE001 - keep what was made; fail only when nothing was
            if files:
                break
            raise
        first = first or result
        files.append(result["file"])
        seeds.append(seed + i)
    return {**first, "file": files[0], "files": files, "seeds": seeds, "seed": seeds[0]}


def main():
    job = json.loads(sys.stdin.read() or "{}")
    prompt = str(job.get("prompt") or "").strip()
    width = max(256, min(int(job.get("width") or 1024), 2048)) // 16 * 16
    height = max(256, min(int(job.get("height") or 1024), 2048)) // 16 * 16
    out_dir = str(job.get("out_dir") or "images")
    # Always a real seed, so a creation can be remade or varied later ("make more like this").
    seed = int(job.get("seed") or 0) or random.randint(1, 2**31 - 1)
    count = max(1, min(int(job.get("count") or 1), 4))
    negative = str(job.get("negative") or "").strip()
    backend = str(job.get("backend") or os.environ.get("LOKI_IMAGE_BACKEND", "auto")).lower()
    try:
        if not prompt:
            raise ValueError("describe the image")
        order = plan_order(backend)["order"]
        errors = []
        for name in order:
            try:
                if name in ("sdcpp", "mflux", "local"):
                    result = local(prompt, width, height, out_dir, seed, count, negative)
                    print(json.dumps({"ok": True, **result}))
                    return
                fn = {"zimage": zimage, "qwen": qwen, "nvidia": nvidia, "huggingface": huggingface,
                      "pollinations": pollinations}.get(name)
                if fn is None:
                    raise ValueError("unknown backend %r (sdcpp, mflux, zimage, qwen, nvidia, huggingface, "
                                     "pollinations)" % name)
                result = one_by_one(fn, prompt, width, height, out_dir, seed, count)
                print(json.dumps({"ok": True, **result}))
                return
            except Exception as exc:  # noqa: BLE001 - try the next backend
                errors.append("%s: %s: %s" % (name, type(exc).__name__, str(exc)[:200]))
        raise RuntimeError("; ".join(errors) or "no image backend")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)[:600]}))


def _child() -> None:
    job = json.loads(sys.stdin.read() or "{}")
    try:
        result = _zimage_once(job["prompt"], int(job["width"]), int(job["height"]), job["out_dir"],
                              int(job.get("seed") or 0), job["plan"])
        print(json.dumps({"ok": True, **result}), flush=True)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(exc).__name__, str(exc)[:300])}), flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--zimage-child"]:
        import faulthandler
        faulthandler.enable()     # a native crash still prints the Python stack to stderr
        _child()
    elif sys.argv[1:2] == ["--plan"]:
        print(json.dumps({"ok": True, **plan_order()}))
    else:
        main()
