"""LOKI on the phone with no app (owner 2026-10-18: "qr dont show up on my phone and links dont go anywhere").

    python tests/test_phone_web.py      (< 20 s)

The pairing QR is a link (http://<computer>:<port>/#loki-phone:...), the phone link serves LOKI's chat page and its
script with a strict CSP and no secret in them, the code still parses for the phone app, and in headless Chromium
the page reads the code from the fragment, clears it from the address bar, and its pure-JS HMAC signs a status call
and a chat that the real PhoneServer accepts. The key hand-off page notices a visit, and on a Mac the firewall
hint names what blocks the phone.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-phoneweb-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_PHONE_RELAY"] = "off"
os.environ["LOKI_PHONE_PORT"] = "0"
os.environ["LOKI_PHONE_HOST"] = "127.0.0.1"
import phone_link  # noqa: E402
import signin  # noqa: E402

PASS: list = []
FAIL: list = []
OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({})).open


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


# --- macOS firewall hint (read-only socketfilterfw answers)
def fw(answers):
    def run(argv, **_k):
        out = types.SimpleNamespace(stdout=answers.get(argv[1], ""), stderr="")
        return out
    return run


on = "Firewall is enabled. (State = 1)"
check("Mac firewall off: no hint", signin.network_hint(run=fw({"--getglobalstate": "Firewall is disabled. (State = 0)"}), platform="darwin") == "")
check("Mac 'block all incoming' is named", "Block all incoming" in signin.network_hint(
    run=fw({"--getglobalstate": on, "--getblockall": "Firewall is set to block all non-essential incoming connections - enabled"}), platform="darwin"))
check("Mac firewall blocking Python is named", "Allow incoming connections" in signin.network_hint(
    run=fw({"--getglobalstate": on, "--getblockall": "disabled", "--getappblocked": "The application is blocked"}), platform="darwin"))
check("Mac firewall permitting Python: no hint", signin.network_hint(
    run=fw({"--getglobalstate": on, "--getblockall": "disabled", "--getappblocked": "The application is permitted"}), platform="darwin") == "")

# --- the key hand-off page notices the phone
ho = signin.PhoneHandoff("x", "X", lambda p, k: {"ok": True}, "127.0.0.1", lambda c: True, ttl_s=60)
check("a new hand-off has not been visited", ho.status()["visited"] is False)
OPEN(ho.url, timeout=5).read()
check("opening the page marks it visited (the window keeps the home link)", ho.status()["visited"] is True)
ho.stop()


# --- pairing is a link; the phone link serves the page
class Agent:
    def __init__(self):
        self.env = TMP / ".env"
        self.env.write_text("", encoding="utf-8")

    def env_file_path(self):
        return self.env


state, agent = types.SimpleNamespace(), Agent()
state.agent = agent
calls = []
phone_link.ui_route(state, agent, "POST", "/phones/enable", {"on": True})
srv = state.phone_server
srv.callbacks = {"status": lambda: {"machine": "mac", "kind": "Mac", "busy": False},
                 "chat": lambda m, mode: (calls.append((m, mode)) or (200, {"ok": True, "response": "echo: " + m}))}
code, data = phone_link.ui_route(state, agent, "POST", "/phones/pair", {"name": "My phone"})
url = data.get("url", "")
check("the pairing QR is a link a phone camera opens", code == 200 and url.startswith("http://") and "/#loki-phone:" in url, data.get("error"))
check("the QR encodes that link", data["svg"].startswith("<svg") and len(data["svgs"]) == len(data["urls"]))
check("the phone app still reads the code inside the link", phone_link.parse_pairing_code(url)["id"] == data["id"])
port = srv.address[1]
page = OPEN("http://127.0.0.1:%d/" % port, timeout=5)
html = page.read().decode()
check("the phone link serves LOKI's chat page", page.status == 200 and "/web.js" in html and "Message LOKI" in html)
check("with a strict CSP (scripts only from itself)", "script-src 'self'" in page.headers.get("Content-Security-Policy", ""))
js = OPEN("http://127.0.0.1:%d/web.js" % port, timeout=5).read().decode()
check("the page and script carry no secret", data["code"].split(":", 1)[1] not in html + js and "token" not in html)
check("the mobile app accepts the link too", '"#" + PAIR_PREFIX' in (REPO / "mobile" / "src" / "lib" / "protocol.ts").read_text(encoding="utf-8"))


async def browser():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  (no Playwright: browser half skipped)")
        return
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            b = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("  (no Chromium: browser half skipped: %s)" % str(exc)[:80])
            return
        ctx = await b.new_context(viewport={"width": 390, "height": 760}, bypass_csp=True)   # Playwright evaluates strings
        pg = await ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        await pg.goto("http://127.0.0.1:%d/#%s" % (port, data["code"]))
        await pg.wait_for_function("document.getElementById('status').textContent.startsWith('Connected')", timeout=8000)
        check("the page signs a status call the real server accepts", True)
        check("the code is gone from the address bar", "#" not in pg.url, pg.url)
        await pg.fill("#text", "hello from the phone")
        await pg.click("#send")
        await pg.wait_for_function("[...document.querySelectorAll('.msg.loki')].some((m) => m.textContent.startsWith('echo:'))", timeout=8000)
        check("a chat from the phone's browser reaches LOKI in Ask mode", calls == [("hello from the phone", "ask")], calls)
        await pg.reload()
        await pg.wait_for_function("document.getElementById('status').textContent.startsWith('Connected')", timeout=8000)
        check("it stays paired in that browser (Home Screen)", True)
        check("no page errors", not errors, errors)
        await b.close()


asyncio.run(browser())
phone_link.ui_route(state, agent, "POST", "/phones/enable", {"on": False})
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
