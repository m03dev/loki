"""Thumbs up / down + the settings panel, end to end in LOKI's real window (index.html, home.js, image_viewer.js) against
the REAL engine routes (engine/image_api.py -> image_feedback.py, image_settings.py). Owner 2026-10-26: "give me a way to
tell them the images are bad with a thumbs down ... lots of settings to adjust what size and pixel we want".
The picture maker is a fake that writes a real PNG of the asked size.

    python tests/test_image_rate_ui.py        (LOKI_SHOTS=<folder> saves screenshots)
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
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright here\n\n0 passed, 0 failed")
    sys.exit(0)
from PIL import Image, ImageDraw  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="loki-rate-ui-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
WS = TMP / "ws"
(WS / "images").mkdir(parents=True)
NAMES = ["moss-golem_20261026-1900.png", "red-dragon_20261026-1910.png"]
for i, n in enumerate(NAMES):
    im = Image.new("RGB", (768, 1024), (200, 200, 205))
    ImageDraw.Draw(im).ellipse((180, 200, 590, 900), fill=(90 + 80 * i, 110, 70))
    im.save(WS / "images" / n)

import creations  # noqa: E402
import image_api  # noqa: E402
import image_feedback  # noqa: E402

creations.write_meta(WS, "images/" + NAMES[0], prompt="a small stocky moss golem", style="game-concept", seed=1234,
                     backend="nvidia", model="flux.2-klein-4b")
STATE = types.SimpleNamespace(agent=types.SimpleNamespace(WORKSPACE=str(WS)))
MADE = {}


def fake_maker(args, cwd):
    MADE.update(args)
    out = Path(cwd) / "images" / "moss-golem_20261026-1930.png"
    Image.new("RGB", (args["width"], args["height"]), (20, 120, 40)).save(out)
    return {"ok": True, "files": ["images/" + out.name], "backend": "mflux", "seed": args.get("seed")}


_remake = image_api.remake
image_api.remake = lambda ws, rel, settings, maker=None, thread=True: _remake(ws, rel, settings, maker=fake_maker, thread=False)
ITEMS = [{"kind": "made", "name": n.split("_")[0].replace("-", " "), "path_or_id": "images/" + n, "updated": time.time() - 10 * i,
          "thumb": "/creations/images/" + n, "video": None, "status": "", "detail": "picture",
          "open": {"mode": "files", "path": "images/" + n}} for i, n in enumerate(NAMES)]


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        errors = []
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
                q = {k: unquote(v) for k, v in (x.split("=", 1) for x in query.split("&") if "=" in x)}
                code, out = image_api.route(STATE, r.request.method, bare, q, body)   # the REAL engine route
                return await r.fulfill(status=code, json=json.loads(json.dumps(out, default=str)))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8894/**", route)
        await page.goto("http://127.0.0.1:8894/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("window.LokiHome && LokiHome.refresh && LokiHome.refresh()")
        await page.wait_for_selector(".home-hero-rate .home-rate-up", timeout=10000)
        check("Home: thumbs up / down right next to the picture", True)
        if SHOTS:
            await page.hover(".home-card")
            await page.wait_for_timeout(200)
            await page.screenshot(path=str(SHOTS / "0_home.png"))
        await page.click(".home-hero-rate .home-rate-up")
        await page.wait_for_function("document.querySelector('.home-rate-up').getAttribute('aria-pressed') === 'true'", timeout=5000)
        check("... thumbs up on Home is saved", image_feedback.rating_of(WS, "images/" + NAMES[0]) == 1)
        await page.click(".home-hero-rate .home-rate-down")
        await page.wait_for_selector(".lv-why:not([hidden]) .lv-chip", timeout=5000)
        check("thumbs down on Home opens the picture and asks why", True)
        await page.click(".lv-chip[data-reason='perspective']")
        await page.click(".lv-chip[data-reason='text']")
        await page.fill(".lv-why .lv-prompt", "the side view is a different creature")
        if SHOTS:
            await page.screenshot(path=str(SHOTS / "1_thumbs_down_why.png"))
        await page.click(".lv-why button[type=submit]")
        await page.wait_for_function("document.querySelector('.lv-down').getAttribute('aria-pressed') === 'true'", timeout=5000)
        row = image_feedback.ratings(WS).get("images/" + NAMES[0]) or {}
        check("... the reasons and the note are saved with the thumbs down", row.get("rating") == -1
              and row.get("reasons") == ["perspective", "text"] and "different creature" in row.get("note", ""), row)
        check("... and they shape the next prompts for images/", "no text" in image_feedback.hints(WS, "images"))
        # settings
        await page.keyboard.press("g")
        await page.wait_for_selector(".lv-settings:not([hidden]) .lv-set-row", timeout=5000)
        rows = await E("[...document.querySelectorAll('.lv-set-row')].map(r => r.dataset.key)")
        check("G opens the settings panel, drawn from the engine's list", {"aspect", "megapixels", "width", "height", "steps",
              "guidance", "sampler", "seed", "count", "strength", "style", "upscale", "pixel_size", "backend"} <= set(rows), rows)
        filled = await E("({p: document.querySelector('.lv-set-prompt').value, seed: document.querySelector('[data-key=seed] input').value})")
        check("... filled from the picture: its prompt and seed", filled == {"p": "a small stocky moss golem", "seed": "1234"}, filled)
        boxes = await E("(() => { const a = document.querySelector('.lv-stage').getBoundingClientRect(), b = document.querySelector('.lv-settings').getBoundingClientRect(); return [a.right, b.left, b.width / innerWidth]; })()")
        check("... in its own column beside the picture, never over it", boxes[0] <= boxes[1] + 1 and 0.18 < boxes[2] < 0.4, boxes)
        fit = await E("(() => { const i = document.querySelector('.lv-img').getBoundingClientRect(), f = document.querySelector('.lv-frame').getBoundingClientRect(); return [i.top >= f.top - 1, i.bottom <= f.bottom + 1, Math.round(i.width / i.height * 100)]; })()")
        check("a tall picture fits whole in the viewer (not cut off at the bottom)", fit[0] and fit[1] and fit[2] == 75, fit)
        await page.select_option("[data-key=backend] select", "nvidia")
        off = await E("document.querySelector('[data-key=sampler]').classList.contains('lv-set-off')")
        check("... a setting the chosen model ignores is greyed (nvidia ignores the sampler)", off)
        await page.select_option("[data-key=backend] select", "auto")
        await page.select_option("[data-key=aspect] select", "9:16")
        await page.fill("[data-key=megapixels] input", "0.5")
        await page.fill("[data-key=steps] input", "12")
        if SHOTS:
            await page.screenshot(path=str(SHOTS / "2_settings.png"))
        await page.click(".lv-set-form button[type=submit]")
        await page.wait_for_function("document.querySelector('.lv-count').textContent === '2 / 3' || document.querySelector('.lv-count').textContent === '3 / 3'", timeout=15000)
        check("Remake: a new picture with those settings (9:16, 0.5 MP, 12 steps, same prompt) shows next",
              MADE.get("steps") == 12 and MADE.get("width") < MADE.get("height") and MADE.get("prompt") == "a small stocky moss golem"
              and (WS / "images" / "moss-golem_20261026-1930.png").is_file(), MADE)
        if SHOTS:
            await page.screenshot(path=str(SHOTS / "3_remade.png"))
        # delete: two clicks, then gone (to trash/), and remembered as a thumbs down
        before = await E("document.querySelector('.lv-count').textContent")
        await page.click(".lv-del")
        armed = await E("document.querySelector('.lv-del').classList.contains('lv-armed')")
        check("one click on the bin only arms it (no pop-up)", armed and (WS / "images" / "moss-golem_20261026-1930.png").is_file())
        await page.click(".lv-del")
        await page.wait_for_function("document.querySelector('.lv-count').textContent !== %r" % before, timeout=5000)
        gone = not (WS / "images" / "moss-golem_20261026-1930.png").exists()
        check("the second click deletes it: gone from the folder and the viewer, kept in trash/",
              gone and (WS / "trash" / "images" / "moss-golem_20261026-1930.png").is_file(), list((WS / "trash").rglob("*")))
        check("... and LOKI learns it was not liked", "deleted" in (image_feedback.ratings(WS).get("images/moss-golem_20261026-1930.png") or {}).get("reasons", []))
        await page.keyboard.press("Escape")
        await page.keyboard.press("Escape")
        check("Esc closes the panel, then the viewer", await E("!document.querySelector('.lv')"))
        check("no script errors", not errors, errors)
        await browser.close()


asyncio.run(main())
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
