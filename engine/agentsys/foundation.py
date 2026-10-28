"""The foundation: the rulebook every LOKI agent works from (owner 2026-10-28: "playbook is the rules its much more
complex its the foundation").

Four layers, strongest first - a lower layer never overrides a higher one:

    1. the owner's rules      AGENTS.md "## The rules", word for word (only what the owner said)
    2. the constitution       skills/playbooks/CONSTITUTION.md - how every LOKI agent works: plan, act, check, hand
                              off, ask, report (LOKI's working method, not the owner's rules)
    3. domain playbooks       skills/playbooks/<kind>/PLAYBOOK.md - one per kind of work (manga, image, 3d, code ...):
                              its stages (who does what, in which order, with which tools, checked how, gated where),
                              the interview questions, the checklist, the quality bar, the known failure modes and
                              their fixes, the hand-off template
    4. learned lines          engine/agentsys/playbook.py - what results and the owner's send-backs taught (ACE)

The layers feed every part of the agent system: context (the preamble every harness gets), the interview (a
playbook's questions come first), the orchestrator (a playbook's stages are the plan's skeleton; a model only fills in
the specifics) and the evaluator (each stage's checklist is what its result is checked against).

PLAYBOOK.md format: a front matter (name, title, triggers, specialists), then "## " sections. Stages and Questions
are JSON in a fenced block (machine-read); everything else is plain markdown (model-read).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_CACHE: dict = {"t": 0.0, "stamp": None, "books": {}}


def root() -> Path:
    return Path(os.environ.get("LOKI_PLAYBOOKS_DIR") or REPO / "skills" / "playbooks")


# ----------------------------------------------------------------------------- layer 1: the owner's rules
def owner_rules(repo: Path | None = None) -> list:
    """AGENTS.md's numbered rules, word for word."""
    try:
        text = ((repo or REPO) / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        return []
    m = re.search(r"^## The rules\s*$(.*?)^## ", text, re.M | re.S)
    if not m:
        return []
    rules, cur = [], ""
    for line in m.group(1).splitlines():
        if re.match(r"^\d+\.\s", line):
            if cur:
                rules.append(cur.strip())
            cur = line
        elif cur and line.startswith("   "):
            cur += " " + line.strip()
    if cur:
        rules.append(cur.strip())
    return rules


def owner_rules_text(repo: Path | None = None) -> str:
    rules = owner_rules(repo)
    if not rules:
        return ""
    return "The owner's rules (his words - they win over everything else):\n" + "\n".join(rules)


# ----------------------------------------------------------------------------- parsing PLAYBOOK.md
def _front(text: str) -> tuple:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text[end + 4:]


def _sections(body: str) -> dict:
    out, name, buf = {}, "_intro", []
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            out[name] = "\n".join(buf).strip()
            name, buf = m.group(1).strip().lower(), []
        else:
            buf.append(line)
    out[name] = "\n".join(buf).strip()
    return out


def _json_block(text: str):
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def parse(text: str, path: str = "") -> dict:
    meta, body = _front(text)
    secs = _sections(body)
    stages = _json_block(secs.get("stages", "")) or []
    questions = _json_block(secs.get("questions", "")) or []
    trig = [t.strip().lower() for t in re.split(r"[,;]", meta.get("triggers", "")) if t.strip()]
    return {"name": meta.get("name") or Path(path).parent.name, "title": meta.get("title") or meta.get("name", ""),
            "triggers": trig, "specialists": [s.strip() for s in meta.get("specialists", "").split(",") if s.strip()],
            "path": path, "sections": secs,
            "stages": [s for s in stages if isinstance(s, dict) and s.get("id") and s.get("objective")],
            "questions": [q for q in questions if isinstance(q, dict) and q.get("question") and q.get("options")]}


def _stamp(base: Path) -> tuple:
    try:
        return tuple(sorted((str(p), p.stat().st_mtime) for p in base.glob("*/PLAYBOOK.md")))
    except OSError:
        return ()


def books() -> dict:
    """Every domain playbook, by name (cached; re-read when a file changes)."""
    base = root()
    st = _stamp(base)
    if _CACHE["stamp"] == st and time.time() - _CACHE["t"] < 60:
        return _CACHE["books"]
    out = {}
    for p in sorted(base.glob("*/PLAYBOOK.md")):
        try:
            b = parse(p.read_text(encoding="utf-8"), str(p))
        except OSError:
            continue
        out[b["name"]] = b
    _CACHE.update(t=time.time(), stamp=st, books=out)
    return out


def constitution() -> str:
    try:
        return (root() / "CONSTITUTION.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def constitution_brief(limit: int = 1800) -> str:
    """The constitution's numbered principles only (what goes into every preamble)."""
    text = constitution()
    lines = [l for l in text.splitlines() if re.match(r"^\s*\d+\.\s", l)]
    out = "How LOKI's agents work (LOKI's working method):\n" + "\n".join(l.strip() for l in lines)
    return out[:limit] if lines else ""


# ----------------------------------------------------------------------------- picking the playbook for a task
_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
# verbs any kind of work uses: half a point, so "draw a manga page" is a manga, not a picture
GENERIC = {"draw", "make", "create", "build", "write", "generate", "design", "edit", "fix", "page", "picture", "image",
           "render", "model", "story", "art", "panel", "chapter"}


def match(task: str, kind: str = "") -> dict | None:
    """The domain playbook for this task: its triggers scored against the task's words; the kind decides a tie."""
    text = " " + " ".join(_WORD.findall(str(task or "").lower())) + " "
    best, score, second = None, 0.0, 0.0
    for b in books().values():
        s = 0.0
        for t in b["triggers"]:
            if t and (" %s " % t) in text or (len(t) > 4 and t in text):
                s += (0.5 if t in GENERIC else 1.0) + 0.2 * t.count(" ")
        if kind and b["name"] == kind:
            s += 0.5
        if s > score:
            best, score, second = b, s, score
        elif s > second:
            second = s
    if best is None and kind:
        best = books().get(kind)
    # a domain word decides; a generic verb alone decides only when no other playbook has it too
    return best if (best and (score >= 1.0 or best["name"] == kind or (score >= 0.5 and second < score))) else None


def kind_for(task: str, fallback: str = "") -> str:
    b = match(task, fallback)
    return b["name"] if b else fallback


def brief(task: str, kind: str = "", limit: int = 3500) -> str:
    """The part of the matching playbook a harness needs for this task: the stages in one line each, the checklist,
    the quality bar and the failure modes (most useful first, cut to `limit`)."""
    b = match(task, kind)
    if not b:
        return ""
    sec = b["sections"]
    parts = ["Playbook: %s (skills/playbooks/%s/PLAYBOOK.md) - follow it step by step." % (b["title"] or b["name"], b["name"])]
    if b["stages"]:
        parts.append("Stages:\n" + "\n".join(
            "%d. %s - %s -> %s%s" % (i + 1, s.get("specialist", "worker"), s["objective"], s.get("output", ""),
                                     " [waits for the owner's OK]" if s.get("gate") == "owner" else "")
            for i, s in enumerate(b["stages"])))
    for key in ("checklist", "quality bar", "failure modes", "tools"):
        if sec.get(key):
            parts.append("%s:\n%s" % (key.capitalize(), sec[key].strip()))
    out = "\n\n".join(parts)
    return out if len(out) <= limit else out[:limit].rsplit("\n", 1)[0] + "\n(...see the full playbook file)"


def stages(task: str, kind: str = "") -> list:
    b = match(task, kind)
    return [dict(s) for s in (b or {}).get("stages", [])]


def questions(task: str, kind: str = "") -> list:
    b = match(task, kind)
    return [dict(q) for q in (b or {}).get("questions", [])]


def checklist_for(task: str, stage_id: str = "", kind: str = "") -> str:
    b = match(task, kind)
    if not b:
        return ""
    st = next((s for s in b["stages"] if s.get("id") == stage_id), None)
    own = (st or {}).get("check", "")
    return "\n".join(x for x in (own, b["sections"].get("checklist", "")) if x)


def overview() -> list:
    return [{"name": b["name"], "title": b["title"], "stages": [s["id"] for s in b["stages"]],
             "questions": len(b["questions"]), "specialists": b["specialists"], "path": b["path"],
             "sections": [k for k in b["sections"] if k != "_intro"]} for b in books().values()]
