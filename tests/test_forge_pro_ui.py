"""Forge the way pro works (app/ui/forge_pro.js + app/ui/forge_scene.js, spec docs/FORGE_PRO_SPEC.md) in
headless Chromium: the pro hotkeys (Ctrl and Cmd alike), the camera on Alt, the hotbox and its zones, the Space tap
between one and four views, context marking menus picked by direction, Create making NEW objects, Duplicate /
Duplicate with Transform, Group with its pivot at the centre, real pivots (move / centre / reset / freeze keep the
object still and the Channel Box's translate unchanged), parent / unparent, hide / show, pick-walk, viewport
click and box selection with the pro modifiers, the Outliner's range / toggle selection and drag-and-drop, every
object editable (the tools' mesh moves into the one you edit), pivot edit mode (d), view undo ([) and the
Blender hotkey set. No engine, no model download: everything starts from primitives. Under a minute.

    python tests/test_forge_pro_ui.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
PART = os.getenv("LOKI_FORGE_PRO_PART", "1")   # 1 = the first half, 2 = the second (test_forge_pro2_ui.py)
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

NEAR = "(a, b, e) => a.every((x, i) => Math.abs(x - b[i]) < (e || 1e-4))"


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
            bare = r.request.url.split("8899", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8899/**", route)
        await page.add_init_script("try { localStorage.setItem('loki-forge-create-mode', 'component') } catch (e) {}")   # these checks start in component mode after Create
        await page.goto("http://127.0.0.1:8899/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("localStorage.removeItem('loki-forge-keymap')")
        await page.evaluate("document.getElementById('open-forge').click()")
        await page.wait_for_selector("#forge:not([hidden])", timeout=15000)
        await page.evaluate("forgeAddPrimitive('cube')")
        await page.wait_for_function("forge.view && forge.view.sm && forge.view.tree", timeout=10000)
        await page.evaluate("forgeModelMode(false)")
        await page.evaluate("document.activeElement && document.activeElement.blur && document.activeElement.blur()")
        vb = await (await page.query_selector("#forge-view")).bounding_box()
        cx, cy = vb["x"] + vb["width"] * 0.5, vb["y"] + vb["height"] * 0.5
        await page.mouse.move(cx, cy)
        T = "forge.view.tree.api"

        # -------- names: Create makes pCube1, a NEW primitive is a new object and the old one stays
        names = await page.evaluate(T + ".list().map((n) => n.name)")
        check("a primitive is named the pro way (pCube1)", names == ["pCube1"], names)
        await page.evaluate("forgeAddPrimitive('sphere')")
        await page.evaluate("forgeModelMode(false)")
        made = await page.evaluate("""() => { const t = forge.view.tree.api;
          return { names: t.list().map((n) => n.name), root: t.root().name, cubeTris: t.node(1).inner.children.some((o) => o.isMesh && o.name === 'shape') }; }""")
        check("Create adds a NEW object - the cube is still in the scene", made["names"] == ["pCube1", "pSphere1"]
              and made["root"] == "pSphere1" and made["cubeTris"], made)

        if PART == "1":   # the second half runs in tests/test_forge_pro2_ui.py (each under a minute)
            # -------- hotkeys: 4 / 5, w on the SELECTED object, q puts it away
            await page.keyboard.press("4")
            wire = await page.evaluate("forge.view.wire")
            await page.keyboard.press("5")
            check("4 wireframe, 5 shaded", wire is True and await page.evaluate("forge.view.wire") is False)
            await page.evaluate(T + ".select(1)")
            await page.keyboard.press("w")
            on_cube = await page.evaluate("forge.view.transform.object === forge.view.tree.api.node(1).grp && forge.view.transform.mode === 'translate'")
            check("w puts the move manipulator on the selected object (not on the one being edited)", on_cube)
            await page.keyboard.press("e")
            check("e rotates", await page.evaluate("forge.view.transform.mode") == "rotate")
            await page.keyboard.press("r")
            check("r scales", await page.evaluate("forge.view.transform.mode") == "scale")
            await page.keyboard.press("q")
            check("q is the select tool: the manipulator goes", not await page.evaluate("!!forge.view.transform.object"))
            await page.keyboard.press("y")
            check("y brings the last tool back", await page.evaluate("forge.view.transform.mode") == "scale"
                  and await page.evaluate("!!forge.view.transform.object"))
            await page.keyboard.press("Escape")
            check("Esc drops the tool (and does not close Forge)", not await page.evaluate("!!forge.view.transform.object")
                  and await page.is_visible("#forge"))

            # -------- the camera: Alt / Option + left / middle / right = tumble / track / dolly, Forge's own controller
            # (owner 17:06: "I want to move like im in [the pro app]"), read from each press
            cs = "() => { const v = forge.view; return { p: v.camera.position.toArray(), t: v.controls.target.toArray(), d: v.camera.position.distanceTo(v.controls.target), mb: [v.controls.mouseButtons.LEFT, v.controls.mouseButtons.MIDDLE, v.controls.mouseButtons.RIGHT] }; }"
            import math
            async def alt_drag(button, dx, dy):
                await page.mouse.move(cx, cy)
                await page.keyboard.down("Alt")
                await page.mouse.down(button=button)
                await page.mouse.move(cx + dx, cy + dy, steps=5)
                await page.mouse.up(button=button)
                await page.keyboard.up("Alt")
                await page.wait_for_timeout(30)
                return await page.evaluate(cs)
            c0 = await page.evaluate(cs)
            c1 = await alt_drag("left", 80, 0)
            c2 = await alt_drag("middle", 40, 30)
            c3 = await alt_drag("right", 60, 0)
            c4 = await alt_drag("right", 0, -60)
            moved = lambda a, b: math.dist(a, b) > 1e-3
            check("no mouse button turns the camera by itself (left selects, right is the marking menu)", c0["mb"] == [None, None, None], c0["mb"])
            check("Alt + left drag tumbles about the centre of interest (same target, same distance)", moved(c0["p"], c1["p"])
                  and not moved(c0["t"], c1["t"]) and abs(c0["d"] - c1["d"]) < 1e-3, [c0, c1])
            check("Alt + middle drag tracks: the camera and its centre of interest move together", moved(c1["t"], c2["t"]) and abs(c1["d"] - c2["d"]) < 1e-3, [c1, c2])
            check("Alt + right drag dollies: to the right moves in, upward moves out", c3["d"] < c2["d"] * 0.9 and c4["d"] > c3["d"] * 1.1, [c2["d"], c3["d"], c4["d"]])
            await page.mouse.move(cx, cy)
            await page.mouse.wheel(0, -240)
            await page.wait_for_timeout(60)
            c5 = await page.evaluate(cs)
            check("the wheel dollies in", c5["d"] < c4["d"], [c4["d"], c5["d"]])
            await page.evaluate("forge.view.frame()")

            # -------- Space: the hotbox CENTRED ON THE MOUSE, the menu rows tight around it (owner 17:06: menus "too far
            # apart", "open up not on the cursor", "neat and tidy"); hovering a menu drops it down right there
            await page.mouse.move(cx, cy)
            await page.keyboard.down(" ")
            await page.wait_for_timeout(140)
            hb = await page.evaluate("""([x, y]) => { const h = document.getElementById('forge-pro-hotbox');
              if (!h) return null;
              const vis = [...h.querySelectorAll('.forge-pro-row')].filter((r) => !r.hidden);
              const rows = vis.map((r) => r.getBoundingClientRect());
              const up = rows.filter((r) => r.bottom <= y + 2).map((r) => y - r.bottom);      // the rows above the middle
              const dn = rows.filter((r) => r.top >= y - 2).map((r) => r.top - y);            // and below it
              return { vis: !h.hidden, c: h._center,
                       cols: vis.reduce((n, r) => n + r.querySelectorAll('.forge-pro-col').length, 0),
                       items: h.querySelectorAll('.forge-pro-item').length,
                       gapUp: Math.round(Math.min.apply(null, up)), gapDown: Math.round(Math.min.apply(null, dn)) }; }""", [cx, cy])
            eb = await (await page.query_selector('#forge-pro-hotbox .forge-pro-col[data-menu="Edit"] .forge-pro-head')).bounding_box()
            await page.mouse.move(eb["x"] + eb["width"] / 2, eb["y"] + eb["height"] / 2)
            await page.wait_for_timeout(120)
            drop = await page.evaluate("""() => { const l = document.querySelector('#forge-pro-hotbox .forge-pro-col[data-menu="Edit"] .forge-pro-list');
              const h = document.querySelector('#forge-pro-hotbox .forge-pro-col[data-menu="Edit"] .forge-pro-head').getBoundingClientRect();
              if (!l || l.hidden) return null; const r = l.getBoundingClientRect();
              return { n: l.querySelectorAll('.forge-pro-item').length, dy: Math.round(h.top - r.bottom), keys: [...l.querySelectorAll('.forge-pro-key')].map((k) => k.textContent).filter(Boolean).length }; }""")
            await page.keyboard.up(" ")
            await page.wait_for_timeout(120)
            check("Space opens the hotbox centred on the mouse (panel menus, the main menus, the middle and the set's rows), rows within 30 px of it",
                  hb and hb["vis"] and abs(hb["c"][0] - cx) < 2 and abs(hb["c"][1] - cy) < 2 and hb["cols"] >= 20 and hb["items"] >= 80
                  and 0 <= hb["gapUp"] <= 30 and 0 <= hb["gapDown"] <= 30, hb)
            check("hovering a menu drops it right at its name, with the hotkeys on the right", bool(drop) and drop["n"] >= 6
                  and abs(drop["dy"]) <= 4 and drop["keys"] >= 4, drop)
            check("the dropped menu stays after releasing Space, so an item can be clicked",
                  not await page.evaluate("document.getElementById('forge-pro-hotbox').hidden"))
            await page.mouse.click(5, 5)
            check("a click away closes it", await page.evaluate("document.getElementById('forge-pro-hotbox').hidden"))
            await page.evaluate("forgeProRun(forge.view, 'wheel')")
            wh = await page.evaluate("""() => { const h = document.getElementById('forge-pro-wheel');
              return h ? { vis: !h.hidden, n: h.querySelectorAll('.forge-wheel-wedge').length } : null; }""")
            await page.keyboard.press("Escape")
            # the wheel carries the showing menu set's menus (Recent + 7 for Forge), kept inside its ring
            check("the wheel is still there: Windows > Radial Menus, the showing set's menus around it",
                  bool(wh) and wh["vis"] and 2 <= wh["n"] <= 12, wh)
            await page.keyboard.down(" ")
            await page.wait_for_timeout(300)
            await page.keyboard.up(" ")
            await page.keyboard.press("Escape")
            check("Escape puts it away; a long hold does not switch views", await page.evaluate("document.getElementById('forge-pro-hotbox').hidden && document.getElementById('forge-pro-wheel').hidden && !forge.view.quad"))
            await page.keyboard.press(" ")
            quad = await page.evaluate("forge.view.quad")
            await page.mouse.move(vb["x"] + vb["width"] * 0.25, vb["y"] + vb["height"] * 0.25)
            await page.keyboard.press(" ")
            after = await page.evaluate("[forge.view.quad, forge.view.cam]")
            check("a Space tap goes to four views; a tap over the top-left pane makes Front big", quad is True and after == [False, "front"], [quad, after])
            # the hotbox's centre zone
            await page.evaluate("forgeProHotboxOpen(forge.view, [%d, %d])" % (cx, cy))
            await page.mouse.move(cx, cy)
            await page.wait_for_timeout(120)
            await page.mouse.down()
            await page.mouse.move(cx, cy - 70, steps=4)
            zone = await page.evaluate("(document.getElementById('forge-pro-marking') || {dataset: {}}).dataset.set")
            await page.mouse.up()
            check("the hotbox's centre zone is the views menu; flicking up picks Perspective", zone == "Views"
                  and await page.evaluate("forge.view.cam") == "persp", [zone, await page.evaluate("forge.view.cam")])
            await page.evaluate(T + ".setTransform(1, 'translate', 0, -1.6)")            # the cube beside the sphere
            await page.evaluate("forge.view.frameBox(forge.view.tree.api.worldBox(forge.view.tree.api.allIds()))")
            await page.wait_for_timeout(50)

            # -------- viewport selection: click, Shift toggles, Ctrl removes, empty click clears, box selects
            await page.evaluate(T + ".selectNone()")
            pts = await page.evaluate("""() => { const t = forge.view.tree.api, v = forge.view, r = v.canvas.getBoundingClientRect();
              v.camera.updateMatrixWorld();
              return t.allIds().map((id) => { const c = t.worldBox([id]).getCenter(new v.THREE.Vector3()).project(v.camera);
                return [id, r.left + (c.x + 1) / 2 * r.width, r.top + (1 - c.y) / 2 * r.height]; }); }""")
            p1 = next(x for x in pts if x[0] == 1)
            p2 = next(x for x in pts if x[0] == 2)
            await page.mouse.click(p2[1], p2[2])
            s1 = await page.evaluate(T + ".selected()")
            await page.keyboard.down("Shift")
            await page.mouse.click(p1[1], p1[2])
            await page.keyboard.up("Shift")
            s2 = await page.evaluate(T + ".selected()")
            await page.keyboard.down("Control")
            await page.mouse.click(p2[1], p2[2])
            await page.keyboard.up("Control")
            s3 = await page.evaluate(T + ".selected()")
            await page.mouse.click(vb["x"] + 8, vb["y"] + 8)
            s4 = await page.evaluate(T + ".selected()")
            check("click selects the object under the mouse", s1 == [2], s1)
            at1 = await page.evaluate("""() => { const v = forge.view, t = v.tree.api; return { cam: v.camera.position.toArray(), fov: v.camera.fov, asp: v.camera.aspect,
              tgt: v.controls.target.toArray(), box: [t.worldBox([1]).min.toArray(), t.worldBox([1]).max.toArray()], T1: t.transform(1).translate, cv: [v.canvas.clientWidth, v.canvas.clientHeight] }; }""")
            check("Shift+click adds (toggles), Ctrl+click takes away, a click on nothing clears", s2 == [2, 1] and s3 == [1] and s4 == [], [s2, s3, s4, p1, at1, vb])
            await page.mouse.move(vb["x"] + 4, vb["y"] + 4)
            await page.mouse.down()
            await page.mouse.move(vb["x"] + vb["width"] - 4, vb["y"] + vb["height"] - 4, steps=6)
            await page.mouse.up()
            s5 = sorted(await page.evaluate(T + ".selected()"))
            check("a box drag selects every object inside it", s5 == [1, 2], s5)
            marks = await page.evaluate("forge.view.tree.nodes.filter((n) => n.inner.children.some((o) => o.name === 'forge-sel')).length")
            check("selected objects are outlined in the viewport (the last one green)", marks == 2, marks)

            # -------- the right-button marking menu, by context, picked by direction
            await page.evaluate(T + ".selectNone()")
            await page.mouse.move(p1[1], p1[2])
            await page.mouse.down(button="right")
            await page.wait_for_timeout(260)
            ring = await page.evaluate("Object.fromEntries([...document.querySelectorAll('#forge-pro-marking .forge-pro-wedge')].map((b) => [b.dataset.pos, b.dataset.proCmd]))")
            await page.mouse.move(p1[1] + 75, p1[2] + 6, steps=4)                     # a flick east, not onto the button
            await page.mouse.up(button="right")
            await page.wait_for_timeout(250)
            st = await page.evaluate("[forge.view.mode, forge.view.edit && forge.view.edit.mode, forge.view.tree.api.root().id]")
            check("right button on an object: the pro ring (N Edge, W Vertex, E Face, S UV, NE Object Mode)",
                  ring.get("N") == "Edge" and ring.get("W") == "Vertex" and ring.get("E") == "Face" and ring.get("S") == "UV"
                  and ring.get("NE") == "Object Mode", ring)
            check("...a flick east picks Face: that object becomes the edited one, in face mode", st == ["poly", "face", 1], st)
            await page.keyboard.press("F10")
            check("F10 edges (F9 / F10 / F11)", await page.evaluate("forge.view.edit.mode") == "edge")
            await page.keyboard.press("F8")
            check("F8 back to object mode", await page.evaluate("forge.view.mode") == "view")
            sph = await page.evaluate("forge.view.tree.api.node(2).inner.children.some((o) => o.isMesh && o.name === 'shape')")
            check("the sphere kept a copy of its mesh when the cube became the edited one", sph)
            # Shift + right button on empty space: the Create ring; flick south = Cube
            n0 = await page.evaluate(T + ".list().length")
            await page.mouse.move(vb["x"] + 30, vb["y"] + vb["height"] - 120)
            await page.keyboard.down("Shift")
            await page.mouse.down(button="right")
            await page.wait_for_timeout(260)
            title = await page.evaluate("document.getElementById('forge-pro-marking').dataset.set")
            await page.mouse.move(vb["x"] + 32, vb["y"] + vb["height"] - 40, steps=4)
            await page.mouse.up(button="right")
            await page.keyboard.up("Shift")
            await page.wait_for_timeout(250)
            await page.evaluate("forgeModelMode(false)")
            n1 = await page.evaluate("[forge.view.tree.api.list().length, forge.view.tree.api.root().name]")
            check("Shift + right button on nothing is the pro Create ring; flicking south makes a new cube", title == "Create"
                  and n1 == [n0 + 1, "pCube2"], [title, n0, n1])

            # right button: the menu is there the moment the button goes down, only while it is held; a quick click
            # does nothing (owner 17:06: "right click doesnt do that ... fix the systems")
            ex, ey = vb["x"] + 40, vb["y"] + 70
            # the empty spot: the first point near the top-left with no object under it (the 3/4 default camera of
            # 2026-10-21 can put a cube under the old fixed point)
            spot = await page.evaluate("""() => { const v = forge.view, r = v.canvas.getBoundingClientRect();
              for (let y = r.top + 70; y < r.bottom - 20; y += 20) for (let x = r.left + 40; x < r.right - 20; x += 20)
                if (!forgeProPickAt(v, x, y)) return [x, y];
              return null; }""")
            if spot:
                ex, ey = spot
            await page.mouse.move(ex, ey)
            await page.mouse.down(button="right")
            now = await page.evaluate("""() => { const h = document.getElementById('forge-pro-marking');
              return { vis: !h.hidden, list: [...h.querySelectorAll('.forge-pro-litem')].map((b) => b.dataset.proId), wedges: h.querySelectorAll('.forge-pro-wedge').length }; }""")
            await page.mouse.up(button="right")
            await page.wait_for_timeout(60)
            gone = await page.evaluate("document.getElementById('forge-pro-marking').hidden")
            n2 = await page.evaluate(T + ".list().length")
            check("right button on nothing: at once, the empty-space list (Complete Tool, Select All, Undo ...), no ring",
                  now["vis"] and now["list"][:2] == ["completeTool", "selectAll"] and "undo" in now["list"] and now["wedges"] == 0, now)
            check("...a quick click (press and let go in place) just closes it - nothing runs, nothing stays open", gone and n2 == n1[0], [gone, n2])

            # -------- Duplicate (Ctrl/Cmd+D) and Duplicate with Transform (Shift+D)
            await page.evaluate(T + ".select(1)")
            await page.keyboard.press("Control+d")
            d1 = await page.evaluate("(() => { const t = forge.view.tree.api, n = t.active(); return [n.name, n.parent, t.list().length]; })()")
            await page.evaluate(T + ".setTransform(null, 'translate', 0, 1.5)")
            await page.keyboard.press("Shift+D")
            d2 = await page.evaluate("(() => { const t = forge.view.tree.api, n = t.active(); return [n.name, t.transform(n.id).translate[0]]; })()")
            await page.keyboard.press("Meta+d")
            d3 = await page.evaluate(T + ".list().length")
            check("Ctrl+D duplicates in place, named with the next number (pCube3)", d1[0] == "pCube3" and d1[1] == 0, d1)
            check("Shift+D makes another copy offset again by the same move (x: -1.6 -> 1.5 -> 4.6)", d2[0] == "pCube4" and abs(d2[1] - 4.6) < 1e-4, d2)
            check("Cmd+D works like Ctrl+D (the Mac)", d3 == d1[2] + 2, [d1, d3])

            # -------- Group: translate 0, pivot at the centre; children keep their place; rotating turns about the middle
            grp = await page.evaluate("""() => { const t = forge.view.tree.api, V = forge.view.THREE;
              const a = t.node(1), b = t.list().find((n) => n.name === 'pCube4');
              t.setTransform(a.id, 'translate', 0, -1); t.setTransform(a.id, 'translate', 2, 0);
              const wa = a.grp.getWorldPosition(new V.Vector3()).toArray(), wb = b.grp.getWorldPosition(new V.Vector3()).toArray();
              t.select(a.id); t.select(b.id, 'add');
              return { wa, wb, ids: [a.id, b.id] }; }""")
            await page.keyboard.press("Control+g")
            g = await page.evaluate("""(w) => { const t = forge.view.tree.api, V = forge.view.THREE, g = t.active();
              const near = %s;
              const wa = t.node(w.ids[0]).grp.getWorldPosition(new V.Vector3()).toArray();
              const box = t.worldBox([g.id]).getCenter(new V.Vector3()).toArray();
              const piv = t.pivotWorld(g.id).toArray();
              t.setTransform(g.id, 'rotate', 1, 180);
              const box2 = t.worldBox([g.id]).getCenter(new V.Vector3()).toArray();
              return { kind: g.kind, name: g.name, kids: t.kids(g.id).length, T: t.transform(g.id).translate,
                       stays: near(wa, w.wa), pivotAtCentre: near(piv, box, 1e-3), turnsAboutMiddle: near(box2, box, 1e-3) }; }""" % NEAR, grp)
            check("Ctrl+G groups: a group1 node with both inside, translate 0", g["kind"] == "group" and g["name"] == "group1"
                  and g["kids"] == 2 and all(abs(x) < 1e-6 for x in g["T"]), g)
            check("...the children did not move, the pivot is the centre, and rotating the group turns about the middle",
                  g["stays"] and g["pivotAtCentre"] and g["turnsAboutMiddle"], g)

            # -------- pivots: move / centre / reset / freeze never move the object; translate stays what it was
            pv = await page.evaluate("""() => { const t = forge.view.tree.api, V = forge.view.THREE, near = %s;
              const n = t.list().find((x) => x.name === 'pCube3');
              t.select(n.id); t.setTransform(n.id, 'translate', 0, 2); t.setTransform(n.id, 'rotate', 2, 30);
              const world = () => t.worldBox([n.id]).min.toArray().concat(t.worldBox([n.id]).max.toArray());
              const w0 = world(), T0 = t.transform(n.id).translate;
              t.setPivot(n.id, [0.5, 0.5, 0]);  const w1 = world(), T1 = t.transform(n.id).translate;
              t.centerPivot(n.id); const w2 = world(), p2 = t.pivotWorld(n.id).toArray(), c2 = t.worldBox([n.id]).getCenter(new V.Vector3()).toArray();
              t.setPivot(n.id, [0.5, 0, 0]); t.resetPivot(n.id); const w3 = world(), P3 = t.transform(n.id).pivot;
              const pw = t.pivotWorld(n.id).toArray();
              t.freeze(n.id); const w4 = world(), f = t.transform(n.id), pw4 = t.pivotWorld(n.id).toArray();
              return { moveStill: near(w0, w1), keepT: near(T0, T1), centre: near(w0, w2) && near(p2, c2, 1e-3),
                       reset: near(w0, w3) && near(P3, [0, 0, 0]),
                       freeze: near(w0, w4, 1e-3) && near(f.translate, [0, 0, 0]) && near(f.rotate, [0, 0, 0]) && near(f.scale, [1, 1, 1]),
                       pivotStays: near(pw, pw4, 1e-3) }; }""" % NEAR)
            check("moving the pivot does not move the object, and the Channel Box translate does not change", pv["moveStill"] and pv["keepT"], pv)
            check("Center Pivot puts it in the middle; Reset Pivot back on the origin - the object never moves", pv["centre"] and pv["reset"], pv)
            check("Freeze Transformations: reads 0 / 0 / 1, nothing moved, and the pivot stayed in the world", pv["freeze"] and pv["pivotStays"], pv)

            # -------- p / Shift+P, h / Ctrl+H / Shift+H / Ctrl+Shift+H, pick-walk
            par = await page.evaluate("""() => { const t = forge.view.tree.api;
              const a = t.list().find((x) => x.name === 'pCube3'), b = t.list().find((x) => x.name === 'pSphere1');
              t.select(a.id); t.select(b.id, 'add'); return [a.id, b.id]; }""")
            await page.keyboard.press("p")
            pp = await page.evaluate(T + ".node(%d).parent" % par[0])
            await page.evaluate(T + ".select(%d)" % par[0])
            await page.keyboard.press("ArrowUp")
            up = await page.evaluate(T + ".selected()")
            await page.keyboard.press("ArrowDown")
            down = await page.evaluate(T + ".selected()")
            await page.keyboard.press("Shift+P")
            unp = await page.evaluate(T + ".node(%d).parent" % par[0])
            check("p parents the first under the LAST selected", pp == par[1], [pp, par])
            check("the arrow keys pick-walk: up to the parent, down to the child", up == [par[1]] and down == [par[0]], [up, down])
            check("Shift+P unparents to the world", unp == 0, unp)
            await page.keyboard.press("h")
            h1 = await page.evaluate(T + ".node(%d).visible" % par[0])
            await page.keyboard.press("Shift+H")
            h2 = await page.evaluate(T + ".node(%d).visible" % par[0])
            await page.keyboard.press("Control+h")
            h3 = await page.evaluate(T + ".node(%d).visible" % par[0])
            await page.keyboard.press("Control+Shift+H")
            h4 = await page.evaluate(T + ".node(%d).visible" % par[0])
            check("h toggles visibility, Shift+H shows, Ctrl+H hides, Ctrl+Shift+H shows the last hidden", [h1, h2, h3, h4] == [False, True, False, True], [h1, h2, h3, h4])

            # -------- the Outliner: range / toggle clicks, drop into / before / onto the world, its menu
            rows = await page.evaluate("[...document.querySelectorAll('#forge-outliner .forge-out-row')].map((r) => +r.dataset.id)")
            await page.click('#forge-outliner .forge-out-row[data-id="%d"] .forge-out-name' % rows[0])
            await page.keyboard.down("Shift")
            await page.click('#forge-outliner .forge-out-row[data-id="%d"] .forge-out-name' % rows[2])
            await page.keyboard.up("Shift")
            rng = await page.evaluate(T + ".selected()")
            # macOS turns Ctrl+click into a SECONDARY click, so the toggle is Cmd there (Ziva) - the handler takes either
            toggle_mod = "Meta" if sys.platform == "darwin" else "Control"
            await page.keyboard.down(toggle_mod)
            await page.click('#forge-outliner .forge-out-row[data-id="%d"] .forge-out-name' % rows[1])
            await page.keyboard.up(toggle_mod)
            tog = await page.evaluate(T + ".selected()")
            check("Outliner: Shift+click selects a range, Ctrl+click toggles one out", sorted(rng) == sorted(rows[:3]) and sorted(tog) == sorted([rows[0], rows[2]]), [rows, rng, tog])
            dd = await page.evaluate("""() => { const t = forge.view.tree.api;
              const a = t.list().find((x) => x.name === 'pCube3'), s = t.list().find((x) => x.name === 'pSphere1');
              t.dropOn(a.id, s.id, 'into'); const into = t.node(a.id).parent === s.id;
              const cyc = t.dropOn(s.id, a.id, 'into');               // a parent under its own child: refused
              t.dropOn(a.id, s.id, 'before'); const before = t.node(a.id).parent === 0 && t.order().indexOf(a.id) === t.order().indexOf(s.id) - 1;
              t.reparent(a.id, s.id); t.reparent(a.id, 0); const world = t.node(a.id).parent === 0;
              return { into, cyc, before, world }; }""")
            check("drag onto an object parents (any object, not only groups); onto its own child is refused", dd["into"] and dd["cyc"] is False, dd)
            check("drop before a row re-orders; onto empty space unparents", dd["before"] and dd["world"], dd)
            await page.click('#forge-outliner .forge-out-row[data-id="%d"] .forge-out-name' % rows[0], button="right")
            menu = await page.evaluate("[...document.querySelectorAll('.forge-out-menu .forge-out-mi')].map((b) => b.dataset.cmd)")
            await page.keyboard.press("Escape")
            await page.mouse.click(vb["x"] + 6, vb["y"] + 6)
            check("the Outliner's right-click menu (Select Hierarchy, Duplicate, Group, pivots, Freeze, Delete ...)",
                  all(x in menu for x in ("Select Hierarchy", "Duplicate", "Group", "Center Pivot", "Reset Pivot", "Freeze Transformations", "Delete")), menu)

        if PART == "2":
            # the first half leaves the cube as the object being edited; start the second half from the same place
            await page.evaluate("""async () => { const t = forge.view.tree.api;
              await forgeAddPrimitive('cube'); forgeModelMode(false); await forgeAddPrimitive('cube'); forgeModelMode(false);
              const c2 = t.list().find((n) => n.name === 'pCube2'); t.select(c2.id); t.groupSelected();   // a group, like the first half's
              const c = t.list().find((n) => n.name === 'pCube1'); if (c && !c.root) t.makeWorking(c.id); t.select(c.id); }""")
            # -------- pivot edit (hold d): the manipulator moves the pivot, the object stays
            await page.evaluate(T + ".select(1)")
            await page.keyboard.down("d")
            pe = await page.evaluate("""() => { const t = forge.view.tree.api, v = forge.view, m = v.pro, V = v.THREE, near = %s;
              const on = t.pivotMode && v.transform.object === m.pivotProxy;
              const box0 = t.worldBox([1]).min.toArray();
              m.pivotProxy.position.add(new V.Vector3(0.3, 0.2, 0)); m.pivotProxy.updateMatrixWorld(true);
              v.transform.dispatchEvent({ type: 'objectChange' });
              return { on, still: near(box0, t.worldBox([1]).min.toArray(), 1e-4),
                       pivot: near(t.pivotWorld(1).toArray(), m.pivotProxy.getWorldPosition(new V.Vector3()).toArray(), 1e-4) }; }""" % NEAR)
            await page.keyboard.up("d")
            off = await page.evaluate("!forge.view.tree.api.pivotMode")
            check("hold d: pivot edit - the handle moves the pivot and the object stays; let go and it ends", pe["on"] and pe["still"] and pe["pivot"] and off, [pe, off])

            # -------- [ undoes a view change
            await page.evaluate("forge.view.rememberView(); forge.view.setView('top')")
            await page.keyboard.press("[")
            vu = await page.evaluate("[forge.view.camera.fov, forge.view.cam, forge.view.controls.enableRotate]")
            check("[ undoes the last view change - the camera, its name and its tumble come back", vu[0] > 10 and vu[1] == "persp" and vu[2] is True, vu)

            # -------- every object editable: the tools' mesh moves into the one you edit
            mk = await page.evaluate("""() => { const t = forge.view.tree.api, v = forge.view;
              const s = t.list().find((x) => x.name === 'pSphere1'), c = t.root();
              const sum = (a) => a.reduce((q, x) => q + Math.abs(x), 0);
              t.makeWorking(s.id);
              const nowRoot = t.root().id === s.id && v.holder.parent === s.grp;
              const before = sum(t.node(c.id).inner.children.find((o) => o.name === 'shape').geometry.attributes.position.array);
              v.dab('inflate', 0, 0.4, 0.3, false);
              const after = sum(t.node(c.id).inner.children.find((o) => o.name === 'shape').geometry.attributes.position.array);
              return { nowRoot, otherUntouched: Math.abs(before - after) < 1e-6, verts: v.sm.n }; }""")
            check("any object can be edited: the sphere takes the tools' mesh, and sculpting it leaves the cube alone",
                  mk["nowRoot"] and mk["otherUntouched"] and mk["verts"] > 100, mk)

            # -------- pro only: no Blender keys, no Blender mouse
            await page.evaluate("forgeModelMode(true)")
            m0 = await page.evaluate("forge.view.edit.mode")
            await page.keyboard.press("2")
            m1 = await page.evaluate("forge.view.edit.mode")
            await page.keyboard.press("g")
            modal = await page.evaluate("!!(forge.view.modalActive && forge.view.modalActive())")
            bb = await page.evaluate("() => { const b = forge.view.pro.controls.mouseButtons; return [b.LEFT, b.MIDDLE, b.RIGHT]; }")
            await page.keyboard.press("3")
            sm3 = await page.evaluate("() => { const v = forge.view, s = v.smoothPrev; return { on: !!(s && s.mesh && s.mesh.parent), baseHidden: !v.meshObj().visible, tris: s && s.mesh ? s.mesh.geometry.index.count / 3 : 0, cage: v.poly.f.length }; }")
            await page.keyboard.press("1")
            sm1 = await page.evaluate("() => { const v = forge.view, s = v.smoothPrev; return { on: !!(s && s.mesh), baseShown: v.meshObj().visible }; }")
            check("3 shows the smoothed surface (display only), 1 the cage again", sm3["on"] and sm3["baseHidden"] and sm3["tris"] > sm3["cage"] * 4
                  and not sm1["on"] and sm1["baseShown"], [sm3, sm1])
            await page.evaluate("forgeModelMode(false)")
            check("pro keys only: 2 / g are not Blender's edge mode / grab (2 is the smooth preview), and no mouse button turns the view without Alt",
                  m1 == m0 and not modal and bb == [None, None, None] and await page.evaluate("forgeKeymap()") == "pro", [m0, m1, modal, bb])

            # -------- the pro workspace: viewport in the middle, Outliner left, Channel Box right, the rest hidden
            lay = await page.evaluate("""() => { const r = (id) => { const e = document.getElementById(id); if (!e || e.hidden) return null; const b = e.getBoundingClientRect(); return b.width > 0 ? [b.left, b.right] : null; };
              const vis = (sel) => { const e = document.querySelector(sel); return !!(e && e.offsetParent !== null && getComputedStyle(e).display !== 'none'); };
              return { out: r('forge-outcol'), stage: r('forge-stage'), chan: r('forge-chancol'), create: r('forge-left'), shelf: vis('#forge .forge-exportbar'),
                       kit: vis('#forge-model'), outInOut: !!document.querySelector('#forge-outcol #forge-outliner'), chInChan: !!document.querySelector('#forge-chancol #forge-channel') }; }""")
            check("the pro layout: the Outliner left, the viewport, the Channel Box right - and nothing else showing",
                  lay["out"] and lay["stage"] and lay["chan"] and lay["out"][1] <= lay["stage"][0] + 1 and lay["stage"][1] <= lay["chan"][0] + 1
                  and lay["create"] is None and not lay["shelf"] and not lay["kit"] and lay["outInOut"] and lay["chInChan"], lay)
            await page.click("#forge-ui-btn")
            ui_off = await page.evaluate("[document.getElementById('forge-outcol').hidden, document.getElementById('forge-chancol').hidden, document.getElementById('forge').classList.contains('forge-bare')]")
            await page.click("#forge-ui-btn")
            ui_on = await page.evaluate("[document.getElementById('forge-outcol').hidden, document.getElementById('forge-chancol').hidden, document.getElementById('forge').classList.contains('forge-bare')]")
            check("the UI button in Forge's title hides every panel and the bars, and brings them back (Ziva's, same store)",
                  ui_off == [True, True, True] and ui_on == [False, False, False], [ui_off, ui_on])
            await page.click("#forge-out-fold")
            fold = await page.evaluate("[document.getElementById('forge-outliner').classList.contains('collapsed'), document.getElementById('forge-outcol').hidden]")
            await page.click("#forge-out-fold")
            check("the Outliner's title folds its list (the column stays) and unfolds it", fold == [True, False], fold)
            await page.keyboard.press("Control+Space")
            bare = await page.evaluate("[document.getElementById('forge-outcol').hidden, document.getElementById('forge-chancol').hidden]")
            await page.keyboard.press("Control+Space")
            back_ = await page.evaluate("[document.getElementById('forge-outcol').hidden, document.getElementById('forge-chancol').hidden]")
            check("Ctrl+Space hides every panel (only the viewport), and brings them back", bare == [True, True] and back_ == [False, False], [bare, back_])
            # the Windows menu in the hotbox brings a panel back (here: the Create panel), with a tick
            await page.mouse.move(cx, cy)
            await page.evaluate("forgeProHotboxOpen(forge.view, [%d, %d])" % (cx, cy))
            await page.wait_for_timeout(100)
            await page.hover('#forge-pro-hotbox .forge-pro-col[data-menu="Windows"] .forge-pro-head')
            await page.wait_for_timeout(220)                 # menus open when the mouse rests on them (hover intent, 2026-10-21)
            drop = await page.evaluate("""() => [...document.querySelectorAll('#forge-pro-hotbox .forge-pro-list')].filter((l) => !l.hidden).map((l) => l.parentElement.dataset.menu)""")
            # Windows > Panels flies out beside its row (menus nest, owner 2026-10-22)
            await page.click('#forge-pro-hotbox .forge-pro-col[data-menu="Windows"] .forge-pro-subitem[data-pro-sub="Panels"]')
            await page.wait_for_timeout(80)
            # Maya's Windows menu: the Outliner and the Channel Box are its own rows (General Editors), ticked when showing
            ticked = await page.evaluate("""() => [...document.querySelectorAll('#forge-pro-hotbox .forge-pro-col[data-menu="Windows"] .forge-pro-item.on, #forge-pro-hotbox .forge-pro-fly .forge-pro-item.on')].map((b) => b.dataset.proId)""")
            await page.click('#forge-pro-hotbox .forge-pro-fly[data-sub="Panels"] .forge-pro-item[data-pro-id="winCreate"]')
            cr = await page.evaluate("!document.getElementById('forge-left').hidden")
            check("hovering a hotbox menu opens just that one; Windows ticks what is showing (Outliner, Channel Box)", drop == ["Windows"]
                  and "winOutliner" in ticked and "winChannel" in ticked and "winCreate" not in ticked, [drop, ticked])
            check("...and Windows > Create panel brings the left panel back", cr)
            await page.evaluate("forgeProPanel('create', false)")
            # a hotbox row near the top of the window must stay CLEAR of the fixed title strip (app/ui/modebar.js, z-index
            # 50, drawn OVER the hotbox at z-index 45): owner idea I5 - "hotbox > Windows > OpenChannelsLayers can't be
            # clicked: covered by titlestrip-side". The strip tops the window; the Windows menu opens UPWARD, so its first
            # row used to be nudged under the strip. forgeProFit now keeps floating menus below it (forgeTopInset()).
            await page.evaluate("typeof forgeProHotboxHide === 'function' && forgeProHotboxHide()")
            await page.evaluate("[...document.querySelectorAll('#forge-pro-hotbox .forge-pro-fly')].forEach((f) => f.remove())")
            await page.mouse.move(650, 430)
            await page.evaluate("forgeProHotboxOpen(forge.view, [650, 430])")
            await page.wait_for_timeout(100)
            await page.hover('#forge-pro-hotbox .forge-pro-col[data-menu="Windows"] .forge-pro-head')
            await page.wait_for_timeout(220)                 # the hover intent opens the Windows list
            strip = await page.evaluate("""() => {
              const item = [...document.querySelectorAll('#forge-pro-hotbox .forge-pro-col[data-menu="Windows"] .forge-pro-item')]
                .find((b) => b.dataset.proId === 'winChannel');          // Maya's "OpenChannelsLayers" row
              if (!item) return { found: false, ids: [...document.querySelectorAll('#forge-pro-hotbox .forge-pro-col[data-menu="Windows"] .forge-pro-item')].map((b) => b.dataset.proId) };
              const r = item.getBoundingClientRect();
              const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
              const ts = document.getElementById('titlestrip').getBoundingClientRect();
              return { found: true, top: r.top, stripBottom: ts.bottom, covered: !!top && top !== item && !item.contains(top),
                       who: top ? (top.id ? '#' + top.id : String(top.className).split(' ')[0]) : '' };
            }""")
            check("the hotbox's Windows > OpenChannelsLayers row opens clear of the title strip and is clickable (owner idea I5)",
                  strip.get("found") and not strip.get("covered") and strip.get("top", 0) >= strip.get("stripBottom", 0) - 1, strip)
            await page.evaluate("typeof forgeProHotboxHide === 'function' && forgeProHotboxHide()")
            await page.keyboard.down(" ")
            await page.wait_for_timeout(120)
            await page.hover('#forge-pro-hotbox .forge-pro-col[data-menu="Recent Commands"] .forge-pro-head')
            await page.wait_for_timeout(250)
            rec = await page.evaluate("""() => [...document.querySelectorAll('#forge-pro-hotbox .forge-pro-col[data-menu="Recent Commands"] .forge-pro-item[data-pro-id]')].map((b) => b.dataset.proId)""")
            await page.keyboard.up(" ")
            await page.keyboard.press("Escape")
            check("the hotbox's Recent Commands lists what you just ran, newest first", rec[:1] == ["winCreate"], rec)
            await page.keyboard.press("Escape")
            check("Esc never closes Forge", await page.is_visible("#forge"))

            # -------- snapping: hold x = grid, v = vertex, c = edge (objects, the pivot and components)
            sn = await page.evaluate("""() => { const v = forge.view, t = v.tree.api, tc = v.transform, V = v.THREE;
              const a = t.list().find((n) => n.name === 'pSphere1'), b = t.node(1);
              t.makeWorking(b.id); t.select(a.id); t.attachTool('translate');
              const drag = (to) => { a.grp.position.copy(to); tc.axis = 'XYZ'; tc.dispatchEvent({ type: 'objectChange' }); return a.grp.getWorldPosition(new V.Vector3()).toArray(); };
              v.pro.held.add('x'); const g = drag(new V.Vector3(0.61, 0.37, -0.13)); v.pro.held.delete('x');
              tc.axis = 'X'; v.pro.held.add('x'); a.grp.position.set(0.61, 0.37, -0.13); tc.dispatchEvent({ type: 'objectChange' }); v.pro.held.delete('x');
              const gx = a.grp.position.toArray(); tc.axis = 'XYZ';
              // v: put the mouse over a corner of the cube and drag the sphere: its pivot lands on that vertex
              const box = t.worldBox([b.id]), corner = new V.Vector3(box.max.x, box.max.y, box.max.z);
              const r = v.canvas.getBoundingClientRect(); v.camera.updateMatrixWorld(); const s = corner.clone().project(v.camera);
              v.pro.mouse = [r.left + (s.x + 1) / 2 * r.width, r.top + (1 - s.y) / 2 * r.height];
              v.pro.held.add('v'); const p = drag(new V.Vector3(2, 2, 2)); v.pro.held.delete('v');
              const pd = Math.hypot(p[0] - corner.x, p[1] - corner.y, p[2] - corner.z);
              // c: a point inside a face of the cube -> the nearest spot on that triangle's edges
              const mid = new V.Vector3((box.min.x + box.max.x) / 2 + (box.max.x - box.min.x) * 0.2, box.max.y - (box.max.y - box.min.y) * 0.05, box.max.z);
              const s2 = mid.clone().project(v.camera); v.pro.mouse = [r.left + (s2.x + 1) / 2 * r.width, r.top + (1 - s2.y) / 2 * r.height];
              v.pro.held.add('c'); const e = drag(new V.Vector3(3, 3, 3)); v.pro.held.delete('c');
              const tb = [box.min.toArray(), box.max.toArray()], near = (x, y) => Math.abs(x - y) < 1e-3;
              const onEdge = [0, 1, 2].filter((k) => near(e[k], tb[0][k]) || near(e[k], tb[1][k])).length >= 2;   // a cube's edge: two coordinates on its box
              tc.detach();
              return { g, gx, pd, e, onEdge, step: v.pro.gridStep }; }""")
            st = sn["step"]
            check("hold x: the object snaps to the grid", all(abs(c / st - round(c / st)) < 1e-6 for c in sn["g"]), sn)
            check("...and only along the handle's axis when you drag one arrow (X)", abs(sn["gx"][0] / st - round(sn["gx"][0] / st)) < 1e-6
                  and abs(sn["gx"][1] - 0.37) < 1e-6 and abs(sn["gx"][2] + 0.13) < 1e-6, sn["gx"])
            check("hold v: the pivot lands exactly on the vertex under the mouse (another object's corner)", sn["pd"] < 1e-4, sn)
            check("hold c: it lands on an edge of the face under the mouse", sn["onEdge"], sn)
            # the viewport's Grid / Edge / Point chips are hidden (owner 2026-10-21: not in the pro viewport); the status
            # line's snap buttons switch a snap on and off
            chips = await page.evaluate("[...document.querySelectorAll('#forge-snaps .forge-snap')].map((b) => b.dataset.snap)")
            chips_hidden = await page.evaluate("!document.getElementById('forge-snaps').offsetParent")
            await page.click('#fmy-status [data-pro-id="snapGrid"]')
            sticky = await page.evaluate("forge.view.pro.snap.grid && document.querySelector('#fmy-status [data-pro-id=\"snapGrid\"]').classList.contains('on')")
            await page.click('#fmy-status [data-pro-id="snapGrid"]')
            check("the snap buttons on the status line switch a snap on and off (the viewport chips are hidden)",
                  chips == ["grid", "edge", "point"] and chips_hidden and sticky, [chips, chips_hidden, sticky])
            comp = await page.evaluate("""() => { const v = forge.view, V = v.THREE, p = new V.Object3D(); v.holder.add(p);
              p.position.set(0.33, 0.12, 0.07); v.pro.held.add('x'); v.snapPivot(p); v.pro.held.delete('x');
              const w = p.getWorldPosition(new V.Vector3()).toArray(); v.holder.remove(p); return [w, v.pro.gridStep]; }""")
            check("components snap too: the component handle lands on the grid with x", all(abs(c / comp[1] - round(c / comp[1])) < 1e-6 for c in comp[0]), comp)
            check("there is a grid on the ground, like the standard one", await page.evaluate("!!(forge.view.pro.grid && forge.view.pro.grid.visible)"))
            await page.evaluate("forgeModelMode(true)")
            await page.keyboard.press("b")
            soft = await page.evaluate("forge.view.edit.prop")
            await page.keyboard.press("b")
            await page.keyboard.press("Alt+x")
            xr = await page.evaluate("forge.view.edit.xray")
            await page.keyboard.press("Alt+x")
            await page.evaluate("forgeModelMode(false)")
            check("b is soft selection, Alt+X is X-ray (the pro keys)", soft is True and xr is True, [soft, xr])

            # -------- the checks the first scene suite had (kept): rename, hide, indent, Channel Box, buttons, Shift+drag
            await page.evaluate("forgeModelMode(false)")
            rid = await page.evaluate(T + ".list().find((n) => n.name === 'pCube3').id")
            await page.evaluate(T + ".rename(%d, 'sidekick')" % rid)
            check("an object can be renamed", await page.evaluate(T + ".node(%d).name" % rid) == "sidekick")
            await page.evaluate(T + ".setVisible(%d, false)" % rid)
            check("an object can be hidden (and comes back)", await page.evaluate(T + ".node(%d).grp.visible" % rid) is False)
            await page.evaluate(T + ".setVisible(%d, true)" % rid)
            ind = await page.evaluate("""() => { const t = forge.view.tree.api, g = t.list().find((n) => n.kind === 'group');
              t.rename(g.id, 'parts'); g.open = true; t.select(g.id);
              return { renamed: t.node(g.id).name, indented: [...document.querySelectorAll('#forge-outliner .forge-out-row')].some((r) => parseFloat(r.style.paddingLeft) > 10) }; }""")
            check("a group can be renamed and the Outliner indents its children", ind["renamed"] == "parts" and ind["indented"], ind)
            await page.evaluate(T + ".select(%d)" % rid)
            await page.evaluate(T + ".resetTransform(%d)" % rid)
            await page.fill("#forge-ch-tx", "3")
            cx3 = await page.evaluate(T + ".transform(%d).translate[0]" % rid)
            check("the Channel Box moves the selected object by typing a number", abs(cx3 - 3) < 1e-6, cx3)
            await page.fill("#forge-ch-ry", "90")
            ry = await page.evaluate(T + ".node(%d).grp.rotation.y * 180 / Math.PI" % rid)
            check("...and rotates in degrees, the way the pro Channel Box shows them", abs(ry - 90) < 1e-3, ry)
            await page.evaluate(T + ".select(1)")
            other = await page.evaluate("document.getElementById('forge-ch-tx').value")
            await page.evaluate(T + ".select(%d)" % rid)
            back3 = await page.evaluate("document.getElementById('forge-ch-tx').value")
            check("the numbers follow the selection", back3 == "3" and other != "3", [other, back3])
            # The panel is taller than the left column on a small window, so no geometric test can see all of its
            # controls at once - that is ordinary scrolling, not a fault. Ask what is true regardless of scroll:
            # each control is in the document, enabled and not hidden... and then prove clickability for real by
            # clicking Reset and watching the transformation actually reset.
            present = await page.evaluate("""() => ['forge-ch-reset', 'forge-ch-pivot', 'forge-ch-rpivot', 'forge-ch-freeze', 'forge-ch-dup', 'forge-ch-group', 'forge-hist-clear'].map((id) => {
              const b = document.getElementById(id);
              return [id, !!b && !b.disabled && b.offsetParent !== null];
            })""")
            check("Reset, Pivot, Reset Pivot, Freeze, Copy, Group and Delete History are all on the panel",
                  all(ok for _, ok in present), present)
            # the Outliner's right-click menu is still open from the check above and covers the panel: close it
            await page.evaluate("const m = document.querySelector('.forge-out-menu'); if (m) m.remove()")
            await page.evaluate(T + ".setTransform(%d, 'translate', 0, 3)" % rid)
            await page.click("#forge-ch-reset")                     # a real click: Playwright scrolls to it itself
            await page.wait_for_timeout(80)
            reset_tr = await page.evaluate(T + ".transform(%d).translate" % rid)   # the node's translate, not grp.position
            check("...and Reset really is clickable: it clears the transformation",
                  all(abs(v) < 1e-6 for v in reset_tr), reset_tr)
            await page.evaluate("document.getElementById('forge-ch-reset').click()")
            rs = await page.evaluate(T + ".transform(%d)" % rid)
            check("Reset puts the selected object back to 0 / 0 / 1", rs["translate"] == [0, 0, 0] and rs["rotate"] == [0, 0, 0], rs)
            n_before = await page.evaluate(T + ".list().length")
            await page.evaluate(T + ".select(%d)" % rid)
            await page.evaluate("forge.view.toggleTransform('translate')")
            await page.keyboard.down("Shift")
            await page.evaluate("forge.view.transform.dispatchEvent({ type: 'dragging-changed', value: true })")
            await page.keyboard.up("Shift")
            sd = await page.evaluate("""() => { const t = forge.view.tree.api, c = t.active();
              return { nodes: t.list().length, root: !!c.root, onGizmo: forge.view.transform.object === c.grp, orig: t.node(%d).grp.visible }; }""" % rid)
            await page.evaluate("forge.view.transform.dispatchEvent({ type: 'dragging-changed', value: false }); forge.view.toggleTransform(null)")
            check("Shift+drag leaves the original and hands the manipulator to a copy", sd["nodes"] == n_before + 1 and not sd["root"] and sd["onGizmo"], sd)

        if PART == "3":   # tests/test_forge_pro3_ui.py
            # -------- Forge dressed as a pro package (app/ui/forge_chrome.js): checked against the reference package on the owner's Mac
            await page.evaluate("forgeModelMode(false)")
            await page.evaluate("forgeProPanel('outliner', true); forgeProPanel('channel', true)")
            look = await page.evaluate("""() => { const p = document.querySelector('#forge .forge-panel');
              return { bg: getComputedStyle(p).backgroundColor,
                       menus: [...document.querySelectorAll('#fmy-menubar .fmy-mb')].map((b) => b.dataset.menu),
                       panelMenus: [...document.querySelectorAll('#fmy-panelbar .fmy-pmb:not(.fmy-pfold)')].map((b) => b.dataset.menu),
                       shelfTabs: [...document.querySelectorAll('#fmy-shelf .fmy-stab')].map((b) => b.dataset.tab),
                       tools: document.querySelectorAll('#fmy-toolbox .fmy-ib').length,
                       stage: getComputedStyle(document.getElementById('forge-stage')).backgroundImage }; }""")
            check("the dark, high-contrast panel (#2b2c2f, owner 17:06) and its menu bar: File Edit Create Select Modify Display Windows Mesh 'Edit Mesh' 'Mesh Tools' 'Mesh Display' Help",
                  look["bg"] == "rgb(43, 44, 47)" and look["menus"][:8] == ["File", "Edit", "Create", "Select", "Modify", "Display", "Windows", "Mesh"]
                  and "Edit Mesh" in look["menus"] and "Mesh Tools" in look["menus"], look)
            check("the viewport has its own menus (View Shading Lighting Show Renderer Panels), the shelf its tabs, a tool box",
                  look["panelMenus"] == ["View", "Shading", "Lighting", "Show", "Renderer", "Panels"] and look["shelfTabs"][:2] == ["Poly Modeling", "Sculpting"]
                  and look["tools"] >= 8 and "128, 153, 184" in look["stage"] and "11, 12, 14" in look["stage"], look)
            # Create > Cube from the menu bar makes a new pCube
            n0 = await page.evaluate(T + ".list().length")
            await page.click('#fmy-menubar .fmy-mb[data-menu="Create"]')
            await page.click('.fmy-drop .fmy-dsub[data-sub="Polygon Primitives"]')
            await page.click('.fmy-subdrop .fmy-ditem[data-pro-id="cube"]')
            await page.evaluate("forgeModelMode(false)")
            made = await page.evaluate("[forge.view.tree.api.list().length, forge.view.tree.api.root().name]")
            check("Create > Cube in the menu bar makes a new pCube (and the menu closes)", made[0] == n0 + 1 and made[1].startswith("pCube")
                  and not await page.evaluate("!!document.querySelector('.fmy-drop')"), [n0, made])
            hud = await page.evaluate("""() => { forge.view.tree.api.select(forge.view.tree.api.root().id); fmySync();
              const row = (k) => [...document.querySelector('#fmy-polycount tr[data-k="' + k + '"]').cells].slice(1).map((c) => +c.textContent);
              return { verts: row('verts'), faces: row('faces'), edges: row('edges'), cam: document.getElementById('fmy-camname').textContent }; }""")
            check("the heads-up poly count: the selected cube reads 8 verts, 12 edges, 6 faces (the pro middle column)",
                  hud["verts"][1] == 8 and hud["edges"][1] == 12 and hud["faces"][1] in (6, 12) and hud["verts"][0] > 8 and hud["cam"] == "persp", hud)
            wire = await page.evaluate("""() => { const t = forge.view.tree.api, n = t.root(); let lines = 0, box = 0;
              n.inner.traverse((o) => { if (o.name === 'forge-sel') { o.traverse((c) => { if (c.isLineSegments && !c.isBox3Helper) lines++; if (c.type === 'Box3Helper') box++; }); } });
              return [lines, box]; }""")
            check("a selected object shows the pro wireframe in the selection colour, not a box", wire[0] >= 1 and wire[1] == 0, wire)
            # the shelf: hidden at first (owner 17:06: "we don't need shelves"), Windows > UI Elements > Shelf brings it
            shelf0 = await page.evaluate("document.getElementById('fmy-shelf').hidden")
            await page.evaluate("fmyUiSet('shelfbar', true)")
            check("the shelf starts hidden and comes back from UI Elements", shelf0 and not await page.evaluate("document.getElementById('fmy-shelf').hidden"))
            await page.click('#fmy-shelf .fmy-stab[data-tab="Poly Modeling"]')
            await page.click('#fmy-shelf .fmy-shelf-btn[data-pro-id="sphere"]')
            await page.evaluate("forgeModelMode(false)")
            check("the shelf's sphere makes a pSphere", (await page.evaluate(T + ".root().name")).startswith("pSphere"))
            # the tool box and the status line follow the tool and the selection mode
            await page.click('#fmy-toolbox .fmy-ib[data-pro-id="rotate"]')
            await page.evaluate("fmySync()")
            tb = await page.evaluate("[forge.view.transform.mode, document.querySelector('#fmy-toolbox [data-pro-id=\"rotate\"]').classList.contains('on')]")
            await page.click('#fmy-status .fmy-selmode[data-pro-id="vertex"]')
            await page.wait_for_timeout(150)
            await page.evaluate("fmySync()")
            sm = await page.evaluate("[forge.view.mode, forge.view.edit.mode, document.querySelector('#fmy-status [data-pro-id=\"vertex\"]').classList.contains('on')]")
            await page.click('#fmy-status .fmy-selmode[data-pro-id="objectMode"]')
            await page.wait_for_timeout(150)
            check("the tool box's Rotate is the pro rotate tool and lights up", tb == ["rotate", True], tb)
            check("the status line's vertex button is component mode, vertices (and lights up); Object goes back", sm == ["poly", "vert", True]
                  and await page.evaluate("forge.view.mode") == "view", sm)
            await page.click('#fmy-status [data-pro-id="snapGrid"]')
            sg = await page.evaluate("forge.view.pro.snap.grid")
            await page.click('#fmy-status [data-pro-id="snapGrid"]')
            check("the status line's snap buttons switch the pro snapping (grid here)", sg is True and not await page.evaluate("forge.view.pro.snap.grid"))
            # the viewport's own Panels menu looks through the top camera; the view cube's FRONT looks from the front
            await page.click('#fmy-panelbar .fmy-pmb[data-menu="Panels"]')
            await page.click('.fmy-drop .fmy-ditem[data-pro-id="top"]')
            await page.evaluate("fmySync()")
            topcam = await page.evaluate("[forge.view.cam, document.getElementById('fmy-camname').textContent]")
            await page.evaluate("document.querySelector('#fmy-cube .fmy-cf-front').click()")
            await page.evaluate("fmySync()")
            frontcam = await page.evaluate("forge.view.cam")
            await page.evaluate("forgeProRun(forge.view, 'persp')")
            check("Panels > top looks through top (the HUD says 'top'); the view cube's FRONT looks from the front", topcam == ["top", "top"] and frontcam == "front", [topcam, frontcam])
            # the command line runs the pro commands
            await page.fill("#fmy-cmd", "polySphere; move 0 2 0")
            await page.press("#fmy-cmd", "Enter")
            await page.wait_for_timeout(150)
            cl = await page.evaluate("""() => { const t = forge.view.tree.api, n = t.active(); return [n.name, t.transform(n.id).translate[1], document.getElementById('fmy-result').textContent]; }""")
            await page.fill("#fmy-cmd", "select -cl; nosuch")
            await page.press("#fmy-cmd", "Enter")
            cl2 = await page.evaluate("[forge.view.tree.api.selected().length, document.getElementById('fmy-result').textContent]")
            await page.evaluate("forgeModelMode(false)")
            check("the command line: polySphere; move 0 2 0 makes a sphere at y = 2, and says so", cl[0].startswith("pSphere") and abs(cl[1] - 2) < 1e-6 and "Result" in cl[2], cl)
            check("...select -cl clears the selection, and an unknown word is an error like the standard one", cl2[0] == 0 and "Cannot find procedure" in cl2[1], cl2)
            # the Channel Box: the pro channels (now including Rotate Order, patch 368), a scrub on a channel's name, SHAPES and INPUTS (the history)
            cb = await page.evaluate("""() => { const t = forge.view.tree.api; t.select(t.list().find((n) => n.name.startsWith('pCube')).id);
              return { rows: [...document.querySelectorAll('#forge-channel .forge-ch-row:not([hidden]) .forge-ch-label')].map((l) => l.textContent),
                       shape: document.querySelector('#forge-channel .forge-ch-node').textContent, name: document.getElementById('forge-ch-name').textContent }; }""")
            check("the Channel Box lists Translate X ... Scale Z, Rotate Order and Visibility, the object's name, and its shape under SHAPES",
                  cb["rows"] == ["Translate X", "Translate Y", "Translate Z", "Rotate X", "Rotate Y", "Rotate Z",
                                 "Scale X", "Scale Y", "Scale Z", "Rotate Order", "Visibility"]
                  and cb["shape"] == cb["name"] + "Shape", cb)
            lbl = await (await page.query_selector('#forge-channel .forge-ch-row .forge-ch-label')).bounding_box()
            tx0 = await page.evaluate(T + ".transform().translate[0]")
            await page.mouse.move(lbl["x"] + lbl["width"] / 2, lbl["y"] + lbl["height"] / 2)
            await page.mouse.down(); await page.mouse.move(lbl["x"] + lbl["width"] / 2 + 40, lbl["y"] + lbl["height"] / 2, steps=4); await page.mouse.up()
            tx1 = await page.evaluate(T + ".transform().translate[0]")
            check("dragging a channel's name scrubs its value (the pro virtual slider)", tx1 > tx0 + 0.5, [tx0, tx1])
            await page.evaluate("forgeModelMode(true)")
            await page.evaluate("forge.view.select([0]); forgeFaceOp('extrude')")
            inputs = await page.evaluate("[...document.querySelectorAll('#forge-history .forge-hist-name')].map((n) => n.textContent)")
            await page.evaluate("forgeModelMode(false)")
            check("INPUTS lists the history with the pro node names (polyExtrudeFace1)", inputs[:1] == ["polyExtrudeFace1"], inputs)
            # the Outliner: the four cameras, greyed, then the scene; the search field filters
            cams = await page.evaluate("[...document.querySelectorAll('#forge-out-list .forge-out-cam')].map((r) => r.dataset.cam)")
            await page.fill("#forge-out-search", "psphere")
            found = await page.evaluate("[...document.querySelectorAll('#forge-out-list .forge-out-row .forge-out-name')].map((n) => n.textContent)")
            await page.fill("#forge-out-search", "")
            check("the Outliner shows persp / top / front / side first, and its search finds by name", cams == ["persp", "top", "front", "side"]
                  and found and all(f.lower().startswith("psphere") for f in found), [cams, found])
            # Ctrl+Space hides the pro UI elements as well, and brings them back
            await page.press("#forge-out-search", "Escape")       # Esc leaves the search field, the keys go back to Forge
            await page.mouse.move(cx, cy)
            await page.keyboard.press("Control+Space")
            gone = await page.evaluate("['fmy-status', 'fmy-shelf', 'fmy-toolbox', 'fmy-helpline'].map((id) => document.getElementById(id).hidden)")
            await page.keyboard.press("Control+Space")
            back = await page.evaluate("['fmy-status', 'fmy-shelf', 'fmy-toolbox', 'fmy-helpline'].map((id) => document.getElementById(id).hidden)")
            if not any(gone):                                   # something was folded already: the first press showed everything
                await page.keyboard.press("Control+Space")
                gone = await page.evaluate("['fmy-status', 'fmy-shelf', 'fmy-toolbox', 'fmy-helpline'].map((id) => document.getElementById(id).hidden)")
                await page.keyboard.press("Control+Space")
                back = await page.evaluate("['fmy-status', 'fmy-shelf', 'fmy-toolbox', 'fmy-helpline'].map((id) => document.getElementById(id).hidden)")
            check("Ctrl+Space hides the status line, shelf, tool box and help line too, and brings them back", all(gone) and not any(back), [gone, back])

        check("no script errors", not errors, errors[:5])
        await browser.close()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 58))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
