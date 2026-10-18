"""LOKI World as a Godot 4 MMO (game/loki-world) - offline checks, plus Godot's own headless
tests and an end-to-end run against the real bridge when a Godot 4 binary is available
(LOKI_SUITE_GODOT=<path>, or `godot` / `godot4` on PATH; skipped otherwise).

    python tests/test_godot_world.py

What it holds the project to: the files and systems are there and parse-sane; Godot files live
only in game/loki-world (AGENTS.md); the net layer only calls routes the bridge really has and
uses the same words/tables as the engine (docs/MMO_API.md, engine/mmo_state.py); no CDN; the web
build page needs no inline script and gets 'wasm-unsafe-eval' only for itself; licence notes.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GAME = REPO / "game" / "loki-world"
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:300]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------
section("the project is there")
REQUIRED = [
    "project.godot", "export_presets.cfg", "icon.svg", "LICENSES.md", ".gitignore", "scenes/main.tscn",
    "autoload/loki_api.gd", "autoload/game_state.gd", "scripts/main.gd",
    "scripts/world/world.gd", "scripts/world/island_builder.gd", "scripts/world/mesh_merger.gd", "scripts/world/mats.gd",
    "scripts/actors/actor.gd", "scripts/actors/player.gd", "scripts/actors/npc_agent.gd", "scripts/actors/monster.gd",
    "scripts/actors/remote_player.gd", "scripts/actors/critter.gd", "scripts/actors/character_model.gd",
    "scripts/hud/hud.gd", "scripts/hud/overlay.gd", "scripts/hud/unit_frames.gd", "scripts/hud/hotbar.gd",
    "scripts/hud/minimap.gd", "scripts/hud/chat_box.gd", "scripts/hud/quest_tracker.gd", "scripts/hud/windows.gd",
    "scripts/hud/ui_kit.gd", "scripts/net/derive.gd", "scripts/net/fake_world.gd",
    "shaders/toon.gdshader", "shaders/outline.gdshader", "shaders/ink.gdshader", "shaders/pixel_post.gdshader",
    "shaders/sky.gdshader", "shaders/glow.gdshader", "shaders/water.gdshader",
    "web/shell.html", "tests/run_tests.gd", "tests/run_tests.tscn",
]
missing = [f for f in REQUIRED if not (GAME / f).is_file()]
check("every required scene, script, shader and file exists", not missing, missing)

proj = read(GAME / "project.godot")
check("project.godot: Godot 4 format, main scene, both autoloads", "config_version=5" in proj
      and 'run/main_scene="res://scenes/main.tscn"' in proj and 'LokiApi="*res://autoload/loki_api.gd"' in proj
      and 'GameState="*res://autoload/game_state.gd"' in proj)
check("project.godot: GL Compatibility everywhere (the web build looks like the desktop one)",
      'renderer/rendering_method="gl_compatibility"' in proj and '"GL Compatibility"' in proj)
check("project.godot: nearest texture filter (sharp pixels)", "textures/canvas_textures/default_texture_filter=0" in proj)
sections = re.findall(r"^\[([a-z_/]+)\]$", proj, re.M)
check("project.godot sections are well formed", sections and all(s in ("application", "autoload", "display", "gui", "physics", "rendering",
                                                                       "input", "shader_globals", "editor_plugins") for s in sections), sections)
for line in proj.splitlines():
    if line and not line.startswith((";", "[")) and "=" not in line:
        check("project.godot line is key=value: %r" % line, False)

# ------------------------------------------------------------------------------------------
section("scenes, scripts and shaders parse-sane")
for tscn in sorted(GAME.rglob("*.tscn")):
    text = read(tscn)
    paths = re.findall(r'path="res://([^"]+)"', text)
    # format=3, or 4 (Godot 4.6+ writes unique_id; scenes/home_island.tscn is saved by Godot 4.7)
    ok = text.startswith("[gd_scene") and re.search(r"format=[34]\b", text.splitlines()[0]) and all((GAME / p).is_file() for p in paths)
    ids = re.findall(r'id="([^"]+)"', text)
    refs = re.findall(r'ExtResource\("([^"]+)"\)', text)
    check("%s: header, resources exist, references resolve" % tscn.relative_to(GAME), ok and all(r in ids for r in refs), paths)

gd_files = sorted(p for p in GAME.rglob("*.gd") if ".godot" not in p.parts
                  and "addons/loki_studio" not in p.as_posix())   # LOKI installs this copy; the original is checked in studio/
bad_indent, bad_head, bad_brackets = [], [], []
for gd in gd_files:
    text = read(gd)
    lines = text.splitlines()
    if not lines or not re.match(r"^(extends|class_name) ", lines[0]):
        bad_head.append(gd.name)
    for i, line in enumerate(lines, 1):
        lead = line[: len(line) - len(line.lstrip())]
        if " " in lead and line.strip() and not line.strip().startswith("#"):
            bad_indent.append("%s:%d" % (gd.name, i))
    code = re.sub(r"#.*", "", re.sub(r'"(?:\\.|[^"\\])*"', '""', text))   # strings first, then comments
    for a, b in ("()", "[]", "{}"):
        if code.count(a) != code.count(b):
            bad_brackets.append("%s %s%s" % (gd.name, a, b))
check("every script starts with extends/class_name", not bad_head, bad_head)
check("scripts indent with tabs only (GDScript style, no mixed indentation)", not bad_indent, bad_indent[:5])
check("brackets balance in every script", not bad_brackets, bad_brackets)
check("typed GDScript 4 (no Godot 3 'onready var'/'yield'/'export var')", not [g.name for g in gd_files
      if re.search(r"^\s*(onready var|export var)|\byield\(", read(g), re.M)])
for sh in sorted(GAME.rglob("*.gdshader")):
    text = read(sh)
    check("%s: shader_type and balanced braces" % sh.name, re.search(r"^shader_type (spatial|canvas_item|sky);", text, re.M) is not None
          and text.count("{") == text.count("}"))

# ------------------------------------------------------------------------------------------
section("the systems the owner asked for")
src = {p.relative_to(GAME).as_posix(): read(p) for p in gd_files}
allsrc = "\n".join(src.values())
shaders = {p.name: read(p) for p in GAME.rglob("*.gdshader")}
for name, needles in {
    "WASD + mouse orbit camera, jump, click-to-target, Tab": [("player.gd", "move_forward"), ("player.gd", "cam_yaw"), ("player.gd", "JUMP_SPEED"),
                                                              ("player.gd", "func pick("), ("player.gd", "func target_next(")],
    "an island per device, bridges of light, fly between": [("world.gd", "func _build_bridge("), ("world.gd", "func fly_to("),
                                                             ("world.gd", "zone_point"), ("world.gd", "you are here")],
    "cel shading (bands), ink outlines, pixelated + posterize/dither": [("toon.gdshader", "bands"), ("outline.gdshader", "cull_front"),
                                                                        ("pixel_post.gdshader", "BAYER"), ("main.gd", "stretch_shrink"),
                                                                        ("main.gd", "TEXTURE_FILTER_NEAREST")],
    "fox, rabbits, crystals, waterfall, day/night": [("character_model.gd", "static func fox("), ("character_model.gd", "static func rabbit("),
                                                     ("island_builder.gd", "static func crystals("), ("home_builder.gd", "water(true)"),
                                                     ("world.gd", "func _day_night(")],
    "HUD: nameplates, target/party frames, minimap, chat, hotbar, cast bar, XP, damage numbers": [
        ("overlay.gd", "func _plate("), ("unit_frames.gd", "Party"), ("minimap.gd", "func _draw_big("), ("chat_box.gd", "chat_with_loki"),
        ("hotbar.gd", "cooldown_left"), ("hotbar.gd", "cast bar"), ("hotbar.gd", "XP bar"), ("overlay.gd", "add_float")],
    "quest log/tracker, bags, character sheet, loot window, emotes, level-ups": [
        ("windows.gd", "func show_quests("), ("quest_tracker.gd", "Quests"), ("windows.gd", "func show_bags("),
        ("windows.gd", "func show_character("), ("windows.gd", "func show_loot("), ("game_state.gd", "EMOTES"),
        ("world.gd", "func level_up_effect(")],
    "agents as NPCs, jobs as quests, failures as monsters, retry, creations as loot": [
        ("npc_agent.gd", "quest_giver"), ("loki_api.gd", "func turn_in("), ("monster.gd", "aggro"),
        ("loki_api.gd", "func retry_failed("), ("world.gd", "func _sync_paintings("), ("loki_api.gd", "func creation_texture(")],
    "other real players from presence, interpolated": [("remote_player.gd", "DELAY_MS"), ("loki_api.gd", "func presence_tick("),
                                                       ("player.gd", "func presence(")],
    "offline mode with fake data": [("loki_api.gd", "func go_offline("), ("fake_world.gd", "\"demo\": true")],
}.items():
    found = []
    for fname, needle in needles:
        body = next((t for k, t in list(src.items()) + list(shaders.items()) if k.split("/")[-1] == fname), "")
        found.append(needle in body)
    check(name, all(found), [n for (n, ok) in zip(needles, found) if not ok])

# ------------------------------------------------------------------------------------------
section("the net layer talks to the routes the bridge really has (docs/MMO_API.md)")
api = src["autoload/loki_api.gd"]
bridge = read(REPO / "engine" / "loki_bridge.py")
mmo_py = read(REPO / "engine" / "mmo_state.py") if (REPO / "engine" / "mmo_state.py").is_file() else ""
ep = dict(re.findall(r'"(\w+)": "(/[^"]*)"', api.split("const EP := {", 1)[1].split("}", 1)[0]))
check("the endpoint table is complete", {"health", "world", "jobs", "creations", "make", "chat", "mmo_state", "mmo_skill",
                                          "mmo_turnin", "mmo_defeat", "mmo_retry", "mmo_note", "mmo_profile", "presence", "retry"} <= set(ep), sorted(ep))
plain = {k: v for k, v in ep.items() if not k.startswith("mmo_") and k != "creation_file"}
missing_routes = [v for v in plain.values() if ('"%s"' % v) not in bridge
                  and not (v.startswith("/forge/") and 'route.startswith("/forge/")' in bridge)]   # Forge: one prefix
check("every plain endpoint is a bridge route", not missing_routes, missing_routes)
check("/creations/<kind>/<file> is served by the bridge", 'route.startswith("/creations/")' in bridge and ep.get("creation_file") == "/creations/")
mmo_paths = [v for k, v in ep.items() if k.startswith("mmo_")]
check("every /mmo/* hook is handled by the engine's MMO API (mmo_state.route)", mmo_py != "" and
      all(('"%s"' % p) in mmo_py for p in mmo_paths) and bridge.count('route.startswith("/mmo/")') >= 2, mmo_paths)
check("presence is POST /world/presence with player + after (+ chat)", '"player": player, "after": presence_cursor' in api
      and 'body["chat"] = line' in api)
check("polls /mmo/state every 3 s, presence 150 ms moving / 1 s idle", "STATE_EVERY := 3.0" in api and "0.15 if moving else 1.0" in api)
check("bearer token on every call; POST bodies are JSON objects, never empty", '"Authorization: Bearer " + token' in api
      and "JSON.stringify(body if body != null else {})" in api)
check("ports 8767 (the app) then 8766 (a CLI engine)", "const PORTS := [8767, 8766]" in api)
check("web build: token from the page fragment like app/ui (#token=), never logged", "(?:^|[#&])token=([^&]+)" in api
      and "print(" not in api)
check("desktop: token from LOKI's state folder (app/loki_app.py TOKEN_FILE = <data>/app/engine.token)",
      'path_join("app").path_join("engine.token")' in api and "harness_data/app/engine.token" in api
      and 'TOKEN_FILE = STATE / "engine.token"' in read(REPO / "app" / "loki_app.py"))
check("a 401 re-reads the token (it changes every time LOKI starts)", api.count("read_token()") >= 3)
check("no /mmo/* -> the game derives the state from /world + /jobs + /creations", "has_mmo = false" in api
      and "Derive.state(last_world, last_jobs, last_creations" in api)
if mmo_py:
    import mmo_state  # noqa: E402
    prompts = dict(re.findall(r'"(\w+)": "(.*)",\n', api.split("const ACTION_PROMPTS := {", 1)[1].split("}", 1)[0]))
    same = all(prompts[k].replace('\\"', '"') % "a fox" == mmo_state.action_prompt(k, "a fox") for k in ("image", "video", "game", "research", "build"))
    check("LOKI-action prompts are the engine's words (Settings > Creations)", same, prompts)
    gs = src["autoload/game_state.gd"]
    skills_gd = re.findall(r'\{"slot": (\d), "id": "(\w+)", "name": "([^"]+)", "kind": "(\w+)", "cd_s": ([\d.]+)', gs)
    skills_py = [(str(s["slot"]), s["id"], s["name"], s["kind"], s["cd_s"]) for s in mmo_state.SKILLS]
    check("the hotbar is the engine's (slots, ids, names, kinds, cooldowns)", [(a, b, c, d, float(e)) for a, b, c, d, e in skills_gd]
          == [(a, b, c, d, float(e)) for a, b, c, d, e in skills_py], skills_gd)
    check("player classes match the engine", set(re.findall(r'^\t"(\w+)": \{"color"', gs, re.M)) == set(mmo_state.CLASSES))
    check("NPC classes match the engine", [r[1] for r in mmo_state.NPC_CLASSES] == re.findall(r'\["[^"]+", "(\w+)", "#', gs.split("NPC_CLASSES", 1)[1].split("]\n]", 1)[0] + "]"))
    check("monster names match the engine", [m[1] for m in mmo_state.MONSTERS] == re.findall(r'\["[^"]+", "([A-Z][\w -]+)", "\w+"\]', gs))
    check("the XP curve is the engine's round(80 * L^1.55)", "80.0 * pow(float(level), 1.55)" in gs and mmo_state.xp_to_next(7) == round(80 * 7 ** 1.55))

# ------------------------------------------------------------------------------------------
section("only here, no CDN, licence notes")
tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split()
godot_outside = [f for f in tracked if f.endswith((".gd", ".tscn", ".tres", ".gdshader", ".uid", ".import")) or f.endswith("project.godot")]
godot_outside = [f for f in godot_outside if not f.startswith("game/loki-world/")
                 and not (f.startswith("studio/godot_plugin/addons/loki_studio/") and f.endswith(".gd"))]
check("no Godot project files tracked outside game/loki-world and the Studio plugin (AGENTS.md)", not godot_outside, godot_outside[:5])
stray = [str(p.relative_to(REPO)) for p in REPO.rglob("project.godot") if "harness_data" not in p.parts and GAME not in p.parents
         and p.parent != GAME and ".git" not in p.parts and ".claude" not in p.parts]
check("no other project.godot in the checkout", not stray, stray)
game_text = "\n".join(read(p) for p in GAME.rglob("*") if p.is_file() and p.suffix in (".gd", ".gdshader", ".tscn", ".godot", ".cfg", ".html"))
urls = [u for u in re.findall(r"https?://[^\s\"'<>)]+", game_text) if not re.match(r"https?://(127\.0\.0\.1|localhost)", u)]
check("no CDN or outside URL in the game (it only talks to LOKI on loopback)", not urls, urls[:5])
wg = UI / "world_godot"
# LOKI's own shell only: the generated Godot build (index.js/.wasm/.pck, the worklets) is never
# scanned - Godot's own index.js carries an MDN link in a comment, and it is not LOKI's page.
host_shell = [wg / n for n in ("index.html", "boot.js", "host.js", "style.css") if (wg / n).is_file()]
web_text = "\n".join(read(p) for p in host_shell)
check("LOKI's own world shell loads nothing from outside (no CDN)", not re.search(r"https?://", web_text))
lic = read(GAME / "LICENSES.md")
check("licence notes: no third-party assets, CC0/MIT only, Godot's MIT notice", "Third-party assets: none" in lic
      and "CC0 or MIT" in lic and "MIT" in lic and "Godot" in lic)
check(".godot/ (the editor cache) is never committed", ".godot/" in read(GAME / ".gitignore") and not [f for f in tracked if "/.godot/" in f])
check("the repo .gitignore lets this project.godot in", "!game/loki-world/project.godot" in read(REPO / ".gitignore"))

# ------------------------------------------------------------------------------------------
section("export: desktop (Steam) and a single-threaded web build into LOKI's window")
presets = read(GAME / "export_presets.cfg")
web = presets.split('name="Web"', 1)[1].split("[preset.1]", 1)[0] if 'name="Web"' in presets else ""
check("presets: Web, Windows Desktop, macOS, Linux", all('platform="%s"' % p in presets for p in ("Web", "Windows Desktop", "macOS", "Linux")))
check("web: single-threaded (no COOP/COEP, no SharedArrayBuffer)", "variant/thread_support=false" in web
      and "ensure_cross_origin_isolation_headers=false" in web)
check("web: exported into app/ui/world_godot/ with LOKI's CSP-clean shell", 'export_path="../../app/ui/world_godot/index.html"' in web
      and 'html/custom_html_shell="res://web/shell.html"' in web)
check("tests and the shell are not packed into the game", presets.count('exclude_filter="tests/*, web/*"') == 4)
for name, text in (("web/shell.html", read(GAME / "web" / "shell.html")), ("world_godot/index.html", read(wg / "index.html"))):
    scripts = re.findall(r"<script([^>]*)>(.*?)</script>", text, re.S)
    inline = [a for a, body in scripts if "src=" not in a and 'type="application/json"' not in a]
    check("%s: no inline script, config in a JSON data block, no inline style" % name, not inline and 'id="godot-config"' in text
          and "style=" not in text and "<style" not in text)
check("the shell has the exporter's placeholders", all(p in read(GAME / "web" / "shell.html") for p in ("$GODOT_URL", "$GODOT_CONFIG", "$GODOT_HEAD_INCLUDE")))
boot = read(wg / "boot.js")
host = read(wg / "host.js")
check("boot.js: single-threaded check, tells LOKI's window missing/failed/starting/ready", "getMissingFeatures({ threads: false })" in boot
      and all(w in boot for w in ('"missing"', '"failed"', '"starting"', '"ready"')) and "location.origin" in boot)
check("host.js: token in the fragment, same-origin messages only, play/background modes", "#token=" in host
      and "ev.origin !== location.origin" in host and '"play"' in host and '"background"' in host)
if shutil.which("node"):
    for js in (wg / "host.js", wg / "boot.js", UI / "world.js"):
        proc = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        check("%s parses" % js.name, proc.returncode == 0, proc.stderr)

section("the hooks in LOKI (small): world.js engine option, Settings choice, bridge serving")
wjs = read(UI / "world.js")
check("world.js: 'godot' (default) plays the Godot game in the World panel, loaded only when it opens; "
      "the home screen keeps the light Babylon world; no build -> the light world plays",
      'game: "godot"' in wjs and 'World.game = want === "godot" ? "godot" : "";' in wjs
      and "loadGodotWorld().then(" in wjs and "WorldGodot.start(state.token, () => false)" in wjs
      and 'if (!World.godotLive) World.game = "";' in wjs)
check("world.js: the panel and background go to the Godot frame when it runs", "window.WorldGodot.panel(true)" in wjs
      and "window.WorldGodot.panel(false)" in wjs and 'loadScript("/ui/world_godot/host.js")' in wjs)
import portal_api  # noqa: E402
check("Settings > General offers godot", "godot" in portal_api.GENERAL_SETTINGS["LOKI_WORLD_ENGINE"]["choices"]
      if hasattr(portal_api, "GENERAL_SETTINGS") else '"godot"' in read(REPO / "engine" / "portal_api.py"))
import loki_bridge  # noqa: E402
check("the bridge serves .wasm (application/wasm) and .pck", loki_bridge.UI_TYPES.get(".wasm") == "application/wasm"
      and ".pck" in loki_bridge.UI_TYPES)
import godot_web  # noqa: E402
_env = os.environ.get("GODOT_EXE")
os.environ["GODOT_EXE"] = sys.executable       # the app passes --godot-exe -> GODOT_EXE
check("native Godot is found from GODOT_EXE (the app passes the path this way, not GODOT_BIN)",
      godot_web.native_godot() == sys.executable)
if _env is None:
    os.environ.pop("GODOT_EXE", None)
else:
    os.environ["GODOT_EXE"] = _env
check("only the Godot page gets 'wasm-unsafe-eval'; nobody gets 'unsafe-eval'", "'wasm-unsafe-eval'" in loki_bridge.GODOT_WORLD_CSP
      and "wasm-unsafe-eval" not in loki_bridge.UI_CSP and "'unsafe-eval'" not in loki_bridge.GODOT_WORLD_CSP
      and "frame-ancestors 'self'" in loki_bridge.GODOT_WORLD_CSP and "script-src 'self'" in loki_bridge.UI_CSP)

# real HTTP: the page, its CSP, the wasm type; other pages unchanged
TMP = Path(tempfile.mkdtemp(prefix="loki-godot-"))
ui_tmp = TMP / "ui"
(ui_tmp / "world_godot").mkdir(parents=True)
shutil.copy(wg / "index.html", ui_tmp / "world_godot" / "index.html")
(ui_tmp / "world_godot" / "index.wasm").write_bytes(b"\0asm\x01\0\0\0")
(ui_tmp / "world_godot" / "index.pck").write_bytes(b"GDPC")
(ui_tmp / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")


class Store:
    def __init__(self, jobs):
        self.jobs = {j["id"]: j for j in jobs}

    def all(self):
        return list(self.jobs.values())

    def get(self, jid):
        return self.jobs.get(jid)

    def remove_finished(self, keep=0):
        return 0


now = time.time()
JOBS = [
    {"id": "g1", "status": "working", "title": "Make an image of a fox", "prompt": "Make an image of a fox", "agent": "loki",
     "backend": "local", "created": now - 300, "started": now - 290, "finished": 0, "error": ""},
    {"id": "g2", "status": "failed", "title": "Research: tea", "prompt": "Research: tea", "agent": "loki", "backend": "local",
     "created": now - 900, "started": now - 890, "finished": now - 60, "error": "timed out after 1800 s"},
]
made_jobs = []


class Jobs:
    store = Store(JOBS)

    def status(self):
        return {"jobs": list(JOBS), "counts": {}, "backends": {}, "running": True}

    def create(self, spec):
        made_jobs.append(spec)
        return {"id": "new%d" % len(made_jobs)}

    def tick(self):
        pass


class _Model:
    model = "fake-model"
    base_url = "http://127.0.0.1:1/v1"


class Agent:
    DATA_DIR = str(TMP / "engine")
    WORKSPACE = str(TMP / "ws")
    model_name = "fake"
    MODELS = {"fake": _Model()}


(TMP / "ws" / "images").mkdir(parents=True)
(TMP / "ws" / "images" / "20261017-101010-a-fox.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
loki_bridge.PORT = 0
loki_bridge.UI_DIR = ui_tmp
bstate = loki_bridge.BridgeState(Agent(), "godot-secret")
bstate.jobs = Jobs()
bserver = loki_bridge.BridgeHTTPServer(bstate)
port = bserver.server_address[1]
loki_bridge.ALLOWED_HOSTS = ("127.0.0.1:%d" % port, "localhost:%d" % port)
loki_bridge.ALLOWED_ORIGINS = loki_bridge.ALLOWED_ORIGINS + ("http://127.0.0.1:%d" % port,)
threading.Thread(target=bserver.serve_forever, daemon=True).start()


def get(path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    r = conn.getresponse()
    return r.status, dict(r.getheaders()), r.read()


try:
    code, hdr, body = get("/ui/world_godot/index.html")
    check("GET /ui/world_godot/index.html: 200 with the Godot page CSP, frameable by LOKI only",
          code == 200 and "'wasm-unsafe-eval'" in hdr.get("Content-Security-Policy", "")
          and "frame-ancestors 'self'" in hdr.get("Content-Security-Policy", "") and hdr.get("X-Frame-Options") == "SAMEORIGIN", hdr)
    # cross-origin isolation (2026-10-18): the window is COEP require-corp, so every bridge answer - framed pages,
    # /ui files that the sandboxed (opaque-origin) chat diagrams load, even an error - must carry COEP and CORP
    # cross-origin, or diagrams, previews, Apps and Play go blank
    check("a UI page is isolated (COOP + COEP) and readable from LOKI's sandboxed frames (CORP cross-origin)",
          hdr.get("Cross-Origin-Opener-Policy") == "same-origin" and hdr.get("Cross-Origin-Embedder-Policy") == "require-corp"
          and hdr.get("Cross-Origin-Resource-Policy") == "cross-origin", hdr)
    code, hdr, body = get("/ui/no-such-file.js")
    check("every other bridge answer (here a 404) carries COEP require-corp + CORP cross-origin",
          code == 404 and hdr.get("Cross-Origin-Embedder-Policy") == "require-corp"
          and hdr.get("Cross-Origin-Resource-Policy") == "cross-origin", hdr)
    _studio_src = read(REPO / "studio" / "studio_server.py")
    check("Studio's server sends COEP + CORP cross-origin (it is a cross-origin frame in the isolated window)",
          '"Cross-Origin-Embedder-Policy", "require-corp"' in _studio_src
          and '"Cross-Origin-Resource-Policy", "cross-origin"' in _studio_src)
    check("the chat preview pane starts under the title strip (its Close button was covered)",
          "html.has-titlestrip .art-canvas { top: var(--titlebar-h); }" in read(REPO / "app" / "ui" / "glass.css"))
    code, hdr, body = get("/ui/world_godot/index.wasm")
    check("the .wasm is served as application/wasm", code == 200 and hdr.get("Content-Type") == "application/wasm", hdr)
    code, hdr, body = get("/ui/world_godot/index.pck")
    check("the .pck is served", code == 200 and body == b"GDPC")
    # the committed engine is index.wasm.gz (2026-10-18): sent gzipped; the newer of .wasm / .wasm.gz wins
    import gzip as _gz  # noqa: E402
    import os as _os  # noqa: E402
    import time as _time  # noqa: E402
    packed = ui_tmp / "world_godot" / "index.wasm.gz"
    packed.write_bytes(_gz.compress(b"\0asm\x01\0\0\0NEW"))
    _os.utime(ui_tmp / "world_godot" / "index.wasm", (_time.time() - 600, _time.time() - 600))
    code, hdr, body = get("/ui/world_godot/index.wasm")
    check("a newer index.wasm.gz is sent as Content-Encoding: gzip, application/wasm", code == 200
          and hdr.get("Content-Encoding") == "gzip" and hdr.get("Content-Type") == "application/wasm"
          and _gz.decompress(body).endswith(b"NEW"), hdr)
    _os.utime(packed, (_time.time() - 1200, _time.time() - 1200))
    code, hdr, body = get("/ui/world_godot/index.wasm")
    check("a newer plain index.wasm (an export from the Godot app) wins over an older .gz", code == 200
          and "Content-Encoding" not in hdr and body.startswith(b"\0asm") and not body.endswith(b"NEW"), hdr)
    packed.unlink()
    code, hdr, body = get("/ui/index.html")
    check("LOKI's own page keeps the strict CSP (no wasm, not frameable)", code == 200
          and "wasm" not in hdr.get("Content-Security-Policy", "") and "frame-ancestors 'none'" in hdr.get("Content-Security-Policy", ""), hdr)
    code, hdr, body = get("/")
    check("LOKI's own page is cross-origin isolated, so the Godot web editor runs INSIDE the window (SharedArrayBuffer)",
          code == 200 and hdr.get("Cross-Origin-Opener-Policy") == "same-origin"
          and hdr.get("Cross-Origin-Embedder-Policy") == "require-corp", hdr)
    code, hdr, body = get("/ui/world_godot/index.js")
    check("no export yet -> index.js is a 404, so boot.js says 'missing' and LOKI uses Babylon", code == 404)

    # ------------------------------------------------------------------------------------------
    section("Godot itself (headless) - when a Godot 4 binary is here")
    godot = os.environ.get("LOKI_SUITE_GODOT") or shutil.which("godot") or shutil.which("godot4")
    version = ""
    if godot:
        try:
            version = subprocess.run([godot, "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            version = ""
    if not version.startswith("4."):
        print("  SKIP no Godot 4 binary (set LOKI_SUITE_GODOT=<path>) - the Godot runs are left to Ziva (ZIVA_TASKS.md)")
    else:
        print("  Godot", version)
        work = TMP / "loki-world"
        shutil.copytree(GAME, work, ignore=shutil.ignore_patterns(".godot", "build"))
        sys.path.insert(0, str(REPO / "studio"))
        import godot_live  # noqa: E402  - LOKI World's plugin, as LOKI puts it in on every machine
        check("LOKI World gets the LOKI plugin (its project.godot enables it and its game helper)",
              godot_live.ensure_world(work)["ok"] and (work / "addons" / "loki_studio" / "game_bridge.gd").is_file()
              and 'res://addons/loki_studio/plugin.cfg' in (work / "project.godot").read_text(encoding="utf-8"))
        env = dict(os.environ, HOME=str(TMP / "home"))
        (TMP / "home").mkdir(exist_ok=True)

        def run_godot(*args, timeout=600):
            p = subprocess.run([godot, "--headless", "--path", str(work), *args], capture_output=True, text=True,
                               timeout=timeout, env=env)
            return p.returncode, p.stdout + p.stderr

        code, out = run_godot("--import", timeout=900)
        check("the project imports headless", code == 0 and "SCRIPT ERROR" not in out, out[-600:])
        code, out = run_godot("res://tests/run_tests.tscn", "--", "--no-save")
        tail = [ln for ln in out.splitlines() if "passed," in ln]
        check("LOKI World's own Godot tests pass (%s)" % (tail[-1] if tail else "?"), code == 0 and tail and tail[-1].endswith(" 0 failed")
              and "SCRIPT ERROR" not in out, out[-1500:])
        code, out = run_godot("--", "--quit-after=200", "--no-save", "--loki-url=http://127.0.0.1:1")
        check("offline: the demo world runs (no LOKI)", code == 0 and "source=offline" in out and "SCRIPT ERROR" not in out, out[-800:])

        # end to end against the real bridge: /mmo/state, presence both ways, chat
        import presence  # noqa: E402
        stop = threading.Event()

        def remote_owner():
            while not stop.is_set():
                presence.HUB.receive("pc", {"machine": "pc", "player": {"name": "Mohamed", "cls": "Warrior", "lvl": 5,
                                                                           "zone": "pc", "u": 0.2, "v": 0.1, "ts": int(time.time() * 1000)},
                                            "chat": [{"oseq": 1, "from": "Mohamed", "text": "hi from the PC"}]})
                stop.wait(1.0)

        threading.Thread(target=remote_owner, daemon=True).start()
        code, out = run_godot("--", "--run-seconds=9", "--no-save", "--loki-url=http://127.0.0.1:%d" % port,
                              "--token=godot-secret", "--say=hello from Godot", timeout=180)
        stop.set()
        summary = next((ln for ln in out.splitlines() if ln.startswith("LOKI World: ran")), "")
        check("against the real bridge the game uses the engine's MMO API (source=engine)", "source=engine" in summary, summary or out[-800:])
        check("...quests from jobs, a monster from the failed job, loot from the creation",
              "quests=2" in summary and "monsters=1" in summary and "loot=1" in summary, summary)
        local = presence.HUB.local or {}
        check("...its avatar reached the presence hub (POST /world/presence)", local.get("name") and local.get("zone") not in (None, ""), local)
        check("...its chat line went out to the other machines", any(c.get("text") == "hello from Godot" for c in presence.HUB.chat))
        check("...and the owner on the PC is in the game", "remotes=1" in summary, summary)
        check("no script errors in the run", "SCRIPT ERROR" not in out, [ln for ln in out.splitlines() if "ERROR" in ln][:5])
finally:
    bserver.shutdown()
    bserver.server_close()

check("ship.py runs this suite", '"test_godot_world"' in read(REPO / "tools" / "ship.py"))
shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
