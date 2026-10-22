"""Forge's sculpt mode, part 2: the Sculpting workspace, masking (paint, invert, hide, clear), a brush's own hotkey and
reordering favourites. Under a minute.

    python tests/test_forge_sculpt_more_ui.py
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
        vis = """(sel) => { const e = document.querySelector(sel); return !!(e && e.offsetParent && getComputedStyle(e).display !== 'none'); }"""
        async def enter():
            await E("fmyRun('sculpt')")
            await page.wait_for_function("forge.view.mode === 'sculpt' && !!document.getElementById('fsc-list')", timeout=8000)
            await page.wait_for_timeout(200)
        await E("fmyRun('sphere')")
        await page.wait_for_timeout(300)
        await E("fmyRun('sphere')")
        await page.wait_for_timeout(300)
        await enter()
        await page.wait_for_function("(ForgeSculpt.library || []).length > 50", timeout=10000)
        await E("forgeSculptUI.show()")
        vb = await page.locator("#forge-view").bounding_box()
        cx, cy = vb["x"] + vb["width"] * 0.55, vb["y"] + vb["height"] * 0.45
        # reorder: Move left in the menu
        await page.click('#fsc-chips .fsc-chip[data-cat="Favourites"]')
        await page.click('#fsc-list .fsc-tile[data-brush="Inflate"]', button="right")
        before = await E("forgeSculptUI.prefs().fav.indexOf('Inflate')")
        await page.click('#fsc-tmenu button:has-text("Move left")')
        check("Move left moves a favourite one place", await E("forgeSculptUI.prefs().fav.indexOf('Inflate')") == before - 1)
        # a brush's own hotkey
        await page.click('#fsc-list .fsc-tile[data-brush="Pinch"]', button="right")
        await page.click('#fsc-tmenu button:has-text("Set a hotkey")')
        await page.keyboard.press("Shift+KeyP")
        check("Set a hotkey: Shift+P is Pinch's now (shown on the tile)", await E("forgeSculptUI.prefs().keys['shift+p']") == "Pinch" and await E("!!document.querySelector('#fsc-list .fsc-tile[data-brush=\"Pinch\"] .fsc-hk')"))
        await E("forgeSculptUI.pick('Clay')")
        await page.mouse.move(700, 400)
        await page.keyboard.press("Shift+KeyP")
        check("...pressing it picks Pinch", await E("forge.view.brush.lib") == "Pinch")
        # masking: Mask on, a stroke paints it (shown dark), invert, hide, clear
        await page.click('#fsc-side .fsc-sticky[data-sticky="mask"]')
        await page.mouse.move(cx - 40, cy); await page.mouse.down()
        await page.mouse.move(cx + 40, cy + 10, steps=10); await page.mouse.up()
        await page.wait_for_timeout(500)
        mk = await E("[ForgeMask.any, !!(forge.view.internals.mesh.getObjectByName('forge-mask')), ForgeMask.w ? Array.from(ForgeMask.w).filter(x => x > 0.5).length : 0]")
        check("Mask on + a stroke paints a mask, drawn as a dark overlay", mk[0] is True and mk[1] is True and mk[2] > 0, mk)
        await page.click('#fsc-side .fsc-sticky[data-sticky="mask"]')
        n0 = mk[2]
        await page.keyboard.press("Control+Shift+KeyI")
        await page.wait_for_timeout(400)
        n1 = await E("Array.from(ForgeMask.w).filter(x => x > 0.5).length")
        check("Ctrl+Shift+I inverts the mask", n1 > n0, [n0, n1])
        t0 = await E("forge.view.internals.mesh.geometry.index.count")
        await page.keyboard.press("h")
        t1 = await E("forge.view.internals.mesh.geometry.index.count")
        check("h hides the masked part (fewer triangles drawn)", t1 < t0 and await E("ForgeMask.hidden"), [t0, t1])
        await page.keyboard.press("h")
        check("...h again shows everything", await E("forge.view.internals.mesh.geometry.index.count") == t0)
        await page.keyboard.press("Shift+KeyU")
        await page.wait_for_timeout(400)
        check("Shift+U clears the mask", await E("Array.from(ForgeMask.w).filter(x => x > 0.01).length") == 0)
        # Workspace: Sculpting (owner 23:53: "sculpting should be in its own workspace just like animation")
        await E("ForgeUVEditor.setWorkspace('sculpt')")
        await page.wait_for_timeout(300)
        ws = await E("[forge.view.mode, document.getElementById('forge-workspace').value, document.getElementById('forge-outcol').hidden, document.getElementById('forge-chancol').hidden]")
        check("Workspace: Sculpting enters sculpt mode with the viewport to itself (Outliner / Channel Box away)", ws == ["sculpt", "sculpt", True, True], ws)
        await page.click("#fsc-done")
        await page.wait_for_timeout(300)
        ws = await E("[forge.view.mode, document.getElementById('forge-workspace').value, document.getElementById('forge-outcol').hidden, document.getElementById('forge-chancol').hidden]")
        check("...Done goes back to Modeling with the Outliner and Channel Box", ws == ["view", "model", False, False], ws)
        await E("fmyRun('sculpt')")
        await page.wait_for_timeout(300)
        check("entering sculpt mode another way switches the workspace to Sculpting", await E("document.getElementById('forge-workspace').value") == "sculpt")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
