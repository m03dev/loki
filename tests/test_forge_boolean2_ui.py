"""Mesh > Booleans > Slice, Hole Punch, Cut Out and Split Edges (Maya's open booleans; app/ui/forge_boolean.js): only
the first mesh's surface is kept, cut where the second crosses it. Two unit cubes overlapping off-axis (so no faces
lie on each other): Hole Punch leaves the first cube's surface minus the part inside the second (area 5, open),
Cut Out only that part (area 1, open), Slice both as two pieces (area 6), Split Edges one closed surface (area 6)
with new edges along the cut. One undo each. Under a minute.

    python tests/test_forge_boolean2_ui.py
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
        res = await E("""(async () => { const w = (ms) => new Promise(r => setTimeout(r, ms)); const v = forge.view, t = v.tree.api, P = window.ForgePoly, out = {};
          const area = (m) => m.f.reduce((a, f) => { let x = 0, y = 0, z = 0; for (let k = 0; k < f.length; k++) { const p = m.v[f[k]], q = m.v[f[(k + 1) % f.length]];
            x += (p[1] - q[1]) * (p[2] + q[2]); y += (p[2] - q[2]) * (p[0] + q[0]); z += (p[0] - q[0]) * (p[1] + q[1]); } return a + Math.hypot(x, y, z) / 2; }, 0);
          for (const op of ['boolHolePunch', 'boolCutOut', 'boolSlice', 'boolSplitEdges']) {
            for (const x of t.sceneNodes()) t.remove(x.id);
            const old = new Set(t.sceneNodes().map((n) => n.id));
            await forgeProRun(v, 'cube'); await w(100); const a = t.selected()[0];
            await forgeProRun(v, 'cube'); await w(100); const b = t.selected()[0];
            t.setTransform(b, 'translate', 0, 0.5); t.setTransform(b, 'translate', 1, 0.5); t.setTransform(b, 'translate', 2, 0.25);
            t.select(a); t.select(b, 'add');
            out[op + '_said'] = await FORGE_PRO_CMDS[op][1](v); await w(150);
            const meshes = t.sceneNodes().filter((n) => n.kind === 'mesh' && !old.has(n.id));
            const m = t.worldPolys(meshes.map((n) => n.id))[0];
            const T = m && P.topology(m.poly);
            out[op] = { n: meshes.length, name: meshes[0] && meshes[0].name, area: m ? +area(m.poly).toFixed(3) : null, faces: m ? m.poly.f.length : 0,
              open: T ? T.edges.filter((e) => e.faces.length === 1).length : -1, shells: m && P.shells ? P.shells(m.poly).length : -1 };
            await forgeProRun(v, 'undo'); await w(150);
            out[op].undo = t.sceneNodes().filter((n) => n.kind === 'mesh' && !old.has(n.id)).length;
          }
          return out; })()""")
        hp, co, sl, se = (dict(res.get(k) or {}, said=res.get(k + "_said")) for k in ("boolHolePunch", "boolCutOut", "boolSlice", "boolSplitEdges"))
        check("Hole Punch: one new object, the first cube's surface minus what is inside the second (area 5), the hole open",
              hp.get("n") == 1 and abs((hp.get("area") or 0) - 5) < 0.01 and hp.get("open", 0) > 0, hp)
        check("Cut Out: only the first cube's surface inside the second (area 1), open", co.get("n") == 1 and abs((co.get("area") or 0) - 1) < 0.01 and co.get("open", 0) > 0, co)
        check("Slice: both parts (area 6 in all), as two separate pieces of one object", sl.get("n") == 1 and abs((sl.get("area") or 0) - 6) < 0.01 and sl.get("shells") == 2, sl)
        check("Split Edges: the same closed surface (area 6, one piece, no open edge) with new edges where the second crossed it",
              se.get("n") == 1 and abs((se.get("area") or 0) - 6) < 0.01 and se.get("shells") == 1 and se.get("open") == 0 and se.get("faces", 0) > 6, se)
        check("each: one undo brings both cubes back", all(x.get("undo") == 2 for x in (hp, co, sl, se)), [x.get("undo") for x in (hp, co, sl, se)])
        miss = await E("""(async () => { const w = (ms) => new Promise(r => setTimeout(r, ms)); const v = forge.view, t = v.tree.api;
          for (const x of t.sceneNodes()) t.remove(x.id); await forgeProRun(v, 'cube'); await w(80); const a = t.selected()[0];
          await forgeProRun(v, 'cube'); await w(80); const b = t.selected()[0]; t.setTransform(b, 'translate', 0, 5); t.select(a); t.select(b, 'add');
          return FORGE_PRO_CMDS.boolSlice[1](v); })()""")
        check("Slice with cubes that do not touch: says so, changes nothing", "do not cross" in str(miss), miss)
        check("Maya's Mesh > Booleans menu has the four", await E("['boolSlice','boolHolePunch','boolCutOut','boolSplitEdges'].every((id) => JSON.stringify(FORGE_MAYA.menus || FORGE_MAYA).includes(id))"))
        check("no script errors", not errors, errors[:5])
        await browser.close()


t0 = time.time()
asyncio.run(asyncio.wait_for(main(), 58))
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
