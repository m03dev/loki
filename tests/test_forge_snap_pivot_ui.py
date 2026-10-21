"""Forge: snapping (hold x = grid, c = edge, v = point) with a real handle drag, and pivot edit mode (the handle
moves the pivot, not the object). Under a minute.

    python tests/test_forge_snap_pivot_ui.py
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
T = "forge.view.tree.api"


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright here\n\n0 passed, 0 failed")
    sys.exit(0)

# the world position of the selected object's origin
POS = "%s.active().grp.getWorldPosition(new forge.view.THREE.Vector3()).toArray()" % T
# is a world point one of `name`'s vertices / on one of its edges?
ON_TARGET = """
(a) => { const p = a[0], name = a[1], T = forge.view.THREE, v = forge.view;
  const node = v.tree.api.list().find((n) => n.name === name);
  if (!node) return 'no target';
  const eps = 1e-3, P = new T.Vector3();
  const verts = [];
  node.grp.traverse((o) => { if (!o.isMesh || !o.geometry || !o.geometry.attributes.position) return;
    o.updateMatrixWorld();
    const pos = o.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) verts.push(new T.Vector3().fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld));
    if (o.geometry.index) { const idx = o.geometry.index, src = verts.slice(); verts.length = 0;
      for (let i = 0; i < idx.count; i++) verts.push(src[idx.getX(i)]); } });
  for (const q of verts) if (q.distanceTo(new T.Vector3(p[0], p[1], p[2])) < eps) return 'vertex';
  const seg = new T.Line3(), q = new T.Vector3(p[0], p[1], p[2]);
  for (let i = 0; i + 2 < verts.length; i += 3) for (const [x, y] of [[0, 1], [1, 2], [2, 0]]) {
    const A = verts[i + x], B = verts[i + y];
    if (!A || !B) continue;
    seg.set(A, B);
    if (seg.closestPointToPoint(q, true, new T.Vector3()).distanceTo(q) < eps) return 'edge'; }
  return 'off'; }"""


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
            bare = r.request.url.split("8893", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8893/**", route)
        await page.goto("http://127.0.0.1:8893/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.click("#open-forge")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        await page.evaluate("forgeAddPrimitive('cube'); forgeModelMode(false)")
        await page.wait_for_function("forge.view && forge.view.sm && forge.view.tree && forge.view.tree.api", timeout=10000)
        await page.evaluate("forge.view.frame()")
        canvas = await page.eval_on_selector("#forge-view", "c => { const r = c.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
        cx, cy, cw, ch = canvas
        E = page.evaluate

        await E("%s.select(%s.list().find((n) => n.kind === 'mesh').id)" % (T, T))
        await E("forge.view.pro.gridStep = 0.25; forge.view.pro.snap = { grid: false, edge: false, point: false }")

        # the snap function itself, all three kinds
        grid = await E("(forge.view.pro.snap = { grid: true, edge: false, point: false }, forgeProSnapPoint(forge.view, new forge.view.THREE.Vector3(0.62, 1.31, -0.44), [], 'XYZ').toArray())")
        check("the grid snap puts a point on a multiple of the grid step",
              all(abs(v / 0.25 - round(v / 0.25)) < 1e-6 for v in grid) and abs(grid[0] - 0.62) < 0.13, grid)

        # a second object to snap onto
        await E("forge.view.tree.api.setTransform(null, 'translate', 0, 0)")
        await E("forgeProRun(forge.view, 'duplicate')")
        await E("forge.view.tree.api.setTransform(null, 'translate', 0, 2)")
        target = await E("%s.active().name" % T)
        await E("forgeProRun(forge.view, 'frameAll')")     # both objects on screen, so the edge ray can hit
        await page.wait_for_timeout(120)
        tpt = await E("""() => { const v = forge.view, T = v.THREE; v.camera.updateMatrixWorld();
          const n = v.tree.api.list().find((x) => x.name === %r); n.grp.updateMatrixWorld(true);
          const s = n.grp.getWorldPosition(new T.Vector3()).project(v.camera), r = v.canvas.getBoundingClientRect();
          return [r.left + (s.x + 1) / 2 * r.width, r.top + (1 - s.y) / 2 * r.height]; }""" % target)
        await E("forge.view.pro.mouse = [%f, %f]; forge.view.pro.snap = { grid: false, edge: false, point: true }" % (tpt[0], tpt[1]))
        onscreen = await E("(() => { const r = forge.view.canvas.getBoundingClientRect(), m = forge.view.pro.mouse; return m[0] >= r.left && m[0] <= r.right && m[1] >= r.top && m[1] <= r.bottom; })()")
        v = await E("(() => { const p = forgeProSnapPoint(forge.view, new forge.view.THREE.Vector3(0.35, 0.2, 0.1), [], 'XYZ'); return p ? p.toArray() : null; })()")
        where_v = await E(ON_TARGET, [v, target])
        check("the point snap puts a point on a vertex of another object", onscreen and where_v == "vertex", [onscreen, v, where_v, target])

        await E("forge.view.pro.snap = { grid: false, edge: true, point: false }")
        c = await E("(() => { const p = forgeProSnapPoint(forge.view, new forge.view.THREE.Vector3(0.35, 0.2, 0.1), [], 'XYZ'); return p ? p.toArray() : null; })()")
        where_c = await E(ON_TARGET, [c, target])
        check("the edge snap puts a point on an edge of another object", c is not None and where_c in ("edge", "vertex"), [c, where_c, onscreen])

        # the manipulator applies it: the same objectChange path a real handle drag runs, with the grid snap on
        pos = await E("""() => { const v = forge.view, T = v.THREE, tc = v.transform, n = v.tree.api.active();
          v.pro.snap = { grid: true, edge: false, point: false };
          tc.attach(n.grp); tc.axis = "X";
          n.grp.position.set(0.62, 0.1, -0.3); n.grp.updateMatrixWorld(true);
          tc.dispatchEvent({ type: "objectChange" });
          v.tree.build();
          return n.grp.position.toArray(); }""")
        snap_ok = abs(pos[0] / 0.25 - round(pos[0] / 0.25)) < 1e-6 and abs(pos[0] - 0.62) > 1e-6
        check("with the grid snap on, the manipulator's own change snaps the object onto the grid", snap_ok, pos)

        # pivot edit: the handle moves the pivot, the object stays put
        mode_now = await E("(async () => { if (forge.view.mode === 'poly') await forgeModelMode(false); return forge.view.mode; })()")
        await page.wait_for_timeout(80)
        await E("%s.select(%s.list().find((n) => n.kind === 'mesh').id)" % (T, T))
        await E("forge.view.tree.api.setTransform(null, 'translate', 0, 0.3); forge.view.pro.snap = { grid: false, edge: false, point: false }")
        before = await E("[%s.transform().translate.slice(), %s.pivotOf().toArray()]" % (T, T))
        opened = await E("(async () => { const r = await forgeProRun(forge.view, 'pivotEdit'); return [r, forge.view.mode, !!forge.view.tree.api.pivotMode]; })()")
        mode = await E("!!forge.view.tree.api.pivotMode")
        moved = await E("""() => { const v = forge.view, T = v.THREE, tc = v.transform, m = v.pro;
          if (!m.pivotProxy || tc.object !== m.pivotProxy) return false;
          m.pivotProxy.position.copy(m.pivotProxy.position.add(new T.Vector3(0.4, 0.3, 0)));
          m.pivotProxy.updateMatrixWorld(true);
          tc.dispatchEvent({ type: "objectChange" });
          return true; }""")
        after = await E("[%s.transform().translate.slice(), %s.pivotOf().toArray()]" % (T, T))
        await E("forgeProRun(forge.view, 'pivotEdit')")
        left = await E("!!forge.view.tree.api.pivotMode")
        same = all(abs(a - b) < 1e-5 for a, b in zip(before[0], after[0]))
        moved_pivot = max(abs(a - b) for a, b in zip(before[1], after[1])) > 0.05
        check("pivot edit: the handle moves the pivot and the object's translate does not change",
              mode is True and left is False and moved is True and same and moved_pivot, [mode, left, moved, before, after, opened, mode_now])

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
