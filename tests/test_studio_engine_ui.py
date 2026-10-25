"""The renamed tabs (owner 2026-10-25): Studio = the render farm manager (Farm view over engine/render_farm.py, plus the
Render view - the Render Studio as before) and Engine = Godot or the Carbon Editor. Stubbed engine, under 30 s.

    python tests/test_studio_engine_ui.py
"""
from __future__ import annotations

import asyncio
import os
import sys
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

PC = "http://192.168.50.7:8188"
FARM = {"ok": True, "stats": {"online": 1, "workers": 2, "active": 1, "queued": 1, "failed": 1, "vram_free": 7e9},
        "workers": [{"url": PC, "name": "PC", "source": "added", "online": True, "gpu": "RTX 3070 Ti", "vram_total": 8e9, "vram_free": 7e9,
                     "enabled": True, "pools": ["gpu"], "busy": True, "rendering": "farm-1", "ok": 3, "failed": 1},
                    {"url": "http://127.0.0.1:8188", "name": "This computer", "source": "studio", "online": False, "why": "connection refused",
                     "enabled": True, "pools": ["gpu"], "ok": 0, "failed": 0}],
        "jobs": [{"id": "farm-1", "name": "Hero shot", "status": "active", "priority": 90, "pool": "gpu", "progress": 0.4, "worker": PC, "eta": 120,
                  "errors": [], "max_errors": 3, "attempts": ["ai-1"], "frames": 48, "workflow": "vace_render", "depends": [], "blacklist": [], "log": [[1, "started"]], "doctor": []},
                 {"id": "farm-2", "name": "Turntable", "status": "failed", "priority": 50, "pool": "gpu", "progress": 0, "worker": None, "eta": None,
                  "errors": [{"msg": "CUDA out of memory"}] * 3, "max_errors": 3, "attempts": ["ai-2"], "frames": 24, "workflow": "vace_render",
                  "depends": [], "blacklist": [PC], "log": [[1, "failed"]],
                  "doctor": [{"cause": "The GPU ran out of video memory.", "fix": "Render smaller."}]}],
        "history": [{"id": "farm-0", "name": "Test", "status": "completed", "secs": 300, "finished": 1}]}
CARBON = {"ok": True, "found": False, "exe": "", "build_dir": "/Volumes/Xero/carbon_mmo/build", "content": "/Volumes/Xero/carbon_mmo/content",
          "building": False, "running": False, "source": True, "note": "Not built on this computer yet - Build it once.", "log_tail": []}


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

        async def route(r):
            bare = r.request.url.split("8892", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if r.request.method == "POST":
                posts.append((bare, r.request.post_data))
            if bare == "/farm/status":
                return await r.fulfill(json=FARM)
            if bare == "/carbon/status":
                return await r.fulfill(json=CARBON)
            if bare == "/carbon/build":
                return await r.fulfill(json={"ok": True, "note": "Building the Carbon Editor"})
            if bare == "/godot-editor/status":
                return await r.fulfill(json={"ok": True, "projects": [], "projects_dir": "~/LOKI Projects"})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8892/**", route)
        await page.goto("http://127.0.0.1:8892/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        names = await E("[...document.querySelectorAll('.modebar-tab span')].map(s => s.textContent)")
        check("the tabs read Home, Forge, Studio, Engine", names == ["Home", "Forge", "Studio", "Engine"], names)

        await E("localStorage.removeItem('loki-studio-view'); LokiModeBar.go('render')")
        await page.wait_for_selector(".sf-view[data-view='farm']", timeout=8000)
        views = await E("[...document.querySelectorAll('.sf-view')].map(b => [b.textContent, b.getAttribute('aria-selected')])")
        check("Studio opens on the Agents view (owner 2026-10-25), Farm and Render beside it", views == [["Agents", "true"], ["Farm", "false"], ["Render", "false"]], views)
        await page.click(".sf-view[data-view='farm']")
        await page.wait_for_selector("#studio-farm .sf-jobrow", timeout=8000)
        stats = await E("[...document.querySelectorAll('#sf-stats .sf-stat')].map(s => s.textContent)")
        check("the stats strip: workers online, rendering, queued, failed, free VRAM", len(stats) == 5 and stats[0].startswith("1 / 2") and "7.0 GB" in stats[4], stats)
        rows = await E("[...document.querySelectorAll('.sf-jobrow')].map(r => r.textContent)")
        check("jobs: name, status, worker, ETA", "Hero shot" in rows[0] and "active" in rows[0] and "PC" in rows[0] and "2 min" in rows[0], rows)
        wk = await E("[...document.querySelectorAll('.sf-workrow')].map(r => r.textContent)")
        check("workers: GPU, VRAM, status (rendering / offline)", "RTX 3070 Ti" in wk[0] and "rendering" in wk[0] and "offline" in wk[1], wk)
        await page.click(".sf-jobrow:nth-of-type(3)")
        det = await E("document.getElementById('sf-detail').textContent")
        check("a failed job shows the farm doctor's cause and fix", "ran out of video memory" in det and "Render smaller" in det, det[:300])
        await page.click('.sf-jobrow:has-text("Turntable") .sf-btn:has-text("Requeue")')
        await page.wait_for_timeout(100)
        check("Requeue posts the farm action", any(b == "/farm/job" and "requeue" in (d or "") for b, d in posts), posts[-3:])
        await page.click(".sf-view[data-view='render']")
        await page.wait_for_selector("#render-studio", timeout=5000)
        check("the Render view is the Render Studio", await E("!!document.querySelector('.sf-render #render-studio') && document.getElementById('studio-farm').hidden"))
        plan = await E("""[LokiRenderStudio.speedPlan({ width: 1280, height: 720, step: 1, fps: 24, speed: 'upscale:2' }),
          LokiRenderStudio.speedPlan({ width: 1280, height: 720, step: 1, fps: 24, speed: 'interpolate:4' }),
          LokiRenderStudio.speedPlan({ width: 1280, height: 720, step: 1, fps: 24, speed: '' })]""")
        check("AI speed-up: half size for the 2x upscale, every 4th frame for x4 in-betweens, untouched without one",
              plan[0]["width"] == 640 and plan[0]["height"] == 360 and plan[0]["post"] == {"op": "upscale", "factor": 2}
              and plan[1]["step"] == 4 and plan[1]["fps"] == 6 and plan[1]["post"]["op"] == "interpolate" and "post" not in plan[2], plan)
        check("the AI speed-up choice is in the path tracer's settings", await E("[...document.querySelectorAll('#rs-speed option')].length") == 5)
        await page.click(".sf-view[data-view='farm']")

        await E("localStorage.removeItem('loki-engine-pick'); LokiModeBar.go('godot')")
        await page.wait_for_selector(".engine-pick .engine-tab", timeout=8000)
        tabs = await E("[...document.querySelectorAll('.engine-tab')].map(b => [b.textContent, b.getAttribute('aria-selected')])")
        check("Engine: Godot and Carbon, Godot first", tabs == [["Godot", "true"], ["Carbon", "false"]], tabs)
        await page.click(".engine-tab:has-text('Carbon')")
        await page.wait_for_timeout(300)
        txt = await E("document.querySelector('.engine-panel[data-engine=\"carbon\"]').textContent")
        check("Carbon: says it is not built yet and offers Build", "Not built" in txt and "Build" in txt, txt[:200])
        check("Carbon: Open is off until it is built", await E("document.querySelector('.engine-panel[data-engine=\"carbon\"] .send').disabled"))
        await page.click(".engine-panel[data-engine='carbon'] button:has-text('Build')")
        await page.wait_for_timeout(150)
        check("Build asks the engine to build (and open after)", any(b == "/carbon/build" and '"open":true' in (d or "") for b, d in posts), posts[-2:])
        check("the choice is remembered", await E("localStorage.getItem('loki-engine-pick')") == "carbon")
        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
