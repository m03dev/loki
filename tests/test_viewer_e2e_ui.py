"""The picture viewer end to end in LOKI's real window (index.html, home.js, chat_media.js, image_viewer.js, Cropper.js)
against the REAL engine routes (engine/region_edit.py) and a real subprocess: Home's preview -> click -> the viewer;
Next / Before through the pictures; select an area by dragging; Save crop and Edit area write real files beside the
original; the original is untouched and every pixel outside the box is identical. The model is
tests/fixtures/fake_sdcpp.py (sd.cpp's command line, not a model) - a real model run is a machine check.

    python tests/test_viewer_e2e_ui.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
PASS: list = []
FAIL: list = []
SHOTS = Path(os.getenv("LOKI_SHOTS", "")) if os.getenv("LOKI_SHOTS") else None


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright here\n\n0 passed, 0 failed")
    sys.exit(0)
from PIL import Image, ImageChops, ImageDraw  # noqa: E402

WS = Path(tempfile.mkdtemp(prefix="loki-viewer-e2e-"))
(WS / "images").mkdir()


def knight(path, sky):
    im = Image.new("RGB", (768, 768), sky)
    d = ImageDraw.Draw(im)
    for y in range(500, 768, 6):
        d.line((0, y, 768, y), fill=(60 + y % 40, 90, 50))
    d.rectangle((330, 300, 440, 560), fill=(150, 150, 165))          # body
    d.ellipse((335, 190, 435, 300), fill=(170, 170, 185))            # head / helmet
    d.rectangle((250, 330, 330, 470), fill=(110, 60, 30))            # shield
    d.line((460, 260, 460, 560), fill=(220, 220, 230), width=10)     # sword
    im.save(path)


NAMES = ["red-fox-cub_20261026-0901.png", "knight-sword-shield_20261026-1021.png", "ancient-mountain-shrine_20261026-1140.png"]
for i, (n, sky) in enumerate(zip(NAMES, ((90, 120, 160), (70, 100, 150), (120, 90, 140)))):
    knight(WS / "images" / n, sky)
    os.utime(WS / "images" / n, (time.time() - 100 * (3 - i),) * 2)
KNIGHT = WS / "images" / NAMES[1]
BEFORE = KNIGHT.read_bytes()

import chat_media  # noqa: E402
import creative  # noqa: E402
import region_edit  # noqa: E402

STATE = types.SimpleNamespace(agent=types.SimpleNamespace(WORKSPACE=str(WS)))
chat_media.bases = lambda st: [WS.resolve()]
key = next(iter(creative.SDCPP_MODELS))
creative.model_files = lambda k, env=None: [(r, "", WS / r, 0) for r in ("diffusion", "vae", "llm")]
creative.local_image_status = lambda env=None, info=None: {"ready": True, "backend": "sdcpp", "bin": sys.executable, "model": key}
creative.machine = lambda: {"vram_gb": 8}
_argv = creative.sdcpp_argv
creative.sdcpp_argv = lambda *a, **k: [sys.executable, str(REPO / "tests/fixtures/fake_sdcpp.py")] + _argv(*a, **k)[1:]
ITEMS = [{"kind": "made", "name": n.split("_")[0].replace("-", " "), "path_or_id": "images/" + n, "updated": time.time() - 100 * (3 - i),
          "thumb": "/creations/images/" + n, "video": None, "status": "", "detail": "picture", "open": {"mode": "files", "path": "images/" + n}}
         for i, n in enumerate(NAMES)][::-1]


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        errors, calls = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            url = r.request.url.split("8894", 1)[1].split("#")[0]
            bare, query = (url.split("?", 1) + [""])[:2]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if bare.startswith("/creations/"):
                f = WS / unquote(bare[len("/creations/"):])
                return await r.fulfill(path=str(f)) if f.is_file() else await r.fulfill(status=404, body="")
            if bare == "/home/projects":
                return await r.fulfill(json={"ok": True, "items": ITEMS, "errors": {}, "counts": {"made": len(ITEMS)}})
            if bare.startswith("/image/"):
                body = json.loads(r.request.post_data or "{}") if r.request.method == "POST" else {}
                q = dict(x.split("=", 1) for x in query.split("&") if "=" in x)
                calls.append((r.request.method, bare, body))
                code, out = region_edit.route(STATE, r.request.method, bare, q, body)   # the REAL engine route
                return await r.fulfill(status=code, json=out)
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8894/**", route)
        await page.goto("http://127.0.0.1:8894/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("window.LokiHome && LokiHome.refresh && LokiHome.refresh()")
        await page.wait_for_selector(".home-hero-pic.home-hero-viewable img", timeout=10000)
        check("Home's preview is a picture you can click", True)
        await page.hover(".home-hero-pic")
        await page.click(".home-hero-pic .home-hero-nav.next")
        name = await E("document.querySelector('.home-hero-name').textContent")
        check("the preview's own Next steps to the next picture", name == "knight sword shield", name)
        await page.click(".home-hero-pic img")
        await page.wait_for_selector(".lv .lv-img", timeout=5000)
        count = await E("document.querySelector('.lv-count').textContent")
        check("a click opens the viewer on that picture", count == "2 / 3", count)
        await page.click(".lv-next")
        check("Next in the viewer", await E("document.querySelector('.lv-count').textContent") == "3 / 3")
        await page.keyboard.press("ArrowLeft")
        await page.wait_for_function("document.querySelector('.lv-img').complete && document.querySelector('.lv-img').naturalWidth > 0")
        check("← back to the knight", await E("document.querySelector('.lv-name').textContent") == "knight sword shield")
        if SHOTS:
            await page.screenshot(path=str(SHOTS / "1_viewer.png"))
        # select the helmet by dragging on the picture, like a person
        await page.keyboard.press("s")
        await page.wait_for_selector(".cropper-canvas", timeout=5000)
        cv = await E("(() => { const r = document.querySelector('.cropper-canvas').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })()")
        await E("document.querySelector('.lv-img').cropper.clear()")
        sx, sy = cv[0] + cv[2] * 320 / 768, cv[1] + cv[3] * 170 / 768
        ex, ey = cv[0] + cv[2] * 450 / 768, cv[1] + cv[3] * 310 / 768
        await page.mouse.move(sx, sy); await page.mouse.down(); await page.mouse.move(ex, ey, steps=8); await page.mouse.up()
        data = await E("document.querySelector('.lv-img').cropper.getData(true)")
        check("dragging selects the helmet area", abs(data["x"] - 320) < 12 and abs(data["y"] - 170) < 12 and data["width"] > 90 and data["height"] > 90, data)
        await page.keyboard.press("f")
        check("F shows just that area", await E("!!document.querySelector('.lv-focus img')"))
        await page.keyboard.press("Escape")
        # Save crop -> a real file
        await page.click(".lv-tools .lv-btn[aria-label='Save crop']")
        await page.wait_for_function("document.querySelector('.lv-say').textContent.startsWith('Saved')", timeout=8000)
        crops = sorted((WS / "images").glob("*_crop*.png"))
        check("Save crop writes the area as its own picture beside the original", len(crops) == 1 and Image.open(crops[0]).size == (data["width"], data["height"]), (crops, data))
        check("... and shows it next in the viewer", "_crop" in await E("document.querySelector('.lv-name').textContent"))
        await page.keyboard.press("ArrowLeft")
        await page.wait_for_function("document.querySelector('.lv-name').textContent === 'knight sword shield'")
        # Edit area -> the real route, the real subprocess, a real new file
        await page.keyboard.press("s")
        await page.wait_for_selector(".cropper-canvas", timeout=5000)
        cv = await E("(() => { const r = document.querySelector('.cropper-canvas').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })()")
        await E("document.querySelector('.lv-img').cropper.clear()")
        sx, sy = cv[0] + cv[2] * 320 / 768, cv[1] + cv[3] * 170 / 768
        ex, ey = cv[0] + cv[2] * 450 / 768, cv[1] + cv[3] * 310 / 768
        await page.mouse.move(sx, sy); await page.mouse.down(); await page.mouse.move(ex, ey, steps=8); await page.mouse.up()
        await page.keyboard.press("e")
        await page.fill(".lv-prompt", "a golden helmet with a red plume")
        if SHOTS:
            await page.screenshot(path=str(SHOTS / "2_select_and_prompt.png"))
        await page.click(".lv-edit button[type=submit]")
        await page.wait_for_function("/^Edited|^Not edited/.test(document.querySelector('.lv-say').textContent)", timeout=30000)
        said = await E("document.querySelector('.lv-say').textContent")
        check("Edit area finishes", said.startswith("Edited"), said)
        edits = sorted((WS / "images").glob("*_edit*.png"))
        check("the edit is a new file beside the original", len(edits) == 1, edits)
        check("the original file is untouched", KNIGHT.read_bytes() == BEFORE)
        if edits:
            a, b = Image.open(KNIGHT).convert("RGB"), Image.open(edits[0]).convert("RGB")
            box = next(c for c in calls if c[1] == "/image/edit-area" and c[0] == "POST")[2]["box"]
            l, t = round(box[0] * 768), round(box[1] * 768)
            r_, b_ = round((box[0] + box[2]) * 768), round((box[1] + box[3]) * 768)
            m = Image.new("L", a.size, 255); m.paste(0, (l, t, r_, b_))
            diff = ImageChops.multiply(ImageChops.difference(a, b).convert("L"), m).getbbox()
            check("every pixel outside the selected box is identical", diff is None, diff)
            inside = ImageChops.difference(a.crop((l, t, r_, b_)), b.crop((l, t, r_, b_))).getbbox()
            check("inside the box it changed", inside is not None)
        await page.wait_for_function("document.querySelector('.lv-img').complete && document.querySelector('.lv-img').naturalWidth > 0")
        check("the viewer shows the edited picture right after the original",
              "_edit" in await E("document.querySelector('.lv-name').textContent") and await E("document.querySelector('.lv-count').textContent") == "3 / 5")   # 3 pictures + the crop + the edit
        if SHOTS:
            await page.screenshot(path=str(SHOTS / "3_edited.png"))
        await page.keyboard.down("b")
        held = await E("document.querySelector('.lv').classList.contains('lv-showing-before')")
        await page.keyboard.up("b")
        check("hold B shows the original again", held)
        await page.keyboard.press("Escape")
        await page.keyboard.press("Escape")
        check("Esc closes the viewer", not await E("!!document.querySelector('.lv')"))
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
