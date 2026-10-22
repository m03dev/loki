"""Forge 2026-10-21 12:46 batch: Multi-Cut the pro way (hover dot + % readout + knife line, Shift snap steps,
middle-click 50 %, Ctrl edge-loop preview / insert, Backspace, Enter), soft / hard edges (polySoftEdge, shading
follows them, a new sphere is soft and a cube hard), normals display, the Animation workspace (no time bars or cog
on the Modeling screen), the smooth preview following an edit. Under a minute.

    python tests/test_forge_mcut_ui.py
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
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        await page.wait_for_function("forge.view && forge.view.pro && forge.view.brush", timeout=10000)
        E = page.evaluate

        await page.wait_for_timeout(300)
        # an edge on screen: point t along edge (a, b) of the working cage, in page pixels
        SP = """([a, b, t]) => { const v = forge.view, P = v.poly, A = P.v[a], B = P.v[b], T = v.THREE;
          const q = new T.Vector3(A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t, A[2] + (B[2] - A[2]) * t).applyMatrix4(v.holder.matrixWorld).project(v.camera);
          const r = v.canvas.getBoundingClientRect(); return [r.left + (q.x + 1) / 2 * r.width, r.top + (1 - q.y) / 2 * r.height]; }"""
        # ---- the Modeling screen is clean
        clean = await E("""(() => { const vis = (id) => { const e = document.getElementById(id); return !!(e && e.offsetParent && getComputedStyle(e).display !== 'none'); };
          return { time: vis('fmy-time'), keys: vis('forge-time'), cog: vis('forge-options-btn') }; })()""")
        check("Modeling has no time slider, no floating key bar and no cog on screen", clean == {"time": False, "keys": False, "cog": False}, clean)
        await E("ForgeUVEditor.setWorkspace('anim')")
        await page.wait_for_timeout(120)
        anim = await E("[!!document.getElementById('fmy-time').offsetParent, document.getElementById('forge-time').parentElement.id, !!document.getElementById('fdock-keys-btn')]")
        check("Workspace: Animation shows the time / range sliders, the key bar folded into them (Keys)", anim == [True, "fmy-time", True], anim)
        await E("ForgeUVEditor.setWorkspace('model')")
        check("Preferences is a command (Windows > Settings/Preferences)", await E("!!FORGE_PRO_CMDS.preferences && FMY_MENUS().find(m => m[0] === 'Windows')[1].includes('preferences')"))

        # ---- soft / hard
        await E("fmyRun('sphere')")
        await page.wait_for_timeout(300)
        check("a new sphere is soft (the pro default angle 30)", await E("forge.view.poly.hard instanceof Map && forge.view.poly.hard.size === 0"))
        smooth = await E("(() => { const n = forge.view.sm.nrm, P = forge.view.poly, f0 = window.ForgePoly.faceNormal(P, P.f[5]); const at = forge.view.polyCorners[5] * 3; return Math.abs(n[at] - f0[0]) + Math.abs(n[at + 1] - f0[1]) + Math.abs(n[at + 2] - f0[2]); })()")
        check("...its corner normals are averaged (smooth shading), not the face normal", smooth > 0.01, smooth)
        await E("fmyRun('hardEdge')")
        await page.wait_for_timeout(150)
        hard = await E("(() => { const n = forge.view.sm.nrm, P = forge.view.poly, f0 = window.ForgePoly.faceNormal(P, P.f[5]); const at = forge.view.polyCorners[5] * 3; return [P.hard.size, Math.abs(n[at] - f0[0]) + Math.abs(n[at + 1] - f0[1]) + Math.abs(n[at + 2] - f0[2])]; })()")
        check("Harden Edge: every edge hard, the corners take the face normal", hard[0] > 500 and hard[1] < 1e-4, hard)
        node = await E("[...document.querySelectorAll('#forge-history .forge-hist-name, #forge-history *')].map(e => e.textContent).join(' ')")
        check("...and it is a polySoftEdge step in INPUTS", "polySoftEdge" in node, node[:200])
        await E("fmyRun('faceNormals')")
        await page.wait_for_timeout(350)
        check("Display > Face Normals draws them", await E("!!forge.view.holder.getObjectByName('forge-normals')"))
        await E("fmyRun('faceNormals')")
        await E("fmyRun('delete')")

        # ---- Multi-Cut on a cube
        await E("fmyRun('cube')")
        await page.wait_for_timeout(300)
        check("a new cube stays crisp (every edge hard at 30)", await E("forge.view.poly.hard.size === 12"))
        await E("fmyRun('multiCut')")
        await page.wait_for_timeout(300)
        E2 = await E("(() => { const P = forge.view.poly, out = []; const seen = new Set(); P.f.forEach(f => f.forEach((a, k) => { const b = f[(k + 1) % f.length], key = Math.min(a, b) + ',' + Math.max(a, b); if (!seen.has(key)) { seen.add(key); out.push([a, b]); } })); return out; })()")
        # pick a front edge that is on screen and pointing sideways
        best = None
        for a, b in E2:
            p1 = await page.evaluate(SP, [a, b, 0.1]); p2 = await page.evaluate(SP, [a, b, 0.9])
            if abs(p1[0] - p2[0]) > 40 and abs(p1[0] - p2[0]) > abs(p1[1] - p2[1]):
                hitv = await page.evaluate("([x, y]) => { const r = forge.view.canvas.getBoundingClientRect(); const h = forge.view.cutPointAt([x - r.left, y - r.top]); return h && h.e ? h.e : null; }", await page.evaluate(SP, [a, b, 0.37]))
                if hitv and sorted(hitv) == sorted([a, b]):
                    best = (a, b); break
        dbg = await E("[forge.view.mode, forge.view.poly.f.length, !!forgeTk.tool]")
        check("found an edge to cut on screen", best is not None, [dbg, E2[:6]])
        if best:
            a, b = best
            x, y = await page.evaluate(SP, [a, b, 0.37])
            await page.mouse.move(x, y)
            await page.wait_for_timeout(80)
            tag = await E("(() => { const t = document.getElementById('forge-mc-tag'); return t && !t.hidden ? t.textContent : ''; })()")
            check("hovering an edge: a readout with the % along it", "Edge" in tag and "%" in tag, tag)
            check("...and a dot where the point will go", await E("!!forge.view.holder.getObjectByName('forge-mc-dot')"))
            await page.keyboard.down("Shift"); await page.mouse.move(x + 1, y)
            await page.wait_for_timeout(80)
            tag = await E("document.getElementById('forge-mc-tag').textContent")
            check("Shift: snaps to the snap step (25 / 50 / 75 %), the steps show as dots", ("25%" in tag or "50%" in tag) and "snap" in tag and await E("!!forge.view.holder.getObjectByName('forge-mc-ticks')"), tag)
            await page.keyboard.up("Shift")
            await page.keyboard.down("Control"); await page.mouse.move(x, y + 1)
            await page.wait_for_timeout(80)
            tag = await E("document.getElementById('forge-mc-tag').textContent")
            check("Ctrl before a point: the edge loop preview", "loop" in tag.lower() and await E("!!forge.view.holder.getObjectByName('forge-mc-loop')"), tag)
            f0 = await E("forge.view.poly.f.length")
            await page.mouse.down(button="middle"); await page.mouse.up(button="middle")
            await page.wait_for_timeout(150)
            await page.keyboard.up("Control")
            f1 = await E("forge.view.poly.f.length")
            check("Ctrl+middle-click inserts the loop (in the middle); the tool stays on", f1 == f0 + 4 and await E("!!forgeTk.tool"), [f0, f1])
            mids = await E("(() => { const P = forge.view.poly; return P.v.filter(p => Math.abs(Math.abs(p[0]) - 0.0) < 1e-6 || Math.abs(Math.abs(p[2]) - 0.0) < 1e-6).length; })()")
            # now two points: a middle-click (50 %) then a plain click, then Enter
            E3 = await E("(() => { const P = forge.view.poly, out = [], seen = new Set(); P.f.forEach(f => f.forEach((a, k) => { const b = f[(k + 1) % f.length], key = Math.min(a, b) + ',' + Math.max(a, b); if (!seen.has(key)) { seen.add(key); out.push([a, b]); } })); return out; })()")
            pair = None
            for fa in await E("forge.view.poly.f.map(f => f.slice())"):
                if len(fa) != 4: continue
                ok = True; pts = []
                for k in (0, 2):
                    a2, b2 = fa[k], fa[(k + 1) % 4]
                    p = await page.evaluate(SP, [a2, b2, 0.5])
                    h = await page.evaluate("([x, y]) => { const r = forge.view.canvas.getBoundingClientRect(); const h = forge.view.cutPointAt([x - r.left, y - r.top]); return h && h.e ? h.e : null; }", p)
                    if not h or sorted(h) != sorted([a2, b2]): ok = False; break
                    pts.append(p)
                if ok: pair = pts; break
            check("found a face with two cuttable edges", pair is not None)
            if pair:
                f2 = await E("forge.view.poly.f.length")
                await page.mouse.move(*pair[0]); await page.mouse.down(button="middle"); await page.mouse.up(button="middle")
                await page.wait_for_timeout(60)
                t1 = await E("forgeTk.tool && forgeTk.tool.pts.length ? forgeTk.tool.pts[0].t : null")
                check("middle-click on an edge: a point at exactly 50 %", t1 == 0.5, t1)
                await page.mouse.move(*pair[1])
                await page.wait_for_timeout(60)
                check("the knife line runs from the last point to the mouse", await E("!!forge.view.holder.getObjectByName('forge-mc-line')"))
                await page.mouse.down(); await page.mouse.up()
                await page.keyboard.press("Backspace")
                check("Backspace takes the last point back", await E("forgeTk.tool.pts.length") == 1)
                await page.mouse.down(); await page.mouse.up()
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(150)
                f3 = await E("forge.view.poly.f.length")
                check("Enter cuts: one face more, the knife and dots are gone", f3 == f2 + 1 and not await E("!!forge.view.holder.getObjectByName('forge-mc-line') || !!forge.view.holder.getObjectByName('forge-mc-dot')"), [f2, f3])

        # ---- the smooth preview follows an edit (no stale cage)
        await E("fmyRun('smooth3')")
        await page.wait_for_timeout(300)
        b0 = await E("(() => { const o = forge.view.holder.getObjectByName('forge-smooth'); o.geometry.computeBoundingBox(); return o.geometry.boundingBox.max.y; })()")
        await E("""(() => { const v = forge.view, P = window.ForgePoly, m = JSON.parse(JSON.stringify({ v: v.poly.v, f: v.poly.f }));
          let top = 0; m.v.forEach((p, i) => { if (p[1] > m.v[top][1]) top = i; }); m.v[top][1] += 2; v.showPoly(m, true); })()""")
        await page.wait_for_timeout(400)
        b1 = await E("(() => { const o = forge.view.holder.getObjectByName('forge-smooth'); o.geometry.computeBoundingBox(); return o.geometry.boundingBox.max.y; })()")
        check("smooth preview (3) rebuilds after the cage changes", b1 > b0 + 0.3, [b0, b1])

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
