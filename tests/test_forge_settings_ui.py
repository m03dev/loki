"""Forge's Settings window and one menu look (owner 2026-10-25: "the preference window needs a hotkey tab ... an actual
settings window ... change my hotkeys, the way i pivot or move, everything modular"; "the menus don't look the same"):
the tabs, the Hotkey Editor inside, settings that really change behaviour (camera style, component pivot, step snaps,
create mode), they persist; every menu family shares the theme; marking-menu chips never overlap or hide under the
list. Under a minute.

    python tests/test_forge_settings_ui.py
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
        wait = page.wait_for_timeout
        await E("forgeProRun(forge.view, 'cube')"); await wait(200)
        await E("forgeProRun(forge.view, 'preferences')"); await wait(200)
        tabs = await E("[...document.querySelectorAll('#forge-settings .fset-tab')].map((b) => b.dataset.tab)")
        check("Settings has Interface, Navigation, Manipulators, Selection, Create, Hotkeys and Menus",
              tabs == ["interface", "navigation", "manipulators", "selection", "create", "hotkeys", "menus"], tabs)
        await page.click('.fset-tab[data-tab="hotkeys"]'); await wait(150)
        check("the Hotkeys tab holds the Hotkey Editor (sets, search, a key box per command)",
              await E("!!document.querySelector('#forge-settings .fset-pane #forge-hotkeys .forge-hk-list') && document.querySelectorAll('#forge-settings .forge-hk-list button').length > 50"))
        check("Windows > Hotkey Editor opens that tab", await E("(FORGE_PRO_CMDS.hotkeyEditor[1](forge.view), document.getElementById('forge-settings').dataset.tab)") == "hotkeys")
        await page.click('.fset-tab[data-tab="menus"]'); await wait(150)
        check("the Menus tab holds Menu Settings, and the Hotkey Editor went back out (not destroyed)",
              await E("!!document.querySelector('#forge-settings .fset-pane #fmenu-settings') && !!document.getElementById('forge-hotkeys')"))
        await page.click('.fset-tab[data-tab="interface"]'); await wait(100)
        check("Interface lists the UI elements as switches", await E("document.querySelectorAll('#forge-settings .fset-pane .fset-check').length") >= 6)
        # navigation: the middle-mouse style makes the middle button alone a camera gesture
        await E("ForgeSettings.set('navStyle', 'mmb')")
        mm = await E("[forgeCamMod({ button: 1, type: 'pointerdown' }), forgeCamMod({ button: 0, altKey: true, type: 'pointerdown' })]")
        await E("ForgeSettings.set('navStyle', 'maya')")
        ma = await E("[forgeCamMod({ button: 1, type: 'pointerdown' }), forgeCamMod({ button: 0, altKey: true, type: 'pointerdown' })]")
        check("Navigation style: middle mouse alone in 'mmb', Alt + a button in 'maya'", mm == [True, False] and ma == [False, True], [mm, ma])
        # manipulators: where the component handle sits
        await E("forgeProRun(forge.view, 'vertex')"); await wait(100)
        pts = await E("""(() => { const v = forge.view, P = window.ForgePoly; const c = v.poly.v.map((p, i) => i);
          const pick = [c.find((i) => v.poly.v[i][0] < 0 && v.poly.v[i][1] < 0 && v.poly.v[i][2] < 0), ...c.filter((i) => v.poly.v[i][0] > 0)];
          ForgeSettings.set('pivotPlacement', 'bbox'); const b = v.pivotPoint(pick);
          ForgeSettings.set('pivotPlacement', 'median'); const m = v.pivotPoint(pick);
          ForgeSettings.set('pivotPlacement', 'bbox'); return [b, m]; })()""")
        check("Component pivot: bounding box centre (Maya) or the average point - they differ on an uneven pick",
              abs(pts[0][0] - 0) < 1e-9 and abs(pts[1][0] - 0.3) < 1e-9, pts)
        await E("ForgeSettings.set('snapRotate', 45)")
        rs = await E("(() => { forgeProSnap(forge.view, 'step', true); const g = forge.view.gizmo || forge.view.transform; const r = g.rotationSnap; forgeProSnap(forge.view, 'step', false); return r; })()")
        await E("ForgeSettings.set('snapRotate', 15)")
        check("Step snap rotate comes from Settings (45 degrees)", abs((rs or 0) - 0.7853981) < 1e-4, rs)
        # create
        await E("forgeProRun(forge.view, 'objectMode')"); await wait(80)
        await E("ForgeSettings.set('createMode', 'component')")
        await E("forgeProRun(forge.view, 'sphere')"); await wait(200)
        cm = await E("forge.view.mode")
        await E("ForgeSettings.set('createMode', 'object')")
        await E("forgeProRun(forge.view, 'cone')"); await wait(200)
        om = await E("forge.view.mode")
        check("Create > Open in: component mode or object mode", cm == "poly" and om == "view", [cm, om])
        # persistence + Reset
        await page.reload()
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await E("document.getElementById('open-forge').click()")
        await page.wait_for_function("forge.view && forge.view.pro", timeout=15000)
        await E("ForgeSettings.set('handleSize', 1.7)")
        await page.reload()
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        check("settings are remembered across a restart", await E("ForgeSettings.get('handleSize')") == 1.7)
        await E("ForgeSettings.reset()")
        check("Reset all puts them back", await E("ForgeSettings.get('handleSize')") == 1)
        await E("document.getElementById('open-forge').click()")
        await page.wait_for_function("forge.view && forge.view.pro && forge.view.brush", timeout=15000)
        await E("forgeProRun(forge.view, 'cube')"); await wait(200)
        # one menu look
        await page.click('#fmy-menubar .fmy-mb[data-menu="Mesh"]'); await wait(120)
        look = await E("(() => { const s = getComputedStyle(document.querySelector('.fmy-drop')); return [s.borderRadius, s.backgroundColor]; })()")
        await page.keyboard.press("Escape"); await page.mouse.click(5, 500); await wait(80)
        await E("forgeProMarkShow(forge.view, 700, 300, forgeProMenu(forge.view, { node: forge.view.tree.api.node(forge.view.tree.api.selected()[0]) }))"); await wait(120)
        lay = await E("""(() => { const h = document.getElementById('forge-pro-marking'); const ws = [...h.querySelectorAll('.forge-pro-wedge')].map((w) => w.getBoundingClientRect());
          const ml = h.querySelector('.forge-pro-mlist'); const lr = ml ? ml.getBoundingClientRect() : null;
          const hit = (a, b) => a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1;
          let overlap = 0, under = 0; for (let i = 0; i < ws.length; i++) { for (let j = i + 1; j < ws.length; j++) if (hit(ws[i], ws[j])) overlap++; if (lr && hit(ws[i], lr)) under++; }
          const s = getComputedStyle(ml); return { n: ws.length, overlap, under, radius: s.borderRadius, bg: s.backgroundColor, pill: getComputedStyle(h.querySelector('.forge-pro-wedge')).borderRadius }; })()""")
        await E("forgeProMarkHide()")
        check("the menu bar and the marking menu's list share one surface (radius, colour)", look[0] == lay["radius"] and look[1] == lay["bg"], [look, lay])
        check("the marking menu's chips are pills and none overlaps another", lay["n"] >= 6 and lay["overlap"] == 0 and lay["pill"].startswith("999"), lay)
        check("...and the list never covers a chip", lay["under"] == 0, lay)
        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
