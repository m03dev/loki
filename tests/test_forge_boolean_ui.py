"""Forge's Mesh > Booleans (app/ui/forge_boolean.js on the vendored three-bvh-csg, MIT): Union / Difference /
Difference (B - A) / Intersection of two picked cubes give the right volumes, the result is one new object and ONE undo
step brings the originals back; the Maya menu has them; every vendored module import resolves. Under a minute.

    python tests/test_forge_boolean_ui.py
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
        res = await E("""(async () => { const w = (ms) => new Promise(r => setTimeout(r, ms)); const v = forge.view, t = v.tree.api, P = window.ForgePoly, out = {};
          for (const op of ['boolUnion', 'boolDifference', 'boolDifferenceBA', 'boolIntersection']) {
            for (const x of t.sceneNodes()) t.remove(x.id);
            const old = new Set(t.sceneNodes().map((n) => n.id));     // the edited object can't be removed; leave it out
            await forgeProRun(v, 'cube'); await w(120); const a = t.selected()[0];
            await forgeProRun(v, 'cube'); await w(120); const b = t.selected()[0];
            t.setTransform(b, 'translate', 0, 0.5); t.setTransform(b, 'translate', 1, 0.5);
            t.select(a); t.select(b, 'add');
            out[op + '_sel'] = t.selected().length; const said = await FORGE_PRO_CMDS[op][1](v); await w(150); out[op + '_said'] = said;
            const meshes = t.sceneNodes().filter((n) => n.kind === 'mesh' && !old.has(n.id));
            const m = t.worldPolys(meshes.map((n) => n.id))[0];
            out[op] = { n: meshes.length, name: meshes[0] && meshes[0].name, vol: m ? +P.volume(m.poly).toFixed(4) : null };
            await forgeProRun(v, 'undo'); await w(150);
            out[op].undo = t.sceneNodes().filter((n) => n.kind === 'mesh' && !old.has(n.id)).length;
          }
          return out; })()""")
        for op, vol in (("boolUnion", 1.75), ("boolDifference", 0.75), ("boolDifferenceBA", 0.75), ("boolIntersection", 0.25)):
            r = dict(res.get(op) or {}, sel=res.get(op + '_sel'), said=res.get(op + '_said'))
            check("%s of two unit cubes half overlapping: one new object (polySurface), volume %s" % (op, vol),
                  r.get("n") == 1 and str(r.get("name", "")).startswith("polySurface") and abs((r.get("vol") or 0) - vol) < 1e-3, r)
            check("%s: one undo brings both cubes back" % op, r.get("undo") == 2, r)
        msg = await E("(async () => { const t = forge.view.tree.api; for (const x of t.sceneNodes()) t.remove(x.id); await forgeProRun(forge.view, 'cube'); return await FORGE_PRO_CMDS.boolUnion[1](forge.view); })()")
        check("one mesh picked: it says what to pick", "two or more meshes" in str(msg), msg)
        check("Maya's Mesh > Booleans menu has the four", await E("['boolUnion','boolDifference','boolDifferenceBA','boolIntersection'].every((id) => JSON.stringify(FORGE_MAYA.menus || FORGE_MAYA).includes(id))"))
        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
