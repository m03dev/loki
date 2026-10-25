"""Pixel art (engine/pixel_art.py: PixelOE's method ported to numpy + Pillow; palettes; dithering) and where it is
offered (the pixelize tool, edit_image action=pixelize, `loki-make pixel`, make_image style pixel-art, the chat's
Pixel art button). Offline, a few seconds.

    python tests/test_pixel_art.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-pixel-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import pixel_art as pa  # noqa: E402

# ------------------------------------------------------------------ the port matches OpenCV where PixelOE used it
try:
    import cv2  # noqa: E402
except ImportError:
    cv2 = None
rng = np.random.default_rng(1)
noise = rng.integers(0, 255, (40, 56, 3)).astype(np.uint8)
if cv2 is not None:
    f = noise.astype(np.float32) / 255
    ref = cv2.cvtColor(f[..., ::-1].copy(), cv2.COLOR_BGR2LAB)
    check("RGB -> LAB matches OpenCV's float LAB (within 0.5)", np.abs(pa.lab_f(f) - ref).max() < 0.5,
          np.abs(pa.lab_f(f) - ref).max())
    ones = np.ones((3, 3), np.float32)
    check("with a hard 3x3 kernel the soft erode / dilate equal OpenCV's",
          np.allclose(pa._morph(f, "erode", ones), cv2.erode(f, np.ones((3, 3), np.uint8)))
          and np.allclose(pa._morph(f, "dilate", ones), cv2.dilate(f, np.ones((3, 3), np.uint8))))
else:
    print("  (OpenCV not installed here: the cross-checks against it are skipped)")
check("PixelOE's circle kernels: 3x3 for thickness 1-3, 5x5 for 4", pa.kernel(1).shape == (3, 3)
      and pa.kernel(3).shape == (3, 3) and pa.kernel(4).shape == (5, 5) and pa.kernel(2)[1, 1] == 1)
check("LAB -> RGB -> LAB round trip is exact", np.abs(pa.rgb_f(pa.lab_f(noise / 255.0)) * 255 - noise).max() < 0.01)

# ------------------------------------------------------------------ pixelize
pic = TMP / "hero.png"
im = Image.new("RGB", (512, 384), (235, 240, 245))
d = ImageDraw.Draw(im)
d.ellipse((150, 60, 360, 300), fill=(200, 60, 40), outline=(20, 20, 30), width=4)
d.rectangle((230, 140, 280, 160), fill=(250, 250, 250))
d.line((100, 340, 420, 340), fill=(20, 20, 30), width=3)
im.save(pic)
r = pa.pixelize(pic, size=64)
out = Image.open(r["file"])
check("a 512x384 picture -> a 64x48 sprite (the longer side is size)", out.size == (64, 48) and r["width"] == 64, out.size)
prev = Image.open(r["preview"])
check("the preview is the sprite enlarged with hard pixels", prev.size == (64 * 8, 48 * 8)
      and prev.resize((64, 48), Image.NEAREST).convert("RGB").tobytes() == out.convert("RGB").tobytes())
def dark(img):
    return int((np.asarray(img.convert("RGB")).astype(int).sum(axis=-1) < 150).sum())


r = pa.pixelize(pic, size=64, outline=0, mode="nearest")
plain = Image.open(r["file"])
check("outline=0 + nearest is the plain shrink", plain.size == (64, 48))
lines = TMP / "lines.png"
li = Image.new("RGB", (512, 512), (240, 240, 235))
for k in range(6):                                    # thin dark strokes on a light ground (lineart, outlines)
    ImageDraw.Draw(li).line((40, 40 + k * 80, 470, 70 + k * 80), fill=(25, 25, 35), width=3)
li.save(lines)
kept = dark(Image.open(pa.pixelize(lines, size=64)["file"]))
lost = dark(Image.open(pa.pixelize(lines, size=64, outline=0, mode="nearest")["file"]))
check("outline expansion keeps thin dark strokes a plain shrink drops", kept > lost * 1.5, (kept, lost))
r = pa.pixelize(pic, size=48, palette="pico-8")
pico = set(pa.parse_palette("pico-8"))
used = {c for _, c in Image.open(r["file"]).convert("RGB").getcolors(1 << 16)}
check("palette pico-8: every pixel is a PICO-8 colour", used <= pico and len(used) >= 3, used - pico)
r = pa.pixelize(pic, size=48, palette="#000000 #ffffff #ff0000", dither="bayer")
used = {c for _, c in Image.open(r["file"]).convert("RGB").getcolors(1 << 16)}
check("a #hex palette with Bayer dithering stays inside the palette", used <= {(0, 0, 0), (255, 255, 255), (255, 0, 0)}, used)
r = pa.pixelize(pic, size=48, colors=6, dither="floyd")
check("colors=6 -> at most 6 colours", r["colors"] <= 6, r["colors"])
for mode in ("center", "median", "k-centroid"):
    r = pa.pixelize(pic, size=32, mode=mode)
    check("mode %s works" % mode, Image.open(r["file"]).size == (32, 24))
spr = TMP / "sprite.png"
s = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
ImageDraw.Draw(s).ellipse((40, 40, 216, 216), fill=(30, 140, 220, 255))
s.save(spr)
r = pa.pixelize(spr, size=32)
alphas = set(np.unique(np.asarray(Image.open(r["file"]).getchannel("A"))).tolist())
check("a transparent sprite stays transparent with hard edges (alpha only 0 or 255)", alphas == {0, 255}, alphas)
for bad, kw in (("mode", {"mode": "blur"}), ("palette", {"palette": "#12"}), ("dither", {"dither": "x"})):
    try:
        pa.pixelize(pic, **kw)
        check("a bad %s is refused plainly" % bad, False)
    except pa.PixelError:
        check("a bad %s is refused plainly" % bad, True)

# ------------------------------------------------------------------ where it is offered
import make_mcp  # noqa: E402
ws = TMP / "ws"
(ws / "images").mkdir(parents=True)
Image.open(pic).save(ws / "images" / "knight.png")
got = make_mcp.call_tool("pixelize", {"image": "images/knight.png", "size": 32, "palette": "endesga-32"}, ws) \
    if hasattr(make_mcp, "call_tool") else make_mcp.pixelize({"image": "images/knight.png", "size": 32,
                                                               "palette": "endesga-32"}, ws)
check("the agents' pixelize tool saves the sprite in the folder", got.get("ok") and (ws / got["file"]).is_file()
      and got["width"] == 32, got)
check("the tool is listed for MCP clients", any(t["name"] == "pixelize" for t in make_mcp.TOOLS))
check("loki-make has 'pixel'", make_mcp.CLI.get("pixel") == "pixelize")


def fake_runner(cmd, input=None, **kw):  # noqa: A002 - make_image's image runner
    job = json.loads(input)
    f = Path(job["out_dir"]) / "lighthouse.png"
    Image.open(pic).save(f)

    class P:
        stdout = json.dumps({"ok": True, "file": str(f), "files": [str(f)], "backend": "local"})
        stderr = ""
        returncode = 0
    return P()


got = make_mcp.make_image({"prompt": "a lighthouse", "style": "pixel-art", "pixel_size": 40}, ws, runner=fake_runner)
check("make_image style pixel-art also makes the real sprite", got.get("ok") and got.get("pixel_sprites")
      and Image.open(ws / got["pixel_sprites"][0]).size[0] == 40, got)
import image_tools  # noqa: E402
got = image_tools.edit(ws / "images" / "knight.png", "pixelize", width=24, palette="gameboy")
check("edit_image action=pixelize", got["ok"] and Image.open(got["path"]).size[0] == 24, got)
import chat_media  # noqa: E402


class St:
    agent = None


chat_media.find = lambda state, raw: Path(raw)  # the workspace check is tested in test_chat_media
got = chat_media.convert(St(), str(ws / "images" / "knight.png"), "pixel")
check("the chat's Pixel art button makes the sprite and hands back its preview", got["ok"] and Path(got["preview"]).is_file())
js = (REPO / "app" / "ui" / "chat_media.js").read_text()
check("pictures in the chat have a Pixel art button", '"Pixel art"' in js and '"pixel"' in js)
check("PixelOE's licence is kept", (REPO / "engine" / "licenses" / "PixelOE-Apache-2.0.txt").is_file())

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
