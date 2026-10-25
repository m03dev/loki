"""Edit > Cut / Copy / Paste (Ctrl+X / C / V, Maya's keys) on objects: Copy + Paste makes copies in place with their
transforms; Cut takes them away and Paste brings them back (as they were, in world space); each is one undo step.
Under a minute.

    python tests/test_forge_clipboard_ui.py
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

        MESH = "forge.view.tree.api.sceneNodes().filter((n) => n.kind === 'mesh').map((n) => n.name)"
        BOX = """(ids) => { const b = forge.view.tree.api.worldBox(ids); return [b.min.toArray(), b.max.toArray()].flat().map((x) => +x.toFixed(4)); }"""
        await E("(async () => { await forgeProRun(forge.view, 'cube'); await forgeProRun(forge.view, 'sphere'); })()")
        ids = await E("forge.view.tree.api.sceneNodes().filter((n) => n.kind === 'mesh').map((n) => n.id)")
        await E("(() => { const t = forge.view.tree.api; t.setTransform(%d, 'translate', 0, 3); t.setTransform(%d, 'rotate', 1, 30); t.select(%d, 'set'); })()" % (ids[1], ids[1], ids[1]))
        b_sph = await E("(%s)([%d])" % (BOX, ids[1]))
        await E("forge.view.canvas.focus && forge.view.canvas.focus()")
        await page.keyboard.press("Control+c"); await page.wait_for_timeout(60)
        await page.keyboard.press("Control+v"); await page.wait_for_timeout(120)
        names = await E(MESH)
        new = await E("forge.view.tree.api.selected()")
        check("Ctrl+C, Ctrl+V: a copy of the sphere, picked, in the same place and turn", len(names) == 3 and new and new[0] not in ids and await E("(%s)(%s)" % (BOX, new)) == b_sph, (names, new))
        q = await E("[%d, %d].map((id) => forge.view.tree.api.node(id).grp.quaternion.toArray().map((x) => +x.toFixed(4)))" % (ids[1], new[0]))
        check("... it is a real copy with its own transform: the same 30° turn about Y", q[0] == q[1] and abs(q[1][1]) > 0.2, q)
        await E("forge.view.undo()"); await page.wait_for_timeout(80)
        check("one undo takes the paste back", len(await E(MESH)) == 2)
        # cut: gone, then paste brings it back as it was
        await E("forge.view.tree.api.select(%d, 'set')" % ids[0])
        b_cube = await E("(%s)([%d])" % (BOX, ids[0]))
        await page.keyboard.press("Control+x"); await page.wait_for_timeout(100)
        check("Ctrl+X: the cube is gone", await E(MESH) == ["pSphere1"], await E(MESH))
        await page.keyboard.press("Control+v"); await page.wait_for_timeout(120)
        back = await E("forge.view.tree.api.selected()")
        check("Ctrl+V after the cut: the cube is back, where it was, as a new object", len(await E(MESH)) == 2 and back and await E("(%s)(%s)" % (BOX, back)) == b_cube, (await E(MESH), back))
        await page.keyboard.press("Control+v"); await page.wait_for_timeout(120)
        check("Paste again: another one (the clipboard stays)", len(await E(MESH)) == 3)
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Edit') || [0, []])[1])")
        check("Edit has Cut, Copy and Paste in Maya's order", [x for x in menu if x in ("cutSel", "copySel", "pasteSel")] == ["cutSel", "copySel", "pasteSel"], menu)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
