"""The agent system in the real window (app/ui/agentsys.js; owner 2026-10-28: "interview like always asks me if this is
what i want with options ... a way for me to not want something made right now i just send it back with a prompt").
Stubbed engine:
  - a message: the owner's words show at once, then the interview card with its questions and options; a pick + Go
    sends the brief (with his choices) to /chat; "As written" sends his words; "Not now" parks it (nothing sent)
  - big work picked as "Specialist team" starts the delegation loop (/agentsys/orchestrate), not /chat
  - LOKI's newest answer has Send back / Not now; a note + Enter sends the revision; the bubble shows his note
  - For you: a question card and an upstream card with their buttons; Parked under the cards
  - Lab > System draws every layer; icons with tooltips, no script errors. Under a minute.

    python tests/test_agentsys_ui.py
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
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


try:
    from playwright.async_api import async_playwright
except ImportError:
    print("SKIP: no Playwright here\n\n0 passed, 0 failed")
    sys.exit(0)

QS = [{"id": "q1", "header": "Style", "question": "Which look should it have?", "multi": False,
       "options": [{"label": "Painterly concept art", "description": "painted"}, {"label": "Pixel art", "description": "pixels"}]},
      {"id": "q2", "header": "Shape", "question": "Which picture shape?", "multi": False,
       "options": [{"label": "16:9", "description": "wide"}, {"label": "1:1", "description": "square"}]}]
WHO = {"id": "q0", "header": "Who", "question": "Who should do it?", "multi": False,
       "options": [{"label": "Specialist team", "description": "plans and checks"}, {"label": "One agent", "description": "alone"}]}
NOW = time.time()
QUESTION = {"id": "cccccc333333", "kind": "question", "status": "waiting", "t": NOW - 30, "tool": "interview",
            "args": {"text": "make a fox sprite", "questions": QS, "plan": "The Concept Artist drafts it."}, "cwd": "/ws",
            "who": "Autopilot", "files": []}
UPSTREAM = {"id": "dddddd444444", "kind": "upstream", "status": "waiting", "t": NOW - 20, "tool": "upstream",
            "args": {"repo": "stephomi/sculptgl", "status": "behind", "behind": 3, "pin": "8e45daf", "changes": ["Fix crease"],
                     "used_in": ["app/ui/forge.js"], "compare_url": "https://github.com/stephomi/sculptgl/compare/8e45daf...master"},
            "cwd": "/ws", "who": "Upstream check", "files": []}


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
        st = {"waiting": [], "questions": QS, "messages": []}

        async def route(r):
            bare = r.request.url.split("8893", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            body = {}
            if r.request.method == "POST":
                body = json.loads(r.request.post_data or "{}")
                posts.append((bare, body))
            if bare == "/agentsys/interview":
                return await r.fulfill(json={"ok": True, "ask": True, "questions": st["questions"], "plan": "The Concept Artist writes it.",
                                             "by": "templates", "kind": "image"})
            if bare == "/agentsys/brief":
                team = any(str(v) == "Specialist team" for v in (body.get("answers") or {}).values())
                ch = "\n".join("- %s: %s" % (k, v) for k, v in (body.get("answers") or {}).items())
                return await r.fulfill(json={"ok": True, "team": team,
                                             "request": body["text"] + "\n\nOwner's choices (from the interview):\n" + ch})
            if bare == "/agentsys/sendback":
                if body.get("action") == "park":
                    return await r.fulfill(json={"ok": True, "parked": "p1"})
                return await r.fulfill(json={"ok": True, "request": "REVISION 1 - the owner sent the last result back.\n\nWhat the owner "
                                             "said is wrong / wants changed (this is the instruction - do exactly this, nothing else "
                                             "extra): " + body.get("note", "") + "\n\nThe original request: x"})
            if bare == "/agentsys/orchestrate":
                return await r.fulfill(json={"ok": True, "orchestration": "o1"})
            if bare == "/chat":
                return await r.fulfill(json={"ok": True, "response": "Here is your golem: images/golem.png"})
            if bare == "/review":
                return await r.fulfill(json={"ok": True, "on": True, "waiting": st["waiting"], "recent": [], "summary": {}})
            if bare == "/review/decide":
                done = body["id"]
                st["waiting"] = [x for x in st["waiting"] if x["id"] != done]
                return await r.fulfill(json={"ok": True, "item": {"id": done}})
            if bare == "/agentsys/parked":
                return await r.fulfill(json={"ok": True, "parked": [{"id": "abcdefabcdef", "request": "make a dragon video",
                                                                       "note": "after the golem", "t": NOW - 600}]})
            if bare == "/agentsys/status":
                return await r.fulfill(json={"ok": True, "interview": "always", "parked": 1, "traces": {
                    "runs": 4, "model_calls": 9, "tool_calls": 12, "tool_errors": 1, "guardrails_tripped": 2,
                    "tokens": {"input": 1000, "output": 200}, "failing_tools": [["bash", 4, 1]]}})
            if bare == "/agentsys/traces":
                return await r.fulfill(json={"ok": True, "runs": [{"trace_id": "t1", "name": "invoke_agent LOKI", "start": NOW - 50,
                                                                   "ms": 4200, "status": "ok", "outcome": "done", "spans": 5,
                                                                   "tools": 2, "llm": 2, "errors": 0, "tripped": []}]})
            if bare == "/agentsys/playbooks":
                return await r.fulfill(json={"ok": True, "playbooks": {"image": {"active": 3, "owner": 1, "retired": 0, "top": [
                    {"id": "img-00004", "section": "owner", "text": "For golems: make it night", "helpful": 2, "harmful": 0}]}}})
            if bare == "/agentsys/upstream":
                return await r.fulfill(json={"ok": True, "last_run": NOW - 3600, "sources": [
                    {"repo": "stephomi/sculptgl", "pin": "8e45daf", "version": "", "follows": "", "used_in": ["app/ui/forge.js"],
                     "seen": {"status": "behind", "behind": 3}}]})
            if bare == "/agentsys/orchestrations":
                return await r.fulfill(json={"ok": True, "runs": [{"id": "o1", "goal": "make a golem asset", "status": "done",
                                                                   "outcome": "verified", "updated": NOW, "steps": [
                                                                       {"id": "s1", "specialist": "Concept Artist", "status": "done"}]}]})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8893/**", route)
        await page.goto("http://127.0.0.1:8893/#token=s3cret")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.wait_for_function("!!window.LokiAgentSys", timeout=10000)
        E = page.evaluate

        # ---------------------------------------------------------------- the interview
        await E("send('make a picture of a moss golem')")
        await page.wait_for_selector(".as-iv:not(.as-iv-wait)", timeout=8000)
        info = await E("""(() => { const c = document.querySelector('.as-iv:not(.as-iv-wait)');
          const users = [...document.querySelectorAll('#transcript .turn.user .bubble')].map((b) => b.textContent);
          return { users, qs: [...c.querySelectorAll('.as-q-tag')].map((n) => n.textContent),
                   opts: [...c.querySelectorAll('.as-opt')].map((b) => [b.dataset.label, b.getAttribute('aria-pressed')]),
                   plan: (c.querySelector('.as-iv-plan') || {}).textContent,
                   tips: [...c.querySelectorAll('.as-acts .as-btn')].map((b) => b.dataset.tipName && b.dataset.tipWhat ? b.dataset.tipName : '') }; })()""")
        check("his message shows at once, before the card", info["users"] == ["make a picture of a moss golem"], info["users"])
        check("the card: the questions, the options, the plan", info["qs"] == ["Style", "Shape"] and len(info["opts"]) == 4
              and info["plan"].startswith("The Concept Artist"), info)
        check("the first option is pre-picked (the suggestion)", info["opts"][0][1] == "true" and info["opts"][2][1] == "true", info["opts"])
        check("its buttons have names and what they do", info["tips"] == ["Go", "As written", "Not now"], info["tips"])
        check("nothing went to /chat before he answered", not any(b == "/chat" for b, _ in posts))
        await page.click(".as-iv .as-opt[data-label='Pixel art']")
        await page.fill(".as-iv .as-note", "green eyes")
        await page.click(".as-iv .as-go")
        await page.wait_for_function("document.querySelectorAll('#transcript .turn.loki').length >= 1", timeout=8000)
        chat = [b for b, d in posts if b == "/chat"]
        sent = next(d for b, d in posts if b == "/chat")
        brief = next(d for b, d in posts if b == "/agentsys/brief")
        check("Go sends his picks and note in the brief", brief["answers"] == {"Style": "Pixel art", "Shape": "16:9"}
              and brief["note"] == "green eyes", brief)
        check("... and the brief to /chat, once", len(chat) == 1 and "Owner's choices" in sent["message"], sent)
        users = await E("[...document.querySelectorAll('#transcript .turn.user .bubble')].map((b) => b.textContent)")
        check("his message is shown once (not again with the brief)", users == ["make a picture of a moss golem"], users)

        # ---------------------------------------------------------------- send back / not now
        await page.wait_for_selector("#transcript .turn.loki .as-sb", timeout=5000)
        bars = await E("document.querySelectorAll('#transcript .as-sb').length")
        check("LOKI's newest answer has Send back / Not now", bars == 1)
        await page.click("#transcript .as-sb .as-sb-back")
        await page.fill("#transcript .as-sb .as-sb-note", "make it night")
        await page.press("#transcript .as-sb .as-sb-note", "Enter")
        await page.wait_for_function("[...document.querySelectorAll('#transcript .turn.user .bubble')].some((b) => b.textContent.startsWith('↩'))", timeout=8000)
        sb = next(d for b, d in posts if b == "/agentsys/sendback")
        check("the note goes to /agentsys/sendback", sb["note"] == "make it night" and sb["kind"] == "chat", sb)
        await page.wait_for_function("document.querySelectorAll('#transcript .turn.loki').length >= 2", timeout=8000)
        last_chat = [d for b, d in posts if b == "/chat"][-1]
        check("the revision request goes to /chat", last_chat["message"].startswith("REVISION 1"), last_chat)
        users = await E("[...document.querySelectorAll('#transcript .turn.user .bubble')].map((b) => b.textContent)")
        check("the bubble shows his note, not the machinery", users[-1] == "↩ Sent back: make it night", users)
        await page.wait_for_function("document.querySelectorAll('#transcript .as-sb').length === 1", timeout=5000)
        check("only the newest answer keeps the bar", await E("document.querySelectorAll('#transcript .turn.loki')[1].contains(document.querySelector('.as-sb'))"))

        # ---------------------------------------------------------------- a reply in a going chat is never held up
        n_iv = len([1 for b, _ in posts if b == "/agentsys/interview"])
        n_chat = len([1 for b, _ in posts if b == "/chat"])
        await page.fill("#prompt", "yes do the second one and make it bigger")
        await page.press("#prompt", "Enter")
        await page.wait_for_function("document.querySelectorAll('#transcript .turn.loki').length >= 3", timeout=8000)
        check("a reply in a going chat goes straight to /chat - no card in front of it",
              len([1 for b, _ in posts if b == "/agentsys/interview"]) == n_iv
              and len([1 for b, _ in posts if b == "/chat"]) == n_chat + 1
              and not await E("!!document.querySelector('.as-iv:not(.as-done)')"))
        attrs = await E("""(() => { const p = document.getElementById('prompt');
          return [p.getAttribute('autocorrect'), p.getAttribute('spellcheck'), p.getAttribute('writingsuggestions'), p.getAttribute('autocapitalize')]; })()""")
        check("the message box has the OS autocorrect and predictions off", attrs == ["off", "false", "false", "off"], attrs)
        made = await E("""(() => { const i = document.createElement('input'); i.type = 'text'; document.body.append(i);
          return new Promise((r) => setTimeout(() => r([i.getAttribute('autocorrect'), i.getAttribute('spellcheck')]), 50)); })()""")
        check("... and so does every text box added later", made == ["off", "false"], made)
        check("the owner's focus is back in the message box after he answers a card", await E("document.activeElement && document.activeElement.id === 'prompt'"))

        # ---------------------------------------------------------------- not now in the interview (a new chat)
        await E("document.getElementById('transcript').replaceChildren()")
        n_chat = len([1 for b, _ in posts if b == "/chat"])
        await E("send('make a picture of a fox spirit')")
        await page.wait_for_selector(".as-iv:not(.as-done):not(.as-iv-wait)", timeout=8000)
        await page.click(".as-iv:not(.as-done) .as-later")
        await page.wait_for_timeout(300)
        park = [d for b, d in posts if b == "/agentsys/sendback" and d.get("action") == "park"]
        check("Not now parks it and sends nothing", park and park[-1]["text"] == "make a picture of a fox spirit"
              and len([1 for b, _ in posts if b == "/chat"]) == n_chat, park)

        # ---------------------------------------------------------------- big work -> the specialist team
        st["questions"] = [WHO] + QS
        await E("document.getElementById('transcript').replaceChildren()")
        await E("send('rework the whole golem asset from scratch')")
        await page.wait_for_selector(".as-iv:not(.as-done):not(.as-iv-wait)", timeout=8000)
        await page.click(".as-iv:not(.as-done) .as-go")
        await page.wait_for_timeout(500)
        orch = [d for b, d in posts if b == "/agentsys/orchestrate"]
        check("Specialist team starts the delegation loop, not a chat turn", orch and "Owner's choices" in orch[-1]["goal"]
              and len([1 for b, _ in posts if b == "/chat"]) == n_chat, orch)

        # ---------------------------------------------------------------- For you: question, upstream, parked
        st["waiting"] = [QUESTION, UPSTREAM]
        await E("showHome()")
        await page.wait_for_function("!!document.getElementById('home-review')", timeout=10000)
        await E("LokiHomeReview.refresh(true)")
        await page.wait_for_selector("#home-review .rv-question", timeout=8000)
        fy = await E("""(() => { const q = document.querySelector('.rv-question'), u = document.querySelector('.rv-upstream');
          return { q: [...q.querySelectorAll('.rv-btn')].map((b) => b.dataset.tipName), qopts: q.querySelectorAll('.rv-qopt').length,
                   u: [...u.querySelectorAll('.rv-btn')].map((b) => b.dataset.tipName), link: !!u.querySelector('.rv-link'),
                   parked: (document.querySelector('.rv-parked summary') || {}).textContent }; })()""")
        await page.wait_for_selector(".rv-parked", timeout=5000)
        fy["parked"] = await E("(document.querySelector('.rv-parked summary') || {}).textContent")
        check("a question card: options and Go / As written / Not now", fy["q"] == ["Go", "As written", "Not now"] and fy["qopts"] == 4, fy)
        check("an upstream card: Adopt / Skip / Not now and the link", fy["u"] == ["Adopt", "Skip", "Not now"] and fy["link"], fy)
        check("Parked under the cards", "Parked (1)" in (fy["parked"] or ""), fy)
        await page.click(".rv-upstream .rv-ok")
        await page.wait_for_timeout(300)
        dec = [d for b, d in posts if b == "/review/decide"]
        check("Adopt is the owner's decision on that card", dec and dec[-1]["action"] == "adopt" and dec[-1]["id"] == UPSTREAM["id"], dec)

        # ---------------------------------------------------------------- Lab > System
        await E("(() => { const d = document.createElement('div'); d.id = 'as-test'; document.body.append(d); return LokiAgentSys.panel(d); })()")
        await page.wait_for_selector("#as-test .as-box", timeout=5000)
        lab = await E("""(() => { const d = document.getElementById('as-test');
          const boxes = [...d.querySelectorAll('.as-box h3')].map((h) => h.textContent);
          const btns = [...d.querySelectorAll('.as-btn')];
          return { boxes, stats: d.querySelectorAll('.as-stat').length, tipless: btns.filter((b) => !b.dataset.tipName || !b.dataset.tipWhat).length,
                   owner: !!d.querySelector('.as-pb-line.as-owner'), up: (d.querySelector('.as-up .as-item') || {}).textContent || '' }; })()""")
        check("Lab > System: every layer", lab["boxes"] == ["This week", "Runs", "Specialist teams", "Playbooks", "Upstream", "Parked"], lab["boxes"])
        check("Lab > System: the numbers, his playbook lines, upstream behind", lab["stats"] == 8 and lab["owner"] and "behind by 3" in lab["up"], lab)
        check("every button has a name and what it does", lab["tipless"] == 0, lab["tipless"])
        await E("LokiAgentSys.leave()")
        check("no script errors", not errors, errors)
        check("this suite stays under 60 s", time.time() - T0 < 60, time.time() - T0)
        await browser.close()

asyncio.run(main())
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
