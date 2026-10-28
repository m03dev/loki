"""Playbooks and toolboxes: one core agent, and per job the owner's way of doing it (owner 2026-10-28, with a screenshot:
"an AI playbook and toolbox strategy replaces the need to build a separate AI agent for every single task").

    playbook   the workflow for one job, in the owner's words: the goal, what DONE means, the steps in order, the
               rules (always / never), examples of good and bad results. LOKI writes it by INTERVIEWING the owner
               (playbook_interview.py); nothing goes in that he did not say or approve.
    toolbox    the resources that job uses: LOKI tools, the owner's files (references, templates, style guides),
               scripts to run, apps (MCP servers).

One file per job: <Home library>/playbooks/<id>.md (~/LOKI Projects/Home/playbooks; LOKI_PLAYBOOKS_DIR overrides), so
it is the same on the Mac and the PC (engine/library_sync.py copies the newer one) and the owner can open it.

How the core agent gets them (Anthropic's Agent Skills design: progressive disclosure):
    index      every approved playbook's name + one line goes into every request's preamble (a few lines)
    the match  the playbook whose triggers / title fit the request goes in in full, with its toolbox resolved
               (tools that exist here, files that exist here)
    on demand  `playbook` tool: read any playbook by name

Why one core agent (docs/AGENT_SYSTEM.md "One core agent"): Google Research's 180-configuration study (2025) - on
sequential work every multi-agent set-up was 39-70% worse than one agent; Anthropic's multi-agent research system wins
only on broad parallel research; Cognition: one writer, read-only helpers, a fresh-context reviewer.

File format:
    ---
    name: concept-art
    title: Concept art
    description: one line - when this playbook is used
    triggers: concept art, character design, creature
    status: approved | draft
    updated: 2026-10-28
    ---
    ## Goal / ## Done means / ## Steps / ## Rules / ## Examples / ## Toolbox (### Tools / Files / Scripts / Apps) /
    ## Owner notes
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

SECTIONS = ("Goal", "Done means", "Steps", "Rules", "Examples", "Toolbox", "Owner notes")
BOX = ("Tools", "Files", "Scripts", "Apps")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("a an the and or of to in on for with by at from as is are be this that it its into your you we our my "
            "i me do make made please can could would should will want need new some any all".split())


def folder() -> Path:
    raw = str(os.environ.get("LOKI_PLAYBOOKS_DIR") or "").strip()
    if raw:
        d = Path(os.path.expanduser(raw))
    else:
        try:
            import agent_folders  # pylint: disable=import-outside-toplevel
            d = agent_folders.projects_dir() / "Home" / "playbooks"
        except Exception:  # noqa: BLE001
            d = Path.home() / "LOKI Projects" / "Home" / "playbooks"
    return d


def slug(text: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:48]) or "job"


def path_for(pid: str) -> Path:
    p = folder() / (slug(pid) + ".md")
    return p


# ----------------------------------------------------------------------------- the file
def parse(text: str, pid: str = "") -> dict:
    meta, body = {}, str(text or "")
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end > 0:
            for line in body[3:end].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            body = body[end + 4:]
    secs: dict = {}
    cur = None
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m and not line.startswith("###"):
            cur = m.group(1).strip()
            secs[cur] = []
        elif cur is not None:
            secs[cur].append(line)
    secs = {k: "\n".join(v).strip() for k, v in secs.items()}
    box: dict = {k.lower(): [] for k in BOX}
    sub = None
    for line in secs.get("Toolbox", "").splitlines():
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            sub = m.group(1).strip().lower()
            continue
        item = re.sub(r"^\s*[-*]\s+", "", line).strip()
        if sub in box and item and line.lstrip().startswith(("-", "*")):
            box[sub].append(item)
    name = meta.get("name") or pid or slug(meta.get("title", ""))
    return {"id": slug(name), "title": meta.get("title") or name, "description": meta.get("description", ""),
            "triggers": [t.strip().lower() for t in re.split(r"[,;]", meta.get("triggers", "")) if t.strip()],
            "status": meta.get("status", "draft"), "updated": meta.get("updated", ""),
            "goal": secs.get("Goal", ""), "done": _items(secs.get("Done means", "")),
            "steps": _items(secs.get("Steps", "")), "rules": _items(secs.get("Rules", "")),
            "examples": secs.get("Examples", ""), "toolbox": box, "notes": _items(secs.get("Owner notes", ""))}


def _items(text: str) -> list:
    out = []
    for line in str(text or "").splitlines():
        m = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)", line)
        if m:
            out.append(m.group(1).strip())
        elif line.strip() and out and line.startswith("  "):
            out[-1] += " " + line.strip()
        elif line.strip():
            out.append(line.strip())
    return out


def render(pb: dict) -> str:
    """The playbook as its file (what the owner reads and edits)."""
    def bullets(xs):
        return "\n".join("- " + x for x in xs) if xs else ""
    lines = ["---", "name: %s" % pb["id"], "title: %s" % pb.get("title", pb["id"]),
             "description: %s" % " ".join(str(pb.get("description") or "").split()),
             "triggers: %s" % ", ".join(pb.get("triggers") or []), "status: %s" % pb.get("status", "draft"),
             "updated: %s" % (pb.get("updated") or time.strftime("%Y-%m-%d")), "---", "",
             "# %s" % pb.get("title", pb["id"]), ""]
    lines += ["## Goal", str(pb.get("goal") or "").strip(), ""]
    lines += ["## Done means", bullets(pb.get("done") or []), ""]
    lines += ["## Steps", "\n".join("%d. %s" % (i + 1, s) for i, s in enumerate(pb.get("steps") or [])), ""]
    lines += ["## Rules", bullets(pb.get("rules") or []), ""]
    lines += ["## Examples", str(pb.get("examples") or "").strip(), ""]
    lines += ["## Toolbox"]
    for k in BOX:
        lines += ["### %s" % k, bullets((pb.get("toolbox") or {}).get(k.lower()) or []) or "- (none)", ""]
    lines += ["## Owner notes", bullets(pb.get("notes") or []), ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).rstrip() + "\n"


def save(pb: dict) -> dict:
    pb = dict(pb)
    pb["id"] = slug(pb.get("id") or pb.get("title"))
    pb["updated"] = time.strftime("%Y-%m-%d")
    for k in BOX:      # "(none)" placeholders never come back as items
        pb.setdefault("toolbox", {})[k.lower()] = [x for x in (pb["toolbox"].get(k.lower()) or []) if x != "(none)"]
    f = path_for(pb["id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name("." + f.name + ".tmp")
    tmp.write_text(render(pb), encoding="utf-8")
    os.replace(tmp, f)
    return pb


def load(pid: str) -> dict | None:
    f = path_for(pid)
    try:
        return parse(f.read_text(encoding="utf-8"), f.stem)
    except OSError:
        return None


def everything(approved_only: bool = False) -> list:
    out = []
    d = folder()
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.md")):
        if f.name.startswith("."):
            continue
        try:
            pb = parse(f.read_text(encoding="utf-8"), f.stem)
        except OSError:
            continue
        pb["file"] = str(f)
        if not approved_only or pb["status"] == "approved":
            out.append(pb)
    return out


def approve(pid: str, text: str = "", as_id: str = "") -> dict:
    """The owner's OK: the playbook is used from now on. `text` = the whole file as he edited it; `as_id` = the
    approved playbook a re-interview's draft replaces (the draft file then goes)."""
    pb = parse(text, pid) if text.strip() else load(pid)
    if not pb:
        raise ValueError("no playbook %r" % pid)
    pb["id"] = slug(as_id or pid)
    pb["status"] = "approved"
    out = save(pb)
    if as_id and slug(as_id) != slug(pid) and path_for(pid).is_file():
        path_for(pid).unlink()
    return out


def remove(pid: str) -> bool:
    """Into the Home library's trash (never deleted outright; library_sync never pulls a trashed file back)."""
    f = path_for(pid)
    if not f.is_file():
        return False
    trash = folder().parent / "trash" / "playbooks"
    trash.mkdir(parents=True, exist_ok=True)
    target = trash / f.name
    if target.exists():
        target = trash / ("%s-%d%s" % (f.stem, int(time.time()), f.suffix))
    os.replace(f, target)
    return True


def add_note(pid: str, note: str) -> dict | None:
    """The owner's send-back note becomes part of that job's playbook (his words, verbatim)."""
    pb = load(pid)
    note = " ".join(str(note or "").split())
    if not pb or not note:
        return None
    if note not in pb["notes"]:
        pb["notes"] = (pb["notes"] + [note])[-40:]
        save(pb)
    return pb


# ----------------------------------------------------------------------------- which playbook fits a request
def _words(text: str) -> set:
    return {w for w in _WORD.findall(str(text or "").lower()) if w not in _STOP and len(w) > 1}


def score(pb: dict, task: str) -> float:
    low = " " + " ".join(_WORD.findall(str(task or "").lower())) + " "
    s = 0.0
    for t in pb.get("triggers") or []:
        t2 = " ".join(_WORD.findall(t))
        if t2 and " %s " % t2 in low:
            s += 2.0 + 0.5 * t2.count(" ")
    title = " ".join(_WORD.findall(str(pb.get("title") or "").lower()))
    if title and " %s " % title in low:
        s += 3.0
    shared = _words(task) & (_words(pb.get("title")) | _words(pb.get("description")))
    return s + 0.5 * len(shared)


def match(task: str, pbs: list | None = None) -> dict | None:
    """The approved playbook for this request, or None."""
    best, top = None, 0.0
    for pb in (everything(True) if pbs is None else pbs):
        sc = score(pb, task)
        if sc > top:
            best, top = pb, sc
    return best if top >= 1.5 else None


# ----------------------------------------------------------------------------- what the agent sees
def index_text(limit: int = 1200) -> str:
    pbs = everything(True)
    if not pbs:
        return ""
    lines = ["The owner's playbooks (his way of doing each job - read one with the playbook tool when it fits):"]
    lines += ["- %s: %s" % (pb["id"], pb["description"] or pb["title"]) for pb in pbs]
    out = "\n".join(lines)
    return out if len(out) <= limit else out[:limit].rsplit("\n", 1)[0]


def resolve_toolbox(pb: dict, tools_known: set | None = None, workspace: Path | None = None) -> dict:
    """The toolbox as it is on THIS machine: which tools exist, which files are here."""
    box = pb.get("toolbox") or {}
    out = {"tools": [], "files": [], "scripts": list(box.get("scripts") or []), "apps": list(box.get("apps") or []),
           "missing": []}
    for t in box.get("tools") or []:
        name = re.split(r"[\s:(\-–]", t.strip(), 1)[0].strip("`")
        if tools_known is not None and name and name not in tools_known:
            out["missing"].append("tool %s" % name)
        out["tools"].append(t)
    home = folder().parent
    for f in box.get("files") or []:
        path = re.split(r"\s+[-–:]\s+", f.strip(), 1)[0].strip("`")
        cands = [Path(os.path.expanduser(path))] if os.path.isabs(os.path.expanduser(path)) else \
            [home / path] + ([Path(workspace) / path] if workspace else [])
        found = next((c for c in cands if c.exists()), None)
        out["files"].append("%s%s" % (f, "" if found else "  (not on this machine)"))
        if not found:
            out["missing"].append("file %s" % path)
    return out


def brief(pb: dict, tools_known: set | None = None, workspace: Path | None = None, limit: int = 3500) -> str:
    """The full playbook + its toolbox, for the agent doing this job."""
    box = resolve_toolbox(pb, tools_known, workspace)
    parts = ["Playbook for this job: %s (the owner's own workflow - follow it)." % pb["title"]]
    if pb.get("goal"):
        parts.append("Goal: " + pb["goal"])
    if pb.get("done"):
        parts.append("Done means:\n" + "\n".join("- " + x for x in pb["done"]))
    if pb.get("steps"):
        parts.append("Steps:\n" + "\n".join("%d. %s" % (i + 1, s) for i, s in enumerate(pb["steps"])))
    if pb.get("rules"):
        parts.append("Rules:\n" + "\n".join("- " + x for x in pb["rules"]))
    if pb.get("notes"):
        parts.append("The owner's notes from earlier results:\n" + "\n".join("- " + x for x in pb["notes"][-10:]))
    tb = []
    for k, label in (("tools", "Tools"), ("files", "Files (the owner's references and templates)"),
                     ("scripts", "Scripts"), ("apps", "Apps")):
        if box[k]:
            tb.append("%s:\n%s" % (label, "\n".join("- " + x for x in box[k])))
    if tb:
        parts.append("Toolbox:\n" + "\n".join(tb))
    if pb.get("examples"):
        parts.append("Examples: " + pb["examples"])
    out = "\n\n".join(parts)
    return out if len(out) <= limit else out[:limit].rsplit("\n", 1)[0] + "\n(...the rest: playbook tool, name=%s)" % pb["id"]


def tool(args: dict) -> dict:
    """The `playbook` tool: list | read <name>."""
    a = dict(args or {})
    name = str(a.get("name") or a.get("id") or "")
    if not name or str(a.get("action") or "") == "list":
        return {"ok": True, "playbooks": [{"name": p["id"], "title": p["title"], "description": p["description"],
                                           "status": p["status"]} for p in everything()]}
    pb = load(name)
    if not pb:
        return {"ok": False, "error": "no playbook %r - action=list shows them" % name}
    return {"ok": True, "status": pb["status"], "playbook": brief(pb, limit=12000)}


TOOL_SCHEMA = {
    "name": "playbook",
    "description": "The owner's playbooks: his own workflow for each job (goal, done means, steps, rules) and its "
                   "toolbox (tools, his reference files and templates, scripts, apps). action=list, or name=<id> to "
                   "read one before doing that job.",
    "inputSchema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["list", "read"]},
                                                      "name": {"type": "string"}}},
}
