"""The Godot tab of LOKI's window: the official Godot 4 web editor, served by LOKI, plus the native editor.

  GET  /godot-editor/app/<file>      the web editor's files (godot.editor.html/.js/.wasm/.pck, worker, icons) with
                                     Cross-Origin-Opener-Policy: same-origin + Cross-Origin-Embedder-Policy: require-corp
                                     (SharedArrayBuffer needs both). No token: a page cannot send one; Host check only,
                                     and these files are Godot's own public build - nothing of the user's.
  GET  /godot-editor/status          installed?, version, the projects, the native Godot (token)
  POST /godot-editor/install         download the editor once into <data>/addons/godot-web-editor, SHA-512 checked
  GET  /godot-editor/project.zip?name=   a project folder as a zip, to import in the web editor's Project Manager
  POST /godot-editor/import {name, confirm: true}   bring back the newest <name>*.zip from Downloads (the web editor's
                                     "Project > Tools > Download Project Source") into the project folder
  POST /godot-editor/new {name}      a new empty Godot project in ~/LOKI Projects
  POST /godot-editor/link {path}     add a Godot project that lives in another folder (it stays there)
  POST /godot-editor/native {name}   open the project in the installed Godot app with the LOKI Studio plugin

The web editor works on a virtual file system in the browser (IndexedDB). Files flow: LOKI's project folder ->
project.zip -> the web editor (Import), and back: the editor's "Download Project Source" zip -> Import here.
The Godot web editor is MIT (godotengine.org); it is downloaded on first use and never committed.
Projects: ~/LOKI Projects/<name> (LOKI_PROJECTS_DIR).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parent.parent
# 4.7.2: the same version as LOKI's own editor (engine/godot_editor.py)
VERSION = "4.7.2-stable"
ZIP_NAME = "Godot_v%s_web_editor.zip" % VERSION
URL = "https://github.com/godotengine/godot/releases/download/%s/%s" % (VERSION, ZIP_NAME)
# from https://github.com/godotengine/godot/releases/download/4.7.2-stable/SHA512-SUMS.txt
SHA512 = ("03ad6b4b4d96f0f7d85bf4fdcf29535891b79d52ee94a11e96895463a2745347"
          "b8f601b455e7a58135bf641df43fc25296bc257bbfce593d477dfa64a2272268")
MAX_ZIP = 200 * 1024 * 1024
ALLOWED_EXT = {".html", ".js", ".wasm", ".pck", ".png", ".svg", ".ico", ".json", ".webmanifest", ".txt", ".md"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".wasm": "application/wasm",
         ".pck": "application/octet-stream", ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon",
         ".json": "application/json", ".webmanifest": "application/manifest+json", ".txt": "text/plain; charset=utf-8",
         ".md": "text/plain; charset=utf-8"}
# The editor page has inline scripts and compiles WebAssembly; it lives on its own path with its own policy.
EDITOR_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
              "img-src 'self' data: blob:; connect-src 'self' blob: data:; worker-src 'self' blob:; "
              "frame-ancestors 'self'; base-uri 'none'; form-action 'none'")
ISOLATION = {"Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Embedder-Policy": "require-corp",
             "Cross-Origin-Resource-Policy": "same-origin"}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,99}$")
_JOB: dict = {"state": "idle", "note": ""}
_LOCK = threading.Lock()


# ------------------------------------------------------------------ where things are
def data_dir() -> Path:
    return Path(os.getenv("LOKI_DATA") or (REPO / "harness_data"))


def editor_dir(data: Path | None = None) -> Path:
    return Path(data or data_dir()) / "addons" / "godot-web-editor"


def projects_dir() -> Path:
    return Path(os.getenv("LOKI_PROJECTS_DIR") or (Path.home() / "LOKI Projects"))


# Godot projects the owner keeps somewhere else (~/new-game-project, ~/dungeon ...): "Add a project from a folder"
# records them here, so the tab lists them beside ~/LOKI Projects/*. Never LOKI's own checkout, never ai_testin.
HIDDEN = {"ai_testin"}


def links_file() -> Path:
    return projects_dir() / ".godot_links.json"


def _links() -> list:
    try:
        got = json.loads(links_file().read_text(encoding="utf-8"))
        return [str(x) for x in got if isinstance(x, str)]
    except (OSError, ValueError, TypeError):
        return []


def _is_loki_repo(p: Path) -> bool:
    try:
        return p.resolve() == REPO.resolve() or (p / "engine" / "loki.py").is_file()
    except OSError:
        return False


def projects() -> list:
    out, seen = [], set()

    def add(p: Path, linked: bool) -> None:
        if not (p.is_dir() and (p / "project.godot").is_file()) or p.name.lower() in HIDDEN or _is_loki_repo(p):
            return
        key = str(p.resolve())
        if key in seen:
            return
        seen.add(key)
        name, n = p.name, 2
        while any(o["name"] == name for o in out):
            name, n = "%s (%d)" % (p.name, n), n + 1
        out.append({"name": name, "label": name + (" - " + str(p.parent) if linked else ""), "path": str(p), "linked": linked})

    base = projects_dir()
    if base.is_dir():
        for p in sorted(base.iterdir()):
            if NAME.match(p.name):
                add(p, False)
    for raw in _links():
        add(Path(raw).expanduser(), True)
    return out


def link_project(path: str) -> dict:
    """Add a Godot project folder that lives outside ~/LOKI Projects (it stays where it is)."""
    p = Path(str(path or "").strip().strip('"')).expanduser()
    if p.name == "project.godot":
        p = p.parent
    if not p.is_dir():
        raise ValueError("no folder %s" % p)
    if not (p / "project.godot").is_file():
        raise ValueError("%s has no project.godot - pick the folder Godot shows in its Project Manager" % p)
    if _is_loki_repo(p):
        raise ValueError("that is LOKI's own folder, not a game project")
    links = [x for x in _links() if Path(x).expanduser().resolve() != p.resolve()] + [str(p.resolve())]
    projects_dir().mkdir(parents=True, exist_ok=True)
    links_file().write_text(json.dumps(links, indent=1), encoding="utf-8")
    name = next((o["name"] for o in projects() if Path(o["path"]).resolve() == p.resolve()), p.name)
    return {"ok": True, "name": name, "note": "Added %s - it stays where it is." % p}


def new_project(name: str) -> dict:
    """A new, empty Godot 4 project in ~/LOKI Projects/<name> (a 3D scene with a camera and a light)."""
    name = str(name or "").strip()
    if not NAME.match(name):
        raise ValueError("use letters, numbers, spaces, . _ - for the name")
    root = projects_dir() / name
    if root.exists():
        raise ValueError("%s already exists" % root)
    root.mkdir(parents=True)
    (root / "project.godot").write_text(
        "; Engine configuration file.\nconfig_version=5\n\n[application]\n\n"
        'config/name="%s"\nrun/main_scene="res://main.tscn"\nconfig/features=PackedStringArray("4.4")\n\n'
        '[rendering]\n\nrenderer/rendering_method="forward_plus"\n' % name.replace('"', ""), encoding="utf-8")
    (root / "main.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="Main" type="Node3D"]\n\n'
        '[node name="Camera3D" type="Camera3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 0.94, 0.34, 0, -0.34, 0.94, 0, 2, 5)\n\n'
        '[node name="Sun" type="DirectionalLight3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 0.7, 0.7, 0, -0.7, 0.7, 0, 5, 0)\n',
        encoding="utf-8")
    return {"ok": True, "name": name, "note": "Made %s." % root}


def project_path(name: str) -> Path:
    for p in projects():
        if p["name"] == name:
            return Path(p["path"])
    raise KeyError("no Godot project %r (in %s)" % (name, projects_dir()))


def native_godot() -> str:
    """The installed Godot editor: GODOT_BIN (or GODOT_EXE, what the app passes), godot/godot4 on
    PATH, or the usual install places (both OSes). On macOS any Godot*.app counts - the mono build
    is Godot_mono.app and a version-named download is Godot_v4.x-stable.app."""
    for cand in (os.getenv("GODOT_BIN", ""), os.getenv("GODOT_EXE", ""),
                 shutil.which("godot") or "", shutil.which("godot4") or ""):
        if cand and Path(cand).is_file():
            return cand
    places = []
    if sys.platform == "darwin":
        places = []
        for base in (Path("/Applications"), Path.home() / "Applications"):
            if base.is_dir():
                places += sorted(base.glob("Godot*.app/Contents/MacOS/Godot"))
        places += [Path("/Applications/Godot.app/Contents/MacOS/Godot"),
                   Path.home() / "Applications/Godot.app/Contents/MacOS/Godot"]
    elif sys.platform == "win32":
        for root in (Path(os.getenv("LOCALAPPDATA", "")) / "Programs", Path(os.getenv("ProgramFiles", "C:/Program Files")),
                     Path.home() / "Desktop", Path.home() / "Downloads"):
            if root.is_dir():
                places += sorted(root.glob("Godot*/Godot*.exe")) + sorted(root.glob("Godot*.exe"))
    else:
        places = [Path("/usr/bin/godot"), Path("/usr/local/bin/godot")]
    for p in places:
        if p.is_file() and "console" not in p.name.lower():
            return str(p)
    return ""


def status(data: Path | None = None) -> dict:
    d = editor_dir(data)
    meta = {}
    try:
        meta = json.loads((d / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {"ok": True, "installed": (d / "godot.editor.html").is_file(), "version": meta.get("version", ""),
            "want": VERSION, "job": dict(_JOB), "projects": projects(), "native": native_godot() or loki_godot(),
            "loki_godot": dict(_GET_GODOT, ready=bool(loki_godot())),
            "projects_dir": str(projects_dir()), "page": "/godot-editor/app/godot.editor.html",
            "flow": "LOKI's project folder -> project.zip -> the web editor's Import; back: the editor's Project > Tools > "
                    "Download Project Source -> 'Bring back from Downloads' here. The web editor keeps its own copy in the "
                    "browser until you bring it back."}


# ------------------------------------------------------------------ the download (checksum + safe unpack)
def safe_member(name: str) -> str:
    """The plain file name a zip member may be unpacked to, or "" (folders, traversal, odd types are refused)."""
    name = str(name or "").replace("\\", "/")
    if not name or name.endswith("/") or name.startswith("/") or ".." in name.split("/") or ":" in name:
        return ""
    base = name.split("/")[-1]
    if not base or base.startswith(".") or Path(base).suffix.lower() not in ALLOWED_EXT:
        return ""
    return base


def unpack(blob: bytes, target: Path) -> list:
    target = Path(target)
    tmp = target.with_name(target.name + ".new")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    names = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for info in zf.infolist():
            base = safe_member(info.filename)
            if not base:
                continue
            dst = (tmp / base).resolve()
            if dst.parent != tmp.resolve():
                continue
            with zf.open(info) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
            names.append(base)
    if "godot.editor.html" not in names:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError("the download has no godot.editor.html - not Godot's web editor")
    (tmp / "installed.json").write_text(json.dumps({"version": VERSION, "sha512": SHA512, "t": time.time(),
                                                    "files": sorted(names)}), encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    return names


def install(data: Path | None = None, opener=urllib.request.urlopen, url: str = URL, sha512: str = SHA512) -> dict:
    """Download, check the SHA-512, unpack. Nothing is kept when the checksum does not match."""
    with _LOCK:
        _JOB.update(state="downloading", note="Downloading Godot %s's web editor (about 55 MB)..." % VERSION)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LOKI/1"})
        h = hashlib.sha512()
        buf = io.BytesIO()
        with opener(req, timeout=120) as resp:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                buf.write(chunk)
                if buf.tell() > MAX_ZIP:
                    raise ValueError("the download is larger than expected - stopped")
        if h.hexdigest() != sha512:
            raise ValueError("the checksum does not match (SHA-512 %s...) - nothing was kept" % h.hexdigest()[:16])
        names = unpack(buf.getvalue(), editor_dir(data))
        res = {"ok": True, "files": len(names), "note": "Godot %s's web editor is ready." % VERSION}
        _JOB.update(state="done", note=res["note"])
        return res
    except Exception as exc:  # noqa: BLE001
        _JOB.update(state="failed", note=str(exc))
        return {"ok": False, "error": str(exc)}


# ------------------------------------------------------------------ project folders <-> the web editor
SKIP_DIRS = {".godot", ".import", ".git", "__pycache__"}


def project_zip(name: str) -> bytes:
    root = project_path(name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if p.is_file() and not (set(rel.parts) & SKIP_DIRS):
                zf.write(p, "%s/%s" % (root.name, rel.as_posix()))
    return buf.getvalue()


def downloads_dir() -> Path:
    return Path(os.getenv("LOKI_DOWNLOADS_DIR") or (Path.home() / "Downloads"))


def import_back(name: str, zip_path: str = "") -> dict:
    """The newest <name>*.zip in Downloads (or zip_path) into the project folder. Paths that leave it are skipped."""
    root = project_path(name)
    if zip_path:
        src = Path(zip_path)
    else:
        found = sorted((p for p in downloads_dir().glob("*.zip") if p.name.lower().startswith(name.lower()[:20])),
                       key=lambda p: p.stat().st_mtime)
        if not found:
            return {"ok": False, "error": "no %s*.zip in %s - in the web editor use Project > Tools > Download Project "
                    "Source first" % (name, downloads_dir())}
        src = found[-1]
    written, skipped = 0, 0
    real = root.resolve()
    with zipfile.ZipFile(src) as zf:
        members = [i for i in zf.infolist() if not i.is_dir()]
        prefix = os.path.commonprefix([i.filename for i in members]) if members else ""
        prefix = prefix[:prefix.rfind("/") + 1] if "/" in prefix else ""
        for info in members:
            rel = info.filename[len(prefix):].replace("\\", "/")
            parts = rel.split("/")
            if not rel or rel.startswith("/") or ".." in parts or ":" in rel or set(parts) & SKIP_DIRS:
                skipped += 1
                continue
            dst = (real / rel).resolve()
            if real not in dst.parents:
                skipped += 1
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as s, open(dst, "wb") as out:
                shutil.copyfileobj(s, out)
            written += 1
    return {"ok": True, "written": written, "skipped": skipped, "from": str(src),
            "note": "%d files from %s are in %s now%s." % (written, src.name, root, (" (%d skipped)" % skipped) if skipped else "")}


def loki_godot(install: bool = False) -> str:
    """LOKI's own standard Godot 4.7.2 (engine/godot_editor.py keeps it in <data>/addons/godot-export), installed on
    first use when `install`: a project opens in it when the computer has no Godot of its own (standard, no C#, the
    Asset Library included). LOKI_GODOT_EDITOR=system never uses it."""
    if os.getenv("LOKI_GODOT_EDITOR", "loki").strip().lower() == "system":
        return ""
    try:
        import godot_editor  # pylint: disable=import-outside-toplevel
        exe = godot_editor.editor_binary()
        if exe is None and install:
            got = godot_editor.install()
            exe = godot_editor.editor_binary()
            if exe is None:
                _GET_GODOT["error"] = str(got.get("error") or "the download failed")
        return str(exe) if exe else ""
    except Exception as exc:  # noqa: BLE001
        _GET_GODOT["error"] = str(exc)
        return ""


def prefetch(log=print) -> str:
    """Engine start: when this computer has no Godot, get LOKI's Godot 4.7.2 in the background once, so Open in
    Godot opens a project at once. LOKI_GODOT_PREFETCH=off skips it."""
    if os.getenv("LOKI_GODOT_EDITOR", "loki").strip().lower() == "system" or \
            os.getenv("LOKI_GODOT_PREFETCH", "on").strip().lower() in ("off", "0", "false", "no"):
        return ""
    if loki_godot():
        return loki_godot()
    if native_godot():
        return ""
    if _GET_GODOT["state"] == "downloading":
        return ""
    _GET_GODOT.update(state="downloading", note="Getting Godot 4.7.2 (one time, checked)...", error="")
    log("[loki-bridge] getting LOKI's Godot 4.7.2 (one time, ~80-170 MB)")
    exe = loki_godot(install=True)
    if exe:
        _GET_GODOT.update(state="done", note="LOKI's Godot 4.7.2 is ready")
        log("[loki-bridge] LOKI's Godot 4.7.2 is ready: " + exe)
    else:
        _GET_GODOT.update(state="failed", note="could not get Godot 4.7.2: " + _GET_GODOT.get("error", ""))
        log("[loki-bridge] could not get LOKI's Godot 4.7.2: " + _GET_GODOT.get("error", ""))
    return exe


_GET_GODOT: dict = {"state": "idle", "note": "", "error": ""}


def open_native(name: str, popen=subprocess.Popen, background: bool = True) -> dict:
    root = project_path(name)
    # the computer's own Godot first; LOKI's own 4.7.2 when there is none (LOKI_GODOT_EDITOR=system: never)
    use_loki = not native_godot() and os.getenv("LOKI_GODOT_EDITOR", "loki").strip().lower() != "system"
    if use_loki and not loki_godot():
        # first time: get LOKI's Godot 4.7.2 (~80-170 MB) in the background, then open - the window never hangs.
        if _GET_GODOT["state"] != "downloading":
            _GET_GODOT.update(state="downloading", note="", error="")

            def get_then_open() -> None:
                exe = loki_godot(install=True)
                if not exe:
                    _GET_GODOT.update(state="failed", note="could not get Godot 4.7.2: %s - try Open in Godot again"
                                      % (_GET_GODOT.get("error") or "no answer"))
                    return
                res = open_native(name, popen, background=False)
                _GET_GODOT.update(state="done", note=res.get("note") or res.get("error") or "")
            if background:
                threading.Thread(target=get_then_open, daemon=True, name="loki-get-godot").start()
            else:
                get_then_open()
        if _GET_GODOT["state"] == "failed":
            return {"ok": False, "error": _GET_GODOT["note"]}
        return {"ok": True, "downloading": True,
                "note": "Getting Godot 4.7.2 (one time, checked) - the project opens by itself when ready."}
    exe = loki_godot() if use_loki else native_godot()
    if not exe:
        return {"ok": False, "error": "Godot is not installed here (or set GODOT_BIN). Get Godot 4 from godotengine.org."}
    note = ""
    try:
        sys.path.insert(0, str(REPO / "studio"))
        import godot_live  # pylint: disable=import-outside-toplevel
        got = godot_live.ensure_plugin(root, sync=True)   # the LOKI plugin + the project's plugins.json
        note = got.get("note", "")
        failed = (got.get("plugins") or {}).get("failed") or []
        if failed:
            note += "; plugins not installed: " + "; ".join(failed)
    except Exception as exc:  # noqa: BLE001 - the editor still opens without the plugin
        note = "the LOKI Studio plugin could not be added (%s)" % exc
    kwargs: dict = {"cwd": str(root), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    try:
        popen([exe, "--editor", "--path", str(root)], **kwargs)
    except OSError as exc:
        return {"ok": False, "error": "could not start Godot: %s" % exc}
    which = "LOKI's Godot 4.7.2" if use_loki else "Godot (%s)" % Path(exe).name
    return {"ok": True, "note": "%s is opening %s with the LOKI plugin. %s" % (which, root.name, note), "godot": exe}


# ------------------------------------------------------------------ HTTP (loki_bridge hands /godot-editor/* here)
def static_file(route: str, data: Path | None = None) -> Path | None:
    rel = route[len("/godot-editor/app/"):]
    if not rel or "/" in rel or "\\" in rel or rel.startswith(".") or Path(rel).suffix.lower() not in ALLOWED_EXT:
        return None
    base = editor_dir(data).resolve()
    target = (base / rel).resolve()
    return target if target.parent == base and target.is_file() else None


def static_headers(path: Path) -> dict:
    h = {"Content-Type": TYPES.get(path.suffix.lower(), "application/octet-stream"), "Cache-Control": "no-cache",
         "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", **ISOLATION}
    if path.suffix.lower() == ".html":
        h["Content-Security-Policy"] = EDITOR_CSP
    return h


def _send(handler: Any, code: int, body: bytes, headers: dict) -> None:
    try:
        handler.send_response(code)
        for k, v in headers.items():
            handler.send_header(k, v)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionError, OSError):
        pass


def _json(handler: Any, code: int, payload: dict) -> None:
    _send(handler, code, json.dumps(payload, default=str).encode("utf-8"),
          {"Content-Type": "application/json", "Cache-Control": "no-store"})


def http(handler: Any, method: str, allowed_hosts, data: Path | None = None, popen=subprocess.Popen) -> None:
    """Serve one /godot-editor/* request on the engine's handler (uses its _authorized / _read_json)."""
    parsed = urlparse(handler.path)
    route = parsed.path
    if handler.headers.get("Host", "") not in allowed_hosts:
        return _json(handler, 403, {"ok": False, "error": "Host not allowed."})
    if method == "GET" and route.startswith("/godot-editor/app/"):
        found = static_file(route, data)
        if found is None:
            return _json(handler, 404, {"ok": False, "error": "not found - install the Godot web editor from the Godot tab"})
        return _send(handler, 200, found.read_bytes(), static_headers(found))
    if not handler._authorized():  # pylint: disable=protected-access
        return None
    q = {k: (v[0] if v else "") for k, v in parse_qs(parsed.query).items()}
    try:
        if method == "GET" and route == "/godot-editor/status":
            return _json(handler, 200, status(data))
        if method == "GET" and route == "/godot-editor/project.zip":
            name = q.get("name", "")
            return _send(handler, 200, project_zip(name), {"Content-Type": "application/zip", "Cache-Control": "no-store",
                                                           "Content-Disposition": 'attachment; filename="%s.zip"' % name})
        if method == "POST":
            body = handler._read_json() if int(handler.headers.get("Content-Length", "0") or 0) > 0 else {}  # pylint: disable=protected-access
            if body is None:
                return None
            if route == "/godot-editor/install":
                if _JOB.get("state") == "downloading":
                    return _json(handler, 200, {"ok": True, "started": False, "note": _JOB["note"]})
                threading.Thread(target=install, args=(data,), daemon=True, name="godot-web-editor").start()
                return _json(handler, 200, {"ok": True, "started": True})
            if route == "/godot-editor/import":
                if body.get("confirm") is not True:
                    return _json(handler, 400, {"ok": False, "error": "bringing files back needs your confirmation"})
                return _json(handler, 200, import_back(str(body.get("name") or "")))
            if route == "/godot-editor/new":
                return _json(handler, 200, new_project(str(body.get("name") or "")))
            if route == "/godot-editor/link":
                return _json(handler, 200, link_project(str(body.get("path") or "")))
            if route == "/godot-editor/native":
                return _json(handler, 200, open_native(str(body.get("name") or ""), popen=popen))
    except KeyError as exc:
        return _json(handler, 404, {"ok": False, "error": str(exc).strip("'\"")})
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        return _json(handler, 400, {"ok": False, "error": str(exc)})
    return _json(handler, 404, {"ok": False, "error": "Unknown endpoint."})
