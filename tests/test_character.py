"""LOKI World - the character creator and "Join world" (offline, well under a minute).

    python tests/test_character.py

engine/character.py (GET/POST /character, <data>/world/character.json) validates and keeps the
character; the Godot game (game/loki-world) shows and dresses your avatar in
it; GET /mmo/state carries it as profile.look for the Godot client (docs/MMO_API.md).
The window part runs in headless Chromium when Playwright is there (skipped otherwise).
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import character  # noqa: E402

PASS, FAIL = [], []
UI = REPO / "app" / "ui"
TMP = Path(tempfile.mkdtemp(prefix="loki-char-"))


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:400]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


class Agent:
    DATA_DIR = str(TMP / "data")
    WORKSPACE = str(TMP / "ws")


class State:
    agent = Agent()


GOOD = {"name": "Wren", "role": "artist", "body": "slim", "skin": "#a8754f", "hair": "curly", "hair_color": "#c4512e",
        "eyes": "wide", "eye_color": "#3f9a5a", "top": "hoodie", "top_color": "#d26aa8", "bottom": "skirt",
        "bottom_color": "#3b4a6b", "accessory": "scarf", "accessory_color": "#e0a73a"}

# ------------------------------------------------------------------------------------------
section("the route: save, load, validate")
code, out = character.route(State(), "GET", "/character", {})
check("GET /character with none made yet -> character null, with the options", code == 200 and out["character"] is None
      and out["options"]["role"] == ["builder", "explorer", "artist", "scholar"] and out["name_max"] == 24, out)
check("every role has a name and one line of what it means", all(r["name"] and r["about"] for r in out["roles"].values())
      and set(out["roles"]) == set(out["options"]["role"]))
code, out = character.route(State(), "POST", "/character", GOOD)
check("POST /character saves a good character", code == 200 and out["character"]["name"] == "Wren"
      and out["character"]["hair"] == "curly", out)
code, out = character.route(State(), "GET", "/character", {})
check("...and GET /character loads it back", code == 200 and {k: out["character"][k] for k in GOOD} == GOOD, out)
saved = TMP / "data" / "world" / "character.json"
check("kept per machine in <data>/world/character.json", saved.is_file() and json.loads(saved.read_text())["name"] == "Wren")
code, out = character.route(State(), "POST", "/character", {"name": "  Kit   Fox "})
check("missing fields take the defaults; spaces tidied", code == 200 and out["character"]["name"] == "Kit Fox"
      and out["character"]["role"] == "builder", out)
bad_cases = [
    ("an empty name", {"name": "   "}),
    ("no name", {"role": "artist"}),
    ("a name over 24 characters", {"name": "x" * 25}),
    ("a name that is not text", {"name": 7}),
    ("an unknown role", dict(GOOD, role="wizard")),
    ("an unknown hair style", dict(GOOD, hair="mohawk")),
    ("a colour not in the palette", dict(GOOD, top_color="#123456")),
    ("free CSS as a colour", dict(GOOD, skin="red;}")),
    ("a number as an option", dict(GOOD, body=3)),
    ("an unknown field", dict(GOOD, script="<b>")),
    ("not an object", ["Wren"]),
]
for label, body in bad_cases:
    code, out = character.route(State(), "POST", "/character", body)
    check("refused: %s (400, says why)" % label, code == 400 and out.get("ok") is False and out.get("error"), (code, out))
check("a refused save leaves the saved one alone", character.load(Path(Agent.DATA_DIR))["name"] == "Kit Fox")
check("control and bidi characters are stripped from the name",
      character.validate({"name": "Mo‮\x00ha"})["name"] == "Moha")
check("exactly 24 characters is fine", character.validate({"name": "y" * 24})["name"] == "y" * 24)
check("upper-case options are read as the same option", character.validate(dict(GOOD, hair="LONG"))["hair"] == "long")
saved.write_text("{broken", encoding="utf-8")
check("a broken file reads as no character (the creator shows again)", character.load(Path(Agent.DATA_DIR)) is None)
saved.write_text(json.dumps(dict(GOOD, hair="mohawk")), encoding="utf-8")
check("a hand-edited file with an unknown option reads as no character", character.load(Path(Agent.DATA_DIR)) is None)
check("other methods / paths", character.route(State(), "PUT", "/character", {})[0] == 405
      and character.route(State(), "GET", "/characters", {})[0] == 404)
character.save(Path(Agent.DATA_DIR), GOOD)

section("the bridge, /mmo/state and the Godot client")
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("loki_bridge routes GET and POST /character to engine/character.py",
      bridge.count('route == "/character"') == 2 and bridge.count("character.route(") == 2)
try:
    import mmo_state  # noqa: E402

    class Store:
        def all(self):
            return []

    class Jobs:
        store = Store()

    State.jobs = Jobs()
    State.chat_lock = None
    code, out = mmo_state.route(State(), "GET", "/mmo/state", {}, lambda *a: (200, {}))
    look = out.get("profile", {}).get("look") or {}
    check("GET /mmo/state carries the character as profile.look, and its name", code == 200 and look.get("hair") == "curly"
          and out["profile"]["name"] == "Wren", (code, str(out)[:300]))
except ImportError as exc:   # pragma: no cover
    check("mmo_state imports", False, exc)
api_doc = (REPO / "docs" / "MMO_API.md").read_text(encoding="utf-8")
check("docs/MMO_API.md documents profile.look and /character", "profile.look" in api_doc and "/character" in api_doc)
player_gd = (REPO / "game" / "loki-world" / "scripts" / "actors" / "player.gd").read_text(encoding="utf-8")
check("the Godot player builds its model from profile.look", 'p.get("look")' in player_gd and "top_color" in player_gd)

section("the window")
UI_FILES = [p.name for p in UI.iterdir()]
check("the JS character creator is gone: the Godot game's character window is the one (2026-10-18)",
      "character.js" not in UI_FILES and "/ui/character.js" not in (UI / "index.html").read_text(encoding="utf-8"))
ship = (REPO / "tools" / "ship.py").read_text(encoding="utf-8")
check("ship.py runs this suite", '"test_character"' in ship)

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
