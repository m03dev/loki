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
        r = await a.evaluate("() => ({ overlay: !!document.querySelector('#main #spaces, body > #spaces'), tab: !!document.getElementById('mode-spaces') })")
        check("nothing of Spaces floats over LOKI home; it is its own tab in the title bar", not r["overlay"] and r["tab"], r)
        await a.click("#mode-spaces")
        await a.wait_for_selector("#spaces .sp-welcome:not([hidden])", timeout=8000)
        r = await a.evaluate("""() => { const app = document.getElementById('spaces').getBoundingClientRect(), strip = document.getElementById('titlestrip').getBoundingClientRect();
          return { w: app.width, h: app.height, vw: innerWidth, vh: innerHeight, top: app.top, strip: strip.bottom }; }""")
        check("the Spaces tab fills the whole window under the title bar (like Discord)",
              abs(r["w"] - r["vw"]) < 2 and abs(r["top"] - r["strip"]) < 2 and abs(r["h"] - (r["vh"] - r["strip"])) < 2, r)

        # ---- Ada makes a space
        await a.click("#sp-welcome .send")
        await a.fill("#sp-dlg input[type=text]", "Night Owls")
        await a.click("#sp-dlg .sp-half:first-child .sp-go")
        await a.wait_for_selector("#sp-dlg textarea.sp-code[readonly]", timeout=8000)
        code = await a.eval_on_selector("#sp-dlg textarea.sp-code", "t => t.value")
        check("making a space opens it and hands over the invite code", code.startswith("loki-space:"), code[:30])
        await a.keyboard.press("Escape")
        r = await a.evaluate("() => ({ stones: document.querySelectorAll('#sp-stones .sp-stone').length, "
                             "rooms: [...document.querySelectorAll('#sp-rooms .sp-room')].map((x) => x.dataset.kind), title: document.querySelector('#sp-head .sp-title').textContent })")
        check("the new space: a stone on the rail, its name on top, a text and a voice room", r["stones"] == 1 and r["title"] == "Night Owls"
              and "text" in r["rooms"] and "voice" in r["rooms"], r)

        # ---- Bo joins with the code
        await b.click("#mode-spaces")
        await b.wait_for_selector("#spaces .sp-welcome:not([hidden])", timeout=8000)
        await b.click("#sp-welcome .sp-wjoin")
        await b.fill("#sp-dlg textarea.sp-code", "here you go: " + code)
        await b.click("#sp-dlg .sp-half:last-child .sp-go")
        await b.wait_for_function("document.querySelectorAll('#sp-stones .sp-stone').length === 1", timeout=15000)
        await b.wait_for_function("[...document.querySelectorAll('#sp-people .sp-pn b')].some((x) => x.textContent.startsWith('Ada'))", timeout=10000)
        check("Bo pastes the invite and is in: he sees Ada in the member list", True)

        # ---- chat, end to end
        await a.wait_for_function("[...document.querySelectorAll('#sp-people .sp-pn b')].some((x) => x.textContent.startsWith('Bo'))", timeout=10000)
        await a.click("#sp-log")
        await a.keyboard.type("hello @Bo - raid tonight?")      # typing anywhere goes into the box
        await a.keyboard.press("Enter")
        await b.wait_for_function("[...document.querySelectorAll('#sp-log .sp-text')].some((x) => x.textContent.includes('raid tonight'))", timeout=10000)
        r = await b.evaluate("() => ({ mention: !!document.querySelector('#sp-log .sp-msg.mention .sp-at.me'), who: [...document.querySelectorAll('#sp-log .sp-msg:not(.grouped) .sp-meta b')].map((x) => x.textContent) })")
        check("Ada's message (typed without clicking the box) reaches Bo, decrypted in his window, his @mention lit", r["mention"] and "Ada" in r["who"], r)
        sid = ADA.listing()["spaces"][0]["id"]
        stored = [e for e in ADA.hosted[sid].events if e.get("kind") == "msg"]
        raw = (TMP / "ada" / "hosted" / sid / "events.jsonl").read_text(encoding="utf-8")
        check("the host only ever stored ciphertext (the words are nowhere on its disk)",
              stored and "raid tonight" not in raw and "ct" in stored[-1], len(raw))
        await b.hover("#sp-log .sp-msg:last-child")
        await b.click("#sp-log .sp-msg:last-child .sp-hover .sp-hv")
        await a.wait_for_selector("#sp-log .sp-react", timeout=10000)
        r = await a.inner_text("#sp-log .sp-react")
        check("Bo reacts; Ada sees it", r.strip().endswith("1"), r)
        await b.fill("#sp-input", "in!")
        await b.keyboard.press("Enter")
        await a.wait_for_function("[...document.querySelectorAll('#sp-log .sp-text')].some((x) => x.textContent === 'in!')", timeout=10000)
        check("and answers", True)

        # ---- a lobby: in the rooms list, into LOKI World, and voice
        await b.click("#sp-rooms .sp-ib[aria-label='Open a lobby']")
        await b.fill("#sp-dlg input[type=text]", "Raid night")
        await b.click("#sp-dlg .sp-go")
        await b.wait_for_function("window.LokiSpaces.state.voice && document.body.dataset.mode === 'world'", timeout=15000)
        r = await b.evaluate("() => ({ pill: !document.getElementById('sp-voicebar').hidden, app: !!document.querySelector('#spaces') && !document.querySelector('[data-mode-pane=spaces]').hidden })")
        check("Bo opens a lobby: he is in its voice and taken into the World tab, with only the small call pill on top",
              r["pill"] and not r["app"], r)
        await a.wait_for_function("[...document.querySelectorAll('#sp-rooms .sp-room')].some((x) => x.dataset.kind === 'lobby')", timeout=15000)
        await a.click("#sp-rooms .sp-room[data-kind='lobby']")
        await a.wait_for_function("""() => { const v = window.LokiSpaces.state.voice; return v && [...v.peers.values()].some((p) => p.pc.connectionState === 'connected'); }""", timeout=25000)
        await b.wait_for_function("""() => { const v = window.LokiSpaces.state.voice; return v && [...v.peers.values()].some((p) => p.pc.connectionState === 'connected'); }""", timeout=15000)
        r = await b.evaluate("""async () => { const v = window.LokiSpaces.state.voice, p = [...v.peers.values()][0];
          const st = await p.pc.getStats(); let bytes = 0; st.forEach((x) => { if (x.type === 'inbound-rtp' && x.kind === 'audio') bytes += x.bytesReceived || 0; });
          return { tracks: p.audio.srcObject ? p.audio.srcObject.getAudioTracks().length : 0, bytes }; }""")
        await asyncio.sleep(1.5)
        r2 = await b.evaluate("""async () => { const p = [...window.LokiSpaces.state.voice.peers.values()][0], st = await p.pc.getStats(); let bytes = 0;
          st.forEach((x) => { if (x.type === 'inbound-rtp' && x.kind === 'audio') bytes += x.bytesReceived || 0; }); return bytes; }""")
        check("Ada clicks the lobby: a real peer-to-peer WebRTC call, Bo receiving her audio", r["tracks"] == 1 and r2 > r["bytes"], (r, r2))
        dtls = await a.evaluate("""async () => { const p = [...window.LokiSpaces.state.voice.peers.values()][0], st = await p.pc.getStats(); let s = '';
          st.forEach((x) => { if (x.type === 'transport') s = x.dtlsState; }); return s; }""")
        check("the call is encrypted (DTLS-SRTP)", dtls == "connected", dtls)
        r = await a.evaluate("() => ({ tiles: document.querySelectorAll('#sp-stage .sp-tile').length, panel: !document.getElementById('sp-vpanel').hidden })")
        check("Ada sees the lobby's stage (a tile each) and 'Voice connected' above her name, like Discord", r["tiles"] == 2 and r["panel"], r)
        await a.click("#sp-vmute")
        await asyncio.sleep(2.2)
        muted = await b.evaluate("() => (window.LokiSpaces.state.data[Object.keys(window.LokiSpaces.state.data)[0]].members.find((m) => m.name === 'Ada') || {}).voice")
        check("Ada mutes: Bo's side knows", bool(muted) and muted.get("muted") is True, muted)
        if os.getenv("LOKI_SHOT"):
            await a.screenshot(path=os.getenv("LOKI_SHOT"))
            await b.screenshot(path=os.getenv("LOKI_SHOT").replace(".png", "-b.png"))
            await a.click("#sp-rooms .sp-room[data-kind='text']")
            await asyncio.sleep(0.6)
            await a.screenshot(path=os.getenv("LOKI_SHOT").replace(".png", "-chat.png"))
        await a.click("#sp-vpanel .sp-ib.hang")
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
