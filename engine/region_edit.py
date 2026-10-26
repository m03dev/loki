"""Edit one area of a picture and leave the rest alone (owner 2026-10-26: "can i crop an area in the images to focus
on it and we can edit the area thats croped or focused not deleting or touching the rest of it").

How it keeps the rest untouched:
  1. take the selected box plus some context around it (CONTEXT, so the edit matches its surroundings);
  2. scale that crop to a size the model likes (multiple of 64, about 1 MP) and run image-to-image on it with the
     prompt - this machine's local backend: stable-diffusion.cpp on the PC (with an inpaint mask), mflux on the Mac;
  3. scale the result back and paste ONLY the selected box into a copy of the original, with a soft edge (feather)
     that stays inside the box. Every pixel outside the box is copied from the original byte for byte.
  4. save the copy as a new file beside the original (<subject>_<stamp>_edit.png, engine/out_names.py); the original
     is never written.

Also: crop() saves just the selected area as its own picture ("focus").

    POST /image/edit-area   {path, box: [x, y, w, h] (0-1 of the picture), prompt, strength 0.2-0.95, feather}
                            -> {ok, job}   (runs in the background)
    GET  /image/edit-area?job=ID            -> {ok, status: running|done|failed, file, path, error}
    POST /image/crop        {path, box}     -> {ok, file, path}
"""
from __future__ import annotations

import random
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

CONTEXT = 0.35          # extra around the box, as a share of its size, given to the model for context
MIN_SIDE = 16           # px: a smaller box is a mis-click
TARGET_PIXELS = 1024 * 1024
JOBS: dict = {}
_LOCK = threading.Lock()


class EditError(Exception):
    pass


# ----------------------------------------------------------------------------- geometry (pure, tested)
def pixel_box(box, width: int, height: int) -> tuple:
    """[x, y, w, h] as 0-1 shares (or pixels when any value > 1) -> integer (left, top, right, bottom), clamped."""
    try:
        x, y, w, h = (float(v) for v in box)
    except (TypeError, ValueError):
        raise EditError("box must be [x, y, width, height]") from None
    if max(x, y, w, h) <= 1.0:
        x, y, w, h = x * width, y * height, w * width, h * height
    left, top = max(0, int(round(x))), max(0, int(round(y)))
    right, bottom = min(width, int(round(x + w))), min(height, int(round(y + h)))
    if right - left < MIN_SIDE or bottom - top < MIN_SIDE:
        raise EditError("select a bigger area (at least %d px each way)" % MIN_SIDE)
    return left, top, right, bottom


def context_box(sel: tuple, width: int, height: int, context: float = CONTEXT) -> tuple:
    left, top, right, bottom = sel
    mx, my = int((right - left) * context), int((bottom - top) * context)
    return max(0, left - mx), max(0, top - my), min(width, right + mx), min(height, bottom + my)


def model_size(w: int, h: int, target: int = TARGET_PIXELS) -> tuple:
    """About `target` pixels, same shape, both sides multiples of 64 (at least 256)."""
    scale = (target / float(max(1, w * h))) ** 0.5
    return max(256, int(round(w * scale / 64.0)) * 64), max(256, int(round(h * scale / 64.0)) * 64)


def feather_mask(size: tuple, inner: tuple, feather: int):
    """L-mode mask the size of the crop: 255 inside `inner` (the selected box, in crop coordinates) fading to 0 at
    its edge over `feather` px - the fade stays INSIDE the box so nothing outside it ever changes."""
    from PIL import Image, ImageDraw, ImageFilter  # pylint: disable=import-outside-toplevel
    mask = Image.new("L", size, 0)
    l, t, r, b = inner
    f = max(0, min(int(feather), (r - l) // 4, (b - t) // 4))
    ImageDraw.Draw(mask).rectangle((l + f, t + f, r - 1 - f, b - 1 - f), fill=255)
    if f:
        mask = mask.filter(ImageFilter.GaussianBlur(f / 2.0))
        clip = Image.new("L", size, 0)
        ImageDraw.Draw(clip).rectangle((l, t, r - 1, b - 1), fill=255)
        from PIL import ImageChops  # pylint: disable=import-outside-toplevel
        mask = ImageChops.multiply(mask, clip)
    return mask


# ----------------------------------------------------------------------------- the model step
def local_img2img(init: Path, mask: Path, prompt: str, width: int, height: int, strength: float, seed: int,
                  out: Path, run: Callable = subprocess.run, status: dict | None = None,
                  info: dict | None = None) -> Path:
    """Image-to-image with this machine's local backend (engine/creative.py): sd.cpp (PC, inpaint with the mask) or
    mflux (Mac). Returns the file it wrote."""
    import creative  # pylint: disable=import-outside-toplevel
    info = info if info is not None else creative.machine()
    status = status if status is not None else creative.local_image_status(None, info)
    if not status.get("ready"):
        raise EditError(status.get("why") or "no local image backend on this computer")
    if status["backend"] == "sdcpp":
        argv = creative.sdcpp_argv(status["bin"], status["model"], prompt, "", width, height, seed, out, 1, info)
        argv += ["-i", str(init), "--mask", str(mask), "--strength", "%.2f" % strength]
    else:
        argv = creative.mflux_argv(status["cmd"], status["model"], prompt, width, height, seed, out,
                                   low_ram=float(info.get("ram_gb") or 0) <= 16)
        argv += ["--image-path", str(init), "--image-strength", "%.2f" % (1.0 - strength)]   # mflux: how much to KEEP
    proc = run(argv, capture_output=True, text=True, timeout=1800)
    if getattr(proc, "returncode", 1) != 0 or not Path(out).is_file():
        tail = ((getattr(proc, "stderr", "") or "") + (getattr(proc, "stdout", "") or "")).strip()[-400:]
        raise EditError("%s failed (exit %s): %s" % (status["backend"], getattr(proc, "returncode", "?"), tail))
    return Path(out)


# ----------------------------------------------------------------------------- edit + crop
def edit_area(src: Path, box, prompt: str, strength: float = 0.75, feather: int = 12, seed: int = 0,
              model: Callable | None = None) -> dict:
    """The whole edit (steps 1-4 above). `model(init, mask, prompt, w, h, strength, seed, out) -> Path`."""
    from PIL import Image  # pylint: disable=import-outside-toplevel
    import out_names  # pylint: disable=import-outside-toplevel
    prompt = " ".join(str(prompt or "").split())
    if not prompt:
        raise EditError("say what the selected area should become")
    src = Path(src)
    original = Image.open(src)
    original.load()
    mode = "RGBA" if original.mode in ("RGBA", "LA", "P") else "RGB"
    base = original.convert(mode)
    W, H = base.size
    sel = pixel_box(box, W, H)
    ctx = context_box(sel, W, H)
    crop = base.crop(ctx).convert("RGB")
    cw, ch = crop.size
    mw, mh = model_size(cw, ch)
    inner = (sel[0] - ctx[0], sel[1] - ctx[1], sel[2] - ctx[0], sel[3] - ctx[1])
    strength = max(0.2, min(0.95, float(strength or 0.75)))
    seed = int(seed) or random.randint(1, 2**31 - 1)
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="loki-area-") as tmp:
        tmp = Path(tmp)
        init, mask_path, out = tmp / "init.png", tmp / "mask.png", tmp / "out.png"
        crop.resize((mw, mh), Image.LANCZOS).save(init)
        sx, sy = mw / float(cw), mh / float(ch)
        hard = Image.new("L", (mw, mh), 0)
        from PIL import ImageDraw  # pylint: disable=import-outside-toplevel
        ImageDraw.Draw(hard).rectangle((int(inner[0] * sx), int(inner[1] * sy), int(inner[2] * sx) - 1,
                                        int(inner[3] * sy) - 1), fill=255)
        hard.save(mask_path)
        made = (model or local_img2img)(init, mask_path, prompt, mw, mh, strength, seed, out)
        result = Image.open(made).convert("RGB").resize((cw, ch), Image.LANCZOS)
    patch = result.convert(mode)
    blend = feather_mask((cw, ch), inner, feather)
    region = base.crop(ctx)
    region.paste(patch, (0, 0), blend)              # only inside the box (the mask is 0 everywhere else)
    edited = base.copy()
    edited.paste(region, ctx[:2])
    stem_text = out_names.display_name(src.name)
    target = out_names.path(src.parent, stem_text, "png", tag="edit", fallback="picture")
    edited.save(target)
    return {"ok": True, "file": target.name, "path": str(target), "source": str(src), "box": list(sel),
            "seed": seed, "strength": strength, "seconds": round(time.time() - t0, 1)}


def crop(src: Path, box) -> dict:
    """Save just the selected area as its own picture, beside the original."""
    from PIL import Image  # pylint: disable=import-outside-toplevel
    import out_names  # pylint: disable=import-outside-toplevel
    src = Path(src)
    img = Image.open(src)
    sel = pixel_box(box, *img.size)
    target = out_names.path(src.parent, out_names.display_name(src.name), "png", tag="crop", fallback="picture")
    img.crop(sel).save(target)
    return {"ok": True, "file": target.name, "path": str(target), "box": list(sel)}


# ----------------------------------------------------------------------------- jobs + routes
def start(src: Path, body: dict, runner: Callable | None = None) -> str:
    job = uuid.uuid4().hex[:10]
    with _LOCK:
        JOBS[job] = {"status": "running", "started": time.time(), "source": str(src)}
        for old in sorted(JOBS, key=lambda k: JOBS[k]["started"])[:-50]:
            JOBS.pop(old, None)

    def work():
        try:
            res = (runner or edit_area)(src, body.get("box"), body.get("prompt"), float(body.get("strength") or 0.75),
                                        int(body.get("feather") or 12), int(body.get("seed") or 0))
            JOBS[job].update(status="done", **res)
        except Exception as exc:  # noqa: BLE001 - the window shows why
            JOBS[job].update(status="failed", ok=False, error="%s" % (exc if isinstance(exc, EditError) else
                                                                     "%s: %s" % (type(exc).__name__, exc)))
    threading.Thread(target=work, name="loki-edit-area", daemon=True).start()
    return job


def route(state: Any, method: str, path: str, query: dict, body: dict) -> tuple:
    import chat_media  # pylint: disable=import-outside-toplevel
    try:
        if method == "GET" and path == "/image/edit-area":
            job = JOBS.get(str(query.get("job") or ""))
            return (200, {"ok": True, **job}) if job else (404, {"ok": False, "error": "no such edit"})
        src = chat_media.find(state, body.get("path"))
        if src.suffix.lower() == ".pdf":
            raise EditError("pick a picture, not a PDF")
        if path == "/image/crop":
            return 200, crop(src, body.get("box"))
        if path == "/image/edit-area":
            if not str(body.get("prompt") or "").strip():
                raise EditError("say what the selected area should become")
            if len([float(v) for v in body.get("box") or []]) != 4:
                raise EditError("box must be [x, y, width, height]")
            return 200, {"ok": True, "job": start(src, body)}
    except (EditError, chat_media.MediaError, OSError) as exc:
        return 400, {"ok": False, "error": str(exc)}
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "box must be [x, y, width, height]"}
    return 404, {"ok": False, "error": "unknown route"}
