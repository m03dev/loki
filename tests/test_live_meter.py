"""The live meter (app/ui/live_meter.js; owner 2026-10-25: "real time token tracking underneath the thinking or its
steps as its working just like ziva ... i want to know what model is being used and when - keep the ui clean").

The window sends a message; the fake engine's progress has steps and "usage" events. One quiet line sits under the
newest step with the model, where it runs, the step, tokens in / out, tok/s and the time; a model switch leaves a
one-line note; when the reply lands the line stays under it, marked done. Under a minute.

    python tests/test_live_meter.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:600],)))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no playwright\n\n0 passed, 0 failed"); sys.exit(0)

U1 = json.dumps({"model": "loki-huihui_ai-qwen3.5-abliterated-9b:latest", "where": "this computer", "step": 2, "input": 2400, "output": 310, "tps": 16.9, "seconds": 9})
U2 = json.dumps({"model": "loki-nvidia/deepseek-ai/deepseek-v4.1-flash", "where": "nvidia", "step": 3, "input": 5200, "output": 900, "seconds": 14})
EVENTS = [{"id": 1, "event": "thinking", "text": "Working..."}, {"id": 2, "event": "tool", "text": "$ git init -q loki-test"},
          {"id": 3, "event": "usage", "text": U1}, {"id": 4, "event": "tool", "text": "$ git commit -m first"},
          {"id": 5, "event": "usage", "text": U2}]


async def main():
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            print("SKIP: no Chromium (%s)" % str(exc)[:80]); return
        page = await b.new_page(viewport={"width": 1300, "height": 860})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        st = {"n": 0, "release": False}

        async def route(r):
            bare = r.request.url.split("8903", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if bare == "/progress":
                st["n"] = min(len(EVENTS), st["n"] + 1)
                return await r.fulfill(json={"ok": True, "chat_id": "c1", "progress": EVENTS[st["n"] - 1:st["n"]]})
            if bare == "/chat":
                while not st["release"]:
                    await asyncio.sleep(0.1)
                return await r.fulfill(json={"ok": True, "response": "Done - made loki-test."})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8903/**", route)
        await page.goto("http://127.0.0.1:8903/#token=s")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("setView('chat')")
        task = asyncio.ensure_future(page.evaluate("send('make a git repo', {direct: true})"))
        await page.wait_for_function("document.querySelector('.live-meter') && document.querySelector('.live-meter').textContent.includes('qwen3.5')", timeout=10000)
        txt = await page.inner_text(".live-meter")
        check("one quiet line under the steps: model, where, step, tokens in/out, tok/s, time",
              "huihui_ai-qwen3.5-abliterated-9b · this computer" in txt and "step 2" in txt and "2.4k in" in txt
              and "310 out" in txt and "16.9 tok/s" in txt and " s" in txt, txt)
        check("... it is the last line of the transcript (under the newest step)",
              await page.evaluate("document.getElementById('transcript').lastElementChild.classList.contains('live-meter')"))
        await page.wait_for_function("document.querySelector('.live-meter').textContent.includes('deepseek')", timeout=10000)
        sw = await page.evaluate("[...document.querySelectorAll('.live-switch')].map((n) => n.textContent)")
        check("a model switch leaves a one-line note (which model, where)", sw and "deepseek-v4.1-flash" in sw[-1] and "nvidia" in sw[-1], sw)
        st["release"] = True
        await task
        await page.wait_for_timeout(300)
        done = await page.evaluate("(() => { const m = document.querySelector('.live-meter'); return m && [m.classList.contains('done'), m.textContent]; })()")
        check("when the reply lands the line stays, marked done", done and done[0] and "5.2k in" in done[1], done)
        check("no page errors", not errors, errors)
        await b.close()

asyncio.run(asyncio.wait_for(main(), 50))
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
