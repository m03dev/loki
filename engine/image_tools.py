"""Picture edits on this computer (research round 3: the image tools of Cherry Studio / Lobe Chat, and
rembg - MIT - for "remove the background"). Nothing leaves the machine.

  info, resize, crop, rotate, flip, convert (png/jpg/webp), compress, grayscale, thumbnail,
  upscale (2x-4x, Pillow Lanczos + a light sharpen; a real AI upscaler when
  `realesrgan-ncnn-vulkan` is on PATH or LOKI_REALESRGAN points at it - MIT, runs on Vulkan,
  so on the PC's NVIDIA card and the Mac's Metal-backed Vulkan alike),
  remove_background (rembg with its u2net/isnet/birefnet ONNX models - the `rembg` add-on;
  the model downloads once to ~/.u2net, ~170 MB).

Every result is a NEW file next to the original (<name>-<what>.<ext>, never overwritten), so an edit
can always be undone by deleting it. Paths stay inside the workspace (the caller checks that).
Pillow is in engine/requirements.txt; rembg is optional.
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
from pathlib import Path

ACTIONS = ("info", "resize", "crop", "rotate", "flip", "convert", "compress", "grayscale", "thumbnail",
           "upscale", "remove_background", "pixelize")
FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP", "gif": "GIF", "bmp": "BMP"}
MAX_PIXELS = 80_000_000
IMPORT = importlib.import_module       # tests swap these
WHICH = shutil.which
RUN = subprocess.run


class ImageError(Exception):
    pass


def _pil():
    try:
        return IMPORT("PIL.Image"), IMPORT("PIL.ImageOps"), IMPORT("PIL.ImageFilter")
    except ImportError:
        raise ImageError("Pillow is not installed - run Update everything (it is in LOKI's requirements) or "
                         "pip install pillow") from None


def _out(src: Path, what: str, ext: str = "") -> Path:
    ext = (ext or src.suffix.lstrip(".") or "png").lower()
    base = src.with_name("%s-%s.%s" % (src.stem, what, ext))
    n = 2
    while base.exists():
        base = src.with_name("%s-%s-%d.%s" % (src.stem, what, n, ext))
        n += 1
    return base


def _save(img, path: Path, quality: int = 90) -> None:
    fmt = FORMATS.get(path.suffix.lstrip(".").lower(), "PNG")
    if fmt == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    kwargs = {"quality": int(quality), "optimize": True} if fmt in ("JPEG", "WEBP") else {"optimize": True} if fmt == "PNG" else {}
    img.save(path, fmt, **kwargs)


def _size(path: Path) -> str:
    n = path.stat().st_size
    return "%.1f MB" % (n / 1e6) if n > 1e6 else "%d KB" % max(1, n // 1000)


def rembg_available() -> bool:
    try:
        IMPORT("rembg")
        return True
    except ImportError:
        return False


def upscaler() -> str:
    exe = os.getenv("LOKI_REALESRGAN", "").strip()
    if exe and Path(exe).is_file():
        return exe
    return WHICH("realesrgan-ncnn-vulkan") or ""


def edit(path: Path, action: str, width: int = 0, height: int = 0, box: str = "", degrees: float = 90,
         direction: str = "horizontal", to: str = "", quality: int = 82, scale: int = 2, model: str = "",
         palette: str = "", colors: int = 0, dither: str = "none") -> dict:
    action = str(action or "info").strip().lower().replace("-", "_").replace(" ", "_")
    if action in ("pixel", "pixel_art", "pixelate", "pixelise"):
        action = "pixelize"
    if action == "pixelize":                  # engine/pixel_art.py: PixelOE's method, palettes, dithering
        import pixel_art  # pylint: disable=import-outside-toplevel
        try:
            res = pixel_art.pixelize(path, size=int(width or 64), palette=palette, colors=int(colors or 0),
                                     dither=dither or "none")
        except pixel_art.PixelError as exc:
            raise ImageError(str(exc)) from None
        return {"ok": True, "path": Path(res["file"]), "detail": "pixel art %dx%d, %d colours: %s (preview %s)" % (
            res["width"], res["height"], res["colors"], Path(res["file"]).name, Path(res["preview"]).name)}
    if action in ("remove_bg", "background", "cutout", "rembg"):
        action = "remove_background"
    if action not in ACTIONS:
        raise ImageError("action must be one of " + ", ".join(ACTIONS))
    src = Path(path)
    if not src.is_file():
        raise ImageError("no picture at %s" % src.name)
    Image, ImageOps, ImageFilter = _pil()
    try:
        img = Image.open(src)
        img.load()
    except Exception as exc:  # noqa: BLE001 - PIL raises many kinds
        raise ImageError("%s is not a picture Pillow can open (%s)" % (src.name, exc)) from None
    if img.width * img.height > MAX_PIXELS:
        raise ImageError("the picture is too big (%dx%d)" % (img.width, img.height))
    img = ImageOps.exif_transpose(img)
    info = {"width": img.width, "height": img.height, "mode": img.mode, "format": (img.format or src.suffix[1:]).upper()}
    if action == "info":
        return {"ok": True, "path": src, "detail": "%s: %dx%d, %s, %s, %s" % (src.name, img.width, img.height,
                                                                            info["format"], img.mode, _size(src))}
    if action == "resize":
        w, h = int(width or 0), int(height or 0)
        if w <= 0 and h <= 0:
            raise ImageError("resize needs width= or height= (the other keeps the shape)")
        if w <= 0:
            w = round(img.width * h / img.height)
        if h <= 0:
            h = round(img.height * w / img.width)
        if w > 12000 or h > 12000:
            raise ImageError("at most 12000 pixels a side")
        out_img, what = img.resize((w, h), Image.LANCZOS), "%dx%d" % (w, h)
    elif action == "thumbnail":
        side = int(width or height or 256)
        out_img = img.copy()
        out_img.thumbnail((side, side), Image.LANCZOS)
        what = "thumb%d" % side
    elif action == "crop":
        try:
            left, top, right, bottom = [int(float(v)) for v in str(box).replace(" ", "").split(",")]
        except ValueError:
            raise ImageError("crop needs box='left,top,right,bottom' in pixels (the picture is %dx%d)"
                             % (img.width, img.height)) from None
        if not (0 <= left < right <= img.width and 0 <= top < bottom <= img.height):
            raise ImageError("the box is outside the picture (%dx%d)" % (img.width, img.height))
        out_img, what = img.crop((left, top, right, bottom)), "crop"
    elif action == "rotate":
        out_img, what = img.rotate(-float(degrees or 90), expand=True, resample=Image.BICUBIC), "rot%d" % int(degrees or 90)
    elif action == "flip":
        vertical = str(direction or "").lower().startswith("v")
        out_img = ImageOps.flip(img) if vertical else ImageOps.mirror(img)
        what = "flipv" if vertical else "fliph"
    elif action == "grayscale":
        out_img, what = ImageOps.grayscale(img), "gray"
    elif action == "convert":
        ext = str(to or "").lower().lstrip(".")
        if ext not in FORMATS:
            raise ImageError("convert needs to= one of png, jpg, webp, gif, bmp")
        target = _out(src, "converted", ext)
        _save(img, target, quality)
        return {"ok": True, "path": target, "detail": "saved %s (%s)" % (target.name, _size(target))}
    elif action == "compress":
        ext = str(to or "").lower().lstrip(".") or ("jpg" if src.suffix.lower() in (".jpg", ".jpeg") else "webp")
        if ext not in ("jpg", "jpeg", "webp", "png"):
            raise ImageError("compress makes jpg, webp or png")
        target = _out(src, "small", ext)
        small = img
        if int(width or 0) > 0 and img.width > int(width):
            small = img.resize((int(width), round(img.height * int(width) / img.width)), Image.LANCZOS)
        _save(small, target, max(30, min(int(quality or 82), 95)))
        return {"ok": True, "path": target, "detail": "saved %s: %s -> %s" % (target.name, _size(src), _size(target))}
    elif action == "upscale":
        factor = max(2, min(int(scale or 2), 4))
        exe = upscaler()
        if exe:
            target = _out(src, "x%d" % factor, "png")
            proc = RUN([exe, "-i", str(src), "-o", str(target), "-s", str(factor)], capture_output=True, text=True,
                       timeout=600, check=False)
            if proc.returncode == 0 and target.exists():
                return {"ok": True, "path": target, "detail": "upscaled %dx with Real-ESRGAN: %s" % (factor, target.name)}
        if img.width * factor > 12000 or img.height * factor > 12000:
            raise ImageError("too big to upscale %dx" % factor)
        out_img = img.resize((img.width * factor, img.height * factor), Image.LANCZOS)
        out_img = out_img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
        what = "x%d" % factor
    else:   # remove_background
        try:
            rembg = IMPORT("rembg")
        except ImportError:
            raise ImageError("removing a background needs the rembg add-on: Settings > Add-ons > rembg > Install "
                             "(about 170 MB the first time). Nothing is uploaded.") from None
        import cutout  # pylint: disable=import-outside-toplevel
        if model in cutout.FORBIDDEN:
            raise ImageError("%s is not used (non-commercial licence); LOKI uses BiRefNet or U^2-Net" % model)
        model = model or cutout.ALLOWED[0]          # never rembg's default (bria-rmbg, non-commercial)
        try:
            session = rembg.new_session(model)
        except Exception:  # noqa: BLE001 - not downloadable: the next licence-safe one
            session = rembg.new_session(cutout.ALLOWED[2])
        out_img = rembg.remove(img, session=session)
        target = _out(src, "nobg", "png")
        _save(out_img, target)
        return {"ok": True, "path": target, "detail": "background removed: %s (transparent PNG)" % target.name}
    target = _out(src, what)
    _save(out_img, target, quality if src.suffix.lower() in (".jpg", ".jpeg", ".webp") else 90)
    return {"ok": True, "path": target, "detail": "saved %s (%dx%d, %s)" % (target.name, out_img.width, out_img.height,
                                                                          _size(target))}
