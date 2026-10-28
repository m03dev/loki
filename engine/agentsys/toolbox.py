"""Toolbox: every tool LOKI has, with what it does to the world, and a search to hand a model the right few.

What this copies (docs/AGENT_SYSTEM.md "Toolbox"):
  - MCP tool annotations (spec 2025-06-18): readOnlyHint, destructiveHint, idempotentHint, openWorldHint. LOKI's
    loki-make server now sends them, and the guardrails read them (a destructive call asks first).
  - Anthropic's tool search / deferred tools and langgraph-bigtool: a small core set is always loaded, the rest is
    found on demand (engine/tool_select.py ranks with BM25 - kept, this module is its catalog).
  - Anthropic "Writing effective tools for agents": namespaced, few, high-signal tools; errors that teach
    (engine/tool_teach.py already does that).
  - Manus: the list stays stable during a request (prompt cache) - `for_task` is computed once per request.

A tool's facts come from what LOKI already knows (loki.MODIFYING, DANGEROUS, NETWORK_WRITES, RUNS_PROJECT,
owner_review.GATED_TOOLS, the categories) plus the table below for the making tools; nothing is guessed from a name.
"""
from __future__ import annotations

from typing import Any

# The making tools (engine/make_mcp.py + loki's tools): which need the GPU / the PC, and which the owner signs off.
GPU = {"make_image", "make_3d", "make_video", "make_turnaround", "make_sprite", "upscale_image", "render_scene",
       "make_local_video", "make_music", "ai_render", "make_3d_tool", "region_edit"}
OPEN_WORLD = {"read_web", "web_search", "research_web", "browse_page", "map_site", "reach", "scrape", "conductor",
              "deep_research_tool", "email", "itch", "generate_media"}
READ_ONLY = {"list_files", "list_tree", "read_file", "folders", "search_files", "code_map", "search_docs",
             "view_image", "list_capabilities", "godot_api", "godot_search", "read_scene", "find_tools",
             "find_specialist", "list_ecc_agents", "list_ecc_skills", "load_ecc_agent", "load_ecc_skill",
             "team_read", "todo_list", "review_repository", "crm_find", "crm_pipeline", "read_document",
             "library", "playbook", "check_script", "web_search", "research_web", "read_web", "map_site"}
DESTRUCTIVE = {"delete_file", "move_file", "run_command", "bash", "ship_loki", "itch"}
CORE = ("read_file", "list_tree", "search_files", "edit_file", "write_file", "bash", "find_tools", "memory",
        "playbook", "orchestrate", "run_subagent", "web_search", "read_web", "make_image", "make_3d")


def facts(name: str, agent: Any = None) -> dict:
    """What one tool does to the world. `agent` = the loki module (optional; adds its own sets)."""
    g = lambda attr: set(getattr(agent, attr, ()) or ()) if agent is not None else set()  # noqa: E731
    try:
        import owner_review  # pylint: disable=import-outside-toplevel
        gated = set(owner_review.GATED_TOOLS)
    except Exception:  # noqa: BLE001
        gated = set()
    modifying = g("MODIFYING") | g("NETWORK_WRITES") | g("DELEGATING") | g("RUNS_PROJECT")
    dangerous = g("DANGEROUS")
    read_only = name in READ_ONLY and name not in modifying
    return {
        "name": name,
        "read_only": read_only,
        "destructive": name in DESTRUCTIVE or name in {"delete_file", "move_file"},
        "asks_itself": name in dangerous or name in gated,       # the tool already asks the owner (no double ask)
        "owner_gate": name in gated,
        "idempotent": read_only,
        "open_world": name in OPEN_WORLD,
        "gpu": name in GPU,
        "category": next((c for c, names in (getattr(agent, "TOOL_CATEGORIES", {}) or {}).items() if name in names),
                         "making" if name in GPU else ""),
    }


def annotations(name: str, agent: Any = None) -> dict:
    """The MCP spec's names for the same facts (sent with tools/list)."""
    f = facts(name, agent)
    return {"readOnlyHint": f["read_only"], "destructiveHint": f["destructive"], "idempotentHint": f["idempotent"],
            "openWorldHint": f["open_world"]}


def catalog(agent: Any) -> list:
    """Every tool the loki module offers: name, one line, facts. For the Toolbox view and the orchestrator."""
    out = []
    seen = set()
    for s in list(getattr(agent, "TOOL_SCHEMAS", []) or []) + list(getattr(agent, "_PORT_SCHEMAS", []) or []):
        fn = (s or {}).get("function") or {}
        n = fn.get("name")
        if not n or n in seen:
            continue
        seen.add(n)
        out.append({**facts(n, agent), "description": str(fn.get("description") or "").split("\n")[0][:200],
                    "params": sorted(((fn.get("parameters") or {}).get("properties") or {}).keys())[:12]})
    try:
        import make_mcp  # pylint: disable=import-outside-toplevel
        for t in make_mcp.TOOLS:
            n = t.get("name")
            if n and n not in seen:
                seen.add(n)
                out.append({**facts(n, agent), "description": str(t.get("description") or "").split("\n")[0][:200],
                            "params": sorted(((t.get("inputSchema") or {}).get("properties") or {}).keys())[:12],
                            "server": "loki-make"})
    except Exception:  # noqa: BLE001
        pass
    out.sort(key=lambda r: (r["category"] or "~", r["name"]))
    return out


def for_task(task: str, schemas: list, limit: int = 8, core: tuple = CORE) -> list:
    """Names to hand a model for this task: the core set it always has, plus the best `limit` matches."""
    have = {((s or {}).get("function") or {}).get("name") for s in schemas}
    names = [n for n in core if n in have]
    try:
        import tool_select  # pylint: disable=import-outside-toplevel
        for n in tool_select.rank(task, schemas, limit=limit, exclude=set(names)):
            n = n if isinstance(n, str) else (n.get("name") if isinstance(n, dict) else str(n))
            if n and n not in names:
                names.append(n)
    except Exception:  # noqa: BLE001 - the core set still works
        pass
    return names


def describe(names: list, agent: Any = None) -> str:
    """One line per tool for a delegation brief: what it is and what it does to the world."""
    lines = []
    for n in names:
        f = facts(n, agent)
        tags = [t for t, on in (("read-only", f["read_only"]), ("asks the owner", f["asks_itself"] or f["destructive"]),
                                ("GPU: runs on the PC", f["gpu"]), ("goes online", f["open_world"])) if on]
        lines.append("- %s%s" % (n, (" (" + ", ".join(tags) + ")") if tags else ""))
    return "\n".join(lines)
