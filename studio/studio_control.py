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
import re
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


# ------------------------------------------------------------------ LOKI's settings, from Studio (docs/STUDIO.md)
# Studio's "LOKI settings" panel: list + toggle + edit through LOKI's own bridge routes (the same ones LOKI's
# Settings use). Every change is the owner's click + confirm in Studio's window; secrets are never read or written.
SETTINGS_READS = {"providers": "/providers", "general": "/settings/general", "capabilities": "/capabilities/manifests",
                  "evolve": "/evolve"}
SETTINGS_WRITES = {"provider_enable": "/providers/enable", "provider_model": "/providers/model",
                   "provider_default": "/providers/default", "general": "/settings/general",
                   "capability": "/capabilities/enable", "evolve_idea": "/evolve/idea"}


def settings_overview(repo: Path | None = None, data: Path | None = None, a=None) -> dict:
    a = a or api(repo, data)
    out: dict = {"ok": True, "running": a.up()}
    for name, path in SETTINGS_READS.items():
        code, body = a.bridge("GET", path, timeout=8.0) if out["running"] else (0, {})
        out[name] = body if code == 200 else {"ok": False, "error": body.get("error") or ("HTTP %s" % code if code else
                                                                                            "LOKI is not running")}
    gen = out.get("general") or {}
    if isinstance(gen.get("settings"), dict):    # never a secret's value, even an empty one
        gen["settings"] = {k: v for k, v in gen["settings"].items() if v.get("kind") != "secret"}
        gen["values"] = {k: v for k, v in (gen.get("values") or {}).items() if k in gen["settings"]}
    if not out["running"]:   # the roadmap is a file: shown even when LOKI is down
        try:
            import evolve  # pylint: disable=import-outside-toplevel
            out["evolve"] = {"ok": True, "items": evolve.roadmap(Path(repo or studio_paths.repo())), "offline": True}
        except Exception as exc:  # noqa: BLE001
            out["evolve"] = {"ok": False, "error": str(exc)}
    return out


def settings_change(what: str, args: dict, repo: Path | None = None, data: Path | None = None, a=None) -> dict:
    """One change: provider on/off / model / default, a General value, a capability on/off, an evolve idea,
    or a roadmap line in docs/EVOLVE.md. Returns LOKI's answer."""
    what = str(what or "")
    args = dict(args or {})
    if what == "roadmap":
        return add_roadmap_line(str(args.get("text") or ""), Path(repo or studio_paths.repo()))
    path = SETTINGS_WRITES.get(what)
    if path is None:
        return {"ok": False, "error": "what is one of %s, roadmap" % ", ".join(SETTINGS_WRITES)}
    if what == "general":
        key = str(args.get("key") or "")
        if not key or re.search(r"(KEY|TOKEN|SECRET|PASSWORD)", key.upper()):
            return {"ok": False, "error": "secrets and keys are changed only in LOKI's Settings > Connections"}
        body = {"values": {key: str(args.get("value", ""))}}
    elif what == "capability":
        body = {"name": str(args.get("name") or ""), "enabled": bool(args.get("on"))}
    elif what == "evolve_idea":
        body = {"text": str(args.get("text") or "")}
    else:
        body = {"id": str(args.get("id") or ""), "on": bool(args.get("on")), "model": str(args.get("model") or "")}
    a = a or api(repo, data)
    if what == "general":   # refuse a secret even if LOKI's list says otherwise
        code, spec = a.bridge("GET", "/settings/general")
        if code == 200 and ((spec.get("settings") or {}).get(key) or {}).get("kind") == "secret":
            return {"ok": False, "error": "secrets are changed only in LOKI's Settings > Connections"}
    code, out = a.bridge("POST", path, body)
    if code == 0:
        return {"ok": False, "error": "LOKI is not running - start it from the LOKI card first"}
    return out if isinstance(out, dict) else {"ok": code == 200}


_ITEM = re.compile(r"^\s*-\s*\[[ xX]\]\s*E(\d+)\b")


def add_roadmap_line(text: str, repo: Path) -> dict:
    """`- [ ] E<n> <text>` at the top of docs/EVOLVE.md's Roadmap in the checkout: LOKI's evolve duty picks it up.
    It is an uncommitted edit in the LOKI folder until the next Ship it / ship.py from there."""
    text = " ".join(str(text or "").split())[:600]
    if len(text) < 8:
        return {"ok": False, "error": "say a little more about the task"}
    path = Path(repo) / "docs" / "EVOLVE.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return {"ok": False, "error": "no docs/EVOLVE.md: %s" % exc}
    n = max([int(m.group(1)) for m in (_ITEM.match(l) for l in lines) if m] + [0]) + 1
    line = "- [ ] E%d %s" % (n, text)
    at = next((i + 1 for i, l in enumerate(lines) if l.strip() == "## Roadmap"), None)
    if at is None:
        lines += ["", "## Roadmap", ""]
        at = len(lines)
    while at < len(lines) and not lines[at].strip():
        at += 1
    lines.insert(at, line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "id": "E%d" % n, "line": line,
            "note": "Added to docs/EVOLVE.md in %s (not shipped yet: it goes out with the next ship from there)." % repo}
