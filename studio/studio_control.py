"""LOKI Studio's hands on the LOKI app itself - they work whether LOKI is up, down or half-updated.

  status()     running or not, its version, the update record (last good, on trial, skipped)
  logs(which)  engine / app / bridge / studio logs straight from disk
  start()      start the LOKI app (app/loki_app.py with LOKI's private Python), detached
  restart()    up: ask the engine to restart (POST /engine/restart); down: start it
  rollback()   go back to the last good version (engine/updater.py's rollback; when the running version
               is not a fresh update, the same move by hand: `git reset --keep <last good>`, which refuses
               to touch local edits, and the bad commit goes on the skip list so it is not taken again)

Start, restart and rollback are asked for by the owner in Studio's window (a click and a confirm);
the development agent cannot call them except restart_engine, which waits for the owner's Approve.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import studio_paths
import loki_mcp
import updater


def api(repo: Path | None = None, data: Path | None = None) -> loki_mcp.LokiAPI:
    r = Path(repo or studio_paths.repo())
    return loki_mcp.LokiAPI(worktree=r, repo=r, data=data or studio_paths.data())


def status(repo: Path | None = None, data: Path | None = None) -> dict:
    repo = Path(repo or studio_paths.repo())
    a = api(repo, data)
    code, health = a.bridge("GET", "/health", timeout=2.0)
    rec = updater.health(repo)
    ver = updater.version(repo)
    out = {"running": code == 200, "version": ver.get("label") or ver.get("commit", ""), "commit": ver.get("commit", ""),
           "last_good": rec.get("last_good", ""), "on_trial": bool(rec.get("pending")),
           "skipped": list(rec.get("skip") or [])[-5:], "history": list(rec.get("history") or [])[-6:]}
    if code == 200:
        out.update(provider=health.get("provider"), model=health.get("model"), mode=health.get("mode"),
                   update=health.get("update"))
    else:
        out["why"] = health.get("error", "")
    out["can_roll_back"] = bool(out["last_good"]) and not str(out["commit"]).startswith(str(out["last_good"])[:12]) \
        if out["commit"] and out["last_good"] else False
    return out


def logs(which: str = "engine", lines: int = 200, data: Path | None = None) -> str:
    return api(data=data).engine_logs(which, lines)


def _detach() -> dict:
    if sys.platform == "win32":
        return {"creationflags": 0x00000008 | 0x00000200}   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return {"start_new_session": True}


def start(repo: Path | None = None, data: Path | None = None, popen=subprocess.Popen) -> dict:
    """Start the LOKI app from the owner's checkout (not from Studio's pinned copy)."""
    repo = Path(repo or studio_paths.repo())
    data = Path(data or studio_paths.data())
    if api(repo, data).up():
        return {"ok": True, "note": "LOKI is already running."}
    script = repo / "app" / "loki_app.py"
    if not script.is_file():
        return {"ok": False, "error": "%s is missing - this is not a LOKI checkout" % script}
    python = studio_paths.engine_python(data)
    if sys.platform == "win32" and python.lower().endswith("python.exe"):
        quiet = python[:-10] + "pythonw.exe"
        python = quiet if Path(quiet).is_file() else python
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LOKI_STUDIO", "LOKI_MCP"))}
    env["LOKI_DATA"] = str(data)
    log = (data / "studio")
    log.mkdir(parents=True, exist_ok=True)
    try:
        with open(log / "loki_start.out", "a", encoding="utf-8") as out:
            popen([python, str(script)], cwd=str(repo), env=env, stdin=subprocess.DEVNULL, stdout=out,
                  stderr=subprocess.STDOUT, close_fds=True, **_detach())
    except OSError as exc:
        return {"ok": False, "error": "could not start LOKI: %s" % exc}
    return {"ok": True, "note": "LOKI is starting (its window opens when the engine is ready)."}


def wait_up(repo: Path | None = None, data: Path | None = None, timeout: float = 120.0) -> bool:
    end = time.time() + timeout
    a = api(repo, data)
    while time.time() < end:
        if a.up():
            return True
        time.sleep(1.0)
    return False


def restart(repo: Path | None = None, data: Path | None = None, popen=subprocess.Popen) -> dict:
    a = api(repo, data)
    if a.up():
        code, out = a.bridge("POST", "/engine/restart", {})
        if code == 200:
            return {"ok": True, "note": out.get("note", "restarting")}
        return {"ok": False, "error": out.get("error", "HTTP %s" % code)}
    return start(repo, data, popen=popen)


def rollback(repo: Path | None = None, why: str = "the owner rolled back from LOKI Studio") -> dict:
    """Back to the last good version on this machine. Nothing is pushed; local edits are kept."""
    repo = Path(repo or studio_paths.repo())
    first = updater.rollback(repo, why=why)
    if first.get("ok"):
        return dict(first, note="went back from %s to %s (the updater's rollback)" % (first["from"][:12], first["to"][:12]))
    rec = updater.health(repo)
    good = str(rec.get("last_good") or "")
    current = updater.version(repo).get("commit", "")
    if not good:
        return {"ok": False, "error": "no earlier good version is known on this machine yet (%s)" % first.get("error", "")}
    if current and good.startswith(current[:12]):
        return {"ok": False, "error": "LOKI already runs the last good version (%s)" % good[:12]}
    code, out = updater.git(repo, "rev-parse", "HEAD")
    bad = out.strip() if code == 0 else current
    code, out = updater.git(repo, "reset", "--keep", good)
    if code != 0:
        return {"ok": False, "error": "could not go back to %s: %s" % (good[:12], out[-240:])}
    skip = [c for c in rec.get("skip", []) if c][-20:]
    if bad and bad not in skip:
        skip.append(bad)
    reasons = dict(rec.get("skip_reasons", {}))
    reasons[bad[:12]] = why[:400]
    rec.update({"pending": "", "skip": skip, "skip_reasons": reasons, "rolled_back_at": time.time(), "rolled_back_from": bad})
    updater._save_health(rec, repo)   # pylint: disable=protected-access - the updater's own record
    updater.note_history("rolled back", repo, **{"from": bad, "to": good, "why": why})
    return {"ok": True, "from": bad, "to": good, "note": "went back from %s to %s; %s will not be taken again"
            % (bad[:12], good[:12], bad[:12])}
