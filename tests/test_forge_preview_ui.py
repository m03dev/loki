"""Forge's tool previews: with the Insert Edge Loop tool armed, hovering an edge draws the loop that a click would
insert (nothing committed), the click runs it, and the preview goes away. Under a minute.

    python tests/test_forge_preview_ui.py
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

PREVIEW = """() => { const v = forge.view, l = v.holder && v.holder.getObjectByName('forge-loop-preview');
  return l && l.geometry && l.geometry.attributes.position ? l.geometry.attributes.position.count : 0; }"""


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
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        await page.evaluate("forgeAddPrimitive('cube')")
        await page.wait_for_function("forge.view && forge.view.sm && forge.view.tree", timeout=10000)
        await page.evaluate("forgeModelMode(true)")
        await page.wait_for_function("forge.view.mode === 'poly' && !!forge.view.poly", timeout=8000)
        await page.evaluate("forge.view.frame()")
        canvas = await page.eval_on_selector("#forge-view", "c => { const r = c.getBoundingClientRect(); return [r.x, r.y]; }")
        cx, cy = canvas
        E = page.evaluate

        async def edge_screen(i):
            return await E("""(i) => { const v = forge.view, P = window.ForgePoly, T = P.topology(v.poly), e = T.edges[i];
              if (!e) return null; const a = v.poly.v[e.a], b = v.poly.v[e.b];
              const m = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
              const s = v.project(m); return s ? [s[0], s[1]] : null; }""", i)

        # nothing armed: no preview
        pt = await edge_screen(0)
        await page.mouse.move(cx + pt[0], cy + pt[1])
        await page.wait_for_timeout(60)
        idle = await E(PREVIEW)
        check("no tool armed: no loop preview", idle == 0, idle)

        # arm the Insert Edge Loop tool, hover an edge
        armed = await E("forge.view.setSelMode('edge'), window.forgeToolkit.tool('insertEdgeLoop')")
        await page.mouse.move(cx + pt[0], cy + pt[1])
        await page.wait_for_timeout(90)
        shown = await E(PREVIEW)
        check("the Insert Edge Loop tool draws the loop it would make, under the cursor",
              armed is True and shown >= 4 and await E("window.forgePreviewState().reason") == "shown", [armed, shown])

        # it follows a different edge
        pt2 = await edge_screen(1)
        await page.mouse.move(cx + pt2[0], cy + pt2[1])
        await page.wait_for_timeout(90)
        pos2 = await E("() => { const l = forge.view.holder.getObjectByName('forge-loop-preview'); const a = l.geometry.attributes.position; return [a.getX(0), a.getY(0), a.getZ(0)]; }")
        pt3 = await edge_screen(2)
        await page.mouse.move(cx + pt3[0], cy + pt3[1])
        await page.wait_for_timeout(90)
        pos3 = await E("() => { const l = forge.view.holder.getObjectByName('forge-loop-preview'); const a = l.geometry.attributes.position; return [a.getX(0), a.getY(0), a.getZ(0)]; }")
        check("the preview follows the edge under the cursor", pos2 != pos3, [pos2, pos3])

        # the click inserts the loop and the preview goes away
        faces0 = await E("forge.view.poly.f.length")
        await page.mouse.move(cx + pt3[0], cy + pt3[1])
        await page.wait_for_timeout(60)
        await page.mouse.click(cx + pt3[0], cy + pt3[1])
        await page.wait_for_timeout(200)
        faces1 = await E("forge.view.poly.f.length")
        after = await E(PREVIEW)
        check("clicking inserts the loop (more faces) and the preview is gone",
              faces1 > faces0 and after == 0, [faces0, faces1, after])

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
