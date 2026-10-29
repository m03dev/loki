"""LOKI's Blender loader - installed ONCE into Blender's scripts/startup/ (engine/blender_link.py setup, or a Script
Directory). It never needs to change: everything else lives in loki_blender_core.py (../loki/), which this loader
loads, and loads again whenever the file changes - so every later fix is a file write, never a restart
(owner 2026-10-26: "make it work i dont wanna be coming back to blender").

Rules it keeps whatever happens:
  - its timer never dies (every tick is wrapped; it always asks to run again);
  - a core that fails to load or start is logged and the running one is kept;
  - status.json says it is alive, which core runs and the last error, even when the core is broken.
"""
import importlib.util
import json
import os
import time
import traceback
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
CORE = Path(os.environ.get("LOKI_BLENDER_CORE") or (HERE.parent / "loki" / "loki_blender_core.py"))
ROOT = Path(os.environ.get("LOKI_BLENDER_INBOX") or (Path.home() / "LOKI Projects" / "Home" / "blender"))
TICK_S = 2.0
STATE = {"core": None, "mtime": 0.0, "error": "", "loaded_at": 0.0, "ticks": 0, "last_log": 0.0}


def log(*parts):
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(str(p) for p in parts))
    print("LOKI:", line.strip())
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        with open(ROOT / "loki_blender.log", "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def _load():
    try:
        mtime = CORE.stat().st_mtime
    except OSError:
        if STATE["error"] != "no core":
            STATE["error"] = "no core"
            log("no core at", CORE)
        return
    if mtime == STATE["mtime"]:
        return
    STATE["mtime"] = mtime          # a broken file is tried once; the next write changes the mtime again
    try:
        spec = importlib.util.spec_from_file_location("loki_blender_core_%d" % int(mtime * 1000), CORE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001
        STATE["error"] = traceback.format_exc()[-1500:]
        log("core did not load - keeping the running one:", STATE["error"])
        return
    old = STATE["core"]
    if old is not None:
        try:
            old.stop()
        except Exception:  # noqa: BLE001
            log("old core stop failed:", traceback.format_exc()[-600:])
    try:
        mod.start(log, ROOT)
    except Exception:  # noqa: BLE001
        STATE["error"] = traceback.format_exc()[-1500:]
        log("core did not start - keeping the old one:", STATE["error"])
        if old is not None:
            try:
                old.start(log, ROOT)
            except Exception:  # noqa: BLE001
                log("old core restart failed:", traceback.format_exc()[-600:])
        return
    STATE.update(core=mod, error="", loaded_at=time.time())
    log("core loaded:", getattr(mod, "VERSION", "?"), "from", CORE)


def _status():
    core = STATE["core"]
    extra = {}
    if core is not None:
        try:
            extra = core.status() or {}
        except Exception:  # noqa: BLE001
            extra = {"core_status_error": traceback.format_exc()[-300:]}
    data = {"alive": True, "blender": bpy.app.version_string, "pid": os.getpid(), "at": time.time(),
            "background": bool(bpy.app.background), "core": getattr(core, "VERSION", None), "core_file": str(CORE),
            "core_error": STATE["error"][-600:]}
    data.update(extra)
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "status.json").write_text(json.dumps(data, default=str), encoding="utf-8")


def _tick():
    STATE["ticks"] += 1
    try:
        _load()
        if STATE["core"] is not None:
            STATE["core"].tick()
    except Exception:  # noqa: BLE001 - never let the timer die
        if time.time() - STATE["last_log"] > 30:
            STATE["last_log"] = time.time()
            log("tick failed:", traceback.format_exc()[-1200:])
    if STATE["ticks"] % 3 == 1:
        try:
            _status()
        except Exception:  # noqa: BLE001
            pass
    return TICK_S


def register():
    log("loader on: Blender", bpy.app.version_string, "core", CORE, "inbox", ROOT / "inbox")
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=1.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    core = STATE["core"]
    if core is not None:
        try:
            core.stop()
        except Exception:  # noqa: BLE001
            pass
