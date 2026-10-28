"""Playbooks: what LOKI has learned works (and doesn't) for each kind of work, as small counted bullets.

This is ACE - Agentic Context Engineering (Zhang et al. 2025, github.com/ace-agent/ace, Apache-2.0: generator,
reflector, curator) with the fixes an independent review found missing from its public code, plus ideas from
Dynamic Cheatsheet, ReasoningBank and Voyager (docs/AGENT_SYSTEM.md "Playbooks"):

  - A playbook is a list of bullets, never one blob: `[img-00042] helpful=3 harmful=0 :: <strategy>`. Whole
    rewrites by a model collapse a playbook (ACE: 18k tokens -> 122), so a model may only PROPOSE small ops
    (add / update / retire) and this code applies them.
  - The counters are used: retrieval ranks by relevance x (helpful - harmful), and a bullet whose harmful count
    beats its helpful count after a few uses is retired (ACE's code never pruned).
  - Every bullet keeps where it came from (the run's trace id, the owner's send-back, an approval) - provenance.
  - Only the top few bullets for THIS task go into the prompt, not the whole playbook.
  - The strongest signal is the owner: a send-back note becomes an "owner" bullet straight away; an approval marks
    the bullets that run used as helpful (Voyager: only verified success promotes a skill).

Storage: <data>/playbooks/<kind>.json (kinds from engine/specialist_library.kind: image, turnaround, 3d, video,
code, marketing, research, writing, general). Thread- and process-safe enough: one write = one os.replace.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable

from . import sub, trace

SECTIONS = ("owner", "strategy", "check", "mistake")     # owner = the owner's taste, straight from his words
PREFIX = {"image": "img", "turnaround": "trn", "3d": "m3d", "video": "vid", "code": "cod", "marketing": "mkt",
          "research": "res", "writing": "wri", "general": "gen", "manga": "mng", "design": "dsg", "mobile-test": "mob",
          "render": "rnd", "music": "mus"}
MAX_BULLETS = int(os.environ.get("LOKI_PLAYBOOK_MAX", "150") or 150)
TOP_K = int(os.environ.get("LOKI_PLAYBOOK_TOP_K", "8") or 8)
_LOCK = threading.Lock()
_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("a an the and or of to in on for with by at from as is are be this that it its into your you we our "
            "it's do does not no but if so then than when what which who how all any some more most very just".split())

# Where a new playbook starts: strategies the research found that the big systems use (docs/AGENT_SYSTEM.md). They are
# marked "seed" and earn or lose their place like every other bullet - none of them is a rule.
SEED = {
    "general": [
        ("strategy", "Restate the goal and what DONE looks like before the first tool call; check the result against it at the end."),
        ("check", "Before saying it is done, open what was made (the file, the picture, the page) - a claim without the file is not done."),
        ("mistake", "Repeating the same call after it failed the same way twice never works - change the approach or ask."),
    ],
    "code": [
        ("strategy", "Read the code you change and its callers first; change the smallest thing that fixes the root cause."),
        ("check", "Run the narrowest test that proves the change, then the suite for that area (within the 1-minute budget)."),
        ("mistake", "Editing a file from memory of an old read breaks it - re-read the lines right before editing them."),
    ],
    "image": [
        ("strategy", "Name subject, pose/action, camera (angle, lens), lighting, palette, medium and style - one concrete phrase each."),
        ("check", "Look at the picture next to the prompt: every named element present, nothing extra, the style right."),
    ],
    "turnaround": [
        ("strategy", "Front, side and back are drawn together on one canvas from the concept, T-pose, flat even light, orthographic."),
        ("check", "Compare silhouette, colours and proportions across the three views - they must be the same character."),
    ],
    "3d": [
        ("strategy", "Start from a clean single-object picture on a plain background; cut it out first."),
        ("check", "Render the model next to its concept and report triangles, seconds and the likeness score."),
    ],
    "video": [
        ("strategy", "One shot, one action: subject, motion, camera move, lighting, duration - Wan's prompt order."),
    ],
    "research": [
        ("strategy", "Split the question into parts and search each part separately; prefer primary sources."),
        ("check", "Every claim in the answer points at a source that was actually read."),
    ],
    "marketing": [
        ("strategy", "Lead with the one thing the audience gets; one call to action; write for the platform's format."),
    ],
    "writing": [
        ("strategy", "Match the length and tone asked for; plain words; the main point first."),
    ],
}


def folder() -> Path:
    return sub("playbooks")


def kind_of(task: str) -> str:
    """The kind of work (for the learned notes), from the specialist library's word lists."""
    try:
        import specialist_library  # pylint: disable=import-outside-toplevel
        k = specialist_library.kind(task)
    except Exception:  # noqa: BLE001
        k = "general"
    return k if k in PREFIX else "general"


def _path(kind: str) -> Path:
    if kind not in PREFIX:
        raise ValueError("unknown playbook kind %r" % kind)
    return folder() / ("%s.json" % kind)


def load(kind: str) -> dict:
    p = _path(kind)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("bullets"), list):
            return data
    except (OSError, ValueError):
        pass
    data = {"kind": kind, "next": 1, "bullets": []}
    for section, text in SEED.get(kind, []):
        _add(data, section, text, origin="seed")
    return data


def save(data: dict) -> None:
    p = _path(data["kind"])
    tmp = p.with_suffix(".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _words(text: str) -> set:
    return {w for w in _WORD.findall(str(text or "").lower()) if w not in _STOP and len(w) > 1}


def _similar(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / float(len(wa | wb))


def _add(data: dict, section: str, text: str, origin: str = "", source: str = "") -> dict:
    text = " ".join(str(text or "").split())[:400]
    section = section if section in SECTIONS else "strategy"
    for b in data["bullets"]:     # the curator's dedupe: near-same words = the same bullet (counters add up)
        if b["status"] == "active" and _similar(b["text"], text) >= 0.8:
            if source and source not in b["sources"]:
                b["sources"] = (b["sources"] + [source])[-12:]
            if section == "owner" and b["section"] != "owner":
                b["section"] = "owner"
            return b
    bid = "%s-%05d" % (PREFIX[data["kind"]], int(data.get("next") or 1))
    data["next"] = int(data.get("next") or 1) + 1
    b = {"id": bid, "section": section, "text": text, "helpful": 0, "harmful": 0, "uses": 0, "status": "active",
         "origin": origin or "reflect", "sources": [source] if source else [], "t": time.time(), "last_used": 0.0}
    data["bullets"].append(b)
    return b


def score(b: dict) -> float:
    """How much a bullet has earned: owner bullets start high, counters move it."""
    base = 3.0 if b["section"] == "owner" else 1.0 if b["origin"] != "seed" else 0.6
    return base + b["helpful"] - 1.5 * b["harmful"]


def select(task: str, kind: str = "", k: int = TOP_K) -> list:
    """The few bullets for this task: relevance to the task words x what they earned. Owner bullets always come."""
    kind = kind or kind_of(task)
    with _LOCK:
        data = load(kind)
    words = _words(task)
    active = [b for b in data["bullets"] if b["status"] == "active"]
    if kind != "general":                         # the general strategies apply to everything
        active += [dict(b, _general=True) for b in load("general")["bullets"] if b["status"] == "active"]

    def rank(b: dict) -> float:
        overlap = len(words & _words(b["text"])) / (1.0 + len(_words(b["text"]))) if words else 0.0
        return score(b) * (0.5 + overlap) - (0.2 if b.get("_general") else 0.0)
    # the owner's notes come first - but only those that share a word with this task (a note about the golem's
    # lighting has no business in a haiku); a note with no subject (added by him in Lab > System) always comes
    owner = [b for b in active if b["section"] == "owner"
             and (not b["text"].startswith('For "') or (words & _words(b["text"])))]
    rest = sorted((b for b in active if b["section"] != "owner"), key=rank, reverse=True)
    picked = (sorted(owner, key=rank, reverse=True)[:max(3, k // 2)] + rest)[:k]
    return picked


def render(bullets: list) -> str:
    if not bullets:
        return ""
    lines = ["Playbook - what has worked before (learned, not rules; cite the ids you used in your final reply):"]
    for b in bullets:
        if not b.get("text"):
            continue
        lines.append("[%s] %s helpful=%d harmful=%d :: %s" % (b["id"], b.get("section", "strategy"), b.get("helpful", 0),
                                                             b.get("harmful", 0), b["text"]))
    return "\n".join(lines)


def used(bullets: list) -> None:
    """Mark the bullets that went into a run (uses / last_used)."""
    by_kind: dict = {}
    for b in bullets:
        by_kind.setdefault(b["id"].split("-")[0], []).append(b["id"])
    with _LOCK:
        for prefix, ids in by_kind.items():
            kind = next((k for k, p in PREFIX.items() if p == prefix), "")
            if not kind:
                continue
            data = load(kind)
            for b in data["bullets"]:
                if b["id"] in ids:
                    b["uses"] += 1
                    b["last_used"] = time.time()
            save(data)


def tag(ids: list, verdict: str, source: str = "") -> int:
    """verdict helpful | harmful for each bullet id; returns how many changed. Retires bullets that keep hurting."""
    if verdict not in ("helpful", "harmful"):
        return 0
    n = 0
    by_prefix: dict = {}
    for i in ids or []:
        by_prefix.setdefault(str(i).split("-")[0], set()).add(str(i))
    with _LOCK:
        for prefix, want in by_prefix.items():
            kind = next((k for k, p in PREFIX.items() if p == prefix), "")
            if not kind:
                continue
            data = load(kind)
            for b in data["bullets"]:
                if b["id"] in want and b["status"] == "active":
                    b[verdict] += 1
                    n += 1
                    if source and source not in b["sources"]:
                        b["sources"] = (b["sources"] + [source])[-12:]
            curate(data)
            save(data)
    return n


def curate(data: dict) -> dict:
    """Deterministic clean-up: retire what keeps hurting, keep the playbook inside MAX_BULLETS."""
    for b in data["bullets"]:
        if b["status"] == "active" and b["section"] != "owner" and b["harmful"] >= 2 and b["harmful"] > b["helpful"] + 1:
            b["status"] = "retired"
            b["retired"] = time.time()
    active = [b for b in data["bullets"] if b["status"] == "active"]
    if len(active) > MAX_BULLETS:
        for b in sorted(active, key=lambda x: (x["section"] == "owner", score(x), x["last_used"]))[:len(active) - MAX_BULLETS]:
            b["status"] = "retired"
            b["retired"] = time.time()
    data["bullets"] = [b for b in data["bullets"] if b["status"] == "active" or time.time() - b.get("retired", 0) < 90 * 86400]
    return data


def apply_ops(kind: str, ops: list, source: str = "", origin: str = "reflect") -> list:
    """The curator: a model's proposed ops, applied by code. ADD {section, text} | UPDATE {id, text} | RETIRE {id}."""
    done = []
    with _LOCK:
        data = load(kind)
        for op in (ops or [])[:6]:
            if not isinstance(op, dict):
                continue
            what = str(op.get("op") or op.get("type") or "").upper()
            if what == "ADD" and str(op.get("text") or "").strip():
                b = _add(data, str(op.get("section") or "strategy"), op["text"], origin=origin, source=source)
                done.append(("ADD", b["id"]))
            elif what in ("UPDATE", "RETIRE"):
                b = next((x for x in data["bullets"] if x["id"] == str(op.get("id") or "")), None)
                if b is None or b["section"] == "owner" and origin != "owner":
                    continue                       # a model never rewrites or retires the owner's own words
                if what == "UPDATE" and str(op.get("text") or "").strip():
                    b["text"] = " ".join(str(op["text"]).split())[:400]
                    done.append(("UPDATE", b["id"]))
                elif what == "RETIRE":
                    b["status"], b["retired"] = "retired", time.time()
                    done.append(("RETIRE", b["id"]))
        curate(data)
        save(data)
    if done:
        trace.event("playbook %s" % kind, "feedback", **{"loki.ops": ["%s %s" % d for d in done]})
    return done


def owner_note(task: str, note: str, kind: str = "", source: str = "", used_ids: list | None = None) -> dict:
    """The owner sent something back with a note: his words become an owner bullet now, and the bullets that run
    used are marked harmful (they did not get it right)."""
    kind = kind or kind_of(task)
    note = " ".join(str(note or "").split())
    if not note:
        return {}
    subject = " ".join(str(task or "").split())[:80]
    text = ("For \"%s\": %s" % (subject, note)) if subject else note
    with _LOCK:
        data = load(kind)
        b = _add(data, "owner", text, origin="owner", source=source)
        curate(data)
        save(data)
    if used_ids:
        tag([i for i in used_ids if i != b["id"]], "harmful", source)
    trace.event("playbook owner note", "feedback", **{"loki.kind": kind, "loki.bullet": b["id"]})
    return b


REFLECT_PROMPT = """You review one finished piece of agent work and propose at most 3 small changes to the playbook for
"%(kind)s" work. The playbook bullets that were used:
%(used)s

The task: %(task)s
What happened: %(outcome)s
%(note)s
Propose only lessons that would help the NEXT similar task (a strategy, a check, or a mistake to avoid), each one short
and concrete. Do not restate existing bullets. Answer with JSON only:
{"ops": [{"op": "ADD", "section": "strategy|check|mistake", "text": "..."}, {"op": "RETIRE", "id": "..."}],
 "helpful": ["ids that clearly helped"], "harmful": ["ids that clearly misled"]}"""


def reflect(task: str, outcome: str, used_bullets: list, ask: Callable[[str], str] | None = None, note: str = "",
            source: str = "") -> dict:
    """After a run (the reflector). Without a model: counters only (verified/approved -> helpful, failed/sent back ->
    harmful). With `ask(prompt) -> text`: also up to 3 new bullets, applied by the curator."""
    kind = kind_of(task)
    ids = [b["id"] for b in used_bullets or []]
    good = outcome in ("verified", "approved", "done")
    bad = outcome in ("failed", "sent_back", "blocked")
    out: dict = {"kind": kind, "tagged": 0, "ops": []}
    if ids and (good or bad):
        out["tagged"] = tag(ids, "helpful" if good else "harmful", source)
    if ask is None or not (good or bad or note):
        return out
    prompt = REFLECT_PROMPT % {"kind": kind, "used": render(used_bullets) or "(none)", "task": str(task)[:1200],
                               "outcome": outcome, "note": ("The owner's note: " + note) if note else ""}
    try:
        raw = ask(prompt) or ""
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except Exception:  # noqa: BLE001 - a bad reflection is just no reflection
        return out
    out["ops"] = apply_ops(kind, data.get("ops") or [], source=source)
    known = set(ids)
    for verdict in ("helpful", "harmful"):
        extra = [i for i in (data.get(verdict) or []) if i in known]
        if extra:
            out["tagged"] += tag(extra, verdict, source)
    return out


def overview() -> dict:
    out = {}
    for kind in PREFIX:
        data = load(kind)
        act = [b for b in data["bullets"] if b["status"] == "active"]
        out[kind] = {"active": len(act), "owner": sum(1 for b in act if b["section"] == "owner"),
                     "retired": sum(1 for b in data["bullets"] if b["status"] == "retired"),
                     "top": [{"id": b["id"], "section": b["section"], "text": b["text"], "helpful": b["helpful"],
                              "harmful": b["harmful"]} for b in sorted(act, key=score, reverse=True)[:6]]}
    return out
