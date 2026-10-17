"""The window really starts: load LOKI's index.html in a headless browser against a fake engine
and check there is no script error, no missing file, and app.js reaches "ready" (the check that
would have caught the Mac's white window before it shipped).

Skips (passes) where Playwright + a Chromium are not installed - CI and Claude's workspace have them.

    python tests/test_ui_smoke.py
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
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:600],)))


def chromium_path() -> str:
    for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium"):
        if p and os.path.exists(p):
            return p
    return ""


try:
    from playwright.async_api import async_playwright  # type: ignore
except ImportError:
    async_playwright = None

if async_playwright is None or not chromium_path():
    print("SKIP: no Playwright/Chromium here")
    print("\n0 passed, 0 failed")
    sys.exit(0)

FAKE = {
    "/health": {"ok": True, "service": "loki", "mode": "smart", "provider": "groq", "model": "x", "providers": "", "route": [],
                "usage": {}, "first_layer": {}, "update": {"commit": "abc", "label": "v0.16"}, "ui_errors": []},
    "/world": {"ok": True, "agents": [], "machines": [], "self": {"name": "test"}, "creations": {"count": 0, "latest": []}},
}


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chromium_path(),
                                          args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = await browser.new_page(viewport={"width": 1240, "height": 820})
        errors, missing, ui_posts = [], [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

        async def route(r):
            path = r.request.url.split("8898", 1)[1].split("?")[0].split("#")[0]
            if path == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if path.startswith("/ui/"):
                f = UI / path[4:]
                if f.is_file():
                    return await r.fulfill(path=str(f))
                if path in ("/ui/error", "/ui/ready"):
                    ui_posts.append((path, r.request.post_data))
                    return await r.fulfill(json={"ok": True})
                missing.append(path)
                return await r.fulfill(status=404, body="missing")
            return await r.fulfill(json=FAKE.get(path, {"ok": True}))

        await page.route("http://127.0.0.1:8898/**", route)
        await page.goto("http://127.0.0.1:8898/#token=t")
        try:
            await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
            ready = True
        except Exception:  # noqa: BLE001
            ready = False
        await page.wait_for_timeout(1500)
        check("every file the window loads exists", not missing, missing)
        check("no script errors while the window starts", not errors, errors[:5])
        check("app.js reaches ready (no white window)", ready, errors[:5])
        check("the window told the engine it is ready (an update on trial is kept)", any(p == "/ui/ready" for p, _ in ui_posts), ui_posts)
        check("no rescue screen", not await page.query_selector("#boot-rescue"))
        await page.click("#open-settings")
        await page.wait_for_timeout(500)
        check("Settings opens", await page.is_visible("#settings"))
        check("still no script errors after opening Settings", not errors, errors[:5])
        await browser.close()


asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
