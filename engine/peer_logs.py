"""Every machine's logs on every machine (owner 2026-10-28: "since loki is linked to the other devices it should also
share logs between them that way you dont need to be on all devices").

Each LOKI answers GET /peer/logs (signed like every peer call, peers.py) with a redacted snapshot of itself: the last
lines of engine.out, loki_app.log and loki_bridge.log, the window's script errors, its recent runs from the agent
system's traces (engine/agentsys/trace.py), failed jobs with their reason, its version and its memory pressure.
Every LOKI_PEER_LOGS_S (300 s) each machine pulls the others' snapshot and keeps it - and its own - in

    <data>/machine_logs/<machine>/{engine.out.txt, app.log.txt, bridge.log.txt, window_errors.txt,
                                   runs.json, jobs_failed.json, summary.json}

so opening ONE machine's folder shows all of them (a helper on the Mac reads the PC's logs there, and the reverse).
GET /logs/machines (the window, Lab) pulls now and returns the summaries. Keys and tokens are masked before anything
leaves a machine; logs never travel anywhere but to the owner's own linked machines.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

LINES = int(os.environ.get("LOKI_PEER_LOG_LINES", "400") or 400)
EVERY_S = float(os.environ.get("LOKI_PEER_LOGS_S", "300") or 300)
_SECRET = re.compile(r"(sk|gsk|xai|pk|rk|nvapi|AIza|ghp|github_pat|hf)[-_A-Za-z0-9]{12,}|Bearer\s+[-._A-Za-z0-9]{12,}")
_ASSIGN = re.compile(r"(?i)\b(api[_-]?key|token|secret|password)(\s*[=:]\s*)[^\s\"',]{8,}")
STATUS: dict = {"last": 0.0, "machines": {}}


def _data_dir(agent: Any = None) -> Path:
    d = getattr(agent, "DATA_DIR", None) if agent is not None else None
    return Path(d) if d else Path(os.environ.get("LOKI_DATA") or Path(__file__).resolve().parent.parent / "harness_data")


def _redact(line: str) -> str:
    return _ASSIGN.sub(lambda m: m.group(1) + m.group(2) + "[key]", _SECRET.sub("[key]", line))


def tail(path: Path, lines: int = LINES) -> list:
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            fh.seek(max(0, size - 400 * lines))
            data = fh.read().decode("utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []
    return [_redact(x)[:500] for x in data]


def _state_dir(agent: Any = None) -> Path:
    try:
        import loki_bridge  # pylint: disable=import-outside-toplevel
        if loki_bridge.STATE_DIR is not None:
            return Path(loki_bridge.STATE_DIR)
    except Exception:  # noqa: BLE001
        pass
    return _data_dir(agent) / "app"


def snapshot(state: Any = None, agent: Any = None, lines: int = LINES) -> dict:
    """This machine, as another machine (or a helper) needs to see it. Read-only, redacted."""
    sd = _state_dir(agent)
    out: dict = {"time": time.time(), "logs": {}}
    try:
        import peers  # pylint: disable=import-outside-toplevel
        out["name"] = peers.my_name()
    except Exception:  # noqa: BLE001
        out["name"] = os.environ.get("LOKI_MACHINE_NAME", "") or "this"
    out["logs"]["engine.out"] = tail(sd / "engine.out", lines)
    out["logs"]["app.log"] = tail(sd / "loki_app.log", min(lines, 200))
    out["logs"]["bridge.log"] = tail(sd / "loki_bridge.log", lines)
    out["window_errors"] = [x for x in out["logs"]["engine.out"] if "window error" in x][-40:]
    try:
        import updater  # pylint: disable=import-outside-toplevel
        out["version"] = updater.version()
    except Exception:  # noqa: BLE001
        out["version"] = {}
    try:
        from agentsys import trace  # pylint: disable=import-outside-toplevel
        out["runs"] = trace.runs(2, limit=40)
        out["traces"] = trace.summary(1)
    except Exception:  # noqa: BLE001
        out["runs"], out["traces"] = [], {}
    failed = []
    jobs = getattr(state, "jobs", None) if state is not None else None
    try:
        for j in (jobs.store.all() if jobs is not None else [])[-200:]:
            if j.get("status") == "failed":
                failed.append({"id": j.get("id"), "title": str(j.get("title") or "")[:120], "error": _redact(str(j.get("error") or ""))[:400],
                               "tail": _redact(str(j.get("output") or ""))[-600:], "finished": j.get("finished")})
    except Exception:  # noqa: BLE001
        pass
    out["jobs_failed"] = failed[-30:]
    try:
        import peer_link  # pylint: disable=import-outside-toplevel
        out["memory"] = peer_link._memory_pressure()   # pylint: disable=protected-access
    except Exception:  # noqa: BLE001
        out["memory"] = {}
    return out


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(name or "machine"))[:40] or "machine"


def save(snap: dict, agent: Any = None, name: str = "") -> Path:
    """Write one machine's snapshot as plain files a person (or a helper) can open."""
    d = _data_dir(agent) / "machine_logs" / _safe_name(name or snap.get("name"))
    d.mkdir(parents=True, exist_ok=True)
    files = {"engine.out.txt": snap.get("logs", {}).get("engine.out") or [],
             "app.log.txt": snap.get("logs", {}).get("app.log") or [],
             "bridge.log.txt": snap.get("logs", {}).get("bridge.log") or [],
             "window_errors.txt": snap.get("window_errors") or []}
    for fname, lines in files.items():
        (d / fname).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (d / "runs.json").write_text(json.dumps(snap.get("runs") or [], indent=1), encoding="utf-8")
    (d / "jobs_failed.json").write_text(json.dumps(snap.get("jobs_failed") or [], indent=1), encoding="utf-8")
    summ = summary(snap)
    (d / "summary.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
    return d


def summary(snap: dict) -> dict:
    t = snap.get("traces") or {}
    return {"name": snap.get("name"), "pulled": time.time(), "time": snap.get("time"),
            "commit": (snap.get("version") or {}).get("commit", ""), "window_errors": len(snap.get("window_errors") or []),
            "last_window_error": (snap.get("window_errors") or [""])[-1][:300],
            "jobs_failed": len(snap.get("jobs_failed") or []), "runs_today": t.get("runs", 0),
            "tool_errors_today": t.get("tool_errors", 0), "memory": snap.get("memory") or {}}


def pull(state: Any = None, agent: Any = None) -> dict:
    """Pull every linked machine's snapshot (and save our own) now."""
    out = {}
    try:
        mine = snapshot(state, agent)
        save(mine, agent)
        out[mine.get("name") or "this"] = summary(mine)
    except Exception as exc:  # noqa: BLE001
        out["this"] = {"error": str(exc)[:200]}
    try:
        import peers  # pylint: disable=import-outside-toplevel
        linked = peers.peers()
    except Exception:  # noqa: BLE001
        linked = []
    for p in linked:
        name = p.get("name") or "peer"
        try:
            got = peers.call(p, "GET", "/peer/logs", timeout=20)
            if not got or not got.get("ok", True) or "logs" not in got:
                out[name] = {"error": str((got or {}).get("error") or "no logs (an older LOKI there?)")[:200]}
                continue
            save(got, agent, name)
            out[name] = summary(got)
        except Exception as exc:  # noqa: BLE001 - one machine away never stops the others
            out[name] = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
    STATUS.update(last=time.time(), machines=out)
    return out


def run_forever(state: Any = None, agent: Any = None) -> None:
    if str(os.environ.get("LOKI_PEER_LOGS", "on")).lower() in ("0", "off", "false", "no"):
        return
    time.sleep(30)                  # let the links come up first
    while True:
        try:
            pull(state, agent)
        except Exception as exc:  # noqa: BLE001
            print("[peer-logs] %s" % exc, flush=True)
        time.sleep(max(60.0, EVERY_S))


def start(state: Any = None, agent: Any = None) -> None:
    threading.Thread(target=run_forever, args=(state, agent), daemon=True, name="loki-peer-logs").start()


def ui_route(state: Any, agent: Any, method: str, route: str) -> tuple | None:
    if route != "/logs/machines":
        return None
    if method == "POST" or time.time() - STATUS["last"] > 60:
        pull(state, agent)
    return 200, {"ok": True, "last": STATUS["last"], "machines": STATUS["machines"],
                 "folder": str(_data_dir(agent) / "machine_logs")}
