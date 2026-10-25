"""LOKI Studio's development sessions.

A session is one conversation with Studio's agent about ONE thing it works on:

  kind "loki"   LOKI's own code. The session gets its own git worktree
                (harness_data/studio/worktrees/<id>, branch studio/<id>, made from the checkout's
                HEAD - the same isolation as improve_loki). The agent's hands on the code and on
                the running LOKI are the LOKI MCP API (engine/loki_mcp.py, a stdio MCP server bound
                to this worktree), plus Studio's own tools (studio_tools.py). It can NEVER ship: the
                owner's "Ship it" runs tools/ship.py (every suite must pass; the health-gated updater
                does the rest on every machine). Discard removes the worktree and its branch.
  kind "godot"  a Godot project - any of the owner's own games - live in the Godot
                editor through the LOKI Studio plugin (studio_godot.py). The agent reads and writes
                the project's files, edits the open scene through the editor's UndoRedo, runs the
                game, playtests it turn by turn, finds lag, reads the editor's and the game's errors.

What every session has (the Ziva workflow, studio_tools.py / studio_commands.py / studio_checkpoints.py):
  modes         default (may change things) / plan (reads, plans with todos, changes nothing) / ask
  checkpoints   every turn (one owner message and all the agent did for it) can be undone:
                git snapshots for code, file snapshots + the editor's UndoRedo for Godot
  approvals     risky calls wait for Approve; optionally every edit too (approve_edits)
  questions     the agent can ask the owner and wait for the answer (ask_owner)
  todos         the agent's live todo list; messages typed while it works are queued
  @-mentions    files, folders, @scene, @selection, @errors, @todos attach their content
  slash commands + templates, AGENTS.md instructions, LOKI memory, skills, subagents, web + Godot
  docs, fork the conversation, any model (DeepSeek V4.1 on NVIDIA first; Claude Code / Codex CLIs)

Every step is an event (user, assistant, thinking, tool, result, diff, approval, question, todos,
checkpoint, command, status, error) kept in harness_data/studio/sessions/<id>/events.jsonl.
"""
from __future__ import annotations

import asyncio
import difflib
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
import studio_tools
import studio_commands
import studio_checkpoints
import studio_index
import studio_destination
import studio_godot
import godot_docs
import loki_mcp

MAX_STEPS = int(os.getenv("LOKI_STUDIO_MAX_STEPS", "60") or 60)
SUB_STEPS = 12
OWNER_ONLY = {"ship"}                       # the model never gets these
ASK_TOOLS = set(loki_mcp.RISKY_TOOLS) - OWNER_ONLY
FINAL = ("shipped", "discarded")
READ_MCP = {"loki_status", "models_doctor", "settings_get", "jobs_list", "job_logs", "engine_logs", "world_summary",
            "memory_search", "tools_health", "creations_list", "read_file", "list_files", "search_files", "git_status",
            "git_diff", "git_log", "read_doc"}
WRITE_MCP = {"edit_file", "write_file"}
MODES = studio_tools.MODES

SYSTEM_PROMPT = """You are LOKI Studio's development agent. You work on LOKI itself - the owner's AI agent
desktop app (Python engine in engine/, the window in app/ui/) - in your OWN git worktree of LOKI
({worktree}, branch {branch}). The running LOKI is a separate program you can inspect and control
through your tools.

Where you stand: you are the INSIDE agent - LOKI's own code, its cleanup, its tests. The owner's work outside the
app (their games, projects, files, marketing) is Home LOKI's job: when they ask for that here, say Home LOKI is
made for it (it is in the same window), and only do it here if they still want you to.

Rules (AGENTS.md is the rulebook - read it with read_doc("AGENTS.md") when in doubt):
- LOKI runs on macOS AND Windows from the same code: never write code for one without the other
  (pathlib, sys.platform branches with both sides, no shell strings).
- Small steps. Add or update a test in tests/ for what you change. Keep docs/ true.
- Know where things are: repo_map (prefix like engine/) before reading. Read only the parts of big files
  you need: search_files first, then read_file with start_line/end_line.
  Edit with edit_file (old_text must be unique: copy a few surrounding lines) or write_file for new files.
- Test with run_tests (suite="test_portal" for one suite; a test run may take at most one minute - the
  owner's rule). Never say a change works before its tests pass.
- You cannot ship or push. When the change is done and its tests pass, say so in one short summary
  and suggest a one-line ship message; the owner reviews the diff and presses "Ship it".
- Never touch harness_data/, .env files, keys or tokens (your tools refuse anyway).
- Risky tools (settings_set, job_start, job_stop, restart_engine, pc_worker) wait for the owner's approval.
- The running LOKI: loki_status, engine_logs, models_doctor, jobs_list, job_logs, tools_health,
  settings_get, memory_search... use them to see what is wrong before you change code.
- Where the work stands: read_doc("HANDOFF.md"); what the Mac/PC agents do: read_doc("ZIVA_TASKS.md").
{common}
Right now: {loki_line}
Reply in plain words. End your turn with no tool call when you are done or need the owner."""

GODOT_PROMPT = """You are LOKI Studio's game-development agent, working LIVE inside the owner's Godot editor on the
project {name!r} at {root} (Godot {godot}). You see and change what the owner sees: the open scenes, the selected
nodes, the script editor, the Output and the errors, and the running game.

How you work:
- Know the project first: project_index (empty = the overview, or a word), project_graph for a diagram.
- Look up the REAL Godot API with godot_docs before you use a class or method you are not sure of
  (this is Godot {godot}; do not guess Godot 3 names).
- Scripts, shaders, resources, scene files: read_file / search_files / edit_file / write_file (res:// paths).
  The open scene: scene_tree, node_info, add_node, set_property, remove_node, connect_signal, attach_script,
  save_scene - these go through the editor's undo history, so the owner can Ctrl+Z them too.
- After a change, check it: editor_errors; run_game, then playtest_step (input -> wait -> screenshot -> new
  errors) turn by turn; find_lag when it is slow; stop_game when done.
- GDScript 2 (Godot 4): typed vars, @export, @onready, signal.connect(callable), await. Keep the owner's style.
- Every turn has a checkpoint; the owner can undo it. Still: small steps, and say what you changed.
{common}
Reply in plain words. End your turn with no tool call when you are done or need the owner."""

COMMON = """- Keep a todo list with todo_write for anything with more than two steps. Ask the owner with ask_owner
  when a decision is theirs. Use subagent for read-only research you can hand off.
- remember / recall: LOKI's memory (shared by the Mac and the PC) - keep decisions and lessons there.
- Skills: list_skills / use_skill. The web: web_search. Diagrams: a ```mermaid block in your answer."""

MODE_TEXT = {
    "plan": ("\nMODE: PLAN. Do NOT change anything (you have read tools only). Read what you need, then write the "
             "plan with todo_write (concrete steps, files, tests) and explain it briefly. The owner switches to Default to do it."),
    "ask": ("\nMODE: ASK. Answer the owner's question about the project from what you read. Do not change anything "
            "(you have read tools only)."),
    "default": "",
}


def _now() -> float:
    return time.time()


def _git(cwd: Path, *args: str, timeout: float = 120.0) -> tuple:
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                              env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
        return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def mcp_tools_to_openai(tools: list, allowed: set | None = None) -> list:
    out = []
    for t in tools:
        name = getattr(t, "name", "")
        if not name or name in OWNER_ONLY or (allowed is not None and name not in allowed):
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


class _NoMCP:
    """A Godot session has no LOKI MCP server: Studio's own tools only."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_tools(self):
        return type("Listed", (), {"tools": []})()

    async def call_tool(self, name, args):
        raise RuntimeError("no such tool here: %s" % name)


class Session:
    def __init__(self, root: Path, meta: dict):
        self.root = root
        self.meta = meta
        self.events: list = []
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pending: dict = {}           # approval / question id -> {"event": Event, "yes": bool|None, "answer": str}
        self.queue: list = []             # follow-ups typed while it works
        self.thread: threading.Thread | None = None
        self._load()

    # ------------------------------------------------------------- storage
    @property
    def id(self) -> str:
        return self.meta["id"]

    @property
    def kind(self) -> str:
        return self.meta.get("kind") or "loki"

    @property
    def work_root(self) -> Path:
        return Path(self.meta.get("root") or self.meta.get("worktree") or ".")

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
        out = {k: m.get(k) for k in ("id", "title", "status", "branch", "worktree", "created", "updated", "provider",
                                     "model", "shipped", "last_check", "kind", "root", "project", "mode", "model_pref",
                                     "approve_edits", "turn", "forked_from", "destination")}
        out["kind"] = out["kind"] or "loki"
        out["mode"] = out["mode"] or "default"
        out["todos"] = m.get("todos") or []
        out["queued"] = len(self.queue)
        out["waiting_for"] = [{"id": k, "kind": v.get("kind", "approval")} for k, v in list(self.pending.items())]
        return out

    @property
    def messages(self) -> list:
        return self.meta.setdefault("messages", [])


class Studio:
    """All sessions, and running them."""

    def __init__(self, repo: Path | None = None, data: Path | None = None, mcp_factory: Callable | None = None,
                 chat: Callable | None = None, python: str = "", ship_runner: Callable | None = None,
                 check_runner: Callable | None = None, hub: studio_godot.GodotHub | None = None,
                 cli_runner: Callable | None = None, dest_runner: Callable | None = None):
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
        self.hub = hub or studio_godot.GodotHub(shots=self.home / "shots")
        self.cli_runner = cli_runner
        self.dest_runner = dest_runner or studio_destination.run   # git/gh for "Where is this going?" (fakes in tests)
        self.tool_extra: dict = {}                   # test hooks for tools (web opener, image maker)
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

    # ------------------------------------------------------------- where this is going (studio_destination.py)
    def destination(self) -> dict:
        """The stored choice, else the implicit one: the owner (or an unknown gh user) keeps "Improve LOKI itself"."""
        choice = studio_destination.load(self.home)
        info = studio_destination.detect(self.repo, self.dest_runner)
        if not choice and info["can_improve_loki"]:
            choice = {"kind": "loki", "name": studio_destination.KINDS["loki"][0], "repo": studio_destination.UPSTREAM,
                      "path": str(self.repo), "implicit": True}
        return {"choice": choice, **info, "chosen": bool(choice) and not choice.get("implicit")}

    def choose_destination(self, kind: str, name: str = "", visibility: str = "private") -> dict:
        return studio_destination.choose(self.home, self.repo, kind, name, visibility, runner=self.dest_runner)

    # ------------------------------------------------------------- sessions
    def list(self) -> list:
        with self.lock:
            return sorted((s.summary() for s in self.sessions.values()), key=lambda s: -(s.get("updated") or 0))

    def get(self, sid: str) -> Session:
        session = self.sessions.get(str(sid or ""))
        if session is None:
            raise KeyError("no session %r" % sid)
        return session

    def checkpoints(self, session: Session) -> studio_checkpoints.Checkpoints:
        kind = "git" if session.kind == "loki" else "files"
        return studio_checkpoints.Checkpoints(session.root / "checkpoints", session.work_root, kind, session.id)

    def new(self, text: str, start: bool = True, mode: str = "default", model: str = "", project: str = "",
            approve_edits: bool = False) -> Session:
        text = str(text or "").strip()
        if not text:
            raise ValueError("say what to build or fix")
        sid = time.strftime("%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        mode = mode if mode in MODES else "default"
        if project:
            root = Path(project).expanduser().resolve()
            if not studio_index.is_godot(root):
                raise ValueError("%s is not a Godot project (no project.godot)" % root)
            meta = {"id": sid, "kind": "godot", "title": text.splitlines()[0][:80], "status": "idle", "branch": "",
                    "worktree": "", "root": str(root), "project": studio_index.parse_project(
                        (root / "project.godot").read_text(encoding="utf-8", errors="replace")).get("name") or root.name,
                    "created": _now(), "updated": _now(), "messages": [], "mode": mode, "model_pref": model or "auto",
                    "approve_edits": bool(approve_edits), "turn": 0}
            note = "New session on the Godot project %s (%s). Every turn has a checkpoint." % (meta["project"], root)
        else:
            dest = self.destination()["choice"]
            if not dest:
                raise ValueError("Where is this going? Choose it first in Studio (My own LOKI, A new app from LOKI, "
                                 "or Just this computer).")
            base = studio_destination.work_repo(dest, self.repo)
            branch = "studio/" + sid
            tree = self.home / "worktrees" / sid
            tree.parent.mkdir(parents=True, exist_ok=True)
            code, out = _git(base, "worktree", "add", "-b", branch, str(tree), "HEAD")
            if code != 0:
                raise RuntimeError("could not make a worktree of %s: %s" % (base, out[-300:]))
            meta = {"id": sid, "kind": "loki", "title": text.splitlines()[0][:80], "status": "idle", "branch": branch,
                    "worktree": str(tree), "root": str(tree), "created": _now(), "updated": _now(), "messages": [],
                    "mode": mode, "model_pref": model or "auto", "approve_edits": bool(approve_edits), "turn": 0,
                    "destination": {k: dest.get(k) for k in ("kind", "name", "repo", "path", "project")}, "base_repo": str(base)}
            note = "New session in its own worktree %s (branch %s) - going to: %s." % (tree, branch, dest.get("name"))
        session = Session(self.home / "sessions" / sid, meta)
        session.save()
        with self.lock:
            self.sessions[sid] = session
        session.add("status", note, status="idle")
        self.send(sid, text, start=start)
        return session

    # ------------------------------------------------------------- messages, commands, mentions
    def live_mention(self, session: Session, name: str) -> str | None:
        if name == "todos":
            todos = session.meta.get("todos") or []
            return "\n".join("[%s] %s" % (t["status"], t["text"]) for t in todos) or None
        if session.kind != "godot":
            return None
        try:
            if name == "errors":
                rows = self.hub.errors(project=str(session.work_root))
                return "\n".join("%s: %s" % (r.get("source", ""), r.get("text", "")) for r in rows[-40:]) or "no errors"
            action = {"scene": "scene_tree", "selection": "selected_code"}[name]
            res = self.hub.call(action, {}, project=str(session.work_root), timeout=8)
            if name == "selection" and res.get("ok"):
                state = self.hub.call("editor_state", {}, project=str(session.work_root), timeout=8)
                return json.dumps({"selected_nodes": (state.get("result") or {}).get("selected_nodes"),
                                   "selected_code": res.get("result")}, indent=1, default=str)
            return json.dumps(res.get("result"), indent=1, default=str) if res.get("ok") else None
        except (studio_godot.GodotError, KeyError):
            return None

    def send(self, sid: str, text: str, start: bool = True) -> dict:
        session = self.get(sid)
        if session.meta.get("status") in FINAL:
            raise ValueError("this session is %s; start a new one" % session.meta["status"])
        text = str(text or "").strip()
        if not text:
            raise ValueError("empty message")
        name, args = studio_commands.parse(text)
        if name:
            handled = self.command(session, name, args)
            if handled.get("done"):
                return handled
            text = handled["text"]
        shown = text
        model_text, attached = studio_commands.expand(text, session.work_root, lambda n: self.live_mention(session, n))
        session.add("user", shown, attachments=attached) if attached else session.add("user", shown)
        with session.lock:
            if session.thread is not None and session.thread.is_alive():
                session.queue.append(model_text)
                return {"queued": True, "position": len(session.queue)}
            session.messages.append({"role": "user", "content": model_text})
            session.save()
        if start:
            self._start(session)
        return {"queued": False}

    def command(self, session: Session, name: str, args: str) -> dict:
        """A slash command. {"done": True, "output"} when Studio answered it; {"text"} = send this to the agent."""
        root = session.work_root
        tpl = studio_commands.templates(root if session.kind == "godot" else None, self.data)

        def done(output: str, **extra) -> dict:
            session.add("command", output, command=name, **extra)
            return {"done": True, "queued": False, "command": name, "output": output}

        if name in ("plan", "ask", "default", "agent"):
            self.set_mode(session.id, "default" if name == "agent" else name)
            if not args:
                return done("Mode: %s." % session.meta["mode"])
            return {"text": args}
        if name in studio_commands.PROMPTS:
            if name == "skill":
                skill, _, rest = args.partition(" ")
                return {"text": studio_commands.fill(studio_commands.PROMPTS[name], rest, skill=skill)}
            return {"text": studio_commands.fill(studio_commands.PROMPTS[name], args)}
        if name in tpl:
            values = {}
            if "{{scene}}" in tpl[name]["text"]:
                values["scene"] = self.live_mention(session, "scene") or ""
            if "{{selection}}" in tpl[name]["text"]:
                values["selection"] = self.live_mention(session, "selection") or ""
            return {"text": studio_commands.fill(tpl[name]["text"], args, **values)}
        ctx = self.tool_ctx(session)
        if name == "help":
            rows = studio_commands.listing(root if session.kind == "godot" else None, self.data)
            return done("\n".join("/%s - %s" % (r["name"], r["description"]) for r in rows))
        if name == "undo":
            turn = int(args) if args.strip().isdigit() else int(session.meta.get("turn") or 0)
            return done(self.undo(session.id, turn)["text"])
        if name == "checkpoints":
            rows = self.checkpoints(session).list()
            return done("\n".join("turn %d - %s - %s%s" % (r["turn"], time.strftime("%H:%M", time.localtime(r["t"])), r["label"],
                                                           (" (%d files)" % len(r["files"])) if r.get("files") else "")
                                  for r in rows) or "no checkpoints yet")
        if name == "todos":
            return done(self.live_mention(session, "todos") or "no todos")
        if name == "fork":
            new = self.fork(session.id)
            return done("Forked into session %s." % new.id, forked=new.id)
        if name == "model":
            pref = args.strip() or "auto"
            session.meta["model_pref"] = pref
            session.save()
            return done("This session now runs on: %s." % pref)
        if name == "approve":
            session.meta["approve_edits"] = args.strip().lower() in ("edits", "on", "yes", "ask")
            session.save()
            return done("Ask before every change: %s." % ("yes" if session.meta["approve_edits"] else "no"))
        if name == "docs":
            return done(godot_docs.answer(args, self.data))
        if name == "web":
            return done(studio_tools.web_search(ctx, args))
        if name == "remember":
            return done(studio_tools.remember(ctx, args))
        if name == "memory":
            return done(studio_tools.recall(ctx, args or session.meta.get("title", "")))
        if name == "skills":
            return done(studio_tools.list_skills(ctx))
        if name == "index":
            if session.kind == "godot":
                return done(studio_tools.project_index(ctx, args))
            return done(studio_tools.repo_map(ctx, args))
        if name == "graph":
            if session.kind != "godot":
                return done("/graph is for Godot projects.")
            return done("```mermaid\n%s\n```" % studio_tools.project_graph(ctx, args or "scenes"))
        if name == "errors":
            return done(studio_tools.editor_errors(ctx) if session.kind == "godot" else "no editor in a LOKI session")
        if name in ("run", "stop", "screenshot", "lag"):
            if session.kind != "godot":
                return done("/%s works in a Godot session (open the project in Godot with the plugin)." % name)
            if name == "run":
                return done(REG("run_game")(ctx, scene=args or "main"))
            if name == "stop":
                return done(REG("stop_game")(ctx))
            if name == "screenshot":
                out = studio_tools.screenshot(ctx, args or "game")
                return done(out, images=ctx.extra.get("images", []))
            return done(studio_tools.find_lag(ctx, float(args) if re.fullmatch(r"\d+(\.\d+)?", args or "") else 4.0))
        if name == "clear":
            return done("Start a new session with New session.")
        return done("Unknown command /%s. /help lists them." % name)

    def set_mode(self, sid: str, mode: str) -> dict:
        session = self.get(sid)
        if mode not in MODES:
            raise ValueError("mode is one of %s" % ", ".join(MODES))
        session.meta["mode"] = mode
        session.save()
        session.add("mode", mode, mode=mode)
        return session.summary()

    def tool_ctx(self, session: Session) -> studio_tools.Ctx:
        return studio_tools.Ctx(root=session.work_root, kind=session.kind, data=self.data, hub=self.hub,
                                checkpoints=self.checkpoints(session), session=session, turn=int(session.meta.get("turn") or 0),
                                repo=self.repo, extra=dict(self.tool_extra))

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
        end = time.time() + timeout
        while time.time() < end:
            thread = session.thread
            if thread is None:
                return True
            thread.join(max(0.05, min(1.0, end - time.time())))
            if not thread.is_alive() and session.thread is thread:
                return True
        return not (session.thread and session.thread.is_alive())

    def approve(self, sid: str, approval_id: str, yes: bool) -> bool:
        session = self.get(sid)
        pending = session.pending.get(str(approval_id))
        if pending is None:
            return False
        pending["yes"] = bool(yes)
        pending["event"].set()
        return True

    def answer(self, sid: str, question_id: str, answer: str) -> bool:
        session = self.get(sid)
        pending = session.pending.get(str(question_id))
        if pending is None or pending.get("kind") != "question":
            return False
        pending["answer"] = str(answer or "")[:4000]
        pending["yes"] = True
        pending["event"].set()
        return True

    def clear_queue(self, sid: str) -> int:
        session = self.get(sid)
        with session.lock:
            n = len(session.queue)
            session.queue.clear()
        return n

    def diff(self, sid: str) -> str:
        session = self.get(sid)
        if session.kind == "loki":
            return loki_mcp.diff_text(Path(session.meta["worktree"]))
        return self.files_diff(session)

    def files_diff(self, session: Session) -> str:
        """A Godot session: every file the agent changed, original (first checkpoint) -> now."""
        cps = self.checkpoints(session)
        first: dict = {}
        for row in cps.list():
            for rel, name in row.get("files", {}).items():
                first.setdefault(rel, (row["turn"], name))
        out = []
        for rel, (turn, name) in sorted(first.items()):
            old = "" if name is None else (cps.store / ("turn-%d" % turn) / name).read_text(encoding="utf-8", errors="replace")
            cur_path = session.work_root / rel
            new = cur_path.read_text(encoding="utf-8", errors="replace") if cur_path.is_file() else ""
            if old == new:
                continue
            out.append("diff --git a/%s b/%s\n" % (rel, rel) + "".join(difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), "a/" + rel if name is not None else "/dev/null",
                "b/" + rel if cur_path.is_file() else "/dev/null")))
        return "\n".join(out)

    def check(self, sid: str, suite: str = "") -> str:
        session = self.get(sid)
        if session.kind != "loki":
            out = "Tests are LOKI's suites; in a Godot session ask the agent to run the game's tests (/test)."
            session.add("check", out, passed=False)
            return out
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
        if session.kind != "loki":
            return "NOT shipped: shipping is for LOKI's own code; a Godot project is saved in place (undo with checkpoints)"
        if session.meta.get("status") in FINAL:
            return "NOT shipped: this session is %s" % session.meta["status"]
        if session.thread is not None and session.thread.is_alive():
            return "NOT shipped: the agent is still working; stop it or wait"
        message = " ".join(str(message or "").split()) or ("LOKI Studio: " + session.meta.get("title", ""))
        dest = session.meta.get("destination") or {"kind": "loki"}     # sessions from before destinations: LOKI itself
        kind = dest.get("kind", "loki")
        base = Path(session.meta.get("base_repo") or self.repo)
        info = studio_destination.detect(self.repo, self.dest_runner)
        why = studio_destination.guard(kind, studio_destination.origin(base, self.dest_runner) if kind in ("loki", "fork")
                                       else "", info.get("gh_user", ""))
        if why:
            session.add("error", "Ship refused: " + why)
            return "NOT shipped: " + why
        session.add("status", "Shipping: every suite runs, then commit, catch up with GitHub, push...", status="shipping")
        if kind in ("app", "local"):
            check = self.check_runner(Path(session.meta["worktree"]), "")
            out = ("NOT shipped:\nthe tests failed - nothing was committed\n" + check[-3000:]) if not check.startswith("ALL PASSED") \
                else studio_destination.publish(kind, Path(session.meta["worktree"]), base, session.meta["branch"], message,
                                                runner=self.dest_runner)
        else:
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
        if session.kind == "godot":
            if self.checkpoints(session).list():
                self.undo(sid, 1)
            session.set_status("discarded", "Discarded: every change this session made is undone; the history stays here.")
            return
        tree = Path(session.meta["worktree"])
        base = Path(session.meta.get("base_repo") or self.repo)
        _git(base, "worktree", "remove", "--force", str(tree))
        if tree.exists():
            shutil.rmtree(tree, ignore_errors=True)
        _git(base, "worktree", "prune")
        if not session.meta.get("shipped"):
            _git(base, "branch", "-D", session.meta["branch"])
        session.set_status("discarded", "Discarded: the worktree and its branch are gone; the history stays here.")

    # ------------------------------------------------------------- checkpoints, undo, fork
    def undo(self, sid: str, turn: int) -> dict:
        """Undo turn `turn` and every later one: files back as they were before it, editor actions undone,
        the conversation from that turn on removed."""
        session = self.get(sid)
        if session.thread is not None and session.thread.is_alive():
            raise ValueError("the agent is working; stop it first")
        turn = int(turn or 0)
        if turn < 1:
            return {"ok": False, "text": "Nothing to undo yet."}
        res = self.checkpoints(session).undo(turn)
        if not res.get("ok"):
            return {"ok": False, "text": "Cannot undo turn %d: %s" % (turn, res.get("error"))}
        editor_note = ""
        if session.kind == "godot":
            try:
                ed = self.hub.call("undo_turn", {"turn": turn}, project=str(session.work_root), timeout=15)
                editor_note = " Editor: %s." % ((ed.get("result") or {}).get("text", "done") if ed.get("ok") and isinstance(ed.get("result"), dict)
                                                else (ed.get("result") or ed.get("error")))
                self.hub.call("rescan", {}, project=str(session.work_root), timeout=5)
            except studio_godot.GodotError as exc:
                editor_note = " (The editor was not reachable: %s.)" % exc
        with session.lock:
            msgs = session.messages
            starts = [i for i, m in enumerate(msgs) if m.get("role") == "user" and m.get("turn")]
            cut = next((i for i in starts if msgs[i]["turn"] >= turn), None)
            if cut is not None:
                del msgs[cut:]
            session.meta["turn"] = turn - 1
            session.save()
        text = "Undid turn%s %s: %d file(s) back as they were (%s).%s" % (
            "s" if len(res["undone_turns"]) > 1 else "", ", ".join(map(str, res["undone_turns"])), len(res["files"]),
            ", ".join(res["files"][:12]) or "no files", editor_note)
        session.add("undo", text, turn=turn, files=res["files"])
        return {"ok": True, "text": text, **res}

    def fork(self, sid: str) -> Session:
        """A new session with this one's conversation; for LOKI code, a new worktree with the same files."""
        src = self.get(sid)
        nid = time.strftime("%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        meta = {k: v for k, v in json.loads(json.dumps(src.meta, default=str)).items()
                if k not in ("shipped", "last_check", "status")}
        meta.update(id=nid, title=("fork: " + src.meta.get("title", ""))[:80], created=_now(), updated=_now(),
                    forked_from=src.id, status="idle")
        if src.kind == "loki":
            branch = "studio/" + nid
            tree = self.home / "worktrees" / nid
            cp = studio_checkpoints.Checkpoints(self.home / "sessions" / nid / "fork-cp", Path(src.meta["worktree"]), "git", nid)
            commit, err = cp._snapshot_tree()   # the source's files as they are now
            code, out = _git(Path(src.meta.get("base_repo") or self.repo), "worktree", "add", "-b", branch, str(tree), commit or "HEAD")
            if code != 0:
                raise RuntimeError("could not fork the worktree: %s" % (out or err)[-300:])
            if commit:
                _git(tree, "reset", "--soft", "HEAD~1")   # the fork starts with the changes uncommitted, like its source
            meta.update(branch=branch, worktree=str(tree), root=str(tree))
        session = Session(self.home / "sessions" / nid, meta)
        session.save()
        with self.lock:
            self.sessions[nid] = session
        session.add("status", "Forked from %s: the same conversation%s." % (src.id, ", in its own worktree with the same files"
                                                                          if src.kind == "loki" else ""), status="idle")
        src.add("status", "Forked into %s." % nid, status=src.meta.get("status"))
        return session

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
            with session.lock:
                session.meta["turn"] = int(session.meta.get("turn") or 0) + 1
                turn = session.meta["turn"]
                last = next((m for m in reversed(session.messages) if m.get("role") == "user"), None)
                if last is not None and not last.get("turn"):
                    last["turn"] = turn
                for m in session.messages:
                    if m.get("role") == "user" and not m.get("turn"):
                        m["turn"] = turn
                session.save()
            try:
                cp = self.checkpoints(session).begin(turn, (last or {}).get("content", "")[:120])
                session.add("checkpoint", "Checkpoint: turn %d can be undone." % turn, turn=turn,
                            ok=not cp.get("error"))
            except Exception as exc:  # noqa: BLE001 - a missing checkpoint never stops the work
                session.add("progress", "No checkpoint for this turn (%s)." % exc)
            pref = str(session.meta.get("model_pref") or "auto")
            if pref in ("claude-code", "codex"):
                self._run_cli(session, pref)
            else:
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

    def _chain_for(self, session: Session):
        pref = str(session.meta.get("model_pref") or "auto")
        if pref in ("", "auto") or self.chat is not studio_models.chat:
            return None
        order = studio_models.chain()
        order.sort(key=lambda p: p.id != pref)
        return order

    def system_prompt(self, session: Session) -> str:
        mode = session.meta.get("mode") or "default"
        common = COMMON + MODE_TEXT.get(mode, "")
        todos = session.meta.get("todos") or []
        if todos:
            common += "\nYour todo list so far:\n" + "\n".join("[%s] %s" % (t["status"], t["text"]) for t in todos)
        if session.kind == "godot":
            root = session.work_root
            idx = studio_index.godot_index(root)
            ed = next((e for e in self.hub.connected() if e["project"] == str(root)), None)
            agents = ""
            for name in ("AGENTS.md", "CLAUDE.md", ".loki/AGENTS.md"):
                f = root / name
                if f.is_file():
                    agents += "\n\nThe project's %s (follow it):\n%s" % (name, f.read_text(encoding="utf-8", errors="replace")[:6000])
                    break
            editor_line = ("\nThe editor is CONNECTED (Godot %s): editor tools work live." % ed["godot"]) if ed else \
                ("\nNo Godot editor is connected for this project right now: files work, editor tools say so. "
                 "Ask the owner to open the project in Godot with the LOKI Studio plugin if you need the editor.")
            return GODOT_PROMPT.format(name=session.meta.get("project") or root.name, root=root,
                                       godot=(ed or {}).get("godot") or idx["project"].get("features", "4").split(",")[0],
                                       common=common) + editor_line + "\n\nThe project:\n" + studio_index.godot_summary(idx) + agents
        tree = session.meta["worktree"]
        return SYSTEM_PROMPT.format(worktree=tree, branch=session.meta["branch"], loki_line=self.loki_line(), common=common)

    def _tools_for(self, session: Session, listed_mcp: list, sub: bool = False) -> tuple:
        mode = "ask" if sub else (session.meta.get("mode") or "default")
        allowed = None if mode == "default" else READ_MCP
        mcp_names = {getattr(t, "name", "") for t in listed_mcp}
        tools = mcp_tools_to_openai(listed_mcp, allowed)
        local = []
        for t in studio_tools.for_session(session.kind, mode):
            if t.name in mcp_names:           # the MCP server's own version wins (read_file etc. in LOKI sessions)
                continue
            if sub and t.name in studio_tools.LOOP_TOOLS:
                continue
            local.append(t)
        return tools + [t.schema() for t in local], {t.name: t for t in local}

    async def _loop(self, session: Session) -> None:
        system = {"role": "system", "content": self.system_prompt(session)}
        factory = self.mcp_factory if session.kind == "loki" else (lambda _s: _NoMCP())
        async with factory(session) as client:
            listed = (await client.list_tools()).tools
            tools, local = self._tools_for(session, listed)
            for _step in range(MAX_STEPS):
                if session.stop.is_set():
                    return
                with session.lock:
                    convo = [system] + [{k: v for k, v in m.items() if k != "turn"} for m in session.messages]
                say = lambda text: session.add("progress", text)  # noqa: E731
                try:
                    provider, message, reasoning = await asyncio.to_thread(self.chat, convo, tools, self._chain_for(session), say,
                                                                           time.sleep, stop=session.stop)
                except studio_models.ModelError as exc:
                    if str(exc) != "stopped":
                        session.add("error", str(exc), how=studio_models.HOW_TO_GET_KEY if "no model is ready" in str(exc) else "")
                    return
                session.meta.update(provider=provider.id, model=provider.model)
                if reasoning:
                    session.add("thinking", reasoning[:6000], provider=provider.id)
                calls = self._calls(message, _step)
                entry = {"role": "assistant", "content": message.get("content") or ""}
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
                    result = await self._call(session, client, call, local, listed)
                    with session.lock:
                        session.messages.append({"role": "tool", "tool_call_id": call.get("id") or "",
                                                 "content": result[:24000]})
                        session.save()
                    if session.stop.is_set():
                        return
            session.add("error", "Stopped after %d steps (LOKI_STUDIO_MAX_STEPS). Say 'continue' to go on." % MAX_STEPS)

    @staticmethod
    def _calls(message: dict, step: int) -> list:
        calls = []
        for n, call in enumerate(message.get("tool_calls") or []):
            call = dict(call)
            call.setdefault("type", "function")
            call["id"] = call.get("id") or "call_%d_%d" % (step, n)
            fn = dict(call.get("function") or {})
            if not isinstance(fn.get("arguments"), str):
                fn["arguments"] = json.dumps(fn.get("arguments") or {})
            call["function"] = fn
            calls.append(call)
        return calls

    async def _call(self, session: Session, client, call: dict, local: dict, listed: list, quiet: bool = False,
                    sub: bool = False) -> str:
        fn = call.get("function") or {}
        name = str(fn.get("name") or "")
        add = (lambda kind, text="", **kw: session.add("progress", "subagent %s: %s" % (kind, str(text)[:200]))) if quiet else session.add
        try:
            args = json.loads(fn.get("arguments") or "{}") if isinstance(fn.get("arguments"), str) else dict(fn.get("arguments") or {})
        except ValueError:
            add("tool", "%s(<bad JSON>)" % name, tool=name)
            return "error: the arguments were not valid JSON; send them again as a JSON object"
        if not isinstance(args, dict):
            args = {}
        args.pop("confirm", None)
        add("tool", "%s(%s)" % (name, json.dumps(args, ensure_ascii=False)[:400]), tool=name, args=args)
        mode = "ask" if sub else (session.meta.get("mode") or "default")
        if name in OWNER_ONLY:
            return "error: only the owner ships (the Ship it button). Say the change is ready and suggest a message."
        mcp_names = {getattr(t, "name", "") for t in listed}
        tool = local.get(name)
        known = studio_tools.REGISTRY.get(name)
        if mode != "default" and tool is None and ((known is not None and not known.read_only) or name in WRITE_MCP
                                                   or (name in mcp_names and name not in READ_MCP)):
            return "refused: %s mode only reads. Switch to Default to change things." % mode.upper()
        if tool is None and name not in mcp_names:
            return "error: there is no tool %r here. Tools: %s" % (name, ", ".join(sorted(set(local) | mcp_names))[:1500])
        writes = (name in WRITE_MCP) if tool is None else (tool.writes or not tool.read_only)
        if mode != "default" and ((tool is None and name not in READ_MCP) or (tool is not None and not tool.read_only)):
            return "refused: %s mode only reads. Switch to Default to change things." % mode.upper()
        risky = name in ASK_TOOLS or (tool is not None and tool.risky) or \
            (session.meta.get("approve_edits") and writes and (tool is None or tool.writes))
        if risky and not sub:
            yes = await self._ask(session, name, args)
            if not yes:
                session.add("result", "the owner said no", tool=name)
                return "refused: the owner said no (or stopped the session)"
        elif risky:
            return "refused: a subagent cannot do that"
        if name == "ask_owner":
            answer = await self._question(session, str(args.get("question") or ""), list(args.get("options") or []))
            session.add("result", answer, tool=name)
            return answer
        if name == "subagent":
            text = await self._subagent(session, client, args, listed)
            session.add("result", text[:6000], tool=name)
            return text
        if tool is not None:
            ctx = self.tool_ctx(session)
            try:
                text = await asyncio.to_thread(tool.fn, ctx, **args)
            except TypeError as exc:
                text = "error: wrong arguments for %s (%s)" % (name, exc)
            except Exception as exc:  # noqa: BLE001 - a tool error goes back to the model
                text = "error: %s: %s" % (type(exc).__name__, exc)
            text = str(text)
            images = [p for p in ctx.extra.get("images", []) if p]
            add("result", text[:6000], tool=name, **({"images": images} if images else {}))
            if tool.writes and session.kind == "godot" and not text.startswith("error") and args.get("path"):
                session.add("diff", self._file_diff(session, str(args.get("path"))), path=args.get("path"))
            return text
        if name in ASK_TOOLS:
            args["confirm"] = loki_mcp.approval_code(self.secret, name, args)
        try:
            out = await client.call_tool(name, args)
            text = "\n".join(getattr(c, "text", "") or "" for c in (getattr(out, "content", None) or [])) or "(no output)"
        except Exception as exc:  # noqa: BLE001 - a tool error goes back to the model
            text = "error: %s: %s" % (type(exc).__name__, exc)
        add("result", text[:6000], tool=name)
        if name in WRITE_MCP and not text.startswith("error") and not quiet:
            session.add("diff", loki_mcp.diff_text(Path(session.meta["worktree"]), str(args.get("path") or ""))[:12000],
                        path=args.get("path"))
        if name == "run_tests":
            session.meta["last_check"] = {"t": _now(), "suite": args.get("suite", ""), "passed": text.startswith("ALL PASSED")}
        return text

    def _file_diff(self, session: Session, path: str) -> str:
        rel = path[6:] if path.startswith("res://") else path
        whole = self.files_diff(session)
        parts = [p for p in whole.split("diff --git ") if p.startswith("a/%s " % rel.strip("/"))]
        return ("diff --git " + parts[0])[:12000] if parts else "(no change in %s)" % path

    async def _ask(self, session: Session, tool: str, args: dict) -> bool:
        aid = uuid.uuid4().hex[:8]
        waiter = {"event": threading.Event(), "yes": None, "kind": "approval"}
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

    async def _question(self, session: Session, question: str, options: list) -> str:
        qid = uuid.uuid4().hex[:8]
        waiter = {"event": threading.Event(), "yes": None, "answer": "", "kind": "question"}
        session.pending[qid] = waiter
        session.meta["status"] = "waiting"
        session.save()
        session.add("question", question[:2000], question_id=qid, options=[str(o)[:120] for o in options[:8]])
        try:
            while not waiter["event"].is_set():
                if session.stop.is_set():
                    return "the owner did not answer (the session was stopped)"
                await asyncio.sleep(0.2)
            return "the owner answered: " + (waiter.get("answer") or "(no answer)")
        finally:
            session.pending.pop(qid, None)
            session.meta["status"] = "working"
            session.save()
            session.add("answered", waiter.get("answer") or "", question_id=qid)

    async def _subagent(self, session: Session, client, args: dict, listed: list) -> str:
        tasks = [str(t).strip() for t in (args.get("tasks") or []) if str(t).strip()][:3] or \
            ([str(args.get("task") or "").strip()] if str(args.get("task") or "").strip() else [])
        if not tasks:
            return "error: give a task"
        tools, local = self._tools_for(session, listed, sub=True)
        base = ("You are a helper of LOKI Studio's agent, with READ-ONLY tools and a small context. Do the task, then answer "
                "with the findings only (paths, names, line numbers, short facts). Work root: %s." % session.work_root)

        async def one(task: str) -> str:
            msgs = [{"role": "system", "content": base}, {"role": "user", "content": task}]
            for step in range(SUB_STEPS):
                if session.stop.is_set():
                    return "(stopped)"
                try:
                    _p, message, _r = await asyncio.to_thread(self.chat, msgs, tools, self._chain_for(session),
                                                              lambda t: None, time.sleep, stop=session.stop)
                except studio_models.ModelError as exc:
                    return "error: %s" % exc
                calls = self._calls(message, step)
                entry = {"role": "assistant", "content": message.get("content") or ""}
                if calls:
                    entry["tool_calls"] = calls
                msgs.append(entry)
                if not calls:
                    return entry["content"] or "(no answer)"
                for call in calls:
                    out = await self._call(session, client, call, local, listed, quiet=True, sub=True)
                    msgs.append({"role": "tool", "tool_call_id": call["id"], "content": out[:12000]})
            return "(the helper ran out of steps)"

        session.add("progress", "Subagent%s: %s" % ("s" if len(tasks) > 1 else "", " | ".join(t[:80] for t in tasks)))
        results = await asyncio.gather(*(one(t) for t in tasks))
        return "\n\n".join("## %s\n%s" % (t[:80], r) for t, r in zip(tasks, results))

    # ------------------------------------------------------------- Claude Code / Codex as the driver
    def _run_cli(self, session: Session, which: str) -> None:
        import studio_cli  # pylint: disable=import-outside-toplevel
        with session.lock:
            prompt = next((m["content"] for m in reversed(session.messages) if m.get("role") == "user"), "")
        runner = self.cli_runner or studio_cli.run
        session.meta.update(provider=which, model=which)
        result = runner(which, prompt, session, self, lambda kind, text: session.add(kind, text), session.stop)
        text = str(result.get("text") or "")
        if result.get("session"):
            session.meta["cli_session"] = result["session"]
        with session.lock:
            session.messages.append({"role": "assistant", "content": text})
            session.save()
        session.add("assistant" if result.get("ok") else "error", text or "(%s gave no answer)" % which, provider=which, model=which)


def REG(name: str):
    """A registered editor tool's function with ctx first (for slash commands)."""
    return studio_tools.REGISTRY[name].fn
