"""Edit Mesh rows built from docs/FORGE_MAYA_PARITY.md (Add Divisions, Flip Triangle Edge, Symmetrize, Flip) run from
Forge's own command table in a real window: on a picked object (whole mesh, Maya), on picked components, one undo
step each, and listed in the Edit Mesh menu. Under a minute.

    python tests/test_forge_editmesh_ui.py
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
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Edit Mesh') || [0, []])[1])")
        check("Edit Mesh lists Add Divisions, Flip Triangle Edge, Symmetrize and Flip",
              all(x in menu for x in ("addDivisions", "flipTriangleEdge", "symmetrize", "flipMesh")), menu)
        await E("forgeProRun(forge.view, 'addDivisions')"); await page.wait_for_timeout(200)
        n = await E(F)
        check("Add Divisions on the picked object divides every face (6 -> 24)", n == 24, n)
        await E("forge.view.undo()"); await page.wait_for_timeout(150)
        check("... one undo step brings the 6 faces back", await E(F) == 6, await E(F))
        await E("(async () => { await forgeProRun(forge.view, 'face'); forge.view.selectItems('face', [0], 'set'); forgeProRun(forge.view, 'addDivisions'); })()")
        await page.wait_for_timeout(250)
        check("on one picked face: only that face divides (6 -> 9)", await E(F) == 9, await E(F))
        await E("(async () => { await forgeProRun(forge.view, 'objectMode'); forgeProRun(forge.view, 'symmetrize'); })()")
        await page.wait_for_timeout(250)
        st = await E("ForgePoly.meshStats(forge.view.poly)")
        check("Symmetrize on the object: still a closed mesh", st["border"] == 0 and st["nonManifoldEdges"] == 0, st)
        await E("forgeProRun(forge.view, 'flipMesh')"); await page.wait_for_timeout(200)
        check("Flip on the object: faces still face out", await E("ForgePoly.volume(forge.view.poly) > 0.5"))
        await E("(async () => { forgeTkRun('triangulate'); await new Promise((r) => setTimeout(r, 100)); await forgeProRun(forge.view, 'edge');"
                " const v = forge.view, T = ForgePoly.topology(v.poly); const e = T.edges.find((x) => x.faces.length === 2"
                " && x.faces.every((fi) => v.poly.f[fi].length === 3)); v.selectItems('edge', [T.edge(e.a, e.b)], 'set');"
                " window.__flipped = [e.a, e.b]; forgeProRun(v, 'flipTriangleEdge'); })()")
        await page.wait_for_timeout(300)
        gone = await E("(() => { const T = ForgePoly.topology(forge.view.poly), [a, b] = window.__flipped; return T.edge(a, b) === undefined; })()")
        check("Flip Triangle Edge on a picked triangle edge turns it", gone)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
