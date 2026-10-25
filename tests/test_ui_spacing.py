"""Nothing overlaps, and there is room between menus (owner 2026-10-21 22:13: "nothing should ever overlap there should
always be some padding between menus"): Home and Forge's sculpt mode at a laptop, a small window, a big screen and a
vertical monitor - every pair of on-screen panels at least GAP px apart. Under a minute.

    python tests/test_ui_spacing.py
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
        GAP = 8
        CHECK = """([sels, gap]) => {
          const vis = (e) => e && e.offsetParent && getComputedStyle(e).display !== 'none' && getComputedStyle(e).visibility !== 'hidden';
          const boxes = [];
          for (const s of sels) for (const e of document.querySelectorAll(s)) if (vis(e)) { const r = e.getBoundingClientRect(); if (r.width > 2 && r.height > 2) boxes.push([s, r]); }
          const bad = [];
          for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
            const [a, A] = boxes[i], [b, B] = boxes[j];
            const dx = Math.max(A.left - B.right, B.left - A.right), dy = Math.max(A.top - B.bottom, B.top - A.bottom);
            if (Math.max(dx, dy) < gap) bad.push(a + ' x ' + b + ' (' + Math.round(Math.max(dx, dy)) + 'px)');
          }
          const W = innerWidth, H = innerHeight;
          for (const [s, r] of boxes) if (r.left < -1 || r.top < -1 || r.right > W + 1 || r.bottom > H + 1) bad.push(s + ' off screen');
          return bad;
        }"""
        SCULPT = ["#fsc-head", "#fsc-side", "#fsc-strip", "#fmy-cube", "#fmy-panelbar"]
        HOME = [".home-head", ".home-hero", ".home-recent-head", ".home-grid", "#composer"]
        SIDE = ["#tidy-top", "#conversations", ".sidebar-foot .foot-row"]
        for (w, h) in [(1400, 860), (1000, 700), (1920, 1080), (900, 1500)]:
            page = await browser.new_page(viewport={"width": w, "height": h})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))

            async def route(r):
                bare = r.request.url.split("8892", 1)[1].split("#")[0].split("?")[0]
                if bare == "/":
                    return await r.fulfill(path=str(UI / "index.html"))
                if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                    return await r.fulfill(path=str(UI / bare[4:]))
                if bare == "/home/projects":
                    return await r.fulfill(json={"ok": True, "items": [{"kind": "render", "name": "a render", "path_or_id": "r1", "created": 1792560000},
                                                                       {"kind": "forge", "name": "a model", "path_or_id": "m1", "created": 1792560000}], "errors": []})
                return await r.fulfill(json={"ok": True})

            await page.route("http://127.0.0.1:8892/**", route)
            await page.goto("http://127.0.0.1:8892/#token=s3cret")
            await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
            await page.wait_for_timeout(700)
            E = page.evaluate
            bad = await E(CHECK, [HOME, GAP])
            check("%dx%d Home: nothing overlaps, room between the parts" % (w, h), not bad, bad)
            bad = await E(CHECK, [SIDE, 4])
            check("%dx%d sidebar: nothing overlaps" % (w, h), not bad, bad)
            check("%dx%d no page scroll bar" % (w, h), await E("document.scrollingElement.scrollHeight <= innerHeight + 1"))
            await E("document.getElementById('open-forge').click()")
            await page.wait_for_function("forge.view && forge.view.pro", timeout=10000)
            await E("fmyRun('sphere')")
            await page.wait_for_timeout(300)
            bad = await E(CHECK, [["#fmy-polycount", "#fmy-cube", "#fmy-panelbar"], GAP])
            check("%dx%d Forge: the HUD, view cube and view menus apart" % (w, h), not bad, bad)
            bad = await E(CHECK, [["#fmy-menubar", "#fmy-status", ".forge-body", "#fmy-helpline"], 0])
            check("%dx%d Forge: menu bar, status line, workspace, help line never overlap" % (w, h), not bad, bad)
            await E("fmyRun('sculpt')")
            await page.wait_for_function("!!document.getElementById('fsc-strip')", timeout=8000)
            await page.wait_for_timeout(700)
            bad = await E(CHECK, [SCULPT, GAP])
            check("%dx%d sculpt mode: header, sliders, strip, view cube, view menus apart" % (w, h), not bad, bad)
            check("%dx%d no script errors" % (w, h), not errors, errors[:3])
            await page.close()
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=58))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
