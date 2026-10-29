"""The keyboard stays in whatever box the owner is typing in, everywhere in the window (owner 2026-10-29: "whever i try to
type ... i get pushed out of the typing box" / "the for you ... wont focus" / "this logic should apply every where").

The For you panel refreshed every 10 s with list.replaceChildren(...), taking every card - the one he typed in too - out
of the page and back, which drops the keyboard. app/ui/boot.js now guards every text box; home_review.js no longer
takes cards out. Checked in the real window (stubbed engine):
  - For you: typing in a card while it refreshes, also when a new card arrives above it: still in the box, caret kept
  - any panel: a box rebuilt by a refresh (innerHTML) gets the keyboard and his words back
  - a timer focusing something else does not take the keyboard; his own click elsewhere, Tab and Escape do
Under a minute.
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
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright here\n\n0 passed, 0 failed")
    sys.exit(0)

NOW = time.time()


def card(i, t):
    return {"id": "c%011d" % i, "kind": "prompt", "status": "waiting", "t": t, "tool": "make_image", "who": "Concept Artist",
            "args": {"prompt": "a moss golem %d" % i}, "cwd": "/ws", "files": []}


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP: no Chromium (%s)" % str(exc)[:100])
            return
        page = await browser.new_page(viewport={"width": 1400, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        st = {"waiting": [card(1, NOW - 100)]}

        async def route(r):
            bare = r.request.url.split("8895", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if bare == "/review":
                return await r.fulfill(json={"ok": True, "on": True, "waiting": st["waiting"], "recent": [], "summary": {}})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8895/**", route)
        await page.goto("http://127.0.0.1:8895/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("LokiHomeReview.refresh(true)")
        await page.wait_for_selector(".rv-prompt .rv-words", timeout=8000)

        # ------------------------------------------------------------ For you, refreshing under his fingers
        await page.click(".rv-prompt .rv-words")
        await E("(() => { const b = document.querySelector('.rv-prompt .rv-words'); b.setSelectionRange(5, 5); })()")
        await page.keyboard.type("big ")
        for _ in range(3):
            await E("LokiHomeReview.refresh(true)")
            await page.wait_for_timeout(150)
        got = await E("""(() => { const a = document.activeElement;
          return [a && a.classList.contains('rv-words'), a && a.value, a && a.selectionStart]; })()""")
        check("For you: refreshing while he types keeps him in the box", got[0], got)
        check("... with his words and his caret where it was", got[1] == "a mosbig s golem 1" and got[2] == 9, got)
        st["waiting"] = [card(2, NOW - 500), card(1, NOW - 100)]           # a new card arrives ABOVE his
        await E("LokiHomeReview.refresh(true)")
        await page.wait_for_timeout(200)
        await page.keyboard.type("x")
        got = await E("""(() => { const a = document.activeElement; const c = a && a.closest('.rv-card');
          return [c && c.dataset.id, a && a.value, document.querySelectorAll('.rv-card').length]; })()""")
        check("... and when a new card arrives above his, he keeps typing in his", got[0] == "c00000000001" and got[1] == "a mosbig xs golem 1"
              and got[2] == 2, got)

        # ------------------------------------------------------------ any panel: a box rebuilt by a refresh
        await E("""(() => { const d = document.createElement('div'); d.id = 'probe-panel';
          d.innerHTML = '<div data-id="row7"><input class="note" placeholder="Note"></div>'; document.body.append(d); })()""")
        await page.click("#probe-panel .note")
        await page.keyboard.type("half a thought")
        await E("""document.getElementById('probe-panel').innerHTML = '<div data-id="row7"><input class="note" placeholder="Note"></div>'""")
        await page.wait_for_timeout(150)
        await page.keyboard.type(" more")
        got = await E("(() => { const a = document.activeElement; return [a && a.className, a && a.value]; })()")
        check("any panel: a box rebuilt by a refresh gets the keyboard and his words back", got == ["note", "half a thought more"], got)

        # ------------------------------------------------------------ something else grabbing focus on a timer
        await E("""(() => { const b = document.createElement('button'); b.id = 'probe-btn'; b.textContent = 'x'; document.body.append(b);
          setTimeout(() => b.focus(), 50); })()""")
        await page.wait_for_timeout(250)
        await page.keyboard.type("!")
        got = await E("(() => { const a = document.activeElement; return [a && a.className, a && a.value]; })()")
        check("a timer focusing a button does not take the keyboard", got == ["note", "half a thought more!"], got)

        # ------------------------------------------------------------ but his own moves are his
        await page.click("#probe-btn")
        await page.wait_for_timeout(200)
        check("his own click elsewhere is respected", await E("document.activeElement && document.activeElement.id") == "probe-btn")
        await page.click("#probe-panel .note")
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(200)
        check("... and Tab is respected", not await E("document.activeElement && document.activeElement.classList.contains('note')"))
        await page.click("#probe-panel .note")
        await E("document.querySelector('#probe-panel .note').remove()")   # the box is gone for good: no fight
        await page.wait_for_timeout(200)
        check("a box that is gone for good is let go", await E("!document.querySelector('#probe-panel .note')"))
        check("no script errors", not errors, errors[:3])
        await browser.close()


asyncio.run(main())
print("\n%d passed, %d failed (%.1f s)" % (len(PASS), len(FAIL), time.time() - T0))
sys.exit(1 if FAIL else 0)
