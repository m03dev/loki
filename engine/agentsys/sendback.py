"""Send it back, or park it: the owner's say over ANY result, not only pictures (owner 2026-10-28: "there needs to also be a
way for me to not want something made right now i just send it back with a prompt").

Two actions on anything LOKI made - a chat reply, a background job, a file, a For you result:

  send back   with a note ("the lighting is flat, make it night"). The note becomes a revision request that carries
              the original request, what was made and exactly what to change (evaluator-optimizer, with the owner
              as the evaluator); the note also goes into the playbook as the owner's own bullet, and the bullets that
              run used are marked harmful - so the next similar task starts from his words.
  park        "not now": the work stops (a running job is cancelled) and its request is kept in Parked, to resume
              later with one click (and an optional note). Nothing is lost, nothing is redrawn on its own.

How the revision is phrased follows what made send-backs work elsewhere: Claude Code's denied-tool message (the model
reads the reason and adapts), LangGraph's human-edits-state-then-replan, Cognition's lesson that review notes must be
held against the owner's instructions (do what he said, not more). Storage: <data>/parked/<id>.json.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from . import playbook, sub, trace

KINDS = ("chat", "job", "file", "review", "text")


def revision_request(original: str, made: str, note: str, files: list | None = None, attempt: int = 1) -> str:
    """The request the agent gets when the owner sends something back."""
    files = [f for f in (files or []) if f][:12]
    made = str(made or "").strip()
    if len(made) > 2500:
        made = made[:2500] + " …"
    parts = ["REVISION %d - the owner sent the last result back." % max(1, attempt),
             "What the owner said is wrong / wants changed (this is the instruction - do exactly this, nothing else "
             "extra): %s" % " ".join(str(note or "").split())[:1500]]
    if original:
        parts.append("The original request: %s" % " ".join(str(original).split())[:2500])
    if files:
        parts.append("What was made (look at it before you change it): %s" % ", ".join(files))
    if made:
        parts.append("The previous answer:\n<<<\n%s\n>>>" % made)
    parts.append("Keep what was right, change what he named, then show the new result. If the note is unclear, ask "
                 "him one short question instead of guessing.")
    return "\n\n".join(parts)


_PATHS = re.compile(r"(?<![\w@:.-])((?:[\w.-]+[/\\])+[\w.-]+\.(?:png|jpe?g|webp|gif|mp4|webm|glb|gltf|obj|fbx|blend|"
                    r"wav|mp3|md|py|js|html|json|txt|pdf))\b", re.I)


def files_in(text: str) -> list:
    return sorted({m.group(1) for m in _PATHS.finditer(str(text or ""))})[:20]


def send_back(kind: str, note: str, original: str = "", made: str = "", files: list | None = None,
              used_bullets: list | None = None, source: str = "", attempt: int = 1) -> dict:
    """Returns {"ok", "request": the revision request, "bullet": the owner bullet}. The caller runs the request where
    the result came from (the same chat, a new job for a job)."""
    note = " ".join(str(note or "").split())
    if not note:
        return {"ok": False, "error": "say what to change - the note is the instruction"}
    if kind not in KINDS:
        return {"ok": False, "error": "unknown kind %r" % kind}
    files = list(files or []) or files_in(made)
    request = revision_request(original, made, note, files, attempt)
    bullet = playbook.owner_note(original or made or note, note, source=source,
                                 used_ids=[b["id"] if isinstance(b, dict) else str(b) for b in used_bullets or []])
    trace.event("send back", "feedback", **{"loki.kind": kind, "loki.note": note, "loki.attempt": attempt})
    return {"ok": True, "request": request, "bullet": (bullet or {}).get("id", ""), "files": files}


# ----------------------------------------------------------------------------- park ("not now")
def folder() -> Path:
    return sub("parked")


def park(kind: str, request: str, note: str = "", made: str = "", source: str = "", who: str = "",
         files: list | None = None) -> dict:
    item = {"id": uuid.uuid4().hex[:12], "kind": kind if kind in KINDS else "text", "request": str(request or "")[:8000],
            "note": " ".join(str(note or "").split())[:1000], "made": str(made or "")[:4000], "source": source,
            "who": who or "", "files": list(files or [])[:20], "t": time.time(), "status": "parked"}
    p = folder() / ("%s.json" % item["id"])
    tmp = p.with_suffix(".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(item, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    trace.event("park", "feedback", **{"loki.kind": kind, "loki.source": source})
    return item


def parked(limit: int = 50) -> list:
    out = []
    for p in folder().glob("*.json"):
        try:
            it = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if it.get("status") == "parked":
            out.append(it)
    out.sort(key=lambda x: -float(x.get("t") or 0))
    return out[:limit]


def _load(item_id: str) -> dict | None:
    if not re.fullmatch(r"[a-f0-9]{12}", str(item_id or "")):
        return None
    try:
        return json.loads((folder() / ("%s.json" % item_id)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def resume(item_id: str, note: str = "") -> dict:
    """Take a parked item back out: returns the request to run (with the new note on it, if any)."""
    it = _load(item_id)
    if not it or it.get("status") != "parked":
        return {"ok": False, "error": "that parked item is gone"}
    request = it["request"]
    extra = " ".join(str(note or "").split())
    if extra:
        request = revision_request(it["request"], it.get("made", ""), extra, it.get("files"))
    elif it.get("note"):
        request = "%s\n\n(When the owner parked this he said: %s)" % (request, it["note"])
    it.update(status="resumed", resumed=time.time())
    (folder() / ("%s.json" % it["id"])).write_text(json.dumps(it, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "request": request, "item": it}


def drop(item_id: str) -> dict:
    it = _load(item_id)
    if not it:
        return {"ok": False, "error": "that parked item is gone"}
    it.update(status="dropped", dropped=time.time())
    (folder() / ("%s.json" % it["id"])).write_text(json.dumps(it, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}
