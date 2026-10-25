"""Forge's creature creator in headless Chromium (app/ui/forge.js + engine/anycreature.py): the body-plan form
(presets that set their own proportions and coat, 9 proportion sliders, coats, 12 colours), a real build through
the engine routes, and the rigged result playing its own Walk / Idle clips. Skips without Playwright + Chromium.
Well under a minute.

    python tests/test_forge_creature_ui.py
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
TMP = Path(tempfile.mkdtemp(prefix="loki-forgecreature-"))
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
        await page.click("#forge .forge-way[data-way='creature']")
        await page.wait_for_function("document.querySelectorAll('#forge-creature-presets button[data-preset]').length >= 6", timeout=15000)
        r = await page.evaluate("""() => ({ sliders: document.querySelectorAll('#forge-creature-sliders input[type=range]').length,
          coats: document.querySelectorAll('#forge-creature-coats [data-coat]').length,
          colours: document.querySelectorAll('#forge-creature-colors input[type=color]').length,
          vertical: [...document.querySelectorAll('#forge-creature-sliders input')].some((i) => getComputedStyle(i).writingMode.startsWith('vertical')) })""")
        check("the body plan is a form: 11 sliders (size, smooth + 9 proportions), coats and 12 colours, all horizontal",
              r["sliders"] >= 11 and r["coats"] >= 6 and r["colours"] >= 12 and not r["vertical"], r)
        await page.click("#forge-creature-presets [data-preset='deer']")
        r = await page.evaluate("""() => ({ legs: +document.getElementById('forge-cr-legs').value, neck: +document.getElementById('forge-cr-neck').value,
          coat: (document.querySelector('#forge-creature-coats .on') || {}).dataset, 
          state: forge.creature.shape.legs })""")
        check("a starter sets its own proportions and coat on the sliders (Deer: long legs and neck, the Fawn coat)",
              r["legs"] > 1.2 and r["neck"] > 1.3 and r["state"] == r["legs"] and r["coat"] and r["coat"]["coat"] == "deer", r)
        await page.click("#forge-creature-coats [data-coat='arctic']")
        r = await page.evaluate("() => [document.getElementById('forge-crc-body').value, forge.creature.colors.body, forge.creature.coat]")
        check("a coat paints every swatch at once", r[0] == r[1] and r[2] == "arctic", r)
        await page.evaluate("""() => { const i = document.getElementById('forge-cr-tail'); i.value = '1.5'; i.dispatchEvent(new Event('input')); }""")
        r = await page.evaluate("forge.creature.shape.tail")
        check("a proportion slider changes what is sent", abs(r - 1.5) < 1e-6, r)
        await page.fill("#forge-creature-name", "deer_ui")
        await page.click("#forge-make")
        await page.wait_for_function("forge.model && /deer_ui/.test(forge.model) && forge.view.anims && forge.view.anims.length", timeout=45000)
        r = await page.evaluate("() => ({ clips: forge.view.anims, bar: !document.getElementById('forge-anim').hidden, status: document.getElementById('forge-status').textContent })")
        check("the creature arrives rigged: its clips (idle, walk) and the Walk / Idle bar", "move" in r["clips"] and r["bar"], r)
        await page.click("#forge-anim [data-clip='move']")
        await page.wait_for_timeout(400)
        r = await page.evaluate("() => ({ anim: forge.view.anim, quad: forge.view.quad })")
        check("Walk plays the walk cycle (and leaves the quad view for the orbit view)", r["anim"] == "move" and not r["quad"], r)
        if os.getenv("LOKI_SHOT"):
            await page.screenshot(path=os.getenv("LOKI_SHOT"))
        await page.click("#forge-model-mode")
        r = await page.evaluate("forge.view.anim")
        check("editing (Model mode) stops the clip, so you edit the mesh, not a pose", r is None, r)
        # the Creature Editor panel (2026-10-21): a title bar that folds, floats, closes - and comes back
        r = await page.evaluate("""() => { const pane = document.querySelector('#forge .forge-pane[data-pane="creature"]');
          const out = { bar: !!pane.querySelector('.forge-cr-bar'), secs: pane.querySelectorAll('details.forge-cr-sec').length,
            who: (document.getElementById('forge-creature-who') || {}).textContent || '', make: !!document.getElementById('forge-creature-make') };
          pane.querySelector('.forge-cr-fold').click(); out.folded = pane.classList.contains('folded') && !pane.querySelector('.forge-cr-body').offsetHeight;
          pane.querySelector('.forge-cr-fold').click(); out.unfolded = !pane.classList.contains('folded');
          pane.querySelector('.forge-cr-float').click(); out.floating = pane.classList.contains('floating') && getComputedStyle(pane).position === 'absolute';
          pane.querySelector('.forge-cr-float').click(); out.docked = !pane.classList.contains('floating') && !!pane.closest('.forge-side');
          pane.querySelector('.forge-cr-close').click(); out.closed = !pane.offsetParent;
          forgeProRun(forge.view, 'winCreature'); out.back = !!pane.offsetParent && !pane.classList.contains('closed');
          return out; }""")
        check("the Creature Editor is a panel: its bar folds it, floats it over the viewport and docks it, closes it, Windows brings it back",
              r["bar"] and r["secs"] >= 6 and r["who"] and r["make"] and r["folded"] and r["unfolded"] and r["floating"]
              and r["docked"] and r["closed"] and r["back"], r)
        r = await page.evaluate("""() => { const d = document.querySelector('#forge .forge-cr-sec[data-sec="Coat"]'); d.open = false;
          return new Promise((ok) => setTimeout(() => ok(JSON.parse(localStorage.getItem('loki-forge-output-crui') || '{}').shut || []), 50)); }""")
        check("a folded section is remembered", "Coat" in r, r)
        real = [e for e in errors if "favicon" not in e]
        check("no page errors", not real, real[:5])
        await browser.close()


asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
