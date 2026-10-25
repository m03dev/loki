"""Select > Grow / Shrink Along Loop, Contiguous Edges and Every Nth in Loop / Ring in a real Forge window
(docs/FORGE_MODELING_FOUNDATION.md stage 4). Under a minute.

    python tests/test_forge_loopsel_ui.py
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

        S = "(() => { const v = forge.view, s = v.edit.sel; return [v.edit.mode, s.v.size, s.e.size, s.f.size]; })()"
        await E("forgeProRun(forge.view, 'plane')"); await page.wait_for_timeout(200)
        info = await E("""(() => { const v = forge.view, P = ForgePoly, T = P.topology(v.poly);
          // the longest row of inside edges (the border is a loop too: not that one)
          const lens = T.edges.map((e, i) => (P.edgeLoop(v.poly, T, i).every((x) => T.edges[x].faces.length === 2) ? P.edgeLoop(v.poly, T, i).length : 0));
          const best = Math.max(...lens), ei = lens.indexOf(best);
          return { faces: v.poly.f.length, loop: best, ei }; })()""")
        check("(a plane with rows of quads)", info["faces"] >= 16 and info["loop"] >= 4 and info["ei"] >= 0, info)
        n = info["loop"]
        PICK1 = """(async () => { const v = forge.view, P = ForgePoly, T = P.topology(v.poly), ei = %d, L = P.edgeLoop(v.poly, T, ei);
          await forgeProRun(v, 'edge');
          // the middle edge of the row: walk it in order from one end
          const set = new Set(L), nb = (x) => [T.edges[x].a, T.edges[x].b].flatMap((a) => T.vertEdges[a]).filter((y) => y !== x && set.has(y));
          let end = L.find((x) => nb(x).length === 1), seen = new Set(), row = [];
          for (let c = end; c !== undefined; c = nb(c).find((y) => !seen.has(y))) { seen.add(c); row.push(c); }
          window.__row = row; v.selectItems('edge', [v.edgeIdOf(T.edges[row[row.length >> 1]].a, T.edges[row[row.length >> 1]].b)], 'set'); })()""" % info["ei"]
        await E(PICK1); await page.wait_for_timeout(100)
        check("(one edge picked in the middle of the row)", (await E(S))[:3] == ["edge", 2, 1] or (await E(S))[2] == 1, await E(S))
        await E("forgeProRun(forge.view, 'growLoop')"); await page.wait_for_timeout(100)
        check("Grow Along Loop: one edge -> 3 along the row", (await E(S))[2] == 3, await E(S))
        await E("forgeProRun(forge.view, 'growLoop')"); await page.wait_for_timeout(100)
        check("... again -> 5 (or the whole row when it is short)", (await E(S))[2] == min(5, n), await E(S))
        await E("forgeProRun(forge.view, 'shrinkLoop')"); await page.wait_for_timeout(100)
        check("Shrink Along Loop gives the ends back", (await E(S))[2] == min(5, n) - 2, await E(S))
        await E("""(() => { const v = forge.view, T = ForgePoly.topology(v.poly);
          v.selectItems('edge', window.__row.map((x) => v.edgeIdOf(T.edges[x].a, T.edges[x].b)), 'set'); forgeProRun(v, 'everyNth2'); })()""")
        await page.wait_for_timeout(100)
        check("Every 2nd of the whole row: half of it, rounded up", (await E(S))[2] == (n + 1) // 2, (await E(S), n))
        await E("""(() => { const v = forge.view, T = ForgePoly.topology(v.poly), x = window.__row[0];
          v.selectItems('edge', [v.edgeIdOf(T.edges[x].a, T.edges[x].b)], 'set'); forgeProRun(v, 'contiguousEdges'); })()""")
        await page.wait_for_timeout(100)
        check("Contiguous Edges from the row's first edge: the whole row", (await E(S))[2] == n, await E(S))
        await E("""(async () => { const v = forge.view, T = ForgePoly.topology(v.poly), x = window.__row[1];
          await forgeProRun(v, 'face'); v.selectItems('face', T.edges[x].faces.slice(), 'set'); })()""")
        await page.wait_for_timeout(100)
        st0 = await E(S)
        await E("forgeProRun(forge.view, 'growLoop')"); await page.wait_for_timeout(100)
        st = await E(S)
        check("Grow Along Loop on two faces in a row: one more at each end that is not the border (3 or 4)", st0[3] == 2 and st[0] == "face" and st[3] in (3, 4), (st0, st))
        msg = await E("(async () => { const v = forge.view; v.selectItems('face', [0], 'set'); return forgeProRun(v, 'growLoop'); })()")
        check("one face alone: says to pick two in a row (which way the strip runs)", "two faces" in str(msg) or (await E(S))[3] == 1, msg)
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Select') || [0, []])[1])")
        check("Select lists Grow / Shrink Along Loop, Contiguous Edges and Every Nth",
              all(x in menu for x in ("growLoop", "shrinkLoop", "contiguousEdges", "everyNth2", "everyNth3")), menu)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
