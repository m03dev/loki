"""Pivot placement (docs/FORGE_MODELING_FOUNDATION.md stage 3): Modify > Pivot > Pivot to Bottom / to World Origin /
to Selection. The pivot moves, the object never does, one undo step each. Under a minute.

    python tests/test_forge_pivot_ui.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
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
        await page.wait_for_function("forge.view && forge.view.pro && forge.view.brush", timeout=15000)
        E = page.evaluate
        F = "forge.view.tree.api.worldPolys ? (() => { const t = forge.view.tree.api; return forge.view.poly ? forge.view.poly.f.length : -1; })() : -1"

        await E("forgeProRun(forge.view, 'cube')"); await page.wait_for_timeout(200)
        T = "forge.view.tree.api"
        await E(T + ".setTransform(" + T + ".selected()[0], 'translate', 0, 2)")
        box0 = await E("(() => { const t = forge.view.tree.api, b = t.worldBox(t.selected()); return [b.min.toArray(), b.max.toArray()].flat().map((x) => +x.toFixed(4)); })()")
        PIV = "(() => { const t = forge.view.tree.api; return t.pivotWorld(t.selected()[0]).toArray().map((x) => +x.toFixed(4)); })()"
        BOX = "(() => { const t = forge.view.tree.api, b = t.worldBox(t.selected()); return [b.min.toArray(), b.max.toArray()].flat().map((x) => +x.toFixed(4)); })()"
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Modify') || [0, []])[1])")
        check("Modify lists Pivot to Bottom / World Origin / Selection", all(x in menu for x in ("pivotBottom", "pivotOrigin", "pivotToSelection")), menu)
        await E("forgeProRun(forge.view, 'pivotBottom')")
        check("Pivot to Bottom: the bottom middle (2, 0, 0), the object stays", await E(PIV) == [2, 0, 0] and await E(BOX) == box0, [await E(PIV), await E(BOX)])
        await E("forgeProRun(forge.view, 'pivotOrigin')")
        check("Pivot to World Origin: (0, 0, 0), the object stays", await E(PIV) == [0, 0, 0] and await E(BOX) == box0, [await E(PIV), await E(BOX)])
        await E("forge.view.undo()")
        check("one undo puts the pivot back on the bottom", await E(PIV) == [2, 0, 0], await E(PIV))
        await E("""(async () => { const v = forge.view; await forgeProRun(v, 'vertex');
          const top = v.poly.v.map((p, i) => i).filter((i) => v.poly.v[i][1] > 0.99); v.selectItems('vert', top, 'set');
          forgeProRun(v, 'pivotToSelection'); await forgeProRun(v, 'objectMode'); })()""")
        await page.wait_for_timeout(200)
        check("Pivot to Selection: the middle of the picked top vertices (2, 1, 0), the object stays",
              await E(PIV) == [2, 1, 0] and await E(BOX) == box0, [await E(PIV), await E(BOX)])
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
