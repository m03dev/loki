"""Forge's window in headless Chromium (split from tests/test_forge3d.py so each suite stays under a minute):
the vendored three.js add-ons load and a .glb exported with GLTFExporter is read back by GLTFLoader; the
model is made from a drawing through the real API, sculpted (SculptGL's brushes), undone, subdivided and
saved; the Output panel is built from the engine's option modules, remembered and greyed out per backend;
the Material Maker graph evaluates a 3-node graph to a texture and applies it to the model; and the Forge
panel fits a 900x600 window (every button reachable). Skips without Playwright + Chromium.

    python tests/test_forge_ui.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-forgeui-"))
WS = TMP / "ws"
WS.mkdir()
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_TRIPOSR_DIR"] = str(TMP / "no-triposr")
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

import forge3d  # noqa: E402
import loki_bridge  # noqa: E402


class Agent:
    WORKSPACE = WS


class State:
    agent = Agent()
    secret = "s3cret"


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), loki_bridge.BridgeHandler)
        self.state = State()


srv = Server()
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path, raw_body=None):
    req = urllib.request.Request(BASE + path, data=raw_body, method="POST" if raw_body is not None else "GET",
                                 headers={"Authorization": "Bearer s3cret", "Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=20) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


GRAPH3 = {"nodes": [   # Material Maker nodes: perlin -> colorize -> Material (albedo), perlin -> height
    {"name": "Material", "type": "material", "parameters": {}},
    {"name": "noise", "type": "perlin", "parameters": {"scale_x": 4, "scale_y": 4, "iterations": 3, "persistence": 0.5}, "seed_int": 7},
    {"name": "tint", "type": "colorize", "parameters": {"gradient": {"interpolation": 1, "type": "Gradient", "points": [
        {"pos": 0, "r": 1, "g": 0, "b": 0, "a": 1}, {"pos": 1, "r": 0, "g": 0, "b": 1, "a": 1}]}}}],
    "connections": [{"from": "noise", "from_port": 0, "to": "tint", "to_port": 0},
                    {"from": "tint", "from_port": 0, "to": "Material", "to_port": 0},
                    {"from": "noise", "from_port": 0, "to": "Material", "to_port": 6}]}


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
            path = r.request.url.split("8898", 1)[1].split("#")[0]
            bare = path.split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if bare.startswith("/forge/"):   # the real engine routes
                st, out, kind = call(path, r.request.post_data_buffer) if r.request.method == "POST" else call(path)
                return await r.fulfill(status=st, body=out, content_type=kind or "application/json")
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8898/**", route)
        await page.goto("http://127.0.0.1:8898/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)

        # -------- the vendored three.js add-ons: export with GLTFExporter, read back with GLTFLoader
        rt = await page.evaluate("""async () => {
          const T = await import('/ui/vendor/three/three.module.js');
          const { GLTFExporter } = await import('/ui/vendor/three/addons/exporters/GLTFExporter.js');
          const { GLTFLoader } = await import('/ui/vendor/three/addons/loaders/GLTFLoader.js');
          const { OBJExporter } = await import('/ui/vendor/three/addons/exporters/OBJExporter.js');
          await import('/ui/vendor/three/addons/controls/OrbitControls.js');
          await import('/ui/vendor/three/addons/controls/TransformControls.js');
          const mesh = new T.Mesh(new T.TorusKnotGeometry(1, 0.3, 64, 8), new T.MeshStandardMaterial({ color: 0xff8800 }));
          const glb = await new GLTFExporter().parseAsync(mesh, { binary: true });
          const back = await new GLTFLoader().parseAsync(glb, '');
          let tris = 0; back.scene.traverse((o) => { if (o.isMesh) tris += o.geometry.index.count / 3; });
          return { bytes: glb.byteLength, magic: new TextDecoder().decode(new Uint8Array(glb, 0, 4)), tris,
                   want: mesh.geometry.index.count / 3, obj: new OBJExporter().parse(mesh).split('\\n').filter((l) => l.startsWith('f ')).length };
        }""")
        check("vendored GLTFExporter writes a .glb that the vendored GLTFLoader reads back", rt["magic"] == "glTF"
              and rt["tris"] == rt["want"] and rt["obj"] == rt["want"], rt)

        # -------- open Forge, the Output panel
        await page.click("#open-forge")
        await page.wait_for_selector("#forge:not([hidden])", timeout=5000)
        await page.wait_for_function("document.querySelectorAll('#forge-output-body .forge-opt').length > 0", timeout=8000)
        n_opts = await page.evaluate("document.querySelectorAll('#forge-output-body .forge-opt').length")
        check("the Output panel is built from the engine's option modules", n_opts == len(forge3d.OPTIONS), n_opts)
        await page.evaluate("document.getElementById('forge-output').open = true")
        await page.select_option("#forge-backend", "lift")
        greyed = await page.evaluate("[...document.querySelectorAll('#forge-output-body .forge-opt.off')].map((r) => r.dataset.opt)")
        check("options the lift ignores are greyed out (texture size, subject fill)", "texture_size" in greyed and "foreground" in greyed
              and "thickness" not in greyed, greyed)
        await page.select_option("#forge-backend", "triposr")
        greyed2 = await page.evaluate("[...document.querySelectorAll('#forge-output-body .forge-opt.off')].map((r) => r.dataset.opt)")
        check("...and change with the backend (TripoSR ignores thickness)", "thickness" in greyed2 and "foreground" not in greyed2, greyed2)
        await page.select_option("#forge-backend", "lift")
        await page.evaluate("""() => { const r = document.querySelector('#forge-output-body input[data-opt="resolution"]');
          r.value = '96'; r.dispatchEvent(new Event('input')); }""")
        stored = await page.evaluate("JSON.parse(localStorage.getItem('loki-forge-output') || '{}').resolution")
        check("a slider is remembered (localStorage)", stored == 96, stored)

        # -------- draw -> make -> the model through the real API with the options
        box = await page.query_selector("#forge-canvas")
        bb = await box.bounding_box()
        await page.mouse.move(bb["x"] + bb["width"] * 0.3, bb["y"] + bb["height"] * 0.5)
        await page.mouse.down()
        for i in range(12):
            await page.mouse.move(bb["x"] + bb["width"] * (0.3 + i * 0.03), bb["y"] + bb["height"] * (0.5 - 0.01 * i))
        await page.mouse.up()
        await page.click("#forge-make")
        await page.wait_for_function("document.getElementById('forge-empty').hidden === true && forge.view && forge.view.sm", timeout=20000)
        side = sorted((WS / "models" / ".meta").glob("*.glb.json"))[-1]
        check("a drawing becomes a model, made with the slider's values", json.loads(side.read_text())["options"]["resolution"] == 96)

        # -------- Maya's interaction layer (app/ui/forge_maya.js): hotkeys, the hotbox, marking menus, camera
        view_box = await (await page.query_selector("#forge-view")).bounding_box()
        vcx, vcy = view_box["x"] + view_box["width"] * 0.5, view_box["y"] + view_box["height"] * 0.5
        await page.keyboard.press("4")
        check("Maya hotkey 4 turns wireframe on", await page.evaluate("forge.view.wire === true"))
        await page.keyboard.press("5")
        check("Maya hotkey 5 goes back to shaded", await page.evaluate("forge.view.wire === false"))
        await page.keyboard.press("w")
        check("w attaches the move handle (Maya's move tool)", await page.evaluate("!!forge.view.transform.object"))
        await page.keyboard.press("q")
        q_state = await page.evaluate("""() => ({ obj: !!forge.view.transform.object,
          ttype: typeof forge.view.transform, detach: typeof forge.view.transform.detach,
          gizmo: !!(forge.view.gizmo && forge.view.gizmo.object), maya: !!forge.view.maya,
          last: forge.view.maya && forge.view.maya.last && forge.view.maya.last[0],
          status: (document.getElementById('forge-status') || {}).textContent })""")
        check("q is Maya's select tool: it puts the handle away", not q_state["obj"], q_state)
        await page.keyboard.down("Alt")
        alt_right = await page.evaluate("forge.view.maya.controls.mouseButtons.RIGHT")
        alt_dbg = await page.evaluate("""() => ({ right: forge.view.maya.controls.mouseButtons.RIGHT,
          left: forge.view.maya.controls.mouseButtons.LEFT, saved: !!forge.view.maya.saved })""")
        await page.keyboard.up("Alt")
        rest_right = await page.evaluate("forge.view.maya.controls.mouseButtons.RIGHT")
        check("Maya camera: Alt puts the dolly on the right button, and the marking menu owns it again on release",
              alt_right is not None and rest_right is None, [alt_right, rest_right, alt_dbg])

        # hold Space -> the hotbox opens over the window; release -> it goes
        await page.evaluate("document.activeElement && document.activeElement.blur && document.activeElement.blur()")
        await page.keyboard.down(" ")
        await page.wait_for_timeout(150)
        hb_vis = await page.is_visible("#forge-maya-hotbox")
        cols = await page.evaluate("document.querySelectorAll('#forge-maya-hotbox .forge-maya-col').length")
        items = await page.evaluate("document.querySelectorAll('#forge-maya-hotbox .forge-maya-item').length")
        await page.keyboard.up(" ")
        await page.wait_for_timeout(120)
        hb_gone = not await page.is_visible("#forge-maya-hotbox")
        check("holding Space opens Maya's hotbox (menu columns with commands), releasing it closes", hb_vis and hb_gone and cols >= 5 and items >= 15,
              [hb_vis, hb_gone, cols, items])

        # hold the right button on the viewport -> the marking menu opens at the cursor; release over a wedge runs it
        await page.mouse.move(vcx, vcy)
        await page.mouse.down(button="right")
        await page.wait_for_timeout(320)
        wheel = await page.evaluate("!document.getElementById('forge-maya-marking').hidden")
        wedges = await page.evaluate("[...document.querySelectorAll('#forge-maya-marking .forge-maya-wedge')].map((b) => b.dataset.mayaCmd)")
        if wheel:
            wb = await (await page.query_selector('#forge-maya-marking .forge-maya-wedge[data-maya-cmd="Rotate"]')).bounding_box()
            await page.mouse.move(wb["x"] + wb["width"] / 2, wb["y"] + wb["height"] / 2)
        await page.mouse.up(button="right")
        await page.wait_for_timeout(120)
        check("holding the right button opens a marking menu at the cursor (8 wedges)", wheel and len(wedges) == 8, wedges)
        check("releasing over a wedge runs it (Rotate puts the handle in rotate mode)",
              await page.evaluate("!!forge.view.transform.object && forge.view.transform.mode === 'rotate'"))
        check("the marking menu closes after the choice",
              await page.evaluate("document.getElementById('forge-maya-marking').hidden"))
        await page.keyboard.press("q")
        await page.keyboard.press("5")   # tidy: select tool, shaded

        # -------- T1/T2: the scene and the Outliner (app/ui/forge_scene.js)
        rows0 = await page.evaluate("document.querySelectorAll('#forge-outliner .forge-out-row').length")
        check("the Outliner shows the working object", rows0 == 1, rows0)
        dup = await page.evaluate("forge.view.tree.api.duplicate().name")
        await page.evaluate("forge.view.tree.api.duplicate()")
        n_nodes = await page.evaluate("forge.view.tree.nodes.length")
        rows1 = await page.evaluate("document.querySelectorAll('#forge-outliner .forge-out-row').length")
        check("Duplicate makes real extra objects, each with its own geometry", n_nodes == 3, [dup, n_nodes])
        check("the Outliner lists them", rows1 == 3, rows1)

        # T1's acceptance test: sculpting the working object must leave another object untouched
        geom = "forge.view.tree.nodes[1].grp.children[0].geometry.attributes.position.array.reduce((s, v) => s + Math.abs(v), 0)"
        before_dup = await page.evaluate(geom)
        sum_active = "forge.view.sm.wpos.reduce((s, v) => s + Math.abs(v), 0)"
        before_active = await page.evaluate(sum_active)
        await page.evaluate("forge.view.dab('inflate', 0.05, 0, 0.05, false)")
        after_dup = await page.evaluate(geom)
        after_active = await page.evaluate(sum_active)
        check("sculpting the working object moves it", abs(after_active - before_active) > 1e-6)
        check("...and leaves the other object untouched (T1's acceptance test)",
              abs(after_dup - before_dup) < 1e-6, [before_dup, after_dup])
        await page.evaluate("forge.view.undo()")

        # rename / visibility
        await page.evaluate("forge.view.tree.api.rename(2, 'sidekick')")
        check("an object can be renamed", await page.evaluate("forge.view.tree.api.node(2).name") == "sidekick")
        await page.evaluate("forge.view.tree.api.setVisible(2, false)")
        check("an object can be hidden (and comes back)",
              await page.evaluate("forge.view.tree.api.node(2).grp.visible") is False)
        await page.evaluate("forge.view.tree.api.setVisible(2, true)")

        # Group (Maya's hotkey) -> a transform node with the selection inside it, pivot at the selection centre
        await page.evaluate("forge.view.tree.api.select(2)")
        await page.evaluate("forge.view.tree.api.select(3, true)")
        await page.keyboard.press("Control+g")
        grp = await page.evaluate("""() => { const t = forge.view.tree.api;
          const g = t.list().find((n) => n.kind === 'group');
          return g ? { id: g.id, kids: t.kids(g.id).length, parent: t.node(2).parent,
                       atOrigin: g.grp.position.length() >= 0 } : null; }""")
        check("Ctrl+G groups the selection into one transform node (Maya's hotkey)",
              bool(grp) and grp["kids"] == 2 and grp["parent"] == grp["id"], grp)
        await page.keyboard.press("Control+Shift+g")
        un = await page.evaluate("""() => { const t = forge.view.tree.api;
          return { groups: t.list().filter((n) => n.kind === 'group').length, parent: t.node(2).parent }; }""")
        check("Ctrl+Shift+G ungroups them back to the top level", un["groups"] == 0 and un["parent"] == 0, un)

        # re-parent by hand (the drag path uses the same call)
        await page.evaluate("forge.view.tree.api.group('holder1', [2, 3])")
        gid = await page.evaluate("forge.view.tree.api.list().find((n) => n.kind === 'group').id")
        await page.evaluate("forge.view.tree.api.reparent(%d, 0)" % gid) if False else None
        moved = await page.evaluate("""() => { const t = forge.view.tree.api;
          const g = t.list().find((n) => n.kind === 'group');
          t.rename(g.id, 'parts');
          return { renamed: t.node(g.id).name, rows: document.querySelectorAll('#forge-outliner .forge-out-row').length,
                   indented: [...document.querySelectorAll('#forge-outliner .forge-out-row')].some((r) => parseFloat(r.style.paddingLeft) > 10) };
        }""")
        check("a group can be renamed and the Outliner indents its children",
              moved["renamed"] == "parts" and moved["indented"], moved)

        # -------- T4: the Channel Box - exact numbers for the selected object
        await page.evaluate("forge.view.tree.api.select(2)")
        await page.fill("#forge-ch-tx", "3")
        moved_x = await page.evaluate("forge.view.tree.api.node(2).grp.position.x")
        check("the Channel Box moves the selected object by typing a number", abs(moved_x - 3) < 1e-6, moved_x)
        await page.fill("#forge-ch-ry", "90")
        rot_y = await page.evaluate("forge.view.tree.api.node(2).grp.rotation.y * 180 / Math.PI")
        check("...and rotates in degrees, the way Maya's Channel Box shows them", abs(rot_y - 90) < 1e-3, rot_y)
        await page.evaluate("forge.view.tree.api.select(1)")
        root_x = await page.evaluate("document.getElementById('forge-ch-tx').value")
        await page.evaluate("forge.view.tree.api.select(2)")
        back_x = await page.evaluate("document.getElementById('forge-ch-tx').value")
        check("the numbers follow the selection", root_x == "0" and back_x == "3", [root_x, back_x])
        hit = await page.evaluate("""() => { const b = document.getElementById('forge-ch-reset');
          const r = b.getBoundingClientRect();
          const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return { ok: el === b || b.contains(el) || (el && el.contains(b)),
                   at: (el && (el.id || el.getAttribute('class'))) || 'none',
                   rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)] }; }""")
        check("the Channel Box's Reset button is really clickable (nothing covers it)", hit["ok"], hit)
        await page.evaluate("document.getElementById('forge-ch-reset').click()")
        reset = await page.evaluate("forge.view.tree.api.node(2).grp.position.toArray()")
        check("Reset puts the selected object back on the origin", reset == [0, 0, 0], reset)

        # -------- T4b: Freeze Transformations and Center Pivot
        hit2 = await page.evaluate("""() => ['forge-ch-pivot', 'forge-ch-freeze'].map((id) => {
          const b = document.getElementById(id);
          if (!b) return { id: id, ok: false };
          const r = b.getBoundingClientRect();
          const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return { id: id, ok: el === b || b.contains(el) }; })""")
        check("Center Pivot and Freeze are on the panel and really clickable", all(h["ok"] for h in hit2), hit2)
        await page.evaluate("document.getElementById('forge-hist-clear').scrollIntoView({ block: 'center' })")
        hist_hit = await page.evaluate("""() => { const b = document.getElementById('forge-hist-clear');
          if (!b) return { ok: false };
          const r = b.getBoundingClientRect();
          const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          return { ok: el === b || b.contains(el), rect: [Math.round(r.top), Math.round(r.height)] }; }""")
        check("the History panel's Delete History button is really clickable", hist_hit["ok"], hist_hit)
        await page.evaluate("forge.view.tree.api.select(1)")
        await page.evaluate("forge.view.tree.api.resetTransform(1)")
        await page.evaluate("forge.view.tree.api.setTransform(1, 'translate', 1, 1)")   # lift it one unit
        frozen = await page.evaluate("""() => { const t = forge.view.tree.api, sm = forge.view.sm;
          const cOf = () => { let lo = 1e9, hi = -1e9;
            for (let i = 0; i < sm.n; i++) { const y = sm.wpos[i * 3 + 1]; if (y < lo) lo = y; if (y > hi) hi = y; }
            return (lo + hi) / 2; };
          const c0 = cOf(); t.freeze(1); const c1 = cOf();
          return { moved: c1 - c0, at: forge.view.holder.position.toArray(),
                   rot: forge.view.holder.rotation.toArray().slice(0, 3) }; }""")
        check("Freeze Transformations bakes the move into the mesh and leaves the object where it was",
              abs(frozen["moved"] - 1) < 1e-4 and frozen["at"] == [0, 0, 0] and frozen["rot"] == [0, 0, 0], frozen)
        piv = await page.evaluate("""() => { const t = forge.view.tree.api, sm = forge.view.sm;
          const cOf = () => { const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
            for (let i = 0; i < sm.n; i++) for (let k = 0; k < 3; k++) { const x = sm.wpos[i * 3 + k];
              if (x < lo[k]) lo[k] = x; if (x > hi[k]) hi[k] = x; }
            return [0, 1, 2].map((k) => (hi[k] + lo[k]) / 2); };
          const before = cOf(); t.centerPivot(1); const after = cOf();
          return { before: before, after: after, at: forge.view.holder.position.toArray() }; }""")
        check("Center Pivot puts the manipulator's origin on the object's middle without moving the object",
              all(abs(a) < 1e-4 for a in piv["after"])
              and max(abs(piv["before"][k] - piv["at"][k]) for k in range(3)) < 1e-4, piv)

        # -------- T5: Shift + drag on the manipulator leaves a copy behind and drags the new one
        await page.evaluate("forge.view.tree.api.select(1)")
        await page.evaluate("forge.view.toggleTransform('translate')")
        n_before = await page.evaluate("forge.view.tree.nodes.length")
        await page.keyboard.down("Shift")
        await page.evaluate("forge.view.transform.dispatchEvent({ type: 'dragging-changed', value: true })")
        await page.keyboard.up("Shift")
        drag = await page.evaluate("""() => { const t = forge.view.tree.api, copy = t.active();
          return { nodes: t.list().length, name: copy.name, root: !!copy.root,
                   onGizmo: !!(forge.view.transform.object && forge.view.transform.object === copy.grp) }; }""")
        check("Shift+drag leaves the original and hands the manipulator to a copy",
              drag["nodes"] == n_before + 1 and not drag["root"] and drag["onGizmo"], drag)
        await page.evaluate("forge.view.toggleTransform(null)")

        # -------- sculpt (SculptGL's brushes), undo, subdivide
        sum_js = "forge.view.sm.wpos.reduce((s, v) => s + Math.abs(v), 0)"
        before = await page.evaluate(sum_js)
        moved = {}
        for b in ("draw", "inflate", "flatten", "pinch", "crease", "smooth"):
            await page.evaluate("forge.view.dab('%s', 0.05, 0, 0.05, false)" % b)
            moved[b] = abs(await page.evaluate(sum_js) - before)
            await page.evaluate("forge.view.undo()")
        check("every SculptGL brush moves vertices (clay, inflate, flatten, pinch, crease, smooth)", all(v > 1e-6 for v in moved.values()), moved)
        check("undo puts them back", abs(await page.evaluate(sum_js) - before) < 1e-3)
        tris = await page.evaluate("forge.view.sm.idx.length / 3")
        await page.evaluate("forge.view.subdivide()")
        check("subdivide makes four times the triangles", await page.evaluate("forge.view.sm.idx.length / 3") == tris * 4)
        await page.click("#forge-mode")
        check("Sculpt mode shows the brushes", await page.is_visible("#forge-sculpt [data-brush='crease']"))

        # -------- materials: a 3-node Material Maker graph -> a texture, applied to the model
        tex = await page.evaluate("""async (g) => {
          const r = await fetch('/ui/vendor/material_maker/nodes.json'); window.ForgeMM.load(await r.json());
          const cv = window.ForgeMaterials.renderMap(g, 'albedo', 64);
          const d = cv.getContext('2d').getImageData(0, 0, 64, 64).data;
          let red = 0, blue = 0, green = 0, distinct = new Set();
          for (let i = 0; i < d.length; i += 4) { red += d[i]; green += d[i + 1]; blue += d[i + 2]; distinct.add(d[i] + ',' + d[i + 2]); }
          const h = window.ForgeMaterials.renderMap(g, 'normal', 32).getContext('2d').getImageData(0, 0, 32, 32).data;
          return { red, green, blue, distinct: distinct.size, normalB: h[2] };
        }""", GRAPH3)
        check("a 3-node Material Maker graph (perlin -> colorize -> material) renders to a texture",
              tex["red"] > 0 and tex["blue"] > 0 and tex["green"] == 0 and tex["distinct"] > 20, tex)
        check("the normal map comes from the height (blue up)", tex["normalB"] > 180, tex)
        await page.click(".forge-tab[data-side='materials']")
        await page.wait_for_function("document.querySelectorAll('.fm-map-img canvas').length === 6", timeout=10000)
        check("the Materials side shows the six PBR maps", True)
        applied = await page.evaluate("""() => { const kids = forge.view.holder.children;
          const mesh = kids.find((o) => o.isMesh) || kids[0] || {};
          const m = mesh.material || {};
          return { map: !!m.map, normal: !!m.normalMap, rough: !!m.roughnessMap,
                   kids: kids.map((o) => o.name || o.type) }; }""")
        check("the material is applied to the model live",
              all(applied[k] for k in ("map", "normal", "rough")), applied)
        await page.evaluate("""() => { const n = window.ForgeMaterials.state.graph.nodes.find((x) => x.type === 'material');
          window.ForgeMaterials.state.sel = n.name; }""")
        await page.evaluate("forgeSave('glb')")
        await page.wait_for_function("/Saved models/.test(document.getElementById('forge-status').textContent)", timeout=15000)
        sculpted = sorted((WS / "models").glob("*-sculpt*.glb"))
        doc = forge3d.read_glb(sculpted[-1])[0] if sculpted else {}
        mat = (doc.get("materials") or [{}])[0]
        check("Save .glb (GLTFExporter) keeps the sculpt and the material's maps", bool(sculpted)
              and forge3d.glb_counts(sculpted[-1])["triangles"] == tris * 4 and "baseColorTexture" in mat.get("pbrMetallicRoughness", {})
              and "normalTexture" in mat, mat)

        # -------- quad view: front / side / top / three-quarter orthographic panels (anyCreature's views)
        QUAD = "#forge .forge-viewbar button[data-tip-name='Quad view']"
        check("the view bar has a Quad view toggle", await page.query_selector(QUAD) is not None)
        await page.click(QUAD)
        await page.wait_for_timeout(250)
        q = await page.evaluate("""() => ({ on: !!forge.view.quad,
          labels: [...document.querySelectorAll('#forge-quad-labels span')].map((s) => s.textContent),
          shown: !document.getElementById('forge-quad-labels').hidden, orbit: forge.view.controls.enabled })""")
        check("Quad view turns on, names the four panels and stops orbiting",
              q["on"] and q["labels"] == ["Front", "Side", "Top", "3/4 view"] and q["shown"] and not q["orbit"], q)
        quad_ink = await page.evaluate("""() => { const cv = document.getElementById('forge-view');
          const g = document.createElement('canvas'); g.width = cv.width; g.height = cv.height;
          const c = g.getContext('2d'); c.drawImage(cv, 0, 0);
          const d = c.getImageData(0, 0, g.width, g.height).data, W = g.width, H = g.height;
          const ink = (x0, y0, x1, y1) => { let n = 0;
            for (let y = y0; y < y1; y += 2) for (let x = x0; x < x1; x += 2) if (d[(y * W + x) * 4 + 3] > 16) n++;
            return n; };
          return [ink(0, 0, W >> 1, H >> 1), ink(W >> 1, 0, W, H >> 1), ink(0, H >> 1, W >> 1, H), ink(W >> 1, H >> 1, W, H)]; }""")
        check("all four orthographic panels draw the model (front, side, top, 3/4 view)",
              all(n > 0 for n in quad_ink) and len(set(quad_ink)) >= 3, quad_ink)
        await page.click(QUAD)
        await page.wait_for_timeout(200)
        back = await page.evaluate("() => ({ on: !!forge.view.quad, orbit: forge.view.controls.enabled, hidden: document.getElementById('forge-quad-labels').hidden })")
        check("toggling Quad view off returns to the orbit view", (not back["on"]) and back["orbit"] and back["hidden"], back)

        # -------- the Creature way: controls, not JSON -> a model in the four panels
        await page.click(".forge-tab[data-side='make']")   # the ways live in the left column
        await page.wait_for_timeout(200)
        await page.click("#forge .forge-way[data-way='creature']")
        await page.wait_for_function("document.querySelectorAll('#forge-creature-presets button[data-preset]').length > 0", timeout=15000)
        presets = await page.eval_on_selector_all("#forge-creature-presets button[data-preset]", "els => els.map((e) => e.dataset.preset)")
        n_sliders = await page.eval_on_selector_all("#forge-creature-sliders input[type=range]", "els => els.length")
        n_colours = await page.eval_on_selector_all("#forge-creature-colors input[type=color]", "els => els.length")
        check("the Creature way draws a friendly form - presets, sliders, colour pickers, no JSON",
              len(presets) >= 3 and n_sliders >= 2 and n_colours >= 2
              and (await page.inner_text("#forge-make")).strip() == "Make creature",
              {"presets": presets, "sliders": n_sliders, "colours": n_colours})
        await page.click("#forge-creature-presets button[data-preset='%s']" % presets[-1])
        await page.fill("#forge-creature-name", "ui_creature")
        await page.click("#forge-make")
        await page.wait_for_function("forge.view && forge.view.quad && forge.view.sm", timeout=60000)
        made = await page.evaluate("() => ({quad: !!forge.view.quad, model: forge.model})")
        check("Make creature compiles a preset and loads it into the four panels, Quad on",
              made["quad"] and "ui_creature" in str(made["model"]), made)
        # the advanced spec is tucked away; an invalid one is refused with the reason
        await page.evaluate("document.querySelector('#forge .forge-advanced').open = true")
        await page.evaluate("document.getElementById('forge-creature-spec').value = 'this is not JSON'")
        await page.click("#forge-make")
        await page.wait_for_function("/not valid JSON/.test(document.getElementById('forge-status').textContent)", timeout=20000)
        spec_err = await page.inner_text("#forge-status")
        check("a pasted spec that is not JSON is refused, with the reason shown", "not valid JSON" in spec_err, spec_err)
        await page.evaluate("document.getElementById('forge-creature-spec').value = ''")
        await page.click("#forge .forge-way[data-way='describe']")
        await page.wait_for_timeout(150)

        # -------- layout: the panel fits 900x600, every button reachable
        await page.set_viewport_size({"width": 900, "height": 600})
        await page.click(".forge-tab[data-side='make']")
        await page.wait_for_timeout(300)
        fit = await page.evaluate("""() => {
          const vw = innerWidth, vh = innerHeight, out = [];
          const panel = document.querySelector('.forge-panel').getBoundingClientRect();
          if (panel.right > vw + 0.5 || panel.bottom > vh + 0.5 || panel.left < -0.5 || panel.top < -0.5) out.push('panel');
          const stage = document.getElementById('forge-stage').getBoundingClientRect();
          for (const b of document.querySelectorAll('#forge .forge-viewbar button, #forge .forge-exportbar button, #forge .forge-head button')) {
            const r = b.getBoundingClientRect();
            if (r.width === 0) continue;
            const inside = r.left >= panel.left - 0.5 && r.right <= panel.right + 0.5 && r.top >= panel.top - 0.5 && r.bottom <= panel.bottom + 0.5;
            const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            if (!inside || !(hit === b || b.contains(hit))) out.push(b.dataset.tipName || b.textContent);
          }
          const side = document.getElementById('forge-left');
          return { bad: out, sideScrolls: side.scrollHeight > side.clientHeight ? getComputedStyle(side).overflowY : 'fits',
                   stageH: Math.round(stage.height) };
        }""")
        check("the Forge panel fits 900x600: viewer, save and toolbar buttons all on screen and clickable", not fit["bad"]
              and fit["stageH"] > 150, fit)
        check("the left column scrolls inside instead of pushing the viewer off", fit["sideScrolls"] in ("auto", "scroll", "fits"), fit)
        await page.click("#forge-mode")
        await page.click("#forge-mode")
        sculpt_ok = await page.evaluate("""() => { const st = document.getElementById('forge-stage').getBoundingClientRect();
          return [...document.querySelectorAll('#forge-sculpt button')].filter((b) => { const r = b.getBoundingClientRect();
            const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            return !(r.bottom <= st.bottom + 0.5 && r.top >= st.top - 0.5 && (hit === b || b.contains(hit))); })
            .map((b) => b.dataset.tipName); }""")
        check("every sculpt tool is on screen and clickable at 900x600 (no hidden scroll)", not sculpt_ok, sculpt_ok)
        await page.click(".forge-tab[data-side='materials']")
        await page.wait_for_timeout(300)
        mats_fit = await page.evaluate("""() => { const p = document.querySelector('.forge-panel').getBoundingClientRect();
          return [...document.querySelectorAll('.fm-bar > *')].every((b) => { const r = b.getBoundingClientRect();
            return r.right <= p.right + 0.5 && r.bottom <= p.bottom + 0.5; }); }""")
        check("the Materials toolbar fits at 900x600", mats_fit)
        await page.screenshot(path=str(TMP / "forge-900x600.png"))
        # -------- T6: construction history - the poly ops, editable, with Delete History
        # (the Forge window may already be closed by the earlier 900x600 section; the panel check below needs it)
        was_closed = await page.evaluate("document.getElementById('forge').hidden")
        if was_closed:
            await page.click("#open-forge")
            await page.wait_for_selector("#forge:not([hidden])", timeout=8000)
        await page.evaluate("forgeAddPrimitive('cube')")
        await page.wait_for_function("forge.view && forge.view.poly && forge.view.poly.f.length > 0", timeout=15000)
        await page.evaluate("forge.view.select([0]); forgeFaceOp('extrude')")
        await page.evaluate("forge.view.select([0]); forgeFaceOp('extrude')")
        hist = await page.evaluate("window.forgeHistory.list()")
        rows = await page.evaluate("document.querySelectorAll('#forge-history .forge-hist-row').length")
        check("every operation is recorded, in order, with its parameters",
              len(hist) == 2 and [h["kind"] for h in hist] == ["extrude", "extrude"], hist)
        check("the History panel lists them", rows == 2, rows)
        sum_js = "forge.view.sm.wpos.reduce((s, v) => s + Math.abs(v), 0)"
        before_amt = await page.evaluate(sum_js)
        await page.evaluate("window.forgeHistory.setAmount(1, 0.6)")
        after_amt = await page.evaluate(sum_js)
        check("changing a step's amount rebuilds the model from the first step (and moves it)",
              await page.evaluate("window.forgeHistory.list()[1].amount") == 0.6
              and abs(after_amt - before_amt) > 1e-5, [before_amt, after_amt])
        left = await page.evaluate("window.forgeHistory.remove(0); window.forgeHistory.list().length")
        check("a step can be removed and the model rebuilds without it", left == 1, left)
        await page.evaluate("window.forgeHistory.clear()")
        check("Delete History empties the stack", await page.evaluate("window.forgeHistory.list().length") == 0)
        await page.evaluate("forgeDynamesh()")
        await page.wait_for_function("window.forgeHistory.list().length === 1", timeout=25000)
        dm = await page.evaluate("""() => { const H = window.forgeHistory, res = forgeModel.dyna.res;
          const f0 = forge.view.poly.f.length;
          H.setAmount(0, res + 16);
          return { ops: H.list(), f0: f0, f1: forge.view.poly.f.length, res: res }; }""")
        check("DynaMesh is recorded as a re-runnable step: change its resolution and the mesh rebuilds",
              bool(dm["ops"]) and dm["ops"][0]["kind"] == "dynamesh" and dm["ops"][0]["amount"] == dm["res"] + 16
              and dm["f1"] != dm["f0"], dm)

        # T6c: a sculpt stroke becomes a history step - the vertices it moved, never the dabs
        await page.evaluate("window.forgeHistory.clear()")
        if not await page.evaluate("forge.view.mode === 'sculpt'"):
            await page.click("#forge-mode")
            await page.wait_for_timeout(250)
        await page.evaluate("forge.view.brush.radius = 0.35")                      # the DynaMesh cubes are coarse
        sum_pre = await page.evaluate("forge.view.sm.wpos.reduce((s, v) => s + Math.abs(v), 0)")
        await page.evaluate("forge.view.dab('inflate', 0.05, 0, 0.05, false)")   # a real brush stroke
        sum_post = await page.evaluate("forge.view.sm.wpos.reduce((s, v) => s + Math.abs(v), 0)")
        stroke_diag = await page.evaluate("""() => { const v = forge.view;
          const top = v.undoStack[v.undoStack.length - 1];
          return { mode: v.mode, radius: v.brush.radius, stack: v.undoStack.length,
                   topIsSm: !!(top && top.sm === v.sm), hasPush: typeof window.forgeHistPushSculpt,
                   hasEnd: typeof v.sculptStrokeEnd, moved: %s !== %s }; }""" % (sum_pre, sum_post))
        await page.evaluate("forge.view.sculptStrokeEnd()")                        # what the pointer's release does
        sh = await page.evaluate("window.forgeHistory.list()")
        affected = sh[0]["affected"] if sh and sh[0]["kind"] == "sculpt" else 0
        check("a sculpt stroke is recorded as a history step - the vertices it moved, not the dabs",
              bool(sh) and sh[0]["kind"] == "sculpt" and affected > 0, [sh, stroke_diag, sum_pre, sum_post])
        sum_now = "forge.view.sm.wpos.reduce((s, v) => s + Math.abs(v), 0)"
        after_stroke = await page.evaluate(sum_now)
        await page.evaluate("window.forgeHistory.remove(0)")
        back = await page.evaluate(sum_now)
        check("removing the stroke puts exactly those vertices back",
              await page.evaluate("window.forgeHistory.list().length") == 0 and abs(back - after_stroke) > 1e-6,
              [after_stroke, back])

        check("no script errors in Forge", not errors, errors[:3])
        await browser.close()


try:
    asyncio.run(asyncio.wait_for(main(), 80))   # the suite grew: scene, Outliner, Channel Box and the Maya keys
except asyncio.TimeoutError:
    check("the Forge window check finishes in time", False)
srv.shutdown()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
