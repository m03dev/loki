"""The live Godot link: LOKI's agents work INSIDE the real Godot editor, on LOKI World (or any project).

Owner, 2026-10-18: "i want the loki world to be an editable project in godot - godot and loki world should be the same
thing ... the agents should be able to roam around in a live project state, change everything ... the web godot is of no
help to us, we want the godot and the assetstore and all the plugins". So:

* LOKI World IS game/loki-world, opened in the owner's real Godot editor (Asset Library, every plugin). The LOKI Studio
  plugin (studio/godot_plugin/addons/loki_studio) is installed into it and enabled by LOKI when it opens the project.
* The plugin links to TWO hubs: LOKI Studio (its own app, as before) and - new - LOKI's engine, through this module.
  The engine writes ~/.loki/engine_connect.json (url + token, mode 600) when it starts; the plugin reads it.
  Routes, the same the plugin already speaks to Studio: POST /api/godot/hello | result | event, GET /api/godot/poll,
  GET /api/godot/editors, POST /api/godot/call {action, args, project?}.
* Every LOKI agent - the chat, background jobs, teams, improve_loki - gets the tool godot_editor(action, args): the
  plugin's actions (studio/studio_godot.ACTIONS: scene tree, node info, set_property, add/remove nodes, scripts, save,
  run/stop the game, screenshots, input to the running game, its live tree) plus install_plugin. A job runs in its own
  process, so the tool calls the engine over loopback; in the engine it calls the hub directly. Every scene change goes
  through the editor's UndoRedo (Ctrl+Z), and Ask/Plan mode only gets the read actions.
* Agents roam while they work: each editor action an agent makes is remembered for ACTIVE_S; LOKI World's /world puts
  that agent at the "godot forge" station with what it is doing as its words (engine/events.world). The running game
  (played from the editor) gets the edits live: the plugin turns on Debug > Synchronize Scene Changes and Synchronize
  Script Changes.
* Plugins from the Asset Library: install_plugin {asset_id} downloads the asset's pinned archive (GitHub, its exact
  commit), copies only its addons/<name>/ into the project and records it in <project>/plugins.json - which IS
  committed for LOKI World, while addons/ stays untracked (AGENTS.md) - so every machine installs the same plugins
  (sync_plugins, run when LOKI opens the project).
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "studio"))
import studio_godot  # noqa: E402  (the hub and the action list are Studio's: one implementation)

WORLD = REPO / "game" / "loki-world"
ASSET_API = "https://godotengine.org/asset-library/api/asset/"
ACTIVE_S = 90.0                     # an agent shows at the Godot station this long after its last editor action
MAX_PLUGIN_ZIP = 80 * 1024 * 1024
READ_ACTIONS = {name for name, (_what, writes) in studio_godot.ACTIONS.items() if not writes} - {"quit", "run_game",
                                                                                                    "game_input"}
EXTRA_ACTIONS = {"install_plugin": "install a plugin from the Godot Asset Library into the project: args.asset_id "
                                   "(the number in its Asset Library page); recorded in plugins.json for every machine",
                 "plugins": "the plugins of the project (installed, enabled, from plugins.json)"}

_HUB: studio_godot.GodotHub | None = None
_LOCK = threading.Lock()
ACTIVITY: dict = {}                 # actor -> {"action", "detail", "t", "project"}
IN_ENGINE = {"on": False}           # the engine process sets this: the hub is here, not across loopback


def hub() -> studio_godot.GodotHub:
    global _HUB
    with _LOCK:
        if _HUB is None:
            _HUB = studio_godot.GodotHub(shots=_data() / "godot" / "shots")
        return _HUB


def _data() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else REPO / "harness_data"


def connect_path() -> Path:
    explicit = os.getenv("LOKI_ENGINE_CONNECT", "").strip()
    if explicit:
        return Path(explicit)
    home = os.getenv("USERPROFILE") if sys.platform == "win32" else os.getenv("HOME")
    return Path(home or str(Path.home())) / ".loki" / "engine_connect.json"


def write_connect(port: int, token: str) -> Path:
    """Tell a Godot editor on this computer where LOKI's engine is (the plugin's second link)."""
    IN_ENGINE["on"] = True
    return studio_godot.write_connect(connect_path(), "http://127.0.0.1:%d" % int(port), token)


# ------------------------------------------------------------------ who is doing what (LOKI World shows it)
def actor() -> str:
    """The agent making this call: a background job, a team role, or LOKI (the chat)."""
    job = os.getenv("LOKI_JOB_ID", "").strip()
    return ("job-" + job) if job else "loki"


def note_activity(who: str, action: str, args: dict, project: str = "", now: float | None = None) -> None:
    detail = action.replace("_", " ")
    a = args or {}
    for key in ("node", "path", "scene", "parent", "script", "asset_id"):
        if a.get(key):
            detail += " " + str(a[key])[:60]
            break
    if action == "set_property" and a.get("property"):
        detail += ".%s = %s" % (a["property"], str(a.get("value", ""))[:30])
    ACTIVITY[str(who)] = {"action": action, "detail": detail, "t": time.time() if now is None else now,
                          "project": project}


def active(now: float | None = None) -> dict:
    """actor -> what it does in Godot right now (the last ACTIVE_S seconds)."""
    t = time.time() if now is None else now
    return {k: v for k, v in list(ACTIVITY.items()) if t - float(v.get("t", 0)) < ACTIVE_S}


def apply_to_world(agents: list, now: float | None = None) -> list:
    """engine/events.world: an agent working in the editor stands at the Godot forge and says what it is doing."""
    act = active(now)
    for a in agents:
        hit = act.get(str(a.get("id", "")))
        if hit:
            a["station"] = "godot forge"
            a["state"] = "working"
            a["last_message"] = "Godot: " + hit["detail"]
            a["godot"] = hit
    return agents


# ------------------------------------------------------------------ the agents' tool
def _engine_call(body: dict, timeout: float) -> dict:
    """From a job process: the engine's hub over loopback (the engine token, as engine/loki_mcp.py)."""
    data = _data()
    token_file = Path(os.getenv("LOKI_BRIDGE_TOKEN_FILE", "") or (data / "app" / "engine.token"))
    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return {"ok": False, "error": "LOKI's engine is not running (no %s)" % token_file}
    url = (os.getenv("LOKI_BRIDGE_URL", "") or "http://127.0.0.1:%s" % (os.getenv("LOKI_APP_PORT", "") or "8767")).rstrip("/")
    req = urllib.request.Request(url + "/api/godot/call", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout + 10) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8") or "{}")
        except ValueError:
            return {"ok": False, "error": "HTTP %s" % exc.code}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "error": "LOKI's engine did not answer (%s)" % getattr(exc, "reason", exc)}


def call(action: str, args: dict | None = None, project: str = "", who: str = "", timeout: float = 30.0) -> dict:
    """One editor action through the engine's hub; remembers who did it (LOKI World shows them working)."""
    action = str(action or "").strip()
    args = dict(args or {})
    if action in EXTRA_ACTIONS:
        return extra(action, args, project)
    if action not in studio_godot.ACTIONS or action == "quit":
        return {"ok": False, "error": "unknown editor action %r - one of: %s" % (
            action, ", ".join(sorted(set(studio_godot.ACTIONS) - {"quit"} | set(EXTRA_ACTIONS))))}
    if not IN_ENGINE["on"]:
        return _engine_call({"action": action, "args": args, "project": project, "who": who or actor(),
                             "timeout": timeout}, timeout)
    try:
        res = hub().call(action, args, project=project, timeout=timeout)
    except studio_godot.GodotError as exc:
        return {"ok": False, "error": str(exc) + " (LOKI World: open it from LOKI's Godot tab - \"Open LOKI World in Godot\")"}
    if res.get("ok"):
        note_activity(who or actor(), action, args, project)
    return res


def godot_editor(action: str, args: Any = None, project: str = "") -> str:
    """The tool: one action in the live Godot editor (see EDITOR_TOOL_DOC)."""
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except ValueError:
            return "args must be a JSON object, e.g. {\"node\": \"Player\", \"property\": \"speed\", \"value\": \"6\"}"
    mode = ""
    try:
        import loki  # pylint: disable=import-outside-toplevel
        mode = str(getattr(loki, "AGENT_MODE", ""))
    except Exception:  # noqa: BLE001
        pass
    if mode in ("ask", "plan") and action not in READ_ACTIONS and action != "plugins":
        return "refused: %s changes the project, and %s mode only looks (switch to Build)" % (action, mode)
    res = call(action, args if isinstance(args, dict) else {}, project)
    text = json.dumps(res, default=str)
    return text[:12000] + ("... (cut)" if len(text) > 12000 else "")


def tool_doc() -> str:
    acts = "; ".join("%s: %s" % (k, v[0]) for k, v in sorted(studio_godot.ACTIONS.items()) if k != "quit")
    acts += "; " + "; ".join("%s: %s" % kv for kv in EXTRA_ACTIONS.items())
    return ("Work in the LIVE Godot editor (the owner's real Godot with LOKI World or another project open, linked by "
            "the LOKI Studio plugin): see and change the open scene, nodes, scripts, run the game and see it, install "
            "Asset Library plugins. Changes are undoable in the editor (Ctrl+Z) and show live in the running game. "
            "Use editor_state first. Values are Godot text like Vector3(0, 1, 0). Actions: " + acts)


# ------------------------------------------------------------------ plugins from the Asset Library
def manifest_path(project: Path) -> Path:
    return Path(project) / "plugins.json"


def read_manifest(project: Path) -> list:
    try:
        data = json.loads(manifest_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in (data.get("plugins") if isinstance(data, dict) else data) or [] if isinstance(p, dict)]


def write_manifest(project: Path, plugins: list) -> None:
    body = {"about": "Godot plugins this project uses, from the Asset Library at an exact commit. LOKI installs "
                     "them into addons/ on every machine (engine/godot_live.py sync_plugins); addons/ is not committed.",
            "plugins": sorted(plugins, key=lambda p: str(p.get("name", "")).lower())}
    manifest_path(project).write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")


def asset_info(asset_id: str, opener=None) -> dict:
    opener = opener or urllib.request.urlopen
    aid = re.sub(r"\D", "", str(asset_id))
    if not aid:
        raise ValueError("asset_id is the number of the asset (godotengine.org/asset-library/asset/<number>)")
    with opener(urllib.request.Request(ASSET_API + aid, headers={"User-Agent": "LOKI"}), timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def install_asset(project: Path, info: dict, opener=None) -> dict:
    """Copy the asset's addons/<name>/ folders (only those) into project/addons. Returns {names, files}."""
    opener = opener or urllib.request.urlopen
    url = str(info.get("download_url") or "")
    if not url.startswith("https://"):
        raise ValueError("the asset has no https download")
    with opener(urllib.request.Request(url, headers={"User-Agent": "LOKI"}), timeout=180) as resp:
        blob = resp.read(MAX_PLUGIN_ZIP + 1)
    if len(blob) > MAX_PLUGIN_ZIP:
        raise ValueError("the asset is bigger than %d MB" % (MAX_PLUGIN_ZIP // 1024 // 1024))
    want = str(info.get("download_hash") or "").strip().lower()
    if want:
        import hashlib  # pylint: disable=import-outside-toplevel
        if hashlib.sha256(blob).hexdigest() != want:
            raise ValueError("the download does not match the Asset Library's hash - nothing was installed")
    names, files = set(), 0
    root = (Path(project) / "addons").resolve()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for member in z.infolist():
            parts = member.filename.replace("\\", "/").split("/")
            if "addons" not in parts:
                continue
            rel = parts[parts.index("addons") + 1:]
            if len(rel) < 2 or not rel[0] or rel[0] == "loki_studio" or any(p in ("..", "") for p in rel[:-1]):
                continue
            dest = (root / Path(*rel)).resolve()
            if not str(dest).startswith(str(root)):
                continue
            if member.is_dir() or member.filename.endswith("/"):
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(member))
            names.add(rel[0])
            files += 1
    if not names:
        raise ValueError("the asset has no addons/ folder - it is not an editor plugin")
    return {"names": sorted(names), "files": files}


def install_plugin(project: Path, asset_id: str, opener=None) -> dict:
    info = asset_info(asset_id, opener)
    got = install_asset(project, info, opener)
    entry = {"name": str(info.get("title", "")), "asset_id": str(info.get("asset_id", asset_id)),
             "version": str(info.get("version_string", "")), "commit": str(info.get("download_commit", "")),
             "download_url": str(info.get("download_url", "")), "license": str(info.get("cost", "")),
             "addons": got["names"]}
    plugins = [p for p in read_manifest(project) if str(p.get("asset_id")) != entry["asset_id"]] + [entry]
    write_manifest(project, plugins)
    return {"ok": True, "installed": entry, "files": got["files"],
            "next": "enable it: godot_editor(action='rescan') then Project Settings > Plugins (the plugins it adds: %s)"
                    % ", ".join("res://addons/%s/plugin.cfg" % n for n in got["names"])}


def sync_plugins(project: Path, opener=None) -> dict:
    """Install every plugin in plugins.json that is missing from addons/ (the same commit as recorded)."""
    done, failed = [], []
    for p in read_manifest(project):
        if all((Path(project) / "addons" / n).is_dir() for n in p.get("addons") or []) and p.get("addons"):
            continue
        try:
            install_asset(project, {"download_url": p.get("download_url"), "download_hash": p.get("download_hash", "")}, opener)
            done.append(p.get("name"))
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            failed.append("%s: %s" % (p.get("name"), exc))
    return {"ok": not failed, "installed": done, "failed": failed}


def plugins(project: Path) -> dict:
    addons = Path(project) / "addons"
    found = sorted(p.parent.name for p in addons.glob("*/plugin.cfg")) if addons.is_dir() else []
    return {"ok": True, "installed": found, "manifest": read_manifest(project)}


def _project_for(project: str) -> Path:
    if project:
        return Path(project)
    live = hub().connected() if IN_ENGINE["on"] else []
    return Path(live[0]["project"]) if live else WORLD


def extra(action: str, args: dict, project: str = "") -> dict:
    root = _project_for(project)
    try:
        if action == "plugins":
            return plugins(root)
        if action == "install_plugin":
            res = install_plugin(root, str(args.get("asset_id", "")))
            note_activity(actor(), action, args, str(root))
            try:
                hub().call("rescan", {}, project=str(root), timeout=10) if IN_ENGINE["on"] else None
            except studio_godot.GodotError:
                pass
            return res
    except (OSError, ValueError, zipfile.BadZipFile, urllib.error.URLError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "unknown action"}


# ------------------------------------------------------------------ LOKI World, always ready to open in Godot
def _tree_digest(folder: Path) -> str:
    import hashlib  # pylint: disable=import-outside-toplevel
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.suffix not in (".uid", ".import"):
            h.update(p.relative_to(folder).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def ensure_world(project: Path = WORLD, sync: bool = False, opener=None) -> dict:
    """LOKI World has this LOKI's plugin (copied only when it differs: an open editor is not disturbed for nothing)
    and, with sync, every plugin in its plugins.json. project.godot already enables both (committed)."""
    import install_godot_plugin  # pylint: disable=import-outside-toplevel
    project = Path(project)
    target = project / "addons" / "loki_studio"
    note = "the LOKI plugin is up to date"
    if not target.is_dir() or _tree_digest(target) != _tree_digest(install_godot_plugin.SOURCE):
        res = install_godot_plugin.install(project)
        if not res.get("ok"):
            return res
        note = "installed the LOKI plugin"
    out = {"ok": True, "note": note}
    if sync:
        out["plugins"] = sync_plugins(project, opener)
    return out


# ------------------------------------------------------------------ HTTP (engine/loki_bridge.py hands /api/godot/* here)
def route(method: str, path: str, data: dict, query: dict) -> tuple | None:
    if not path.startswith("/api/godot/"):
        return None
    h = hub()
    try:
        if method == "GET" and path == "/api/godot/poll":
            return 200, {"ok": True, "commands": h.poll(query.get("editor", ""), float(query.get("wait") or 20))}
        if method == "GET" and path == "/api/godot/editors":
            return 200, {"ok": True, "editors": h.connected(), "activity": active(),
                         "actions": sorted(set(studio_godot.ACTIONS) - {"quit"} | set(EXTRA_ACTIONS))}
        if method == "POST" and path == "/api/godot/hello":
            got = h.hello(data)
            print("[loki-bridge] Godot %s linked: %s (plugin %s)" % (data.get("godot_version", "?"), data.get("project_path", "?"),
                                                                    data.get("plugin_version", "?")), flush=True)
            return 200, {"ok": True, **got}
        if method == "POST" and path == "/api/godot/result":
            h.result(data.get("editor"), data)
            return 200, {"ok": True}
        if method == "POST" and path == "/api/godot/event":
            h.event(data.get("editor"), str(data.get("kind") or ""), data.get("data"))
            return 200, {"ok": True}
        if method == "POST" and path == "/api/godot/call":
            res = call(str(data.get("action") or ""), dict(data.get("args") or {}), str(data.get("project") or ""),
                       who=str(data.get("who") or "loki"), timeout=float(data.get("timeout") or 30))
            return 200, res
    except KeyError as exc:
        return 404, {"ok": False, "error": str(exc).strip("'\"")}
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}
