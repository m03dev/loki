"""LOKI's event stream: one record of what really happened, for the world and every agent.

Everything that matters is an event with the same shape (docs/VISION.md section 9):

    {"seq": 1760421600123456789, "t": 1760421600.12, "type": "task.started",
     "sender": "Builder", "recipient": "all", "task": "a1b2c3d4", "team": "9f8e7d6c",
     "machine": "pc", "payload": {...}}

Types: agent.status, agent.message, task.created, task.assigned, task.started,
task.blocked, task.completed, task.failed, approval.required, artifact.created,
verification.completed, decision.made.

Events are appended to harness_data/events/events.jsonl by any LOKI process on this machine
(the engine and its background agents), so nothing depends on one process staying up. The
engine serves them on GET /events?after=<seq>&wait=<s> (a long poll), and GET /world turns
them, with the live jobs and teams, into the agents a visual client such as the Godot LOKI
World draws (docs/WORLD.md). A client never invents activity: every character action maps
to an event here.
"""
from __future__ import annotations

import json
import os
import platform
import threading
import time
from pathlib import Path

TYPES = ("agent.status", "agent.message", "task.created", "task.assigned", "task.started",
         "task.blocked", "task.completed", "task.failed", "approval.required",
         "artifact.created", "verification.completed", "decision.made")
MAX_BYTES = int(os.getenv("LOKI_EVENTS_MAX_BYTES", str(4 * 1024 * 1024)))
_lock = threading.Lock()
_cond = threading.Condition(_lock)
_last_seq = 0


def _data_dir() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def log_path() -> Path:
    path = _data_dir() / "events"
    path.mkdir(parents=True, exist_ok=True)
    return path / "events.jsonl"


def machine_name() -> str:
    return (os.getenv("LOKI_PEER_NAME", "") or platform.node() or "this-machine").strip()[:40]


def _next_seq() -> int:
    """Strictly increasing within this process; time-based so processes interleave sanely."""
    global _last_seq
    seq = time.time_ns()
    if seq <= _last_seq:
        seq = _last_seq + 1
    _last_seq = seq
    return seq


def emit(type_: str, sender: str, payload: dict | None = None, task: str = "", team: str = "",
         recipient: str = "all") -> dict:
    """Record one event. Never raises: the stream must never break the work it describes."""
    if type_ not in TYPES:
        raise ValueError("unknown event type %r" % type_)
    try:
        with _cond:
            event = {"seq": _next_seq(), "t": time.time(), "type": type_, "sender": str(sender or "LOKI")[:60],
                     "recipient": str(recipient or "all")[:60], "task": str(task or "")[:40],
                     "team": str(team or os.getenv("LOKI_TEAM_ID", "") or "")[:40],
                     "machine": machine_name(), "payload": _clean(payload or {})}
            path = log_path()
            try:
                if path.is_file() and path.stat().st_size > MAX_BYTES:
                    _rotate(path)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event) + "\n")
            except OSError:
                pass
            _cond.notify_all()
            return event
    except Exception:  # noqa: BLE001
        return {}


def _clean(payload: dict) -> dict:
    """Keep payloads small and free of secrets."""
    out = {}
    for key, value in list(payload.items())[:20]:
        if any(word in str(key).lower() for word in ("key", "secret", "token", "password")):
            continue
        if isinstance(value, str):
            value = value[:2000]
        out[str(key)[:40]] = value
    return out


def _rotate(path: Path) -> None:
    """Keep the newest half of the log."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    path.write_text("\n".join(lines[len(lines) // 2:]) + "\n", encoding="utf-8")


def read(after: int = 0, limit: int = 500, types: tuple | None = None) -> list:
    path = log_path()
    if not path.is_file():
        return []
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("seq", 0) > after and (not types or event.get("type") in types):
                out.append(event)
    out.sort(key=lambda e: e.get("seq", 0))
    return out[-limit:] if after == 0 else out[:limit]


def wait(after: int = 0, timeout: float = 20.0, limit: int = 500) -> list:
    """Long poll: return new events, waiting up to `timeout` seconds for the first one.
    Events from other processes (background agents) are seen by re-reading the file."""
    deadline = time.monotonic() + max(0.0, min(timeout, 60.0))
    while True:
        events = read(after, limit)
        if events or time.monotonic() >= deadline:
            return events
        with _cond:
            _cond.wait(timeout=min(1.0, max(0.05, deadline - time.monotonic())))


def latest_seq() -> int:
    events = read(0, limit=1)
    return events[-1]["seq"] if events else 0


# --- the world: who is there and what they are doing ---------------------------------

STATIONS = {
    "LOKI": "hall", "Researcher": "library", "Architect": "drafting table", "Builder": "workshop",
    "Tester": "test bench", "Reviewer": "review desk", "Browser tester": "terminal",
    "Loki agent": "workshop", "claude-code": "workshop", "codex": "workshop", "hermes": "library",
}
JOB_STATE = {"queued": "waiting", "starting": "working", "working": "working", "blocked": "blocked",
             "done": "done", "failed": "failed", "cancelled": "idle"}


def world(jobs: list, teams: list, chat_busy: bool, last_decision: dict | None = None,
          recent_seconds: float = 3600.0) -> dict:
    """The agents a visual client should draw right now, from real state only."""
    now = time.time()
    msgs = {}
    for event in read(0, limit=400, types=("agent.message",)):
        msgs[event.get("sender", "")] = event
    agents = [{
        "id": "loki", "name": "LOKI", "role": "conductor", "state": "working" if chat_busy else "idle",
        "station": STATIONS["LOKI"], "task": (last_decision or {}).get("kind", "") if chat_busy else "",
        "team": "", "machine": machine_name(),
        "last_message": (msgs.get("LOKI") or {}).get("payload", {}).get("text", ""),
    }]
    for job in jobs:
        finished = float(job.get("finished") or 0)
        if job.get("status") in ("done", "failed", "cancelled") and finished and now - finished > recent_seconds:
            continue
        title = str(job.get("title") or "")
        role = _role_of(job)
        agents.append({
            "id": "job-" + str(job.get("id")), "name": role, "role": role.lower(),
            "state": JOB_STATE.get(job.get("status", ""), "idle"),
            "station": STATIONS.get(role, "workshop"), "task": title[:120], "team": job.get("team", ""),
            "machine": machine_name(),
            "last_message": (msgs.get(role) or {}).get("payload", {}).get("text", ""),
        })
    return {"ok": True, "machine": machine_name(), "time": now, "agents": agents,
            "teams": [{"id": t.get("id"), "goal": t.get("goal"), "status": t.get("status"),
                       "stage": t.get("stage")} for t in teams[:10]],
            "cursor": latest_seq()}


def _role_of(job: dict) -> str:
    title = str(job.get("title") or "")
    if title.startswith("Team ") and "·" in title:
        return title.split("·", 1)[1].split(":", 1)[0].strip()
    agent = str(job.get("agent") or "")
    return "Loki agent" if agent == "loki" else agent or "agent"
