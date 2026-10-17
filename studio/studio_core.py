"""LOKI Studio's development sessions: one conversation = one git worktree of LOKI = one branch.

The owner types what to build or fix. A session gets its own worktree
(harness_data/studio/worktrees/<id>, branch studio/<id>, made from the checkout's HEAD - the same
isolation as improve_loki) and an agent that runs INSIDE Studio on DeepSeek V4.1 Flash (NVIDIA NIM,
studio_models.py, with fallbacks). Its only hands are the LOKI MCP API (engine/loki_mcp.py, started
as a stdio MCP server bound to this worktree): it reads, searches and edits LOKI's code there, runs
the test suites, reads HANDOFF / ZIVA_TASKS, and inspects and controls the running LOKI (health,
logs, settings, jobs, restart). Risky calls wait for the owner's Approve in Studio. It can NEVER
ship: the owner's "Ship it" runs tools/ship.py (every suite must pass; the health-gated updater
does the rest on every machine). Discard removes the worktree and its branch.

Every step is an event (user, assistant, thinking, tool, result, diff, approval, status, error)
kept in harness_data/studio/sessions/<id>/events.jsonl, so history survives restarts.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import studio_paths
import studio_models
import loki_mcp

MAX_STEPS = int(os.getenv("LOKI_STUDIO_MAX_STEPS", "60") or 60)
OWNER_ONLY = {"ship"}                       # the model never gets these
ASK_TOOLS = set(loki_mcp.RISKY_TOOLS) - OWNER_ONLY
FINAL = ("shipped", "discarded")

SYSTEM_PROMPT = """You are LOKI Studio's development agent. You work on LOKI itself - the owner's AI agent
desktop app (Python engine in engine/, the window in app/ui/) - in your OWN git worktree of LOKI
({worktree}, branch {branch}). The running LOKI is a separate program you can inspect and control
through your tools.

Rules (AGENTS.md is the rulebook - read it with read_doc("AGENTS.md") when in doubt):
- LOKI runs on macOS AND Windows from the same code: never write code for one without the other
  (pathlib, sys.platform branches with both sides, no shell strings).
- Small steps. Add or update a test in tests/ for what you change. Keep docs/ true.
- Read only the parts of big files you need: search_files first, then read_file with start_line/end_line.
  Edit with edit_file (old_text must be unique: copy a few surrounding lines) or write_file for new files.
- Test with run_tests (suite="test_portal" for one suite; empty = all, slow). Never say a change works
  before its tests pass.
- You cannot ship or push. When the change is done and its tests pass, say so in one short summary
  and suggest a one-line ship message; the owner reviews the diff and presses "Ship it".
- Never touch harness_data/, .env files, keys or tokens (your tools refuse anyway).
- Risky tools (settings_set, job_start, job_stop, restart_engine) wait for the owner's approval.
- The running LOKI: loki_status, engine_logs, models_doctor, jobs_list, job_logs, tools_health,
  settings_get, memory_search... use them to see what is wrong before you change code.
- Where the work stands: read_doc("HANDOFF.md"); what the Mac/PC agents do: read_doc("ZIVA_TASKS.md").

Right now: {loki_line}
Reply in plain words. End your turn with no tool call when you are done or need the owner."""


def _now() -> float:
    return time.time()


def _git(cwd: Path, *args: str, timeout: float = 120.0) -> tuple:
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                              env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
        return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def mcp_tools_to_openai(tools: list) -> list:
    out = []
    for t in tools:
        name = getattr(t, "name", "")
        if not name or name in OWNER_ONLY:
            continue
        schema = dict(getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {"type": "object", "properties": {}})
        props = dict(schema.get("properties") or {})
        props.pop("confirm", None)   # the approval code is Studio's, never the model's
        schema["properties"] = props
        schema["required"] = [r for r in (schema.get("required") or []) if r != "confirm"]
        schema.pop("title", None)
        out.append({"type": "function", "function": {"name": name, "description": (getattr(t, "description", "") or "")[:900],
                                                     "parameters": schema}})
    return out


class Session:
    def __init__(self, root: Path, meta: dict):
        self.root = root
        self.meta = meta
        self.events: list = []
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pending: dict = {}           # approval id -> {"event": Event, "yes": bool|None}
        self.queue: list = []             # follow-ups typed while it works
        self.thread: threading.Thread | None = None
        self._load()

    # ------------------------------------------------------------- storage
    @property
    def id(self) -> str:
        return self.meta["id"]

    def _load(self) -> None:
        try:
            for line in (self.root / "events.jsonl").read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.events.append(json.loads(line))
        except (OSError, ValueError):
            pass
        try:
            self.meta.update(json.loads((self.root / "session.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        if self.meta.get("status") in ("working", "waiting"):   # Studio was closed mid-run
            self.meta["status"] = "stopped"

    def save(self) -> None:
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.root / "session.json.tmp"
            tmp.write_text(json.dumps(self.meta, indent=1, default=str), encoding="utf-8")
            os.replace(tmp, self.root / "session.json")

    def add(self, kind: str, text: str = "", **extra) -> dict:
        with self.lock:
            event = {"id": (self.events[-1]["id"] + 1) if self.events else 1, "t": _now(), "type": kind,
                     "text": str(text)[:20000], **extra}
            self.events.append(event)
            self.root.mkdir(parents=True, exist_ok=True)
            with (self.root / "events.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, default=str) + "\n")
            self.meta["updated"] = event["t"]
            return event

    def set_status(self, status: str, note: str = "") -> None:
        with self.lock:
            self.meta["status"] = status
            self.save()
        self.add("status", note or status, status=status)

    def summary(self) -> dict:
        m = self.meta
        return {k: m.get(k) for k in ("id", "title", "status", "branch", "worktree", "created", "updated", "provider",
                                      "model", "shipped", "last_check")}

    @property
    def messages(self) -> list:
        return self.meta.setdefault("messages", [])


class Studio:
    """All sessions, and running them."""

    def __init__(self, repo: Path | None = None, data: Path | None = None, mcp_factory: Callable | None = None,
                 chat: Callable | None = None, python: str = "", ship_runner: Callable | None = None,
                 check_runner: Callable | None = None):
        self.repo = Path(repo or studio_paths.repo()).resolve()
        self.data = Path(data or studio_paths.data()).resolve()
        self.home = self.data / "studio"
        self.home.mkdir(parents=True, exist_ok=True)
        self.secret = secrets.token_hex(24)          # the approval codes for risky MCP calls
        self.mcp_factory = mcp_factory or self._stdio_mcp
        self.chat = chat or studio_models.chat
        self.python = python or studio_paths.engine_python(self.data)
        self.ship_runner = ship_runner or (lambda tree, msg: loki_mcp.run_ship(tree, msg, self.python, self.data))
        self.check_runner = check_runner or (lambda tree, suite: loki_mcp.run_check(tree, suite, self.python))
        self.sessions: dict = {}
        self.lock = threading.RLock()
        for meta_file in sorted((self.home / "sessions").glob("*/session.json")):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                self.sessions[meta["id"]] = Session(meta_file.parent, meta)
            except (OSError, ValueError, KeyError):
                continue

    # ------------------------------------------------------------- MCP
    def _stdio_mcp(self, session: Session):
        """The LOKI MCP API as its own process (stdio), bound to this session's worktree."""
        from mcp import Client, StdioServerParameters  # pylint: disable=import-outside-toplevel
        env = {k: v for k, v in os.environ.items() if not re.search(r"(_API_KEY|_TOKEN)$", k)}
        env.update(LOKI_DATA=str(self.data), LOKI_MCP_APPROVAL_SECRET=self.secret, PYTHONUNBUFFERED="1")
        params = StdioServerParameters(command=sys.executable,
                                       args=[str(studio_paths.ENGINE / "loki_mcp.py"), "--worktree", session.meta["worktree"],
                                             "--repo", str(self.repo)], env=env)
        return Client(params, read_timeout_seconds=3700)

    # ------------------------------------------------------------- sessions
    def list(self) -> list:
        with self.lock:
            return sorted((s.summary() for s in self.sessions.values()), key=lambda s: -(s.get("updated") or 0))

    def get(self, sid: str) -> Session:
        session = self.sessions.get(str(sid or ""))
        if session is None:
            raise KeyError("no session %r" % sid)
        return session

    def new(self, text: str, start: bool = True) -> Session:
        text = str(text or "").strip()
        if not text:
            raise ValueError("say what to build or fix")
        sid = time.strftime("%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        branch = "studio/" + sid
        tree = self.home / "worktrees" / sid
        tree.parent.mkdir(parents=True, exist_ok=True)
        code, out = _git(self.repo, "worktree", "add", "-b", branch, str(tree), "HEAD")
        if code != 0:
            raise RuntimeError("could not make a worktree of %s: %s" % (self.repo, out[-300:]))
        meta = {"id": sid, "title": text.splitlines()[0][:80], "status": "idle", "branch": branch,
                "worktree": str(tree), "created": _now(), "updated": _now(), "messages": []}
        session = Session(self.home / "sessions" / sid, meta)
        session.save()
        with self.lock:
            self.sessions[sid] = session
        session.add("status", "New session in its own worktree %s (branch %s)." % (tree, branch), status="idle")
        self.send(sid, text, start=start)
        return session

    def send(self, sid: str, text: str, start: bool = True) -> dict:
        session = self.get(sid)
        if session.meta.get("status") in FINAL:
            raise ValueError("this session is %s; start a new one" % session.meta["status"])
        text = str(text or "").strip()
        if not text:
            raise ValueError("empty message")
        session.add("user", text)
        with session.lock:
            if session.thread is not None and session.thread.is_alive():
                session.queue.append(text)
                return {"queued": True}
            session.messages.append({"role": "user", "content": text})
            session.save()
        if start:
            self._start(session)
        return {"queued": False}

    def _start(self, session: Session) -> None:
        session.stop.clear()
        session.thread = threading.Thread(target=self._run, args=(session,), daemon=True, name="studio-" + session.id)
        session.thread.start()

    def stop(self, sid: str) -> None:
        session = self.get(sid)
        session.stop.set()
        for p in list(session.pending.values()):
            p["yes"] = False
            p["event"].set()

    def wait(self, sid: str, timeout: float = 60.0) -> bool:
        session = self.get(sid)
        thread = session.thread
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    def approve(self, sid: str, approval_id: str, yes: bool) -> bool:
        session = self.get(sid)
        pending = session.pending.get(str(approval_id))
        if pending is None:
            return False
        pending["yes"] = bool(yes)
        pending["event"].set()
        return True

    def diff(self, sid: str) -> str:
        return loki_mcp.diff_text(Path(self.get(sid).meta["worktree"]))

    def check(self, sid: str, suite: str = "") -> str:
        session = self.get(sid)
        session.add("status", "Running the tests%s..." % ((" (%s)" % suite) if suite else " (all suites)"), status=session.meta.get("status"))
        out = self.check_runner(Path(session.meta["worktree"]), suite)
        session.meta["last_check"] = {"t": _now(), "suite": suite, "passed": out.startswith("ALL PASSED")}
        session.save()
        session.add("check", out, passed=out.startswith("ALL PASSED"))
        return out

    def ship(self, sid: str, message: str, approved: bool = False) -> str:
        """The owner's "Ship it": tools/ship.py from the session's worktree. Refused without the owner."""
        session = self.get(sid)
        if not approved:
            session.add("error", "Ship refused: only the owner can ship, with the Ship it button.")
            return "NOT shipped: needs the owner's approval in Studio"
        if session.meta.get("status") in FINAL:
            return "NOT shipped: this session is %s" % session.meta["status"]
        if session.thread is not None and session.thread.is_alive():
            return "NOT shipped: the agent is still working; stop it or wait"
        message = " ".join(str(message or "").split()) or ("LOKI Studio: " + session.meta.get("title", ""))
        session.add("status", "Shipping: every suite runs, then commit, catch up with GitHub, push...", status="shipping")
        out = self.ship_runner(Path(session.meta["worktree"]), message)
        ok = out.startswith("shipped")
        session.add("ship", out, ok=ok)
        if ok:
            session.meta["shipped"] = {"t": _now(), "message": message}
            session.set_status("shipped", "Shipped. Every machine takes it through the health-gated updater.")
        else:
            session.set_status("idle", "Not shipped - see why above. Fix it in this session and ship again.")
        return out

    def discard(self, sid: str) -> None:
        session = self.get(sid)
        self.stop(sid)
        self.wait(sid, 10)
        tree = Path(session.meta["worktree"])
        _git(self.repo, "worktree", "remove", "--force", str(tree))
        if tree.exists():
            shutil.rmtree(tree, ignore_errors=True)
        _git(self.repo, "worktree", "prune")
        if not session.meta.get("shipped"):
            _git(self.repo, "branch", "-D", session.meta["branch"])
        session.set_status("discarded", "Discarded: the worktree and its branch are gone; the history stays here.")

    # ------------------------------------------------------------- the agent loop
    def loki_line(self) -> str:
        try:
            api = loki_mcp.LokiAPI(worktree=self.repo, repo=self.repo, data=self.data)
            return ("the running LOKI answers (%s)." % api.bridge("GET", "/health", timeout=2)[1].get("model", "")) \
                if api.up() else "LOKI is NOT running - you can still read its logs with engine_logs."
        except Exception as exc:  # noqa: BLE001
            return "LOKI's state is unknown (%s)." % exc

    def _run(self, session: Session) -> None:
        session.set_status("working")
        try:
            asyncio.run(self._loop(session))
        except Exception as exc:  # noqa: BLE001 - a session must never take Studio down
            session.add("error", "%s: %s" % (type(exc).__name__, exc))
        finally:
            with session.lock:
                more = list(session.queue)
                session.queue.clear()
                for text in more:
                    session.messages.append({"role": "user", "content": text})
                session.save()
            if more and not session.stop.is_set():
                session.thread = None
                self._start(session)
                return
            if session.meta.get("status") in ("working", "waiting"):
                session.set_status("stopped" if session.stop.is_set() else "idle",
                                   "Stopped." if session.stop.is_set() else "Waiting for you.")

    async def _loop(self, session: Session) -> None:
        tree = session.meta["worktree"]
        system = {"role": "system", "content": SYSTEM_PROMPT.format(worktree=tree, branch=session.meta["branch"],
                                                                     loki_line=self.loki_line())}
        async with self.mcp_factory(session) as client:
            listed = await client.list_tools()
            tools = mcp_tools_to_openai(listed.tools)
            for _step in range(MAX_STEPS):
                if session.stop.is_set():
                    return
                with session.lock:
                    convo = [system] + list(session.messages)
                say = lambda text: session.add("progress", text)  # noqa: E731
                try:
                    provider, message, reasoning = await asyncio.to_thread(self.chat, convo, tools, None, say,
                                                                           time.sleep, stop=session.stop)
                except studio_models.ModelError as exc:
                    if str(exc) != "stopped":
                        session.add("error", str(exc), how=studio_models.HOW_TO_GET_KEY if "no model is ready" in str(exc) else "")
                    return
                session.meta.update(provider=provider.id, model=provider.model)
                if reasoning:
                    session.add("thinking", reasoning[:6000], provider=provider.id)
                calls = []
                for n, call in enumerate(message.get("tool_calls") or []):
                    call = dict(call)
                    call.setdefault("type", "function")
                    call["id"] = call.get("id") or "call_%d_%d" % (_step, n)
                    fn = dict(call.get("function") or {})
                    if not isinstance(fn.get("arguments"), str):
                        fn["arguments"] = json.dumps(fn.get("arguments") or {})
                    call["function"] = fn
                    calls.append(call)
                entry ={"role": "assistant", "content": message.get("content") or ""}
                if calls:
                    entry["tool_calls"] = calls
                with session.lock:
                    session.messages.append(entry)
                    session.save()
                if entry["content"]:
                    session.add("assistant", entry["content"], provider=provider.id, model=provider.model)
                if not calls:
                    return
                for call in calls:
                    result = await self._call(session, client, call)
                    with session.lock:
                        session.messages.append({"role": "tool", "tool_call_id": call.get("id") or "",
                                                 "content": result[:24000]})
                        session.save()
                    if session.stop.is_set():
                        return
            session.add("error", "Stopped after %d steps (LOKI_STUDIO_MAX_STEPS). Say 'continue' to go on." % MAX_STEPS)

    async def _call(self, session: Session, client, call: dict) -> str:
        fn = call.get("function") or {}
        name = str(fn.get("name") or "")
        try:
            args = json.loads(fn.get("arguments") or "{}") if isinstance(fn.get("arguments"), str) else dict(fn.get("arguments") or {})
        except ValueError:
            session.add("tool", "%s(<bad JSON>)" % name, tool=name)
            return "error: the arguments were not valid JSON; send them again as a JSON object"
        args.pop("confirm", None)
        session.add("tool", "%s(%s)" % (name, json.dumps(args, ensure_ascii=False)[:400]), tool=name, args=args)
        if name in OWNER_ONLY:
            return "error: only the owner ships (the Ship it button). Say the change is ready and suggest a message."
        if name in ASK_TOOLS:
            yes = await self._ask(session, name, args)
            if not yes:
                session.add("result", "the owner said no", tool=name)
                return "refused: the owner said no (or stopped the session)"
            args["confirm"] = loki_mcp.approval_code(self.secret, name, args)
        try:
            out = await client.call_tool(name, args)
            text = "\n".join(getattr(c, "text", "") or "" for c in (getattr(out, "content", None) or [])) or "(no output)"
        except Exception as exc:  # noqa: BLE001 - a tool error goes back to the model
            text = "error: %s: %s" % (type(exc).__name__, exc)
        session.add("result", text[:6000], tool=name)
        if name in ("edit_file", "write_file") and not text.startswith("error"):
            session.add("diff", loki_mcp.diff_text(Path(session.meta["worktree"]), str(args.get("path") or ""))[:12000],
                        path=args.get("path"))
        if name == "run_tests":
            session.meta["last_check"] = {"t": _now(), "suite": args.get("suite", ""), "passed": text.startswith("ALL PASSED")}
        return text

    async def _ask(self, session: Session, tool: str, args: dict) -> bool:
        aid = uuid.uuid4().hex[:8]
        waiter = {"event": threading.Event(), "yes": None}
        session.pending[aid] = waiter
        session.meta["status"] = "waiting"
        session.save()
        session.add("approval", "The agent wants to run %s(%s)." % (tool, json.dumps(args, ensure_ascii=False)[:300]),
                    approval=aid, tool=tool, args=args, state="open")
        try:
            while not waiter["event"].is_set():
                if session.stop.is_set():
                    return False
                await asyncio.sleep(0.2)
            return bool(waiter["yes"])
        finally:
            session.pending.pop(aid, None)
            session.meta["status"] = "working"
            session.save()
            session.add("approved" if waiter["yes"] else "denied", tool, approval=aid)
