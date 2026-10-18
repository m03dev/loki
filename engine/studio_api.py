"""The engine's two small doors for LOKI Studio (studio/, docs/STUDIO.md):

  GET  /studio            is Studio running here, and how to start it by hand
  POST /studio/open       open LOKI Studio (its own app and window; or bring it to the front)
  POST /studio/embed      the Studio TAB of LOKI's window: start Studio's server in the background (no window) once,
                          and give the tab its address with Studio's token (app/ui/modebar.js frames it)
  POST /engine/restart    restart this engine (the LOKI MCP API's restart_engine, after the owner said yes)

LOKI Studio is a separate program on purpose - like a game editor next to the game - so it keeps
working when LOKI is broken, stopped or mid-update. LOKI itself only has a button that opens it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
ROUTES = {("GET", "/studio"), ("POST", "/studio/open"), ("POST", "/studio/embed"), ("POST", "/engine/restart")}
_EMBED = {"t": 0.0, "lock": threading.Lock()}
EMBED_GRACE_S = 25.0      # one background start at a time; a second click while it comes up does not start another


def handles(method: str, route: str) -> bool:
    return (method, route) in ROUTES


def _data(state: Any) -> Path:
    agent = getattr(state, "agent", None)
    return Path(getattr(agent, "DATA_DIR", "") or os.getenv("LOKI_DATA") or (REPO / "harness_data"))


def how_to_start() -> str:
    if sys.platform == "win32":
        return 'Double-click "Loki Studio.cmd" in the LOKI folder (%s).' % REPO
    if sys.platform == "darwin":
        return "Open LOKI Studio.app (made by studio/make_studio_app.sh), or run: bash \"%s\"" % (REPO / "studio" / "loki_studio.sh")
    return "Run: bash \"%s\"" % (REPO / "studio" / "loki_studio.sh")


def running(data: Path) -> dict:
    """Studio's own note about itself (studio/server.py writes it), if that Studio answers."""
    try:
        info = json.loads((data / "studio" / "running.json").read_text(encoding="utf-8"))
        token = (data / "studio" / "studio.token").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return {}
    req = urllib.request.Request("http://127.0.0.1:%d/api/ping" % int(info.get("port") or 0),
                                 headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                return dict(info, token=token)
    except (OSError, ValueError):
        pass
    return {}


def _spawn(argv: list, data: Path, popen=None) -> None:
    env = dict(os.environ, LOKI_DATA=str(data))
    for name in ("LOKI_SUPERVISED", "LOKI_PORT", "LOKI_JOB_ID"):
        env.pop(name, None)
    kwargs: dict = {"cwd": str(REPO), "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    python = sys.executable
    if sys.platform == "win32" and python.lower().endswith("python.exe"):
        quiet = python[:-10] + "pythonw.exe"
        python = quiet if Path(quiet).is_file() else python
    (popen or subprocess.Popen)([python, *argv], **kwargs)  # noqa: S603 - our own program


def _git_head(tree: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=5, check=False)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def wanted_code(data: Path) -> str:
    """The commit Studio should run now: its pin (the move it was cleared for, else the pin), else the checkout."""
    try:
        rec = json.loads((data / "studio" / "pin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = {}
    if isinstance(rec, dict) and (data / "studio" / "pinned" / "studio" / "studio_app.py").is_file():
        return str(rec.get("next") or rec.get("commit") or "")
    return _git_head(REPO)


def stale(info: dict, data: Path) -> bool:
    """True when the running Studio's code is not the code it should run (or it is too old to say)."""
    have = str(info.get("code") or "")
    want = wanted_code(data)
    return not have or bool(want and have != want)


def busy(data: Path, now: float | None = None) -> bool:
    """A Studio session is working right now: never restart under it."""
    import time as _time  # pylint: disable=import-outside-toplevel
    now = _time.time() if now is None else now
    for path in (data / "studio" / "sessions").glob("*/session.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(rec.get("status")) in ("working", "starting") and now - float(rec.get("updated") or 0) < 900:
            return True
    return False


def stop(info: dict, wait_s: float = 4.0) -> None:
    """End a running Studio server (its sessions and worktrees stay on disk)."""
    import signal  # pylint: disable=import-outside-toplevel
    import time as _time  # pylint: disable=import-outside-toplevel
    pid = int(info.get("pid") or 0)
    if pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)   # Windows: TerminateProcess
    except OSError:
        return
    end = _time.time() + wait_s
    while _time.time() < end:
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/api/ping" % int(info.get("port") or 0),
                                         headers={"Authorization": "Bearer " + str(info.get("token") or "")})
            urllib.request.urlopen(req, timeout=0.5).close()
        except (OSError, ValueError):
            return
        _time.sleep(0.25)


def embed(data: Path, popen=None, clock=None) -> dict:
    """Studio for the tab: its address + token when it runs; else start its server once in the background."""
    import time as _time  # pylint: disable=import-outside-toplevel
    now = (clock or _time.time)()
    up = running(data)
    if up and stale(up, data) and not busy(data):
        stop(up)        # a Studio still on old code (the Mac ran 9d1f8db for hours, 2026-10-18): start it fresh
        up = running(data)
    if up:
        return {"ok": True, "running": True, "url": "http://127.0.0.1:%d/#token=%s" % (int(up["port"]), up["token"])}
    if getattr(sys, "frozen", False):
        return {"ok": False, "error": "This packaged LOKI has no Studio inside. " + how_to_start()}
    script = REPO / "studio" / "studio_app.py"
    if not script.is_file():
        return {"ok": False, "error": "studio/studio_app.py is missing in %s" % REPO}
    with _EMBED["lock"]:
        if now - _EMBED["t"] < EMBED_GRACE_S:
            return {"ok": True, "running": False, "starting": True, "note": "LOKI Studio is starting..."}
        _EMBED["t"] = now
    try:
        _spawn([str(script), "--headless"], data, popen)
    except OSError as exc:
        _EMBED["t"] = 0.0
        return {"ok": False, "error": "could not start LOKI Studio (%s). %s" % (exc, how_to_start())}
    return {"ok": True, "running": False, "starting": True, "started": True, "note": "LOKI Studio is starting..."}


def open_studio(data: Path) -> dict:
    up = running(data)
    if up:
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/api/raise" % int(up["port"]), data=b"{}", method="POST",
                                         headers={"Authorization": "Bearer " + up["token"], "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2).close()
        except OSError:
            pass
        return {"ok": True, "already": True, "note": "LOKI Studio is already open; it was brought to the front."}
    if getattr(sys, "frozen", False):
        return {"ok": False, "error": "This packaged LOKI has no Studio inside. " + how_to_start()}
    script = REPO / "studio" / "studio_app.py"
    if not script.is_file():
        return {"ok": False, "error": "studio/studio_app.py is missing in %s" % REPO}
    env = dict(os.environ, LOKI_DATA=str(data))
    for name in ("LOKI_SUPERVISED", "LOKI_PORT", "LOKI_JOB_ID"):
        env.pop(name, None)
    kwargs: dict = {"cwd": str(REPO), "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    python = sys.executable
    if sys.platform == "win32" and python.lower().endswith("python.exe"):
        quiet = python[:-10] + "pythonw.exe"   # no console window
        python = quiet if Path(quiet).is_file() else python
    try:
        subprocess.Popen([python, str(script)], **kwargs)  # noqa: S603 - our own program
    except OSError as exc:
        return {"ok": False, "error": "could not start LOKI Studio (%s). %s" % (exc, how_to_start())}
    return {"ok": True, "started": True, "note": "LOKI Studio is starting in its own window."}


def route(state: Any, method: str, path: str, data: dict | None = None) -> tuple:
    data_dir = _data(state)
    if (method, path) == ("GET", "/studio"):
        up = running(data_dir)
        return 200, {"ok": True, "running": bool(up), "port": up.get("port"), "how": how_to_start()}
    if (method, path) == ("POST", "/studio/embed"):
        out = embed(data_dir)
        return (200 if out.get("ok") else 500), out
    if (method, path) == ("POST", "/studio/open"):
        out = open_studio(data_dir)
        return (200 if out.get("ok") else 500), dict(out, how=how_to_start())
    if (method, path) == ("POST", "/engine/restart"):
        restart = getattr(state, "restart_engine", None)
        if restart is None:
            return 503, {"ok": False, "error": "this engine cannot restart itself"}
        threading.Timer(0.8, restart).start()   # answer first, then go
        return 200, {"ok": True, "note": "the engine restarts in a moment; the window reloads when it is back"}
    return 404, {"ok": False, "error": "Unknown endpoint."}
