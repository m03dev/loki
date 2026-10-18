"""The live Godot link (engine/godot_live.py): LOKI's agents work inside the REAL Godot editor on LOKI World.

    python tests/test_godot_live.py      (< 60 s; the real-editor half needs a Godot 4 binary: LOKI_SUITE_GODOT or GODOT_BIN)

Without Godot: an agent's editor work puts it at the Godot forge in LOKI World with what it does; Plan mode only reads;
Asset Library plugins install only their addons/ folder, are recorded in plugins.json and re-install from it; the engine
answers the plugin's routes. With Godot: a copy of LOKI World opens in a headless Godot editor with the LOKI Studio
plugin, the plugin links to the engine's hub by itself (~/.loki/engine_connect.json), and godot_editor calls read the
live editor, add a node to the open main scene, set its property and save - the .tscn on disk has it, undoable.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "studio"))
TMP = Path(tempfile.mkdtemp(prefix="loki-glive-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_ENGINE_CONNECT"] = str(TMP / "engine_connect.json")
os.environ["LOKI_STUDIO_CONNECT"] = str(TMP / "studio_connect.json")   # a stand-in LOKI Studio (below)
import godot_live  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


# ------------------------------------------------------------------ agents roam: editor work -> the Godot forge
godot_live.note_activity("job-abc", "set_property", {"node": "Player", "property": "speed", "value": "6"}, now=1000.0)
world = godot_live.apply_to_world([{"id": "loki", "station": "hall", "state": "idle"},
                                   {"id": "job-abc", "station": "workshop", "state": "working"}], now=1010.0)
check("an agent working in the editor stands at the Godot forge", world[1]["station"] == "godot forge"
      and world[1]["last_message"] == "Godot: set property Player.speed = 6", world[1])
check("...the others stay where they are", world[0]["station"] == "hall")
later = godot_live.apply_to_world([{"id": "job-abc", "station": "workshop"}], now=1000.0 + godot_live.ACTIVE_S + 1)
check("...and goes back when it stops", later[0]["station"] == "workshop")
import events  # noqa: E402
check("the forge is a world station", events.STATIONS.get("Godot") == "godot forge")
builder = (REPO / "game" / "loki-world" / "scripts" / "world" / "island_builder.gd").read_text(encoding="utf-8")
check("LOKI World has the Godot forge station", '"godot forge"' in builder)

# ------------------------------------------------------------------ Plan mode only reads
import loki  # noqa: E402
loki.AGENT_MODE = "plan"
check("Plan mode cannot change the project", godot_live.godot_editor("add_node", {"type": "Node3D"}).startswith("refused"))
check("...but can look", not godot_live.godot_editor("scene_tree", {}).startswith("refused"))
loki.AGENT_MODE = "build"
check("every agent has the godot_editor tool", "godot_editor" in loki.LOCAL_TOOLS
      and any(t["function"]["name"] == "godot_editor" for t in loki.model_tool_schemas()))
check("an unknown action says which exist", "unknown editor action" in godot_live.godot_editor("format_disk"))

# ------------------------------------------------------------------ plugins from the Asset Library
proj = TMP / "proj"
proj.mkdir()
(proj / "project.godot").write_text("config_version=5\n", encoding="utf-8")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("dialogue-abc123/README.md", "readme")
    z.writestr("dialogue-abc123/addons/dialogue_manager/plugin.cfg", "[plugin]\nname=\"Dialogue\"\nscript=\"p.gd\"\n")
    z.writestr("dialogue-abc123/addons/dialogue_manager/p.gd", "@tool\nextends EditorPlugin\n")
    z.writestr("dialogue-abc123/addons/loki_studio/evil.gd", "x")          # never replaces LOKI's own plugin
    z.writestr("dialogue-abc123/addons/../../escape.txt", "x")
    z.writestr("dialogue-abc123/project.godot", "should not be copied")
ZIP = buf.getvalue()
INFO = {"asset_id": "1207", "title": "Dialogue Manager", "version_string": "3.4", "download_commit": "abc123",
        "download_url": "https://codeload.github.com/x/y/zip/abc123", "cost": "MIT"}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(req, timeout=0):
    return Resp(json.dumps(INFO).encode() if "asset-library" in req.full_url else ZIP)


res = godot_live.install_plugin(proj, "1207", opener)
check("a plugin installs from the Asset Library", res["ok"] and (proj / "addons" / "dialogue_manager" / "plugin.cfg").is_file(), res)
check("only its addons/ folder is copied (not its project.godot, not outside)", not (proj / "README.md").exists()
      and (proj / "project.godot").read_text() == "config_version=5\n" and not (TMP / "escape.txt").exists())
check("it can never replace LOKI's own plugin", not (proj / "addons" / "loki_studio").exists())
man = godot_live.read_manifest(proj)
check("recorded in plugins.json at its exact commit", man and man[0]["commit"] == "abc123" and man[0]["addons"] == ["dialogue_manager"], man)
shutil.rmtree(proj / "addons")
again = godot_live.sync_plugins(proj, opener)
check("another machine installs the same plugins from plugins.json", again["ok"] and again["installed"] == ["Dialogue Manager"]
      and (proj / "addons" / "dialogue_manager" / "p.gd").is_file(), again)
try:
    godot_live.install_asset(proj, dict(INFO, download_hash="0" * 64), opener)
    check("a download that does not match the Asset Library's hash is refused", False)
except ValueError as exc:
    check("a download that does not match the Asset Library's hash is refused", "hash" in str(exc))

# ------------------------------------------------------------------ Open in Godot: LOKI World with LOKI's own Godot 4.7.2
import godot_web  # noqa: E402
import world_build  # noqa: E402
opened, got = [], []
_real_bin, _real_install = world_build.editor_binary, world_build.install
fake_exe = TMP / "Godot"
world_build.editor_binary = lambda data=None: fake_exe if got else None
world_build.install = lambda data=None, opener=None, say=None: (got.append(1), {"ok": True})[1]
godot_live.ensure_world = lambda *a, **k: {"ok": True, "note": "ready"}
r1 = godot_web.open_native("loki-world", popen=lambda argv, **kw: opened.append(argv), background=False)
check("the first Open gets LOKI's Godot 4.7.2 (never the window waiting on a download)", r1.get("downloading") and got == [1], r1)
check("...then opens LOKI World in it, as an editor", opened and opened[-1][0] == str(fake_exe) and "--editor" in opened[-1]
      and opened[-1][-1].endswith("loki-world"), opened)
r2 = godot_web.open_native("loki-world", popen=lambda argv, **kw: opened.append(argv))
check("after that it opens at once with it", r2.get("ok") and not r2.get("downloading") and "4.7.2" in r2["note"], r2)
os.environ["LOKI_GODOT_EDITOR"] = "system"
check("LOKI_GODOT_EDITOR=system uses the computer's own Godot", godot_web.loki_godot() == "")
os.environ.pop("LOKI_GODOT_EDITOR")
world_build.editor_binary, world_build.install = _real_bin, _real_install
import importlib  # noqa: E402
godot_live = importlib.reload(godot_live)

# ------------------------------------------------------------------ the engine's hub over HTTP (as loki_bridge serves it)
TOKEN = "engine-token"


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _go(self, method):
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            body = b'{"ok": false}'
            self.send_response(401)
        else:
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}") if n else {}
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            code, payload = godot_live.route(method, u.path, data, q) or (404, {"ok": False})
            body = json.dumps(payload).encode()
            self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self._go("GET")

    def do_POST(self):  # noqa: N802
        self._go("POST")


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]

# LOKI Studio's own hub (its app), on another port with another token: the plugin links to it AND to the engine
import studio_godot  # noqa: E402
STUDIO_HUB = studio_godot.GodotHub()
STUDIO_TOKEN = "studio-token"


class SH(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _go(self, method):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        data = json.loads(self.rfile.read(n) or b"{}") if n else {}
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        code, payload = 401, {"ok": False}
        if self.headers.get("Authorization") == "Bearer " + STUDIO_TOKEN:
            code = 200
            if u.path == "/api/godot/hello":
                payload = {"ok": True, **STUDIO_HUB.hello(data)}
            elif u.path == "/api/godot/poll":
                payload = {"ok": True, "commands": STUDIO_HUB.poll(q.get("editor"), float(q.get("wait") or 20))}
            elif u.path == "/api/godot/result":
                STUDIO_HUB.result(data.get("editor"), data)
                payload = {"ok": True}
            elif u.path == "/api/godot/event":
                STUDIO_HUB.event(data.get("editor"), str(data.get("kind") or ""), data.get("data"))
                payload = {"ok": True}
            else:
                payload = {"ok": True}      # the dock's own calls (/api/state, ...)
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self._go("GET")

    def do_POST(self):  # noqa: N802
        self._go("POST")


ssrv = ThreadingHTTPServer(("127.0.0.1", 0), SH)
ssrv.daemon_threads = True
threading.Thread(target=ssrv.serve_forever, daemon=True).start()
studio_godot.write_connect(Path(os.environ["LOKI_STUDIO_CONNECT"]), "http://127.0.0.1:%d" % ssrv.server_address[1], STUDIO_TOKEN)
path = godot_live.write_connect(PORT, TOKEN)
conn = json.loads(Path(path).read_text(encoding="utf-8"))
check("the engine tells the editor where it is (url + token)", conn["url"] == "http://127.0.0.1:%d" % PORT and conn["token"] == TOKEN)
check("...in a file only this user can read", os.name == "nt" or (Path(path).stat().st_mode & 0o077) == 0)
check("no editor yet: a plain answer that says how to open LOKI World", "Open LOKI World" in json.dumps(
    godot_live.call("editor_state", {})))

# ------------------------------------------------------------------ REAL Godot: the editor links to the engine
GODOT = next((g for g in (os.getenv("LOKI_SUITE_GODOT", ""), os.getenv("GODOT_BIN", ""), shutil.which("godot") or "")
              if g and Path(g).is_file()), "")
if not GODOT:
    print("  SKIP no Godot 4 binary (set LOKI_SUITE_GODOT) - the live-editor half runs on the Mac/PC")
else:
    import install_godot_plugin  # noqa: E402
    world = TMP / "loki-world"
    shutil.copytree(REPO / "game" / "loki-world", world, ignore=shutil.ignore_patterns(".godot", "addons"))
    install_godot_plugin.install(world)
    log = open(TMP / "editor.log", "w")
    env = dict(os.environ, LOKI_STUDIO_TEST="1")
    proc = subprocess.Popen([GODOT, "--headless", "--editor", "--path", str(world)], stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        t0 = time.time()
        while time.time() - t0 < 30 and not godot_live.hub().connected():
            time.sleep(0.3)
        eds = godot_live.hub().connected()
        check("the real Godot editor links to LOKI's engine by itself", bool(eds) and eds[0]["project"] == str(world.resolve()),
              (eds, (TMP / "editor.log").read_text()[-1500:]))
        t1 = time.time()
        while time.time() - t1 < 10 and not STUDIO_HUB.connected():
            time.sleep(0.3)
        check("...and to LOKI Studio at the same time (two links, one editor)", bool(STUDIO_HUB.connected()))
        if STUDIO_HUB.connected():
            sres = STUDIO_HUB.call("editor_state", {}, timeout=15)
            check("Studio's link still answers on its own", sres.get("ok") and sres["result"]["project_name"] == "LOKI World", sres)
        if eds:
            os.environ.pop("LOKI_JOB_ID", None)
            st = godot_live.call("editor_state", {}, who="job-live")
            check("an agent reads the live editor (LOKI World, Godot 4)", st.get("ok") and st["result"]["project_name"] == "LOKI World", st)
            op = godot_live.call("open_scene", {"path": "res://scenes/main.tscn"}, who="job-live")
            check("it opens LOKI World's main scene", op.get("ok"), op)
            time.sleep(0.5)
            full = godot_live.call("scene_tree", {"depth": 6}, who="job-live")
            paths = [n.get("path", "") for n in (full.get("result") or {}).get("nodes", [])]
            check("the editor shows LOKI World itself: the World and its home island, not an empty scene",
                  any(p.endswith("World/HomeIsland") for p in paths) and any(p.endswith("World") for p in paths), paths[:15])
            time.sleep(0.5)
            add = godot_live.call("add_node", {"parent": ".", "type": "Node3D", "name": "AgentBeacon",
                                               "properties": {"position": "Vector3(3, 1, -2)"}}, who="job-live")
            check("it adds a node to the live scene", add.get("ok"), add)
            sp = godot_live.call("set_property", {"node": "AgentBeacon", "property": "visible", "value": "false"}, who="job-live")
            check("it changes a property", sp.get("ok"), sp)
            tree = godot_live.call("scene_tree", {}, who="job-live")
            names = [n.get("path") for n in (tree.get("result") or {}).get("nodes", [])]
            check("the live tree has the new node", "AgentBeacon" in names, names[:20])
            sv = godot_live.call("save_scene", {}, who="job-live")
            tscn = (world / "scenes" / "main.tscn").read_text(encoding="utf-8")
            check("saved: the .tscn on disk has it, with the property", sv.get("ok") and 'name="AgentBeacon"' in tscn
                  and "visible = false" in tscn, (sv, tscn[-400:]))
            w2 = godot_live.apply_to_world([{"id": "job-live", "station": "workshop"}])
            check("meanwhile LOKI World shows that agent at the Godot forge, saying what it did",
                  w2[0]["station"] == "godot forge" and "save scene" in w2[0]["last_message"], w2)
            meta = world / ".godot" / "editor" / "project_metadata.cfg"
            md = meta.read_text(encoding="utf-8") if meta.is_file() else ""
            check("live sync is on (edits reach the running game)", "run_live_debug=true" in md and "run_reload_scripts=true" in md, md[:300])
    finally:
        proc.kill()
        proc.wait(timeout=10)
        log.close()
srv.shutdown()
ssrv.shutdown()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
