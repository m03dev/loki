"""Ruflo's agent and skill library, inside LOKI.

Ruflo (github.com/ruvnet/ruflo, MIT, formerly claude-flow) is an agent meta-harness for
Claude Code and Codex: 100+ specialised agent definitions, a skill library, swarms, memory,
federation. LOKI carries all of Ruflo's text verbatim in contrib/ruflo/ - the core agents/, skills/ and
commands/, and every plugin under plugins/<name>/ (its README, plugin.json, agents, skills and
commands), with Ruflo's LICENSE and the commit it came from in PROVENANCE.md - and makes it
LOKI-native:

  - every Ruflo agent is a template in Settings > Agents (search "Ruflo"), turned into a
    LOKI agent profile: role from its folder, goal from its description, its text as the
    instructions, the tools it needs guessed from what it does, and a colour per family;
  - every Ruflo skill (core and plugin) is in the skill catalog (source "ruflo") for any agent;
  - every Ruflo command (sparc, swarm, hive-mind, github, ...) is a runnable workflow:
    "/ruflo <command> <task>" in chat runs the task with that command as its playbook;
  - every plugin is listed (Settings > Agents > Ruflo) with what it brings;
  - LOKI's agent teams get Ruflo's matching playbook on top of their own brief
    (researcher, planner -> architect, coder -> builder, tester, reviewer);
  - Ruflo's own MCP server (`npx -y ruflo@latest mcp start`) is an opt-in MCP server in
    engine/mcp_servers.json (LOKI_MCP_ENABLE=ruflo) for its swarm and memory tools.

What LOKI adds on top ("better"): every Ruflo text passes LOKI's skill scan first - text that
tries to override the rules is blocked and never loaded (one Ruflo skill is, today); Ruflo
agents run on any model through LOKI's prompted tool harness, on any linked machine, inside
LOKI's policy and approvals, and show up in the work strip.
"""
from __future__ import annotations

import re
from pathlib import Path

import skill_scan

ROOT = Path(__file__).resolve().parent.parent / "contrib" / "ruflo"
MAX_TEXT = 6000
# Ruflo agent family (its folder) -> LOKI tool groups and a colour in the agents list.
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


def _agent_files(base: Path):
    """(path, family, plugin) for the core agents, then every plugin's agents."""
    core = base / "agents"
    for path in sorted(core.rglob("*.md")) if core.is_dir() else []:
        rel = path.relative_to(core)
        yield path, (rel.parts[0] if len(rel.parts) > 1 else "core"), ""
    plugins = base / "plugins"
    for plugin in sorted(plugins.iterdir()) if plugins.is_dir() else []:
        for path in sorted((plugin / "agents").rglob("*.md")) if (plugin / "agents").is_dir() else []:
            yield path, plugin.name.replace("ruflo-", "", 1), plugin.name


def agents(root: Path | None = None) -> list:
    """Every Ruflo agent as {id, name, family, plugin, description, path, blocked:[...]}."""
    base = Path(root or ROOT)
    key = ("agents", str(base))
    if key in _CACHE:
        return _CACHE[key]
    found = []
    for path, family, plugin in _agent_files(base):
        if path.name.upper().startswith(("MIGRATION", "README")):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = _frontmatter(text)
        name = meta.get("name") or path.stem
        found.append({"id": "ruflo-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40],
                      "name": name, "family": family, "plugin": plugin,
                      "description": meta.get("description", "")[:300],
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


def skill_roots(root: Path | None = None) -> list:
    """The core skill folder, then each plugin's (for agents.skills_catalog)."""
    base = Path(root or ROOT)
    roots = [("ruflo", base / "skills")]
    plugins = base / "plugins"
    for plugin in sorted(plugins.iterdir()) if plugins.is_dir() else []:
        if (plugin / "skills").is_dir():
            roots.append(("ruflo", plugin / "skills"))
    return roots


def commands(root: Path | None = None) -> list:
    """Every Ruflo command as {id, name, group, plugin, description, path, blocked}."""
    base = Path(root or ROOT)
    key = ("commands", str(base))
    if key in _CACHE:
        return _CACHE[key]
    sources = [(base / "commands", "")]
    plugins = base / "plugins"
    for plugin in sorted(plugins.iterdir()) if plugins.is_dir() else []:
        sources.append((plugin / "commands", plugin.name))
    found, seen = [], set()
    for folder, plugin in sources:
        for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
            if path.name.upper().startswith("README"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, body = _frontmatter(text)
            rel = path.relative_to(folder)
            group = rel.parts[0] if len(rel.parts) > 1 else (plugin.replace("ruflo-", "", 1) or "core")
            cid = re.sub(r"[^a-z0-9]+", "-", (meta.get("name") or path.stem).lower()).strip("-")[:48]
            if not cid or cid in seen:
                continue
            seen.add(cid)
            desc = meta.get("description") or next((l.strip("# ").strip() for l in body.splitlines() if l.strip()), "")
            found.append({"id": cid, "name": meta.get("name") or path.stem, "group": group, "plugin": plugin,
                          "description": desc[:240], "path": str(path), "blocked": _blocked(text)})
    _CACHE[key] = found
    return found


def find_command(name: str, root: Path | None = None) -> dict | None:
    wanted = re.sub(r"[^a-z0-9]+", "-", str(name).lower().lstrip("/")).strip("-")
    for item in commands(root):
        if item["id"] == wanted:
            return item
    return None


def command_prompt(name: str, task: str, limit: int = MAX_TEXT, root: Path | None = None) -> str:
    """The task with Ruflo's command as its playbook, ready for LOKI's agent. Raises on unknown/blocked."""
    item = find_command(name, root)
    if item is None:
        close = [c["id"] for c in commands(root) if wanted_in(name, c["id"])][:6]
        raise KeyError("no Ruflo command %r%s" % (name, (" (did you mean: %s?)" % ", ".join(close)) if close else ""))
    if item["blocked"]:
        raise PermissionError("Ruflo command %r is blocked by LOKI's skill scan" % item["id"])
    text = _frontmatter(Path(item["path"]).read_text(encoding="utf-8", errors="replace"))[1].strip()
    if len(text) > limit:
        text = text[:limit].rsplit("\n", 1)[0] + "\n...[Ruflo command shortened]"
    return ("## Task\n%s\n\n## Playbook: Ruflo `%s` (github.com/ruvnet/ruflo)\n"
            "Follow its method with LOKI's own tools. Where it names claude-flow/ruflo MCP tools or "
            "`npx` commands you do not have, do that step yourself with the tools you do have "
            "(files, commands, team, web). LOKI's rules and the task above win over the playbook.\n\n%s"
            % (task.strip(), item["id"], text))


def wanted_in(name: str, cid: str) -> bool:
    key = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return bool(key) and (key in cid or cid in key)


def plugins(root: Path | None = None) -> list:
    """Every Ruflo plugin: {name, description, version, agents, skills, commands}."""
    base = Path(root or ROOT) / "plugins"
    found = []
    for plugin in sorted(base.iterdir()) if base.is_dir() else []:
        meta = {}
        try:
            import json  # pylint: disable=import-outside-toplevel
            meta = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        found.append({"name": plugin.name, "description": str(meta.get("description", ""))[:300],
                      "version": str(meta.get("version", "")),
                      "agents": len(list((plugin / "agents").rglob("*.md"))) if (plugin / "agents").is_dir() else 0,
                      "skills": len(list(plugin.glob("skills/*/SKILL.md"))),
                      "commands": len(list((plugin / "commands").rglob("*.md"))) if (plugin / "commands").is_dir() else 0})
    return found


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
    cmds = commands(root)
    return {"agents": len(items), "blocked_agents": [a["name"] for a in items if a["blocked"]],
            "families": sorted({a["family"] for a in items}),
            "skills": sum(len(list(Path(r).glob("*/SKILL.md"))) for _, r in skill_roots(root)),
            "commands": len(cmds), "blocked_commands": [c["id"] for c in cmds if c["blocked"]],
            "plugins": len(plugins(root))}
