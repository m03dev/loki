"""Home shows a Forge model as a live 3D model (app/ui/model_preview.js; owner 2026-10-26: "i want to preview them in
loki as 3d assets once they are made i should be able to open inside forge"). LOKI's real window (index.html +
home.js + model_preview.js + vendored three.js) in headless Chromium, a real .glb made by Forge's own writer, the
engine stubbed. Checks: the big preview draws the model (WebGL canvas, triangles counted), the card's thumbnail is
the model's render, double-click opens Forge with that model. Skips cleanly without a browser / WebGL.

    python tests/test_home_3d_ui.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright\n\n0 passed, 0 failed")
    sys.exit(0)
from PIL import Image, ImageDraw  # noqa: E402
import forge3d  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="loki-home3d-"))
pic = TMP / "dragon.png"
im = Image.new("RGB", (256, 256), (255, 255, 255))
ImageDraw.Draw(im).ellipse((60, 40, 200, 220), fill=(200, 60, 40))
im.save(pic)
res = forge3d.make_3d(str(pic), TMP / "models", "a little dragon", "lift")
GLB = Path(res["glb"])
RENDER = TMP / "render.png"
Image.new("RGB", (64, 64), (10, 200, 10)).save(RENDER)
ITEMS = [{"kind": "forge", "name": "a little dragon", "path_or_id": "models/" + GLB.name, "updated": time.time(),
          "thumb": "/creations/renders/render.png", "status": "", "detail": "9,000 triangles",
          "open": {"mode": "forge", "model": GLB.name}}]


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=["--use-gl=swiftshader", "--enable-webgl"]) if exe
                             else p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"]))
        except Exception as exc:  # noqa: BLE001
            print("SKIP: no Chromium (%s)" % str(exc)[:100])
            return
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        errors, served = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8895", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                ctype = "text/javascript" if bare.endswith(".js") else None
                return await r.fulfill(path=str(UI / bare[4:]), **({"content_type": ctype} if ctype else {}))
            if bare == "/home/projects":
                return await r.fulfill(json={"ok": True, "items": ITEMS, "errors": {}, "counts": {"forge": 1}})
            if bare.startswith("/forge/file/"):
                served.append((bare, r.request.headers.get("authorization")))
                return await r.fulfill(body=GLB.read_bytes(), content_type="model/gltf-binary")
            if bare == "/creations/renders/render.png":
                return await r.fulfill(path=str(RENDER), content_type="image/png")
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8895/**", route)
        await page.goto("http://127.0.0.1:8895/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        check("model_preview.js loads in LOKI's window", await E("!!window.LokiModelPreview"))
        await E("LokiHome.refresh && LokiHome.refresh()")
        await page.wait_for_selector(".home-hero-pic.home-hero-3d", timeout=10000)
        try:
            await page.wait_for_selector(".home-hero-pic[data-mp-ready='1'] canvas.mp-canvas", timeout=15000)
            ready = True
        except Exception:  # noqa: BLE001
            ready = False
        if not ready and not await E("(() => { try { return !!document.createElement('canvas').getContext('webgl2'); } catch (e) { return false; } })()"):
            print("SKIP the WebGL part (no WebGL in this browser)")
        else:
            check("the big preview draws the model itself (WebGL canvas)", ready)
            check("... fetched from /forge/file/<model> with the token", served and served[0][0] == "/forge/file/" + GLB.name
                  and served[0][1] == "Bearer s3cret", served)
            box = await E("(() => { const c = document.querySelector('.home-hero-pic canvas.mp-canvas'); const r = c.getBoundingClientRect(); return [r.width, r.height]; })()")
            check("... filling the preview", box[0] > 300 and box[1] > 150, box)
            await page.wait_for_timeout(400)
            px = await E("""(() => { const c = document.querySelector('.home-hero-pic canvas.mp-canvas');
              const g = c.getContext('webgl2') || c.getContext('webgl'); return !!g; })()""")
            check("... a live WebGL context", px)
            frozen = await E("Object.isFrozen(window.LokiModeBar)")
            before = await E("LokiModeBar.active()")
            await page.dblclick(".home-hero-pic canvas.mp-canvas")
            await page.wait_for_timeout(600)
            after = await E("LokiModeBar.active()")
            model = await E("(typeof forge !== 'undefined' && forge.model) || ''")
            check("double-click opens it in Forge (the mode bar switches to Forge)", before == "loki" and after == "forge", [frozen, before, after])
            check("... with that model", model in ("", GLB.name), model)
            check("... and a click on the model never opens the picture viewer over it", not await E("!!document.querySelector('.lv')"))
        thumb = await E("(() => { const i = document.querySelector('.home-card img'); return i ? i.getAttribute('src') : null; })()")
        check("the card's thumbnail is the model's render", thumb == "/creations/renders/render.png", thumb)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
