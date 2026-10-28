"""Context: one assembler for what every harness is told before the request (the "preamble").

Before this, LOKI's memory pack, lessons and triage were only built in LOKI's own loop - OpenCode, DeepSeek Harness,
the CLI harnesses and the local agent (the default path) got none of it. Now every harness gets the same block.

Order and rules (docs/AGENT_SYSTEM.md "Context"):
  - Manus / Anthropic prompt caching: the stable parts first, the parts that change per request last, keys in a
    fixed order, no timestamps at the top - so a provider's prefix cache keeps hitting.
  - Manus recitation: the plan (task ledger) goes LAST, nearest the request, where attention is strongest.
  - Mem0 / Letta: memory comes as a small bounded pack (memory.pack, token-budgeted), never the whole store.
  - ACE: only the top playbook bullets for this task, with their ids so the run can cite what it used.
  - Budgets: LOKI_PREAMBLE_CHARS (6000 chars; 2500 for a model on this computer - a 9B model's 16k window).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import playbook, toolbox


def budget(local: bool = False) -> int:
    if local:
        return int(os.environ.get("LOKI_PREAMBLE_LOCAL_CHARS", "2500") or 2500)
    return int(os.environ.get("LOKI_PREAMBLE_CHARS", "6000") or 6000)


def _memory(task: str, agent: Any) -> tuple:
    if agent is None:
        return "", {}
    try:
        import memory  # pylint: disable=import-outside-toplevel
        mem = memory.pack(task, root=getattr(agent, "DATA_DIR", None), repo=getattr(agent, "REPO_ROOT", None),
                          workspace=getattr(agent, "WORKSPACE", None))
        return str(mem.get("text") or ""), mem
    except Exception:  # noqa: BLE001 - no memory is still a working request
        return "", {}


def build(task: str, agent: Any = None, local: bool = False, ledger_text: str = "", extra: str = "",
          bullets: list | None = None, with_tools: bool = False) -> dict:
    """{"text": the preamble, "bullets": playbook bullets used, "memory": memory ids used, "chars": n}."""
    limit = budget(local)
    bullets = playbook.select(task, k=4 if local else playbook.TOP_K) if bullets is None else bullets
    pb = playbook.render(bullets)
    mem_text, mem = _memory(task, agent)
    tools_text = ""
    if with_tools and agent is not None:
        names = toolbox.for_task(task, list(getattr(agent, "TOOL_SCHEMAS", []) or []), limit=6)
        tools_text = "Tools that fit this task:\n" + toolbox.describe(names, agent) if names else ""
    sections = [("extra", extra), ("memory", mem_text), ("playbook", pb), ("tools", tools_text), ("ledger", ledger_text)]
    # trim from the least important end until it fits: tools, then memory, then the playbook's tail
    order_to_cut = ["tools", "memory", "playbook", "extra"]
    parts = {k: (v or "").strip() for k, v in sections}

    def size() -> int:
        return sum(len(v) + 2 for v in parts.values() if v)
    for key in order_to_cut:
        if size() <= limit:
            break
        over = size() - limit
        if parts[key]:
            parts[key] = parts[key][:max(0, len(parts[key]) - over - 1)].rsplit("\n", 1)[0] if len(parts[key]) > over else ""
    text = "\n\n".join(parts[k] for k, _ in sections if parts[k])
    bullets = [b for b in bullets if "[%s]" % b["id"] in text]      # only what the harness really saw counts as used
    return {"text": text, "bullets": bullets, "memory": list(mem.get("used") or []) if isinstance(mem, dict) else [],
            "chars": len(text)}
