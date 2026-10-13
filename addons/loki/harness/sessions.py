"""Agent sessions - the Herdr idea, and the blueprint's multi-agent runtime (section 9)
and worker registry (section 7.1).

Herdr (herdr.dev) is a runtime that hosts many coding agents, each in its own terminal,
and marks each working / blocked / idle so you never go pane by pane hunting for the one
waiting on you. Loki does not host terminals, but it can keep the same BOOKKEEPING: a
registry of agent sessions, each with a workspace, the agent driving it and a status.

That registry is the shared state over which a multi-agent run - or a human - can see who
is doing what and who is stuck. Pure functions over a dict, so they are unit-testable; the
caller owns persistence.
"""
from __future__ import annotations

import time
import uuid

STATUSES = ("working", "blocked", "idle", "done")
ICONS = {"working": "*", "blocked": "!", "idle": "o", "done": "x"}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def empty() -> dict:
    return {"sessions": []}


def add(data: dict, name: str, workspace: str = "", agent: str = "loki",
        status: str = "working", task: str = "") -> dict:
    if status not in STATUSES:
        status = "working"
    session = {
        "id": uuid.uuid4().hex[:8],
        "name": str(name).strip() or "session",
        "workspace": str(workspace),
        "agent": str(agent) or "loki",
        "status": status,
        "task": str(task),
        "started": _now(),
        "updated": _now(),
    }
    data.setdefault("sessions", []).append(session)
    return session


def update(data: dict, session_id: str, status: str = "", task: str = "") -> bool:
    for session in data.get("sessions", []):
        if session.get("id") == session_id or session.get("name") == session_id:
            if status in STATUSES:
                session["status"] = status
            if task:
                session["task"] = task
            session["updated"] = _now()
            return True
    return False


def close(data: dict, session_id: str) -> bool:
    return update(data, session_id, status="done")


def summary(data: dict) -> dict:
    counts = {name: 0 for name in STATUSES}
    for session in data.get("sessions", []):
        if session.get("status") in counts:
            counts[session["status"]] += 1
    counts["total"] = len(data.get("sessions", []))
    counts["needs_attention"] = [s.get("name") for s in data.get("sessions", [])
                                 if s.get("status") == "blocked"]
    return counts


def render(data: dict) -> str:
    sessions = data.get("sessions", [])
    if not sessions:
        return "no agent sessions"
    lines = ["%-1s %-16s %-9s %-11s %s" % ("", "session", "status", "agent", "workspace / task")]
    for session in sessions:
        lines.append("%-1s %-16s %-9s %-11s %s%s" % (
            ICONS.get(session.get("status"), "?"),
            str(session.get("name", ""))[:16],
            str(session.get("status", ""))[:9],
            str(session.get("agent", ""))[:11],
            session.get("workspace", ""),
            ("  " + str(session.get("task", ""))) if session.get("task") else ""))
    counts = summary(data)
    lines.append("")
    lines.append("working %d   blocked %d   idle %d   done %d"
                 % (counts["working"], counts["blocked"], counts["idle"], counts["done"]))
    if counts["needs_attention"]:
        lines.append("needs attention: " + ", ".join(counts["needs_attention"]))
    return chr(10).join(lines)
