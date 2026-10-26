"""The art team's craft (owner 2026-10-25: "it should be professional"): a brief becomes an art director's prompt, and a
finished picture can be enlarged 2x / 4x with Real-ESRGAN (github.com/xinntao/Real-ESRGAN, BSD-3; the portable
ncnn-vulkan build: no Python, no CUDA - it runs on the Mac's GPU and the PC's).

    direct(prompt, style)          the prompt with that style's medium, light, finish and composition words; a style's
                                   negative prompt; style "" leaves the prompt as written
    upscale(path, scale, anime)    -> the enlarged copy beside it ("<name>-4x.png"); installs Real-ESRGAN once
                                   (about 45 MB, into LOKI's data folder)
"""
from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

GENERAL_NEG = ("blurry, low resolution, jpeg artifacts, watermark, signature, text artifacts, extra fingers, "
               "deformed hands, bad anatomy, duplicated limbs, cropped, out of frame, oversaturated, muddy colors")
STYLES = {
    # Owner 2026-10-25 21:02: "who made the concept art its fantastic we need more like that, who ever made that is
    # hired" - the red baby dragon by LOKI's builder (prompt) + FLUX.2 klein 4B on NVIDIA (picture). Its recipe:
    "game-concept": ("game concept art, cinematic dramatic lighting, painterly fantasy style, detailed textures, "
                     "glowing accents, rich warm color, atmospheric depth, 16:9 ultra wide", GENERAL_NEG),
    # the same hand, for a subject that will become a sprite or a 3D model: alone, whole, readable, on plain white
    "sprite-source": ("single subject, full body, centered, isolated on a plain flat white background, no scenery, "
                      "no ground shadow, clean readable silhouette, game asset reference, painterly fantasy style, "
                      "dramatic lighting, detailed", GENERAL_NEG + ", background scenery, multiple subjects, cut off"),
    "concept-art": ("professional concept art, matte painting, cinematic composition, dramatic volumetric lighting, "
                    "rich atmospheric depth, highly detailed, art station quality", GENERAL_NEG),
    "oil-painting": ("oil painting on canvas, visible confident brushstrokes, painterly, classical composition, "
                     "warm chiaroscuro lighting, rich layered color, museum quality fine art", GENERAL_NEG + ", photo"),
    "watercolor": ("watercolor painting, soft wet-on-wet washes, paper texture, delicate edges, luminous light, "
                   "loose expressive linework", GENERAL_NEG + ", photo, 3d render"),
    "comic": ("comic book art, bold clean inks, dynamic panel composition, cel shading, crisp line weight, "
              "vibrant flat colors, professional graphic novel quality", GENERAL_NEG + ", photo, blurry lines"),
    "manga": ("manga illustration, clean precise linework, screentone shading, expressive characters, dynamic angle",
              GENERAL_NEG + ", photo, 3d render"),
    "book-cover": ("professional book cover illustration, strong central focal point, clear space for the title at the "
                   "top, striking color palette, dramatic lighting, print quality", GENERAL_NEG),
    "photo": ("professional photograph, 85mm lens, shallow depth of field, natural soft light, true-to-life color, "
              "sharp focus, high dynamic range", GENERAL_NEG + ", painting, illustration, cartoon"),
    "product": ("studio product photography, seamless background, softbox lighting, crisp reflections, sharp focus, "
                "commercial catalog quality", GENERAL_NEG + ", clutter"),
    "3d-render": ("high-end 3D render, physically based materials, global illumination, soft shadows, octane quality, "
                  "clean studio backdrop", GENERAL_NEG + ", flat, sketch"),
    "pixel-art": ("pixel art, crisp pixels, limited palette, clean silhouettes, retro game sprite quality",
                  "blurry, anti-aliased, smooth gradients, photo, jpeg artifacts"),
    "character-sheet": ("character design sheet, front side and back views, neutral pose, clean flat background, "
                        "consistent proportions, professional game art", GENERAL_NEG + ", busy background"),
    "texture": ("seamless tileable texture, flat even lighting, no shadows, top-down, high detail surface",
                "perspective, shadows, objects, text, watermark"),
}


def direct(prompt: str, style: str = "") -> tuple:
    """(prompt, negative) for a style; an unknown or empty style keeps the prompt as written."""
    prompt = str(prompt or "").strip()
    key = str(style or "").strip().lower().replace(" ", "-").replace("_", "-")
    if key not in STYLES:
        return prompt, ""
    pos, neg = STYLES[key]
    return ("%s. %s" % (prompt.rstrip(". "), pos)), neg


# ------------------------------------------------------------------ Real-ESRGAN (portable)
RELEASE = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
ASSETS = {"darwin": "realesrgan-ncnn-vulkan-20220424-macos.zip", "win32": "realesrgan-ncnn-vulkan-20220424-windows.zip",
          "linux": "realesrgan-ncnn-vulkan-20220424-ubuntu.zip"}


def tools_dir() -> Path:
    try:
        import creative  # pylint: disable=import-outside-toplevel
        base = Path(creative.data_dir())
    except Exception:  # noqa: BLE001
        base = Path(os.environ.get("LOKI_DATA") or Path.home() / ".loki")
    return base / "tools" / "realesrgan"


def find_upscaler() -> str:
    exe = "realesrgan-ncnn-vulkan" + (".exe" if sys.platform == "win32" else "")
    on_path = shutil.which(exe)
    if on_path:
        return on_path
    for p in tools_dir().rglob(exe) if tools_dir().is_dir() else []:
        return str(p)
    return ""


def install_upscaler(opener=urllib.request.urlopen) -> str:
    plat = "linux" if sys.platform.startswith("linux") else sys.platform
    asset = ASSETS.get(plat)
    if not asset:
        raise RuntimeError("no Real-ESRGAN build for %s" % platform.system())
    dest = tools_dir()
    dest.mkdir(parents=True, exist_ok=True)
    zpath = dest / asset
    with opener(urllib.request.Request(RELEASE + asset, headers={"User-Agent": "Loki/1.0"}), timeout=300) as resp:
        zpath.write_bytes(resp.read())
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            target = (dest / m.filename).resolve()
            if dest.resolve() not in target.parents and target != dest.resolve():
                continue                                    # never outside the folder
            z.extract(m, dest)
    zpath.unlink(missing_ok=True)
    exe = find_upscaler()
    if not exe:
        raise RuntimeError("Real-ESRGAN unpacked but its program was not found")
    os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return exe


def upscale(path: str, scale: int = 4, anime: bool = False, run=subprocess.run) -> dict:
    src = Path(path)
    if not src.is_file():
        return {"ok": False, "error": "no such picture: %s" % path}
    scale = 4 if int(scale or 4) >= 3 else 2
    exe = find_upscaler()
    if not exe:
        try:
            exe = install_upscaler()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "Real-ESRGAN could not be installed: %s" % str(exc)[:200]}
    model = "realesrgan-x4plus-anime" if anime else "realesrgan-x4plus"     # both are 4x models
    out = src.with_name("%s-%dx.png" % (src.stem, scale))
    cmd = [exe, "-i", str(src), "-o", str(out), "-n", model, "-s", "4", "-f", "png"]
    models = Path(exe).parent / "models"
    if models.is_dir():
        cmd += ["-m", str(models)]
    proc = run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0 or not out.is_file():
        return {"ok": False, "error": ("Real-ESRGAN failed: %s" % (proc.stderr or proc.stdout or "")[-300:]).strip()}
    if scale == 2:   # 4x, then a clean half: sharper than any 2x-only model
        try:
            from PIL import Image  # pylint: disable=import-outside-toplevel
            with Image.open(out) as im:
                im.resize((im.width // 2, im.height // 2), Image.LANCZOS).save(out)
        except Exception:  # noqa: BLE001
            scale = 4
            out = out.rename(src.with_name("%s-4x.png" % src.stem))
    return {"ok": True, "file": str(out), "scale": scale, "model": model}
