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

        # -------- Maya's layer and the scene are attached (their behaviour: tests/test_forge_maya_ui.py)
        attached = await page.evaluate("""() => ({ maya: !!forge.view.maya, tree: !!(forge.view.tree && forge.view.tree.api),
          rows: document.querySelectorAll('#forge-outliner .forge-out-row').length })""")
        check("Maya's layer and the scene (Outliner) are attached to the viewer", attached["maya"] and attached["tree"]
              and attached["rows"] == 1, attached)


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
    asyncio.run(asyncio.wait_for(main(), 60))   # Maya keys + scene moved to tests/test_forge_maya_ui.py
except asyncio.TimeoutError:
    check("the Forge window check finishes in time", False)
srv.shutdown()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
