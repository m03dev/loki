"""Modify > Match Transformations (Maya: MatchTranslation / MatchRotation / MatchScaling / MatchTransform /
MatchPivots): the picked objects take the LAST picked one's world translation, rotation, scale or pivot place, one
undo step each; a parented object matches in world space too. Under a minute.

    python tests/test_forge_match_ui.py
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

        T = "forge.view.tree.api"
        W = """(id) => { const t = forge.view.tree.api, n = t.node(id), T = forge.view.THREE; n.grp.updateMatrixWorld(true);
          const p = new T.Vector3(), q = new T.Quaternion(), s = new T.Vector3(); n.grp.matrixWorld.decompose(p, q, s);
          const r = (a) => a.map((x) => +x.toFixed(4)); return { p: r(p.toArray()), q: r(q.toArray()).map((x, i, a) => (a[3] < 0 ? -x : x) + 0), s: r(s.toArray()) }; }"""
        BOX = """(id) => { const b = forge.view.tree.api.worldBox([id]); return [b.min.toArray(), b.max.toArray()].flat().map((x) => +x.toFixed(4)); }"""
        await E("(async () => { await forgeProRun(forge.view, 'cube'); await forgeProRun(forge.view, 'sphere'); await forgeProRun(forge.view, 'cylinder'); })()")
        ids = await E("forge.view.tree.api.list().filter((n) => n.kind === 'mesh').map((n) => n.id)")
        a, b, c = ids
        await E("""(() => { const t = forge.view.tree.api, b = %d; t.setTransform(b, 'translate', 0, 3); t.setTransform(b, 'translate', 1, 1);
          t.setTransform(b, 'rotate', 1, 30); t.setTransform(b, 'scale', 0, 2); t.setTransform(b, 'scale', 1, 2); t.setTransform(b, 'scale', 2, 2); })()""" % b)
        wb = await E("(%s)(%d)" % (W, b))
        sel = "(() => { const t = forge.view.tree.api; t.select(%d, 'set'); t.select(%d, 'add'); })()"
        await E(sel % (a, b))
        await E("forgeProRun(forge.view, 'matchTranslate')")
        wa = await E("(%s)(%d)" % (W, a))
        check("Match Translation: the cube's pivot lands on the sphere's (3, 1, 0); its rotation and scale stay", wa["p"] == wb["p"] and wa["s"] == [1, 1, 1], (wa, wb))
        await E("forgeProRun(forge.view, 'matchRotate')")
        wa = await E("(%s)(%d)" % (W, a))
        check("Match Rotation: the same world rotation (30° about Y)", wa["q"] == wb["q"], (wa["q"], wb["q"]))
        await E("forgeProRun(forge.view, 'matchScale')")
        check("Match Scaling: the same world scale (2, 2, 2)", (await E("(%s)(%d)" % (W, a)))["s"] == wb["s"])
        await E("forge.view.undo()")
        check("one undo takes back only the scale", (await E("(%s)(%d)" % (W, a)))["s"] == [1, 1, 1] and (await E("(%s)(%d)" % (W, a)))["q"] == wb["q"])
        # a parented object matches in WORLD space: the cylinder under a turned group
        await E("""(() => { const t = forge.view.tree.api; t.select(%d, 'set'); const g = t.group('grp', [%d]); t.setTransform(g, 'rotate', 2, 45); t.setTransform(g, 'translate', 2, -2); })()""" % (c, c))
        await E(sel % (c, b))
        await E("forgeProRun(forge.view, 'matchAll')")
        wc = await E("(%s)(%d)" % (W, c))
        check("Match All Transforms on an object inside a turned, moved group: the same world place, turn and size", wc == wb, (wc, wb))
        # Match Pivots: the pivot moves, the object does not
        box_a = await E("(%s)(%d)" % (BOX, a))
        await E("forge.view.tree.api.setTransform(%d, 'translate', 0, -4)" % a)
        box_a = await E("(%s)(%d)" % (BOX, a))
        await E(sel % (a, b))
        await E("forgeProRun(forge.view, 'matchPivot')")
        pa = await E("forge.view.tree.api.pivotWorld(%d).toArray().map((x) => +x.toFixed(4))" % a)
        check("Match Pivots: the cube's pivot goes onto the sphere's; the cube stays where it is", pa == wb["p"] and await E("(%s)(%d)" % (BOX, a)) == box_a, (pa, wb["p"]))
        one = await E("(async () => { const t = forge.view.tree.api; t.select(%d, 'set'); return forgeProMatch(forge.view, 'all'); })()" % a)
        check("one object picked: it says to pick two or more (the last is the target)", "last" in one, one)
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Modify') || [0, []])[1])")
        check("Modify > Match Transformations has all five, in Maya's place", all(x in menu for x in ("matchAll", "matchTranslate", "matchRotate", "matchScale", "matchPivot")), menu)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
