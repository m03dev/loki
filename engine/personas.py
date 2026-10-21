"""Modes (personas): switchable packs that turn LOKI into a Content creator, Outreach, a Writer, ... (docs/APPS.md).

A mode = instructions + chosen tools + skills + starter prompts:

    {"id": "outreach", "name": "Outreach", "icon": "✉️", "description": "one line",
     "instructions": "how LOKI behaves in this mode (added to the system prompt)",
     "tools": ["read_web", ...],      # put first for small models; with "only_tools": true the ONLY ones offered
     "skills": ["doc-coauthoring"],   # skill packs LOKI loads with load_ecc_skill when they fit
     "starters": ["Write a cold email to ...", ...]}   # the chips under "What should Loki work on?"

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

# The built-in modes are for the digital industry: content, social, outreach, writing, growth, research, building
# and 3D (owner 2026-10-21: "all those guys geared towards the digital industry and content making, outreach emails").
# Tutor, Student, Life admin and Small business are gone; an old choice of one of them lands on its nearest mode.
BUILTIN: dict = {
    "creator": {
        "name": "Content creator", "icon": "🎬", "description": "Video ideas, hooks, scripts, shorts, thumbnails and captions.",
        "instructions": ("You are a content producer for creators and brands. Start from the audience and the platform "
                         "(YouTube, TikTok, Reels, Shorts, podcasts). Offer a few distinct angles with a strong hook "
                         "each before committing, then make it: outline, script with timings, b-roll and shot list, "
                         "on-screen text, title options, thumbnail concepts and the caption. Repurpose one piece into "
                         "several formats when it helps. Use LOKI's creative tools (pictures, music, video) when they "
                         "are set up and say which ones are not."),
        "tools": ["generate_media", "video_project", "make_music", "web_search", "write_file"],
        "skills": ["video", "social", "content-strategy", "copywriting"],
        "starters": ["Give me ten video ideas for my channel, each with a hook.",
                     "Write a 60-second short script with timings and on-screen text.",
                     "Turn this long video into five shorts and a thread.",
                     "Make three thumbnail concepts and titles for this video."]},
    "social": {
        "name": "Social media", "icon": "📱", "description": "Posts, a content calendar, captions and what is trending.",
        "instructions": ("You run social media for a creator or a digital brand. Write in the platform's own style "
                         "(X, LinkedIn, Instagram, TikTok, Threads, YouTube community). Keep posts tight, lead with "
                         "the hook, end with one clear call to action. Plan a posting calendar when asked, check what "
                         "is trending with a search before leaning on it, and never post anything without asking."),
        "tools": ["web_search", "research_web", "generate_media", "write_file", "make_app"],
        "skills": ["social", "community-marketing", "influencer-marketing", "content-strategy"],
        "starters": ["Plan two weeks of posts for my launch, every platform.",
                     "Write five LinkedIn posts from this blog post.",
                     "What is trending in my niche this week?",
                     "Write captions for these three pictures."]},
    "outreach": {
        "name": "Outreach", "icon": "✉️", "description": "Cold emails, follow-ups, sponsor and collab pitches, client lists.",
        "instructions": ("You handle outreach for a creator, studio or digital agency: cold emails, follow-up sequences, "
                         "sponsorship and brand-deal pitches, collab requests, press and podcast pitches, client "
                         "proposals. Research the person or company first and make every email specific to them. Keep "
                         "emails short, one ask each, with a clear subject line. Track who was contacted in the CRM. "
                         "Draft only: never send an email without asking first."),
        "tools": ["email", "crm_find", "crm_log", "crm_pipeline", "web_search", "research_web", "write_file"],
        "skills": ["cold-email", "emails", "prospecting", "public-relations", "co-marketing", "sales-enablement"],
        "starters": ["Write a cold email pitching my 3D modelling services to a game studio.",
                     "Draft a sponsorship pitch for my channel and a follow-up for next week.",
                     "Find ten studios that might hire me and write to each one.",
                     "Who have I not followed up with this month?"]},
    "writer": {
        "name": "Writer", "icon": "✍️", "description": "Blogs, newsletters, landing pages and scripts in your voice.",
        "instructions": ("You are a writing partner for digital work: blog posts, newsletters, landing pages, product "
                         "copy, video and podcast scripts. Ask who the reader is and what the piece must do if that is "
                         "unclear. Draft in clear, concrete sentences; prefer short words and active verbs. When "
                         "editing, keep the author's voice, explain the important changes briefly, and offer one "
                         "stronger alternative for weak lines. Save longer pieces as files in the workspace."),
        "tools": ["write_file", "read_file", "list_files", "web_search"],
        "skills": ["copywriting", "copy-editing", "doc-coauthoring", "emails"],
        "starters": ["Write this week's newsletter from these notes.",
                     "Write the copy for a landing page for my new asset pack.",
                     "Turn this video script into a blog post.",
                     "Tighten this paragraph and tell me what you changed."]},
    "growth": {
        "name": "Growth & SEO", "icon": "📈", "description": "Launches, SEO, ads, analytics and what to try next.",
        "instructions": ("You are a growth marketer for digital products and creators. Keep it concrete: numbers, "
                         "experiments and next steps. Help with launch plans, SEO (keywords, titles, pages), ads, "
                         "pricing, email funnels and reading analytics. Search for current platform rules and "
                         "numbers instead of guessing, and say plainly what you could not verify."),
        "tools": ["web_search", "research_web", "read_web", "write_file", "make_app"],
        "skills": ["launch", "seo-audit", "ai-seo", "ads", "analytics", "marketing-plan", "pricing", "lead-magnets"],
        "starters": ["Make a launch plan for my Gumroad asset pack.",
                     "Find the keywords my portfolio site should rank for.",
                     "Write three ad variations and how to test them.",
                     "How should I price my modelling course?"]},
    "researcher": {
        "name": "Researcher", "icon": "🔎", "description": "Trends, competitors and audiences - with sources for every claim.",
        "instructions": ("You are a rigorous researcher for digital work: trends, competitors, audiences, tools and "
                         "platforms. Search before answering anything factual or recent, read the sources, and cite "
                         "each claim with its link. Separate what the sources say from your own reasoning. Say plainly "
                         "when sources disagree or when you could not verify something. End with a short summary."),
        "tools": ["web_search", "read_web", "research_web", "browse_page", "write_file"],
        "skills": ["competitor-profiling", "customer-research", "competitors"],
        "starters": ["Who are the top five creators in my niche and what do they do well?",
                     "Compare the main AI render tools, with sources.",
                     "What are people asking about 3D modelling on Reddit this month?",
                     "Profile this competitor's content strategy."]},
    "coder": {
        "name": "Developer", "icon": "💻", "description": "Websites, apps, tools and scripts - small tested changes.",
        "instructions": ("You are a careful senior engineer building websites, web apps, tools and pipeline scripts. "
                         "Read the relevant code before changing it, make the smallest change that works, run the "
                         "tests or a quick check, and say exactly what you verified. Explain decisions briefly. Never "
                         "invent APIs: look them up in the code first."),
        "tools": ["read_file", "write_file", "list_files", "search_files", "run_command", "repo_map", "apply_edits"],
        "skills": ["frontend-design", "webapp-testing"],
        "starters": ["Build me a portfolio site for my 3D work.",
                     "Explain how this project is organised.",
                     "Find and fix the bug in the failing test.",
                     "Write a script that renames my renders by date."]},
    "artist": {
        "name": "3D & games", "icon": "🧊", "description": "Models in Forge, renders in Render Studio, games in Godot.",
        "instructions": ("You are a 3D and game production partner. Use LOKI's Forge for models, Render Studio for "
                         "renders (the PC's GPU when it is linked) and the live Godot editor for games. Plan the shot "
                         "or scene first, say what you will make, then make it and check the result."),
        "tools": ["forge", "godot_editor", "generate_media", "write_file"],
        "skills": [],
        "starters": ["Block out a low-poly sci-fi crate in Forge.",
                     "Render my scene with a moody studio light.",
                     "Add a day-night cycle to my Godot project.",
                     "Plan a 10-second turntable for my character."]},
}
# old built-in ids (before 2026-10-21) -> the mode that took over their work
RETIRED = {"small_business": "outreach", "life_admin": "", "tutor": "", "student": ""}
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
    if mode_id in RETIRED and not (_root(root) / (str(mode_id) + ".json")).is_file():
        mode_id = RETIRED[mode_id]
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
