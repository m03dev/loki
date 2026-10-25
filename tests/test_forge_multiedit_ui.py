"""Forge: several objects' components at once (owner 2026-10-25: "I can't select a mesh's verts, Shift select another
mesh and see its verts and select them as well. That should be a thing, just like Maya").

  * component mode on one mesh, Shift + click ANOTHER mesh: it joins - its vertices show and can be picked with the
    first one's (one multi-edit session, forge_scene.js multiBegin);
  * F9 with two meshes picked in object mode: both at once;
  * a move across both, an extrude on one of them, then object mode (F8): each object gets its own pieces back in
    its own space, its transform untouched;
  * undo inside the session works; an undo that lands on the session while in object mode splits it again.
Under a minute.

    python tests/test_forge_multiedit_ui.py
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

# every mesh in world space: [verts, faces, the sum of its y (a moved vertex shows), its lowest x] - read quietly
WORLD = """(() => { const v = forge.view, t = v.tree.api, o = {}; v.undoQuiet(() => { const keep = t.selected();
  t.selectMany(t.list().filter((n) => n.kind === 'mesh').map((n) => n.id), 'set');
  for (const p of t.worldPolys()) o[p.name] = [p.poly.v.length, p.poly.f.length,
    Math.round(p.poly.v.reduce((s, q) => s + q[1], 0) * 100) / 100, Math.round(Math.min(...p.poly.v.map((q) => q[0])) * 100) / 100];
  t.selectMany(keep, 'set'); }); return o; })()"""


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
        wait = page.wait_for_timeout

        await E("""(async () => { const v = forge.view, t = v.tree.api; await forgeProRun(v, 'cube'); await forgeProRun(v, 'sphere');
          const s = t.list().find((n) => n.name === 'pSphere1'); t.setTransform(s.id, 'translate', 0, 1.5); })()""")
        await wait(200)
        w0 = await E(WORLD)
        # ---- component mode on the cube alone
        await E("(async () => { const t = forge.view.tree.api; t.select(t.list().find((n) => n.name === 'pCube1').id); await forgeProRun(forge.view, 'vertex'); })()")
        await wait(200)
        one = await E("[forge.view.mode, forge.view.poly.v.length, forge.view.tree.api.multiIds().length]")
        check("F9 on one cube: its 8 vertices, no session", one == ["poly", 8, 0], one)
        # ---- Shift + click the sphere: it joins
        at = await E("""(() => { const v = forge.view, t = v.tree.api, THREE = v.THREE, b = t.worldBox([t.list().find((n) => n.name === 'pSphere1').id]);
          const c = b.getCenter(new THREE.Vector3()).project(v.camera), r = v.canvas.getBoundingClientRect();
          return [r.left + (c.x + 1) / 2 * r.width, r.top + (1 - c.y) / 2 * r.height]; })()""")
        await page.keyboard.down("Shift")
        await page.mouse.click(at[0], at[1])
        await page.keyboard.up("Shift")
        await wait(250)
        two = await E("[forge.view.mode, forge.view.poly.v.length, forge.view.tree.api.multiIds().length, forge.view.tree.api.selected().length]")
        check("Shift + click the sphere in component mode: it joins - 8 + 266 vertices to pick from, both objects selected",
              two == ["poly", 274, 2, 2], two)
        say = await E("(document.getElementById('forge-status') || {}).textContent || ''")
        check("... and Forge says so", "added" in say or "together" in say, say)
        # ---- pick a vertex of each, move them up together (the cage edit a tool makes)
        picked = await E("""(() => { const v = forge.view; v.setSelMode('vert'); v.selectItems('vert', [0, 8], 'set'); const n = v.selectedVerts().length;
          const m = ForgePoly.clone(v.poly); for (const i of v.selectedVerts()) m.v[i][1] += 1; v.showPoly(m, true); return n; })()""")
        check("a vertex of each object picked at once", picked == 2, picked)
        # ---- extrude a face of the sphere part
        await E("""(async () => { const v = forge.view; v.setSelMode('face'); v.selectItems('face', [6 + 30], 'set'); await forgeProRun(v, 'extrude'); })()""")
        await wait(200)
        nf = await E("forge.view.poly.f.length")
        await E("forgeProRun(forge.view, 'objectMode')"); await wait(250)
        w1 = await E(WORLD)
        st = await E("[forge.view.mode, forge.view.tree.api.multiIds().length]")
        check("F8 splits it back: object mode, no session", st == ["view", 0], st)
        check("the cube keeps its 8 vertices / 6 faces, its moved corner up by 1", w1.get("pCube1", [0])[:2] == [8, 6] and abs(w1["pCube1"][2] - w0["pCube1"][2] - 1) < 1e-6, [w0, w1])
        check("the sphere got the extrude (more faces) and stays where it was (x from 1)", w1.get("pSphere1", [0, 0])[1] > w0["pSphere1"][1] and w1["pSphere1"][3] >= 0.99 and nf > 294, [w0, w1, nf])
        # ---- undo: back into the joined state while in object mode -> split again at once
        await E("forge.view.undo()"); await wait(200)
        u = await E("[forge.view.mode, forge.view.tree.api.multiIds().length, forge.view.tree.api.worldPolys().length]")
        check("undo in object mode never leaves the objects joined", u[:2] == ["view", 0] and u[2] == 2, u)
        # ---- F9 with both picked: both at once
        await E("(async () => { const t = forge.view.tree.api; t.selectMany(t.list().filter((n) => n.kind === 'mesh').map((n) => n.id), 'set'); await forgeProRun(forge.view, 'vertex'); })()")
        await wait(250)
        both = await E("[forge.view.mode, forge.view.tree.api.multiIds().length, forge.view.poly.v.length]")
        check("two meshes picked + F9: both objects' components at once", both[0] == "poly" and both[1] == 2 and both[2] > 270, both)
        await E("(() => { const v = forge.view; v.selectItems('vert', [1], 'set'); })()")
        await E("(async () => { await forgeProRun(forge.view, 'objectMode'); })()"); await wait(200)
        w2 = await E(WORLD)
        check("... and back: both intact", sorted(w2) == ["pCube1", "pSphere1"] and w2["pCube1"][0] == 8, w2)
        # ---- a sculpt or another object ends a session too
        await E("(async () => { const t = forge.view.tree.api; t.selectMany(t.list().filter((n) => n.kind === 'mesh').map((n) => n.id), 'set'); await forgeProRun(forge.view, 'vertex'); await forgeProRun(forge.view, 'sculpt'); })()")
        await wait(300)
        sc = await E("[forge.view.mode, forge.view.tree.api.multiIds().length, forge.view.tree.api.worldPolys().length]")
        check("going to Sculpt from a session splits it first", sc[1] == 0 and sc[2] == 2, sc)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    import time
    t0 = time.time()
    asyncio.run(main())
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
        sys.exit(1)
