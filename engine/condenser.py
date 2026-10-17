"""Context condenser: summarize old turns so a long task never overflows the model's window.

Ported from OpenHands' LLMSummarizingCondenser (OpenHands/software-agent-sdk,
openhands/sdk/context/condenser/llm_summarizing_condenser.py and its prompts
summarizing_system.j2 / summarizing_events.j2), MIT - see engine/licenses/OpenHands-MIT.txt.
Re-written for LOKI's plain message list (OpenAI chat format) without pydantic or litellm.

How it works (the same rules as OpenHands):

  * Reasons to condense: the conversation has more than `max_messages` messages (soft), or more
    than `max_chars` characters (hard - the next request could fail), or the provider just said
    the context is too long (a request - hard).
  * Keep the head: the system prompt and the first `keep_first` messages after it (the goal)
    are never forgotten, so the request still opens with a system message and the goal.
  * Keep the tail: the most recent messages, about half of the limit. The cut respects atomic
    units - an assistant message with tool calls and the tool results that answer it stay
    together, so the tail never starts with an orphan `tool` message (providers reject that).
  * Everything in between (including an earlier summary) is summarized by the model into one
    state summary - USER_CONTEXT, TASK_TRACKING, COMPLETED, PENDING, CODE_STATE, TESTS, CHANGES,
    VERSION_CONTROL_STATUS - and that summary takes their place.
  * If the summary call fails, retry with every event cut 20% shorter (hard_context_reset);
    if it still fails, fall back to a summary built from the events themselves (tool calls,
    files, errors, last notes) - condensing must never be the reason a task stops.
"""
from __future__ import annotations

import json
import os
import re
from typing import Awaitable, Callable

SUMMARY_TAG = "[LOKI context summary]"

# OpenHands summarizing_system.j2 (MIT), unchanged in substance.
SUMMARY_SYSTEM = """You are maintaining a context-aware state summary for an interactive agent.
You will be given a list of events corresponding to actions taken by the agent, which will include previous summaries.
If the events being summarized contain ANY task-tracking, you MUST include a TASK_TRACKING section to maintain continuity.
When referencing tasks make sure to preserve exact task IDs and statuses.

Track:

USER_CONTEXT: (Preserve essential user requirements, goals, and clarifications in concise form)

TASK_TRACKING: {Active tasks, their IDs and statuses - PRESERVE TASK IDs}

COMPLETED: (Tasks completed so far, with brief results)
PENDING: (Tasks that still need to be done)
CURRENT_STATE: (Current variables, data structures, or relevant state)

For code-specific tasks, also include:
CODE_STATE: {File paths, function signatures, data structures}
TESTS: {Failing cases, error messages, outputs}
CHANGES: {Code edits, variable updates}
DEPS: {Dependencies, imports, external calls}
VERSION_CONTROL_STATUS: {Repository state, current branch, PR status, commit history}

PRIORITIZE:
1. Adapt tracking format to match the actual task type
2. Capture key user requirements and goals
3. Distinguish between completed and pending tasks
4. Keep all sections concise and relevant

SKIP: Tracking irrelevant details for the current task type

Example formats:

For code tasks:
USER_CONTEXT: Fix FITS card float representation issue
COMPLETED: Modified mod_float() in card.py, all tests passing
PENDING: Create PR, update documentation
CODE_STATE: mod_float() in card.py updated
TESTS: test_format() passed
CHANGES: str(val) replaces f"{val:.16G}"
DEPS: None modified
VERSION_CONTROL_STATUS: Branch: fix-float-precision, Latest commit: a1b2c3d

For other tasks:
USER_CONTEXT: Write 20 haikus based on coin flip results
COMPLETED: 15 haikus written for results [T,H,T,H,T,H,T,T,H,T,H,T,H,T,H]
PENDING: 5 more haikus needed
CURRENT_STATE: Last flip: Heads, Haiku count: 15/20"""

_CONTEXT_ERROR = re.compile(r"context(_length|[ _-]window)?[^\n]{0,40}(exceed|too long|maximum|limit)|"
                            r"maximum context|too many tokens|prompt is too long|reduce the length", re.I)


def is_context_error(text: str) -> bool:
    return bool(_CONTEXT_ERROR.search(str(text or "")))


def limits(local: bool = False, env: dict | None = None) -> tuple:
    """(max_messages, max_chars) - smaller for a local model with a small window."""
    env = env if env is not None else os.environ
    msgs = int(env.get("LOKI_CONDENSE_MESSAGES", "160") or 160)
    chars = int(env.get("LOKI_CONDENSE_CHARS", "") or (60000 if local else 280000))
    return msgs, chars


def enabled(env: dict | None = None) -> bool:
    return str((env if env is not None else os.environ).get("LOKI_CONDENSE", "on")).strip().lower() \
        not in ("0", "off", "false", "no")


def _content(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):   # multimodal parts
        return " ".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in c)
    return str(c or "")


def size(messages: list) -> int:
    total = 0
    for m in messages:
        if isinstance(m, dict):
            total += len(_content(m))
            for call in m.get("tool_calls") or []:
                if isinstance(call, dict):
                    total += len(json.dumps(call.get("function") or {}))
    return total


def reasons(messages: list, max_messages: int, max_chars: int, requested: bool = False) -> set:
    out = set()
    if requested:
        out.add("request")
    if max_chars > 0 and size(messages) > max_chars:
        out.add("tokens")
    if max_messages > 0 and len(messages) > max_messages:
        out.add("events")
    return out


def _safe_start(messages: list, index: int, floor: int) -> int:
    """Move a cut point back so it never lands inside an assistant-tool_calls + tool-results unit."""
    index = max(floor, min(index, len(messages)))
    while index > floor and index < len(messages) and messages[index].get("role") == "tool":
        index -= 1
    return index


def head_size(messages: list, keep_first: int = 1) -> int:
    """System prompt + the first `keep_first` messages after it (the goal)."""
    start = 1 if messages and messages[0].get("role") == "system" else 0
    return min(len(messages), start + max(0, keep_first))


def plan(messages: list, max_messages: int, max_chars: int, keep_first: int = 1,
         requested: bool = False) -> tuple | None:
    """(forget_start, forget_end) or None when there is nothing to condense."""
    why = reasons(messages, max_messages, max_chars, requested)
    if not why:
        return None
    start = head_size(messages, keep_first)
    tail_targets = []
    if "events" in why:
        tail_targets.append(max(2, max_messages // 2 - keep_first - 1))
    if "request" in why:
        tail_targets.append(max(2, (len(messages) - start) // 2))
    if "tokens" in why:
        # keep the newest messages that fit in half the char budget
        budget, keep = max_chars // 2, 0
        for m in reversed(messages[start:]):
            budget -= size([m])
            if budget < 0:
                break
            keep += 1
        tail_targets.append(max(2, keep))
    keep_tail = min(tail_targets)
    end = _safe_start(messages, len(messages) - keep_tail, start)
    if end - start < 2:
        return None      # condensing would not make real progress (OpenHands' minimum_progress)
    return start, end


def render_event(m: dict, limit: int = 1500) -> str:
    role = m.get("role", "?")
    parts = []
    text = _content(m).strip()
    if text:
        parts.append(text)
    for call in m.get("tool_calls") or []:
        if isinstance(call, dict):
            fn = call.get("function") or {}
            parts.append("CALL %s(%s)" % (fn.get("name", "?"), str(fn.get("arguments", ""))[:600]))
    body = "\n".join(parts)
    if len(body) > limit:
        body = body[:limit // 2] + "\n...[%d chars cut]...\n" % (len(body) - limit) + body[-limit // 2:]
    return "%s: %s" % (role.upper(), body)


def events_prompt(events: list) -> str:
    return "".join("\n<EVENT>\n%s\n</EVENT>\n" % e for e in events) + "\nNow summarize the events using the rules above."


def fallback_summary(forgotten: list) -> str:
    """A summary built from the events themselves, when the model cannot write one."""
    calls, errors, files, notes = [], [], [], []
    for m in forgotten:
        for call in m.get("tool_calls") or []:
            if isinstance(call, dict):
                fn = call.get("function") or {}
                name = fn.get("name", "?")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except (TypeError, ValueError):
                    args = {}
                key = ""
                if isinstance(args, dict):
                    for k in ("filename", "path", "pattern", "suite", "url", "query", "command"):
                        if args.get(k):
                            key = str(args[k])[:70]
                            break
                    if name in ("write_file", "edit_file", "append_file", "insert_lines") and args.get("filename"):
                        files.append(str(args["filename"]))
                calls.append(name + ("(" + key + ")" if key else ""))
        text = _content(m).strip()
        if m.get("role") == "tool" and text[:120].lower().startswith(("error", "some failed", "not shipped", "refused")):
            errors.append(text.splitlines()[0][:160])
        elif m.get("role") == "assistant" and text:
            notes.append(text.splitlines()[0][:200])
        elif m.get("role") == "user" and text.startswith(SUMMARY_TAG):
            notes.append(text[len(SUMMARY_TAG):].strip()[:1200])
    lines = ["COMPLETED: %d earlier steps (summarized without a model): %s" % (len(calls), ", ".join(calls[-40:]))]
    if files:
        lines.append("CHANGES: files written or edited: %s" % ", ".join(dict.fromkeys(files)))
    if errors:
        lines.append("TESTS/ERRORS seen: " + " | ".join(errors[-6:]))
    if notes:
        lines.append("NOTES: " + " | ".join(notes[-6:]))
    return "\n".join(lines)


Summarizer = Callable[[list], Awaitable[str]]


async def condense(messages: list, summarize: Summarizer | None, max_messages: int, max_chars: int,
                   keep_first: int = 1, requested: bool = False, retries: int = 3) -> dict:
    """Condense `messages` IN PLACE. Returns {"condensed": bool, "forgot": n, "summary": str, "how": ...}."""
    span = plan(messages, max_messages, max_chars, keep_first, requested)
    if span is None:
        return {"condensed": False, "forgot": 0}
    start, end = span
    forgotten = [m for m in messages[start:end] if isinstance(m, dict)]
    summary, how = "", "model"
    if summarize is not None:
        limit = 1500
        for _ in range(max(1, retries)):
            try:
                summary = str(await summarize([{"role": "system", "content": SUMMARY_SYSTEM},
                                               {"role": "user", "content": events_prompt(
                                                   [render_event(m, limit) for m in forgotten])}]) or "").strip()
            except Exception:  # noqa: BLE001 - shrink the events and try again (hard_context_reset)
                summary = ""
            if summary:
                break
            limit = max(200, int(limit * 0.8))
    if not summary:
        summary, how = fallback_summary(forgotten), "fallback"
    note = {"role": "user", "content": "%s Earlier work in this task was condensed to keep the context small:\n%s\n"
            "(Continue from here; re-read a file if you need its exact current text.)" % (SUMMARY_TAG, summary)}
    # The summary sits right after the goal; the next message after it must not be an orphan tool result.
    messages[start:end] = [note]
    return {"condensed": True, "forgot": len(forgotten), "summary": summary, "how": how,
            "start": start, "end": end, "note": note}


def condense_sync(messages: list, max_messages: int, max_chars: int, keep_first: int = 1,
                  requested: bool = False) -> dict:
    """The model-free condenser (fallback summary only) - for callers with no event loop."""
    import asyncio  # pylint: disable=import-outside-toplevel
    return asyncio.run(condense(messages, None, max_messages, max_chars, keep_first, requested))


def summary_present(messages: list) -> bool:
    return any(isinstance(m, dict) and m.get("role") == "user" and _content(m).startswith(SUMMARY_TAG)
               for m in messages)

