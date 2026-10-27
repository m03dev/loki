"""Home on a vertical / squeezed screen (owner 2026-10-26: "i cant see the home ui right because im using the screen
vertically and they disappeared ... make it so the ui logic is smarter and fits better even when squished").
LOKI's real window (index.html, chat_view.js flow + ui_tidy.js preview size) in headless Chromium, engine stubbed.
Checks, per window shape: Home is never hidden in a chat; a tall or narrow window stacks Home over the chat using the
FULL width (the old rules left an empty 320px column); a wide window stays side by side; Layout > Arrange overrides;
the preview is not stuck at its floor. Skips cleanly without a browser.

    python tests/test_home_flow_ui.py
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
from PIL import Image  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="loki-flow-"))
Image.new("RGB", (64, 40), (200, 60, 40)).save(TMP / "p.png")
ITEMS = [{"kind": "image", "name": "pic %d" % i, "path_or_id": "images/p.png", "updated": time.time() - i * 3600,
          "thumb": "/creations/images/p.png", "status": "", "detail": "", "open": {"mode": "image", "path": "p.png"}}
         for i in range(16)]
GEOM = """(() => { const b = s => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect();
  return {x: r.x, y: r.y, w: r.width, h: r.height, shown: getComputedStyle(e).display !== 'none' && r.width > 0}; };
  return {split: b('#loki-split'), hub: b('#home-hub'), chat: b('#chat-col'), pic: b('.home-hero-pic'),
          flow: (document.getElementById('loki-split') || {}).dataset.flow || ''}; })()"""


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP: no Chromium (%s)" % str(exc)[:100])
            return

        async def open_page(w, h):
            page = await browser.new_page(viewport={"width": w, "height": h})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))

            async def route(r):
                bare = r.request.url.split("8895", 1)[1].split("#")[0].split("?")[0]
                if bare == "/":
                    return await r.fulfill(path=str(UI / "index.html"))
                if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                    ct = "text/javascript" if bare.endswith(".js") else None
                    return await r.fulfill(path=str(UI / bare[4:]), **({"content_type": ct} if ct else {}))
                if bare == "/home/projects":
                    return await r.fulfill(json={"ok": True, "items": ITEMS, "errors": {}, "counts": {"image": 16}})
                if bare.startswith("/creations/images/"):
                    return await r.fulfill(path=str(TMP / "p.png"), content_type="image/png")
                return await r.fulfill(json={"ok": True})
            await page.route("http://127.0.0.1:8895/**", route)
            await page.goto("http://127.0.0.1:8895/#token=t")
            await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
            await page.evaluate("LokiHome.refresh && LokiHome.refresh()")
            await page.wait_for_selector(".home-card", timeout=8000)
            await page.wait_for_timeout(500)
            return page, errors

        async def to_chat(page):
            await page.evaluate("document.getElementById('main').classList.remove('home')")
            await page.wait_for_timeout(250)

        # a vertical 1080x1920 screen: stacked, Home on top, the chat under it, both full width
        page, errors = await open_page(1080, 1920)
        g = await page.evaluate(GEOM)
        check("portrait 1080x1920: Home and the chat are stacked", g["flow"] == "stack", g["flow"])
        check("... both use the split's full width", abs(g["hub"]["w"] - g["split"]["w"]) < 2 and abs(g["chat"]["w"] - g["split"]["w"]) < 2, g)
        check("... Home above the chat", g["hub"]["y"] < g["chat"]["y"], g)
        check("... the preview is big, not stuck at its floor", g["pic"] and g["pic"]["h"] > 250, g["pic"])
        home_h = g["hub"]["h"]
        await to_chat(page)
        g = await page.evaluate(GEOM)
        check("in a chat Home stays on screen (it used to disappear)", g["hub"]["shown"] and g["hub"]["h"] > 150, g["hub"])
        check("... with a smaller share, so the chat gets more room", g["hub"]["h"] < home_h and g["chat"]["h"] > g["hub"]["h"], g)
        check("no script errors (portrait)", not errors, errors[:3])
        await page.close()

        # a narrow 720x1280 window: no empty phantom column
        page, errors = await open_page(720, 1280)
        await to_chat(page)
        g = await page.evaluate(GEOM)
        check("narrow 720x1280 in a chat: Home is shown", g["hub"]["shown"], g["hub"])
        check("... and nothing is squeezed into part of the window (no empty column)",
              g["chat"]["w"] > 700 and abs(g["hub"]["w"] - g["chat"]["w"]) < 2, g)
        await page.close()

        # a wide landscape window: side by side; Arrange > Stacked overrides, Auto brings it back
        page, errors = await open_page(1600, 900)
        g = await page.evaluate(GEOM)
        check("landscape 1600x900: side by side", g["flow"] == "row" and g["hub"]["x"] < g["chat"]["x"] and abs(g["hub"]["y"] - g["chat"]["y"]) < 2, g)
        check("... the preview is not stuck at its floor", g["pic"] and g["pic"]["h"] > 200, g["pic"])
        await page.evaluate("LokiChatView.setFlow('stack')")
        await page.wait_for_timeout(200)
        g = await page.evaluate(GEOM)
        check("Layout > Arrange > Stacked stacks a wide window too", g["flow"] == "stack" and g["hub"]["y"] < g["chat"]["y"], g)
        await page.evaluate("LokiChatView.setFlow('auto')")
        await page.wait_for_timeout(200)
        check("... and Auto brings side by side back", (await page.evaluate(GEOM))["flow"] == "row")
        check("no script errors (landscape)", not errors, errors[:3])
        await page.close()
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 55))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
