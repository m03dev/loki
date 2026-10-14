"""Resumable project state - blueprint PART 2 / section 7.3.

Loki records what a project IS, where the work has got to, and what comes next, so a
later session (or a different model, or a human) can pick the work up without deriving
it again. The file is plain JSON under harness_data/ so it can be read and edited by
hand as well as by the agent.

Fields: objective (str), phase (str), completed, files_changed, tests, known_issues,
decisions, blockers, next_actions (lists).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

TEXT_FIELDS = ("objective", "phase")
LIST_FIELDS = ("completed", "files_changed", "tests", "known_issues", "decisions",
               "blockers", "next_actions")
FIELDS = TEXT_FIELDS + LIST_FIELDS


def empty() -> dict:
    data = {name: "" for name in TEXT_FIELDS}
    for name in LIST_FIELDS:
        data[name] = []
    data["updated"] = ""
    return data


def load(path) -> dict:
    path = Path(path)
    data = empty()
    if not path.is_file():
        return data
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return data
    if not isinstance(raw, dict):
        return data
    for name in TEXT_FIELDS:
        if isinstance(raw.get(name), str):
            data[name] = raw[name]
    for name in LIST_FIELDS:
        if isinstance(raw.get(name), list):
            data[name] = [str(x) for x in raw[name]]
    data["updated"] = str(raw.get("updated", ""))
    return data


def save(path, data: dict) -> None:
    data["updated"] = time.strftime("%Y-%m-%d %H:%M")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add(data: dict, field: str, item: str) -> str:
    if field not in LIST_FIELDS:
        return "unknown list field: %s (use one of %s)" % (field, ", ".join(LIST_FIELDS))
    item = str(item).strip()
    if not item:
        return "nothing to add"
    if item not in data[field]:
        data[field].append(item)
    return "added to %s" % field


def set_field(data: dict, field: str, value) -> str:
    if field in TEXT_FIELDS:
        data[field] = str(value)
        return "set %s" % field
    if field in LIST_FIELDS:
        if isinstance(value, list):
            data[field] = [str(x) for x in value]
        else:
            data[field] = [line.strip() for line in str(value).splitlines() if line.strip()]
        return "set %s" % field
    return "unknown field: %s (use one of %s)" % (field, ", ".join(FIELDS))


def render(data: dict) -> str:
    lines = ["Objective: " + (data.get("objective") or "(not set)"),
             "Phase:     " + (data.get("phase") or "(not set)"),
             "Updated:   " + (data.get("updated") or "(never)")]
    for name in LIST_FIELDS:
        items = data.get(name) or []
        if not items:
            continue
        lines.append("")
        lines.append(name.replace("_", " ").title() + ":")
        for item in items:
            lines.append("  - " + item)
    return "\n".join(lines)
