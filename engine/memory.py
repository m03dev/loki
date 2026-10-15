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
    semantic    lasting facts and notes   memory.md facts + brain.py vault + knowledge.py
    procedural  how to do things          agents.skills_catalog (SKILL.md folders)

Read-only tiers (procedural) say so instead of pretending to write.
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
                 "module": "reasoning_bank.py + experience.py", "writes": True, "fields": ("goal",)},
    "semantic": {"owns": "lasting facts about the user and the project",
                 "module": "memory.md + brain.py + knowledge.py", "writes": True, "fields": ("fact",)},
    "procedural": {"owns": "how to do things (skills)", "module": "agents.skills_catalog",
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
        return {"ok": True, "tier": tier, "saved": body, "path": str(path)}
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
        elif tier == "semantic":
            path = facts_file(root)
            if path.is_file():
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    body = line.strip().lstrip("-").strip()
                    if body and (not needle or needle in body.lower()):
                        out.append({"tier": tier, "text": body, "source": str(path)})
                        if len(out) >= limit:
                            break
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
