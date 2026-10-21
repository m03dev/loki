"""LOKI's own standard Godot editor (4.7.2), for a computer that has no Godot of its own.

The Godot tab opens the owner's projects (~/LOKI Projects/<name>) in the Godot installed on the computer
(engine/godot_web.py native_godot). When there is none, LOKI gets the official standard Godot 4.7.2 editor once,
into <data>/addons/godot-export/editor/ (never the repo), SHA-512 checked against the release's SHA512-SUMS, and
opens the project in that. Nothing is kept when a checksum does not match. Godot is MIT.
"""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
VERSION = "4.7.2-stable"
BASE = "https://github.com/godotengine/godot/releases/download/%s/" % VERSION
# from https://github.com/godotengine/godot/releases/download/4.7.2-stable/SHA512-SUMS.txt
EDITORS = {
    "darwin": ("Godot_v4.7.2-stable_macos.universal.zip",
               "38aa16e5bba2083941fc5b3e54be0089bd4cc35e32415f5b9fd9a8a6a7b9818255d44532ea8ef94b5aef56c4b407c2d634fa4f657e4ebe681ebbf59b7bac69ca"),
    "win32": ("Godot_v4.7.2-stable_win64.exe.zip",
              "83decd58fdf67b9d657958a1ae6bf1929c20785315a81effe245874cdc57acb709bf868e00778a96984338c1b29dafdb453c6847747694621c6ecf5da2259993"),
    "linux": ("Godot_v4.7.2-stable_linux.x86_64.zip",
              "9aa00f7a605200940bce3027a567b782f49bd8e940dd06ae9e987bd65aee1b1467edd56ed84fcdcbdd44354bf613bdbb4e5d2913e925850368e150c59ed54c65"),
}


def _data() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else REPO / "harness_data"


def home(data: Path | None = None) -> Path:
    return (data or _data()) / "addons" / "godot-export"


def platform_key() -> str:
    return "darwin" if sys.platform == "darwin" else "win32" if sys.platform == "win32" else "linux"


def editor_binary(data: Path | None = None) -> Path | None:
    """LOKI's own standard Godot editor, when it is there."""
    root = home(data) / "editor"
    if not root.is_dir():
        return None
    if platform_key() == "darwin":
        found = sorted(root.glob("*.app/Contents/MacOS/Godot"))
    elif platform_key() == "win32":
        found = sorted(p for p in root.glob("Godot*.exe") if "console" not in p.name.lower())
    else:
        found = sorted(p for p in root.glob("Godot*") if p.is_file())
    return found[0] if found else None


def _download(url: str, opener=urllib.request.urlopen) -> bytes:
    with opener(urllib.request.Request(url, headers={"User-Agent": "LOKI"}), timeout=900) as resp:
        return resp.read()


def install(data: Path | None = None, opener=urllib.request.urlopen, say: Callable[[str], None] = lambda _t: None,
            editor_only: bool = True) -> dict:
    """Get LOKI's own Godot editor (once). Nothing is kept when the checksum does not match.
    (`editor_only` is accepted for older callers; the editor is all there is.)"""
    del editor_only
    root = home(data)
    if editor_binary(data) is not None:
        return {"ok": True}
    name, want = EDITORS[platform_key()]
    say("Downloading Godot %s (one time, %s)..." % (VERSION, "about 170 MB" if platform_key() == "darwin" else "about 80 MB"))
    blob = _download(BASE + name, opener)
    if hashlib.sha512(blob).hexdigest() != want:
        return {"ok": False, "error": "the Godot download did not match its SHA-512 - nothing was kept"}
    target = root / "editor"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.infolist():
            dest = (target / info.filename).resolve()
            if not str(dest).startswith(str(target.resolve())):
                shutil.rmtree(target, ignore_errors=True)
                return {"ok": False, "error": "unsafe path in the Godot zip: %s" % info.filename}
            z.extract(info, target)
            mode = (info.external_attr >> 16) & 0o777
            if mode & 0o111:
                dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if editor_binary(data) is None:
        return {"ok": False, "error": "the Godot zip had no editor in it"}
    return {"ok": True}
