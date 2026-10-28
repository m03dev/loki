"""The delegation loop: one orchestrator, specialists on call, every step checked (owner 2026-10-28: "ai delegation
loop").

Built from what the big systems published (docs/AGENT_SYSTEM.md "Orchestration"):
  - Magentic-One (Microsoft): an outer loop with a TASK LEDGER (facts given / to look up / to derive / educated
    guesses + the plan) and an inner loop with a PROGRESS LEDGER after every step (satisfied? looping? progressing?
    who next? what instruction?). A stall counter; past STALL_LIMIT (2) the orchestrator reflects, rewrites the facts
    and makes a new plan for what is left. Caps on re-plans and steps; at a cap it reports its best result plainly.
  - Anthropic multi-agent research: every delegated task carries an objective, an output format, the tools to use
    and its boundaries (vague briefs made workers overlap); effort scales with the task (1 worker for a simple job,
    2-4 for a comparison, more only for a big one); workers return a short summary + file paths, not transcripts.
  - Anthropic evaluator-optimizer / ADK LoopAgent critic-refiner: each step's result is checked against its own
    `check`; a failed check goes back to the same specialist with the fixes, up to MAX_REVISIONS times.
  - Cognition / Claude Code: writes are single-threaded (one writing step at a time); read-only steps may run side by
    side. Workers cannot start workers.
  - A2A / LangGraph interrupts: a step that waits for the owner (a picture prompt in For you) PARKS the whole run with
    its ledger saved; `resume` picks it up where it stopped. Nothing is redone that was already approved.

The loop itself is plain code; `ask(prompt) -> text` (a model call) and `run_worker(step) -> result` (a specialist on
whichever harness - engine/agentsys/runtime.py wires LOKI's) are injected, so it is tested without a model.
Storage: <data>/orchestrations/<id>.json - the ledgers, every step and its result (durable; Lab shows it).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import guardrails, sub, trace

MAX_PARALLEL_READS = int(os.environ.get("LOKI_ORCH_PARALLEL", "3") or 3)

EFFORT = """Effort (copy this scale - too many workers waste the owner's tokens):
- one clear thing to make or answer: 1 step
- a thing plus its check (make + verify, research + summary): 2-3 steps
- a comparison or a pipeline (concept -> turnaround -> model -> render): 3-6 steps
- a big build or rework: up to 8 steps, split so each step has ONE owner and ONE output"""

LEDGER_PROMPT = """You are LOKI's orchestrator. You do not do the work yourself: you plan it and hand each step to the
specialist best at it, then check every result.

The goal:
<<<
%(goal)s
>>>

Specialists you can hand steps to (name: what they do):
%(specialists)s

%(effort)s

Write the TASK LEDGER as JSON only:
{"facts_given": ["what the goal / the owner already says"],
 "facts_to_look_up": ["what must be found out first"],
 "facts_to_derive": ["what follows by reasoning"],
 "guesses": ["educated guesses, marked as such"],
 "acceptance": ["how we know the WHOLE goal is done - checkable, e.g. a file exists, a test passes"],
 "plan": [{"id": "s1", "specialist": "<one name from the list>", "objective": "one sentence",
           "output": "exactly what comes back (file path pattern / format)", "tools": ["tool names"],
           "boundaries": "what NOT to do / touch", "writes": true, "depends_on": [], "check": "how this step is checked"}]}
%(previous)s"""

PROGRESS_PROMPT = """You are LOKI's orchestrator checking progress (the progress ledger).
The goal: %(goal)s
Acceptance: %(acceptance)s
Steps so far:
%(steps)s
Steps not done yet: %(left)s

Answer with JSON only:
{"satisfied": false, "looping": false, "progressing": true, "reason": "one line",
 "next": "<id of the next step, or empty>", "instruction": "what the next specialist must do differently, if anything"}"""

REVIEW_PROMPT = """Check one step of LOKI's work against its own check. Be strict and concrete; do not invent problems.
Step: %(objective)s
Expected output: %(output)s
Check: %(check)s
What the specialist reported:
<<<
%(summary)s
>>>
Files it says it made: %(files)s (missing on disk: %(missing)s)
Answer with JSON only: {"pass": true, "fixes": ["exact change needed", "..."]}"""


def folder() -> Path:
    return sub("orchestrations")


def _json(raw: str) -> dict:
    raw = re.sub(r"<think>.*?</think>", "", str(raw or ""), flags=re.S)
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e <= s:
        raise ValueError("no JSON object")
    return json.loads(raw[s:e + 1])


def _clip(s: Any, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def normalize_plan(plan: Any, specialists: dict, limit: int) -> list:
    out, seen = [], set()
    for i, st in enumerate(plan or []):
        if not isinstance(st, dict) or not str(st.get("objective") or "").strip():
            continue
        sid = re.sub(r"[^a-z0-9_-]", "", str(st.get("id") or "s%d" % (i + 1)).lower()) or "s%d" % (i + 1)
        while sid in seen:
            sid += "x"
        seen.add(sid)
        spec = str(st.get("specialist") or "").strip()
        if spec not in specialists:      # a name the model made up: the closest real one, else the general worker
            low = spec.lower()
            spec = next((k for k in specialists if k.lower() == low or low in k.lower() or k.lower() in low), "") if low else ""
            if not spec and low:
                import difflib  # pylint: disable=import-outside-toplevel
                close = difflib.get_close_matches(low, [k.lower() for k in specialists], n=1, cutoff=0.75)
                spec = next((k for k in specialists if close and k.lower() == close[0]), "")
            spec = spec or ("worker" if "worker" in specialists else next(iter(specialists)))
        out.append({"id": sid, "specialist": spec, "objective": _clip(st["objective"], 400),
                    "output": _clip(st.get("output") or "a short report of what was done, with file paths", 300),
                    "tools": [str(t) for t in (st.get("tools") or [])][:8],
                    "boundaries": _clip(st.get("boundaries") or "only this step's objective", 300),
                    "writes": bool(st.get("writes", True)), "depends_on": [str(d) for d in (st.get("depends_on") or [])],
                    "check": _clip(st.get("check") or "the output exists and matches the objective", 300),
                    "gate": "owner" if str(st.get("gate") or "").lower() == "owner" else "",
                    "status": "todo", "attempts": 0, "result": None, "review": None})
        if len(out) >= limit:
            break
    known = {s["id"] for s in out}
    for s in out:
        s["depends_on"] = [d for d in s["depends_on"] if d in known and d != s["id"]]
    return out


def brief(step: dict, goal: str, ledger: dict, done: list, fixes: list | None = None, instruction: str = "") -> str:
    """What a specialist is handed: objective, output, tools, boundaries (Anthropic's four), plus what came before."""
    parts = ["You are the %s, working on ONE step of a bigger goal. Do this step only." % step["specialist"],
             "The whole goal (context, not your job): %s" % _clip(goal, 1200),
             "YOUR STEP: %s" % step["objective"],
             "WHAT TO HAND BACK: %s. Keep the report short: what you made, the file paths, what you checked." % step["output"],
             "HOW IT WILL BE CHECKED: %s" % step["check"],
             "BOUNDARIES: %s. Do not start other agents." % step["boundaries"]]
    if step.get("tools"):
        parts.append("TOOLS to use: %s" % ", ".join(step["tools"]))
    facts = [f for f in (ledger.get("facts_given") or [])][:8]
    if facts:
        parts.append("Known facts: " + "; ".join(_clip(f, 200) for f in facts))
    prev = [d for d in done if d["id"] in step.get("depends_on", [])] or done[-2:]
    for d in prev:
        r = d.get("result") or {}
        parts.append("Result of %s (%s): %s%s" % (d["id"], d["specialist"], _clip(r.get("summary"), 600),
                                                 (" Files: " + ", ".join(r.get("files") or [])[:600]) if r.get("files") else ""))
    if fixes:
        parts.append("THIS IS A REVISION. Your last result failed its check. Fix exactly this:\n- " + "\n- ".join(
            _clip(f, 300) for f in fixes))
    if instruction:
        parts.append("The orchestrator adds: %s" % _clip(instruction, 600))
    parts.append("End with DONE: <one line> or BLOCKED: <what you need>. If something waits for the owner's OK, say so "
                 "and stop - that is not a failure.")
    return "\n\n".join(parts)


class Orchestrator:
    def __init__(self, ask: Callable[[str], Awaitable[str]], run_worker: Callable[[dict, str], Awaitable[dict]],
                 specialists: dict, budget: guardrails.Budget | None = None,
                 exists: Callable[[str], bool] | None = None, on_event: Callable[[str, str], None] | None = None):
        self._ask, self.run_worker, self.specialists = ask, run_worker, dict(specialists or {})
        self.check_off: Callable | None = None     # (step, result, run) -> For you card id (the owner's check-off)
        self.card_state: Callable | None = None    # card id -> (status, note)
        self.ask_timeout = float(os.environ.get("LOKI_ORCH_ASK_S", "120") or 120)
        self.specialists.setdefault("worker", "a general agent: does any step with the full tool set")
        self.budget = budget or guardrails.Budget()
        self.exists = exists or (lambda p: Path(p).exists())
        self.on_event = on_event or (lambda kind, text: None)
        self.stall = guardrails.StallWatch(same=2)

    async def ask(self, prompt: str) -> str:
        """The orchestrator's own model calls (ledger, review, progress) never hang a run: past ask_timeout the
        caller's fallback decides (one plain step / the worker's own result / no progress)."""
        return await asyncio.wait_for(self._ask(prompt), self.ask_timeout)

    # ------------------------------------------------------------------ the record
    def _save(self, run: dict) -> dict:
        run["updated"] = time.time()
        run["budget"] = self.budget.as_dict()
        p = folder() / ("%s.json" % run["id"])
        tmp = p.with_suffix(".tmp%d" % os.getpid())
        tmp.write_text(json.dumps(run, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, p)
        return run

    def _say(self, kind: str, text: str) -> None:
        try:
            self.on_event(kind, text)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ the outer loop
    def skeleton(self, goal: str) -> list:
        """The owner's playbook steps for this goal (agentsys/playbooks.py), as plan steps for the core agent, or []."""
        try:
            from . import playbooks  # pylint: disable=import-outside-toplevel
            pb = playbooks.match(goal)
        except Exception:  # noqa: BLE001
            pb = None
        if not pb or not pb.get("steps"):
            return []
        done = "; ".join(pb.get("done") or [])
        tools = [re.split(r"[\s:(]", t.strip(), 1)[0].strip("`") for t in (pb.get("toolbox") or {}).get("tools") or []]
        return [{"id": "s%d" % (i + 1), "specialist": "worker", "objective": st, "output": "what this step makes",
                 "tools": [t for t in tools if t][:8], "check": done if i == len(pb["steps"]) - 1 else "",
                 "writes": True, "depends_on": ["s%d" % i] if i else []} for i, st in enumerate(pb["steps"])]

    def done_means(self, goal: str) -> str:
        try:
            from . import playbooks  # pylint: disable=import-outside-toplevel
            pb = playbooks.match(goal)
        except Exception:  # noqa: BLE001
            pb = None
        return "\n".join("- " + x for x in (pb or {}).get("done") or [])

    async def ledger(self, goal: str, previous: str = "") -> dict:
        skel = self.skeleton(goal)
        specs = "\n".join("- %s: %s" % (k, _clip(v, 160)) for k, v in self.specialists.items())
        effort = EFFORT
        if skel:
            effort += ("\n\nTHE OWNER'S PLAYBOOK for this job gives the steps - they are the plan, in this order, every "
                       "step done by the worker (the one core agent); fill in each step's output for THIS goal; never "
                       "drop or reorder his steps:\n" + json.dumps(skel, ensure_ascii=False)[:5000])
        prompt = LEDGER_PROMPT % {"goal": _clip(goal, 4000), "specialists": specs, "effort": effort,
                                  "previous": ("\nThe last plan stalled. What happened:\n" + previous +
                                               "\nRewrite the facts (what we now know) and plan ONLY the remaining work.")
                                  if previous else ""}
        with trace.span("orchestrator ledger", "step"):
            try:
                data = _json(await self.ask(prompt))
            except Exception as exc:  # noqa: BLE001 - one plain step with the general worker
                data = {"facts_given": [], "acceptance": [], "plan": [], "error": str(exc)[:200]}
        plan = normalize_plan(data.get("plan"), self.specialists, limit=10)
        if not plan and skel and not previous:     # no model: the playbook's own stages, as they are
            plan = normalize_plan([dict(st, objective="%s (for: %s)" % (st["objective"], _clip(goal, 200))) for st in skel],
                                  self.specialists, limit=10)
        by_id = {st["id"]: st for st in skel}
        for st in plan:                       # the owner's gates and the playbook's checks are never dropped by a model
            src = by_id.get(st["id"])
            if src:
                if src.get("gate") == "owner":
                    st["gate"] = "owner"
                if src.get("check") and src["check"] not in st["check"]:
                    st["check"] = _clip(st["check"] + "; " + src["check"], 600)
        if not plan:
            plan = normalize_plan([{"id": "s1", "specialist": "worker", "objective": goal[:400],
                                    "output": "the finished result with file paths", "writes": True}],
                                  self.specialists, 1)
        return {k: data.get(k) or [] for k in ("facts_given", "facts_to_look_up", "facts_to_derive", "guesses",
                                               "acceptance")} | {"plan": plan}

    async def run(self, goal: str, run_id: str = "") -> dict:
        run = {"id": run_id or uuid.uuid4().hex[:12], "goal": goal, "started": time.time(), "status": "working",
               "ledgers": [], "steps": [], "events": [], "outcome": ""}
        self.goal_text = goal
        with trace.span("invoke_agent orchestrator", "agent", **{"gen_ai.agent.name": "LOKI orchestrator",
                                                                  "loki.orchestration": run["id"]}) as sp:
            led = await self.ledger(goal)
            run["ledgers"].append({k: v for k, v in led.items() if k != "plan"})
            run["steps"] = led["plan"]
            run["trace_id"] = sp.trace_id
            self._say("task", "Plan: " + " -> ".join("%s (%s)" % (s["id"], s["specialist"]) for s in run["steps"]))
            self._save(run)
            await self._loop(run)
            sp.set(**{"loki.outcome": run["outcome"], "loki.steps": len(run["steps"])})
        return self._save(run)

    async def resume(self, run_id: str) -> dict:
        p = folder() / ("%s.json" % run_id)
        run = json.loads(p.read_text(encoding="utf-8"))
        self.goal_text = run.get("goal", "")
        for s in run["steps"]:
            if s["status"] != "waiting":
                continue
            verdict = self.card_state(s["card"]) if s.get("card") and self.card_state else ("", "")
            if verdict[0] == "approved":       # he checked the hand-off off: the stage is done
                s["status"] = "done"
            elif verdict[0] in ("retake", "rejected"):   # sent back with his note: the same specialist again
                s["status"], s["owner_note"] = "todo", verdict[1]
            elif verdict[0] in ("parked",):
                s["status"] = "waiting"        # not now: it keeps waiting
            else:
                s["status"] = "todo"           # the owner answered a picture prompt: that step goes again
        run["status"] = "working"
        with trace.span("invoke_agent orchestrator (resume)", "agent", **{"loki.orchestration": run_id}) as sp:
            await self._loop(run)
            sp.set(**{"loki.outcome": run["outcome"]})
        return self._save(run)

    # ------------------------------------------------------------------ the inner loop
    def _ready(self, run: dict) -> list:
        done = {s["id"] for s in run["steps"] if s["status"] == "done"}
        return [s for s in run["steps"] if s["status"] == "todo" and all(d in done for d in s["depends_on"])]

    async def _loop(self, run: dict) -> None:
        instruction = ""
        while True:
            stop = self.budget.check()
            if not stop.ok:
                run["events"].append({"t": time.time(), "stop": stop.reason})
                break
            ready = self._ready(run)
            if not ready:
                break
            # single-threaded writes; read-only steps side by side (at most MAX_PARALLEL_READS)
            reads = [s for s in ready if not s["writes"]][:MAX_PARALLEL_READS]
            batch = reads if reads else [ready[0]]
            await asyncio.gather(*(self._do_step(run, s, instruction) for s in batch))
            instruction = ""
            self._save(run)
            if any(s["status"] == "waiting" for s in run["steps"]):
                break                       # the owner's turn: park the whole run
            # the progress ledger: deterministic when it is clear, the model when a step failed
            failed = [s for s in batch if s["status"] == "failed"]
            stalled = any(s.get("stalled") for s in batch)
            if not failed and not stalled:
                self.budget.stalls = 0
                continue
            prog = await self._progress(run)
            run["events"].append({"t": time.time(), "progress": prog})
            if prog.get("satisfied"):
                break
            if prog.get("looping") or not prog.get("progressing", True) or stalled:
                self.budget.stalls += 1
            spent = bool(failed) and all(s["attempts"] > self.budget.max_revisions for s in failed)
            if self.budget.stalls > self.budget.stall_limit or spent:   # stuck, or the failed step has no tries left
                if self.budget.replans >= self.budget.max_replans:
                    run["events"].append({"t": time.time(), "stop": "stalled after %d re-plans" % self.budget.replans})
                    break
                await self._replan(run, prog)
                continue
            # retry the failed step once more with the orchestrator's instruction (it counts as an attempt)
            nxt = next((s for s in run["steps"] if s["id"] == prog.get("next")), None) or (failed[0] if failed else None)
            if nxt is not None and nxt["status"] == "failed" and nxt["attempts"] <= self.budget.max_revisions:
                nxt["status"] = "todo"
                instruction = str(prog.get("instruction") or "")
        self._finish(run)

    async def _do_step(self, run: dict, step: dict, instruction: str = "") -> None:
        done = [s for s in run["steps"] if s["status"] == "done"]
        fixes: list = []
        while True:
            self.budget.steps += 1
            step["attempts"] += 1
            step["status"] = "working"
            if step.get("owner_note") and not fixes:
                fixes = ["The owner sent this back: " + step.pop("owner_note")]
            text = brief(step, run["goal"], (run["ledgers"] or [{}])[-1], done, fixes, instruction)
            self._say("task", "%s -> %s: %s" % (step["id"], step["specialist"], step["objective"][:160]))
            with trace.span("invoke_agent %s" % step["specialist"], "handoff",
                            **{"gen_ai.agent.name": step["specialist"], "loki.step": step["id"],
                               "loki.attempt": step["attempts"]}) as sp:
                try:
                    res = await self.run_worker(step, text) or {}
                except Exception as exc:  # noqa: BLE001 - a crashed worker is a failed attempt, not a crashed run
                    res = {"ok": False, "summary": "%s: %s" % (type(exc).__name__, exc)}
                res = {"ok": bool(res.get("ok")), "summary": _clip(res.get("summary"), 2000),
                       "files": [str(f) for f in (res.get("files") or [])][:20], "waiting": bool(res.get("waiting")),
                       "tokens": int(res.get("tokens") or 0), "job": str(res.get("job") or "")}
                self.budget.spend(res["tokens"])
                sp.set(**{"loki.ok": res["ok"], "loki.files": len(res["files"])})
            step["result"] = res
            if self.stall.add(step["specialist"], step["objective"], res["summary"]).action != guardrails.OK:
                step["stalled"] = True
            if res["waiting"]:
                step["status"] = "waiting"
                self._say("task", "%s waits for your OK in Home > For you." % step["id"])
                return
            review = await self._review(step, res)
            step["review"] = review
            if review.get("pass"):
                if step.get("gate") == "owner" and self.check_off is not None:
                    # the owner's rule 8: every hand-off waits for his check-off (Home > For you)
                    try:
                        step["card"] = self.check_off(step, res, run)
                    except Exception:  # noqa: BLE001 - no For you here: the check passed, it goes on
                        step["card"] = ""
                    if step.get("card"):
                        step["status"] = "waiting"
                        self._say("task", "%s waits for your check-off in Home > For you." % step["id"])
                        return
                step["status"] = "done"
                return
            if step["attempts"] > self.budget.max_revisions or not self.budget.check().ok:
                step["status"] = "failed"
                return
            fixes = list(review.get("fixes") or ["the check failed: " + step["check"]])
            self._say("task", "%s goes back to %s: %s" % (step["id"], step["specialist"], "; ".join(fixes)[:200]))

    async def _review(self, step: dict, res: dict) -> dict:
        """The evaluator: files must exist (code check), then the model holds it against the step's own check."""
        missing = [f for f in res["files"] if not self.exists(f)]
        if not res["ok"] and not res["summary"]:
            return {"pass": False, "fixes": ["the step gave no result at all"]}
        if missing:
            return {"pass": False, "fixes": ["these files are not there: %s - make them or report the real paths"
                                             % ", ".join(missing[:6])]}
        if re.search(r"^\s*BLOCKED\b", res["summary"], re.M) and not res["ok"]:
            return {"pass": False, "fixes": ["it was blocked: %s" % res["summary"][:300]]}
        try:
            with trace.span("evaluate %s" % step["id"], "guardrail"):
                book = self.done_means(self.goal_text) if getattr(self, "goal_text", "") else ""
                data = _json(await self.ask(REVIEW_PROMPT % {
                    "objective": step["objective"], "output": step["output"],
                    "check": step["check"] + (("\nThe owner's playbook - done means:\n" + book[:2500]) if book else ""),
                    "summary": res["summary"][:3000], "files": ", ".join(res["files"]) or "none",
                    "missing": ", ".join(missing) or "none"}))
            return {"pass": bool(data.get("pass")), "fixes": [_clip(f, 300) for f in (data.get("fixes") or [])][:5]}
        except Exception:  # noqa: BLE001 - no reviewer: the worker's own DONE / ok decides
            return {"pass": bool(res["ok"]), "fixes": [] if res["ok"] else ["the specialist did not finish"]}

    async def _progress(self, run: dict) -> dict:
        lines = []
        for s in run["steps"]:
            r = s.get("result") or {}
            lines.append("- %s %s [%s, %d tries]: %s" % (s["id"], s["specialist"], s["status"], s["attempts"],
                                                         _clip(r.get("summary"), 300)))
        left = [s["id"] for s in run["steps"] if s["status"] in ("todo", "failed")]
        try:
            data = _json(await self.ask(PROGRESS_PROMPT % {
                "goal": _clip(run["goal"], 1500), "acceptance": "; ".join((run["ledgers"] or [{}])[-1].get("acceptance") or [])[:800],
                "steps": "\n".join(lines)[:6000], "left": ", ".join(left) or "none"}))
            return {"satisfied": bool(data.get("satisfied")), "looping": bool(data.get("looping")),
                    "progressing": bool(data.get("progressing", True)), "reason": _clip(data.get("reason"), 300),
                    "next": str(data.get("next") or ""), "instruction": _clip(data.get("instruction"), 600)}
        except Exception:  # noqa: BLE001 - no model: a failed step is no progress
            return {"satisfied": False, "looping": False, "progressing": False, "reason": "no progress check",
                    "next": left[0] if left else "", "instruction": ""}

    async def _replan(self, run: dict, prog: dict) -> None:
        self.budget.replans += 1
        self.budget.stalls = 0
        what = "\n".join("- %s (%s): %s - %s" % (s["id"], s["specialist"], s["status"], _clip((s.get("result") or {}).get("summary"), 300))
                         for s in run["steps"]) + "\nWhy it stalled: " + str(prog.get("reason") or "")
        self._say("task", "Stalled - re-planning (%d of %d): %s" % (self.budget.replans, self.budget.max_replans,
                                                                    str(prog.get("reason") or "")[:160]))
        led = await self.ledger(run["goal"], previous=what)
        keep = [s for s in run["steps"] if s["status"] == "done"]
        for s in led["plan"]:
            s["id"] = "r%d%s" % (self.budget.replans, s["id"])
            s["depends_on"] = ["r%d%s" % (self.budget.replans, d) for d in s["depends_on"]]
        for s in run["steps"]:
            if s["status"] != "done":
                s["status"] = "replaced"
        run["ledgers"].append({k: v for k, v in led.items() if k != "plan"} | {"replan": self.budget.replans})
        run["steps"] = keep + [s for s in run["steps"] if s["status"] == "replaced"] + led["plan"]

    def _finish(self, run: dict) -> None:
        live = [s for s in run["steps"] if s["status"] != "replaced"]
        if any(s["status"] == "waiting" for s in live):
            run["status"], run["outcome"] = "waiting", "waiting_for_owner"
        elif live and all(s["status"] == "done" for s in live):
            run["status"], run["outcome"] = "done", "verified"
        elif any(s["status"] == "done" for s in live):
            run["status"], run["outcome"] = "partial", "partial"
        else:
            run["status"], run["outcome"] = "failed", "failed"
        run["finished"] = time.time()
        run["files"] = sorted({f for s in live for f in ((s.get("result") or {}).get("files") or [])})


def report(run: dict) -> str:
    """The owner's view of a finished run: what each specialist did, what was checked, what is left."""
    word = {"verified": "Done - every step passed its check.", "partial": "Partly done - some steps did not pass.",
            "failed": "Not done.", "waiting_for_owner": "Waiting for you in Home > For you - it carries on after your OK."}
    lines = [word.get(run.get("outcome"), run.get("status", "")), ""]
    for s in run.get("steps", []):
        if s["status"] == "replaced":
            continue
        r = s.get("result") or {}
        mark = {"done": "✓", "failed": "✗", "waiting": "…", "todo": "·", "working": "…"}.get(s["status"], "·")
        lines.append("%s %s - %s: %s" % (mark, s["specialist"], s["objective"], _clip(r.get("summary"), 240) or s["status"]))
        if s["status"] == "failed" and (s.get("review") or {}).get("fixes"):
            lines.append("   still wrong: " + "; ".join(s["review"]["fixes"])[:300])
    if run.get("files"):
        lines += ["", "Files: " + ", ".join(run["files"][:12])]
    stop = next((e["stop"] for e in reversed(run.get("events") or []) if e.get("stop")), "")
    if stop:
        lines += ["", "Stopped: " + stop]
    return "\n".join(lines)


def recent(limit: int = 20) -> list:
    out = []
    for p in sorted(folder().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": r["id"], "goal": _clip(r.get("goal"), 200), "status": r.get("status"),
                    "outcome": r.get("outcome"), "steps": [{"id": s["id"], "specialist": s["specialist"],
                                                             "status": s["status"]} for s in r.get("steps", [])
                                                            if s["status"] != "replaced"],
                    "updated": r.get("updated")})
    return out
