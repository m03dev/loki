"""What the model is SENT each turn - the cheap half of LOKI's context management (owner 2026-10-25: "sometimes I get
millions of tokens from a prompt ... improve the harness, i want it to be the best").

Why it was expensive: every model call re-sent the whole conversation, every old tool result in full, until it reached
~280,000 characters; a 40-step task near that size is millions of tokens. What the best harnesses do instead:

  * OBSERVATION MASKING - old tool results are replaced by a one-line stub; the call itself stays, so the model knows
    what it did and can call again. "The Complexity Trap" (Lindenbauer et al., NeurIPS 2025, arXiv 2508.21433): on
    SWE-bench Verified this matches LLM summarization's solve rate at about half the cost of the raw agent. Anthropic's
    context-editing ("clear_tool_uses": keep the last 3-4 tool results, clear in batches) is the same idea.
  * CLEAR IN BATCHES - the masked boundary only moves every `step` tool results, so the start of the prompt stays
    byte-identical for several turns and the provider's prefix cache keeps hitting (DeepSeek caches automatically and
    reports `prompt_cache_hit_tokens`; OpenAI-style APIs report `prompt_tokens_details.cached_tokens`). Clearing one
    result per turn would rewrite the prompt every turn and miss the cache every time.
  * Old, huge tool-call ARGUMENTS (a whole file passed to write_file) are cut the same way.
  * LLM summarization (engine/condenser.py) stays the second line, for the dialogue itself.

Pure functions on OpenAI-shaped message dicts; the conversation history is never changed, only the copy sent.
"""
from __future__ import annotations

import json
import os

KEEP = 4            # the newest tool results always go in full
STEP = 6            # the masked boundary moves in steps of this many tool results (cache-friendly)
MIN_CHARS = 600     # results shorter than this are not worth masking
ARG_CHARS = 1500    # an old tool call's arguments longer than this are cut
STUB = "[cleared to save context: %s - %d characters. Call the tool again if you need it.]"


def settings(env: dict | None = None) -> dict:
    env = os.environ if env is None else env

    def num(key: str, dflt: int) -> int:
        try:
            return max(0, int(env.get(key, "") or dflt))
        except ValueError:
            return dflt
    return {"on": str(env.get("LOKI_MASK", "on")).strip().lower() not in ("0", "off", "false", "no"),
            "keep": max(1, num("LOKI_MASK_KEEP", KEEP)), "step": max(1, num("LOKI_MASK_STEP", STEP)),
            "min_chars": num("LOKI_MASK_MIN", MIN_CHARS)}


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):     # content parts
        return "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return str(content or "")


def _gist(text: str, limit: int = 160) -> str:
    line = " ".join(text.strip().split())
    return (line[:limit] + "...") if len(line) > limit else line


def _tool_names(messages: list) -> dict:
    """tool_call_id -> tool name (from the assistant messages that made the calls)."""
    out = {}
    for m in messages:
        for c in (m.get("tool_calls") or []) if isinstance(m, dict) else []:
            fn = c.get("function") if isinstance(c, dict) else getattr(c, "function", None)
            cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
            name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
            if cid:
                out[cid] = name or "tool"
    return out


def mask(messages: list, keep: int = KEEP, step: int = STEP, min_chars: int = MIN_CHARS) -> tuple[list, dict]:
    """(the view to send, stats). Tool results older than the newest `keep` are stubbed, in batches of `step`."""
    tool_idx = [i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") == "tool"]
    over = len(tool_idx) - keep
    n_mask = (over // step) * step if over > 0 else 0
    stats = {"tools": len(tool_idx), "masked": 0, "saved_chars": 0, "args_cut": 0}
    if n_mask <= 0:
        return messages, stats
    masked = set(tool_idx[:n_mask])
    boundary = tool_idx[n_mask - 1]           # everything up to here is "old"
    names = _tool_names(messages)
    view = []
    for i, m in enumerate(messages):
        if i in masked:
            text = _text(m.get("content"))
            if len(text) >= min_chars:
                name = names.get(m.get("tool_call_id"), m.get("name") or "tool")
                stub = STUB % ("%s said: %s" % (name, _gist(text)), len(text))
                stats["masked"] += 1
                stats["saved_chars"] += len(text) - len(stub)
                m = dict(m, content=stub)
        elif i < boundary and isinstance(m, dict) and m.get("role") == "assistant" and m.get("tool_calls"):
            calls, cut = [], False
            for c in m["tool_calls"]:
                fn = c.get("function") if isinstance(c, dict) else None
                args = fn.get("arguments") if isinstance(fn, dict) else None
                if isinstance(args, str) and len(args) > ARG_CHARS:
                    short = json.dumps({"_cleared": "arguments of an old call (%d characters) cut to save context" % len(args),
                                        "_start": args[:300]})
                    c = dict(c, function=dict(fn, arguments=short))
                    stats["saved_chars"] += len(args) - len(short)
                    stats["args_cut"] += 1
                    cut = True
                calls.append(c)
            if cut:
                m = dict(m, tool_calls=calls)
        view.append(m)
    return view, stats


RESULT_CHARS = 24000   # one tool result never brings more than this into the conversation


def cap_result(text, limit: int | None = None):
    """A tool result over `limit` keeps its start and end (where errors and summaries are) with a note in between -
    what Claude Code / SWE-agent do with long command output. Non-strings pass through."""
    if not isinstance(text, str):
        return text
    if limit is None:
        try:
            limit = int(os.environ.get("LOKI_TOOL_RESULT_CHARS", "") or RESULT_CHARS)
        except ValueError:
            limit = RESULT_CHARS
    if limit <= 0 or len(text) <= limit:
        return text
    head, tail = int(limit * 0.7), int(limit * 0.25)
    return (text[:head] + "\n\n[... %d characters cut from the middle to save context - read the part you need "
            "(read_file with start_line / end_line, or a narrower search) ...]\n\n" % (len(text) - head - tail) + text[-tail:])


def cached_tokens(usage) -> int | None:
    """Prompt tokens the provider served from its cache, whichever way it reports them (None = not reported)."""
    if usage is None:
        return None
    get = (lambda o, k: o.get(k) if isinstance(o, dict) else getattr(o, k, None))
    hit = get(usage, "prompt_cache_hit_tokens")            # DeepSeek
    if isinstance(hit, int):
        return hit
    det = get(usage, "prompt_tokens_details")              # OpenAI-compatible (NVIDIA NIM, OpenRouter, vLLM ...)
    if det is not None:
        c = get(det, "cached_tokens")
        if isinstance(c, int):
            return c
    c = get(usage, "cache_read_input_tokens")              # Anthropic-style
    return c if isinstance(c, int) else None
