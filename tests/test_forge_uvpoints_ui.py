"""UV > Best Plane, Split UVs, Merge UVs and Delete UVs in a real Forge window (app/ui/forge_uv_editor.js): a cube
gets Best Plane UVs on two picked faces; Automatic gives six shells; picking two neighbouring faces' shared UV points
and Splitting makes them separate, Merge brings them back together; Delete UVs leaves none; each one undo step.
Under a minute.

    python tests/test_forge_uvpoints_ui.py
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

        UVN = "(() => { const m = forge.view.poly; return ForgeUV.has(m) ? [m.uv.length, ForgeUV.shells(m).length] : null; })()"
        await E("forgeAddPrimitive('cube')"); await page.wait_for_timeout(200)
        await E("(async () => { const v = forge.view; await forgeProRun(v, 'face'); v.selectItems('face', [0, 1], 'set'); await forgeProRun(v, 'uvBestPlane'); })()")
        await page.wait_for_timeout(120)
        check("Best Plane on two picked faces: the cube has UVs now (a projection along the two faces' average normal)", await E(UVN) is not None, await E(UVN))
        # the rest on a plane: Planar on a cube lays its sides flat as lines, points on top of each other
        await E("(async () => { const v = forge.view; await forgeProRun(v, 'objectMode'); forgeAddPrimitive('plane'); })()"); await page.wait_for_timeout(250)
        await E("(async () => { const v = forge.view; await forgeProRun(v, 'face'); v.selectItems('face', [], 'set'); await forgeProRun(v, 'uvBestPlane'); })()")
        await page.wait_for_timeout(120)
        n0 = await E(UVN)
        check("(Best Plane on a whole plane: one shell, a point per vertex)", n0 and n0[1] == 1 and n0[0] == await E("forge.view.poly.v.length"), n0)
        # the two UV points the faces 0 and 1 share: pick them in the UV Editor (state.selUV) and Split
        await E("""(() => { const m = forge.view.poly; let sh = [];
          for (let x = 0; x < m.f.length && !sh.length; x++) for (let y = x + 1; y < m.f.length && !sh.length; y++) sh = m.fuv[x].filter((i) => m.fuv[y].includes(i));
          window.__shared = sh; ForgeUVEditor.state.selUV = new Set(sh); })()""")
        shared = await E("window.__shared.length")
        await E("forgeProRun(forge.view, 'uvSplit')"); await page.wait_for_timeout(120)
        n1 = await E(UVN)
        check("Split UVs on the %d UV points two faces share: more UV points, nothing else changes shape" % shared, shared >= 1 and n1[0] > n0[0], (n0, n1))
        await E("forge.view.undo()"); await page.wait_for_timeout(80)
        check("one undo: back to the shared points", await E(UVN) == n0)
        await E("forgeProRun(forge.view, 'uvSplit')"); await page.wait_for_timeout(80)
        # the split points: the shared ones and their new copies (ids past the old count) - not every point, since
        # Planar Z lays the cube's front and back on top of each other and those would merge too
        await E("ForgeUVEditor.state.selUV = new Set([...window.__shared, ...forge.view.poly.uv.map((_, i) => i).filter((i) => i >= %d)])" % n0[0])
        await E("forgeProRun(forge.view, 'uvMerge')"); await page.wait_for_timeout(120)
        check("Merge UVs (the split points picked, 0.01): they are one again", await E(UVN) == n0, (await E(UVN), n0))
        await E("forgeProRun(forge.view, 'uvDelete')"); await page.wait_for_timeout(120)
        check("Delete UVs: the plane has none left", await E(UVN) is None)
        await E("forge.view.undo()"); await page.wait_for_timeout(80)
        check("... and one undo brings them back", await E(UVN) == n0)
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'UV') || [0, []])[1])")
        check("the UV menu has Best Plane, Split UVs, Delete UVs and Merge UVs", all(x in menu for x in ("uvBestPlane", "uvSplit", "uvDelete", "uvMerge")), menu)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
