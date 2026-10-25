"""Forge, 2026-10-25 (owner: "fix how scale works ... scale down to flatten", "right click brings up the wheel and shift
right click does the same thing", "quick menu buttons are broken", "more features like maya per object"):

  * Flatten X / Y / Z / Normal: components lie flat (one undo step), objects get Scale <axis> = 0; hold R + left
    button = Scale's marking menu with them;
  * per object (Maya): Bevel / Merge / Extrude with the object picked and no components work on the whole mesh;
  * the Quick Menu and every marking menu only show commands that run (a saved dead id is dropped), To UVs works;
  * sculpting: the right button = the brush wheel, Shift + right = the Mask menu (never the wheel twice).
Under a minute.

    python tests/test_forge_flatten_ui.py
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

        async def cube():
            await E("forgeProRun(forge.view, 'cube')"); await wait(120)

        # ---- Create: a new object lands in object mode, selected, and the camera stays where it is (Maya / Unreal /
        # the three.js editor's AddObjectCommand: select it, never move the view)
        cam0 = await E("forge.view.camera.position.toArray().concat(forge.view.controls ? forge.view.controls.target.toArray() : [])")
        await cube()
        cam1 = await E("forge.view.camera.position.toArray().concat(forge.view.controls ? forge.view.controls.target.toArray() : [])")
        st = await E("[forge.view.mode, forge.view.tree.api.selected().length]")
        check("Create: the new cube is in OBJECT mode and selected", st == ["view", 1], st)
        check("Create: the camera does not move", all(abs(a - b) < 1e-6 for a, b in zip(cam0, cam1)), [cam0, cam1])
        await E("forgeProRun(forge.view, 'sphere')"); await wait(150)
        cam2 = await E("forge.view.camera.position.toArray().concat(forge.view.controls ? forge.view.controls.target.toArray() : [])")
        check("...not for the second object either", all(abs(a - b) < 1e-6 for a, b in zip(cam1, cam2)), [cam1, cam2])
        # ---- flatten components
        await cube()
        await E("forgeProRun(forge.view, 'face')"); await wait(60)
        await E("forge.view.selectItems('face', [...forge.view.poly.f.keys()], 'set')"); await wait(40)
        await E("forgeProRun(forge.view, 'flattenY')"); await wait(80)
        ys = await E("[...new Set(forge.view.poly.v.map(p => p[1].toFixed(6)))]")
        check("Flatten Y on the picked faces: every vertex on one plane", len(ys) == 1, ys)
        await E("forgeProRun(forge.view, 'undo')"); await wait(80)
        ys = await E("[...new Set(forge.view.poly.v.map(p => p[1].toFixed(6)))]")
        check("...one undo step brings the cube back", len(ys) == 2, ys)
        # ---- the Scale handle dragged PAST its centre stops flat - never negative (inverted, inside-out geometry)
        await cube()
        await E("forgeProRun(forge.view, 'face')"); await wait(80)
        await E("forge.view.selectItems('face', forge.view.poly.f.map((_, i) => i), 'set')")
        await E("forgeProRun(forge.view, 'scale')"); await wait(250)
        piv = await E("""(() => { const v = forge.view, o = v.gizmo.object, r = v.canvas.getBoundingClientRect();
            const sp = (w) => { const p = w.project(v.camera); return [r.left + (p.x + 1) / 2 * r.width, r.top + (1 - p.y) / 2 * r.height]; };
            const c = o.getWorldPosition(new v.THREE.Vector3()); return sp(c.clone()).concat(sp(c.clone().add(new v.THREE.Vector3(1, 0, 0)))); })()""")
        px, py, qx, qy = piv
        hit = None
        for i in range(4, 60):
            t = i / 40
            await page.mouse.move(px + (qx - px) * t, py + (qy - py) * t); await wait(10)
            if await E("forge.view.gizmo.axis") == "X":
                hit = (px + (qx - px) * t, py + (qy - py) * t); break
        check("found the Scale handle's X box on screen", hit is not None)
        if hit:
            await page.mouse.down()
            for t in (0.6, 0.2, 0.0, -0.6, -1.4):
                await page.mouse.move(px + (hit[0] - px) * t, py + (hit[1] - py) * t, steps=4); await wait(25)
            held = await E("forge.view.gizmo.object.scale.x")
            await page.mouse.up(); await wait(250)
            vol = await E("window.ForgePoly.volume(forge.view.poly)")
            check("dragged far past the centre, the scale stays a hair above 0 (flat), never negative", 0 < held < 1e-3, held)
            check("...so the cube is flat, not turned inside out (volume ~0, not negative)", -1e-6 < vol < 1e-3, vol)
        await E("forgeProRun(forge.view, 'objectMode')"); await wait(80)
        # ---- the R marking menu
        mm = await E("forgeProMenu(forge.view, { key: 'r' }).ring")
        check("hold R + left button: Scale's marking menu has Flatten X / Y / Z / Normal",
              mm.get("W") == "flattenX" and mm.get("N") == "flattenY" and mm.get("E") == "flattenZ" and mm.get("S") == "flattenNormal", mm)
        # ---- per object (Maya): Merge / Bevel with no components picked act on the whole mesh
        await cube()
        f0 = await E("forge.view.poly.f.length")
        await E("forge.view.selectItems && forge.view.selectItems('face', [], 'set')")
        await E("forgeProRun(forge.view, 'bevel')"); await wait(100)
        f1 = await E("forge.view.poly.f.length")
        check("Bevel with the object picked (no components) bevels every edge, like Maya", f1 > f0 + 10, [f0, f1])
        say = await E("document.getElementById('forge-status').textContent")
        check("...and says it worked on the whole object", "whole object" in say, say)
        await cube()
        await E("forge.view.selectItems && forge.view.selectItems('face', [], 'set')")
        await E("forgeProRun(forge.view, 'extrude')"); await wait(100)
        say = await E("document.getElementById('forge-status').textContent")
        check("Extrude with no components picked extrudes every face (the whole object, like Maya)", "Extrude (whole object)" in say, say)
        # ---- objects: Scale <axis> = 0
        await cube()
        await E("forgeProRun(forge.view, 'objectMode')"); await wait(80)
        sc = await E("""(async () => { const t = forge.view.tree.api; const id = t.list().filter(n => n.kind === 'mesh').pop().id; t.select(id);
          await forgeProRun(forge.view, 'flattenZ'); const n = t.node(id); return [n.grp.scale.x, n.grp.scale.y, n.grp.scale.z]; })()""")
        check("Flatten Z on an object: its Scale Z goes to 0 (a hair above, so it can still be picked)", sc[0] == 1 and sc[1] == 1 and sc[2] < 1e-3, sc)
        # ---- dead commands never show
        await E("""(() => { const p = forgeMenusPrefs(); p.quick = { ring: { N: 'noSuchCommand', S: 'frameSel' }, list: ['alsoGone', 'duplicate'] }; forgeMenusSave(p); })()""")
        await E("forgeMenusQuickOpen(forge.view, [650, 430])"); await wait(60)
        ids = await E("[...document.querySelectorAll('#forge-pro-marking [data-id], #forge-pro-marking [data-pro-id]')].map(b => b.dataset.id || b.dataset.proId)")
        labels = await E("document.getElementById('forge-pro-marking').textContent")
        check("a saved Quick Menu with commands an update removed: the dead ones are left out", "noSuchCommand" not in labels and "alsoGone" not in labels and "Frame Selection" in labels, [ids, labels[:200]])
        await E("forgeProMarkHide()")
        await E("(() => { const p = forgeMenusPrefs(); p.quick = null; forgeMenusSave(p); })()")
        dead = await E("""(() => { const out = []; const v = forge.view; const chk = (m) => { for (const id of Object.values(m.ring || {}).concat(m.list || [])) if (typeof id === 'string' && id !== '-' && !(FORGE_PRO_CMDS[id] && typeof FORGE_PRO_CMDS[id][1] === 'function')) out.push(id); };
          for (const c of [{}, { ctrl: true }, { shift: true }, { key: 'q' }, { key: 'w' }, { key: 'r' }]) chk(forgeProMenu(v, c));
          chk(FORGE_QUICK_DEFAULT); return out; })()""")
        check("no marking menu or the Quick Menu points at a command that doesn't run", not dead, dead)
        check("To UVs is a real command now (Ctrl + right button, east)", await E("typeof FORGE_PRO_CMDS.toUV[1] === 'function'"))
        # ---- sculpting: one button, one menu (a fresh Forge, so nothing from above is in the way)
        await page.reload()
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await E("document.getElementById('open-forge').click()")
        await page.wait_for_function("forge.view && forge.view.pro && forge.view.brush", timeout=15000)
        await E("fmyRun('sphere')"); await wait(200)
        await E("fmyRun('sculpt')")
        await page.wait_for_function("forge.view.mode === 'sculpt'", timeout=20000)
        await wait(200)
        vb = await page.locator("#forge-view").bounding_box()
        cx, cy = vb["x"] + vb["width"] * 0.5, vb["y"] + vb["height"] * 0.5
        await page.keyboard.down("Shift")
        await page.mouse.move(cx, cy); await page.mouse.down(button="right")
        await wait(60)
        st = await E("[!!document.getElementById('fsc-wheel'), !document.getElementById('forge-pro-marking').hidden, document.getElementById('forge-pro-marking').textContent]")
        await page.mouse.up(button="right"); await page.keyboard.up("Shift")
        check("sculpting: Shift + right button opens the Mask menu, not the brush wheel", (not st[0]) and st[1] and "Invert" in st[2], st)
        await E("forgeProMarkHide()")
        await page.mouse.down(button="right"); await wait(60)
        st = await E("[!!document.getElementById('fsc-wheel'), document.getElementById('forge-pro-marking').hidden]")
        await page.mouse.up(button="right")
        check("...and the plain right button is the brush wheel (and only that)", st == [True, True], st)
        await E("forgeSculptUI.close()")
        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
