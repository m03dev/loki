"""Connect accounts without copying keys around: browser sign-in, sign-in codes, and the phone.

Three ways, all ending with a key saved by loki.connect_provider (checked, then written to
harness_data/.env):

1. OpenRouter sign-in (OAuth PKCE, https://openrouter.ai/docs/guides/overview/auth/oauth)
     browser mode: LOKI opens openrouter.ai/auth in your browser with a callback to this
       engine (http://localhost:<port>/oauth/openrouter/callback); you click Authorize and
       the key arrives by itself.
     code mode (for the QR code): no callback; the OpenRouter page shows a code, you scan
       the QR with your phone, sign in there, and type the code into LOKI.
   Either way the code is swapped for a key at POST /api/v1/auth/keys with the verifier,
   so an intercepted code is useless on its own.

2. Sign-in codes (OAuth device flow, RFC 8628) for providers that offer it - Hugging Face
   today. It needs an OAuth app's client id (LOKI_HF_CLIENT_ID); without one the card
   falls back to "paste a token". LOKI shows the short code and a QR of the verification
   page; it polls until you approve on any device.

3. Send a key from your phone (PhoneHandoff): LOKI opens a one-time page on your home
   network for five minutes and shows its QR code. Open it on the phone (where you just
   created the key), paste, send. One use, private-network clients only, then it closes.
   It is plain HTTP on your LAN - fine at home, and the UI says so.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

OPENROUTER_AUTH = "https://openrouter.ai/auth"
OPENROUTER_KEYS = "https://openrouter.ai/api/v1/auth/keys"
FLOW_TTL_S = 600          # OpenRouter codes expire after 10 minutes
HANDOFF_TTL_S = 300

DEVICE_PROVIDERS = {
    # provider id -> device authorization endpoints (RFC 8628)
    "huggingface": {"device": "https://huggingface.co/oauth/device", "token": "https://huggingface.co/oauth/token",
                    "client_env": "LOKI_HF_CLIENT_ID", "scope": "openid profile inference-api"},
}

_FLOWS: dict = {}          # state -> {provider, verifier, mode, created, done, result}
_lock = threading.Lock()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple:
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _prune() -> None:
    now = time.time()
    for key in [k for k, f in _FLOWS.items() if now - f["created"] > FLOW_TTL_S]:
        _FLOWS.pop(key, None)


def openrouter_start(port: int, mode: str = "browser") -> dict:
    """Begin an OpenRouter sign-in. Returns {state, url}; open `url` (or show its QR)."""
    verifier, challenge = pkce_pair()
    state = _b64url(secrets.token_bytes(18))
    params = {"code_challenge": challenge, "code_challenge_method": "S256", "state": state,
              "key_label": "LOKI"}
    if mode == "browser":
        params["callback_url"] = "http://localhost:%d/oauth/openrouter/callback" % int(port)
    with _lock:
        _prune()
        _FLOWS[state] = {"provider": "openrouter", "verifier": verifier, "mode": mode,
                         "created": time.time(), "done": False, "result": None}
    return {"ok": True, "state": state, "mode": mode, "url": OPENROUTER_AUTH + "?" + urllib.parse.urlencode(params),
            "expires_in": FLOW_TTL_S}


def openrouter_exchange(code: str, verifier: str, opener=urllib.request.urlopen) -> str:
    body = json.dumps({"code": code, "code_verifier": verifier, "code_challenge_method": "S256"}).encode()
    req = urllib.request.Request(OPENROUTER_KEYS, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "Loki/1.0"})
    try:
        with opener(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raise ValueError({400: "the sign-in method did not match; start again",
                          403: "that code is wrong or expired; start again"}.get(exc.code, "OpenRouter answered HTTP %d" % exc.code)) from None
    key = str(data.get("key") or "").strip()
    if not key:
        raise ValueError("OpenRouter sent no key back")
    return key


def openrouter_finish(state: str, code: str, connect: Callable[[str, str], dict],
                      opener=urllib.request.urlopen) -> dict:
    """Swap the code for a key and connect it. `state` must be a flow this engine started."""
    with _lock:
        _prune()
        flow = _FLOWS.get(str(state or ""))
    if flow is None:
        return {"ok": False, "error": "this sign-in has expired or was not started here; start again"}
    if flow["done"]:
        return flow["result"]
    code = str(code or "").strip()
    if not code or len(code) > 400:
        return {"ok": False, "error": "enter the code OpenRouter showed you"}
    try:
        key = openrouter_exchange(code, flow["verifier"], opener=opener)
        result = connect("openrouter", key)
    except ValueError as exc:
        result = {"ok": False, "error": str(exc)}
    with _lock:
        flow.update({"done": True, "result": result})
    return result


def flow_status(state: str) -> dict:
    with _lock:
        flow = _FLOWS.get(str(state or ""))
    if flow is None:
        return {"ok": False, "error": "unknown or expired sign-in"}
    return {"ok": True, "done": flow["done"], "result": flow["result"], "provider": flow["provider"],
            "expires_in": max(0, int(FLOW_TTL_S - (time.time() - flow["created"])))}


def callback_page(ok: bool, message: str) -> str:
    colour = "#a3be8c" if ok else "#ff7777"
    return ("<!doctype html><meta charset=utf-8><title>LOKI</title><body style=\"background:#1f1f24;"
            "color:#e6e9ee;font:16px -apple-system,system-ui,sans-serif;display:grid;place-items:center;"
            "height:100vh;margin:0\"><div style=\"text-align:center\"><div style=\"font-size:44px;color:%s\">%s</div>"
            "<p>%s</p><p style=\"color:#9aa0aa\">You can close this tab and go back to LOKI.</p></div></body>"
            % (colour, "&#10003;" if ok else "&#10007;", html.escape(message)))


# --------------------------------------------------------------------------- device flow
def device_available(provider: str, env: dict) -> bool:
    spec = DEVICE_PROVIDERS.get(provider)
    return bool(spec and str(env.get(spec["client_env"], "")).strip())


def _form(url: str, fields: dict, opener) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Accept": "application/json", "User-Agent": "Loki/1.0",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8") or "{}")
        except ValueError:
            return {"error": "http_%d" % exc.code}


def device_start(provider: str, env: dict, connect: Callable[[str, str], dict],
                 opener=urllib.request.urlopen, sleep=time.sleep) -> dict:
    spec = DEVICE_PROVIDERS.get(provider)
    if not spec or not device_available(provider, env):
        return {"ok": False, "error": "sign-in codes need an OAuth app for %s (set %s); paste a token instead"
                % (provider, (spec or {}).get("client_env", "a client id"))}
    client_id = str(env.get(spec["client_env"])).strip()
    data = _form(spec["device"], {"client_id": client_id, "scope": spec["scope"]}, opener)
    if not data.get("device_code"):
        return {"ok": False, "error": "the provider did not start a sign-in (%s)" % data.get("error", "no code")}
    state = _b64url(secrets.token_bytes(18))
    flow = {"provider": provider, "verifier": "", "mode": "device", "created": time.time(), "done": False,
            "result": None}
    with _lock:
        _prune()
        _FLOWS[state] = flow
    interval = max(2, int(data.get("interval") or 5))
    expires = min(int(data.get("expires_in") or 900), 900)

    def poll() -> None:
        nonlocal interval
        deadline = time.time() + expires
        while time.time() < deadline:
            sleep(interval)
            reply = _form(spec["token"], {"client_id": client_id, "device_code": data["device_code"],
                                          "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, opener)
            if reply.get("access_token"):
                result = connect(provider, reply["access_token"])
                break
            err = reply.get("error", "")
            if err == "slow_down":
                interval += 5
                continue
            if err == "authorization_pending":
                continue
            result = {"ok": False, "error": {"expired_token": "the code expired; start again",
                                             "access_denied": "sign-in was declined"}.get(err, err or "sign-in failed")}
            break
        else:
            result = {"ok": False, "error": "the code expired; start again"}
        with _lock:
            flow.update({"done": True, "result": result})

    threading.Thread(target=poll, daemon=True, name="loki-device-signin").start()
    return {"ok": True, "state": state, "user_code": data.get("user_code", ""),
            "verification_uri": data.get("verification_uri", ""),
            "url": data.get("verification_uri_complete") or data.get("verification_uri", ""),
            "expires_in": expires}


# --------------------------------------------------------------------------- phone hand-off
class _QuickServer(ThreadingHTTPServer):
    """HTTPServer without its reverse-DNS lookup of the bind address (socket.getfqdn), which
    can stall for ~30 s on a Mac with slow DNS before the page even exists."""
    daemon_threads = True

    def server_bind(self) -> None:
        import socketserver  # pylint: disable=import-outside-toplevel
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), port


class PhoneHandoff:
    """A one-time page on the home network that sends one key from a phone to LOKI."""

    def __init__(self, provider: str, label: str, connect: Callable[[str, str], dict],
                 host_ip, private_client: Callable[[str], bool], ttl_s: float = HANDOFF_TTL_S,
                 bind: str = "0.0.0.0", keys_url: str = "", port_number: int = 0) -> None:
        self.provider, self.label, self.connect = provider, label, connect
        self.keys_url = keys_url if str(keys_url).startswith("https://") else ""
        hosts = [host_ip] if isinstance(host_ip, str) else [h for h in host_ip if h]
        self.token = _b64url(secrets.token_bytes(24))
        self.created = time.time()
        self.ttl_s = ttl_s
        self.result: dict | None = None
        self.private_client = private_client
        handoff = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                return

            def _page(self, code: int, body: str) -> None:
                raw = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(raw)

            def _allowed(self) -> bool:
                if not handoff.private_client(self.client_address[0]):
                    self._page(403, callback_page(False, "Only devices on your home network can use this page."))
                    return False
                path = urllib.parse.urlparse(self.path).path.rstrip("/")
                if path != "/k/" + handoff.token:
                    self._page(404, callback_page(False, "This link is not valid. Make a new QR code in LOKI."))
                    return False
                if handoff.expired():
                    self._page(410, callback_page(False, "This link has expired. Make a new QR code in LOKI."))
                    return False
                return True

            def do_GET(self):  # noqa: N802
                if self._allowed():
                    self._page(200, handoff.form())

            def do_POST(self):  # noqa: N802
                if not self._allowed():
                    return
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 8192)
                except ValueError:
                    length = 0
                fields = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
                key = (fields.get("key") or [""])[0].strip()
                if not key:
                    self._page(400, handoff.form("Paste the key first."))
                    return
                result = handoff.connect(handoff.provider, key)
                handoff.result = result
                self._page(200, callback_page(bool(result.get("ok")), result.get("message") or result.get("error", "")))
                if result.get("ok"):
                    threading.Thread(target=handoff.stop, daemon=True).start()

        # the same port every time when it is free, so a firewall "Allow" the owner gave once still fits
        self.httpd = None
        for candidate in ([port_number, 0] if port_number else [0]):
            try:
                self.httpd = _QuickServer((bind, candidate), Handler)
                break
            except OSError:
                continue
        if self.httpd is None:
            raise OSError("no free port for the phone page")
        self.created = time.time()          # the five minutes start once the page is up
        self.port = self.httpd.server_address[1]
        # every address a phone on the same network could use, the likeliest first (the window
        # offers the next one when the phone cannot open the first)
        self.urls = ["http://%s:%d/k/%s" % (h, self.port, self.token) for h in (hosts or ["127.0.0.1"])]
        self.url = self.urls[0]
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="loki-phone-handoff").start()
        timer = threading.Timer(ttl_s, self.stop)
        timer.daemon = True      # an open page never keeps LOKI (or a test) from exiting
        timer.start()

    def expired(self) -> bool:
        return time.time() - self.created > self.ttl_s or bool(self.result and self.result.get("ok"))

    def form(self, error: str = "") -> str:
        return ("<!doctype html><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\">"
                "<title>Send a key to LOKI</title><body style=\"background:#1f1f24;color:#e6e9ee;"
                "font:17px -apple-system,system-ui,sans-serif;margin:0;padding:28px 18px\">"
                "<h2 style=\"margin:0 0 6px\">Send a key to LOKI</h2>"
                "<p style=\"color:#9aa0aa;margin:0 0 18px\">%s - goes straight to your computer, once.</p>%s"
                "%s<form method=post><input name=key type=password autocomplete=off autofocus placeholder=\"Paste the API key\" "
                "style=\"width:100%%;box-sizing:border-box;font-size:17px;padding:14px;border-radius:12px;border:1px solid #34343c;"
                "background:#2a2a31;color:#e6e9ee\"><button style=\"margin-top:14px;width:100%%;padding:14px;font-size:17px;"
                "border:0;border-radius:12px;background:#e6e9ee;color:#1f1f24;font-weight:600\">Send to LOKI</button></form>"
                "<p style=\"color:#9aa0aa;font-size:13px;margin-top:18px\">Plain HTTP on your home network. "
                "This page stops working after one key or five minutes.</p></body>"
                % (html.escape(self.label), ("<p style=\"color:#ff7777\">%s</p>" % html.escape(error)) if error else "",
                   ("<p style=\"margin:0 0 16px\"><a href=\"%s\" target=_blank rel=noopener style=\"color:#8ab4ff\">"
                    "1. Get a key from %s</a> (copy it), then come back here.</p>" % (html.escape(self.keys_url, quote=True), html.escape(self.label)))
                   if self.keys_url else ""))

    def status(self) -> dict:
        return {"ok": True, "provider": self.provider, "url": self.url, "urls": self.urls, "done": bool(self.result),
                "result": self.result, "expires_in": max(0, int(self.ttl_s - (time.time() - self.created)))}

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:  # noqa: BLE001
            pass


HANDOFFS: dict = {}   # token -> PhoneHandoff


HANDOFF_PORT = 8770


def network_hint(run=None) -> str:
    """Why a phone on the same Wi-Fi may still not open the page, when we can tell.

    On Windows a Wi-Fi marked "Public" blocks every incoming connection (Python's firewall
    rule is for Private networks only), so the phone just spins. Read-only check."""
    if os.name != "nt" and run is None:
        return ""
    import subprocess  # pylint: disable=import-outside-toplevel
    run = run or subprocess.run
    try:
        out = run(["powershell", "-NoProfile", "-Command", "(Get-NetConnectionProfile).NetworkCategory"],
                  capture_output=True, text=True, timeout=4, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        categories = (out.stdout or "").split()
    except Exception:  # noqa: BLE001
        return ""
    if "Public" in categories and "Private" not in categories:
        return ("Windows treats this Wi-Fi as a Public network, which blocks the phone. In Windows Settings > "
                "Network & internet > Wi-Fi > this network, choose Private - or just copy the key and use Paste here.")
    return ""


def handoff_start(provider: str, label: str, connect, host_ip, private_client, keys_url: str = "") -> dict:
    for token in [t for t, h in HANDOFFS.items() if h.expired()]:
        HANDOFFS.pop(token).stop()
    try:
        port_number = int(os.environ.get("LOKI_HANDOFF_PORT", HANDOFF_PORT))
    except ValueError:
        port_number = HANDOFF_PORT
    handoff = PhoneHandoff(provider, label, connect, host_ip, private_client, keys_url=keys_url, port_number=port_number)
    HANDOFFS[handoff.token] = handoff
    return {"id": handoff.token, **handoff.status()}


def handoff_status(token: str) -> dict:
    handoff = HANDOFFS.get(str(token or ""))
    return handoff.status() if handoff else {"ok": False, "error": "expired"}
