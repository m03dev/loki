"""HTTP routes for the agent system (engine/loki_bridge.py sends every /agentsys/* request here).

GET  /agentsys/status          every layer at a glance: runs, outcomes, tokens, guardrails, playbooks, upstream
GET  /agentsys/traces          ?days=1&trace=<id>: the latest runs, or one run's spans
GET  /agentsys/playbooks       the playbooks per kind of work (top bullets, counts)
GET  /agentsys/upstream        the sources registry with what the last check saw
GET  /agentsys/parked          what the owner parked ("not now")
GET  /agentsys/orchestrations  the delegation runs (ledgers, steps, outcome)
GET  /agentsys/toolbox         every tool with what it does to the world
POST /agentsys/interview       {text, force?} -> the questions with options (or ask:false)
POST /agentsys/brief           {text, answers, questions, note} -> the request with the owner's choices on it
POST /agentsys/sendback        {kind: chat|job|file|text, note, action: send|park, conversation_id?, job_id?, path?, text?}
POST /agentsys/parked/resume   {id, note?} -> the request to run again
POST /agentsys/parked/drop     {id}
POST /agentsys/orchestrate     {goal, conversation_id?} -> starts the delegation loop in the background
POST /agentsys/upstream/check  {limit?} -> checks now, queues For you cards for what is new
POST /agentsys/playbook        {kind, op: add|retire, text?, id?, section?} - the owner edits a playbook himself
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import interview, orchestrator, playbook, runtime, sendback, toolbox, trace, upstream


def _q(path: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}


def _ask_sync(state: Any, budget_s: float = 4.5):
    """A plain model call the interview may use, bounded (never holds the owner up)."""
    agent, loop = getattr(state, "agent", None), getattr(state, "loop", None)
    if agent is None or loop is None or not hasattr(agent, "_port_ask"):
        return None

    def ask(prompt: str) -> str:
        fut = asyncio.run_coroutine_threadsafe(agent._port_ask(prompt, max_tokens=900), loop)  # pylint: disable=protected-access
        try:
            return fut.result(timeout=budget_s)
        except Exception:  # noqa: BLE001
            fut.cancel()
            raise
    return ask


# jobs LOKI has seen the owner ask for, to interview him about (playbook.kind_of on recent work) - names, not rules
JOB_NAMES = {"image": "Concept art", "turnaround": "Turnaround sheets", "3d": "3D models", "video": "Video clips",
             "code": "Coding in LOKI", "marketing": "Marketing posts", "research": "Research", "writing": "Writing",
             "manga": "Manga", "design": "UI and app design", "render": "Renders", "music": "Music",
             "mobile-test": "Testing the phone app"}


def suggested_jobs(state: Any) -> list:
    """The kinds of work in the owner's recent requests that have no playbook yet (most asked first)."""
    from . import playbooks as _pbs  # pylint: disable=import-outside-toplevel
    have = {p["id"] for p in _pbs.everything()} | {_pbs.slug(p["title"]) for p in _pbs.everything()}
    counts: dict = {}
    try:
        for r in trace.runs(14, limit=300):
            k = playbook.kind_of(str(r.get("name") or "") + " " + str(r.get("input") or ""))
            counts[k] = counts.get(k, 0) + 1
    except Exception:  # noqa: BLE001
        pass
    for k in ("image", "turnaround", "3d", "manga", "code", "render"):
        counts.setdefault(k, 0)
    out = [{"kind": k, "title": JOB_NAMES[k], "seen": n} for k, n in sorted(counts.items(), key=lambda x: -x[1])
           if k in JOB_NAMES and _pbs.slug(JOB_NAMES[k]) not in have]
    return out[:8]


def status(state: Any) -> dict:
    st = upstream.load_state()
    counts: dict = {}
    for rec in st.get("repos", {}).values():
        counts[rec.get("status", "?")] = counts.get(rec.get("status", "?"), 0) + 1
    return {"ok": True, "installed": runtime.STATE["installed"], "interview": interview.mode(),
            "traces": trace.summary(7), "playbooks": {k: {kk: v[kk] for kk in ("active", "owner", "retired")}
                                                        for k, v in playbook.overview().items()},
            "orchestrations": orchestrator.recent(8), "parked": len(sendback.parked()),
            "upstream": {"last_run": st.get("last_run", 0), "status": counts,
                         "sources": len(upstream.registry())}}


def _conversation(state: Any, cid: str) -> tuple:
    """(the owner's last request, LOKI's last answer) in one chat."""
    agent = getattr(state, "agent", None)
    msgs = []
    try:
        msgs = agent.conversation_messages(cid) if cid else list(agent.messages)
    except Exception:  # noqa: BLE001
        msgs = []
    last_a = next((m for m in reversed(msgs) if m.get("role") == "assistant" and str(m.get("content") or "").strip()), None)
    idx = msgs.index(last_a) if last_a in msgs else len(msgs)
    last_u = next((m for m in reversed(msgs[:idx]) if m.get("role") == "user" and str(m.get("content") or "").strip()
                   and not str(m.get("content")).startswith(("REVISION ", "<tool_response>"))), None)
    return (str((last_u or {}).get("content") or ""), str((last_a or {}).get("content") or ""))


def sendback_route(state: Any, data: dict) -> tuple:
    kind = str(data.get("kind") or "chat")
    action = str(data.get("action") or "send")
    note = str(data.get("note") or "")
    cid = str(data.get("conversation_id") or "")
    agent = getattr(state, "agent", None)
    original, made, files, bullets, attempt = "", "", [], [], 1
    if kind == "chat":
        original, made = _conversation(state, cid)
        run = runtime.last_run(cid) or runtime.stored_run(cid)
        if run and run.get("reply", "")[:200] == made[:200]:
            bullets = run.get("bullets") or []
        attempt = 1 + sum(1 for m in (agent.conversation_messages(cid) if agent is not None and cid else [])
                          if str(m.get("content") or "").startswith("REVISION ")) if agent is not None else 1
    elif kind == "job":
        jobs = getattr(state, "jobs", None)
        job = jobs.store.get(str(data.get("job_id") or "")) if jobs is not None else None
        if not job:
            return 404, {"ok": False, "error": "no such job"}
        original = str(job.get("prompt") or "")
        try:
            made = Path(getattr(agent, "DATA_DIR", "."), "jobs", job["id"] + ".result.txt").read_text(encoding="utf-8")
        except OSError:
            made = str(job.get("output") or job.get("error") or "")[-4000:]
        if action == "park" and job.get("status") in ("queued", "starting", "working", "blocked"):
            jobs.cancel(job["id"])
    elif kind == "file":
        path = str(data.get("path") or "")
        files = [path] if path else []
        original = str(data.get("text") or "") or "the file %s" % path
    else:
        original = str(data.get("text") or "")
    if action == "park":
        it = sendback.park(kind, original, note=note, made=made, source=cid or str(data.get("job_id") or ""), files=files)
        return 200, {"ok": True, "parked": it["id"]}
    out = sendback.send_back(kind, note, original=original, made=made, files=files, used_bullets=bullets,
                             source=cid or str(data.get("job_id") or ""), attempt=attempt)
    if not out.get("ok"):
        return 400, out
    if kind == "job" and data.get("run", True):
        started = runtime._start_job(out["request"], "Revision: %s" % note[:70],   # pylint: disable=protected-access
                                     cid=str((getattr(state, "jobs", None).store.get(str(data.get("job_id"))) or {})
                                             .get("conversation_id") or "") if getattr(state, "jobs", None) else "")
        out.update(started)
    return 200, out


def route(state: Any, method: str, path: str, data: dict | None = None) -> tuple:
    data = data or {}
    r = urlparse(path).path.rstrip("/")
    q = _q(path)
    try:
        if method == "GET":
            if r == "/agentsys/status":
                return 200, status(state)
            if r == "/agentsys/traces":
                days = max(1, min(14, int(q.get("days") or 1)))
                if q.get("trace"):
                    return 200, {"ok": True, "spans": trace.spans(days, trace=q["trace"])}
                return 200, {"ok": True, "runs": trace.runs(days, limit=int(q.get("limit") or 30))}
            if r == "/agentsys/playbooks":
                if q.get("kind"):
                    return 200, {"ok": True, "playbook": playbook.load(q["kind"])}
                return 200, {"ok": True, "playbooks": playbook.overview()}
            if r == "/agentsys/playbooks/owner":   # the owner's playbooks + toolboxes (agentsys/playbooks.py)
                from . import context as _ctx, playbook_interview, playbooks as _pbs  # pylint: disable=import-outside-toplevel
                if q.get("id"):
                    pb = _pbs.load(q["id"])
                    if not pb:
                        return 404, {"ok": False, "error": "no such playbook"}
                    return 200, {"ok": True, "playbook": pb, "text": _pbs.render(pb)}
                return 200, {"ok": True, "folder": str(_pbs.folder()), "rules": _ctx.owner_rules(),
                             "playbooks": [{k: p[k] for k in ("id", "title", "description", "status", "updated", "triggers")}
                                           | {"steps": len(p["steps"]), "tools": len(p["toolbox"].get("tools") or []),
                                              "files": len(p["toolbox"].get("files") or [])} for p in _pbs.everything()],
                             "interviews": playbook_interview.recent(6), "suggested": suggested_jobs(state)}
            if r == "/agentsys/playbooks/interview":
                from . import playbook_interview  # pylint: disable=import-outside-toplevel
                return 200, {"ok": True, "interview": playbook_interview.session(q.get("id", ""))}
            if r == "/agentsys/upstream":
                st = upstream.load_state()
                reg = upstream.registry()
                return 200, {"ok": True, "last_run": st.get("last_run", 0), "sources": [
                    {**e, "seen": {k: v for k, v in (st["repos"].get(e["repo"].lower()) or {}).items()
                                   if k in ("status", "head", "release", "behind", "checked", "archived", "compare_url")}}
                    for e in reg]}
            if r == "/agentsys/parked":
                return 200, {"ok": True, "parked": sendback.parked()}
            if r == "/agentsys/orchestrations":
                if q.get("id"):
                    p = orchestrator.folder() / ("%s.json" % q["id"])
                    return 200, {"ok": True, "run": json.loads(p.read_text(encoding="utf-8"))}
                return 200, {"ok": True, "runs": orchestrator.recent(int(q.get("limit") or 20))}
            if r == "/agentsys/toolbox":
                return 200, {"ok": True, "tools": toolbox.catalog(getattr(state, "agent", None))}
        if method == "POST":
            if r == "/agentsys/interview":
                text = str(data.get("text") or "")
                return 200, {"ok": True, **interview.make(text, ask=_ask_sync(state), force=bool(data.get("force")),
                                                          followup=bool(data.get("followup")))}
            if r == "/agentsys/brief":
                return 200, {"ok": True, "request": interview.brief(str(data.get("text") or ""), data.get("answers") or {},
                                                                    data.get("questions") or [], str(data.get("note") or "")),
                             "team": runtime._team_choice(data.get("answers") or {}) == "team"}   # pylint: disable=protected-access
            if r == "/agentsys/sendback":
                return sendback_route(state, data)
            if r == "/agentsys/parked/resume":
                out = sendback.resume(str(data.get("id") or ""), str(data.get("note") or ""))
                return (200 if out.get("ok") else 404), out
            if r == "/agentsys/parked/drop":
                out = sendback.drop(str(data.get("id") or ""))
                return (200 if out.get("ok") else 404), out
            if r == "/agentsys/orchestrate":
                goal = str(data.get("goal") or "").strip()
                if not goal:
                    return 400, {"ok": False, "error": "a goal is needed"}
                out = runtime.start_orchestration(goal, str(data.get("conversation_id") or ""))
                return (200 if out.get("ok") else 503), out
            if r == "/agentsys/upstream/check":
                res = upstream.check(limit=int(data["limit"]) if data.get("limit") else None)
                ws = str(getattr(getattr(state, "agent", None), "WORKSPACE", ".") or ".")
                cards = upstream.queue_cards(res["new"], ws)
                return 200, {"ok": True, "checked": res["checked"], "total": res["total"], "new": len(res["new"]),
                             "cards": [c["id"] for c in cards], "token": res["token"]}
            if r.startswith("/agentsys/playbooks/"):   # the owner's playbooks: interview, approve, remove
                from . import playbook_interview, playbooks as _pbs  # pylint: disable=import-outside-toplevel
                agent = getattr(state, "agent", None)
                if r == "/agentsys/playbooks/interview/start":
                    return 200, {"ok": True, "interview": playbook_interview.start(
                        str(data.get("title") or ""), ask=_ask_sync(state, 20), agent=agent)}
                if r == "/agentsys/playbooks/interview/answer":
                    sid = str(data.get("id") or "")
                    final = playbook_interview.session(sid)["step"] >= len(playbook_interview.QUESTIONS) - 1
                    return 200, {"ok": True, "interview": playbook_interview.answer(
                        sid, data.get("picked") or [], str(data.get("text") or ""),
                        ask=_ask_sync(state, 60 if final else 20), agent=agent, back=bool(data.get("back")))}
                if r == "/agentsys/playbooks/approve":
                    pb = _pbs.approve(str(data.get("id") or ""), str(data.get("text") or ""), str(data.get("replaces") or ""))
                    return 200, {"ok": True, "playbook": {"id": pb["id"], "status": pb["status"]}}
                if r == "/agentsys/playbooks/remove":
                    return 200, {"ok": _pbs.remove(str(data.get("id") or ""))}
            if r == "/agentsys/playbook":
                kind = str(data.get("kind") or "general")
                op = str(data.get("op") or "add").upper()
                if op == "ADD":
                    done = playbook.apply_ops(kind, [{"op": "ADD", "section": data.get("section") or "owner",
                                                      "text": data.get("text") or ""}], origin="owner", source="owner")
                else:
                    done = playbook.apply_ops(kind, [{"op": "RETIRE", "id": data.get("id")}], origin="owner")
                return 200, {"ok": bool(done), "done": done}
    except (ValueError, OSError) as exc:
        return 400, {"ok": False, "error": str(exc)[:300]}
    return 404, {"ok": False, "error": "unknown agent-system route"}
