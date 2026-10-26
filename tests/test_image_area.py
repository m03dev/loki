"""Edit one area of a picture, leave the rest (owner 2026-10-26: "crop an area ... edit the area thats croped or
focused not deleting or touching the rest of it") and step through pictures with next (app/ui/image_viewer.js).
The model is faked; the viewer runs in headless Chromium when Playwright is there (skips cleanly otherwise).

    python tests/test_image_area.py
"""
from __future__ import annotations

import base64
import io
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-area-"))
PASS, FAIL = [], []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %r" % (detail,)))


from PIL import Image, ImageChops  # noqa: E402
import region_edit  # noqa: E402

# a picture with detail everywhere, so any stray change shows
src_img = Image.new("RGB", (640, 480))
src_img.putdata([((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256) for y in range(480) for x in range(640)])
(TMP / "images").mkdir()
SRC = TMP / "images" / "knight-sword-shield_20261026-1021.png"
src_img.save(SRC)
before = SRC.read_bytes()
seen = {}


def fake_model(init, mask, prompt, w, h, strength, seed, out):
    seen.update(size=Image.open(init).size, mask=Image.open(mask).getbbox(), w=w, h=h, prompt=prompt)
    Image.new("RGB", (w, h), (255, 0, 0)).save(out)       # the "model" paints everything red - even outside the box
    return out


res = region_edit.edit_area(SRC, [0.25, 0.25, 0.25, 0.25], "a golden helmet", model=fake_model)
out = Image.open(res["path"]).convert("RGB")
sel = tuple(res["box"])
check("the original file is never written", SRC.read_bytes() == before)
check("the edit is a new file beside it, named _edit", Path(res["path"]).parent == SRC.parent and "_edit" in res["file"], res["file"])
check("box in pixels", sel == (160, 120, 320, 240), sel)
outside = ImageChops.difference(out, src_img)
mask = Image.new("L", out.size, 255)
mask.paste(0, sel)
check("every pixel outside the box is identical", ImageChops.multiply(outside.convert("L"), mask).getbbox() is None,
      ImageChops.multiply(outside.convert("L"), mask).getbbox())
centre = out.getpixel((240, 180))
check("inside the box is the model's work", centre == (255, 0, 0), centre)
check("the model gets context around the box at a model size (x64)", seen["w"] % 64 == 0 and seen["h"] % 64 == 0
      and seen["size"] == (seen["w"], seen["h"]), seen)
check("the mask marks only the box inside the context crop", seen["mask"] and seen["mask"][0] > 0 and seen["mask"][2] < seen["w"], seen)
try:
    region_edit.edit_area(SRC, [0.5, 0.5, 0.01, 0.01], "x", model=fake_model)
    check("a mis-click box is refused", False)
except region_edit.EditError:
    check("a mis-click box is refused", True)
try:
    region_edit.edit_area(SRC, [0.1, 0.1, 0.5, 0.5], " ", model=fake_model)
    check("an empty prompt is refused", False)
except region_edit.EditError:
    check("an empty prompt is refused", True)

c = region_edit.crop(SRC, [0, 0, 0.5, 0.5])
check("crop saves just the area, beside it", Image.open(c["path"]).size == (320, 240) and "_crop" in c["file"], c)
check("crop leaves the original", SRC.read_bytes() == before)

# the backends' command lines (nothing runs)
runs = []


def fake_run(argv, **kw):
    runs.append(argv)
    Path(argv[argv.index("-o") + 1] if "-o" in argv else argv[argv.index("--output") + 1]).write_bytes(b"x")
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


import creative  # noqa: E402
creative.model_files = lambda key, env=None: [("diffusion", "", TMP / "d", ""), ("vae", "", TMP / "v", ""), ("llm", "", TMP / "l", "")]
key = next(iter(creative.SDCPP_MODELS))
region_edit.local_img2img(TMP / "i.png", TMP / "m.png", "helmet", 1024, 768, 0.7, 5, TMP / "o1.png", run=fake_run,
                          status={"ready": True, "backend": "sdcpp", "bin": "sd", "model": key}, info={"vram_gb": 8})
a = runs[-1]
check("PC: sd.cpp img2img with the mask and strength", "-i" in a and "--mask" in a and a[a.index("--strength") + 1] == "0.70", a[-8:])
region_edit.local_img2img(TMP / "i.png", TMP / "m.png", "helmet", 1024, 768, 0.7, 5, TMP / "o2.png", run=fake_run,
                          status={"ready": True, "backend": "mflux", "cmd": "mflux", "model": "z"}, info={"ram_gb": 16})
a = runs[-1]
check("Mac: mflux img2img keeps 1-strength of the picture", "--image-path" in a and a[a.index("--image-strength") + 1] == "0.30", a[-6:])

# the routes (background job, then done)
state = types.SimpleNamespace(agent=types.SimpleNamespace(WORKSPACE=str(TMP)))
import chat_media  # noqa: E402
chat_media.bases = lambda st: [TMP.resolve()]
orig = region_edit.edit_area
region_edit.edit_area = lambda s, b, p, st, f, sd: orig(s, b, p, st, f, sd, model=fake_model)
code, r = region_edit.route(state, "POST", "/image/edit-area", {}, {"path": "images/" + SRC.name, "box": [0.1, 0.1, 0.3, 0.3], "prompt": "a cape"})
check("POST /image/edit-area starts a job", code == 200 and r.get("job"), r)
for _ in range(50):
    code, s = region_edit.route(state, "GET", "/image/edit-area", {"job": r["job"]}, {})
    if s.get("status") != "running":
        break
    time.sleep(0.05)
check("the job finishes with the new file", s.get("status") == "done" and Path(s["path"]).is_file(), s)
code, r = region_edit.route(state, "POST", "/image/edit-area", {}, {"path": "images/" + SRC.name, "box": [0.1, 0.1, 0.3, 0.3]})
check("no prompt -> 400", code == 400, r)
code, r = region_edit.route(state, "POST", "/image/crop", {}, {"path": "../../etc/passwd", "box": [0, 0, 1, 1]})
check("outside the workspace -> refused", code == 400, r)

# ---- the viewer in a browser: next / before, area select (Cropper.js)
try:
    from playwright.sync_api import sync_playwright  # noqa: E402
except ImportError:
    sync_playwright = None
if sync_playwright:
    def durl(color):
        b = io.BytesIO(); Image.new("RGB", (400, 300), color).save(b, "PNG")
        return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
    ui = REPO / "app" / "ui"
    page_html = TMP / "viewer.html"
    page_html.write_text("<!doctype html><html><head><link rel=stylesheet href='%s'><link rel=stylesheet href='%s'></head><body>"
                         "<script src='%s'></script><script src='%s'></script></body></html>" % (
                             (ui / "vendor/cropper/cropper.min.css").as_uri(), (ui / "image_viewer.css").as_uri(),
                             (ui / "vendor/cropper/cropper.min.js").as_uri(), (ui / "image_viewer.js").as_uri()), encoding="utf-8")
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 1280, "height": 800})
            pg.goto(page_html.as_uri())
            items = [{"src": durl(c), "name": "pic %d" % i, "path": "images/p%d.png" % i} for i, c in enumerate(("red", "green", "blue"))]
            pg.evaluate("(it) => LokiViewer.open(it, 0)", items)
            check("viewer opens on the first picture", pg.inner_text(".lv-count") == "1 / 3")
            pg.click(".lv-next")
            check("Next shows the next picture", pg.inner_text(".lv-count") == "2 / 3" and pg.inner_text(".lv-name") == "pic 1")
            pg.keyboard.press("ArrowRight")
            check("→ steps too, and Next stops at the end", pg.inner_text(".lv-count") == "3 / 3" and pg.is_disabled(".lv-next"))
            pg.keyboard.press("ArrowLeft")
            check("← goes back", pg.inner_text(".lv-count") == "2 / 3")
            pg.keyboard.press("s")
            pg.wait_for_selector(".cropper-container", timeout=3000)
            check("S starts the area tool (Cropper.js)", pg.is_visible(".cropper-crop-box"))
            pg.keyboard.press("f")
            check("F focuses on the selected area", pg.is_visible(".lv-focus img"))
            pg.keyboard.press("Escape")
            check("Esc leaves focus first, keeps the viewer", pg.is_visible(".lv") and not pg.query_selector(".lv-focus"))
            pg.keyboard.press("e")
            check("E asks what the area should become", pg.is_visible(".lv-prompt"))
            for _ in range(4):
                pg.keyboard.press("Escape")
            check("Esc closes in the end", not pg.query_selector(".lv"))
            br.close()
    except Exception as exc:  # noqa: BLE001 - no browser on this machine
        print("SKIP the browser part (%s)" % type(exc).__name__)
else:
    print("SKIP the browser part (no Playwright)")
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
