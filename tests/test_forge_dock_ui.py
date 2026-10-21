"""Forge's layout system (forge_dock.js): every panel moves (drag its title to an edge to dock it, anywhere else to
float it), floats, closes and comes back; top / bottom docks for vertical monitors; the bars over the viewport move by
their grip; the Channel Box column's parts fold and resize; named layouts; no page scroll bar. Under a minute.

    python tests/test_forge_dock_ui.py
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

        async def drag(sel, x, y):
            box = await page.locator(sel).first.bounding_box()
            await page.mouse.move(box["x"] + 12, box["y"] + box["height"] / 2)
            await page.mouse.down()
            await page.mouse.move(box["x"] + 40, box["y"] + 40, steps=4)
            await page.mouse.move(x, y, steps=8)
            await page.mouse.up()
            await page.wait_for_timeout(120)

        check("the page itself never scrolls (no bar down the right side)",
              await E("document.scrollingElement.scrollHeight <= document.scrollingElement.clientHeight"),
              await E("[document.scrollingElement.scrollHeight, document.scrollingElement.clientHeight]"))
        check("the Outliner's own title is its drag handle (no second title bar)",
              await E("!!document.querySelector('#forge-outcol .forge-out-title.fdock-handle') && !document.querySelector('#forge-outcol > .fdock-head')"))
        check("every docked panel has a float and a close button",
              await E("['forge-outcol','forge-chancol'].every(id => document.querySelector('#' + id + ' > .fdock-btns .fdock-b-close') && document.querySelector('#' + id + ' > .fdock-btns .fdock-b-float'))"))

        body = await page.locator("#forge .forge-body").bounding_box()
        # drag the Outliner onto the right edge
        await drag("#forge-outcol .forge-out-title", body["x"] + body["width"] - 6, body["y"] + body["height"] / 2)
        r = await E("""(() => { const o = document.getElementById('forge-outcol').getBoundingClientRect(), s = document.getElementById('forge-stage').getBoundingClientRect();
          return { dock: document.getElementById('forge-outcol').dataset.dock, right: o.left >= s.right - 2 }; })()""")
        check("dropped on the right edge: the Outliner docks right of the viewport", r == {"dock": "right", "right": True}, r)
        # ... and to the bottom
        await drag("#forge-outcol .forge-out-title", body["x"] + body["width"] / 2, body["y"] + body["height"] - 4)
        r = await E("""(() => { const o = document.getElementById('forge-outcol').getBoundingClientRect(), s = document.getElementById('forge-stage').getBoundingClientRect();
          return { dock: document.getElementById('forge-outcol').dataset.dock, below: o.top >= s.bottom - 1, bar: !document.getElementById('fdock-row-bottom').hidden }; })()""")
        check("dropped on the bottom edge: it docks below the viewport, with a bar to resize the row", r == {"dock": "bottom", "below": True, "bar": True}, r)
        h0 = await E("document.getElementById('forge-outcol').getBoundingClientRect().height")
        bar = await page.locator("#fdock-row-bottom").bounding_box()
        await page.mouse.move(bar["x"] + 200, bar["y"] + 3); await page.mouse.down()
        await page.mouse.move(bar["x"] + 200, bar["y"] - 80, steps=6); await page.mouse.up()
        await page.wait_for_timeout(100)
        h1 = await E("document.getElementById('forge-outcol').getBoundingClientRect().height")
        check("dragging the row bar makes the bottom panels taller", h1 > h0 + 40, [h0, h1])
        # anywhere in the middle: it floats there
        await drag("#forge-outcol .forge-out-title", body["x"] + body["width"] * 0.5, body["y"] + body["height"] * 0.3)
        r = await E("(() => { const p = document.getElementById('forge-outcol'); return [p.dataset.dock, getComputedStyle(p).position, p.style.left.endsWith('%')]; })()")
        check("dropped in the middle: it floats, placed in %", r == ["float", "absolute", True], r)
        await page.dblclick("#forge-outcol .forge-out-title")
        await page.wait_for_timeout(120)
        check("double-click a floating title: back where it was docked", await E("document.getElementById('forge-outcol').dataset.dock") == "bottom")
        # the float button and the close button
        await page.click("#forge-chancol > .fdock-btns .fdock-b-float")
        await page.wait_for_timeout(100)
        check("the float button floats the Channel Box", await E("document.getElementById('forge-chancol').dataset.dock") == "float")
        await page.click("#forge-chancol > .fdock-btns .fdock-b-float")
        await page.wait_for_timeout(100)
        check("again: it docks back on the right", await E("document.getElementById('forge-chancol').dataset.dock") == "right")
        await page.click("#forge-chancol > .fdock-btns .fdock-b-close")
        await page.wait_for_timeout(100)
        check("the close button hides the Channel Box", await E("document.getElementById('forge-chancol').hidden") is True)
        await E("forgeProPanel('channel', true)")
        await page.wait_for_timeout(100)
        check("the Windows menu brings it back", await E("document.getElementById('forge-chancol').hidden") is False)
        # right-click a title: the dock menu
        await page.click("#forge-chancol .forge-panel-tab", button="right")
        await page.wait_for_timeout(80)
        items = await E("[...document.querySelectorAll('#fdock-menu .fmy-dlabel')].map(e => e.textContent)")
        check("right-click a title: Dock left / right / above / below / Float / Close / Reset", all(x in items for x in ["Dock left", "Dock right", "Dock below the viewport", "Float", "Close", "Reset the layout"]), items)
        await page.keyboard.press("Escape"); await page.mouse.click(5, 5)

        # the Channel Box column's parts
        await page.click("#forge-history .fdock-fold")
        await page.wait_for_timeout(60)
        check("INPUTS folds to its title", await E("document.getElementById('forge-history').classList.contains('fdock-folded')"))
        await page.click("#forge-history .fdock-fold")
        check("the column has a resize edge above INPUTS too", await E("!!document.getElementById('forge-split-hist')"))

        # the bars over the viewport (the sculpt brush bar here; Modeling shows none, the Time Slider is in Animation)
        await E("fmyRun('cube')"); await page.wait_for_timeout(300)
        await E("fmyRun('sculpt')")
        await page.wait_for_timeout(1200)
        g = await E("!!document.querySelector('#forge-sculpt > .fdock-bargrip')")
        check("a bar over the viewport has a grip", g)
        gb = await page.locator("#forge-sculpt > .fdock-bargrip").bounding_box()
        t0 = await E("document.getElementById('forge-sculpt').getBoundingClientRect().left")
        await page.mouse.move(gb["x"] + 3, gb["y"] + 5); await page.mouse.down()
        await page.mouse.move(gb["x"] + 220, gb["y"] + 60, steps=6); await page.mouse.up()
        await page.wait_for_timeout(80)
        t1 = await E("document.getElementById('forge-sculpt').getBoundingClientRect().left")
        saved = await E("JSON.parse(localStorage.getItem('loki-forge-dock-bars') || '{}')['forge-sculpt']")
        check("dragging the grip moves the bar and keeps it (as a fraction of the viewport)", t1 > t0 + 150 and saved and saved["dx"] > 0, [t0, t1, saved])
        await E("typeof forgeMode === 'function' && forgeMode()")

        # named layouts survive a reload, the vertical window has its own layout
        await E("forgeDockSaveAs('mine')")
        await E("forgeDockReset()")
        check("Reset puts the Outliner back on the left", await E("document.getElementById('forge-outcol').dataset.dock") == "left")
        await E("forgeDockUse('mine')")
        check("loading the saved layout puts it back below", await E("document.getElementById('forge-outcol').dataset.dock") == "bottom")
        await page.set_viewport_size({"width": 900, "height": 1500})
        await page.wait_for_timeout(900)
        r = await E("[document.getElementById('forge .forge-body') ? 1 : 0, document.querySelector('#forge .forge-body').classList.contains('fdock-portrait'), document.getElementById('forge-chancol').dataset.dock]")
        check("a tall window gets its own layout: the Channel Box under the viewport", r[1] is True and r[2] == "bottom", r)
        await page.set_viewport_size({"width": 1300, "height": 860})
        await page.wait_for_timeout(900)
        check("back to a wide window: its own layout again", await E("document.getElementById('forge-chancol').dataset.dock") == "right")

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
