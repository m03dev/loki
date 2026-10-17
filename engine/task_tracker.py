"""Task tracker: a structured plan with ids and statuses that survives context condensing.

Ported from OpenHands' task_tracker tool (OpenHands/software-agent-sdk,
openhands-tools/openhands/tools/task_tracker/definition.py: commands `view` and `plan`, statuses
todo / in_progress / done, and the status aliases other agents' todo tools use), MIT - see
engine/licenses/OpenHands-MIT.txt.

`plan` replaces the whole list (the model sends every task, with its status); `view` shows it.
The list is kept in harness_data/task_tracker.json and mirrored into plan.md, so LOKI's older
todo_list tool and the window show the same plan. The condenser's summary keeps the task ids
(TASK_TRACKING), so a long job does not lose its place.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

STATUSES = ("todo", "in_progress", "done")
ALIASES = {"pending": "todo", "to_do": "todo", "open": "todo", "doing": "in_progress", "in progress": "in_progress",
           "started": "in_progress", "completed": "done", "complete": "done", "finished": "done"}
MAX_TASKS = 40
MARK = {"todo": "[ ]", "in_progress": "[~]", "done": "[x]"}


def _status(value) -> str:
    s = str(value or "todo").strip().lower().replace("-", "_")
    s = ALIASES.get(s, s)
    return s if s in STATUSES else "todo"


def _load(path: Path) -> list:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def render(tasks: list) -> str:
    if not tasks:
        return "No tasks yet. Use task_tracker command='plan' with task_list to make a plan."
    counts = {s: sum(1 for t in tasks if t["status"] == s) for s in STATUSES}
    lines = ["Plan: %d todo, %d in progress, %d done" % (counts["todo"], counts["in_progress"], counts["done"])]
    for i, t in enumerate(tasks, 1):
        lines.append("%d. %s %s%s" % (i, MARK[t["status"]], t["title"], (" - " + t["notes"]) if t.get("notes") else ""))
    return "\n".join(lines)


def run(command: str = "view", task_list=None, path: Path | None = None, plan_file: Path | None = None) -> str:
    path = Path(path) if path else Path(os.getenv("LOKI_DATA", "harness_data")) / "task_tracker.json"
    command = str(command or "view").strip().lower()
    if command == "view":
        return render(_load(path))
    if command != "plan":
        return "error: command is 'view' or 'plan'"
    if isinstance(task_list, str):
        try:
            task_list = json.loads(task_list)
        except ValueError:
            return "error: task_list must be a JSON list of {title, notes, status}"
    if not isinstance(task_list, list):
        return "error: plan needs task_list: the FULL list of tasks [{title, notes, status}]"
    tasks = []
    for item in task_list[:MAX_TASKS]:
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            continue
        tasks.append({"title": " ".join(str(item["title"]).split())[:200],
                      "notes": " ".join(str(item.get("notes", "") or "").split())[:300],
                      "status": _status(item.get("status"))})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tasks, indent=1), encoding="utf-8")
    if plan_file is not None:
        try:
            # plan.md's own format (todo_add / todo_done count "- [ ]" lines)
            Path(plan_file).write_text("\n".join("- %s %s%s" % (
                "[x]" if t["status"] == "done" else "[ ]", t["title"],
                " (in progress)" if t["status"] == "in_progress" else "") for t in tasks) + "\n", encoding="utf-8")
        except OSError:
            pass
    return "Plan updated.\n" + render(tasks)
