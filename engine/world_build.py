"""Rebuild LOKI World's web build from game/loki-world - the loop between the Godot editor and the World tab.

Owner, 2026-10-18: "loki world wasnt build in godot ... how are we going to incorporate into godot editor ... they feel
like separate pieces". The game is one Godot 4.7 project (game/loki-world). You change it in the Godot editor (the
Godot tab: "Open in the Godot app", or the web editor), then "Rebuild World" here exports it to app/ui/world_godot/
and the World tab shows your change. LOKI's own agents (Studio, improve_loki) use the same call.

Why LOKI keeps its own Godot for this: a C# (mono) Godot - the Mac's is - cannot export to the web, and the web
export needs Godot's web template. So, once, into <data>/addons/godot-export/ (never the repo):
  * the official standard Godot 4.7.2 editor for this OS, SHA-512 checked against the release's SHA512-SUMS;
  * only the web template (web_nothreads_release.zip, ~10 MB) read out of the 1.3 GB template pack with HTTP range
    requests, zip-CRC checked and SHA-512 pinned (WEB_TEMPLATE_SHA512);
then `godot --headless --path game/loki-world --export-release Web`, and index.wasm is stored gzipped (the engine
serves it with Content-Encoding: gzip; engine/loki_bridge.py). Godot is MIT.

    GET  /world/build          status: installed, building, last result
    POST /world/build          {confirm: true} start a rebuild in the background
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
GAME = REPO / "game" / "loki-world"
OUT = REPO / "app" / "ui" / "world_godot"
VERSION = "4.7.2-stable"
TEMPLATE_DIR_NAME = "4.7.2.stable"
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
TEMPLATES_TPZ = "Godot_v4.7.2-stable_export_templates.tpz"
WEB_TEMPLATE = "web_nothreads_release.zip"
# the member's own hash (computed 2026-10-18 from the official 4.7.2 tpz; the tpz itself is 1.3 GB, never fetched whole)
WEB_TEMPLATE_SHA512 = ("33a52b6d9b1ce32d3683caaa3ea4b997a3f84c76a92a2e4a98a115b46da55d88"
                       "7854c9ef49bbf3b45b9629938110837978132c3a8cda26d278eb020bd6a9b8ea")
GZIP_ABOVE = 5_000_000          # files bigger than this are kept gzipped (index.wasm)

_LOCK = threading.Lock()
JOB: dict = {"state": "idle", "note": "", "t": 0.0, "log": ""}


def _data() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else REPO / "harness_data"


def home(data: Path | None = None) -> Path:
    return (data or _data()) / "addons" / "godot-export"


def platform_key() -> str:
    return "darwin" if sys.platform == "darwin" else "win32" if sys.platform == "win32" else "linux"


def editor_binary(data: Path | None = None) -> Path | None:
    """LOKI's own standard Godot for exporting, when it is there."""
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


def template_dir(data: Path | None = None) -> Path:
    """Godot looks for export templates under its data folder; LOKI points Godot's data folder at its own
    (XDG_DATA_HOME / APPDATA / HOME on macOS for the export process only), so nothing of the owner's is touched."""
    return home(data) / "userdata" / "godot" / "export_templates" / TEMPLATE_DIR_NAME


def export_env(data: Path | None = None) -> dict:
    user = home(data) / "userdata"
    env = dict(os.environ)
    if platform_key() == "darwin":
        # macOS Godot keeps templates in ~/Library/Application Support/Godot: a private HOME just for the export
        fake = home(data) / "home"
        (fake / "Library" / "Application Support" / "Godot").mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(fake)
    elif platform_key() == "win32":
        env["APPDATA"] = str(user)
    else:
        env["XDG_DATA_HOME"] = str(user)
    return env


def template_target(data: Path | None = None) -> Path:
    if platform_key() == "darwin":
        return home(data) / "home" / "Library" / "Application Support" / "Godot" / "export_templates" / TEMPLATE_DIR_NAME
    return template_dir(data)


def ready(data: Path | None = None) -> bool:
    return editor_binary(data) is not None and (template_target(data) / WEB_TEMPLATE).is_file()


def status(data: Path | None = None) -> dict:
    built = (OUT / "index.pck").is_file() and ((OUT / "index.wasm.gz").is_file() or (OUT / "index.wasm").is_file())
    try:
        built_at = (OUT / "index.pck").stat().st_mtime
    except OSError:
        built_at = 0.0
    newest = 0.0
    for p in GAME.rglob("*"):
        if p.is_file() and ".godot" not in p.parts and "tests" not in p.parts:
            newest = max(newest, p.stat().st_mtime)
    return {"ok": True, "installed": ready(data), "built": built, "out_of_date": bool(built and newest > built_at + 1),
            "version": VERSION, "job": dict(JOB), "project": str(GAME)}


# ------------------------------------------------------------------ downloads
class _Ranged(io.RawIOBase):
    """A remote file read with HTTP Range requests, so zipfile can take one member out of a 1.3 GB pack."""

    def __init__(self, url: str, opener=urllib.request.urlopen) -> None:
        super().__init__()
        self.url, self.pos, self.opener = url, 0, opener
        with opener(urllib.request.Request(url, method="HEAD"), timeout=60) as resp:
            self.size = int(resp.headers["Content-Length"])

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = offset if whence == 0 else (self.pos + offset if whence == 1 else self.size + offset)
        return self.pos

    def tell(self) -> int:
        return self.pos

    def readinto(self, buf) -> int:
        n = min(len(buf), self.size - self.pos)
        if n <= 0:
            return 0
        req = urllib.request.Request(self.url, headers={"Range": "bytes=%d-%d" % (self.pos, self.pos + n - 1)})
        with self.opener(req, timeout=180) as resp:
            data = resp.read()
        buf[:len(data)] = data
        self.pos += len(data)
        return len(data)


def _download(url: str, opener=urllib.request.urlopen) -> bytes:
    with opener(urllib.request.Request(url, headers={"User-Agent": "LOKI"}), timeout=900) as resp:
        return resp.read()


def install(data: Path | None = None, opener=urllib.request.urlopen, say: Callable[[str], None] = lambda _t: None,
            editor_only: bool = False) -> dict:
    """Get LOKI's own Godot editor and the web template (once). Nothing is kept when a checksum does not match.
    editor_only: just the editor (Open in Godot needs nothing else)."""
    root = home(data)
    if editor_binary(data) is None:
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
                    return {"ok": False, "error": "unsafe path in the Godot zip: %s" % info.filename}
                z.extract(info, target)
                mode = (info.external_attr >> 16) & 0o777
                if mode & 0o111:
                    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if editor_binary(data) is None:
            return {"ok": False, "error": "the Godot zip had no editor in it"}
    if editor_only:
        return {"ok": True}
    tpl = template_target(data) / WEB_TEMPLATE
    if not tpl.is_file():
        say("Taking Godot's web template out of the template pack (about 10 MB of 1.3 GB)...")
        with zipfile.ZipFile(io.BufferedReader(_Ranged(BASE + TEMPLATES_TPZ, opener), buffer_size=1 << 20)) as z:
            member = next((n for n in z.namelist() if n.endswith("/" + WEB_TEMPLATE)), "")
            if not member:
                return {"ok": False, "error": "the template pack has no %s" % WEB_TEMPLATE}
            blob = z.read(member)          # zipfile checks the member's CRC
        if hashlib.sha512(blob).hexdigest() != WEB_TEMPLATE_SHA512:
            return {"ok": False, "error": "the web template did not match its SHA-512 - nothing was kept"}
        tpl.parent.mkdir(parents=True, exist_ok=True)
        tpl.write_bytes(blob)
    return {"ok": True}


# ------------------------------------------------------------------ the build
def export(data: Path | None = None, run=subprocess.run, out: Path = OUT) -> dict:
    """Export game/loki-world to `out` with LOKI's Godot; big files are kept gzipped. Returns {ok, log, files}."""
    godot = editor_binary(data)
    if godot is None:
        return {"ok": False, "error": "LOKI's Godot is not installed yet"}
    env = export_env(data)
    log = ""
    try:   # the plugin's game helper is an autoload of LOKI World: it must be there to export cleanly
        import godot_live  # pylint: disable=import-outside-toplevel
        godot_live.ensure_world(GAME)
    except Exception:  # noqa: BLE001 - the export still works, with a warning from Godot
        pass
    for args in (["--headless", "--path", str(GAME), "--import"],
                 ["--headless", "--path", str(GAME), "--export-release", "Web"]):
        proc = run([str(godot), *args], capture_output=True, text=True, timeout=900, env=env, cwd=str(GAME))
        log += re.sub(r"\x1b\[[0-9;]*m", "", (proc.stdout or "")[-4000:] + (proc.stderr or "")[-4000:])
        if proc.returncode != 0:
            return {"ok": False, "error": "Godot stopped (%s)" % proc.returncode, "log": log[-3000:]}
    files = []
    for p in sorted(out.glob("index.*")):
        if p.suffix == ".gz":
            continue
        if p.stat().st_size > GZIP_ABOVE:
            gz = p.with_name(p.name + ".gz")
            # deterministic (no time, no name in the header): an unchanged engine gives the same bytes, so a rebuild
            # never adds another 10 MB to git
            with open(p, "rb") as src, open(gz, "wb") as raw, \
                    gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as dst:
                shutil.copyfileobj(src, dst)
            p.unlink()
            files.append(gz.name)
        else:
            files.append(p.name)
    if "index.pck" not in files:
        return {"ok": False, "error": "Godot made no game pack (index.pck)", "log": log[-3000:]}
    return {"ok": True, "files": files, "log": log[-1500:]}


def rebuild(data: Path | None = None, opener=urllib.request.urlopen, run=subprocess.run) -> dict:
    with _LOCK:
        if JOB["state"] == "building":
            return {"ok": False, "error": "a rebuild is already running"}
        JOB.update(state="building", note="Getting ready...", t=time.time(), log="")
    try:
        got = install(data, opener, say=lambda t: JOB.update(note=t))
        if not got.get("ok"):
            JOB.update(state="failed", note=got.get("error", "install failed"))
            return got
        JOB.update(note="Exporting LOKI World from game/loki-world...")
        res = export(data, run)
        JOB.update(state="done" if res.get("ok") else "failed", log=res.get("log", ""),
                   note=("LOKI World rebuilt (%s). The World tab shows it when you open it again." % ", ".join(res["files"]))
                   if res.get("ok") else res.get("error", "failed"))
        return res
    except Exception as exc:  # noqa: BLE001 - a failed rebuild must never take the engine down
        JOB.update(state="failed", note="%s: %s" % (type(exc).__name__, exc))
        return {"ok": False, "error": JOB["note"]}


def route(method: str, path: str, data: dict, data_dir: Path | None = None) -> tuple | None:
    if path != "/world/build":
        return None
    if method == "GET":
        return 200, status(data_dir)
    if not (data or {}).get("confirm"):
        return 400, {"ok": False, "error": "rebuilding LOKI World needs confirm: true (it downloads Godot once)"}
    if JOB["state"] == "building":
        return 200, {"ok": True, "started": False, "note": JOB["note"]}
    threading.Thread(target=rebuild, args=(data_dir,), daemon=True, name="loki-world-build").start()
    return 200, {"ok": True, "started": True}


if __name__ == "__main__":
    print(json.dumps(rebuild(), indent=1))
