"""Forge's component mode in headless Chromium (app/ui/forge_edit.js + forge_poly.js), with the pro keys only (owner
2026-10-19): F9 / F10 / F11 vertex / edge / face with REAL mouse events - a click picks the nearest vertex, Shift
toggles, Ctrl takes away, a dragged box takes only what you can see (X-ray, Alt+X, takes the back too), a double-click
on an edge selects its loop, Alt+click is only ever the camera - and the handles: w / e / r on the selection, dragging
the X arrow, Ctrl+Z (and the first drag after it), b soft selection pulling the neighbours, > / < / Ctrl+Shift+I, and
Delete in vertex mode taking the faces around it.
Skips without Playwright + Chromium. Well under a minute.

    python tests/test_forge_edit_ui.py
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
TMP = Path(tempfile.mkdtemp(prefix="loki-forgeedit-"))
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
            if bare.startswith("/forge/"):
                st, out, kind = call(path, r.request.post_data_buffer) if r.request.method == "POST" else call(path)
                return await r.fulfill(status=st, body=out, content_type=kind or "application/json")
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8898/**", route)
        await page.goto("http://127.0.0.1:8898/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("forgeOpen()")
        await page.wait_for_function("!!(forge.view && forge.view.showPoly && forge.view.setSelMode)", timeout=20000)
        await page.evaluate("forgeModelMode(true)")            # F8 / the Modeling Toolkit is hidden by default (the pro workspace)
        await page.evaluate("document.querySelector(\"#forge [data-prim='cube']\").click()")
        await page.evaluate("forgeModelMode(true)")
        await page.evaluate("""() => { const i = document.querySelector('#forge-model-params input'); i.value = '3'; i.dispatchEvent(new Event('input')); forge.view.frame(); }""")
        canvas = await page.eval_on_selector("#forge-view", "c => { const r = c.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
        cx, cy, cw, ch = canvas

        async def screen(vi):
            s = await page.evaluate("(i) => forge.view.project(forge.view.poly.v[i])", vi)
            return [cx + s[0], cy + s[1]]

        async def nearest_front(sign=1):   # the visible vertex nearest the canvas centre, on the side facing the camera
            return await page.evaluate("""() => { const v = forge.view, c = v.controls.object.position, r = document.getElementById('forge-view').getBoundingClientRect();
              let best = -1, bd = 1e9; v.poly.v.forEach((p, i) => { const s = v.project(p); if (!s) return;
                const toCam = Math.hypot(p[0] - c.x, p[1] - c.y, p[2] - c.z); const d = Math.hypot(s[0] - r.width / 2, s[1] - r.height / 2) + toCam * 40;
                if (d < bd) { bd = d; best = i; } }); return best; }""")

        sel = "() => ({ v: forge.view.edit.sel.v.size, e: forge.view.edit.sel.e.size, f: forge.view.edit.sel.f.size, mode: forge.view.edit.mode })"
        await page.keyboard.press("F9")
        vi = await nearest_front()
        pt = await screen(vi)
        await page.mouse.click(pt[0] + 3, pt[1] + 2)
        r = await page.evaluate(sel)
        got = await page.evaluate("[...forge.view.edit.sel.v]")
        check("F9 = vertex mode; a click picks the vertex nearest the mouse", r["mode"] == "vert" and got == [vi], (r, got, vi))
        other = await page.evaluate("(vi) => { const v = forge.view, a = v.poly.v[vi]; let best = -1, bd = 1e9; v.poly.v.forEach((p, i) => { if (i === vi) return; const d = Math.hypot(p[0]-a[0], p[1]-a[1], p[2]-a[2]); if (d < bd) { bd = d; best = i; } }); return best; }", vi)
        pt2 = await screen(other)
        await page.keyboard.down("Shift"); await page.mouse.click(pt2[0], pt2[1]); await page.keyboard.up("Shift")
        r = await page.evaluate(sel)
        check("Shift+click adds a second vertex (and the edge between them follows)", r["v"] == 2 and r["e"] == 1, r)
        await page.keyboard.down("Control"); await page.mouse.click(pt2[0], pt2[1]); await page.keyboard.up("Control")
        r = await page.evaluate(sel)
        check("Ctrl+click takes it away again", r["v"] == 1, r)
        await page.mouse.click(cx + 8, cy + ch - 8)
        r = await page.evaluate(sel)
        check("a click on nothing deselects", r["v"] == 0, r)

        total = await page.evaluate("forge.view.poly.v.length")
        await page.mouse.move(cx + 5, cy + 5); await page.mouse.down(); await page.mouse.move(cx + cw / 2, cy + ch / 2, steps=4)
        await page.mouse.move(cx + cw - 5, cy + ch - 5, steps=4)
        mq = await page.evaluate("() => !document.querySelector('#forge-stage .forge-marquee').hidden")
        await page.mouse.up()
        r = await page.evaluate(sel)
        check("a dragged box shows the marquee and takes only the vertices you can see", mq and 0 < r["v"] < total, (mq, r, total))
        visible = r["v"]
        await page.keyboard.press("Alt+x")
        await page.mouse.move(cx + 5, cy + 5); await page.mouse.down(); await page.mouse.move(cx + cw - 5, cy + ch - 5, steps=6); await page.mouse.up()
        r = await page.evaluate(sel)
        check("X-ray (Alt+X): the same box takes the back too - every vertex", r["v"] == total and visible < total, (r, total))
        await page.keyboard.press("Alt+x")
        await page.keyboard.down("Control")
        await page.mouse.move(cx + 5, cy + 5); await page.mouse.down(); await page.mouse.move(cx + cw - 5, cy + ch - 5, steps=6); await page.mouse.up()
        await page.keyboard.up("Control")
        r = await page.evaluate(sel)
        check("Ctrl+box takes the visible ones away again", r["v"] == total - visible, (r, total, visible))

        await page.keyboard.press("F11")
        await page.mouse.move(cx + 5, cy + 5); await page.mouse.down(); await page.mouse.move(cx + cw - 5, cy + ch - 5, steps=6); await page.mouse.up()
        r = await page.evaluate(sel)
        check("F11 = face mode; a box takes the visible faces (not the 54 of the whole cube)", r["mode"] == "face" and 9 <= r["f"] < 54, r)

        await page.keyboard.press("F10")
        e_pt = await page.evaluate("""() => { const v = forge.view, T = ForgePoly.topology(v.poly), c = v.controls.object.position;
          let best = null, bd = 1e9; T.edges.forEach((e, i) => { const a = v.poly.v[e.a], b = v.poly.v[e.b], m = [(a[0]+b[0])/2, (a[1]+b[1])/2, (a[2]+b[2])/2];
            if (Math.abs(Math.abs(m[0]) - 0.5) < 1e-6 || Math.abs(Math.abs(m[1]) - 0.5) < 1e-6 || Math.abs(Math.abs(m[2]) - 0.5) < 1e-6) {
              const nface = [m[0] * 2, m[1] * 2, m[2] * 2].map((x) => Math.abs(x) > 0.999 ? 1 : 0).reduce((s, x) => s + x, 0);
              if (nface !== 1) return; const d = Math.hypot(m[0]-c.x, m[1]-c.y, m[2]-c.z); if (d < bd) { bd = d; best = { i, s: v.project(m) }; } } });
          return best; }""")
        await page.mouse.dblclick(cx + e_pt["s"][0], cy + e_pt["s"][1])
        r = await page.evaluate(sel)
        check("F10 = edge mode; a double-click selects the whole edge loop (12 edges round a 3x3x3 cube)", r["mode"] == "edge" and r["e"] == 12, r)
        await page.keyboard.down("Alt"); await page.mouse.click(cx + 10, cy + 10); await page.keyboard.up("Alt")
        r2 = await page.evaluate(sel)
        check("Alt/Option + click is only the camera: it never changes the selection", r2 == r, (r, r2))

        await page.keyboard.press("F11")
        face_pt = [cx + cw / 2, cy + ch / 2]
        await page.mouse.click(face_pt[0], face_pt[1])
        await page.keyboard.press("w")
        r = await page.evaluate("() => ({ on: !!forge.view.gizmo.object, mode: forge.view.gizmo.mode, at: forge.view.gizmo.object && forge.view.gizmo.object.position.toArray(), c: ForgePoly.median(forge.view.poly, forge.view.selectedVerts()) })")
        check("w puts the move handle on the selection's middle", r["on"] and r["mode"] == "translate" and all(abs(a - b) < 1e-6 for a, b in zip(r["at"], r["c"])), r)
        await page.keyboard.press("w")
        check("...and w again keeps it (pro does not toggle the tool off)", await page.evaluate("!!forge.view.gizmo.object"))
        await page.keyboard.press("e")
        rot = await page.evaluate("forge.view.gizmo.mode")
        await page.keyboard.press("r")
        scl = await page.evaluate("forge.view.gizmo.mode")
        check("e is the rotate handle and r the scale handle on the selection", rot == "rotate" and scl == "scale", [rot, scl])
        await page.keyboard.press("w")
        # drag the handle's X arrow with the real mouse: walk out from the pivot along the screen direction of +X
        async def drag_x(dist):
            piv = await page.evaluate("() => { const v = forge.view, c = ForgePoly.median(v.poly, v.selectedVerts()); return [v.project(c), v.project([c[0] + 0.3, c[1], c[2]])]; }")
            for k in range(4, 60, 2):
                t = k / 40.0
                x = cx + piv[0][0] + (piv[1][0] - piv[0][0]) * t
                y = cy + piv[0][1] + (piv[1][1] - piv[0][1]) * t
                await page.mouse.move(x, y)
                if await page.evaluate("forge.view.gizmo.axis") == "X":
                    await page.mouse.down(); await page.mouse.move(x + dist, y, steps=5); await page.mouse.up()
                    return True
            return False
        xs0 = await page.evaluate("() => forge.view.selectedVerts().map((i) => forge.view.poly.v[i][0])")
        ok = await drag_x(60)
        xs1 = await page.evaluate("() => forge.view.selectedVerts().map((i) => forge.view.poly.v[i][0])")
        dx = [b - a for a, b in zip(xs0, xs1)]
        check("dragging the handle's X arrow moves the selected vertices along X, all together",
              ok and dx and all(abs(d - dx[0]) < 1e-6 for d in dx) and abs(dx[0]) > 0.01, (ok, dx))
        await page.keyboard.press("Control+z")
        back = await page.evaluate("() => forge.view.selectedVerts().map((i) => forge.view.poly.v[i][0])")
        check("Ctrl+Z puts it back", all(abs(a - b) < 1e-9 for a, b in zip(back, xs0)), (back, xs0))
        # b: soft selection - the neighbours follow part of the way
        t0 = await page.evaluate("() => forge.view.poly.v.map((p) => p[0])")
        ok0 = await drag_x(60)
        d_after = await page.evaluate("(before) => Math.max(...forge.view.poly.v.map((p, i) => Math.abs(p[0] - before[i])))", t0)
        check("the first handle drag right after Ctrl+Z moves too (the handle used to keep its old place)", ok0 and d_after > 0.01, (ok0, d_after))
        await page.keyboard.press("Control+z")
        await page.keyboard.press("b")
        soft_on = await page.evaluate("forge.view.edit.prop")
        before = await page.evaluate("() => forge.view.poly.v.map((p) => p[0])")
        ok = await drag_x(60)
        moved = await page.evaluate("""(before) => { const v = forge.view, sel = new Set(v.selectedVerts()); let full = 0, part = 0, d0 = null;
          v.poly.v.forEach((p, i) => { const d = p[0] - before[i]; if (sel.has(i)) { full++; d0 = d; } });
          v.poly.v.forEach((p, i) => { const d = p[0] - before[i]; if (!sel.has(i) && Math.abs(d) > 1e-6 && Math.abs(d) < Math.abs(d0) - 1e-6) part++; });
          return [full, part]; }""", before)
        check("b = soft selection: the selection moves the whole way and its neighbours part of it", soft_on and ok and moved[0] >= 1 and moved[1] >= 2, (soft_on, ok, moved))
        await page.keyboard.press("b")
        await page.keyboard.press("Control+z")

        n0 = await page.evaluate("forge.view.selected.length")
        await page.keyboard.press(">")
        n1 = await page.evaluate("forge.view.selected.length")
        await page.keyboard.press("Control+Shift+I")
        n2 = await page.evaluate("forge.view.selected.length")
        await page.keyboard.press("<")
        n3 = await page.evaluate("forge.view.selected.length")
        check("> grows, Ctrl+Shift+I inverts, < shrinks", n1 > n0 and n2 == 54 - n1 and n3 < n2, (n0, n1, n2, n3))

        await page.keyboard.press("F9")
        await page.evaluate("forge.view.selectItems('vert', [0], 'set')")
        f0 = await page.evaluate("forge.view.poly.f.length")
        k = await page.evaluate("forge.view.poly.f.filter((f) => f.includes(0)).length")
        await page.keyboard.press("Delete")
        f1 = await page.evaluate("forge.view.poly.f.length")
        # the pro rule (owner 2026-10-21): Delete on a vertex DISSOLVES it - the faces round it become one face
        check("Delete in vertex mode dissolves the vertex: the faces round it merge into one", k >= 3 and f0 - f1 == k - 1, (f0, f1, k))
        await page.keyboard.press("Control+z")

        await page.mouse.dblclick(cx + cw / 2, cy + ch / 2)
        r = await page.evaluate(sel)
        check("a double-click on a vertex selects the piece it belongs to (every vertex of the cube)", r["v"] == total, r)
        if os.getenv("LOKI_SHOT"):
            await page.keyboard.press("F11")
            await page.mouse.click(cx + cw / 2, cy + ch / 2)
            await page.screenshot(path=os.getenv("LOKI_SHOT"))
        real = [e for e in errors if "favicon" not in e]
        check("no page errors", not real, real[:5])
        await browser.close()


asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
