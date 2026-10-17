"""LOKI Studio's loopback server: its window (studio/ui) and the API behind it.

127.0.0.1 only, a fresh bearer token per start (the window gets it in the URL fragment, which is
never sent to a server; LOKI's "open Studio" button reads harness_data/studio/studio.token), a Host
check against DNS rebinding, and a strict CSP (script-src 'self': no inline scripts).

  GET  /api/ping                          alive
  GET  /api/state                         sessions, the model driving, LOKI's status, the pin
  GET  /api/session?id=&after=            one session: its summary + events after an id
  POST /api/session/new     {text}        a new session (its own worktree) and start working
  POST /api/session/send    {id, text}    a follow-up in the SAME session (same worktree/branch)
  POST /api/session/stop    {id}
  POST /api/session/approve {id, approval, yes}
  GET  /api/session/diff?id=
  POST /api/session/check   {id, suite?}  run the tests (tools/ship.py --check) in its worktree
  POST /api/session/ship    {id, message, confirm: true}   the owner's Ship it (tools/ship.py)
  POST /api/session/discard {id, confirm: true}
  GET  /api/loki/logs?which=&lines=
  POST /api/loki/start | /api/loki/restart | /api/loki/rollback {confirm: true}
  POST /api/raise                         bring the window to the front (LOKI's button)
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import studio_paths
import studio_models
import studio_control
import studio_pin

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
MAX_BODY = 64_000


class StudioServer:
    def __init__(self, studio, port: int = 0, ui_dir: Path | None = None, control=studio_control,
                 on_raise: Callable | None = None):
        self.studio = studio
        self.control = control
        self.ui = Path(ui_dir or studio_paths.UI)
        self.token = secrets.token_urlsafe(32)
        self.on_raise = on_raise or (lambda: None)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", int(port or 0)), self._handler())
        self.port = self.httpd.server_address[1]
        self.allowed_hosts = {"127.0.0.1:%d" % self.port, "localhost:%d" % self.port}
        self.thread: threading.Thread | None = None
        self._status_cache = {"t": 0.0, "value": {}}

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d/#token=%s" % (self.port, self.token)

    def start(self) -> None:
        home = self.studio.home
        (home / "studio.token").write_text(self.token, encoding="utf-8")
        try:
            os.chmod(home / "studio.token", 0o600)
        except OSError:
            pass
        (home / "running.json").write_text(json.dumps({"port": self.port, "pid": os.getpid(), "t": time.time()}),
                                           encoding="utf-8")
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="studio-http")
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        for name in ("studio.token", "running.json"):
            try:
                (self.studio.home / name).unlink()
            except OSError:
                pass

    def loki_status(self) -> dict:
        if time.time() - self._status_cache["t"] > 3:
            try:
                value = self.control.status(self.studio.repo, self.studio.data)
            except Exception as exc:  # noqa: BLE001
                value = {"running": False, "why": str(exc)}
            self._status_cache = {"t": time.time(), "value": value}
        return self._status_cache["value"]

    # ------------------------------------------------------------- routes
    def get(self, path: str, query: dict) -> tuple:
        q = {k: (v[0] if v else "") for k, v in query.items()}
        if path == "/api/ping":
            return 200, {"ok": True, "service": "loki-studio"}
        if path == "/api/state":
            rec = studio_pin.record(self.studio.data)
            return 200, {"ok": True, "sessions": self.studio.list(), "driver": studio_models.driver_status(),
                         "loki": self.loki_status(), "pin": {"commit": str(rec.get("commit", ""))[:12],
                                                             "running_from": str(studio_paths.CODE)},
                         "repo": str(self.studio.repo)}
        if path == "/api/session":
            s = self.studio.get(q.get("id"))
            after = int(q.get("after") or 0)
            with s.lock:
                events = [e for e in s.events if e["id"] > after][-400:]
            return 200, {"ok": True, "session": s.summary(), "events": events,
                         "working": bool(s.thread and s.thread.is_alive())}
        if path == "/api/session/diff":
            return 200, {"ok": True, "diff": self.studio.diff(q.get("id"))[:400_000]}
        if path == "/api/loki/logs":
            return 200, {"ok": True, "text": self.control.logs(q.get("which") or "engine", int(q.get("lines") or 200),
                                                              self.studio.data)}
        return 404, {"ok": False, "error": "unknown endpoint"}

    def post(self, path: str, data: dict) -> tuple:
        st = self.studio
        if path == "/api/raise":
            self.on_raise()
            return 200, {"ok": True}
        if path == "/api/session/new":
            s = st.new(str(data.get("text") or ""))
            return 200, {"ok": True, "session": s.summary()}
        if path == "/api/session/send":
            return 200, {"ok": True, **st.send(data.get("id"), str(data.get("text") or ""))}
        if path == "/api/session/stop":
            st.stop(data.get("id"))
            return 200, {"ok": True}
        if path == "/api/session/approve":
            return 200, {"ok": st.approve(data.get("id"), str(data.get("approval") or ""), bool(data.get("yes")))}
        if path == "/api/session/check":
            sid = data.get("id")
            st.get(sid)
            threading.Thread(target=st.check, args=(sid, str(data.get("suite") or "")), daemon=True).start()
            return 200, {"ok": True, "started": True}
        if path == "/api/session/ship":
            if data.get("confirm") is not True:
                return 400, {"ok": False, "error": "shipping needs the owner's confirmation"}
            sid = data.get("id")
            st.get(sid)
            threading.Thread(target=st.ship, args=(sid, str(data.get("message") or "")), kwargs={"approved": True},
                             daemon=True).start()
            return 200, {"ok": True, "started": True}
        if path == "/api/session/discard":
            if data.get("confirm") is not True:
                return 400, {"ok": False, "error": "discarding needs the owner's confirmation"}
            st.discard(data.get("id"))
            return 200, {"ok": True}
        if path in ("/api/loki/start", "/api/loki/restart", "/api/loki/rollback"):
            if data.get("confirm") is not True:
                return 400, {"ok": False, "error": "needs the owner's confirmation"}
            self._status_cache["t"] = 0.0
            if path.endswith("/start"):
                return 200, self.control.start(st.repo, st.data)
            if path.endswith("/restart"):
                return 200, self.control.restart(st.repo, st.data)
            return 200, self.control.rollback(st.repo)
        return 404, {"ok": False, "error": "unknown endpoint"}

    # ------------------------------------------------------------- HTTP
    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # quiet
                return

            def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Security-Policy", CSP)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, payload: Any) -> None:
                self._send(code, json.dumps(payload, default=str).encode("utf-8"))

            def _host_ok(self) -> bool:
                if self.headers.get("Host", "") not in server.allowed_hosts:
                    self._json(403, {"ok": False, "error": "host not allowed"})
                    return False
                return True

            def _auth(self) -> bool:
                given = self.headers.get("Authorization", "")
                if not secrets.compare_digest(given, "Bearer " + server.token):
                    self._json(401, {"ok": False, "error": "bad token"})
                    return False
                return True

            def _static(self, path: str) -> bool:
                if path == "/":
                    rel = "index.html"
                elif path.startswith("/ui/"):
                    rel = path[4:]
                else:
                    return False
                target = (server.ui / rel).resolve()
                if server.ui.resolve() not in target.parents or not target.is_file():
                    self._json(404, {"ok": False, "error": "not found"})
                    return True
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                self._send(200, target.read_bytes(), ctype)
                return True

            def _route(self, method: str) -> None:
                if not self._host_ok():
                    return
                parsed = urlparse(self.path)
                if method == "GET" and self._static(parsed.path):
                    return
                if not self._auth():
                    return
                try:
                    if method == "GET":
                        code, payload = server.get(parsed.path, parse_qs(parsed.query))
                    else:
                        length = int(self.headers.get("Content-Length", "0") or 0)
                        if length > MAX_BODY:
                            self._json(413, {"ok": False, "error": "too large"})
                            return
                        raw = self.rfile.read(length) if length else b"{}"
                        data = json.loads(raw.decode("utf-8") or "{}")
                        if not isinstance(data, dict):
                            raise ValueError("the body must be a JSON object")
                        code, payload = server.post(parsed.path, data)
                except KeyError as exc:
                    code, payload = 404, {"ok": False, "error": str(exc).strip("'\"")}
                except (ValueError, RuntimeError) as exc:
                    code, payload = 400, {"ok": False, "error": str(exc)}
                except Exception as exc:  # noqa: BLE001
                    code, payload = 500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
                self._json(code, payload)

            def do_GET(self):  # noqa: N802
                self._route("GET")

            def do_POST(self):  # noqa: N802
                self._route("POST")

        return Handler
