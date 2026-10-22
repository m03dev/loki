"""Forge's undo queue, hotkey table and manipulator (2026-10-21) in headless Chromium:

- undo / redo cover the SCENE, not just the mesh: Create, Delete, Group, a typed channel, editing another object -
  each one step, in order, and editing another object no longer empties the queue (owner: "the history in forge
  doesn't work");
- Shift + drag on a face manipulator extrudes, then moves the new faces - one undo step, and the construction history
  gets the extrude and the move (polyTweak), so changing an earlier step keeps the move;
- the manipulator is drawn the pro way (one-way arrows, a camera-facing centre square, front-half rotate rings) and
  turns orange while Shift is held over a handle, with the help line saying what Shift will do;
- the hotkeys are a table (app/ui/forge_keys.js): the pro default set, chords for Ctrl/Cmd/Alt/Shift, a locked
  Default set, your own set made by binding a key, the Hotkey Editor capturing a key press, export / import.
No engine, no model download. Under a minute.

    python tests/test_forge_undo_keys_ui.py
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
NAMES = T + ".list().map((n) => n.name + (n.root ? '*' : ''))"


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
            bare = r.request.url.split("8897", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8897/**", route)
        await page.goto("http://127.0.0.1:8897/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("localStorage.removeItem('loki-forge-hotkeys')")
        await page.evaluate("document.getElementById('open-forge').click()")
        await page.wait_for_selector("#forge:not([hidden])", timeout=15000)
        E = page.evaluate
        await E("forgeAddPrimitive('cube')")
        await page.wait_for_function("forge.view && forge.view.sm && forge.view.tree", timeout=10000)
        await E("forgeModelMode(false)")

        # -------- the scene is in the undo queue
        await E("forgeAddPrimitive('sphere')")
        await E("forgeModelMode(false)")
        made = await E(NAMES)
        await E("forgeProRun(forge.view, 'undo')")
        undone = await E(NAMES)
        await E("forgeProRun(forge.view, 'redo')")
        redone = await E(NAMES)
        check("Create is one undo step: undo takes the sphere away and gives the cube back to the tools, redo returns it",
              made == ["pCube1", "pSphere1*"] and undone == ["pCube1*"] and redone == ["pCube1", "pSphere1*"], [made, undone, redone])
        cube = await E(T + ".list()[0].id")
        await E(T + ".select(%d)" % cube)
        await E(T + ".setTransform(null, 'translate', 0, 2.5)")
        await E("forgeProRun(forge.view, 'group')")
        grouped = await E(NAMES)
        await E("forgeProRun(forge.view, 'undo')")
        after_g = await E(NAMES)
        tx_kept = await E(T + ".transform().translate[0]")
        await E("forgeProRun(forge.view, 'undo')")
        tx_undone = await E(T + ".transform().translate[0]")
        check("Group and a channel edit undo one at a time, newest first",
              "group1" in grouped and after_g == ["pCube1", "pSphere1*"] and abs(tx_kept - 2.5) < 1e-6 and abs(tx_undone) < 1e-6,
              [grouped, after_g, tx_kept, tx_undone])
        await E(T + ".select(%d)" % cube)
        await E("forgeProRun(forge.view, 'delete')")
        deleted = await E(NAMES)
        await E("forgeProRun(forge.view, 'undo')")
        back = await E(NAMES + ".concat(" + T + ".list().map((n) => !!n.grp.parent))")
        check("Delete undoes: the object is back in the scene with its mesh",
              deleted == ["pSphere1*"] and back[:2] == ["pCube1", "pSphere1*"] and all(back[2:]), [deleted, back])
        n_before = await E("forge.view.undoStack.length")
        await E(T + ".makeWorking(%d)" % cube)
        n_after = await E("forge.view.undoStack.length")
        await E("forgeProRun(forge.view, 'undo')")
        work_back = await E(NAMES)
        check("editing another object keeps the queue (one step more) and undoes back to the old one",
              n_after == n_before + 1 and work_back == ["pCube1", "pSphere1*"], [n_before, n_after, work_back])
        msg = await E("""() => { const v = forge.view; v.undoStack.length = 0; v.undo(); return document.getElementById('forge-status').textContent; }""")
        check("an empty queue says so (the pro message)", "no more commands to undo" in msg.lower(), msg)

        # -------- Shift + drag on a face manipulator: extrude + move, one step, in the history
        await E("forgeAddPrimitive('cube')")
        await E("forge.view.select([0]); forge.view.setTool('translate')")
        await page.wait_for_timeout(150)
        pt = await E("""(() => { const v = forge.view, g = v.gizmo, THREE = v.internals.THREE; g.getHelper().updateMatrixWorld(true);
          const c = v.internals.camera, r = v.internals.canvas.getBoundingClientRect();
          const s = g._gizmo.gizmo.translate.children.find((h) => h.name === 'Y'); s.geometry.computeBoundingBox();
          const q = s.geometry.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(s.matrixWorld).project(c);
          return [r.left + (q.x + 1) / 2 * r.width, r.top + (1 - q.y) / 2 * r.height]; })()""")
        await page.mouse.move(pt[0], pt[1])
        await page.wait_for_timeout(80)
        axis = await E("forge.view.gizmo.axis")
        await page.keyboard.down("Shift")
        await E("forge.view.dirty = true")
        await page.wait_for_timeout(120)
        await E("forge.view.gizmo.getHelper().updateMatrixWorld(true)")   # the handle's look is set when it is drawn
        look = await E("""() => ({ col: forge.view.gizmo._gizmo.materialLib.active.color.getHexString(),
          help: (document.getElementById('fmy-help') || {}).textContent || '' })""")
        check("Shift over a handle turns it orange and the help line says the drag will extrude",
              axis == "Y" and look["col"] == "ff9a1e" and "extrude" in look["help"].lower(), [axis, look])
        faces0 = await E("forge.view.poly.f.length")
        steps0 = await E("forge.view.undoStack.length")
        await page.mouse.down()
        for i in range(5):
            await page.mouse.move(pt[0], pt[1] - 8 * (i + 1))
            await page.wait_for_timeout(25)
        await page.mouse.up()
        await page.keyboard.up("Shift")
        ex = await E("""() => ({ faces: forge.view.poly.f.length, hist: window.forgeHistory.list().map((h) => h.kind),
          steps: forge.view.undoStack.length })""")
        await E("forgeProRun(forge.view, 'undo')")
        ex_undo = await E("forge.view.poly.f.length")
        await E("forgeProRun(forge.view, 'redo')")
        check("Shift + drag extrudes the face and moves it: 4 new side faces, extrude + polyTweak in the history, ONE undo step",
              ex["faces"] == faces0 + 4 and ex["hist"][-2:] == ["extrude", "tweak"] and ex["steps"] == steps0 + 1 and ex_undo == faces0,
              [faces0, ex, steps0, ex_undo])
        rows = await E("[...document.querySelectorAll('#forge-hist-list .forge-hist-name')].map((x) => x.textContent)")
        check("INPUTS names the move polyTweak", any(r.startswith("polyTweak") for r in rows), rows)

        # -------- the manipulator looks like the pro handles
        sty = await E("""() => { const g = forge.view.gizmo._gizmo, t = g.gizmo.translate.children, r = g.gizmo.rotate.children;
          const neg = t.filter((h) => h.name === 'X').some((h) => { h.geometry.computeBoundingBox(); return h.geometry.boundingBox.min.x < -0.05; });
          return { styled: !!g.forgeStyled, center: t.some((h) => h.name === 'XYZ' && h.userData.faceCamera), oneWay: !neg,
            rings: r.filter((h) => /^[XYZ]$/.test(h.name)).length, view: r.some((h) => h.name === 'E'),
            obj: !!(forge.view.transform && forge.view.transform._gizmo.forgeStyled) }; }""")
        check("the manipulator is the pro one: one-way arrows, a screen-facing centre square, 3 rings + the view ring",
              sty["styled"] and sty["obj"] and sty["center"] and sty["oneWay"] and sty["rings"] == 3 and sty["view"], sty)

        # -------- the middle button drags the manipulator from anywhere (the last handle used, else the view plane)
        await E("forgeModelMode(false)")
        await E(T + ".select(" + T + ".list()[0].id); forgeProRun(forge.view, 'move')")
        await page.wait_for_timeout(100)
        x0 = await E(T + ".transform().translate")
        n0 = await E("forge.view.undoStack.length")
        await page.mouse.move(420, 640)
        await page.mouse.down(button="middle")
        for i in range(5):
            await page.mouse.move(420 + 14 * (i + 1), 640)
            await page.wait_for_timeout(20)
        await page.mouse.up(button="middle")
        mm = await E("[" + T + ".transform().translate, forge.view.undoStack.length, (forge.view.undoStack[forge.view.undoStack.length - 1] || {}).label]")
        check("a middle-button drag anywhere moves the selection with the manipulator - one 'Move' undo step",
              abs(mm[0][0] - x0[0]) > 0.05 and mm[1] == n0 + 1 and mm[2] == "Move", [x0, mm])

        # -------- hotkeys: a table
        ch = await E("""() => { const K = (o) => forgeKeyChord(Object.assign({ key: '', code: '', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false }, o));
          return [K({ key: 'z', code: 'KeyZ', metaKey: true, shiftKey: true }), K({ key: '∂', code: 'KeyD', altKey: true }),
                  K({ key: '>', code: 'Period', shiftKey: true }), K({ key: 'F9', code: 'F9' }), K({ key: 'D', code: 'KeyD', shiftKey: true }),
                  K({ key: '1', code: 'Digit1', ctrlKey: true }), K({ key: 'Shift', code: 'ShiftLeft', shiftKey: true })]; }""")
        check("keys become chords: Cmd = Ctrl, Option+D on a Mac is alt+d, > is >, Shift+D is shift+d",
              ch == ["ctrl+shift+z", "alt+d", ">", "f9", "shift+d", "ctrl+1", ""], ch)
        dflt = await E("""() => [forgeHotkeys.action('w'), forgeHotkeys.action('ctrl+z'), forgeHotkeys.action('shift+z'),
          forgeHotkeys.action('alt+shift+d'), forgeHotkeys.action('ctrl+d'), forgeHotkeys.action('f8'), forgeHotkeys.active()]""")
        check("the default set is the pro one (w Move, Ctrl+Z / Shift+Z, Alt+Shift+D Delete History, F8)",
              dflt == ["move", "undo", "redo", "deleteHistory", "duplicate", "objComp", "Default"], dflt)
        await E("forgeModelMode(false)")
        await E(T + ".select(" + T + ".list()[0].id)")
        await page.mouse.move(650, 430)
        await page.keyboard.press("Alt+d")
        sel_none = await E(T + ".selected().length")
        check("Alt+D runs Select None through the table", sel_none == 0, sel_none)
        bound = await E("""() => { const set = forgeHotkeys.bind('k', 'frameAll'); return { set, act: forgeHotkeys.action('k'),
          dflt: forgeHotkeys.defaults().k || null, sets: forgeHotkeys.sets() }; }""")
        check("binding a key copies the locked Default set into your own and uses it",
              bound["set"] == "My_Hotkeys" and bound["act"] == "frameAll" and bound["dflt"] is None and "Default" in bound["sets"], bound)
        await E("forgeHotkeys.bind('w', 'scale')")
        await E(T + ".select(" + T + ".list()[0].id)")
        await page.keyboard.press("w")
        tool = await E("forge.view.transform.object ? forge.view.transform.mode : null")
        check("a re-bound key does the new thing (w = Scale in your set)", tool == "scale", tool)
        exp = await E("forgeHotkeys.export()")
        imp = await E("""(t) => { const n = forgeHotkeys.import(t); return [n, forgeHotkeys.action('w'), forgeHotkeys.active()]; }""", exp)
        await E("forgeHotkeys.use('Default')")
        back_w = await E("forgeHotkeys.action('w')")
        check("export / import a set, and switching back to Default gives the default keys",
              imp[0].startswith("My_Hotkeys") and imp[1] == "scale" and back_w == "move", [imp, back_w])
        await E("forgeProRun(forge.view, 'hotkeyEditor')")
        ed = await E("""() => { const b = document.getElementById('forge-hotkeys');
          return { open: b && !b.hidden, rows: b.querySelectorAll('.forge-hk-row').length, groups: b.querySelectorAll('.forge-hk-group').length }; }""")
        check("Windows > Hotkey Editor lists every command in groups", ed["open"] and ed["rows"] > 60 and ed["groups"] >= 8, ed)
        await page.fill("#forge-hotkeys .forge-hk-search", "frame all")
        await page.click('#forge-hotkeys .forge-hk-row[data-action="frameAll"] .forge-hk-key.add')
        await page.keyboard.press("Control+Alt+f")
        cap = await E("""() => [forgeHotkeys.action('ctrl+alt+f'), forgeHotkeys.active(),
          (document.querySelector('#forge-hotkeys .forge-hk-note') || {}).textContent]""")
        check("the editor takes the next key press as the new key (into a set of your own)",
              cap[0] == "frameAll" and cap[1] != "Default", cap)
        await page.keyboard.press("Escape")
        check("Esc closes the editor", await E("document.getElementById('forge-hotkeys').hidden"))

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
