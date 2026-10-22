"""Forge's menus, your way (forge_menus.js): tear-off menus that float and come back after a reload, the Quick Menu
(Alt+Q) and right-click to add to it, Menu Settings (size / opacity / where the wheel and hotbox open), editing a
marking menu, moving the wheel by its middle. Under a minute.

    python tests/test_forge_menus_ui.py
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
        await page.evaluate("document.getElementById('open-forge').click()")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        await page.wait_for_function("forge.view && forge.view.pro && forge.view.brush", timeout=10000)
        E = page.evaluate

        await page.wait_for_timeout(300)
        # tear-off: the File menu's dashed line
        await page.click('#fmy-menubar .fmy-mb[data-menu="File"]')
        await page.wait_for_timeout(60)
        check("a menu bar menu has a tear-off line", await E("!!document.querySelector('.fmy-drop .fmenu-tear')"))
        await page.click(".fmy-drop .fmenu-tear")
        await page.wait_for_timeout(80)
        check("tearing it off leaves File as a floating menu", await E("!!document.querySelector('.fmenu-torn[aria-label=\"File\"] .fmy-ditem')"))
        hd = await page.locator('.fmenu-torn[aria-label="File"] .fmenu-torn-head').bounding_box()
        await page.mouse.move(hd["x"] + 20, hd["y"] + 8); await page.mouse.down()
        await page.mouse.move(hd["x"] + 260, hd["y"] + 180, steps=6); await page.mouse.up()
        await page.wait_for_timeout(60)
        pos = await E("JSON.parse(localStorage.getItem('loki-forge-tearoffs'))[0]")
        check("it moves by its title and keeps its place (in %)", pos and pos["x"] > 0 and pos["y"] > 0 and pos["title"] == "File", pos)

        # the Quick Menu
        await E("fmyRun('quickMenu')")
        await page.wait_for_timeout(60)
        q = await E("(() => { const h = document.getElementById('forge-pro-marking'); return [!h.hidden, h.querySelectorAll('.forge-pro-wedge').length, h.classList.contains('fmenu-quick')]; })()")
        check("Alt+Q's command opens the Quick Menu: eight favourites around the mouse", q == [True, 8, True], q)
        await page.mouse.click(20, 400)
        await page.wait_for_timeout(60)
        check("a click elsewhere puts it away", await E("document.getElementById('forge-pro-marking').hidden"))
        check("Alt+Q is in the hotkey set", await E("forgeHotkeys && forgeHotkeys.keysFor('quickMenu').includes('alt+q')"), await E("forgeHotkeys.keysFor('quickMenu')"))
        await page.click('#fmy-menubar .fmy-mb[data-menu="Mesh"]')
        await page.wait_for_timeout(60)
        await page.click('.fmy-drop .fmy-ditem[data-pro-id="triangulate"]', button="right")
        await page.wait_for_timeout(60)
        check("right-click a menu item: it joins the Quick Menu", await E("JSON.stringify(forgeMenusQuick()).includes('triangulate')"))

        # Menu Settings: size, where they open, a marking menu edited
        await E("forgeMenusSettings()")
        check("Menu Settings opens", await E("!!document.getElementById('fmenu-settings')"))
        await E("(() => { const s = document.getElementById('fmenu-scale'); s.value = '1.5'; s.dispatchEvent(new Event('input')); })()")
        await E("forgeProWheelOpen(forge.view, [650, 450])")
        await page.wait_for_timeout(60)
        check("the size applies to the wheel", await E("document.getElementById('forge-pro-wheel').style.scale") == "1.5")
        hub = await page.locator("#forge-pro-wheel .forge-wheel-hub").bounding_box()
        await page.mouse.move(hub["x"] + hub["width"] / 2, hub["y"] + hub["height"] / 2); await page.mouse.down()
        await page.mouse.move(hub["x"] + 140, hub["y"] - 60, steps=6); await page.mouse.up()
        await page.wait_for_timeout(60)
        p = await E("forgeMenusPrefs()")
        check("drag the wheel's middle: it opens there from now on", p["open"] == "fixed" and p["wheelAt"] and 0 < p["wheelAt"][0] < 1, p)
        await E("forgeProWheelClose(); forgeProWheelOpen(forge.view, [100, 100])")
        await page.wait_for_timeout(40)
        left = await E("parseFloat(document.getElementById('forge-pro-wheel').style.left)")
        check("...even when opened somewhere else", left > 300, left)
        await E("forgeProWheelClose()")
        await E("(() => { const s = document.getElementById('fmenu-pick'); s.value = 'Create'; s.dispatchEvent(new Event('change')); })()")
        await E("(() => { const s = document.querySelector('#fmenu-settings select[data-slot=\"S\"]'); s.value = 'sphere'; s.dispatchEvent(new Event('change')); })()")
        ring = await E("forgeProMenu(forge.view, { shift: true }).ring.S")
        check("edit the Create marking menu: south is now Sphere", ring == "sphere", ring)
        await E("document.getElementById('fmenu-reset1').click()")
        check("Reset this menu puts it back", await E("forgeProMenu(forge.view, { shift: true }).ring.S") == "cube")

        # the hotbox menus tear off too
        await E("forgeProHotboxOpen(forge.view, [650, 450])")
        await page.wait_for_timeout(60)
        check("every hotbox menu has a tear-off line", await E("document.querySelectorAll('#forge-pro-hotbox .forge-pro-list .fmenu-tear').length >= 10"))
        await E("forgeProHotboxHide()")

        await page.reload()
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("document.getElementById('open-forge').click()")
        await page.wait_for_function("forge.view && forge.view.pro", timeout=10000)
        await page.wait_for_timeout(900)
        check("after a reload the torn-off File menu is back", await E("!!document.querySelector('.fmenu-torn[aria-label=\"File\"]')"))

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
