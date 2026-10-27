"""Home's tabs filter, agents live in Lab, several chats at once (owner 2026-10-26: "those tabs dont work they need to
isolate whatever they have selected ... remove the agent working and team from loki home chat move them over to lab
... when i try to start another chat it says i cant cuz thers another chat going ... run in background chat thing
doesnt work"). LOKI's real window in headless Chromium, the engine stubbed (a /chat that takes its time, /jobs,
/conversations with parked chats). Skips cleanly without a browser.

    python tests/test_home_tabs_chats_ui.py
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

TMP = Path(tempfile.mkdtemp(prefix="loki-tabs-"))
Image.new("RGB", (64, 40), (200, 60, 40)).save(TMP / "p.png")
NOW = time.time()
ITEMS = ([{"kind": "made", "name": "pic %d" % i, "path_or_id": "images/p%d.png" % i, "updated": NOW - i,
           "thumb": "/creations/images/p.png", "open": {"mode": "files"}} for i in range(4)]
         + [{"kind": "render", "name": "render %d" % i, "path_or_id": "r%d" % i, "updated": NOW - 50 - i,
             "thumb": "/creations/images/p.png", "open": {"mode": "render"}} for i in range(2)]
         + [{"kind": "forge", "name": "model 0", "path_or_id": "models/m0.glb", "updated": NOW - 90,
             "thumb": "/creations/images/p.png", "open": {"mode": "forge", "model": "m0.glb"}}]
         + [{"kind": "job", "name": "agent making a dragon", "path_or_id": "j1", "updated": NOW, "status": "working",
             "open": {"mode": "job"}}])

ENG = {"busy": False, "active": "c1", "convs": [{"id": "c1", "title": "first chat", "updated": NOW, "count": 2}],
       "msgs": {"c1": [{"role": "user", "content": "make a dragon"}, {"role": "assistant", "content": "done"}]},
       "jobs": [], "posted": [], "n": 1}


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("SKIP: no Chromium (%s)" % str(exc)[:100])
            return
        page = await browser.new_page(viewport={"width": 1500, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def listing(parked=False, active=None):
            return {"ok": True, "active": active or ENG["active"], "parked": parked, "conversations": ENG["convs"]}

        async def route(r):
            bare = r.request.url.split("8895", 1)[1].split("#")[0]
            q = bare.split("?", 1)[1] if "?" in bare else ""
            bare = bare.split("?")[0]
            body = {}
            try:
                body = json.loads(r.request.post_data or "{}")
            except Exception:  # noqa: BLE001
                body = {}
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                ct = "text/javascript" if bare.endswith(".js") else None
                return await r.fulfill(path=str(UI / bare[4:]), **({"content_type": ct} if ct else {}))
            if bare == "/home/projects":
                return await r.fulfill(json={"ok": True, "items": ITEMS, "errors": {}, "counts": {}})
            if bare.startswith("/creations/"):
                return await r.fulfill(path=str(TMP / "p.png"), content_type="image/png")
            if bare == "/chat":
                ENG["busy"] = True
                await asyncio.sleep(4)
                ENG["busy"] = False
                return await r.fulfill(json={"ok": True, "response": "the first chat's answer", "chat_id": "x"})
            if bare == "/conversations" and r.request.method == "POST":
                ENG["n"] += 1
                cid = "c%d" % ENG["n"]
                ENG["convs"].insert(0, {"id": cid, "title": "New chat", "updated": time.time(), "count": 0})
                ENG["msgs"][cid] = []
                if ENG["busy"]:
                    return await r.fulfill(json=listing(True, cid))
                ENG["active"] = cid
                return await r.fulfill(json=listing())
            if bare == "/conversations":
                return await r.fulfill(json=listing())
            if bare == "/conversations/switch":
                cid = body.get("id")
                if not ENG["busy"]:
                    ENG["active"] = cid
                return await r.fulfill(json=dict(listing(ENG["busy"], cid), messages=ENG["msgs"].get(cid, [])))
            if bare == "/conversations/messages":
                cid = q.split("id=", 1)[1] if "id=" in q else ""
                return await r.fulfill(json={"ok": True, "id": cid, "messages": ENG["msgs"].get(cid, [])})
            if bare == "/jobs" and r.request.method == "POST":
                ENG["posted"].append(body)
                job = {"id": "job%d" % len(ENG["posted"]), "status": "working", "title": body.get("prompt", ""),
                       "conversation_id": body.get("conversation_id", "")}
                ENG["jobs"].append(job)
                cid = body.get("conversation_id")
                if cid:
                    ENG["msgs"].setdefault(cid, []).append({"role": "user", "content": body.get("prompt", "")})
                return await r.fulfill(json={"ok": True, "id": job["id"], "jobs": ENG["jobs"], "counts": {"working": 1}})
            if bare == "/jobs":
                return await r.fulfill(json={"ok": True, "jobs": ENG["jobs"], "counts": {}})
            return await r.fulfill(json={"ok": True})

        await page.route("http://127.0.0.1:8895/**", route)
        await page.goto("http://127.0.0.1:8895/#token=t")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        E = page.evaluate
        await E("LokiHome.refresh()")
        await page.wait_for_selector(".home-card")
        await page.wait_for_timeout(400)

        # ---- the tabs
        tabs = await E("[...document.querySelectorAll('.home-kinds .home-kind')].map(b => b.dataset.kind)")
        check("Home's tabs include Agents", "job" in tabs, tabs)
        cards = "[...document.querySelectorAll('.home-grid .home-card')].map(c => c.dataset.kind)"
        await page.click(".home-grid .home-card[data-kind='made']")   # pick a picture: it goes big
        await page.wait_for_timeout(500)
        if await E("!!document.querySelector('.lv')"):
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)
        for kind in ("forge", "render", "made", "job"):
            await page.click(".home-kinds .home-kind[data-kind='%s']" % kind)
            await page.wait_for_timeout(250)
            shown = await E(cards)
            hero_kind = await E("(() => { const k = document.querySelector('.home-hero-kind span'); return k ? k.textContent : ''; })()")
            check("tab %s shows only %s cards" % (kind, kind), shown and all(k == kind for k in shown), shown)
            check("... and its big preview is that kind too (a picked picture no longer sticks)",
                  hero_kind and hero_kind != ("Made" if kind != "made" else "x"), hero_kind)
        await page.click(".home-kinds .home-kind[data-kind='all']")
        await page.wait_for_timeout(250)
        check("All has no agent jobs in the grid", "job" not in await E(cards))

        # ---- the agents strip is not under the Home chat, it is in Lab > Agents
        under_chat = await E("(() => { const w = document.getElementById('work'); return !!w && !!w.closest('.chat-col') && getComputedStyle(w).display !== 'none'; })()")
        check("the agents / teams strip is not under the Home chat", not under_chat)
        await E("LokiModeBar.go('render', {view: 'agents'})")
        await page.wait_for_timeout(600)
        in_lab = await E("(() => { const w = document.getElementById('work'); return !!w && !!w.closest('.sf-work'); })()")
        check("... it is in Lab > Agents", in_lab)
        await E("LokiModeBar.go('loki')")
        await page.wait_for_timeout(300)

        # ---- two chats at once
        await E("switchTo('c1')")
        await page.wait_for_timeout(300)
        await E("void send('a long job in the first chat', {direct: true})")   # not awaited: it answers for 4 s
        await page.wait_for_timeout(500)
        check("the first chat is answering", await E("state.busy === true && viewIsBusy()"))
        await E("newChat()")
        await page.wait_for_timeout(400)
        check("a new chat opens while the first one answers", await E("state.active !== 'c1'"), await E("state.active"))
        check("... and its Send is not blocked", await E("!document.getElementById('send').disabled"))
        second = await E("state.active")
        await E("void send('and what about a sprite?')")
        await page.wait_for_timeout(500)
        posted = ENG["posted"][-1] if ENG["posted"] else {}
        check("a message in the second chat runs as a background agent for THAT chat",
              posted.get("conversation_id") == second and "sprite" in posted.get("prompt", ""), posted)
        check("... the message shows in the second chat", "sprite" in await E("document.getElementById('transcript').textContent"))
        await page.wait_for_timeout(4200)   # the first chat's answer arrives meanwhile
        check("the first chat's answer does not land in the second chat",
              "the first chat's answer" not in await E("document.getElementById('transcript').textContent"))
        # the background job ends: its answer is written into the second chat (engine) and shown
        ENG["msgs"].setdefault(second, []).append({"role": "assistant", "content": "here is your sprite"})
        if ENG["jobs"]:
            ENG["jobs"][-1]["status"] = "done"
        await page.wait_for_timeout(4500)
        check("the background answer appears in its chat", "here is your sprite" in await E("document.getElementById('transcript').textContent"))

        # ---- Run in background in a quiet chat
        await E("document.getElementById('in-background') && (document.getElementById('in-background').checked = true)")
        has_toggle = await E("!!document.getElementById('in-background')")
        if has_toggle:
            n = len(ENG["posted"])
            await E("void send('render the castle in the background')")
            await page.wait_for_timeout(500)
            check("Run in background sends it as a job with its chat", len(ENG["posted"]) == n + 1
                  and ENG["posted"][-1].get("conversation_id") == await E("state.active"), ENG["posted"][-1:])
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(main(), 55))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
