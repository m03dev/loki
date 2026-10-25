"""Mesh Display > Conform, Set to Face and Average in a real Forge window: a cube with two faces turned inside out
(Reverse) faces out again after Conform, one undo step; Set to Face makes every edge hard, Average every edge soft.
Under a minute.

    python tests/test_forge_normals2_ui.py
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

        VOL = "+ForgePoly.volume(forge.view.poly).toFixed(4)"
        await E("forgeProRun(forge.view, 'cube')"); await page.wait_for_timeout(200)
        v0 = await E(VOL)
        await E("(async () => { const v = forge.view; await forgeProRun(v, 'face'); v.selectItems('face', [1, 4], 'set'); await forgeProRun(v, 'reverse'); })()")
        await page.wait_for_timeout(100)
        bad = await E(VOL)
        check("(Reverse on two faces: the cube is no longer consistent)", bad != v0, (v0, bad))
        await E("(async () => { const v = forge.view; v.selectItems('face', [], 'set'); await forgeProRun(v, 'conformNormals'); })()")
        await page.wait_for_timeout(100)
        check("Conform with nothing picked: the whole cube faces out again", await E(VOL) == v0, (await E(VOL), v0))
        check("... and it is in the construction history (polyNormal)", await E("(() => { const o = forgeModel.hist && forgeModel.hist.ops.slice(-1)[0]; return o ? o.op || o.kind : null; })()") == "conformNormals")
        await E("forge.view.undo()"); await page.wait_for_timeout(80)
        check("one undo: the two faces are turned in again", await E(VOL) == bad)
        HARD = "(() => { const m = forge.view.poly, T = ForgePoly.topology(m), h = m.hard instanceof Map ? m.hard : new Map(); return [T.edges.length, T.edges.filter((e) => h.get(ForgePoly.edgeKey(e.a, e.b))).length]; })()"
        await E("(async () => { const v = forge.view; await forgeProRun(v, 'objectMode'); await forgeProRun(v, 'sphere'); await forgeProRun(v, 'face'); v.selectItems('face', [], 'set'); await forgeProRun(v, 'setToFace'); })()")
        await page.wait_for_timeout(100)
        h = await E(HARD)
        check("Set to Face (nothing picked): every edge of the sphere is hard - faceted", h[0] > 0 and h[1] == h[0], h)
        await E("forgeProRun(forge.view, 'averageNormals')"); await page.wait_for_timeout(100)
        h = await E(HARD)
        check("Average: every edge soft - smooth", h[1] == 0, h)
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Mesh Display') || [0, []])[1])")
        check("Mesh Display has Average, Conform and Set to Face in Maya's order", [x for x in menu if x in ("averageNormals", "conformNormals", "setToFace")] == ["averageNormals", "conformNormals", "setToFace"], menu)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
