"""Forge's UV Editing workspace (owner 2026-10-21: "camera based, then select edges, cut, select UV shell, unfold
and layout ... settings ... a real system"), in headless Chromium: the workspace picker, the UV Editor beside the
viewport (with its resize edge), projections on the model's GPU UVs, picking faces in the editor (kept in step with
the viewport), dragging UVs, cut / sew from the viewport's edges, shells, the C++ unfold + layout (when the engine
has them), settings that persist, the checker, undo. Plus the node suite for the model (tests/js/test_forge_uv.js).
Skips without Playwright + Chromium. Under a minute.

    python tests/test_forge_uv_ui.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


node = shutil.which("node")
if node:
    r = subprocess.run([node, str(REPO / "tests" / "js" / "test_forge_uv.js")], capture_output=True, text=True, timeout=30)
    print(r.stdout.strip())
    check("the UV model (forge_uv.js) passes its node suite", r.returncode == 0, (r.stdout + r.stderr)[-400:])

T = "forge.view.tree.api"
# the screen point at the middle of face 2's UVs in the UV Editor
CENTRE = """(() => { const S = ForgeUVEditor.state, m = forge.view.poly, c = m.fuv[window._fi == null ? 2 : window._fi]; let u = 0, v = 0; for (const i of c) { u += m.uv[i][0]; v += m.uv[i][1]; }
  u /= c.length; v /= c.length; const r = S.canvas.getBoundingClientRect(), z = S.cam.z;
  return [r.left + r.width / 2 + (u - S.cam.u) * z, r.top + r.height / 2 - (v - S.cam.v) * z]; })()"""


async def ui():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("SKIP: no Playwright here")
        return
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            print("SKIP: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1400, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8894", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8894/**", route)
        await page.goto("http://127.0.0.1:8894/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("['loki-forge-uv', 'loki-forge-workspace', 'loki-forge-split'].forEach((k) => localStorage.removeItem(k))")
        await page.evaluate("document.getElementById('open-forge').click()")
        await page.wait_for_function("window.forge && forge.view && forge.view.tree && document.getElementById('forge-workspace')", timeout=15000)
        await E("forgeAddPrimitive('cube')")
        await page.wait_for_timeout(200)

        # ---- the workspace picker: Modeling | UV Editing
        ws = await E("[...document.getElementById('forge-workspace').options].map((o) => o.textContent)")
        check("the Workspace picker offers Modeling, Sculpting, UV Editing, Retopology, Baking, Materials and Animation", ws == ["Modeling", "Sculpting", "UV Editing", "Retopology", "Baking", "Materials", "Animation"], ws)
        await page.select_option("#forge-workspace", "uv")
        await page.wait_for_timeout(250)
        pan = await E("""(() => { const p = document.getElementById('forge-uvpanel'), b = p.getBoundingClientRect(), s = document.getElementById('forge-stage').getBoundingClientRect();
          return { shown: !p.hidden, w: b.width, beside: b.left >= s.right - 2, edge: !!document.querySelector('.forge-split[data-panel=forge-uvpanel]:not([hidden])'),
                   ws: localStorage.getItem('loki-forge-workspace'), mode: forge.view.mode }; })()""")
        check("UV Editing: the UV Editor opens beside the viewport, with a resize edge, the model in component mode",
              pan["shown"] and pan["w"] > 300 and pan["beside"] and pan["edge"] and pan["ws"] == "uv" and pan["mode"] == "poly", pan)

        # ---- Create UVs: planar on all faces -> the model's GPU UVs follow
        await E("document.querySelector('#forge-uvpanel [data-op=planar]').click()")
        await page.wait_for_timeout(150)
        gpu = await E("""(() => { const m = forge.view.poly, a = forge.view.meshObj().geometry.attributes.uv.array, c = ForgeUV.cornerUVs(m);
          return [ForgeUV.has(m), ForgeUV.shells(m).length, a.length === c.length && a.every((x, i) => Math.abs(x - c[i]) < 1e-6)]; })()""")
        check("Planar: the cube has map UVs, one shell, and the GPU mesh shows exactly those UVs", gpu == [True, 1, True], gpu)
        await E("ForgeUVEditor.OPS.automatic()")
        await page.wait_for_function("/^Automatic|Layout could not/.test(document.querySelector('#forge-uvpanel .fuv-status').textContent)", timeout=15000)
        auto = await E("ForgeUV.shells(forge.view.poly).length")
        check("Automatic: six shells on a cube (one per side)", auto == 6, auto)

        # ---- pick a face in the editor: the viewport's face selection follows; double-click = its shell
        await E("ForgeUVEditor.frame(true)")
        pt = await E(CENTRE)
        await page.mouse.click(pt[0], pt[1])
        sel = await E("[...forge.view.edit.sel.f]")
        check("a click on a face in the UV Editor selects that face in the viewport too", sel == [2], sel)
        await E("forge.view.select([0, 1, 2, 3, 4, 5]); ForgeUVEditor.draw()")
        await E("ForgeUVEditor.OPS.planar('z')")
        await page.wait_for_timeout(150)
        # the face with the most UV area (a planar Z map squashes the side faces to lines)
        await E("window._fi = forge.view.poly.f.map((_, i) => i).sort((a, b) => Math.abs(ForgeUV.faceAreaUV(forge.view.poly, b)) - Math.abs(ForgeUV.faceAreaUV(forge.view.poly, a)))[0]")
        await E("forge.view.select([window._fi]); ForgeUVEditor.frame(true)")
        pt = await E(CENTRE)
        await page.mouse.dblclick(pt[0], pt[1])
        shell = await E("[...forge.view.edit.sel.f].sort((a, b) => a - b)")
        check("double-click: the whole shell (here: all six faces after a planar map)", shell == [0, 1, 2, 3, 4, 5], shell)

        # ---- drag the selected UVs (Move)
        before = await E("forge.view.poly.uv.map((p) => p.slice())")
        await page.mouse.move(pt[0], pt[1])
        await page.mouse.down()
        await page.mouse.move(pt[0] + 60, pt[1], steps=4)
        await page.mouse.up()
        await page.wait_for_timeout(100)
        after = await E("forge.view.poly.uv.map((p) => p.slice())")
        z = await E("ForgeUVEditor.state.cam.z")
        du = [a[0] - b[0] for a, b in zip(after, before)]
        check("dragging selected UVs moves them (by the mouse distance in UV units), one undo step",
              len(after) == len(before) and all(abs(d - 60 / z) < 0.02 for d in du), [du[:3], 60 / z])
        await E("forgeProRun(forge.view, 'undo')")
        back = await E("forge.view.poly.uv.map((p) => p.slice())")
        check("undo puts the UVs back", all(abs(a[0] - b[0]) < 1e-9 for a, b in zip(back, before)), [back[:2], before[:2]])

        # ---- cut / sew from the viewport's edge selection
        await E("forge.view.setSelMode('edge')")
        top = await E("""(() => { const m = forge.view.poly, T = ForgePoly.topology(m), out = [];
          T.edges.forEach((e, i) => { if (m.v[e.a][1] > 0 && m.v[e.b][1] > 0) out.push(i); }); return out; })()""")
        await E("(() => { const ed = forge.view.edit; ed.sel.e = new Set(%s); })()" % top)
        n0 = await E("ForgeUV.shells(forge.view.poly).length")
        await E("ForgeUVEditor.OPS.cut()")
        n1 = await E("ForgeUV.shells(forge.view.poly).length")
        check("Cut the four top edges selected in the viewport: the top becomes its own shell", n1 == n0 + 1, [n0, n1])
        await E("(() => { const ed = forge.view.edit; const m = forge.view.poly, T = ForgePoly.topology(m); const out = [];"
                " T.edges.forEach((e, i) => { if (m.v[e.a][1] > 0 && m.v[e.b][1] > 0) out.push(i); }); ed.sel.e = new Set(out); })()")
        await E("ForgeUVEditor.OPS.sew()")
        n2 = await E("ForgeUV.shells(forge.view.poly).length")
        check("Sew them again: one shell", n2 == n0, [n0, n2])
        await E("forge.view.edit.sel.e = new Set()")
        msg = await E("ForgeUVEditor.OPS.cut(), document.querySelector('#forge-uvpanel .fuv-status').textContent")
        check("Cut with no edges selected says what to do (no silent no-op)", "Select edges" in msg, msg)

        # ---- texel density, pins, flips
        await E("forge.view.select([])")
        await E("(() => { const s = forgeUvSettings(); s.density = 300; forgeUvSaveSettings(s); })()")
        await E("ForgeUVEditor.OPS.setDensity()")
        den = await E("ForgeUV.density(forge.view.poly, [], forgeUvSettings().densityRes)")
        check("Set texel density: the model measures what Settings says (300 px per unit)", abs(den - 300) < 1, den)
        await E("ForgeUVEditor.state.mode = 'uv'; ForgeUVEditor.pickUVs([0, 1], 'set'); ForgeUVEditor.OPS.pin()")
        pins = await E("forge.view.poly.uvPins")
        check("Pin: the selected UV points are pinned (kept for Unfold)", sorted(pins) == [0, 1], pins)
        await E("ForgeUVEditor.state.mode = 'face'")

        # ---- the C++ unfold / layout (needs the engine's uvUnfold / uvLayout)
        await E("ForgeGeom.usable()")
        await page.wait_for_function("ForgeGeom.state === 'on' || ForgeGeom.state === 'off'", timeout=8000)
        has = await E("ForgeGeom.supports('uvUnfold') && ForgeGeom.supports('uvLayout')")
        if has:
            await E("ForgeUVEditor.OPS.automatic()")
            await page.wait_for_function("/^Automatic/.test(document.querySelector('#forge-uvpanel .fuv-status').textContent)", timeout=15000)
            await E("ForgeUVEditor.OPS.unfold()")
            await page.wait_for_function("/Unfolded|Unfold:/.test(document.querySelector('#forge-uvpanel .fuv-status').textContent)", timeout=10000)
            uf = await E("[document.querySelector('#forge-uvpanel .fuv-status').textContent, ForgeUV.distortion(forge.view.poly).filter((d) => d.flipped).length]")
            check("Unfold (C++): every shell unfolded, no flipped faces", uf[0].startswith("Unfolded") and uf[1] == 0, uf)
            await E("ForgeUVEditor.OPS.layout()")
            await page.wait_for_function("/Layout/.test(document.querySelector('#forge-uvpanel .fuv-status').textContent)", timeout=10000)
            lay = await E("""(() => { const m = forge.view.poly; return [m.uv.every((p) => p[0] >= -1e-6 && p[0] <= 1 + 1e-6 && p[1] >= -1e-6 && p[1] <= 1 + 1e-6), ForgeUV.overlapCount(m)]; })()""")
            check("Layout (C++): every UV inside 0-1, no shells overlapping", lay == [True, 0], lay)
        else:
            print("  SKIP unfold / layout: this engine build has no uvUnfold / uvLayout yet")

        # ---- Smart Unwrap (UVgami's seams + unfold + layout) on a cylinder: shells that are disks, inside 0-1
        await E("forgeAddPrimitive('cylinder')")
        await page.wait_for_timeout(200)
        await E("ForgeUVEditor.OPS.smart()")
        await page.wait_for_function("/Smart Unwrap:/.test(document.querySelector('#forge-uvpanel .fuv-status').textContent) && !/placing/.test(document.querySelector('#forge-uvpanel .fuv-status').textContent)", timeout=15000)
        sm = await E("""(() => { const m = forge.view.poly, sh = ForgeUV.shells(m);
          return [document.querySelector('#forge-uvpanel .fuv-status').textContent, sh.length, sh.every((s) => ForgeUVgami.topology(m, s.faces, ForgeUV.seams(m)).disk),
                  m.uv.every((p) => p[0] >= -1e-6 && p[0] <= 1 + 1e-6 && p[1] >= -1e-6 && p[1] <= 1 + 1e-6), ForgeUV.overlapCount(m)]; })()""")
        check("Smart Unwrap on a cylinder: seams placed, every shell a flat disk, packed inside 0-1 with no overlaps", sm[0].startswith("Smart Unwrap:") and sm[1] >= 2 and sm[2] and sm[3] and sm[4] == 0, sm)
        await E("forgeAddPrimitive('torus')")
        await page.wait_for_timeout(200)
        await E("ForgeUVEditor.OPS.atlas()")
        await page.wait_for_function("/^Atlas:/.test(document.querySelector('#forge-uvpanel .fuv-status').textContent) && !/unwrapping/.test(document.querySelector('#forge-uvpanel .fuv-status').textContent)", timeout=15000)
        at = await E("[document.querySelector('#forge-uvpanel .fuv-status').textContent, ForgeUV.has(forge.view.poly), forge.view.poly.uv.every((p) => p[0] >= -1e-6 && p[0] <= 1 + 1e-6 && p[1] >= -1e-6 && p[1] <= 1 + 1e-6)]")
        check("Atlas (xatlas, C++) on a torus: charts made, every UV inside 0-1", at[0].startswith("Atlas:") and "charts" in at[0] and at[1] and at[2], at)
        await E("forgeAddPrimitive('torus')")
        await page.wait_for_timeout(200)
        await E("(() => { const s = forgeUvSettings(); s.optcutsBudget = 6; forgeUvSaveSettings(s); })()")
        await E("ForgeUVEditor.OPS.optcuts()")
        await page.wait_for_function("/^OptCuts: [0-9]+ shells|^OptCuts: [^i]/.test(document.querySelector('#forge-uvpanel .fuv-status').textContent) && !/optimising|iteration/.test(document.querySelector('#forge-uvpanel .fuv-status').textContent)", timeout=15000)
        oc = await E("[document.querySelector('#forge-uvpanel .fuv-status').textContent, ForgeUV.has(forge.view.poly), ForgeUV.distortion(forge.view.poly).filter((d) => d.flipped).length, forge.view.poly.uv.every((p) => p[0] >= -1e-6 && p[0] <= 1 + 1e-6 && p[1] >= -1e-6 && p[1] <= 1 + 1e-6)]")
        check("OptCuts (C++, its own worker) on a torus: seams + unfold optimised, no flips, laid out in 0-1", "shells" in oc[0] and oc[1] and oc[2] == 0 and oc[3], oc)
        await E("forgeAddPrimitive('cube')")
        await page.wait_for_timeout(200)
        await E("ForgeUVEditor.OPS.autoSeams()")
        seams = await E("ForgeUV.seams(forge.view.poly).size")
        check("Auto Seams on a cube places the seams only (the 7-edge cross of the original add-on)", seams == 7, seams)

        # ---- settings persist; the checker; Modeling hides the editor again
        await E("document.getElementById('forge-uv-gear').click()")
        inp = await E("!!document.querySelector('#forge-uvpanel .fuv-settings:not([hidden]) [data-key=layoutPadding]')")
        await E("(() => { const i = document.querySelector('#forge-uvpanel [data-key=layoutPadding]'); i.value = '9'; i.dispatchEvent(new Event('change')); })()")
        kept = await E("JSON.parse(localStorage.getItem('loki-forge-uv')).layoutPadding")
        check("the gear opens Settings; a changed setting is remembered (padding 9 px)", inp and kept == 9, [inp, kept])
        await E("ForgeUVEditor.OPS.checker()")
        ck = await E("!!(forge.view.material.map && forge.view.material.map.isCanvasTexture)")
        await E("ForgeUVEditor.OPS.checker()")
        ck2 = await E("!(forge.view.material.map && forge.view.material.map.isCanvasTexture)")
        check("Checker puts a checker texture on the model, and takes it off again", ck and ck2, [ck, ck2])
        menu = await E("FMY_MENUS().find((m) => m[0] === 'UV')[1].filter((x) => FORGE_PRO_CMDS[x]).length")
        check("the UV menu in the menu bar has the UV commands", menu >= 12, menu)
        await page.select_option("#forge-workspace", "model")
        await page.wait_for_timeout(150)
        hid = await E("document.getElementById('forge-uvpanel').hidden")
        check("Modeling: the UV Editor goes away", hid, hid)
        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(ui(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
