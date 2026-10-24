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
        await page.evaluate("document.getElementById('open-forge').click()")
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
            const cmds = forgeMenuFlat(ids);
            if (!cmds.length) empty.push(name);
            for (const id of cmds) if (!FORGE_PRO_CMDS[id]) dead.push(name + " > " + id);
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
                  await E("document.querySelector('.forge-pro-sethead').textContent") in ("Modeling", "Sculpting", "Animation", "Rendering"))
            check("the rows under the middle are the showing set's menus - Maya's Modeling set, in Maya's order",
                  [r["menus"] for r in down] == [["Mesh", "Edit Mesh", "Mesh Tools", "Mesh Display"], ["UV"]], down)
            check("only one set's rows are up at a time", len(down) == 2 and all(not r["hidden"] for r in down))

        # the ladder is tidy: no two rows overlap, and the lot fits the viewport
        geom = await E("""() => { const h = document.getElementById('forge-pro-hotbox');
          const rs = [...h.querySelectorAll('.forge-pro-row')].filter((r) => !r.hidden)
            .map((r) => r.getBoundingClientRect()).sort((a, b) => a.top - b.top);
          let overlap = 0;
          for (let i = 1; i < rs.length; i++) if (rs[i].top < rs[i - 1].bottom - 0.5) overlap++;
          const box = h.querySelector('.forge-pro-hbbox').getBoundingClientRect();
          return { n: rs.length, overlap, inside: (rs[0].top >= 0 && rs[rs.length - 1].bottom <= innerHeight) }; }""")
        check("the hotbox's rows stack without overlapping and stay on screen",
              geom["n"] >= 5 and geom["overlap"] == 0 and geom["inside"], geom)

        # switching the menu set
        await E("window.forgeMenuSet('modeling')")
        await page.wait_for_timeout(120)
        down2 = await E("""() => [...document.querySelectorAll('#forge-pro-hotbox .forge-pro-row[data-set]')]
          .filter((r) => !r.hidden).map((r) => [...r.querySelectorAll('.forge-pro-col')].map((c) => c.dataset.menu))""")
        head2 = await E("document.querySelector('.forge-pro-sethead').textContent")
        check("switching the menu set shows that set's menus only",
              head2 == "Modeling" and down2 == [["Mesh", "Edit Mesh", "Mesh Tools", "Mesh Display"], ["UV"]], [head2, down2])
        check("the panel and main menus stay where they are when the set changes",
              await E("document.querySelectorAll('#forge-pro-hotbox .forge-pro-row.up').length") == 3)
        await E("window.forgeMenuSet('modeling')")

        # ---- the WINDOW's menu bar is built from the same catalogue, so the two can never drift apart
        bar = await E("""() => { const cat = FORGE_PRO_MENUS, out = [];
          for (const [name, items] of FMY_MENUS()) {
            // plain-string ids must be real commands; an ["id", "Label", fn] row (in a submenu too) carries its own handler
            const own = new Set(); const walk = (l) => { for (const x of l) if (Array.isArray(x)) { if (Array.isArray(x[1])) walk(x[1]); else own.add(x[0]); } };
            walk(items);
            const ids = forgeMenuFlat(items).filter((x) => !own.has(x));
            const all = forgeMenuFlat(items);
            // only plain-string ids must be real commands; an ["id", "Label", fn] row carries its own handler
            out.push({ name: name, ids: all, want: forgeMenuFlat(cat[name] || []),
                       dupes: all.filter((x, i) => all.indexOf(x) !== i),
                       dead: ids.filter((x) => !FORGE_PRO_CMDS[x]) });
          }
          return out; }""")
        names = [m["name"] for m in bar]
        check("the window menu bar is Maya 2027's Modeling bar: File .. Windows, Mesh, Edit Mesh, Mesh Tools, Mesh Display, UV, Help",
              names == ["File", "Edit", "Create", "Select", "Modify", "Display", "Windows", "Mesh", "Edit Mesh", "Mesh Tools", "Mesh Display", "UV", "Help"], names)
        shared = [m for m in bar if m["want"]]
        check("every command the catalogue lists is in the matching window menu, in the same order (no drift)",
              shared and all(m["ids"][:len(m["want"])] == m["want"] for m in shared),
              [(m["name"], m["want"], m["ids"][:len(m["want"])]) for m in shared if m["ids"][:len(m["want"])] != m["want"]][:2])
        check("no window menu lists a command twice", all(not m["dupes"] for m in bar), [m["dupes"] for m in bar if m["dupes"]][:2])
        check("every item in every window menu is a real command", all(not m["dead"] for m in bar), [m["dead"] for m in bar if m["dead"]][:2])

        # ---- the status line's menu set drives the window's menu bar (one list behind both)
        opts = await E("[...document.getElementById('fmy-menuset').options].map((o) => o.value)")
        check("the status line offers the menu sets (Maya's Modeling / Animation / Rendering, and Sculpting + Level)", opts == ["modeling", "sculpting", "animation", "rendering", "level"], opts)
        await E("() => { const s = document.getElementById('fmy-menuset'); s.value = 'animation'; s.dispatchEvent(new Event('change')); }")
        await page.wait_for_timeout(250)
        anim = await E("[...document.querySelectorAll('#fmy-menubar .fmy-mb')].map((b) => b.textContent)")
        check("choosing Animation puts Maya's Key and Playback menus in the bar (and takes Modeling's away)",
              "Key" in anim and "Playback" in anim and "Edit Mesh" not in anim and "File" in anim and "Help" in anim, anim)
        await E("() => { const s = document.getElementById('fmy-menuset'); s.value = 'modeling'; s.dispatchEvent(new Event('change')); }")
        await page.wait_for_timeout(250)
        mod = await E("[...document.querySelectorAll('#fmy-menubar .fmy-mb')].map((b) => b.textContent)")
        check("...and choosing Modeling brings them back", "Edit Mesh" in mod and "UV" in mod and "Animation" not in mod, mod)
        await E("() => { const s = document.getElementById('fmy-menuset'); s.value = 'modeling'; s.dispatchEvent(new Event('change')); }")
        await page.wait_for_timeout(200)

        # ---- the heads-up poly count reads like a modeler's: two columns (the scene, the selection)
        await page.keyboard.press("F8")                       # object mode, through the app's own key path
        await page.wait_for_function("forge.view.mode !== 'poly'", timeout=8000)
        await page.wait_for_function("!document.getElementById('fmy-polycount').classList.contains('fmy-comp')", timeout=4000)
        hud = await E("""() => { const t = document.getElementById('fmy-polycount');
          const cells = [...t.rows[0].cells];
          return { n: cells.length, shown: cells.filter((c) => c.offsetParent !== null).length, comp: t.classList.contains('fmy-comp') }; }""")
        check("the poly count reads like a modeler's HUD - two columns now, the component one only when it counts",
              hud["n"] == 4 and hud["shown"] == 3 and not hud["comp"], hud)
        await page.keyboard.press("F9")                       # vertex mode: now the components are what counts
        await page.wait_for_function("forge.view.mode === 'poly' && forge.view.edit && forge.view.edit.mode === 'vert'", timeout=8000)
        await page.wait_for_function("document.getElementById('fmy-polycount').classList.contains('fmy-comp')", timeout=4000)
        hud2 = await E("""() => { const t = document.getElementById('fmy-polycount');
          const cells = [...t.rows[0].cells];
          return { shown: cells.filter((c) => c.offsetParent !== null).length, comp: t.classList.contains('fmy-comp'),
                   all: +t.rows[0].cells[1].textContent }; }""")
        check("...and the component column comes back in component mode",
              hud2["shown"] == 4 and hud2["comp"] and hud2["all"] >= 8, hud2)
        # ---- the marking menus: the reference's per-context sets, switches that show a tick, and a nested list.
        # Opened through the app's own forgeProMenu/forgeProMarkShow (the input path is covered by test_forge_pro_ui),
        # so these are about what the menus contain.
        await E("forgeModelMode(false)")
        await page.wait_for_function("forge.view.mode !== 'poly'", timeout=8000)
        menu = await E("""() => { const v = forge.view, api = v.tree.api; api.select(1);
          const read = () => { const h = document.getElementById('forge-pro-marking');
            const rows = [...h.querySelectorAll('.forge-pro-litem')];
            const ring = {};
            for (const b of h.querySelectorAll('.forge-pro-wedge')) ring[b.dataset.pos] = b.dataset.proId || ('>' + b.dataset.proSub);
            return { hub: h.querySelector('.forge-pro-hub').textContent, ring,
                     labels: Object.fromEntries([...h.querySelectorAll('.forge-pro-wedge')].map((b) => [b.dataset.pos, b.textContent])),
                     rows: rows.map((b) => b.dataset.proId || null) }; };
          const out = {};
          forgeProMarkShow(v, 420, 300, forgeProMenu(v, { shift: true, node: api.node(1), key: '', ctrl: false }));
          out.tools = read();
          const sub = document.querySelector('#forge-pro-marking .forge-pro-wsub[data-pos="SE"]');
          if (sub) sub.click();
          out.sub = read();
          forgeProMarkShow(v, 420, 300, forgeProMenu(v, { shift: true, key: '', ctrl: false }));
          out.create = read();
          forgeProMarkHide();
          return out; }""")
        tools = menu["tools"]
        check("Shift + right button on an object is Maya's object marking menu, every wedge at Maya's place",
              tools["hub"] == "Mesh tools" and tools["ring"] == {"S": "extrude", "SW": "insertLoopTool", "NE": "fillHole", "N": "targetWeld",
                                                                  "W": "multiCut", "NW": "sculpt", "SE": ">Soften/Harden Edges"}, tools)
        check("...with Maya's labels (Insert Edge Loop Tool, Target Weld Tool ...)",
              tools["labels"].get("SW") == "Insert Edge Loop Tool" and tools["labels"].get("N") == "Target Weld Tool", tools["labels"])
        check("...and its list in Maya's order (Offset Edge Loop, Smooth ... Combine)",
              tools["rows"][:2] == ["offsetEdgeLoop", "smooth"] and "combine" in tools["rows"] and "separate" in tools["rows"], tools["rows"])
        check("a sub-menu wedge (Soften/Harden Edges) opens its own marking menu at Maya's places",
              menu["sub"]["ring"] == {"S": "softHardDisplay", "SE": "hardEdge", "E": "softHard", "NE": "softEdge"}, menu["sub"])
        cr = menu["create"]
        check("Shift + right button on nothing is Maya's Create ring (Sphere E, Torus SE, Cube S, Cone SW, Cylinder W, Plane NW)",
              cr["hub"] == "Create" and cr["ring"] == {"E": "sphere", "SE": "torus", "S": "cube", "SW": "cone", "W": "cylinder", "NW": "plane"}
              and "quadDraw" in cr["rows"], cr)

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
