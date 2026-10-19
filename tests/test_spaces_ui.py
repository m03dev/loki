"""LOKI Spaces in the window (app/ui/spaces.js + engine/spaces.py), two machines in headless Chromium: Ada's window
makes a space on LOKI home, Bo's window joins it with the invite code (real HTTP between two Spaces engines), they
chat end to end encrypted (the engines only ever hold ciphertext), mention, react, open a lobby that shows on the
home screen over the world and takes Bo into the World tab - and then they TALK: a real WebRTC call between the
two windows (Chromium's fake microphone), set up through encrypted signals relayed by the host, with mute showing
on the other side. Skips without Playwright + Chromium. Well under a minute.

    python tests/test_spaces_ui.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-spacesui-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_SPACES_RELAY"] = "off"
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

import spaces  # noqa: E402
import spaces_api  # noqa: E402

ADA = spaces.Spaces(TMP / "ada", port=0, relay=False)
BO = spaces.Spaces(TMP / "bo", port=0, relay=False)
ADA.profile("Ada", "#7fcfc2")
BO.profile("Bo", "#e0a96d")


async def page_for(browser, who):
    ctx = await browser.new_context(viewport={"width": 1300, "height": 860}, permissions=["microphone"])
    page = await ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

    async def route(r):
        path = r.request.url.split("8898", 1)[1].split("#")[0]
        bare = path.split("?")[0]
        if bare == "/":
            return await r.fulfill(path=str(UI / "index.html"))
        if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
            return await r.fulfill(path=str(UI / bare[4:]))
        if bare == "/spaces" or bare.startswith("/spaces/"):
            body = json.loads(r.request.post_data or "{}") if r.request.method == "POST" else None
            st, out = await asyncio.to_thread(spaces_api.route, r.request.method, path, body, who)
            return await r.fulfill(status=st, body=json.dumps(out), content_type="application/json")
        return await r.fulfill(json={"ok": True})

    await page.route("http://127.0.0.1:8898/**", route)
    await page.goto("http://127.0.0.1:8898/#token=s3cret")
    await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
    return page, errors


async def main():
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream", "--disable-features=WebRtcHideLocalIpsWithMdns"]
        try:
            browser = await (p.chromium.launch(executable_path=exe, args=args) if exe else p.chromium.launch(args=args))
        except Exception as exc:  # noqa: BLE001
            print("SKIP: Playwright has no Chromium (%s)" % str(exc)[:120])
            return
        a, err_a = await page_for(browser, ADA)
        b, err_b = await page_for(browser, BO)
        await a.wait_for_selector("#sp-rail", state="visible", timeout=8000)
        r = await a.evaluate("() => { const d = document.getElementById('spaces'); return { shown: !d.hidden, mode: document.body.dataset.mode || 'loki' }; }")
        check("the Spaces rail sits on LOKI home (over the live world)", r["shown"], r)

        # ---- Ada makes a space
        await a.click("#sp-rail .sp-add")
        await a.fill("#sp-dlg input[type=text]", "Night Owls")
        await a.click("#sp-dlg .sp-half:first-child .sp-go")
        await a.wait_for_selector("#sp-dlg textarea.sp-code[readonly]", timeout=8000)
        code = await a.eval_on_selector("#sp-dlg textarea.sp-code", "t => t.value")
        check("making a space opens it and hands over the invite code", code.startswith("loki-space:"), code[:30])
        await a.keyboard.press("Escape")
        r = await a.evaluate("() => ({ stones: document.querySelectorAll('#sp-stones .sp-stone').length, open: !document.getElementById('sp-panel').hidden, "
                             "rooms: [...document.querySelectorAll('#sp-rooms .sp-room')].map((x) => x.dataset.kind) })")
        check("the new space has a stone on the rail and a text and a voice room", r["stones"] == 1 and r["open"] and "text" in r["rooms"] and "voice" in r["rooms"], r)

        # ---- Bo joins with the code
        await b.click("#sp-rail .sp-add")
        await b.fill("#sp-dlg textarea.sp-code", "here you go: " + code)
        await b.click("#sp-dlg .sp-half:last-child .sp-go")
        await b.wait_for_function("document.querySelectorAll('#sp-stones .sp-stone').length === 1 && !document.getElementById('sp-panel').hidden", timeout=15000)
        await b.wait_for_function("[...document.querySelectorAll('#sp-people .sp-pn')].some((x) => x.textContent.startsWith('Ada'))", timeout=10000)
        check("Bo pastes the invite and is in: he sees Ada in the member list", True)

        # ---- chat, end to end
        await a.wait_for_function("[...document.querySelectorAll('#sp-people .sp-pn')].some((x) => x.textContent.startsWith('Bo'))", timeout=10000)
        await a.fill("#sp-input", "hello @Bo - raid tonight?")
        await a.keyboard.press("Enter")
        await b.wait_for_function("[...document.querySelectorAll('#sp-log .sp-text')].some((x) => x.textContent.includes('raid tonight'))", timeout=10000)
        r = await b.evaluate("() => ({ mention: !!document.querySelector('#sp-log .sp-msg.mention .sp-at.me'), who: document.querySelector('#sp-log .sp-msg:not(.grouped) .sp-meta b')?.textContent })")
        check("Ada's message reaches Bo, decrypted in his window, his @mention lit", r["mention"] and r["who"] == "Ada", r)
        sid = ADA.listing()["spaces"][0]["id"]
        stored = [e for e in ADA.hosted[sid].events if e.get("kind") == "msg"]
        raw = (TMP / "ada" / "hosted" / sid / "events.jsonl").read_text(encoding="utf-8")
        check("the host only ever stored ciphertext (the words are nowhere on its disk)",
              stored and "raid tonight" not in raw and "ct" in stored[-1], len(raw))
        await b.hover("#sp-log .sp-msg")
        await b.click("#sp-log .sp-msg .sp-hover .sp-hv")
        await a.wait_for_selector("#sp-log .sp-react", timeout=10000)
        r = await a.inner_text("#sp-log .sp-react")
        check("Bo reacts; Ada sees it", r.strip().endswith("1"), r)
        await b.fill("#sp-input", "in!")
        await b.keyboard.press("Enter")
        await a.wait_for_function("[...document.querySelectorAll('#sp-log .sp-text')].some((x) => x.textContent === 'in!')", timeout=10000)
        check("and answers", True)

        # ---- a lobby: on the home screen, into LOKI World, and voice
        await b.click("#sp-head .sp-tools .sp-ib:nth-child(2)")
        await b.fill("#sp-dlg input[type=text]", "Raid night")
        await b.click("#sp-dlg .sp-go")
        await b.wait_for_function("window.LokiSpaces.state.voice && document.body.dataset.mode === 'world'", timeout=15000)
        r = await b.evaluate("() => ({ dock: !document.getElementById('spaces').hidden, world: document.getElementById('spaces').classList.contains('in-world'), bar: !document.getElementById('sp-voicebar').hidden })")
        check("Bo opens a lobby: he is in its voice, taken into the World tab, the dock and the voice bar with him",
              r["dock"] and r["world"] and r["bar"], r)
        await a.click("#sp-head .sp-tools .sp-ib:last-child")      # Ada closes the panel: the home shows the lobby cards
        await a.wait_for_selector("#sp-lobbies .sp-lcard", timeout=15000)
        card = await a.inner_text("#sp-lobbies .sp-lcard")
        if os.getenv("LOKI_SHOT"):
            await a.screenshot(path=os.getenv("LOKI_SHOT").replace(".png", "-home.png"))
        check("the lobby shows on Ada's home screen over the world, with who is in it", "Raid night" in card and "1/8" in card, card)
        await a.click("#sp-lobbies .sp-lcard button")
        await a.wait_for_function("""() => { const v = window.LokiSpaces.state.voice; return v && [...v.peers.values()].some((p) => p.pc.connectionState === 'connected'); }""", timeout=25000)
        await b.wait_for_function("""() => { const v = window.LokiSpaces.state.voice; return v && [...v.peers.values()].some((p) => p.pc.connectionState === 'connected'); }""", timeout=15000)
        r = await b.evaluate("""async () => { const v = window.LokiSpaces.state.voice, p = [...v.peers.values()][0];
          const st = await p.pc.getStats(); let bytes = 0; st.forEach((x) => { if (x.type === 'inbound-rtp' && x.kind === 'audio') bytes += x.bytesReceived || 0; });
          return { tracks: p.audio.srcObject ? p.audio.srcObject.getAudioTracks().length : 0, bytes }; }""")
        await asyncio.sleep(1.5)
        r2 = await b.evaluate("""async () => { const p = [...window.LokiSpaces.state.voice.peers.values()][0], st = await p.pc.getStats(); let bytes = 0;
          st.forEach((x) => { if (x.type === 'inbound-rtp' && x.kind === 'audio') bytes += x.bytesReceived || 0; }); return bytes; }""")
        check("Ada joins from the card: a real peer-to-peer WebRTC call, Bo receiving her audio", r["tracks"] == 1 and r2 > r["bytes"], (r, r2))
        dtls = await a.evaluate("""async () => { const p = [...window.LokiSpaces.state.voice.peers.values()][0], st = await p.pc.getStats(); let s = '';
          st.forEach((x) => { if (x.type === 'transport') s = x.dtlsState; }); return s; }""")
        check("the call is encrypted (DTLS-SRTP)", dtls == "connected", dtls)
        await a.click("#sp-vmute")
        await asyncio.sleep(2.2)
        muted = await b.evaluate("() => (window.LokiSpaces.state.data[Object.keys(window.LokiSpaces.state.data)[0]].members.find((m) => m.name === 'Ada') || {}).voice")
        check("Ada mutes: Bo's side knows", bool(muted) and muted.get("muted") is True, muted)
        if os.getenv("LOKI_SHOT"):
            await a.evaluate("window.LokiSpaces.open(Object.keys(window.LokiSpaces.state.data)[0])")
            await asyncio.sleep(1.2)
            await a.screenshot(path=os.getenv("LOKI_SHOT"))
            await b.screenshot(path=os.getenv("LOKI_SHOT").replace(".png", "-b.png"))
        await a.click("#sp-voicebar .sp-ib.hang")
        await b.wait_for_function("() => window.LokiSpaces.state.voice && window.LokiSpaces.state.voice.peers.size === 0", timeout=12000)
        check("Ada leaves: Bo's call to her closes", True)
        real = [e for e in err_a + err_b if "favicon" not in e and "WebAssembly" not in e]   # the harness serves no Godot build
        check("no page errors in either window", not real, real[:5])
        await browser.close()


asyncio.run(main())
ADA.stop()
BO.stop()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
