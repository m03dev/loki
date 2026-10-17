"""The engine's two small doors for LOKI Studio (studio/, docs/STUDIO.md):

  GET  /studio            is Studio running here, and how to start it by hand
  POST /studio/open       open LOKI Studio (its own app and window; or bring it to the front)
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
ROUTES = {("GET", "/studio"), ("POST", "/studio/open"), ("POST", "/engine/restart")}


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
