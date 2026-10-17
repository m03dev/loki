"""Loopback API for the research-round-3 features (docs/integrations/research-2026-10-17b.md). The bridge
only routes here (engine/loki_bridge.py: one GET block, one POST block, one unauthenticated page route).

  chats     POST /convo/cut {id, text, occurrence}            edit / regenerate: cut before that message
            POST /convo/branch {id, role, text, occurrence}   a new chat up to that message
            POST /convo/export {id, format: md|html|json, all} -> {name, text, path} (also saved in exports/)
            POST /convo/import {name, text} | {path}           ChatGPT / Claude / Open WebUI / LibreChat / LOKI / Markdown
  prompts   GET  /prompts[?q=]   POST /prompts/save {name, title, text, tags}   /prompts/delete {name}
            POST /prompts/fill {name | text, values, clipboard} -> {text, missing, variables}
  compare   POST /compare {prompt, models: [..]}  POST /compare/vote {winner, losers, prompt}  GET /compare/board
  previews  POST /artifact {code, kind: html|svg} -> {id, url}   POST /artifact/save {id, name}
            GET  /artifact/<id>  (no token: a sandboxed page with its own CSP - artifacts.py)
  everyday  GET  /everyday?kind=weather|news|time&q=...   POST /everyday {kind: translate, text, to}
  your data GET  /data   GET /data/backups   POST /data/backup {secrets}   POST /data/restore {name, confirm}
            POST /data/clear {kind, confirm}
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import artifacts
import chat_io
import chat_plus
import compare
import everyday
import prompt_library
import your_data

PREFIXES = ("/convo/", "/prompts", "/compare", "/artifact", "/everyday", "/data")


BIG_BODY = {"/convo/import": 150_000_000, "/artifact": 4_000_000}


def read_json(handler: Any) -> dict | None:
    """The JSON body of a big-body route (the bridge's own limit is 32 KB): a chat export or a page."""
    import json  # pylint: disable=import-outside-toplevel
    limit = BIG_BODY.get(urlparse(handler.path).path, 32_000)
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        length = -1
    if length <= 0 or length > limit:
        handler._send_json(413, {"ok": False, "error": "too big (the limit here is %d MB)" % max(1, limit // 1_000_000)})  # noqa: SLF001
        return None
    try:
        value = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        handler._send_json(400, {"ok": False, "error": "Invalid JSON body."})   # noqa: SLF001
        return None
    if not isinstance(value, dict):
        handler._send_json(400, {"ok": False, "error": "JSON body must be an object."})   # noqa: SLF001
        return None
    return value


def handles(route: str) -> bool:
    return route.startswith(PREFIXES) and not route.startswith("/database")


def _data_dir(agent: Any) -> Path:
    return Path(getattr(agent, "DATA_DIR", None) or os.getenv("LOKI_DATA") or "harness_data")


def _workspace(agent: Any) -> Path:
    return Path(getattr(agent, "WORKSPACE", None) or os.getenv("LOKI_WORKSPACE") or ".")


def library(agent: Any) -> prompt_library.Library:
    return prompt_library.Library(_data_dir(agent) / "prompts.json")


def arena(agent: Any) -> compare.Arena:
    return compare.Arena(_data_dir(agent) / "arena.json")


def store(agent: Any) -> artifacts.Store:
    return artifacts.Store(_data_dir(agent) / "artifacts")


def _run(state: Any, coro, timeout: float):
    if getattr(state, "loop", None) is None:
        coro.close()
        raise RuntimeError("the agent is not ready yet")
    return asyncio.run_coroutine_threadsafe(coro, state.loop).result(timeout=timeout)


def _busy(state: Any, fn):
    locks = state.try_busy() if hasattr(state, "try_busy") else []
    if locks is None:
        return 409, {"ok": False, "error": "LOKI is answering; try again when it is done."}
    try:
        out = fn()
    finally:
        if locks:
            state.release_busy(locks)
    return (200 if out.get("ok") else 400), out


def _in_workspace(agent: Any, rel: str) -> Path:
    ws = _workspace(agent).resolve()
    path = (ws / str(rel or "")).resolve()
    if path != ws and ws not in path.parents:
        raise ValueError("the file must be inside the workspace")
    return path


def _is_local(agent: Any):
    def check(provider: str) -> bool:
        cfg = getattr(agent, "MODELS", {}).get(provider)
        base = str(getattr(cfg, "base_url", "") or "")
        return bool(re.search(r"localhost|127\.0\.0\.1|\[::1\]|:11434|^cli-agent://", base)) or provider.startswith("local")
    return check


def _clear_chats(agent: Any):
    def run():
        for cid in [c["id"] for c in agent.list_conversations()]:
            agent.delete_conversation(cid)
    return run


def serve_artifact(handler: Any, route: str, allowed_hosts) -> None:
    """GET /artifact/<id>: the page with artifacts.CSP (sandboxed, no network). No token - the frame
    cannot send one - but only for LOKI's own host names (like the UI)."""
    if handler.headers.get("Host", "") not in allowed_hosts:
        handler._send_json(403, {"ok": False, "error": "Host not allowed."})   # noqa: SLF001
        return
    aid = route.rsplit("/", 1)[-1]
    origin = "http://" + handler.headers.get("Host", "")
    body = store(handler.server.state.agent).get(aid)
    if body is None:
        handler._send_json(404, {"ok": False, "error": "That preview is gone; open it again from the chat."})  # noqa: SLF001
        return
    try:
        body = artifacts.page(body, origin)
        handler.send_response(200)
        for k, v in artifacts.headers(origin):
            handler.send_header(k, v)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionError, OSError):
        pass


def route(state: Any, method: str, path: str, data: dict) -> tuple:
    try:
        return _route(state, method, path, data or {})
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - one broken card must never break the window
        return 500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


def _route(state: Any, method: str, path: str, data: dict) -> tuple:
    agent = state.agent
    url = urlparse(path)
    r = url.path
    q = {k: v[-1] for k, v in parse_qs(url.query).items()}
    # ------------------------------------------------------------------ chats
    if r == "/convo/cut" and method == "POST":
        return _busy(state, lambda: chat_plus.cut_before(agent, str(data.get("id", "")), str(data.get("text", "")),
                                                         int(data.get("occurrence") or 0)))
    if r == "/convo/branch" and method == "POST":
        def go():
            out = chat_plus.branch(agent, str(data.get("id", "")), str(data.get("role", "assistant")),
                                   str(data.get("text", "")), int(data.get("occurrence") or 0))
            if out.get("ok"):
                out["conversations"] = agent.list_conversations()
                out["active"] = out["id"]
            return out
        return _busy(state, go)
    if r == "/convo/export" and method == "POST":
        out = chat_plus.export(agent, str(data.get("id", "")), str(data.get("format", "md")), bool(data.get("all")))
        if out.get("ok") and data.get("save", True):
            folder = _workspace(agent) / "exports"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / out["name"]).write_text(out["text"], encoding="utf-8")
            out["path"] = "exports/" + out["name"]
        return (200 if out.get("ok") else 404), out
    if r == "/convo/import" and method == "POST":
        text, name = str(data.get("text", "")), str(data.get("name", ""))
        if not text and data.get("path"):
            p = _in_workspace(agent, str(data["path"]))
            if not p.is_file():
                return 404, {"ok": False, "error": "no file %s in the workspace" % data["path"]}
            if p.stat().st_size > 200_000_000:
                return 400, {"ok": False, "error": "that file is over 200 MB"}
            text, name = p.read_text(encoding="utf-8", errors="replace"), p.name
        if len(text) > 200_000_000:
            return 400, {"ok": False, "error": "that file is over 200 MB"}
        parsed = chat_io.parse(text, name)
        if not parsed.get("ok"):
            return 400, parsed

        def add():
            ids = chat_plus.add_chats(agent, parsed["chats"])
            return {"ok": True, "source": parsed["source"], "imported": len(ids), "skipped": parsed.get("skipped", 0),
                    "conversations": agent.list_conversations()}
        return _busy(state, add)
    # ------------------------------------------------------------------ prompts
    lib = library(agent)
    if r == "/prompts" and method == "GET":
        return 200, {"ok": True, "prompts": lib.search(q.get("q", ""), 200) if q.get("q") else lib.all()}
    if r == "/prompts/save" and method == "POST":
        out = lib.save(str(data.get("name", "")), str(data.get("text", "")), str(data.get("title", "")), data.get("tags"))
        return (200 if out.get("ok") else 400), out
    if r == "/prompts/delete" and method == "POST":
        out = lib.delete(str(data.get("name", "")))
        return (200 if out.get("ok") else 404), out
    if r == "/prompts/fill" and method == "POST":
        text = str(data.get("text", ""))
        if data.get("name"):
            p = lib.get(str(data["name"]))
            if p is None:
                return 404, {"ok": False, "error": "no prompt called %s - /prompts lists them" % data["name"]}
            text = p["text"]
            lib.used(p["name"])
        out = prompt_library.fill(text, data.get("values") or {}, clipboard=str(data.get("clipboard", ""))[:20000])
        out["variables"] = prompt_library.variables(text)
        out["ok"] = True
        return 200, out
    # ------------------------------------------------------------------ compare
    if r == "/compare" and method == "POST":
        models = [m for m in (data.get("models") or []) if m in getattr(agent, "MODELS", {}) and m not in ("smart", "online")]
        ask = getattr(agent, "_r3_model_ask", None)
        if ask is None:
            return 500, {"ok": False, "error": "this engine cannot compare models"}
        out = _run(state, compare.run(str(data.get("prompt", "")), models, ask,
                                      float(os.getenv("LOKI_COMPARE_TIMEOUT", "120"))), 400)
        return (200 if out.get("ok") else 400), out
    if r == "/compare/vote" and method == "POST":
        out = arena(agent).vote(str(data.get("winner", "")), list(data.get("losers") or []), str(data.get("prompt", "")))
        return (200 if out.get("ok") else 400), out
    if r == "/compare/board":
        return 200, {"ok": True, "board": arena(agent).board()}
    # ------------------------------------------------------------------ previews
    if r == "/artifact" and method == "POST":
        out = store(agent).put(str(data.get("code", "")), str(data.get("kind", "html")))
        return (200 if out.get("ok") else 400), out
    if r == "/artifact/save" and method == "POST":
        out = store(agent).save(str(data.get("id", "")), _workspace(agent), str(data.get("name", "")))
        return (200 if out.get("ok") else 404), out
    # ------------------------------------------------------------------ everyday
    if r == "/everyday":
        kind = str((data if method == "POST" else q).get("kind", "")).lower()
        arg = str((data if method == "POST" else q).get("q", "") or "")
        if kind == "weather":
            text = everyday.weather(arg, int(q.get("days", data.get("days", 3)) or 3))
        elif kind == "news":
            text = everyday.news(arg)
        elif kind in ("time", "clock"):
            text = everyday.clock(arg)
        elif kind == "translate":
            ask = getattr(agent, "_port_ask", None)
            text = _run(state, everyday.translate(str(data.get("text", arg)), str(data.get("to", "")), ask), 180)
        else:
            return 400, {"ok": False, "error": "kind must be weather, news, time or translate"}
        return (400 if text.startswith("error:") else 200), {"ok": not text.startswith("error:"), "text": text}
    # ------------------------------------------------------------------ your data
    if r == "/data" and method == "GET":
        entries = []
        try:
            entries = agent.USAGE.entries(since=0)
        except Exception:  # noqa: BLE001 - no ledger yet
            entries = []
        inv = your_data.inventory(_data_dir(agent), _workspace(agent), entries, _is_local(agent),
                                  len(agent.list_conversations()) if hasattr(agent, "list_conversations") else 0)
        inv.update(ok=True, backups=your_data.list_backups(), backup_dir=str(your_data.backup_dir()),
                   clearable=your_data.CLEARABLE)
        return 200, inv
    if r == "/data/backups":
        return 200, {"ok": True, "backups": your_data.list_backups(), "backup_dir": str(your_data.backup_dir())}
    if r == "/data/backup" and method == "POST":
        version = ""
        try:
            import updater  # pylint: disable=import-outside-toplevel
            version = updater.version(Path(__file__).resolve().parent.parent).get("label", "")
        except Exception:  # noqa: BLE001
            pass
        try:
            agent.save_history()
        except Exception:  # noqa: BLE001
            pass
        return 200, your_data.backup(_data_dir(agent), _workspace(agent), include_secrets=bool(data.get("secrets")),
                                     version=version)
    if r == "/data/restore" and method == "POST":
        if not data.get("confirm"):
            return 400, {"ok": False, "error": "restoring replaces LOKI's data with the backup's - confirm first"}
        name = Path(str(data.get("name", ""))).name
        if not re.match(r"^loki-backup-[\w.-]+\.zip$", name):
            return 400, {"ok": False, "error": "pick one of the backups in the list"}
        return _busy(state, lambda: your_data.restore(your_data.backup_dir() / name, _data_dir(agent), _workspace(agent)))
    if r == "/data/clear" and method == "POST":
        if not data.get("confirm"):
            return 400, {"ok": False, "error": "clearing deletes it for good - confirm first"}
        usage = getattr(agent, "USAGE", None)
        return _busy(state, lambda: your_data.clear(str(data.get("kind", "")), _data_dir(agent), _clear_chats(agent),
                                                    usage.reset if usage is not None else None))
    return 404, {"ok": False, "error": "Unknown endpoint."}
