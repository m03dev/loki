"""Render Studio's Render View behaves like a 3D app's: its own File / View / Render menu bar over the view, a
batch-render progress panel (name, step, %, elapsed, Cancel) while a job runs, Keep image for comparison, and
Fit / Actual size. Headless Chromium against a stubbed /render API. Under a minute.

    python tests/test_render_studio_maya_ui.py
"""
from __future__ import annotations

import asyncio
import json
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

WF = json.loads((REPO / "engine" / "ai_renderer_workflows" / "vace_render.json").read_text(encoding="utf-8"))
RUNNING = {"job": "ai-20261021-1-ab", "name": "Shot 1", "kind": "ai", "status": "running", "progress": 0.4,
           "last": "running on pc: sampling 8/20"}


def status(jobs):
    return {"ok": True, "settings": {"url": "http://192.168.1.50:8188", "consent_remote": False, "timeout_s": 3600,
                                     "url_shown": "http://192.168.1.50:8188", "where": {"place": "peer", "own": True, "note": "LOKI's linked machine 'pc'"}},
            "workflows": [{k: WF.get(k) for k in ("name", "label", "params", "uploads", "constraints", "custom_nodes")} | {"models": WF["models"]}],
            "jobs": jobs, "active": []}


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
        errors, posted = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
        jobs = [dict(RUNNING)]

        async def route(r):
            bare = r.request.url.split("8895", 1)[1].split("#")[0]
            path = bare.split("?")[0]
            if path == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if path.startswith("/ui/") and (UI / path[4:]).is_file():
                return await r.fulfill(path=str(UI / path[4:]))
            if path == "/render/status":
                return await r.fulfill(json=status(jobs))
            if path in ("/render/cancel", "/render/preflight", "/render/presets", "/render/retry"):
                try:
                    posted.append((path, json.loads(r.request.post_data or "{}")))
                except ValueError:
                    posted.append((path, {}))
                return await r.fulfill(json={"ok": True, "report": {"ok": True, "blockers": [], "warnings": [], "checked": []}})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8895/**", route)
        await page.goto("http://127.0.0.1:8895/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await page.click("#mode-render")
        await page.wait_for_selector("#render-studio", timeout=8000)
        await page.wait_for_timeout(400)

        # ---- the Render View's menu bar
        menus = await E("[...document.querySelectorAll('#rs-viewbar .rs-menubtn')].map((b) => b.dataset.menu)")
        check("the view has its own File / View / Render menu bar", menus == ["file", "view", "render"], menus)
        open_now = await E("[...document.querySelectorAll('#rs-viewbar .rs-menulist')].map((l) => l.hidden)")
        check("every menu starts closed", all(open_now), open_now)
        await page.click("#rs-menu-file .rs-menubtn")
        await page.wait_for_timeout(80)
        one = await E("[...document.querySelectorAll('#rs-viewbar .rs-menulist')].map((l) => l.hidden)")
        check("clicking a menu opens just that one", one == [False, True, True], one)
        await page.click("#rs-menu-render .rs-menubtn")
        await page.wait_for_timeout(80)
        two = await E("[...document.querySelectorAll('#rs-viewbar .rs-menulist')].map((l) => l.hidden)")
        check("opening another closes the first (one menu at a time)", two == [True, True, False], two)
        await page.click("#rs-stage")
        await page.wait_for_timeout(80)
        check("a click on the view closes the menus", await E("[...document.querySelectorAll('#rs-viewbar .rs-menulist')].every((l) => l.hidden)"))

        items = await E("""() => { const o = {}; for (const l of document.querySelectorAll('#rs-viewbar .rs-menulist'))
          o[l.dataset.for] = [...l.querySelectorAll('.rs-menuitem')].map((m) => m.dataset.kind); return o; }""")
        check("File offers Save image, Reload and Close the view",
              items.get("file") == ["save", "reload", "close"], items.get("file"))
        check("View offers Fit, Actual size, Keep image and letting it go",
              items.get("view") == ["fit", "actual", "keep", "unkeep"], items.get("view"))
        check("Render offers Render, Preflight, Cancel and Retry",
              items.get("render") == ["render", "preflight", "cancel", "retry"], items.get("render"))

        # ---- the batch-render progress panel
        prog = await E("""() => { const el = document.getElementById('rs-progress');
          return { hidden: el.hidden, name: document.getElementById('rs-progress-name').textContent,
                   pct: document.getElementById('rs-progress-pct').textContent,
                   bar: document.getElementById('rs-progress-bar').style.width,
                   last: document.getElementById('rs-progress-last').textContent,
                   cancel: !!document.getElementById('rs-progress-cancel') }; }""")
        check("a running job raises the progress panel, with its name, step and percentage",
              not prog["hidden"] and "Shot 1" in prog["name"] and prog["pct"] == "40%" and prog["bar"] == "40%" and "sampling 8/20" in prog["last"], prog)
        check("the panel carries a Cancel button", prog["cancel"])

        # ---- Render > Cancel cancels that job
        await page.click("#rs-menu-render .rs-menubtn")
        await page.wait_for_timeout(80)
        await page.click('#rs-menu-render .rs-menuitem[data-kind="cancel"]')
        await page.wait_for_timeout(250)
        check("Render > Cancel asks the engine to stop the job", ("/render/cancel", {"job": RUNNING["job"]}) in posted, posted[-2:])

        # ---- the panel goes away once nothing is running
        jobs[0] = dict(RUNNING, status="succeeded", progress=1.0)
        await E("window.LokiRenderStudio.refresh()")
        await page.wait_for_timeout(300)
        check("the panel goes away when the job is done", await E("document.getElementById('rs-progress').hidden"))

        # ---- View > Fit / Actual size
        await page.click("#rs-menu-view .rs-menubtn")
        await page.wait_for_timeout(60)
        await page.click('#rs-menu-view .rs-menuitem[data-kind="actual"]')
        await page.wait_for_timeout(80)
        actual = await E("document.getElementById('rs-stage').classList.contains('rs-actual')")
        await page.click("#rs-menu-view .rs-menubtn")
        await page.wait_for_timeout(60)
        await page.click('#rs-menu-view .rs-menuitem[data-kind="fit"]')
        await page.wait_for_timeout(80)
        check("View > Actual size / Fit to window toggle how the result is shown",
              actual and not await E("document.getElementById('rs-stage').classList.contains('rs-actual')"))

        # ---- File > Save image with nothing shown says so, and does not blow up
        await E("window.LokiRenderStudio.refresh()")
        await page.wait_for_timeout(200)
        await page.click("#rs-menu-file .rs-menubtn")
        await page.wait_for_timeout(60)
        await page.click('#rs-menu-file .rs-menuitem[data-kind="save"]')
        await page.wait_for_timeout(120)
        msg = await E("document.getElementById('rs-info').textContent")
        check("File > Save image says there is nothing to save rather than failing", "nothing is shown" in msg.lower(), msg[:160])

        check("no script errors", not errors, errors[:5])
        await browser.close()


asyncio.run(asyncio.wait_for(main(), timeout=55))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
