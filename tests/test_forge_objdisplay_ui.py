"""Display > Object Display (Maya): Template makes the picked object a grey wire that a viewport click goes through
(the Outliner still picks it, so Untemplate reaches it); Bounding Box draws it as its box and No Bounding Box brings
the mesh back; undo carries both. Under a minute.

    python tests/test_forge_objdisplay_ui.py
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

        await E("(async () => { await forgeProRun(forge.view, 'cube'); await forgeProRun(forge.view, 'sphere'); })()")
        ids = await E("forge.view.tree.api.sceneNodes().filter((n) => n.kind === 'mesh').map((n) => n.id)")
        cube, sph = ids
        LOOK = """(id) => { const t = forge.view.tree.api, n = t.node(id), s = n.inner.children.find((c) => c.isMesh && c.name === 'shape') || (n.root ? forge.view.meshObj && forge.view.meshObj() : null);
          return { tmpl: !!n.templated, wire: !!(s && s.material && s.material.wireframe), box: !!n.inner.children.find((c) => c.name === 'forge-bbox'), shown: !!(s && s.visible),
                   pick: t.pickables({ select: true }).some((o) => { let x = o; while (x) { if (x === n.grp) return true; x = x.parent; } return false; }) }; }"""
        await E("forge.view.tree.api.select(%d, 'set')" % cube)
        await E("forgeProRun(forge.view, 'templateObj')"); await page.wait_for_timeout(80)
        lk = await E("(%s)(%d)" % (LOOK, cube))
        check("Template: the cube is a grey wire, a viewport click goes through it, and it leaves the selection",
              lk["tmpl"] and lk["wire"] and not lk["pick"] and await E("forge.view.tree.api.selected()") == [], lk)
        await E("forge.view.tree.api.select(%d, 'set')" % cube)
        check("the Outliner still picks a templated object (so it can be untemplated)", await E("forge.view.tree.api.selected()") == [cube])
        await E("forgeProRun(forge.view, 'untemplateObj')"); await page.wait_for_timeout(80)
        lk = await E("(%s)(%d)" % (LOOK, cube))
        check("Untemplate: solid and pickable again", not lk["tmpl"] and not lk["wire"] and lk["pick"], lk)
        await E("forge.view.tree.api.select(%d, 'set')" % sph)
        await E("forgeProRun(forge.view, 'showBBox')"); await page.wait_for_timeout(80)
        lk = await E("(%s)(%d)" % (LOOK, sph))
        check("Bounding Box: the sphere draws as its box (the mesh hidden)", lk["box"] and not lk["shown"], lk)
        await E("forge.view.undo()"); await page.wait_for_timeout(100)
        lk = await E("(%s)(%d)" % (LOOK, sph))
        check("one undo: the sphere's mesh is back", not lk["box"] and lk["shown"], lk)
        await E("forge.view.redo()"); await page.wait_for_timeout(100)
        await E("forgeProRun(forge.view, 'hideBBox')"); await page.wait_for_timeout(80)
        lk = await E("(%s)(%d)" % (LOOK, sph))
        check("No Bounding Box: the mesh again", not lk["box"] and lk["shown"], lk)
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Display') || [0, []])[1])")
        check("Display > Object Display has Template, Untemplate, Bounding Box, No Bounding Box", all(x in menu for x in ("templateObj", "untemplateObj", "showBBox", "hideBBox")), menu)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
