"""Lab > Tasks in LOKI's real window (app/ui/task_board.js in studio_farm.js), the engine stubbed: the first Lab view,
"Needs you" first with the reason, Finished with the answer and the pictures made, Try again now posts /tasks/retry,
requests and standing goals apart. Skips cleanly without a browser.

    python tests/test_task_board_ui.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright\n\n0 passed, 0 failed")
    sys.exit(0)
from PIL import Image  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="loki-tbui-"))
Image.new("RGB", (64, 64), (40, 160, 90)).save(TMP / "knight.png")
NOW = time.time()
BOARD = {"ok": True, "machine": "this PC", "updated": NOW, "counts": {"done": 1, "failed": 1, "running": 1, "retrying": 1},
         "rows": [
             {"id": "r1", "kind": "request", "text": "[windows] DO FIRST - area edit proof on this PC: make a knight", "status": "failed",
              "tries": 3, "max_tries": 3, "summary": "The Builder could not finish its part.", "why": "Builder: BLOCKED: The command line is too long.",
              "answer": "BLOCKED: NOT DONE", "files": [], "started": NOW - 9000, "finished": NOW - 3000, "next_try": 0},
             {"id": "r2", "kind": "request", "text": "[windows] Hunyuan3D 2.1 on this PC", "status": "retrying", "tries": 1, "max_tries": 3,
              "summary": "The Builder could not finish its part.", "why": "Builder: timed out", "answer": "", "files": [],
              "started": NOW - 2000, "finished": NOW - 600, "next_try": NOW + 600},
             {"id": "r3", "kind": "request", "text": "[windows] Make a knight picture", "status": "done", "tries": 1, "max_tries": 3,
              "summary": "Done and checked.", "why": "", "answer": "DONE: drew images/knight.png", "files": ["images/knight.png", "qa/knight.md"],
              "started": NOW - 5000, "finished": NOW - 4000, "next_try": 0},
             {"id": "always-0-1", "kind": "goal", "text": "draw a sprite", "status": "running", "tries": 1, "max_tries": 1,
              "summary": "Working - stage build.", "why": "", "answer": "", "files": [], "started": NOW - 100, "finished": 0, "next_try": 0}]}
POSTS: list = []


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP: no Chromium (%s)" % str(exc)[:100])
            return
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8895", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                ct = "text/javascript" if bare.endswith(".js") else None
                return await r.fulfill(path=str(UI / bare[4:]), **({"content_type": ct} if ct else {}))
            if bare == "/tasks/board":
                return await r.fulfill(json=BOARD)
            if bare in ("/tasks/retry", "/tasks/dismiss"):
                POSTS.append((bare, json.loads(r.request.post_data or "{}")))
                return await r.fulfill(json=BOARD)
            if bare == "/creations/images/knight.png":
                return await r.fulfill(path=str(TMP / "knight.png"), content_type="image/png")
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8895/**", route)
        await page.goto("http://127.0.0.1:8895/#token=t")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("localStorage.removeItem('loki-studio-view'); localStorage.removeItem('loki-task-board')")
        await E("LokiModeBar.go('render')")
        await page.wait_for_selector(".tb-row", timeout=8000)
        check("Lab opens on Tasks", await E("document.querySelector('.sf-view[aria-selected=true]').dataset.view") == "tasks")
        names = await E("[...document.querySelectorAll('.tb-row')].map(r => r.dataset.id)")
        check("Needs you first: the failed and the retrying requests", names == ["r1", "r2"], names)
        check("... with the reason in plain sight", "command line is too long" in await E("document.querySelector('.tb-row[data-id=r1] .tb-why').textContent"))
        check("... the request's own words, without the [windows] DO FIRST prefix",
              (await E("document.querySelector('.tb-row[data-id=r1] .tb-name').textContent")).startswith("area edit proof"))
        check("... and how many tries", "try 3 of 3" in await E("document.querySelector('.tb-row[data-id=r1] .tb-meta').textContent"))
        await page.click(".tb-row[data-id=r1] .tb-btn:has-text('Try again now')")
        await page.wait_for_timeout(300)
        check("Try again now posts /tasks/retry", POSTS and POSTS[-1] == ("/tasks/retry", {"id": "r1"}), POSTS)
        await page.click(".tb-filter:has-text('Finished')")
        await page.wait_for_timeout(200)
        check("Finished shows what got done", await E("[...document.querySelectorAll('.tb-row')].map(r => r.dataset.id)") == ["r3"])
        await page.wait_for_timeout(300)
        check("... the picture it made, as a picture",
              await E("(() => { const i = document.querySelector('.tb-row[data-id=r3] img.tb-pic'); return !!i && i.naturalWidth > 0; })()"))
        check("... and its other files by name", "qa/knight.md" in await E("document.querySelector('.tb-row[data-id=r3] .tb-files').textContent"))
        await page.click(".tb-row[data-id=r3] .tb-btn:has-text('Answer')")
        await page.wait_for_timeout(150)
        check("... and its answer on a click", "drew images/knight.png" in await E("document.querySelector('.tb-row[data-id=r3] .tb-answer').textContent"))
        await page.click(".tb-kind:has-text('Standing goals')")
        await page.click(".tb-filter:has-text('Working')")
        await page.wait_for_timeout(200)
        check("standing goals are apart from requests", await E("[...document.querySelectorAll('.tb-row')].map(r => r.dataset.id)") == ["always-0-1"])
        check("the summary line counts everything", "1 finished" in await E("document.querySelector('.tb-line').textContent"))
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 55))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
