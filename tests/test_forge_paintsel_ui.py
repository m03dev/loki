"""The Paint Selection Tool (Maya: ArtPaintSelectTool; forge_edit.js view.paintSelect / circleSelect): a real mouse
stroke over a plane adds faces, Ctrl + stroke takes them away, a click only takes what is under the brush, [ / ] size
it, vertex mode paints vertices, Esc / W put it down and a drag is a marquee again. Under a minute.

    python tests/test_forge_paintsel_ui.py
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

        S = "(() => { const s = forge.view.edit.sel; return [forge.view.edit.mode, s.v.size, s.e.size, s.f.size]; })()"
        await E("(async () => { await forgeProRun(forge.view, 'plane'); await forgeProRun(forge.view, 'frameAll'); })()")
        await page.wait_for_timeout(300)
        nf = await E("forge.view.poly.f.length")
        msg = await E("forgeProRun(forge.view, 'paintSelect')")
        await page.wait_for_timeout(150)
        check("Paint Selection Tool: face mode, the brush ring shows", await E("[forge.view.edit.mode, forge.view.edit.paint, !document.querySelector('.forge-paintsel').hidden]") == ["face", True, True], msg)
        # the middle of the plane on screen
        cx, cy = await E("""(() => { const v = forge.view, T = v.THREE, P = v.poly, c = [0, 1, 2].map((k) => P.v.reduce((a, p) => a + p[k], 0) / P.v.length);
          const q = new T.Vector3(c[0], c[1], c[2]).applyMatrix4(v.holder.matrixWorld).project(v.camera), r = v.canvas.getBoundingClientRect();
          return [r.left + (q.x + 1) / 2 * r.width, r.top + (1 - q.y) / 2 * r.height]; })()""")
        await E("forge.view.paintRadius(14)")
        await page.mouse.move(cx, cy); await page.mouse.down(); await page.mouse.up(); await page.wait_for_timeout(80)
        one = (await E(S))[3]
        check("a click paints only what is under the brush (a few faces, not all)", 1 <= one < nf, (one, nf))
        await page.mouse.move(cx - 120, cy); await page.mouse.down()
        for k in range(1, 13):
            await page.mouse.move(cx - 120 + k * 20, cy)
        await page.mouse.up(); await page.wait_for_timeout(80)
        stroke = (await E(S))[3]
        check("a stroke across the plane adds the faces it passes over", stroke > one and stroke < nf, (one, stroke, nf))
        await page.keyboard.down("Control"); await page.mouse.move(cx - 120, cy); await page.mouse.down()
        for k in range(1, 13):
            await page.mouse.move(cx - 120 + k * 20, cy)
        await page.mouse.up(); await page.keyboard.up("Control"); await page.wait_for_timeout(80)
        check("Ctrl + the same stroke takes them away again", (await E(S))[3] < stroke, await E(S))
        r0 = await E("forge.view.paintRadius()")
        await page.keyboard.press("]"); r1 = await E("forge.view.paintRadius()")
        await page.keyboard.press("["); await page.keyboard.press("["); r2 = await E("forge.view.paintRadius()")
        check("] makes the brush bigger, [ smaller", r1 > r0 and r2 < r1, (r0, r1, r2))
        await E("(async () => { forge.view.setSelMode('vert'); forge.view.selectItems('vert', [], 'set'); })()")
        await page.mouse.move(cx, cy); await page.mouse.down(); await page.mouse.move(cx + 30, cy + 10); await page.mouse.up()
        await page.wait_for_timeout(80)
        st = await E(S)
        check("vertex mode: the brush paints vertices", st[0] == "vert" and 1 <= st[1] < await E("forge.view.poly.v.length"), st)
        await page.keyboard.press("Escape"); await page.wait_for_timeout(50)
        check("Esc puts the brush down (the ring goes)", await E("[forge.view.edit.paint, document.querySelector('.forge-paintsel').hidden]") == [False, True])
        await E("forgeProRun(forge.view, 'paintSelect')")
        await page.keyboard.press("w"); await page.wait_for_timeout(50)
        check("W (the Move tool) puts it down too", await E("forge.view.edit.paint") is False)
        await E("forge.view.setSelMode('face')")
        await page.mouse.move(cx - 60, cy - 60); await page.mouse.down(); await page.mouse.move(cx + 60, cy + 60, steps=4); await page.mouse.up()
        await page.wait_for_timeout(80)
        check("without the brush a drag is a marquee again (a box of faces)", (await E(S))[3] >= 4, await E(S))
        menu = await E("forgeMenuFlat((FMY_MENUS().find((m) => m[0] === 'Select') || [0, []])[1])")
        check("Select lists the Paint Selection Tool", "paintSelect" in menu, menu)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
