"""Home's live view (app/ui/home_live.js; owner 2026-10-25: "what happened to my live view in the home page i still
want to see stuff"): Home shows the agents at work right now on every machine - what, where, the stage, the last line -
and the machines; a click opens Studio > Agents; nobody working: one line with the machines and Make. Stubbed engine.
Under a minute.

    python tests/test_home_live_ui.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
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

KINDS = [{"id": k, "label": l, "folder": f} for k, l, f in (("art", "Art", "Art"), ("painting", "Painting", "Paintings"), ("3d", "3D model", "3D Models"),
         ("comic", "Comic book", "Comics"), ("novel", "Novel", "Novels"), ("website", "Website", "Websites"), ("game", "Game", "Games"))]
TWO = {"ok": True, "machine": "mac", "hint": "", "kinds": KINDS, "stats": {"working": 2},
       "machines": [{"name": "mac", "self": True, "ok": True, "os": "Darwin", "working": 1},
                    {"name": "pc", "self": False, "ok": True, "os": "Windows", "working": 1, "ms": 14}],
       "agents": [{"id": "job-a1", "name": "Loki agent", "state": "working", "status": "working", "task": "Comic book: Robot Painter",
                   "machine": "mac", "stage": "build", "last_message": "Drawing page 2, panel 3", "since": time.time() - 300,
                   "job": "a1", "kind": "comic", "workspace": "/Users/m/LOKI Projects/Comics/robot-painter", "can_stop": True},
                  {"id": "job-p1", "name": "Builder", "state": "working", "status": "working", "task": "Art: castle at dusk",
                   "machine": "pc", "remote": True, "job": "p1", "kind": "art", "folder": "castle", "can_stop": True,
                   "last_message": "Round 2 of 3"}]}
ONE = {**TWO, "machines": TWO["machines"][:1], "agents": [], "hint": "Only this computer is linked. ... link code ..."}


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1300, "height": 860})
        errors, posts = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        state = {"view": TWO}

        async def route(r):
            bare = r.request.url.split("8893", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if r.request.method == "POST":
                posts.append((bare, json.loads(r.request.post_data or "{}")))
            if bare == "/studio/agents":
                return await r.fulfill(json=state["view"])
            if bare == "/studio/make":
                return await r.fulfill(json={"ok": True, "machine": "pc", "job": {"id": "p9"}})
            if bare == "/studio/agents/stop":
                return await r.fulfill(json={"ok": True})
            if bare == "/peers/link":
                return await r.fulfill(json={"ok": True, "name": "pc"})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8893/**", route)
        await page.goto("http://127.0.0.1:8893/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await page.wait_for_selector("#home-livewall .hl-agent", timeout=10000)
        info = await E("""(() => { const w = document.getElementById('home-livewall'), hub = document.getElementById('home-hub');
          const r = w.getBoundingClientRect(); return { inHub: hub.contains(w), shown: r.width > 0 && r.height > 0,
          title: w.querySelector('.hl-title').textContent, machines: w.querySelector('.hl-machines').textContent,
          tiles: [...w.querySelectorAll('.hl-agent')].map((t) => [t.dataset.machine, t.textContent]) }; })()""")
        check("Home shows the live view in the hub, on screen", info["inHub"] and info["shown"], info)
        check("... '2 agents working', and both machines", info["title"] == "2 agents working" and "mac" in info["machines"] and "pc" in info["machines"], info)
        check("... each agent: what, which machine, the stage, its last line", len(info["tiles"]) == 2 and info["tiles"][0][0] == "mac"
              and "Robot Painter" in info["tiles"][0][1] and "build" in info["tiles"][0][1] and "panel 3" in info["tiles"][0][1]
              and info["tiles"][1][0] == "pc" and "castle" in info["tiles"][1][1], info["tiles"])
        await page.click("#home-livewall .hl-agent[data-machine='pc']")
        await page.wait_for_selector("#sa-agents .sa-card", timeout=8000)
        check("a click opens Studio on Agents", await E("document.querySelector(\".sf-view[data-view='agents']\").getAttribute('aria-selected')") == "true")
        state["view"] = ONE
        await page.set_viewport_size({"width": 1900, "height": 900})   # a wide Home pane: the idle line shows
        await E("LokiModeBar.go('loki')"); await page.wait_for_timeout(200)
        await E("LokiHomeLive.tick()"); await page.wait_for_timeout(400)
        idle = await E("(() => { const w = document.getElementById('home-livewall'); return [w.classList.contains('idle'), w.textContent]; })()")
        check("nobody working: one calm line - Live, the machine, Make something, how to link the other", idle[0] and "Make something" in idle[1]
              and "mac" in idle[1] and "link the other in Studio > Agents" in idle[1], idle)
        check("... and it sits in the header row (no extra height)", await E("document.getElementById('home-livewall').parentNode.classList.contains('home-head')"))
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
