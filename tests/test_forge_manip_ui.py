"""Manipulator modes (docs/FORGE_MODELING_FOUNDATION.md stage 5): Component (Normal) axes put the handle's Y along the
picked faces' normal; "Each Piece About Its Own Centre" scales two faces each about its own middle; Tweak Mode drags a
vertex with one press - no click to pick it first - in one undo step. Under a minute.

    python tests/test_forge_manip_ui.py
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

        C = """(fi) => { const v = forge.view, f = v.poly.f[fi]; return [0, 1, 2].map((k) => +(f.reduce((a, i) => a + v.poly.v[i][k], 0) / f.length).toFixed(4)); }"""
        SIZE = """(fi) => { const v = forge.view, f = v.poly.f[fi], xs = f.map((i) => v.poly.v[i]); let d = 0; for (const a of xs) for (const b of xs) d = Math.max(d, Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])); return +d.toFixed(4); }"""
        DRAG = """(fn) => { const g = forge.view.gizmo, o = g.object; g.dispatchEvent({ type: 'mouseDown' }); (new Function('o', fn))(o); o.updateMatrix(); g.dispatchEvent({ type: 'objectChange' }); g.dispatchEvent({ type: 'mouseUp' }); }"""
        await E("forgeProRun(forge.view, 'cube')"); await page.wait_for_timeout(200)
        # which face looks along +X?
        side = await E("""(() => { const v = forge.view; return v.poly.f.findIndex((f) => f.every((i) => v.poly.v[i][0] > 0.49)); })()""")
        await E("(async () => { const v = forge.view; await forgeProRun(v, 'face'); v.selectItems('face', [%d], 'set'); await forgeProRun(v, 'move'); })()" % side)
        await page.wait_for_timeout(120)
        await E("forgeProRun(forge.view, 'componentAxes')")
        y = await E("(() => { const q = forge.view.gizmo.object.quaternion, T = forge.view.THREE; return new T.Vector3(0, 1, 0).applyQuaternion(q).toArray().map((x) => +x.toFixed(4)); })()")
        check("Component axes on the +X face: the handle's Y points along +X (the face's normal)", y == [1, 0, 0], y)
        check("... and the handle works in its own (local) space", await E("forge.view.gizmo.space") == "local")
        c0 = await E("(%s)(%d)" % (C, side))
        await E("(%s)('o.translateY(0.5)')" % DRAG)
        c1 = await E("(%s)(%d)" % (C, side))
        check("moving 0.5 along the handle's Y pushes the face out along its normal (x + 0.5)", abs(c1[0] - c0[0] - 0.5) < 1e-3 and abs(c1[1] - c0[1]) < 1e-3, (c0, c1))
        await E("forge.view.undo()")
        await E("forgeProRun(forge.view, 'worldAxes')")
        check("World axes: the handle is square to the world again", await E("[forge.view.gizmo.space, forge.view.gizmo.object.quaternion.w]") == ["world", 1])
        # ---- each piece about its own centre: the top and the bottom face, scaled to half
        await E("forgeProRun(forge.view, 'objectAxes')")
        tb = await E("""(() => { const v = forge.view, ys = v.poly.f.map((f) => f.reduce((a, i) => a + v.poly.v[i][1], 0) / f.length);
          return [ys.indexOf(Math.max(...ys)), ys.indexOf(Math.min(...ys))]; })()""")
        await E("(async () => { const v = forge.view; v.selectItems('face', %s, 'set'); await forgeProRun(v, 'scale'); })()" % tb)
        await page.wait_for_timeout(100)
        before = [await E("(%s)(%d)" % (C, f)) for f in tb]; s0 = await E("(%s)(%d)" % (SIZE, tb[0]))
        await E("forgeProRun(forge.view, 'pivotEach')")
        await E("(%s)('o.scale.set(0.5, 0.5, 0.5)')" % DRAG)
        after = [await E("(%s)(%d)" % (C, f)) for f in tb]; s1 = await E("(%s)(%d)" % (SIZE, tb[0]))
        check("Each Piece: both faces shrink to half, each about its own middle (their middles stay)", after == before and abs(s1 - s0 / 2) < 1e-3, (before, after, s0, s1))
        await E("forge.view.undo()")
        await E("forgeProRun(forge.view, 'pivotEach')")
        await E("(%s)('o.scale.set(0.5, 0.5, 0.5)')" % DRAG)
        joint = [await E("(%s)(%d)" % (C, f)) for f in tb]
        check("... off again: one pivot, so the two faces come together (their middles move)", abs(joint[0][1] - before[0][1]) > 0.2, (before, joint))
        await E("forge.view.undo()")
        # ---- tweak mode
        await E("(async () => { const v = forge.view; await forgeProRun(v, 'vertex'); v.selectItems('vert', [], 'set'); await forgeProRun(v, 'select'); })()")
        await E("forgeProRun(forge.view, 'tweakMode')")
        vid = await E("""(() => { const v = forge.view; let best = -1, by = -1; v.poly.v.forEach((p, i) => { const s = v.project(p); if (s && p[1] > 0.9 && s[1] > by) { by = s[1]; best = i; } }); return best; })()""")
        pt = await E("(() => { const v = forge.view, s = v.project(v.poly.v[%d]), r = v.canvas.getBoundingClientRect(); return [r.left + s[0], r.top + s[1]]; })()" % vid)
        allv = await E("forge.view.poly.v.map((p) => p.map((x) => +x.toFixed(4)))")
        await page.mouse.move(pt[0], pt[1]); await page.mouse.down()
        for k in range(1, 6):
            await page.mouse.move(pt[0] + k * 8, pt[1] - k * 6)
        await page.mouse.up(); await page.wait_for_timeout(100)
        now = await E("forge.view.poly.v.map((p) => p.map((x) => +x.toFixed(4)))")
        moved = [i for i in range(len(now)) if now[i] != allv[i]]
        hit = await E("[...forge.view.edit.sel.v]")
        check("Tweak Mode: one press and drag on a vertex moves THAT vertex (it was not picked), nothing else",
              len(moved) == 1 and hit == moved, (moved, hit, vid))
        await E("forge.view.undo()"); await page.wait_for_timeout(80)
        check("... one undo puts it back", await E("forge.view.poly.v.map((p) => p.map((x) => +x.toFixed(4)))") == allv)
        await E("forgeProRun(forge.view, 'tweakMode')")
        await page.mouse.move(pt[0], pt[1]); await page.mouse.down(); await page.mouse.move(pt[0] + 40, pt[1] - 30, steps=4); await page.mouse.up()
        check("Tweak Mode off: the same drag is a marquee - nothing moves", await E("forge.view.poly.v.map((p) => p.map((x) => +x.toFixed(4)))") == allv)
        # ---- discrete steps per tool (Maya's Discrete Move / Rotate / Scale)
        SN = "[forge.view.gizmo.translationSnap, forge.view.gizmo.rotationSnap && +(forge.view.gizmo.rotationSnap * 180 / Math.PI).toFixed(3), forge.view.gizmo.scaleSnap, forge.view.transform.rotationSnap && +(forge.view.transform.rotationSnap * 180 / Math.PI).toFixed(3)]"
        await E("forgeProRun(forge.view, 'discreteRotate')")
        check("Discrete Rotate: both handles (object and component) turn in 15° steps, move and scale stay smooth", await E(SN) == [None, 15, None, 15], await E(SN))
        await E("forge.view.canvas.focus && forge.view.canvas.focus()")
        await page.keyboard.down("j"); await page.wait_for_timeout(50)
        held = await E(SN)
        await page.keyboard.up("j"); await page.wait_for_timeout(50)
        check("holding j steps everything; letting go keeps only the always-on rotate", held[0] is not None and held[2] is not None and await E(SN) == [None, 15, None, 15], (held, await E(SN)))
        await E("forgeProRun(forge.view, 'discreteRotate')")
        check("Discrete Rotate off: smooth again", await E(SN) == [None, None, None, None], await E(SN))
        await E("ForgeSettings.set('discreteRotate', false)")
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Modify') || [0, []])[1])")
        check("Modify lists Component axes, Each Piece, Tweak Mode and the Discrete steps", all(x in menu for x in ("componentAxes", "pivotEach", "tweakMode", "discreteMove", "discreteRotate", "discreteScale")), menu)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
