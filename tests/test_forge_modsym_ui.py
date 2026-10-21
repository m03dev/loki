"""Forge's modelling symmetry in headless Chromium: with symmetry on, dragging the move handle mirrors the move
onto the mirrored vertices (M' = S M S), with symmetry off it does not. A real mouse drag of the X arrow.

    python tests/test_forge_modsym_ui.py
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

PAIRS = """(a) => {
  const p0 = a[0], p1 = a[1], eps = 1e-4, N = p0.length, out = { pairs: 0, ok: 0, bad: [] };
  const find = (q) => { for (let j = 0; j < N; j++) { const r = p0[j];
    if (Math.abs(r[0] - q[0]) < eps && Math.abs(r[1] - q[1]) < eps && Math.abs(r[2] - q[2]) < eps) return j; } return -1; };
  for (const i of forge.view.selectedVerts()) {
    const j = find([-p0[i][0], p0[i][1], p0[i][2]]);
    if (j < 0 || j === i) continue;
    out.pairs++;
    const di = [p1[i][0]-p0[i][0], p1[i][1]-p0[i][1], p1[i][2]-p0[i][2]];
    const dj = [p1[j][0]-p0[j][0], p1[j][1]-p0[j][1], p1[j][2]-p0[j][2]];
    if (Math.abs(dj[0] + di[0]) < 1e-6 && Math.abs(dj[1] - di[1]) < 1e-6 && Math.abs(dj[2] - di[2]) < 1e-6 && Math.abs(di[0]) > 1e-3) out.ok++;
    else out.bad.push([i, j, di, dj]);
  }
  return out; }"""


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
        await page.evaluate("forgeOpen()")
        await page.wait_for_function("!!(forge.view && forge.view.showPoly && forge.view.setSelMode)", timeout=20000)
        await page.evaluate("forgeModelMode(true)")
        await page.evaluate("document.querySelector(\"#forge [data-prim='cube']\").click()")
        await page.evaluate("forgeModelMode(true)")
        await page.evaluate("forge.view.frame()")
        canvas = await page.eval_on_selector("#forge-view", "c => { const r = c.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
        cx, cy, cw, ch = canvas

        await page.keyboard.press("F9")

        async def drag_x(dist):
            piv = await page.evaluate("() => { const v = forge.view, c = ForgePoly.median(v.poly, v.selectedVerts()); return [v.project(c), v.project([c[0] + 0.3, c[1], c[2]])]; }")
            for k in range(4, 60, 2):
                t = k / 40.0
                x = cx + piv[0][0] + (piv[1][0] - piv[0][0]) * t
                y = cy + piv[0][1] + (piv[1][1] - piv[0][1]) * t
                await page.mouse.move(x, y)
                if await page.evaluate("forge.view.gizmo.axis") == "X":
                    await page.mouse.down(); await page.mouse.move(x + dist, y, steps=5); await page.mouse.up()
                    return True
            return False

        async def select_left():
            return await page.evaluate("""() => { const idx = []; forge.view.poly.v.forEach((p, i) => { if (p[0] < -1e-6) idx.push(i); });
              forge.view.selectItems('vert', idx, 'set'); return idx.length; }""")

        # --- regression: modelling symmetry is OFF by default, so an ordinary drag must not mirror
        n0 = await select_left()
        await page.keyboard.press("w")
        q0 = await page.evaluate("() => forge.view.poly.v.map((p) => p.slice())")
        okd = await drag_x(60)
        q1 = await page.evaluate("() => forge.view.poly.v.map((p) => p.slice())")
        dmap = await page.evaluate("(a) => { const p0 = a[0], p1 = a[1], eps = 1e-4, N = p0.length; let flipped = 0, moved = 0; "
            "const find = (q) => { for (let j = 0; j < N; j++) { const r = p0[j]; if (Math.abs(r[0]-q[0])<eps && Math.abs(r[1]-q[1])<eps && Math.abs(r[2]-q[2])<eps) return j; } return -1; }; "
            "const sel = new Set(forge.view.selectedVerts()); "
            "for (const i of sel) { const j = find([-p0[i][0], p0[i][1], p0[i][2]]); if (j < 0 || j === i) continue; "
            "const di = p1[i][0]-p0[i][0], dj = p1[j][0]-p0[j][0]; if (Math.abs(di) > 1e-4) moved++; if (Math.abs(dj) > 1e-4 && di*dj < 0) flipped++; } "
            "return [moved, flipped, !!forge.view.brush.symModel]; }", [q0, q1])
        check("modelling symmetry is OFF by default: an ordinary component drag does not mirror",
              n0 > 0 and okd and dmap[0] > 0 and dmap[1] == 0 and dmap[2] is False, [n0, okd, dmap])
        await page.keyboard.press("Control+z")

        # --- control: symmetry axes off, the mirrored vertices must not move
        await page.evaluate("forge.view.brush.symBits = 0; forge.view.brush.symModel = true")
        n = await select_left()
        await page.keyboard.press("w")
        p0 = await page.evaluate("() => forge.view.poly.v.map((p) => p.slice())")
        ok = await drag_x(60)
        p1 = await page.evaluate("() => forge.view.poly.v.map((p) => p.slice())")
        off = await page.evaluate(PAIRS, [p0, p1])
        check("with symmetry off a component move leaves the mirrored vertices alone",
              n > 0 and ok and off["pairs"] > 0 and off["ok"] == 0, [n, ok, off])
        await page.keyboard.press("Control+z")

        # --- symmetry ON: dragging X mirrors the move onto the partners
        await page.evaluate("forge.view.brush.symBits = 1; forge.view.brush.symModel = true")
        await select_left()
        await page.keyboard.press("w")
        p0 = await page.evaluate("() => forge.view.poly.v.map((p) => p.slice())")
        ok = await drag_x(60)
        p1 = await page.evaluate("() => forge.view.poly.v.map((p) => p.slice())")
        on = await page.evaluate(PAIRS, [p0, p1])
        moved = await page.evaluate("(a) => Math.max(...a[1].map((p, i) => Math.abs(p[0] - a[0][i][0])))", [p0, p1])
        check("with X symmetry on, dragging X moves each mirrored vertex the opposite way (same y and z)",
              ok and moved > 0.02 and on["pairs"] > 0 and on["ok"] == on["pairs"] and not on["bad"], [ok, moved, on])
        await page.keyboard.press("Control+z")

        # --- symmetry ON, drag Y: the mirror keeps y, flips nothing else
        await page.evaluate("forge.view.brush.symBits = 2; forge.view.brush.symModel = true")   # Y only
        await select_left()
        await page.keyboard.press("w")
        p0 = await page.evaluate("() => forge.view.poly.v.map((p) => p.slice())")
        piv_y = await page.evaluate("() => { const v = forge.view, c = ForgePoly.median(v.poly, v.selectedVerts()); return [v.project(c), v.project([c[0], c[1] + 0.3, c[2]])]; }")
        dragged = False
        for k in range(4, 60, 2):
            t = k / 40.0
            x = cx + piv_y[0][0] + (piv_y[1][0] - piv_y[0][0]) * t
            y = cy + piv_y[0][1] + (piv_y[1][1] - piv_y[0][1]) * t
            await page.mouse.move(x, y)
            if await page.evaluate("forge.view.gizmo.axis") == "Y":
                await page.mouse.down(); await page.mouse.move(x, y + 60, steps=5); await page.mouse.up(); dragged = True
                break
        p1 = await page.evaluate("() => forge.view.poly.v.map((p) => p.slice())")
        # Y symmetry mirrors across XZ, so a Y drag moves the partner the opposite way in Y
        y_mirror = await page.evaluate("""(a) => { const p0 = a[0], p1 = a[1], N = p0.length, eps = 1e-4;
          const find = (q) => { for (let j = 0; j < N; j++) { const r = p0[j];
            if (Math.abs(r[0] - q[0]) < eps && Math.abs(r[1] - q[1]) < eps && Math.abs(r[2] - q[2]) < eps) return j; } return -1; };
          let pairs = 0, ok = 0, bad = [], d0 = 0;
          for (const i of forge.view.selectedVerts()) { const j = find([p0[i][0], -p0[i][1], p0[i][2]]); if (j < 0 || j === i) continue;
            pairs++; const di = [p1[i][1] - p0[i][1], p1[i][0] - p0[i][0]], dj = [p1[j][1] - p0[j][1], p1[j][0] - p0[j][0]];
            d0 = di[0];
            if (Math.abs(dj[0] + di[0]) < 1e-6 && Math.abs(dj[1]) < 1e-6 && Math.abs(di[1]) < 1e-6 && Math.abs(di[0]) > 1e-3) ok++;
            else bad.push([i, j, di, dj]); }
          return [pairs, ok, bad, d0]; }""", [p0, p1])
        check("Y symmetry mirrors about XZ: a Y drag moves each partner the opposite way in Y, X untouched",
              dragged and y_mirror[0] > 0 and y_mirror[1] == y_mirror[0] and not y_mirror[2], y_mirror)

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
