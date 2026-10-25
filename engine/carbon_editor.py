"""The Engine tab's second engine: the Carbon Editor (native/carbon_mmo, the owner's C++ engine on CCP's Carbon).

Owner 2026-10-25: "rename godot tab to engine, well add our carbon engine in there as an option". The Engine tab picks
Godot or Carbon; this module is Carbon's side - find the built editor, build it (native/carbon_mmo/tools/build.py, the
one-command build, in the background with a log), open it, and say what is going on. Same build dirs as build.py:
the Mac builds on the external drive Xero when it is mounted (/Volumes/Xero/carbon_mmo/build), else in the repo
(native/carbon_mmo/build); LOKI_CARBON_BUILD points somewhere else.

    GET  /carbon/status          {found, exe, build_dir, content, building, running, log_tail}
    POST /carbon/open  {}        start the editor (detached), with its content folder
    POST /carbon/build {open}    run tools/build.py --keep --no-tests in the background (open = --open when it is done)

Standard library only; `popen` is injectable for the tests.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parent.parent
CARBON = REPO / "native" / "carbon_mmo"
MAC = sys.platform == "darwin"
WIN = sys.platform.startswith("win")
EXE = "cmmo_editor.exe" if WIN else "cmmo_editor"
_STATE: dict = {"building": False, "started": 0.0, "proc": None, "editor": None, "last": ""}
_LOCK = threading.Lock()


def build_dirs(env: dict | None = None) -> list[Path]:
    """Where a build may be, the one build.py would use first."""
    env = os.environ if env is None else env
    out = []
    if env.get("LOKI_CARBON_BUILD"):
        out.append(Path(env["LOKI_CARBON_BUILD"]).expanduser())
    if MAC and Path("/Volumes/Xero").is_dir():
        out.append(Path("/Volumes/Xero/carbon_mmo/build"))
    out.append(CARBON / "build")
    return out


def find_exe(env: dict | None = None) -> Path | None:
    for d in build_dirs(env):
        exe = d / "bin" / EXE
        if exe.is_file():
            return exe
    return None


def _log_file(build: Path) -> Path:
    return build.parent / "loki_build.log"


def _tail(path: Path, n: int = 12) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def status(env: dict | None = None) -> dict:
    exe = find_exe(env)
    build = exe.parent.parent if exe else build_dirs(env)[0]
    ed = _STATE.get("editor")
    running = bool(ed and ed.poll() is None)
    b = _STATE.get("proc")
    building = bool(b and b.poll() is None)
    note = ("Building the Carbon Editor..." if building else
            "The Carbon Editor is open." if running else
            "Ready - open the Carbon Editor." if exe else
            "Not built on this computer yet - Build it once (a few minutes; needs CMake and a C++ compiler).")
    return {"ok": True, "found": bool(exe), "exe": str(exe) if exe else "", "build_dir": str(build),
            "content": str(build.parent / "content"), "building": building, "running": running,
            "source": CARBON.is_dir(), "note": note, "log_tail": _tail(_log_file(build)) if (building or not exe) else [],
            "last": _STATE.get("last", "")}


def _spawn_kw(cwd: Path, logf) -> dict:
    kw: dict[str, Any] = {"cwd": str(cwd), "stdout": logf, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if WIN:
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # detached, own group, no console window
    else:
        kw["start_new_session"] = True
    return kw


def open_editor(env: dict | None = None, popen: Callable = subprocess.Popen) -> dict:
    exe = find_exe(env)
    if not exe:
        return {"ok": False, "error": "The Carbon Editor is not built on this computer yet.", "how": "Press Build."}
    with _LOCK:
        ed = _STATE.get("editor")
        if ed and ed.poll() is None:
            return {"ok": True, "note": "The Carbon Editor is already open.", "already": True}
        build = exe.parent.parent
        content = build.parent / "content"
        content.mkdir(parents=True, exist_ok=True)
        logf = open(build.parent / "editor.log", "w", encoding="utf-8")   # noqa: SIM115 - the child owns it
        _STATE["editor"] = popen([str(exe), "--content", str(content)], **_spawn_kw(build.parent, logf))
        _STATE["last"] = "opened %s" % time.strftime("%H:%M")
    return {"ok": True, "note": "The Carbon Editor is opening (File > New Starter Zone, then Play: Alt+P)."}


def build(open_after: bool = False, env: dict | None = None, popen: Callable = subprocess.Popen) -> dict:
    script = CARBON / "tools" / "build.py"
    if not script.is_file():
        return {"ok": False, "error": "native/carbon_mmo is not in this copy of LOKI."}
    with _LOCK:
        b = _STATE.get("proc")
        if b and b.poll() is None:
            return {"ok": True, "note": "Already building.", "already": True}
        target = build_dirs(env)[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        logf = open(_log_file(target), "w", encoding="utf-8")   # noqa: SIM115 - the child owns it
        argv = [sys.executable, str(script), "--build-dir", str(target), "--keep", "--no-tests"] + (["--open"] if open_after else [])
        _STATE["proc"] = popen(argv, **_spawn_kw(CARBON, logf))
        _STATE["started"] = time.time()
        _STATE["last"] = "build started %s" % time.strftime("%H:%M")
    return {"ok": True, "note": "Building the Carbon Editor in %s - the log is below." % target}


def route(method: str, path: str, body: dict | None = None, env: dict | None = None, popen: Callable = subprocess.Popen) -> tuple:
    try:
        if method == "GET" and path == "/carbon/status":
            return 200, status(env)
        if method == "POST" and path == "/carbon/open":
            return 200, open_editor(env, popen)
        if method == "POST" and path == "/carbon/build":
            return 200, build(bool((body or {}).get("open")), env, popen)
    except OSError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}
