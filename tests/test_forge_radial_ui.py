"""Forge's radial symmetry end to end: the UI command sets it, the stroke carries it to the sculpt worker, and a
real mouse stroke repeats the dab around the object axis (the core change is checked by
native/sculpt/wasm/test/test_engine.js's "radial symmetry" line). Under a minute.

    python tests/test_forge_radial_ui.py
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

# moved vertices since `before`, and how many azimuthal sectors (around the object's Y through its centroid)
MOVE = """(a) => { const p0 = a[0], p1 = a[1]; let cx = 0, cz = 0, n = 0;
  for (let i = 0; i < p0.length; i += 3) { cx += p0[i]; cz += p0[i + 2]; n++; }
  cx /= n; cz /= n;
  let moved = 0; const sect = new Set();
  for (let i = 0; i < p0.length; i += 3) {
    if (Math.abs(p0[i] - p1[i]) + Math.abs(p0[i + 1] - p1[i + 1]) + Math.abs(p0[i + 2] - p1[i + 2]) > 1e-5) {
      moved++; sect.add(Math.floor(((Math.atan2(p1[i + 2] - cz, p1[i] - cx) + Math.PI + Math.PI / 4) % (2 * Math.PI)) / (Math.PI / 2)));
    }
  }
  return [moved, sect.size]; }"""


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
            bare = r.request.url.split("8897", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8897/**", route)
        await page.goto("http://127.0.0.1:8897/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("forgeOpen()")
        await page.wait_for_function("!!(forge.view && forge.view.showPoly)", timeout=20000)
        await page.evaluate("forgeModelMode(true)")
        await page.evaluate("document.querySelector(\"#forge [data-prim='sphere']\").click()")
        await page.evaluate("forge.view.frame()")
        if not await page.evaluate("forge.view.mode === 'sculpt'"):
            await page.evaluate("forgeMode()")
        try:
            await page.wait_for_function("window.ForgeSculpt && (window.ForgeSculpt.ok || window.ForgeSculpt.failed)", timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        if not await page.evaluate("!!ForgeSculpt.ok"):
            check("the sculpting engine loads (needed for radial)", False, await page.evaluate("ForgeSculpt.failed"))
            await browser.close()
            return
        canvas = await page.eval_on_selector("#forge-view", "c => { const r = c.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
        cx, cy, cw, ch = canvas
        mx, my = cx + cw / 2, cy + ch / 2
        idle = "() => !ForgeSculpt.pressed && !ForgeSculpt.openStrokes && !ForgeSculpt.busy"
        E = page.evaluate

        await E("forge.view.brush.radius = 0.12; forge.view.brush.symBits = 0; forge.view.brush.symModel = false; forge.view.brush.radial = 0;")
        await E("forgeBrush('draw')")

        async def stroke():
            before = await E("forge.view.sm.wpos.slice()")
            await page.mouse.move(mx, my)
            await page.mouse.down()
            await page.mouse.move(mx + 20, my + 10, steps=6)
            await page.mouse.up()
            await page.wait_for_function(idle, timeout=10000)
            await page.wait_for_timeout(80)
            after = await E("forge.view.sm.wpos.slice()")
            return await E(MOVE, [before, after])

        off = await stroke()
        await E("forge.view.undo()")
        await page.wait_for_timeout(60)

        cmd = await E("forgeProRun(forge.view, 'symRadial4')")
        await E("fmySync()")
        ui = await E("[forge.view.brush.radial, forge.view.brush.radialAxis, document.getElementById('fmy-symlabel').textContent]")
        check("Radial Symmetry 4 sets the brush and the status line reads it",
              ui[0] == 4 and ui[1] == 1 and "Radial 4 Y" in ui[2], [cmd, ui])

        four = await stroke()
        check("radial 4 repeats one stroke into several sectors (symmetric-x/z copies)",
              off[0] >= 1 and four[0] >= off[0] * 2 and four[0] >= 4 and four[1] >= 3 and off[1] <= 2, [off, four])

        await E("forgeProRun(forge.view, 'symRadialOff')")
        await E("fmySync()")
        gone = await E("[forge.view.brush.radial, document.getElementById('fmy-symlabel').textContent]")
        check("Radial Symmetry Off stops it", gone[0] == 0, gone)

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
