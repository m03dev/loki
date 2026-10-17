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
            # LOKI World's Godot web export (app/ui/world_godot/): the engine and the game pack
            ".wasm": "application/wasm", ".pck": "application/octet-stream"}
UI_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' data: blob:; "
          "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
# The Godot world page only: WebAssembly needs 'wasm-unsafe-eval' (not 'unsafe-eval' - no JS eval),
# and LOKI's own window frames it (same origin). Every other UI page keeps UI_CSP.
GODOT_WORLD_PAGE = "/ui/world_godot/index.html"
GODOT_WORLD_CSP = (UI_CSP.replace("script-src 'self'", "script-src 'self' 'wasm-unsafe-eval'")
                   .replace("frame-ancestors 'none'", "frame-ancestors 'self'"))


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
    """What LOKI World shows besides the agents: your other machines, the model answering
    right now, and today's usage. Cheap: cached, never waits on the network."""
    out: dict = {}
    try:
        import peer_link  # pylint: disable=import-outside-toplevel
        out["machines"] = peer_link.world_machines()
    except Exception:  # noqa: BLE001
        out["machines"] = []
    try:   # the creations hall: how many things LOKI made, and the newest few
        import creations  # pylint: disable=import-outside-toplevel
        made = creations.list_creations(Path(getattr(agent, "WORKSPACE", ".")), limit=400)
        out["creations"] = {"count": len(made), "latest": [{"title": c["title"], "kind": c["kind"], "show": c["show"]}
                                                           for c in made[:5]]}
    except Exception:  # noqa: BLE001
        out["creations"] = {"count": 0, "latest": []}
    try:   # the MMO: the owner's avatars on the other machines, and the world chat
        import presence  # pylint: disable=import-outside-toplevel
        out["presence"] = presence.world_part()
    except Exception:  # noqa: BLE001
        out["presence"] = {"players": [], "chat": [], "cursor": 0}
    try:   # the island you stand on is this machine: its name and OS
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
        if route == GODOT_WORLD_PAGE:
            self._send_static(found, framed=True, csp=GODOT_WORLD_CSP)
            return True
        self._send_static(found, framed=(route == "/ui/play.html"))
        return True

    def _send_static(self, found: Path, framed: bool = False, csp: str = "") -> None:
        """One static file. `framed`: the Play page, which LOKI's own window shows in a sandboxed
        frame - it may be framed by LOKI itself (same origin) and nothing else. `csp`: a page's
        own policy (the Godot world page: GODOT_WORLD_CSP)."""
        body = found.read_bytes()
        try:
            self.send_response(200)
            self.send_header("Content-Type", UI_TYPES.get(found.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN" if framed else "DENY")
            self.send_header("Content-Security-Policy", csp or (
                UI_CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'") if framed else UI_CSP))
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

    def _oauth_callback(self, route: str) -> bool:
        """GET /oauth/openrouter/callback: the browser comes straight back from openrouter.ai.
        No bearer token here; signin.openrouter_finish only completes a flow this engine
        started (its random `state`), and the Host must be this machine's loopback."""
        if route != "/oauth/openrouter/callback":
            return False
        import signin  # pylint: disable=import-outside-toplevel
        import portal_api  # pylint: disable=import-outside-toplevel
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            self._send_json(403, {"ok": False, "error": "Host not allowed."})
            return True
        query = parse_qs(urlparse(self.path).query)
        result = signin.openrouter_finish((query.get("state") or [""])[0], (query.get("code") or [""])[0],
                                          lambda p, k: portal_api.connect(self.server.state.agent, p, k))
        body = signin.callback_page(bool(result.get("ok")), result.get("message") or result.get("error", "")).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        return True

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if self._serve_ui(route):
            return
        if self._serve_game(route):
            return
        if self._serve_creation(route):
            return
        if self._oauth_callback(route):
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
        if route in ("/speed", "/jobs/stats", "/user_tools"):   # session 28: LOKI improving itself
            import self_api  # pylint: disable=import-outside-toplevel
            self._send_json(*self_api.route(self.server.state, "GET", self.path, {}))
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
                                  "update": update_status(), "ui_errors": UI_ERRORS[-10:]})
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
        if route.startswith("/mmo/"):   # LOKI World MMO game state (docs/MMO_API.md, engine/mmo_state.py)
            import mmo_state  # pylint: disable=import-outside-toplevel
            self._send_json(*mmo_state.route(self.server.state, "GET", route, {}, job_action))
            return
        if route == "/world/presence":   # LOKI World MMO: the other machines' avatars + chat
            import presence  # pylint: disable=import-outside-toplevel
            try:
                after = int((parse_qs(urlparse(self.path).query).get("after") or ["0"])[0])
            except ValueError:
                after = 0
            self._send_json(200, presence.HUB.snapshot(after))
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
        try:
            import portal_api  # pylint: disable=import-outside-toplevel
            handled = portal_api.handle_post(state, route, data, port=PORT, job_action=job_action)
        except Exception as exc:  # noqa: BLE001
            handled = (500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
        if handled is not None:
            self._send_json(*handled)
            return
        import self_api  # pylint: disable=import-outside-toplevel - session 28: LOKI improving itself
        if self_api.handles("POST", route):
            self._send_json(*self_api.route(state, "POST", route, data, job_action))
            return
        if route in ("/world/presence", "/world/retry"):
            self._send_json(*world_action(state, route, data))
            return
        if route.startswith("/mmo/"):   # LOKI World MMO game actions (docs/MMO_API.md)
            import mmo_state  # pylint: disable=import-outside-toplevel
            self._send_json(*mmo_state.route(state, "POST", route, data, job_action))
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
                result = future.result()  # wait as long as the task needs
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
        if route == "/capabilities/install":
            self._send_json(*capability_install(state, data))
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


def world_action(state: "BridgeState", route: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """LOKI World MMO (app/ui/mmo/): POST /world/presence {player, chat?, after} - this machine's
    avatar, shared with the linked machines (presence.py); POST /world/retry {id, model?} - start
    a failed job again on a stronger model (the loot of a defeated failure monster). The retry
    goes through job_action, so the policy decides exactly as for any new job."""
    import presence  # pylint: disable=import-outside-toplevel
    if route == "/world/presence":
        return 200, presence.app_post(data)
    jobs = state.jobs
    if jobs is None:
        return 503, {"ok": False, "error": "Background jobs are not running."}
    job_id = "".join(ch for ch in str(data.get("id") or "") if ch.isalnum())[:16]
    try:
        spec = presence.retry_spec(jobs.store.get(job_id), str(data.get("model") or ""))
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return job_action(state, "/jobs", spec)


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
    import memory_core  # pylint: disable=import-outside-toplevel
    import skill_learning  # pylint: disable=import-outside-toplevel
    root = Path(getattr(state.agent, "DATA_DIR", "") or memory_core.data_dir())
    if method == "GET":
        query = ((data or {}).get("q") or [""])[0] if isinstance(data, dict) else ""
        if query:
            found = memory_core.fetch(query, root=root)
            items = found["items"]
        else:
            items = list(reversed(memory_core.items(root)))[:200]
        return 200, {"ok": True, "items": items, "skills": skill_learning.learned(root),
                     "stats": memory_core.stats(root)}
    data = data if isinstance(data, dict) else {}
    action = str(data.get("action", "")).lower()
    if action == "learn":
        out = memory_core.learn(str(data.get("text", "")), tier=str(data.get("tier", "semantic")), root=root,
                                source="owner")
    elif action == "edit":
        out = memory_core.edit(str(data.get("id", "")), str(data.get("text", "")), root=root)
    elif action == "forget":
        out = memory_core.forget(str(data.get("id", "")), root=root)
    else:
        return 400, {"ok": False, "error": "action is learn, edit or forget"}
    return (200 if out.get("ok") else 400), out


def memory_metadata(agent: Any) -> dict[str, Any]:
    """Which memories and learned skills this reply used (memory_core pack + memory tool), and the
    skill it learned - the reply metadata the window shows under the answer. {} when none."""
    out: dict[str, Any] = {}
    try:
        used = [dict(m) for m in (getattr(agent, "LAST_RECALL", None) or [])][:12]
        skills = list(getattr(agent, "LAST_SKILLS", None) or [])
        learned = dict(getattr(agent, "LAST_LEARNED", None) or {})
    except Exception:  # noqa: BLE001
        return out
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
        if name in ("smart", "online"):
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
             "blurb": "Like Smart, but never uses a model on this computer."}]
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


async def serve() -> None:
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
    import loki  # pylint: disable=import-outside-toplevel

    if loki.model_name not in loki.MODELS:
        loki.model_name = "local-reasoning"
    secret_path = Path(args.secret_file)
    secret = secrets.token_urlsafe(32)

    state = BridgeState(loki, secret)
    state.restart_engine = restart_engine
    state.project = project
    threading.Thread(target=memory_guard, args=(state,), daemon=True, name="loki-memory-guard").start()
    try:   # the owner said yes to TimesFM-3 (2026-10-17): install it once where it is missing
        import forecast  # pylint: disable=import-outside-toplevel
        forecast.install_if_approved()
    except Exception:  # noqa: BLE001
        pass
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
    try:
        import workers  # pylint: disable=import-outside-toplevel
        state.jobs = workers.default_supervisor(Path(loki.DATA_DIR))
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
    try:
        import updater  # pylint: disable=import-outside-toplevel
        updater.RUNNING_COMMIT = updater.version().get("commit", "")
        def _idle() -> bool:   # nobody is talking to LOKI and no background job is running
            if (state.chat_lock is not None and state.chat_lock.locked()) or state.chat_request_lock.locked() \
                    or state.task_request_lock.locked() or time.time() - state.last_request_at < 120:
                return False
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
    try:
        import phone_link  # pylint: disable=import-outside-toplevel
        state.phone_server = phone_link.start(state, loki)
    except Exception as exc:  # noqa: BLE001 - the phone link is optional; chat must still start
        print(f"[loki-bridge] phone link unavailable: {exc}", flush=True)
    try:
        import channels  # pylint: disable=import-outside-toplevel
        channels.start(state, loki)   # Telegram: idle until a bot token is saved and this machine polls
    except Exception as exc:  # noqa: BLE001 - channels are optional; chat must still start
        print(f"[loki-bridge] channels unavailable: {exc}", flush=True)
    threading.Thread(target=write_status_forever, args=(state,), daemon=True, name="loki-status").start()
    threading.Thread(target=lambda: loki.resolve_local(force=True), daemon=True, name="loki-local").start()
    try:   # each provider's live state for routing and Settings > Connections (free /models probes only)
        loki.provider_health.start_background(loki)
    except Exception as exc:  # noqa: BLE001 - routing works without it
        print(f"[loki-bridge] provider health probes unavailable: {exc}", flush=True)
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
