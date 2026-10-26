"""LOKI's Blender startup script (installed by engine/blender_link.py into Blender's user scripts/startup/ folder;
Blender runs every module there at launch and calls register()).

1. Turns on the MCP for Blender add-on (blender_mcp, MIT, contrib/blender_mcp) - its own auto-start then opens the
   MCP socket on 127.0.0.1:9876 for `uvx mcp-for-blender` (LOKI's "blender" MCP server).
2. A file inbox for the same commands, for agents that can only move files (owner 2026-10-26: "blender is on go
   on"): every job dropped in  <LOKI Projects>/Home/blender/inbox/<name>.json  -  {"type": "execute_code",
   "params": {"code": "..."}} or a list of such commands, or a plain <name>.py (run as execute_code)  -  is run in
   order through the add-on's own BlenderMCPServer.execute_command (exactly what the socket does), and the answer
   is written to  blender/outbox/<name>.json ; the job moves to blender/done/. Only that folder is read.
   LOKI_BLENDER_INBOX overrides the folder; LOKI_BLENDER_INBOX=off turns the inbox off.
"""
import json
import os
import time
import traceback
from pathlib import Path

import bpy

POLL_S = 1.5
_server = None


def inbox_root() -> Path:
    env = os.environ.get("LOKI_BLENDER_INBOX", "")
    if env:
        return Path(env)
    return Path.home() / "LOKI Projects" / "Home" / "blender"


def _mcp():
    """The add-on's server object: the running one (socket) or a private one just for the inbox."""
    global _server
    srv = getattr(bpy.types, "blendermcp_server", None)
    if srv is not None:
        return srv
    if _server is None:
        import blender_mcp  # pylint: disable=import-outside-toplevel
        _server = blender_mcp.BlenderMCPServer(port=0)
    return _server


def run_job(path: Path) -> dict:
    if path.suffix == ".py":
        commands = [{"type": "execute_code", "params": {"code": path.read_text(encoding="utf-8")}}]
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        commands = data if isinstance(data, list) else [data]
    results = []
    for c in commands:
        t0 = time.time()
        try:
            res = _mcp().execute_command(c)
        except Exception as exc:  # noqa: BLE001 - the answer says what broke
            res = {"status": "error", "message": "%s: %s" % (type(exc).__name__, exc), "traceback": traceback.format_exc()}
        res["seconds"] = round(time.time() - t0, 2)
        res["type"] = c.get("type")
        results.append(res)
        if res.get("status") != "success":
            break
    return {"job": path.name, "ok": all(r.get("status") == "success" for r in results), "results": results,
            "blender": bpy.app.version_string, "file": bpy.data.filepath, "at": time.time()}


def poll():
    root = inbox_root()
    inbox, outbox, done = root / "inbox", root / "outbox", root / "done"
    try:
        jobs = sorted(p for p in inbox.glob("*") if p.suffix in (".json", ".py") and p.is_file())
    except OSError:
        jobs = []
    for job in jobs[:1]:                                   # one per tick: Blender stays responsive
        try:
            age = time.time() - job.stat().st_mtime
            if age < 0.8:                                  # still being written
                break
            answer = run_job(job)
        except Exception as exc:  # noqa: BLE001
            answer = {"job": job.name, "ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        outbox.mkdir(parents=True, exist_ok=True)
        done.mkdir(parents=True, exist_ok=True)
        (outbox / (job.stem + ".json")).write_text(json.dumps(answer, indent=2, default=str), encoding="utf-8")
        try:
            os.replace(job, done / job.name)
        except OSError:
            job.unlink(missing_ok=True)
    return POLL_S


def _heartbeat():
    root = inbox_root()
    try:
        (root / "inbox").mkdir(parents=True, exist_ok=True)
        srv = getattr(bpy.types, "blendermcp_server", None)
        (root / "status.json").write_text(json.dumps({
            "blender": bpy.app.version_string, "pid": os.getpid(), "at": time.time(), "file": bpy.data.filepath,
            "mcp_socket": bool(srv is not None and getattr(srv, "running", False)), "port": 9876}), encoding="utf-8")
    except OSError:
        pass
    return 10.0


def register():
    try:
        import addon_utils  # pylint: disable=import-outside-toplevel
        if not addon_utils.check("blender_mcp")[1]:
            addon_utils.enable("blender_mcp", default_set=True, persistent=True)
    except Exception as exc:  # noqa: BLE001 - Blender must still start
        print("LOKI: could not turn on blender_mcp:", exc)
    if os.environ.get("LOKI_BLENDER_INBOX", "").lower() != "off":
        bpy.app.timers.register(poll, first_interval=3.0, persistent=True)
        bpy.app.timers.register(_heartbeat, first_interval=2.0, persistent=True)
    print("LOKI: Blender MCP add-on on, inbox", inbox_root() / "inbox")


def unregister():
    for fn in (poll, _heartbeat):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
