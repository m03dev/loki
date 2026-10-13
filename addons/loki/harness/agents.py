"""Your agents: named helpers you create once and hand tasks to.

An agent is a profile - a name, what it is good at (its instructions), which engine runs
it, which model it uses and whether it may run commands. Running one starts a background
job (workers.py). The built-in engine is Loki's own loop, so agents work offline with
nothing else installed; Claude Code, Codex and Hermes are used when installed.

Stored in harness_data/agents.json. Pure functions over a list plus a tiny store.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

ENGINES = ("loki", "claude-code", "codex", "hermes")
MAX_INSTRUCTIONS = 6000
STARTERS = [
    {"id": "researcher", "name": "Researcher", "engine": "loki", "allow_commands": False,
     "instructions": "You find things out. Use the conductor's research and read_web roles when they "
                     "are available, read the project's files, and write what you learned to "
                     "notes/research-<topic>.md with sources. Never change code."},
    {"id": "builder", "name": "Builder", "engine": "loki", "allow_commands": True,
     "instructions": "You implement the task in small steps: read the relevant files, make the "
                     "change, then run the project's tests or checks to prove it works. Keep the "
                     "change minimal and explain it in your final DONE line."},
    {"id": "reviewer", "name": "Reviewer", "engine": "loki", "allow_commands": False,
     "instructions": "You review code without changing it. Read the files involved and write a "
                     "short review to notes/review.md: real bugs first (with file and line), then "
                     "risks, then small improvements."},
    {"id": "tester", "name": "Tester", "engine": "loki", "allow_commands": True,
     "instructions": "You make sure things work. Find how the project is tested, run the tests, "
                     "and when something is missing add a focused test. Report what passed and "
                     "what failed."},
]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or uuid.uuid4().hex[:6]


def validate(spec: dict) -> dict:
    """A clean agent profile from user input; raises ValueError with a readable reason."""
    name = str(spec.get("name") or "").strip()
    if not name:
        raise ValueError("an agent needs a name")
    if len(name) > 40:
        raise ValueError("keep the name under 40 characters")
    engine = str(spec.get("engine") or "loki").strip().lower()
    if engine not in ENGINES:
        raise ValueError("engine must be one of " + ", ".join(ENGINES))
    instructions = str(spec.get("instructions") or "").strip()
    if len(instructions) > MAX_INSTRUCTIONS:
        raise ValueError("instructions are longer than %d characters" % MAX_INSTRUCTIONS)
    return {"id": str(spec.get("id") or _slug(name)), "name": name, "engine": engine,
            "instructions": instructions, "model": str(spec.get("model") or "").strip(),
            "allow_commands": bool(spec.get("allow_commands")),
            "isolate": bool(spec.get("isolate", True)), "updated": time.strftime("%Y-%m-%d %H:%M:%S")}


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()

    def all(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [a for a in data if isinstance(a, dict) and a.get("id")]
        except (OSError, ValueError):
            pass
        return [dict(a, starter=True) for a in STARTERS]

    def _save(self, agents: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(agents, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, agent_id: str) -> dict | None:
        return next((a for a in self.all() if a["id"] == agent_id), None)

    def save(self, spec: dict) -> dict:
        agent = validate(spec)
        with self.lock:
            agents = [a for a in self.all() if a["id"] != agent["id"]]
            agents.append(agent)
            self._save(agents)
        return agent

    def delete(self, agent_id: str) -> bool:
        with self.lock:
            agents = self.all()
            kept = [a for a in agents if a["id"] != agent_id]
            if len(kept) == len(agents):
                return False
            self._save(kept)
            return True


def job_spec(agent: dict, task: str, workspace: str, timeout_s: int = 3600) -> dict:
    """The background-job spec that runs `task` as this agent."""
    task = str(task or "").strip()
    if not task:
        raise ValueError("give the agent a task")
    spec = {"backend": "local", "agent": agent["engine"], "workspace": workspace,
            "isolate": agent.get("isolate", True), "timeout_s": timeout_s,
            "title": "%s: %s" % (agent["name"], task.splitlines()[0][:60]),
            "allow_commands": agent.get("allow_commands", False), "model": agent.get("model", "")}
    if agent["engine"] == "loki":
        spec["prompt"] = task
        spec["profile"] = {"name": agent["name"], "instructions": agent.get("instructions", "")}
    else:
        # External agents get the profile as part of their prompt.
        prefix = ("You are %s. %s\n\n" % (agent["name"], agent["instructions"])) if agent.get("instructions") else ""
        spec["prompt"] = prefix + task
    return spec
