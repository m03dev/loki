"""The Godot editor link: LOKI Studio <-> the LOKI Studio plugin inside a running Godot editor.

The plugin (studio/godot_plugin/addons/loki_studio) is a second front end for Studio that lives in
the Godot editor, like Ziva does, in ANY Godot project. It finds Studio through the connect file
(~/.loki/studio_connect.json: url + token, written by Studio at start, owner-only permissions;
LOKI_STUDIO_CONNECT overrides the path) and talks to Studio's loopback HTTP API with that token.

Its editor bridge says hello (project path, name, Godot version), then LONG-POLLS for commands:

    POST /api/godot/hello   {project_path, project_name, godot_version, plugin_version}  -> {editor}
    GET  /api/godot/poll?editor=&wait=20        -> {commands: [{id, action, args}]}   (blocks <= wait s)
    POST /api/godot/result  {editor, id, ok, result | error}
    POST /api/godot/event   {editor, kind, data}   errors / output / selection / game events, pushed

The agent's Godot tools call `GodotHub.call(action, args)`: the command is queued for that
editor, the call waits for its result (or times out and says so). ACTIONS is the contract; the
plugin's bridge.gd implements the same names (tests/test_studio_godot.py checks both sides).
"""
from __future__ import annotations

import base64
import collections
import json
import os
import threading
import time
import uuid
from pathlib import Path

PLUGIN_VERSION = "1.1"
POLL_MAX_S = 25.0
STALE_S = 45.0                    # no poll for this long = the editor is gone

# action -> (what it does, writes?)   The editor bridge (bridge.gd) implements every one.
ACTIONS = {
    "editor_state": ("project, open scenes, the edited scene, selected nodes, open scripts, the current script and its selected code, playing or not", False),
    "scene_tree": ("the node tree of the edited scene (or args.scene): path, type, script, a few key properties", False),
    "node_info": ("every property (name, type, value) of one node (args.node = a path like Player/Camera3D)", False),
    "selected_code": ("the code selected in the script editor (or the current line) with the file and line numbers", False),
    "errors": ("errors and warnings from the editor and the running game since args.since (an index)", False),
    "output": ("the last lines of the editor's Output", False),
    "set_property": ("set node.property = value (args.node, args.property, args.value as Godot text like Vector3(0, 1, 0)); undoable", True),
    "add_node": ("add a node: args.parent, args.type (a class) or args.scene (res:// to instance), args.name, args.properties; undoable", True),
    "remove_node": ("remove args.node from the edited scene; undoable", True),
    "connect_signal": ("connect args.from.signal -> args.to.method in the edited scene (persistent); undoable", True),
    "attach_script": ("attach args.script (res://...gd) to args.node; undoable", True),
    "new_scene": ("create a scene: args.path (res://...tscn), args.root_type, args.root_name; opens it", True),
    "open_scene": ("open args.path in the editor", False),
    "save_scene": ("save the edited scene (or all open scenes with args.all)", True),
    "open_script": ("open args.path in the script editor at args.line", False),
    "select_nodes": ("select args.nodes (paths) in the scene tree dock", False),
    "rescan": ("rescan the file system after files changed on disk (scripts reload)", False),
    "run_game": ("play the game: args.scene = main | current | res://path", False),
    "stop_game": ("stop the running game", False),
    "screenshot": ("a PNG of args.target = editor | 2d | 3d | game (the running game's viewport)", False),
    "game_input": ("send input to the running game: args.events = [{action|key|mouse|text, hold_ms, x, y, wait_ms}]", False),
    "game_tree": ("the running game's live node tree (args.depth)", False),
    "game_monitors": ("sample the running game's performance monitors for args.seconds: fps, frame/physics times, draw calls, objects, nodes, memory; the busiest node types", False),
    "game_get": ("read a property of a node in the running game (args.node = a path from the scene root or /root/..., args.property)", False),
    "undo_turn": ("undo every editor action Studio made in turn >= args.turn (the editor's own UndoRedo)", True),
    "quit": ("close the editor (tests only)", False),
}
GAME_ACTIONS = {"screenshot", "game_input", "game_tree", "game_monitors", "game_get"}


class GodotError(RuntimeError):
    pass


def connect_path() -> Path:
    if os.getenv("LOKI_STUDIO_CONNECT"):
        return Path(os.environ["LOKI_STUDIO_CONNECT"])
    return Path.home() / ".loki" / "studio_connect.json"


def write_connect(path: Path, url: str, token: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"url": url, "token": token, "pid": os.getpid(), "t": time.time(),
                               "plugin_version": PLUGIN_VERSION}), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return path


def remove_connect(path: Path, token: str) -> None:
    try:
        if json.loads(Path(path).read_text(encoding="utf-8")).get("token") == token:
            Path(path).unlink()
    except (OSError, ValueError):
        pass


class Editor:
    def __init__(self, eid: str, hello: dict):
        self.id = eid
        self.project = str(Path(str(hello.get("project_path") or "")).resolve()) if hello.get("project_path") else ""
        self.name = str(hello.get("project_name") or Path(self.project).name or "Godot project")[:120]
        self.version = str(hello.get("godot_version") or "")[:40]
        self.plugin_version = str(hello.get("plugin_version") or "")[:20]
        self.queue: collections.deque = collections.deque()
        self.results: dict = {}
        self.cond = threading.Condition()
        self.last_seen = time.time()
        self.errors: collections.deque = collections.deque(maxlen=400)
        self.error_count = 0
        self.output: collections.deque = collections.deque(maxlen=400)
        self.state: dict = {}
        self.events: collections.deque = collections.deque(maxlen=200)

    def summary(self) -> dict:
        return {"editor": self.id, "project": self.project, "name": self.name, "godot": self.version,
                "plugin": self.plugin_version, "alive": self.alive(), "last_seen": self.last_seen,
                "errors": self.error_count, "playing": bool(self.state.get("playing")),
                "edited_scene": str(self.state.get("edited_scene") or "")}

    def alive(self) -> bool:
        return time.time() - self.last_seen < STALE_S


class GodotHub:
    def __init__(self, shots: Path | None = None):
        self.editors: dict = {}
        self.lock = threading.RLock()
        self.shots = Path(shots) if shots else None
        self.listeners: list = []      # callables(editor, kind, data): Studio adds events to sessions

    # ------------------------------------------------------------- the plugin's side
    def hello(self, data: dict) -> dict:
        project = str(data.get("project_path") or "")
        if not project:
            raise ValueError("hello needs project_path (the editor's res:// folder)")
        with self.lock:
            # the same project re-connecting (editor restart, plugin reload) keeps its id
            old = next((e for e in self.editors.values() if project and e.project == str(Path(project).resolve())), None)
            eid = old.id if old else "ed-" + uuid.uuid4().hex[:8]
            ed = Editor(eid, data)
            if old:
                ed.errors, ed.error_count, ed.output = old.errors, old.error_count, old.output
                with old.cond:            # anyone waiting on the old link gets an answer
                    old.cond.notify_all()
            self.editors[eid] = ed
        return {"editor": eid, "plugin_version": PLUGIN_VERSION, "actions": sorted(ACTIONS)}

    def get(self, eid: str) -> Editor:
        ed = self.editors.get(str(eid or ""))
        if ed is None:
            raise KeyError("no Godot editor %r is connected (it says hello first)" % eid)
        return ed

    def poll(self, eid: str, wait: float = 20.0) -> list:
        ed = self.get(eid)
        end = time.time() + max(0.0, min(POLL_MAX_S, float(wait or 0)))
        with ed.cond:
            ed.last_seen = time.time()
            while not ed.queue and time.time() < end and self.editors.get(eid) is ed:
                ed.cond.wait(min(1.0, max(0.05, end - time.time())))
                ed.last_seen = time.time()
            out = []
            while ed.queue and len(out) < 8:
                out.append(ed.queue.popleft())
            return out

    def result(self, eid: str, data: dict) -> None:
        ed = self.get(eid)
        cid = str(data.get("id") or "")
        with ed.cond:
            ed.last_seen = time.time()
            ed.results[cid] = {"ok": bool(data.get("ok", True)), "result": data.get("result"),
                               "error": str(data.get("error") or "")}
            ed.cond.notify_all()

    def event(self, eid: str, kind: str, data) -> None:
        ed = self.get(eid)
        ed.last_seen = time.time()
        kind = str(kind or "")
        if kind == "errors":
            for row in (data if isinstance(data, list) else [data])[:100]:
                if isinstance(row, dict):
                    ed.errors.append(dict(row, n=ed.error_count))
                    ed.error_count += 1
        elif kind == "output":
            for line in (data if isinstance(data, list) else [data])[:200]:
                ed.output.append(str(line)[:600])
        elif kind == "state" and isinstance(data, dict):
            ed.state.update(data)
        ed.events.append({"t": time.time(), "kind": kind})
        for fn in list(self.listeners):
            try:
                fn(ed, kind, data)
            except Exception:  # noqa: BLE001 - a listener never breaks the link
                pass

    # ------------------------------------------------------------- Studio's side
    def connected(self) -> list:
        with self.lock:
            return [e.summary() for e in self.editors.values() if e.alive()]

    def pick(self, eid: str = "", project: str = "") -> Editor:
        with self.lock:
            if eid:
                return self.get(eid)
            live = [e for e in self.editors.values() if e.alive()]
            if project:
                want = str(Path(project).resolve())
                match = [e for e in live if e.project == want]
                if match:
                    return max(match, key=lambda e: e.last_seen)
                raise GodotError("no Godot editor with %s open is connected. Open the project in Godot with the "
                                 "LOKI Studio plugin enabled (Project > Project Settings > Plugins)." % project)
            if not live:
                raise GodotError("no Godot editor is connected. Open your project in Godot with the LOKI Studio plugin "
                                 "enabled; it connects to Studio by itself.")
            return max(live, key=lambda e: e.last_seen)

    def call(self, action: str, args: dict | None = None, eid: str = "", project: str = "", timeout: float = 30.0) -> dict:
        """Run one editor action and wait for its result: {"ok", "result", "error"}."""
        if action not in ACTIONS:
            raise GodotError("unknown editor action %r (known: %s)" % (action, ", ".join(sorted(ACTIONS))))
        ed = self.pick(eid, project)
        cid = uuid.uuid4().hex[:10]
        with ed.cond:
            ed.queue.append({"id": cid, "action": action, "args": dict(args or {})})
            ed.cond.notify_all()
            end = time.time() + timeout
            while cid not in ed.results:
                left = end - time.time()
                if left <= 0:
                    try:
                        ed.queue.remove(next(c for c in ed.queue if c["id"] == cid))
                    except (StopIteration, ValueError):
                        pass
                    raise GodotError("the Godot editor did not answer %s within %.0f s" % (action, timeout))
                ed.cond.wait(min(1.0, left))
            res = ed.results.pop(cid)
        if action == "screenshot" and res.get("ok") and isinstance(res.get("result"), dict):
            res["result"] = self._save_shot(res["result"])
        return res

    def _save_shot(self, result: dict) -> dict:
        b64 = result.pop("png_base64", "")
        if not b64 or self.shots is None:
            return result
        try:
            raw = base64.b64decode(b64)
        except (ValueError, TypeError):
            return dict(result, error="the screenshot was not valid base64")
        self.shots.mkdir(parents=True, exist_ok=True)
        path = self.shots / ("%s-%s.png" % (time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:4]))
        path.write_bytes(raw)
        return dict(result, path=str(path), bytes=len(raw))

    def errors(self, eid: str = "", project: str = "", since: int = 0) -> list:
        ed = self.pick(eid, project)
        return [e for e in list(ed.errors) if e.get("n", 0) >= int(since or 0)]


def describe_actions() -> str:
    return "\n".join("%s%s - %s" % (name, " (changes the project)" if w else "", what) for name, (what, w) in sorted(ACTIONS.items()))
