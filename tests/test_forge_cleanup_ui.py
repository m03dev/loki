"""Forge's 2026-10-21 clean-up (owner: "when forge starts there should be nothing in the scene ... just the hidden cams
in the outliner", "h to hide doesn't work and v visibility doesnt work add r for ref cant click through", "add free
image plane so we can import png or jpeg", "make all the ui panels adjustable ... everything is %", "get rid of the
scroll bar on the right side", "get rid of spaces"), in headless Chromium with real mouse and key presses.
Skips without Playwright + Chromium. Under a minute.

    python tests/test_forge_cleanup_ui.py
"""
from __future__ import annotations

import asyncio
import base64
import os
import struct
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def png(w, h, rgb):
    """A tiny solid PNG, no Pillow needed."""
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright here\n\n0 passed, 0 failed")
    sys.exit(0)

T = "forge.view.tree.api"


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
        E = page.evaluate
        await E("localStorage.removeItem('loki-forge-hotkeys'); localStorage.removeItem('loki-forge-split')")

        tabs = await E("[...document.querySelectorAll('.modebar-tab')].map((b) => b.dataset.mode)")
        check("Spaces is out of the title bar",
              "spaces" not in tabs and "forge" in tabs and not await E("!!window.LokiSpaces"), tabs)

        await page.evaluate("document.getElementById('open-forge').click()")
        await page.wait_for_function("window.forge && forge.view && forge.view.tree", timeout=15000)
        await page.wait_for_timeout(300)

        # ---- a new scene is empty: only the four cameras in the Outliner, an empty Channel Box
        start = await E("""({ rows: [...document.querySelectorAll('#forge-out-list > *')].map((r) => r.textContent.trim()),
          nodes: %s.sceneNodes().length, sel: forge.view.tree.sel.length,
          chan: document.getElementById('forge-channel').classList.contains('forge-ch-none'),
          tx: getComputedStyle(document.querySelector('#forge-channel > .forge-ch-row')).display })""" % T)
        check("a new scene: the Outliner lists only persp / top / front / side, nothing selected, Channel Box empty",
              start["rows"] == ["persp", "top", "front", "side"] and start["nodes"] == 0 and start["sel"] == 0
              and start["chan"] and start["tx"] == "none", start)
        cam = await E("(() => { const p = forge.view.camera.position; return [p.x, p.y, p.z]; })()")
        check("the default persp camera looks down at the grid from the front-right (a 3/4 view, not edge-on)",
              cam[0] > 1 and cam[1] > 1 and cam[2] > 1, cam)

        # ---- Create: the cube is the first and only scene object
        await E("forgeAddPrimitive('cube')")
        await page.wait_for_timeout(200)
        await E("forgeModelMode(false)")
        made = await E("[%s.sceneNodes().map((n) => n.name), forge.view.tree.sel.length]" % T)
        check("Create > Cube makes pCube1, selected (no leftover empty object)", made == [["pCube1"], 1], made)

        # ---- hide / show with real key presses over the viewport
        vp = await E("(() => { const b = document.querySelector('#forge canvas').getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()")
        await page.mouse.move(vp[0], vp[1])
        vis = lambda: E("%s.sceneNodes()[0].visible" % T)  # noqa: E731
        await page.keyboard.press("h"); a = await vis()
        await page.keyboard.press("h"); b = await vis()
        await page.keyboard.press("Control+h"); c = await vis()
        await page.keyboard.press("Shift+h"); d = await vis()
        check("h toggles, Ctrl+H hides, Shift+H shows (real keys over the viewport)", [a, b, c, d] == [False, True, False, True], [a, b, c, d])
        # typing in the Channel Box, then Enter: the keys belong to the viewport again
        await page.click("#forge-ch-tx")
        await page.keyboard.type("0")
        await page.keyboard.press("Enter")
        await page.keyboard.press("h")
        e1 = await vis()
        await page.keyboard.press("h")
        check("after typing a channel value + Enter, h works again (the field gives the keys back)", e1 is False, e1)

        # ---- Display Layers: V hides, R = shown but clicks go through, T = template
        await E("forgeAddPrimitive('cube')")
        await page.wait_for_timeout(150)
        await E("forgeModelMode(false)")
        ids = await E("%s.sceneNodes().map((n) => n.id)" % T)
        await E("%s.select(%d)" % (T, ids[0]))
        await page.click("#forge-layer-add")
        await page.click("#forge-layer-assign")
        roles = await E("[...document.querySelectorAll('#forge-layer-list .forge-layer-row:not(.default) .forge-layer-tog')].map((b) => b.textContent)")
        check("every layer row has V, T and R", roles == ["V", "T", "R"], roles)
        await page.click("#forge-layer-list .forge-layer-row:not(.default) [data-role='vis']")
        hid = await E("[forge.view.tree.byId[%d].grp.visible, %s.pickables().length]" % (ids[0], T))
        await page.click("#forge-layer-list .forge-layer-row:not(.default) [data-role='vis']")
        check("V off hides the layer and nothing on it can be picked", hid == [False, 1], hid)
        await page.click("#forge-layer-list .forge-layer-row:not(.default) [data-role='ref']")
        ref = await E("""(() => { const n = forge.view.tree.byId[%d]; return [%s.layersRef(%d), n.grp.visible,
          %s.pickables({ select: true }).length, %s.pickables().length]; })()""" % (ids[0], T, ids[0], T, T))
        check("R: the layer is drawn but a click goes through it (snapping still sees it)", ref == [True, True, 1, 2], ref)
        await E("%s.select(null)" % T)
        await E("forgeProRun(forge.view, 'frameAll')")
        await page.wait_for_timeout(150)
        hits = await E("""(() => { const r = forge.view.canvas.getBoundingClientRect(), out = new Set();
          for (let x = r.left + 4; x < r.right; x += 12) for (let y = r.top + 4; y < r.bottom; y += 12) { const n = forgeProPickAt(forge.view, x, y); if (n) out.add(n.id); }
          return [...out]; })()""")
        check("clicking over the whole viewport never picks the referenced object", ids[0] not in hits and ids[1] in hits, [hits, ids])
        await E("%s.select(%d)" % (T, ids[0]))
        osel = await E("forge.view.tree.sel")
        check("a referenced object can still be picked from the Outliner (as in the pro tool)", osel == [ids[0]], osel)
        await page.click("#forge-layer-list .forge-layer-row:not(.default) [data-role='tpl']")
        tpl = await E("[%s.layersTemplate(%d), %s.layersRef(%d), forge.view.tree.sel.includes(%d)]" % (T, ids[0], T, ids[0], ids[0]))
        check("T replaces R (one choice) and drops the object from the selection", tpl == [True, False, False], tpl)
        await page.click("#forge-layer-list .forge-layer-row:not(.default) [data-role='tpl']")
        await E("forgeProRun(forge.view, 'undo')")
        und = await E("[%s.layersTemplate(%d), %s.layersRef(%d)]" % (T, ids[0], T, ids[0]))
        check("layer R / T changes undo", und == [True, False], und)

        # ---- Free Image Plane from a PNG
        url = "data:image/png;base64," + base64.b64encode(png(40, 20, (200, 80, 40))).decode()
        ip = await E("forgeImagePlaneAdd(%r, 'ref').then((n) => n && [n.name, n.kind, forge.view.tree.sel[0] === n.id])" % url)
        dims = await E("""(() => { const n = %s.sceneNodes().find((x) => x.kind === 'imagePlane'); const s = n.inner.children.find((o) => o.isMesh);
          s.geometry.computeBoundingBox(); const b = s.geometry.boundingBox; return [Math.round((b.max.x - b.min.x) / (b.max.y - b.min.y) * 100) / 100, !!s.material.map]; })()""" % T)
        check("Create > Free Image Plane: imagePlane1, selected, textured, keeping the picture's 2:1 shape",
              ip == ["imagePlane1", "imagePlane", True] and dims == [2, True], [ip, dims])
        row = await E("!document.getElementById('forge-ch-alpha').closest('.forge-ch-row').hidden")
        await E("%s.setAlphaGain(forge.view.tree.sel[0], 0.4)" % T)
        ag = await E("%s.alphaGain(forge.view.tree.sel[0])" % T)
        check("the image plane has Alpha Gain in the Channel Box", row and abs(ag - 0.4) < 1e-6, [row, ag])
        menu = await E("!!(FORGE_PRO_CMDS.imagePlane) && forgeMenuFlat(FMY_MENUS().find((m) => m[0] === 'Create')[1]).includes('imagePlane')")
        check("Free Image Plane is a command and in the Create menu", menu, menu)
        await E("forgeProRun(forge.view, 'undo')")
        gone = await E("%s.sceneNodes().filter((n) => n.kind === 'imagePlane').length" % T)
        check("undo takes the image plane away", gone == 0, gone)

        # ---- panels resize by dragging their edge; sizes are % of Forge's width
        h = await E("(() => { const b = document.querySelector('.forge-split[data-panel=forge-outcol]').getBoundingClientRect(); return [b.x + b.width / 2, b.y + 200]; })()")
        w0 = await E("document.getElementById('forge-outcol').getBoundingClientRect().width")
        await page.mouse.move(h[0], h[1])
        cur = await E("getComputedStyle(document.querySelector('.forge-split[data-panel=forge-outcol]')).cursor")
        await page.mouse.down(); await page.mouse.move(h[0] + 120, h[1], steps=4); await page.mouse.up()
        w1 = await E("document.getElementById('forge-outcol').getBoundingClientRect().width")
        saved = await E("JSON.parse(localStorage.getItem('loki-forge-split') || '{}')")
        check("hover the Outliner's edge: a resize cursor; drag: it is wider, saved as a % of the width",
              cur == "col-resize" and w1 > w0 + 80 and 10 < saved.get("forge-outcol", 0) < 46, [cur, w0, w1, saved])
        await page.set_viewport_size({"width": 1000, "height": 800})
        await page.wait_for_timeout(150)
        ratio = await E("document.getElementById('forge-outcol').getBoundingClientRect().width / document.querySelector('#forge .forge-body').getBoundingClientRect().width * 100")
        check("the % holds when the window changes size", abs(ratio - saved["forge-outcol"]) < 1.5, [ratio, saved])
        await page.dblclick(".forge-split[data-panel=forge-outcol]")
        back = await E("JSON.parse(localStorage.getItem('loki-forge-split') || '{}')['forge-outcol'] === undefined")
        check("double-click an edge: the panel goes back to its default size", back, back)
        sp = await E("""(() => { const h = document.getElementById('forge-split-layers'); return !!h && !h.hidden
          && !!document.querySelector('.forge-split[data-panel=forge-chancol]:not([hidden])'); })()""")
        check("the Channel Box has a resize edge, and a second one above the Display Layers", sp, sp)

        # ---- no scroll bars
        sb = await E("[getComputedStyle(document.getElementById('forge-chancol')).scrollbarWidth, getComputedStyle(document.getElementById('forge-out-list')).scrollbarWidth]")
        # owner 2026-10-21: "it should only show up in places that need scrolling" - thin and invisible until hovered
        col = await E("getComputedStyle(document.getElementById('forge-out-list')).scrollbarColor")
        check("scroll bars in Forge are thin and only show on hover where something scrolls", sb == ["thin", "thin"] and ("transparent" in col or "rgba(0, 0, 0, 0)" in col), [sb, col])

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
