#!/usr/bin/env python3
"""Do LOKI's agents finish real tasks? The task-success benchmark.

Runs the owner's realistic tasks (tests/tasks/catalog.py: write a doc, fix code and run its
test, research with sources, make a picture, summarize a file, plan a project, build in a
sandbox, a team job, a task that needs an assumption, tasks that must end BLOCKED honestly)
through the REAL background-job path - `loki.run_job`, the same goal loop a job started from
the app runs - each in its own throwaway workspace, then checks the real result: files on
disk, tests that pass, pictures that are pictures, sources that came from a tool, a DONE line
that does not lie.

    python tools/task_bench.py --model local            the local model (Ollama)
    python tools/task_bench.py --model local,bonsai,smart
    python tools/task_bench.py --model groq --tasks doc-readme,code-fix-bug
    python tools/task_bench.py --scripted               no model: scripted small-model behaviours
    python tools/task_bench.py --list

Writes harness_data/bench/<date>.json (every model run that day; latest.json is the newest)
and <date>.md (the table), and a log per task under harness_data/bench/logs/. Settings > Lab
shows the latest scores; the autopilot runs it nightly on the PC (LOKI_TASK_BENCH).

--scripted replaces the model with scripted fakes that reproduce what small models did in
the PC's job logs (empty and <think>-only replies, ```json tool calls, wrong tool names,
premature DONE, BLOCKED guesses, huge outputs, cut-off calls...), and the web and image
specialists with fixtures, so the loop's recovery is tested anywhere (tests/test_task_success.py).

Models: local = whatever LOKI's local slot resolves to; bonsai = local pinned to Bonsai 2
(LOKI_BENCH_BONSAI to name another tag); smart = LOKI's own routing; anything else is a
provider name from loki.MODELS (groq, openrouter, gemini, claude-code, codex, ...).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import types
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "engine"
TESTS = REPO / "tests"
BONSAI_TAG = "hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Ternary-Bonsai-2-9B-Q2_0"
SCRIPTED_LOCAL = "qwen3:8b"          # what the scripted fake pretends to be (a local qwen3)
STRONG = "groq"                       # the provider a scripted job escalates to
REAL_TIMEOUT_S = float(os.getenv("LOKI_BENCH_TIMEOUT", "900"))
SCRIPTED_TIMEOUT_S = 60.0


def _tasks_module():
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    import tasks  # noqa: E402  pylint: disable=import-outside-toplevel
    return tasks


def data_dir() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else REPO / "harness_data"


def bench_dir() -> Path:
    return data_dir() / "bench"


# =============================================================================== the child
# One task = one child process: `task_bench.py --child spec.json`. It imports the engine
# like a real job does (LOKI_WORKSPACE = the throwaway folder, LOKI_JOB_ID set), counts what
# happens, and in a scripted run swaps the model and the web/image specialists for fakes.

class _Counter:
    def __init__(self) -> None:
        self.calls = 0           # model requests
        self.tools = 0           # tool calls the loop ran (top level)
        self.tin = 0
        self.tout = 0
        self.max_prompt = 0      # the longest request sent, in characters
        self.depth = 0


def _msg_chars(messages) -> int:
    total = 0
    for m in messages or []:
        if isinstance(m, dict):
            total += len(str(m.get("content") or "")) + len(json.dumps(m.get("tool_calls") or []))
    return total


class _CountingCompletions:
    def __init__(self, inner, counter: _Counter) -> None:
        self._inner = inner
        self._counter = counter

    async def create(self, **kwargs):
        self._counter.calls += 1
        self._counter.max_prompt = max(self._counter.max_prompt, _msg_chars(kwargs.get("messages")))
        return await self._inner.create(**kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _instrument(loki, counter: _Counter, make_client=None) -> None:
    base = make_client or loki.make_client

    def make():
        client = base()
        return types.SimpleNamespace(chat=types.SimpleNamespace(
            completions=_CountingCompletions(client.chat.completions, counter)), _inner=client)
    loki.make_client = make

    record = loki.USAGE.record

    def rec(*args, **kwargs):
        entry = record(*args, **kwargs)
        counter.tin += int(entry.get("in") or 0)
        counter.tout += int(entry.get("out") or 0)
        return entry
    loki.USAGE.record = rec

    call_tool = loki.call_tool

    async def counted(name, args):
        top = counter.depth == 0
        counter.depth += 1
        try:
            if top:
                counter.tools += 1
            return await call_tool(name, args)
        finally:
            counter.depth -= 1
    loki.call_tool = counted


# ------------------------------------------------------------------------------- the fakes

def _fake_response(step: dict, messages: list):
    content = step.get("content")
    tool_calls = None
    if step.get("calls"):
        tool_calls = []
        for name, args in step["calls"]:
            fn = types.SimpleNamespace(name=name, arguments=json.dumps(args))
            tool_calls.append(types.SimpleNamespace(id="call_" + uuid.uuid4().hex[:10], type="function", function=fn))
        content = content or ""
    msg = types.SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls)
    usage = types.SimpleNamespace(prompt_tokens=max(1, _msg_chars(messages) // 4),
                                  completion_tokens=max(1, len(str(content or "")) // 4 + 8 * len(tool_calls or [])))
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")], usage=usage)


class ScriptedModel:
    """A fake chat-completions endpoint that plays a task's script, lane by lane: the lane the
    job starts on, then "strong" once LOKI escalated the job to another model."""

    def __init__(self, loki, lanes: dict, lane: str) -> None:
        self.loki = loki
        self.queues = {name: list(steps) for name, steps in lanes.items()}
        self.lane = lane
        self.played: list = []
        self.not_offered: list = []
        self.all_tools = {t["function"]["name"] for t in loki.TOOL_SCHEMAS}

    @staticmethod
    def _offered(kwargs: dict):
        """The tool names this request offered (native list, or the prompted <tools> block)."""
        if kwargs.get("tools"):
            return {((t.get("function") or t).get("name")) for t in kwargs["tools"] if isinstance(t, dict)}
        for m in kwargs.get("messages") or []:
            text = str(m.get("content") or "") if isinstance(m, dict) else ""
            if "<tools>" in text:
                return set(re.findall(r'\{"name": "([\w-]+)"', text))
        return None

    def current_lane(self) -> str:
        if getattr(self.loki, "_ESCALATED", False) and "strong" in self.queues:
            return "strong"
        return self.lane

    async def create(self, **kwargs):
        lane = self.current_lane()
        queue = self.queues.get(lane) or []
        step = queue.pop(0) if queue else {"content": ""}    # out of script: the model goes quiet
        messages = kwargs.get("messages") or []
        if callable(step):
            step = step(messages)
        offered = self._offered(kwargs)
        for name, _args in step.get("calls") or []:
            # A real model only calls what it was offered: a script that needs a tool LOKI did not
            # offer shows a gap in the loop (run_command hidden from a job allowed to run tests...).
            if offered is not None and name in self.all_tools and name not in offered and name not in self.not_offered:
                self.not_offered.append(name)
        self.played.append({"lane": lane, "step": {k: (v if k != "content" else str(v)[:120]) for k, v in step.items()
                                                    if k != "calls"} | ({"calls": [c[0] for c in step["calls"]]}
                                                                         if step.get("calls") else {})})
        if step.get("sleep"):
            await asyncio.sleep(float(step["sleep"]))
        return _fake_response(step, messages)


def _web_fixtures(loki, web: dict) -> None:
    results = list(web.get("results") or [])
    pages = dict(web.get("pages") or {})

    def web_search(query: str = "", mode: str = "web", max_results: int = 8) -> str:
        if not results:
            return "No results for %r." % query
        lines = ["Search results for %r:" % query]
        for i, r in enumerate(results[:max_results or 8], 1):
            lines.append("%d. %s\n   %s\n   %s" % (i, r["title"], r["url"], r.get("snippet", "")))
        return "\n".join(lines)

    def read_web(url: str = "", max_chars: int = 20000, query: str = "") -> str:
        text = pages.get(str(url).strip())
        if text is None:
            hit = next((r for r in results if r["url"] == str(url).strip()), None)
            text = hit.get("snippet") if hit else None
        return ("# %s\n\n%s" % (url, text)) if text else "error: could not fetch %s (HTTP 404)" % url

    def research_web(question: str = "", mode: str = "web", pages_n: int = 3, queries=None, **_kw) -> str:
        lines = ["Sources for %r:" % question]
        for i, r in enumerate(results[:3], 1):
            lines.append("[%d] %s - %s\n%s" % (i, r["title"], r["url"], pages.get(r["url"], r.get("snippet", ""))))
        return "\n".join(lines) + "\n\nCite the sources by number with their links."

    for name, fn in (("web_search", web_search), ("read_web", read_web), ("research_web", research_web)):
        if name in loki.LOCAL_TOOLS:
            loki.LOCAL_TOOLS[name] = fn


PNG_1PX = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360f8cfc000000301010018dd8db00000000049454e44ae426082")


def _specialist_fixtures(loki, task, web: dict) -> None:
    real = loki.LOCAL_TOOLS.get("conductor")

    def conductor(role: str = "", task_text: str = "", url: str = "", **kw) -> str:
        role = str(role).strip().lower()
        what = str(kw.get("task", task_text) or "")
        if role == "image":
            if task.image == "fail":
                return ("error: no image backend is set up on this machine (turn on an image add-on in "
                        "Settings > Add-ons, or set up Pollinations).")
            slug = re.sub(r"[^a-z0-9]+", "-", what.lower()).strip("-")[:40] or "picture"
            path = loki.WORKSPACE / "images" / ("%s.png" % slug)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(PNG_1PX)
            return "made %s with fake-image (1x1 PNG)" % path
        if role == "research":
            return loki.LOCAL_TOOLS["research_web"](what) if "research_web" in loki.LOCAL_TOOLS else "no sources"
        if role == "read_web":
            return loki.LOCAL_TOOLS["read_web"](url or what) if "read_web" in loki.LOCAL_TOOLS else "error"
        return real(role=role, task=what, url=url) if real else "error: no specialist %s" % role

    def conductor_entry(role: str = "", task: str = "", url: str = "") -> str:  # noqa: F811 - the tool's names
        return conductor(role=role, task_text=task, url=url)
    loki.LOCAL_TOOLS["conductor"] = conductor_entry


def _install_scripted(loki, task, spec: dict) -> ScriptedModel:
    lanes = dict((task.scripts.get(spec.get("scenario") or "small") or {}))
    fake = ScriptedModel(loki, lanes, spec.get("lane") or "small")
    loki.make_client = lambda: types.SimpleNamespace(chat=types.SimpleNamespace(completions=fake))
    has_strong = "strong" in lanes
    loki.provider_configured = lambda name: name in ("local", "local-small") or (has_strong and name == STRONG)
    loki.model_setup.keep_warm = lambda *a, **k: None

    async def summarize(_messages):
        return "USER_CONTEXT: the task.\nCOMPLETED: the steps so far (scripted summary)."
    loki._summarize_for_condenser = summarize
    _web_fixtures(loki, task.web)
    _specialist_fixtures(loki, task, task.web)
    return fake


def child_main(spec_path: str) -> int:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    for p in (str(ENGINE), str(TESTS)):
        if p not in sys.path:
            sys.path.insert(0, p)
    counter = _Counter()
    metrics: dict = {"crash": ""}
    fake = None
    started = time.monotonic()
    code = None
    try:
        import loki  # noqa: E402  pylint: disable=import-outside-toplevel
        if spec.get("scripted"):
            task = _tasks_module().BY_ID[spec["task"]]
            fake = _install_scripted(loki, task, spec)
        _instrument(loki, counter)
        job = {"id": spec["job_id"], "prompt": spec["prompt"], "profile": spec.get("profile") or {},
               "allow_commands": bool(spec.get("allow_commands")), "model": spec.get("model") or "",
               "result_path": spec["result_path"], "deadline_s": spec.get("deadline_s") or 0}
        job_file = Path(spec_path).with_suffix(".job.json")
        job_file.write_text(json.dumps(job), encoding="utf-8")
        code = asyncio.run(loki.run_job(str(job_file)))
        metrics["escalated"] = loki.model_name if getattr(loki, "_ESCALATED", False) else ""
    except BaseException as exc:  # noqa: BLE001 - a crash is a result to record, not to hide
        metrics["crash"] = "%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()[-1500:])
        if isinstance(exc, KeyboardInterrupt):
            raise
    metrics.update({"exit": code, "seconds": round(time.monotonic() - started, 2), "steps": counter.calls,
                    "tool_calls": counter.tools, "tokens_in": counter.tin, "tokens_out": counter.tout,
                    "max_prompt_chars": counter.max_prompt, "played": fake.played if fake else [],
                    "not_offered": fake.not_offered if fake else []})
    Path(spec["metrics_path"]).write_text(json.dumps(metrics), encoding="utf-8")
    return 0


# ============================================================================== the parent

_DONE_RE = re.compile(r"^\s*[*_`#>\s]*(DONE|BLOCKED)\b\**\s*[:\-.]?", re.I | re.M)


def outcome_line(text: str, word: str) -> str:
    for line in (text or "").splitlines():
        m = _DONE_RE.match(line)
        if m and m.group(1).upper() == word:
            return line.strip()
    return ""


def _model_env(model: str, scripted: bool) -> tuple:
    """(model name for the job, extra environment)."""
    if scripted:
        return "local", {"LOKI_LOCAL_MODEL": SCRIPTED_LOCAL}
    if model == "bonsai":
        return "local", {"LOKI_LOCAL_MODEL": os.getenv("LOKI_BENCH_BONSAI", BONSAI_TAG)}
    return model, {}


def _child_env(ws: Path, job_id: str, extra: dict, scripted: bool, data: Path, no_escalate: bool,
               team_id: str = "", role_name: str = "") -> dict:
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("LOKI_") and k not in ("LOKI_DATA",)) or k in ("LOKI_ALLOW_PAID",)}
    if not scripted:
        # a real run keeps the machine's model settings (LOKI_PREFER, LOKI_LOCAL_MODEL, keys...)
        env.update({k: v for k, v in os.environ.items() if k.startswith("LOKI_")
                    and k not in ("LOKI_WORKSPACE", "LOKI_JOB_ID", "LOKI_TEAM_ID", "LOKI_TEAM_ROLE")})
    env.pop("GAME_PROJECT", None)
    env.update({"LOKI_WORKSPACE": str(ws), "LOKI_DATA": str(data), "LOKI_JOB_ID": job_id, "LOKI_MODE": "build",
                "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "LOKI_EXPERIENCE": "0",
                "LOKI_TEAM_ID": team_id, "LOKI_TEAM_ROLE": role_name, "LOKI_TIMESFM_APPROVED": "0"})
    if scripted:
        env.update({"LOKI_AUTO_UPDATE": "0", "LOKI_LAYA": "off", "LOKI_PREFER": "local"})
    if no_escalate:
        env["LOKI_NO_ESCALATE"] = "1"
    env.update(extra)
    return env


def run_job_child(*, task, prompt: str, ws: Path, model: str, scripted: bool, scenario: str, lane: str,
                  data: Path, log_path: Path, timeout: float, deadline: float, allow_commands: bool,
                  profile: dict | None = None, no_escalate: bool = False, team_id: str = "") -> dict:
    """Run one job through the real loki.run_job in a child process; return its record."""
    job_model, extra = _model_env(model, scripted)
    job_id = "bench-%s-%s" % (task.id, uuid.uuid4().hex[:6])
    work = Path(tempfile.mkdtemp(prefix="loki-bench-job-"))
    spec = {"task": task.id, "prompt": prompt, "model": job_model, "scripted": scripted, "scenario": scenario,
            "lane": lane, "job_id": job_id, "allow_commands": allow_commands, "profile": profile or {},
            "result_path": str(work / "result.txt"), "metrics_path": str(work / "metrics.json"),
            "deadline_s": deadline}
    spec_path = work / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    env = _child_env(ws, job_id, extra, scripted, data, no_escalate, team_id,
                     str((profile or {}).get("name") or ""))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    timed_out = False
    with open(log_path, "wb") as log:
        kwargs = {"cwd": str(ws), "stdout": log, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "env": env}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve()), "--child", str(spec_path)],
                                **kwargs)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait(timeout=30)
    seconds = round(time.monotonic() - started, 2)
    try:
        metrics = json.loads((work / "metrics.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        metrics = {}
    try:
        final = (work / "result.txt").read_text(encoding="utf-8").strip()
    except OSError:
        final = ""
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    if not final and not timed_out:
        # an old engine writes no result on a BLOCKED exit: take the last DONE/BLOCKED line of the log
        lines = [ln for ln in log_text.splitlines() if _DONE_RE.match(ln)]
        final = lines[-1].strip() if lines else ""
    shutil.rmtree(work, ignore_errors=True)
    code = metrics.get("exit")
    if timed_out:
        status = "timeout"
    elif metrics.get("crash") or code is None:
        status = "error"
    elif code in (2, 3, 4):
        status = "blocked"
    elif outcome_line(final, "DONE"):
        status = "done"
    elif task.expect == "answer" and code == 0 and final and not outcome_line(final, "BLOCKED"):
        status = "answer"
    else:
        status = "unfinished"
    return {"status": status, "final": final, "exit": code, "seconds": metrics.get("seconds", seconds),
            "steps": metrics.get("steps", 0), "tool_calls": metrics.get("tool_calls", 0),
            "tokens": int(metrics.get("tokens_in", 0)) + int(metrics.get("tokens_out", 0)),
            "max_prompt_chars": metrics.get("max_prompt_chars", 0), "escalated": metrics.get("escalated", ""),
            "crash": (metrics.get("crash") or "")[:600], "played": metrics.get("played", []),
            "not_offered": metrics.get("not_offered", []),
            "done_line": outcome_line(final, "DONE"), "log": str(log_path)}


class BenchJobs:
    """What team.TeamRunner needs from workers.Supervisor: each role's job runs at once, in
    order, through the same real run_job child as every other task."""

    def __init__(self, run) -> None:
        self.run = run
        self.jobs: dict = {}
        self.store = types.SimpleNamespace(get=self.jobs.get, update=self._update, all=lambda: list(self.jobs.values()))

    def _update(self, job_id: str, **fields) -> None:
        self.jobs.setdefault(job_id, {}).update(fields)

    def create(self, spec: dict) -> dict:
        role = str((spec.get("profile") or {}).get("role") or "builder")
        prompt = str(spec.get("prompt") or "")
        lane = role + ("#fix" if "FIX ROUND" in prompt else "#recheck" if "Re-check after the fix round" in prompt else "")
        record = self.run(spec, role, lane)
        job_id = "job-%s-%d" % (role, len(self.jobs))
        self.jobs[job_id] = {"id": job_id, "status": "done" if record.get("exit") == 0 else "failed",
                             "output": record.get("final") or record.get("crash") or record.get("status"),
                             "record": record, "role": role}
        return {"id": job_id}

    def tick(self) -> None:
        return None

    def cancel(self, job_id: str) -> None:
        return None


def _known_urls(task) -> list | None:
    if not task.web:
        return None
    urls = [r["url"] for r in task.web.get("results", [])] + list(task.web.get("pages", {}))
    return sorted(set(urls))


def _setup(task, ws: Path) -> None:
    for rel, content in task.files.items():
        path = ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")


def _expected(task, status: str) -> bool:
    if task.expect == "answer":
        return status in ("answer", "done")
    return status == task.expect


def run_task(task, model: str, *, scripted: bool, scenario: str, logs: Path, data: Path,
             timeout: float = 0, keep: bool = False, no_escalate: bool = False) -> dict:
    tasks = _tasks_module()
    ws = Path(tempfile.mkdtemp(prefix="loki-bench-%s-" % task.id))
    _setup(task, ws)
    if task.deadline_s:
        deadline = float(task.deadline_s)
        limit = timeout or (deadline + 15 if scripted else deadline + 120)
    else:
        limit = timeout or (SCRIPTED_TIMEOUT_S if scripted else REAL_TIMEOUT_S)
        deadline = max(5.0, limit - (10 if scripted else 60))
    started = time.monotonic()
    team_info: dict = {}
    if task.team:
        record = _run_team(task, model, ws, scripted=scripted, scenario=scenario, logs=logs, data=data,
                           limit=limit, deadline=deadline, no_escalate=no_escalate, team_info=team_info)
    else:
        record = run_job_child(task=task, prompt=task.prompt, ws=ws, model=model, scripted=scripted, scenario=scenario,
                               lane="small", data=data, log_path=logs / ("%s.log" % task.id), timeout=limit,
                               deadline=deadline, allow_commands=task.allow_commands, no_escalate=no_escalate)
    result = dict(record, team=team_info, known_urls=_known_urls(task) if scripted else None)
    reasons = []
    if not _expected(task, record["status"]):
        why = {"timeout": "timed out after %ds (nothing saved)" % int(limit),
               "error": "crashed: %s" % (record.get("crash") or "no result").splitlines()[0][:200],
               "unfinished": "ended without DONE or BLOCKED: %s" % ((record.get("final") or "(nothing)").splitlines() or [""])[0][:160],
               }.get(record["status"], "ended %s, expected %s: %s" % (
                   record["status"].upper(), task.expect.upper(), ((record.get("final") or "").splitlines() or [""])[0][:160]))
        reasons.append(why)
    if record.get("not_offered"):
        reasons.append("the model needed a tool LOKI did not offer it: %s" % ", ".join(record["not_offered"]))
    for check in list(task.checks) + list(tasks.ALWAYS):
        try:
            why = check(ws, result)
        except Exception as exc:  # noqa: BLE001 - a broken check is a failed check
            why = "check %s crashed: %s" % (getattr(check, "__name__", "?"), exc)
        if why:
            reasons.append(why)
    if not keep:
        shutil.rmtree(ws, ignore_errors=True)
    return {"id": task.id, "kind": task.kind, "expect": task.expect, "behaviour": task.behaviour,
            "ok": not reasons, "reason": "; ".join(reasons)[:500], "status": record["status"],
            "steps": record["steps"], "tool_calls": record["tool_calls"], "tokens": record["tokens"],
            "seconds": round(time.monotonic() - started, 1), "escalated": record.get("escalated", ""),
            "max_prompt_chars": record.get("max_prompt_chars", 0),
            "final": (record.get("final") or "")[:400], "log": record.get("log", ""),
            "workspace": str(ws) if keep else "", "team": team_info or None}


def _run_team(task, model, ws, *, scripted, scenario, logs, data, limit, deadline, no_escalate, team_info) -> dict:
    sys.path.insert(0, str(ENGINE)) if str(ENGINE) not in sys.path else None
    import team as team_mod  # noqa: E402  pylint: disable=import-outside-toplevel
    totals = {"steps": 0, "tool_calls": 0, "tokens": 0, "escalated": "", "max_prompt_chars": 0}
    holder: dict = {}
    started = time.monotonic()

    def run(spec: dict, role: str, lane: str) -> dict:
        lanes = task.scripts.get(scenario or "small") or {}
        use = lane if (not scripted or lane in lanes) else role
        left = max(10.0, limit - (time.monotonic() - started))
        record = run_job_child(task=task, prompt=spec["prompt"], ws=ws, model=model, scripted=scripted,
                               scenario=scenario, lane=use, data=data,
                               log_path=logs / ("%s.%s.%d.log" % (task.id, role, len(holder))), timeout=left,
                               deadline=min(deadline, max(5.0, left - 10)), allow_commands=bool(spec.get("allow_commands")),
                               profile=spec.get("profile"), no_escalate=no_escalate, team_id=holder.get("team", ""))
        holder[len(holder)] = record
        for k in ("steps", "tool_calls", "tokens"):
            totals[k] += int(record.get(k) or 0)
        totals["max_prompt_chars"] = max(totals["max_prompt_chars"], int(record.get("max_prompt_chars") or 0))
        totals["escalated"] = totals["escalated"] or record.get("escalated", "")
        totals["not_offered"] = sorted(set(totals.get("not_offered", [])) | set(record.get("not_offered") or []))
        members.append({"role": lane, "status": record["status"], "final": (record.get("final") or "")[:200]})
        return record

    members: list = []

    jobs = BenchJobs(run)
    runner = team_mod.TeamRunner(jobs, policy=None, decide=None)
    # the team id must be known before the first agent starts: start a dry copy to read the id path
    original_tick = runner.tick

    def tick_once() -> None:
        return None
    runner.tick = tick_once
    team = runner.start(task.prompt, str(ws), model="" if scripted else _model_env(model, False)[0])
    holder["team"] = team["id"]
    runner.tick = original_tick
    status = "error"
    for _ in range(12):
        runner.tick()
        team = runner.get(team["id"]) or team
        if team.get("status") in team_mod.FINAL:
            status = "done" if team.get("status") == "done" else "blocked"
            break
        if time.monotonic() - started > limit:
            status = "timeout"
            break
    team_info.update({"id": team.get("id"), "verdict": team.get("verdict", ""), "roles": team.get("roles", []),
                      "jobs": {k: jobs.jobs.get(v, {}).get("status") for k, v in (team.get("jobs") or {}).items()},
                      "members": members})
    verdict = str(team.get("verdict") or "")
    final = ("DONE: team %s" % verdict) if verdict.startswith("verified") else (
        "BLOCKED: team %s" % (verdict or "did not finish"))
    if status == "done" and not verdict.startswith("verified"):
        status = "blocked"
    return dict(totals, status=status, final=final, exit=0 if status == "done" else 2, done_line="",
                log=str(logs / ("%s.*.log" % task.id)))


# ============================================================================== reporting

def summarize(model: str, rows: list, scripted: bool, scenario: str, started: float) -> dict:
    passed = sum(1 for r in rows if r["ok"])
    return {"model": model, "scripted": scripted, "scenario": scenario if scripted else "",
            "passed": passed, "total": len(rows), "rate": round(passed / len(rows), 3) if rows else 0.0,
            "seconds": round(sum(r["seconds"] for r in rows), 1),
            "steps": sum(r["steps"] for r in rows), "tokens": sum(r["tokens"] for r in rows),
            "escalated": sum(1 for r in rows if r.get("escalated")),
            "timeouts": sum(1 for r in rows if r["status"] == "timeout"),
            "started": started, "finished": time.time(), "host": platform.node(), "os": sys.platform,
            "tasks": rows}


def markdown(report: dict) -> str:
    runs = report.get("runs") or {}
    out = ["# LOKI task-success benchmark - %s" % report.get("date", ""), "",
           "| model | passed | rate | steps | tokens | time | escalated | timeouts |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, run in runs.items():
        out.append("| %s | %d/%d | %d%% | %d | %d | %ds | %d | %d |" % (
            name, run["passed"], run["total"], round(100 * run["rate"]), run["steps"], run["tokens"],
            int(run["seconds"]), run["escalated"], run["timeouts"]))
    for name, run in runs.items():
        out += ["", "## %s%s" % (name, " (scripted: %s)" % run.get("scenario") if run.get("scripted") else ""), "",
                "| task | kind | expect | result | status | steps | tools | tokens | secs | why it failed |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in run["tasks"]:
            out.append("| %s | %s | %s | %s | %s%s | %d | %d | %d | %.0f | %s |" % (
                r["id"], r["kind"], r["expect"], "PASS" if r["ok"] else "FAIL", r["status"],
                " (escalated to %s)" % r["escalated"] if r.get("escalated") else "", r["steps"], r["tool_calls"],
                r["tokens"], r["seconds"], (r["reason"] or "").replace("|", "/")[:180]))
    return "\n".join(out) + "\n"


def save(report_runs: dict, out: Path, date: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / ("%s.json" % date)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = {"date": date, "runs": {}}
    report.setdefault("runs", {}).update(report_runs)
    report["date"] = date
    report["updated"] = time.time()
    text = json.dumps(report, indent=1)
    path.write_text(text, encoding="utf-8")
    (out / "latest.json").write_text(text, encoding="utf-8")
    (out / ("%s.md" % date)).write_text(markdown(report), encoding="utf-8")
    return path


def latest(out: Path | None = None) -> dict:
    """The newest report, trimmed for Settings > Lab: per model the score and each task's result."""
    try:
        report = json.loads(((out or bench_dir()) / "latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": True, "date": "", "runs": []}
    runs = []
    for name, run in (report.get("runs") or {}).items():
        runs.append({"model": name, "passed": run.get("passed", 0), "total": run.get("total", 0),
                     "rate": run.get("rate", 0), "seconds": run.get("seconds", 0), "escalated": run.get("escalated", 0),
                     "scripted": bool(run.get("scripted")), "finished": run.get("finished", 0),
                     "failed": [{"id": t["id"], "reason": t.get("reason", "")[:160]} for t in run.get("tasks", [])
                                if not t.get("ok")][:12]})
    return {"ok": True, "date": report.get("date", ""), "runs": runs}


# ============================================================================== main

def run_bench(models: list, *, scripted: bool = False, scenario: str = "small", only: list | None = None,
              kind: str = "", jobs: int = 0, timeout: float = 0, out: Path | None = None, keep: bool = False,
              no_escalate: bool = False, say=print) -> dict:
    tasks = _tasks_module()
    chosen = [t for t in tasks.TASKS if (not only or t.id in only) and (not kind or t.kind == kind)]
    if scripted:
        chosen = [t for t in chosen if t.scripts.get(scenario)]
    out = out or bench_dir()
    date = time.strftime("%Y-%m-%d")
    runs: dict = {}
    for model in models:
        label = ("scripted-" + scenario) if scripted else model
        data = Path(tempfile.mkdtemp(prefix="loki-bench-data-")) if scripted else data_dir()
        logs = out / "logs" / date / re.sub(r"[^\w.-]+", "_", label)
        started = time.time()
        say("== %s: %d tasks%s" % (label, len(chosen), "" if scripted else " (model %s)" % model))
        workers = jobs or (min(6, os.cpu_count() or 2) if scripted else 1)
        lock = threading.Lock()
        rows: list = []

        def one(task):
            row = run_task(task, model, scripted=scripted, scenario=scenario, logs=logs, data=data,
                           timeout=timeout, keep=keep, no_escalate=no_escalate)
            with lock:
                rows.append(row)
                say("  %-22s %s  %-10s %3d steps %5.1fs  %s" % (task.id, "PASS" if row["ok"] else "FAIL", row["status"],
                                                               row["steps"], row["seconds"], row["reason"][:150]))
            return row
        singles = [t for t in chosen if not t.team]
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(one, singles))
        for t in chosen:
            if t.team:
                one(t)
        order = {t.id: i for i, t in enumerate(chosen)}
        rows.sort(key=lambda r: order[r["id"]])
        runs[label] = summarize(model, rows, scripted, scenario, started)
        say("== %s: %d/%d passed" % (label, runs[label]["passed"], runs[label]["total"]))
        if scripted:
            shutil.rmtree(data, ignore_errors=True)
    path = save(runs, out, date)
    say("wrote %s and %s" % (path, path.with_suffix(".md")))
    return {"date": date, "runs": runs, "path": str(path)}


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--child"]:
        return child_main(argv[1])
    parser = argparse.ArgumentParser(description="LOKI's task-success benchmark (see the module docstring)")
    parser.add_argument("--model", default="local", help="comma list: local, bonsai, smart, groq, openrouter, claude-code ...")
    parser.add_argument("--scripted", action="store_true", help="scripted fake models and fixtures (no model needed)")
    parser.add_argument("--scenario", default="small", help="the scripted behaviour to play (small, cheat)")
    parser.add_argument("--tasks", default="", help="comma list of task ids")
    parser.add_argument("--kind", default="", help="only tasks of this kind")
    parser.add_argument("--jobs", type=int, default=0, help="tasks at once (default 1 for a real model)")
    parser.add_argument("--timeout", type=float, default=0, help="seconds per task (default 900 real, 60 scripted)")
    parser.add_argument("--out", default="", help="where to write the report (default harness_data/bench)")
    parser.add_argument("--keep", action="store_true", help="keep each task's workspace")
    parser.add_argument("--no-escalate", action="store_true", help="never hand a stuck job to a stronger model")
    parser.add_argument("--strict", action="store_true", help="exit 1 when a task fails")
    parser.add_argument("--list", action="store_true", help="list the tasks")
    args = parser.parse_args(argv)
    if args.list:
        for t in _tasks_module().TASKS:
            print("%-22s %-9s %-7s %s" % (t.id, t.kind, t.expect, t.prompt[:90]))
        return 0
    models = [m.strip() for m in args.model.split(",") if m.strip()] or ["local"]
    if args.scripted:
        models = models[:1]
    result = run_bench(models, scripted=args.scripted, scenario=args.scenario,
                       only=[t.strip() for t in args.tasks.split(",") if t.strip()], kind=args.kind, jobs=args.jobs,
                       timeout=args.timeout, out=Path(args.out) if args.out else None, keep=args.keep,
                       no_escalate=args.no_escalate)
    failed = sum(r["total"] - r["passed"] for r in result["runs"].values())
    return 1 if (args.strict and failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
