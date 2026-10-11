"""Loki Cloud auth service (minimal).

Handles "Sign in with Google" for the Loki editor plugin and issues Loki
session tokens. Stdlib only -- no third-party dependencies.

Flow
  1. Plugin opens   GET /auth/google/start?redirect_uri=http://127.0.0.1:PORT/callback
  2. We 302 to Google's consent screen (Web OAuth client).
  3. Google calls    GET /auth/google/callback?code=...&state=...
  4. We exchange the code, mint a one-time code, and 302 back to redirect_uri.
  5. Plugin POSTs    /auth/session {code}  ->  {token, user}
  6. Plugin uses the token as a Bearer for hosted agent calls.

Config (env or cloud/.env):
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
  LOKI_CLOUD_BASE_URL   e.g. http://localhost:8788
  LOKI_CLOUD_PORT       default 8788
"""
from __future__ import annotations

import json
import os
import base64
import hashlib
import secrets
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent


def load_env() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
BASE_URL = os.getenv("LOKI_CLOUD_BASE_URL", "http://localhost:8788")
PORT = int(os.getenv("LOKI_CLOUD_PORT", "8788"))
UPSTREAM_BASE = os.getenv("UPSTREAM_BASE", "https://openrouter.ai/api/v1")
UPSTREAM_KEY = os.getenv("UPSTREAM_API_KEY", "")
UPSTREAM_MODEL = os.getenv("UPSTREAM_MODEL", "poolside/laguna-s-2.1:free")

# In-memory stores; replace with a database for production.
PENDING: dict[str, dict] = {}   # state -> {redirect_uri}
ONE_TIME: dict[str, dict] = {}  # one-time code -> {user}
SESSIONS: dict[str, dict] = {}  # session token -> {user, created}
LOCK = threading.Lock()
SESSIONS_FILE = ROOT / "sessions.json"


def _load_sessions() -> None:
    try:
        SESSIONS.update(json.loads(SESSIONS_FILE.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        pass


def _save_sessions() -> None:
    try:
        SESSIONS_FILE.write_text(json.dumps(SESSIONS), encoding="utf-8")
    except OSError:
        pass


_load_sessions()


def _cookie_session(handler: "Handler") -> None:
    pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args) -> None:
        import sys
        sys.stderr.write("[cloud] " + self.command + " " + self.path + chr(10))
        sys.stderr.flush()

    def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"))

    def _redirect(self, url: str) -> None:
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/health":
            return self._json(200, {"ok": True, "service": "loki-cloud", "google": bool(CLIENT_ID), "upstream": bool(UPSTREAM_KEY)})

        if parsed.path == "/auth/google/start":
            redirect_uri = (query.get("redirect_uri") or [""])[0]
            if not redirect_uri:
                return self._json(400, {"ok": False, "error": "redirect_uri is required"})
            if not CLIENT_ID:
                return self._json(500, {"ok": False, "error": "GOOGLE_CLIENT_ID is not configured"})
            state = secrets.token_urlsafe(24)
            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
            with LOCK:
                PENDING[state] = {"redirect_uri": redirect_uri, "created": time.time(), "verifier": verifier}
            params = {
                "client_id": CLIENT_ID,
                "redirect_uri": BASE_URL + "/auth/google/callback",
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent",
            }
            return self._redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params))

        if parsed.path == "/auth/google/callback":
            return self._google_callback(query)

        if parsed.path == "/v1/models":
            if not self._session():
                return self._json(401, {"ok": False, "error": "sign in first"})
            try:
                req = urllib.request.Request(UPSTREAM_BASE + "/models",
                                             headers={"Authorization": "Bearer " + UPSTREAM_KEY})
                payload = urllib.request.urlopen(req, timeout=20).read()
                return self._send(200, payload)
            except Exception as exc:  # noqa: BLE001
                return self._json(502, {"ok": False, "error": str(exc)})

        if parsed.path == "/auth/me":
            token = self._bearer()
            with LOCK:
                session = SESSIONS.get(token or "")
            if not session:
                return self._json(401, {"ok": False, "error": "not signed in"})
            return self._json(200, {"ok": True, "user": session["user"]})

        return self._json(404, {"ok": False, "error": "unknown endpoint"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"ok": False, "error": "invalid JSON"})

        if parsed.path == "/v1/chat/completions":
            if not self._session():
                return self._json(401, {"ok": False, "error": "sign in first"})
            if not UPSTREAM_KEY:
                return self._json(500, {"ok": False, "error": "UPSTREAM_API_KEY is not configured"})
            body = dict(data)
            if not body.get("model") or body.get("model") == "auto":
                body["model"] = UPSTREAM_MODEL
            try:
                req = urllib.request.Request(
                    UPSTREAM_BASE + "/chat/completions",
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json",
                             "Authorization": "Bearer " + UPSTREAM_KEY})
                payload = urllib.request.urlopen(req, timeout=120).read()
                return self._send(200, payload)
            except urllib.error.HTTPError as exc:
                return self._send(exc.code, exc.read())
            except Exception as exc:  # noqa: BLE001
                return self._json(502, {"ok": False, "error": str(exc)})

        if parsed.path == "/auth/session":
            code = data.get("code", "")
            with LOCK:
                entry = ONE_TIME.pop(code, None)
            if not entry:
                return self._json(400, {"ok": False, "error": "invalid or used code"})
            token = secrets.token_urlsafe(32)
            with LOCK:
                SESSIONS[token] = {"user": entry["user"], "created": time.time()}
                _save_sessions()
            return self._json(200, {"ok": True, "token": token, "user": entry["user"]})

        return self._json(404, {"ok": False, "error": "unknown endpoint"})

    def _session(self) -> dict | None:
        token = self._bearer()
        with LOCK:
            return SESSIONS.get(token or "")

    def _bearer(self) -> str:
        header = self.headers.get("Authorization", "")
        return header[7:] if header.startswith("Bearer ") else ""

    def _google_callback(self, query: dict) -> None:
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        with LOCK:
            pending = PENDING.pop(state, None)
        if not code or not pending:
            return self._json(400, {"ok": False, "error": "bad callback"})

        fields = {
            "code": code,
            "client_id": CLIENT_ID,
            "redirect_uri": BASE_URL + "/auth/google/callback",
            "grant_type": "authorization_code",
            "code_verifier": pending.get("verifier", ""),
        }
        if CLIENT_SECRET:  # confidential (Web) client; omit for a Desktop client (PKCE only)
            fields["client_secret"] = CLIENT_SECRET
        token_payload = urllib.parse.urlencode(fields).encode("utf-8")
        try:
            req = urllib.request.Request("https://oauth2.googleapis.com/token", data=token_payload)
            tokens = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
            id_token = tokens.get("id_token", "")
            claims = _decode_jwt_payload(id_token)
        except Exception as exc:  # noqa: BLE001
            return self._json(502, {"ok": False, "error": "google exchange failed: %s" % exc})

        user = {"email": claims.get("email", ""), "name": claims.get("name", ""), "sub": claims.get("sub", "")}
        one_time = secrets.token_urlsafe(24)
        with LOCK:
            ONE_TIME[one_time] = {"user": user, "created": time.time()}
        joiner = "&" if "?" in pending["redirect_uri"] else "?"
        return self._redirect("%s%scode=%s" % (pending["redirect_uri"], joiner, one_time))


def _decode_jwt_payload(token: str) -> dict:
    import base64
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    padding = "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(parts[1] + padding).decode("utf-8"))


def main() -> None:
    print("[loki-cloud] auth service on %s (google client: %s)" % (BASE_URL, "set" if CLIENT_ID else "MISSING"))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
