"""Loopback API that lets the Loki Godot dock call the real Loki agent."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import threading
import time
import uuid
from contextlib import AsyncExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs, quote
import urllib.request
import webbrowser


MAX_BODY_BYTES = 32_000
MAX_PROMPT_CHARS = 16_000
CLOUD_URL = os.environ.get("LOKI_CLOUD_URL", "http://localhost:8788")


def _session_path(project) -> Path:
    return Path(project) / ".godot" / "loki_session.json"


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


def begin_sign_in(state, project) -> str:
    """Open the browser to Loki Cloud sign-in and capture the loopback code."""
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
            html = b"<html><body style='font-family:sans-serif;padding:40px'><h2>Loki: signed in</h2><p>Close this tab and return to Godot.</p></body></html>"
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
PORT = 8766


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Loki-to-Godot editor bridge")
    parser.add_argument("--loki-root", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--godot-exe", required=True)
    parser.add_argument("--secret-file", required=True)
    return parser.parse_args()


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

    def push_progress(self, chat_id: str, event: str, text: str) -> None:
        with self.lock:
            self.progress_seq += 1
            self.progress.append({"id": self.progress_seq, "chat_id": chat_id, "event": event, "text": text[:500]})
            self.progress = self.progress[-160:]

    def _start_heartbeat(self, chat_id: str) -> threading.Event:
        """Push a liveness event every few seconds so the dock never looks frozen."""
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
            try:
                answer = await self.agent.run_agent(prompt)
                self.push_progress(chat_id, "done", "Response ready.")
                return {"ok": True, "response": answer, "chat_id": chat_id}
            except self.agent.BudgetExhausted as exc:
                self.push_progress(chat_id, "done", "Stopped: %s." % exc.reason)
                return {"ok": True, "response": "Stopped early: %s." % exc.reason, "chat_id": chat_id, "stopped": True}
            except self.agent.ModelUnavailable as exc:
                self.push_progress(chat_id, "error", exc.hint)
                return {"ok": False, "error": exc.hint, "chat_id": chat_id}
            except Exception as exc:
                error = "%s: %s" % (type(exc).__name__, exc)
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
            except Exception as exc:
                detail: str = "%s: %s" % (type(exc).__name__, exc)
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


class BridgeHandler(BaseHTTPRequestHandler):
    server: "BridgeHTTPServer"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        origin = self.headers.get("Origin", "")
        if origin and origin not in ("http://127.0.0.1", "http://localhost", "null"):
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

    def do_GET(self) -> None:
        if not self._authorized():
            return
        route = urlparse(self.path).path
        if route == "/health":
            self._send_json(200, {"ok": True, "service": "loki", "model": self.server.state.agent.MODELS[self.server.state.agent.model_name].model})
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
        if route == "/auth/status":
            session = self.server.state.session or {}
            user = session.get("user") or {}
            self._send_json(200, {"ok": True, "signed_in": bool(session.get("token")),
                                  "user": user, "cloud": CLOUD_URL})
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
                state.profile = {"name": config.get("profile", "name", fallback="").strip()[:100], "notes": config.get("profile", "notes", fallback="").strip()[:4000]}
                assert state.loop is not None and state.chat_lock is not None
                async def update_profile() -> None:
                    async with state.chat_lock:
                        memory: str = state.agent.load_memory().replace("- The user's name is Tim and they are 26 years old." + chr(10), "")
                        lines: list[str] = []
                        if state.profile["name"]:
                            lines.append("Preferred name: " + state.profile["name"])
                        if state.profile["notes"]:
                            lines.append("User-provided profile/preferences: " + state.profile["notes"])
                        memory += chr(10) * 2 + "Editable user profile:" + chr(10) + (chr(10).join(lines) if lines else "(none provided)")
                        state.agent.messages[0] = {"role": "system", "content": state.agent.SYSTEM_PROMPT.format(memory=memory)}
                asyncio.run_coroutine_threadsafe(update_profile(), state.loop).result(timeout=30)
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
            print("[loki-bridge] model switched to " + name, flush=True)
            self._send_json(200, {"ok": True, "current": name})
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
            if state.loop is None or state.chat_lock is None:
                self._send_json(503, {"ok": False, "error": "Agent loop is not ready."})
                return
            async def reset_chat() -> None:
                async with state.chat_lock:
                    memory: str = state.agent.load_memory().replace("- The user's name is Tim and they are 26 years old." + chr(10), "")
                    lines: list[str] = []
                    if state.profile["name"]:
                        lines.append("Preferred name: " + state.profile["name"])
                    if state.profile["notes"]:
                        lines.append("User-provided profile/preferences: " + state.profile["notes"])
                    memory += chr(10) * 2 + "Editable user profile:" + chr(10) + (chr(10).join(lines) if lines else "(none provided)")
                    state.agent.messages[:] = [{"role": "system", "content": state.agent.SYSTEM_PROMPT.format(memory=memory)}]
            future = asyncio.run_coroutine_threadsafe(reset_chat(), state.loop)
            try:
                future.result(timeout=15)
                self._send_json(200, {"ok": True})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        self._send_json(404, {"ok": False, "error": "Unknown endpoint."})


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
    """Tee stdout/stderr to .godot/loki_bridge.log no matter who launched us."""
    try:
        log_dir = project / ".godot"
        log_dir.mkdir(parents=True, exist_ok=True)
        handle = open(log_dir / "loki_bridge.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(sys.stdout, handle)
        sys.stderr = _Tee(sys.stderr, handle)
    except OSError:
        pass


async def serve() -> None:
    args = parse_args()
    root = Path(args.loki_root).resolve()
    project = Path(args.project_dir).resolve()
    sys_path = os.sys.path
    sys_path.insert(0, str(root))
    start_logging(project)
    os.environ["GAME_PROJECT"] = str(project)
    os.environ["LOKI_WORKSPACE"] = str(project)
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
    # Hosted mode: model calls go through Loki Cloud (key stays server-side).
    loki.MODELS["cloud"] = loki.ModelConfig(
        base_url=CLOUD_URL + "/v1",
        api_key=(state.session or {}).get("token", ""),
        model=os.environ.get("LOKI_CLOUD_MODEL", "auto"),
    )
    if os.environ.get("LOKI_MODEL") == "cloud" and not (state.session or {}).get("token"):
        print("[loki-bridge] LOKI_MODEL=cloud but not signed in yet", flush=True)
    state.session = load_session(project)
    state.loop = asyncio.get_running_loop()
    state.chat_lock = asyncio.Lock()
    stack = AsyncExitStack()
    state.mcp_stack = stack
    await stack.__aenter__()
    await loki.connect_mcp(stack)

    async def editor_approve(kind: str, detail: str) -> bool:
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
        server, server_thread = start_bridge_server(state, secret_path, secret)
    except OSError as exc:
        await stack.aclose()
        raise RuntimeError(f"Bridge port {PORT} is already occupied; refusing to overwrite the active bridge token.") from exc
    keeper_stop = threading.Event()
    keeper = threading.Thread(target=keep_secret_alive, args=(secret_path, secret, keeper_stop), name="loki-secret-keeper", daemon=True)
    keeper.start()
    print(f"[loki-bridge] ready at http://{HOST}:{PORT} (model={loki.MODELS[loki.model_name].model})", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        keeper_stop.set()
        server.shutdown()
        server.server_close()
        await stack.aclose()
        secret_path.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(serve())
