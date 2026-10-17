"""Subagents (roadmap E3): a short-lived helper with a narrow tool set and its own small context.

Ported from the design and policy of OpenHuman's sub-agent host (tinyhumansai/openhuman,
crates/openhuman-core/src/agent/subagent_host + agent/orchestration/tools/spawn_subagent.rs),
GPL-3.0 - see engine/licenses/OpenHuman-GPL-3.0.txt. Re-written in Python for LOKI's loop.

The rules kept from OpenHuman:

  * The parent hands off ONE focused task; the child runs its own tool loop on the parent's
    provider (same model routing) and its whole transcript collapses into ONE result that the
    parent receives as a normal tool result. The parent's context only grows by that result.
  * Tools are narrowed: the child gets the tools the caller names, intersected with what the
    parent itself may use right now (plan mode, disabled categories and add-ons still apply),
    minus a deny list. A child can NEVER spawn another sub-agent or delegate (no recursion
    tree nobody budgets), nor change LOKI itself, nor start teams.
  * A narrow system prompt (the task, the tools, "return one result") and an iteration cap
    (LOKI_SUBAGENT_TURNS, default 12); unattended background jobs may lift it (autonomous cap).
  * Several tasks can run side by side (`tasks`, at most MAX_PARALLEL) - research and file
    searches at the same time.

Everything outside (the model request, the tool call, the schemas) is injected, so
tests/test_core_upgrade.py runs it with a fake model.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Awaitable, Callable

import condenser
import stuck

DEFAULT_TOOLS = ("read_file", "search_files", "list_tree", "list_files", "read_web", "memory")
NEVER = frozenset({"run_subagent", "delegate", "improve_loki", "ship_loki", "start_team", "team_post",
                   "conductor_browse", "open_godot", "run_godot"})
MAX_TURNS = int(os.getenv("LOKI_SUBAGENT_TURNS", "12") or 12)
AUTONOMOUS_TURNS = int(os.getenv("LOKI_SUBAGENT_AUTONOMOUS_TURNS", "40") or 40)
MAX_PARALLEL = 4
RESULT_CHARS = 6000
TOOL_RESULT_CHARS = 6000
CONTEXT_CHARS = 60000

PROMPT = """You are a LOKI sub-agent: a short-lived helper with one focused task and a few tools.
Work only on the task below. Use your tools to find out what you need; do not guess.
You cannot ask questions, start other agents or change LOKI itself.
When you have the answer, reply with ONE final message (no tool call) that starts with
'RESULT:' and holds everything the caller needs - facts, file paths with line numbers, short
quotes - in at most 40 lines. If you cannot finish, reply 'RESULT: incomplete - <what you found
and what is missing>'.

Your tools: {tools}

Task:
{task}"""


def narrow(requested, available: list, never=NEVER) -> list:
    """The child's tool names: the requested ones (or the defaults) the parent may use, minus the deny list."""
    if isinstance(requested, str):
        requested = [t.strip() for t in requested.replace(";", ",").split(",") if t.strip()]
    wanted = list(requested or DEFAULT_TOOLS)
    allowed = set(available)
    return [t for t in dict.fromkeys(wanted) if t in allowed and t not in never]


def iter_cap(autonomous: bool = False, requested: int = 0) -> int:
    """Turns a child may take. An unattended run (a background job) lifts the cap (OpenHuman's
    autonomous lift); a request for more is honoured up to the ceiling."""
    ceiling = AUTONOMOUS_TURNS if autonomous else max(MAX_TURNS, 24)
    if requested and int(requested) > 0:
        return min(int(requested), ceiling)
    return AUTONOMOUS_TURNS if autonomous else MAX_TURNS


Request = Callable[[list, list], Awaitable[dict]]
CallTool = Callable[[str, dict], Awaitable[str]]


def _as_message(raw: Any) -> dict:
    """A provider message object or dict -> {"content", "tool_calls": [{id, function: {name, arguments}}]}."""
    if isinstance(raw, dict):
        msg = dict(raw)
    else:
        msg = {"content": getattr(raw, "content", "") or "", "tool_calls": []}
        for call in getattr(raw, "tool_calls", None) or []:
            fn = getattr(call, "function", None)
            msg["tool_calls"].append({"id": getattr(call, "id", ""), "type": "function",
                                      "function": {"name": getattr(fn, "name", ""),
                                                   "arguments": getattr(fn, "arguments", "{}")}})
    msg["role"] = "assistant"
    msg["content"] = str(msg.get("content") or "")
    msg["tool_calls"] = [c for c in (msg.get("tool_calls") or []) if isinstance(c, dict)]
    if not msg["tool_calls"]:
        msg.pop("tool_calls", None)
    return msg


async def run(task: str, tools: list, schemas: list, request: Request, call_tool: CallTool,
              max_turns: int = 0, progress: Callable[[str], None] | None = None) -> dict:
    """Run one sub-agent. Returns {"ok", "result", "turns", "tools_used", "stopped"}."""
    task = str(task or "").strip()
    if not task:
        return {"ok": False, "result": "error: give the sub-agent a task", "turns": 0, "tools_used": []}
    schemas = [s for s in schemas if s.get("function", {}).get("name") in set(tools)]
    cap = max_turns or MAX_TURNS
    messages: list = [{"role": "system", "content": PROMPT.format(tools=", ".join(tools) or "(none)", task=task)},
                      {"role": "user", "content": task}]
    used: list = []
    nudged = False
    for turn in range(1, cap + 1):
        if condenser.size(messages) > CONTEXT_CHARS:
            await condenser.condense(messages, None, 0, CONTEXT_CHARS, keep_first=1)
        try:
            msg = _as_message(await request(messages, schemas))
        except Exception as exc:  # noqa: BLE001 - one failed child must not fail the parent
            return {"ok": False, "result": "error: the sub-agent's model call failed: %s" % str(exc)[:300],
                    "turns": turn, "tools_used": used}
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            text = msg["content"].strip()
            if text.upper().startswith("RESULT:"):
                text = text[7:].strip()
            return {"ok": bool(text), "result": (text or "(the sub-agent gave no result)")[:RESULT_CHARS],
                    "turns": turn, "tools_used": used}
        for call in calls:
            fn = call.get("function") or {}
            name = str(fn.get("name", ""))
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = None
            if name not in tools:
                result = "error: %s is not one of your tools (%s)" % (name, ", ".join(tools))
            elif not isinstance(args, dict):
                result = "error: arguments must be a JSON object"
            else:
                used.append(name)
                if progress:
                    progress("%s(%s)" % (name, json.dumps(args)[:120]))
                try:
                    result = str(await call_tool(name, args))
                except Exception as exc:  # noqa: BLE001
                    result = "error: %s" % exc
            if len(result) > TOOL_RESULT_CHARS:
                result = result[:TOOL_RESULT_CHARS] + "\n...[cut; ask for a smaller range]"
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
        pattern = stuck.detect(messages)
        if pattern:
            if nudged:
                return {"ok": False, "result": "incomplete - the sub-agent got stuck (%s). Last notes: %s" % (
                    pattern, (msg.get("content") or "")[:400]), "turns": turn, "tools_used": used, "stopped": pattern}
            nudged = True
            messages.append({"role": "user", "content": stuck.advice(pattern)})
    # Out of turns: ask once for what it has, without tools.
    messages.append({"role": "user", "content": "You are out of turns. Reply now with 'RESULT:' and what you found."})
    try:
        msg = _as_message(await request(messages, []))
        text = msg["content"].strip()
    except Exception:  # noqa: BLE001
        text = ""
    if text.upper().startswith("RESULT:"):
        text = text[7:].strip()
    return {"ok": False, "result": ("incomplete (turn cap %d): " % cap) + (text or "no result")[:RESULT_CHARS],
            "turns": cap, "tools_used": used, "stopped": "turn_cap"}


async def run_many(tasks: list, tools: list, schemas: list, request: Request, call_tool: CallTool,
                   max_turns: int = 0) -> list:
    """Several sub-agents side by side (at most MAX_PARALLEL at once)."""
    gate = asyncio.Semaphore(MAX_PARALLEL)

    async def one(t: str) -> dict:
        async with gate:
            return await run(t, tools, schemas, request, call_tool, max_turns)
    return list(await asyncio.gather(*(one(t) for t in tasks)))


def format_results(tasks: list, results: list) -> str:
    if len(results) == 1:
        r = results[0]
        head = "Sub-agent result" if r.get("ok") else "Sub-agent (did not finish)"
        return "%s (%d turns, tools: %s):\n%s" % (head, r.get("turns", 0), ", ".join(dict.fromkeys(r.get("tools_used") or [])) or "none", r.get("result", ""))
    parts = []
    for i, (t, r) in enumerate(zip(tasks, results), 1):
        parts.append("## Sub-agent %d: %s\n%s(%d turns)\n%s" % (
            i, str(t)[:100], "" if r.get("ok") else "[did not finish] ", r.get("turns", 0), r.get("result", "")))
    return "\n\n".join(parts)
