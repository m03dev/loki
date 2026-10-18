"""LOKI World - your character: the name and look you walk the world with, on this machine.

LOKI World's character (the Godot game's character window; the old JS creator is gone, 2026-10-18). It is kept per machine in <data>/world/character.json (harness_data,
never committed) and served by the bridge:

    GET  /character   {ok, character: {...} | null, options, roles, name_max}
    POST /character   {name, role, body, skin, hair, hair_color, eyes, eye_color, top, top_color,
                       bottom, bottom_color, accessory, accessory_color}  -> {ok, character}

Only the options below are accepted (colours are fixed palettes, not free hex), so a client can
draw any saved character without checking it again. GET /mmo/state carries it as profile.look
(docs/MMO_API.md), so the Godot client can use the same look.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

VERSION = 1
NAME_MAX = 24

# The same lists as app/ui/character.js OPTIONS (tests/test_character.py keeps them equal).
OPTIONS: dict = {
    "role": ["builder", "explorer", "artist", "scholar"],
    "body": ["slim", "regular", "broad"],
    "skin": ["#f6d7bf", "#e9bf9c", "#d29e76", "#a8754f", "#7d5234", "#55361f"],
    "hair": ["short", "long", "spiky", "bun", "curly", "bald"],
    "hair_color": ["#1d1a1f", "#4a2f22", "#8a5a33", "#d9b26a", "#c4512e", "#e8e4dc", "#5b7bd6", "#d26aa8"],
    "eyes": ["round", "visor", "sleepy", "wide"],
    "eye_color": ["#2b2b33", "#5a3a22", "#3f78c9", "#3f9a5a", "#2ee6d6", "#9b6ad6"],
    "top": ["tunic", "jacket", "hoodie"],
    "top_color": ["#3b82c4", "#2ec4b6", "#55b85c", "#e0a73a", "#d9604f", "#8b7bff", "#d26aa8", "#e8e4dc", "#3a3f4b", "#8a5a33"],
    "bottom": ["trousers", "shorts", "skirt"],
    "bottom_color": ["#2e3440", "#3b4a6b", "#5a4632", "#4f6b3a", "#7a2f3a", "#8a8f99", "#c9b28a"],
    "accessory": ["none", "hat", "scarf"],
    "accessory_color": ["#d9604f", "#e0a73a", "#2ec4b6", "#8b7bff", "#e8e4dc", "#3a3f4b"],
}

# What each role means in LOKI (the creator shows the line under the name).
ROLES: dict = {
    "builder": {"name": "Builder", "color": "#e0a73a", "about": "Makes things real: code, apps and games, tested and shipped."},
    "explorer": {"name": "Explorer", "color": "#55b85c", "about": "Goes out and finds things: the web, new tools, other machines' islands."},
    "artist": {"name": "Artist", "color": "#d26aa8", "about": "Pictures, video, music and sketches - what LOKI makes for you to keep."},
    "scholar": {"name": "Scholar", "color": "#3b82c4", "about": "Reads, researches and remembers, so every answer has its sources."},
}

DEFAULT: dict = {
    "role": "builder", "body": "regular", "skin": "#e9bf9c", "hair": "short", "hair_color": "#4a2f22",
    "eyes": "round", "eye_color": "#2b2b33", "top": "tunic", "top_color": "#3b82c4", "bottom": "trousers",
    "bottom_color": "#2e3440", "accessory": "none", "accessory_color": "#d9604f",
}

_CONTROL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
_LOCK = threading.Lock()


def clean_name(value: Any) -> str:
    """A name as it may be shown: no control or bidi characters, single spaces, trimmed."""
    if not isinstance(value, str):
        raise ValueError("the name must be text")
    name = re.sub(r"\s+", " ", _CONTROL.sub("", value)).strip()
    if not name:
        raise ValueError("give your character a name")
    if len(name) > NAME_MAX:
        raise ValueError("a name is at most %d characters" % NAME_MAX)
    return name


def validate(data: Any) -> dict:
    """The character to save, or ValueError with a plain sentence. Every field must be one of
    OPTIONS (missing ones take the default); unknown fields are refused, not ignored."""
    if not isinstance(data, dict):
        raise ValueError("a character is an object of name and look")
    unknown = sorted(k for k in data if k not in OPTIONS and k not in ("name", "version"))
    if unknown:
        raise ValueError("unknown field%s: %s" % ("s" if len(unknown) > 1 else "", ", ".join(unknown[:5])))
    out = {"version": VERSION, "name": clean_name(data.get("name"))}
    for key, allowed in OPTIONS.items():
        value = data.get(key, DEFAULT[key])
        if not isinstance(value, str):
            raise ValueError("%s must be one of: %s" % (key, ", ".join(allowed)))
        value = value.strip().lower()
        if value not in allowed:
            raise ValueError("%s must be one of: %s" % (key, ", ".join(allowed)))
        out[key] = value
    return out


def path_for(data_dir: Path) -> Path:
    return Path(data_dir) / "world" / "character.json"


def load(data_dir: Path) -> dict | None:
    """This machine's character, or None when none was made yet (or the file is broken)."""
    try:
        raw = json.loads(path_for(data_dir).read_text(encoding="utf-8"))
        return validate(raw)
    except (OSError, ValueError):
        return None


def save(data_dir: Path, data: Any) -> dict:
    char = validate(data)
    path = path_for(data_dir)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(char, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    return char


def _data_dir(state: Any) -> Path:
    root = getattr(getattr(state, "agent", None), "DATA_DIR", "") or ""
    if not root:
        import sys  # pylint: disable=import-outside-toplevel
        root = getattr(sys.modules.get("loki"), "DATA_DIR", "") or "."
    return Path(root)


def route(state: Any, method: str, path: str, data: Any) -> tuple:
    """GET /character | POST /character -> (status, payload)."""
    if path != "/character":
        return 404, {"ok": False, "error": "Unknown endpoint."}
    root = _data_dir(state)
    if method == "GET":
        return 200, {"ok": True, "character": load(root), "options": OPTIONS, "roles": ROLES, "name_max": NAME_MAX}
    if method == "POST":
        try:
            return 200, {"ok": True, "character": save(root, data)}
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
    return 405, {"ok": False, "error": "Use GET or POST."}
