"""Pivot system, part two (docs/FORGE_MODELING_FOUNDATION.md stage 3b): D in COMPONENT mode places the components'
own pivot (the handle moves, the components do not); rotate then turns about it; a new selection or Reset Pivot drops
it. Modify > Bake Pivot makes the pivot the object's origin (nothing moves); Freeze keeps the quad cage. Under a minute.

    python tests/test_forge_pivot2_ui.py
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

        T = "forge.view.tree.api"
        PIV = "(() => { const t = forge.view.tree.api; return t.pivotWorld(t.selected()[0]).toArray().map((x) => +x.toFixed(4)); })()"
        BOX = "(() => { const t = forge.view.tree.api, b = t.worldBox(t.selected()); return [b.min.toArray(), b.max.toArray()].flat().map((x) => +x.toFixed(4)); })()"
        await E("forgeProRun(forge.view, 'cube')"); await page.wait_for_timeout(200)
        await E(T + ".setTransform(" + T + ".selected()[0], 'translate', 0, 2)")
        await E("forgeProRun(forge.view, 'centerPivot')")      # local (0, 0.5, 0): off the cube's own origin (its base)
        box0 = await E(BOX)
        await E("forgeProRun(forge.view, 'bakePivot')")
        piv_local = await E("forge.view.tree.api.pivotOf(forge.view.tree.api.selected()[0]).toArray()")
        check("Bake Pivot: the pivot is the origin now (local 0, 0, 0), still at (2, 0.5, 0) in the world, nothing moved",
              piv_local == [0, 0, 0] and await E(PIV) == [2, 0.5, 0] and await E(BOX) == box0, [piv_local, await E(PIV), await E(BOX), box0])
        check("... the cage keeps its 6 quads", await E("forge.view.poly ? forge.view.poly.f.map((f) => f.length).join() : 'none'") == "4,4,4,4,4,4")
        await E("forge.view.undo()"); await page.wait_for_timeout(100)
        check("one undo: the pivot is back off the origin, the object where it was", await E("forge.view.tree.api.pivotOf(forge.view.tree.api.selected()[0]).toArray().some((x) => Math.abs(x) > 1e-6)") and await E(BOX) == box0)
        await E(T + ".setTransform(" + T + ".selected()[0], 'rotate', 1, 45)")
        b45 = await E(BOX)
        await E("forgeProRun(forge.view, 'freeze')")
        check("Freeze on a turned cube: nothing moves, and the cage is still 6 quads (it used to fall back to triangles)",
              await E(BOX) == b45 and await E("forge.view.poly ? forge.view.poly.f.map((f) => f.length).join() : 'none'") == "4,4,4,4,4,4", (await E(BOX), b45))
        check("... and it stays: in the construction history, or the primitive's INPUTS let go (they would rebuild the old cube)",
              await E("forgeModel.hist ? forgeModel.hist.ops.slice(-1)[0].kind === 'xform' : !forgeModel.prim"))
        # ---- D in component mode
        await E("(async () => { const v = forge.view; await forgeProRun(v, 'face'); v.selectItems('face', [0], 'set'); await forgeProRun(v, 'rotate'); })()")
        await page.wait_for_timeout(150)
        before = await E("forge.view.poly.v.map((p) => p.map((x) => +x.toFixed(4)))")
        mid0 = await E("forge.view.gizmo.object.position.toArray().map((x) => +x.toFixed(4))")
        await E("forge.view.canvas.focus && forge.view.canvas.focus()")
        await page.keyboard.down("d"); await page.wait_for_timeout(80)
        st = await E("[forge.view.edit.pivotEdit, forge.view.gizmo.mode, !!forge.view.gizmo.object]")
        check("D held in face mode: pivot edit, the handle is a move handle", st == [True, "translate", True], st)
        # drag the handle: as the manipulator does it (mouseDown, the object moves, objectChange, mouseUp)
        await E("""(() => { const g = forge.view.gizmo, o = g.object; g.dispatchEvent({ type: 'mouseDown' });
          o.position.set(o.position.x + 0.7, o.position.y, o.position.z); o.updateMatrix(); g.dispatchEvent({ type: 'objectChange' }); g.dispatchEvent({ type: 'mouseUp' }); })()""")
        same = await E("forge.view.poly.v.map((p) => p.map((x) => +x.toFixed(4)))") == before
        await page.keyboard.up("d"); await page.wait_for_timeout(80)
        cp = await E("forge.view.customPivot() && forge.view.customPivot().map((x) => +x.toFixed(4))")
        check("moving the pivot moves no vertex; D up keeps it as the custom pivot", same and cp is not None and abs(cp[0] - mid0[0] - 0.7) < 1e-3, (same, cp, mid0))
        check("D up: back to the Rotate handle, sitting on the custom pivot",
              await E("[forge.view.edit.pivotEdit, forge.view.gizmo.mode, forge.view.gizmo.object.position.toArray().map((x) => +x.toFixed(4))]") == [False, "rotate", cp])
        # rotate 90 degrees about Y: the face's middle moves (it turns about the off-centre pivot), the pivot stays
        await E("""(() => { const g = forge.view.gizmo, o = g.object; g.dispatchEvent({ type: 'mouseDown' });
          o.rotation.set(0, Math.PI / 2, 0); o.updateMatrix(); g.dispatchEvent({ type: 'objectChange' }); g.dispatchEvent({ type: 'mouseUp' }); })()""")
        await page.wait_for_timeout(80)
        r = await E("""(() => { const v = forge.view, f = v.poly.f[0], c = [0, 1, 2].map((k) => f.reduce((a, i) => a + v.poly.v[i][k], 0) / f.length); return c.map((x) => +x.toFixed(4)); })()""")
        moved = abs(r[0] - mid0[0]) + abs(r[2] - mid0[2])
        d0 = ((mid0[0] - cp[0]) ** 2 + (mid0[2] - cp[2]) ** 2) ** 0.5
        d1 = ((r[0] - cp[0]) ** 2 + (r[2] - cp[2]) ** 2) ** 0.5
        check("Rotate turns the face about the custom pivot (its middle swings round it, same distance)", moved > 0.5 and abs(d0 - d1) < 1e-3, (r, mid0, cp))
        await E("forge.view.selectItems('face', [1], 'set')"); await page.wait_for_timeout(50)
        check("a new selection drops the custom pivot (Maya)", await E("forge.view.customPivot()") is None)
        # Reset Pivot in component mode
        await page.keyboard.down("d")
        await E("""(() => { const g = forge.view.gizmo, o = g.object; g.dispatchEvent({ type: 'mouseDown' });
          o.position.y += 2; o.updateMatrix(); g.dispatchEvent({ type: 'objectChange' }); g.dispatchEvent({ type: 'mouseUp' }); })()""")
        await page.keyboard.up("d")
        had = await E("!!forge.view.customPivot()")
        msg = await E("forgeProRun(forge.view, 'resetPivot')")
        check("Reset Pivot in component mode drops the custom pivot (the object's pivot is untouched)", had and await E("forge.view.customPivot()") is None, (had, msg))
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Modify') || [0, []])[1])")
        check("Modify lists Bake Pivot", "bakePivot" in menu, menu)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
