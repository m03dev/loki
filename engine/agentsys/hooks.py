"""Hooks: the chassis' plug points, so a new layer is added without touching the harnesses.

The hook names are the ones the big harnesses settled on (Claude Agent SDK hooks, Google ADK callbacks / plugins,
OpenAI guardrails): before_request (UserPromptSubmit / before_run), after_request (Stop / after_run), before_tool
(PreToolUse / before_tool_callback), after_tool (PostToolUse / after_tool_callback). Their rules, copied:
  - every hook for an event runs; the strictest decision wins (deny > ask > allow)
  - a hook that raises never breaks the request: it is recorded in the trace and skipped (fail open), EXCEPT on
    before_tool, where a crashed check blocks the call (fail closed - Claude Code's rule for PreToolUse)
  - hooks see a dict and return a dict of changes (or None)

    from agentsys import hooks
    hooks.on("before_request", lambda ctx: {"preamble_extra": "..."})
"""
from __future__ import annotations

from typing import Any, Callable

from . import trace

EVENTS = ("before_request", "after_request", "before_tool", "after_tool")
_HOOKS: dict = {e: [] for e in EVENTS}
_RANK = {"allow": 0, "ask": 1, "deny": 2}


def on(event: str, fn: Callable[[dict], Any], name: str = "") -> Callable:
    if event not in EVENTS:
        raise ValueError("unknown hook event %r (one of %s)" % (event, ", ".join(EVENTS)))
    fn._hook_name = name or getattr(fn, "__name__", "hook")   # noqa: SLF001
    _HOOKS[event].append(fn)
    return fn


def off(event: str, fn: Callable) -> None:
    if fn in _HOOKS.get(event, []):
        _HOOKS[event].remove(fn)


def clear() -> None:
    for e in EVENTS:
        _HOOKS[e].clear()


def run(event: str, ctx: dict) -> dict:
    """Run every hook for `event`. Returns the merged changes; "decision" is the strictest one any hook gave."""
    merged: dict = {}
    decision = "allow"
    for fn in list(_HOOKS.get(event, [])):
        try:
            out = fn(dict(ctx)) or {}
        except Exception as exc:  # noqa: BLE001
            trace.event("hook %s failed" % getattr(fn, "_hook_name", "hook"), "guardrail", status="note",
                        **{"loki.event": event, "error.message": str(exc)[:200]})
            if event == "before_tool":
                out = {"decision": "deny", "reason": "a safety check crashed: %s" % str(exc)[:120]}
            else:
                continue
        if not isinstance(out, dict):
            continue
        d = str(out.pop("decision", "allow") or "allow")
        if _RANK.get(d, 0) > _RANK.get(decision, 0):
            decision = d
            merged["reason"] = out.get("reason", merged.get("reason", ""))
        for k, v in out.items():
            if k == "preamble_extra" and merged.get(k):
                merged[k] = merged[k] + "\n\n" + str(v)
            else:
                merged[k] = v
    merged["decision"] = decision
    return merged
