"""Make one image. stdin/stdout JSON, like every runner.

    {"prompt": "...", "width": 1024, "height": 1024, "out_dir": "<workspace>/images",
     "backend": "auto" | "zimage" | "pollinations", "seed": 0}

Backends, in "auto" order:
  zimage        Z-Image Turbo (Tongyi-MAI/Z-Image-Turbo, Apache-2.0, 6B, 8-9 steps) through
                diffusers on CUDA or Apple MPS. On a GPU with less than 12 GB (the RTX 3070 Ti
                has 8 GB) the model is offloaded to system RAM piece by piece: slower, but it
                fits. Needs `python tools/setup_imagegen.py` once (torch + diffusers + the
                weights, about 20 GB).
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
        order = [backend] if backend != "auto" else (["zimage"] if zimage_ready() else []) + ["pollinations"]
        errors = []
        for name in order:
            try:
                result = (zimage if name == "zimage" else pollinations)(prompt, width, height, out_dir, seed)
                print(json.dumps({"ok": True, **result}))
                return
            except Exception as exc:  # noqa: BLE001 - try the next backend
                errors.append("%s: %s: %s" % (name, type(exc).__name__, str(exc)[:200]))
        raise RuntimeError("; ".join(errors) or "no image backend")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)[:600]}))


if __name__ == "__main__":
    main()
