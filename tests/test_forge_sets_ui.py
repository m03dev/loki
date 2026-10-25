"""Create > Sets > Quick Select Set and Windows > Sets (app/ui/forge_sets.js; FORGE_MODELING_FOUNDATION stage 4):
a set of objects and a set of faces, picked again from the Sets window (the right object and component mode first),
+ / - / rename / delete, and undo carries the sets. Under a minute.

    python tests/test_forge_sets_ui.py
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

        S = "(() => { const v = forge.view, s = v.edit && v.edit.sel; return [v.edit ? v.edit.mode : '', s ? s.f.size : -1, forge.view.tree.api.root().name, forgeProComp(v)]; })()"
        await E("(async () => { await forgeProRun(forge.view, 'cube'); await forgeProRun(forge.view, 'sphere'); await forgeProRun(forge.view, 'cylinder'); })()")
        ids = await E("forge.view.tree.api.list().filter((n) => n.kind === 'mesh').map((n) => [n.id, n.name])")
        check("(three objects)", [x[1] for x in ids] == ["pCube1", "pSphere1", "pCylinder1"], ids)
        cube, sph, cyl = [x[0] for x in ids]
        await E("(() => { const t = forge.view.tree.api; t.select(%d, 'set'); t.select(%d, 'add'); })()" % (cube, cyl))
        msg = await E("forgeProRun(forge.view, 'quickSet')")
        sets = await E("forge.view.tree.api.setList().map((s) => [s.name, s.kind, s.items])")
        check("Quick Select Set on two picked objects: set1 holds them", sets == [["set1", "objects", [cube, cyl]]], (sets, msg))
        check("... and the Sets window opens with its row", await E("!document.getElementById('forge-sets').hidden && document.querySelectorAll('#forge-sets .fsets-row').length === 1"))
        # faces of the sphere
        await E("""(async () => { const v = forge.view, t = v.tree.api; t.select(%d, 'set'); await forgeProComponents(v, 'face');
          v.selectItems('face', [0, 1, 2, 3, 4], 'set'); })()""" % sph)
        await page.wait_for_timeout(120)
        await E("document.querySelector('#forge-sets .fx-foot .forge-btn').click()")
        sets = await E("forge.view.tree.api.setList().map((s) => [s.name, s.kind, s.items.length, s.node])")
        check("New Set in face mode on the sphere: 5 faces of the sphere", sets[-1] == ["set2", "face", 5, sph], sets)
        # leave, pick something else, then Select the face set from the window
        await E("(async () => { await forgeProObjectMode(forge.view); forge.view.tree.api.select(%d, 'set'); })()" % cube)
        await page.wait_for_timeout(120)
        await E("document.querySelector('#forge-sets .fsets-row[data-set=\"2\"] .forge-btn').click()")
        await page.wait_for_timeout(300)
        st = await E(S)
        check("Select on the face set: the sphere, in face mode, the same 5 faces", st == ["face", 5, "pSphere1", True], st)
        # + and -
        await E("forge.view.selectItems('face', [10, 11], 'set')")
        await E("ForgeSets.edit(2, +1)")
        n1 = await E("forge.view.tree.api.setGet(2).items.length")
        await E("forge.view.selectItems('face', [0, 10], 'set')")
        await E("ForgeSets.edit(2, -1)")
        n2 = await E("forge.view.tree.api.setGet(2).items.slice().sort((a, b) => a - b)")
        check("+ adds what is picked (7), - takes it out (5 left, without 0 and 10)", n1 == 7 and n2 == [1, 2, 3, 4, 11], (n1, n2))
        bad = await E("(async () => { await forgeProObjectMode(forge.view); forge.view.tree.api.select(%d, 'set'); return ForgeSets.edit(2, 1); })()" % cube)
        check("+ with objects picked on a face set says what the set holds", "faces" in bad, bad)
        # the object set from the window
        await E("document.querySelector('#forge-sets .fsets-row[data-set=\"1\"] .forge-btn').click()")
        await page.wait_for_timeout(200)
        check("Select on the object set: the cube and the cylinder picked, object mode",
              await E("[forge.view.tree.api.selected(), forgeProComp(forge.view)]") == [[cube, cyl], False])
        # rename, delete, undo
        await E("(() => { const i = document.querySelector('#forge-sets .fsets-row[data-set=\"1\"] .fsets-name'); i.value = 'props'; i.dispatchEvent(new Event('change')); })()")
        check("rename in the window", await E("forge.view.tree.api.setGet(1).name") == "props")
        await E("document.querySelector('#forge-sets .fsets-row[data-set=\"1\"] .forge-btn:last-child').click()")
        check("x deletes the set; the objects stay", await E("[forge.view.tree.api.setList().length, forge.view.tree.api.list().filter((n) => n.kind === 'mesh').length]") == [1, 3])
        await E("forge.view.undo(); ForgeSets.render()"); await page.wait_for_timeout(150)
        check("Ctrl+Z brings the deleted set back (sets are in the scene's undo)",
              await E("forge.view.tree.api.setList().map((s) => s.name)") == ["props", "set2"], await E("forge.view.tree.api.setList().map((s) => s.name)"))
        menu = await E("[forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Create') || [0, []])[1]), forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Windows') || [0, []])[1])]")
        check("Create has Quick Select Set, Windows has Sets (Maya's places)", "quickSet" in menu[0] and "setEditor" in menu[1], menu)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
