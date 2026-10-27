"""Studio > Agents in a real window (app/ui/studio_agents.js; owner 2026-10-25: "a place i can see my agents working as
well and other machines ... some sort of control"): Studio opens on Agents; every machine shows (this Mac, the PC,
online / offline); every agent at work with its machine, stage, last line and a Stop; Stop on the PC's agent posts
machine=pc; Make posts the kind, the brief and the machine; with one machine, a box to paste the link code. Stubbed
engine. Under a minute.

    python tests/test_studio_agents_ui.py
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
        await E("localStorage.removeItem('loki-studio-view'); LokiModeBar.go('render', {view: 'agents'})")   # Lab opens on Tasks now
        await page.wait_for_selector("#sa-agents .sa-card", timeout=8000)
        check("Studio opens on Agents", await E("document.querySelector(\".sf-view[data-view='agents']\").getAttribute('aria-selected')") == "true")
        ms = await E("[...document.querySelectorAll('.sa-machine')].map((m) => [m.dataset.machine, m.classList.contains('on'), m.textContent])")
        check("both machines show: this Mac and the PC, online, with how many are working", [m[0] for m in ms] == ["mac", "pc"]
              and all(m[1] for m in ms) and "this computer" in ms[0][2] and "Windows" in ms[1][2] and "1 working" in ms[1][2], ms)
        cards = await E("[...document.querySelectorAll('.sa-card')].map((c) => [c.dataset.machine, c.textContent])")
        check("every agent at work: what, which machine, the stage, the last line", len(cards) == 2 and cards[0][0] == "mac"
              and "Robot Painter" in cards[0][1] and "stage: build" in cards[0][1] and "panel 3" in cards[0][1]
              and cards[1][0] == "pc" and "on pc" in cards[1][1] and "castle" in cards[1][1], cards)
        await page.click(".sa-card[data-machine='pc'] .sa-btn:has-text('Stop')")
        await page.wait_for_timeout(150)
        stop = [b for u, b in posts if u == "/studio/agents/stop"]
        check("Stop on the PC's agent asks the PC (machine=pc, job p1)", stop and stop[-1] == {"machine": "pc", "job": "p1"}, stop)
        await page.click(".sa-card[data-machine='mac'] .sa-btn:has-text('Stop')")
        await page.wait_for_timeout(150)
        stop = [b for u, b in posts if u == "/studio/agents/stop"]
        check("Stop on this Mac's agent stops it here (no machine)", stop[-1] == {"machine": "", "job": "a1"}, stop)
        kinds = await E("[...document.querySelectorAll('.sa-kind')].map((b) => b.textContent)")
        check("Make offers Art, Painting, 3D model, Comic book, Novel, Website, Game", kinds == ["Art", "Painting", "3D model", "Comic book", "Novel", "Website", "Game"], kinds)
        await page.click(".sa-kind[data-kind='novel']")
        await page.fill("#sa-brief", "a mystery novel set on a frozen space station")
        await page.fill("#sa-name", "Cold Orbit")
        await page.select_option("#sa-where", "pc")
        await page.click("#sa-go")
        await page.wait_for_timeout(150)
        mk = [b for u, b in posts if u == "/studio/make"]
        check("Make posts the kind, the brief, the name and the machine", mk and mk[-1] == {"kind": "novel", "brief": "a mystery novel set on a frozen space station",
              "name": "Cold Orbit", "machine": "pc"}, mk)
        check("... and says where it started", "pc" in await E("document.getElementById('sa-say').textContent"))
        await page.click("#sa-go")
        await page.wait_for_timeout(100)
        check("Make with no brief asks for one (nothing posted)", len([1 for u, _ in posts if u == "/studio/make"]) == 1
              and "first" in await E("document.getElementById('sa-say').textContent"))
        typed = await E("(() => { const b = document.getElementById('sa-brief'); b.focus(); return document.activeElement === b; })()")
        await page.keyboard.type("w")
        check("typing in the brief never fires app shortcuts (W stays a letter)", typed and await E("document.getElementById('sa-brief').value") == "w")
        # one machine: the link box
        state["view"] = ONE
        await E("LokiStudioAgents.refresh()"); await page.wait_for_timeout(300)
        check("only one machine: the hint and a box for the link code", await E("!!document.querySelector('#sa-link .sa-code')")
              and "link code" in await E("document.getElementById('sa-link').textContent"))
        await page.fill("#sa-link .sa-code", "LOKI-LINK-abc")
        await page.click("#sa-link .sa-btn:has-text('Link')")
        await page.wait_for_timeout(150)
        check("Link posts the code to /peers/link", [b for u, b in posts if u == "/peers/link"][-1:] == [{"code": "LOKI-LINK-abc"}])
        check("nobody working: it says so and points to Make", "Nobody is working" in await E("document.getElementById('sa-agents').textContent"))
        over = await E("""(() => { const els = [...document.querySelectorAll('.sa-make, .sa-machines, .sa-agents')].map((e) => e.getBoundingClientRect());
          for (let i = 0; i < els.length - 1; i++) if (els[i].bottom > els[i + 1].top + 1) return true; return document.documentElement.scrollWidth > innerWidth + 1; })()""")
        check("nothing overlaps, no sideways scroll", not over)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
