"""Ziva works for the owner through LOKI (owner 2026-10-25: "i have ziva inside my loki godot live link i want that
agent to work for me").

Ziva is a closed agent inside the Godot editor (its own models: Ziva Baby, GPT-6 ...); it has no API to be driven from
outside - but it DOES load MCP servers, and a Godot project's `.mcp.json` is read by Ziva automatically
(ziva.sh/docs/mcp-servers). So LOKI puts its tools into every Godot project of the owner's that has Ziva:

  .mcp.json  {"mcpServers": {"loki": {"command": <LOKI's python>, "args": [<engine/make_mcp.py>, "--shell"]}}}

and Ziva, from its own chat panel, can then run commands (git repos, files, builds - in ~/LOKI Projects), make
pictures / 3D / video with LOKI's makers, and hand work to the other machine. Other servers already in the file are
kept. link(projects_dir) is called when the engine starts and from Settings > Agent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

NAME = "loki"


def entry() -> dict:
    return {"command": sys.executable, "args": [str(Path(__file__).resolve().parent / "make_mcp.py"), "--shell"]}


def ziva_projects(root: Path, depth: int = 3) -> list:
    """Godot projects (project.godot) at or under root, up to `depth` folders down, that have Ziva (addons/ziva_agent)."""
    root = Path(root)
    found = []
    for d in range(0, depth + 1):
        for p in root.glob("/".join(["*"] * d + ["project.godot"])):
            if (p.parent / "addons" / "ziva_agent").is_dir() and p.parent not in found:
                found.append(p.parent)
    return found


def link_project(project: Path) -> str:
    """Add (or refresh) LOKI in the project's .mcp.json; 'added', 'updated' or 'same'."""
    f = Path(project) / ".mcp.json"
    data = {}
    if f.is_file():
        try:
            data = json.loads(f.read_text(encoding="utf-8") or "{}")
        except ValueError:
            return "skipped: .mcp.json is not valid JSON"
    servers = data.setdefault("mcpServers", {})
    want = entry()
    if servers.get(NAME) == want:
        return "same"
    state = "updated" if NAME in servers else "added"
    servers[NAME] = want
    f.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return state


def link(root: Path | None = None) -> dict:
    if root is None:
        import agent_folders  # pylint: disable=import-outside-toplevel
        root = agent_folders.projects_dir()
    done = {}
    for p in ziva_projects(Path(root)):
        try:
            done[str(p)] = link_project(p)
        except OSError as exc:
            done[str(p)] = "failed: %s" % exc
    return {"ok": True, "projects": done}
