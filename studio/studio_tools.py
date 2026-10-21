"""Studio's own tools, next to the LOKI MCP API: the Ziva-parity layer.

Which tools a session gets depends on what it works on (`kind`) and its mode:

  kind "loki"   LOKI's own code in a session worktree: the LOKI MCP API (studio_core) + these:
                repo_map, godot_docs, todos, questions, memory, skills, web_search, subagent,
                generate_image, pc_worker
  kind "godot"  a Godot project (any of the owner's own games), live in the editor
                through the LOKI Studio plugin: project files (read/list/search/edit/write/delete,
                each write checkpointed), project_index / project_graph, every editor action
                (scene tree, nodes, properties, signals, scripts, scenes), run / stop the game,
                playtest_step (input -> wait -> screenshot -> new errors), find_lag, screenshots,
                plus the common ones above

Modes: "default" may change things; "plan" and "ask" only get READ tools (+ todos, questions,
memory) - a plan or an answer, never a change. Every tool is a plain function of (ctx, **args)
returning text; `ask_owner` and `subagent` are run by studio_core (they need the loop).
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import studio_paths  # noqa: F401  (engine/ on sys.path)
import studio_index
import godot_docs
import studio_godot

MODES = ("default", "plan", "ask")
DENY_PARTS = {".git", ".godot", "harness_data", "node_modules", "__pycache__", ".import"}
DENY_NAMES = re.compile(r"(^|/)(\.env(\..*)?|.*\.token|.*\.pem|.*\.key|id_rsa.*|export_credentials\.cfg)$", re.I)
MAX_READ = 60_000


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    required: tuple = ()
    fn: Callable | None = None
    read_only: bool = True          # may run in plan / ask mode
    kinds: tuple = ("loki", "godot")
    risky: bool = False             # asks the owner first, every time
    writes: bool = False            # changes the project (asks when the session asks before edits)

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description[:900], "parameters": {
            "type": "object", "properties": self.params, "required": list(self.required)}}}


@dataclass
class Ctx:
    """What a tool may use: the session's root, its checkpoints, the editor link, Studio's data."""
    root: Path
    kind: str
    data: Path
    hub: Any = None
    checkpoints: Any = None
    session: Any = None
    turn: int = 0
    repo: Path | None = None
    extra: dict = field(default_factory=dict)


REGISTRY: dict = {}


def tool(name: str, description: str, params: dict | None = None, required=(), read_only=True, kinds=("loki", "godot"),
         risky=False, writes=False):
    def wrap(fn):
        REGISTRY[name] = Tool(name, description, params or {}, tuple(required), fn, read_only, tuple(kinds), risky, writes)
        return fn
    return wrap


def S(desc: str, kind: str = "string", **extra) -> dict:
    return dict({"type": kind, "description": desc}, **extra)


def for_session(kind: str, mode: str = "default", editor: bool = True) -> list:
    out = []
    for t in REGISTRY.values():
        if kind not in t.kinds:
            continue
        if mode in ("plan", "ask") and not t.read_only:
            continue
        out.append(t)
    return out


# ------------------------------------------------------------------ the project's files (Godot sessions)
def inside(ctx: Ctx, rel: str) -> Path:
    raw = str(rel or ".").strip()
    if raw.startswith("res://"):
        raw = raw[6:] or "."
    raw = raw.replace("\\", "/")
    root = Path(ctx.root).resolve()
    target = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    try:
        inner = target.relative_to(root)
    except ValueError:
        raise PermissionError("%s is outside the project %s" % (rel, root)) from None
    if set(inner.parts) & DENY_PARTS or DENY_NAMES.search(inner.as_posix()):
        raise PermissionError("%s is off limits (secrets, caches, .git)" % rel)
    return target


def _after_write(ctx: Ctx, target: Path) -> None:
    if ctx.hub is not None and ctx.kind == "godot":
        try:
            ctx.hub.call("rescan", {"path": studio_index.res_path(ctx.root, target)}, project=str(ctx.root), timeout=3)
        except Exception:  # noqa: BLE001 - no editor: the files are still right
            pass


@tool("read_file", "Read a project file (res:// or relative). start_line/end_line (1-based) for a part of a big file.",
      {"path": S("res://player.gd or scripts/player.gd"), "start_line": S("first line", "integer"), "end_line": S("last line", "integer")},
      ("path",), kinds=("godot",))
def read_file(ctx: Ctx, path: str, start_line: int = 0, end_line: int = 0) -> str:
    try:
        text = inside(ctx, path).read_text(encoding="utf-8", errors="replace")
    except (PermissionError, OSError) as exc:
        return "error: %s" % exc
    if start_line or end_line:
        lines = text.splitlines()
        a, b = max(1, int(start_line or 1)), min(len(lines), int(end_line or len(lines)))
        text = "\n".join("%d: %s" % (i, lines[i - 1]) for i in range(a, b + 1))
    return text if len(text) <= MAX_READ else text[:MAX_READ] + "\n... (read a range with start_line/end_line)"


@tool("list_files", "List a project folder (pattern: a glob like *.gd).", {"path": S("folder, default the project root"),
      "pattern": S("glob")}, kinds=("godot",))
def list_files(ctx: Ctx, path: str = ".", pattern: str = "") -> str:
    try:
        target = inside(ctx, path)
    except PermissionError as exc:
        return "error: %s" % exc
    if not target.is_dir():
        return "error: %s is not a folder" % path
    rows = [c.name + ("/" if c.is_dir() else "") for c in sorted(target.iterdir())
            if c.name not in DENY_PARTS and not DENY_NAMES.search(c.name) and (not pattern or fnmatch.fnmatch(c.name, pattern))]
    return "\n".join(rows[:500]) or "(empty)"


@tool("search_files", "Search the project for a regular expression: path:line: text (glob narrows, e.g. *.gd).",
      {"pattern": S("regex"), "glob": S("file glob"), "path": S("folder")}, ("pattern",), kinds=("godot",))
def search_files(ctx: Ctx, pattern: str, glob: str = "", path: str = ".") -> str:
    try:
        rx = re.compile(pattern)
        base = inside(ctx, path)
    except (re.error, PermissionError) as exc:
        return "error: %s" % exc
    hits = []
    for f in sorted(base.rglob("*")):
        try:
            rel = f.relative_to(ctx.root)
        except ValueError:
            continue
        if not f.is_file() or set(rel.parts) & DENY_PARTS or DENY_NAMES.search(rel.as_posix()):
            continue
        if (glob and not fnmatch.fnmatch(f.name, glob)) or f.stat().st_size > 2_000_000 or f.suffix in (".png", ".jpg", ".glb", ".wav", ".ogg"):
            continue
        try:
            for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if rx.search(line):
                    hits.append("res://%s:%d: %s" % (rel.as_posix(), n, line.strip()[:200]))
                    if len(hits) >= 200:
                        return "\n".join(hits) + "\n... (narrow the search)"
        except OSError:
            continue
    return "\n".join(hits) or "no match"


@tool("edit_file", "Replace old_text (must appear exactly once: copy a few surrounding lines) with new_text in a project file.",
      {"path": S("file"), "old_text": S("exact text"), "new_text": S("replacement")}, ("path", "old_text", "new_text"),
      read_only=False, kinds=("godot",), writes=True)
def edit_file(ctx: Ctx, path: str, old_text: str, new_text: str) -> str:
    try:
        target = inside(ctx, path)
        text = target.read_text(encoding="utf-8")
    except (PermissionError, OSError) as exc:
        return "error: %s" % exc
    count = text.count(old_text) if old_text else 0
    if count != 1:
        return "error: old_text appears %d times in %s; it must appear exactly once" % (count, path)
    if ctx.checkpoints is not None:
        ctx.checkpoints.before_write(target)
    target.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
    _after_write(ctx, target)
    return "edited %s (%+d lines)" % (path, new_text.count("\n") - old_text.count("\n"))


@tool("write_file", "Create or overwrite a project file (scripts, scenes, shaders, resources, docs).",
      {"path": S("file"), "content": S("the whole file")}, ("path", "content"), read_only=False, kinds=("godot",), writes=True)
def write_file(ctx: Ctx, path: str, content: str) -> str:
    try:
        target = inside(ctx, path)
    except PermissionError as exc:
        return "error: %s" % exc
    if ctx.checkpoints is not None:
        ctx.checkpoints.before_write(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _after_write(ctx, target)
    return "wrote %s (%d lines)" % (path, content.count("\n") + 1)


@tool("delete_file", "Delete a project file (undoable with the turn's checkpoint).", {"path": S("file")}, ("path",),
      read_only=False, kinds=("godot",), writes=True)
def delete_file(ctx: Ctx, path: str) -> str:
    try:
        target = inside(ctx, path)
    except PermissionError as exc:
        return "error: %s" % exc
    if not target.is_file():
        return "error: no file %s" % path
    if ctx.checkpoints is not None:
        ctx.checkpoints.before_write(target)
    target.unlink()
    _after_write(ctx, target)
    return "deleted %s" % path


# ------------------------------------------------------------------ project awareness
@tool("project_index", "What is in the Godot project and how it hangs together: empty = the overview; a word = every scene, "
      "node, script, signal, autoload or input action matching it (e.g. 'player', 'CharacterBody3D', 'died').",
      {"query": S("a file, class, node type, signal, function or word")}, kinds=("godot",))
def project_index(ctx: Ctx, query: str = "") -> str:
    return studio_index.godot_query(studio_index.godot_index(ctx.root), query)


@tool("project_graph", "A mermaid diagram of the project: kind=scenes (instancing + scripts) or signals (who connects to whom). "
      "Put it in your answer in a ```mermaid block; Studio draws it.", {"kind": S("scenes | signals"), "focus": S("only paths containing this")},
      kinds=("godot",))
def project_graph(ctx: Ctx, kind: str = "scenes", focus: str = "") -> str:
    return studio_index.godot_mermaid(studio_index.godot_index(ctx.root), "signals" if "sig" in str(kind) else "scenes", focus)


@tool("repo_map", "The code map: per file its classes and functions (prefix narrows to a folder like engine/ or studio/).",
      {"prefix": S("folder")})
def repo_map(ctx: Ctx, prefix: str = "") -> str:
    prefix = str(prefix or "").strip().strip("/")
    if prefix and (".." in prefix or prefix.split("/")[0] in DENY_PARTS):
        return "error: not that folder"
    return studio_index.repo_map(ctx.root, prefix)


@tool("godot_docs", "The Godot class reference, offline and for this Godot version: a class ('CharacterBody3D'), a member "
      "('Node.get_tree', 'Input.is_action_pressed') or words ('move and slide'). Look up the REAL API before you use it.",
      {"query": S("class, Class.member or words")}, ("query",))
def godot_docs_tool(ctx: Ctx, query: str) -> str:
    return godot_docs.answer(query, ctx.data)


# ------------------------------------------------------------------ the editor (through the plugin)
def editor(ctx: Ctx, action: str, args: dict | None = None, timeout: float = 30.0) -> dict:
    if ctx.hub is None:
        raise studio_godot.GodotError("Studio has no editor link")
    args = dict(args or {})
    args.setdefault("turn", ctx.turn)
    return ctx.hub.call(action, args, project=str(ctx.root), timeout=timeout)


def _fmt(res: dict) -> str:
    if not res.get("ok"):
        return "error: " + (res.get("error") or "the editor said no")
    r = res.get("result")
    return r if isinstance(r, str) else json.dumps(r, indent=1, default=str)[:MAX_READ]


def _editor_tool(name: str, action: str, desc: str, params: dict, required=(), read_only=True, writes=False, timeout=30.0):
    def fn(ctx: Ctx, **args):
        try:
            return _fmt(editor(ctx, action, args, timeout))
        except studio_godot.GodotError as exc:
            return "error: %s" % exc
    REGISTRY[name] = Tool(name, desc, params, tuple(required), fn, read_only, ("godot",), False, writes)


_editor_tool("editor_state", "editor_state", "The live editor: open scenes, the edited scene, selected nodes, open scripts, the "
             "current script and its selected code, whether the game runs.", {})
_editor_tool("scene_tree", "scene_tree", "The LIVE node tree of the edited scene (or scene=res://...): paths, types, scripts.",
             {"scene": S("res:// of an open scene; empty = the edited one")})
_editor_tool("node_info", "node_info", "Every property of one node in the edited scene.", {"node": S("node path like Player/Camera3D")}, ("node",))
_editor_tool("selected_code", "selected_code", "The code the owner selected in Godot's script editor (file, lines, text).", {})
_editor_tool("set_property", "set_property", "Set a node's property in the edited scene, undoable in the editor. value is Godot text: "
             "5, true, \"text\", Vector3(0, 1, 0), Color(1, 0, 0), res://icon.svg (loads it).",
             {"node": S("node path"), "property": S("property name"), "value": S("Godot value text")}, ("node", "property", "value"),
             read_only=False, writes=True)
_editor_tool("add_node", "add_node", "Add a node to the edited scene (undoable): a class (type) or an instanced scene (scene=res://...tscn).",
             {"parent": S("parent path, '.' = the root"), "type": S("class, e.g. Sprite2D"), "scene": S("res:// .tscn to instance"),
              "name": S("node name"), "properties": S("{property: Godot value text}", "object")}, ("parent",), read_only=False, writes=True)
_editor_tool("remove_node", "remove_node", "Remove a node from the edited scene (undoable).", {"node": S("node path")}, ("node",),
             read_only=False, writes=True)
_editor_tool("connect_signal", "connect_signal", "Connect a signal in the edited scene (saved with the scene; undoable).",
             {"from": S("emitting node path"), "signal": S("signal name"), "to": S("receiving node path"), "method": S("method name")},
             ("from", "signal", "to", "method"), read_only=False, writes=True)
_editor_tool("attach_script", "attach_script", "Attach a script file to a node (undoable). Write the script with write_file first.",
             {"node": S("node path"), "script": S("res://...gd")}, ("node", "script"), read_only=False, writes=True)
_editor_tool("new_scene", "new_scene", "Create a new scene file with a root node and open it.",
             {"path": S("res://scenes/x.tscn"), "root_type": S("e.g. Node2D"), "root_name": S("root name")}, ("path",),
             read_only=False, writes=True)
_editor_tool("open_scene", "open_scene", "Open a scene in the editor.", {"path": S("res:// .tscn")}, ("path",))
_editor_tool("save_scene", "save_scene", "Save the edited scene (all=true: every open scene).", {"all": S("save all", "boolean")},
             read_only=False, writes=True)
_editor_tool("open_script", "open_script", "Show a script in Godot's script editor at a line.", {"path": S("res:// .gd"),
             "line": S("line", "integer")}, ("path",))
_editor_tool("select_nodes", "select_nodes", "Select nodes in the editor so the owner sees them.", {"nodes": S("node paths", "array",
             items={"type": "string"})}, ("nodes",))
_editor_tool("run_game", "run_game", "Play the game from the editor: scene=main (default), current, or a res:// scene.",
             {"scene": S("main | current | res://...")}, read_only=False)
_editor_tool("stop_game", "stop_game", "Stop the running game.", {}, read_only=False)
_editor_tool("game_tree", "game_tree", "The RUNNING game's live node tree (what actually exists at runtime).",
             {"depth": S("levels", "integer")})
_editor_tool("game_get", "game_get", "Read a value in the RUNNING game: a node's property (score, health, position...).",
             {"node": S("node path from the current scene, or /root/Autoload"), "property": S("property name")}, ("node", "property"))


@tool("editor_errors", "Errors and warnings from the Godot editor and the running game (script errors, failed loads, pushed "
      "errors), newest last. since = the index from a previous call to see only new ones.", {"since": S("index", "integer")},
      kinds=("godot",))
def editor_errors(ctx: Ctx, since: int = 0) -> str:
    try:
        rows = ctx.hub.errors(project=str(ctx.root), since=int(since or 0))
    except studio_godot.GodotError as exc:
        return "error: %s" % exc
    if not rows:
        return "no errors%s" % (" since %d" % since if since else "")
    return "\n".join("[%d] %s%s: %s%s" % (r.get("n", 0), r.get("source", "editor"), (" " + r.get("type", "")) if r.get("type") else "",
                                           r.get("text", ""), (" (%s:%s)" % (r.get("file"), r.get("line"))) if r.get("file") else "")
                     for r in rows[-80:]) + "\nnext since=%d" % (rows[-1].get("n", 0) + 1)


@tool("screenshot", "A picture of the editor or the running game: target=game (the game's viewport), 3d, 2d, or editor. "
      "Saved as a PNG the owner sees in the thread.", {"target": S("game | 3d | 2d | editor")}, kinds=("godot",))
def screenshot(ctx: Ctx, target: str = "game") -> str:
    try:
        res = editor(ctx, "screenshot", {"target": target or "game"}, 20)
    except studio_godot.GodotError as exc:
        return "error: %s" % exc
    if not res.get("ok"):
        return "error: " + res.get("error", "")
    r = res.get("result") or {}
    ctx.extra.setdefault("images", []).append(r.get("path", ""))
    return "screenshot of the %s: %sx%s, saved %s" % (r.get("target", target), r.get("width", "?"), r.get("height", "?"), r.get("path", "(not saved)"))


@tool("playtest_step", "ONE playtest turn: send input to the RUNNING game, wait, then get a screenshot, the new errors and what "
      "the game reports. events = [{action:'jump', hold_ms:200} | {key:'W', hold_ms:500} | {mouse:'left', x:400, y:300} | "
      "{text:'hello'} | {wait_ms:500}]. Run the game first (run_game). Look at the result, then decide the next step.",
      {"events": S("input events", "array", items={"type": "object"}), "wait_ms": S("wait after the input", "integer"),
       "screenshot": S("take a screenshot (default true)", "boolean")}, ("events",), read_only=False, kinds=("godot",))
def playtest_step(ctx: Ctx, events: list, wait_ms: int = 300, screenshot: bool = True) -> str:
    try:
        before = ctx.hub.errors(project=str(ctx.root))
        start_n = (before[-1].get("n", 0) + 1) if before else 0
        res = editor(ctx, "game_input", {"events": list(events or [])[:40], "wait_ms": int(wait_ms or 0)}, 60)
        out = ["input: " + _fmt(res)]
        if screenshot:
            out.append(globals()["screenshot"](ctx, "game"))
        new = ctx.hub.errors(project=str(ctx.root), since=start_n)
        out.append("new errors: " + ("; ".join(r.get("text", "")[:200] for r in new[-10:]) if new else "none"))
        return "\n".join(out)
    except studio_godot.GodotError as exc:
        return "error: %s" % exc


def analyse_lag(m: dict) -> str:
    """Plain-words reasons from the game's monitor samples."""
    tips = []
    fps = float(m.get("fps_min") or m.get("fps") or 0)
    if fps and fps < 30:
        tips.append("the frame rate drops to %.0f fps" % fps)
    proc = float(m.get("process_ms_max") or 0)
    phys = float(m.get("physics_ms_max") or 0)
    if proc > 12:
        tips.append("_process work takes up to %.1f ms a frame - look at the busiest scripts below and move work out of _process" % proc)
    if phys > 8:
        tips.append("physics takes up to %.1f ms - too many bodies/collision pairs, or heavy _physics_process" % phys)
    if float(m.get("draw_calls_max") or 0) > 2500:
        tips.append("%d draw calls - batch with MultiMesh, merge meshes, fewer materials" % m["draw_calls_max"])
    if float(m.get("objects") or 0) > 50000 or float(m.get("nodes") or 0) > 15000:
        tips.append("%s nodes / %s objects - too many; pool or free them" % (m.get("nodes"), m.get("objects")))
    if float(m.get("orphan_nodes") or 0) > 100:
        tips.append("%s orphan nodes (removed but never freed) - a leak; queue_free them" % m["orphan_nodes"])
    if float(m.get("video_mem_mb") or 0) > 1500:
        tips.append("%.0f MB of video memory - big textures; compress or downsize" % m["video_mem_mb"])
    return "; ".join(tips) or "no obvious hot spot in the monitors"


@tool("find_lag", "Find what makes the RUNNING game slow: samples Godot's performance monitors for some seconds (fps, frame and "
      "physics times, draw calls, nodes, objects, orphans, memory) and the busiest node types/scripts, then says where to look. "
      "Run the game first (run_game) and reproduce the slow part.", {"seconds": S("how long to sample (1-20)", "number")},
      kinds=("godot",))
def find_lag(ctx: Ctx, seconds: float = 4.0) -> str:
    try:
        res = editor(ctx, "game_monitors", {"seconds": max(1.0, min(20.0, float(seconds or 4)))}, 40)
    except studio_godot.GodotError as exc:
        return "error: %s" % exc
    if not res.get("ok"):
        return "error: " + res.get("error", "")
    m = res.get("result") or {}
    return "verdict: %s\n%s" % (analyse_lag(m), json.dumps(m, indent=1, default=str)[:8000])


# ------------------------------------------------------------------ todos, memory, skills, web, image, the PC
@tool("todo_write", "Your todo list for this session, shown to the owner live. Send the WHOLE list each time: "
      "[{text, status: pending|doing|done}]. Keep one item 'doing'.",
      {"items": S("the todo list", "array", items={"type": "object", "properties": {"text": {"type": "string"},
                                                                                     "status": {"type": "string"}}})}, ("items",))
def todo_write(ctx: Ctx, items: list) -> str:
    clean = []
    for it in list(items or [])[:40]:
        if isinstance(it, str):
            it = {"text": it}
        status = str((it or {}).get("status") or "pending").lower()
        clean.append({"text": str((it or {}).get("text") or "")[:200], "status": status if status in ("pending", "doing", "done") else "pending"})
    if ctx.session is not None:
        with ctx.session.lock:
            ctx.session.meta["todos"] = clean
            ctx.session.save()
        ctx.session.add("todos", "\n".join(("[x] " if t["status"] == "done" else "[>] " if t["status"] == "doing" else "[ ] ") + t["text"]
                                           for t in clean), todos=clean)
    return "todos saved (%d, %d done)" % (len(clean), sum(t["status"] == "done" for t in clean))


@tool("remember", "Keep a fact or lesson in LOKI's memory (shared by the Mac and the PC): a decision, a convention of this "
      "project, a fix that worked. Never a secret.", {"text": S("one short sentence"), "kind": S("project | decision | lesson | fact | preference")},
      ("text",))
def remember(ctx: Ctx, text: str, kind: str = "project") -> str:
    try:
        import memory_core  # pylint: disable=import-outside-toplevel
        item = memory_core.learn(text, kind=str(kind or "project"), root=ctx.data, source="studio",
                                 meta={"project": str(ctx.root.name)})
        return "remembered (%s): %s" % (item.get("status", "ok") if isinstance(item, dict) else "ok", str(text)[:120])
    except Exception as exc:  # noqa: BLE001
        return "error: memory is not available here (%s)" % exc


@tool("recall", "What LOKI's memory knows about something (facts, decisions, lessons, learned skills).", {"query": S("what to recall")},
      ("query",))
def recall(ctx: Ctx, query: str) -> str:
    try:
        import memory_core  # pylint: disable=import-outside-toplevel
        got = memory_core.recall(query, limit=8, root=ctx.data, repo=ctx.repo, mark_used=True)
        return got.get("evidence") or got.get("note") or "nothing"
    except Exception as exc:  # noqa: BLE001
        return "error: memory is not available here (%s)" % exc


def skill_dirs(ctx: Ctx) -> list:
    out = [Path(ctx.root) / ".loki" / "skills", Path(ctx.root) / "skills", Path(ctx.data) / "skills"]
    if ctx.repo:
        out.append(Path(ctx.repo) / "skills")
    seen, uniq = set(), []
    for d in out:
        key = str(d.resolve()) if d.exists() else str(d)
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    return uniq


def skills(ctx: Ctx) -> dict:
    found = {}
    for d in skill_dirs(ctx):
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("SKILL.md"))[:300]:
            text = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^name:\s*(.+)$", text, re.M)
            dm = re.search(r"^description:\s*(.+)$", text, re.M)
            name = (m.group(1).strip() if m else f.parent.name).strip("\"'")
            found.setdefault(name, {"name": name, "path": str(f), "description": (dm.group(1).strip() if dm else "")[:240]})
    return found


@tool("list_skills", "The skills (SKILL.md playbooks) this project and LOKI have: name and when to use it.", {})
def list_skills(ctx: Ctx) -> str:
    found = skills(ctx)
    return "\n".join("- %s: %s" % (s["name"], s["description"]) for s in found.values()) or "no skills found"


@tool("use_skill", "Load a skill's instructions (its SKILL.md) and follow them.", {"name": S("skill name")}, ("name",))
def use_skill(ctx: Ctx, name: str) -> str:
    found = skills(ctx)
    s = found.get(name) or next((v for k, v in found.items() if k.lower() == str(name).lower()), None)
    if not s:
        return "error: no skill %r. Skills: %s" % (name, ", ".join(found) or "none")
    return Path(s["path"]).read_text(encoding="utf-8", errors="replace")[:MAX_READ]


@tool("web_search", "Search the web (no key needed): results with titles, links and snippets. mode=web|news|academic|discussion.",
      {"query": S("query"), "mode": S("web | news | academic | discussion")}, ("query",))
def web_search(ctx: Ctx, query: str, mode: str = "web") -> str:
    try:
        import web_search as ws  # pylint: disable=import-outside-toplevel
        opener = ctx.extra.get("web_opener")
        found = ws.search(query, mode=mode or "web", opener=opener)
        return ws.format_results(query, found)
    except Exception as exc:  # noqa: BLE001
        return "error: web search failed (%s)" % exc


@tool("generate_image", "Make a picture with LOKI's local image model (sprites, textures, concept art) into the project.",
      {"prompt": S("what to draw"), "path": S("where to save, e.g. res://art/tree.png"), "width": S("px", "integer"),
       "height": S("px", "integer")}, ("prompt", "path"), read_only=False, writes=True)
def generate_image(ctx: Ctx, prompt: str, path: str, width: int = 512, height: int = 512) -> str:
    try:
        target = inside(ctx, path) if ctx.kind == "godot" else (Path(ctx.root) / str(path).lstrip("/")).resolve()
        if ctx.kind != "godot" and Path(ctx.root).resolve() not in target.parents:
            return "error: outside the worktree"
    except PermissionError as exc:
        return "error: %s" % exc
    maker = ctx.extra.get("image_maker")
    try:
        if maker is None:
            import creative  # pylint: disable=import-outside-toplevel
            maker = lambda p, w, h, out: creative.run_local_image(p, "", w, h, 0, 1, out)["files"]  # noqa: E731
        out_dir = Path(ctx.data) / "studio" / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        files = maker(prompt, int(width or 512), int(height or 512), out_dir)
    except Exception as exc:  # noqa: BLE001
        return "error: no local picture maker on this machine (%s). Install it in LOKI: Settings > Add-ons > local-image." % exc
    if not files:
        return "error: the picture maker made nothing"
    if ctx.checkpoints is not None:
        ctx.checkpoints.before_write(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(Path(files[0]).read_bytes())
    ctx.extra.setdefault("images", []).append(str(target))
    _after_write(ctx, target)
    return "made %s (%d bytes)" % (path, target.stat().st_size)


@tool("pc_worker", "Hand a long or GPU task to another of the owner's machines (default the PC) as a LOKI background job; "
      "returns the job id. Check it with pc_job. Asks the owner first.", {"task": S("what to do there"), "machine": S("peer name, default pc")},
      ("task",), read_only=False, risky=True)
def pc_worker(ctx: Ctx, task: str, machine: str = "pc") -> str:
    try:
        import peers  # pylint: disable=import-outside-toplevel
        peer = peers.find(machine or "pc")
        if not peer:
            return "error: no linked machine %r (tools/peer_link.py pair links the Mac and the PC)" % machine
        got = peers.call(peer, "POST", "/peer/jobs", {"prompt": str(task)[:16000], "title": "[Studio] " + str(task)[:60]})
        job = got.get("job") or {}
        return "started on %s: job %s (%s)" % (machine, job.get("id", "?"), job.get("status", "?"))
    except Exception as exc:  # noqa: BLE001
        return "error: %s" % exc


@tool("pc_job", "The status and output of a job on another machine (from pc_worker).", {"id": S("job id"), "machine": S("peer name")}, ("id",))
def pc_job(ctx: Ctx, id: str, machine: str = "pc") -> str:  # noqa: A002
    try:
        import peers  # pylint: disable=import-outside-toplevel
        peer = peers.find(machine or "pc")
        if not peer:
            return "error: no linked machine %r" % machine
        job = peers.call(peer, "GET", "/peer/jobs/" + re.sub(r"[^A-Za-z0-9]", "", str(id))[:16]).get("job") or {}
        return json.dumps({k: job.get(k) for k in ("id", "status", "title", "result", "error", "output")}, default=str)[:8000]
    except Exception as exc:  # noqa: BLE001
        return "error: %s" % exc


# Run by studio_core (they need the loop); listed here so they get schemas and mode rules.
REGISTRY["ask_owner"] = Tool("ask_owner", "Ask the owner a question and WAIT for the answer (a choice or free text). Use it when a "
                             "decision is theirs: which approach, a name, what the game should feel like.",
                             {"question": S("the question"), "options": S("choices to click (optional)", "array", items={"type": "string"})},
                             ("question",), None, True)
REGISTRY["subagent"] = Tool("subagent", "Run a helper agent with READ-ONLY tools and its own small context, for research inside "
                            "the project (find where X is done, summarise a system). tasks = several to run side by side (max 3).",
                            {"task": S("one task"), "tasks": S("several tasks", "array", items={"type": "string"})}, (), None, True)

LOOP_TOOLS = {"ask_owner", "subagent"}
