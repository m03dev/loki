"""Select > Convert Selection (Ctrl+F9 / F10 / F11, perimeters, shell), Similar and Shortest Edge Path in a real
Forge window (docs/FORGE_MODELING_FOUNDATION.md stage 4). Under a minute.

    python tests/test_forge_select_ui.py
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
        await E("(async () => { await forgeProRun(forge.view, 'face'); forge.view.selectItems('face', [0], 'set'); })()")
        await page.wait_for_timeout(100)
        await E("forge.view.canvas.focus && forge.view.canvas.focus()")
        S = "(() => { const v = forge.view, s = v.edit.sel; return [v.edit.mode, s.v.size, s.e.size, s.f.size]; })()"
        await page.keyboard.press("Control+F9"); await page.wait_for_timeout(120)
        check("Ctrl+F9: the face's 4 vertices, vertex mode", (await E(S))[:2] == ["vert", 4], await E(S))
        await page.keyboard.press("Control+F10"); await page.wait_for_timeout(120)
        st = await E(S)
        check("Ctrl+F10: the edges touching them, edge mode", st[0] == "edge" and st[2] >= 4, st)
        await page.keyboard.press("Control+F11"); await page.wait_for_timeout(120)
        st = await E(S)
        check("Ctrl+F11: the faces touching them, face mode", st[0] == "face" and st[3] >= 1, st)
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Select') || [0, []])[1])")
        check("Select lists Convert Selection, Similar, Shortest Edge Path",
              all(x in menu for x in ("convertToVerts", "convertToEdgePerimeter", "convertToShell", "selectSimilar", "shortestPath")), menu)
        await E("(async () => { forge.view.selectItems('face', [0], 'set'); forgeProRun(forge.view, 'selectSimilar'); })()")
        await page.wait_for_timeout(120)
        check("Similar: every face of the cube is the same quad", (await E(S))[3] == 6, await E(S))
        await E("(async () => { forge.view.selectItems('face', [0], 'set'); forgeProRun(forge.view, 'convertToEdgePerimeter'); })()")
        await page.wait_for_timeout(120)
        st = await E(S)
        check("To Edge Perimeter: the 4 edges round one face", st[0] == "edge" and st[2] == 4, st)
        await E("""(async () => { const v = forge.view; await forgeProRun(v, 'vertex');
          const P = v.poly.v, lo = P.findIndex((p) => p[0] < 0 && p[1] < 0.01 && p[2] < 0), hi = P.findIndex((p) => p[0] > 0 && p[1] > 0.99 && p[2] > 0);
          v.selectItems('vert', [lo, hi], 'set'); forgeProRun(v, 'shortestPath'); })()""")
        await page.wait_for_timeout(150)
        st = await E(S)
        check("Shortest Edge Path between opposite corners: 3 edges", st[0] == "edge" and st[2] == 3, st)
        # speed: a click on a big mesh repaints only the colours (drawOverlay kept the wire), not 100k edges
        sp = await E("""(async () => { const v = forge.view, P = ForgePoly; await forgeProRun(v, 'objectMode'); await forgeProRun(v, 'sphere');
          let m = v.poly; while (m.f.length < 40000) m = P.smooth(m); v.showPoly(m, true);
          await forgeProRun(v, 'face'); v.selectItems('face', [0], 'set');
          const t = performance.now(); for (let k = 0; k < 5; k++) v.selectItems('face', [k], 'add'); return [m.f.length, (performance.now() - t) / 5]; })()""")
        check("a click on a %d-face mesh takes under 25 ms (it was ~50: the whole wire was rebuilt)" % sp[0], sp[1] < 25, sp)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
