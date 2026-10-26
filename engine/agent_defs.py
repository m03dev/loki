"""Subagents defined as Markdown files - shinpr/sub-agents-skills (MIT, vendored in engine/vendor_subagents/).

An agent is a .md file: YAML-ish frontmatter (run-agent, model, effort, permission, tools) and a body with its
role, Task, Out of Scope and Done When. One definition, any backend:

    run-agent: loki          LOKI's own sub-agent loop (engine/subagent.py) on LOKI's models - the default
    run-agent: opencode | codex | claude | kimi | glm | grok | gemini | antigravity | cursor-agent | ...
                             that coding CLI, through the vendored runner, when it is installed here
    model:                   a LOKI model name for run-agent loki; the CLI's own model name otherwise
    permission: read-only | safe-edit | yolo   (default read-only for loki agents)
    tools:                   for run-agent loki: the exact tools (else they follow the permission)

Where definitions come from (the first one with a name wins): the project's .agents/ folder, $SUB_AGENTS_DIR,
then LOKI's built-in set in engine/subagents/ (researcher, code-reviewer, bug-investigator, file-finder, checker,
writer).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILTIN = HERE / "subagents"
VENDOR = HERE / "vendor_subagents"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

import _loader  # noqa: E402  (vendored)

READ_TOOLS = ("read_file", "search_files", "list_tree", "list_files", "read_web", "memory")
EDIT_TOOLS = READ_TOOLS + ("write_file", "edit_file", "append_file")
YOLO_TOOLS = EDIT_TOOLS + ("run_command",)
PERMISSION_TOOLS = {"read-only": READ_TOOLS, "safe-edit": EDIT_TOOLS, "yolo": YOLO_TOOLS}
CLI_EXE = {"glm": "claude", "kimi": "claude", "antigravity": "agy"}


def dirs(workspace=None) -> list:
    out = []
    if workspace:
        out.append(Path(workspace) / ".agents")
    if os.getenv("SUB_AGENTS_DIR"):
        out.append(Path(os.environ["SUB_AGENTS_DIR"]))
    out.append(BUILTIN)
    return [d for d in out if d.is_dir()]


def list_all(workspace=None) -> list:
    """[{name, description, run_agent, permission, where}] - project definitions shadow built-in ones."""
    seen, out = set(), []
    for d in dirs(workspace):
        for item in _loader.list_agents(str(d)):
            if item["name"] in seen:
                continue
            seen.add(item["name"])
            try:
                a = load(item["name"], workspace)
            except (FileNotFoundError, ValueError):
                continue
            out.append({"name": item["name"], "description": item["description"], "run_agent": a["run_agent"],
                        "permission": a["permission"], "where": "built-in" if d == BUILTIN else str(d)})
    return out


def load(name: str, workspace=None) -> dict:
    """The definition: {name, run_agent, permission, model, effort, tools, system, file}."""
    _loader.validate_agent_name(name)
    last = None
    for d in dirs(workspace):
        try:
            a = _loader.load_agent(str(d), name)
        except FileNotFoundError as exc:
            last = exc
            continue
        front, _ = _loader.parse_frontmatter(Path(a.file_path).read_text(encoding="utf-8"))
        run = (a.run_agent or "loki").strip().lower()
        perm = front.get("permission") and a.permission or ("read-only" if run == "loki" else a.permission)
        tools = [t.strip() for t in str(front.get("tools") or "").replace(";", ",").split(",") if t.strip()]
        return {"name": name, "run_agent": run, "permission": perm, "model": a.model, "effort": a.effort,
                "tools": tools or list(PERMISSION_TOOLS[perm]), "system": a.system_context, "file": a.file_path}
    raise FileNotFoundError("no subagent called %r (list: %s)" % (
        name, ", ".join(x["name"] for x in list_all(workspace)) or "none")) from last


def cli_ready(run_agent: str) -> bool:
    return bool(shutil.which(CLI_EXE.get(run_agent, run_agent)))


def run_external(defn: dict, task: str, workspace, timeout_s: int = 600) -> dict:
    """Run a definition on its coding CLI. {"ok", "result", "cli", "error"?}."""
    import _builder  # pylint: disable=import-outside-toplevel
    import _executor  # pylint: disable=import-outside-toplevel
    inv = _builder.AgentInvocation(cli=defn["run_agent"], prompt=task, cwd=str(Path(workspace).resolve()),
                                   system_context=defn["system"], agent_file=defn["file"],
                                   permission=defn["permission"], model=defn["model"], effort=defn["effort"])
    try:
        res = _executor.execute_agent(inv, timeout_ms=int(timeout_s) * 1000)
    except ValueError as exc:
        return {"ok": False, "cli": defn["run_agent"], "result": "", "error": str(exc)}
    text = res.get("result")
    text = text if isinstance(text, str) else str(text or "")
    return {"ok": res.get("status") == "success", "cli": defn["run_agent"], "result": text,
            "error": res.get("error", ""), "status": res.get("status")}


def describe(workspace=None) -> str:
    items = list_all(workspace)
    if not items:
        return "no subagents defined"
    return "\n".join("- %s (%s, %s): %s" % (i["name"], i["run_agent"], i["permission"], i["description"])
                     for i in items)
