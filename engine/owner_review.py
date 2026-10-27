"""The owner signs off: no agent draws a picture without the owner's OK on its prompt, and no hand-off goes on until the
owner has seen it (owner 2026-10-27: "i never get prompted before they make an image i should be overseeing the prompt
and the images gen like check off should come through my eyes once i should see the hands offs ... focus on the
specific agents and their skills first").

Two kinds of item wait in Home > For you:

    prompt   an agent wants to draw: who asks (Concept Artist, Technical Artist, an agent's job), the tool and its
             prompt. The owner approves it as it is, edits the words first, or says no. Approved: LOKI draws it
             itself (no agent and no model needed for that) and the result comes back as a ...
    result   pictures / models / renders with the hand-off notes (what was checked). Approve: it goes on (a pipeline
             stage is approved and the next agent gets it). Retake with a note: a new prompt card comes back with the
             old prompt and the note, for the owner to fix and approve - nothing is redrawn on its own.

Asset-pipeline items (engine/asset_pipeline.py) carry asset + stage; the pipeline itself waits on them (status
"owner"). Everything else (an agent's make_image in a job or a chat) is gated in make_mcp.call: the agent is told the
prompt waits for the owner and stops - its task shows "waits for you", not a failure, and is never retried into
duplicates (the same prompt is one card).

Storage: <data>/review/<id>.json, one file per item (the engine, every job process and the MCP servers share it).
LOKI_OWNER_REVIEW=off turns the gate off (the test suites run with it off unless they test it).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

GATED_TOOLS = ("make_image", "make_turnaround", "make_sprite")   # every picture an agent makes (owner's choice)
MARK = "WAITING FOR THE OWNER"
OWNER_OK = "_owner_ok"           # set by LOKI after the owner approved: the call goes through
KINDS = ("prompt", "result")
OPEN = ("waiting", "working")    # waiting = the owner's turn; working = LOKI is drawing what was approved
_LOCK = threading.Lock()


def on() -> bool:
    return str(os.environ.get("LOKI_OWNER_REVIEW", "on")).strip().lower() not in ("0", "off", "false", "no")


def data_dir() -> Path:
    return Path(os.environ.get("LOKI_DATA") or (Path(__file__).resolve().parent.parent / "harness_data"))


def folder() -> Path:
    d = data_dir() / "review"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(item_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]{6,32}", str(item_id or "")):
        raise ValueError("unknown review item")
    return folder() / ("%s.json" % item_id)


def _save(item: dict) -> dict:
    p = _path(item["id"])
    tmp = p.with_suffix(".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(item, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return item


def get(item_id: str) -> dict | None:
    try:
        return json.loads(_path(item_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def items(status: tuple | None = None, limit: int = 200) -> list:
    out = []
    for p in folder().glob("*.json"):
        try:
            it = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if status is None or it.get("status") in status:
            out.append(it)
    out.sort(key=lambda it: float(it.get("t") or 0))
    return out[-limit:]


def waiting() -> list:
    """What is the owner's turn, oldest first (what is being drawn after an OK is listed too)."""
    return items(OPEN)


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def who_from_env() -> str:
    """Who is asking, for a call that is not the pipeline: the job's title, else the chat."""
    title = os.environ.get("LOKI_JOB_TITLE", "").strip()
    if title:
        return "Agent: " + title[:80]
    return "Agent (job %s)" % os.environ["LOKI_JOB_ID"] if os.environ.get("LOKI_JOB_ID") else "LOKI (chat)"


def queue(kind: str, tool: str, args: dict, cwd: str, who: str = "", asset: str = "", stage: str = "",
          files: list | None = None, handoff: str = "", note: str = "", parent: str = "") -> dict:
    """Add an item for the owner. The same open prompt (same tool, words, folder, asset/stage) is ONE card: a retried
    job or a second call finds the card that is already there."""
    if kind not in KINDS:
        raise ValueError("kind is prompt or result")
    args = {k: v for k, v in dict(args or {}).items() if k != OWNER_OK}
    with _LOCK:
        if kind == "prompt":
            key = (tool, _norm(args.get("prompt") or args.get("subject") or ""), str(cwd), asset, stage)
            for it in items(OPEN):
                if it["kind"] == "prompt" and (it["tool"], _norm(it["args"].get("prompt") or it["args"].get("subject")
                                                                  or ""), it["cwd"], it.get("asset", ""),
                                               it.get("stage", "")) == key:
                    return it
            if asset and stage:          # one open card per pipeline stage
                for it in items(OPEN):
                    if it.get("asset") == asset and it.get("stage") == stage and it["kind"] == "prompt":
                        return it
        item = {"id": uuid.uuid4().hex[:12], "kind": kind, "status": "waiting", "t": time.time(), "tool": tool,
                "args": args, "cwd": str(cwd), "who": who or who_from_env(), "asset": asset, "stage": stage,
                "files": [str(f) for f in (files or [])], "handoff": str(handoff or "")[:4000],
                "note": str(note or "")[:800], "parent": parent, "job": os.environ.get("LOKI_JOB_ID", "")}
        return _save(item)


def waiting_for_jobs(job_ids) -> list:
    """Open prompt cards a set of jobs left for the owner (a task that waits for you is not a failed task)."""
    ids = {str(j) for j in (job_ids or []) if j}
    return [it for it in items(OPEN) if it.get("job") in ids] if ids else []


def gate(tool: str, args: dict, cwd) -> dict | None:
    """make_mcp.call asks this first. None = go ahead; else the answer the agent gets instead of a picture."""
    if tool not in GATED_TOOLS or not on() or (args or {}).get(OWNER_OK):
        return None
    it = queue("prompt", tool, args or {}, str(cwd))
    words = str((args or {}).get("prompt") or (args or {}).get("subject") or "")[:200]
    return {"ok": False, "waiting_for_owner": True, "review": it["id"],
            "error": "%s: your %s prompt (%r) is in Home > For you. The owner approves or edits it, then LOKI draws it "
                     "and shows them the result - do NOT draw it another way or call this again. Stop here and say "
                     "the picture waits for the owner's OK." % (MARK, tool, words)}


# ----------------------------------------------------------------------------- the owner's decisions
def decide(item_id: str, action: str, prompt: str = "", note: str = "", ws=None,
           runner: Callable[[dict], None] | None = None) -> dict:
    """approve | reject (a prompt) ; approve | retake (a result). Returns the item. `runner(item)` draws an approved
    non-pipeline prompt (in the background in the engine); pipeline items go back to the pipeline."""
    it = get(item_id)
    if it is None:
        return {"ok": False, "error": "that card is gone"}
    if it["status"] not in OPEN:
        return {"ok": False, "error": "already %s" % it["status"], "item": it}
    action = str(action or "").lower()
    if it["kind"] == "prompt":
        if action not in ("approve", "reject"):
            return {"ok": False, "error": "a prompt is approved or rejected"}
        if action == "reject":
            it.update(status="rejected", decided=time.time(), note=note[:800])
            _save(it)
            if it.get("asset") and ws is not None:
                _pipeline().owner_prompt(Path(ws), it["asset"], it["stage"], ok=False, note=note)
            return {"ok": True, "item": it}
        words = " ".join(str(prompt or "").split())
        if words:
            key = "prompt" if "prompt" in it["args"] or it["tool"] == "make_image" else "subject"
            if words != " ".join(str(it["args"].get(key) or "").split()):
                it["edited_from"] = it["args"].get(key, "")
                it["args"][key] = words[:1800]
        it.update(status="working" if not it.get("asset") else "approved", decided=time.time())
        _save(it)
        if it.get("asset") and ws is not None:
            _pipeline().owner_prompt(Path(ws), it["asset"], it["stage"], ok=True, args=it["args"])
        elif runner is not None:
            runner(it)
        return {"ok": True, "item": it}
    if action not in ("approve", "retake"):
        return {"ok": False, "error": "a result is approved or sent back (retake)"}
    it.update(status="approved" if action == "approve" else "retake", decided=time.time(), note=note[:800])
    _save(it)
    if it.get("asset") and ws is not None:
        _pipeline().owner_result(Path(ws), it["asset"], it["stage"], ok=action == "approve", note=note)
    elif action == "retake":
        # the old prompt + the note comes back as a new card; nothing is redrawn until the owner approves it
        src = get(it.get("parent") or "") or {}
        args = dict(src.get("args") or it.get("args") or {})
        if note:
            args["prompt"] = ("%s. Owner's note: %s" % (str(args.get("prompt") or "").rstrip(". "), note))[:1800]
        queue("prompt", it["tool"], args, it["cwd"], who=it["who"], note=note, parent=it["id"])
        _feedback(it, note)
    return {"ok": True, "item": it}


def _pipeline():
    import asset_pipeline  # pylint: disable=import-outside-toplevel
    return asset_pipeline


def _feedback(it: dict, note: str) -> None:
    """A sent-back picture teaches the next prompts (engine/image_feedback.py), like a thumbs-down."""
    try:
        import image_feedback  # pylint: disable=import-outside-toplevel
        ws = Path(it["cwd"])
        for f in it.get("files") or []:
            rel = os.path.relpath(f, ws) if Path(f).is_absolute() else f
            image_feedback.rate(ws, rel, -1, note=note or "the owner sent it back", pipeline=False)
    except Exception:  # noqa: BLE001 - feedback is a nicety
        pass


def draw(it: dict, call: Callable[[str, dict, Path], dict] | None = None) -> dict:
    """Run an approved prompt card and put the result in front of the owner."""
    if call is None:
        import make_mcp  # pylint: disable=import-outside-toplevel
        call = make_mcp.call
    args = dict(it["args"], **{OWNER_OK: True})
    try:
        res = call(it["tool"], args, Path(it["cwd"])) or {}
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    files = res.get("files") or ([res["file"]] if res.get("file") else [])
    if isinstance(files, dict):
        files = list(files.get("views", {}).values()) if files.get("views") else list(files.values())
    if not res.get("ok") or not files:
        it.update(status="failed", error=str(res.get("error") or "nothing was made")[:400], finished=time.time())
        _save(it)
        return it
    lines = ["Made by %s with %s." % (res.get("backend") or "LOKI", it["tool"]),
             "Prompt: %s" % str(it["args"].get("prompt") or it["args"].get("subject") or "")[:600]]
    if it.get("edited_from"):
        lines.append("You edited it from: %s" % str(it["edited_from"])[:300])
    result = queue("result", it["tool"], it["args"], it["cwd"], who=it["who"], files=[str(f) for f in files],
                   handoff="\n".join(lines), parent=it["id"])
    it.update(status="done", result=result["id"], finished=time.time())
    _save(it)
    return it


def run_in_background(it: dict) -> None:
    threading.Thread(target=draw, args=(it,), daemon=True, name="owner-review-" + it["id"]).start()


def summary() -> dict:
    w = waiting()
    return {"waiting": sum(1 for it in w if it["status"] == "waiting"),
            "prompts": sum(1 for it in w if it["kind"] == "prompt" and it["status"] == "waiting"),
            "results": sum(1 for it in w if it["kind"] == "result" and it["status"] == "waiting"),
            "drawing": sum(1 for it in w if it["status"] == "working")}


# ----------------------------------------------------------------------------- the engine's routes
def route(state: Any, method: str, route_: str, q: dict, data: dict) -> tuple:
    """GET /review (what waits for the owner + the last decisions), POST /review/decide {id, action, prompt?, note?}."""
    ws = Path(getattr(getattr(state, "agent", None), "WORKSPACE", "") or ".")
    if (method, route_) == ("GET", "/review"):
        recent = [it for it in items(("approved", "rejected", "retake", "done", "failed"))][-20:]
        return 200, {"ok": True, "on": on(), "waiting": waiting(), "recent": recent[::-1], "summary": summary(),
                     "workspace": str(ws)}
    if (method, route_) == ("POST", "/review/decide"):
        out = decide(str(data.get("id") or ""), str(data.get("action") or ""), str(data.get("prompt") or ""),
                     str(data.get("note") or ""), ws=ws, runner=run_in_background)
        if out.get("ok") and (out.get("item") or {}).get("asset"):
            try:   # the pipeline goes on now, not at the autopilot's next pass
                threading.Thread(target=_pipeline().tick, args=(ws,), daemon=True, name="pipeline-after-review").start()
            except Exception:  # noqa: BLE001
                pass
        return (200 if out.get("ok") else 400), out
    return 404, {"ok": False, "error": "unknown review route"}
