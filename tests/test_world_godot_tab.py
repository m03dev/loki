"""The World tab IS the Godot game (owner 2026-10-18: "loki world wasnt build in godot where is it").

    python tests/test_world_godot_tab.py      (< 60 s; skips without Playwright + Chromium or without the web build)

LOKI's window, served from app/ui like the real app, opens the World tab: the exported Godot build
(app/ui/world_godot/, engine committed gzipped) starts in a frame laid over the World panel, reports ready, and
the old JavaScript world's own Join world / Edit character buttons are not shown on top of it.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
WG = UI / "world_godot"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


check("the web build is committed (page, script, game pack, gzipped engine)",
      all((WG / n).is_file() for n in ("index.html", "index.js", "index.pck", "index.wasm.gz", "boot.js", "host.js")))
try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright\n\n%d passed, 0 failed" % len(PASS))
    sys.exit(0 if not FAIL else 1)

API = {"/settings/general": {"ok": True, "values": {"LOKI_WORLD_ENGINE": "godot", "LOKI_WORLD": "background"}},
       "/health": {"ok": True, "service": "loki", "mode": "build", "model": "fake"},
       "/world": {"ok": True, "self": {"name": "test-mac", "os": "Darwin"}, "agents": [], "machines": []},
       "/character": {"ok": True, "character": {"name": "Mohamed", "role": "builder"}}}   # a character made before


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
        try:
            b = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            print("SKIP: no Chromium (%s)" % str(exc)[:100])
            return
        ctx = await b.new_context(viewport={"width": 1200, "height": 760}, bypass_csp=True)
        pg = await ctx.new_page()
        errors, world_msgs = [], []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        if os.getenv("LOKI_DEBUG"):
            pg.on("console", lambda m: print("   console:", m.type, m.text[:160])); pg.on("request", lambda r: print("   req", r.url.split("8897")[-1][:60]) if "world" in r.url or "settings" in r.url else None)

        async def route(r):
            path = r.request.url.split("8897", 1)[1].split("#")[0].split("?")[0]
            if path == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if path.startswith("/ui/"):
                f = UI / path[4:]
                if f.is_file():
                    return await r.fulfill(path=str(f))
                gz = Path(str(f) + ".gz")
                if path.endswith(".wasm") and gz.is_file():
                    # the engine sends index.wasm.gz with Content-Encoding: gzip (tests/test_godot_world.py checks
                    # that over a real socket); Playwright's fake response is not decoded, so unpack it here
                    return await r.fulfill(body=gzip.decompress(gz.read_bytes()), headers={"Content-Type": "application/wasm"})
                return await r.fulfill(status=404, json={"ok": False})
            return await r.fulfill(json=API.get(path, {"ok": True}))

        await pg.route("http://127.0.0.1:8897/**", route)
        if os.getenv("LOKI_DEBUG"):
            await pg.add_init_script("""(() => { const rm = Element.prototype.remove; Element.prototype.remove = function () {
              if (this.tagName === 'IFRAME') console.log('IFRAME REMOVED ' + new Error().stack.replace(/\\n/g, ' | ').slice(0, 400));
              return rm.call(this); }; window.addEventListener('message', (e) => console.log('MSG ' + JSON.stringify(e.data) + ' t=' + Math.round(performance.now()))); })()""")
        await pg.goto("http://127.0.0.1:8897/#token=t")
        await pg.wait_for_function("window.LOKI_READY === true", timeout=30000)
        if os.getenv("LOKI_DEBUG"):
            await pg.wait_for_timeout(4000)
            print("   DEBUG", await pg.evaluate("({ws: typeof World, engine: World.engine, wg: typeof window.WorldGodot, after: typeof window.afterStart, frames: document.querySelectorAll('iframe').length, scripts: [...document.scripts].map(s => s.src.split('/').pop()).filter(x => /world|host/.test(x))})"))
        await pg.click("#mode-world")
        try:
            await pg.wait_for_function("(() => { const f = document.querySelector('iframe.world-godot');"
                                       " return f && f.style.display === 'block' && f.offsetWidth > 300; })()", timeout=30000)
            shown = True
        except Exception:  # noqa: BLE001
            shown = False
        check("the World tab shows the Godot game in a frame over the panel", shown,
              await pg.evaluate("({engine: World.engine, frame: !!document.querySelector('iframe.world-godot')})"))
        box = await pg.evaluate("""() => { const f = document.querySelector('iframe.world-godot'),
            p = document.querySelector('[data-panel="world"] .world-frame'); if (!f || !p) return null;
            const a = f.getBoundingClientRect(), c = p.getBoundingClientRect();
            return [Math.round(a.left - c.left), Math.round(a.top - c.top), Math.round(a.width - c.width), Math.round(a.height - c.height)]; }""")
        check("laid exactly over the World panel's box", box == [0, 0, 0, 0], box)
        game = pg.frame_locator("iframe.world-godot")
        try:
            await pg.wait_for_function("(() => { const f = document.querySelector('iframe.world-godot');"
                                       " const c = f && f.contentDocument && f.contentDocument.getElementById('canvas');"
                                       " return c && c.width > 100; })()", timeout=40000)
            started = True
        except Exception:  # noqa: BLE001
            started = False
        check("the Godot engine starts in it (canvas sized)", started)
        hidden = await pg.evaluate("""() => [...document.querySelectorAll('[data-panel="world"] button')]
            .filter((x) => x.offsetParent && /Join world|Edit character/.test(x.textContent)).length""")
        check("the old JavaScript world's Join world / Edit character are not laid over the Godot game", hidden == 0, hidden)
        if os.getenv("LOKI_SHOT"):
            await pg.wait_for_timeout(8000)
            await pg.screenshot(path=os.getenv("LOKI_SHOT"))
        # an AudioWorklet's module is fetched outside Playwright's routing here, so it cannot load in this harness;
        # through the real engine (engine/loki_bridge.py serving app/ui) it loads (checked 2026-10-18)
        errors = [e for e in errors if "worklet" not in e.lower()]
        await pg.evaluate("window.LokiCharacter.open({ edit: true })")      # Edit character over the World tab
        await pg.wait_for_timeout(1500)
        r = await pg.evaluate("""() => { const f = document.querySelector('iframe.world-godot');
            return { creator: window.LokiCharacter.isOpen(), frameShown: !!f && f.style.display === 'block' }; }""")
        check("when the character creator is open, the game frame steps aside (it covered the dialog)",
              r["creator"] and not r["frameShown"], r)
        check("no page errors", not errors, errors[:3])
        await b.close()


asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
