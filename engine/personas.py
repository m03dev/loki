"""Modes (personas): switchable packs that turn LOKI into a Tutor, a Writer, a Coder, ... (docs/APPS.md).

A mode = instructions + chosen tools + skills + starter prompts:

    {"id": "tutor", "name": "Tutor", "icon": "🎓", "description": "one line",
     "instructions": "how LOKI behaves in this mode (added to the system prompt)",
     "tools": ["read_web", ...],      # put first for small models; with "only_tools": true the ONLY ones offered
     "skills": ["doc-coauthoring"],   # skill packs LOKI loads with load_ecc_skill when they fit
     "starters": ["Quiz me on ...", ...]}   # the chips under "What should Loki work on?"

Built-in modes are below; the owner's own live in DATA_DIR/modes/<id>.json, the chosen one in
DATA_DIR/modes/active.json. A mode can be exported as a .lokimode file and imported elsewhere. An
imported mode is untrusted text: it is scanned like a downloaded skill (skill_scan.BLOCK_PATTERNS -
a mode that tries to switch off approvals is refused) and it can never grant anything: tools only
narrow or reorder what LOKI already offers; approvals and the policy engine are unchanged.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")
FORMAT = "loki-mode/1"
MAX_INSTRUCTIONS = 6000

BUILTIN: dict = {
    "tutor": {
        "name": "Tutor", "icon": "🎓", "description": "Teaches step by step, checks understanding, never just hands over answers.",
        "instructions": ("You are a patient tutor. Find out what the learner already knows, then teach one idea at a "
                         "time with a short example. Ask a quick question to check understanding before moving on. "
                         "For homework, guide with hints and questions instead of giving the final answer straight "
                         "away, unless the learner asks for it after trying. Use plain words; define any jargon. "
                         "Offer practice questions or flashcards (the Study cards app) when useful."),
        "tools": ["read_web", "web_search", "write_file", "make_app"], "skills": [],
        "starters": ["Teach me the basics of photosynthesis, one step at a time.",
                     "Quiz me on Spanish verbs - start easy.",
                     "Explain fractions to a 10-year-old with an example.",
                     "Make me flashcards for the French Revolution."]},
    "writer": {
        "name": "Writer", "icon": "✍️", "description": "Drafts, edits and tightens writing in your voice.",
        "instructions": ("You are a skilled writing partner. Ask who the reader is and what the piece must achieve if "
                         "that is unclear. Draft in clear, concrete sentences; prefer short words and active verbs. "
                         "When editing, keep the author's voice, explain the important changes briefly, and offer one "
                         "stronger alternative for weak lines. Save longer pieces as files in the workspace."),
        "tools": ["write_file", "read_file", "list_files"], "skills": ["doc-coauthoring", "copy-editing", "novel-writer"],
        "starters": ["Help me write a cover letter for a junior designer job.",
                     "Tighten this paragraph and tell me what you changed.",
                     "Outline a short story about a lighthouse keeper.",
                     "Write a friendly email asking my landlord to fix the heating."]},
    "coder": {
        "name": "Coder", "icon": "💻", "description": "Reads the project, writes small tested changes, explains them.",
        "instructions": ("You are a careful senior engineer. Read the relevant code before changing it, make the "
                         "smallest change that works, run the tests or a quick check, and say exactly what you "
                         "verified. Explain decisions briefly. Never invent APIs: look them up in the code first."),
        "tools": ["read_file", "write_file", "list_files", "search_files", "run_command", "repo_map", "apply_edits"],
        "skills": ["frontend-design", "webapp-testing"],
        "starters": ["Explain how this project is organised.",
                     "Find and fix the bug in the failing test.",
                     "Add a command-line flag --verbose and a test for it.",
                     "Review my last change for bugs."]},
    "researcher": {
        "name": "Researcher", "icon": "🔎", "description": "Finds sources, compares them and cites every claim.",
        "instructions": ("You are a rigorous researcher. Search before answering anything factual or recent, read the "
                         "sources, and cite each claim with its link. Separate what the sources say from your own "
                         "reasoning. Say plainly when sources disagree or when you could not verify something. End "
                         "with a short summary and the open questions."),
        "tools": ["web_search", "read_web", "research_web", "browse_page", "write_file"], "skills": [],
        "starters": ["Compare the three most popular note-taking apps, with sources.",
                     "What does the latest research say about sleep and memory?",
                     "Find five grants for small arts projects and list their deadlines.",
                     "Summarise this topic for a beginner, with links."]},
    "life_admin": {
        "name": "Life admin", "icon": "🗂️", "description": "Bills, forms, appointments, plans and lists - sorted.",
        "instructions": ("You help with everyday admin: budgets, bills, forms, letters, appointments, travel and "
                         "household plans. Turn vague worries into a short checklist with dates. Draft letters and "
                         "emails ready to send (but never send anything without asking). Suggest a LOKI app (Budget, "
                         "Meal planner, Habits) when it would keep the work going."),
        "tools": ["calendar", "email", "write_file", "make_app", "web_search"], "skills": [],
        "starters": ["Make me a monthly budget from my income and bills.",
                     "Help me plan meals and a shopping list for this week.",
                     "Draft a letter to cancel my gym membership.",
                     "Make a checklist for moving house next month."]},
    "small_business": {
        "name": "Small business", "icon": "🏪", "description": "Invoices, customers, marketing and plans for a small business.",
        "instructions": ("You are a practical small-business assistant. Keep answers concrete: numbers, next steps, "
                         "templates. Help with invoices, pricing, customer follow-ups (the CRM), simple marketing, "
                         "social posts and plans. Point out legal or tax questions that need a professional instead "
                         "of guessing."),
        "tools": ["crm_find", "crm_log", "crm_pipeline", "write_file", "make_app", "web_search", "email"],
        "skills": ["pricing", "social", "copywriting"],
        "starters": ["Make an invoice for 10 hours of design work at $60/hour.",
                     "Write three Instagram posts for my bakery's new bread.",
                     "Who are my customers I have not contacted in a month?",
                     "Help me price a new service."]},
    "student": {
        "name": "Student", "icon": "📚", "description": "Study plans, notes, flashcards and essay help - honestly.",
        "instructions": ("You help a student learn and stay organised: study plans with dates, clear notes, "
                         "flashcards, practice questions, essay outlines and feedback. Help them write their own work "
                         "- explain and give feedback instead of writing graded work for them. Keep plans realistic."),
        "tools": ["write_file", "make_app", "read_web", "web_search"], "skills": [],
        "starters": ["Make a two-week study plan for my biology exam.",
                     "Turn my notes into flashcards.",
                     "Give me feedback on my essay outline.",
                     "Explain this topic, then give me 5 practice questions."]},
    "creator": {
        "name": "Creator", "icon": "🎨", "description": "Ideas, scripts, pictures, music and videos.",
        "instructions": ("You are a creative partner for videos, posts, art, music and games. Offer a few distinct "
                         "ideas before committing, then make it: scripts, captions, picture prompts, sketches, "
                         "music. Use LOKI's creative tools (pictures, music, video, games) when they are set up and "
                         "say which ones are not."),
        "tools": ["generate_media", "make_music", "video_project", "game_engine_guide", "write_file"],
        "skills": ["video", "social"],
        "starters": ["Give me five video ideas for a cooking channel.",
                     "Write a 30-second script about my new product.",
                     "Make a picture of a cozy cabin in the snow, pixel art.",
                     "Make a tiny game where the fox collects stars."]},
}
for _id, _m in BUILTIN.items():
    _m["id"] = _id
    _m["builtin"] = True


def _root(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root) / "modes"
    explicit = os.getenv("LOKI_DATA", "").strip()
    return (Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data") / "modes"


def _scan_text(text: str) -> list:
    import skill_scan  # pylint: disable=import-outside-toplevel
    found = []
    for pattern in skill_scan.BLOCK_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            found.append("tries to override LOKI's rules: %r" % match.group(0)[:60])
    return found


def clean(mode: dict) -> dict:
    """A mode as LOKI keeps it, or ValueError saying what is wrong."""
    if not isinstance(mode, dict):
        raise ValueError("a mode is an object")
    name = " ".join(str(mode.get("name") or "").split())[:40]
    if not name:
        raise ValueError("a mode needs a name")
    mid = str(mode.get("id") or "").strip().lower() or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if mid and not mid[0].isalpha():
        mid = "m_" + mid
    mid = mid[:40]
    if not ID_RE.match(mid):
        raise ValueError("a mode id is 2-40 lowercase letters, digits, - or _")
    instructions = str(mode.get("instructions") or "").strip()[:MAX_INSTRUCTIONS]
    problems = _scan_text(instructions + "\n" + str(mode.get("description") or "") + "\n" + "\n".join(map(str, mode.get("starters") or [])))
    if problems:
        raise ValueError("refused: the mode " + "; ".join(problems))
    listed = lambda key, n, size: [str(x).strip()[:size] for x in (mode.get(key) or []) if str(x).strip()][:n]  # noqa: E731
    tools = [t for t in listed("tools", 40, 60) if re.match(r"^[A-Za-z0-9_.:-]+$", t)]
    skills = [s for s in listed("skills", 12, 80) if re.match(r"^[A-Za-z0-9_.-]+$", s)]
    return {"id": mid, "name": name, "icon": str(mode.get("icon") or "")[:8],
            "description": " ".join(str(mode.get("description") or "").split())[:200],
            "instructions": instructions, "tools": tools, "only_tools": bool(mode.get("only_tools")) and bool(tools),
            "skills": skills, "starters": listed("starters", 6, 200), "builtin": False}


def list_modes(root: Path | None = None) -> list:
    out = [dict(m) for m in BUILTIN.values()]
    folder = _root(root)
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            if path.name == "active.json":
                continue
            try:
                mode = json.loads(path.read_text(encoding="utf-8"))
                mode = dict(mode, id=path.stem, builtin=False)
            except (OSError, ValueError):
                continue
            out = [m for m in out if m["id"] != mode["id"]] + [mode]
    return out


def get(mode_id: str, root: Path | None = None) -> dict | None:
    for mode in list_modes(root):
        if mode["id"] == mode_id:
            return mode
    return None


def save(mode: dict, root: Path | None = None) -> dict:
    try:
        mode = clean(mode)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if mode["id"] in BUILTIN and not mode.get("override"):
        mode["id"] = mode["id"] + "_mine"
    folder = _root(root)
    folder.mkdir(parents=True, exist_ok=True)
    mode["updated"] = time.time()
    (folder / (mode["id"] + ".json")).write_text(json.dumps(mode, ensure_ascii=False, indent=1), encoding="utf-8")
    _CACHE.clear()
    return {"ok": True, "mode": mode}


def delete(mode_id: str, root: Path | None = None) -> dict:
    if mode_id in BUILTIN:
        return {"ok": False, "error": "built-in modes cannot be deleted"}
    path = _root(root) / (str(mode_id) + ".json")
    if not ID_RE.match(str(mode_id)) or not path.is_file():
        return {"ok": False, "error": "no mode %s" % mode_id}
    path.unlink()
    if active_id(root) == mode_id:
        set_active("", root)
    _CACHE.clear()
    return {"ok": True}


def active_id(root: Path | None = None) -> str:
    try:
        return str(json.loads((_root(root) / "active.json").read_text(encoding="utf-8")).get("id") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def set_active(mode_id: str, root: Path | None = None) -> dict:
    mode_id = str(mode_id or "")
    if mode_id and get(mode_id, root) is None:
        return {"ok": False, "error": "no mode %s" % mode_id}
    folder = _root(root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "active.json").write_text(json.dumps({"id": mode_id, "t": time.time()}), encoding="utf-8")
    _CACHE.clear()
    return {"ok": True, "active": mode_id}


_CACHE: dict = {}


def active(root: Path | None = None) -> dict | None:
    """The chosen mode (cached by the active file's mtime, so every system prompt can ask cheaply)."""
    path = _root(root) / "active.json"
    try:
        stamp = (str(path), path.stat().st_mtime)
    except OSError:
        return None
    if _CACHE.get("stamp") != stamp:
        mid = active_id(root)
        _CACHE.update(stamp=stamp, mode=get(mid, root) if mid else None)
    return _CACHE.get("mode")


def export(mode_id: str, root: Path | None = None) -> dict:
    mode = get(mode_id, root)
    if mode is None:
        return {"ok": False, "error": "no mode %s" % mode_id}
    body = {k: mode.get(k) for k in ("id", "name", "icon", "description", "instructions", "tools", "only_tools", "skills", "starters")}
    body["format"] = FORMAT
    return {"ok": True, "filename": "%s.lokimode" % mode["id"], "text": json.dumps(body, ensure_ascii=False, indent=1)}


def import_text(text: str, root: Path | None = None) -> dict:
    try:
        data = json.loads(str(text or ""))
    except ValueError:
        return {"ok": False, "error": "that is not a LOKI mode file (not JSON)"}
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return {"ok": False, "error": "that is not a LOKI mode file (format must be %s)" % FORMAT}
    data.pop("builtin", None)
    data.pop("override", None)
    return save(data, root)


def prompt_section(mode: dict | None) -> str:
    """What the system prompt gains while a mode is on."""
    if not mode:
        return ""
    lines = ["# Mode: %s" % mode.get("name", "")]
    if mode.get("instructions"):
        lines.append(str(mode["instructions"]))
    if mode.get("skills"):
        lines.append("Skill packs for this mode (load one with load_ecc_skill when it fits): " + ", ".join(mode["skills"]))
    if mode.get("tools"):
        lines.append("Tools that suit this mode: " + ", ".join(mode["tools"]) + ".")
    lines.append("(The mode changes how you work, never the safety rules: risky actions still ask the owner.)")
    return "\n".join(lines)
