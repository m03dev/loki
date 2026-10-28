"""LOKI interviews the owner to write a playbook (owner 2026-10-28: "LOKI interviews me").

One question at a time, each with options to pick (LOKI's suggestions - what the toolbox has, what is in the Home
library, what a model proposes for this job) AND the owner's own words. Nothing he did not pick or type goes into the
playbook; LOKI's model only suggests options and tidies his answers into the file's sections. At the end the owner
reads the draft and approves it (or edits it first); only an approved playbook is ever used.

    start(title)              -> {sid, question}
    answer(sid, picked, text) -> {question} | {draft}
    session(sid)              -> the whole interview

The questions (the screenshot's parts: workflow - rules, objective, definition of success; toolbox - files, scripts,
data, tools):
    goal      what the job is and what it is for
    done      what a finished result looks like (how he knows it is done)
    steps     how he does it, in order
    rules     always / never
    tools     which of LOKI's tools the job uses
    files     his references, templates, data folders
    apps      apps / scripts
    examples  a good result and what to avoid
Sessions live in <data>/playbook_interviews/<sid>.json.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Callable

from . import playbooks

QUESTIONS = [
    ("goal", "Goal", "What is this job, and what is it for?", False),
    ("done", "Done means", "How do you know it is done? What does a finished result look like?", True),
    ("steps", "Steps", "How do you do it - the steps, in order?", True),
    ("rules", "Rules", "What must always happen, and what must never happen?", True),
    ("tools", "Tools", "Which of LOKI's tools should this job use?", True),
    ("files", "Files", "Which of your files should it use - references, templates, style guides, data folders?", True),
    ("apps", "Apps", "Any apps or scripts it should use?", True),
    ("examples", "Examples", "Show a good result (a file) and say what to avoid.", True),
]
SUGGEST_PROMPT = """You help a game artist write down how HE does a job, so an AI agent can follow it.
Job: %(title)s. What he said so far:
%(so_far)s

Question to him now: %(question)s
Suggest %(n)d short, concrete answers he might pick (each under 14 words, specific to this job, no fluff).
Answer with JSON only: {"options": ["...", "..."]}"""
DRAFT_PROMPT = """Turn the owner's interview answers into his playbook. Use ONLY what he said or picked - add nothing,
change no meaning; just tidy the wording into short lines. Job: %(title)s

His answers:
%(answers)s

Answer with JSON only:
{"description": "one line: when this playbook is used", "triggers": ["3-8 short words or phrases a request about this
 job would contain"], "goal": "...", "done": ["..."], "steps": ["..."], "rules": ["..."], "examples": "..."}"""


def folder() -> Path:
    base = os.environ.get("LOKI_DATA") or str(Path(__file__).resolve().parents[2] / "harness_data")
    d = Path(base) / "playbook_interviews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(sid: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", str(sid or "")):
        raise ValueError("unknown interview")
    return folder() / ("%s.json" % sid)


def _save(s: dict) -> dict:
    s["t"] = time.time()
    _path(s["id"]).write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")
    return s


def session(sid: str) -> dict:
    return json.loads(_path(sid).read_text(encoding="utf-8"))


def recent(limit: int = 10) -> list:
    out = []
    for f in sorted(folder().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": s["id"], "title": s["title"], "step": s["step"], "done": bool(s.get("draft"))})
    return out


# ----------------------------------------------------------------------------- the options LOKI offers
def _tool_options(title: str, agent=None) -> list:
    out = []
    try:
        from . import toolbox  # pylint: disable=import-outside-toplevel
        schemas = list(getattr(agent, "TOOL_SCHEMAS", []) or [])
        names = toolbox.for_task(title, schemas, limit=10) if schemas else []
        desc = {}
        for s in schemas:
            fn = (s or {}).get("function") or {}
            desc[fn.get("name")] = str(fn.get("description") or "").split(". ")[0][:90]
        out = [{"label": n, "description": desc.get(n, "")} for n in names if n]
    except Exception:  # noqa: BLE001
        out = []
    if not out:
        try:
            import make_mcp  # pylint: disable=import-outside-toplevel
            words = playbooks._words(title)  # pylint: disable=protected-access
            ranked = sorted(make_mcp.TOOLS, key=lambda t: -len(words & playbooks._words(  # pylint: disable=protected-access
                t["name"].replace("_", " ") + " " + t.get("description", ""))))
            out = [{"label": t["name"], "description": t.get("description", "").split(". ")[0][:90]} for t in ranked[:8]]
        except Exception:  # noqa: BLE001
            out = []
    return out[:10]


def _file_options() -> list:
    """Folders and recent files in the Home library he might point to."""
    home = playbooks.folder().parent
    out = []
    try:
        for d in sorted(p for p in home.iterdir() if p.is_dir() and not p.name.startswith((".", "trash"))):
            try:
                n = sum(1 for _ in d.iterdir())
            except OSError:
                n = 0
            if n and d.name != "playbooks":
                out.append({"label": d.name + "/", "description": "%d items in your Home library" % n})
    except OSError:
        pass
    return out[:12]


def _app_options() -> list:
    out = []
    try:
        cfg = json.loads((Path(__file__).resolve().parents[1] / "mcp_servers.json").read_text(encoding="utf-8"))
        for name, spec in cfg.get("mcpServers", {}).items():
            note = str(spec.get("note") or "")
            out.append({"label": name, "description": (note.split(". ")[0] if note else "MCP server")[:90]})
    except (OSError, ValueError):
        pass
    return out[:12]


def _model_options(s: dict, key: str, question: str, ask: Callable | None, n: int = 4) -> list:
    if ask is None:
        return []
    so_far = "\n".join("- %s: %s" % (k, _answer_text(v)) for k, v in s["answers"].items()) or "(nothing yet)"
    try:
        raw = ask(SUGGEST_PROMPT % {"title": s["title"], "so_far": so_far, "question": question, "n": n})
        raw = re.sub(r"<think>.*?</think>", "", str(raw or ""), flags=re.S)
        data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        return [{"label": str(o)[:120], "description": "suggested"} for o in data.get("options") or [] if str(o).strip()][:n]
    except Exception:  # noqa: BLE001 - suggestions are a help, never a blocker
        return []


def _question(s: dict, ask: Callable | None, agent=None) -> dict | None:
    if s["step"] >= len(QUESTIONS):
        return None
    key, header, text, multi = QUESTIONS[s["step"]]
    if key == "tools":
        opts = _tool_options(s["title"], agent)
    elif key == "files":
        opts = _file_options()
    elif key == "apps":
        opts = _app_options()
    else:
        opts = _model_options(s, key, text, ask)
    return {"key": key, "header": header, "question": text, "multi": multi, "options": opts,
            "n": s["step"] + 1, "of": len(QUESTIONS),
            "hint": "Pick any that fit and/or write your own (one per line)." if multi else "Write it in your words."}


def _answer_text(a: dict) -> str:
    return "; ".join([*a.get("picked", []), *[x for x in a.get("lines", [])]])


# ----------------------------------------------------------------------------- the flow
def start(title: str, ask: Callable | None = None, agent=None) -> dict:
    title = " ".join(str(title or "").split())[:80]
    if not title:
        raise ValueError("which job? e.g. 'concept art for a game character'")
    s = {"id": uuid.uuid4().hex[:12], "title": title, "step": 0, "answers": {}, "created": time.time(), "draft": None}
    s["question"] = _question(s, ask, agent)
    return _save(s)


def answer(sid: str, picked: list | None = None, text: str = "", ask: Callable | None = None, agent=None,
           back: bool = False) -> dict:
    s = session(sid)
    if back:
        s["step"] = max(0, s["step"] - 1)
        s["question"] = _question(s, ask, agent)
        return _save(s)
    if s["step"] >= len(QUESTIONS):
        return s
    key = QUESTIONS[s["step"]][0]
    lines = [ln.strip(" -*\t") for ln in str(text or "").splitlines() if ln.strip(" -*\t")]
    s["answers"][key] = {"picked": [str(p)[:300] for p in (picked or [])][:20], "lines": lines[:40]}
    s["step"] += 1
    s["question"] = _question(s, ask, agent)
    if s["question"] is None:
        s["draft"] = draft(s, ask)
    return _save(s)


def draft(s: dict, ask: Callable | None = None) -> dict:
    """The playbook from his answers (saved as a draft; used only after he approves it)."""
    a = s["answers"]

    def items(k):
        v = a.get(k) or {}
        return [*v.get("picked", []), *v.get("lines", [])]
    pb = {"id": playbooks.slug(s["title"]), "title": s["title"][:1].upper() + s["title"][1:], "status": "draft",
          "description": "", "triggers": [], "goal": "; ".join(items("goal")), "done": items("done"),
          "steps": items("steps"), "rules": items("rules"), "examples": "; ".join(items("examples")),
          "toolbox": {"tools": items("tools"), "files": items("files"), "scripts": [], "apps": items("apps")}, "notes": []}
    # scripts: anything he wrote under apps that looks like a command
    pb["toolbox"]["scripts"] = [x for x in pb["toolbox"]["apps"] if re.search(r"(^|\s)(python|node|npx|bash|\./|loki-make)\b", x)]
    pb["toolbox"]["apps"] = [x for x in pb["toolbox"]["apps"] if x not in pb["toolbox"]["scripts"]]
    if ask is not None:
        try:
            raw = ask(DRAFT_PROMPT % {"title": s["title"], "answers": "\n".join(
                "%s: %s" % (k, _answer_text(v)) for k, v in a.items())})
            raw = re.sub(r"<think>.*?</think>", "", str(raw or ""), flags=re.S)
            d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
            for k in ("goal", "examples", "description"):
                if str(d.get(k) or "").strip():
                    pb[k] = str(d[k]).strip()[:600]
            for k in ("done", "steps", "rules"):
                if isinstance(d.get(k), list) and d[k] and len(d[k]) <= 3 * max(1, len(pb[k])) + 3:
                    pb[k] = [str(x).strip()[:300] for x in d[k] if str(x).strip()]
            if isinstance(d.get("triggers"), list):
                pb["triggers"] = [str(x).strip().lower()[:40] for x in d["triggers"] if str(x).strip()][:8]
        except Exception:  # noqa: BLE001 - his answers as they are
            pass
    if not pb["description"]:
        pb["description"] = "How the owner does %s" % s["title"].lower()
    if not pb["triggers"]:
        pb["triggers"] = [s["title"].lower()] + sorted(playbooks._words(s["title"]))[:4]  # pylint: disable=protected-access
    existing = playbooks.load(pb["id"])
    if existing and existing.get("status") == "approved":   # a re-interview never replaces the approved one silently
        pb["id"] = playbooks.slug(pb["id"] + "-new")
    playbooks.save(pb)
    return {"id": pb["id"], "text": playbooks.render(pb), "replaces": existing["id"] if existing else ""}
