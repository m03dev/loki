"""Slash commands, prompt templates and @-mentions for LOKI Studio (the window and the Godot dock).

  /command args        a built-in (BUILTINS: some answer at once, some become a prompt for the agent)
  /template args       a prompt template: a .md file in <project>/.loki/prompts/, harness_data/studio/prompts/
                       or studio/prompts/ (bundled). {{args}}, {{selection}}, {{scene}} are filled in.
  @path/to/file        that file's text is attached to the message (folders: their listing)
  @scene @selection @errors @todos     the live editor's scene tree, the selected nodes + code, its errors,
                       the session's todo list
"""
from __future__ import annotations

import re
from pathlib import Path

import studio_paths

BUNDLED = studio_paths.HERE / "prompts"

# name -> (what it does, "now" = Studio answers itself | "prompt" = it becomes a message for the agent)
BUILTINS = {
    "help": ("list the commands and templates", "now"),
    "plan": ("Plan mode: the agent reads and plans (todos), changes nothing; /plan <task> plans that task", "mode"),
    "ask": ("Ask mode: questions about the project, read-only; /ask <question>", "mode"),
    "default": ("Default mode: the agent may change files (every turn has a checkpoint)", "mode"),
    "undo": ("undo the last turn (or /undo N: turn N and everything after it) - files and editor changes", "now"),
    "checkpoints": ("list this session's turns you can go back to", "now"),
    "todos": ("show the agent's todo list", "now"),
    "fork": ("copy this conversation into a new session (try another way without losing this one)", "now"),
    "model": ("/model <id>: drive this session with another model (auto, nvidia, openrouter, opencode-zen, gemini, groq, "
              "local, lmstudio, claude-code, codex)", "now"),
    "approve": ("/approve edits|auto: ask before every file/scene change, or not", "now"),
    "docs": ("/docs <class or words>: the Godot reference, offline", "now"),
    "web": ("/web <query>: search the web", "now"),
    "remember": ("/remember <fact>: keep it in LOKI's memory", "now"),
    "memory": ("/memory <query>: what LOKI's memory knows", "now"),
    "skills": ("list the skills", "now"),
    "index": ("/index [word]: the project index (scenes, scripts, signals) or the repo map", "now"),
    "graph": ("/graph [scenes|signals]: a diagram of the project", "now"),
    "errors": ("the editor's and the game's errors", "now"),
    "run": ("play the game (/run current, /run res://x.tscn)", "now"),
    "stop": ("stop the game", "now"),
    "screenshot": ("/screenshot [game|3d|2d|editor]", "now"),
    "lag": ("/lag [seconds]: find what makes the running game slow", "now"),
    "playtest": ("/playtest <goal>: the agent plays the game turn by turn to check <goal>", "prompt"),
    "fix": ("the agent fixes the current editor/game errors", "prompt"),
    "review": ("the agent reviews this session's changes", "prompt"),
    "test": ("the agent runs the tests that matter and fixes what fails", "prompt"),
    "skill": ("/skill <name> [task]: do the task following that skill", "prompt"),
    "clear": ("start a new session", "now"),
}

PROMPTS = {
    "playtest": ("Playtest the game to check: {{args}}\nDo it turn by turn: run_game, then playtest_step with a few inputs, look at "
                 "the screenshot result and the errors, decide the next input. Keep a todo list of what you checked. Stop the game "
                 "at the end and report what works and what does not (with the errors), then propose fixes."),
    "fix": ("Look at editor_errors and fix them one by one: find the cause with project_index / read_file, fix it, rescan, "
            "check the errors are gone. {{args}}"),
    "review": ("Review every change in this session (the diff) like a strict senior reviewer: bugs, both platforms (macOS and "
               "Windows), missing tests, unclear names. List problems first, then fix the real ones. {{args}}"),
    "test": ("Run the tests that cover what changed (at most a minute each), read the failures and fix them. {{args}}"),
    "skill": ("Use the skill {{skill}} (use_skill first, then follow it) for: {{args}}"),
}


def template_dirs(project: Path | None, data: Path | None) -> list:
    dirs = []
    if project:
        dirs.append(Path(project) / ".loki" / "prompts")
    if data:
        dirs.append(Path(data) / "studio" / "prompts")
    dirs.append(BUNDLED)
    return dirs


def templates(project: Path | None = None, data: Path | None = None) -> dict:
    """name -> {"path", "description", "text"}: the project's win over the owner's, which win over the bundled ones."""
    out = {}
    for d in template_dirs(project, data):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            name = re.sub(r"[^a-z0-9_-]", "", f.stem.lower())
            if not name or name in out or name in BUILTINS:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            desc = ""
            m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
            if m:
                dm = re.search(r"^description:\s*(.+)$", m.group(1), re.M)
                desc = dm.group(1).strip() if dm else ""
                text = text[m.end():]
            out[name] = {"path": str(f), "description": desc or text.strip().splitlines()[0][:120] if text.strip() else desc,
                         "text": text.strip()}
    return out


def listing(project: Path | None = None, data: Path | None = None) -> list:
    rows = [{"name": n, "description": d, "kind": k} for n, (d, k) in BUILTINS.items()]
    rows += [{"name": n, "description": t["description"], "kind": "template"} for n, t in templates(project, data).items()]
    return rows


def parse(text: str) -> tuple:
    """("name", "args") for '/name args', else ("", text)."""
    m = re.match(r"^/([a-z][a-z0-9_-]*)\b\s*(.*)$", str(text or "").strip(), re.S)
    return (m.group(1).lower(), m.group(2).strip()) if m else ("", str(text or ""))


def fill(template: str, args: str = "", **values) -> str:
    out = template.replace("{{args}}", args).replace("$ARGUMENTS", args)
    for k, v in values.items():
        out = out.replace("{{%s}}" % k, str(v))
    return re.sub(r"\{\{\w+\}\}", "", out).strip()


# ------------------------------------------------------------------ @-mentions
MENTION = re.compile(r"(?<![\w.])@((?:res://)?[\w./\\-]+[\w/])")
SPECIAL = ("scene", "selection", "errors", "todos")
MAX_ATTACH = 14_000


def mentions(text: str) -> list:
    return list(dict.fromkeys(m.group(1) for m in MENTION.finditer(str(text or ""))))


def complete(root: Path, query: str, limit: int = 30) -> list:
    """Paths under root that start with / contain `query` - for the @ autocomplete."""
    root = Path(root)
    q = str(query or "").replace("res://", "").lower().lstrip("/")
    out = [s for s in SPECIAL if s.startswith(q)] if len(q) < 10 else []
    base = root
    if "/" in q:
        head = q.rsplit("/", 1)[0]
        if (root / head).is_dir():
            base = root / head
    try:
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(root).as_posix()
            parts = set(p.relative_to(root).parts)
            if parts & {".git", ".godot", "harness_data", "node_modules", "__pycache__", ".import"} or p.name.endswith((".import", ".uid")):
                continue
            if q in rel.lower():
                out.append(rel + ("/" if p.is_dir() else ""))
                if len(out) >= limit:
                    break
    except OSError:
        pass
    return out


def expand(text: str, root: Path, live=None) -> tuple:
    """(text for the model, [attachment names]). `live(name)` returns the text of a special mention
    (scene, selection, errors, todos) or None."""
    parts, names = [], []
    for name in mentions(text):
        key = name.lower()
        if key in SPECIAL:
            body = live(key) if live else None
            if body:
                parts.append("@%s:\n%s" % (name, str(body)[:MAX_ATTACH]))
                names.append("@" + name)
            continue
        rel = name.replace("\\", "/")
        rel = (rel[6:] if rel.startswith("res://") else rel).rstrip("/")
        target = (Path(root) / rel).resolve()
        try:
            target.relative_to(Path(root).resolve())
        except ValueError:
            continue
        if any(p in (".git", "harness_data", ".godot") for p in Path(rel).parts) or re.search(r"(^|/)\.env|\.token$|\.key$|\.pem$", rel):
            continue
        if target.is_dir():
            items = sorted(c.name + ("/" if c.is_dir() else "") for c in target.iterdir() if not c.name.startswith("."))[:200]
            parts.append("@%s (folder):\n%s" % (rel, "\n".join(items)))
            names.append("@" + rel)
        elif target.is_file() and target.stat().st_size < 2_000_000:
            body = target.read_text(encoding="utf-8", errors="replace")
            if len(body) > MAX_ATTACH:
                body = body[:MAX_ATTACH] + "\n... (cut; read_file for the rest)"
            parts.append("@%s:\n```\n%s\n```" % (rel, body))
            names.append("@" + rel)
    if not parts:
        return text, []
    return text + "\n\n[Attached by the owner's @-mentions]\n" + "\n\n".join(parts), names
