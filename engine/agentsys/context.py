"""Context: one assembler for what every harness is told before the request (the "preamble").

Before this, LOKI's memory pack, lessons and triage were only built in LOKI's own loop - OpenCode, DeepSeek Harness,
the CLI harnesses and the local agent (the default path) got none of it. Now every harness gets the same block.

Order and rules (docs/AGENT_SYSTEM.md "Context"):
  - Manus / Anthropic prompt caching: the stable parts first, the parts that change per request last, keys in a
    fixed order, no timestamps at the top - so a provider's prefix cache keeps hitting.
  - Manus recitation: the plan (task ledger) goes LAST, nearest the request, where attention is strongest.
  - Mem0 / Letta: memory comes as a small bounded pack (memory.pack, token-budgeted), never the whole store.
  - ACE: only the top playbook bullets for this task, with their ids so the run can cite what it used.
  - The owner's rules first (AGENTS.md, never cut), then the index of his playbooks and the matching one in full
    with its toolbox (agentsys/playbooks.py) - nothing LOKI made up.
  - Budgets: LOKI_PREAMBLE_CHARS (10000 chars; 4000 for a model on this computer).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import playbook, playbooks, toolbox


def owner_rules(repo: Path | None = None) -> list:
    """AGENTS.md's numbered rules, word for word - the only rules (no agent adds its own)."""
    import re  # pylint: disable=import-outside-toplevel
    try:
        text = ((repo or Path(__file__).resolve().parents[2]) / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        return []
    m = re.search(r"^## The rules\s*$(.*?)^## ", text, re.M | re.S)
    rules, cur = [], ""
    for line in (m.group(1) if m else "").splitlines():
        if re.match(r"^\d+\.\s", line):
            if cur:
                rules.append(cur.strip())
            cur = line
        elif cur and line.startswith("   "):
            cur += " " + line.strip()
    if cur:
        rules.append(cur.strip())
    return rules


def owner_rules_text() -> str:
    rules = owner_rules()
    return ("The owner's rules (his words - they win over everything else):\n" + "\n".join(rules)) if rules else ""


def budget(local: bool = False) -> int:
    if local:
        return int(os.environ.get("LOKI_PREAMBLE_LOCAL_CHARS", "4000") or 4000)
    return int(os.environ.get("LOKI_PREAMBLE_CHARS", "10000") or 10000)


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
    pb_text = playbook.render(bullets)
    mem_text, mem = _memory(task, agent)
    tools_text = ""
    if with_tools and agent is not None:
        names = toolbox.for_task(task, list(getattr(agent, "TOOL_SCHEMAS", []) or []), limit=6)
        tools_text = "Tools that fit this task:\n" + toolbox.describe(names, agent) if names else ""
    # the owner's rules (AGENTS.md, word for word), the index of his playbooks, and the one for this job in full
    # with its toolbox (Anthropic's Agent Skills: names first, the full playbook only when it fits)
    try:
        rules = owner_rules_text()
        index = playbooks.index_text(600 if local else 1200)
        pb = playbooks.match(task)
        known = {((x or {}).get("function") or {}).get("name") for x in getattr(agent, "TOOL_SCHEMAS", []) or []} or None
        domain = playbooks.brief(pb, known, getattr(agent, "WORKSPACE", None), 1800 if local else 4000) if pb else ""
    except Exception:  # noqa: BLE001
        rules = index = domain = ""
    sections = [("rules", rules), ("extra", extra), ("domain", domain), ("index", index), ("memory", mem_text),
                ("playbook", pb_text), ("tools", tools_text), ("ledger", ledger_text)]
    # trim from the least important end until it fits: tools, memory, the learned notes, the playbook index, the
    # playbook's tail - the owner's rules are never cut
    order_to_cut = ["tools", "memory", "playbook", "index", "domain", "extra"]
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
