"""Loopback API for the Loki engine.

Two front ends use it: the standalone Loki app (app/, which this server can also hand
its UI to) and command-line runs. Godot is an optional capability for game projects.
"""
from __future__ import annotations

import argparse
import asyncio
import errno
import json
import addons_install
try:   # no console windows on Windows (engine/no_console.py)
    import no_console  # noqa: F401
except Exception:  # noqa: BLE001
    pass
import os
import secrets
import shutil
import socket
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

ENGINE_T0 = time.monotonic()   # speed watch (E6): engine start -> bridge ready


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
            ".json": "application/json; charset=utf-8",
            ".wasm": "application/wasm", ".pck": "application/octet-stream", ".gz": "application/gzip",
            ".woff2": "font/woff2"}   # the bundled Inter (app/ui/fonts): the same letters on the Mac and on Windows
# style-src allows inline <style>: pywebview injects one for its drag regions (the Mac title bar)
# and the bundled Mermaid adds one per diagram; both were blocked ("could not load (no address) -
# <style>" in engine.out). Scripts stay 'self' only - no inline script, no eval.
UI_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' data: blob:; "
          "connect-src 'self'; frame-src 'self' http://127.0.0.1:* http://localhost:*; "   # the Studio tab: Studio's own loopback server
          "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
# Forge's sculpting engine runs in a Web Worker (app/ui/vendor/sculpt/sculpt_worker.js). A dedicated worker takes
# its policy from its own response, so WebAssembly is allowed for that one script - it can only load LOKI's own
# files and has no DOM - while every page keeps UI_CSP (no 'wasm-unsafe-eval' in the window itself).
SCULPT_WORKER = "/ui/vendor/sculpt/sculpt_worker.js"
SCULPT_WORKER_CSP = "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'"
# Every Web Worker that runs LOKI's own WebAssembly gets SCULPT_WORKER_CSP: the sculpting engine and OptCuts
# (app/ui/vendor/optcuts/optcuts_worker.js, Forge's UV unwrap).
WORKER_PAGES = {SCULPT_WORKER, "/ui/vendor/optcuts/optcuts_worker.js"}


def memory_guard(state: Any, every_s: float = 60.0) -> None:
    """Every minute: sample memory, forecast it (forecast.py) and, when this machine is about to
    run out while LOKI is idle, unload idle local models before it starts swapping."""
    import forecast  # pylint: disable=import-outside-toplevel
    time.sleep(30)
    while True:
        try:
            busy = bool((state.chat_lock is not None and state.chat_lock.locked()) or state.chat_request_lock.locked()
                        or state.task_request_lock.locked() or time.time() - state.last_request_at < 120)
            result = forecast.memory_tick(busy, forecast.ollama_unload_idle)
            if result.get("action"):
                print("[loki-bridge] memory guard: %s" % result["action"], flush=True)
        except Exception as exc:  # noqa: BLE001 - never take the engine down
            print("[loki-bridge] memory guard error: %s" % exc, flush=True)
        time.sleep(every_s)


def forecast_report(agent: Any) -> dict:
    import forecast  # pylint: disable=import-outside-toplevel
    try:
        entries = agent.USAGE.entries(time.time() - 3 * 86400)
    except Exception:  # noqa: BLE001
        entries = []
    limit = float(getattr(agent, "DAILY_USD_LIMIT", 0) or 0)
    return {"ok": True, **forecast.status(), "latency": forecast.provider_outlook(entries),
            "spend": forecast.spend_outlook(entries, limit)}


_USAGE_CACHE: dict = {"t": 0.0, "today": {}}
UI_ERRORS: list = []   # the window's script errors (boot.js), newest last; also in /health


UI_STATE = {"ready": threading.Event(), "rescue": "", "ready_info": {}}


def update_trial_watch(updater, wait_s: float | None = None, restart=None) -> str:
    """After an update: the window must report ready within LOKI_TRIAL_UI_S seconds (default 300).
    Ready -> this version is good. The rescue screen, or silence -> roll back to the last good
    version (it goes on the skip list with the reason) and restart the whole app on it."""
    wait_s = float(os.getenv("LOKI_TRIAL_UI_S", "300") or 300) if wait_s is None else wait_s
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if UI_STATE["ready"].wait(2.0):
            updater.mark_good()
            print("[loki-bridge] update trial passed: the window is ready on the new version", flush=True)
            return "good"
        if UI_STATE["rescue"]:
            break
    why = ("its window showed an error: " + UI_STATE["rescue"][:300]) if UI_STATE["rescue"] else \
        "its window did not become ready in %d s" % wait_s
    result = updater.rollback(why=why)
    print("[loki-bridge] update trial FAILED (%s); rollback: %s" % (why, result), flush=True)
    if result.get("ok"):
        (restart or restart_engine)()
        return "rolled back"
    return "failed"


def redact_line(text: str) -> str:
    """No tokens or keys from a client error line go into the log."""
    import re as _re  # pylint: disable=import-outside-toplevel
    return _re.sub(r"(token=|Bearer\s+|sk-[A-Za-z0-9_-]{4})[A-Za-z0-9._~+/=-]+", r"\1[redacted]", text)


def world_extras(agent: Any) -> dict:
    """The live view (GET /world) besides the agents: your other machines, the model answering
    right now, and today's usage. Cheap: cached, never waits on the network."""
    out: dict = {}
    try:
        import peer_link  # pylint: disable=import-outside-toplevel
        out["machines"] = peer_link.machines_live()
    except Exception:  # noqa: BLE001
        out["machines"] = []
    try:   # how many things LOKI made, and the newest few
        import creations  # pylint: disable=import-outside-toplevel
        made = creations.list_creations(Path(getattr(agent, "WORKSPACE", ".")), limit=400)
        out["creations"] = {"count": len(made), "latest": [{"title": c["title"], "kind": c["kind"], "show": c["show"]}
                                                           for c in made[:5]]}
    except Exception:  # noqa: BLE001
        out["creations"] = {"count": 0, "latest": []}
    try:   # this machine: its name and OS
        import platform  # pylint: disable=import-outside-toplevel
        import peers  # pylint: disable=import-outside-toplevel
        out["self"] = {"name": peers.my_name(), "os": platform.system()}
    except Exception:  # noqa: BLE001
        out["self"] = {}
    try:
        name = agent.active_model_name()
        cfg = agent.MODELS[name]
        out["model"] = {"provider": name, "model": cfg.model,
                        "local": "11434" in cfg.base_url or "127.0.0.1" in cfg.base_url or "localhost" in cfg.base_url}
    except Exception:  # noqa: BLE001
        out["model"] = {}
    if time.time() - _USAGE_CACHE["t"] > 30:
        try:
            _USAGE_CACHE["today"] = agent.USAGE.summary().get("today", {})
        except Exception:  # noqa: BLE001
            _USAGE_CACHE["today"] = {}
        _USAGE_CACHE["t"] = time.time()
    out["usage"] = _USAGE_CACHE["today"]
    return out


ALREADY_RUNNING_EXIT_CODE = 73   # app/loki_app.py: "an engine already runs here" - attach to it, not a crash


def restart_engine() -> None:
    """Restart this engine on the code now on disk (after an update).

    Started by the app (LOKI_SUPERVISED=1): exit with updater.RESTART_EXIT_CODE and the app
    starts a fresh engine and reloads the window. Started on its own (a service, the CLI):
    start a fresh copy that waits a moment for this one's ports, then exit."""
    import updater  # pylint: disable=import-outside-toplevel
    print("[loki-bridge] restarting to apply the update", flush=True)
    if os.environ.get("LOKI_SUPERVISED") == "1":
        os._exit(updater.RESTART_EXIT_CODE)
    env = dict(os.environ, LOKI_START_DELAY="3")
    argv = [sys.executable, *sys.argv] if not getattr(sys, "frozen", False) else [sys.executable, *sys.argv[1:]]
    options: dict = {"creationflags": 0x08000000 | 0x00000200} if sys.platform == "win32" else {"start_new_session": True}
    try:
        subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, **options)
    except OSError as exc:
        print("[loki-bridge] could not restart: %s" % exc, flush=True)
        return
    os._exit(0)


def update_status() -> dict:
    """This machine's LOKI version and whether GitHub has a newer one (engine/updater.py)."""
    try:
        import updater  # pylint: disable=import-outside-toplevel
        return updater.status()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


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


GAME_TYPES = (".js", ".json", ".png", ".svg")


def game_file(workspace: Path, route: str) -> Path | None:
    """Map /games/<name>/<file> to workspace/games/<name>/<file>, refusing anything else."""
    relative = route[len("/games/"):]
    if not relative or "\\" in relative or relative.startswith("/") or ".." in relative.split("/"):
        return None
    root = (Path(workspace) / "games").resolve()
    try:
        candidate = (root / relative).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if candidate.suffix not in GAME_TYPES or not candidate.is_file():
        return None
    return candidate


def list_games(ui_dir: Path | None, workspace: Path) -> list:
    """Every playable game: the ones that ship with LOKI and the ones LOKI built in the workspace."""
    out = []
    for src, root in (("builtin", Path(ui_dir) / "games" if ui_dir else None), ("workspace", Path(workspace) / "games")):
        if root is None or not root.is_dir():
            continue
        for folder in sorted(root.iterdir()):
            script = folder / "game.js"
            if not script.is_file():
                continue
            try:
                first = script.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            except (OSError, IndexError):
                first = ""
            title = first.lstrip("/ ").split(" - ")[0].strip() or folder.name
            out.append({"name": folder.name, "title": title[:80], "src": src,
                        "about": first.lstrip("/ ")[len(title):].lstrip(" -")[:200], "t": script.stat().st_mtime})
    return out


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
        self.last_request_at = 0.0  # when the owner last asked something (the autopilot waits for quiet)
        self.autopilot = None       # autopilot.Autopilot, set when the engine starts
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
        self.phone_server: Any = None  # phone_link.PhoneServer when the phone app may talk to this machine
        self.channels: dict[str, Any] = {}  # channels.Channel per chat app (Telegram), started at boot

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

    def note_request(self) -> None:
        """A real request from the owner just started: the autopilot stays quiet after it."""
        self.last_request_at = time.time()

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
                # the agent is OpenCode + CodeGraph (engine/opencode_engine.py); LOKI_AGENT_ENGINE=loki = the old loop
                if hasattr(self.agent, "run_opencode") and self.agent.opencode_engine.engine_choice() != "loki":
                    answer = await self.agent.run_opencode(prompt)
                else:
                    answer = await self.agent.run_agent(prompt)
                self.push_progress(chat_id, "done", "Response ready.")
                return {"ok": True, "response": answer, "chat_id": chat_id, "usage": usage_total(spent),
                        **memory_metadata(self.agent)}
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
                self.loop.call_soon(lambda: flush_chat_jobs(self)) if self.loop else None

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
                if hasattr(self.agent, "run_opencode") and self.agent.opencode_engine.engine_choice() != "loki":
                    summary = await self.agent.run_opencode(task, task=True)
                else:
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
        try:
            import events  # pylint: disable=import-outside-toplevel
            events.emit("approval.required", "LOKI", {"tool": tool_name, "details": details[:300]})
        except Exception:  # noqa: BLE001
            pass
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


def phone_ui(state: "BridgeState", method: str, route: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Settings > Machines > Phone: pair the LOKI phone app (engine/phone_link.py)."""
    try:
        import phone_link  # pylint: disable=import-outside-toplevel
        result = phone_link.ui_route(state, state.agent, method, route, data)
    except Exception as exc:  # noqa: BLE001
        return 500, {"ok": False, "error": f"phone link failed: {type(exc).__name__}: {exc}"}
    return result if result is not None else (404, {"ok": False, "error": "Unknown endpoint."})


def talk_ui(state: "BridgeState", method: str, route: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Talking to LOKI: the Telegram channel (engine/channels.py) and voice (engine/voice_input.py)."""
    try:
        import channels  # pylint: disable=import-outside-toplevel
        import voice_input  # pylint: disable=import-outside-toplevel
        result = channels.ui_route(state, method, route, data) or voice_input.ui_route(state, method, route, data)
    except Exception as exc:  # noqa: BLE001
        return 500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    return result or (404, {"ok": False, "error": "Unknown endpoint."})


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
        if name in ("smart", "online", "max", "fast") or name.startswith("local"):
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


# Sent on every bridge response that does not set its own (BridgeHandler.end_headers).
COI_HEADERS = (("Cross-Origin-Embedder-Policy", "require-corp"), ("Cross-Origin-Resource-Policy", "cross-origin"))


class BridgeHandler(BaseHTTPRequestHandler):
    server: "BridgeHTTPServer"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    # Cross-origin isolation (the Godot web editor inside LOKI's window needs it) means the window is
    # COEP require-corp, so EVERY document it frames must send COEP too and every file one of its sandboxed frames
    # loads (opaque origin: the chat's diagrams load /ui/vendor/mermaid, Apps, Play) must allow a cross-origin read.
    # Without this the diagrams, previews, Apps and Play went blank. A response that sets its own policy keeps it.
    def send_response(self, code: int, message: Any = None) -> None:
        self._coi_sent = set()
        super().send_response(code, message)

    def send_header(self, keyword: str, value: str) -> None:
        sent = getattr(self, "_coi_sent", None)
        if sent is not None:
            sent.add(keyword.lower())
        super().send_header(keyword, value)

    def end_headers(self) -> None:
        sent = getattr(self, "_coi_sent", None)
        if sent is not None:
            for name, value in COI_HEADERS:
                if name.lower() not in sent:
                    super().send_header(name, value)
            self._coi_sent = None
        super().end_headers()

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
        if route in WORKER_PAGES:
            self._send_static(found, csp=SCULPT_WORKER_CSP)
            return True
        self._send_static(found, framed=(route == "/ui/play.html"))
        return True

    def _send_static(self, found: Path, framed: bool = False, csp: str = "", kind: str = "", encoding: str = "") -> None:
        """One static file. `framed`: the Play page, which LOKI's own window shows in a sandboxed
        frame - it may be framed by LOKI itself (same origin) and nothing else. `csp`: a page's
        own policy (the sculpting worker: SCULPT_WORKER_CSP)."""
        body = found.read_bytes()
        try:
            self.send_response(200)
            self.send_header("Content-Type", UI_TYPES.get(kind or found.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            if encoding:
                self.send_header("Content-Encoding", encoding)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN" if framed else "DENY")
            self.send_header("Content-Security-Policy", csp or (
                UI_CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'") if framed else UI_CSP))
            # Cross-origin isolation: LOKI's window and the pages it frames are all its own origin,
            # so this costs nothing and it is what lets the Godot web editor run INSIDE the window
            # (it needs SharedArrayBuffer, which a browser gives only to an isolated page).
            # CORP cross-origin (not same-origin): the window's sandboxed frames have an opaque origin and load
            # /ui/vendor files (Mermaid); before isolation no file sent CORP at all, so this exposes nothing new
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    def _serve_game(self, route: str) -> bool:
        """GET /games/<name>/<file>: a game LOKI built in the workspace (games/<name>/), for the
        Play page's sandboxed frame. Only .js/.json/.png/.svg, only inside workspace/games, and
        only for this machine's own host name (like the UI)."""
        if not route.startswith("/games/") or route == "/games/list":
            return False
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            self._send_json(403, {"ok": False, "error": "Host not allowed."})
            return True
        found = game_file(Path(getattr(self.server.state.agent, "WORKSPACE", ".")), route)
        if found is None:
            self._send_json(404, {"ok": False, "error": "Not found."})
            return True
        self._send_static(found)
        return True

    def _serve_app(self, route: str) -> bool:
        """GET /apps/<w|t|x|p>/<name>/<file>: a LOKI mini-app's files for its sandboxed frame in the Apps area
        (engine/apps.py). Only that app's folder and safe file types, only this machine's host name; pages
        get apps.APP_CSP (no network, scripts from files only, sandboxed even when opened on their own)."""
        import apps_api  # pylint: disable=import-outside-toplevel
        if not apps_api.is_file_route(route):
            return False
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            self._send_json(403, {"ok": False, "error": "Host not allowed."})
            return True
        import apps  # pylint: disable=import-outside-toplevel
        agent = self.server.state.agent
        root = getattr(agent, "DATA_DIR", None)
        found = apps.app_file(route, Path(getattr(agent, "WORKSPACE", ".")), Path(root) if root else None)
        if found is None:
            self._send_json(404, {"ok": False, "error": "Not found."})
            return True
        body = found.read_bytes()
        page = found.suffix.lower() == ".html"
        try:
            self.send_response(200)
            self.send_header("Content-Type", apps.APP_TYPES.get(found.suffix.lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN" if page else "DENY")
            self.send_header("Content-Security-Policy", apps.APP_CSP if page else "default-src 'none'; sandbox")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        return True

    def _send_forge(self, out: tuple) -> None:
        """Forge's answer: (status, json) or (status, bytes, content type) for a model file."""
        if len(out) == 2:
            self._send_json(*out)
            return
        status, body, kind = out
        try:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    def _serve_creation(self, route: str) -> bool:
        """GET /creations/<kind>/<file>: a picture, video, sketch or sound LOKI made in the
        workspace, for Settings > Creations (an <img>/<video> cannot send the bearer token).
        Only those folders and file types, and only for this machine's own host name."""
        if not route.startswith("/creations/"):
            return False
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            self._send_json(403, {"ok": False, "error": "Host not allowed."})
            return True
        import creations  # pylint: disable=import-outside-toplevel
        found = creations.creation_file(Path(getattr(self.server.state.agent, "WORKSPACE", ".")), route)
        if found is None:
            self._send_json(404, {"ok": False, "error": "Not found."})
            return True
        body = found.read_bytes()
        try:
            self.send_response(200)
            self.send_header("Content-Type", creations.TYPES.get(found.suffix.lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=300")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        return True

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route.startswith("/artifact/"):   # research round 3: a chat preview page, sandboxed (engine/assist_api.py)
            import assist_api  # pylint: disable=import-outside-toplevel
            assist_api.serve_artifact(self, route, ALLOWED_HOSTS)
            return
        if route.startswith("/godot-editor/"):   # the Godot tab: the web editor + projects (engine/godot_web.py)
            import godot_web  # pylint: disable=import-outside-toplevel
            godot_web.http(self, "GET", ALLOWED_HOSTS, Path(getattr(self.server.state.agent, "DATA_DIR", "") or godot_web.data_dir()))
            return
        if self._serve_ui(route):
            return
        if self._serve_game(route):
            return
        if self._serve_creation(route):
            return
        if self._serve_app(route):   # LOKI Apps: a mini-app's files for its sandboxed frame
            return
        if not self._authorized():
            return
        try:
            import portal_api  # pylint: disable=import-outside-toplevel
            handled = portal_api.handle_get(self.server.state, self.path)
        except Exception as exc:  # noqa: BLE001 - one bad card must not break Settings
            handled = (500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
        if handled is not None:
            self._send_json(*handled)
            return
        if route == "/cleanup":   # what could go: test chats, empty chats, test / duplicate memories (engine/cleanup.py)
            import cleanup  # pylint: disable=import-outside-toplevel
            self._send_json(*cleanup.route(self.server.state, "GET", route, {}))
            return
        if route == "/tools/shelf":   # the Tool Shelf: game-dev tools installed on request (engine/toolshelf.py)
            import toolshelf  # pylint: disable=import-outside-toplevel
            self._send_json(*toolshelf.route(self.server.state, "GET", route, {}, {}))
            return
        if route == "/local/models":   # every model downloaded on this computer (engine/local_models.py)
            import local_models  # pylint: disable=import-outside-toplevel
            self._send_json(*local_models.route(self.server.state, "GET", route, {}, {}))
            return
        if route in ("/video/status", "/video/jobs"):   # type a line, get a video (engine/text_video.py)
            import text_video  # pylint: disable=import-outside-toplevel
            self._send_json(*text_video.route(self.server.state, "GET", route, {}))
            return
        if route == "/review":   # what waits for the owner's OK: prompts and hand-offs (engine/owner_review.py)
            import owner_review  # pylint: disable=import-outside-toplevel
            self._send_json(*owner_review.route(self.server.state, "GET", route, {}, {}))
            return
        if route.startswith("/agentsys/"):   # the agent system: traces, playbooks, upstream, parked (engine/agentsys/)
            from agentsys import api as _agentsys_api  # pylint: disable=import-outside-toplevel
            self._send_json(*_agentsys_api.route(self.server.state, "GET", self.path))
            return
        if route in ("/image/settings", "/image/info", "/image/remake", "/image/feedback"):   # engine/image_api.py
            import image_api  # pylint: disable=import-outside-toplevel
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            self._send_json(*image_api.route(self.server.state, "GET", route, q, {}))
            return
        if route == "/offload/status":   # which work this machine gives the PC, and what the PC can take (engine/offload.py)
            import offload  # pylint: disable=import-outside-toplevel
            self._send_json(*offload.route(self.server.state, "GET", route, {}, {}))
            return
        if route == "/image/edit-area":   # an area edit's progress (engine/region_edit.py)
            import region_edit  # pylint: disable=import-outside-toplevel
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            self._send_json(*region_edit.route(self.server.state, "GET", route, q, {}))
            return
        if route == "/chat/media":   # a picture or PDF named in a reply, shown in the chat (engine/chat_media.py)
            import chat_media  # pylint: disable=import-outside-toplevel
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            self._send_json(*chat_media.route(self.server.state, "GET", route, q, {}))
            return
        if route == "/studio/agents":   # Lab > Agents: every agent on every machine (engine/studio_agents.py)
            import studio_agents  # pylint: disable=import-outside-toplevel
            try:
                self._send_json(200, studio_agents.view(self.server.state))
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        if route == "/studio":   # session 29: LOKI Studio (engine/studio_api.py)
            import studio_api  # pylint: disable=import-outside-toplevel
            self._send_json(*studio_api.route(self.server.state, "GET", route))
            return
        if route == "/home/projects":   # the home screen's preview hub (engine/home_projects.py)
            import home_projects  # pylint: disable=import-outside-toplevel
            q = {k: (v[0] if v else "") for k, v in parse_qs(urlparse(self.path).query).items()}
            self._send_json(*home_projects.route(self.server.state, route, q))
            return
        if route.startswith("/render/"):   # Render Studio (engine/ai_renderer.py)
            import ai_renderer  # pylint: disable=import-outside-toplevel
            self._send_forge(ai_renderer.handle_get(self.server.state, self.path))
            return
        if route.startswith("/farm/"):   # Studio's render farm manager (engine/render_farm.py)
            import render_farm  # pylint: disable=import-outside-toplevel
            self._send_json(*render_farm.route(self.server.state, "GET", self.path))
            return
        if route.startswith("/carbon/"):   # the Engine tab's Carbon Editor (engine/carbon_editor.py)
            import carbon_editor  # pylint: disable=import-outside-toplevel
            self._send_json(*carbon_editor.route("GET", route))
            return
        if route == "/agent/engine":   # the agent: OpenCode + CodeGraph (engine/opencode_engine.py)
            self._send_json(200, {"ok": True, **self.server.state.agent.engine_status()})
            return
        if route.startswith("/api/godot/"):   # the live Godot editor link (engine/godot_live.py)
            import godot_live  # pylint: disable=import-outside-toplevel
            q = {k: (v[0] if v else "") for k, v in parse_qs(urlparse(self.path).query).items()}
            self._send_json(*godot_live.route("GET", route, {}, q))
            return
        if route.startswith("/forge/"):   # Forge, the 3D panel (engine/forge_api.py)
            import forge_api  # pylint: disable=import-outside-toplevel
            self._send_forge(forge_api.handle_get(self.server.state, self.path))
            return
        import usability_api  # pylint: disable=import-outside-toplevel - session 29: help, onboarding, language
        if usability_api.handles("GET", route):
            self._send_json(*usability_api.route(self.server.state, "GET", self.path))
            return
        if route in ("/speed", "/jobs/stats", "/user_tools"):   # session 28: LOKI improving itself
            import self_api  # pylint: disable=import-outside-toplevel
            self._send_json(*self_api.route(self.server.state, "GET", self.path, {}))
            return
        if route.startswith("/files/"):   # session 29: the Files view (engine/files_api.py)
            import files_api  # pylint: disable=import-outside-toplevel
            try:
                self._send_json(*files_api.handle(self.server.state, "GET", self.path, {}))
            except Exception as exc:  # noqa: BLE001 - a broken preview must not break the window
                self._send_json(500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        import apps_api  # pylint: disable=import-outside-toplevel - LOKI Apps, modes, extensions
        if apps_api.owns(route) or route == "/extensions":
            try:
                self._send_json(*apps_api.handle_get(self.server.state, self.path))
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        if route.startswith(("/tools/health", "/connectors", "/computer")):   # Settings > Tools (engine/tools_api.py)
            import tools_api  # pylint: disable=import-outside-toplevel
            try:
                self._send_json(*tools_api.handle(self.server.state, "GET", self.path, {}))
            except Exception as exc:  # noqa: BLE001 - one broken card must not break Settings
                self._send_json(500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        import assist_api  # pylint: disable=import-outside-toplevel - research round 3 (chats, prompts, compare, data)
        if assist_api.handles(route):
            self._send_json(*assist_api.route(self.server.state, "GET", self.path, {}))
            return
        if route.startswith("/qol/"):   # session 29: chat quality of life (engine/qol.py)
            import qol  # pylint: disable=import-outside-toplevel
            self._send_json(*qol.route(self.server.state, "GET", self.path))
            return
        if route.startswith("/peers"):
            self._send_json(*peer_ui(self.server.state, "GET", route, {}))
            return
        if route.startswith("/phones"):
            self._send_json(*phone_ui(self.server.state, "GET", route, {}))
            return
        if route.startswith("/channels") or route == "/voice":
            self._send_json(*talk_ui(self.server.state, "GET", route, {}))
            return
        if route.startswith("/automations"):   # session 29: Settings > Automations (engine/automations.py)
            import automations  # pylint: disable=import-outside-toplevel
            self._send_json(*automations.ui_route(self.server.state, "GET", self.path, {}, PORT))
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
                                  "first_layer": first_layer_status(agent),
                                  "update": update_status(), "deps": deps_status(), "ui_errors": UI_ERRORS[-10:]})
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
            self._send_json(200, {"ok": True, "current": agent.model_name, "models": list(agent.MODELS.keys()),
                                  **model_menu(agent)})
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
        if route == "/memory/core":
            self._send_json(*memory_core_api(self.server.state, "GET", parse_qs(urlparse(self.path).query)))
            return
        if route == "/sketch/reply":
            self._send_json(200, sketch_reply_latest(self.server.state))
            return
        if route == "/state":
            agent = self.server.state.agent
            text = agent.project_state_text() if hasattr(agent, "project_state_text") else ""
            self._send_json(200, {"ok": True, "state": text})
            return
        if route == "/evolve":
            ev = getattr(self.server.state, "evolve", None)
            auto = getattr(self.server.state, "autopilot", None)
            log = [e for e in (auto.data["log"] if auto is not None else []) if e.get("duty") == "evolve"][-20:]
            self._send_json(200, ev.status() | {"log": log} if ev is not None else {"ok": False, "error": "evolve is not running"})
            return
        if route == "/bench":
            self._send_json(200, bench_latest(self.server.state))
            return
        if route == "/autopilot":
            auto = getattr(self.server.state, "autopilot", None)
            self._send_json(200, {"ok": True, **(auto.status() if auto is not None else {"enabled": False})})
            return
        if route == "/storage":   # Lab > Storage: usage, what may go, the trash (engine/storage.py)
            self._send_json(*storage_route(self.server.state, "GET", route, dict((k, v[0]) for k, v in parse_qs(urlparse(self.path).query).items())))
            return
        if route == "/tasks/board":   # Lab > Tasks: what the agents were asked, finished, failed and why (task_board.py)
            self._send_json(*task_board_route(self.server.state, "GET", route, {}))
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
                payload = {"ok": True, **jobs.status()}
                try:   # session 28: queued jobs carry a duration + failure-risk forecast (job_stats.py)
                    import job_stats  # pylint: disable=import-outside-toplevel
                    payload = job_stats.annotate(payload, jobs.store.all(),
                                                 Path(getattr(self.server.state.agent, "DATA_DIR", ".") or "."))
                except Exception:  # noqa: BLE001
                    pass
                self._send_json(200, payload)
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
            return
        if route == "/system/check":
            import system_check  # pylint: disable=import-outside-toplevel
            self._send_json(200, {"ok": True, **system_check.RUNNER.snapshot()})
            return
        if route == "/update":
            self._send_json(200, {"ok": True, **update_status()})
            return
        if route in ("/events", "/world"):
            import events  # pylint: disable=import-outside-toplevel
            state = self.server.state
            if route == "/events":
                query = dict(part.split("=", 1) for part in urlparse(self.path).query.split("&") if "=" in part)
                try:
                    after, wait_s = int(query.get("after", "0")), float(query.get("wait", "0"))
                except ValueError:
                    after, wait_s = 0, 0.0
                found = events.wait(after, timeout=wait_s) if wait_s > 0 else events.read(after)
                self._send_json(200, {"ok": True, "events": found,
                                      "cursor": found[-1]["seq"] if found else after})
                return
            runner = getattr(state.agent, "TEAMS", None)
            raw_jobs = state.jobs.store.all() if state.jobs is not None else []
            busy = bool(state.chat_lock is not None and state.chat_lock.locked())
            payload = events.world(raw_jobs, runner.all() if runner else [], busy,
                                   dict(getattr(state.agent, "LAST_TRIAGE", {}) or {}))
            payload.update(world_extras(state.agent))
            self._send_json(200, payload)
            return
        if route == "/teams":
            agent = self.server.state.agent
            runner = getattr(agent, "TEAMS", None)
            teams_list = [agent.teams.present(t, runner.jobs) for t in runner.all()[:10]] if runner else []
            self._send_json(200, {"ok": True, "teams": teams_list})
            return
        if route == "/forecast":
            self._send_json(200, forecast_report(self.server.state.agent))
            return
        if route == "/crm":
            self._send_json(*crm_route(self.server.state, "GET", route, {}))
            return
        if route == "/creations":
            import creations  # pylint: disable=import-outside-toplevel
            ws = Path(getattr(self.server.state.agent, "WORKSPACE", "."))
            self._send_json(200, {"ok": True, "items": creations.list_creations(ws), "games": list_games(UI_DIR, ws),
                                  "ideas": creations.IDEAS, "making": creations.making(),
                                  "styles": creations.styles(), "aspects": list(creations.ASPECTS),
                                  "creative": creative_summary()})
            return
        if route == "/games/list":
            ws = Path(getattr(self.server.state.agent, "WORKSPACE", "."))
            self._send_json(200, {"ok": True, "games": list_games(UI_DIR, ws)})
            return
        if route == "/media/status":
            import higgsfield  # pylint: disable=import-outside-toplevel
            self._send_json(200, {"ok": True, **higgsfield.status()})
            return
        if route in ("/checkpoints", "/checkpoints/changes", "/workbench/files"):
            query = dict(part.split("=", 1) for part in urlparse(self.path).query.split("&") if "=" in part)
            from urllib.parse import unquote  # pylint: disable=import-outside-toplevel
            state = self.server.state
            cps = getattr(state, "checkpoints", None)
            if route == "/workbench/files":
                import workbench  # pylint: disable=import-outside-toplevel
                self._send_json(200, {"ok": True, "files": workbench.search_files(state.project or Path("."),
                                                                                    unquote(query.get("q", "")))})
                return
            if cps is None:
                self._send_json(503, {"ok": False, "error": "checkpoints are not available"})
                return
            if route == "/checkpoints":
                self._send_json(200, {"ok": True, "checkpoints": cps.list()})
            else:
                self._send_json(200, cps.changes(unquote(query.get("id", ""))))
            return
        if route == "/experience":
            agent = self.server.state.agent
            exp = getattr(agent, "experience", None)
            if exp is None:
                self._send_json(503, {"ok": False, "error": "experience log is not available"})
                return
            self._send_json(200, {"ok": True, **exp.summary(), "new_examples": exp.new_examples(),
                                  "providers": exp.provider_stats(),
                                  "tool_stats": exp.tool_stats(),
                                  "memory": agent.memory.stats(),
                                  "learned_order": agent.routing_order(agent.SMART_ORDER),
                                  "tuned_promoted": bool(getattr(agent, "TUNED_PROMOTED", False))})
            return
            return
        if route == "/autosetup/status":
            import auto_setup  # pylint: disable=import-outside-toplevel
            self._send_json(200, {"ok": True, **auto_setup.status()})
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
        if urlparse(self.path).path.startswith("/hook/"):   # session 29: an automation's webhook - its own secret key
            import automations  # pylint: disable=import-outside-toplevel
            self._send_json(*automations.hook_request(self.server.state, self.path, self.headers, self.rfile))
            return
        if urlparse(self.path).path.startswith("/godot-editor/"):   # the Godot tab (engine/godot_web.py)
            import godot_web  # pylint: disable=import-outside-toplevel
            godot_web.http(self, "POST", ALLOWED_HOSTS, Path(getattr(self.server.state.agent, "DATA_DIR", "") or godot_web.data_dir()))
            return
        if not self._authorized():
            return
        route = urlparse(self.path).path
        if route in ("/convo/import", "/artifact"):   # research round 3: chat exports / previews are big bodies
            import assist_api  # pylint: disable=import-outside-toplevel
            body = assist_api.read_json(self)
            if body is not None:
                self._send_json(*assist_api.route(self.server.state, "POST", self.path, body))
            return
        if route.startswith("/forge/"):   # Forge: drawings and sculpted meshes are big bodies (engine/forge_api.py)
            import forge_api  # pylint: disable=import-outside-toplevel
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > forge_api.MAX_BODY:
                self._send_json(413, {"ok": False, "error": "Request body is too large."})
                return
            self._send_forge(forge_api.handle_post(self.server.state, self.path, self.rfile.read(length)))
            return
        if route in ("/agent/engine/install", "/agent/engine/set"):   # Settings > Agent
            body = self._read_json() if int(self.headers.get("Content-Length", "0") or 0) > 0 else {}
            if body is None:
                return
            agent = self.server.state.agent
            if route.endswith("/set"):
                choice = str(body.get("engine", "")).lower()
                choice = choice if choice in agent.opencode_engine.HARNESSES else "auto"
                os.environ["LOKI_AGENT_ENGINE"] = choice
                try:
                    where = Path(agent.DATA_DIR) / "opencode"
                    where.mkdir(parents=True, exist_ok=True)
                    (where / "harness.txt").write_text(choice, encoding="utf-8")
                except OSError:
                    pass
                self._send_json(200, {"ok": True, **agent.engine_status()})
            else:
                done = agent.opencode_engine.install(body.get("which") or ("opencode", "codegraph", "dsh"))
                self._send_json(200, {"ok": all(v in ("ok", "already") for v in done.values()), "result": done,
                                      **agent.engine_status()})
            return
        if route.startswith("/farm/") or route.startswith("/carbon/"):   # Studio's farm / the Engine tab's Carbon Editor
            body = self._read_json() if int(self.headers.get("Content-Length", "0") or 0) > 0 else {}
            if body is None:
                return
            if route.startswith("/farm/"):
                import render_farm  # pylint: disable=import-outside-toplevel
                self._send_json(*render_farm.route(self.server.state, "POST", self.path, body))
            else:
                import carbon_editor  # pylint: disable=import-outside-toplevel
                self._send_json(*carbon_editor.route("POST", route, body))
            return
        if route.startswith("/render/"):   # Render Studio: jobs, passes, ComfyUI (engine/ai_renderer.py)
            import ai_renderer  # pylint: disable=import-outside-toplevel
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > ai_renderer.MAX_BODY:
                self._send_json(413, {"ok": False, "error": "Request body is too large."})
                return
            self._send_forge(ai_renderer.handle_post(self.server.state, self.path, self.rfile.read(length)))
            return
        if route == "/files/upload":   # session 29: a dropped file's raw bytes (not JSON; engine/files_api.py)
            import files_api  # pylint: disable=import-outside-toplevel
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = -1
            self._send_json(*files_api.save_upload(self.server.state, urlparse(self.path).query, self.rfile, length))
            return
        import apps_api  # pylint: disable=import-outside-toplevel - LOKI Apps, modes, extensions (bigger bodies)
        if apps_api.owns(route):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length <= 0 or length > apps_api.MAX_BODY:
                self._send_json(413, {"ok": False, "error": "Request body is empty or too large."})
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"ok": False, "error": "Invalid JSON body."})
                return
            try:
                self._send_json(*apps_api.handle(self.server.state, "POST", self.path, body))
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        data = self._read_json()
        if data is None:
            return
        state = self.server.state
        try:
            import portal_api  # pylint: disable=import-outside-toplevel
            handled = portal_api.handle_post(state, route, data, port=PORT, job_action=job_action)
        except Exception as exc:  # noqa: BLE001
            handled = (500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
        if handled is not None:
            self._send_json(*handled)
            return
        if route.startswith("/api/godot/"):   # the live Godot editor link (engine/godot_live.py)
            import godot_live  # pylint: disable=import-outside-toplevel
            self._send_json(*godot_live.route("POST", route, data, {}))
            return
        if route == "/cleanup/remove":   # remove exactly the chosen chats / memories (the window asked the owner)
            import cleanup  # pylint: disable=import-outside-toplevel
            busy = state.try_busy()
            if busy is None:
                self._send_json(409, {"ok": False, "error": "Loki is busy; try again when it is done."})
                return
            try:
                self._send_json(*cleanup.route(state, "POST", route, data))
            finally:
                state.release_busy(busy)
            return
        if route == "/open/link":   # a link the owner clicked in the chat: their browser (http/https only)
            url = str(data.get("url") or "").strip()
            if not re.match(r"^https?://[^\s]+$", url):
                self._send_json(400, {"ok": False, "error": "only web links (http / https) open from the chat"})
                return
            threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
            self._send_json(200, {"ok": True})
            return
        if route in ("/tools/shelf/install", "/tools/shelf/remove"):   # engine/toolshelf.py (the window asked first)
            import toolshelf  # pylint: disable=import-outside-toplevel
            self._send_json(*toolshelf.route(state, "POST", route, {}, data))
            return
        if route == "/local/models/remove":   # uninstall a downloaded model (engine/local_models.py)
            import local_models  # pylint: disable=import-outside-toplevel
            self._send_json(*local_models.route(state, "POST", route, {}, data))
            return
        if route == "/video/make":   # type a line, get a video (engine/text_video.py)
            import text_video  # pylint: disable=import-outside-toplevel
            self._send_json(*text_video.route(state, "POST", route, data))
            return
        if route.startswith("/agentsys/"):   # interview, send back / park, orchestrate, upstream check (engine/agentsys/)
            from agentsys import api as _agentsys_api  # pylint: disable=import-outside-toplevel
            self._send_json(*_agentsys_api.route(state, "POST", self.path, data))
            return
        if route == "/review/decide":   # the owner approves / edits / rejects / sends back (engine/owner_review.py)
            import owner_review  # pylint: disable=import-outside-toplevel
            self._send_json(*owner_review.route(state, "POST", route, {}, data))
            return
        if route in ("/image/remake", "/image/rate", "/image/delete"):   # settings, thumbs, delete (engine/image_api.py)
            import image_api  # pylint: disable=import-outside-toplevel
            self._send_json(*image_api.route(state, "POST", route, {}, data))
            return
        if route in ("/image/edit-area", "/image/crop"):   # edit / crop one area of a picture (engine/region_edit.py)
            import region_edit  # pylint: disable=import-outside-toplevel
            self._send_json(*region_edit.route(state, "POST", route, {}, data))
            return
        if route in ("/chat/media/open", "/chat/media/convert"):   # engine/chat_media.py
            import chat_media  # pylint: disable=import-outside-toplevel
            self._send_json(*chat_media.route(state, "POST", route, {}, data))
            return
        if route in ("/studio/make", "/studio/agents/stop", "/studio/agents/again"):   # engine/studio_agents.py
            import studio_agents  # pylint: disable=import-outside-toplevel
            try:
                if route == "/studio/make":
                    out = studio_agents.make(state, data.get("kind"), data.get("brief"), str(data.get("name") or ""),
                                             str(data.get("machine") or ""))
                elif route == "/studio/agents/stop":
                    out = studio_agents.stop(state, str(data.get("machine") or ""), str(data.get("job") or ""))
                else:
                    out = studio_agents.again(state, str(data.get("machine") or ""), str(data.get("job") or ""))
                self._send_json(200, out)
            except ValueError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - a linked machine away is an answer, not a crash
                self._send_json(502, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        import studio_api  # pylint: disable=import-outside-toplevel - session 29: LOKI Studio + engine restart
        if studio_api.handles("POST", route):
            self._send_json(*studio_api.route(state, "POST", route, data))
            return
        import usability_api  # pylint: disable=import-outside-toplevel - session 29: onboarding, language
        if usability_api.handles("POST", route):
            self._send_json(*usability_api.route(state, "POST", route, data))
            return
        import self_api  # pylint: disable=import-outside-toplevel - session 28: LOKI improving itself
        if self_api.handles("POST", route):
            self._send_json(*self_api.route(state, "POST", route, data, job_action))
            return
        if route.startswith("/files/"):   # session 29: the Files view (engine/files_api.py)
            import files_api  # pylint: disable=import-outside-toplevel
            try:
                self._send_json(*files_api.handle(state, "POST", self.path, data))
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        if route.startswith(("/tools/health", "/connectors", "/computer")):   # Settings > Tools (engine/tools_api.py)
            import tools_api  # pylint: disable=import-outside-toplevel
            try:
                self._send_json(*tools_api.handle(state, "POST", self.path, data))
            except Exception as exc:  # noqa: BLE001 - one broken card must not break Settings
                self._send_json(500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        import assist_api  # pylint: disable=import-outside-toplevel - research round 3 (chats, prompts, compare, data)
        if assist_api.handles(route):
            self._send_json(*assist_api.route(state, "POST", self.path, data))
            return
        if route.startswith("/qol/"):   # session 29: chat quality of life (engine/qol.py)
            import qol  # pylint: disable=import-outside-toplevel
            self._send_json(*qol.route(state, "POST", self.path, data))
            return
        if route.startswith("/peers"):
            self._send_json(*peer_ui(state, "POST", route, data))
            return
        if route.startswith("/phones"):
            self._send_json(*phone_ui(state, "POST", route, data))
            return
        if route.startswith("/channels") or route.startswith("/voice/"):
            self._send_json(*talk_ui(state, "POST", route, data))
            return
        if route.startswith("/automations"):   # session 29: Settings > Automations (engine/automations.py)
            import automations  # pylint: disable=import-outside-toplevel
            self._send_json(*automations.ui_route(state, "POST", route, data, PORT))
            return
        if route in ("/teams", "/teams/cancel"):
            runner = getattr(state.agent, "TEAMS", None)
            if runner is None:
                self._send_json(503, {"ok": False, "error": "agent teams are not running"})
                return
            try:
                if route == "/teams":
                    team = runner.start(str(data.get("goal") or ""), str(state.project))
                else:
                    team = runner.cancel(str(data.get("id") or ""))
                    if team is None:
                        self._send_json(404, {"ok": False, "error": "no such team"})
                        return
            except ValueError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return
            self._send_json(200, {"ok": True, "team": state.agent.teams.present(team, runner.jobs)})
            return
        if route in ("/system/check", "/system/fix"):
            self._send_json(*system_action(state, route, data))
            return
        if route == "/update/check":
            try:
                import updater  # pylint: disable=import-outside-toplevel
                self._send_json(200, {"ok": True, **updater.check_now()})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc)})
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
            state.note_request()
            extra: dict = {}
            try:
                # Claude Code habits: @file attaches that file; a request that may change files
                # is checkpointed first, so its changes can be reviewed and rewound.
                import workbench  # pylint: disable=import-outside-toplevel
                prompt, attached = workbench.expand_mentions(prompt, state.project or Path("."))
                if attached:
                    extra["attached"] = attached
                cps = getattr(state, "checkpoints", None)
                if cps is not None and (is_task or state.agent.mode_state().get("mode") == "build"):
                    point = cps.take(prompt.strip().splitlines()[0][:120] if prompt.strip() else "request")
                    if point.get("id"):
                        extra["checkpoint"] = point["id"]
            except Exception as exc:  # noqa: BLE001
                extra["checkpoint_error"] = str(exc)[:200]
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
                turn_t0 = time.time()
                result = future.result()  # wait as long as the task needs
                try:   # what the turn made is shown in the chat even when the reply only says "I made an image"
                    import chat_media  # pylint: disable=import-outside-toplevel
                    made = chat_media.made_since(state, turn_t0)
                    if made and isinstance(result, dict) and isinstance(result.get("response"), str):
                        new = chat_media.with_made(result["response"], made)
                        if new != result["response"]:
                            for m in reversed(getattr(state.agent, "messages", [])):
                                if m.get("role") == "assistant" and m.get("content") == result["response"]:
                                    m["content"] = new          # the saved chat shows them too
                                    break
                            result["response"] = new
                        result["made"] = made
                except Exception:  # noqa: BLE001 - never lose the reply over this
                    pass
                if isinstance(result, dict) and extra:
                    result = {**result, **extra}
                    if extra.get("checkpoint") and getattr(state, "checkpoints", None) is not None:
                        try:
                            changed = state.checkpoints.changes(extra["checkpoint"])
                            result["changed_files"] = changed.get("files", [])[:50]
                        except Exception:  # noqa: BLE001
                            pass
                self._send_json(200, result)
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": f"Bridge request failed: {type(exc).__name__}: {exc}"})
            finally:
                request_lock.release()
            return
        if route.startswith("/crm/"):
            self._send_json(*crm_route(state, "POST", route, data))
            return
        if route in ("/clipboard/paste", "/clipboard/copy"):
            # the window's own Paste/Copy (engine/clipboard_io.py) - pywebview can block the browser's
            import clipboard_io  # pylint: disable=import-outside-toplevel
            if route == "/clipboard/paste":
                self._send_json(200, {"ok": True, "text": clipboard_io.read()})
            else:
                self._send_json(200, {"ok": clipboard_io.write(str(data.get("text", "")))})
            return
        if route == "/quit":
            # Settings > Quit LOKI: stop for good (the app then exits instead of keeping it in the background)
            self._send_json(200, {"ok": True, "quitting": True})
            threading.Timer(0.5, os._exit, [76]).start()
            return
        if route == "/ui/ready":
            # app.js: the window started and connected (an update on trial is now good)
            UI_STATE["ready_info"] = {"t": time.time(), "ua": str(data.get("ua", ""))[:200],
                                      "version": str(data.get("version", ""))[:40]}
            UI_STATE["ready"].set()
            self._send_json(200, {"ok": True})
            return
        if route == "/ui/error":
            # boot.js: a script error or the rescue screen in the window - kept in engine.out, where a
            # blank or broken window on a machine nobody is watching can be diagnosed later.
            text = redact_line(str(data.get("error", "")))[:2000]
            ua = str(data.get("ua", ""))[:200]
            UI_ERRORS.append({"t": time.time(), "error": text, "ua": ua})
            if text.startswith("rescue screen shown"):
                UI_STATE["rescue"] = text
            del UI_ERRORS[:-30]
            print("[loki-bridge] window error: %s  (%s)" % (text, ua), flush=True)
            self._send_json(200, {"ok": True})
            return
        if route == "/creations/make":
            # A picture is made straight by the image specialist - no chat model in between to
            # misunderstand it (the cause of the failed fox jobs). Videos and games still go to a
            # background job (they need an agent). Runs in a thread; the wall polls /creations.
            import creations  # pylint: disable=import-outside-toplevel
            what = str(data.get("prompt", "")).strip()[:600]
            if not what:
                self._send_json(400, {"ok": False, "error": "say what to make"})
                return
            if data.get("kind") == "video":   # session 28: a local video (Wan2GP) or Higgsfield
                self._send_json(200, creations.make_video(state.agent, what, seconds=_num(data.get("seconds"), 3.0)))
                return
            self._send_json(200, creations.make_image(
                state.agent, what, style=str(data.get("style", ""))[:60], enhance=bool(data.get("enhance")),
                aspect=str(data.get("aspect", "1:1"))[:8], count=int(_num(data.get("count"), 1)),
                seed=int(_num(data.get("seed"), 0))))
            return
        if route in ("/creations/like", "/creations/delete", "/creations/more", "/creations/animate"):
            # session 28: the star, delete (to the trash folder), make more like this, animate this
            import creations  # pylint: disable=import-outside-toplevel
            rel = str(data.get("path", ""))[:300]
            ws = Path(getattr(state.agent, "WORKSPACE", "."))
            if route == "/creations/like":
                out = creations.set_liked(ws, rel, bool(data.get("liked", True)))
            elif route == "/creations/delete":
                out = creations.delete_creation(ws, rel)
            elif route == "/creations/more":
                out = creations.more_like(state.agent, rel, count=int(_num(data.get("count"), 4)))
            else:
                out = creations.animate(state.agent, rel, str(data.get("prompt", ""))[:600],
                                        seconds=_num(data.get("seconds"), 3.0))
            self._send_json(200 if out.get("ok") else 400, out)
            return
        if route == "/sketch":
            # a drawing from the composer's pad: saved as a PNG in the workspace for view_image
            import base64  # pylint: disable=import-outside-toplevel
            raw = str(data.get("png", ""))
            if not raw.startswith("data:image/png;base64,") or len(raw) > 8_000_000:
                self._send_json(400, {"ok": False, "error": "send a PNG data URL (up to about 6 MB)"})
                return
            try:
                blob = base64.b64decode(raw.split(",", 1)[1], validate=True)
            except ValueError:
                self._send_json(400, {"ok": False, "error": "that is not valid PNG data"})
                return
            if not blob.startswith(b"\x89PNG"):
                self._send_json(400, {"ok": False, "error": "that is not a PNG"})
                return
            folder = Path(getattr(state.agent, "WORKSPACE", ".")) / "sketches"
            folder.mkdir(parents=True, exist_ok=True)
            name = "sketch-%s.png" % time.strftime("%Y%m%d-%H%M%S")
            (folder / name).write_bytes(blob)
            self._send_json(200, {"ok": True, "path": "sketches/" + name})
            return
        if route in ("/evolve/idea", "/evolve/start", "/evolve/approve"):
            ev = getattr(state, "evolve", None)
            if ev is None:
                self._send_json(503, {"ok": False, "error": "evolve is not running"})
                return
            if route == "/evolve/idea":
                self._send_json(200, ev.add_idea(str(data.get("text", ""))))
                return
            if route == "/evolve/approve":
                self._send_json(200, ev.approve(str(data.get("id", "")), bool(data.get("yes", True))))
                return
            if ev.busy():
                self._send_json(409, {"ok": False, "error": "LOKI is already changing itself; one change at a time"})
                return
            line = ev.step(state.agent.improve_loki)
            self._send_json(200 if line and not line.startswith("Could not") else 400,
                            {"ok": bool(line) and not line.startswith("Could not"), "line": line or "nothing left to do"})
            return
        if route == "/options":
            # "Which do you mean?": 3-4 readings of an open request (engine/options.py). Quick
            # "no" when the request is specific; one model call when it is open.
            import options  # pylint: disable=import-outside-toplevel
            text = str(data.get("text", ""))
            if not options.should_offer(text, force=bool(data.get("force"))):
                self._send_json(200, {"ok": True, "offer": False, "options": []})
                return
            if state.loop is None:
                self._send_json(200, {"ok": True, "offer": False, "options": [], "error": "the agent is not ready"})
                return
            agent = state.agent

            async def complete(prompt_text: str) -> str:
                client = agent.make_client()
                reply = await client.chat.completions.create(
                    model=agent.MODELS[agent.active_model_name()].model, max_tokens=900, temperature=0.7,
                    messages=[{"role": "user", "content": prompt_text}])
                return str(reply.choices[0].message.content or "")
            context = "workspace: %s" % os.environ.get("LOKI_WORKSPACE", "")
            try:
                found = asyncio.run_coroutine_threadsafe(options.suggest(text, complete, context), state.loop).result(timeout=90)
            except Exception as exc:  # noqa: BLE001 - no options: the request just goes ahead
                found = {"options": [], "error": str(exc)[:200]}
            self._send_json(200, {"ok": True, "offer": bool(found["options"]), **found})
            return
        if route == "/media/generate":
            # Spends the user's Higgsfield credits: only ever from an explicit request.
            import higgsfield  # pylint: disable=import-outside-toplevel
            ws = getattr(state.agent, "WORKSPACE", None)
            result = higgsfield.generate(str(data.get("prompt", "")), kind=str(data.get("kind", "image")),
                                         application=str(data.get("model", "")), workspace=ws,
                                         aspect_ratio=str(data.get("aspect_ratio", "16:9")))
            self._send_json(200 if result.get("ok") else 400, result)
            return
        if route == "/forecast/install":
            import forecast  # pylint: disable=import-outside-toplevel
            self._send_json(200, forecast.install())
            return
        if route in ("/checkpoints/rewind", "/checkpoints/take"):
            cps = getattr(state, "checkpoints", None)
            if cps is None:
                self._send_json(503, {"ok": False, "error": "checkpoints are not available"})
                return
            busy = state.try_busy()
            if busy is None:
                self._send_json(409, {"ok": False, "error": "Loki is working; stop it first, then rewind."})
                return
            try:
                if route == "/checkpoints/take":
                    point = cps.take(str(data.get("label", "saved by you"))[:200], kind="manual")
                    self._send_json(200 if point.get("id") else 500, {"ok": bool(point.get("id")), **point})
                else:
                    self._send_json(200, cps.rewind(str(data.get("id", ""))))
            finally:
                state.release_busy(busy)
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
        if route == "/approval/ask":
            # an outside agent (Claude Code, Codex ... through LOKI's tools - engine/make_mcp.py --shell) asks the owner first: the same
            # Allow / Deny card as LOKI's own risky actions, with what it is going to do. Blocks until answered.
            tool = str(data.get("tool") or "a command")[:120]
            details = str(data.get("details") or "")[:10_000]
            wait_s = max(10.0, min(float(data.get("timeout_s") or 600), 1800.0))
            deadline = time.time() + wait_s
            while True:                            # one card at a time: wait for the one on screen to be answered
                with state.lock:
                    if state.pending is None:
                        ticket = {"id": uuid.uuid4().hex, "tool": tool, "details": details, "event": threading.Event(),
                                  "approved": False}
                        state.pending = ticket
                        break
                if time.time() > deadline:
                    self._send_json(200, {"ok": True, "approved": False, "why": "another approval is still waiting"})
                    return
                time.sleep(0.5)
            try:
                answered = ticket["event"].wait(max(1.0, deadline - time.time()))
            finally:
                with state.lock:
                    if state.pending is ticket:
                        state.pending = None
            self._send_json(200, {"ok": True, "approved": bool(answered and ticket["approved"]),
                                  "why": "" if answered else "nobody answered in time"})
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
        if route == "/memory/core":
            self._send_json(*memory_core_api(state, "POST", data))
            return
        if route.startswith("/conversations") or route == "/memory":
            busy = state.try_busy()
            if busy is None:
                # another chat is answering (owner 2026-10-26: "it says i cant cuz thers another chat going"): a new
                # chat is made and opened anyway, another chat can be opened to read; the running answer keeps the
                # active chat, and what is sent in this one runs as a background agent (chat_job_done answers in it)
                if route == "/conversations":
                    cid = state.agent.park_conversation(str(data.get("title", "") or ""))
                    self._send_json(200, {"ok": True, "active": cid, "parked": True, "conversations": state.agent.list_conversations()})
                elif route == "/conversations/switch" and str(data.get("id", "")) in {c["id"] for c in state.agent.list_conversations()}:
                    cid = str(data.get("id", ""))
                    self._send_json(200, {"ok": True, "active": cid, "parked": cid != state.agent.active_conversation_id(),
                                          "messages": state.agent.conversation_messages(cid), "conversations": state.agent.list_conversations()})
                elif route == "/conversations/rename":
                    ok = state.agent.rename_conversation(str(data.get("id", "")), str(data.get("title", "")))
                    self._send_json(200 if ok else 404, {"ok": ok, "conversations": state.agent.list_conversations()})
                else:
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
        if route in ("/storage/clean", "/storage/restore", "/storage/keep", "/storage/empty-trash"):
            self._send_json(*storage_route(state, "POST", route, data))
            return
        if route in ("/tasks/retry", "/tasks/dismiss"):
            self._send_json(*task_board_route(state, "POST", route, data))
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
        if route == "/capabilities/install":
            self._send_json(*capability_install(state, data))
            return
        if route == "/autosetup/start":   # "Install everything this machine needs" (Settings > Add-ons)
            import auto_setup  # pylint: disable=import-outside-toplevel
            which = str(data.get("level") or "")
            if which not in ("", "recommended", "everything"):
                self._send_json(400, {"ok": False, "error": "level is recommended or everything"})
                return
            self._send_json(200, auto_setup.start(Path(getattr(state.agent, "DATA_DIR", ".")), which or "recommended",
                                                  delay_s=0.5))
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
        cid = str(spec.get("conversation_id") or "")
        agent = getattr(state, "agent", None)
        if cid and agent is not None and hasattr(agent, "append_to_conversation"):
            # a chat message run in the background: it is the chat's next turn - the agent gets the chat so far, the
            # message is in the chat at once, and the answer lands there when the job ends (chat_job_done)
            ask = str(spec.get("prompt") or "").strip()
            before = agent.conversation_context(cid) if hasattr(agent, "conversation_context") else ""
            if before:
                spec["prompt"] = ("This continues a chat with the owner. The chat so far:\n\n%s\n\nThe owner's new message "
                                  "(answer it as the chat's next reply):\n%s" % (before, ask))
            spec.setdefault("title", ask.splitlines()[0][:80] if ask else "")
            agent.append_to_conversation(cid, "user", ask)
            watch_chat_jobs(state)
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


def storage_route(state: "BridgeState", method: str, route: str, data: dict) -> tuple:
    import storage  # pylint: disable=import-outside-toplevel
    agent = state.agent
    data_dir = Path(getattr(agent, "DATA_DIR", "") or Path(__file__).resolve().parent.parent / "harness_data")
    ws = Path(getattr(agent, "WORKSPACE", "")) if getattr(agent, "WORKSPACE", "") else None
    return storage.route(data_dir, ws, method, route, data, job_status=_job_status_fn(state),
                         repo=Path(__file__).resolve().parent.parent)


def _job_status_fn(state: "BridgeState"):
    jobs = getattr(state, "jobs", None)

    def status(job_id: str) -> str:
        try:
            j = jobs.store.get(job_id) if jobs is not None else None
        except Exception:  # noqa: BLE001
            j = None
        return str((j or {}).get("status") or "")
    return status


def task_board_route(state: "BridgeState", method: str, route: str, data: dict) -> tuple:
    """GET /tasks/board; POST /tasks/retry {id} (try it again now), /tasks/dismiss {id} (take it off the board)."""
    auto = getattr(state, "autopilot", None)
    if auto is None:
        return 503, {"ok": False, "error": "The autopilot is not running on this computer."}
    with auto.lock:
        if method == "POST":
            key = str(data.get("id") or "")
            done = auto.retry(key) if route == "/tasks/retry" else auto.dismiss(key)
            if not done:
                return 404, {"ok": False, "error": "No such task (or a standing goal - those run in turn on their own)."}
            auto._save()  # pylint: disable=protected-access
        auto.settle()
        board = auto.board()
    return 200, board


def deps_status() -> dict:
    """GET /health "deps": what engine/deps_check.py found and installed at this start."""
    try:
        import deps_check  # pylint: disable=import-outside-toplevel
        return deps_check.status()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "failed": str(exc)}


def chat_job_answer(job: dict, data_dir: Path | None) -> str:
    """The answer a finished chat job gave: its result file (loki.run_job writes it), else the end of its log."""
    text = ""
    if data_dir is not None:
        try:
            text = (Path(data_dir) / "jobs" / (str(job.get("id", "")) + ".result.txt")).read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
    if not text:
        text = str(job.get("output") or job.get("error") or "").strip()[-4000:]
    for prefix in ("DONE:", "DONE -", "DONE"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    if job.get("status") in ("failed", "cancelled"):
        text = ("The background agent stopped (%s). " % job.get("status")) + (text or "It left no answer.")
    return text or "The background agent finished without an answer."


def chat_job_done(state: "BridgeState", job: dict) -> bool:
    """A chat job finished: its answer goes into the chat it came from (once). While a chat is answering in front, an
    answer for THAT chat waits until it is done (its history is being written)."""
    cid = str(job.get("conversation_id") or "")
    if not cid or job.get("status") not in ("done", "failed", "cancelled"):
        return False
    agent = getattr(state, "agent", None)
    if agent is None or not hasattr(agent, "append_to_conversation"):
        return False
    with state.lock:
        delivered = state.__dict__.setdefault("chat_jobs_delivered", set())
        if job.get("id") in delivered:
            return False
        if cid == agent.active_conversation_id() and state.chat_lock is not None and state.chat_lock.locked():
            state.__dict__.setdefault("chat_jobs_waiting", {})[job["id"]] = dict(job)
            return False
        delivered.add(job.get("id"))
    data_dir = Path(getattr(agent, "DATA_DIR", "") or ".") if getattr(agent, "DATA_DIR", "") else None
    return bool(agent.append_to_conversation(cid, "assistant", chat_job_answer(job, data_dir)))


def flush_chat_jobs(state: "BridgeState") -> None:
    waiting = state.__dict__.get("chat_jobs_waiting") or {}
    for job_id in list(waiting):
        job = waiting.pop(job_id, None)
        if job:
            chat_job_done(state, job)


def watch_chat_jobs(state: "BridgeState") -> None:
    """Hook the job supervisor once: every status change of a chat job is checked for its answer."""
    jobs = getattr(state, "jobs", None)
    if jobs is None or getattr(jobs, "_chat_watch", False):
        return
    previous = jobs.on_change

    def on_change(job: dict) -> None:
        if previous is not None:
            try:
                previous(job)
            except Exception:  # noqa: BLE001
                pass
        try:
            chat_job_done(state, job)
        except Exception:  # noqa: BLE001 - a chat answer never breaks the job loop
            traceback.print_exc()

    jobs.on_change = on_change
    jobs._chat_watch = True


def system_action(state: "BridgeState", route: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """POST /system/check {allow_paid?, image_test?} starts the System check (engine/system_check.py);
    POST /system/fix {action, args} does one of its SAFE fixes ("recheck" starts it again)."""
    import system_check  # pylint: disable=import-outside-toplevel
    action = str(data.get("action") or "")
    if route == "/system/check" or action == "recheck":
        options = data if route == "/system/check" else (data.get("args") or {})
        ctx = system_check.Context(state.agent, state, allow_paid=bool(options.get("allow_paid")),
                                   image_test=bool(options.get("image_test")), deps={"job_action": job_action})
        if not system_check.RUNNER.start(ctx):
            return 409, {"ok": False, "error": "The system check is already running.", **system_check.RUNNER.snapshot()}
        return 200, {"ok": True, "started": True, **system_check.RUNNER.snapshot()}
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    result = system_check.apply_fix(state, action, args)
    return (200 if result.get("ok") else 400), result


def bench_latest(state: Any) -> dict[str, Any]:
    """GET /bench: the latest task-success benchmark (tools/task_bench.py) for Settings > Lab."""
    try:
        tools_dir = str(Path(__file__).resolve().parent.parent / "tools")
        if tools_dir not in sys.path:
            sys.path.append(tools_dir)
        import task_bench  # pylint: disable=import-outside-toplevel
        import autopilot as _autopilot  # pylint: disable=import-outside-toplevel
        data_dir = Path(getattr(getattr(state, "agent", None), "DATA_DIR", "") or task_bench.data_dir())
        out = task_bench.latest(data_dir / "bench")
        auto = getattr(state, "autopilot", None)
        out["running"] = bool(auto is not None and auto.bench_running())
        out["enabled"] = _autopilot.task_bench_enabled()
        return out
    except Exception as exc:  # noqa: BLE001 - a missing report must never break the window
        return {"ok": False, "error": "the task benchmark is not available: %s" % exc}


def sketch_reply_latest(state: Any) -> dict[str, Any]:
    """GET /sketch/reply: the newest drawing LOKI made on the pad (sketches/loki-*.json), or none."""
    folder = Path(getattr(state.agent, "WORKSPACE", ".")) / "sketches"
    try:
        newest = max(folder.glob("loki-*.json"), key=lambda p: p.stat().st_mtime, default=None)
        if newest is None:
            return {"ok": True, "shapes": []}
        data = json.loads(newest.read_text(encoding="utf-8"))
        return {"ok": True, "name": newest.name, "note": str(data.get("note", ""))[:500],
                "shapes": list(data.get("shapes") or [])[:200], "t": data.get("t", 0)}
    except (OSError, ValueError):
        return {"ok": True, "shapes": []}


def memory_core_api(state: Any, method: str, data: Any) -> tuple[int, dict[str, Any]]:
    """GET /memory/core[?q=] lists (or recalls) LOKI's learned memories and skills; POST
    {action: learn|edit|forget, text, id, tier} changes them (engine/memory_core.py)."""
    import memory as memory_mod  # pylint: disable=import-outside-toplevel
    import memory_core  # pylint: disable=import-outside-toplevel
    import memory_store  # pylint: disable=import-outside-toplevel
    import memory_sync  # pylint: disable=import-outside-toplevel
    import skill_learning  # pylint: disable=import-outside-toplevel
    agent = state.agent
    root = Path(getattr(agent, "DATA_DIR", "") or memory_core.data_dir())
    workspace = getattr(agent, "WORKSPACE", None)
    notes = getattr(agent, "MEMORY_FILE", None)
    if method == "GET":
        query = ((data or {}).get("q") or [""])[0] if isinstance(data, dict) else ""
        kind = ((data or {}).get("kind") or [""])[0] if isinstance(data, dict) else ""

        def clean(i: dict) -> dict:
            return {k: v for k, v in i.items() if not k.startswith("_")}
        if query:
            # what LOKI would recall for this (the same retrieval a request uses), with its scores
            found = memory_mod.retrieve(query, root=root, workspace=workspace, notes_file=notes, budget_tokens=2000,
                                        kinds=[kind] if kind else None, mark_used=False)
            items = [{"id": i["id"], "kind": i["kind"], "tier": i["tier"], "text": i["text"], "score": i["score"],
                      "why": i.get("why", {})} for i in found["items"]]
            extra = {"knowledge": found.get("knowledge", []), "mode": found.get("mode")}
        else:
            items = [clean(i) for i in reversed(memory_core.items(root, kind=kind))][:300]
            extra = {}
        midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        superseded = [clean(i) for i in reversed(memory_core.all_items(root)) if i.get("status") == "superseded"][:40]
        index = {}
        try:
            import knowledge  # pylint: disable=import-outside-toplevel
            if workspace:
                index = knowledge.project_index(Path(workspace), root).status()
        except Exception:  # noqa: BLE001
            pass
        return 200, {"ok": True, "items": items, "skills": skill_learning.learned(root),
                     "stats": memory_core.stats(root), "today": [clean(i) for i in memory_core.learned_since(midnight, root)],
                     "superseded": superseded, "kinds": [{"kind": k, "label": memory_store.KIND_LABEL[k]}
                                                         for k in memory_store.KINDS],
                     "sync": memory_sync.status(root), "index": index,
                     "profile": memory_mod.profile_block(root, notes), **extra}
    data = data if isinstance(data, dict) else {}
    action = str(data.get("action", "")).lower()
    item_id = str(data.get("id", ""))
    if action == "learn":
        out = memory_core.learn(str(data.get("text", "")), tier=str(data.get("tier", "semantic")), root=root,
                                source="owner", kind=str(data.get("kind", "") or ""))
    elif action == "edit":
        out = memory_core.edit(item_id, str(data.get("text", "")), root=root, kind=str(data.get("kind", "") or ""))
    elif action in ("forget", "undo"):
        out = memory_core.forget(item_id, root=root)
    elif action == "keep":
        out = memory_core.keep(item_id, root=root)
    elif action == "keep_all":
        midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        kept = [memory_core.keep(i["id"], root=root) for i in memory_core.learned_since(midnight, root)]
        out = {"ok": True, "kept": len(kept)}
    elif action == "restore":
        out = memory_core.restore(item_id, root=root)
    elif action == "sync":
        out = {"ok": True, "results": memory_sync.sync_all(root, notes)}
    elif action == "reindex":
        import knowledge  # pylint: disable=import-outside-toplevel
        if not workspace:
            return 400, {"ok": False, "error": "no workspace project is open"}
        out = knowledge.project_index(Path(workspace), root).refresh(budget_s=20.0)
    else:
        return 400, {"ok": False, "error": "action is learn, edit, forget, undo, keep, keep_all, restore, sync or reindex"}
    return (200 if out.get("ok") else 400), out


def memory_metadata(agent: Any) -> dict[str, Any]:
    """Which memories and learned skills this reply used (memory_core pack + memory tool), and the
    skill it learned - the reply metadata the window shows under the answer. {} when none."""
    out: dict[str, Any] = {}
    try:
        used = [dict(m) for m in (getattr(agent, "LAST_RECALL", None) or [])][:12]
        skills = list(getattr(agent, "LAST_SKILLS", None) or [])
        learned = dict(getattr(agent, "LAST_LEARNED", None) or {})
        noted = [dict(n) for n in (getattr(agent, "LAST_NOTED", None) or [])][:5]
    except Exception:  # noqa: BLE001
        return out
    if noted:
        out["memories_learned"] = noted
    if used:
        out["memories_used"] = used
    if skills:
        out["skills_used"] = skills
    if learned:
        out["learned_skill"] = {"id": learned.get("id", ""), "refreshed": bool(learned.get("refreshed"))}
    return out


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
    """POST /setup/pull {tags:[...]} | /setup/install-ollama | /setup/use {model} | /setup/prefer {prefer}
    | /setup/auto (one click) | /setup/upgrade {tag?}."""
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

    def use(model: str) -> dict:
        if model:
            os.environ["LOKI_LOCAL_MODEL"] = model
        else:
            os.environ.pop("LOKI_LOCAL_MODEL", None)
        try:   # remembered: survives an update restart and reaches every background job
            agent.write_env_setting("LOKI_LOCAL_MODEL", model or "")
            sfile = agent.DATA_DIR / "loki_settings.json"
            try:
                saved = json.loads(sfile.read_text(encoding="utf-8")) if sfile.is_file() else {}
            except ValueError:
                saved = {}
            saved["local_model"] = model or ""
            sfile.write_text(json.dumps(saved, indent=1), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print("  [setup] could not remember the local model: %s" % exc)
        return agent.resolve_local(force=True)
    if route in ("/setup/auto", "/setup/upgrade"):
        # One click: Ollama -> best fitting model -> long context -> switch -> keep warm.
        snap = ms.status(info=agent.HARDWARE or None)
        if route == "/setup/upgrade":
            upgrade = snap.get("upgrade") or {}
            tag = str(data.get("tag") or upgrade.get("tag") or "").strip()
            if not tag:
                return 409, {"ok": False, "error": "No better model fits this computer right now."}
            names = [m["name"] for m in snap["ollama"]["models"]]
            row = next((r for r in ms.plan(snap["scan"], names)["rows"] if r["tag"] == tag), None)
            if row is None:
                return 409, {"ok": False, "error": "%s does not fit this computer's memory." % tag}
            if not row["fits_disk"] and not row["installed"]:
                return 409, {"ok": False, "error": "Not enough free disk space for %s: free up %s GB first."
                             % (tag, row["free_up_gb"])}
            tags = [tag]
        else:
            tags = list(snap["auto"].get("tags") or [])
            if data.get("quick") and (snap.get("quick") or {}).get("tags"):
                tags = list(snap["quick"]["tags"])   # the welcome tour: a small, quick first model (session 30)
            if not tags:
                return 409, {"ok": False, "error": snap["auto"].get("error") or "No model fits this computer."}
        if not ms.start_in_background(ms.run_auto, tags, snap["scan"], use):
            return 409, {"ok": False, "error": "Already busy - wait for it to finish."}
        return 200, {"ok": True, "tags": tags, "progress": ms.PROGRESS.snapshot()}
    if route == "/setup/use":
        # Pinning a model must also give it a long enough context (see ms.with_long_context): with
        # Ollama's 4096 default the prompt is truncated, the user's message can be dropped, and a
        # strict template like Bonsai 2's answers HTTP 500 - LOKI then answers from another provider
        # without saying so. The one-click setup did this; the plain "use this model" did not.
        picked = str(data.get("model", "")).strip()
        if picked:
            try:
                picked = ms.with_long_context(picked, info=agent.HARDWARE or None)
            except Exception as exc:  # noqa: BLE001 - never block switching on the context step
                print("  [setup] could not prepare a long context for %s: %s" % (picked, exc))
        state_now = use(picked)
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


MENU_GROUPS = (("auto", "Automatic"), ("local", "On this computer"), ("free", "Free"),
               ("subscription", "Your subscriptions"), ("paid", "Pay per use"))


def model_menu(agent: Any) -> dict[str, Any]:
    """The model picker at the top: Smart first (and what it would use right now), then
    every model LOKI can use RIGHT NOW grouped by cost, then the ones that still need a
    key or a download. Never raises; a provider whose check fails is listed as not ready."""
    try:
        import providers_catalog  # pylint: disable=import-outside-toplevel
    except Exception:  # noqa: BLE001
        providers_catalog = None
    current = getattr(agent, "model_name", "")
    try:
        resolved = agent.active_model_name()
    except Exception:  # noqa: BLE001
        resolved = current
    entries = []
    for name in agent.MODELS:
        if name in ("smart", "online", "max", "fast"):
            continue
        card = (providers_catalog.get(name) if providers_catalog else None) or {}
        try:
            ready = bool(agent.provider_configured(name))
        except Exception:  # noqa: BLE001
            ready = False
        try:
            tier = agent.provider_tier(name)
        except Exception:  # noqa: BLE001
            tier = "free"
        cfg = agent.MODELS.get(name)
        entries.append({"name": name, "label": card.get("name") or name, "group": tier, "ready": ready,
                        "model": getattr(cfg, "model", "") or "", "blurb": card.get("blurb", "")})
    entries.sort(key=lambda e: (not e["ready"], [g for g, _ in MENU_GROUPS].index(e["group"])
                                if e["group"] in dict(MENU_GROUPS) else 9, e["label"].lower()))
    labels = {e["name"]: e["label"] for e in entries}
    auto = [{"name": "smart", "label": "Smart", "group": "auto", "ready": True,
             "blurb": "Picks the best free model for each message and switches when one runs out.",
             "using": labels.get(resolved, resolved) if current == "smart" else ""},
            {"name": "online", "label": "Online only", "group": "auto", "ready": True,
             "blurb": "Like Smart, but never uses a model on this computer."},
            {"name": "max", "label": "Max (hard tasks)", "group": "auto", "ready": True,
             "blurb": "The strongest model that is ready: your Claude Code / Codex plan first, then GLM-5.3 "
                      "(free on NVIDIA, thinking on). Slower - for hard builds, debugging and planning.",
             "using": labels.get(resolved, resolved) if current == "max" else ""},
            {"name": "fast", "label": "Fast", "group": "auto", "ready": True,
             "blurb": "The quickest capable model that is ready (Nemotron on NVIDIA, then DeepSeek V4.1 Flash) - for quick "
                      "questions and many small steps.",
             "using": labels.get(resolved, resolved) if current == "fast" else ""}]
    return {"entries": auto + entries, "groups": [{"id": g, "label": label} for g, label in MENU_GROUPS],
            "resolved": resolved, "resolved_label": labels.get(resolved, resolved),
            "ready_count": sum(1 for e in entries if e["ready"])}


def crm_route(state: "BridgeState", method: str, route: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """GET /crm (pipeline + lists) and POST /crm/<op> (add, update, delete, find, log, list,
    pipeline, history). The database is the engine's own (loki.crm_store: DATA_DIR/crm.sqlite3)."""
    import crm  # pylint: disable=import-outside-toplevel
    agent = getattr(state, "agent", None)
    try:
        store = agent.crm_store() if hasattr(agent, "crm_store") else \
            crm.CRM(Path(getattr(agent, "DATA_DIR", ".") or ".") / "crm.sqlite3")
    except Exception as exc:  # noqa: BLE001
        return 500, {"ok": False, "error": "the CRM could not be opened: %s" % exc}
    op = route[len("/crm/"):].strip("/") if route.startswith("/crm/") else ""
    return crm.handle(store, method, op, data)


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


def _num(value: Any, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def creative_summary() -> dict:
    """Settings > Creations: which local picture/video maker this machine has (engine/creative.py)."""
    try:
        import creative  # pylint: disable=import-outside-toplevel
        return creative.summary()
    except Exception as exc:  # noqa: BLE001 - the wall still works without it
        return {"error": "%s: %s" % (type(exc).__name__, str(exc)[:160])}


def capability_install(state: "BridgeState", data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """POST /capabilities/install {name}. pip-install one add-on's requirements into LOKI's venv.
    The owner asks for one add-on by name from Settings > Add-ons; nothing installs on its own."""
    registry = getattr(state.agent, "CAPABILITIES", None)
    if registry is None:
        return 503, {"ok": False, "error": "No capability registry."}
    name = str(data.get("name", "")).strip()
    if name not in {entry["name"] for entry in registry.present()}:
        return 400, {"ok": False, "error": "Unknown add-on: %s" % (name or "(none)")}
    result = addons_install.install(name)
    result["capabilities"] = registry.present()
    if state.jobs is not None:
        state.jobs._avail.clear()  # pylint: disable=protected-access
    return (200 if result.get("ok") else 400), result


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
    # SO_REUSEADDR: the engine must be able to rebind its port at once after a restart. A
    # previous instance that just exited leaves the port in TIME_WAIT, and macOS/Linux then
    # refuse the bind (Errno 48) for ~30 s - which the app reads as "this version did not
    # start" and rolls back, so a good update looks broken. With SO_REUSEADDR the bind still
    # fails over a live listener on macOS/Linux. On Windows SO_REUSEADDR means "share a port
    # that is in use" (a second process could bind over a live engine), and Windows already lets
    # a listener rebind a port that only has TIME_WAIT connections, so it stays off there.
    # port_is_answering() refuses a port that already accepts connections on every platform
    # before we bind (see start_bridge_server).
    allow_reuse_address = sys.platform != "win32"
    # A page load asks for ~25 files at once (index.html pulls every panel script), and the app's
    # window opens right when the engine is at its busiest (model warm-up, MCP servers connecting,
    # an update unpacking). socketserver's default backlog is 5, so the OS refuses the connections
    # past it and the browser reports ERR_CONNECTION_RESET / ERR_SOCKET_NOT_CONNECTED for some of
    # them - measured on the Mac: 46 of 60 simultaneous requests reset. The window then comes up
    # with dead panels (Play, Creations, Brain, the drawing pad) or, if app.js or app.css is one of
    # the dropped ones, blank. A generous backlog costs nothing; both platforms accept it.
    request_queue_size = 128

    def handle_error(self, request, client_address):  # noqa: D401
        """A client that hangs up mid-reply (BrokenPipe/ConnectionReset - a probe sending junk, a
        window closed while loading) is not an engine error: skip the traceback that buried real
        errors in engine.out. Everything else is logged as before."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)

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


def port_is_answering(host: str, port: int) -> bool:
    """True when something already accepts connections on host:port (a live bridge).

    A port left in TIME_WAIT by a just-exited engine refuses connections, so it reads as free
    here and the bind is allowed - exactly what we want after a restart. Only a port that still
    answers (a running engine) is refused, on every platform.
    """
    if port == 0:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


def start_bridge_server(state: BridgeState, secret_path: Path, secret: str) -> tuple[BridgeHTTPServer, threading.Thread]:
    if port_is_answering(HOST, PORT):
        raise OSError(errno.EADDRINUSE, f"port {PORT} is already serving a bridge")
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


# Startup timing (owner 2026-10-25: "windows feels slow on start up"): how long each step before the window can talk to
# the engine took, printed at "ready" (the slowest first) and kept in <data>/app/startup.json for System check.
_STARTUP = {"t0": time.time(), "last": time.time(), "steps": [], "cur": "start (logging, paths)"}


def _startup_mark(label: str) -> None:
    """The step called `label` starts now; the one before it is timed."""
    now = time.time()
    _STARTUP["steps"].append((_STARTUP["cur"], round(now - _STARTUP["last"], 2)))
    _STARTUP["last"], _STARTUP["cur"] = now, label


def _startup_report() -> None:
    total = round(time.time() - _STARTUP["t0"], 2)
    slow = sorted(_STARTUP["steps"], key=lambda x: -x[1])[:6]
    print("[loki-bridge] engine up in %.1f s; slowest: %s" % (total, ", ".join("%s %.1fs" % s for s in slow)), flush=True)
    try:
        data = Path(os.environ.get("LOKI_DATA") or Path(__file__).resolve().parent.parent / "harness_data") / "app"
        data.mkdir(parents=True, exist_ok=True)
        (data / "startup.json").write_text(json.dumps({"total_s": total, "steps": _STARTUP["steps"],
                                                       "at": time.time()}, indent=1), encoding="utf-8")
    except OSError:
        pass


async def serve() -> None:
    _STARTUP.update(t0=time.time(), last=time.time())
    global STATE_DIR, UI_DIR
    args = parse_args()
    try:   # a restart after an update: let the old engine free its ports first
        time.sleep(min(30.0, float(os.environ.pop("LOKI_START_DELAY", "0") or 0)))
    except ValueError:
        pass
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
    _startup_mark("import loki (the engine)")
    import loki  # pylint: disable=import-outside-toplevel
    _startup_mark("bridge state, session")

    if loki.model_name not in loki.MODELS:
        loki.model_name = "local-reasoning"
    secret_path = Path(args.secret_file)
    secret = secrets.token_urlsafe(32)

    state = BridgeState(loki, secret)
    state.restart_engine = restart_engine
    state.project = project
    threading.Thread(target=memory_guard, args=(state,), daemon=True, name="loki-memory-guard").start()
    _startup_mark('forecast')
    try:   # the owner said yes to TimesFM-3 (2026-10-17): install it once where it is missing
        import forecast  # pylint: disable=import-outside-toplevel
        forecast.install_if_approved()
    except Exception:  # noqa: BLE001
        pass
    _startup_mark('workbench')
    try:
        import workbench  # pylint: disable=import-outside-toplevel
        state.checkpoints = workbench.Checkpoints(project, (STATE_DIR or project / ".loki") / "checkpoints.git")
    except Exception as exc:  # noqa: BLE001 - checkpoints are a convenience, never a reason not to start
        state.checkpoints = None
        print("[loki-bridge] checkpoints are off: %s" % exc, flush=True)
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
    _startup_mark('workers')
    try:
        import workers  # pylint: disable=import-outside-toplevel
        state.jobs = workers.default_supervisor(Path(loki.DATA_DIR))
        watch_chat_jobs(state)   # chat jobs answer in their chat, also those that finish after a restart
        state.jobs.start()
        loki.JOBS = state.jobs
        try:
            import laya as _laya  # pylint: disable=import-outside-toplevel
            loki.TEAMS = loki.teams.TeamRunner(state.jobs, policy=loki.POLICY,
                                               decide=_laya.decide if _laya.backend() else None,
                                               choose_model=loki.model_for_role)
            threading.Thread(target=loki.TEAMS.run_forever, daemon=True, name="loki-teams").start()
        except Exception as exc:  # noqa: BLE001 - teams are optional; jobs still work
            print(f"[loki-bridge] agent teams unavailable: {exc}", flush=True)
        try:
            import autopilot as _autopilot  # pylint: disable=import-outside-toplevel
            import system_check as _sc  # pylint: disable=import-outside-toplevel

            def _run_check() -> dict:
                ctx = _sc.Context(loki, state=state, allow_paid=False, image_test=False)
                return _sc.run(ctx)

            def _apply(action: str, args: dict) -> dict:
                return _sc.apply_fix(state, action, args)

            import evolve as _evolve  # pylint: disable=import-outside-toplevel
            state.evolve = _evolve.Evolve(Path(__file__).resolve().parent.parent, Path(loki.DATA_DIR))
            state.autopilot = _autopilot.Autopilot(
                state=state, agent=loki, data_dir=Path(loki.DATA_DIR),
                run_check=_run_check, apply_fix=_apply, start_team=loki.start_team,
                evolve=state.evolve, improve=loki.improve_loki)
            if _autopilot.Autopilot.enabled():
                threading.Thread(target=state.autopilot.run_forever, daemon=True, name="loki-autopilot").start()
                print("[loki-bridge] autopilot on: LOKI works when idle (health, inbox, weekly report)", flush=True)
        except Exception as exc:  # noqa: BLE001 - the autopilot is optional
            print(f"[loki-bridge] autopilot unavailable: {exc}", flush=True)
        print("[loki-bridge] background jobs: " + ", ".join(
            "%s %s" % (name, "ready" if info["available"] else "off")
            for name, info in state.jobs.status()["backends"].items()), flush=True)
    except Exception as exc:  # noqa: BLE001 - jobs are optional; chat must still start
        print(f"[loki-bridge] background jobs unavailable: {exc}", flush=True)
    try:   # the agent system's engine side: For you handlers, the orchestrator's background runs (engine/agentsys/)
        from agentsys import runtime as _agentsys_rt  # pylint: disable=import-outside-toplevel
        _agentsys_rt.install(loki)
        _agentsys_rt.attach(state)
    except Exception as exc:  # noqa: BLE001 - the chat works without it
        print(f"[loki-bridge] agent system unavailable: {exc}", flush=True)
    _startup_mark('updater')
    try:
        import updater  # pylint: disable=import-outside-toplevel
        updater.RUNNING_COMMIT = updater.version().get("commit", "")
        def _idle(strict: bool = True) -> bool:   # nobody is talking to LOKI (strict: and no background job runs)
            if (state.chat_lock is not None and state.chat_lock.locked()) or state.chat_request_lock.locked() \
                    or state.task_request_lock.locked() or time.time() - state.last_request_at < 120:
                return False
            if not strict:
                return True
            try:
                jobs = state.jobs.store.all() if state.jobs is not None else []
                return not any(j.get("status") in ("queued", "starting", "working", "blocked") for j in jobs)
            except Exception:  # noqa: BLE001
                return False

        def _apply() -> None:
            import update_all  # pylint: disable=import-outside-toplevel
            update_all.apply_here(updater, restart_engine)

        threading.Thread(target=updater.run_forever, kwargs={"idle": _idle, "apply": _apply},
                         daemon=True, name="loki-update").start()
        print("[loki-bridge] version " + (updater.version().get("commit") or "(not a git checkout)"), flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[loki-bridge] update checks unavailable: {exc}", flush=True)
    _startup_mark('laya')
    try:
        import laya  # pylint: disable=import-outside-toplevel
        laya.warm()  # the first layer asks Laya about every request: load the model now
        print("[loki-bridge] first layer: " + (
            "Laya (%s)" % laya.backend() if laya.backend() else
            "built-in rules (Laya not set up: tools/setup_laya.py)"), flush=True)
    except Exception as exc:  # noqa: BLE001 - Laya is optional; the rules answer without it
        print(f"[loki-bridge] Laya unavailable: {exc}", flush=True)
    _startup_mark('peer_link')
    try:
        import peer_link  # pylint: disable=import-outside-toplevel
        state.peer_server = peer_link.start(state, loki)
        threading.Thread(target=peer_link.sync_forever, args=(state, loki), daemon=True, name="loki-peers").start()
    except OSError as exc:
        print(f"[loki-bridge] peer link could not listen: {exc}", flush=True)
    except Exception as exc:  # noqa: BLE001 - the link is optional; chat must still start
        print(f"[loki-bridge] peer link unavailable: {exc}", flush=True)
    _startup_mark('phone_link')
    try:
        import phone_link  # pylint: disable=import-outside-toplevel
        state.phone_server = phone_link.start(state, loki)
    except Exception as exc:  # noqa: BLE001 - the phone link is optional; chat must still start
        print(f"[loki-bridge] phone link unavailable: {exc}", flush=True)
    _startup_mark('channels')
    try:
        import channels  # pylint: disable=import-outside-toplevel
        channels.start(state, loki)   # Telegram: idle until a bot token is saved and this machine polls
    except Exception as exc:  # noqa: BLE001 - channels are optional; chat must still start
        print(f"[loki-bridge] channels unavailable: {exc}", flush=True)
    _startup_mark('automations')
    try:   # session 29: automations - triggers -> conditions -> steps, one runner (engine/automations.py)
        import automations  # pylint: disable=import-outside-toplevel
        automations.start(state, loki)
    except Exception as exc:  # noqa: BLE001 - automations are optional; chat must still start
        print(f"[loki-bridge] automations unavailable: {exc}", flush=True)
    _startup_mark('qol')
    try:   # session 29: chat QoL - interrupted turns, steering, allow-for-session (engine/qol.py)
        import qol  # pylint: disable=import-outside-toplevel
        qol.install(state, loki)
    except Exception as exc:  # noqa: BLE001 - comfort features are optional; chat must still start
        print(f"[loki-bridge] chat QoL unavailable: {exc}", flush=True)
    threading.Thread(target=write_status_forever, args=(state,), daemon=True, name="loki-status").start()
    threading.Thread(target=lambda: loki.resolve_local(force=True), daemon=True, name="loki-local").start()
    _startup_mark('ninerouter')
    try:   # 9Router (engine/ninerouter.py): start it on 127.0.0.1 when it is installed and not running
        import ninerouter  # pylint: disable=import-outside-toplevel
        ninerouter.start_background()
    except Exception as exc:  # noqa: BLE001 - an add-on; chat must still start
        print(f"[loki-bridge] 9router unavailable: {exc}", flush=True)
    _startup_mark('provider health probes')
    try:   # each provider's live state for routing and Settings > Connections (free /models probes only)
        loki.provider_health.start_background(loki)
    except Exception as exc:  # noqa: BLE001 - routing works without it
        print(f"[loki-bridge] provider health probes unavailable: {exc}", flush=True)
    threading.Thread(target=initial_ecc_sync, args=(loki,), daemon=True).start()
    threading.Thread(target=dump_godot_api, args=(args.godot_exe, root), daemon=True).start()
    _startup_mark('ECC sync, Godot API threads')
    try:
        _startup_mark("start the HTTP server")
        server, server_thread = start_bridge_server(state, secret_path, secret)
        _startup_mark("done")
        _startup_report()
    except OSError as exc:
        await stack.aclose()
        # another LOKI engine already serves this port (owner 2026-10-28, the PC: a second LOKI window started a second
        # engine; it crashed 5 times into the first one and the app gave up). Say so with its own exit code: the app
        # attaches to the running engine (or restarts it on the new code) instead of counting a crash.
        print(f"[loki-bridge] another LOKI engine already serves port {PORT}; leaving it running (exit "
              f"{ALREADY_RUNNING_EXIT_CODE})", flush=True)
        raise SystemExit(ALREADY_RUNNING_EXIT_CODE) from exc
    keeper_stop = threading.Event()
    keeper = threading.Thread(target=keep_secret_alive, args=(secret_path, secret, keeper_stop), name="loki-secret-keeper", daemon=True)
    keeper.start()
    print(f"[loki-bridge] workspace {project}; Godot {'at ' + args.godot_exe if args.godot_exe else 'not configured'}", flush=True)
    print(f"[loki-bridge] ready at http://{HOST}:{PORT} (model={loki.MODELS[loki.model_name].model})", flush=True)
    try:   # the live Godot link: a Godot editor with the LOKI Studio plugin finds this engine (engine/godot_live.py)
        import godot_live  # pylint: disable=import-outside-toplevel
        godot_live.write_connect(PORT, secret)
        # no Godot on this computer: LOKI's own Godot 4.7.2, so Open in Godot opens a project at once (engine/godot_web.py)
        def godot_ready() -> None:
            try:
                import godot_web  # pylint: disable=import-outside-toplevel
                godot_web.prefetch(lambda t: print(t, flush=True))
            except Exception as exc:  # noqa: BLE001
                print(f"[loki-bridge] LOKI's Godot not fetched: {exc}", flush=True)
        threading.Thread(target=godot_ready, daemon=True, name="loki-godot-ready").start()
    except Exception as exc:  # noqa: BLE001 - the editor link is optional
        print(f"[loki-bridge] live Godot link unavailable: {exc}", flush=True)
    try:   # LOKI installs the add-ons it needs by itself, in the background (engine/auto_setup.py)
        import auto_setup  # pylint: disable=import-outside-toplevel

        def _busy() -> bool:
            held = state.try_busy()
            if held is None:
                return True
            for lock in held:
                lock.release()
            return False
        auto_setup.start(Path(getattr(loki, "DATA_DIR", ".")), busy=_busy)
    except Exception:  # noqa: BLE001
        pass
    try:   # every required package installed - a failed pip run during an update is retried here (engine/deps_check.py)
        import deps_check  # pylint: disable=import-outside-toplevel
        deps_check.start_background()
    except Exception:  # noqa: BLE001
        pass
    try:   # NVIDIA serves DeepSeek under changing names; a wrong one was HTTP 404 on the Mac
        import nim_models  # pylint: disable=import-outside-toplevel
        if "nvidia" in loki.MODELS:
            nim_models.fix_later(loki.MODELS["nvidia"], on_change=lambda c: print("[loki-bridge] NVIDIA model " + c, flush=True))
            if "nvidia-pro" in loki.MODELS:   # Max mode: the strongest model this key serves (nim_models.STRONGEST)
                nim_models.fix_later(loki.MODELS["nvidia-pro"], key=loki.MODELS["nvidia"].api_key,
                                     on_change=lambda c: print("[loki-bridge] Max mode model " + c, flush=True))
            if "nvidia-nemotron" in loki.MODELS:   # Fast mode: the Nemotron this key serves (nim_models.NEMOTRON)
                nim_models.fix_later(loki.MODELS["nvidia-nemotron"], key=loki.MODELS["nvidia"].api_key,
                                     on_change=lambda c: print("[loki-bridge] Nemotron model " + c, flush=True))
    except Exception:  # noqa: BLE001
        pass
    try:   # speed watch (E6): how long the engine took to answer
        import speed_watch  # pylint: disable=import-outside-toplevel
        speed_watch.record("startup", (time.monotonic() - ENGINE_T0) * 1000, root=Path(loki.DATA_DIR))
    except Exception:  # noqa: BLE001
        pass
    try:
        import updater  # pylint: disable=import-outside-toplevel
        if os.environ.get("LOKI_SUPERVISED") == "1" and updater.on_trial():
            # A fresh update is only good once the WINDOW works too (the Mac's white window had a
            # healthy engine): wait for the window to say it is ready, else go back.
            threading.Thread(target=update_trial_watch, args=(updater,), daemon=True, name="loki-update-trial").start()
        else:
            updater.mark_good()   # this version starts and answers here: it is the one to go back to
    except Exception:  # noqa: BLE001
        pass
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
        if state.phone_server is not None:
            state.phone_server.stop()
        for channel in (getattr(state, "channels", None) or {}).values():
            channel.stop()
        server.shutdown()
        server.server_close()
        await stack.aclose()
        secret_path.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(serve())
