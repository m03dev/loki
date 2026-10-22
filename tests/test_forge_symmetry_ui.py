"""Forge's symmetry in headless Chromium: the sculpt/poly symmetry is an X/Y/Z bitmask (the core supports
1 X, 2 Y, 4 Z - the JS used to send only 1). The status line shows the axes, the right-click menu picks them,
the commands toggle them, and the mirror-set helper returns every non-empty subset. Under a minute.

    python tests/test_forge_symmetry_ui.py
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
            bare = r.request.url.split("8893", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8893/**", route)
        await page.goto("http://127.0.0.1:8893/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("localStorage.removeItem('loki-forge-hotkeys')")
        await page.evaluate("document.getElementById('open-forge').click()")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        await page.evaluate("forgeAddPrimitive('cube')")
        await page.wait_for_function("forge.view && forge.view.sm", timeout=10000)
        E = page.evaluate

        bit0 = await E("forge.view.brush.symBits")
        cmd = await E("(typeof FORGE_PRO_CMDS !== 'undefined') && !!(FORGE_PRO_CMDS.symX && FORGE_PRO_CMDS.symY && FORGE_PRO_CMDS.symZ && FORGE_PRO_CMDS.symOff)")
        check("symmetry is a bitmask by default and the X/Y/Z/Off commands exist", bit0 == 1 and cmd, [bit0, cmd])

        # the commands set the axes and the status line reads them back (X is on by default; Y toggles bit 2)
        async def run_sym(cmd):
            await E("forgeProRun(forge.view, '%s')" % cmd)
            await E("fmySync()")               # the status line refreshes on a 750 ms interval; update it now
            return await E("[forge.view.brush.symBits, document.getElementById('fmy-symlabel').textContent]")
        y = await run_sym("symY")
        xy = await run_sym("symX")
        off = await run_sym("symOff") + [await E("forge.view.brush.symmetry")]
        check("Symmetry Y -> X Y -> Off sets the bits and the status label follows",
              y == [3, "Symmetry: Object XY"] and xy == [2, "Symmetry: Object Y"] and off == [0, "Symmetry: Off", False], [y, xy, off])

        # the status button toggles off, then back to the last axes
        last = await E("forge.view.brush.symLast || 1")
        await page.click("#fmy-symm")
        on1 = await E("forge.view.brush.symBits")
        await page.click("#fmy-symm")
        on2 = await E("forge.view.brush.symBits")
        check("the status symmetry button toggles off, then restores the last axes", on1 == last and on2 == 0, [last, on1, on2])

        # right-click opens the axis menu (X / Y / Z / Off)
        await page.click("#fmy-symm")
        await E("forge.view.brush.symBits = 1")
        await page.click("#fmy-symm", button="right")
        await page.wait_for_timeout(80)
        menu = await E("[...document.querySelectorAll('.forge-pm-pop .forge-pm-item')].map((b) => b.textContent.trim())")
        check("right-click on the symmetry button opens the X / Y / Z / Off + radial menu",
              len(menu) >= 8 and menu[0].endswith("X (mirror across YZ)") and menu[3].endswith("Off") and any("Radial 4" in m for m in menu), menu)
        await page.keyboard.press("Escape")
        await E("document.querySelectorAll('.forge-pm-pop').forEach((x) => x.remove())")

        # the mirror-set helper: every non-empty subset of the active axes, with the right signs
        copies = await E("forge.view.symCopies([1, 2, 3], 7)")
        sig = sorted((tuple(c["sign"]), tuple(c["p"])) for c in copies)
        expect = sorted([((-1, 1, 1), (-1, 2, 3)), ((1, -1, 1), (1, -2, 3)), ((1, 1, -1), (1, 2, -3)),
                         ((-1, -1, 1), (-1, -2, 3)), ((-1, 1, -1), (-1, 2, -3)), ((1, -1, -1), (1, -2, -3)),
                         ((-1, -1, -1), (-1, -2, -3))])
        only_x = await E("forge.view.symCopies([1, 2, 3], 1)")
        check("symCopies(X Y Z) gives all 7 mirror instances with the right signs; X alone gives just the X mirror",
              sig == expect and len(only_x) == 1 and only_x[0]["sign"] == [-1, 1, 1], [sig[:2], only_x])

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
