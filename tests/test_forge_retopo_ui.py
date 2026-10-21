"""Forge's Retopology workspace (Quad Draw on a live surface, app/ui/forge_retopo.js) in headless Chromium: the
surface gets a BVH, clicks put dots on it, Shift-click makes quads from the nearest four, symmetry mirrors, a drag
slides a dot along the surface, Tab-drag extrudes from a border edge, Shift-drag relaxes, Ctrl-click deletes, the
tool's undo, and Make Object turns it into a new Forge object. Skips without Playwright. Under a minute.

    python tests/test_forge_retopo_ui.py
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

RT = "ForgeRetopo"


async def main():
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
        await E("['loki-forge-retopo', 'loki-forge-workspace'].forEach((k) => localStorage.removeItem(k))")
        await page.click("#open-forge")
        await page.wait_for_function("window.forge && forge.view && forge.view.tree && document.getElementById('forge-workspace')", timeout=15000)
        await E("forgeAddPrimitive('sphere')")
        await page.wait_for_timeout(200)
        await E("forgeModelMode(false); forgeProRun(forge.view, 'frameAll')")
        await page.wait_for_timeout(200)
        await E("forge.view.tree.api.select(forge.view.tree.api.sceneNodes()[0].id)")
        opts = await E("[...document.getElementById('forge-workspace').options].map((o) => o.value)")
        await page.select_option("#forge-workspace", "retopo")
        await page.wait_for_timeout(200)
        on = await E("[%s.state.on, %s.state.bvh && %s.state.bvh.triangles, !document.getElementById('forge-retopo-bar').hidden]" % (RT, RT, RT))
        check("Workspace > Retopology: Quad Draw is on, the selected sphere is the live surface (with a BVH), its bar shows",
              "retopo" in opts and on[0] and on[1] > 100 and on[2], [opts, on])

        # four dots around the middle of the view -> a quad on Shift-click
        c = await E("(() => { const r = forge.view.canvas.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        pts = [(c[0] - 40, c[1] - 40), (c[0] + 40, c[1] - 40), (c[0] + 40, c[1] + 40), (c[0] - 40, c[1] + 40)]
        for x, y in pts:
            await page.mouse.click(x, y)
        dots = await E("%s.state.cage.v.length" % RT)
        on_surface = await E("""(() => { const R = ForgeRetopo.state, g = R.surface.geometry; g.computeBoundingSphere(); const s = g.boundingSphere;
          return R.cage.v.map((p) => Math.abs(Math.hypot(p[0] - s.center.x, p[1] - s.center.y, p[2] - s.center.z) - s.radius) / s.radius); })()""")
        check("four clicks: four dots, each on the sphere's surface", dots == 4 and all(d < 0.05 for d in on_surface), [dots, on_surface])
        await page.keyboard.down("Shift")
        await page.mouse.click(c[0], c[1])
        await page.keyboard.up("Shift")
        f = await E("%s.state.cage.f" % RT)
        facing = await E("""(() => { const R = ForgeRetopo.state, f = R.cage.f[0], s = f.map((i) => ForgeRetopo.toScreen(R.cage.v[i]));
          let a = 0; for (let k = 0; k < s.length; k++) { const p = s[k], q = s[(k + 1) % s.length]; a += p[0] * q[1] - q[0] * p[1]; } return a; })()""")
        check("Shift-click between them: one quad, wound to face the camera", len(f) == 1 and len(f[0]) == 4 and facing < 0, [f, facing])

        # Tab + drag from the right border edge -> a second quad
        await page.keyboard.down("Tab")
        await page.mouse.move(c[0] + 40, c[1])
        await page.mouse.down()
        await page.mouse.move(c[0] + 110, c[1], steps=4)
        await page.mouse.up()
        await page.keyboard.up("Tab")
        ext = await E("[%s.state.cage.f.length, %s.state.cage.v.length]" % (RT, RT))
        check("Tab + drag from a border edge extrudes a new quad (2 faces, 6 dots)", ext == [2, 6], ext)
        # drag a dot: it slides and stays on the surface
        before = await E("%s.state.cage.v[0].slice()" % RT)
        await page.mouse.move(*pts[0])
        await page.mouse.down()
        await page.mouse.move(pts[0][0] - 25, pts[0][1] - 10, steps=3)
        await page.mouse.up()
        after = await E("%s.state.cage.v[0].slice()" % RT)
        moved = sum((a - b) ** 2 for a, b in zip(after, before)) ** 0.5
        check("dragging a dot slides it along the surface", moved > 0.01, [before, after])
        # undo / redo
        await page.keyboard.press("Control+z")
        und = await E("%s.state.cage.v[0].slice()" % RT)
        check("Ctrl+Z undoes the slide (the tool's own undo)", all(abs(a - b) < 1e-6 for a, b in zip(und, before)), [und, before])
        await page.keyboard.press("Control+Shift+z")
        # relax with Shift + drag
        base = await E("JSON.stringify(%s.state.cage.v)" % RT)
        await page.keyboard.down("Shift")
        await page.mouse.move(c[0] + 20, c[1])
        await page.mouse.down()
        await page.mouse.move(c[0] + 40, c[1] + 5, steps=5)
        await page.mouse.up()
        await page.keyboard.up("Shift")
        rel = await E("JSON.stringify(%s.state.cage.v)" % RT)
        check("Shift + drag relaxes the dots under the brush", rel != base, None)
        # symmetry: a dot on the right gets its mirror
        await E("(() => { const s = JSON.parse(localStorage.getItem('loki-forge-retopo') || '{}'); s.symmetry = true; localStorage.setItem('loki-forge-retopo', JSON.stringify(s)); })()")
        n0 = await E("%s.state.cage.v.length" % RT)
        await page.mouse.click(c[0] - 90, c[1] + 80)
        sym = await E("(() => { const v = ForgeRetopo.state.cage.v; return [v.length, v[v.length - 2], v[v.length - 1]]; })()")
        check("Symmetry X: one click makes the dot and its mirror (x flipped, y and z the same - found on the far side along the mirrored normal)",
              sym[0] == n0 + 2 and abs(sym[1][0] + sym[2][0]) < 0.03 and abs(sym[1][1] - sym[2][1]) < 0.03 and abs(sym[1][2] - sym[2][2]) < 0.03, sym)
        await page.keyboard.down("Control")
        await page.mouse.click(c[0] - 90, c[1] + 80)
        await page.keyboard.up("Control")
        dl = await E("%s.state.cage.v.length" % RT)
        check("Ctrl + click deletes the dot under the mouse", dl == n0 + 1, [n0, dl])
        # Make Object
        nodes0 = await E("forge.view.tree.api.sceneNodes().length")
        await E("document.querySelector('#forge-retopo-bar [data-rt=finish]').click()")
        await page.wait_for_timeout(300)
        made = await E("[forge.view.tree.api.sceneNodes().length, forge.view.poly && forge.view.poly.f.length, %s.state.cage.f.length]" % RT)
        check("Make Object: a new object in the scene with the drawn faces (the tool starts empty again)", made[0] == nodes0 + 1 and made[1] == 2 and made[2] == 0, [nodes0, made])
        await page.select_option("#forge-workspace", "model")
        off = await E("[%s.state.on, document.getElementById('forge-retopo-bar').hidden]" % RT)
        check("back to Modeling: Quad Draw is off", off == [False, True], off)
        bvh = await E("""(() => { const P = forge.view.THREE; const n = 200000, pos = new Float32Array(n * 9); for (let i = 0; i < n; i++) { const x = (i % 500) / 50, y = Math.floor(i / 500) / 50;
          pos.set([x, y, 0, x + 0.02, y, 0, x, y + 0.02, 0], i * 9); } const t = performance.now(); const B = forgeRetopoBVH(pos, null, null); const tb = performance.now() - t;
          const t2 = performance.now(); let hits = 0; for (let k = 0; k < 1000; k++) if (B.ray([Math.random() * 10, Math.random() * 4, 1], [0, 0, -1])) hits++; return [tb, performance.now() - t2, hits]; })()""")
        check("the surface BVH: 200 000 triangles built in well under 3 s, 1 000 rays in under 100 ms, hitting the half of the grid that has triangles", bvh[0] < 3000 and bvh[1] < 100 and 400 < bvh[2] < 600, bvh)
        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
