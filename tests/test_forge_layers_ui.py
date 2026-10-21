"""Forge's Display Layers (the pro Layer Editor under the Channel Box) in headless Chromium: a layer is created,
the selection is assigned to it, V hides the whole layer, T templates it (shown but not selectable), it can be
renamed, deleted (the objects stay) and every step undoes. Skips without Playwright + Chromium. Under a minute.

    python tests/test_forge_layers_ui.py
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

T = "forge.view.tree.api"
LAYER = "forge.view.tree"


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
            bare = r.request.url.split("8894", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8894/**", route)
        await page.goto("http://127.0.0.1:8894/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("localStorage.removeItem('loki-forge-hotkeys')")
        await page.click("#open-forge")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        await page.evaluate("forgeAddPrimitive('cube')")
        await page.wait_for_function("forge.view && forge.view.sm && forge.view.tree", timeout=10000)
        await page.evaluate("forgeModelMode(false)")
        E = page.evaluate

        # the Layer Editor is there, under the Channel Box, with the Default layer
        dom = await E("""() => ({ ed: !!document.getElementById('forge-layer-editor'),
          inCol: !!document.querySelector('#forge-chancol #forge-layer-editor'),
          rows: [...document.querySelectorAll('#forge-layer-list .forge-layer-row')].map((r) => r.querySelector('.forge-layer-name').textContent),
          add: !!document.getElementById('forge-layer-add') })""")
        check("Display Layers sits under the Channel Box with a Default layer and a + button",
              dom["ed"] and dom["inCol"] and dom["add"] and dom["rows"] == ["Default"], dom)

        # create a layer, make a second object, assign the selection to the layer
        await E("forgeAddPrimitive('cube')")
        await page.wait_for_timeout(120)
        meshes = await E(T + ".list().filter((n) => n.kind === 'mesh').map((n) => n.id)")
        await E(T + ".select(%d)" % meshes[0])
        await page.click("#forge-layer-add")
        await page.click("#forge-layer-assign")
        L1 = await E(T + ".layerList()")
        check("New layer + Assign puts the selected object on it", len(L1) == 1 and L1[0]["count"] == 1 and L1[0]["current"], L1)

        # V hides the whole layer
        await page.click("#forge-layer-list .forge-layer-row:not(.default) [data-role='vis']")
        vis1 = await E("""(() => { const a = %s.layerList()[0]; const l = %s.layers.find((x) => x.id === a.id);
          const nid = [...l.nodes][0]; return [forge.view.tree.byId[nid].grp.visible, %s.layerNorm(forge.view.tree.byId[nid])]; })()""" % (T, LAYER, T))
        await page.click("#forge-layer-list .forge-layer-row:not(.default) [data-role='vis']")
        vis2 = await E("""(() => { const a = %s.layerList()[0]; const l = %s.layers.find((x) => x.id === a.id);
          const nid = [...l.nodes][0]; return forge.view.tree.byId[nid].grp.visible; })()""" % (T, LAYER))
        check("V on a layer hides every object on it, and shows them again", vis1 == [False, False] and vis2 is True, [vis1, vis2])

        # T templates the layer: still drawn, but not selectable
        await page.click("#forge-layer-list .forge-layer-row:not(.default) [data-role='tpl']")
        nid = await E("[...(%s.layers.find((l) => l.id === %s.layerList()[0].id)).nodes][0]" % (LAYER, T))
        await E(T + ".select(null)")
        await E(T + ".select(%d)" % nid)
        tp = await E("[%s.layersTemplate(%d), forge.view.tree.byId[%d].grp.visible, %s.sel.indexOf(%d)]" % (T, nid, nid, LAYER, nid))
        check("T templates the layer (object shown, but select() refuses it - the pro rule)", tp == [True, True, -1], tp)
        await page.click("#forge-layer-list .forge-layer-row:not(.default) [data-role='tpl']")

        # rename through the API (the row text follows)
        await E(T + ".layerRename(%s.layerList()[0].id, 'Body')" % T)
        name = await E("document.querySelector('#forge-layer-list .forge-layer-row:not(.default) .forge-layer-name').textContent")
        check("a layer renames (double-click in the UI; the row follows)", name == "Body", name)

        # delete the layer: its objects stay in the scene
        await page.click("#forge-layer-list .forge-layer-row:not(.default) .forge-ch-x")
        after = await E("[%s.layerList().length, %s.list().filter((n) => n.kind === 'mesh').length]" % (T, T))
        check("deleting a layer leaves its objects in the scene", after == [0, len(meshes)], after)

        # undo brings the layer back (layer ops are one undo step)
        await E("forgeProRun(forge.view, 'undo')")
        back = await E(T + ".layerList().length")
        check("undo brings the deleted layer back", back == 1, back)

        # the commands and the Display menu expose it
        cmds = await E("(typeof FORGE_PRO_CMDS !== 'undefined') && !!(FORGE_PRO_CMDS.layerEditor && FORGE_PRO_CMDS.layerAdd && FORGE_PRO_CMDS.layerAssign)")
        check("Layer Editor / Create Empty Layer / Assign are commands (menu, hotbox, command line)", cmds, cmds)

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
