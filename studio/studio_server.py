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
  GET  /api/destination                   where this is going: the stored choice, gh's user, the default
  POST /api/destination {kind, name?, visibility?, confirm: true}   loki | fork | app | local (studio_destination.py)
  GET  /api/loki/settings                 LOKI's providers, General settings, capabilities, evolve list (via its bridge)
  POST /api/loki/settings {what, args, confirm: true}  one change (studio_control.settings_change)

The agent API (the window AND the Godot plugin's dock use it; docs/STUDIO.md):
  POST /api/session/new  {text, mode?, model?, project? | editor?, approve_edits?}  project = a Godot project
  POST /api/session/mode {id, mode}   default | plan | ask          POST /api/session/model {id, model}
  POST /api/session/answer {id, question, answer}                  the agent's ask_owner question
  GET  /api/session/checkpoints?id=   POST /api/session/undo {id, turn}   POST /api/session/fork {id}
  POST /api/session/queue/clear {id}  POST /api/session/approve_edits {id, on}
  GET  /api/commands?id=   slash commands + templates     GET /api/mentions?id=&q=   @ completion
  GET  /api/models         every model a session can use  GET /api/godot/docs?q=     the Godot reference
The Godot editor link (studio_godot.py; the plugin's bridge.gd):
  POST /api/godot/hello | /api/godot/result | /api/godot/event     GET /api/godot/poll?editor=&wait=
  GET  /api/godot/editors   POST /api/godot/call {action, args, project?}   POST /api/godot/tool {tool, args, project?}
  POST /api/godot/install {project, confirm: true}   copy the plugin into a Godot project and enable it
"""
from __future__ import annotations

import json
import subprocess
import mimetypes
import os
try:   # no console windows on Windows for anything started from here (engine/no_console.py)
    sys_path_engine = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")
    import sys as _sys
    if sys_path_engine not in _sys.path:
        _sys.path.append(sys_path_engine)
    import no_console  # noqa: F401
except Exception:  # noqa: BLE001
    pass
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
import studio_godot
import studio_commands
import studio_tools
import godot_docs

# frame-ancestors: LOKI's own window shows Studio as its Studio tab (app/ui/modebar.js) - a loopback page only; the
# token still arrives only in the URL fragment, so a page that frames Studio without it can do nothing.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'self' http://127.0.0.1:* http://localhost:*; base-uri 'none'; form-action 'none'")
MAX_BODY = 64_000
MAX_EDITOR_BODY = 16_000_000          # the editor's results carry screenshots
EDITOR_TOOLS = {"editor_errors", "screenshot", "playtest_step", "find_lag", "project_index", "project_graph", "godot_docs"}



def _code_commit() -> str:
    """The commit this Studio's code is (its pinned copy or the checkout): LOKI's window restarts a
    Studio whose code is older than the one it should run (engine/studio_api.embed)."""
    try:
        import studio_paths  # pylint: disable=import-outside-toplevel
        out = subprocess.run(["git", "-C", str(studio_paths.CODE), "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=5, check=False)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""

class StudioServer:
    def __init__(self, studio, port: int = 0, ui_dir: Path | None = None, control=studio_control,
                 on_raise: Callable | None = None, connect_file: Path | None = None):
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
        self.connect_file = Path(connect_file) if connect_file else None
        self.hub = studio.hub

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
        (home / "running.json").write_text(json.dumps({"port": self.port, "pid": os.getpid(), "t": time.time(),
                                                       "code": _code_commit()}), encoding="utf-8")
        if self.connect_file is not None:   # how the Godot plugin (in any project) finds this Studio
            studio_godot.write_connect(self.connect_file, "http://127.0.0.1:%d" % self.port, self.token)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="studio-http")
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.connect_file is not None:
            studio_godot.remove_connect(self.connect_file, self.token)
        for name in ("studio.token", "running.json"):
            try:
                (self.studio.home / name).unlink()
            except OSError:
                pass

    def _loki_bridge(self, method: str, path: str, body: dict | None = None) -> tuple:
        """The running LOKI's own API (its bridge token, as the LOKI MCP API uses it)."""
        import loki_mcp  # pylint: disable=import-outside-toplevel
        api = loki_mcp.LokiAPI(worktree=self.studio.repo, repo=self.studio.repo, data=self.studio.data)
        return api.bridge(method, path, body, timeout=20.0)

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
                         "repo": str(self.studio.repo), "editors": self.hub.connected()}
        if path == "/api/godot/poll":
            return 200, {"ok": True, "commands": self.hub.poll(q.get("editor"), float(q.get("wait") or 20))}
        if path == "/api/godot/editors":
            return 200, {"ok": True, "editors": self.hub.connected(), "actions": studio_godot.describe_actions()}
        if path == "/api/godot/docs":
            return 200, {"ok": True, "output": godot_docs.answer(q.get("q") or "", self.studio.data),
                         "status": godot_docs.status(self.studio.data)}
        if path == "/api/models":
            return 200, {"ok": True, "models": studio_models.choices(), "driver": studio_models.driver_status()}
        if path == "/api/commands":
            root = None
            if q.get("id"):
                s = self.studio.get(q.get("id"))
                root = s.work_root if s.kind == "godot" else None
            return 200, {"ok": True, "commands": studio_commands.listing(root, self.studio.data)}
        if path == "/api/mentions":
            s = self.studio.get(q.get("id")) if q.get("id") else None
            root = s.work_root if s else Path(q.get("project") or self.studio.repo)
            return 200, {"ok": True, "items": studio_commands.complete(root, q.get("q") or "")}
        if path == "/api/shot":
            name = Path(q.get("path") or "")
            allowed = [(self.studio.home / "shots").resolve(), (self.studio.home / "images").resolve()]
            target = name.resolve()
            if not any(a in target.parents for a in allowed) or target.suffix.lower() != ".png" or not target.is_file():
                return 404, {"ok": False, "error": "no such picture"}
            import base64  # pylint: disable=import-outside-toplevel
            return 200, {"ok": True, "data": "data:image/png;base64," + base64.b64encode(target.read_bytes()).decode("ascii")}
        if path == "/api/session/checkpoints":
            s = self.studio.get(q.get("id"))
            return 200, {"ok": True, "checkpoints": [{k: r.get(k) for k in ("turn", "t", "label", "kind")} | {"files": sorted(r.get("files") or {})}
                                                     for r in self.studio.checkpoints(s).list()]}
        if path == "/api/session":
            s = self.studio.get(q.get("id"))
            after = int(q.get("after") or 0)
            with s.lock:
                events = [e for e in s.events if e["id"] > after][-400:]
            return 200, {"ok": True, "session": s.summary(), "events": events,
                         "working": bool(s.thread and s.thread.is_alive())}
        if path == "/api/session/diff":
            return 200, {"ok": True, "diff": self.studio.diff(q.get("id"))[:400_000]}
        if path == "/api/destination":
            return 200, {"ok": True, **self.studio.destination()}
        if path == "/api/loki/settings":
            return 200, self.control.settings_overview(self.studio.repo, self.studio.data)
        if path == "/api/loki/cleanup":   # Clean up: what could go in the running LOKI (engine/cleanup.py)
            status, data = self._loki_bridge("GET", "/cleanup")
            return (200, data) if status == 200 else (200, {"ok": False, "error": data.get("error") or "LOKI is not running"})
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
            project = str(data.get("project") or "")
            if not project and data.get("editor"):
                project = self.hub.get(data.get("editor")).project
            s = st.new(str(data.get("text") or ""), mode=str(data.get("mode") or "default"), model=str(data.get("model") or ""),
                       project=project, approve_edits=bool(data.get("approve_edits")))
            return 200, {"ok": True, "session": s.summary()}
        if path == "/api/session/send":
            return 200, {"ok": True, **st.send(data.get("id"), str(data.get("text") or ""))}
        if path == "/api/session/mode":
            return 200, {"ok": True, "session": st.set_mode(data.get("id"), str(data.get("mode") or ""))}
        if path == "/api/session/model":
            s = st.get(data.get("id"))
            return 200, {"ok": True, **st.command(s, "model", str(data.get("model") or "auto"))}
        if path == "/api/session/approve_edits":
            s = st.get(data.get("id"))
            return 200, {"ok": True, **st.command(s, "approve", "edits" if data.get("on") else "auto")}
        if path == "/api/session/answer":
            return 200, {"ok": st.answer(data.get("id"), str(data.get("question") or ""), str(data.get("answer") or ""))}
        if path == "/api/session/undo":
            res = st.undo(data.get("id"), int(data.get("turn") or 0))
            return 200, {"ok": bool(res.get("ok")), **({} if res.get("ok") else {"error": res.get("text")}), "text": res.get("text")}
        if path == "/api/session/fork":
            return 200, {"ok": True, "session": st.fork(data.get("id")).summary()}
        if path == "/api/session/queue/clear":
            return 200, {"ok": True, "cleared": st.clear_queue(data.get("id"))}
        if path == "/api/godot/hello":
            return 200, {"ok": True, **self.hub.hello(data)}
        if path == "/api/godot/result":
            self.hub.result(data.get("editor"), data)
            return 200, {"ok": True}
        if path == "/api/godot/event":
            self.hub.event(data.get("editor"), str(data.get("kind") or ""), data.get("data"))
            return 200, {"ok": True}
        if path == "/api/godot/call":
            action = str(data.get("action") or "")
            if action == "quit":
                return 400, {"ok": False, "error": "not from here"}
            try:
                res = self.hub.call(action, dict(data.get("args") or {}), project=str(data.get("project") or ""),
                                    eid=str(data.get("editor") or ""), timeout=float(data.get("timeout") or 30))
            except studio_godot.GodotError as exc:
                return 200, {"ok": False, "error": str(exc)}
            return 200, res
        if path == "/api/godot/tool":
            name = str(data.get("tool") or "")
            if name not in EDITOR_TOOLS:
                return 400, {"ok": False, "error": "tool is one of %s" % ", ".join(sorted(EDITOR_TOOLS))}
            project = str(data.get("project") or "") or next((e["project"] for e in self.hub.connected()), "")
            if not project:
                return 200, {"ok": False, "error": "no Godot project: give project= or connect an editor"}
            ctx = studio_tools.Ctx(root=Path(project), kind="godot", data=st.data, hub=self.hub, repo=st.repo)
            out = studio_tools.REGISTRY[name].fn(ctx, **dict(data.get("args") or {}))
            return 200, {"ok": not str(out).startswith("error"), "output": out}
        if path == "/api/godot/install":
            if data.get("confirm") is not True:
                return 400, {"ok": False, "error": "installing the plugin needs the owner's confirmation"}
            import install_godot_plugin  # pylint: disable=import-outside-toplevel
            return 200, install_godot_plugin.install(Path(str(data.get("project") or "")))
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
        if path == "/api/destination":
            if data.get("confirm") is not True:
                return 400, {"ok": False, "error": "choosing where this goes needs the owner's confirmation"}
            res = st.choose_destination(str(data.get("kind") or ""), str(data.get("name") or ""),
                                        "public" if data.get("visibility") == "public" else "private")
            if not res.get("ok") and res.get("how"):
                res["error"] = "%s\n\n%s" % (res.get("error", ""), res["how"])
            return 200, res
        if path == "/api/loki/cleanup/remove":
            if data.get("confirm") is not True:
                return 400, {"ok": False, "error": "removing chats or memories needs the owner's confirmation"}
            status, out = self._loki_bridge("POST", "/cleanup/remove", {"ids": list(data.get("ids") or [])})
            return (200, out) if status == 200 else (200, {"ok": False, "error": out.get("error") or "LOKI is not running"})
        if path == "/api/loki/settings":
            if data.get("confirm") is not True:
                return 400, {"ok": False, "error": "changing LOKI's settings needs the owner's confirmation"}
            return 200, self.control.settings_change(str(data.get("what") or ""), dict(data.get("args") or {}),
                                                     st.repo, st.data)
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
                # LOKI's window is cross-origin isolated (COEP require-corp) and shows Studio as its Studio tab, a
                # cross-origin frame: without these two headers the browser refuses to show Studio there at all
                self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
                self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
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
                        limit = MAX_EDITOR_BODY if parsed.path in ("/api/godot/result", "/api/godot/event") else MAX_BODY
                        if length > limit:
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
