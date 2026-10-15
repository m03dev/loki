"""Ruflo's agent and skill library, inside LOKI.

Ruflo (github.com/ruvnet/ruflo, MIT, formerly claude-flow) is an agent meta-harness for
Claude Code and Codex: 100+ specialised agent definitions, a skill library, swarms, memory,
federation. LOKI carries its library verbatim in contrib/ruflo/ (agents/ and skills/,
with Ruflo's LICENSE and the commit it came from in PROVENANCE.md) and makes it LOKI-native:

  - every Ruflo agent is a template in Settings > Agents (search "Ruflo"), turned into a
    LOKI agent profile: role from its folder, goal from its description, its text as the
    instructions, the tools it needs guessed from what it does, and a colour per family;
  - every Ruflo skill is in the skill catalog (source "ruflo") for any agent to load;
  - LOKI's agent teams get Ruflo's matching playbook on top of their own brief
    (researcher, planner -> architect, coder -> builder, tester, reviewer);
  - Ruflo's own MCP server (`npx -y ruflo@latest mcp start`) is an opt-in MCP server in
    engine/mcp_servers.json (LOKI_MCP_ENABLE=ruflo) for its swarm and memory tools.

What LOKI adds on top ("better"): every Ruflo text passes LOKI's skill scan first - text that
tries to override the rules is blocked and never loaded (one Ruflo skill is, today); Ruflo
agents run on any model through LOKI's prompted tool harness, on any linked machine, inside
LOKI's policy and approvals, and show up in LOKI World.
"""
from __future__ import annotations

import re
from pathlib import Path

import skill_scan

ROOT = Path(__file__).resolve().parent.parent / "contrib" / "ruflo"
MAX_TEXT = 6000
# Ruflo agent family (its folder) -> LOKI tool groups and a colour in LOKI World.
FAMILY = {
    "core": (["files", "commands"], "#a3be8c"), "development": (["files", "commands"], "#a3be8c"),
    "testing": (["files", "commands"], "#ebcb8b"), "analysis": (["files"], "#b48ead"),
    "architecture": (["files"], "#b48ead"), "documentation": (["files"], "#88c0d0"),
    "github": (["files", "commands", "web"], "#5e81ac"), "devops": (["files", "commands"], "#d08770"),
    "data": (["files", "commands"], "#88c0d0"), "security": (["files"], "#bf616a"),
    "goal": (["files", "team"], "#8fb3d9"), "sparc": (["files", "commands"], "#8fb3d9"),
    "swarm": (["files", "team"], "#8fb3d9"), "hive-mind": (["files", "team"], "#8fb3d9"),
    "consensus": (["files", "team"], "#5e81ac"), "optimization": (["files", "commands"], "#d08770"),
}
# LOKI team role -> the Ruflo agent whose playbook it gets.
TEAM_PLAYBOOKS = {"researcher": "researcher", "architect": "planner", "builder": "coder",
                  "tester": "tester", "reviewer": "reviewer"}
_CACHE: dict = {}


def _frontmatter(text: str) -> tuple:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta, text[end + 4:].lstrip("\n")


def _blocked(text: str) -> list:
    hits = []
    for pattern in skill_scan.BLOCK_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            hits.append(match.group(0)[:60])
    return hits


def agents(root: Path | None = None) -> list:
    """Every Ruflo agent as {id, name, family, description, path, blocked:[...]}."""
    root = Path(root or ROOT) / "agents"
    key = ("agents", str(root))
    if key in _CACHE:
        return _CACHE[key]
    found = []
    for path in sorted(root.rglob("*.md")):
        if path.name.upper().startswith(("MIGRATION", "README")):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = _frontmatter(text)
        name = meta.get("name") or path.stem
        rel = path.relative_to(root)
        family = rel.parts[0] if len(rel.parts) > 1 else "core"
        found.append({"id": "ruflo-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40],
                      "name": name, "family": family, "description": meta.get("description", "")[:300],
                      "path": str(path), "blocked": _blocked(text), "chars": len(body)})
    seen, unique = set(), []
    for item in found:                   # Ruflo has a few same-named agents in two folders
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)
    _CACHE[key] = unique
    return unique


def body(agent: dict) -> str:
    try:
        text = Path(agent["path"]).read_text(encoding="utf-8", errors="replace")
    except (OSError, KeyError):
        return ""
    return _frontmatter(text)[1].strip()


def template(agent: dict) -> dict:
    """A LOKI agent profile (agents.validate shape) made from one Ruflo agent."""
    tools, color = FAMILY.get(agent["family"], (["files"], "#8fb3d9"))
    text = body(agent)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT - 40].rsplit("\n", 1)[0] + "\n...[Ruflo playbook shortened]"
    title = re.sub(r"[-_]+", " ", agent["name"]).strip().title()[:40] or "Ruflo Agent"
    return {"id": agent["id"], "name": title, "engine": "loki", "role": agent["family"],
            "goal": agent["description"] or ("Ruflo %s agent" % agent["family"]),
            "instructions": text, "tools": list(tools), "allow_commands": "commands" in tools,
            "color": color, "source": "ruflo", "family": agent["family"]}


def templates(root: Path | None = None) -> list:
    """Every Ruflo agent that passes LOKI's scan, as a builder template."""
    return [template(a) for a in agents(root) if not a["blocked"]]


def skill_root(root: Path | None = None) -> tuple:
    return ("ruflo", Path(root or ROOT) / "skills")


def playbook(role: str, limit: int = 3000, root: Path | None = None) -> str:
    """Ruflo's playbook for a LOKI team role ("" when there is none or it is blocked)."""
    wanted = TEAM_PLAYBOOKS.get(role)
    if not wanted:
        return ""
    for agent in agents(root):
        if agent["name"] == wanted and agent["family"] == "core" and not agent["blocked"]:
            text = body(agent)
            return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n...[shortened]"
    return ""


def summary(root: Path | None = None) -> dict:
    items = agents(root)
    return {"agents": len(items), "blocked_agents": [a["name"] for a in items if a["blocked"]],
            "families": sorted({a["family"] for a in items}),
            "skills": len(list((Path(root or ROOT) / "skills").glob("*/SKILL.md")))}
