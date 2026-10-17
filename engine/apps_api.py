"""The window's API for LOKI Apps, modes and extensions (engine/loki_bridge.py routes here).

    GET  /apps/list                       installed apps + the gallery + extension apps
    POST /apps/install {template, name?}  /apps/remove {name}  /apps/sync
    POST /apps/storage {app, op, key?, value?}       a mini-app's own store (apps.storage)
    POST /apps/ask {app, prompt, data?}              "ask LOKI" from inside an app (loki.app_ask)
    POST /apps/files/save {app, name, content, encoding?}   after the owner approved it in the window
    POST /apps/files/list {app}  /apps/files/read {app, name}
    GET  /personas    POST /personas/active {id}  /personas/save {mode}  /personas/delete {id}
                      /personas/import {text}  /personas/export {id}
    GET  /extensions  POST /extensions/scan {source}  /extensions/install {token}
                      /extensions/toggle {id, on}  /extensions/trust {id, on}  /extensions/remove {id}

The app key in a request is the one the WINDOW knows for the frame it opened (apps.js never takes it from
the app's own message), so one app cannot read another's store. Every route needs the bridge token.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import apps
import extensions
import personas

MAX_BODY = 6_000_000
PREFIXES = ("/apps/", "/personas", "/extensions")


def owns(route: str) -> bool:
    return route.startswith(PREFIXES) and not is_file_route(route)


def is_file_route(route: str) -> bool:
    return route.startswith(("/apps/w/", "/apps/t/", "/apps/x/", "/apps/p/"))


def _ws(agent: Any) -> Path:
    return Path(getattr(agent, "WORKSPACE", "."))


def _data(agent: Any) -> Path | None:
    root = getattr(agent, "DATA_DIR", None)
    return Path(root) if root else None


def _reserved(agent: Any) -> set:
    reg = getattr(agent, "EXTENSIONS", None)
    return reg.builtin() if reg is not None else set(getattr(agent, "LOCAL_TOOLS", {}) or {})


def _resync(agent: Any) -> None:
    reg = getattr(agent, "EXTENSIONS", None)
    if reg is not None:
        try:
            reg.sync()
        except Exception:  # noqa: BLE001
            pass


def _app_listing(agent: Any) -> dict:
    ext_apps = []
    for item in extensions.listing(_data(agent)):
        if item["enabled"] and item["app"]:
            ext_apps.append({"key": "x:" + item["id"], "name": item["id"], "kind": "x", "title": item["name"],
                             "description": item["description"], "icon": "🧩", "url": item["app_url"], "by": "extension"})
    return {"apps": apps.list_apps(_ws(agent)) + ext_apps, "templates": apps.list_templates(),
            "workspace": str(_ws(agent)), "sync": apps.LAST_SYNC}


def _ask(state: Any, data: dict) -> tuple:
    agent = state.agent
    fn = getattr(agent, "app_ask", None)
    if fn is None or getattr(state, "loop", None) is None:
        return 503, {"ok": False, "error": "LOKI is still starting"}
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        return 400, {"ok": False, "error": "ask needs a question"}
    future = asyncio.run_coroutine_threadsafe(fn(str(data.get("app") or ""), prompt[:8000], data.get("data")), state.loop)
    try:
        answer = future.result(timeout=240)
    except Exception as exc:  # noqa: BLE001 - no model, timeout...: the app shows it
        future.cancel()
        return 200, {"ok": False, "error": "LOKI could not answer: %s" % (str(exc)[:300] or type(exc).__name__)}
    return 200, {"ok": True, "answer": answer}


def handle(state: Any, method: str, path: str, data: dict) -> tuple:
    agent = state.agent
    route = urlparse(path).path
    ws, root = _ws(agent), _data(agent)
    apps.ensure_sync_thread(agent)
    data = data if isinstance(data, dict) else {}
    try:
        # ---------------------------------------------------------------- apps
        if route == "/apps/list":
            return 200, {"ok": True, **_app_listing(agent)}
        if method != "POST" and route.startswith("/apps/"):
            return 405, {"ok": False, "error": "POST only"}
        if route == "/apps/install":
            out = apps.install_template(ws, str(data.get("template") or ""), str(data.get("name") or ""))
            return (200 if out.get("ok") else 400), out
        if route == "/apps/remove":
            out = apps.remove_app(ws, str(data.get("name") or ""), root, keep_data=not data.get("forget_data"))
            return (200 if out.get("ok") else 400), out
        if route == "/apps/sync":
            return 200, {"ok": True, "results": apps.sync_all(ws, root)}
        if route == "/apps/storage":
            out = apps.storage(str(data.get("app") or ""), str(data.get("op") or ""), str(data.get("key") or ""),
                               data.get("value"), root)
            return (200 if out.get("ok") else 400), out
        if route == "/apps/ask":
            return _ask(state, data)
        if route == "/apps/files/save":
            out = apps.save_file(ws, str(data.get("app") or ""), str(data.get("name") or ""),
                                 str(data.get("content") or ""), str(data.get("encoding") or "text"))
            return (200 if out.get("ok") else 400), out
        if route == "/apps/files/list":
            return 200, apps.list_files(ws, str(data.get("app") or ""))
        if route == "/apps/files/read":
            out = apps.read_file(ws, str(data.get("app") or ""), str(data.get("name") or ""))
            return (200 if out.get("ok") else 404), out
        # ---------------------------------------------------------------- modes
        if route == "/personas":
            return 200, {"ok": True, "modes": personas.list_modes(root), "active": personas.active_id(root)}
        if method != "POST":
            return 405, {"ok": False, "error": "POST only"}
        if route == "/personas/active":
            out = personas.set_active(str(data.get("id") or ""), root)
            apply = getattr(agent, "apply_persona", None)
            if out.get("ok") and apply is not None:
                apply()
            return (200 if out.get("ok") else 400), out
        if route == "/personas/save":
            out = personas.save(data.get("mode") or {}, root)
            return (200 if out.get("ok") else 400), out
        if route == "/personas/delete":
            out = personas.delete(str(data.get("id") or ""), root)
            return (200 if out.get("ok") else 400), out
        if route == "/personas/import":
            out = personas.import_text(str(data.get("text") or ""), root)
            return (200 if out.get("ok") else 400), out
        if route == "/personas/export":
            out = personas.export(str(data.get("id") or ""), root)
            if out.get("ok"):   # also as a file in the workspace, ready to send to someone
                try:
                    folder = ws / "LOKI modes"
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / out["filename"]).write_text(out["text"], encoding="utf-8")
                    out["path"] = str(folder / out["filename"])
                except OSError:
                    pass
            return (200 if out.get("ok") else 404), out
        # ---------------------------------------------------------------- extensions
        if route == "/extensions/scan":
            out = extensions.stage(str(data.get("source") or ""), root, _reserved(agent))
            return (200 if out.get("ok") else 400), out
        if route == "/extensions/install":
            out = extensions.install(str(data.get("token") or ""), root, _reserved(agent))
            _resync(agent)
            return (200 if out.get("ok") else 400), out
        if route in ("/extensions/toggle", "/extensions/trust"):
            out = extensions.set_flag(str(data.get("id") or ""), "enabled" if route.endswith("toggle") else "trusted",
                                      bool(data.get("on")), root)
            _resync(agent)
            return (200 if out.get("ok") else 400), out
        if route == "/extensions/remove":
            out = extensions.remove(str(data.get("id") or ""), root)
            _resync(agent)
            return (200 if out.get("ok") else 400), out
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "unknown endpoint"}


def handle_get(state: Any, path: str) -> tuple:
    route = urlparse(path).path
    if route == "/extensions":
        return 200, {"ok": True, "extensions": extensions.listing(_data(state.agent)),
                     "format": extensions.FORMAT}
    return handle(state, "GET", path, {})
