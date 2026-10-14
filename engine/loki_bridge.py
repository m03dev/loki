"""Loopback API for the Loki engine.

Two front ends use it: the standalone Loki app (app/, which this server can also hand
its UI to) and command-line runs. Godot is an optional capability for game projects.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import traceback
import time
import uuid
from contextlib import AsyncExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs, quote
import urllib.request
import urllib.error
import webbrowser


MAX_BODY_BYTES = 32_000
MAX_PROMPT_CHARS = 16_000
CLOUD_URL = os.environ.get("LOKI_CLOUD_URL", "http://localhost:8788")


# Where the bridge keeps its log and sign-in session: the app passes its own folder
# with --state-dir; otherwise <workspace>/.loki.
STATE_DIR: Path | None = None


def _state_dir(project) -> Path:
    return STATE_DIR if STATE_DIR is not None else Path(project) / ".loki"


def _session_path(project) -> Path:
    return _state_dir(project) / "loki_session.json"


def load_session(project) -> dict:
    try:
        return json.loads(_session_path(project).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_session(project, data) -> None:
    try:
        path = _session_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


CLOUD_DIR = Path(__file__).resolve().parents[1] / "cloud"


def _cloud_is_local() -> bool:
    """True when CLOUD_URL points at this machine (safe to auto-start the cloud)."""
    return urlparse(CLOUD_URL).hostname in ("localhost", "127.0.0.1", "::1")


def _cloud_healthy() -> bool:
    try:
        with urllib.request.urlopen(CLOUD_URL + "/health", timeout=2) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001
        return False


def ensure_cloud_running() -> bool:
    """Best-effort: start the bundled local cloud auth service if it is not up.

    Only ever does this for a loopback CLOUD_URL, so a remote cloud is untouched.
    Returns True when the cloud answered a health probe afterwards.
    """
    import subprocess

    if _cloud_healthy():
        return True
    if not _cloud_is_local():
        return False
    server = CLOUD_DIR / "auth_server.py"
    if not server.is_file():
        return False
    env = dict(os.environ)
    port = urlparse(CLOUD_URL).port
    if port:
        env["LOKI_CLOUD_PORT"] = str(port)
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        log = open(CLOUD_DIR / "cloud.log", "a", encoding="utf-8")
    except OSError:
        log = subprocess.DEVNULL
    try:
        subprocess.Popen([sys.executable, str(server)], cwd=str(CLOUD_DIR), env=env,
                         stdout=log, stderr=subprocess.STDOUT, creationflags=creationflags)
    except OSError:
        return False
    for _ in range(20):
        if _cloud_healthy():
            return True
        time.sleep(0.25)
    return _cloud_healthy()


def validate_session(state, project) -> None:
    """Drop a saved session the cloud no longer accepts (e.g. cloud restarted).

    Only clears the session on an explicit 401, never when the cloud is simply
    unreachable, so an offline cloud does not sign the user out.
    """
    token = (state.session or {}).get("token", "")
    if not token:
        return
    req = urllib.request.Request(CLOUD_URL + "/auth/me", headers={"Authorization": "Bearer " + token})
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            state.session = {}
            save_session(project, {})
    except Exception:  # noqa: BLE001
        pass


def begin_sign_in(state, project) -> str:
    """Open the browser to Loki Cloud sign-in and capture the loopback code."""
    ensure_cloud_running()
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_a) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            query = parse_qs(urlparse(self.path).query)
            code = (query.get("code") or [""])[0]
            if code:
                try:
                    body = json.dumps({"code": code}).encode("utf-8")
                    req = urllib.request.Request(CLOUD_URL + "/auth/session", data=body,
                                                 headers={"Content-Type": "application/json"})
                    reply = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
                    state.session = {"token": reply.get("token", ""), "user": reply.get("user", {})}
                    save_session(project, state.session)
                    try:
                        state.agent.MODELS["cloud"].api_key = state.session["token"]
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    state.session = {}
            html = b"<html><body style='font-family:sans-serif;padding:40px'><h2>Loki: signed in</h2><p>Close this tab and return to Loki.</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Callback)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    redirect_uri = quote("http://127.0.0.1:%d/callback" % port, safe="")
    url = CLOUD_URL + "/auth/google/start?redirect_uri=" + redirect_uri
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    return url


MAX_TOOL_APPROVAL_SECONDS = 90
MAX_TASK_STEPS = 0  # 0 = no cap on task steps
HOST = "127.0.0.1"
# 8766 for a command-line engine; the app runs its own on 8767 (LOKI_PORT).
PORT = int(os.environ.get("LOKI_PORT", "8766") or 8766)
ALLOWED_ORIGINS = ("http://127.0.0.1", "http://localhost", "null",
                   f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}")
ALLOWED_HOSTS = (f"127.0.0.1:{PORT}", f"localhost:{PORT}")
UI_DIR: Path | None = None
UI_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
            ".json": "application/json; charset=utf-8"}
UI_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
          "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


def first_layer_status(agent) -> dict:
    """What answers the first layer right now, and its last verdict (for the UI)."""
    try:
        import laya  # pylint: disable=import-outside-toplevel
        laya_state = laya.status()
    except Exception:  # noqa: BLE001
        laya_state = {"enabled": False}
    server = laya_state.get("server") or {}
    if laya_state.get("backend") == "http":
        answering = "laya"
    elif laya_state.get("enabled") and server.get("state") == "ready":
        answering = "laya"
    else:
        answering = "rules"
    return {"answering": answering, "laya": laya_state,
            "last": dict(getattr(agent, "LAST_TRIAGE", {}) or {})}


def resolve_workspace(project_dir: str = "") -> Path:
    """The folder Loki works in: --project-dir, else $LOKI_WORKSPACE, else ~/LOKI Projects/Home."""
    chosen = (project_dir or os.environ.get("LOKI_WORKSPACE", "")).strip()
    return Path(chosen).expanduser().resolve() if chosen else (Path.home() / "LOKI Projects" / "Home").resolve()


def ui_file(ui_dir: Path, route: str) -> Path | None:
    """Map a UI route to a file inside ui_dir, refusing anything that escapes it."""
    relative = "index.html" if route == "/" else route[len("/ui/"):]
    if not relative or "\\" in relative or relative.startswith("/"):
        return None
    root = ui_dir.resolve()
    try:
        candidate = (root / relative).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if candidate.suffix not in UI_TYPES or not candidate.is_file():
        return None
    return candidate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Loki engine (loopback API)")
    parser.add_argument("--loki-root", required=True, help="the harness folder (loki.py)")
    parser.add_argument("--project-dir", default="",
                        help="workspace the file tools may touch (default: $LOKI_WORKSPACE or ~/LOKI Projects/Home)")
    parser.add_argument("--godot-exe", default="", help="optional; enables the Godot tools")
    parser.add_argument("--secret-file", required=True)
    parser.add_argument("--state-dir", default="", help="log + session folder (default: <project>/.godot)")
    parser.add_argument("--ui-dir", default="", help="serve the standalone app UI from this folder")
    return parser.parse_args(argv)


def write_secret_atomic(secret_path: Path, secret: str) -> None:
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = secret_path.with_name(secret_path.name + ".tmp")
    temporary.write_text(secret, encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, secret_path)


class BridgeState:
    def __init__(self, agent: Any, secret: str) -> None:
        self.agent = agent
        self.secret = secret
        self.loop: asyncio.AbstractEventLoop | None = None
        self.chat_lock: asyncio.Lock | None = None
        self.chat_request_lock = threading.Lock()
        self.task_request_lock = threading.Lock()
        self.lock = threading.Lock()
        self.pending: dict[str, Any] | None = None
        self.mcp_stack: AsyncExitStack | None = None
        self.profile: dict[str, str] = {"name": "", "notes": ""}
        self.session: dict[str, Any] = {}
        self.project: Path | None = None
        self.progress: list[dict[str, Any]] = []
        self.progress_seq: int = 0
        self.progress_chat_id: str = ""
        self.jobs: Any = None  # workers.Supervisor - background jobs (local / herdr / cua)
        self.brain: dict[str, Any] = {}  # last brain-map graph (its note ids are the only readable files)
        self.peer_server: Any = None  # peers.PeerServer when this machine listens for your other machines

    def try_busy(self) -> list | None:
        # acquire both request locks, or None when a request is in flight
        got: list = []
        for lock in (self.chat_request_lock, self.task_request_lock):
            if lock.acquire(blocking=False):
                got.append(lock)
            else:
                for held in got:
                    held.release()
                return None
        return got

    @staticmethod
    def release_busy(locks: list) -> None:
        for lock in locks:
            lock.release()

    def push_progress(self, chat_id: str, event: str, text: str) -> None:
        with self.lock:
            self.progress_seq += 1
            self.progress.append({"id": self.progress_seq, "chat_id": chat_id, "event": event, "text": text[:500]})
            self.progress = self.progress[-160:]

    def _start_heartbeat(self, chat_id: str) -> threading.Event:
        """Push a liveness event every few seconds so the window never looks frozen."""
        stop = threading.Event()
        started = time.monotonic()

        def beat() -> None:
            while not stop.wait(8.0):
                self.push_progress(chat_id, "thinking",
                                   "Still working... %ds elapsed" % int(time.monotonic() - started))

        threading.Thread(target=beat, name="loki-heartbeat", daemon=True).start()
        return stop

    async def request_chat(self, prompt: str) -> dict[str, Any]:
        if len(prompt) > MAX_PROMPT_CHARS:
            return {"ok": False, "error": "Prompt exceeds %d characters." % MAX_PROMPT_CHARS}
        assert self.chat_lock is not None
        async with self.chat_lock:
            chat_id = uuid.uuid4().hex
            with self.lock:
                self.progress_chat_id = chat_id
                self.progress.clear()
                self.progress_seq = 0
            self.push_progress(chat_id, "thinking", "Loki is thinking...")
            old_callback = getattr(self.agent, "loki_progress_callback", None)

            def callback(event: str, text: str) -> None:
                self.push_progress(chat_id, event, text)

            self.agent.loki_progress_callback = callback
            self.agent.clear_cancel()
            stop_heartbeat = self._start_heartbeat(chat_id)
            spent = getattr(self.agent, "LAST_USAGE", None)
            if isinstance(spent, list):
                spent.clear()
            try:
                answer = await self.agent.run_agent(prompt)
                self.push_progress(chat_id, "done", "Response ready.")
                return {"ok": True, "response": answer, "chat_id": chat_id, "usage": usage_total(spent)}
            except self.agent.BudgetExhausted as exc:
                self.push_progress(chat_id, "done", "Stopped: %s." % exc.reason)
                return {"ok": True, "response": "Stopped early: %s." % exc.reason, "chat_id": chat_id, "stopped": True}
            except self.agent.ModelUnavailable as exc:
                self.push_progress(chat_id, "error", exc.hint)
                return {"ok": False, "error": exc.hint, "chat_id": chat_id}
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                error = self.agent.friendly_error(exc)
                self.push_progress(chat_id, "error", error)
                return {"ok": False, "error": error, "chat_id": chat_id}
            finally:
                stop_heartbeat.set()
                if old_callback is None:
                    try:
                        delattr(self.agent, "loki_progress_callback")
                    except AttributeError:
                        pass
                else:
                    self.agent.loki_progress_callback = old_callback

    async def request_task(self, task: str, steps: int) -> dict[str, Any]:
        if len(task) > MAX_PROMPT_CHARS:
            return {"ok": False, "error": "Task exceeds %d characters." % MAX_PROMPT_CHARS}
        assert self.chat_lock is not None
        task_id: str = uuid.uuid4().hex
        async with self.chat_lock:
            with self.lock:
                self.progress_chat_id = task_id
                self.progress.clear()
                self.progress_seq = 0
            self.push_progress(task_id, "task", "Starting multi-step task (no step limit)." if steps <= 0 else "Starting multi-step task with up to %d turns." % steps)
            previous_steps: int = self.agent.GOAL_STEPS
            self.agent.GOAL_STEPS = steps
            old_callback = getattr(self.agent, "loki_progress_callback", None)

            def callback(event: str, text: str) -> None:
                self.push_progress(task_id, event, text)

            self.agent.loki_progress_callback = callback
            self.agent.clear_cancel()
            stop_heartbeat = self._start_heartbeat(task_id)
            try:
                summary = await self.agent.pursue_goal(task)
                text = (summary or "").strip() or "Task finished."
                self.push_progress(task_id, "done", text)
                return {"ok": True, "response": text, "chat_id": task_id}
            except self.agent.BudgetExhausted as exc:
                self.push_progress(task_id, "done", "Stopped: %s." % exc.reason)
                return {"ok": True, "response": "Stopped early: %s." % exc.reason, "chat_id": task_id, "stopped": True}
            except self.agent.ModelUnavailable as exc:
                self.push_progress(task_id, "error", exc.hint)
                return {"ok": False, "error": exc.hint, "chat_id": task_id}
            except Exception as exc:  # noqa: BLE001
                # Always leave a full traceback in the bridge log: a one-line message
                # in the panel is not enough to diagnose an unexpected failure.
                traceback.print_exc()
                detail: str = self.agent.friendly_error(exc)
                self.push_progress(task_id, "error", detail)
                return {"ok": False, "error": detail, "chat_id": task_id}
            finally:
                stop_heartbeat.set()
                self.agent.GOAL_STEPS = previous_steps
                if old_callback is None:
                    try:
                        delattr(self.agent, "loki_progress_callback")
                    except AttributeError:
                        pass
                else:
                    self.agent.loki_progress_callback = old_callback

    async def request_approval(self, tool_name: str, details: str) -> bool:
        self.push_progress(self.progress_chat_id, "approval", f"Approval required: {tool_name} {details[:350]}")
        ticket_id = uuid.uuid4().hex
        finished = threading.Event()
        ticket: dict[str, Any] = {"id": ticket_id, "tool": tool_name, "details": details[:10_000], "event": finished, "approved": False}
        with self.lock:
            self.pending = ticket
        try:
            accepted = await asyncio.to_thread(finished.wait, MAX_TOOL_APPROVAL_SECONDS)
            return bool(accepted and ticket["approved"])
        finally:
            with self.lock:
                if self.pending is ticket:
                    self.pending = None


def ecc_library(agent) -> dict:
    """The agents and skills currently vendored, aggregated across every library."""
    libraries = agent.vendor_library() if hasattr(agent, "vendor_library") else {}
    agents: list[str] = []
    skills: list[str] = []
    for data in libraries.values():
        agents += data.get("agents", [])
        skills += data.get("skills", [])
    return {"agents": sorted(set(agents)), "skills": sorted(set(skills)), "libraries": libraries}


def dump_godot_api(godot_exe: str, harness) -> None:
    """Generate extension_api.json (the Godot API reference) on first run."""
    target = harness / "extension_api.json"
    if target.is_file() or not godot_exe:
        return
    try:
        print("[loki-bridge] generating the Godot API reference (first run)...", flush=True)
        subprocess.run([godot_exe, "--headless", "--dump-extension-api"],
                       cwd=str(harness), timeout=240)
        print("  [api] extension_api.json ready" if target.is_file()
              else "  [api] dump produced nothing", flush=True)
    except Exception as exc:
        print(f"  [api] dump failed: {exc}", flush=True)


def peer_ui(state: "BridgeState", method: str, route: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Settings > Machines: link this Loki with your other machines (harness/peer_link.py)."""
    try:
        import peer_link  # pylint: disable=import-outside-toplevel
        result = peer_link.ui_route(state, state.agent, method, route, data)
    except Exception as exc:  # noqa: BLE001
        return 500, {"ok": False, "error": f"peer link failed: {type(exc).__name__}: {exc}"}
    return result if result is not None else (404, {"ok": False, "error": "Unknown endpoint."})


def initial_ecc_sync(agent) -> None:
    """Fetch the agent/skill libraries on first run so their tools work with no setup."""
    try:
        import ecc_sync
        if not ecc_sync.missing():
            return
    except Exception:
        pass
    try:
        print("[loki-bridge] fetching the agent/skill libraries (first run)...", flush=True)
        print("  " + agent.sync_ecc(False), flush=True)
    except Exception as exc:
        print(f"  [sync] initial sync failed: {exc}", flush=True)


def connection_inventory(agent: Any) -> dict[str, Any]:
    """Credential-free overview of model providers and optional local integrations."""
    providers: list[dict[str, str]] = []
    for name, cfg in agent.MODELS.items():
        if name in ("smart", "online") or name.startswith("local"):
            continue
        if cfg.base_url.startswith("cli-agent://"):
            ready = bool(agent.provider_configured(name))
            status = "CLI installed; sign-in not verified" if ready else "CLI not installed"
        elif "11434" in cfg.base_url:
            ready = bool(agent.provider_configured(name))
            status = "Ollama service detected" if ready else "Ollama not detected"
        else:
            key_ready = bool(str(cfg.api_key or "").strip())
            status = "Credential configured (connectivity not verified)" if key_ready else "Not configured"
        providers.append({"id": name, "label": name.replace("-", " ").title(), "status": status})
    tools: list[dict[str, str]] = []
    for label, command, ready_text in (
        ("Chrome DevTools MCP prerequisite (Node/npx)", "npx", "Node/npx installed; Chrome MCP not configured"),
        ("PowerShell 7", "pwsh", "Installed; MCP not enabled"),
        ("Windows PowerShell", "powershell", "Installed; MCP not enabled"),
        ("CMake CLI", "cmake", "Installed; CMake MCP not enabled"),
    ):
        executable = shutil.which(command)
        status = ready_text if executable else "Not detected"
        tools.append({"id": command, "label": label, "status": status})
    return {"providers": providers, "tools": tools,
            "mcp_servers": agent.mcp_status() if hasattr(agent, "mcp_status") else {}}


class BridgeHandler(BaseHTTPRequestHandler):
    server: "BridgeHTTPServer"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionError, OSError):
            # The dock gave up (its HTTPRequest timed out or was cancelled) and closed
            # the socket, so there is nobody left to answer. Letting this raise only
            # printed a scary traceback in the bridge log; the request was already gone.
            return

    def _authorized(self) -> bool:
        origin = self.headers.get("Origin", "")
        if origin and origin not in ALLOWED_ORIGINS:
            self._send_json(403, {"ok": False, "error": "Origin not allowed."})
            return False
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + self.server.state.secret
        if not secrets.compare_digest(supplied, expected):
            self._send_json(401, {"ok": False, "error": "Invalid local bridge token."})
            return False
        return True

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"ok": False, "error": "Invalid Content-Length."})
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"ok": False, "error": "Request body is empty or too large."})
            return None
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "error": "Invalid JSON body."})
            return None
        if not isinstance(value, dict):
            self._send_json(400, {"ok": False, "error": "JSON body must be an object."})
            return None
        return value

    def _serve_ui(self, route: str) -> bool:
        """Serve the standalone app's static UI. Returns False if `route` is not a UI path.

        The UI holds no secrets (the token reaches it in the URL fragment, which is
        never sent here), but the Host check still stops a DNS-rebinding page from
        loading it under a foreign name.
        """
        if UI_DIR is None or not (route == "/" or route.startswith("/ui/")):
            return False
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            self._send_json(403, {"ok": False, "error": "Host not allowed."})
            return True
        found = ui_file(UI_DIR, route)
        if found is None:
            self._send_json(404, {"ok": False, "error": "Not found."})
            return True
        body = found.read_bytes()
        try:
            self.send_response(200)
            self.send_header("Content-Type", UI_TYPES.get(found.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", UI_CSP)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        return True

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if self._serve_ui(route):
            return
        if not self._authorized():
            return
        if route.startswith("/peers"):
            self._send_json(*peer_ui(self.server.state, "GET", route, {}))
            return
        if route == "/connections":
            self._send_json(200, {"ok": True, **connection_inventory(self.server.state.agent)})
            return
        if route == "/health":
            agent = self.server.state.agent
            resolved = agent.active_model_name() if hasattr(agent, "active_model_name") else agent.model_name
            report = agent.smart_report() if hasattr(agent, "smart_report") else ""
            route_trace = list(getattr(agent, "ROUTE_TRACE", []))
            self._send_json(200, {"ok": True, "service": "loki", "mode": agent.model_name,
                                  "workspace": os.environ.get("LOKI_WORKSPACE", ""),
                                  "provider": resolved, "model": agent.MODELS[resolved].model,
                                  "providers": report, "route": route_trace,
                                  "usage": dict(getattr(agent, "REQUEST_USAGE", {})),
                                  "first_layer": first_layer_status(agent)})
            return
        if route == "/progress":
            try:
                query = urlparse(self.path).query
                after = int(dict(part.split("=", 1) for part in query.split("&") if "=" in part).get("after", "0"))
            except (ValueError, TypeError):
                after = 0
            state = self.server.state
            with state.lock:
                events = [event for event in state.progress if int(event["id"]) > after]
                payload = {"ok": True, "chat_id": state.progress_chat_id, "progress": events, "latest_id": state.progress_seq}
            self._send_json(200, payload)
            return
        if route == "/approval":
            with self.server.state.lock:
                ticket = self.server.state.pending
                result = None if ticket is None else {"id": ticket["id"], "tool": ticket["tool"], "details": ticket["details"]}
            self._send_json(200, {"ok": True, "approval": result})
            return
        if route == "/models":
            agent = self.server.state.agent
            self._send_json(200, {"ok": True, "current": agent.model_name, "models": list(agent.MODELS.keys())})
            return
        if route == "/settings":
            self._send_json(200, {"ok": True, **self.server.state.agent.categories_state()})
            return
        if route == "/mode":
            self._send_json(200, {"ok": True, **self.server.state.agent.mode_state()})
            return
        if route == "/auth/status":
            session = self.server.state.session or {}
            user = session.get("user") or {}
            self._send_json(200, {"ok": True, "signed_in": bool(session.get("token")),
                                  "user": user, "cloud": CLOUD_URL})
            return
        if route == "/conversations":
            agent = self.server.state.agent
            self._send_json(200, {"ok": True, "active": agent.active_conversation_id(),
                                  "conversations": agent.list_conversations()})
            return
        if route == "/conversations/messages":
            agent = self.server.state.agent
            cid = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
            self._send_json(200, {"ok": True, "id": cid, "messages": agent.conversation_messages(cid)})
            return
        if route == "/memory":
            self._send_json(200, {"ok": True, "memory": self.server.state.agent.get_memory()})
            return
        if route == "/state":
            agent = self.server.state.agent
            text = agent.project_state_text() if hasattr(agent, "project_state_text") else ""
            self._send_json(200, {"ok": True, "state": text})
            return
        if route == "/sessions":
            agent = self.server.state.agent
            text = agent.agent_sessions() if hasattr(agent, "agent_sessions") else ""
            self._send_json(200, {"ok": True, "sessions": text})
            return
        if route == "/vault":
            agent = self.server.state.agent
            text = agent.api_vault_lookup("stats") if hasattr(agent, "api_vault_lookup") else ""
            self._send_json(200, {"ok": True, "vault": text})
            return
        if route == "/ecc":
            self._send_json(200, {"ok": True, **ecc_library(self.server.state.agent)})
            return
        if route == "/jev":
            agent = self.server.state.agent
            status = agent.jev_status() if hasattr(agent, "jev_status") else {}
            if hasattr(agent, "decision_status"):
                status = {**status, "decision": agent.decision_status()}
            self._send_json(200, {"ok": True, **status})
            return
        if route == "/setup":
            self._send_json(200, {"ok": True, **setup_status(self.server.state)})
            return
        if route == "/setup/progress":
            self._send_json(200, {"ok": True, "progress": self.server.state.agent.model_setup.PROGRESS.snapshot()})
            return
        if route == "/usage":
            self._send_json(200, {"ok": True, **self.server.state.agent.USAGE.summary()})
            return
        if route == "/agents":
            self._send_json(200, {"ok": True, "agents": self.server.state.agent.AGENTS.all(),
                                  "engines": list(self.server.state.agent.agent_profiles.ENGINES)})
            return
        if route == "/jobs":
            jobs = self.server.state.jobs
            if jobs is None:
                self._send_json(503, {"ok": False, "error": "Background jobs are not running."})
            else:
                self._send_json(200, {"ok": True, **jobs.status()})
            return
        if route == "/jobs/screenshot":
            self._send_json(*job_screenshot(self.server.state, parse_qs(urlparse(self.path).query)))
            return
        if route == "/brain":
            self._send_json(*brain_graph(self.server.state))
            return
        if route == "/brain/note":
            self._send_json(*brain_note(self.server.state, parse_qs(urlparse(self.path).query)))
            return
        if route == "/conductor":
            conductor_obj = getattr(self.server.state.agent, "CONDUCTOR", None)
            self._send_json(200, {"ok": True, "roles": conductor_obj.roster() if conductor_obj else []})
            return
        if route == "/capabilities/manifests":
            registry = getattr(self.server.state.agent, "CAPABILITIES", None)
            self._send_json(200, {"ok": True, "capabilities": registry.present() if registry else []})
            return
        if route == "/fleet":
            agent = self.server.state.agent
            fleet = getattr(agent, "federation", None)
            self._send_json(200, {"ok": True, "workers": fleet.health() if fleet else []})
        if route == "/experience":
            agent = self.server.state.agent
            exp = getattr(agent, "experience", None)
            if exp is None:
                self._send_json(503, {"ok": False, "error": "experience log is not available"})
                return
            self._send_json(200, {"ok": True, **exp.summary(), "new_examples": exp.new_examples(),
                                  "providers": exp.provider_stats(),
                                  "learned_order": agent.routing_order(agent.SMART_ORDER),
                                  "tuned_promoted": bool(getattr(agent, "TUNED_PROMOTED", False))})
            return
            return
        if route == "/capabilities":
            agent = self.server.state.agent
            if hasattr(agent, "capability_summary"):
                self._send_json(200, {"ok": True, **agent.capability_summary()})
            else:
                self._send_json(200, {"ok": True, "total": 0})
            return
        self._send_json(404, {"ok": False, "error": "Unknown endpoint."})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        route = urlparse(self.path).path
        data = self._read_json()
        if data is None:
            return
        state = self.server.state
        if route.startswith("/peers"):
            self._send_json(*peer_ui(state, "POST", route, data))
            return
        if route in ("/chat", "/task"):
            is_task: bool = route == "/task"
            prompt: Any = data.get("task" if is_task else "message", "")
            if not isinstance(prompt, str) or not prompt.strip():
                self._send_json(400, {"ok": False, "error": "A non-empty message/task is required."})
                return
            if state.loop is None:
                self._send_json(503, {"ok": False, "error": "Agent loop is not ready."})
                return
            request_lock: threading.Lock = state.task_request_lock if is_task else state.chat_request_lock
            if not request_lock.acquire(blocking=False):
                self._send_json(409, {"ok": False, "error": "Loki is already handling a request."})
                return
            try:
                if is_task:
                    try:
                        steps: int = int(data.get("steps", 0))
                    except (ValueError, TypeError):
                        self._send_json(400, {"ok": False, "error": "steps must be an integer."})
                        return
                    if MAX_TASK_STEPS > 0:
                        steps = min(MAX_TASK_STEPS, steps)
                    if steps <= 0:
                        steps = 0  # unlimited: run until DONE/BLOCKED
                    future = asyncio.run_coroutine_threadsafe(state.request_task(prompt.strip(), steps), state.loop)
                else:
                    future = asyncio.run_coroutine_threadsafe(state.request_chat(prompt.strip()), state.loop)
                self._send_json(200, future.result())  # wait as long as the task needs
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": f"Bridge request failed: {type(exc).__name__}: {exc}"})
            finally:
                request_lock.release()
            return
        if route == "/cancel":
            if state.loop is None:
                self._send_json(503, {"ok": False, "error": "Agent loop is not ready."})
                return
            state.agent.request_cancel()
            state.push_progress(state.progress_chat_id, "thinking", "Cancel requested; stopping soon...")
            self._send_json(200, {"ok": True})
            return
        if route == "/mode":
            self.server.state.agent.set_mode(str(data.get("mode", "")))
            self._send_json(200, {"ok": True, **self.server.state.agent.mode_state()})
            return
        if route == "/connect":
            result = self.server.state.agent.connect_provider(
                str(data.get("provider", "")), str(data.get("key", "")))
            self._send_json(200 if result.get("ok") else 400, result)
            return
        if route == "/profile":
            profile_path = data.get("profile_path", "")
            if not isinstance(profile_path, str) or not profile_path:
                self._send_json(400, {"ok": False, "error": "A profile path is required."})
                return
            try:
                profile_file = Path(profile_path).resolve(strict=True)
                profile_file.relative_to(Path.home().resolve())
                if profile_file.name != "loki_profile.cfg" or not profile_file.is_file():
                    raise ValueError("Unexpected profile file.")
                import configparser
                config = configparser.ConfigParser()
                config.read(profile_file, encoding="utf-8")
                name = config.get("profile", "name", fallback="").strip()
                notes = config.get("profile", "notes", fallback="").strip()
                busy = state.try_busy()
                if busy is None:
                    self._send_json(409, {"ok": False, "error": "Loki is busy; try again shortly."})
                    return
                try:
                    state.agent.set_profile(name, notes)
                finally:
                    state.release_busy(busy)
                self._send_json(200, {"ok": True})
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": f"Could not load profile: {type(exc).__name__}: {exc}"})
            return
        if route == "/model":
            name = data.get("model", "")
            agent = self.server.state.agent
            if name not in agent.MODELS:
                self._send_json(400, {"ok": False, "error": "Unknown model."})
                return
            agent.model_name = name
            resolved = name
            report = ""
            if name == "smart" and hasattr(agent, "active_model_name"):
                agent._SMART_FAILED.clear()
                resolved = agent.active_model_name()
                report = agent.smart_report() if hasattr(agent, "smart_report") else ""
            print("[loki-bridge] model switched to %s (using %s)" % (name, resolved), flush=True)
            self._send_json(200, {"ok": True, "current": name, "resolved": resolved, "smart": report})
            return
        if route == "/auth/start":
            project = self.server.state.project
            url = begin_sign_in(self.server.state, project)
            self._send_json(200, {"ok": True, "url": url})
            return
        if route == "/auth/signout":
            self.server.state.session = {}
            save_session(self.server.state.project, {})
            self._send_json(200, {"ok": True})
            return
        if route == "/settings":
            name = data.get("category", "")
            enabled = data.get("enabled")
            if not isinstance(enabled, bool) or not self.server.state.agent.set_category(name, enabled):
                self._send_json(400, {"ok": False, "error": "Unknown tool category."})
                return
            self._send_json(200, {"ok": True, **self.server.state.agent.categories_state()})
            return
        if route == "/approval":
            ticket_id = data.get("id", "")
            approved = data.get("approved")
            if not isinstance(ticket_id, str) or not isinstance(approved, bool):
                self._send_json(400, {"ok": False, "error": "Approval id and boolean decision are required."})
                return
            with state.lock:
                ticket = state.pending
                if ticket is None or not secrets.compare_digest(ticket["id"], ticket_id):
                    self._send_json(404, {"ok": False, "error": "Approval request expired or no longer pending."})
                    return
                ticket["approved"] = approved
                ticket["event"].set()
            self._send_json(200, {"ok": True, "approved": approved})
            return
        if route == "/reset":
            busy = state.try_busy()
            if busy is None:
                self._send_json(409, {"ok": False, "error": "Loki is busy; try again shortly."})
                return
            try:
                state.agent.clear_active_conversation()
            finally:
                state.release_busy(busy)
            self._send_json(200, {"ok": True, "conversations": state.agent.list_conversations()})
            return
        if route.startswith("/conversations") or route == "/memory":
            busy = state.try_busy()
            if busy is None:
                self._send_json(409, {"ok": False, "error": "Loki is busy; try again shortly."})
                return
            try:
                if route == "/conversations":
                    cid = state.agent.new_conversation(str(data.get("title", "") or ""))
                    self._send_json(200, {"ok": True, "active": cid, "conversations": state.agent.list_conversations()})
                elif route == "/conversations/switch":
                    cid = str(data.get("id", ""))
                    if not state.agent.switch_conversation(cid):
                        self._send_json(404, {"ok": False, "error": "No such conversation."})
                    else:
                        self._send_json(200, {"ok": True, "active": cid, "messages": state.agent.conversation_messages(cid), "conversations": state.agent.list_conversations()})
                elif route == "/conversations/rename":
                    if not state.agent.rename_conversation(str(data.get("id", "")), str(data.get("title", ""))):
                        self._send_json(404, {"ok": False, "error": "No such conversation."})
                    else:
                        self._send_json(200, {"ok": True, "conversations": state.agent.list_conversations()})
                elif route == "/conversations/delete":
                    if not state.agent.delete_conversation(str(data.get("id", ""))):
                        self._send_json(404, {"ok": False, "error": "No such conversation."})
                    else:
                        self._send_json(200, {"ok": True, "active": state.agent.active_conversation_id(), "conversations": state.agent.list_conversations()})
                elif route == "/memory":
                    message = state.agent.set_memory(str(data.get("text", "")))
                    self._send_json(200, {"ok": True, "memory": state.agent.get_memory(), "message": message})
            finally:
                state.release_busy(busy)
            return
        if route == "/state":
            try:
                message: str = state.agent.project_state_update(
                    str(data.get("action", "view")),
                    str(data.get("field", "")),
                    str(data.get("value", "")),
                )
                self._send_json(200, {"ok": True, "message": message,
                                      "state": state.agent.project_state_text()})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": f"project state failed: {exc}"})
            return
        if route == "/sessions":
            try:
                message: str = state.agent.agent_sessions(
                    str(data.get("action", "list")), str(data.get("name", "")),
                    str(data.get("session_id", "")), str(data.get("status", "")),
                    str(data.get("task", "")), str(data.get("workspace", "")),
                    str(data.get("agent", "loki")))
                self._send_json(200, {"ok": True, "message": message})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": f"sessions failed: {exc}"})
            return
        if route == "/vault":
            try:
                message: str = state.agent.api_vault_lookup(
                    str(data.get("action", "search")), str(data.get("query", "")),
                    str(data.get("category", "")), str(data.get("auth", "")),
                    str(data.get("name", "")), str(data.get("url", "")),
                    str(data.get("provider", "")), str(data.get("docs", "")),
                    int(data.get("limit", 25)))
                self._send_json(200, {"ok": True, "message": message})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": f"vault failed: {exc}"})
            return
        if route.startswith("/jobs"):
            self._send_json(*job_action(state, route, data))
            return
        if route == "/brain/vault":
            self._send_json(*brain_vault(state, data))
            return
        if route.startswith("/setup/"):
            self._send_json(*setup_action(state, route, data))
            return
        if route == "/usage/reset":
            state.agent.USAGE.reset()
            self._send_json(200, {"ok": True, **state.agent.USAGE.summary()})
            return
        if route.startswith("/agents"):
            self._send_json(*agents_action(state, route, data))
            return
        if route == "/capabilities/enable":
            self._send_json(*capability_toggle(state, data))
            return
        if route == "/ecc/sync":
            try:
                message: str = state.agent.sync_ecc(bool(data.get("force", False)))
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": f"ECC sync failed: {exc}"})
                return
            self._send_json(200, {"ok": True, "message": message, **ecc_library(state.agent)})
            return
        self._send_json(404, {"ok": False, "error": "Unknown endpoint."})


def job_action(state: "BridgeState", route: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """POST /jobs (create), /jobs/cancel, /jobs/clear. Returns (status, payload)."""
    jobs = state.jobs
    if jobs is None:
        return 503, {"ok": False, "error": "Background jobs are not running."}
    if route == "/jobs":
        spec = dict(data)
        engine_policy = getattr(state.agent, "POLICY", None) if getattr(state, "agent", None) else None
        if engine_policy is not None:
            verdict = engine_policy.job(str(spec.get("backend") or "local").strip().lower(),
                                        str(spec.get("agent") or "").strip().lower())
            if not verdict.allowed:
                return 403, {"ok": False, "error": verdict.reason}
        if not str(spec.get("workspace") or "").strip() and state.project is not None:
            spec["workspace"] = str(state.project)
        try:
            job = jobs.create(spec)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
        threading.Thread(target=jobs.tick, daemon=True).start()  # start it now, not next tick
        return 200, {"ok": True, "id": job["id"], **jobs.status()}
    if route == "/jobs/cancel":
        job = jobs.cancel(str(data.get("id", "")))
        if job is None:
            return 404, {"ok": False, "error": "No such job."}
        return 200, {"ok": True, **jobs.status()}
    if route == "/jobs/clear":
        removed = jobs.store.remove_finished(keep=0)
        return 200, {"ok": True, "removed": removed, **jobs.status()}
    return 404, {"ok": False, "error": "Unknown endpoint."}


def usage_total(entries: Any) -> dict[str, Any]:
    """One request's usage: tokens, time, cost and the one-line meter."""
    entries = list(entries or [])
    if not entries:
        return {}
    total = {"calls": len(entries), "in": sum(e["in"] for e in entries), "out": sum(e["out"] for e in entries),
             "ms": sum(e["ms"] for e in entries), "cost": round(sum(e["cost"] for e in entries), 6),
             "model": entries[-1]["model"], "provider": entries[-1]["provider"],
             "free": all(e["free"] for e in entries), "est": any(e.get("est") for e in entries)}
    total["tps"] = round(total["out"] / (total["ms"] / 1000.0), 1) if total["ms"] >= 250 else 0.0
    total["price"] = entries[-1].get("price", "")
    try:
        import usage as usage_mod  # pylint: disable=import-outside-toplevel
        total["line"] = usage_mod.line(total)
    except Exception:
        total["line"] = ""
    return total


def setup_status(state: "BridgeState") -> dict[str, Any]:
    agent = state.agent
    info = agent.model_setup.status(info=agent.HARDWARE or None)
    local = agent.resolve_local()
    info["active"] = {"model": agent.model_name, "using": agent.active_model_name(),
                      "local": local.get("name", ""), "local_note": local.get("note", ""),
                      "online": agent.online(), "prefer": agent.PREFER}
    # Loki's goal is to work offline: offer setup whenever there is no local model, even if a
    # cloud route works (the UI remembers "Later").
    info["needs_setup"] = not local.get("name")
    info["cloud_ready"] = [n for n in agent.SMART_ORDER
                           if n not in agent.LOCAL_PROVIDERS and agent.provider_configured(n)]
    return info


def setup_action(state: "BridgeState", route: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """POST /setup/pull {tags:[...]} | /setup/install-ollama | /setup/use {model} | /setup/prefer {prefer}."""
    agent = state.agent
    ms = agent.model_setup
    if route == "/setup/pull":
        tags = data.get("tags") or ([data["tag"]] if data.get("tag") else [])
        tags = [str(t).strip() for t in tags if str(t).strip()][:6]
        if not tags:
            return 400, {"ok": False, "error": "Which model? (tags)"}
        if ms.ollama_models() is None:
            return 409, {"ok": False, "error": "Ollama is not running. Install or open Ollama first."}

        def pull_then_use() -> None:
            got = ms.pull(tags)
            if got:
                agent.resolve_local(force=True)
        if not ms.start_in_background(pull_then_use):
            return 409, {"ok": False, "error": "Already downloading - wait for it to finish."}
        return 200, {"ok": True, "progress": ms.PROGRESS.snapshot()}
    if route == "/setup/install-ollama":
        if not ms.start_in_background(ms.install_ollama):
            return 409, {"ok": False, "error": "Already busy - wait for it to finish."}
        return 200, {"ok": True, "progress": ms.PROGRESS.snapshot()}
    if route == "/setup/use":
        model = str(data.get("model", "")).strip()
        if model:
            os.environ["LOKI_LOCAL_MODEL"] = model
        else:
            os.environ.pop("LOKI_LOCAL_MODEL", None)
        state_now = agent.resolve_local(force=True)
        return 200, {"ok": True, "local": state_now.get("name", "")}
    if route == "/setup/prefer":
        prefer = str(data.get("prefer", "local")).strip().lower()
        agent.PREFER = "cloud" if prefer == "cloud" else "local"
        return 200, {"ok": True, "prefer": agent.PREFER, "using": agent.active_model_name()}
    return 404, {"ok": False, "error": "Unknown endpoint."}


def agents_action(state: "BridgeState", route: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """POST /agents (save) | /agents/delete {id} | /agents/run {id, task}."""
    agent = state.agent
    store = agent.AGENTS
    try:
        if route == "/agents":
            saved = store.save(data)
            return 200, {"ok": True, "agent": saved, "agents": store.all()}
        if route == "/agents/delete":
            if not store.delete(str(data.get("id", ""))):
                return 404, {"ok": False, "error": "No such agent."}
            return 200, {"ok": True, "agents": store.all()}
        if route == "/agents/run":
            profile = store.get(str(data.get("id", "")))
            if profile is None:
                return 404, {"ok": False, "error": "No such agent."}
            workspace = str(data.get("workspace") or state.project or "")
            spec = agent.agent_profiles.job_spec(profile, str(data.get("task", "")), workspace,
                                                 int(data.get("timeout_s") or 3600))
            return job_action(state, "/jobs", spec)
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}


def write_status_forever(state: "BridgeState") -> None:
    """harness_data/app/status.json: a live health snapshot (for Settings > Diagnostics and
    for support). No secrets: key NAMES only, never values."""
    path = (STATE_DIR or Path(".")) / "status.json"
    while True:
        try:
            agent = state.agent
            local = agent.resolve_local()
            jobs = state.jobs.status() if state.jobs is not None else {}
            snapshot = {
                "time": time.strftime("%Y-%m-%d %H:%M:%S"), "pid": os.getpid(), "port": PORT,
                "model": agent.model_name, "using": agent.active_model_name(),
                "local": {k: local.get(k) for k in ("name", "source", "note")},
                "online": agent.online(), "prefer": agent.PREFER, "hardware": agent.HARDWARE,
                "keys": sorted(k for k, v in os.environ.items() if k.endswith("_API_KEY") and v.strip()),
                "mcp_tools": len(getattr(agent, "mcp_sessions", {}) or {}),
                "backends": jobs.get("backends", {}), "job_counts": jobs.get("counts", {}),
                "usage_today": agent.USAGE.summary().get("today", {}),
                "capabilities": {r["name"]: r["status"] for r in agent.CAPABILITIES.present()},
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, path)
        except Exception as exc:  # noqa: BLE001
            print(f"[loki-bridge] status snapshot failed: {exc}", flush=True)
        time.sleep(30)


def capability_toggle(state: "BridgeState", data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """POST /capabilities/enable {name, enabled}. Only the user (through the app) does this;
    no tool exposes it to the model."""
    registry = getattr(state.agent, "CAPABILITIES", None)
    if registry is None:
        return 503, {"ok": False, "error": "No capability registry."}
    try:
        registry.set_enabled(str(data.get("name", "")), bool(data.get("enabled")))
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    if state.jobs is not None:
        state.jobs._avail.clear()  # pylint: disable=protected-access
    return 200, {"ok": True, "capabilities": registry.present()}


def brain_graph(state: "BridgeState") -> tuple[int, dict[str, Any]]:
    """GET /brain: Loki's knowledge as a graph (plus the user's Obsidian vault, read-only)."""
    import brain  # pylint: disable=import-outside-toplevel
    agent = state.agent
    data_dir = Path(getattr(agent, "DATA_DIR", ".") or ".")
    vault = brain.load_settings(data_dir).get("vault") or os.environ.get("LOKI_OBSIDIAN_VAULT", "")
    try:
        roster = agent.CONDUCTOR.roster() if hasattr(agent, "CONDUCTOR") else []
        skills = agent._skill_entries() if hasattr(agent, "_skill_entries") else []  # pylint: disable=protected-access
        graph = brain.build(data_dir, Path(getattr(agent, "WORKSPACE", state.project or ".")),
                            getattr(agent, "CAPABILITIES", None), roster, skills, vault)
    except Exception as exc:  # noqa: BLE001
        return 500, {"ok": False, "error": f"brain map failed: {type(exc).__name__}: {exc}"}
    state.brain = graph
    return 200, {"ok": True, "vault": vault, **brain.public(graph)}


def brain_note(state: "BridgeState", query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
    import brain  # pylint: disable=import-outside-toplevel
    text = brain.note_text(state.brain, (query.get("id") or [""])[0])
    if text is None:
        return 404, {"ok": False, "error": "Not a note in the current map."}
    return 200, {"ok": True, "text": text}


def brain_vault(state: "BridgeState", data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    import brain  # pylint: disable=import-outside-toplevel
    try:
        vault = brain.save_vault(Path(getattr(state.agent, "DATA_DIR", ".")), str(data.get("path", "")))
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 200, {"ok": True, "vault": vault}


def job_screenshot(state: "BridgeState", query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
    """The last virtual-computer screenshot of a job, as a data: URL (the UI's CSP allows it)."""
    import base64  # pylint: disable=import-outside-toplevel
    jobs = state.jobs
    job = jobs.store.get((query.get("id") or [""])[0]) if jobs is not None else None
    path = Path(str(((job or {}).get("handle") or {}).get("screenshot", "")))
    if job is None or not path.is_file():
        return 404, {"ok": False, "error": "No screenshot for that job."}
    return 200, {"ok": True, "image": "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")}


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, state: BridgeState) -> None:
        super().__init__((HOST, PORT), BridgeHandler)
        self.state = state


def keep_secret_alive(secret_path: Path, secret: str, stop: threading.Event) -> None:
    """Re-write the shared secret if anything removes it while the bridge runs."""
    while not stop.is_set():
        try:
            if not secret_path.exists():
                write_secret_atomic(secret_path, secret)
        except OSError:
            pass
        stop.wait(2.0)


def start_bridge_server(state: BridgeState, secret_path: Path, secret: str) -> tuple[BridgeHTTPServer, threading.Thread]:
    server = BridgeHTTPServer(state)
    write_secret_atomic(secret_path, secret)
    server_thread = threading.Thread(target=server.serve_forever, name="loki-loopback-http", daemon=True)
    server_thread.start()
    return server, server_thread


class _Tee:
    """Write to several streams at once so the bridge always leaves a log."""

    def __init__(self, *streams: Any) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            try:
                stream.write(data)
                stream.flush()
            except Exception:
                pass
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            try:
                stream.flush()
            except Exception:
                pass

    def reconfigure(self, **kwargs: Any) -> None:
        for stream in self._streams:
            try:
                stream.reconfigure(**kwargs)
            except Exception:
                pass

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        for stream in self._streams:
            try:
                return stream.fileno()
            except Exception:
                continue
        raise OSError("no fileno available")

    @property
    def encoding(self) -> str:
        return "utf-8"


def start_logging(project: Path) -> None:
    """Tee stdout/stderr to <state dir>/loki_bridge.log no matter who launched us."""
    try:
        log_dir = _state_dir(project)
        log_dir.mkdir(parents=True, exist_ok=True)
        handle = open(log_dir / "loki_bridge.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(sys.stdout, handle)
        sys.stderr = _Tee(sys.stderr, handle)
    except OSError:
        pass


async def serve() -> None:
    global STATE_DIR, UI_DIR
    args = parse_args()
    root = Path(args.loki_root).resolve()
    project = resolve_workspace(args.project_dir)
    project.mkdir(parents=True, exist_ok=True)
    if args.state_dir:
        STATE_DIR = Path(args.state_dir).expanduser().resolve()
    if args.ui_dir:
        UI_DIR = Path(args.ui_dir).expanduser().resolve()
    sys_path = os.sys.path
    sys_path.insert(0, str(root))
    start_logging(project)
    os.environ["LOKI_WORKSPACE"] = str(project)
    # Godot is an optional adapter: only point the game tools at a Godot project.
    if (project / "project.godot").is_file():
        os.environ["GAME_PROJECT"] = str(project)
    os.environ["GODOT_EXE"] = args.godot_exe
    os.environ["LOKI_AUTO_APPROVE"] = "0"
    # Do NOT force a model here: harness/.env (or the environment) decides,
    # via loki.model_name. Only fall back if that name is unknown.
    import loki  # pylint: disable=import-outside-toplevel

    if loki.model_name not in loki.MODELS:
        loki.model_name = "local-reasoning"
    secret_path = Path(args.secret_file)
    secret = secrets.token_urlsafe(32)

    state = BridgeState(loki, secret)
    state.project = project
    state.session = load_session(project)
    validate_session(state, project)
    # Hosted mode: model calls go through Loki Cloud (key stays server-side).
    loki.MODELS["cloud"] = loki.ModelConfig(
        base_url=CLOUD_URL + "/v1",
        api_key=(state.session or {}).get("token", ""),
        model=os.environ.get("LOKI_CLOUD_MODEL", "auto"),
    )
    if os.environ.get("LOKI_MODEL") == "cloud" and not (state.session or {}).get("token"):
        print("[loki-bridge] LOKI_MODEL=cloud but not signed in yet", flush=True)
    state.loop = asyncio.get_running_loop()
    state.chat_lock = asyncio.Lock()
    stack = AsyncExitStack()
    state.mcp_stack = stack
    await stack.__aenter__()
    # MCP servers (uvx/npx) can take many seconds to start, and need the network the first
    # time. Connect them in the background so the window is usable at once; their tools
    # join when ready.
    async def connect_mcp_later() -> None:
        try:
            await loki.connect_mcp(stack)
        except Exception as exc:  # noqa: BLE001
            print(f"[loki-bridge] MCP servers unavailable: {exc}", flush=True)
    asyncio.get_running_loop().create_task(connect_mcp_later())

    async def editor_approve(kind: str, detail: str, decidable: bool = True) -> bool:
        # The app always asks the human; the policy engine has already refused anything
        # it denies, so only ASK verdicts reach here.
        return await state.request_approval(kind, detail)

    loki.approve = editor_approve
    original_call_tool = loki.call_tool
    in_tool_wrapper = False
    async def observed_call_tool(name: str, tool_args: dict[str, Any]) -> str:
        nonlocal in_tool_wrapper
        if in_tool_wrapper:
            return await original_call_tool(name, tool_args)
        in_tool_wrapper = True
        state.push_progress(state.progress_chat_id, "tool", f"Calling {name}({json.dumps(tool_args, ensure_ascii=False)[:300]})")
        try:
            result = await original_call_tool(name, tool_args)
            state.push_progress(state.progress_chat_id, "tool_result", f"{name}: {str(result)[:350]}")
            return result
        finally:
            in_tool_wrapper = False
    loki.call_tool = observed_call_tool
    try:
        import workers  # pylint: disable=import-outside-toplevel
        state.jobs = workers.default_supervisor(Path(loki.DATA_DIR))
        state.jobs.start()
        loki.JOBS = state.jobs
        print("[loki-bridge] background jobs: " + ", ".join(
            "%s %s" % (name, "ready" if info["available"] else "off")
            for name, info in state.jobs.status()["backends"].items()), flush=True)
    except Exception as exc:  # noqa: BLE001 - jobs are optional; chat must still start
        print(f"[loki-bridge] background jobs unavailable: {exc}", flush=True)
    try:
        import laya  # pylint: disable=import-outside-toplevel
        laya.warm()  # the first layer asks Laya about every request: load the model now
        print("[loki-bridge] first layer: " + (
            "Laya (%s)" % laya.backend() if laya.backend() else
            "built-in rules (Laya not set up: tools/setup_laya.py)"), flush=True)
    except Exception as exc:  # noqa: BLE001 - Laya is optional; the rules answer without it
        print(f"[loki-bridge] Laya unavailable: {exc}", flush=True)
    try:
        import peer_link  # pylint: disable=import-outside-toplevel
        state.peer_server = peer_link.start(state, loki)
        threading.Thread(target=peer_link.sync_forever, args=(state, loki), daemon=True, name="loki-peers").start()
    except OSError as exc:
        print(f"[loki-bridge] peer link could not listen: {exc}", flush=True)
    except Exception as exc:  # noqa: BLE001 - the link is optional; chat must still start
        print(f"[loki-bridge] peer link unavailable: {exc}", flush=True)
    threading.Thread(target=write_status_forever, args=(state,), daemon=True, name="loki-status").start()
    threading.Thread(target=lambda: loki.resolve_local(force=True), daemon=True, name="loki-local").start()
    threading.Thread(target=initial_ecc_sync, args=(loki,), daemon=True).start()
    threading.Thread(target=dump_godot_api, args=(args.godot_exe, root), daemon=True).start()
    try:
        server, server_thread = start_bridge_server(state, secret_path, secret)
    except OSError as exc:
        await stack.aclose()
        raise RuntimeError(f"Bridge port {PORT} is already occupied; refusing to overwrite the active bridge token.") from exc
    keeper_stop = threading.Event()
    keeper = threading.Thread(target=keep_secret_alive, args=(secret_path, secret, keeper_stop), name="loki-secret-keeper", daemon=True)
    keeper.start()
    print(f"[loki-bridge] workspace {project}; Godot {'at ' + args.godot_exe if args.godot_exe else 'not configured'}", flush=True)
    print(f"[loki-bridge] ready at http://{HOST}:{PORT} (model={loki.MODELS[loki.model_name].model})", flush=True)
    if hasattr(loki, "smart_report"):
        print(f"[loki-bridge] {loki.smart_report()}", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        keeper_stop.set()
        if state.jobs is not None:
            state.jobs.stop()
        if state.peer_server is not None:
            state.peer_server.stop()
        server.shutdown()
        server.server_close()
        await stack.aclose()
        secret_path.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(serve())
