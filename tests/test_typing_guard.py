"""LOKI never closes the window while the owner types (owner 2026-10-29: "whever i try to type on mac i get pushed out
of the typing box ... this has happened before i thought you fixed it").

The cause (harness_data/app/loki_app.log on the Mac): an automatic update counted LOKI as idle when nothing had been
SENT for 2 minutes, so writing a longer message was "idle" and the whole window closed and reopened under his fingers -
33 times on 2026-10-28, 103 on 2026-10-25. Checked here:
  - the engine: owner_active() after the window reports typing / an unsent message; the updater does not apply then
  - another machine's "update now" is deferred while he types here
  - the real window (qol.js): typing reports activity + "a message is in the box" to /ui/active (throttled), a sent
    message says the box is empty, and after a reload his unsent text is back with the cursor in the box
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
sys.path.insert(0, str(REPO / "engine"))
PASS: list = []
FAIL: list = []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


# ------------------------------------------------------------------ the engine side
import loki_bridge as B  # noqa: E402
import updater  # noqa: E402

now = time.time()
B.UI_STATE.update(active_at=0.0, draft=False)
check("nobody at the window: not active", not B.owner_active(now))
B.UI_STATE.update(active_at=now - 30, draft=False)
check("typed 30 s ago: active", B.owner_active(now))
B.UI_STATE.update(active_at=now - 6 * 60, draft=False)
check("6 minutes away with an empty box: not active (updates may go in)", not B.owner_active(now))
B.UI_STATE.update(active_at=now - 20 * 60, draft=True)
check("a half-written message 20 minutes ago: still active", B.owner_active(now))
B.UI_STATE.update(active_at=now - 40 * 60, draft=True)
check("... but not forever (40 minutes)", not B.owner_active(now))


def idle_like_bridge(strict=True):   # the bridge's _idle: nobody sent anything for 2 min, and the new owner check
    return not B.owner_active()


B.UI_STATE.update(active_at=time.time(), draft=True)
check("an update waiting 30 minutes does not apply while he types",
      not updater.ready_to_apply(idle_like_bridge, waiting_since=time.time() - 1800))
src = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
i = src.index("def _idle(strict: bool = True)")
check("the updater's idle test asks owner_active()", "owner_active()" in src[i:i + 700])
pl = (REPO / "engine" / "peer_link.py").read_text(encoding="utf-8")
j = pl.index("def apply_update()")
check("another machine's 'update now' waits while he types here", "owner_active" in pl[j:j + 900] and "deferred" in pl[j:j + 900])
B.UI_STATE.update(active_at=0.0, draft=False)

# ------------------------------------------------------------------ the window side
try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None


async def window():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("  SKIP window: no Chromium (%s)" % str(exc)[:100])
            return
        ctx = await browser.new_context(viewport={"width": 1300, "height": 900})
        page = await ctx.new_page()
        errors, active = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8894", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if bare == "/ui/active":
                active.append(json.loads(r.request.post_data or "{}"))
            if bare == "/agentsys/interview":
                return await r.fulfill(json={"ok": True, "ask": False})
            if bare == "/chat":
                return await r.fulfill(json={"ok": True, "response": "ok"})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8894/**", route)
        await page.goto("http://127.0.0.1:8894/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.click("#prompt")
        await page.keyboard.type("i am writing a long message to loki", delay=5)
        await page.wait_for_timeout(300)
        check("typing tells the engine he is here, with a message in the box",
              any(a.get("draft") is True for a in active), active)
        n = len(active)
        await page.keyboard.type(" and more words", delay=5)
        await page.wait_for_timeout(200)
        check("... throttled (not one request per key)", len(active) - n <= 1, len(active) - n)

        # a restart reloads the window: his unsent text is back and the cursor is in the box at its end
        await page.wait_for_timeout(400)          # the draft is saved 300 ms after the last key
        await page.reload()
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.wait_for_timeout(600)
        back = await page.evaluate("""(() => { const p = document.getElementById('prompt');
          return [p.value, document.activeElement === p, p.selectionStart === p.value.length]; })()""")
        check("after a reload his unsent message is back", back[0] == "i am writing a long message to loki and more words", back)
        check("... with the cursor in the box at the end", back[1] and back[2], back)

        active.clear()
        await page.evaluate("document.getElementById('prompt').value = ''")
        await page.keyboard.press("a")
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(200)
        check("an emptied box is reported at once (updates may go in once he steps away)",
              any(a.get("draft") is False for a in active), active)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if async_playwright is None:
    print("  SKIP window: no Playwright here")
else:
    asyncio.run(window())
print("\n%d passed, %d failed (%.1f s)" % (len(PASS), len(FAIL), time.time() - T0))
sys.exit(1 if FAIL else 0)
