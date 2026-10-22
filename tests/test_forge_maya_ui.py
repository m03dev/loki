"""Forge's Maya-style behaviours. First the camera modifier: Option / Alt has always navigated, and the owner asked
for Command too ("maya is hold down command and drag to move in the viewport") - so both turn/track/dolly the view, and
a drag with either never moves the object. Headless Chromium, under a minute.

    python tests/test_forge_maya_ui.py
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

CAM = """() => { const c = forge.view.camera, t = forge.view.controls ? forge.view.controls.target : null;
  return { q: c.quaternion.toArray(), p: c.position.toArray(),
           d: t ? c.position.distanceTo(t) : 0 }; }"""
OBJ = """() => { const t = forge.view.tree.api, n = t.active(); return n ? t.transform(n.id).translate : null; }"""


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
            bare = r.request.url.split("8896", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8896/**", route)
        await page.goto("http://127.0.0.1:8896/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.click("#open-forge")
        await page.wait_for_function("forge.view && forge.view.pro && forge.view.canvas", timeout=10000)
        await page.evaluate("forgeAddPrimitive('cube')")
        await page.wait_for_timeout(300)
        E = page.evaluate
        rect = await E("() => { const r = forge.view.canvas.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
        cx, cy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2

        check("the camera modifier accepts Command as well as Option/Alt", await E("forgeCamMod({altKey:true}) && forgeCamMod({metaKey:true}) && !forgeCamMod({})"))

        async def drag(mod, button, dx, dy):
            if mod:
                await page.keyboard.down(mod)
            await page.mouse.move(cx, cy)
            await page.mouse.down(button=button)
            await page.mouse.move(cx + dx, cy + dy, steps=6)
            await page.mouse.up(button=button)
            if mod:
                await page.keyboard.up(mod)
            await page.wait_for_timeout(120)

        base = await E(CAM)
        await drag("Meta", "left", 90, 40)
        cmd = await E(CAM)
        moved = sum(abs(a - b) for a, b in zip(base["q"], cmd["q"]))
        check("Command + drag turns the camera (tumble)", moved > 0.05, [moved, base["q"][:2], cmd["q"][:2]])

        await drag("Alt", "left", -80, -30)
        alt = await E(CAM)
        moved2 = sum(abs(a - b) for a, b in zip(cmd["q"], alt["q"]))
        check("Option / Alt + drag still turns it, exactly as before", moved2 > 0.05, [moved2])

        before = await E(CAM)
        await drag("Meta", "right", 60, 30)
        after = await E(CAM)
        check("Command + right-drag dollies in or out", abs(after["d"] - before["d"]) > 0.02, [before["d"], after["d"]])

        # box zoom stays where it belongs: the camera modifier + Ctrl (Maya's Ctrl + Option + left)
        b4 = await E(CAM)
        await page.keyboard.down("Alt")
        await page.keyboard.down("Control")
        await page.mouse.move(cx, cy)
        await page.mouse.down(button="left")
        await page.mouse.move(cx + 60, cy + 45, steps=4)
        await page.mouse.up(button="left")
        await page.keyboard.up("Control")
        await page.keyboard.up("Alt")
        await page.wait_for_timeout(140)
        af = await E(CAM)
        check("box zoom is still the camera modifier + Ctrl", abs(af["d"] - b4["d"]) > 0.01, [b4["d"], af["d"]])

        # a Command drag is the camera, not the object: the selection must not budge
        await E("forge.view.tree.api.select(1)")
        t0 = await E(OBJ)
        await drag("Meta", "left", 70, 30)
        t1 = await E(OBJ)
        unchanged = t0 and t1 and all(abs(a - b) < 1e-9 for a, b in zip(t0, t1))
        check("a Command drag while something is selected moves the view, never the object", unchanged, [t0, t1])

        # ---- the menus: one catalogue, no dead entries, and the hotbox laid out the reference way
        cat = await E("""() => { const dead = [], empty = [];
          for (const [name, ids] of Object.entries(FORGE_PRO_MENUS)) {
            if (!ids.length) empty.push(name);
            for (const id of ids) if (!FORGE_PRO_CMDS[id]) dead.push(name + " > " + id);
          }
          return { dead, empty, count: Object.keys(FORGE_PRO_MENUS).length }; }""")
        check("every menu in the catalogue has items, and every item is a real command",
              not cat["dead"] and not cat["empty"], cat)

        await page.keyboard.down("Space")
        await page.wait_for_timeout(350)
        rows = await E("""() => { const h = document.getElementById('forge-pro-hotbox'); if (!h || h.hidden) return null;
          return [...h.querySelectorAll('.forge-pro-row')].map((r) => ({
            side: r.classList.contains('up') ? 'up' : 'down',
            mid: !!r.dataset.mid, top: Math.round(r.getBoundingClientRect().top),
            set: r.dataset.set || '', hidden: !!r.hidden,
            menus: [...r.querySelectorAll('.forge-pro-col')].map((c) => c.dataset.menu) })); }""")
        await page.keyboard.up("Space")
        await page.wait_for_timeout(150)
        check("Space opens the hotbox with rows", bool(rows) and len(rows) >= 4, rows)
        if rows:
            up = [r for r in rows if r["side"] == "up"]          # in DOM order: panel menus, main menus, middle
            down = [r for r in rows if r["side"] == "down" and not r["hidden"]]
            check("the rows ladder down: panel menus, the main menus, then the middle row (which is the one nearest the centre)",
                  len(up) == 3
                  and up[0]["menus"] == ["View", "Shading", "Lighting", "Show", "Renderer", "Panels"]
                  and up[1]["menus"] == ["File", "Edit", "Create", "Select", "Modify", "Display", "Windows", "Help"]
                  and up[2]["menus"] == ["Recent Commands", "Menu Set", "Hotbox Controls"] and up[2]["mid"]
                  and up[0]["top"] < up[1]["top"] < up[2]["top"], up)
            check("the menu-set button names the set that is showing",
                  await E("document.querySelector('.forge-pro-sethead').textContent") in ("Forge", "Modeling", "Sculpting", "Animation", "Rendering"))
            check("the rows under the middle are the showing set's menus",
                  [r["menus"] for r in down] == [["Mesh", "Edit Mesh", "Mesh Tools"], ["Snap", "Symmetry", "Sculpt"], ["Animation"]], down)
            check("only one set's rows are up at a time", len(down) == 3 and all(not r["hidden"] for r in down))

        # the ladder is tidy: no two rows overlap, and the lot fits the viewport
        geom = await E("""() => { const h = document.getElementById('forge-pro-hotbox');
          const rs = [...h.querySelectorAll('.forge-pro-row')].filter((r) => !r.hidden)
            .map((r) => r.getBoundingClientRect()).sort((a, b) => a.top - b.top);
          let overlap = 0;
          for (let i = 1; i < rs.length; i++) if (rs[i].top < rs[i - 1].bottom - 0.5) overlap++;
          const box = h.querySelector('.forge-pro-hbbox').getBoundingClientRect();
          return { n: rs.length, overlap, inside: (rs[0].top >= 0 && rs[rs.length - 1].bottom <= innerHeight) }; }""")
        check("the hotbox's rows stack without overlapping and stay on screen",
              geom["n"] >= 6 and geom["overlap"] == 0 and geom["inside"], geom)

        # switching the menu set
        await E("window.forgeMenuSet('modeling')")
        await page.wait_for_timeout(120)
        down2 = await E("""() => [...document.querySelectorAll('#forge-pro-hotbox .forge-pro-row[data-set]')]
          .filter((r) => !r.hidden).map((r) => [...r.querySelectorAll('.forge-pro-col')].map((c) => c.dataset.menu))""")
        head2 = await E("document.querySelector('.forge-pro-sethead').textContent")
        check("switching the menu set shows that set's menus only",
              head2 == "Modeling" and down2 == [["Mesh", "Edit Mesh", "Mesh Tools"], ["Snap", "Symmetry"]], [head2, down2])
        check("the panel and main menus stay where they are when the set changes",
              await E("document.querySelectorAll('#forge-pro-hotbox .forge-pro-row.up').length") == 3)
        await E("window.forgeMenuSet('forge')")

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
