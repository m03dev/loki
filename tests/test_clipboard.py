"""Paste that always works in LOKI's window (the owner could not paste his API key anywhere).

    python tests/test_clipboard.py      (< 30 s; the browser part skips without Playwright)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


html = (UI / "index.html").read_text(encoding="utf-8")
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
app_py = (REPO / "app" / "loki_app.py").read_text(encoding="utf-8")
check("the window loads clipboard.js", "/ui/clipboard.js" in html)
check("the engine can read/write the computer's clipboard for the window", '"/clipboard/paste"' in bridge and '"/clipboard/copy"' in bridge)
check("text in the window can be selected (pywebview text_select)", "text_select=True" in app_py)
sys.path.insert(0, str(REPO / "engine"))
import clipboard_io  # noqa: E402
check("clipboard_io caps what it returns", clipboard_io.MAX <= 20000 and isinstance(clipboard_io.read(), str))

try:
    from playwright.async_api import async_playwright  # type: ignore
except ImportError:
    async_playwright = None
CHROME = "/opt/pw-browsers/chromium"

PAGE = """<!doctype html><html><body>
<input id="key" type="password"><textarea id="ta"></textarea>
<script>function api(p, b){ window.calls=(window.calls||[]).concat([p]);
  return Promise.resolve(p==="/clipboard/paste" ? {ok:true, text:"  nvapi-TESTKEY123\\n"} : {ok:true}); }</script>
<script src="/ui/clipboard.js"></script></body></html>"""


async def browser():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME)
        pg = await b.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            path = r.request.url.split("8897", 1)[1].split("?")[0]
            if path == "/":
                return await r.fulfill(body=PAGE, content_type="text/html")
            return await r.fulfill(path=str(UI / path[4:]))
        await pg.route("http://127.0.0.1:8897/**", route)
        await pg.goto("http://127.0.0.1:8897/")
        await pg.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'))")
        await pg.wait_for_timeout(200)
        check("a key field gets a Paste button", await pg.locator(".clip-paste").count() == 1)
        await pg.click(".clip-paste")
        await pg.wait_for_timeout(900)
        val = await pg.input_value("#key")
        check("Paste fills the key field through the engine when the browser cannot (trimmed, one line)",
              val == "nvapi-TESTKEY123", val)
        await pg.click("#ta", button="right")
        check("right-click on a text field shows Cut / Copy / Paste / Select all",
              await pg.locator(".clip-menu button").count() == 4)
        await pg.click(".clip-menu button:has-text('Paste')")
        await pg.wait_for_timeout(900)
        check("Paste from the menu inserts the clipboard text", "nvapi-TESTKEY123" in await pg.input_value("#ta"))
        await pg.fill("#ta", "")
        await pg.focus("#ta")
        await pg.keyboard.press("Control+v")    # headless has nothing to paste: the fallback must fill it
        await pg.wait_for_timeout(900)
        check("Ctrl+V that brings nothing falls back to the engine's clipboard", "nvapi-TESTKEY123" in await pg.input_value("#ta"),
              await pg.input_value("#ta"))
        check("no script errors", not errors, errors)
        await b.close()


if async_playwright is not None and os.path.exists(CHROME):
    asyncio.run(browser())
else:
    print("  (browser part skipped: no Playwright/Chromium)")
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
