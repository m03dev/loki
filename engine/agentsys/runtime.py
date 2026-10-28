"""The chassis: LOKI's agent system put around every harness.

`install(loki)` runs once when engine/loki.py loads (in the engine AND in every background-job process), so the same
layers wrap whatever does the work:

    run_opencode   (the window's chat, Build tasks and background jobs: OpenCode, DeepSeek Harness, the CLI harnesses,
                   the local shell agent)  -> context preamble (memory pack + playbook bullets), a trace of the run,
                   the output guardrail, learning after the request (memory.after_request)
    run_agent / pursue_goal (LOKI's own loop, LOKI_AGENT_ENGINE=loki) -> trace + outcome
    call_tool      (LOKI's own loop) -> a span per tool, outside text spotlighted as data
    _model_request -> a span per model call with its tokens

Before this the memory, lessons and checks only ran in LOKI's own loop, so on the default path (OpenCode) none of
them did (docs/AGENT_SYSTEM.md "Why"). `attach(state)` (the bridge, at start) adds the parts that need the engine:
the For you handlers for interview and upstream cards and the orchestrator's background runs.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import context, guardrails, hooks, interview, orchestrator, playbook, sendback, toolbox, trace, upstream

STATE: dict = {"agent": None, "state": None, "installed": False, "last": {}, "orchestrations": {}}
_DEPTH = contextvars.ContextVar("agentsys_depth", default=0)   # per task, not per thread (the engine is one loop)


def _agent():
    return STATE["agent"]


def _conv_id(agent: Any) -> str:
    try:
        return str(agent.active_conversation_id() or "")
    except Exception:  # noqa: BLE001
        return ""


def _is_local(agent: Any) -> bool:
    try:
        return bool(agent._cfg_is_local(agent.MODELS[agent.active_model_name()]))   # pylint: disable=protected-access
    except Exception:  # noqa: BLE001
        return False


def _request_text(text: str) -> str:
    """The owner's own words inside a wrapped job prompt (a background chat message carries the chat so far)."""
    m = re.search(r"The owner's new message \(answer it as the chat's next reply\):\n(.*)$", str(text or ""), re.S)
    return (m.group(1) if m else str(text or "")).strip()


def last_run(conversation_id: str = "") -> dict:
    return dict(STATE["last"].get(conversation_id or "", {}) or STATE["last"].get("", {}) or {})


def _remember_run(cid: str, rec: dict) -> None:
    STATE["last"][cid or ""] = rec
    STATE["last"][""] = rec
    try:   # the job processes are separate: the engine reads it from here for a send-back
        p = Path(sub_path("runs")) / ("%s.json" % (re.sub(r"[^A-Za-z0-9_-]", "", cid) or "_last"))
        p.write_text(json.dumps(rec, ensure_ascii=False)[:200000], encoding="utf-8")
    except OSError:
        pass


def sub_path(name: str) -> str:
    from . import sub  # pylint: disable=import-outside-toplevel
    return str(sub(name))


def stored_run(cid: str) -> dict:
    try:
        return json.loads((Path(sub_path("runs")) / ("%s.json" % (re.sub(r"[^A-Za-z0-9_-]", "", cid) or "_last")))
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ----------------------------------------------------------------------------- the wrappers
def _wrap_harness(agent: Any, name: str) -> None:
    orig = getattr(agent, name, None)
    if orig is None or getattr(orig, "_agentsys", False):
        return

    async def wrapped(text: str, task: bool = False, allow_bash: bool = True, preamble: str = ""):
        if _DEPTH.get() > 0:          # a harness falling back to another one: wrap once
            return await orig(text, task=task, allow_bash=allow_bash, preamble=preamble)
        token = _DEPTH.set(1)
        cid = _conv_id(agent)
        ask = _request_text(text)
        start = len(getattr(agent, "messages", []) or [])
        ctx = {"text": "", "bullets": [], "memory": []}
        try:
            ctx = context.build(ask, agent, local=_is_local(agent))
        except Exception:  # noqa: BLE001 - a request without the extra context still runs
            pass
        hk = hooks.run("before_request", {"text": ask, "task": task, "conversation_id": cid,
                                          "kind": playbook.kind_of(ask)})
        if hk.get("decision") == "deny":
            _DEPTH.reset(token)
            return "NOT DONE - %s" % (hk.get("reason") or "a check stopped this request")
        pre = "\n\n".join(x for x in (preamble, ctx["text"], hk.get("preamble_extra", "")) if x)
        attrs = {"gen_ai.agent.name": "LOKI", "loki.harness": _harness(agent), "loki.kind": playbook.kind_of(ask),
                 "loki.task": bool(task), "loki.job": os.environ.get("LOKI_JOB_ID", ""),
                 "gen_ai.conversation.id": cid, "loki.preamble_chars": len(pre),
                 "loki.bullets": [b["id"] for b in ctx["bullets"]]}
        try:
            attrs["gen_ai.request.model"] = agent.active_model_name()
        except Exception:  # noqa: BLE001
            pass
        reply = ""
        try:
            with trace.span("invoke_agent LOKI", "agent", **attrs) as sp:
                reply = await orig(text, task=task, allow_bash=allow_bash, preamble=pre)
                reply = _after(agent, ask, reply, sp, ctx, cid, task)
                after = hooks.run("after_request", {"text": ask, "reply": str(reply or ""), "trace_id": sp.trace_id,
                                                    "conversation_id": cid})
                if isinstance(after.get("reply"), str):
                    reply = after["reply"]
        finally:
            _DEPTH.reset(token)
            _learn_later(agent, start)
        return reply
    wrapped._agentsys = True       # noqa: SLF001
    wrapped.__wrapped__ = orig
    setattr(agent, name, wrapped)


def _harness(agent: Any) -> str:
    try:
        return str(agent.opencode_engine.engine_choice())
    except Exception:  # noqa: BLE001
        return "loki"


def _after(agent: Any, ask: str, reply: Any, sp: trace.Span, ctx: dict, cid: str, task: bool) -> Any:
    text = str(reply or "")
    try:
        ok_calls = int(getattr(agent, "_task_ok_calls", -1))
    except (TypeError, ValueError):
        ok_calls = -1
    v = guardrails.output_check(text, getattr(agent, "WORKSPACE", None), tool_calls=ok_calls,
                                roots=[getattr(agent, "REPO_ROOT", None), getattr(agent, "DATA_DIR", None)])
    if v.action == guardrails.NOTE and v.check == "output.missing_files" and text:
        reply = text + "\n\n(LOKI check: %s - this is not shown as done.)" % v.reason
    outcome = "answered"
    try:
        o = agent.reply_outcome(text)
        outcome = {"DONE": "done", "BLOCKED": "blocked"}.get(str(o).upper(), outcome)
    except Exception:  # noqa: BLE001
        pass
    if text.lstrip().startswith("NOT DONE"):
        outcome = "not_done"
    if v.action != guardrails.OK:
        outcome = "unverified" if outcome in ("done", "answered") and v.check != "output.unbacked" else outcome
    sp.set(**{"loki.outcome": outcome, "loki.guardrail": v.check or "ok"})
    try:
        playbook.used(ctx["bullets"])
        if outcome == "done" and v.action == guardrails.OK and task:
            playbook.tag([b["id"] for b in ctx["bullets"]], "helpful", sp.trace_id)
    except Exception:  # noqa: BLE001
        pass
    _remember_run(cid, {"request": ask, "reply": text[:12000], "bullets": [b["id"] for b in ctx["bullets"]],
                        "trace_id": sp.trace_id, "files": sendback.files_in(text), "t": time.time(),
                        "outcome": outcome, "job": os.environ.get("LOKI_JOB_ID", "")})
    return reply


def _learn_later(agent: Any, start: int) -> None:
    """What the owner said in this request that is worth keeping (memory.after_request) - off the request's path."""
    try:
        msgs = [m for m in list(getattr(agent, "messages", []) or [])[start:] if isinstance(m, dict)]
    except Exception:  # noqa: BLE001
        return
    if not msgs:
        return

    def go() -> None:
        try:
            import memory  # pylint: disable=import-outside-toplevel
            memory.after_request(msgs, "done", root=getattr(agent, "DATA_DIR", None))
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=go, daemon=True, name="agentsys-learn").start()


def _wrap_loop(agent: Any, name: str) -> None:
    orig = getattr(agent, name, None)
    if orig is None or getattr(orig, "_agentsys", False):
        return

    async def wrapped(*args, **kwargs):
        text = str(args[0] if args else kwargs.get("user_message") or kwargs.get("goal") or "")
        with trace.span("invoke_agent LOKI (own loop)", "agent", **{"gen_ai.agent.name": "LOKI", "loki.harness": "loki",
                                                                     "loki.kind": playbook.kind_of(text),
                                                                     "gen_ai.conversation.id": _conv_id(agent)}) as sp:
            reply = await orig(*args, **kwargs)
            try:
                o = agent.reply_outcome(str(reply or ""))
            except Exception:  # noqa: BLE001
                o = ""
            sp.set(**{"loki.outcome": {"DONE": "done", "BLOCKED": "blocked"}.get(str(o).upper(), "answered")})
            _remember_run(_conv_id(agent), {"request": text, "reply": str(reply or "")[:12000], "bullets": [],
                                            "trace_id": sp.trace_id, "files": sendback.files_in(str(reply or "")),
                                            "t": time.time()})
            return reply
    wrapped._agentsys = True       # noqa: SLF001
    setattr(agent, name, wrapped)


def _wrap_tools(agent: Any) -> None:
    orig = getattr(agent, "call_tool", None)
    if orig is None or getattr(orig, "_agentsys", False):
        return

    async def call_tool(name: str, args: dict) -> str:
        with trace.span("execute_tool %s" % name, "tool", **{"gen_ai.tool.name": name}) as sp:
            pre = hooks.run("before_tool", {"name": name, "args": args, "facts": toolbox.facts(name, agent)})
            if pre.get("decision") == "deny":
                sp.fail(pre.get("reason", "denied"), "denied")
                return "refused: %s" % (pre.get("reason") or "a check stopped this call")
            if isinstance(pre.get("args"), dict):
                args = pre["args"]
            result = await orig(name, args)
            post = hooks.run("after_tool", {"name": name, "args": args, "result": result if isinstance(result, str) else str(result)})
            if isinstance(post.get("result"), str):
                result = post["result"]
            text = result if isinstance(result, str) else str(result)
            if re.match(r"\s*(error|refused|denied|failed)\b", text[:40], re.I):
                sp.status = "error"
                sp.set(**{"error.type": "tool_error", "error.message": text[:200]})
            fenced, _v = guardrails.spotlight(name, text)
            return fenced if isinstance(result, str) else result
    call_tool._agentsys = True     # noqa: SLF001
    agent.call_tool = call_tool


def _wrap_model(agent: Any) -> None:
    orig = getattr(agent, "_model_request", None)
    if orig is None or getattr(orig, "_agentsys", False):
        return

    async def _model_request(client, kwargs: dict, cfg, provider: str = ""):
        with trace.span("chat %s" % (getattr(cfg, "model", "") or provider), "llm",
                        **{"gen_ai.request.model": getattr(cfg, "model", ""), "loki.provider": provider,
                           "gen_ai.request.max_tokens": (kwargs or {}).get("max_tokens", 0)}) as sp:
            response = await orig(client, kwargs, cfg, provider)
            try:
                u = getattr(response, "usage", None)
                sp.set(**{"gen_ai.usage.input_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
                          "gen_ai.usage.output_tokens": int(getattr(u, "completion_tokens", 0) or 0),
                          "gen_ai.response.finish_reasons": [getattr(c, "finish_reason", "") for c in
                                                             (getattr(response, "choices", None) or [])][:4]})
            except Exception:  # noqa: BLE001
                pass
            return response
    _model_request._agentsys = True   # noqa: SLF001
    agent._model_request = _model_request   # pylint: disable=protected-access


def install(agent: Any) -> bool:
    if STATE["installed"] or agent is None:
        return STATE["installed"]
    STATE["agent"] = agent
    for name in ("run_opencode",):
        _wrap_harness(agent, name)
    for name in ("run_agent", "pursue_goal"):
        _wrap_loop(agent, name)
    _wrap_tools(agent)
    _wrap_model(agent)
    STATE["installed"] = True
    return True


# ----------------------------------------------------------------------------- the engine side (bridge)
def attach(state: Any) -> None:
    STATE["state"] = state
    try:
        import owner_review  # pylint: disable=import-outside-toplevel
        owner_review.HANDLERS["question"] = _decide_question
        owner_review.HANDLERS["upstream"] = _decide_upstream
    except Exception:  # noqa: BLE001
        pass
    try:
        trace.prune()
    except Exception:  # noqa: BLE001
        pass


def _start_job(prompt: str, title: str, cid: str = "", profile: dict | None = None) -> dict:
    agent, state = _agent(), STATE["state"]
    jobs = getattr(state, "jobs", None) or getattr(agent, "JOBS", None)
    if jobs is None:
        return {"ok": False, "error": "background jobs are not running"}
    spec = {"backend": "local", "agent": "loki", "prompt": prompt, "title": title[:80], "isolate": False,
            "timeout_s": 3600, "allow_commands": True, "workspace": str(getattr(agent, "WORKSPACE", "") or ""),
            "profile": profile or {}}
    if cid:
        spec["conversation_id"] = cid
        try:
            agent.append_to_conversation(cid, "user", title)
        except Exception:  # noqa: BLE001
            pass
    try:
        job = jobs.create(spec)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    threading.Thread(target=jobs.tick, daemon=True).start()
    return {"ok": True, "job": job["id"]}


def _decide_question(item: dict, action: str, data: dict) -> dict:
    """A parked interview: answer -> the brief runs as a job; go -> as written; park -> Parked."""
    args = item.get("args") or {}
    text = str(args.get("text") or "")
    if action in ("park", "not_now"):
        sendback.park("text", text, note=data.get("note", ""), source="question:" + item["id"], who=item.get("who", ""))
        return {"ok": True, "status": "parked"}
    if action not in ("answer", "go", "approve"):
        return {"ok": False, "error": "answer, go or park"}
    answers = data.get("answers") if action == "answer" else {}
    request = interview.brief(text, answers if isinstance(answers, dict) else {}, args.get("questions"), data.get("note", ""))
    who = _team_choice(answers)
    if who == "team":
        out = start_orchestration(request)
    else:
        out = _start_job(request, text.splitlines()[0][:80] if text else "LOKI")
    return {"ok": bool(out.get("ok")), "status": "answered", "answer": answers, **out}


def _decide_upstream(item: dict, action: str, data: dict) -> dict:
    args = item.get("args") or {}
    if action == "skip":
        upstream.skip(args.get("repo", ""), args.get("mark", ""))
        return {"ok": True, "status": "skipped"}
    if action in ("park", "not_now"):
        sendback.park("text", args.get("prompt", ""), note=data.get("note", ""), source="upstream:" + args.get("repo", ""),
                      who="Upstream check")
        return {"ok": True, "status": "parked"}
    if action not in ("adopt", "approve"):
        return {"ok": False, "error": "adopt, skip or park"}
    prompt = str(args.get("prompt") or "")
    if data.get("note"):
        prompt += "\n\nThe owner adds: " + str(data["note"])[:800]
    out = _start_job(prompt, "Upstream: adopt %s" % args.get("repo", ""))
    return {"ok": bool(out.get("ok")), "status": "adopted", **out}


def _team_choice(answers: Any) -> str:
    if not isinstance(answers, dict):
        return ""
    for k, v in answers.items():
        val = " ".join(v) if isinstance(v, (list, tuple)) else str(v)
        if str(k).lower() in ("who", "q_who") and "team" in val.lower():
            return "team"
    return ""


# ----------------------------------------------------------------------------- the orchestrator, wired to LOKI
def specialists() -> dict:
    out = {"worker": "a general LOKI agent with the full tool set - anything that is not a specialist's job"}
    try:
        import art_specialists  # pylint: disable=import-outside-toplevel
        for k, sp in art_specialists.SPECIALISTS.items():
            out[sp["name"]] = "%s (tool: %s)" % (sp["does"], sp["tool"])
    except Exception:  # noqa: BLE001
        pass
    try:
        import team  # pylint: disable=import-outside-toplevel
        for k in ("researcher", "architect", "builder", "tester", "reviewer"):
            r = team.ROLES[k]
            out[r["name"]] = r["brief"][:160] + ("" if r["writes"] else " (read-only)")
    except Exception:  # noqa: BLE001
        pass
    return out


_READ_ONLY_SPECIALISTS = {"Researcher", "Reviewer"}


def _skill_for(name: str) -> str:
    try:
        import art_specialists  # pylint: disable=import-outside-toplevel
        for k, sp in art_specialists.SPECIALISTS.items():
            if sp["name"] == name:
                return art_specialists.skills_text(k)
    except Exception:  # noqa: BLE001
        pass
    return ""


async def _worker(step: dict, text: str) -> dict:
    agent = _agent()
    skill = _skill_for(step["specialist"])
    task = text + ("\n\nYour skill (follow it):\n" + skill[:6000] if skill else "")
    bullets = playbook.select(step["objective"], k=4)
    pb = playbook.render(bullets)
    if pb:
        task += "\n\n" + pb
    if not step["writes"] or step["specialist"] in _READ_ONLY_SPECIALISTS:
        out = await agent.run_subagent(task=task, tools=",".join(step.get("tools") or []))
        ok = not str(out).startswith(("error:", "Sub-agent (did not finish)")) and "NOT DONE" not in str(out)[:400]
        return {"ok": ok, "summary": str(out)[-3000:], "files": sendback.files_in(str(out))}
    started = _start_job(task, "%s: %s" % (step["specialist"], step["objective"]),
                         profile={"name": step["specialist"], "role": step["specialist"].lower().replace(" ", "_"),
                                  "instructions": skill[:4000]})
    if not started.get("ok"):
        out = await agent.run_subagent(task=task, tools="read_file,write_file,edit_file,search_files,list_tree,bash")
        return {"ok": not str(out).startswith("error:"), "summary": str(out)[-3000:], "files": sendback.files_in(str(out))}
    job_id = started["job"]
    state = STATE["state"]
    jobs = getattr(state, "jobs", None) or getattr(agent, "JOBS", None)
    deadline = time.time() + 3700
    job: dict = {}
    while time.time() < deadline:
        await asyncio.sleep(3)
        job = jobs.store.get(job_id) or {}
        if job.get("status") in ("done", "failed", "cancelled"):
            break
    text_out = ""
    try:
        text_out = Path(agent.DATA_DIR, "jobs", job_id + ".result.txt").read_text(encoding="utf-8")
    except OSError:
        text_out = str(job.get("output") or job.get("error") or "")[-4000:]
    waiting = False
    try:
        import owner_review  # pylint: disable=import-outside-toplevel
        waiting = bool(owner_review.waiting_for_jobs([job_id]))
    except Exception:  # noqa: BLE001
        pass
    ok = job.get("status") == "done" and not re.match(r"\s*(BLOCKED|NOT DONE)", text_out)
    ws = Path(getattr(agent, "WORKSPACE", ".") or ".")
    files = [f for f in sendback.files_in(text_out)]
    return {"ok": ok, "summary": text_out[-3000:], "files": [str(ws / f) if not Path(f).is_absolute() else f for f in files],
            "waiting": waiting and not ok, "job": job_id}


async def _ask(prompt: str) -> str:
    agent = _agent()
    return await agent._port_ask(prompt, max_tokens=2500)   # pylint: disable=protected-access


def _say(cid: str):
    agent = _agent()

    def say(kind: str, text: str) -> None:
        try:
            agent._progress(kind, text)   # pylint: disable=protected-access
        except Exception:  # noqa: BLE001
            pass
        try:
            import events  # pylint: disable=import-outside-toplevel
            events.emit("orchestrator." + kind, "LOKI orchestrator", {"text": text[:400], "conversation": cid})
        except Exception:  # noqa: BLE001
            pass
    return say


def start_orchestration(goal: str, conversation_id: str = "") -> dict:
    """Run the delegation loop in the background on the engine's loop; the report lands in the chat (or Lab)."""
    state, agent = STATE["state"], _agent()
    loop = getattr(state, "loop", None)
    if agent is None or loop is None:
        return {"ok": False, "error": "the engine is not running"}
    import uuid  # pylint: disable=import-outside-toplevel
    run_id = uuid.uuid4().hex[:12]
    orch = orchestrator.Orchestrator(_ask, _worker, specialists(), on_event=_say(conversation_id))
    if conversation_id:
        try:
            agent.append_to_conversation(conversation_id, "user", goal.split("\n\n" + interview.ANSWERS_MARK)[0])
        except Exception:  # noqa: BLE001
            pass

    async def go() -> None:
        try:
            run = await orch.run(goal, run_id=run_id)
            text = orchestrator.report(run)
        except Exception as exc:  # noqa: BLE001
            text = "The orchestration stopped: %s: %s" % (type(exc).__name__, exc)
        if conversation_id:
            try:
                agent.append_to_conversation(conversation_id, "assistant", text)
            except Exception:  # noqa: BLE001
                pass
    STATE["orchestrations"][run_id] = asyncio.run_coroutine_threadsafe(go(), loop)
    return {"ok": True, "orchestration": run_id}


def resume_orchestration(run_id: str, conversation_id: str = "") -> dict:
    state = STATE["state"]
    loop = getattr(state, "loop", None)
    if loop is None:
        return {"ok": False, "error": "the engine is not running"}
    orch = orchestrator.Orchestrator(_ask, _worker, specialists(), on_event=_say(conversation_id))

    async def go() -> None:
        run = await orch.resume(run_id)
        if conversation_id:
            try:
                _agent().append_to_conversation(conversation_id, "assistant", orchestrator.report(run))
            except Exception:  # noqa: BLE001
                pass
    STATE["orchestrations"][run_id] = asyncio.run_coroutine_threadsafe(go(), loop)
    return {"ok": True, "orchestration": run_id}


def parked_orchestrations_ready() -> list:
    """Waiting runs whose owner cards are all decided: the autopilot resumes them."""
    out = []
    try:
        import owner_review  # pylint: disable=import-outside-toplevel
        open_jobs = {it.get("job") for it in owner_review.items(owner_review.OPEN)}
    except Exception:  # noqa: BLE001
        return out
    for r in orchestrator.recent(50):
        if r.get("status") != "waiting" or r["id"] in STATE["orchestrations"] and not STATE["orchestrations"][r["id"]].done():
            continue
        try:
            run = json.loads((orchestrator.folder() / ("%s.json" % r["id"])).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        jobs = {str((s.get("result") or {}).get("job") or "") for s in run["steps"] if s["status"] == "waiting"}
        if not (jobs & open_jobs):
            out.append(r["id"])
    return out
