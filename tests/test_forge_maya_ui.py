"""Forge the way Maya works (app/ui/forge_maya.js + app/ui/forge_scene.js, spec docs/FORGE_MAYA_SPEC.md) in
headless Chromium: Maya's hotkeys (Ctrl and Cmd alike), the camera on Alt, the hotbox and its zones, the Space tap
between one and four views, context marking menus picked by direction, Create making NEW objects, Duplicate /
Duplicate with Transform, Group with its pivot at the centre, real pivots (move / centre / reset / freeze keep the
object still and the Channel Box's translate unchanged), parent / unparent, hide / show, pick-walk, viewport
click and box selection with Maya's modifiers, the Outliner's range / toggle selection and drag-and-drop, every
object editable (the tools' mesh moves into the one you edit), pivot edit mode (d), view undo ([) and the
Blender hotkey set. No engine, no model download: everything starts from primitives. Under a minute.

    python tests/test_forge_maya_ui.py
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
        await page.goto("http://127.0.0.1:8899/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("localStorage.removeItem('loki-forge-keymap')")
        await page.click("#open-forge")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
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
        check("a primitive is named the Maya way (pCube1)", names == ["pCube1"], names)
        await page.evaluate("forgeAddPrimitive('sphere')")
        await page.evaluate("forgeModelMode(false)")
        made = await page.evaluate("""() => { const t = forge.view.tree.api;
          return { names: t.list().map((n) => n.name), root: t.root().name, cubeTris: t.node(1).inner.children.some((o) => o.isMesh && o.name === 'shape') }; }""")
        check("Create adds a NEW object - the cube is still in the scene (Maya)", made["names"] == ["pCube1", "pSphere1"]
              and made["root"] == "pSphere1" and made["cubeTris"], made)

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

        # -------- the camera: Alt / Option
        btn = "() => { const b = forge.view.maya.controls.mouseButtons; return [b.LEFT, b.MIDDLE, b.RIGHT]; }"
        bare = await page.evaluate(btn)
        await page.keyboard.down("Alt")
        alt = await page.evaluate(btn)
        await page.keyboard.up("Alt")
        back = await page.evaluate(btn)
        check("without Alt no button turns the camera (left selects, right is the marking menu)", bare == [None, None, None], bare)
        check("Alt + left / middle / right = tumble / track / dolly", alt == [0, 2, 1], alt)   # THREE.MOUSE ROTATE 0, DOLLY 1, PAN 2
        check("...and back on release", back == [None, None, None], back)

        # -------- the Space wheel: it floats WHERE THE MOUSE IS; hovering a wedge brings that menu down
        # (owner 2026-10-20: "i want the space bar menue to float where my mouse is just like maya not a newhud
        # its like a wheel and when you hover over it brings down a new menue")
        await page.mouse.move(cx, cy)
        await page.keyboard.down(" ")
        await page.wait_for_timeout(140)
        wh = await page.evaluate("""([x, y]) => { const h = document.getElementById('forge-maya-wheel');
          if (!h) return null;
          const r = h.getBoundingClientRect();
          return { vis: !h.hidden, heads: [...h.querySelectorAll('.forge-wheel-wedge')].map((b) => b.dataset.mayaHead),
                   dx: Math.round(r.left - x), dy: Math.round(r.top - y) }; }""", [cx, cy])
        wb = await (await page.query_selector("#forge-maya-wheel .forge-wheel-wedge")).bounding_box()
        await page.mouse.move(wb["x"] + wb["width"] / 2, wb["y"] + wb["height"] / 2)
        await page.wait_for_timeout(150)
        wsub = await page.evaluate("""() => { const s = document.querySelector('#forge-maya-wheel .forge-wheel-sub');
          return s ? { head: s.dataset.head, n: s.querySelectorAll('.forge-wheel-item').length } : null; }""")
        await page.keyboard.up(" ")
        await page.wait_for_timeout(120)
        check("Space floats a wheel AT THE MOUSE (10 menus)", wh and wh["vis"] and len(wh["heads"]) >= 9
              and abs(wh["dx"]) < 26 and abs(wh["dy"]) < 26, wh)
        check("hovering a wedge brings that menu down beside it", bool(wsub) and wsub["n"] >= 2, wsub)
        check("the menu stays open after releasing Space, so an item can be clicked",
              not await page.evaluate("document.getElementById('forge-maya-wheel').hidden"))
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(120)
        check("Escape puts the wheel away", await page.evaluate("document.getElementById('forge-maya-wheel').hidden"))

        # -------- every panel can hide, with a slide or a fold, and it is remembered
        await page.evaluate("forgePanels.hideAll()")
        await page.wait_for_timeout(280)
        hid = await page.evaluate("""() => ({ bare: document.getElementById('forge').classList.contains('forge-bare'),
          out: document.getElementById('forge-outliner').classList.contains('collapsed'),
          side: document.getElementById('forge-left').classList.contains('collapsed'),
          stored: JSON.parse(localStorage.getItem('loki-forge-panels') || '{}') })""")
        check("hide all: the left column slides away, the Outliner folds and the bars clear - and it sticks",
              hid["bare"] and hid["out"] and hid["side"] and hid["stored"].get("floats") is False, hid)
        await page.click("#forge-ui-btn")
        await page.wait_for_timeout(280)
        back = await page.evaluate("""() => ({ bare: document.getElementById('forge').classList.contains('forge-bare'),
          out: document.getElementById('forge-outliner').classList.contains('collapsed') })""")
        check("the UI button in the title brings every panel back", not back["bare"] and not back["out"], back)
        await page.keyboard.press(" ")
        quad = await page.evaluate("forge.view.quad")
        await page.mouse.move(vb["x"] + vb["width"] * 0.25, vb["y"] + vb["height"] * 0.25)
        await page.keyboard.press(" ")
        after = await page.evaluate("[forge.view.quad, forge.view.cam]")
        check("a Space tap goes to four views; a tap over the top-left pane makes Front big", quad is True and after == [False, "front"], [quad, after])
        # the hotbox's centre zone (the full Maya layout, still reached from the wheel's last entry)
        await page.evaluate("forgeMayaHotboxOpen(forge.view, [%d, %d])" % (cx, cy))
        await page.mouse.move(cx, cy)
        await page.wait_for_timeout(260)
        await page.mouse.down()
        await page.mouse.move(cx, cy - 70, steps=4)
        zone = await page.evaluate("document.getElementById('forge-maya-marking').dataset.set")
        await page.mouse.up()
        await page.keyboard.up(" ")
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
        ring = await page.evaluate("Object.fromEntries([...document.querySelectorAll('#forge-maya-marking .forge-maya-wedge')].map((b) => [b.dataset.pos, b.dataset.mayaCmd]))")
        await page.mouse.move(p1[1] + 75, p1[2] + 6, steps=4)                     # a flick east, not onto the button
        await page.mouse.up(button="right")
        await page.wait_for_timeout(250)
        st = await page.evaluate("[forge.view.mode, forge.view.edit && forge.view.edit.mode, forge.view.tree.api.root().id]")
        check("right button on an object: Maya's ring (N Edge, W Vertex, E Face, S UV, NE Object Mode)",
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
        title = await page.evaluate("document.getElementById('forge-maya-marking').dataset.set")
        await page.mouse.move(vb["x"] + 32, vb["y"] + vb["height"] - 40, steps=4)
        await page.mouse.up(button="right")
        await page.keyboard.up("Shift")
        await page.wait_for_timeout(250)
        await page.evaluate("forgeModelMode(false)")
        n1 = await page.evaluate("[forge.view.tree.api.list().length, forge.view.tree.api.root().name]")
        check("Shift + right button on nothing is Maya's Create ring; flicking south makes a new cube", title == "Create"
              and n1 == [n0 + 1, "pCube2"], [title, n0, n1])

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
        check("Ctrl+G groups: a group1 node with both inside, translate 0 (Maya)", g["kind"] == "group" and g["name"] == "group1"
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
        check("p parents the first under the LAST selected (Maya)", pp == par[1], [pp, par])
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
        # macOS turns Ctrl+click into a SECONDARY click (the row's own menu), so the toggle is Cmd there -
        # which is the Mac convention anyway, and the handler takes either.
        toggle_mod = "Meta" if sys.platform == "darwin" else "Control"
        await page.keyboard.down(toggle_mod)
        await page.click('#forge-outliner .forge-out-row[data-id="%d"] .forge-out-name' % rows[1])
        await page.keyboard.up(toggle_mod)
        tog = await page.evaluate(T + ".selected()")
        check("Outliner: Shift+click selects a range, Ctrl/Cmd+click toggles one out",
              sorted(rng) == sorted(rows[:3]) and sorted(tog) == sorted([rows[0], rows[2]]), [rows, rng, tog, toggle_mod])
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

        # -------- pivot edit (hold d): the manipulator moves the pivot, the object stays
        await page.evaluate(T + ".select(1)")
        await page.keyboard.down("d")
        pe = await page.evaluate("""() => { const t = forge.view.tree.api, v = forge.view, m = v.maya, V = v.THREE, near = %s;
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
        vu = await page.evaluate("forge.view.camera.fov")
        check("[ undoes the last view change", vu > 10, vu)

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

        # -------- the Blender set brings Blender's edit keys back; Maya again by default
        await page.evaluate("forgeSetKeymap('blender')")
        await page.evaluate("forgeModelMode(true)")
        await page.keyboard.press("2")
        bl = await page.evaluate("forge.view.edit.mode")
        bbtn = await page.evaluate(btn)
        await page.evaluate("forgeSetKeymap('maya')")
        await page.keyboard.press("2")
        mm = await page.evaluate("forge.view.edit.mode")
        await page.evaluate("forgeModelMode(false)")
        check("Hotkeys: Blender - 2 is edge mode and the left button orbits; Maya set - 2 does nothing there", bl == "edge"
              and bbtn[0] == 0 and mm == "edge", [bl, bbtn, mm])

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
        check("...and rotates in degrees, the way Maya's Channel Box shows them", abs(ry - 90) < 1e-3, ry)
        await page.evaluate(T + ".select(1)")
        other = await page.evaluate("document.getElementById('forge-ch-tx').value")
        await page.evaluate(T + ".select(%d)" % rid)
        back3 = await page.evaluate("document.getElementById('forge-ch-tx').value")
        check("the numbers follow the selection", back3 == "3" and other != "3", [other, back3])
        clickable = await page.evaluate("""() => ['forge-ch-reset', 'forge-ch-pivot', 'forge-ch-rpivot', 'forge-ch-freeze', 'forge-ch-dup', 'forge-ch-group', 'forge-hist-clear'].map((id) => {
          const b = document.getElementById(id); if (!b) return [id, false];
          b.scrollIntoView({ block: 'center' });
          const r = b.getBoundingClientRect(), el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return [id, el === b || b.contains(el)]; })""")
        check("Reset, Pivot, Reset Pivot, Freeze, Copy, Group and Delete History are on the panel and really clickable", all(ok for _, ok in clickable), clickable)
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

        check("no script errors", not errors, errors[:5])
        await browser.close()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 58))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
