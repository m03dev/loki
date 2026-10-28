"""System check: do LOKI's parts work TOGETHER on this machine, and what fixes the rest?

One click in the app (Settings > System check, or "Check everything" in the sidebar) runs an
ordered list of checks in a background thread. Each one exercises a real path through
LOKI - the smart route to a model, the agent's tool loop, the first layer, a background job
seen through the jobs API, the event stream and the world, a team board, the policy engine,
add-ons, specialists, local models, linked machines and the phone link - and returns

    {"id", "title", "status": "ok" | "warn" | "fail" | "skip", "detail": plain English,
     "fix": {"text", "ui", "action", "args", "label"} | None, "items": [...], "ms"}

`ui` names the Settings tab that fixes it ("settings:connections"); `action` names a SAFE
fix the engine may do on its own (apply_fix): switch a dead provider off, let used-up
providers back in, warm Laya, start Ollama, start the job runner, retry local Z-Image.
Nothing here approves an add-on, applies an update or spends money: paid providers are only
checked for a key unless the person allows it, and a real image is made only when they
click "Run a real image test". Every network call has a short timeout and the whole run
stays under about a minute.

Every outside dependency can be replaced through Context.deps, so tests/test_systems.py runs
the same checks offline with fakes only at the edges.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Callable

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
BUDGET_S = float(os.getenv("LOKI_SYSTEM_CHECK_BUDGET", "60") or 60)
PROVIDER_TIMEOUT_S = 10.0
LOCAL_TIMEOUT_S = 25.0
TOOL_TIMEOUT_S = 30.0
JOB_TIMEOUT_S = 45.0
ENGINE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- shapes
def fix(text: str, ui: str = "", action: str = "", args: dict | None = None, label: str = "") -> dict:
    return {"text": text, "ui": ui, "action": action, "args": dict(args or {}),
            "label": label or ("Fix" if action else "Open")}


def result(check_id: str, title: str, status: str, detail: str, fix_: dict | None = None,
           items: list | None = None, **data: Any) -> dict:
    out = {"id": check_id, "title": title, "status": status, "detail": detail, "fix": fix_,
           "items": list(items or [])}
    if data:
        out["data"] = data
    return out


class Context:
    """What one run may use: the engine (loki module), the bridge state, the options, and
    replaceable dependencies (tests pass fakes)."""

    def __init__(self, agent: Any, state: Any = None, allow_paid: bool = False, image_test: bool = False,
                 deps: dict | None = None, budget_s: float = BUDGET_S) -> None:
        self.agent = agent
        self.state = state
        self.allow_paid = bool(allow_paid)
        self.image_test = bool(image_test)
        self.deps = dict(deps or {})
        self.shared: dict = {}
        self.deadline = time.monotonic() + budget_s

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def dep(self, name: str, default: Callable[[], Any]) -> Any:
        if name not in self.deps:
            self.deps[name] = default()
        return self.deps[name]

    def module(self, name: str) -> Any:
        return self.dep(name, lambda: __import__(name))


def _label(pid: str) -> str:
    try:
        import providers_catalog  # pylint: disable=import-outside-toplevel
        return (providers_catalog.get(pid) or {}).get("name") or pid
    except Exception:  # noqa: BLE001
        return pid


def _ago(t: float) -> str:
    if not t:
        return "never"
    s = max(0, int(time.time() - float(t)))
    return "%ds ago" % s if s < 60 else "%d min ago" % (s // 60) if s < 3600 else "%d h ago" % (s // 3600)


# --------------------------------------------------------------------------- 1. engine + updates
def check_engine(ctx: Context) -> dict:
    title = "Engine & updates"
    updater = ctx.module("updater")
    try:
        u = updater.status()
    except Exception as exc:  # noqa: BLE001
        return result("engine", title, FAIL, "LOKI could not read its own version: %s" % exc,
                      fix("Open Machines & updates", "settings:machines"))
    label = u.get("label") or u.get("commit") or "unknown version"
    py = "Python %s on %s" % (sys.version.split()[0], {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, sys.platform))
    problem, error = str(u.get("problem") or ""), str(u.get("error") or "")
    head = "LOKI %s, %s." % (label, py)
    if problem or error:
        why = problem or "update failed"
        if why == "GitHub sign-in needed":
            try:
                hint = updater.sign_in_hint()
            except Exception:  # noqa: BLE001
                hint = "Sign in to GitHub (gh auth login, then gh auth setup-git)."
            todo = fix(hint, "settings:machines", label="Open")
        elif why == "local edits block the update":
            todo = fix("Local edits on this machine stop the update: ship them (tools/ship.py) or undo them, "
                       "then restart LOKI.", "settings:machines")
        elif why == "LOKI folder missing":
            todo = fix(error or "The LOKI folder is missing - attach its disk, then restart LOKI.", "settings:machines")
        elif why == "GitHub unreachable":
            todo = fix("GitHub cannot be reached from here. Check the internet; LOKI tries again on its own.",
                       "settings:machines")
        else:
            todo = fix("Open Machines & updates and press Update everything; if it fails again, the error "
                       "above says why.", "settings:machines")
        return result("engine", title, FAIL, "%s Updates are not applying: %s%s" % (
            head, why, (" - " + error[:240]) if error and error != why else ""), todo, label=label)
    if not u.get("git"):
        return result("engine", title, WARN, head + " This copy is not a git checkout, so it cannot update "
                      "itself; it becomes one the next time LOKI starts.", fix("Restart LOKI", "settings:machines"))
    if not u.get("enabled", True):
        return result("engine", title, WARN, head + " Automatic updates are switched off.",
                      fix("Turn on 'Update automatically' in General", "settings:general"))
    try:
        restart = bool(updater.restart_needed())
    except Exception:  # noqa: BLE001
        restart = False
    if restart:
        return result("engine", title, WARN, head + " A newer version is already on disk; LOKI uses it after a "
                      "restart.", fix("Restart LOKI to use it (Machines & updates)", "settings:machines"))
    if u.get("update_available"):
        return result("engine", title, WARN, head + " A newer LOKI is waiting on GitHub.",
                      fix("Update everything", "settings:machines", label="Update"))
    checked = u.get("checked") or 0
    return result("engine", title, OK, head + (" Up to date (checked %s)." % _ago(checked) if checked
                                               else " Update checks run in the background."), label=label)


# --------------------------------------------------------------------------- 2. models (smart route)
def route_order(agent: Any) -> list:
    """The providers in the order a request tries them right now (what active_model_name
    walks), with the pinned model first. Used-up marks are ignored: the check tests them."""
    mode = getattr(agent, "model_name", "smart")
    order = []
    if mode not in ("smart", "online", "max", "fast") and mode in agent.MODELS:
        order.append(mode)
    if mode != "online":
        try:
            if getattr(agent, "PREFER", "local") == "local" and agent.local_ready():
                order.append("local")
        except Exception:  # noqa: BLE001
            pass
    base = agent.ONLINE_ORDER if mode == "online" else agent.SMART_ORDER
    try:
        base = agent.routing_order(base)
    except Exception:  # noqa: BLE001
        base = list(base)
    for name in base:
        if name not in order:
            order.append(name)
    return order


TRANSIENT = ("rate limited right now", "busy right now")


def provider_problem(detail: str, name: str) -> tuple:
    """(short reason, what to do) from a provider test's detail."""
    low = (detail or "").lower()
    if "rejected" in low or "401" in low or "invalid api key" in low or "unauthorized" in low:
        return "key rejected", "Replace %s's key in Connections, or switch it off." % name
    if any(w in low for w in ("no credit", "insufficient", "balance", "402", "billing", "quota")):
        return "out of credit", "Top up %s, or switch it off so LOKI stops trying it." % name
    if "no access" in low or "403" in low:
        return "no access to its model", "Pick another model for %s in Connections, or switch it off." % name
    if "not available here" in low or "404" in low:
        return "model not found", "Pick another model for %s in Connections." % name
    if "rate limited" in low or "429" in low:
        return "rate limited right now", "Nothing to do: the key works; LOKI waits and retries."
    if any(w in low for w in ("http 500", "http 502", "http 503", "http 504", "overloaded", "temporarily unavailable")):
        return "busy right now", "Nothing to do: its server is busy; LOKI moves on to the next provider meanwhile."
    if "not installed" in low:
        return "not installed", "Install it, or switch %s off." % name
    if "could not reach" in low or "timed out" in low or "timeout" in low:
        return "unreachable", "Check that %s is up (and the internet), or switch it off." % name
    return "error", "Test it again in Connections; switch it off if it keeps failing."


def _default_provider_test(agent: Any, pid: str, timeout: float) -> dict:
    import providers_catalog  # pylint: disable=import-outside-toplevel
    return (providers_catalog.test(agent, pid, timeout=timeout) or {}).get("test") or {}


def check_models(ctx: Context) -> dict:
    title = "Models (smart route)"
    agent = ctx.agent
    test = ctx.dep("provider_test", lambda: _default_provider_test)
    ready, off, paid = [], [], []
    for pid in route_order(agent):
        try:
            if agent.provider_disabled(pid):
                off.append(pid)
                continue
            if not agent.provider_configured(pid):
                continue
        except Exception:  # noqa: BLE001
            continue
        if agent.provider_tier(pid) == "paid" and not ctx.allow_paid:
            paid.append(pid)
            continue
        ready.append(pid)
    if not ready:
        why = "No model is ready: no provider has a key and no local model is running."
        if paid:
            why = "Only paid providers have keys (%s), and paid use is off." % ", ".join(_label(p) for p in paid)
        return result("models", title, FAIL, why, fix("Connect a free provider (Groq or Gemini take a minute), or "
                                                      "set up a local model", "settings:connections"),
                      items=[{"id": p, "name": _label(p), "status": SKIP, "detail": "paid - not tested"} for p in paid])
    timeout = min(PROVIDER_TIMEOUT_S, max(2.0, ctx.remaining() / 3))
    # A local model may still be loading into memory: give it longer for its first token.
    slow = {pid: max(timeout, min(LOCAL_TIMEOUT_S, ctx.remaining() / 2)) if agent.provider_tier(pid) == "local"
            else timeout for pid in ready}
    outcomes: dict = {}
    pool = ThreadPoolExecutor(max_workers=min(6, len(ready)))
    try:
        futures = {pid: pool.submit(test, agent, pid, slow[pid]) for pid in ready}
        waited_from = time.monotonic()
        for pid, future in futures.items():
            try:
                left = slow[pid] + 5 - (time.monotonic() - waited_from)
                outcomes[pid] = future.result(timeout=max(0.1, left)) or {}
            except FutureTimeout:
                outcomes[pid] = {"ok": False, "detail": "timed out after %ds" % int(slow[pid])}
            except Exception as exc:  # noqa: BLE001
                outcomes[pid] = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
    finally:
        pool.shutdown(wait=False)      # a hung provider must not hold the whole check
    items, dead, answered, limited, agents = [], [], "", [], []
    for pid in ready:
        out = outcomes.get(pid) or {}
        name = _label(pid)
        detail = str(out.get("detail") or "")
        if out.get("ok") and agent.provider_tier(pid) == "subscription":
            # A coding CLI is only checked for being installed (asking it costs your plan's time).
            agents.append(pid)
            items.append({"id": pid, "name": name, "status": OK, "detail": detail or "installed"})
        elif out.get("ok") and "rate limited" not in detail.lower():
            if not answered:
                answered = pid
            items.append({"id": pid, "name": name, "status": OK,
                          "detail": "answered in %d ms" % int(out.get("ms") or 0) + (
                              " (first in the route)" if pid == answered else "")})
        elif out.get("ok"):
            limited.append(pid)
            items.append({"id": pid, "name": name, "status": WARN, "detail": "rate limited right now (the key works)"})
        else:
            reason, todo = provider_problem(detail, name)
            if reason in TRANSIENT:
                limited.append(pid)
                items.append({"id": pid, "name": name, "status": WARN, "detail": "%s - %s" % (reason, detail[:160])})
                continue
            dead.append((pid, reason))
            items.append({"id": pid, "name": name, "status": FAIL, "detail": "%s - %s" % (reason, detail[:160]),
                          "fix": fix(todo, "settings:connections", "provider_off", {"id": pid},
                                     label="Switch off")})
    for pid in paid:
        items.append({"id": pid, "name": _label(pid), "status": SKIP,
                      "detail": "key set; paid, so not tested (tick 'Test paid providers too' for one tiny request)"})
    ctx.shared["answered_by"] = answered
    ctx.shared["answered_ms"] = int((outcomes.get(answered) or {}).get("ms") or 0) if answered else 0
    used_up = sorted(p for p in getattr(agent, "_SMART_FAILED", set()) if p in outcomes and (outcomes[p] or {}).get("ok"))
    notes = []
    if off:
        notes.append("Switched off: %s." % ", ".join(_label(p) for p in off))
    if used_up:
        notes.append("%s answered now but %s marked used up for this session." % (
            ", ".join(_label(p) for p in used_up), "is" if len(used_up) == 1 else "are"))
    dead_text = ", ".join("%s (%s)" % (_label(p), r) for p, r in dead)
    if limited and answered:
        notes.insert(0, "Busy or rate limited right now (LOKI retries them): %s." % ", ".join(_label(p) for p in limited))
    if not answered:
        if agents:
            return result("models", title, WARN, ("No model answered a test prompt%s; LOKI falls back to %s, which is "
                          "installed (its sign-in is checked on first use). %s" % (
                              (" (dead: %s)" % dead_text) if dead else "", ", ".join(_label(p) for p in agents),
                              " ".join(notes))).strip(),
                          fix("Connect a free provider so LOKI does not depend on one subscription", "settings:connections"),
                          items=items)
        if limited:
            return result("models", title, WARN, "Every ready provider is busy or rate limited right now (%s); LOKI "
                          "waits and retries. %s" % (", ".join(_label(p) for p in limited), " ".join(notes)),
                          fix("Connect one more free provider so LOKI has somewhere to go", "settings:connections"),
                          items=items)
        return result("models", title, FAIL, "None of the %d ready providers answered: %s. %s" % (
            len(ready), dead_text, " ".join(notes)), fix("Fix or replace these keys in Connections", "settings:connections"),
            items=items)
    first = "%s answered a tiny prompt through the smart route in %d ms." % (_label(answered), ctx.shared["answered_ms"])
    try:
        pick = agent.active_model_name()
    except Exception:  # noqa: BLE001
        pick = answered
    if pick != answered and pick in dict(dead):
        first += " The route still picks %s first, which is dead." % _label(pick)
    if dead:
        return result("models", title, WARN, ("%s %d %s dead: %s. %s" % (
            first, len(dead), "provider is" if len(dead) == 1 else "providers are", dead_text, " ".join(notes))).strip(),
            fix("Switch the dead ones off so LOKI stops trying them", "settings:connections", "provider_off",
                {"ids": [p for p, _ in dead]}, label="Switch them off"),
            items=items, answered=answered)
    todo = fix("Let LOKI use them again now", action="revive_providers", label="Use again") if used_up else None
    return result("models", title, OK, ("%s %d of %d ready providers work. %s" % (
        first, len([i for i in items if i["status"] == OK]), len(ready), " ".join(notes))).strip(), todo,
        items=items, answered=answered)


# --------------------------------------------------------------------------- 3. tool calling
SELF_TEST_FILES = ("loki-check-alpha.txt", "loki-check-beta.txt")


def _tool_schema(agent: Any) -> dict:
    for item in getattr(agent, "TOOL_SCHEMAS", []) or []:
        if (item.get("function") or {}).get("name") == "list_tree":
            return item
    return {"type": "function", "function": {"name": "list_tree", "description": "Show the project as a tree.",
                                             "parameters": {"type": "object", "properties": {
                                                 "subdir": {"type": "string"}}}}}


def _default_tool_client(agent: Any, pid: str):
    cfg = agent.MODELS[pid]
    return agent.AsyncOpenAI(base_url=cfg.base_url, api_key=str(cfg.api_key or "") or "local", timeout=20)


async def _tool_round(agent: Any, client: Any, cfg: Any, pid: str, folder: Path) -> dict:
    schema = _tool_schema(agent)
    messages = [{"role": "system", "content": "You are LOKI's self-test. When asked, call the list_tree tool. "
                                              "After the tool answers, reply with one short line naming the files."},
                {"role": "user", "content": "Call list_tree for the folder '.', then tell me the names of the files in it."}]
    kwargs = {"model": cfg.model, "messages": messages, "tools": [schema], "max_tokens": 400}
    if "11434" in str(cfg.base_url) or "ollama" in str(cfg.api_key):
        kwargs["extra_body"] = {"think": False}
    first = await agent._model_request(client, kwargs, cfg, pid)  # pylint: disable=protected-access
    message = first.choices[0].message
    calls = list(getattr(message, "tool_calls", None) or [])
    listing = "\n".join(sorted(p.name for p in folder.iterdir()))
    if calls:
        call = calls[0]
        if getattr(call.function, "name", "") != "list_tree":
            return {"called": False, "detail": "it called %s instead of list_tree" % call.function.name}
        messages.append(agent._as_dict(message))  # pylint: disable=protected-access
        messages.append({"role": "tool", "tool_call_id": getattr(call, "id", "") or "call_0", "content": listing})
    else:
        recovered = agent._recover_text_tool_calls(getattr(message, "content", "") or "")  # pylint: disable=protected-access
        if not recovered:
            return {"called": False, "detail": "it answered in text and never called the tool"}
        messages.append({"role": "assistant", "content": getattr(message, "content", "") or ""})
        messages.append({"role": "user", "content": "Result of list_tree:\n" + listing})
    kwargs["messages"] = messages
    second = await agent._model_request(client, kwargs, cfg, pid)  # pylint: disable=protected-access
    reply = str(getattr(second.choices[0].message, "content", "") or "")
    return {"called": True, "read_back": "alpha" in reply.lower() or "beta" in reply.lower(), "reply": reply[:200],
            "prompted": bool(agent.tool_harness.configured(pid)) if hasattr(agent, "tool_harness") else False}


def check_tools(ctx: Context) -> dict:
    title = "Tool calling (agent loop)"
    agent = ctx.agent
    pid = ctx.shared.get("answered_by") or ""
    if not pid:
        return result("tools", title, SKIP, "No model answered, so tool calling could not be tried.")
    cfg = agent.MODELS.get(pid)
    if cfg is None or str(cfg.base_url).startswith(getattr(agent, "CLI_AGENT_PREFIX", "cli-agent://")):
        return result("tools", title, SKIP, "%s is a subscription agent that runs its own tools; nothing to test "
                      "here." % _label(pid))
    if ctx.remaining() < 8:
        return result("tools", title, SKIP, "Skipped: the check ran out of time.")
    folder = Path(getattr(agent, "DATA_DIR", ".")) / "system_check" / ("tools-" + uuid.uuid4().hex[:6])
    folder.mkdir(parents=True, exist_ok=True)
    for name in SELF_TEST_FILES:
        (folder / name).write_text("LOKI system check\n", encoding="utf-8")
    failed_before = set(getattr(agent, "_SMART_FAILED", set()))
    started = time.monotonic()
    try:
        client = ctx.dep("tool_client", lambda: _default_tool_client)(agent, pid)
        out = asyncio.run(asyncio.wait_for(_tool_round(agent, client, cfg, pid, folder),
                                           timeout=min(TOOL_TIMEOUT_S, ctx.remaining())))
    except asyncio.TimeoutError:
        out = {"error": "no answer within %d s" % int(min(TOOL_TIMEOUT_S, ctx.remaining()))}
    except Exception as exc:  # noqa: BLE001
        out = {"error": "%s: %s" % (type(exc).__name__, getattr(exc, "hint", None) or exc)}
    finally:
        # The check must not change routing: forget any used-up mark it caused.
        marks = getattr(agent, "_SMART_FAILED", None)
        if isinstance(marks, set):
            for name in list(marks - failed_before):
                marks.discard(name)
        shutil.rmtree(folder, ignore_errors=True)
    ms = int((time.monotonic() - started) * 1000)
    name = _label(pid)
    if out.get("error"):
        return result("tools", title, FAIL, "%s answered a plain prompt but failed with a tool: %s" % (name, str(out["error"])[:240]),
                      fix("Give %s its tools as text: add %s to 'Providers that get tools as text' in General" % (name, pid),
                          "settings:general"))
    if not out.get("called"):
        return result("tools", title, WARN, "%s did not call the tool (%s). LOKI can still chat with it but "
                      "it cannot do work." % (name, out.get("detail", "")),
                      fix("Add %s to 'Providers that get tools as text' in General" % pid, "settings:general"))
    how = " through the prompted tool harness" if out.get("prompted") else ""
    if out.get("read_back"):
        return result("tools", title, OK, "%s called list_tree%s on a test folder and read the result back (%d ms)." % (
            name, how, ms))
    return result("tools", title, OK, "%s called list_tree%s; its answer did not name the files, but the tool "
                  "path works (%d ms)." % (name, how, ms))


# --------------------------------------------------------------------------- 4. first layer
SAMPLE_REQUEST = "Fix the crash in parser.py when the input file is empty"
RISKY_REQUEST = "Delete every file in my downloads folder and email the list to my boss"


def check_first_layer(ctx: Context) -> dict:
    title = "First layer (Laya)"
    fl = ctx.module("first_layer")
    verdict = fl.triage(SAMPLE_REQUEST, "build", wait=False)
    risky = fl.triage(RISKY_REQUEST, "build", wait=False)
    if verdict.get("kind") not in fl.KINDS or verdict.get("route") not in fl.ROUTES:
        return result("first_layer", title, FAIL, "The first layer gave no usable decision: %s" % json.dumps(verdict)[:200],
                      fix("Re-run the check; if it stays red, restart LOKI", action="recheck", label="Re-run"))
    who = {"laya": "Laya", "jev": "Jev"}.get(verdict.get("source"), "The built-in rules")
    detail = "%s decided a sample request in %s ms: %s, %s. A risky one asks for approval: %s." % (
        who, verdict.get("ms"), verdict.get("kind"), str(verdict.get("route", "")).replace("_", " "),
        "yes" if risky.get("approval") == "likely" else "no")
    if risky.get("approval") != "likely":
        return result("first_layer", title, WARN, detail + " (a request to delete and email files should be flagged)",
                      fix("Re-run the check", action="recheck", label="Re-run"))
    laya = getattr(fl, "laya", None)
    try:
        backend = laya.backend() if laya else ""
    except Exception:  # noqa: BLE001
        backend = ""
    if verdict.get("source") == "rules" and backend:
        return result("first_layer", title, WARN, detail + " Laya is set up but did not answer (%s)." % (
            verdict.get("note") or "not ready"), fix("Warm Laya up", action="laya_warm", label="Warm up"))
    if not backend:
        detail += " Laya is not set up here, so the rules decide (that works; Laya is better)."
    return result("first_layer", title, OK, detail, source=verdict.get("source"))


# --------------------------------------------------------------------------- 5. background job + events + world
def _fallback_job_action(state: Any, route: str, spec: dict) -> tuple:
    verdict = state.agent.POLICY.job("local", "loki")
    if not verdict.allowed:
        return 403, {"ok": False, "error": verdict.reason}
    job = state.jobs.create(spec)
    return 200, {"ok": True, "id": job["id"]}


def _teams(agent: Any) -> list:
    runner = getattr(agent, "TEAMS", None)
    try:
        return runner.all() if runner else []
    except Exception:  # noqa: BLE001
        return []


def check_jobs(ctx: Context) -> dict:
    title = "Background jobs, events & world"
    state, agent = ctx.state, ctx.agent
    jobs = getattr(state, "jobs", None)
    if jobs is None:
        return result("jobs", title, FAIL, "Background jobs are not running in this engine.",
                      fix("Restart LOKI; background agents start with it", "settings:machines"))
    if hasattr(jobs, "running") and not jobs.running():
        return result("jobs", title, FAIL, "The job runner is stopped, so background agents never start.",
                      fix("Start the job runner", action="jobs_start", label="Start"))
    if ctx.remaining() < 10:
        return result("jobs", title, SKIP, "Skipped: the check ran out of time before this step (run it again).")
    events = ctx.module("events")
    workspace = Path(getattr(agent, "DATA_DIR", ".")) / "system_check" / "job"
    workspace.mkdir(parents=True, exist_ok=True)
    mark = events.latest_seq()
    action = ctx.dep("job_action", lambda: _fallback_job_action)
    code, reply = action(state, "/jobs", {
        "backend": "local", "agent": "loki", "prompt": "System check: prove a background agent runs here.",
        "title": "System check · background job", "workspace": str(workspace), "isolate": False,
        "timeout_s": 60, "selfcheck": True})
    if code != 200 or not reply.get("ok"):
        return result("jobs", title, FAIL, "A background job was refused: %s" % reply.get("error", code),
                      fix("Open Add-ons: the policy refused the built-in agent", "settings:capabilities"))
    job_id = reply["id"]
    started = time.monotonic()
    limit = min(JOB_TIMEOUT_S, max(5.0, ctx.remaining() - 5))
    job = {}
    seen_states = []
    while time.monotonic() - started < limit:
        try:
            jobs.tick()
        except Exception:  # noqa: BLE001
            pass
        listed = [j for j in jobs.status().get("jobs", []) if j.get("id") == job_id]   # what GET /jobs serves
        job = listed[0] if listed else {}
        if job.get("status") and (not seen_states or seen_states[-1] != job["status"]):
            seen_states.append(job["status"])
        if job.get("status") in ("done", "failed", "cancelled"):
            break
        time.sleep(0.3)
    secs = time.monotonic() - started
    raw = jobs.store.get(job_id) or {}
    world = events.world(jobs.store.all(), _teams(agent), False)
    in_world = [a for a in world.get("agents", []) if a.get("id") == "job-" + job_id]
    kinds = [e.get("type") for e in events.read(mark, limit=2000) if e.get("task") == job_id]
    try:
        if raw.get("status") in ("done", "failed", "cancelled"):
            jobs.store.remove(job_id)
            for suffix in (".log", ".job.json", ".result.txt"):
                (Path(jobs.data_dir) / "jobs" / (job_id + suffix)).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    if job.get("status") != "done":
        if not job.get("status") or job.get("status") not in ("done", "failed", "cancelled"):
            try:
                jobs.cancel(job_id)
            except Exception:  # noqa: BLE001
                pass
            return result("jobs", title, FAIL, "The test job did not finish in %d s (states seen: %s)." % (
                int(limit), " > ".join(seen_states) or "none"), fix("Restart LOKI, then run the check again", "settings:machines"))
        return result("jobs", title, FAIL, "The test job %s: %s" % (job.get("status"), (job.get("error") or
                      job.get("output") or "")[-240:]), fix("Run the check again; if it stays red, send the job "
                                                             "log (harness_data/jobs) to Claude", action="recheck",
                                                             label="Re-run"))
    missing = [k for k in ("task.created", "task.started", "task.completed") if k not in kinds]
    if missing:
        return result("jobs", title, FAIL, "The job ran, but the event stream is missing %s." % ", ".join(missing),
                      fix("Re-run the check", action="recheck", label="Re-run"))
    if not in_world or in_world[0].get("state") != "done":
        return result("jobs", title, FAIL, "The job ran and its events arrived, but the live view (GET /world) did not show it "
                      "as done (%s)." % (in_world[0].get("state") if in_world else "not there"),
                      fix("Re-run the check", action="recheck", label="Re-run"))
    return result("jobs", title, OK, "A background agent started on this computer, finished in %.1f s (%s), and "
                  "showed up in the event stream (%s) and in the live view as %s." % (
                      secs, " > ".join(seen_states), ", ".join(dict.fromkeys(kinds)), in_world[0].get("name")))


# --------------------------------------------------------------------------- 6. teams
def check_teams(ctx: Context) -> dict:
    title = "Agent teams"
    agent = ctx.agent
    runner = getattr(agent, "TEAMS", None)
    if runner is None:
        return result("teams", title, FAIL, "Agent teams are not running in this engine.",
                      fix("Restart LOKI; teams start with the job runner", "settings:machines"))
    events = ctx.module("events")
    team_mod = ctx.dep("team", lambda: getattr(agent, "teams", None) or __import__("team"))
    workspace = Path(getattr(agent, "DATA_DIR", ".")) / "system_check" / "team"
    workspace.mkdir(parents=True, exist_ok=True)
    mark = events.latest_seq()
    try:
        team = runner.start("System check: plan a tiny notes app with a test", str(workspace), dry_run=True)
    except TypeError:
        return result("teams", title, FAIL, "This engine's team runner has no dry run (old code is running).",
                      fix("Restart LOKI to load the new version", "settings:machines"))
    except ValueError as exc:
        return result("teams", title, FAIL, "A team could not start: %s" % exc,
                      fix("Open Add-ons: the policy refused the built-in agent", "settings:capabilities"))
    team_id = team["id"]
    posts = team_mod.board(team_id)
    kinds = [(e.get("type"), e.get("sender")) for e in events.read(mark, limit=2000) if e.get("team") == team_id]
    jobs = getattr(ctx.state, "jobs", None)
    world = events.world(jobs.store.all() if jobs is not None else [], runner.all(), False)
    listed = [t for t in world.get("teams", []) if t.get("id") == team_id]
    try:
        runner.forget(team_id)
    except Exception:  # noqa: BLE001
        pass
    problems = []
    if len(posts) < 2:
        problems.append("the board has %d post(s)" % len(posts))
    if ("agent.message", "LOKI") not in kinds:
        problems.append("its board posts never reached the event stream")
    if "verification.completed" not in [k for k, _ in kinds]:
        problems.append("its result was never announced")
    if not listed:
        problems.append("the live view did not list it")
    if problems:
        return result("teams", title, FAIL, "A team dry run went wrong: %s." % "; ".join(problems),
                      fix("Re-run the check", action="recheck", label="Re-run"))
    return result("teams", title, OK, "A team was planned (%s), posted %d notes on its board, and appeared in "
                  "the event stream and in the live view. No agent was started for this test." % (
                      ", ".join(team.get("roles") or []) or "roles chosen", len(posts)))


# --------------------------------------------------------------------------- 7. safety
def check_policy(ctx: Context) -> dict:
    title = "Safety & approvals"
    agent = ctx.agent
    pol = getattr(agent, "POLICY", None)
    if pol is None:
        return result("policy", title, FAIL, "The policy engine is missing.", fix("Restart LOKI", "settings:machines"))
    cases = [
        ("a destructive command is refused", pol.tool_call("run_command", {"command": "rm -rf /"}).decision, "deny"),
        ("a file outside the project is refused", pol.tool_call("read_file", {"filename": "../../../etc/passwd"}).decision, "deny"),
        ("deleting a file always asks you", pol.tool_call("delete_file", {"path": "notes.txt"}).decision, "ask"),
        ("reading the project is allowed", pol.tool_call("list_tree", {}).decision, "allow"),
        ("the built-in background agent is allowed", pol.job("local", "loki").decision, "allow"),
    ]
    wrong = ["%s (got %s)" % (name, got) for name, got, want in cases if got != want]
    if getattr(agent, "AUTO_APPROVE", False):
        return result("policy", title, FAIL, "LOKI_AUTO_APPROVE=1: every risky action runs without asking you.",
                      fix("Remove LOKI_AUTO_APPROVE from harness_data/.env and restart LOKI", "settings:general"))
    if wrong:
        return result("policy", title, FAIL, "Safety rules are not doing their job: %s." % "; ".join(wrong),
                      fix("Do not use LOKI for risky work until this is fixed; tell Claude", action="recheck", label="Re-run"))
    paid = "Paid providers are %s (daily limit $%.2f)." % (
        "allowed" if getattr(agent, "ALLOW_PAID", False) else "never used on their own",
        float(getattr(agent, "DAILY_USD_LIMIT", 1.0) or 0))
    return result("policy", title, OK, "All %d safety rules hold: destructive commands and paths outside the project "
                  "are refused, deletes ask you, normal work runs. %s" % (len(cases), paid))


# --------------------------------------------------------------------------- 8. add-ons
def check_capabilities(ctx: Context) -> dict:
    title = "Add-ons"
    registry = getattr(ctx.agent, "CAPABILITIES", None)
    if registry is None:
        return result("capabilities", title, FAIL, "No add-on registry.", fix("Restart LOKI", "settings:machines"))
    rows = registry.present()
    changed = [r["name"] for r in rows if r["status"] == "changed"]
    invalid = [r["name"] for r in rows if r["status"] == "invalid"]
    missing = [r for r in rows if r["status"] == "missing"]
    on = [r["name"] for r in rows if r["status"] == "enabled"]
    off = [r["name"] for r in rows if r["status"] == "disabled"]
    items = [{"id": n, "name": n, "status": FAIL, "detail": "changed since you turned it on - off until you OK it",
              "fix": fix("Review %s and turn it back on" % n, "settings:capabilities", label="Review")} for n in changed]
    items += [{"id": n, "name": n, "status": FAIL, "detail": "its manifest is invalid"} for n in invalid]
    items += [{"id": r["name"], "name": r["name"], "status": WARN, "detail": "needs " + ", ".join(r.get("missing") or [])}
              for r in missing]
    tail = " On: %s. %d more %s off until you turn them on." % (", ".join(on) or "none", len(off),
                                                                 "is" if len(off) == 1 else "are")
    if changed or invalid:
        what = []
        if changed:
            what.append("%s changed since you turned %s on, so %s off until you OK %s again" % (
                ", ".join(changed), "it" if len(changed) == 1 else "them", "it is" if len(changed) == 1 else "they are",
                "it" if len(changed) == 1 else "them"))
        if invalid:
            what.append("%s %s an invalid manifest" % (", ".join(invalid), "has" if len(invalid) == 1 else "have"))
        return result("capabilities", title, FAIL, "; ".join(what) + "." + tail,
                      fix("Review and turn back on in Add-ons (LOKI never does this for you)", "settings:capabilities",
                          label="Review"), items=items)
    if missing:
        return result("capabilities", title, WARN, "%s %s turned on but missing something it needs.%s" % (
            ", ".join(r["name"] for r in missing), "is" if len(missing) == 1 else "are", tail),
            fix("Open Add-ons and press Install on each one (or run tools/setup_extras.py)", "settings:capabilities"),
            items=items)
    return result("capabilities", title, OK, "No add-on is changed or broken.%s" % tail)


# --------------------------------------------------------------------------- 9. specialists
def _plan_file(agent: Any) -> Path:
    return Path(getattr(agent, "DATA_DIR", ".")) / "app" / "imagegen_plan.json"


def _default_image_plan() -> dict:
    import conductor  # pylint: disable=import-outside-toplevel
    script = ENGINE / "runners" / "imagegen.py"
    # The same interpreter the image specialist uses (a packaged build runs runners itself).
    proc = subprocess.run([*conductor.python_command(), str(script), "--plan"], capture_output=True, text=True,
                          timeout=40, shell=False)
    lines = [l for l in (proc.stdout or "").splitlines() if l.strip().startswith("{")]
    if not lines:
        raise RuntimeError((proc.stderr or "no answer").strip()[-200:])
    return json.loads(lines[-1])


IMAGE_NAMES = {"zimage": "Z-Image Turbo (on this computer)", "qwen": "Qwen-Image (ModelScope, free)",
               "nvidia": "FLUX on NVIDIA (your NVIDIA key)", "gemini": "Nano Banana on Gemini (GEMINI_API_KEY)",
               "huggingface": "FLUX on Hugging Face (HF_TOKEN)"}


def check_specialists(ctx: Context) -> dict:
    title = "Specialists (image, media, ...)"
    conductor = getattr(ctx.agent, "CONDUCTOR", None)
    if conductor is None:
        return result("specialists", title, FAIL, "The conductor is missing.", fix("Restart LOKI", "settings:machines"))
    roster = conductor.roster()
    ready = ["%s (%s)" % (r["role"], r["via"]) for r in roster if r["ready"]]
    image = next((r for r in roster if r["role"] == "image"), {"ready": False, "why": "no image role"})
    base = "Ready: %s." % (", ".join(ready) or "none")
    if not image.get("ready"):
        why = str(image.get("why") or "")
        if "changed" in why:
            return result("specialists", title, FAIL, "The image specialist is blocked: %s. %s" % (why, base),
                          fix("Review image-gen in Add-ons and turn it back on", "settings:capabilities", label="Review"))
        return result("specialists", title, WARN, "The image specialist is off (%s). %s" % (why, base),
                      fix("Turn on image-gen in Add-ons to make images", "settings:capabilities"))
    try:
        plan = ctx.dep("image_plan", lambda: _default_image_plan)()
    except Exception as exc:  # noqa: BLE001
        return result("specialists", title, WARN, "Could not tell which image backend would run: %s. %s" % (exc, base),
                      fix("Re-run the check", action="recheck", label="Re-run"))
    order = plan.get("order") or []
    skipped = plan.get("skipped") or {}
    first = IMAGE_NAMES.get(order[0], order[0]) if order else "nothing"
    detail = "Images would be made with %s." % first
    if len(order) > 1:
        detail += " Then: %s." % ", ".join(IMAGE_NAMES.get(o, o) for o in order[1:])
    status, todo = OK, None
    crash = str(skipped.get("zimage") or "")
    if "crashed" in crash:
        status = WARN
        detail += " Local Z-Image is skipped: %s." % crash[:240]
        todo = fix("Try local Z-Image again on the next image", action="zimage_retry", label="Retry Z-Image")
    if ctx.image_test:
        runner = ctx.dep("image_run", lambda: (lambda prompt: conductor.run("image", prompt)))
        box: dict = {}
        worker = threading.Thread(target=lambda: box.update(out=runner("a small red circle on a white background, flat icon")),
                                  daemon=True)
        worker.start()
        worker.join(180)
        out = str(box.get("out", "error: no image within 3 minutes"))
        if out.startswith("error"):
            return result("specialists", title, FAIL, "A real image test failed: %s. %s" % (out[:300], base),
                          fix("Open Add-ons", "settings:capabilities"))
        detail += " Real test: %s." % out[:200]
    return result("specialists", title, status, "%s %s" % (detail, base), todo)


# --------------------------------------------------------------------------- 10. local models
def check_local_models(ctx: Context) -> dict:
    title = "Local models"
    agent = ctx.agent
    ms = ctx.dep("model_setup", lambda: getattr(agent, "model_setup", None) or __import__("model_setup"))
    try:
        snap = ms.status(info=getattr(agent, "HARDWARE", None) or None)
    except Exception as exc:  # noqa: BLE001
        return result("local_models", title, WARN, "Could not look at local models: %s" % exc,
                      fix("Open Local models", "settings:models"))
    ollama = snap.get("ollama") or {}
    best = snap.get("best") or {}
    servers = snap.get("servers") or []
    upgrade = snap.get("upgrade")
    if not ollama.get("running") and not servers:
        if ollama.get("installed"):
            return result("local_models", title, WARN, "Ollama is installed but not running, so LOKI has no model "
                          "when the internet or the free quotas are gone.", fix("Start Ollama", action="start_ollama", label="Start"))
        return result("local_models", title, WARN, "No local model on this computer: LOKI needs the internet for "
                      "every reply.", fix("Set up a local model (one click)", "settings:models"))
    if best and best.get("tools"):
        detail = "Ollama runs %s (best of %d installed)." % (best.get("name"), len(ollama.get("models") or []))
    elif servers:
        detail = "%s runs %s." % (servers[0].get("label", "A local server"), ", ".join((servers[0].get("models") or [])[:2]))
    else:
        return result("local_models", title, WARN, "Ollama runs, but none of its models can use tools.",
                      fix("Download a model that can (one click)", "settings:models"))
    if upgrade:
        return result("local_models", title, OK, detail + " A better one fits: %s (%s)." % (upgrade.get("tag"), upgrade.get("why", "")),
                      fix("Upgrade in Local models", "settings:models", label="Upgrade"))
    return result("local_models", title, OK, detail)


# --------------------------------------------------------------------------- 11. usage + memory
def check_usage(ctx: Context) -> dict:
    title = "Usage & memory"
    agent = ctx.agent
    try:
        today = (agent.USAGE.summary() or {}).get("today") or {}
    except Exception as exc:  # noqa: BLE001
        return result("usage", title, FAIL, "The usage ledger cannot be read: %s" % exc, fix("Open Usage", "settings:usage"))
    spent = float(agent.paid_spent_today()) if hasattr(agent, "paid_spent_today") else float(today.get("cost") or 0)
    limit = float(getattr(agent, "DAILY_USD_LIMIT", 1.0) or 0)
    rb = ctx.dep("reasoning_bank", lambda: getattr(agent, "reasoning_bank", None) or __import__("reasoning_bank"))
    try:
        bank = rb.summary()
    except Exception as exc:  # noqa: BLE001
        bank = {"enabled": False, "error": str(exc)}
    detail = "Today: %d model calls, $%.2f spent (limit $%.2f). ReasoningBank: %s lessons (%s worked, %s failed)%s." % (
        int(today.get("calls") or 0), spent, limit, bank.get("items", 0), bank.get("worked", 0), bank.get("failed", 0),
        "" if bank.get("enabled", True) else " - switched off")
    if limit and spent >= limit:
        return result("usage", title, WARN, detail + " The daily paid limit is reached, so paid models are paused.",
                      fix("Raise the daily limit in General", "settings:general"))
    if bank.get("error"):
        return result("usage", title, WARN, detail + " The lessons file cannot be read: %s" % bank["error"],
                      fix("Re-run the check", action="recheck", label="Re-run"))
    return result("usage", title, OK, detail)


# --------------------------------------------------------------------------- 12. peers
def check_peers(ctx: Context) -> dict:
    title = "Linked machines"
    peers = ctx.module("peers")
    configured = peers.peers()
    if not configured:
        listening = getattr(ctx.state, "peer_server", None) is not None
        return result("peers", title, SKIP, "No other machine is linked%s." % (
            " (this one listens for one)" if listening else ""))
    statuses = peers.status_all()
    items = []
    for s in statuses:
        if s.get("ok"):
            hello = s.get("hello") or {}
            items.append({"id": s["name"], "name": s["name"], "status": OK,
                          "detail": "answers in %d ms%s" % (s.get("ms", 0), (", runs " + str(hello.get("commit"))[:7])
                                                            if hello.get("commit") else "")})
        else:
            items.append({"id": s["name"], "name": s["name"], "status": FAIL, "detail": str(s.get("error", ""))[:200]})
    dead = [i for i in items if i["status"] == FAIL]
    if dead:
        return result("peers", title, FAIL if len(dead) == len(items) else WARN,
                      "%d of %d linked machines cannot be reached: %s. Both must be on the same network (or "
                      "Tailscale)." % (len(dead), len(items), "; ".join("%s: %s" % (i["name"], i["detail"]) for i in dead)),
                      fix("Put both machines on the same network, or install Tailscale on both; check that LOKI runs "
                          "there, then link again", "settings:machines"), items=items)
    return result("peers", title, OK, "Every linked machine answers: %s." % ", ".join(
        "%s (%s)" % (i["name"], i["detail"]) for i in items), items=items)


# --------------------------------------------------------------------------- 13. phone link
def check_phone(ctx: Context) -> dict:
    title = "Phone link"
    phone = ctx.module("phone_link")
    if not phone.enabled():
        return result("phone", title, SKIP, "The phone link is off.")
    server = getattr(ctx.state, "phone_server", None)
    if server is None:
        return result("phone", title, FAIL, "The phone link is on but not listening.",
                      fix("Turn the phone link off and on again in Machines & updates", "settings:machines"))
    port = server.address[1] if hasattr(server, "address") else phone.port()
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=1.5):
            pass
    except OSError as exc:
        return result("phone", title, FAIL, "The phone link should listen on port %s but does not answer (%s)." % (port, exc),
                      fix("Turn the phone link off and on again", "settings:machines"))
    registry = getattr(ctx.state, "phone_registry", None)
    try:
        phones = registry.present() if registry is not None else []
    except Exception:  # noqa: BLE001
        phones = []
    if not phones:
        return result("phone", title, WARN, "The phone link listens on port %s, but no phone is paired yet." % port,
                      fix("Pair your phone (scan the code in Machines & updates)", "settings:machines"))
    return result("phone", title, OK, "The phone link listens on port %s; %d phone%s paired." % (
        port, len(phones), "" if len(phones) == 1 else "s"))


# --------------------------------------------------------------------------- 14. disk + memory
def free_memory_gb() -> float | None:
    """Memory free for new work right now (both platforms; None when unknown)."""
    try:
        if sys.platform == "win32":
            import ctypes  # pylint: disable=import-outside-toplevel

            class _Mem(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            mem = _Mem()
            mem.dwLength = ctypes.sizeof(_Mem)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):  # type: ignore[attr-defined]
                return round(mem.ullAvailPhys / 2**30, 1)
            return None
        if sys.platform == "darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
            size = 4096
            pages = 0
            for line in out.splitlines():
                if "page size of" in line:
                    size = int("".join(ch for ch in line.split("page size of")[1] if ch.isdigit()) or 4096)
                if line.startswith(("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable")):
                    pages += int("".join(ch for ch in line.split(":")[1] if ch.isdigit()) or 0)
            return round(pages * size / 2**30, 1)
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 2**20, 1)
    except Exception:  # noqa: BLE001
        return None
    return None


def check_autopilot(ctx: Context) -> dict:
    """Is the autopilot on, and what has it done? (health fixes, the [loki] inbox, reports)"""
    auto = getattr(ctx.state, "autopilot", None) if ctx.state is not None else None
    if auto is None:
        return result("autopilot", "Autopilot (works when idle)", WARN,
                      "The autopilot is not running in this engine; LOKI only works when you ask it to.",
                      fix("Restart LOKI to start the autopilot", action="recheck", label="Re-run"))
    try:
        status = auto.status()
    except Exception as exc:  # noqa: BLE001
        return result("autopilot", "Autopilot (works when idle)", WARN, "Could not read it: %s" % exc)
    if not status.get("enabled"):
        return result("autopilot", "Autopilot (works when idle)", WARN,
                      "Switched off (LOKI_AUTOPILOT=off). LOKI only acts when you ask it to.",
                      items=[])
    log = status.get("log") or []
    recent = "; ".join("%s: %s" % (e.get("duty"), e.get("text", "")) for e in log[-3:]) or "nothing yet"
    detail = ("On. It runs the health check, picks up [loki] requests in LOKI_TASKS.md, and writes a "
              "weekly 'what LOKI learned' report when LOKI is idle. %s. Recently: %s" % (
                  ("Idle now" if status.get("idle") else "Waiting: %s" % status.get("waiting_for", "")), recent))
    return result("autopilot", "Autopilot (works when idle)", OK, detail,
                  items=[{"duty": e.get("duty"), "text": e.get("text")} for e in log[-6:]])


def check_disk(ctx: Context) -> dict:
    title = "Disk & memory"
    agent = ctx.agent
    disk = ctx.dep("disk", lambda: (lambda path: shutil.disk_usage(str(path))))
    data_dir = Path(getattr(agent, "DATA_DIR", "."))
    probe = data_dir
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        usage = disk(probe)
        free_gb = round(usage.free / 2**30, 1)
    except OSError as exc:
        return result("disk", title, WARN, "Free disk space is unknown: %s" % exc)
    mem_free = ctx.dep("free_memory", lambda: free_memory_gb)()
    ram = float((getattr(agent, "HARDWARE", None) or {}).get("ram_gb") or 0)
    detail = "%.1f GB free on the disk with LOKI's data. Memory: %s free%s." % (
        free_gb, ("%.1f GB" % mem_free) if mem_free is not None else "unknown", (" of %.0f GB" % ram) if ram else "")
    if free_gb < 2:
        return result("disk", title, FAIL, detail + " That is too little: updates, models and jobs can break.",
                      fix("Free up disk space (empty the trash, delete unused Ollama models)", "settings:models"))
    if free_gb < 10:
        return result("disk", title, WARN, detail + " Local models need more room.",
                      fix("Free up some disk space", "settings:models"))
    if mem_free is not None and mem_free < 1:
        return result("disk", title, WARN, detail + " Very little memory is free: close some apps.",
                      fix("Close apps you do not need"))
    return result("disk", title, OK, detail)


# --------------------------------------------------------------------------- the run
CHECKS: list = [
    ("engine", "Engine & updates", check_engine),
    ("models", "Models (smart route)", check_models),
    ("tools", "Tool calling (agent loop)", check_tools),
    ("first_layer", "First layer (Laya)", check_first_layer),
    ("jobs", "Background jobs, events & world", check_jobs),
    ("teams", "Agent teams", check_teams),
    ("policy", "Safety & approvals", check_policy),
    ("capabilities", "Add-ons", check_capabilities),
    ("specialists", "Specialists (image, media, ...)", check_specialists),
    ("local_models", "Local models", check_local_models),
    ("usage", "Usage & memory", check_usage),
    ("peers", "Linked machines", check_peers),
    ("phone", "Phone link", check_phone),
    ("autopilot", "Autopilot (works when idle)", check_autopilot),
    ("disk", "Disk & memory", check_disk),
]


def summarize(results: list) -> dict:
    counted = [r for r in results if r["status"] != SKIP]
    bad = [r for r in counted if r["status"] == FAIL]
    warn = [r for r in counted if r["status"] == WARN]
    good = len(counted) - len(bad)
    if not counted:
        line = "Nothing was checked."
    elif bad:
        line = "%d of %d systems work together. %d need%s you: %s." % (
            good, len(counted), len(bad), "s" if len(bad) == 1 else "", ", ".join(r["title"] for r in bad))
    elif warn:
        line = "All %d systems work together. %d worth a look: %s." % (
            len(counted), len(warn), ", ".join(r["title"] for r in warn))
    else:
        line = "All %d systems work together." % len(counted)
    return {"line": line, "state": FAIL if bad else WARN if warn else OK, "working": good, "counted": len(counted),
            "ok": len(counted) - len(bad) - len(warn), "warn": len(warn), "fail": len(bad),
            "skip": len(results) - len(counted)}


def run(ctx: Context, on_progress: Callable[[dict], None] | None = None, checks: list | None = None) -> dict:
    """Run every check in order. Never raises; a check that crashes is a red row that says so."""
    started = time.time()
    results: list = []
    todo = list(checks if checks is not None else CHECKS)
    for index, (check_id, title, fn) in enumerate(todo):
        if on_progress:
            on_progress({"index": index, "total": len(todo), "current": title, "results": list(results)})
        t0 = time.monotonic()
        # No row is skipped wholesale for time: the quick ones always run, and the slow ones
        # (model calls, the job, the image plan) shorten their own waits to what is left.
        try:
            row = fn(ctx)
        except Exception as exc:  # noqa: BLE001 - one broken check must not hide the others
            row = result(check_id, title, FAIL, "The check itself failed: %s: %s" % (type(exc).__name__, str(exc)[:240]),
                         fix("Re-run the check; if it stays red, tell Claude", action="recheck", label="Re-run"))
        row["ms"] = int((time.monotonic() - t0) * 1000)
        results.append(row)
    report = {"ok": True, "started": started, "finished": time.time(), "seconds": round(time.time() - started, 1),
              "results": results, "summary": summarize(results),
              "options": {"allow_paid": ctx.allow_paid, "image_test": ctx.image_test}}
    if on_progress:
        on_progress({"index": len(todo), "total": len(todo), "current": "", "results": list(results)})
    return report


class Runner:
    """One run at a time, in the background; the UI polls snapshot()."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state: dict = {"running": False, "progress": {"index": 0, "total": len(CHECKS), "current": ""},
                            "report": None}

    def start(self, ctx: Context, checks: list | None = None) -> bool:
        with self.lock:
            if self.state["running"]:
                return False
            self.state.update(running=True, progress={"index": 0, "total": len(checks or CHECKS), "current": "",
                                                      "results": []})

        def progress(p: dict) -> None:
            with self.lock:
                self.state["progress"] = p

        def work() -> None:
            try:
                report = run(ctx, progress, checks)
            except Exception as exc:  # noqa: BLE001
                report = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc), "results": [],
                          "summary": {"line": "The check could not run: %s" % exc, "state": FAIL}}
            with self.lock:
                self.state.update(running=False, report=report)

        threading.Thread(target=work, name="loki-system-check", daemon=True).start()
        return True

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state, default=str))


RUNNER = Runner()


# --------------------------------------------------------------------------- safe fixes
SAFE_ACTIONS = ("provider_off", "revive_providers", "laya_warm", "start_ollama", "jobs_start", "zimage_retry")


def apply_fix(state: Any, action: str, args: dict | None = None, write_env=None) -> dict:
    """Do one SAFE fix. Never approves an add-on, applies an update or spends money."""
    args = dict(args or {})
    agent = state.agent
    if action not in SAFE_ACTIONS:
        return {"ok": False, "error": "LOKI does not do '%s' on its own; use the button that opens Settings." % action}
    if action == "provider_off":
        import providers_catalog  # pylint: disable=import-outside-toplevel
        if write_env is None:
            import portal_api  # pylint: disable=import-outside-toplevel
            write_env = portal_api._write_env(agent)  # pylint: disable=protected-access
        ids = [str(i).strip().lower() for i in (args.get("ids") or [args.get("id")]) if str(i or "").strip()]
        done = []
        for pid in ids:
            if providers_catalog.set_enabled(pid, False, write_env).get("ok"):
                done.append(pid)
        if not done:
            return {"ok": False, "error": "no such provider"}
        return {"ok": True, "message": "Switched off: %s. LOKI will not route to %s." % (
            ", ".join(_label(p) for p in done), "it" if len(done) == 1 else "them"), "off": done}
    if action == "revive_providers":
        back = sorted(getattr(agent, "_SMART_FAILED", set()))
        agent._SMART_FAILED.clear()  # pylint: disable=protected-access
        getattr(agent, "_RATE_LIMITED", {}).clear()
        return {"ok": True, "message": "LOKI may use %s again." % (", ".join(back) or "every provider")}
    if action == "laya_warm":
        import laya  # pylint: disable=import-outside-toplevel
        laya.warm()
        return {"ok": True, "message": "Laya is loading its model; check again in a minute."}
    if action == "start_ollama":
        ms = getattr(agent, "model_setup", None) or __import__("model_setup")
        threading.Thread(target=ms.start_ollama, daemon=True).start()
        return {"ok": True, "message": "Starting Ollama; check again in a few seconds."}
    if action == "jobs_start":
        jobs = getattr(state, "jobs", None)
        if jobs is None:
            return {"ok": False, "error": "background jobs are not part of this engine; restart LOKI"}
        jobs.start()
        return {"ok": True, "message": "The job runner is running again."}
    if action == "zimage_retry":
        path = _plan_file(agent)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        if record.get("works") is None and path.is_file():
            path.unlink()
        return {"ok": True, "message": "The next image tries local Z-Image again (it falls back if it crashes)."}
    return {"ok": False, "error": "unknown action"}
