"""Make one image. stdin/stdout JSON, like every runner.

    {"prompt": "...", "width": 1024, "height": 1024, "out_dir": "<workspace>/images",
     "backend": "auto" | "zimage" | "pollinations", "seed": 0}

Backends, in "auto" order:
  zimage        Z-Image Turbo (Tongyi-MAI/Z-Image-Turbo, Apache-2.0, 6B, 8-9 steps) through
                diffusers on CUDA or Apple MPS. On a GPU with less than 12 GB (the RTX 3070 Ti
                has 8 GB) the model is offloaded to system RAM piece by piece: slower, but it
                fits. Needs `python tools/setup_imagegen.py` once (torch + diffusers + the
                weights, about 20 GB).
  qwen          Qwen-Image 2.1 through ModelScope's free API-Inference (about 250 images a day
                once the ModelScope account is bound to a verified Alibaba Cloud account). Used
                when MODELSCOPE_API_KEY is set. Asynchronous: submit, then poll the task.
  pollinations  image.pollinations.ai: free, no account. The prompt goes to a third party.
"""
import json
import os
import re
import sys
import time
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


def zimage_ready():
    try:
        import importlib.util
        if not (importlib.util.find_spec("torch") and importlib.util.find_spec("diffusers")):
            return False
        import diffusers
        return hasattr(diffusers, "ZImagePipeline")
    except Exception:  # noqa: BLE001
        return False


def zimage(prompt, width, height, out_dir, seed):
    import torch
    from diffusers import ZImagePipeline
    if torch.cuda.is_available():
        device, dtype = "cuda", torch.bfloat16
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 2 ** 30
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        device, dtype, vram_gb = "mps", torch.bfloat16, 0.0
    else:
        device, dtype, vram_gb = "cpu", torch.float32, 0.0
    pipe = ZImagePipeline.from_pretrained(ZIMAGE_ID, torch_dtype=dtype)
    if device == "cuda" and vram_gb < 12:
        pipe.enable_model_cpu_offload()          # 8 GB cards: layers move to the GPU as needed
    else:
        pipe.to(device)
    generator = torch.Generator("cpu").manual_seed(int(seed)) if seed else None
    image = pipe(prompt=prompt, width=width, height=height, num_inference_steps=9,
                 guidance_scale=0.0, generator=generator).images[0]
    path = _out_path(out_dir, prompt)
    image.save(path)
    return {"file": str(path), "backend": "zimage", "device": device}


def _json_request(url, key, body=None, headers=None, timeout=60):
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


def pollinations(prompt, width, height, out_dir, seed):
    params = {"width": width, "height": height, "nologo": "true"}
    if seed:
        params["seed"] = int(seed)
    url = "https://image.pollinations.ai/prompt/%s?%s" % (urllib.parse.quote(prompt[:1500]), urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={"User-Agent": "Loki/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
        kind = resp.headers.get("Content-Type", "image/jpeg")
    if not data or not kind.startswith("image/"):
        raise RuntimeError("Pollinations returned no image")
    path = _out_path(out_dir, prompt, "png" if "png" in kind else "jpg")
    path.write_bytes(data)
    return {"file": str(path), "backend": "pollinations", "note": "made by a free third-party service"}


def main():
    job = json.loads(sys.stdin.read() or "{}")
    prompt = str(job.get("prompt") or "").strip()
    width = max(256, min(int(job.get("width") or 1024), 2048)) // 16 * 16
    height = max(256, min(int(job.get("height") or 1024), 2048)) // 16 * 16
    out_dir = str(job.get("out_dir") or "images")
    seed = int(job.get("seed") or 0)
    backend = str(job.get("backend") or os.environ.get("LOKI_IMAGE_BACKEND", "auto")).lower()
    try:
        if not prompt:
            raise ValueError("describe the image")
        order = [backend] if backend != "auto" else ((["zimage"] if zimage_ready() else [])
                                                     + (["qwen"] if os.environ.get("MODELSCOPE_API_KEY") else [])
                                                     + ["pollinations"])
        errors = []
        for name in order:
            try:
                fn = {"zimage": zimage, "qwen": qwen, "pollinations": pollinations}.get(name)
                if fn is None:
                    raise ValueError("unknown backend %r (zimage, qwen, pollinations)" % name)
                result = fn(prompt, width, height, out_dir, seed)
                print(json.dumps({"ok": True, **result}))
                return
            except Exception as exc:  # noqa: BLE001 - try the next backend
                errors.append("%s: %s: %s" % (name, type(exc).__name__, str(exc)[:200]))
        raise RuntimeError("; ".join(errors) or "no image backend")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)[:600]}))


if __name__ == "__main__":
    main()
