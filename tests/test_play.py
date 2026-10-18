"""LOKI's own game engine (app/ui/engine), the Play panel, workspace games, and the Brain map
screen - offline checks.

    python tests/test_play.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import loki_bridge  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:240]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


ui = REPO / "app" / "ui"
engine_js = (ui / "engine" / "pixel_engine.js").read_text(encoding="utf-8")
html = (ui / "index.html").read_text(encoding="utf-8")

section("the engine: LOKI World's look, its own code, no libraries")
check("pixel framebuffer + Bayer posterize + cel bands + ink outlines",
      all(x in engine_js for x in ("bayer4", "BANDS", "gl.cullFace(gl.FRONT)", "NEAREST")))
check("no imports and no network in the engine", "import " not in engine_js.split('"use strict";', 1)[1]
      and "fetch(" not in engine_js and "http" not in engine_js.split('"use strict";', 1)[1])
check("the critters come with it (fox, rabbit) and props", all(("%s(" % m) in engine_js for m in ("fox", "rabbit", "tree", "island")))
if shutil.which("node"):
    for f in ("engine/pixel_engine.js", "engine/play.js", "games/fox_berries/game.js", "play_panel.js", "brain.js"):
        proc = subprocess.run(["node", "--check", str(ui / f)], capture_output=True, text=True)
        check("%s parses" % f, proc.returncode == 0, proc.stderr)
    probe = ("global.window={};require(%r);const M=window.PixelEngine.MESHES;let bad=0;"
             "for(const m of Object.values(M))for(let i=0;i<m.p.length;i+=9){const c=[0,1,2].map(j=>(m.p[i+j]+m.p[i+3+j]+m.p[i+6+j])/3);"
             "if(c[0]*m.n[i]+c[1]*m.n[i+1]+c[2]*m.n[i+2]<0)bad++;}console.log(bad)") % str(ui / "engine" / "pixel_engine.js")
    out = subprocess.run(["node", "-e", probe], capture_output=True, text=True)
    check("every mesh face points outward (so culling and outlines are right)", out.stdout.strip() == "0", out.stdout + out.stderr)

section("games are sealed off from LOKI")
panel = (ui / "play_panel.js").read_text(encoding="utf-8")
check("the Play frame is sandboxed to scripts only (no same-origin: no token, no storage)",
      'setAttribute("sandbox", "allow-scripts")' in panel and "allow-same-origin" not in panel)
check("Settings has Play and Brain tabs", 'data-tab="play"' in html and 'data-tab="brain"' in html
      and "/ui/play_panel.js" in html and "/ui/brain.js" in html)
check("a game stops when Settings closes or another tab opens", "stopPlay" in panel and "stopPlay()" in (ui / "app.js").read_text(encoding="utf-8"))

section("workspace games: served only from workspace/games, only safe file types")
TMP = Path(tempfile.mkdtemp(prefix="loki-play-"))
(TMP / "games" / "snake").mkdir(parents=True)
(TMP / "games" / "snake" / "game.js").write_text("// Snake - eat and grow\n(function(){})();\n", encoding="utf-8")
(TMP / "secret.txt").write_text("no", encoding="utf-8")
(TMP / "games" / "snake" / "notes.txt").write_text("no", encoding="utf-8")
check("a game file is found", loki_bridge.game_file(TMP, "/games/snake/game.js") is not None)
check("nothing outside workspace/games", loki_bridge.game_file(TMP, "/games/../secret.txt") is None
      and loki_bridge.game_file(TMP, "/games/snake/../../secret.txt") is None)
check("only .js/.json/.png/.svg", loki_bridge.game_file(TMP, "/games/snake/notes.txt") is None)
games = loki_bridge.list_games(ui, TMP)
names = {(g["name"], g["src"]) for g in games}
check("the list has the built-in game and LOKI's own", ("fox_berries", "builtin") in names and ("snake", "workspace") in names, games)
check("titles come from the first comment line", any(g["title"] == "Snake" and "eat and grow" in g["about"] for g in games), games)
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("only the Play page may be framed, and only by LOKI itself",
      'framed=(route == "/ui/play.html")' in bridge and "frame-ancestors 'self'" in bridge)
shutil.rmtree(TMP, ignore_errors=True)

section("LOKI's agents can make games")
import loki  # noqa: E402
guide = loki.game_engine_guide()
check("game_engine_guide gives the API, the workflow and a full example",
      "games/<name>/game.js" in guide and "PixelEngine.create" in guide and "Fox & Berries" in guide)
check("it is offered to the model", "game_engine_guide" in loki.MODEL_TOOL_NAMES and "game_engine_guide" in loki.TOOL_CATEGORIES["creative"])

section("Creations: what LOKI made, front and centre")
import creations  # noqa: E402
TMP2 = Path(tempfile.mkdtemp())
(TMP2 / "images").mkdir()
(TMP2 / "images" / "20261014-201742-red-fox-in-studio-light.jpg").write_bytes(b"\xff\xd8\xff")
(TMP2 / "images" / "notes.txt").write_text("no", encoding="utf-8")
(TMP2 / "sketches").mkdir()
(TMP2 / "sketches" / "sketch-20261015-101010.png").write_bytes(b"\x89PNG")
(TMP2 / "secret.jpg").write_bytes(b"x")
made = creations.list_creations(TMP2)
check("the fox shows with a readable title", any(c["title"] == "Red fox in studio light" and c["show"] == "image" for c in made), made)
check("only pictures, videos, sketches and sounds are listed", not any(c["path"].endswith(".txt") for c in made) and len(made) == 2, made)
check("a creation is served from its folder", creations.creation_file(TMP2, "/creations/images/20261014-201742-red-fox-in-studio-light.jpg") is not None)
check("nothing outside those folders", creations.creation_file(TMP2, "/creations/../secret.jpg") is None
      and creations.creation_file(TMP2, "/creations/images/../secret.jpg") is None
      and creations.creation_file(TMP2, "/creations/images/notes.txt") is None
      and creations.creation_file(TMP2, "/creations/games/x.js") is None)
check("the bridge lists them (token) and serves the files (this machine only, sandboxed)",
      'route == "/creations"' in bridge and "def _serve_creation(" in bridge and "default-src 'none'; sandbox" in bridge)
creations_js = (ui / "creations.js").read_text(encoding="utf-8")
check("Settings > Creations: the wall, a 'make it' box that starts a background job, more like this",
      'data-tab="creations"' in html and "/ui/creations.js" in html and 'api("/jobs"' in creations_js
      and "Make more like this" in creations_js)
island = (REPO / "game" / "loki-world" / "scenes" / "home_island.tscn").read_text(encoding="utf-8")
check("LOKI World (the Godot game) has a creations hall that hangs the newest pieces",
      "creations" in island.lower() and "paintings" in (REPO / "game" / "loki-world" / "scripts" / "world" / "world.gd").read_text(encoding="utf-8"))
shutil.rmtree(TMP2, ignore_errors=True)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
