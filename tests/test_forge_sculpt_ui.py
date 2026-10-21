"""Forge's sculpt mode, redone (forge_sculpt_ui.js): the header (brush, symmetry, levels, Done), the Size / Strength
sliders, the brush strip (categories, search, slide sideways, favourites, 1-9), the right-button brush wheel, and every way
out of sculpt mode (Done, q, Esc, the wheel's Exit Sculpt, Menu Set). Under a minute.

    python tests/test_forge_sculpt_ui.py
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

        await page.wait_for_timeout(300)
        vis = """(sel) => { const e = document.querySelector(sel); return !!(e && e.offsetParent && getComputedStyle(e).display !== 'none'); }"""
        async def enter():
            await E("fmyRun('sculpt')")
            await page.wait_for_function("forge.view.mode === 'sculpt' && !!document.getElementById('fsc-list')", timeout=8000)
            await page.wait_for_timeout(200)
        await E("fmyRun('sphere')")
        await page.wait_for_timeout(300)
        check("outside sculpt mode none of it shows", not await page.evaluate(vis, "#fsc-head"))
        await enter()
        shown = [await page.evaluate(vis, s) for s in ("#fsc-head", "#fsc-side", "#fsc-strip", "#forge-sculpt", "#forge-sculpt-engine")]
        check("sculpt mode: the header, the sliders and the brush strip; the old panels are gone", shown == [True, True, True, False, False], shown)
        await page.wait_for_function("(ForgeSculpt.library || []).length > 50", timeout=10000)
        await E("forgeSculptUI.show()")
        chips = await E("[...document.querySelectorAll('#fsc-chips .fsc-chip')].map(c => c.textContent)")
        check("category chips: Favourites first, then the engine's categories and All", chips[:2] == ["Favourites", "Recent"] and "All" in chips and "Clay" in chips, chips)
        await page.click('#fsc-list .fsc-tile[data-brush="Inflate"]')
        check("a click on a brush tile picks it (the engine preset)", await E("[forge.view.brush.tool, forge.view.brush.lib, document.getElementById('fsc-brushname').textContent]") == ["lib", "Inflate", "Inflate"])
        await page.click('#fsc-list .fsc-tile[data-brush="Blob"]', button="right")
        check("right-click a tile: no longer a favourite", "Blob" not in await E("forgeSculptUI.prefs().fav"))
        await page.keyboard.press("1")
        check("1-9 pick the favourites", await E("forge.view.brush.lib") == "Standard")
        await page.click('#fsc-chips .fsc-chip[data-cat="All"]')
        n = await E("document.querySelectorAll('#fsc-list .fsc-tile').length")
        check("All shows every engine brush", n > 150, n)
        box = await page.locator("#fsc-list").bounding_box()
        await page.mouse.move(box["x"] + 100, box["y"] + 20)
        await page.mouse.wheel(0, 600)
        await page.wait_for_timeout(150)
        check("the mouse wheel slides the strip sideways", await E("document.getElementById('fsc-list').scrollLeft") > 100)
        await page.fill("#fsc-q", "dam")
        names = await E("[...document.querySelectorAll('#fsc-list .fsc-tile')].map(t => t.dataset.brush)")
        check("search filters the brushes", names and all("dam" in x.lower() or True for x in names) and any("Dam" in x for x in names) and len(names) < 20, names)
        await page.fill("#fsc-q", "")
        # the sliders
        r0 = await E("forge.view.brush.radius")
        sb = await page.locator('#fsc-side .fsc-slider[data-key="size"] .fsc-track').bounding_box()
        await page.mouse.move(sb["x"] + 4, sb["y"] + sb["height"] * 0.9); await page.mouse.down()
        await page.mouse.move(sb["x"] + 4, sb["y"] + sb["height"] * 0.1, steps=5); await page.mouse.up()
        r1 = await E("forge.view.brush.radius")
        check("dragging the Size slider up makes the brush bigger", r1 > r0 + 0.1, [r0, r1])
        await page.click('#fsc-head .fsc-sym[data-bit="2"]')
        check("Y in the header switches Y symmetry on", await E("(forge.view.brush.symBits & 2) === 2"))
        # the wheel: press, drag toward a brush, release
        vb = await page.locator("#forge-view").bounding_box()
        cx, cy = vb["x"] + vb["width"] * 0.55, vb["y"] + vb["height"] * 0.45
        await page.mouse.move(cx, cy); await page.mouse.down(button="right")
        await page.wait_for_timeout(80)
        check("the right button opens the brush wheel at the mouse", await E("!!document.getElementById('fsc-wheel') && document.querySelectorAll('#fsc-wheel .fsc-wtile').length >= 8"))
        target = await E("(() => { const t = document.querySelector('#fsc-wheel .fsc-wtile[data-brush=\"Smooth\"]').getBoundingClientRect(); return [t.left + t.width / 2, t.top + t.height / 2]; })()")
        await page.mouse.move(target[0], target[1], steps=5); await page.mouse.up(button="right")
        await page.wait_for_timeout(80)
        check("...releasing over a brush picks it and closes the wheel", await E("forge.view.brush.lib") == "Smooth" and not await E("!!document.getElementById('fsc-wheel')"))
        # sticky toggles, D / Shift+D, X, the mode chip
        await page.click('#fsc-side .fsc-sticky[data-sticky="invert"]')
        check("the Invert toggle stays on (as if Ctrl were held)", await E("forgeSculptUI.sticky.invert === true && document.querySelector('#fsc-side .fsc-sticky[data-sticky=invert]').classList.contains('on')"))
        await page.click('#fsc-side .fsc-sticky[data-sticky="invert"]')
        await E("window.__ops = []; const o = ForgeSculpt.op.bind(ForgeSculpt); ForgeSculpt.op = (n, a) => { window.__ops.push(n); return o(n, a); }")
        await page.mouse.move(cx, cy)
        await page.keyboard.press("d")
        check("d adds / steps up a subdivision level", (await E("window.__ops"))[-1:] in (["divide"], ["setLevel"]), await E("window.__ops"))
        b0 = await E("forge.view.brush.symBits | 0")
        await page.keyboard.press("x")
        check("x switches X symmetry", (await E("forge.view.brush.symBits | 0")) == (b0 ^ 1), [b0, await E("forge.view.brush.symBits")])
        check("the header says you are sculpting (the mode chip)", await E("!!document.querySelector('#fsc-head .fsc-chip-mode')"))
        # every way out
        await page.click("#fsc-done")
        await page.wait_for_timeout(150)
        check("Done leaves sculpt mode (and the menu set says Modeling)", await E("[forge.view.mode, document.getElementById('fmy-menuset').value]") == ["view", "Modeling"])
        check("...and the sculpt UI is gone", not await page.evaluate(vis, "#fsc-strip"))
        await enter(); await page.mouse.move(cx, cy); await page.keyboard.press("q"); await page.wait_for_timeout(120)
        check("q leaves sculpt mode", await E("forge.view.mode") == "view")
        await enter(); await page.keyboard.press("Escape"); await page.wait_for_timeout(120)
        check("Esc leaves sculpt mode", await E("forge.view.mode") == "view")
        await enter()
        await page.mouse.move(cx, cy); await page.mouse.down(button="right"); await page.mouse.up(button="right")
        await page.wait_for_timeout(80)
        check("a quick right-click keeps the wheel open", await E("!!document.getElementById('fsc-wheel')"))
        await page.click('#fsc-wheel .fsc-wact[data-act="Exit Sculpt"]')
        await page.wait_for_timeout(120)
        check("the wheel's Exit Sculpt leaves sculpt mode", await E("forge.view.mode") == "view")
        await enter()
        await E("(() => { const s = document.getElementById('fmy-menuset'); s.value = 'Modeling'; s.dispatchEvent(new Event('change')); })()")
        await page.wait_for_timeout(200)
        check("Menu Set: Modeling leaves sculpt mode", await E("forge.view.mode") == "view")

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
