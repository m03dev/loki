"""Lab > Storage in LOKI's real window (app/ui/storage_view.js), the engine stubbed: how much LOKI uses against its
budget, where the space goes, what can go with why and how much, ticking a category and Clean up posting exactly those
ids with the plan's id, the trash with Restore. Skips cleanly without a browser.

    python tests/test_storage_ui.py
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
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright\n\n0 passed, 0 failed")
    sys.exit(0)

ITEMS = [{"id": "w1", "category": "worktrees", "path": "D:/loki/harness_data/worktrees/aaaa", "rel": "", "size": 80_000_000, "why": "improve job aaaa is done", "action": "delete"},
         {"id": "w2", "category": "worktrees", "path": "D:/loki/harness_data/worktrees/bbbb", "rel": "", "size": 79_000_000, "why": "improve job bbbb is done", "action": "delete"},
         {"id": "j1", "category": "agent_junk", "path": "C:/Home/node_modules", "rel": "node_modules", "size": 210_000_000, "why": "node_modules that an agent built in the workspace", "action": "delete"},
         {"id": "d1", "category": "drafts", "path": "C:/Home/images/x.png", "rel": "images/x.png", "size": 120_000, "why": "a standing goal made it 9 days ago and nobody kept it", "action": "trash"}]
CATS = {"worktrees": {"count": 2, "size": 159_000_000, "label": "LOKI's code for finished improve jobs", "kind": "regenerable", "when": "safe"},
        "agent_junk": {"count": 1, "size": 210_000_000, "label": "build leftovers agents made (node_modules, dist, logs)", "kind": "regenerable", "when": "safe"},
        "drafts": {"count": 1, "size": 120_000, "label": "what standing goals and tests made", "kind": "yours", "when": "budget"}}
DATA = {"ok": True, "usage": {"areas": [{"id": "worktrees", "label": "Code copies for improve jobs", "path": "D:/loki/harness_data/worktrees", "size": 3_000_000_000},
                                        {"id": "ws:node_modules", "label": "node_modules an agent installed", "path": "C:/Home/node_modules", "size": 210_000_000}],
                              "total": 3_400_000_000, "free": 40_000_000_000, "disk": 1_000_000_000_000, "budget": 20_000_000_000,
                              "min_free": 25_000_000_000, "auto": "budget"},
        "plan": {"id": "plan123", "items": ITEMS, "categories": CATS, "frees": sum(i["size"] for i in ITEMS)},
        "trash": [{"batch": "20261027-0830", "items": 3, "size": 2_000_000, "t": time.time()}]}
POSTS: list = []


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP: no Chromium (%s)" % str(exc)[:100])
            return
        page = await browser.new_page(viewport={"width": 1300, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8895", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                ct = "text/javascript" if bare.endswith(".js") else None
                return await r.fulfill(path=str(UI / bare[4:]), **({"content_type": ct} if ct else {}))
            if bare == "/storage":
                return await r.fulfill(json=DATA)
            if bare.startswith("/storage/"):
                POSTS.append((bare, json.loads(r.request.post_data or "{}")))
                if bare == "/storage/clean":
                    return await r.fulfill(json={"ok": True, "removed": 3, "freed": 369_000_000, "batch": "", "errors": []})
                return await r.fulfill(json={"ok": True, "restored": 3, "errors": []})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8895/**", route)
        await page.goto("http://127.0.0.1:8895/#token=t")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("localStorage.setItem('loki-studio-view', 'storage'); LokiModeBar.go('render')")
        await page.wait_for_selector(".st-title", timeout=8000)
        title = await E("document.querySelector('.st-title').textContent")
        check("it says how much LOKI uses against its budget", "3.4 GB" in title and "20.0 GB" in title, title)
        check("where the space goes, biggest first", (await E("document.querySelector('.st-area .st-a-name').textContent")).startswith("Code copies"))
        cats = await E("[...document.querySelectorAll('.st-cat-name')].map(n => n.textContent)")
        check("what can go, by kind", len(cats) == 3 and any("node_modules" in c for c in cats), cats)
        check("... each with why", "nobody kept it" in await E("document.body.textContent"))
        check("... and what happens to it (deleted, or the trash first)", "to the trash first" in await E("document.body.textContent"))
        check("nothing is ticked until you tick it", await E("document.getElementById('st-go').disabled"))
        await page.click(".st-cat:nth-of-type(1) .st-cat-sum input")
        await page.wait_for_timeout(150)
        label = await E("document.getElementById('st-go').textContent")
        check("ticking a kind says how much it frees", "Clean up 2" in label and "159 MB" in label, label)
        await page.click("#st-go")
        await page.wait_for_timeout(300)
        posted = [b for u, b in POSTS if u == "/storage/clean"]
        check("Clean up runs exactly what was ticked, with the plan's id", posted and posted[-1] == {"plan": "plan123", "ids": ["w1", "w2"]}, posted)
        check("... and says what it freed", "Freed 369 MB" in await E("document.querySelector('.st-say').textContent"))
        await page.click(".st-area button:has-text('Restore')")
        await page.wait_for_timeout(300)
        check("the trash can be restored", ("/storage/restore", {"batch": "20261027-0830"}) in POSTS, POSTS)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 55))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
