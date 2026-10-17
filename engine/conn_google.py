"""Google sign-in for Gmail and Google Calendar (OAuth 2.0 for desktop apps: loopback + PKCE).

Why not the device-code flow: Google's "TV and limited-input" flow does not allow the Gmail or
Calendar scopes. Desktop apps use the loopback flow instead (RFC 8252): LOKI opens Google's
consent page in the browser, Google redirects to http://127.0.0.1:<random port>/ on this computer,
and LOKI swaps the one-time code (with its PKCE verifier) for a refresh token. Nothing listens
longer than the sign-in (10 minutes at most) and only on the loopback address.

The owner creates the OAuth client once (Google Cloud console > APIs & Services > Credentials >
Create OAuth client ID > Desktop app; enable the Gmail API and the Google Calendar API) and pastes
its client id and secret in Settings > Tools > Google. A Desktop client's "secret" is not really
secret (Google says so), but LOKI stores it as a SECRET setting anyway. The refresh token IS secret:
saved as GOOGLE_REFRESH_TOKEN in harness_data/.env, never shown, never logged.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable

import urllib.error

import connectors

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = {
    "mail": "https://mail.google.com/",                                  # IMAP/SMTP with XOAUTH2
    "calendar": "https://www.googleapis.com/auth/calendar.events",      # read + create events
}
SIGNIN_TIMEOUT_S = 600

SPEC = {
    "id": "google",
    "label": "Google account (Gmail + Calendar)",
    "about": "One Google sign-in for Gmail (read, search, drafts; sending asks) and Google Calendar "
             "(read; creating an event asks). Uses your own OAuth client - see the steps below.",
    "tool": "",
    "writes": [],
    "signin": "google",
    "help": "Google Cloud console > APIs & Services: enable Gmail API + Google Calendar API; OAuth consent "
            "screen (External, add yourself as a test user); Credentials > Create OAuth client ID > Desktop "
            "app. Paste the client id and secret here, Save, then Sign in with Google.",
    "fields": [
        {"key": "GOOGLE_CLIENT_ID", "label": "OAuth client id (Desktop app)", "kind": "text"},
        {"key": "GOOGLE_CLIENT_SECRET", "label": "OAuth client secret", "kind": "secret"},
        {"key": "GOOGLE_REFRESH_TOKEN", "label": "Refresh token (set by Sign in with Google)", "kind": "secret"},
    ],
}

OPENER = urllib.request.urlopen
_TOKEN_CACHE: dict = {"token": "", "exp": 0.0, "for": ""}
FLOWS: dict = {}


class GoogleError(Exception):
    pass


def status(source: dict | None = None) -> dict:
    if not connectors.get("GOOGLE_CLIENT_ID", source):
        return {"configured": False, "detail": "no OAuth client id yet"}
    if not connectors.get("GOOGLE_REFRESH_TOKEN", source):
        return {"configured": False, "detail": "client saved - now Sign in with Google"}
    return {"configured": True, "detail": "signed in"}


def test(source: dict | None = None) -> dict:
    try:
        access_token(source, force=True)
    except GoogleError as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": True, "detail": "Google answered with a fresh access token"}


def _post_form(url: str, fields: dict, timeout: float = 20.0) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with OPENER(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            body = {}
        raise GoogleError("Google refused (HTTP %s): %s" % (exc.code, body.get("error_description") or body.get("error") or "")) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GoogleError("cannot reach Google (%s)" % getattr(exc, "reason", exc)) from exc


def access_token(source: dict | None = None, force: bool = False) -> str:
    """A fresh access token from the saved refresh token (cached until a minute before it expires)."""
    refresh = connectors.get("GOOGLE_REFRESH_TOKEN", source)
    client = connectors.get("GOOGLE_CLIENT_ID", source)
    if not refresh or not client:
        raise GoogleError("Google is not signed in - Settings > Tools > Google account > Sign in with Google")
    key = hashlib.sha256((client + refresh).encode()).hexdigest()
    if not force and _TOKEN_CACHE["for"] == key and _TOKEN_CACHE["exp"] > time.time() + 60:
        return _TOKEN_CACHE["token"]
    body = _post_form(TOKEN_URL, {"client_id": client, "client_secret": connectors.get("GOOGLE_CLIENT_SECRET", source),
                                  "refresh_token": refresh, "grant_type": "refresh_token"})
    token = str(body.get("access_token") or "")
    if not token:
        raise GoogleError("Google gave no access token - sign in again")
    _TOKEN_CACHE.update(token=token, exp=time.time() + float(body.get("expires_in") or 3000), **{"for": key})
    return token


def _pkce() -> tuple:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def auth_url(client_id: str, redirect: str, state: str, challenge: str, scopes: list) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": " ".join(scopes),
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "consent"})


def start_signin(write_env: Callable[[dict], None], source: dict | None = None, open_browser=None,
                 scopes: list | None = None, port: int = 0) -> dict:
    """Start the loopback sign-in. Returns {ok, state, url}; the browser is opened when open_browser is given."""
    client = connectors.get("GOOGLE_CLIENT_ID", source)
    if not client:
        return {"ok": False, "error": "paste the OAuth client id (and secret) and Save first"}
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(16)
    flow = {"state": state, "done": False, "ok": False, "error": "", "started": time.time()}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a):   # never log the code
            return

        def do_GET(self):  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got_state = (query.get("state") or [""])[0]
            if not secrets.compare_digest(got_state, state):
                self._answer(400, "This sign-in link is not the one LOKI started.")
                return
            if query.get("error"):
                flow.update(done=True, error="Google said: %s" % query["error"][0])
                self._answer(200, "Sign-in cancelled. You can close this tab.")
                return
            code = (query.get("code") or [""])[0]
            try:
                body = _post_form(TOKEN_URL, {"client_id": client, "client_secret": connectors.get("GOOGLE_CLIENT_SECRET", source),
                                              "code": code, "code_verifier": verifier, "grant_type": "authorization_code",
                                              "redirect_uri": redirect})
                refresh = str(body.get("refresh_token") or "")
                if not refresh:
                    raise GoogleError("Google sent no refresh token (remove LOKI's access at "
                                      "myaccount.google.com/permissions and sign in again)")
                write_env({"GOOGLE_REFRESH_TOKEN": refresh})
                if body.get("access_token"):
                    _TOKEN_CACHE.update(token=str(body["access_token"]), exp=time.time() + float(body.get("expires_in") or 3000),
                                        **{"for": hashlib.sha256((client + refresh).encode()).hexdigest()})
                flow.update(done=True, ok=True)
                self._answer(200, "LOKI is signed in to Google. You can close this tab.")
            except GoogleError as exc:
                flow.update(done=True, error=str(exc))
                self._answer(200, "Sign-in failed: %s" % exc)

        def _answer(self, code: int, text: str) -> None:
            raw = ("<!doctype html><meta charset=utf-8><title>LOKI</title><p style='font:16px system-ui'>%s</p>"
                   % text.replace("<", "&lt;")).encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            threading.Thread(target=server.shutdown, daemon=True).start()

    server = http.server.HTTPServer(("127.0.0.1", int(port or 0)), Handler)
    redirect = "http://127.0.0.1:%d/" % server.server_address[1]

    def serve() -> None:
        server.timeout = 1.0
        deadline = time.time() + SIGNIN_TIMEOUT_S
        try:
            while not flow["done"] and time.time() < deadline:
                server.handle_request()
        finally:
            server.server_close()
            if not flow["done"]:
                flow.update(done=True, error="the sign-in timed out")

    threading.Thread(target=serve, daemon=True, name="loki-google-signin").start()
    url = auth_url(client, redirect, state, challenge, scopes or list(SCOPES.values()))
    FLOWS[state] = flow
    if open_browser is not None:
        try:
            open_browser(url)
        except Exception:  # noqa: BLE001 - the window shows the link too
            pass
    return {"ok": True, "state": state, "url": url}


def signin_status(state: str) -> dict:
    flow = FLOWS.get(str(state or ""))
    if flow is None:
        return {"ok": False, "error": "no such sign-in"}
    return {"ok": True, "done": flow["done"], "signed_in": flow["ok"], "error": flow["error"]}


def api(method: str, url: str, body: dict | None = None, source: dict | None = None, timeout: float = 20.0) -> dict:
    """One Google REST call with the access token. Raises GoogleError with a plain reason."""
    token = access_token(source)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with OPENER(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8") or "{}").get("error", {})
            detail = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        except Exception:  # noqa: BLE001
            detail = ""
        raise GoogleError("Google answered HTTP %s %s" % (exc.code, detail)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GoogleError("cannot reach Google (%s)" % getattr(exc, "reason", exc)) from exc


def xoauth2(user: str, token: str) -> bytes:
    """The SASL XOAUTH2 string IMAP/SMTP want (Gmail)."""
    return ("user=%s\x01auth=Bearer %s\x01\x01" % (user, token)).encode()


connectors.register(__import__(__name__))
