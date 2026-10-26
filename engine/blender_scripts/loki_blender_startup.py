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
import sys
import time
import traceback
from pathlib import Path

import bpy

try:                                                       # proof the module was imported at all
    with open(Path(__file__).resolve().parent / "loki_blender.log", "a", encoding="utf-8") as _fh:
        _fh.write("%s imported\n" % time.strftime("%H:%M:%S"))
except OSError:
    pass

POLL_S = 1.5
_server = None
_HERE = Path(__file__).resolve().parent


def log(*parts):
    """A line in loki_blender.log beside this script and in the inbox folder: what ran, what broke (no console)."""
    line = "%s %s\n" % (time.strftime("%H:%M:%S"), " ".join(str(p) for p in parts))
    print("LOKI:", line.strip())
    for d in (_HERE, inbox_root()):
        try:
            d.mkdir(parents=True, exist_ok=True)
            with open(d / "loki_blender.log", "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass


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
            if c.get("type") == "loki_reload":
                bpy.app.timers.register(reload_self, first_interval=0.5)
                res = {"status": "success", "result": {"reloading": True}}
            elif c.get("type") == "loki_python":           # plain Python, without the add-on (repair jobs)
                ns = {"bpy": bpy}
                exec(c.get("params", {}).get("code", ""), ns)  # noqa: S102 - the owner's own inbox folder only
                res = {"status": "success", "result": {"done": True}}
            else:
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
    try:
        return _poll()
    except Exception:  # noqa: BLE001 - a broken tick must not stop the inbox
        log("poll failed:", traceback.format_exc())
        return POLL_S


def _poll():
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
            log("job", job.name)
            answer = run_job(job)
            log("job", job.name, "ok" if answer.get("ok") else "FAILED")
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
    except Exception:  # noqa: BLE001
        log("heartbeat failed:", traceback.format_exc())
    return 10.0


def ensure_mcp():
    """Turn the add-on on and its MCP socket (9876) up. Runs from a timer, AFTER startup: inside a startup module's
    register() Blender restricts bpy (RestrictBlend) and addon_utils.enable failed there on the PC (2026-10-26,
    Blender 5.2.3: check() stayed (False, False), so the add-on's Scene properties never existed)."""
    errors = []
    try:
        import addon_utils  # pylint: disable=import-outside-toplevel
        if not addon_utils.check("blender_mcp")[1]:
            addon_utils.modules_refresh() if hasattr(addon_utils, "modules_refresh") else None
            addon_utils.enable("blender_mcp", default_set=True, persistent=True,
                               handle_error=lambda exc: errors.append(traceback.format_exc()))
        state = addon_utils.check("blender_mcp")
    except Exception:  # noqa: BLE001
        errors.append(traceback.format_exc())
        state = (False, False)
    log("addon_utils.enable blender_mcp ->", state, *(["errors:"] + errors if errors else []))
    if not state[1] or not hasattr(bpy.types.Scene, "blendermcp_port"):
        try:                                               # fallback: register the add-on module ourselves
            import blender_mcp  # pylint: disable=import-outside-toplevel
            if not hasattr(bpy.types.Scene, "blendermcp_port"):
                blender_mcp.register()
            log("blender_mcp registered directly")
        except Exception:  # noqa: BLE001
            log("blender_mcp register failed:", traceback.format_exc())
            return None
    try:
        srv = getattr(bpy.types, "blendermcp_server", None)
        if srv is None or not getattr(srv, "running", False):
            import blender_mcp  # pylint: disable=import-outside-toplevel
            srv = srv or blender_mcp.BlenderMCPServer(port=9876)
            bpy.types.blendermcp_server = srv
            srv.start()
        log("MCP socket on 9876:", bool(getattr(srv, "running", False)))
    except Exception:  # noqa: BLE001
        log("MCP socket failed:", traceback.format_exc())
    return None


def reload_self():
    """Job {"type": "loki_reload"}: load this script again from disk (a fix reaches a running Blender, no restart)."""
    import importlib  # pylint: disable=import-outside-toplevel
    mod = sys.modules.get(__name__)
    unregister()
    mod = importlib.reload(mod)
    mod.register()
    log("reloaded", __file__)
    return None


def register():
    log("register: Blender", bpy.app.version_string, "home", Path.home(), "inbox", inbox_root() / "inbox")
    bpy.app.timers.register(ensure_mcp, first_interval=1.0, persistent=True)
    if os.environ.get("LOKI_BLENDER_INBOX", "").lower() != "off":
        bpy.app.timers.register(poll, first_interval=3.0, persistent=True)
        bpy.app.timers.register(_heartbeat, first_interval=2.0, persistent=True)
    log("timers on")


def unregister():
    for fn in (poll, _heartbeat, ensure_mcp):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
