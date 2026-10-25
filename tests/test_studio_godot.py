"""Session 29: LOKI Studio inside Godot (the plugin) and the full agent workflow - offline, under a minute.

  1. the plugin's files: present, plugin.cfg right, GDScript sane (tabs, @tool, preloads exist), it lives only
     in studio/godot_plugin (AGENTS.md's third Godot place) and the installer puts it into ANY project
  2. the contract: every editor action Studio knows is implemented by bridge.gd (and back), and every
     /api/... path the dock and the bridge call is served by Studio's server
  3. the editor link with a FAKE editor speaking the real HTTP protocol: hello, long-poll, results,
     events (errors), screenshots saved, re-hello after a Studio restart
  4. a Godot session on a scripted model: project index, docs, file edits with checkpoints, live editor
     actions, playtest_step, find_lag, todos, ask_owner, subagent, approvals before edits, Plan/Ask modes
     read-only, per-turn undo (files + the editor's UndoRedo), discard, the diff
  5. a LOKI session: git checkpoints + undo through the real LOKI MCP API, fork into a new worktree
  6. @-mentions, slash commands, prompt templates, AGENTS.md, memory, skills
  7. the offline Godot docs, the project index + mermaid graph, the repo map
  8. Studio as an MCP server; Claude Code / Codex as drivers (stream parsing with a fake CLI)
  9. REAL Godot (when a binary is here): the plugin loads in a headless editor in a temp project, its
     bridge connects to a real Studio server and does real editor actions with undo; the game bridge
     injects input into a real running game, reads it back, samples monitors, catches errors

    python tests/test_studio_godot.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

T0 = time.time()
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "studio"))
TMP = Path(tempfile.mkdtemp(prefix="loki-studio-godot-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_HEALTH_FILE"] = str(TMP / "provider_health.json")
os.environ["LOKI_HEALTH_PROBES"] = "0"
os.environ["LOKI_RATE_FILE_DIR"] = str(TMP / "ratelimit")
os.environ["LOKI_EMBED"] = "off"
os.environ["LOKI_STUDIO_CONNECT"] = str(TMP / "connect.json")
for _k in ("LOKI_BRIDGE_URL", "LOKI_STUDIO_MODEL", "LOKI_STUDIO_REPO", "LOKI_PEERS"):
    os.environ.pop(_k, None)
for _k in [k for k in os.environ if k.endswith("_API_KEY")]:
    os.environ.pop(_k)
os.environ["LOKI_BRIDGE_URL"] = "http://127.0.0.1:9"

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:700],)))


def section(title):
    print("\n== %s  (%.1fs)" % (title, time.time() - T0))


def git(cwd, *args):
    p = subprocess.run(["git", "-c", "user.email=t@loki", "-c", "user.name=t", *args], cwd=str(cwd), capture_output=True, text=True)
    return p.stdout.strip()


def wait_for(fn, timeout=10.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


PLUGIN = REPO / "studio" / "godot_plugin" / "addons" / "loki_studio"
DATA = TMP / "data"
DATA.mkdir(parents=True, exist_ok=True)

import studio_godot  # noqa: E402
import studio_tools  # noqa: E402
import studio_index  # noqa: E402
import studio_commands  # noqa: E402
import studio_checkpoints  # noqa: E402
import studio_models  # noqa: E402
import studio_core  # noqa: E402
import studio_server  # noqa: E402
import godot_docs  # noqa: E402
import install_godot_plugin  # noqa: E402

# ================================================================= 1. the plugin's files
section("1. the plugin: files, GDScript sanity, where it lives, the installer")
need = ["plugin.cfg", "plugin.gd", "api.gd", "bridge.gd", "dock.gd", "debugger.gd", "game_bridge.gd", "error_logger.gd", "context_menu.gd"]
check("every plugin file is there", all((PLUGIN / f).is_file() for f in need), [f for f in need if not (PLUGIN / f).is_file()])
cfg = (PLUGIN / "plugin.cfg").read_text(encoding="utf-8")
check("plugin.cfg names the plugin, its version and plugin.gd", '[plugin]' in cfg and 'name="LOKI Studio"' in cfg
      and 'script="plugin.gd"' in cfg and re.search(r'version="\d', cfg))
gd = {f: (PLUGIN / f).read_text(encoding="utf-8") for f in need if f.endswith(".gd")}
check("every script extends something", all(re.search(r"^extends \w+", t, re.M) for t in gd.values()))
check("the editor scripts are @tool (they run inside the editor)", all(gd[f].startswith("@tool") for f in
                                                                      ("plugin.gd", "api.gd", "bridge.gd", "dock.gd", "debugger.gd", "context_menu.gd")))
check("the game bridge is NOT a tool script (it only runs in the game)", not gd["game_bridge.gd"].startswith("@tool"))
bad_indent = [f for f, t in gd.items() for line in t.splitlines() if re.match(r"^ +\S", line) and not line.lstrip().startswith("##")]
check("GDScript is indented with tabs only", not bad_indent, bad_indent[:5])
refs = sorted(set(re.findall(r'"res://addons/loki_studio/([^"]+)"', "\n".join(gd.values()))))
check("every res://addons/loki_studio path the scripts use exists", refs and all((PLUGIN / r).is_file() for r in refs), refs)
check("no editor-only class in the game bridge (exports would break)", not re.search(r"\b(EditorInterface|EditorPlugin|EditorUndoRedoManager)\b",
                                                                                   gd["game_bridge.gd"]))
check("the optional 4.5+/4.4+ classes are loaded only when they exist", "ClassDB.class_exists(\"Logger\")" in gd["plugin.gd"]
      and "ClassDB.class_exists(\"EditorContextMenuPlugin\")" in gd["plugin.gd"] and "ClassDB.class_exists(\"EditorDock\")" in gd["plugin.gd"])
check("no project.godot, .godot cache or .uid inside the plugin folder", not list((REPO / "studio" / "godot_plugin").rglob("project.godot"))
      and not list((REPO / "studio" / "godot_plugin").rglob("*.uid")) and not list((REPO / "studio" / "godot_plugin").rglob(".godot")))
agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
check("AGENTS.md names the plugin folder as the third Godot place", "studio/godot_plugin/addons/loki_studio" in agents and "three" in agents.lower())
tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split()
stray = [f for f in tracked if f.endswith((".gd", ".tscn", ".tres", ".uid", ".godot", ".import")) and
         not f.startswith("studio/godot_plugin/addons/loki_studio/")]
check("no Godot files tracked outside the three places", not stray, stray[:5])

GP = TMP / "game"
(GP / "scenes").mkdir(parents=True)
(GP / "scripts").mkdir()
(GP / "project.godot").write_text('config_version=5\r\n\r\n[application]\r\n\r\nconfig/name="Pebble"\r\nrun/main_scene="res://scenes/main.tscn"\r\n'
                                  'config/features=PackedStringArray("4.7", "Forward Plus")\r\n\r\n[autoload]\r\n\r\nGame="*res://scripts/game.gd"\r\n\r\n'
                                  '[editor_plugins]\r\n\r\nenabled=PackedStringArray("res://addons/other/plugin.cfg")\r\n\r\n[input]\r\n\r\njump={\r\n"deadzone": 0.5,\r\n"events": []\r\n}\r\n',
                                  encoding="utf-8", newline="")
(GP / "scenes" / "main.tscn").write_text('[gd_scene load_steps=3 format=3]\n\n[ext_resource type="Script" path="res://scripts/player.gd" id="1"]\n'
                                         '[ext_resource type="PackedScene" path="res://scenes/coin.tscn" id="2"]\n\n'
                                         '[node name="Main" type="Node2D"]\n\n[node name="Player" type="CharacterBody2D" parent="."]\nscript = ExtResource("1")\n\n'
                                         '[node name="Coin" parent="." instance=ExtResource("2")]\n\n'
                                         '[connection signal="died" from="Player" to="." method="_on_player_died"]\n', encoding="utf-8")
(GP / "scenes" / "coin.tscn").write_text('[gd_scene format=3]\n\n[node name="Coin" type="Area2D"]\n', encoding="utf-8")
(GP / "scripts" / "player.gd").write_text("class_name Player\nextends CharacterBody2D\n\nsignal died\n@export var speed := 200.0\n\n"
                                          "func _physics_process(delta: float) -> void:\n\tvelocity.x = Input.get_axis(\"ui_left\", \"ui_right\") * speed\n"
                                          "\tmove_and_slide()\n\nfunc hit() -> void:\n\tdied.emit()\n", encoding="utf-8")
(GP / "scripts" / "game.gd").write_text("extends Node\n\nvar score := 0\n\nfunc _ready() -> void:\n\tvar s = preload(\"res://scenes/coin.tscn\")\n", encoding="utf-8")
(GP / "AGENTS.md").write_text("# Pebble rules\nAlways use typed GDScript. Coins are worth 10.\n", encoding="utf-8")
res = install_godot_plugin.install(GP)
pg = (GP / "project.godot").read_bytes().decode("utf-8")
check("the installer copies the plugin into any project", res["ok"] and (GP / "addons" / "loki_studio" / "plugin.gd").is_file(), res)
check("...enables it next to the project's other plugins", 'enabled=PackedStringArray("res://addons/other/plugin.cfg", "res://addons/loki_studio/plugin.cfg")' in pg, pg)
check("...adds the game bridge autoload and keeps the others", 'LokiStudioGame="*res://addons/loki_studio/game_bridge.gd"' in pg and 'Game="*res://scripts/game.gd"' in pg)
check("...and keeps Windows line ends", "\r\n" in pg and "\n" not in pg.replace("\r\n", ""))
install_godot_plugin.install(GP)
pg2 = (GP / "project.godot").read_bytes().decode("utf-8")
check("installing twice changes nothing", pg2 == pg and pg2.count("loki_studio/plugin.cfg") == 1 and pg2.count("LokiStudioGame=") == 1)
check("the installer refuses a folder that is not a Godot project", not install_godot_plugin.install(TMP / "nope")["ok"])
gone = install_godot_plugin.install(GP, remove=True)
pg3 = (GP / "project.godot").read_bytes().decode("utf-8")
check("--remove takes it out again (files, plugin entry, autoload)", gone["ok"] and not (GP / "addons" / "loki_studio").exists()
      and "loki_studio" not in pg3 and "res://addons/other/plugin.cfg" in pg3)
install_godot_plugin.install(GP)

# ================================================================= 2. the contract
section("2. the contract: editor actions and the dock's API paths")
impl = set(re.findall(r"^func _do_(\w+)\(", gd["bridge.gd"], re.M))
check("bridge.gd implements every editor action Studio knows", set(studio_godot.ACTIONS) <= impl, sorted(set(studio_godot.ACTIONS) - impl))
check("...and Studio knows every action bridge.gd implements", impl <= set(studio_godot.ACTIONS), sorted(impl - set(studio_godot.ACTIONS)))
game_kinds = set(re.findall(r'^\t\t"(\w+)":', gd["game_bridge.gd"], re.M))
check("the game bridge answers what the editor bridge asks it", {"input", "screenshot", "tree", "monitors", "get"} <= game_kinds, game_kinds)
api_paths = sorted(set(p.split("?")[0] for p in re.findall(r'"(/api/[a-z/_]+(?:\?[^"]*)?)"', gd["dock.gd"] + gd["bridge.gd"] + gd["api.gd"])))
check("the dock and the bridge use Studio's API", len(api_paths) >= 15, api_paths)

FAKE = TMP / "fake-loki"
(FAKE / "tools").mkdir(parents=True)
(FAKE / "engine").mkdir()
(FAKE / "README.md").write_text("LOKI\nThe clear button.\n", encoding="utf-8")
(FAKE / "AGENTS.md").write_text("# AGENTS\nboth platforms\n", encoding="utf-8")
(FAKE / "HANDOFF.md").write_text("# HANDOFF\nnow\n", encoding="utf-8")
(FAKE / "engine" / "core.py").write_text("def route(x):\n    return x\n\nclass Engine:\n    pass\n", encoding="utf-8")
(FAKE / "tools" / "ship.py").write_text("import sys\nprint('  fake  1 passed, 0 failed'); sys.exit(0)\n", encoding="utf-8")
(FAKE / ".gitignore").write_text("harness_data/\n", encoding="utf-8")
git(FAKE, "init", "-q", "-b", "master")
git(FAKE, "add", "-A")
git(FAKE, "commit", "-qm", "c1")


class Script:
    """A scripted model: each call pops the next reply; records what it was sent."""

    def __init__(self):
        self.queue: list = []
        self.calls: list = []
        self.lock = threading.Lock()

    def __call__(self, messages, tools, _chain, say, sleep, stop=None):
        with self.lock:
            self.calls.append({"messages": json.loads(json.dumps(messages)), "tools": [t["function"]["name"] for t in tools or []]})
            item = self.queue.pop(0) if self.queue else {"content": "done (script ran out)"}
        if callable(item):
            item = item(messages)
        msg = {"role": "assistant", "content": item.get("content", "")}
        if item.get("tool"):
            msg["tool_calls"] = [{"id": "c%d" % len(self.calls), "type": "function",
                                  "function": {"name": item["tool"], "arguments": json.dumps(item.get("args", {}))}}]
        return studio_models.Provider("nvidia", "fake", "http://x", "deepseek-ai/deepseek-v4.1-flash", key="k"), msg, item.get("thinking", "")


def tool(tool_name_, **args):
    return {"tool": tool_name_, "args": args}


chat = Script()
hub = studio_godot.GodotHub(shots=DATA / "studio" / "shots")
from mcp import Client  # noqa: E402
import loki_mcp  # noqa: E402
holder: dict = {}


def mcp_factory(session):
    return Client(loki_mcp.build_server(loki_mcp.LokiAPI(worktree=session.meta["worktree"], repo=FAKE, data=DATA,
                                                         approval_secret=holder["studio"].secret, python=sys.executable,
                                                         bridge_url="http://127.0.0.1:9", token_file=DATA / "app" / "engine.token")))


studio = studio_core.Studio(repo=FAKE, data=DATA, mcp_factory=mcp_factory, chat=chat, python=sys.executable, hub=hub)
holder["studio"] = studio
srv = studio_server.StudioServer(studio, port=0, connect_file=TMP / "connect.json")
srv.start()
BASE = "http://127.0.0.1:%d" % srv.port
conn = json.loads((TMP / "connect.json").read_text())
check("Studio writes the connect file the plugin reads (url + token, owner-only)", conn["url"] == BASE and conn["token"] == srv.token
      and (os.name == "nt" or oct((TMP / "connect.json").stat().st_mode)[-3:] == "600"), conn)


def http(method, path, body=None, timeout=15):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": "Bearer " + srv.token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


unknown = []
for p in api_paths:
    if p in ("/api/godot/poll",):
        continue
    code, data = (http("GET", p) if p in ("/api/state", "/api/models", "/api/commands", "/api/mentions", "/api/session", "/api/session/diff")
                  else http("POST", p, {}))
    if code == 404 and "unknown endpoint" in str(data.get("error", "")):
        unknown.append(p)
check("every path the dock and the bridge call is served by Studio's server", not unknown, unknown)
code, data = http("GET", "/api/godot/poll?editor=nobody&wait=0")
check("a poll from an unknown editor is a 404 (the bridge then says hello again)", code == 404, (code, data))


# ================================================================= 3. the editor link, with a fake editor
section("3. the editor link with a fake editor on the real HTTP protocol")


class FakeEditor:
    """Speaks bridge.gd's protocol over HTTP: hello, long-poll, answer; a tiny scene with undo per turn."""

    def __init__(self, project):
        self.project = str(project)
        self.nodes = {".": "Node2D", "Player": "CharacterBody2D", "Coin": "Area2D"}
        self.props: dict = {}
        self.history: list = []          # (turn, undo fn)
        self.seen: list = []
        self.eid = ""
        self.stop = False
        self.playing = False
        self.thread = threading.Thread(target=self.run, daemon=True)

    def hello(self):
        code, data = http("POST", "/api/godot/hello", {"project_path": self.project, "project_name": "Pebble", "godot_version": "4.7.2",
                                                         "plugin_version": "1.0"})
        self.eid = data.get("editor", "")

    def run(self):
        self.hello()
        while not self.stop:
            code, data = http("GET", "/api/godot/poll?editor=%s&wait=2" % self.eid, timeout=10)
            if code == 404:
                self.hello()
                continue
            for cmd in data.get("commands", []):
                self.seen.append(cmd)
                ok, result = self.do(cmd["action"], cmd.get("args") or {})
                http("POST", "/api/godot/result", {"editor": self.eid, "id": cmd["id"], "ok": ok,
                                                   "result": result if ok else None, "error": "" if ok else result})

    def do(self, action, a):
        turn = int(a.get("turn", 0))
        if action == "editor_state":
            return True, {"project": self.project, "edited_scene": "res://scenes/main.tscn", "selected_nodes": ["Player"],
                          "open_scripts": ["res://scripts/player.gd"], "playing": self.playing}
        if action == "scene_tree":
            return True, {"scene": "res://scenes/main.tscn", "nodes": [{"path": p, "type": t} for p, t in self.nodes.items()]}
        if action == "selected_code":
            return True, {"file": "res://scripts/player.gd", "from_line": 7, "to_line": 8, "text": "velocity.x = ..."}
        if action == "add_node":
            name = a.get("name") or a.get("type")
            self.nodes[name] = a.get("type", "")
            self.history.append((turn, lambda n=name: self.nodes.pop(n, None)))
            return True, "added %s" % name
        if action == "set_property":
            key = (a["node"], a["property"])
            old = self.props.get(key)
            self.props[key] = a["value"]
            self.history.append((turn, lambda k=key, o=old: self.props.__setitem__(k, o)))
            return True, "%s.%s = %s" % (a["node"], a["property"], a["value"])
        if action == "undo_turn":
            n = 0
            for t, fn in reversed(list(self.history)):
                if t >= int(a.get("turn", 0)):
                    fn()
                    n += 1
            self.history = [(t, f) for t, f in self.history if t < int(a.get("turn", 0))]
            return True, {"undone": n, "text": "undid %d editor action(s)" % n}
        if action == "run_game":
            self.playing = True
            return True, "the game runs (main)"
        if action == "stop_game":
            self.playing = False
            return True, "stopped"
        if action == "game_input":
            if not self.playing:
                return False, "the game is not running from this editor (run_game first)"
            http("POST", "/api/godot/event", {"editor": self.eid, "kind": "errors", "data": [
                {"source": "game", "type": "error", "text": "Invalid access to property 'hp' on a null instance", "file": "res://scripts/player.gd", "line": 9}]})
            return True, {"sent": ["action %s" % e.get("action", e.get("key")) for e in a.get("events", [])]}
        if action == "screenshot":
            import base64
            png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()
            return True, {"target": a.get("target"), "width": 640, "height": 360, "png_base64": png}
        if action == "game_monitors":
            return True, {"fps": 24.0, "fps_min": 11.0, "process_ms_max": 31.0, "physics_ms_max": 2.0, "draw_calls_max": 120,
                          "nodes": 900, "objects": 4000, "orphan_nodes": 350, "processing": [["res://scripts/enemy.gd", 300]]}
        if action == "rescan":
            return True, "rescanned"
        return False, "fake editor: no %s" % action


ed = FakeEditor(GP.resolve())
ed.thread.start()
live = wait_for(lambda: [e for e in hub.connected() if e["project"] == str(GP.resolve())], 10)
check("the editor says hello and shows as connected (project, Godot version)", live and live[0]["project"] == str(GP.resolve())
      and live[0]["godot"] == "4.7.2", live)
r = hub.call("editor_state", {}, project=str(GP), timeout=10)
check("an editor action goes through the long-poll and comes back", r["ok"] and r["result"]["selected_nodes"] == ["Player"], r)
r = hub.call("screenshot", {"target": "game"}, project=str(GP), timeout=10)
shot = Path(r["result"].get("path", ""))
check("a screenshot is saved as a PNG file in Studio's data (not kept in memory)", r["ok"] and shot.is_file() and shot.read_bytes().startswith(b"\x89PNG")
      and "png_base64" not in r["result"], r)
code, data = http("GET", "/api/shot?path=" + urllib.request.quote(str(shot)))
check("the window and the dock can fetch it (only from Studio's picture folders)", code == 200 and data["data"].startswith("data:image/png;base64,")
      and http("GET", "/api/shot?path=" + urllib.request.quote(str(GP / "project.godot")))[0] == 404)
try:
    hub.call("make_coffee", {}, project=str(GP))
    check("an unknown action is refused before it is sent", False)
except studio_godot.GodotError:
    check("an unknown action is refused before it is sent", True)
try:
    hub.call("editor_state", {}, project=str(TMP / "other"))
    check("no editor for another project: a plain error that says how to connect one", False)
except studio_godot.GodotError as exc:
    check("no editor for another project: a plain error that says how to connect one", "LOKI Studio plugin" in str(exc), exc)
old_id = ed.eid
again = hub.hello({"project_path": str(GP), "project_name": "Pebble", "godot_version": "4.7.2"})
check("the same project saying hello again keeps its editor id", again["editor"] == old_id)
code, data = http("POST", "/api/godot/call", {"action": "quit", "args": {}})
check("nobody can close the editor over the API", code == 400)

# ================================================================= 4. a Godot session
section("4. a Godot session: index, docs, files + checkpoints, live editor, playtest, lag, todos, questions, undo")
XML = TMP / "docs-xml"
XML.mkdir()
(XML / "CharacterBody2D.xml").write_text('<?xml version="1.0" encoding="UTF-8" ?>\n<class name="CharacterBody2D" inherits="PhysicsBody2D">'
                                         '<brief_description>A 2D physics body specialized for characters moved by script.</brief_description>'
                                         '<description>Use [method move_and_slide].</description><methods><method name="move_and_slide">'
                                         '<return type="bool" /><description>Moves the body based on [member velocity].</description></method></methods>'
                                         '<members><member name="velocity" type="Vector2" setter="" getter="" default="Vector2(0, 0)">Current velocity.</member></members>'
                                         '<signals></signals><constants><constant name="MOTION_MODE_GROUNDED" value="0" enum="MotionMode">Ground.</constant></constants></class>',
                                         encoding="utf-8")
(XML / "PhysicsBody2D.xml").write_text('<?xml version="1.0" ?><class name="PhysicsBody2D" inherits="CollisionObject2D"><brief_description>Abstract.</brief_description>'
                                       '<description></description><methods><method name="move_and_collide"><return type="KinematicCollision2D" />'
                                       '<param index="0" name="motion" type="Vector2" /><description>Moves.</description></method></methods></class>', encoding="utf-8")
(XML / "version.py").write_text('major = 4\nminor = 7\npatch = 2\nstatus = "stable"\n', encoding="utf-8")
built = godot_docs.build(DATA, folder=str(XML))
check("the Godot docs cache builds from Godot's class XML (offline)", built["ok"] and built["classes"] == 2 and built["version"] == "4.7.2-stable", built)

chat.queue = [
    tool("todo_write", items=[{"text": "find the player", "status": "doing"}, {"text": "add a jump", "status": "pending"}]),
    tool("project_index", query="player"),
    tool("godot_docs", query="CharacterBody2D.move_and_slide"),
    tool("edit_file", path="res://scripts/player.gd", old_text="@export var speed := 200.0", new_text="@export var speed := 260.0\n@export var jump := 420.0"),
    tool("write_file", path="res://scripts/coin.gd", content="extends Area2D\n\nconst VALUE := 10\n"),
    tool("add_node", parent=".", type="Sprite2D", name="Shadow"),
    tool("set_property", node="Player", property="position", value="Vector2(10, 20)"),
    tool("write_file", path="../escape.txt", content="x"),
    tool("write_file", path=".godot/editor/x.cfg", content="x"),
    {"content": "Done: speed 260, a jump value, coin.gd, a Shadow node. ```mermaid\ngraph LR\n a-->b\n```"},
]
s = studio.new("Make the player faster and add a coin script", project=str(GP))
studio.wait(s.id, 30)
ev = s.events
types = [e["type"] for e in ev]
results = {e.get("tool"): e["text"] for e in ev if e["type"] == "result"}
check("a Godot session works on the project in place (no worktree), kind godot", s.kind == "godot" and s.meta["root"] == str(GP.resolve())
      and s.meta["project"] == "Pebble" and not s.meta["worktree"], s.meta)
sysmsg = chat.calls[0]["messages"][0]["content"]
check("its system prompt: the live editor, the project overview and the project's AGENTS.md", "inside the owner's Godot editor" in sysmsg
      and "res://scripts/player.gd" in sysmsg and "Coins are worth 10" in sysmsg and "CONNECTED" in sysmsg, sysmsg[:400])
tl = chat.calls[0]["tools"]
check("it gets the Godot tools (files, editor, playtest, lag, docs, index) and not LOKI's ship", all(t in tl for t in (
    "read_file", "edit_file", "write_file", "scene_tree", "add_node", "set_property", "run_game", "playtest_step", "find_lag",
    "screenshot", "editor_errors", "godot_docs", "project_index", "project_graph", "todo_write", "ask_owner", "subagent",
    "remember", "web_search")) and "ship" not in tl and "run_tests" not in tl, tl)
check("todos stream to the owner and are kept with the session", any(e["type"] == "todos" for e in ev) and s.summary()["todos"][0]["text"] == "find the player")
check("project_index answers from the real files (class, signals, used by scenes)", "class_name Player" in results.get("project_index", "")
      and "died" in results.get("project_index", "") and "res://scenes/main.tscn" in results.get("project_index", ""), results.get("project_index"))
check("godot_docs answers from the offline reference", "Moves the body based on velocity" in results.get("godot_docs", ""), results.get("godot_docs"))
check("edit_file changed the real file", "speed := 260.0" in (GP / "scripts" / "player.gd").read_text())
check("write_file made a new script", (GP / "scripts" / "coin.gd").read_text().startswith("extends Area2D"))
check("the live editor did the scene edits (add_node, set_property) with the turn number",
      ed.nodes.get("Shadow") == "Sprite2D" and ed.props.get(("Player", "position")) == "Vector2(10, 20)"
      and all(c["args"].get("turn") == 1 for c in ed.seen if c["action"] in ("add_node", "set_property")), ed.seen[-4:])
esc = [e["text"] for e in ev if e["type"] == "result" and e.get("tool") == "write_file" and e["text"].startswith("error")]
check("files outside the project and the .godot cache are refused", len(esc) == 2 and not (TMP / "escape.txt").exists(), esc)
check("writes ask the editor to rescan", any(c["action"] == "rescan" for c in ed.seen))
check("every write shows its diff in the thread", any(e["type"] == "diff" and "+@export var jump := 420.0" in e["text"] for e in ev))
check("a checkpoint event opens the turn", "checkpoint" in types and s.meta["turn"] == 1)
diff = studio.diff(s.id)
check("the session's diff: every file it changed, from before the session", "a/scripts/player.gd" in diff and "/dev/null" in diff
      and "+const VALUE := 10" in diff and "-@export var speed := 200.0" in diff, diff[:600])

# turn 2: playtest + lag + a question + a subagent
chat.queue = [
    tool("run_game", scene="main"),
    tool("playtest_step", events=[{"action": "jump", "hold_ms": 200}], wait_ms=100),
    tool("find_lag", seconds=2),
    tool("ask_owner", question="Should coins respawn?", options=["yes", "no"]),
    tool("subagent", task="where is the score kept?"),
    tool("search_files", pattern="score"),           # the subagent's own call
    {"content": "score is in res://scripts/game.gd (var score)"},   # the subagent's answer
    tool("stop_game"),
    {"content": "Playtested: jump works, one error; lag: _process in enemy.gd. Coins respawn as you said."},
]
studio.send(s.id, "playtest the jump and look for lag")
q = wait_for(lambda: [e for e in s.events if e["type"] == "question"], 20)
check("ask_owner shows the question with its choices and waits", q and q[-1]["options"] == ["yes", "no"] and s.meta["status"] == "waiting", q)
code, data = http("POST", "/api/session/answer", {"id": s.id, "question": q[-1]["question_id"], "answer": "yes"}) if q else (0, {})
studio.wait(s.id, 30)
ev = s.events
res2 = [e for e in ev if e["type"] == "result"]
play = next((e["text"] for e in res2 if e.get("tool") == "playtest_step"), "")
check("playtest_step: input -> screenshot -> the NEW game errors, in one result", "action jump" in play and "screenshot of the game" in play
      and "null instance" in play, play)
check("...and the screenshot is in the thread for the owner", any(e.get("images") for e in res2 if e.get("tool") == "playtest_step"))
lag = next((e["text"] for e in res2 if e.get("tool") == "find_lag"), "")
check("find_lag says where the time goes, in plain words", "_process work takes up to 31.0 ms" in lag and "orphan nodes" in lag
      and "enemy.gd" in lag, lag[:400])
check("the owner's answer went back to the agent", any(m.get("role") == "tool" and "the owner answered: yes" in str(m.get("content")) for m in s.messages))
sub = next((e["text"] for e in res2 if e.get("tool") == "subagent"), "")
check("a subagent researched with read-only tools and reported back", "res://scripts/game.gd" in sub, sub)
sub_call = next((c for c in chat.calls if c["messages"][0]["content"].startswith("You are a helper")), None)
check("...with no write, editor-change or loop tools", sub_call and "search_files" in sub_call["tools"] and not any(
    t in sub_call["tools"] for t in ("write_file", "edit_file", "add_node", "subagent", "ask_owner", "run_game")), sub_call and sub_call["tools"])
check("turn 2 has its own checkpoint", s.meta["turn"] == 2 and len(studio.checkpoints(s).list()) == 2)

# undo turn 1 (and 2): files back, the editor's actions undone, the conversation trimmed
code, data = http("POST", "/api/session/undo", {"id": s.id, "turn": 1})
check("Undo turn 1 puts every file back as it was before the session", code == 200 and data["ok"]
      and "speed := 200.0" in (GP / "scripts" / "player.gd").read_text() and not (GP / "scripts" / "coin.gd").exists(), data)
check("...the editor undid its scene actions of those turns", "Shadow" not in ed.nodes and ed.props.get(("Player", "position")) is None
      and any(c["action"] == "undo_turn" and c["args"]["turn"] == 1 for c in ed.seen))
check("...and the conversation goes back to before that turn", not [m for m in s.messages if m.get("role") == "user"] and s.meta["turn"] == 0
      and not studio.checkpoints(s).list(), [m.get("content", "")[:40] for m in s.messages])

# Plan mode: read-only
chat.queue = [tool("write_file", path="res://x.gd", content="x"), tool("todo_write", items=["read player.gd", "add jump"]),
              {"content": "Plan: 1. read player.gd 2. add a jump."}]
studio.send(s.id, "/plan add a double jump")
studio.wait(s.id, 20)
last = chat.calls[-1]
check("/plan switches to Plan mode and sends the task", s.meta["mode"] == "plan" and any(m.get("content") == "add a double jump" for m in last["messages"]))
check("Plan mode: no tool that changes things is offered", "write_file" not in last["tools"] and "add_node" not in last["tools"]
      and "read_file" in last["tools"] and "todo_write" in last["tools"], last["tools"])
check("...and one called anyway is refused, nothing written", not (GP / "x.gd").exists() and any(
    m.get("role") == "tool" and "PLAN mode only reads" in str(m.get("content")) for m in s.messages))
check("the system prompt says PLAN", "MODE: PLAN" in last["messages"][0]["content"])
http("POST", "/api/session/mode", {"id": s.id, "mode": "default"})

# Ask before edits
http("POST", "/api/session/approve_edits", {"id": s.id, "on": True})
chat.queue = [tool("write_file", path="res://notes.txt", content="hello"), tool("write_file", path="res://notes2.txt", content="x"),
              {"content": "one written, one refused"}]
studio.send(s.id, "write two notes")
first = wait_for(lambda: s.pending and [e for e in s.events if e["type"] == "approval"], 15)
check("with 'Ask first' every file change waits for Approve", bool(first) and not (GP / "notes.txt").exists())
studio.approve(s.id, first[-1]["approval"], True)
second = wait_for(lambda: s.pending and len([e for e in s.events if e["type"] == "approval"]) >= len(first) + 1, 15)
studio.approve(s.id, [e for e in s.events if e["type"] == "approval"][-1]["approval"], False)
studio.wait(s.id, 20)
check("...Approve writes, Deny does not", (GP / "notes.txt").read_text() == "hello" and not (GP / "notes2.txt").exists())

# a message while it works is queued; /undo; discard
chat.queue = [lambda m: (time.sleep(0.8), {"content": "first"})[1], {"content": "second"}]
studio.send(s.id, "first message")
time.sleep(0.2)
qd = studio.send(s.id, "second message")
studio.wait(s.id, 20)
check("a message typed while the agent works is queued, then handled in order", qd.get("queued") and
      [m["content"] for m in s.messages if m.get("role") == "assistant"][-2:] == ["first", "second"])
studio.send(s.id, "/checkpoints")
check("/checkpoints lists the turns you can go back to", "turn" in s.events[-1]["text"] and s.events[-1]["type"] == "command")
studio.discard(s.id)
check("Discard in a Godot session undoes every change of the session", not (GP / "notes.txt").exists() and s.meta["status"] == "discarded")

# ================================================================= 5. a LOKI session: git checkpoints, fork
section("5. a LOKI session: git checkpoints through the LOKI MCP API, undo, fork")
chat.queue = [tool("repo_map", prefix="engine"),
              tool("edit_file", path="README.md", old_text="The clear button.", new_text="The clear button (tooltip)."),
              tool("write_file", path="engine/new_mod.py", content="X = 1\n"), {"content": "done"}]
ls = studio.new("Add a tooltip")
studio.wait(ls.id, 30)
wt = Path(ls.meta["worktree"])
rmap = next((e["text"] for e in ls.events if e["type"] == "result" and e.get("tool") == "repo_map"), "")
check("a LOKI session keeps its own worktree and gets the repo map", wt.is_dir() and "engine/core.py" in rmap and "route, Engine" in rmap, rmap)
check("its tools: the LOKI MCP API + Studio's own (no ship, no Godot editor tools)", "edit_file" in chat.calls[-1]["tools"]
      and "loki_status" in chat.calls[-1]["tools"] and "todo_write" in chat.calls[-1]["tools"] and "add_node" not in chat.calls[-1]["tools"]
      and "ship" not in chat.calls[-1]["tools"])
check("the edit and the new file happened in the worktree", "(tooltip)" in (wt / "README.md").read_text() and (wt / "engine" / "new_mod.py").is_file())
cps = studio.checkpoints(ls).list()
check("the turn's checkpoint is a git snapshot commit (the branch is not touched)", cps and cps[0]["kind"] == "git" and len(cps[0]["commit"]) == 40
      and git(wt, "rev-parse", "HEAD") == git(FAKE, "rev-parse", "master")
      and git(wt, "rev-parse", "refs/studio-checkpoints/%s/1" % ls.id) == cps[0]["commit"], cps)
fork = studio.fork(ls.id)
fwt = Path(fork.meta["worktree"])
check("Fork: a new session with the same conversation and its own worktree with the same changes", fwt.is_dir() and fwt != wt
      and "(tooltip)" in (fwt / "README.md").read_text() and (fwt / "engine" / "new_mod.py").is_file()
      and len(fork.messages) == len(ls.messages) and fork.meta["forked_from"] == ls.id
      and git(fwt, "rev-parse", "HEAD") == git(FAKE, "rev-parse", "master"))
out = studio.undo(ls.id, 1)
check("Undo turn 1 (git): the edit reverted AND the new file removed", out["ok"] and "(tooltip)" not in (wt / "README.md").read_text()
      and not (wt / "engine" / "new_mod.py").exists() and git(wt, "status", "--short") == "", (out, git(wt, "status", "--short")))
check("...the fork keeps its changes", "(tooltip)" in (fwt / "README.md").read_text())
check("...and the checkpoint ref is cleaned up", not git(wt, "for-each-ref", "refs/studio-checkpoints/%s" % ls.id))
studio.discard(fork.id)
studio.discard(ls.id)

# ================================================================= 6. mentions, commands, templates, memory, skills
section("6. @-mentions, slash commands, templates, memory, skills")
text, names = studio_commands.expand("look at @scripts/player.gd and @res://scenes/ and @nothere.gd and @../secret", GP)
check("@file attaches its text, @folder its listing; missing or outside paths are skipped", names == ["@scripts/player.gd", "@scenes"]
      and "class_name Player" in text and "main.tscn" in text, names)
check("@-mention completion lists project paths (and the live ones)", "scripts/player.gd" in studio_commands.complete(GP, "play")
      and "scene" in studio_commands.complete(GP, "sc"))
(GP / ".loki" / "prompts").mkdir(parents=True)
(GP / ".loki" / "prompts" / "juice.md").write_text("---\ndescription: add game feel\n---\nAdd juice (screen shake, particles) to {{args}}. Selected: {{selection}}\n",
                                                   encoding="utf-8")
chat.queue = [{"content": "ok"}]
g2 = studio.new("hello", project=str(GP))
studio.wait(g2.id, 10)
code, data = http("GET", "/api/commands?id=" + g2.id)
names_ = {c["name"]: c for c in data["commands"]}
check("/api/commands lists built-ins and the project's own templates", {"plan", "ask", "undo", "fork", "docs", "lag", "playtest"} <= set(names_)
      and names_.get("juice", {}).get("description") == "add game feel", sorted(names_)[:40])
chat.queue = [{"content": "juiced"}]
studio.send(g2.id, "/juice the coin pickup")
studio.wait(g2.id, 10)
sent = [m["content"] for m in g2.messages if m.get("role") == "user"][-1]
check("a template becomes the message, with {{args}} and the live {{selection}} filled in", sent.startswith("Add juice (screen shake, particles) to the coin pickup")
      and "velocity.x" in sent, sent)
chat.queue = [{"content": "seen"}]
studio.send(g2.id, "what is @scene and @selection")
studio.wait(g2.id, 10)
sent = [m["content"] for m in g2.messages if m.get("role") == "user"][-1]
ue = [e for e in g2.events if e["type"] == "user"][-1]
check("@scene and @selection attach the LIVE editor's tree and selection", "CharacterBody2D" in sent and "selected_nodes" in sent
      and ue.get("attachments") == ["@scene", "@selection"], ue)
r = studio.send(g2.id, "/docs CharacterBody2D")
check("/docs answers at once from the offline reference", r.get("done") and "CharacterBody2D < PhysicsBody2D" in r["output"], r)
r = studio.send(g2.id, "/remember Pebble coins are worth 10")
r2 = studio.send(g2.id, "/memory coins")
check("/remember and /memory use LOKI's memory (the Mac + PC one)", "remembered" in r["output"] and "worth 10" in r2["output"], (r, r2))
(GP / ".loki" / "skills" / "juice").mkdir(parents=True)
(GP / ".loki" / "skills" / "juice" / "SKILL.md").write_text("---\nname: juice\ndescription: game feel\n---\nShake the camera 0.1 s.\n", encoding="utf-8")
r = studio.send(g2.id, "/skills")
check("/skills lists the project's skills (and LOKI's)", "juice: game feel" in r["output"], r["output"][:300])
r = studio.send(g2.id, "/graph signals")
check("/graph draws the signal graph as a mermaid diagram", "```mermaid" in r["output"] and "died" in r["output"], r["output"])
r = studio.send(g2.id, "/model codex")
check("/model picks another driver for this session", g2.meta["model_pref"] == "codex" and "codex" in r["output"])
r = studio.send(g2.id, "/nonsense")
check("an unknown command says so and lists help", "Unknown command" in r["output"])
r = studio.send(g2.id, "/help")
check("/help lists every command and template", "/playtest" in r["output"] and "/juice" in r["output"])
r = studio.send(g2.id, "/lag 2")
check("/lag runs find_lag on the running game at once", "verdict:" in r["output"] or "error" in r["output"], r["output"][:200])

# ================================================================= 7. docs, index, repo map
section("7. the offline Godot docs, the project index, mermaid, the repo map")
check("docs: Class.member", "move_and_slide() -> bool" in godot_docs.show("CharacterBody2D.move_and_slide", DATA))
check("docs: a property with its default", "velocity: Vector2 = Vector2(0, 0)" in godot_docs.show("CharacterBody2D.velocity", DATA))
check("docs: words find members", any(h[1] == "CharacterBody2D.move_and_slide" for h in godot_docs.search("move slide", DATA)))
check("docs: an unknown class names the closest ones", "Closest" in godot_docs.show("CharacterBody", DATA))
idx = studio_index.godot_index(GP)
check("index: project.godot (name, main scene, autoloads, input actions)", idx["project"]["name"] == "Pebble" and idx["project"]["autoloads"].get("Game")
      == "res://scripts/game.gd" and "jump" in idx["project"]["inputs"])
sc = idx["scenes"]["res://scenes/main.tscn"]
check("index: scenes (nodes, scripts, instances, signal connections)", any(n["script"] == "res://scripts/player.gd" for n in sc["nodes"])
      and any(n["instance"] == "res://scenes/coin.tscn" for n in sc["nodes"]) and sc["connections"][0]["signal"] == "died")
check("index: scripts (class_name, extends, signals, exports, funcs, preloads)", idx["scripts"]["res://scripts/player.gd"]["class_name"] == "Player"
      and idx["scripts"]["res://scripts/player.gd"]["signals"] == ["died"] and "speed" in idx["scripts"]["res://scripts/player.gd"]["exports"]
      and "res://scenes/coin.tscn" in idx["scripts"]["res://scripts/game.gd"]["refs"])
check("index: the plugin's own files are part of the project too", any(p.startswith("res://addons/loki_studio/") for p in idx["scripts"]))
mm = studio_index.godot_mermaid(idx, "scenes")
check("mermaid: scenes -> instanced scenes and scripts", mm.startswith("graph LR") and "-->|Coin|" in mm and "-.->" in mm, mm)
check("the window draws mermaid diagrams (no CDN: its own small renderer)", "mermaid" in (REPO / "studio" / "ui" / "studio.js").read_text())

# ================================================================= 8. Studio as an MCP server; CLI drivers
section("8. Studio as an MCP server (for Claude Code / Codex / Cursor); Claude Code and Codex as drivers")
import studio_mcp  # noqa: E402
tools8 = studio_mcp.Tools(studio_mcp.StudioLink(str(TMP / "connect.json"), str(GP)))
st8 = tools8.studio_status()
check("studio_status through Studio's API: the connected editor", "Pebble" in st8 and "4.7.2" in st8, st8[:300])
out8 = tools8.godot("scene_tree")
check("godot(action) drives the live editor", "CharacterBody2D" in out8, out8[:200])
check("godot_docs and project_index work with no Studio at all", "CharacterBody2D" in tools8.godot_docs("CharacterBody2D")
      and "Player" in tools8.project_index("player"))
out8 = tools8.godot_playtest_step('[{"action": "jump"}]')
check("godot_playtest_step: the same playtest turn for an outside client", "screenshot" in out8 or "error" in out8, out8[:200])


async def list_mcp():
    async with Client(studio_mcp.build_server(tools8)) as c:
        return [t.name for t in (await c.list_tools()).tools]
names8 = asyncio.run(list_mcp())
check("the MCP server lists Studio's tools", {"godot", "godot_playtest_step", "godot_find_lag", "godot_docs", "studio_new_session"} <= set(names8), names8)
dead = studio_mcp.Tools(studio_mcp.StudioLink(str(TMP / "missing.json"), str(GP)))
check("Studio not running: a plain message", "not running" in dead.studio_status())

import studio_cli  # noqa: E402
cl = [json.dumps({"type": "system", "session_id": "abc"}),
      json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading."}, {"type": "tool_use", "name": "mcp__loki_studio__godot", "input": {"action": "scene_tree"}}]}}),
      json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "Main [Node2D]"}]}}),
      json.dumps({"type": "result", "result": "All done.", "session_id": "abc"})]
parsed = [k for line in cl for k in studio_cli.parse_line("claude-code", line)]
check("Claude Code's stream-json: tool calls, results, the answer, the session id", ("tool", 'mcp__loki_studio__godot({"action": "scene_tree"})') in parsed
      and ("final", "All done.") in parsed and ("session", "abc") in parsed, parsed)
cx = studio_cli.parse_line("codex", json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Codex done."}}))
check("Codex's --json events: the answer", ("final", "Codex done.") in cx, cx)


class FakeProc:
    def __init__(self, argv, **kw):
        self.argv = argv
        self.stdout = iter(line + "\n" for line in cl)

    def wait(self):
        return 0

    def poll(self):
        return 0


seen_argv = {}
chat.queue = []
studio.cli_runner = lambda which, prompt, session, st, emit, stop: (seen_argv.update(argv=studio_cli.argv_for(which, prompt, session, st)),
                                                                    studio_cli.run(which, prompt, session, st, emit, stop, popen=FakeProc))[1]
g3 = studio.new("tidy the player script", project=str(GP), model="claude-code")
studio.wait(g3.id, 10)
check("a session driven by Claude Code: its stream lands in the thread, the answer is the reply", any(e["type"] == "assistant" and e["text"] == "All done."
      for e in g3.events) and any(e["type"] == "tool" and "scene_tree" in e["text"] for e in g3.events) and g3.meta.get("cli_session") == "abc")
argv = seen_argv.get("argv", [])
cfg_mcp = json.loads((g3.root / "mcp.json").read_text()) if (g3.root / "mcp.json").exists() else {}
check("...started with Studio's MCP server for the project and acceptEdits (Plan -> plan)", "--mcp-config" in argv and "acceptEdits" in argv
      and "studio_mcp.py" in json.dumps(cfg_mcp) and str(GP.resolve()) in json.dumps(cfg_mcp), argv)
check("the model list offers Auto, DeepSeek on NVIDIA, LM Studio, Ollama, Claude Code and Codex",
      {"auto", "nvidia", "openrouter", "local", "lmstudio", "claude-code", "codex"} <= {m["id"] for m in studio_models.choices({})})

# ================================================================= 9. real Godot
section("9. REAL Godot: the plugin in a headless editor, the game bridge in a running game")


def find_godot():
    for cand in (os.getenv("GODOT_BIN", ""), shutil.which("godot") or "", shutil.which("godot4") or "",
                 str(Path.home() / "godotengine" / "godot" / "bin" / "godot.linuxbsd.editor.x86_64.llvm")):
        if cand and Path(cand).is_file():
            return cand
    return ""


GODOT = find_godot()
if not GODOT:
    print("  SKIP no Godot binary here (GODOT_BIN) - the real-editor checks run on a machine with Godot")
else:
    RP = TMP / "real"
    RP.mkdir()
    (RP / "project.godot").write_text('config_version=5\n\n[application]\n\nconfig/name="Real Probe"\nrun/main_scene="res://main.tscn"\n\n'
                                      '[input]\n\njump={\n"deadzone": 0.5,\n"events": []\n}\n', encoding="utf-8")
    (RP / "main.tscn").write_text('[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" path="res://main.gd" id="1"]\n\n'
                                  '[node name="Main" type="Node2D"]\nscript = ExtResource("1")\n', encoding="utf-8")
    (RP / "main.gd").write_text("extends Node2D\n\nvar jumps := 0\nvar _was := false\n\n\nfunc _physics_process(_delta: float) -> void:\n"
                                "\tvar now := Input.is_action_pressed(\"jump\")\n\tif now and not _was:\n\t\tjumps += 1\n\t_was = now\n", encoding="utf-8")
    (RP / "broken.gd").write_text("extends Node\n\nfunc oops(:\n", encoding="utf-8")
    install_godot_plugin.install(RP)
    env = dict(os.environ, LOKI_STUDIO_CONNECT=str(TMP / "connect.json"), LOKI_STUDIO_TEST="1")
    log = (TMP / "godot-editor.log").open("w")
    proc = subprocess.Popen([GODOT, "--headless", "--editor", "--path", str(RP)], stdout=log, stderr=subprocess.STDOUT, env=env)
    spec = {"out": str(TMP / "selftest.json"), "steps": [
        {"kind": "get", "args": {"node": ".", "property": "jumps"}},
        {"kind": "input", "args": {"events": [{"action": "jump", "hold_ms": 60}, {"wait_ms": 40}, {"action": "jump", "hold_ms": 60},
                                              {"key": "W", "hold_ms": 20}, {"action": "missing"}], "wait_ms": 30}},
        {"kind": "get", "args": {"node": ".", "property": "jumps"}},
        {"kind": "tree", "args": {"depth": 3}},
        {"kind": "monitors", "args": {"seconds": 1}},
        {"kind": "push_error", "text": "LOKI selftest error"},
        {"kind": "errors", "args": {}},
        {"kind": "screenshot", "args": {}}]}
    try:
        linked = wait_for(lambda: [e for e in hub.connected() if e["project"] == str(RP.resolve())], 40, 0.2)
        check("the plugin loads in a real Godot editor and its bridge connects to Studio", bool(linked),
              (TMP / "godot-editor.log").read_text()[-1500:])
        if linked:
            rp = str(RP)
            st = hub.call("editor_state", {}, project=rp, timeout=15)
            check("editor_state from the real editor (project, Godot 4.x, main scene)", st["ok"] and st["result"]["project_name"] == "Real Probe"
                  and st["result"]["godot"].startswith("4.") and st["result"]["main_scene"] == "res://main.tscn", st)
            op = hub.call("open_scene", {"path": "res://main.tscn"}, project=rp, timeout=15)
            tree = hub.call("scene_tree", {}, project=rp, timeout=15)
            check("open_scene + scene_tree: the real scene's nodes", op["ok"] and tree["ok"] and tree["result"]["nodes"][0]["type"] == "Node2D"
                  and tree["result"]["nodes"][0].get("script") == "res://main.gd", (op, tree))
            add = hub.call("add_node", {"parent": ".", "type": "Sprite2D", "name": "Hero", "turn": 7}, project=rp, timeout=15)
            setp = hub.call("set_property", {"node": "Hero", "property": "position", "value": "Vector2(10, 20)", "turn": 7}, project=rp, timeout=15)
            info = hub.call("node_info", {"node": "Hero"}, project=rp, timeout=15)
            pos = next((p["value"] for p in (info.get("result") or {}).get("properties", []) if p["name"] == "position"), "")
            check("add_node + set_property through the editor's UndoRedo (real nodes, real values)", add["ok"] and setp["ok"]
                  and pos == "Vector2(10, 20)", (add, setp, pos))
            bad = hub.call("add_node", {"parent": ".", "type": "NotAClass"}, project=rp, timeout=15)
            check("a wrong class is a clear error, nothing added", not bad["ok"] and "not a node class" in bad["error"], bad)
            sig = hub.call("connect_signal", {"from": "Hero", "signal": "visibility_changed", "to": ".", "method": "_on_hero_visible", "turn": 7},
                           project=rp, timeout=15)
            check("connect_signal (persistent, undoable) - and it notes the missing method", sig["ok"] and "has no method" in str(sig["result"]), sig)
            att = hub.call("attach_script", {"node": "Hero", "script": "res://broken.gd", "turn": 7}, project=rp, timeout=15)
            errs = wait_for(lambda: [e for e in hub.errors(project=rp) if "broken.gd" in json.dumps(e)], 10, 0.2)
            check("the editor's real errors reach Studio (a script that does not parse)", bool(errs) and not att["ok"], (att, hub.errors(project=rp)[-3:]))
            und = hub.call("undo_turn", {"turn": 7}, project=rp, timeout=15)
            tree2 = hub.call("scene_tree", {}, project=rp, timeout=15)
            check("undo_turn: the editor's own UndoRedo takes the turn back (Hero gone)", und["ok"] and und["result"]["undone"] == 3
                  and not any(n["path"] == "Hero" for n in tree2["result"]["nodes"]), (und, tree2))
            shot = hub.call("screenshot", {"target": "editor"}, project=rp, timeout=15)
            check("a screenshot in a headless editor says plainly there is no picture", not shot["ok"] and "headless" in shot["error"], shot)
            hub.call("quit", {}, project=rp, timeout=10)
    finally:
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
    (TMP / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    try:
        subprocess.run([GODOT, "--headless", "--path", str(RP), "--", "--loki-selftest=" + str(TMP / "spec.json")], capture_output=True, timeout=25)
    except subprocess.TimeoutExpired:
        pass
    got = json.loads((TMP / "selftest.json").read_text()) if (TMP / "selftest.json").is_file() else {"results": []}
    rs = got["results"]
    check("the game bridge runs in a real game", len(rs) == len(spec["steps"]), got)
    if len(rs) == len(spec["steps"]):
        check("injected input reaches the game's own polling (jumps 0 -> 2, held >= 2 physics frames)",
              rs[0]["result"]["value"] == "0" and rs[2]["result"]["value"] == "2", (rs[0], rs[2]))
        check("an unknown action is reported with the real ones", "no input action missing (actions: jump)" in rs[1]["result"]["sent"], rs[1])
        check("the live game tree", any(n["path"] == "/root/Main" and n.get("script") == "res://main.gd" for n in rs[3]["result"]["nodes"]))
        mon = rs[4]["result"]
        check("performance monitors sampled over real frames", mon["frames"] > 10 and mon["fps"] > 0 and "process_ms_max" in mon
              and any(p[0] == "res://main.gd" for p in mon["processing"]), mon)
        check("the game's errors are caught (Logger) with file and backtrace", got.get("logger") and any(
            e["text"] == "LOKI selftest error" and e["source"] == "game" for e in rs[6]["result"]), rs[6])
        check("a headless game has no picture, and says so", not rs[7]["ok"] and "headless" in rs[7]["error"], rs[7])

# ================================================================= 10. the window
section("10. Studio's window: modes, the Godot target, todos, questions, diagrams (headless Chromium)")
try:
    from playwright.async_api import async_playwright  # type: ignore
except ImportError:
    async_playwright = None
chromium = next((p for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if p and os.path.exists(p)), "")
if async_playwright is None:
    print("  SKIP Playwright is not installed here")
else:
    chat.queue = [tool("todo_write", items=[{"text": "read the scene", "status": "done"}, {"text": "add a coin", "status": "doing"}]),
                  tool("ask_owner", question="Gold or silver coins?", options=["gold", "silver"])]
    studio.send(g2.id, "/model auto")
    studio.send(g2.id, "plan the coins")
    wait_for(lambda: [e for e in g2.events if e["type"] == "question"], 15)

    async def look():
        async with async_playwright() as pw:
            launch = {"headless": True}
            exe = next((str(p) for p in Path(chromium).glob("chrome-linux*/chrome")), "") if chromium and Path(chromium).is_dir() else ""
            if exe:
                launch["executable_path"] = exe
            browser = await pw.chromium.launch(**launch)
            page = await browser.new_page(viewport={"width": 1360, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(srv.url + "&session=" + g2.id)
            await page.wait_for_selector(".mermaid svg rect", timeout=15000)
            await page.wait_for_selector(".ev.question button", timeout=15000)
            await page.wait_for_timeout(500)
            got = await page.evaluate("""() => ({rects: document.querySelectorAll('.mermaid svg rect').length,
                modes: [...document.querySelectorAll('#modes button')].map(b => b.textContent),
                targets: [...document.querySelectorAll('#target option')].map(o => o.textContent),
                todos: document.getElementById('todos').hidden ? '' : document.getElementById('todos').textContent,
                question: document.querySelector('.ev.question') && document.querySelector('.ev.question').textContent,
                undo: !document.getElementById('act-undo').disabled, ship: document.getElementById('act-ship').hidden})""")
            await page.fill("#prompt", "/pl")
            await page.dispatch_event("#prompt", "input")
            await page.wait_for_timeout(400)
            sugg = await page.evaluate("() => [...document.querySelectorAll('#suggest li')].map(li => li.textContent)")
            await page.click(".ev.question button")
            await page.wait_for_timeout(300)
            shots = os.getenv("LOKI_SUITE_SCREENS", "")
            await page.screenshot(path=str(Path(shots) / "studio-godot.png" if shots else TMP / "studio-godot.png"))
            await browser.close()
            return got, sugg, errors
    try:
        got, sugg, errors = asyncio.run(look())
        check("the window draws the /graph mermaid diagram itself (boxes, no CDN)", got["rects"] >= 2, got)
        check("Default / Plan / Ask, and the linked Godot project as a target", got["modes"] == ["Default", "Plan", "Ask"]
              and any("Godot: Pebble" in t for t in got["targets"]), got)
        check("the todo list and the agent's question with its choices", "add a coin" in got["todos"] and "Gold or silver" in (got["question"] or ""), got)
        check("a Godot session: Ship hidden (nothing to ship); Undo waits while the agent works", got["ship"] and not got["undo"], got)
        check("typing / suggests the commands", any(s.startswith("/plan") for s in sugg) and any(s.startswith("/playtest") for s in sugg), sugg)
        answered = wait_for(lambda: any(e["type"] == "answered" for e in g2.events), 10)
        check("clicking a choice answers the agent", answered and any(e["type"] == "answered" and e["text"] == "gold" for e in g2.events))
        check("no errors in the page", not errors, errors)
    except Exception as exc:  # noqa: BLE001
        check("the window opens in headless Chromium", False, "%s: %s" % (type(exc).__name__, exc))
    studio.stop(g2.id)
    studio.wait(g2.id, 10)

ed.stop = True
srv.stop()
check("Studio removes its connect file when it stops", not (TMP / "connect.json").exists())
print("\n%d passed, %d failed  (%.1fs)" % (len(PASS), len(FAIL), time.time() - T0))
if FAIL:
    print("FAILED: " + "; ".join(FAIL))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if FAIL else 0)
