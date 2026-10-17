"""Memory: ONE interface over the four tiers LOKI actually has.

LOKI grew five peer modules that all hold "memory": knowledge.py (a `viking://` store),
brain.py (the Obsidian-style vault graph), project_state.py (the task in hand),
reasoning_bank.py (what worked and failed on similar past tasks) and experience.py (the
outcome log). Nothing said which one owned what, so "memory" was not one system - it was the
pile of tabs the owner objects to.

This module names the tiers and gives each the same three verbs - **remember / recall / stats**
- by DELEGATING to the module that already owns the data. No storage moves and nothing is
rewritten; what changes is that a caller asks `memory` instead of guessing which module holds
what.

    working     the task in hand          project_state.py    (objective, files, decisions)
    episodic    what happened last time   reasoning_bank.py   (lessons) + experience.py (log)
                                          + memory_core.py episodic learnings
    semantic    lasting facts and notes   memory.md facts + brain.py vault + knowledge.py
                                          + memory_core.py learnings (the `memory` tool)
    procedural  how to do things          agents.skills_catalog (SKILL.md folders, including
                                          the skills LOKI learned itself: skill_learning.py)

memory_core.py (session 26, OpenHuman's design) adds learn / recall / forget with relevance
scoring and the bounded per-request memory pack; `learn`, `forget` and `pack` below are its
entry points, and recall/stats here include what it holds.

Read-only tiers (procedural) say so instead of pretending to write.

Session 28 (memory & knowledge) adds the ONE retrieval path every request uses - profile_block()
(always on, bounded), pack() (lessons + memories + project passages, token-budgeted), retrieve()
(the same search Settings > Memory shows) and after_request() (automatic, reviewable learning). The
memories themselves live in memory_core (kinds, supersede, sync: memory_store / memory_sync).
"""
from __future__ import annotations

import os
from pathlib import Path

TIERS = ("working", "episodic", "semantic", "procedural")

# What each tier is, and the module that really owns the bytes (for the UI and the docs).
MANIFEST: dict = {
    "working": {"owns": "the task in hand", "module": "project_state.py",
                "writes": True, "fields": ("objective", "phase", "completed", "files_changed",
                                           "tests", "known_issues", "decisions", "blockers",
                                           "next_actions")},
    "episodic": {"owns": "what worked and what failed on similar past tasks",
                 "module": "reasoning_bank.py + experience.py + memory_core.py", "writes": True, "fields": ("goal",)},
    "semantic": {"owns": "lasting facts about the user and the project",
                 "module": "memory.md + brain.py + knowledge.py + memory_core.py", "writes": True, "fields": ("fact",)},
    "procedural": {"owns": "how to do things (skills, including learned ones)",
                   "module": "agents.skills_catalog + skill_learning.py",
                   "writes": False, "fields": ()},
}

HERE = Path(__file__).resolve().parent


def data_dir(root: Path | None = None) -> Path:
    """Where LOKI keeps its own data (LOKI_DATA, else harness_data)."""
    if root is not None:
        return Path(root)
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else HERE.parent / "harness_data"


def facts_file(root: Path | None = None) -> Path:
    """The semantic tier's plain facts (one `- fact` line each)."""
    return data_dir(root) / "memory.md"


def state_file(root: Path | None = None) -> Path:
    """The working tier's task state."""
    return data_dir(root) / "project_state.json"


def tier_of(source: str) -> str:
    """Which tier a module name belongs to - so a caller can stop guessing."""
    name = str(source or "").lower()
    for tier, spec in MANIFEST.items():
        if name and name.split(".")[0] in spec["module"]:
            return tier
    if name in ("project_state", "state"):
        return "working"
    if name in ("reasoning_bank", "experience"):
        return "episodic"
    if name in ("knowledge", "brain", "memory"):
        return "semantic"
    if name in ("skills", "agents", "skills_catalog"):
        return "procedural"
    return ""


def remember(tier: str, text: str, root: Path | None = None, **meta) -> dict:
    """Write into a tier. The tier decides what the text means; unsupported writes say so."""
    tier = str(tier or "").lower()
    if tier == "semantic":
        body = str(text or "").strip()
        if not body:
            return {"ok": False, "tier": tier, "error": "nothing to remember"}
        path = facts_file(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("- %s\n" % body.replace("\n", " ").strip())
        out = {"ok": True, "tier": tier, "saved": body, "path": str(path)}
        try:   # and into the one memory model (kind, history, sync to the other machines)
            import memory_core  # pylint: disable=import-outside-toplevel
            core = memory_core.learn(body, tier="semantic", root=data_dir(root), source="save_memory")
            out["id"], out["kind"] = core.get("id"), core.get("kind")
        except Exception:  # noqa: BLE001
            pass
        return out
    if tier == "working":
        import project_state  # pylint: disable=import-outside-toplevel

        field = str(meta.get("field") or "completed")
        data = project_state.load(state_file(root))
        if field not in project_state.FIELDS:
            return {"ok": False, "tier": tier, "error": "unknown field %r (have %s)"
                    % (field, ", ".join(project_state.FIELDS))}
        if field in project_state.LIST_FIELDS:
            project_state.add(data, field, str(text))
        else:
            project_state.set_field(data, field, str(text))
        project_state.save(state_file(root), data)
        return {"ok": True, "tier": tier, "field": field, "saved": str(text)}
    if tier == "episodic":
        import reasoning_bank  # pylint: disable=import-outside-toplevel

        goal = str(meta.get("goal") or text or "")
        reasoning_bank.remember(goal, str(meta.get("status") or "done"),
                                str(meta.get("outcome") or ""), list(meta.get("messages") or []),
                                root=root)
        return {"ok": True, "tier": tier, "saved": goal}
    if tier == "procedural":
        return {"ok": False, "tier": tier,
                "error": "procedural memory is the skills folders; write a SKILL.md instead"}
    return {"ok": False, "tier": tier, "error": "unknown tier %r (have %s)" % (tier, ", ".join(TIERS))}


def _count_files(root: Path, suffix: str = ".md", limit: int = 500) -> int:
    """How many files of a kind live under a folder, without walking an unbounded tree."""
    if not root or not Path(root).is_dir():
        return 0
    total = 0
    for path in Path(root).rglob("*"):
        if path.is_file() and path.name.endswith(suffix):
            total += 1
            if total >= limit:
                break
    return total


def recall(tier: str, query: str = "", limit: int = 5, root: Path | None = None,
           repo: Path | None = None) -> list:
    """Read from a tier. Best-effort: a broken tier returns [] rather than raising."""
    tier = str(tier or "").lower()
    needle = str(query or "").strip().lower()
    out: list = []
    try:
        if tier == "working":
            import project_state  # pylint: disable=import-outside-toplevel

            data = project_state.load(state_file(root))
            text = project_state.render(data)
            if not needle or needle in text.lower():
                out.append({"tier": tier, "text": text})
        elif tier == "episodic":
            import reasoning_bank  # pylint: disable=import-outside-toplevel

            for item in reasoning_bank.recall(str(query or ""), k=limit, root=root):
                out.append({"tier": tier, "text": str(item.get("goal", "")),
                            "worked": bool(item.get("worked")),
                            "steps": item.get("steps", ""), "when": item.get("t")})
            out += _core(tier, needle, limit - len(out), root)
        elif tier == "semantic":
            path = facts_file(root)
            if path.is_file():
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    body = line.strip().lstrip("-").strip()
                    if body and (not needle or needle in body.lower()):
                        out.append({"tier": tier, "text": body, "source": str(path)})
                        if len(out) >= limit:
                            break
            if len(out) < limit:
                out += _core(tier, needle, limit - len(out), root)
        elif tier == "procedural":
            import agents  # pylint: disable=import-outside-toplevel

            base = Path(repo or HERE.parent)
            for skill in agents.skills_catalog(agents.skill_roots(base, data_dir(root))):
                text = "%s - %s" % (skill.get("name", ""), skill.get("description", ""))
                if not needle or needle in text.lower():
                    out.append({"tier": tier, "text": text, "id": skill.get("id"),
                                "source": skill.get("source")})
                    if len(out) >= limit:
                        break
    except Exception:  # noqa: BLE001 - memory is advice; it must never break a caller
        return out
    return out[:limit]


def _core(tier: str, needle: str, limit: int, root: Path | None) -> list:
    """memory_core.py items of a tier that contain `needle` (newest first)."""
    if limit <= 0:
        return []
    import memory_core  # pylint: disable=import-outside-toplevel

    found = []
    for item in reversed(memory_core.items(data_dir(root), tier)):
        if not needle or needle in item.get("text", "").lower():
            found.append({"tier": tier, "text": item["text"], "id": item["id"], "source": "memory_core",
                          "when": item.get("t")})
            if len(found) >= limit:
                break
    return found


def learn(text: str, tier: str = "semantic", root: Path | None = None, **meta) -> dict:
    """Store a learning in memory_core (secrets scrubbed; host facts stamped)."""
    import memory_core  # pylint: disable=import-outside-toplevel

    return memory_core.learn(text, tier=tier, root=data_dir(root), tags=meta.pop("tags", None), meta=meta)


def forget(item_id: str = "", query: str = "", root: Path | None = None, all_matches: bool = False) -> dict:
    import memory_core  # pylint: disable=import-outside-toplevel

    return memory_core.forget(item_id, query, root=data_dir(root), all_matches=all_matches)


# --------------------------------------------------------------------------- session 28: one path
# The ONE way chat, background jobs and teams get memory into a request (all three run through
# loki._triage -> pack below):
#
#   always on   profile_block()  the owner's notes (memory.md) + the most important profile and
#               preference memories, capped at PROFILE_TOKENS - who the owner is, in every prompt
#   per request pack()           lessons from similar past tasks (reasoning_bank) + the memories
#               that match this request (memory_core.retrieve: hybrid search, recency, importance,
#               dedupe, token budget) + passages of the project's own docs/code with path:line
#               citations (knowledge.ProjectIndex) - each part with its own token share
#   after       after_request()  the durable things the owner said, learned automatically
#               (memory_extract), shown for review in Settings > Memory

PROFILE_TOKENS = int(os.getenv("LOKI_MEMORY_PROFILE_TOKENS", "350") or 350)
PACK_TOKENS = int(os.getenv("LOKI_MEMORY_PACK_TOKENS", "1000") or 1000)
LESSON_TOKENS = 300
KNOWLEDGE_TOKENS = 250
PROFILE_KINDS = ("profile", "preference")


def _note_lines(text: str) -> list:
    return [ln.strip() for ln in str(text or "").splitlines() if ln.strip() and ln.strip("-*# \t")]


def profile_block(root: Path | None = None, notes_file: Path | None = None,
                  budget_tokens: int = PROFILE_TOKENS) -> dict:
    """{"text", "lines": [included note lines], "ids": [included memory ids], "tokens"} - bounded.

    The notes come first, line by line, while they fit; then the most important profile and
    preference memories that the notes do not already say. What does not fit is still found by
    pack() when a request is about it."""
    import memory_search  # pylint: disable=import-outside-toplevel

    notes = Path(notes_file) if notes_file else facts_file(root)
    try:
        lines = _note_lines(notes.read_text(encoding="utf-8")) if notes.is_file() else []
    except OSError:
        lines = []
    budget = max(40, int(budget_tokens)) * 4
    out, used, kept = [], 0, []
    for line in lines:
        if used + len(line) + 1 > budget:
            break
        out.append(line)
        kept.append(line)
        used += len(line) + 1
    ids, item_texts = [], []
    try:
        import memory_core  # pylint: disable=import-outside-toplevel
        said = {" ".join(ln.lstrip("-* ").lower().split()) for ln in lines}
        best = sorted((i for i in memory_core.items(data_dir(root)) if i.get("kind") in PROFILE_KINDS),
                      key=lambda i: (-float(i.get("importance", 0.5) or 0.5), -float(i.get("updated") or i.get("t") or 0)))
        for item in best:
            text = " ".join(str(item.get("text", "")).split())
            if text.lower() in said or any(memory_search.near_duplicate(text, ln.lstrip("-* "), 0.8) for ln in lines):
                continue
            line = "- " + text
            if used + len(line) + 1 > budget:
                break
            out.append(line)
            ids.append(item["id"])
            item_texts.append(text)
            used += len(line) + 1
    except Exception:  # noqa: BLE001 - the profile is advice; it must never break a prompt
        pass
    text = "\n".join(out)
    return {"text": text, "lines": kept, "ids": ids, "texts": item_texts, "tokens": memory_search.tokens_of(text),
            "left_out": len(lines) - len(kept)}


def _notes_beyond(root: Path | None, notes_file: Path | None, included: list) -> list:
    """memory.md lines that did not fit the profile block, as retrieval candidates."""
    import hashlib  # pylint: disable=import-outside-toplevel

    notes = Path(notes_file) if notes_file else facts_file(root)
    try:
        lines = _note_lines(notes.read_text(encoding="utf-8")) if notes.is_file() else []
    except OSError:
        return []
    inside = set(included)
    out = []
    for line in lines:
        if line in inside:
            continue
        body = line.lstrip("-* ").strip()
        out.append({"id": "note:" + hashlib.sha1(body.encode("utf-8")).hexdigest()[:8], "kind": "profile",
                    "tier": "semantic", "text": body, "t": 0, "importance": 0.7, "source": "notes"})
    return out


def knowledge_hits(query: str, workspace: Path | None, root: Path | None = None, top: int = 3,
                   wait: bool = False) -> list:
    """Passages of the workspace project's docs/code for a query (knowledge.ProjectIndex)."""
    if not workspace or os.getenv("LOKI_PROJECT_INDEX", "on").strip().lower() in ("0", "off", "false", "no"):
        return []
    try:
        import knowledge  # pylint: disable=import-outside-toplevel
        index = knowledge.project_index(Path(workspace), data_dir(root))
        index.ensure_fresh(background=not wait)
        return index.search(query, top=top)
    except Exception:  # noqa: BLE001
        return []


def retrieve(query: str, root: Path | None = None, repo: Path | None = None, workspace: Path | None = None,
             budget_tokens: int = 450, kinds=None, knowledge: bool = True, notes_file: Path | None = None,
             mark_used: bool = True) -> dict:
    """THE retrieval: memories (+ notes beyond the profile) and project passages for a query.
    {"items": [...], "knowledge": [...], "tokens", "mode"} - Settings > Memory's search uses it too."""
    import memory_core  # pylint: disable=import-outside-toplevel

    prof = profile_block(root, notes_file)
    found = memory_core.retrieve(query, root=data_dir(root), repo=repo, budget_tokens=budget_tokens, kinds=kinds,
                                 extra=_notes_beyond(root, notes_file, prof["lines"]), mark_used=mark_used)
    found["knowledge"] = knowledge_hits(query, workspace, root) if knowledge else []
    return found


def pack(query: str, root: Path | None = None, repo: Path | None = None, workspace: Path | None = None,
         lessons: bool = True, notes_file: Path | None = None, budget_tokens: int | None = None) -> dict:
    """The bounded memory pack for one request: {"text", "used", "skills", "lessons", "sources", "tokens"}.

    Lessons (<= LESSON_TOKENS), memories (memory_core.PACK_CHARS/4 tokens) and project passages
    (<= KNOWLEDGE_TOKENS), all inside budget_tokens (LOKI_MEMORY_PACK_TOKENS, default 1000).
    What the always-on profile already says is not repeated."""
    import memory_core  # pylint: disable=import-outside-toplevel
    import memory_search  # pylint: disable=import-outside-toplevel

    total = int(budget_tokens or PACK_TOKENS)
    parts, used, skills, sources = [], [], [], []
    lesson_count = 0
    left = total
    if lessons:
        try:
            import reasoning_bank  # pylint: disable=import-outside-toplevel
            note = reasoning_bank.prompt_for(query, limit=min(LESSON_TOKENS, left) * 4)
        except Exception:  # noqa: BLE001
            note = ""
        if note:
            parts.append(note)
            lesson_count = note.count("\n- ")
            left -= memory_search.tokens_of(note)
    if memory_core.enabled():
        prof = profile_block(root, notes_file)
        core = memory_core.pack(query, root=data_dir(root), repo=repo,
                                budget=min(memory_core.PACK_CHARS, max(0, left - 20) * 4),
                                extra=_notes_beyond(root, notes_file, prof["lines"]),
                                skip_texts=[ln.lstrip("-* ") for ln in prof["lines"]])
        if core.get("text"):
            parts.append(core["text"])
            used, skills = core["used"], core["skills"]
            left -= memory_search.tokens_of(core["text"])
        share = min(KNOWLEDGE_TOKENS, left)
        if share >= 60:
            hits = knowledge_hits(query, workspace, root)
            lines, cost = [], 0
            for hit in hits:
                snippet = " ".join(hit["text"].split())[:420]
                line = "[%s] %s" % (hit["cite"], snippet)
                if cost + memory_search.tokens_of(line) > share - 30:
                    break
                lines.append(line)
                sources.append(hit["cite"])
                cost += memory_search.tokens_of(line)
            if lines:
                parts.append("# From the project's own files (cite them as path:line when you use them)\n"
                             + "\n".join(lines))
    text = "\n\n".join(p for p in parts if p).strip()
    return {"text": text, "used": used, "skills": skills, "lessons": lesson_count, "sources": sources,
            "tokens": memory_search.tokens_of(text)}


def after_request(messages: list, status: str = "done", root: Path | None = None, ask=None) -> list:
    """Learn the durable things the owner said in one finished request (memory_extract). Marked for
    review. Returns [{id, text, kind}] of what was new. Never raises."""
    if status in ("error",):
        return []
    if os.getenv("LOKI_JOB_ID", "").strip() and os.getenv("LOKI_MEMORY_EXTRACT_JOBS", "") != "1":
        return []      # a background job's prompt is written by LOKI or a schedule, not said by the owner
    try:
        import memory_core  # pylint: disable=import-outside-toplevel
        import memory_extract  # pylint: disable=import-outside-toplevel

        out = []
        for text, kind in memory_extract.extract(messages, ask=ask):
            got = memory_core.learn(text, kind=kind, root=data_dir(root), source="auto", review=True)
            if got.get("ok") and not got.get("updated"):
                out.append({"id": got["id"], "text": text, "kind": got.get("kind", kind),
                            "superseded": got.get("superseded", [])})
        return out
    except Exception:  # noqa: BLE001 - learning must never break a request
        return []


def stats(root: Path | None = None, repo: Path | None = None) -> dict:
    """What each tier actually holds right now - the one place to see all of LOKI's memory."""
    data = data_dir(root)
    out: dict = {"data_dir": str(data), "tiers": {}}
    try:
        import project_state  # pylint: disable=import-outside-toplevel

        state = project_state.load(state_file(root))
        out["tiers"]["working"] = {"fields": sum(
            1 for name in project_state.FIELDS
            if (state.get(name) if isinstance(state.get(name), str) else list(state.get(name) or [])))}
    except Exception:  # noqa: BLE001
        out["tiers"]["working"] = {"fields": 0}
    try:
        import reasoning_bank  # pylint: disable=import-outside-toplevel

        bank = reasoning_bank.summary(root)
        out["tiers"]["episodic"] = {"lessons": bank.get("items", 0), "worked": bank.get("worked", 0),
                                    "failed": bank.get("failed", 0)}
    except Exception:  # noqa: BLE001
        out["tiers"]["episodic"] = {"lessons": 0, "worked": 0, "failed": 0}
    path = facts_file(root)
    facts = 0
    if path.is_file():
        facts = sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                    if line.strip().startswith("- "))
    out["tiers"]["semantic"] = {"facts": facts, "vault_notes": _count_files(_vault_dir(data))}
    try:
        import memory_core  # pylint: disable=import-outside-toplevel

        core = memory_core.stats(data)
        out["tiers"]["semantic"]["learned"] = core["by_tier"].get("semantic", 0)
        out["tiers"]["episodic"]["learned"] = core["by_tier"].get("episodic", 0)
        out["kinds"] = core.get("by_kind", {})
        out["search"] = core.get("search", {})
    except Exception:  # noqa: BLE001
        pass
    try:
        import agents  # pylint: disable=import-outside-toplevel

        base = Path(repo or HERE.parent)
        out["tiers"]["procedural"] = {"skills": len(agents.skills_catalog(agents.skill_roots(base, data)))}
    except Exception:  # noqa: BLE001
        out["tiers"]["procedural"] = {"skills": 0}
    return out


def _vault_dir(data: Path) -> Path:
    try:
        import brain  # pylint: disable=import-outside-toplevel

        return Path(brain.load_settings(data).get("vault") or "")
    except Exception:  # noqa: BLE001
        return Path("")


def describe() -> list:
    """The tier table, for the UI and the docs."""
    return [{"tier": tier, "owns": MANIFEST[tier]["owns"], "module": MANIFEST[tier]["module"],
             "writes": MANIFEST[tier]["writes"], "fields": list(MANIFEST[tier]["fields"])}
            for tier in TIERS]
