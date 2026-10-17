"""Headless Chromium check of the mic button and the Telegram card: the real app/ui files under
LOKI's real CSP, a stub engine (no model, no token, no Telegram).

    python tests/voice_preview/shot.py [out_dir]     (default: a temp folder)

Holds the mic with Chromium's fake microphone, posts the WAV to a stub /voice/transcribe that
checks it with engine/voice_input.decode_wav_upload, checks the words land in the message box,
the speaker toggle, the "no Whisper, no speech recognition" notice, and screenshots the mic with
its tooltip, the mic while listening, and Settings > General's Telegram card. Needs Playwright +
Chromium (not part of the suites; the suites check the same hooks without a browser).
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import tempfile  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="loki-shots-voice-"))
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO / "engine"))
import voice_input  # noqa: E402
import loki_bridge  # noqa: E402

UI = REPO / "app" / "ui"
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png"}
seen = {"wav_bytes": 0, "whisper": True}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        route = urlparse(self.path).path
        if route.startswith("/ui/"):
            f = UI / route[4:]
            if not f.is_file():
                self.send_error(404)
                return
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", TYPES.get(f.suffix, "application/octet-stream"))
            self.send_header("Content-Security-Policy", loki_bridge.UI_CSP)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/voice":
            stt = {"engine": "faster-whisper", "detail": "model base", "install": ""} if seen["whisper"] else {"engine": "", "install": "x"}
            return self._json(200, {"ok": True, "stt": stt, "tts": {"kokoro": False, "engine": "os"}})
        if route == "/conversations":
            return self._json(200, {"ok": True, "conversations": [], "active": ""})
        if route == "/settings/general":
            import portal_api
            vals = {k: ("" if v["kind"] == "secret" else v["default"]) for k, v in portal_api.GENERAL.items()}
            return self._json(200, {"ok": True, "settings": portal_api.GENERAL, "values": vals,
                                    "secrets_saved": {"LOKI_TELEGRAM_TOKEN": True, "HIGGSFIELD_KEY": False}, "model": "local"})
        if route == "/channels":
            return self._json(200, {"ok": True, "channels": [{"name": "telegram", "label": "Telegram", "token_saved": True,
                "poll_here": True, "poll_why": "auto: the Windows PC answers", "polling": True,
                "bot": {"username": "my_loki_bot"}, "paired": False, "owner": {}, "mode": "ask", "last_error": "",
                "pairing": {"code": "K7QM2XPA", "expires_in": 880, "link": "https://t.me/my_loki_bot?start=K7QM2XPA"}}]})
        if route == "/qr":
            import qr
            return self._json(200, {"ok": True, "svg": qr.svg("https://t.me/my_loki_bot?start=K7QM2XPA")})
        return self._json(200, {"ok": False, "error": "stub"})

    def do_POST(self):  # noqa: N802
        route = urlparse(self.path).path
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if route == "/voice/transcribe":
            try:
                blob = voice_input.decode_wav_upload(data.get("audio", ""))
            except ValueError as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            seen["wav_bytes"] = len(blob)
            seen["rate"] = int.from_bytes(blob[24:28], "little")
            return self._json(200, {"ok": True, "text": "hello from the fake mic", "engine": "faster-whisper"})
        if route == "/conversations":
            return self._json(200, {"ok": True, "conversations": [], "active": ""})
        return self._json(200, {"ok": False, "error": "stub"})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = "http://127.0.0.1:%d/ui/index.html#token=t" % srv.server_address[1]

from playwright.sync_api import sync_playwright  # noqa: E402

errors = []
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                                 "--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": 1100, "height": 720})
    ctx.grant_permissions(["microphone"], origin="http://127.0.0.1:%d" % srv.server_address[1])
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(url)
    page.wait_for_selector("#mic.icon-btn", timeout=15000)
    page.wait_for_timeout(500)
    info = page.evaluate("""() => ({
        mic: document.querySelector('#mic').getAttribute('aria-label'),
        svg: !!document.querySelector('#mic svg'), spk: !!document.querySelector('#speak-replies svg'),
        order: [...document.querySelector('.composer-row').children].map(n => n.id || n.className).join(' | ')})""")
    print("buttons:", info)
    # hover -> tooltip
    page.hover("#mic")
    page.wait_for_selector(".icon-tip:not([hidden])", timeout=3000)
    tip = page.evaluate("document.querySelector('.icon-tip').innerText")
    print("tooltip:", tip.replace("\n", " / "))
    box = page.locator(".composer").bounding_box()
    clip = {"x": max(0, box["x"] - 10), "y": max(0, box["y"] - 150), "width": min(1100, box["width"] + 20), "height": box["height"] + 160}
    page.screenshot(path=str(OUT / "voice-mic-tooltip.png"), clip=clip)
    # push to talk: hold 1.5 s with the fake microphone, let go
    page.mouse.move(*[v for v in (page.locator("#mic").bounding_box()[k] + 8 for k in ("x", "y"))])
    page.mouse.down()
    page.wait_for_timeout(300)
    rec = page.evaluate("document.querySelector('#mic').classList.contains('recording')")
    page.wait_for_timeout(1300)
    page.screenshot(path=str(OUT / "voice-mic-recording.png"), clip=clip)
    page.mouse.up()
    for _ in range(100):
        if "fake mic" in page.evaluate("document.querySelector('#prompt').value"):
            break
        page.wait_for_timeout(100)
    print("recording state while held:", rec, "| prompt now:", page.evaluate("document.querySelector('#prompt').value"),
          "| WAV bytes:", seen["wav_bytes"], "rate:", seen.get("rate"))
    # speaker toggle
    page.click("#speak-replies")
    print("speaker:", page.evaluate("[document.querySelector('#speak-replies').getAttribute('aria-pressed'), document.querySelector('#speak-replies').dataset.icon]"))
    page.click("#speak-replies")
    # no whisper and no speech recognition -> a notice, never silence
    seen["whisper"] = False
    page2 = ctx.new_page()
    page2.add_init_script("delete window.webkitSpeechRecognition; delete window.SpeechRecognition;")
    page2.on("pageerror", lambda e: errors.append(str(e)))
    page2.goto(url)
    page2.wait_for_selector("#mic.icon-btn", timeout=15000)
    page2.wait_for_timeout(300)
    page2.click("#mic")
    page2.wait_for_selector(".notice.error", timeout=5000)
    print("without whisper/SR:", page2.evaluate("document.querySelector('.notice.error').textContent"))
    page3 = ctx.new_page()
    page3.on("pageerror", lambda e: errors.append(str(e)))
    page3.goto(url)
    page3.wait_for_selector("#open-settings", timeout=15000)
    page3.click("#open-settings")
    page3.click('[data-tab="general"]')
    page3.wait_for_selector(".channel-card .pair-code svg", timeout=8000)
    card = page3.locator(".channel-card")
    card.scroll_into_view_if_needed()
    card.screenshot(path=str(OUT / "telegram-card.png"))
    print("card:", page3.evaluate("document.querySelector('.channel-card').innerText").replace("\n", " / ")[:500])
    b.close()
print("page errors:", errors[:10])
print("screenshots in", OUT)
srv.shutdown()
