"""Forge's Options panel (the cog): which interface elements show, every tool value adjustable inside its own
min/max, rows you can hide, named presets, and a reset. Under a minute.

    python tests/test_forge_options_ui.py
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


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright here\n\n0 passed, 0 failed")
    sys.exit(0)


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            print("SKIP: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1300, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

        async def route(r):
            bare = r.request.url.split("8892", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8892/**", route)
        await page.goto("http://127.0.0.1:8892/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.click("#open-forge")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        await page.wait_for_function("forge.view && forge.view.pro && forge.view.brush", timeout=10000)
        E = page.evaluate

        check("the cog button is on the stage", await E("!!document.getElementById('forge-options-btn')"))
        await page.click("#forge-options-btn")
        await page.wait_for_timeout(60)
        check("it opens the Options panel", await E("!document.getElementById('forge-options').hidden"))

        # interface visibility: the chrome's own UI-element list, driven from the panel
        rowsel = "#forge-opt-ui-toolbox"
        check("the Interface section lists the UI elements", await E("!!document.querySelector('" + rowsel + "')"))
        was = await E("!!forge.view && fmyUi().toolbox")
        await page.click(rowsel)
        await page.wait_for_timeout(80)
        hid = await E("document.getElementById('fmy-toolbox') ? document.getElementById('fmy-toolbox').hidden : null")
        check("unchecking one hides that element", hid is True and was is True, [was, hid])
        await page.click(rowsel)
        await page.wait_for_timeout(80)
        check("re-checking brings it back", await E("document.getElementById('fmy-toolbox').hidden") is False)

        # a numeric option respects its own limits
        lim = await E("""() => { const n = document.getElementById('forge-opt-gridStep');
          return n ? { min: +n.min, max: +n.max, step: +n.step, val: +n.value } : null; }""")
        check("an option carries its min / max / step limits", lim and lim["min"] == 0.05 and lim["max"] == 2 and lim["step"] == 0.05, lim)
        await E("() => { const n = document.getElementById('forge-opt-gridStep'); n.value = '99'; n.dispatchEvent(new Event('change')); }")
        await page.wait_for_timeout(60)
        clamped = await E("[forge.view.pro.gridStep, document.getElementById('forge-opt-gridStep').value]")
        check("a value past the max is clamped to it", clamped[0] == 2 and clamped[1] == "2", clamped)
        await E("() => { const n = document.getElementById('forge-opt-gridStep'); n.value = '0.5'; n.dispatchEvent(new Event('change')); }")
        await page.wait_for_timeout(60)
        check("the live view takes the value", await E("forge.view.pro.gridStep") == 0.5)
        check("the value is remembered", await E("forge.view.forgeOptions.state().opts.gridStep") == 0.5)

        # presets
        await E("() => { const n = document.getElementById('forge-opt-name'); n.value = 'Wide grid'; document.getElementById('forge-opt-save').click(); }")
        await page.wait_for_timeout(80)
        check("saving a preset stores the set", await E("!!forge.view.forgeOptions.state().presets['Wide grid']"))
        await E("() => { const n = document.getElementById('forge-opt-gridStep'); n.value = '0.1'; n.dispatchEvent(new Event('change')); }")
        await page.wait_for_timeout(60)
        await E("forge.view.forgeOptions.preset('Wide grid')")
        await page.wait_for_timeout(80)
        check("applying a preset restores it", await E("forge.view.pro.gridStep") == 0.5)
        check("the preset list offers it", await E("[...document.getElementById('forge-opt-presets').options].some(o => o.value === 'Wide grid')"))

        # hiding a row, and bringing hidden rows back
        await E("() => { const r = document.querySelector('[data-opt=\\'gridStep\\'] .forge-opt-x'); r.click(); }")
        await page.wait_for_timeout(80)
        check("a row can be hidden from the panel", await E("!document.querySelector('[data-opt=\\'gridStep\\']')"))
        await E("document.getElementById('forge-opt-showhidden').click()")
        await page.wait_for_timeout(80)
        check("Show hidden brings the rows back", await E("!!document.querySelector('[data-opt=\\'gridStep\\']')"))

        # reset
        await E("document.getElementById('forge-opt-reset').click()")
        await page.wait_for_timeout(80)
        check("Reset returns the defaults", await E("forge.view.pro.gridStep") == 0.25)

        # a real reload: the panel was left on 0.3, so a fresh page comes back on 0.3
        await E("() => { const n = document.getElementById('forge-opt-gridStep'); n.value = '0.3'; n.dispatchEvent(new Event('change')); }")
        await page.wait_for_timeout(60)
        await page.reload()
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.click("#open-forge")
        await page.wait_for_function("forge.view && forge.view.pro", timeout=10000)
        await page.wait_for_timeout(120)
        check("the panel's values survive a reload", await E("forge.view.pro.gridStep") == 0.3, await E("forge.view.pro.gridStep"))

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
