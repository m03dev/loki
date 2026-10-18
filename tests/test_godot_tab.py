"""The Godot tab drives the REAL Godot editor (owner 2026-10-18: "the web godot is of no help to us").

    python tests/test_godot_tab.py      (< 30 s; skips without Playwright + Chromium)

LOKI World is picked first and opens in the Godot app; the live link shows the linked editor and what each agent does
in it; "Send to the agents" starts a background agent that works in the live editor (godot_editor); plugins from the
Asset Library are listed and added; no web editor anywhere in the tab.
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
    print("SKIP: no Playwright\n\n0 passed, 0 failed")
    sys.exit(0)

NOW = time.time()
API = {
    "/godot-editor/status": {"ok": True, "projects": [{"name": "home", "label": "Home"}, {"name": "loki-world", "label": "LOKI World"}],
                             "native": "/Applications/Godot.app/Contents/MacOS/Godot", "projects_dir": "~/LOKI Projects"},
    "/api/godot/editors": {"ok": True, "editors": [],     # filled below from a REAL hub's summary (studio_godot.Editor)
                           "activity": {"job-7f3a": {"action": "add_node", "detail": "add node Lighthouse", "t": NOW - 5}}},
}
posts = []
sys.path.insert(0, str(REPO / "studio"))
import studio_godot  # noqa: E402
_hub = studio_godot.GodotHub()
_eid = _hub.hello({"project_path": "/x/game/loki-world", "project_name": "LOKI World", "godot_version": "4.8.0"})["editor"]
_hub.event(_eid, "state", {"edited_scene": "res://scenes/main.tscn", "playing": True})
API["/api/godot/editors"]["editors"] = _hub.connected()


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            b = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP: no Chromium (%s)" % str(exc)[:100])
            return
        ctx = await b.new_context(viewport={"width": 1200, "height": 800}, bypass_csp=True)
        pg = await ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            path = r.request.url.split("8896", 1)[1].split("#")[0].split("?")[0]
            if path == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if path.startswith("/ui/") and path.endswith(".wasm"):
                gz = UI / (path[4:] + ".gz")   # committed gzipped; the engine sends it with Content-Encoding
                if gz.is_file():
                    import gzip
                    return await r.fulfill(body=gzip.decompress(gz.read_bytes()), headers={"Content-Type": "application/wasm"})
            if path.startswith("/ui/") and (UI / path[4:]).is_file():
                return await r.fulfill(path=str(UI / path[4:]))
            body = r.request.post_data
            if r.request.method == "POST":
                posts.append((path, json.loads(body or "{}")))
            if path == "/api/godot/call":
                data = json.loads(body or "{}")
                if data.get("action") == "plugins":
                    return await r.fulfill(json={"ok": True, "installed": ["loki_studio", "dialogue_manager", "terrain3d"],
                                                 "manifest": [{"name": "Dialogue Manager", "version": "3.4", "license": "MIT",
                                                               "addons": ["dialogue_manager"]}]})
                if data.get("action") == "install_plugin":
                    return await r.fulfill(json={"ok": True, "installed": {"name": "Phantom Camera", "version": "0.8"}, "next": "enable it"})
            if path == "/jobs" and r.request.method == "POST":
                return await r.fulfill(json={"ok": True, "id": "job-new"})
            if path == "/godot-editor/native":
                return await r.fulfill(json={"ok": True, "note": "Godot is opening loki-world with the LOKI Studio plugin."})
            return await r.fulfill(json=API.get(path, {"ok": True}))

        await pg.route("http://127.0.0.1:8896/**", route)
        await pg.goto("http://127.0.0.1:8896/#token=t")
        await pg.wait_for_function("window.LOKI_READY === true", timeout=30000)
        await pg.click("#mode-godot")
        await pg.wait_for_selector(".godot-editor-row", timeout=10000)
        pane = '[data-mode-pane="godot"]'
        check("LOKI World is picked first", await pg.eval_on_selector(pane + " select", "s => s.value") == "loki-world")
        text = await pg.inner_text(pane)
        check("the live link shows the linked Godot editor", "Godot 4.8.0 - LOKI World - editing res://scenes/main.tscn - the game is running" in text, text[:300])
        check("...and what each agent is doing in it", "Agent 7f3a: add node Lighthouse" in text, text[:500])
        check("plugins: the recorded ones, and the ones only on this machine", "Dialogue Manager 3.4 (MIT)" in text and "terrain3d" in text, text)
        check("no web editor in the tab", "web editor" not in text.lower() and not await pg.query_selector(pane + " iframe"))
        await pg.click(pane + " button:has-text('Open in Godot')")
        await pg.wait_for_timeout(300)
        check("Open in Godot opens the project in the Godot app", ("/godot-editor/native", {"name": "loki-world"}) in posts, posts)
        await pg.fill(pane + " .godot-ask textarea", "add a lighthouse on the east cliff")
        await pg.click(pane + " .godot-ask button")
        await pg.wait_for_timeout(300)
        job = next((d for pth, d in posts if pth == "/jobs"), {})
        check("Send to the agents starts an agent that works in the live editor", "godot_editor" in job.get("prompt", "")
              and "add a lighthouse on the east cliff" in job.get("prompt", "") and job.get("isolate") is False, job)
        await pg.fill(pane + " .godot-plugin-add input", "2490")
        await pg.click(pane + " .godot-plugin-add button[type=submit]")
        await pg.wait_for_timeout(300)
        check("a plugin is added by its Asset Library number", any(pth == "/api/godot/call" and d.get("action") == "install_plugin"
                                                                  and d["args"]["asset_id"] == "2490" for pth, d in posts))
        if os.getenv("LOKI_SHOT"):
            await pg.screenshot(path=os.getenv("LOKI_SHOT"))
        check("no page errors", not errors, errors[:3])
        await b.close()


asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
