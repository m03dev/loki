"""Home > For you in the real window (app/ui/home_review.js; owner 2026-10-27: "i should be overseeing the prompt and the
images gen like check off should come through my eyes once i should see the hands offs"). Stubbed engine:
  - nothing waiting: no panel; a prompt card and a hand-off card: the panel sits right under Home's header, on screen
  - a prompt card: who asks, the stage, the prompt in an editable box; Approve sends the owner's edited words
  - a hand-off card: its picture (from /chat/media), the hand-off notes, Retake needs a note, Approve checks it off
  - icons with tooltips, nothing overlaps inside a card, no script errors. Under a minute.

    python tests/test_home_review_ui.py
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

PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5E"
       "rkJggg==")
NOW = time.time()
PROMPT = {"id": "aaaaaa111111", "kind": "prompt", "status": "waiting", "t": NOW - 120, "tool": "make_image",
          "args": {"prompt": "a moss golem guardian, grey stone body, glowing amber eyes"}, "cwd": "/ws",
          "who": "Concept Artist", "asset": "moss-golem", "stage": "concept", "files": [],
          "handoff": "Concept Artist for moss-golem (creature)\nDelivers: one picture of the subject", "note": ""}
RESULT = {"id": "bbbbbb222222", "kind": "result", "status": "waiting", "t": NOW - 60, "tool": "turnaround",
          "args": {"prompt": "a red baby dragon"}, "cwd": "/ws", "who": "Technical Artist", "asset": "red-dragon",
          "stage": "turnaround", "files": ["turnarounds/red-dragon/sheet.png", "turnarounds/red-dragon/front.png"],
          "handoff": "# red-dragon turnaround v001 - PASS\n\n## Checks\n- PASS views: front, side, back", "note": ""}


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        page = await browser.new_page(viewport={"width": 1300, "height": 900})
        errors, posts = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        state = {"waiting": []}

        async def route(r):
            bare = r.request.url.split("8893", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            if r.request.method == "POST":
                posts.append((bare, json.loads(r.request.post_data or "{}")))
            if bare == "/review":
                return await r.fulfill(json={"ok": True, "on": True, "waiting": state["waiting"], "recent": [],
                                             "summary": {"waiting": len(state["waiting"])}})
            if bare == "/review/decide":
                done = posts[-1][1]["id"]
                state["waiting"] = [x for x in state["waiting"] if x["id"] != done]
                return await r.fulfill(json={"ok": True, "item": {"id": done}})
            if bare == "/chat/media":
                return await r.fulfill(json={"ok": True, "data_url": PNG})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8893/**", route)
        await page.goto("http://127.0.0.1:8893/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await page.wait_for_function("!!document.getElementById('home-review')", timeout=15000)
        check("nothing waiting: no For you panel", await E("document.getElementById('home-review').hidden"))

        state["waiting"] = [PROMPT, RESULT]
        await E("LokiHomeReview.refresh(true)")
        await page.wait_for_selector("#home-review .rv-card", timeout=8000)
        info = await E("""(() => { const p = document.getElementById('home-review'), hub = document.getElementById('home-hub');
          const r = p.getBoundingClientRect(), head = hub.querySelector('.home-head');
          return { shown: !p.hidden && r.width > 0 && r.height > 0, underHead: p.previousElementSibling === head,
                   count: p.querySelector('.rv-count').textContent,
                   cards: [...p.querySelectorAll('.rv-card')].map((c) => c.className) }; })()""")
        check("two cards: the panel is right under Home's header, on screen, with the count", info["shown"]
              and info["underHead"] and info["count"] == "2" and len(info["cards"]) == 2, info)
        check("the hand-off comes first (it holds up the next agent), then the prompt",
              "rv-result" in info["cards"][0] and "rv-prompt" in info["cards"][1], info["cards"])

        pc = await E("""(() => { const c = document.querySelector('.rv-prompt');
          return { who: c.querySelector('.rv-who').textContent, asset: c.querySelector('.rv-asset').textContent,
                   words: c.querySelector('.rv-words').value, tips: [...c.querySelectorAll('.rv-btn')].map((b) => b.dataset.tipName) }; })()""")
        check("a prompt card: who asks, the asset and stage, the prompt in an editable box", pc["who"] == "Concept Artist"
              and pc["asset"] == "moss-golem / concept" and pc["words"].startswith("a moss golem"), pc)
        check("... its buttons are icons with names in their tooltips", pc["tips"] == ["Approve and draw", "No"], pc["tips"])
        await page.fill(".rv-prompt .rv-words", "a moss golem guardian, mossy boulders, amber eyes, front view")
        await page.click(".rv-prompt .rv-ok")
        await page.wait_for_timeout(400)
        check("Approve sends the owner's edited words", posts and posts[-1][0] == "/review/decide"
              and posts[-1][1] == {"id": PROMPT["id"], "action": "approve",
                                   "prompt": "a moss golem guardian, mossy boulders, amber eyes, front view"}, posts[-1:])
        check("... and the card leaves", await E("document.querySelectorAll('#home-review .rv-prompt').length") == 0)

        rc = await E("""(() => { const c = document.querySelector('.rv-result');
          return { pics: [...c.querySelectorAll('.rv-pics img')].map((i) => i.src.slice(0, 22)),
                   notes: c.querySelector('.rv-notes').textContent }; })()""")
        check("a hand-off card shows its pictures and the hand-off notes", rc["pics"] == ["data:image/png;base64,"] * 2
              and "PASS views" in rc["notes"], rc)
        n = len(posts)
        await page.click(".rv-result .rv-retake")
        await page.wait_for_timeout(200)
        check("Retake without a note asks for one (nothing is sent)", len(posts) == n
              and await E("document.querySelector('.rv-result .rv-note-in').classList.contains('want')"))
        await page.fill(".rv-result .rv-note-in", "the back view does not match the front")
        await page.click(".rv-result .rv-retake")
        await page.wait_for_timeout(400)
        check("Retake sends the note", posts[-1][1] == {"id": RESULT["id"], "action": "retake",
                                                       "note": "the back view does not match the front"}, posts[-1:])
        check("all done: the panel hides again", await E("document.getElementById('home-review').hidden"))

        # the Prompt Expert (engine/prompt_expert.py): improving..., then the better words with the agent's own below
        working = dict(PROMPT, id="cccccc333333", expert={"status": "working"})
        state["waiting"] = [working]
        await E("LokiHomeReview.refresh(true)")
        await page.wait_for_selector(".rv-expert.working", timeout=8000)
        done = dict(working, args={"prompt": "A moss golem guardian of stacked mossy boulders, amber eyes, front view"},
                    agent_prompt="moss golem", expert={"status": "done", "why": "added materials and view", "by": "nvidia"})
        state["waiting"] = [done]
        await E("LokiHomeReview.refresh(true)")
        await page.wait_for_selector(".rv-expert.done", timeout=8000)
        ex = await E("""(() => { const c = document.querySelector('.rv-prompt');
          return { line: c.querySelector('.rv-expert').textContent, words: c.querySelector('.rv-words').value,
                   agent: c.querySelector('.rv-agent pre').textContent }; })()""")
        check("Prompt Expert: 'improving...' first, then its better words in the box, the agent's own words below",
              ex["line"].startswith("Improved by the Prompt Expert: added materials") and ex["words"].startswith("A moss golem guardian of")
              and ex["agent"] == "moss golem", ex)
        typed = dict(done, expert={"status": "done", "why": "x"}, id=done["id"])
        await page.fill(".rv-prompt .rv-words", "my own words")
        state["waiting"] = [dict(typed, expert={"status": "failed", "error": "late"})]
        await E("LokiHomeReview.refresh(true)")
        await page.wait_for_timeout(300)
        check("what the owner is typing is never wiped by a refresh", await E("document.querySelector('.rv-prompt .rv-words').value") == "my own words")

        state["waiting"] = [RESULT]
        await page.set_viewport_size({"width": 700, "height": 1200})     # the owner's vertical screen
        await E("LokiHomeReview.refresh(true)")
        await page.wait_for_selector(".rv-result", timeout=8000)
        lap = await E("""(() => { const c = document.querySelector('.rv-result'), r = c.getBoundingClientRect();
          const kids = [...c.querySelectorAll('.rv-note-in, .rv-btn')].map((x) => x.getBoundingClientRect());
          const over = kids.some((a, i) => kids.some((b, j) => j > i && !(a.right <= b.left || b.right <= a.left
                                 || a.bottom <= b.top || b.bottom <= a.top)));
          return { inside: kids.every((k) => k.left >= r.left - 1 && k.right <= r.right + 1), over }; })()""")
        check("on a narrow / vertical screen the note box and buttons stay inside the card, nothing overlaps",
              lap["inside"] and not lap["over"], lap)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 58))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
