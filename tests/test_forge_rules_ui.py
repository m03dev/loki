"""Forge follows the pro modeller's rules (2026-10-21, owner: "a lot dont seem to work right and dont seem to follow
[the pro] logic when it comes to modeling and moving verts") - in headless Chromium:

- display keys: 4 = wireframe ONLY on every object (the shaded surfaces stop drawing), 5 = shaded again;
- the viewport has no Grid / Edge / Point chips (the status line keeps the snap buttons);
- f frames the selected COMPONENTS (one vertex: the camera goes to it), a frames everything in the scene;
- the object manipulator leaves when you go to components (it used to stay, so Shift over a face's handle duplicated
  the object), the tool carries across, and Shift + drag over the face handle extrudes;
- the hotbox's menus open when the mouse rests on a name, not while it sweeps across the row (the "jittering");
- the Generate panel (the make-with-LOKI tools) has a title bar: fold, float, close;
- the Modeling Toolkit: a tab beside the Channel Box with every tool; the tools follow the pro rules
  (context Ctrl+E on edges, Delete on an edge DISSOLVES it, Bevel with live Tool Settings and an INPUTS step,
  Multi-Cut by clicking, Edge Loop / Ring selection).
No engine, no model download. Under a minute.

    python tests/test_forge_rules_ui.py
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
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright here\n\n0 passed, 0 failed")
    sys.exit(0)

T = "forge.view.tree.api"
# where a component handle axis is on screen
HANDLE = """(name) => { const v = forge.view, g = v.gizmo, THREE = v.internals.THREE; g.getHelper().updateMatrixWorld(true);
  const c = v.internals.camera, r = v.internals.canvas.getBoundingClientRect();
  const s = g._gizmo.gizmo.translate.children.find((h) => h.name === name); s.geometry.computeBoundingBox();
  const q = s.geometry.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(s.matrixWorld).project(c);
  return [r.left + (q.x + 1) / 2 * r.width, r.top + (1 - q.y) / 2 * r.height]; }"""
# a vertex / edge midpoint on screen (in the working mesh)
SCREEN = """(p) => { const v = forge.view, THREE = v.internals.THREE, c = v.internals.camera, r = v.internals.canvas.getBoundingClientRect();
  v.holder.updateMatrixWorld(true); const q = new THREE.Vector3(p[0], p[1], p[2]).applyMatrix4(v.holder.matrixWorld).project(c);
  return [r.left + (q.x + 1) / 2 * r.width, r.top + (1 - q.y) / 2 * r.height]; }"""


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
            bare = r.request.url.split("8896", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8896/**", route)
        await page.goto("http://127.0.0.1:8896/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("localStorage.removeItem('loki-forge-hotkeys'); localStorage.removeItem('loki-forge-genui')")
        await page.click("#open-forge")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        E = page.evaluate
        await E("forgeAddPrimitive('cube')")
        await page.wait_for_function("forge.view && forge.view.sm && forge.view.tree", timeout=10000)
        await E("forgeModelMode(false)")
        await page.mouse.move(650, 450)

        # -------- 4 / 5, the snap chips
        await page.keyboard.press("4")
        w4 = await E("""() => { const out = []; let s = forge.view.holder; while (s.parent) s = s.parent;
          s.traverse((o) => { if (o.isMesh && (o.name === 'forge' || o.name === 'shape')) out.push([o.material.colorWrite, !!o.userData.fmyWire]); }); return out; }""")
        await page.keyboard.press("5")
        w5 = await E("""() => { const out = []; let s = forge.view.holder; while (s.parent) s = s.parent;
          s.traverse((o) => { if (o.isMesh && (o.name === 'forge' || o.name === 'shape')) out.push([o.material.colorWrite, !!o.userData.fmyWire]); }); return out; }""")
        check("4 is wireframe only (surfaces stop drawing, edges show), 5 is shaded again",
              w4 and all(not c and wr for c, wr in w4) and all(c and not wr for c, wr in w5), [w4, w5])
        check("no Grid / Edge / Point chips in the viewport", await E("!document.getElementById('forge-snaps').offsetParent"))

        # -------- the object manipulator leaves in component mode; Shift + drag on the face handle extrudes
        await E(T + ".select(" + T + ".list()[0].id)")
        await page.keyboard.press("w")
        await page.keyboard.press("F11")
        await page.wait_for_timeout(150)
        await E("forge.view.select([4])")
        await page.wait_for_timeout(100)
        st = await E("[!!forge.view.transform.object, !!forge.view.gizmo.object, forge.view.tool && forge.view.tool()]")
        check("going to components takes the object manipulator away and the move tool carries over to the face", st == [False, True, "translate"], st)
        pt = await E(HANDLE, "Y")
        await page.mouse.move(pt[0], pt[1])
        await page.wait_for_timeout(60)
        n_obj = await E(T + ".list().length")
        f0 = await E("forge.view.poly.f.length")
        await page.keyboard.down("Shift")
        await page.mouse.down()
        for i in range(4):
            await page.mouse.move(pt[0], pt[1] - 9 * (i + 1))
            await page.wait_for_timeout(25)
        await page.mouse.up()
        await page.keyboard.up("Shift")
        after = await E("[" + T + ".list().length, forge.view.poly.f.length]")
        check("Shift + drag over the face's handle extrudes the face (no copy of the object)", after == [n_obj, f0 + 4], [n_obj, f0, after])

        # -------- f frames the vertex, a frames everything
        await E("forge.view.setSelMode('vert'); forge.view.selectItems('vert', [0], 'set')")
        await page.keyboard.press("f")
        fv = await E("""() => { const v = forge.view, THREE = v.internals.THREE; v.holder.updateMatrixWorld(true);
          const p = new THREE.Vector3().fromArray(v.poly.v[0]).applyMatrix4(v.holder.matrixWorld);
          return [v.controls ? v.controls.target.distanceTo(p) : v.internals.camera.position.distanceTo(p), v.internals.camera.position.distanceTo(p)]; }""")
        await page.keyboard.press("a")
        fa = await E("forge.view.internals.camera.position.length()")
        check("f with one vertex picked frames that vertex (the camera comes close to it); a frames everything again",
              fv[1] < 2.0 and fa > fv[1], [fv, fa])

        # -------- the hotbox: a sweep across the menu names opens nothing, resting on one opens it
        await page.keyboard.down(" ")
        await page.wait_for_timeout(60)
        heads = await E("""[...document.querySelectorAll('#forge-pro-hotbox .forge-pro-row.up .forge-pro-head')].map((h) => { const r = h.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })""")
        for x, y in heads:
            await page.mouse.move(x, y)
            await page.wait_for_timeout(15)
        swept = await E("document.querySelectorAll('#forge-pro-hotbox .forge-pro-list:not([hidden])').length")
        await page.wait_for_timeout(250)
        rested = await E("document.querySelectorAll('#forge-pro-hotbox .forge-pro-list:not([hidden])').length")
        await page.keyboard.up(" ")
        await page.keyboard.press("Escape")
        check("holding Space: sweeping across the menu names opens none of them (calm), resting on one opens just it",
              swept <= 1 and rested == 1, [swept, rested])

        # -------- the Generate panel
        g = await E("""() => { forgeProPanel('create', true); const side = document.getElementById('forge-left');
          const out = { bar: !!side.querySelector('.forge-gen-bar'), labels: [...side.querySelectorAll('.forge-way')].map((b) => b.dataset.lab) };
          side.querySelector('.forge-gen-float').click(); out.floating = side.classList.contains('floating') && getComputedStyle(side).position === 'absolute';
          side.querySelector('.forge-gen-float').click(); out.docked = !side.classList.contains('floating');
          side.querySelector('.forge-gen-fold').click(); out.folded = side.classList.contains('folded'); side.querySelector('.forge-gen-fold').click();
          side.querySelector('.forge-gen-close').click(); out.closed = side.hidden; forgeProPanel('create', true); out.back = !side.hidden;
          return out; }""")
        check("the Generate panel: named tabs, and its bar floats / docks / folds / closes it",
              g["bar"] and g["labels"] == ["Draw", "Image", "Describe", "Creature"] and g["floating"] and g["docked"] and g["folded"] and g["closed"] and g["back"], g)
        await E("forgeProPanel('create', false)")

        # -------- the Modeling Toolkit and the tools
        await E("forgeProRun(forge.view, 'winToolkit')")
        tk = await E("""() => { const b = document.getElementById('forge-toolkit'); return { open: b && !b.hidden,
          buttons: [...b.querySelectorAll('.forge-tk-btn')].map((x) => x.dataset.proId), away: document.getElementById('forge-channel').classList.contains('forge-tk-away') }; }""")
        check("Windows > Modeling Toolkit: a tab beside the Channel Box with the mesh, component and tool buttons",
              tk["open"] and tk["away"] and all(x in tk["buttons"] for x in ["bevel", "bridge", "multiCut", "targetWeld", "offsetEdgeLoop", "connect"]), tk)
        has_ops = await E("!!(window.ForgePoly && window.ForgePoly.bevel && window.ForgePoly.dissolveEdges)")
        if has_ops:
            await E("forgeAddPrimitive('cube')")
            await E("forge.view.setSelMode('edge')")
            e0 = await E("forge.view.edgeIdOf(...forge.view.poly.f[0].slice(0, 2))")
            await E("forge.view.selectItems('edge', [%d], 'set')" % e0)
            f0 = await E("forge.view.poly.f.length")
            await page.keyboard.press("Delete")
            f1 = await E("forge.view.poly.f.length")
            check("Delete on an edge DISSOLVES it: its two faces become one (the pro rule), not a hole",
                  f1 == f0 - 1, [f0, f1])
            await E("forgeProRun(forge.view, 'undo')")
            await E("forge.view.setSelMode('edge'); forge.view.selectItems('edge', [%d], 'set')" % e0)
            await page.keyboard.press("Control+b")
            bev = await E("""() => { const P = window.ForgePoly, T = P.topology(forge.view.poly); return {
              faces: forge.view.poly.f.length, hist: window.forgeHistory.list().map((h) => h.node || h.kind),
              settings: [...document.querySelectorAll('#forge-tk-settings input[type=range]')].length,
              closed: T.edges.every((e) => e.faces.length === 2) }; }""")
            check("Ctrl+B bevels the edge: a new face, a polyBevel step in INPUTS, its settings in Tool Settings, and every edge still on two faces (Ziva's check)",
                  bev["faces"] == f0 + 1 and "polyBevel" in bev["hist"] and bev["settings"] >= 1 and bev["closed"], bev)
            moved = await E("""() => { const before = JSON.stringify(forge.view.poly.v); window.forgeToolkit.tweak('fraction', 0.2);
              return [JSON.stringify(forge.view.poly.v) !== before, forge.view.poly.f.length, forge.view.undoStack.length]; }""")
            check("changing Fraction redoes the bevel in place (same faces, new positions, no new undo step)",
                  moved[0] and moved[1] == bev["faces"], moved)
            await E("forgeProRun(forge.view, 'undo')")
            await E("forge.view.setSelMode('edge'); forge.view.selectItems('edge', [%d], 'set')" % e0)
            await page.keyboard.press("Control+e")
            ex = await E("[forge.view.poly.f.length, forge.view.edit.mode, forge.view.tool && forge.view.tool()]")
            check("Ctrl+E with an edge picked extrudes the EDGE (a new face) and hands over the move tool",
                  ex[0] == f0 + 1 and ex[1] == "edge" and ex[2] == "translate", ex)
            await E("forgeProRun(forge.view, 'undo')")
            # Multi-Cut across the front face: click two edges' middles, Enter
            quad = await E("""() => { const v = forge.view, m = v.poly; let best = 0, bz = -1e9;
              m.f.forEach((f, i) => { const z = f.reduce((s, k) => s + m.v[k][2], 0) / f.length; if (z > bz) { bz = z; best = i; } });
              const f = m.f[best], mid = (a, b) => [0, 1, 2].map((k) => (m.v[a][k] + m.v[b][k]) / 2); return [best, mid(f[0], f[1]), mid(f[2], f[3])]; }""")
            a = await E(SCREEN, quad[1])
            b = await E(SCREEN, quad[2])
            fc = await E("forge.view.poly.f.length")
            await E("forgeProRun(forge.view, 'multiCut')")
            await page.mouse.click(a[0], a[1])
            await page.mouse.click(b[0], b[1])
            await page.keyboard.press("Enter")
            mc = await E("forge.view.poly.f.length")
            check("Multi-Cut: click two edges of a face and Enter - the face is cut in two", mc == fc + 1, [fc, mc])
            await E("forgeAddPrimitive('torus')")
            await E("forge.view.setSelMode('edge')")
            ring = await E("""() => { const m = forge.view.poly; const f = m.f.find((x) => x.length === 4); return forge.view.edgeIdOf(f[0], f[1]); }""")
            await E("(i) => forge.view.selectItems('edge', [i], 'set')", ring)
            await E("forgeProRun(forge.view, 'loopSel')")
            n = await E("forge.view.edit.sel.e.size")
            check("Select > To Edge Loop grows an edge into its loop", n >= 4, n)
        else:
            check("the polygon tools library (forge_polyops.js) is loaded", False, "ForgePoly.bevel / dissolveEdges missing")

        # -------- camera based selection, wireframe colours, the In-View Editor (t)
        await E("forgeAddPrimitive('sphere')")
        await E("forge.view.setSelMode('vert')")
        r = await E("""() => { const v = forge.view, c = v.canvas.getBoundingClientRect(), out = {};
          const box = () => { v.boxSelect(0, 0, c.width, c.height, 'set'); return v.edit.sel.v.size; };
          out.n = v.poly.v.length;
          v.cameraBasedSelection('auto'); out.shaded = box();
          v.cameraBasedSelection('off'); out.off = box();
          v.cameraBasedSelection('on'); out.on = box();
          v.cameraBasedSelection('auto'); forgeProRun(v, 'wire'); out.wire = box(); forgeProRun(v, 'shaded');
          return out; }""")
        check("marquee: shaded takes only the front vertices; Camera Based Selection Off (or wireframe 4) takes the back ones too",
              r["shaded"] < r["n"] and r["off"] == r["n"] and r["on"] == r["shaded"] and r["wire"] == r["n"], r)
        await E("forgeModelMode(false)")
        await E("forgeProRun(forge.view, 'wire')")
        await page.wait_for_timeout(150)
        cols = await E("""() => { const out = {}; let s = forge.view.holder; while (s.parent) s = s.parent; const t = forge.view.tree.api;
          s.traverse((o) => { if (o.isMesh && o.userData.fmyWire) { const n = t.nodeOfObject(o); out[n ? n.name : o.name] = [o.userData.fmyWire.material.color.getHexString(), o.material.depthWrite]; } }); return out; }""")
        await E("forgeProRun(forge.view, 'shaded')")
        lead = [c for c, d in cols.values() if c == "65fdcd"]
        check("wireframe: the selected object light green, the others dark blue, and nothing hides the back edges",
              len(lead) == 1 and any(c == "101e66" for c, d in cols.values()) and all(d is False for c, d in cols.values()), cols)
        await E("forgeModelMode(true)")
        await E("forge.view.setSelMode('edge'); forge.view.selectItems('edge', [0], 'set')")
        await page.keyboard.press("Control+b")
        ive = await E("""() => { const b = document.getElementById('forge-ive'); return { open: b && !b.hidden, title: b && b.querySelector('.forge-ive-title').textContent,
          rows: b ? [...b.querySelectorAll('.forge-ive-row')].map((r) => r.dataset.k) : [] }; }""")
        await E("window.forgeToolkit.ive.hide()")
        await page.mouse.move(650, 450)
        await page.keyboard.press("t")
        back = await E("!document.getElementById('forge-ive').hidden")
        lab = await E("""() => { const r = document.querySelector('#forge-ive .forge-ive-row[data-k="segments"] .forge-ive-label').getBoundingClientRect(); return [r.left + 10, r.top + r.height / 2]; }""")
        f0 = await E("forge.view.poly.f.length")
        await page.mouse.move(lab[0], lab[1]); await page.mouse.down()
        await page.mouse.move(lab[0] + 60, lab[1], steps=6); await page.mouse.up()
        f1 = await E("forge.view.poly.f.length")
        check("a tool opens the In-View Editor (polyBevel1: Fraction, Segments); t brings it back; dragging Segments' name redoes the bevel",
              ive["open"] and ive["title"] == "polyBevel1" and ive["rows"][:2] == ["fraction", "segments"] and back and f1 > f0, [ive, back, f0, f1])

        # -------- preselection highlight: the face under the mouse lights up before the click
        await E("forge.view.setSelMode('face')")
        await page.mouse.move(640, 440)
        await page.mouse.move(650, 450)
        await page.wait_for_timeout(120)
        pre = await E("""() => { let n = null; forge.view.holder.traverse((o) => { if (o.name === 'forge-preselect') n = o.type; }); return n; }""")
        check("preselection highlight: the face under the mouse is outlined before you click", pre == "LineSegments", pre)

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
