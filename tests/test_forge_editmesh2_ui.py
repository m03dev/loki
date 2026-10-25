"""Edit Mesh > Edit Edge Flow and Edit Mesh > Transform, Mesh Tools > Connect, in a real Forge window: a sphere's
loop pulled in towards its middle goes back out onto the round when Edit Edge Flow runs on it (one undo step, in the
construction history); Transform puts the move handle on the components along their normal. Under a minute.

    python tests/test_forge_editmesh2_ui.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
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
        F = "forge.view.tree.api.worldPolys ? (() => { const t = forge.view.tree.api; return forge.view.poly ? forge.view.poly.f.length : -1; })() : -1"

        await E("forgeProRun(forge.view, 'sphere')"); await page.wait_for_timeout(200)
        # the loop nearest the equator, then pull it in to 80 % of the radius (as a flat cut would leave it)
        info = await E("""(async () => { const v = forge.view, P = ForgePoly, T = P.topology(v.poly);
          const c = [0, 1, 2].map((k) => v.poly.v.reduce((a, p) => a + p[k], 0) / v.poly.v.length);
          const r = (p) => Math.hypot(p[0] - c[0], p[1] - c[1], p[2] - c[2]);
          let best = -1, bd = Infinity;
          T.edges.forEach((e, i) => { const y = (v.poly.v[e.a][1] + v.poly.v[e.b][1]) / 2; if (Math.abs(v.poly.v[e.a][1] - v.poly.v[e.b][1]) < 1e-6 && Math.abs(y - c[1]) < bd) { bd = Math.abs(y - c[1]); best = i; } });
          const loop = P.edgeLoop(v.poly, T, best), vs = [...new Set(loop.flatMap((ei) => [T.edges[ei].a, T.edges[ei].b]))];
          const R = r(v.poly.v[vs[0]]), m = P.clone(v.poly);
          for (const i of vs) { const p = m.v[i]; m.v[i] = [c[0] + (p[0] - c[0]) * 0.8, p[1], c[2] + (p[2] - c[2]) * 0.8]; }
          v.showPoly(m, true);
          await forgeProRun(v, 'edge'); v.selectItems('edge', loop.map((ei) => v.edgeIdOf(T.edges[ei].a, T.edges[ei].b)), 'set');
          window.__loop = { vs, c, R };
          return { n: loop.length, R, r0: r(v.poly.v[vs[0]]) }; })()""")
        check("(a loop round the sphere, pulled in to 80 %)", info["n"] >= 8 and abs(info["r0"] / info["R"] - 0.8) < 0.02, info)
        RAD = "(() => { const v = forge.view, L = window.__loop; return L.vs.map((i) => Math.hypot(v.poly.v[i][0] - L.c[0], v.poly.v[i][2] - L.c[2])).reduce((a, x) => a + x, 0) / L.vs.length; })()"
        r_in = await E(RAD)
        await E("forgeProRun(forge.view, 'editEdgeFlow')"); await page.wait_for_timeout(150)
        r_out = await E(RAD)
        flat_r = await E("(() => { const v = forge.view, L = window.__loop, p = v.poly.v[L.vs[0]]; return Math.hypot(p[0] - L.c[0], p[2] - L.c[2]) / Math.hypot(p[0] - L.c[0], p[1] - L.c[1], p[2] - L.c[2]); })()")
        check("Edit Edge Flow: the loop goes back out towards the round (within 3 % of where it was before the dent)", r_out > r_in and abs(r_out - info["R"]) / info["R"] < 0.03, (r_in, r_out, info["R"], flat_r))
        check("... it is a node in the construction history (polyEditEdgeFlow)", await E("(() => { const h = forgeModel.hist; const o = h && h.ops.slice(-1)[0]; return o ? o.op || o.kind : null; })()") == "editEdgeFlow")
        await E("forge.view.undo()"); await page.wait_for_timeout(100)
        check("one undo: the dent is back", abs(await E(RAD) - r_in) < 1e-6)
        # Transform: the move handle along the components' normal
        await E("(async () => { const v = forge.view; await forgeProRun(v, 'face'); v.selectItems('face', [0], 'set'); await forgeProRun(v, 'transformComp'); })()")
        await page.wait_for_timeout(100)
        st = await E("[forge.view.gizmo.mode, forge.view.axes(), forge.view.gizmo.space]")
        check("Edit Mesh > Transform: the move handle, on Component (normal) axes", st == ["translate", "normal", "local"], st)
        await E("forgeProRun(forge.view, 'objectAxes')")
        menus = await E("[forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Edit Mesh') || [0, []])[1]), forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Mesh Tools') || [0, []])[1])]")
        check("Edit Mesh has Edit Edge Flow and Transform; Mesh Tools has Connect", "editEdgeFlow" in menus[0] and "transformComp" in menus[0] and "connect" in menus[1], menus)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
