"""Your agents: built once, with skills, tools, a model, a harness and a home machine.

An agent is a profile:

    name, role, goal         who it is and what it is for (the goal also routes work to it)
    instructions             how it works, in its own words
    engine (harness)         loki (LOKI's own loop: works offline, any model via the
                             prompted tool harness), claude-code, codex, hermes, opencode, openhands
    model, fallback          which provider it uses first, and which one if that fails
    skills                   SKILL.md folders it loads (skills/ in the repo, or your own in
                             harness_data/skills); their text is added to its instructions
    tools                    tool groups it may use (files, web, media, image, browser, ...)
    allow_commands           may it run commands in its (isolated) workspace
    machine                  "here", "auto" (the best linked machine) or a peer's name
    memory                   none | agent | project: what it remembers between runs
    max_minutes              how long one run may take
    color                    its colour in LOKI World

Running one starts a background job (workers.py) - here, or on the machine it lives on.
You never HAVE to build agents: teams (team.py) assemble roles on their own. The builder is
for agents you want to keep. `draft(description)` proposes a complete profile from one
sentence, offline, so building one is "describe it, check it, save it".

Stored in harness_data/agents.json. Pure functions over a list plus a tiny store.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

ENGINES = ("loki", "claude-code", "codex", "hermes", "opencode", "openhands")
ENGINE_LABELS = {"loki": "LOKI (built in, works offline)", "claude-code": "Claude Code (subscription)",
                 "codex": "Codex (subscription)", "hermes": "Hermes Agent", "opencode": "OpenCode",
                 "openhands": "OpenHands (local Ollama model by default)"}
TOOL_GROUPS = {
    "files": "read and edit files in its workspace",
    "commands": "run commands (tests, builds) in its workspace",
    "web": "read web pages and search (conductor read_web / research, Agent Reach)",
    "media": "video and audio: info, transcripts, downloads (yt-dlp)",
    "image": "generate images (Z-Image Turbo locally, or Pollinations)",
    "vision": "track objects in videos: cars, people (conductor track; RF-DETR + Roboflow trackers)",
    "browser": "drive a real browser (Browser Use; always asks first)",
    "memory": "long-term memory (Hindsight)",
    "team": "talk to other agents on the team board",
}
MEMORY_SCOPES = ("none", "agent", "project")
MAX_INSTRUCTIONS = 6000
MAX_SKILL_CHARS = 4000
MAX_SKILLS = 8
COLORS = ("#8fb3d9", "#a3be8c", "#ebcb8b", "#b48ead", "#88c0d0", "#d08770", "#bf616a", "#5e81ac")

STARTERS = [
    {"id": "researcher", "name": "Researcher", "engine": "loki", "allow_commands": False,
     "role": "research", "goal": "find things out and write them down with sources",
     "tools": ["files", "web", "media"], "color": "#88c0d0",
     "instructions": "You find things out. Use the conductor's research and read_web roles when they "
                     "are available, read the project's files, and write what you learned to "
                     "notes/research-<topic>.md with sources. Never change code."},
    {"id": "builder", "name": "Builder", "engine": "loki", "allow_commands": True,
     "role": "build", "goal": "implement changes and prove they work",
     "tools": ["files", "commands"], "color": "#a3be8c",
     "instructions": "You implement the task in small steps: read the relevant files, make the "
                     "change, then run the project's tests or checks to prove it works. Keep the "
                     "change minimal and explain it in your final DONE line."},
    {"id": "reviewer", "name": "Reviewer", "engine": "loki", "allow_commands": False,
     "role": "review", "goal": "review code without changing it", "tools": ["files"], "color": "#b48ead",
     "instructions": "You review code without changing it. Read the files involved and write a "
                     "short review to notes/review.md: real bugs first (with file and line), then "
                     "risks, then small improvements."},
    {"id": "tester", "name": "Tester", "engine": "loki", "allow_commands": True,
     "role": "test", "goal": "make sure things work", "tools": ["files", "commands"], "color": "#ebcb8b",
     "instructions": "You make sure things work. Find how the project is tested, run the tests, "
                     "and when something is missing add a focused test. Report what passed and "
                     "what failed."},
]

# Templates: complete agents you can start from in the builder (they are not saved until
# you save one). Each is a real, useful agent, not a placeholder.
TEMPLATES = STARTERS + [
    {"id": "app-idea", "name": "App Idea Shaper", "engine": "loki", "allow_commands": False,
     "role": "product", "goal": "turn a rough app idea into a buildable spec", "tools": ["files", "web"],
     "color": "#d08770",
     "instructions": "You turn a rough app idea into a spec someone can build. Work one step at a "
                     "time: the problem and who has it, the smallest version that helps them, the "
                     "core features (at most five), what it runs on, what data it keeps, and the "
                     "biggest technical risk. Check whether something like it already exists (web). "
                     "Write the result to notes/spec-<name>.md with a short build plan at the end. "
                     "(Pattern from github/awesome-copilot's simple app idea generator.)"},
    {"id": "video-researcher", "name": "Video Researcher", "engine": "loki", "allow_commands": False,
     "role": "research", "goal": "learn from videos: transcripts, summaries, key moments",
     "tools": ["files", "media", "web"], "color": "#5e81ac",
     "instructions": "You learn from videos. Get the video's details and transcript with the media "
                     "tools (yt-dlp), summarise it with timestamps for the key moments, and write it "
                     "to notes/video-<title>.md. Only download what the user has the right to use."},
    {"id": "web-reach", "name": "Web Scout", "engine": "loki", "allow_commands": False,
     "role": "research", "goal": "see what people say across the web (pages, GitHub, YouTube, RSS, Reddit)",
     "tools": ["files", "web", "media"], "color": "#88c0d0",
     "instructions": "You scout the web through Agent Reach's channels (web pages, GitHub, YouTube, "
                     "RSS, and the social sites the user has set up). Collect what you find with "
                     "links, separate facts from opinions, and write notes/scout-<topic>.md."},
    {"id": "artist", "name": "Image Artist", "engine": "loki", "allow_commands": False,
     "role": "create", "goal": "make images for the project", "tools": ["files", "image"], "color": "#bf616a",
     "instructions": "You make images. Write a precise prompt (subject, style, lighting, framing), "
                     "generate with the image tool, save into images/, and list what you made."},
    {"id": "opencode-coder", "name": "OpenCode Coder", "engine": "opencode", "allow_commands": True,
     "role": "build", "goal": "code with OpenCode on any provider (Zen's free models work)",
     "tools": ["files", "commands"], "color": "#a3be8c",
     "instructions": "Implement the task, run the tests, and summarise the change."},
    {"id": "openhands-coder", "name": "OpenHands Coder", "engine": "openhands", "allow_commands": True,
     "role": "build", "goal": "code with OpenHands on this computer's local Ollama model",
     "tools": ["files", "commands"], "color": "#5e81ac",
     "instructions": "Implement the task in small steps, run the project's tests, and summarise what changed."},
    # Written for LOKI (the stage-by-stage idea follows the common novel-writing workflow that
    # tools such as MuMuAINovel use; no text or prompt from any of them is copied here).
    {"id": "novel-writer", "name": "Novel Writer", "engine": "loki", "allow_commands": False,
     "role": "create", "goal": "write a novel stage by stage, from idea to revised chapters, in novel/",
     "tools": ["files"], "memory": "project", "max_minutes": 240, "color": "#b48ead",
     "instructions": (
         "You write long fiction in stages and keep every stage in files under novel/ so the work "
         "survives restarts and can be edited by the author between stages. Before each stage, read "
         "what already exists and continue from it; never silently overwrite the author's edits.\n"
         "1. Idea - novel/00-idea.md: premise in two sentences, genre, audience, tone, length target, "
         "and the central question the story answers. If the request is vague, propose three premises "
         "and pick the strongest, saying why.\n"
         "2. World - novel/01-world.md: setting, time, rules (technology, magic, society), places that "
         "matter, and the limits the plot must respect.\n"
         "3. Characters - novel/02-characters.md: for each main character a want, a need, a flaw, a "
         "secret, how they speak, and how they change; plus the relationships between them.\n"
         "4. Outline - novel/03-outline.md: acts, then one line per chapter (goal, conflict, turn, "
         "what the reader learns), ending with the climax and resolution.\n"
         "5. Chapters - novel/chapters/NN-title.md, one file per chapter, written from the outline. "
         "Show through scenes and dialogue, keep each character's voice, end chapters with momentum. "
         "After each chapter append a short summary to novel/04-summaries.md.\n"
         "6. Continuity check - novel/05-continuity.md: compare the chapters against the world, "
         "character sheets and summaries; list every contradiction (names, ages, timeline, rules, "
         "who knows what) with chapter and line, and how to fix it.\n"
         "7. Rewrite pass - fix what the continuity check found, tighten prose, cut repetition, and "
         "note what changed in novel/06-revisions.md.\n"
         "Work one stage per run unless the task asks for more, and end with a DONE line naming the "
         "files you wrote and the next stage.")},
]

# Words in a description -> what the agent needs. Used by draft().
_DRAFT_RULES = [
    (r"\b(test|qa|verify|check)\w*", {"role": "test", "tools": ["files", "commands"], "allow_commands": True}),
    (r"\b(build|code|implement|fix|refactor|program|develop)\w*",
     {"role": "build", "tools": ["files", "commands"], "allow_commands": True}),
    (r"\b(review|audit|critique)\w*", {"role": "review", "tools": ["files"]}),
    (r"\b(research|find|look up|compare|learn|investigate|summar)\w*", {"role": "research", "tools": ["files", "web"]}),
    (r"\b(video|youtube|podcast|transcri|audio)\w*", {"tools": ["media"]}),
    (r"\b(track|tracking|detect|count (cars|people|objects))\w*", {"tools": ["vision"]}),
    (r"\b(image|picture|art|logo|icon|illustrat|draw)\w*", {"role": "create", "tools": ["image"]}),
    (r"\b(browse|website|log ?in|form|click)\w*", {"tools": ["browser"]}),
    (r"\b(twitter|reddit|social|github|rss|news)\w*", {"tools": ["web"]}),
    (r"\b(idea|spec|product|app idea|plan)\w*", {"role": "product", "tools": ["files", "web"]}),
    (r"\b(remember|memory|notes)\w*", {"memory": "agent", "tools": ["memory"]}),
    (r"\b(gpu|train|fine-?tune|heavy|render)\w*", {"machine": "auto"}),
]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or uuid.uuid4().hex[:6]


def _clean_list(value, allowed=None, limit: int = 16) -> list:
    if isinstance(value, str):
        value = [v for v in re.split(r"[,\s]+", value) if v]
    out = []
    for item in value or []:
        item = str(item).strip().lower()
        if item and (allowed is None or item in allowed) and item not in out:
            out.append(item)
    return out[:limit]


def validate(spec: dict) -> dict:
    """A clean agent profile from user input; raises ValueError with a readable reason."""
    name = str(spec.get("name") or "").strip()
    if not name:
        raise ValueError("an agent needs a name")
    if len(name) > 40:
        raise ValueError("keep the name under 40 characters")
    engine = str(spec.get("engine") or "loki").strip().lower()
    if engine not in ENGINES:
        raise ValueError("engine must be one of " + ", ".join(ENGINES))
    instructions = str(spec.get("instructions") or "").strip()
    if len(instructions) > MAX_INSTRUCTIONS:
        raise ValueError("instructions are longer than %d characters" % MAX_INSTRUCTIONS)
    memory = str(spec.get("memory") or "none").strip().lower()
    if memory not in MEMORY_SCOPES:
        raise ValueError("memory must be one of " + ", ".join(MEMORY_SCOPES))
    machine = str(spec.get("machine") or "here").strip()[:40] or "here"
    if not re.match(r"^[A-Za-z0-9_. -]+$", machine):
        raise ValueError("machine must be here, auto or a linked machine's name")
    try:
        minutes = int(spec.get("max_minutes") or 60)
    except (TypeError, ValueError):
        raise ValueError("max minutes must be a number") from None
    minutes = max(1, min(minutes, 24 * 60))
    skills = _clean_list(spec.get("skills"), limit=MAX_SKILLS)
    for skill in skills:
        if not re.match(r"^[a-z0-9][a-z0-9_-]{0,63}$", skill):
            raise ValueError("unknown skill name %r" % skill)
    color = str(spec.get("color") or "").strip()
    if not re.match(r"^#[0-9a-fA-F]{6}$", color):
        color = COLORS[sum(map(ord, name)) % len(COLORS)]
    return {"id": str(spec.get("id") or _slug(name)), "name": name, "engine": engine,
            "role": str(spec.get("role") or "").strip()[:40],
            "goal": str(spec.get("goal") or "").strip()[:200],
            "instructions": instructions, "model": str(spec.get("model") or "").strip()[:80],
            "fallback": str(spec.get("fallback") or "").strip()[:80],
            "skills": skills, "tools": _clean_list(spec.get("tools"), TOOL_GROUPS),
            "allow_commands": bool(spec.get("allow_commands")),
            "isolate": bool(spec.get("isolate", True)), "machine": machine, "memory": memory,
            "max_minutes": minutes, "color": color,
            "updated": time.strftime("%Y-%m-%d %H:%M:%S")}


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()

    def all(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [a for a in data if isinstance(a, dict) and a.get("id")]
        except (OSError, ValueError):
            pass
        return [dict(a, starter=True) for a in STARTERS]

    def _save(self, agents: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(agents, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, agent_id: str) -> dict | None:
        return next((a for a in self.all() if a["id"] == agent_id), None)

    def save(self, spec: dict) -> dict:
        agent = validate(spec)
        with self.lock:
            agents = [a for a in self.all() if a["id"] != agent["id"]]
            agents.append(agent)
            self._save(agents)
        return agent

    def delete(self, agent_id: str) -> bool:
        with self.lock:
            agents = self.all()
            kept = [a for a in agents if a["id"] != agent_id]
            if len(kept) == len(agents):
                return False
            self._save(kept)
            return True


# --------------------------------------------------------------------------- skills
def _frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    meta = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta


def skill_roots(repo: Path, data_dir: Path) -> list:
    # skills/marketing: coreyhaines31/marketingskills (MIT, vendored; LICENSE beside it).
    roots = [("loki", Path(repo) / "skills"), ("yours", Path(data_dir) / "skills"),
             ("marketing", Path(repo) / "skills" / "marketing")]
    try:   # Ruflo's core skills and every plugin's (contrib/ruflo)
        import ruflo_library  # pylint: disable=import-outside-toplevel
        return roots + ruflo_library.skill_roots(Path(repo) / "contrib" / "ruflo")
    except Exception:  # noqa: BLE001
        return roots + [("ruflo", Path(repo) / "contrib" / "ruflo" / "skills")]


def skills_catalog(roots: list) -> list[dict]:
    """Every SKILL.md LOKI can give an agent: [{id, name, description, source, path}]."""
    found, seen = [], set()
    for source, root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for skill_md in sorted(root.glob("*/SKILL.md")):
            sid = skill_md.parent.name.lower()
            if sid in seen or not re.match(r"^[a-z0-9][a-z0-9_-]{0,63}$", sid):
                continue
            try:
                text = skill_md.read_text(encoding="utf-8", errors="replace")[:20000]
            except OSError:
                continue
            meta = _frontmatter(text)
            try:   # skills are untrusted text: one that tries to override LOKI's rules is never offered
                import skill_scan  # pylint: disable=import-outside-toplevel
                if skill_scan.scan(skill_md).get("verdict") == "blocked":
                    continue
            except Exception:  # noqa: BLE001
                pass
            seen.add(sid)
            found.append({"id": sid, "name": meta.get("name", sid), "description": meta.get("description", "")[:300],
                          "source": source, "path": str(skill_md)})
    return found


def skill_text(skill: dict) -> str:
    try:
        text = Path(skill["path"]).read_text(encoding="utf-8", errors="replace")
    except (OSError, KeyError):
        return ""
    end = text.find("\n---", 3) if text.startswith("---") else -1
    body = text[end + 4:] if end >= 0 else text
    body = body.strip()
    return body if len(body) <= MAX_SKILL_CHARS else body[:MAX_SKILL_CHARS] + "\n...[skill truncated]"


def full_instructions(agent: dict, catalog: list | None = None) -> str:
    """The agent's instructions with its goal, tool rules and skills spelled out."""
    parts = []
    if agent.get("role") or agent.get("goal"):
        parts.append("Role: %s. Goal: %s." % (agent.get("role") or "agent", agent.get("goal") or "the task"))
    if agent.get("instructions"):
        parts.append(agent["instructions"])
    tools = agent.get("tools") or []
    if tools:
        parts.append("Tools you are meant to use: " + "; ".join("%s (%s)" % (t, TOOL_GROUPS[t]) for t in tools if t in TOOL_GROUPS)
                     + ". Do not use tool groups outside this list.")
    if agent.get("memory") and agent["memory"] != "none":
        parts.append("Keep what you learn that will matter next time in notes/%s-memory.md (%s memory)."
                     % (agent.get("id", "agent"), agent["memory"]))
    by_id = {s["id"]: s for s in (catalog or [])}
    for sid in agent.get("skills") or []:
        skill = by_id.get(sid)
        if skill:
            text = skill_text(skill)
            if text:
                parts.append("## Skill: %s\n%s" % (skill.get("name", sid), text))
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- drafting
def draft(description: str, catalog: list | None = None) -> dict:
    """A complete agent profile from one sentence, with no model: rules over the words."""
    text = str(description or "").strip()
    if not text:
        raise ValueError("describe the agent in a sentence")
    low = text.lower()
    spec = {"role": "", "tools": ["files"], "allow_commands": False, "memory": "none", "machine": "here"}
    for pattern, adds in _DRAFT_RULES:
        if re.search(pattern, low):
            for key, value in adds.items():
                if key == "tools":
                    spec["tools"] = list(dict.fromkeys(spec["tools"] + value))
                elif key == "role" and spec["role"]:
                    continue
                else:
                    spec[key] = value
    role = spec["role"] or "helper"
    words = re.findall(r"[A-Za-z][A-Za-z0-9]+", text)
    stop = {"a", "an", "the", "that", "who", "which", "and", "for", "to", "of", "my", "me", "i", "agent",
            "want", "make", "build", "can", "will", "should", "with", "in", "on", "it", "is"}
    key = [w for w in words if w.lower() not in stop][:2]
    name = (" ".join(w.capitalize() for w in key) + " " + role.capitalize()).strip()[:40] or "New Agent"
    skills = []
    for skill in catalog or []:
        hay = (skill.get("name", "") + " " + skill.get("description", "")).lower()
        if any(w.lower() in hay for w in words if len(w) > 4):
            skills.append(skill["id"])
    instructions = ("You are %s. %s Work in small, checkable steps, write what you produce into the "
                    "workspace, and end with a DONE line that says what you did and how you checked it."
                    % (name, text[0].upper() + text[1:] + ("" if text.endswith(".") else ".")))
    return validate({"name": name, "role": role, "goal": text[:200], "instructions": instructions,
                     "tools": spec["tools"], "allow_commands": spec["allow_commands"], "memory": spec["memory"],
                     "machine": spec["machine"], "skills": skills[:MAX_SKILLS], "engine": "loki"})


# --------------------------------------------------------------------------- running
def job_spec(agent: dict, task: str, workspace: str, timeout_s: int = 0, catalog: list | None = None) -> dict:
    """The background-job spec that runs `task` as this agent."""
    task = str(task or "").strip()
    if not task:
        raise ValueError("give the agent a task")
    timeout_s = int(timeout_s or int(agent.get("max_minutes") or 60) * 60)
    tools = set(agent.get("tools") or [])
    allow = bool(agent.get("allow_commands")) or "commands" in tools
    spec = {"backend": "local", "agent": agent["engine"], "workspace": workspace,
            "isolate": agent.get("isolate", True), "timeout_s": timeout_s,
            "title": "%s: %s" % (agent["name"], task.splitlines()[0][:60]),
            "allow_commands": allow, "model": agent.get("model", ""),
            "fallback": agent.get("fallback", ""), "agent_id": agent.get("id", ""),
            "machine": agent.get("machine", "here"), "color": agent.get("color", "")}
    instructions = full_instructions(agent, catalog)
    if agent["engine"] == "loki":
        spec["prompt"] = task
        spec["profile"] = {"name": agent["name"], "instructions": instructions}
    else:
        # External agents get the profile as part of their prompt.
        prefix = ("You are %s. %s\n\n" % (agent["name"], instructions)) if instructions else ""
        spec["prompt"] = prefix + task
    return spec


def remote_prompt(spec: dict) -> str:
    """What a peer receives: the peer decides HOW to run it, so the profile rides in the text."""
    profile = spec.get("profile") or {}
    head = ("You are the agent \"%s\".\n%s\n\n# Task\n" % (profile.get("name", "agent"), profile.get("instructions", ""))
            if profile else "")
    return (head + spec.get("prompt", ""))[:16000]
