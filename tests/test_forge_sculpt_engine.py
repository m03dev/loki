"""Forge's native sculpting engine in headless Chromium (app/ui/forge_sculpt.js + app/ui/vendor/sculpt/: the C++
engine built to WebAssembly, running in a Web Worker). Real mouse strokes go through the worker and come back as
moved vertices; a library brush, dynamic detail (more triangles under the brush), remesh, quad remesh, subdivision
levels, the matcap gallery and the wire overlay; Forge's undo and history still work; the worker alone may run
WebAssembly (its own CSP) while LOKI's pages keep UI_CSP. The engine itself: native/sculpt/wasm/test/test_engine.js
(run here too when node is installed).
Skips without Playwright + Chromium. Well under a minute.

    python tests/test_forge_sculpt_engine.py
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
TMP = Path(tempfile.mkdtemp(prefix="loki-forgesculpt-"))
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



def engine_unit():
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("  (node not installed: engine unit test skipped)")
        return
    out = subprocess.run([node, str(REPO / "native" / "sculpt" / "wasm" / "test" / "test_engine.js"), str(UI / "vendor" / "sculpt" / "sculpt.wasm")],
                         capture_output=True, text=True, timeout=50, check=False)
    lines = out.stdout.strip().splitlines()
    check("the engine: every brush kernel, undo, symmetry, dynamic detail, remesh, quad remesh, levels, paint, mask (node)",
          out.returncode == 0 and lines and lines[-1] == "ALL OK", (out.stdout[-600:], out.stderr[-300:]))


def headers():
    import http.client
    saved = (loki_bridge.UI_DIR, loki_bridge.ALLOWED_HOSTS)
    loki_bridge.UI_DIR = UI
    loki_bridge.ALLOWED_HOSTS = ("127.0.0.1:%d" % srv.server_address[1],)
    res = {}
    for path in ("/ui/vendor/sculpt/sculpt_worker.js", "/ui/forge_sculpt.js", "/ui/vendor/sculpt/sculpt.wasm"):
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        conn.request("GET", path)
        r = conn.getresponse()
        res[path] = (r.status, r.getheader("Content-Security-Policy", ""), r.getheader("Content-Type", ""))
        r.read(); conn.close()
    loki_bridge.UI_DIR, loki_bridge.ALLOWED_HOSTS = saved
    w, f, m = res["/ui/vendor/sculpt/sculpt_worker.js"], res["/ui/forge_sculpt.js"], res["/ui/vendor/sculpt/sculpt.wasm"]
    check("only the sculpt worker may compile WebAssembly; pages keep UI_CSP; the .wasm is served as application/wasm",
          w[0] == 200 and "'wasm-unsafe-eval'" in w[1] and "'unsafe-eval'" not in w[1].replace("'wasm-unsafe-eval'", "")
          and f[0] == 200 and "wasm-unsafe-eval" not in f[1] and m[0] == 200 and m[2] == "application/wasm", res)


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            print("SKIP: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        ctx = await browser.new_context(viewport={"width": 1300, "height": 860})
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

        async def route(r):
            path = r.request.url.split("8898", 1)[1].split("#")[0]
            bare = path.split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                kind = "application/wasm" if bare.endswith(".wasm") else None
                return await r.fulfill(path=str(UI / bare[4:]), **({"content_type": kind} if kind else {}))
            if bare.startswith("/forge/"):
                st, out, kind = call(path, r.request.post_data_buffer) if r.request.method == "POST" else call(path)
                return await r.fulfill(status=st, body=out, content_type=kind or "application/json")
            return await r.fulfill(json={"ok": True})

        await ctx.route("http://127.0.0.1:8898/**", route)   # the context: the worker's own fetches too
        await page.goto("http://127.0.0.1:8898/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("forgeOpen()")
        await page.wait_for_function("!!(forge.view && forge.view.showPoly)", timeout=20000)
        await page.evaluate("forgeModelMode(true)")
        await page.evaluate("document.querySelector(\"#forge [data-prim='sphere']\").click()")
        await page.evaluate("forge.view.frame()")
        if not await page.evaluate("forge.view.mode === 'sculpt'"):
            await page.evaluate("forgeMode()")
        try:
            await page.wait_for_function("window.ForgeSculpt && (window.ForgeSculpt.ok || window.ForgeSculpt.failed)", timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        st = await page.evaluate("({ ok: ForgeSculpt.ok, failed: ForgeSculpt.failed, panel: !!document.getElementById('forge-sculpt-engine'), visible: !document.getElementById('forge-sculpt-engine').hidden })")
        check("the sculpting engine loads in its worker and the Sculpting panel shows in Sculpt mode", st["ok"] and st["panel"] and st["visible"], st)
        if not st["ok"]:
            return
        canvas = await page.eval_on_selector("#forge-view", "c => { const r = c.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
        cx, cy, cw, ch = canvas
        mx, my = cx + cw / 2, cy + ch / 2
        total = "forge.view.sm.wpos.reduce((s, v) => s + Math.abs(v), 0)"
        idle = "() => !ForgeSculpt.pressed && !ForgeSculpt.openStrokes && !ForgeSculpt.busy"

        async def stroke(dx=60, dy=0, steps=8, start=(0, 0)):
            await page.mouse.move(mx + start[0], my + start[1])
            await page.mouse.down()
            await page.mouse.move(mx + start[0] + dx, my + start[1] + dy, steps=steps)
            await page.mouse.up()
            await page.wait_for_function(idle, timeout=10000)
            await page.wait_for_timeout(80)

        await page.evaluate("window.forgeHistory && window.forgeHistory.clear && window.forgeHistory.clear()")
        await page.evaluate("forge.view.brush.radius = 0.15; forgeBrush('draw')")
        before = await page.evaluate(total)
        tris0 = await page.evaluate("forge.view.sm.idx.length / 3")
        await stroke()
        after = await page.evaluate(total)
        info = await page.evaluate("({ loads: ForgeSculpt.stats.loads, updates: ForgeSculpt.stats.updates, same: ForgeSculpt.loadedSm === forge.view.sm })")
        check("a real mouse stroke runs in the engine and the moved vertices come back into Forge's mesh",
              abs(after - before) > 1e-4 and info["updates"] > 0 and info["same"], (before, after, info))
        hist = await page.evaluate("window.forgeHistory ? window.forgeHistory.list() : []")
        check("the stroke is one history step (recorded when the worker finished it)", bool(hist) and hist[0]["kind"] == "sculpt" and hist[0]["affected"] > 0, hist[:2])
        await page.evaluate("forge.view.undo()")
        undone = await page.evaluate(total)
        check("Forge's undo puts the vertices back", abs(undone - before) < 1e-3, (before, undone))
        await stroke(dx=0, dy=50)
        again = await page.evaluate(total)
        check("after an undo the next stroke starts from the undone shape (engine re-synced, not reloaded)",
              abs(again - undone) > 1e-4 and await page.evaluate("ForgeSculpt.stats.loads") == info["loads"], (undone, again))

        await page.select_option("#forge-sculpt-lib", label="Clay Strips")
        b2 = await page.evaluate(total)
        await stroke(dx=-50, dy=20)
        check("a brush from the library (Clay Strips) sculpts", abs(await page.evaluate(total) - b2) > 1e-4
              and await page.evaluate("forge.view.brush.tool === 'lib'"))
        await page.evaluate("forgeBrush('grab')")
        b3 = await page.evaluate(total)
        await stroke(dx=0, dy=-40, steps=5)
        check("Grab (the engine's Move) pulls the surface along", abs(await page.evaluate(total) - b3) > 1e-4)

        await page.evaluate("forgeBrush('draw')")
        await page.click("#forge-sculpt-dyn")
        await stroke(dx=80, dy=10, steps=10)
        tris1 = await page.evaluate("forge.view.sm.idx.length / 3")
        check("dynamic detail adds triangles where the brush works", tris1 > tris0, (tris0, tris1))
        await page.click("#forge-sculpt-dyn")

        await page.evaluate("ForgeSculpt.op('voxelRemesh', 64)")
        await page.wait_for_function(idle, timeout=20000)
        rem = await page.evaluate("({ tris: forge.view.sm.idx.length / 3, same: ForgeSculpt.loadedSm === forge.view.sm, say: document.getElementById('forge-status').textContent })")
        check("Remesh rebuilds an even surface (new mesh in Forge and the engine)", rem["tris"] > 0 and rem["tris"] != tris1 and rem["same"], rem)
        await page.evaluate("forge.view.undo()")
        check("a remesh is one undo step", await page.evaluate("forge.view.sm.idx.length / 3") == tris1)
        await page.evaluate("ForgeSculpt.op('quadRemesh', 600)")
        await page.wait_for_function(idle, timeout=30000)
        q = await page.evaluate("forge.view.sm.idx.length / 3")
        await page.evaluate("ForgeSculpt.op('divide')")
        await page.wait_for_function(idle, timeout=20000)
        lv = await page.evaluate("({ tris: forge.view.sm.idx.length / 3, label: document.getElementById('forge-sculpt-level').textContent })")
        check("quad remesh, then Divide adds a subdivision level (4x the faces)", q > 100 and lv["tris"] >= q * 3.5 and "Level 1 / 1" in lv["label"], (q, lv))
        await page.evaluate("ForgeSculpt.op('setLevel', 0)")
        await page.wait_for_function(idle, timeout=20000)
        check("Lower level steps back to level 0", await page.evaluate("forge.view.sm.idx.length / 3") == q
              and "Level 0" in await page.evaluate("document.getElementById('forge-sculpt-level').textContent"))

        await page.click("#forge [data-matcap='red_wax']")
        await page.wait_for_function("(() => { const m = forge.view.internals.mesh; return m && m.material && m.material.isMeshMatcapMaterial; })()", timeout=5000)
        check("the matcap gallery puts a matcap on the model", True)
        await page.click("#forge [data-matcap='']")
        check("Lit goes back to the lit material", await page.evaluate("!forge.view.internals.mesh.material.isMeshMatcapMaterial"))
        n = await page.evaluate("document.querySelectorAll('#forge [data-matcap]').length")
        check("six matcaps + Lit, no more", n == 7, n)

        await page.evaluate("ForgeSculpt.op('divide')")
        await page.wait_for_function(idle, timeout=20000)
        await page.evaluate("forge.view.setLook('wire', true)")
        near = await page.evaluate("() => new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(() => { const w = forge.view.internals.mesh.children.find((c) => c.name === 'forge-wire'); ok(w ? [w.visible, w.material.opacity] : null); })))")
        await page.evaluate("forge.view.controls.object.position.multiplyScalar(12); forge.view.controls.update(); forge.view.dirty = true")
        far = await page.evaluate("() => new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(() => { const w = forge.view.internals.mesh.children.find((c) => c.name === 'forge-wire'); ok(w ? w.material.opacity : null); })))")
        check("the wire is an overlay that fades as edges crowd on screen (never solid)", near and near[0] and far is not None and far < near[1], (near, far))
        await page.evaluate("forge.view.setLook('wire', false)")
        bad = [e for e in errors if "favicon" not in e]
        check("no page errors", not bad, bad[:5])
        await browser.close()


engine_unit()
headers()
asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
