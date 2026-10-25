"""Forge's Model bar in headless Chromium (app/ui/forge_model.js + forge_poly.js): a primitive is added and shaped
with its sliders, a face is picked with a real click, extruded (and the redo slider re-does it live), inset,
smoothed, undone; a sculpt is DynaMeshed into quads; the bar fits a 900x600 window; and the sidebar's icon row
(LOKI Studio last) stays inside the sidebar (owner 2026-10-18: "the loki studio button is past the border").
Skips without Playwright + Chromium. Well under a minute.

    python tests/test_forge_model_ui.py
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
TMP = Path(tempfile.mkdtemp(prefix="loki-forgemodel-"))
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
        await page.add_init_script("try { localStorage.setItem('loki-forge-create-mode', 'component') } catch (e) {}")   # these checks start in component mode after Create
        await page.goto("http://127.0.0.1:8898/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        # these panels are hidden in the pro workspace until Windows (Space menu) brings them back - this suite tests them
        await page.evaluate("localStorage.setItem('loki-forge-panels', JSON.stringify({ create: true, toolkit: true, shelf: true }))")

        await page.evaluate("forgeOpen()")
        await page.wait_for_function("!!(forge.view && forge.view.showPoly)", timeout=20000)
        await page.click("#forge-model-mode")
        await page.wait_for_selector("#forge-model:not([hidden])", timeout=5000)
        await page.click("#forge [data-prim='cube']")
        r = await page.evaluate("() => ({ f: forge.view.poly.f.length, sliders: document.querySelectorAll('#forge-model-params input').length,"
                                " empty: document.getElementById('forge-empty').hidden })")
        check("Cube from the Model bar: 6 faces and its sliders (Segments, Baseline)", r["f"] == 6 and r["sliders"] == 2 and r["empty"], r)
        await page.evaluate("""() => { const i = document.querySelector('#forge-model-params input'); i.value = '3';
          i.dispatchEvent(new Event('input')); }""")
        r = await page.evaluate("forge.view.poly.f.length")
        check("the Segments slider reshapes it live (3 -> 54 faces)", r == 54, r)
        await page.click("#forge [data-prim='cylinder']")
        await page.evaluate("forge.view.frame()")
        box = await page.eval_on_selector("#forge-view", "c => { const r = c.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }")
        await page.mouse.click(box[0], box[1])
        r = await page.evaluate("forge.view.selected.slice()")
        check("a real click on the model picks the face under it", len(r) == 1, r)
        before = await page.evaluate("forge.view.poly.f.length")
        await page.evaluate("forgeFaceOp('extrude')")
        r = await page.evaluate("() => ({ f: forge.view.poly.f.length, vol: ForgePoly.volume(forge.view.poly), redo: !!document.querySelector('#forge-model-redo input') })")
        check("Extrude adds the side quads and a Distance slider", r["f"] == before + 4 and r["redo"], (before, r))
        v1 = r["vol"]
        await page.evaluate("""() => { const i = document.querySelector('#forge-model-redo input'); i.value = '0.6';
          i.dispatchEvent(new Event('input')); }""")
        r = await page.evaluate("() => ({ f: forge.view.poly.f.length, vol: ForgePoly.volume(forge.view.poly), sel: forge.view.selected.length })")
        check("the Distance slider re-does the extrude live (bigger, same faces, still picked)", r["f"] == before + 4 and r["vol"] > v1 and r["sel"] == 1, r)
        await page.evaluate("forgeFaceOp('inset')")
        r = await page.evaluate("forge.view.poly.f.length")
        check("Inset adds a ring of 4", r == before + 8, r)
        await page.evaluate("forgeFaceOp('smooth')")
        r = await page.evaluate("() => forge.view.poly.f.every((f) => f.length === 4)")
        check("Smooth (Catmull-Clark) leaves only quads", r)
        await page.evaluate("forge.view.undo()")
        r = await page.evaluate("forge.view.poly.f.length")
        check("Undo brings back the mesh before Smooth", r == before + 8, r)
        await page.click("#forge-mode")            # Sculpt: the Model bar goes away, a stroke drops the poly cage
        await page.evaluate("forge.view.dab('inflate', 0, 0.5, 0, false)")
        r = await page.evaluate("() => ({ bar: document.getElementById('forge-model').hidden, poly: forge.view.poly })")
        check("Sculpt and Model take turns", r["bar"], r)
        await page.evaluate("forgeDynamesh()")
        await page.wait_for_function("forge.view.poly && forge.view.poly.f.length > 100", timeout=20000)
        r = await page.evaluate("() => ({ f: forge.view.poly.f.length, quads: forge.view.poly.f.every((f) => f.length === 4), vol: ForgePoly.volume(forge.view.poly) })")
        check("DynaMesh rebuilds the model as even quads facing out", r["quads"] and r["vol"] > 0, r)
        # Insert Edge Loop (restored): an edge in Edge mode -> a loop round its quad ring, kept in the history
        r = await page.evaluate("""() => { const v = forge.view; forgeModelMode(true); v.setSelMode('edge'); v.selectItems('edge', [0], 'set');
          const f0 = v.poly.f.length; const msg = forgeProRun(v, 'edgeLoop');
          return { f0, f1: v.poly.f.length, quads: v.poly.f.every((f) => f.length === 4), hist: (forgeHistory.list ? forgeHistory.list() : []).map((h) => h.kind || h) }; }""")
        check("Insert Edge Loop splits the quad ring the picked edge crosses (all quads still)", r["f1"] > r["f0"] and r["quads"], r)
        await page.set_viewport_size({"width": 900, "height": 600})
        await page.evaluate("forgeModelMode(true)")
        r = await page.evaluate("""() => { const s = document.getElementById('forge-stage').getBoundingClientRect(),
          b = document.getElementById('forge-model').getBoundingClientRect(); return [b.left >= s.left, b.right <= s.right, b.top >= s.top, b.bottom <= s.bottom + 1]; }""")
        check("the Model bar fits a 900x600 window", all(r), r)
        await page.evaluate("forgeClose()")
        r = await page.evaluate("""() => { const side = document.querySelector('.sidebar').getBoundingClientRect(),
          row = [...document.querySelectorAll('.sidebar .foot-row > *')].filter((x) => x.offsetParent);
          const last = document.getElementById('open-studio'); const b = last ? last.getBoundingClientRect() : null;
          return { n: row.length, inside: row.every((x) => x.getBoundingClientRect().right <= side.right - 1), studio: !!b && b.right <= side.right - 1 }; }""")
        # the foot row is Files, Settings, Check everything, Quit (LOKI Studio lives in the More menu now): four
        # buttons, every one inside the sidebar
        check("the sidebar's icon row, LOKI Studio included, stays inside the sidebar", r["n"] >= 4 and r["inside"] and r["studio"], r)
        # Mesh > Combine / Separate / Mirror (the menu bar's Mesh menu, the hotbox, the command line)
        r = await page.evaluate("""async () => { const v = forge.view, t = v.tree.api;
          forgeModelMode(false); await forgeAddPrimitive('cube'); forgeModelMode(false); const a = t.root().id;
          await forgeAddPrimitive('cube'); forgeModelMode(false); const b = t.root().id;
          t.setTransform(b, 'translate', 0, 3); t.selectMany([a, b], 'set');
          const n0 = t.list().filter((n) => n.kind === 'mesh').length;
          forgeProRun(v, 'combine');
          const c = t.active(), n1 = t.list().filter((n) => n.kind === 'mesh').length, f1 = v.poly ? v.poly.f.length : -1;
          forgeProRun(v, 'separate');
          const parts = t.selected().map((id) => t.node(id).name);
          t.select(parts.length ? t.selected()[0] : c.id);
          t.setTransform(null, 'translate', 0, 2);
          const fm0 = (t.active().root && v.poly) ? v.poly.f.length : 6;
          const res = await forgeProCommandLine('polyMirrorFace -axis 0');
          return { n0, n1, name: c.name, f1, parts, fm0, fm1: v.poly ? v.poly.f.length : -1, res,
                   menu: forgeMenuFlat((FORGE_PRO_ROWS.find((r) => r[0] === 'Mesh') || [0, []])[1]) }; }""")
        check("Combine: two cubes become one object polySurface1 (12 faces), the edited one", r["n1"] == r["n0"] - 1 and r["name"].startswith("polySurface") and r["f1"] == 12, r)
        check("Separate: the two pieces become two objects again", len(r["parts"]) == 2, r)
        check("Mirror (polyMirrorFace -axis 0) adds the mirrored copy across X", r["fm1"] == r["fm0"] * 2 and "Mirror" in r["res"]
              and [m for m in r["menu"] if m in ("combine", "separate", "mirror")][:3] == ["combine", "separate", "mirror"]
              and r["menu"].index("combine") < r["menu"].index("separate") < r["menu"].index("mirror"), r)   # Booleans come first (Maya)
        # Edit Mesh > Fill Hole and Merge to Center, from the hotbox's commands
        r = await page.evaluate("""async () => { const v = forge.view, t = v.tree.api;
          forgeModelMode(false); await forgeAddPrimitive('cube'); forgeModelMode(true);
          v.setSelMode('face'); v.selectItems('face', [0], 'set'); forgeFaceOp('delete');
          const holed = v.poly.f.length;
          v.selectItems('face', [], 'set'); const a = forgeProRun(v, 'fillHole'); const filled = v.poly.f.length;
          v.setSelMode('vert'); v.selectItems('vert', [0, 1], 'set'); const nv = v.poly.v.length; forgeProRun(v, 'mergeCenter');
          return { holed, filled, nv, nv2: v.poly.v.length, hist: forgeModel.hist ? forgeModel.hist.length : 0 }; }""")
        check("Fill Hole closes the hole a deleted face left; Merge to Center joins two vertices", r["filled"] == r["holed"] + 1
              and r["nv2"] == r["nv"] - 1, r)
        real = [e for e in errors if "favicon" not in e]
        check("no page errors", not real, real[:5])
        await browser.close()


asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
