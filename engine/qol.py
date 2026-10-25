"""Quality of life in the chat (session 29): LOKI's own versions of the comfort features in Ziva's
public patch notes (ziva.sh/changelog, ziva.sh/docs - list and sources in docs/integrations/ZIVA_QOL.md).
Clean-room: written from what those notes SAY the features do; no Ziva code or files were used.

The engine side of app/ui/qol.js:

  recovery   classify(error) -> what went wrong in plain words + the choices that fit (retry, wait and
             retry with a countdown, another model, a model on this computer, summarize and retry, fix
             the key, new chat, what happened); alternatives(agent) = the models ready right now.
  interrupted a chat turn in flight is written to <data>/qol/inflight.json and removed when it ends,
             so a turn cut off by a crash, a quit or an update is offered again on the next start.
  steering   a message typed with Ctrl/Cmd+Enter while LOKI works is read at its next step (the agent
             loop's _trim_context is wrapped; nothing in loki.py changes); unread ones come back.
  approvals  "Allow for this session": the SAME action (tool + exact details) is not asked again
             until the engine restarts. Never for policy.ALWAYS_ASK, connector writes or extensions.
  context    how full the chat is against the condenser's limit; "Summarize now" condenses it.
  search     every chat's title and messages; pinned chats; desktop notifications; what happened.

The bridge routes /qol/* here (one GET block, one POST block) and calls install() once at start.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

STARTED = time.time()
_LOCK = threading.Lock()
STEERS: list = []                 # [{id, text, t}] waiting for the agent's next step
SESSION_RULES: dict = {}          # key -> {tool, preview, t}: actions allowed for this engine session
_STEER_SEQ = [0]
NEVER_SESSION_EXTRA = {"extension_tool", "ship", "push", "payment", "purchase"}


# ------------------------------------------------------------------ storage
def data_dir(agent: Any = None) -> Path:
    base = getattr(agent, "DATA_DIR", "") or os.environ.get("LOKI_DATA", "") or "."
    path = Path(base) / "qol"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, value: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------ recovery: what went wrong, what you can do
ACTION_TEXT = {
    "retry": "Try again",
    "wait": "Wait, then try again",
    "switch": "Use another model",
    "local": "Use a model on this computer",
    "smart": "Let LOKI pick a model that works",
    "compact": "Summarize the chat and try again",
    "new_chat": "Start a new chat",
    "connections": "Fix the key (Connections)",
    "models": "Local models",
    "details": "What happened?",
    "draft": "Put my message back in the box",
}

_RULES = (   # (kind, pattern) - first match wins
    ("busy", r"already handling a request|loki is busy"),
    ("context", r"context[_ ]length|context window|maximum context|too many tokens|prompt is too long|"
                r"reduce the length|input is too long|exceeds the model|request too large|413"),
    ("quota", r"quota|insufficient[_ ]?(funds|credit|balance)|out of credit|credit balance|billing|"
              r"payment required|\b402\b|exhausted|spend(ing)? (cap|limit)|daily limit|monthly limit|plan limit"),
    ("rate_limit", r"rate.?limit|too many requests|\b429\b|slow down|requests per minute|tpm|rpm limit"),
    ("auth", r"\b401\b|\b403\b|unauthori[sz]ed|invalid (api )?key|incorrect api key|api key (is )?(missing|invalid|not valid)|"
             r"needs an api key|no api key|authentication|permission denied by the provider|forbidden|expired (token|key|login)"),
    ("model_missing", r"model missing|does not have .* yet|ollama pull|model .*not found|no such model|unknown model"),
    ("local_down", r"ollama does not look like it is running|cannot reach the model at (localhost|127\.0\.0\.1)|11434|lm studio"),
    ("timeout", r"timed out|timeout|took too long|no answer in \d+s"),
    ("network", r"could not reach|cannot reach|connection (failed|refused|reset|error|aborted)|unreachable|"
                r"name resolution|getaddrinfo|network|offline|ssl|eof occurred|remote end closed|bad gateway|\b50[234]\b"),
    ("no_model", r"no model (is )?(set up|ready|available)|no provider|set up a model|model unavailable"),
    ("empty", r"empty reply|no choices|returned nothing"),
    ("stopped", r"cancelled by the user|stopped early|stopped:"),
    ("budget", r"turn budget|time budget|safety ceiling|time limit"),
)

_ADVICE = {
    "busy": ("LOKI is still working on the last message",
             "Your message waits in the queue and goes out as soon as LOKI is free - or press Stop.",
             ["retry", "details"]),
    "context": ("This chat is too long for the model",
                "The conversation no longer fits what this model can read at once. Summarize it and go on, use a "
                "model with a bigger memory, or start a new chat.",
                ["compact", "switch", "new_chat", "details"]),
    "quota": ("This model's allowance is used up",
              "The provider says the free allowance or credit is spent. Another model (or one on this computer) "
              "can carry on now; this one comes back when the allowance resets.",
              ["smart", "switch", "local", "connections", "details"]),
    "rate_limit": ("The model asked LOKI to slow down",
                   "Too many requests in a short time. Wait a moment and LOKI tries again by itself, or carry on "
                   "with another model now.",
                   ["wait", "switch", "local", "smart", "details"]),
    "auth": ("The key for this model was not accepted",
             "The provider refused the key (missing, wrong or expired). Paste a fresh key in Connections, or use "
             "another model meanwhile.",
             ["connections", "switch", "local", "smart", "details"]),
    "model_missing": ("That model is not downloaded",
                      "The model on this computer has not been downloaded yet. Get it in Local models, or use another "
                      "model now.",
                      ["models", "switch", "smart", "details"]),
    "local_down": ("The model on this computer is not running",
                   "Ollama (or the local server) is not answering. Start it and try again, or use an online model.",
                   ["retry", "models", "switch", "smart", "details"]),
    "timeout": ("The model took too long",
                "No answer came in time. It is often a busy server: try again, or let another model answer.",
                ["retry", "switch", "local", "details"]),
    "network": ("LOKI could not reach the model",
                "The internet connection or the provider is down. LOKI can try again by itself, or a model on this "
                "computer can answer without the internet.",
                ["wait", "local", "switch", "retry", "details"]),
    "no_model": ("No model is ready",
                 "LOKI needs one model to answer. Connect a free one online or set one up on this computer.",
                 ["connections", "models", "smart", "details"]),
    "empty": ("The model sent back an empty answer",
              "That happens with overloaded free models. Try again or use another model.",
              ["retry", "switch", "local", "details"]),
    "stopped": ("Stopped", "You stopped it. Your message is still in the chat - send it again when you like.",
                ["retry", "draft"]),
    "budget": ("LOKI hit its time or step limit",
               "This request ran out of its budget before finishing. Try again (it continues from the chat), or hand "
               "it to a background agent with no limit.",
               ["retry", "switch", "details"]),
    "unknown": ("LOKI could not answer", "Something went wrong. Try again, use another model, or see what happened.",
                ["retry", "switch", "local", "details"]),
}


def wait_seconds(text: str) -> int:
    """How long the provider asked us to wait (0 = it did not say)."""
    try:
        import provider_health  # pylint: disable=import-outside-toplevel
        found = float(provider_health.retry_after(str(text)) or 0)
    except Exception:  # noqa: BLE001
        found = 0.0
    if not found:
        m = re.search(r"(?:retry|try again|wait)\D{0,20}(\d+(?:\.\d+)?)\s*(ms|s|sec|seconds?|m|min|minutes?)\b", str(text), re.I)
        if m:
            found = float(m.group(1)) * (60 if m.group(2).lower().startswith("m") and m.group(2).lower() != "ms" else 1)
            if m.group(2).lower() == "ms":
                found = found / 1000.0
    return int(max(0, min(found, 24 * 3600)) + 0.999) if found else 0


def classify(text: str, status: int = 0) -> dict:
    """{kind, title, advice, actions, wait_s, error} for an error the chat got."""
    raw = str(text or "")
    low = raw.lower()
    kind = "unknown"
    if status == 429:
        kind = "rate_limit"
    elif status in (401, 403):
        kind = "auth"
    elif status == 409:
        kind = "busy"
    else:
        for name, pattern in _RULES:
            if re.search(pattern, low):
                kind = name
                break
    if kind == "quota" and re.search(r"per.?minute|\brpm\b|\btpm\b|requests per", low):
        kind = "rate_limit"   # Gemini's RESOURCE_EXHAUSTED "per minute" is a rate limit, not a spent allowance
    title, advice, actions = _ADVICE[kind]
    wait = wait_seconds(raw) if kind in ("rate_limit", "quota", "network", "timeout") else 0
    if kind == "rate_limit" and not wait:
        wait = 20
    if kind == "network" and not wait:
        wait = 15
    if kind == "quota" and wait and wait <= 120:   # a short "quota" wait is really a rate limit
        actions = ["wait"] + [a for a in actions if a != "wait"]
    return {"kind": kind, "title": title, "advice": advice, "actions": list(actions), "wait_s": wait,
            "error": raw[:600], "labels": {a: ACTION_TEXT[a] for a in actions}}


def alternatives(agent: Any, exclude: str = "") -> list:
    """Models LOKI could switch to right now: [{name, label, local}] (ready ones only)."""
    out = []
    try:
        import providers_catalog  # pylint: disable=import-outside-toplevel
    except Exception:  # noqa: BLE001
        providers_catalog = None
    for name in list(getattr(agent, "MODELS", {}) or {}):
        if name in ("smart", "online") or name == exclude:
            continue
        try:
            if not agent.provider_configured(name):
                continue
            tier = agent.provider_tier(name)
        except Exception:  # noqa: BLE001
            continue
        card = (providers_catalog.get(name) if providers_catalog else None) or {}
        out.append({"name": name, "label": card.get("name") or name, "local": tier == "local", "tier": tier})
    out.sort(key=lambda e: (not e["local"], e["tier"] != "free", e["label"].lower()))
    return out[:12]


def recovery(agent: Any, error: str, status: int = 0) -> dict:
    out = classify(error, status)
    current = ""
    try:
        current = agent.active_model_name()
    except Exception:  # noqa: BLE001
        current = getattr(agent, "model_name", "")
    alts = alternatives(agent, exclude=current)
    out["current"] = current
    out["alternatives"] = alts
    out["has_local"] = any(a["local"] for a in alts)
    if not out["has_local"]:
        out["actions"] = [a for a in out["actions"] if a != "local"] + (["models"] if "models" not in out["actions"]
                                                                          and "local" in out["actions"] else [])
    if not alts:
        out["actions"] = [a for a in out["actions"] if a not in ("switch", "local")]
        if "connections" not in out["actions"] and out["kind"] not in ("busy", "stopped"):
            out["actions"].append("connections")
    out["labels"] = {a: ACTION_TEXT[a] for a in out["actions"]}
    return out


# ------------------------------------------------------------------ interrupted turns
class Inflight:
    """The chat turn being answered right now, on disk, so a crash or a quit cannot lose it."""

    def __init__(self, folder: Path) -> None:
        self.path = Path(folder) / "inflight.json"

    def start(self, prompt: str, convo: str = "", model: str = "") -> None:
        try:
            _write(self.path, {"prompt": prompt[:20000], "convo": convo, "model": model, "t": time.time(),
                               "pid": os.getpid(), "engine_started": STARTED})
        except OSError:
            pass

    def finish(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass

    def interrupted(self) -> dict | None:
        """A turn a PREVIOUS engine run never finished (this run's own turn is not 'interrupted')."""
        data = _read(self.path, None)
        if not isinstance(data, dict) or not data.get("prompt"):
            return None
        if data.get("pid") == os.getpid() and abs(float(data.get("engine_started") or 0) - STARTED) < 1e-6:
            return None
        if time.time() - float(data.get("t") or 0) > 7 * 86400:
            return None
        return {"prompt": data["prompt"], "convo": data.get("convo", ""), "model": data.get("model", ""),
                "t": data.get("t", 0)}

    dismiss = finish


# ------------------------------------------------------------------ steering
def add_steer(text: str) -> dict:
    text = str(text or "").strip()[:8000]
    if not text:
        return {"ok": False, "error": "nothing to send"}
    with _LOCK:
        _STEER_SEQ[0] += 1
        item = {"id": _STEER_SEQ[0], "text": text, "t": time.time()}
        STEERS.append(item)
        del STEERS[:-20]
    return {"ok": True, "id": item["id"], "waiting": len(STEERS)}


def take_steers() -> list:
    with _LOCK:
        out = list(STEERS)
        STEERS.clear()
    return out


def cancel_steer(steer_id: int) -> bool:
    with _LOCK:
        for i, s in enumerate(STEERS):
            if s["id"] == steer_id:
                del STEERS[i]
                return True
    return False


STEER_PREFIX = "[The user added this while you were working - take it into account from now on]: "


def inject_steers(agent: Any, state: Any = None) -> int:
    """Put waiting steers into the conversation the agent is about to send. Returns how many."""
    items = take_steers()
    if not items:
        return 0
    history = getattr(agent, "messages", None)
    if not isinstance(history, list):
        with _LOCK:
            STEERS[:0] = items
        return 0
    last = history[-1] if history else {}
    if isinstance(last, dict) and last.get("role") == "assistant" and last.get("tool_calls"):
        with _LOCK:            # tool results still due: never split a tool call from its results
            STEERS[:0] = items
        return 0
    text = "\n\n".join(s["text"] for s in items)
    history.append({"role": "user", "content": STEER_PREFIX + text})
    if state is not None and hasattr(state, "push_progress"):
        for s in items:
            state.push_progress(getattr(state, "progress_chat_id", ""), "steer", json.dumps({"id": s["id"], "text": s["text"][:400]}))
    return len(items)


# ------------------------------------------------------------------ approvals for this session
def never_for_session() -> set:
    try:
        import policy  # pylint: disable=import-outside-toplevel
        return set(policy.ALWAYS_ASK) | set(getattr(policy, "ACTION_ALWAYS_ASK", {}) or {}) | NEVER_SESSION_EXTRA
    except Exception:  # noqa: BLE001
        return {"delete_file", "delegate"} | NEVER_SESSION_EXTRA


def rule_key(tool: str, details: str) -> str:
    return hashlib.sha256(("%s\n%s" % (tool, " ".join(str(details or "").split()))).encode("utf-8")).hexdigest()


def session_allows(tool: str, details: str) -> bool:
    if tool in never_for_session():
        return False
    return rule_key(tool, details) in SESSION_RULES


def allow_for_session(state: Any, ticket_id: str) -> tuple:
    """Approve the pending ticket AND remember this exact action until the engine restarts."""
    import secrets  # pylint: disable=import-outside-toplevel
    with state.lock:
        ticket = state.pending
        if ticket is None or not secrets.compare_digest(str(ticket.get("id", "")), str(ticket_id or "")):
            return 404, {"ok": False, "error": "That approval is no longer waiting."}
        tool = str(ticket.get("tool", ""))
        if tool in never_for_session():
            return 400, {"ok": False, "error": "%s always asks - it cannot be allowed for the whole session." % tool,
                         "never": True}
        SESSION_RULES[rule_key(tool, ticket.get("details", ""))] = {
            "tool": tool, "preview": " ".join(str(ticket.get("details", "")).split())[:160], "t": time.time()}
        ticket["approved"] = True
        ticket["event"].set()
    return 200, {"ok": True, "approved": True, "rules": len(SESSION_RULES)}


# ------------------------------------------------------------------ context
def context(agent: Any) -> dict:
    import condenser  # pylint: disable=import-outside-toplevel
    history = getattr(agent, "messages", []) or []
    try:
        local = bool(agent._is_local_model())  # noqa: SLF001
    except Exception:  # noqa: BLE001
        local = False
    max_messages, max_chars = condenser.limits(local=local)
    chars = condenser.size(history)
    cache = getattr(agent, "_CONDENSE_CACHE", {}) or {}
    pct = int(round(100.0 * chars / max_chars)) if max_chars else 0
    if cache:   # the model already gets a summary of the older part
        try:
            view = history[:cache["start"]] + [cache["note"]] + history[cache["end"]:]
            pct = int(round(100.0 * condenser.size(view) / max_chars)) if max_chars else 0
        except (KeyError, TypeError):
            pass
    level = "full" if pct >= 95 else "long" if pct >= 75 else "ok"
    return {"ok": True, "chars": chars, "max_chars": max_chars, "percent": pct, "messages": len(history),
            "max_messages": max_messages, "condensed": bool(cache), "level": level, "local": local,
            "enabled": condenser.enabled()}


def compact(state: Any) -> tuple:
    """Summarize the older part of the active chat now (the condenser, as if the model asked)."""
    agent = state.agent
    if getattr(state, "loop", None) is None or not hasattr(agent, "_model_view"):
        return 503, {"ok": False, "error": "LOKI's engine is not ready."}
    busy = state.try_busy()
    if busy is None:
        return 409, {"ok": False, "error": "LOKI is busy; it summarizes after the current answer."}
    try:
        before = context(agent)
        if before["messages"] < 6:
            return 200, {"ok": True, "condensed": False, "note": "This chat is still short - nothing to summarize.",
                         "before": before, "after": before}
        future = asyncio.run_coroutine_threadsafe(agent._model_view(requested=True), state.loop)  # noqa: SLF001
        future.result(timeout=240)
        after = context(agent)
        return 200, {"ok": True, "condensed": after["condensed"], "before": before, "after": after,
                     "note": "Summarized the older part of the chat; the full history is kept."
                     if after["condensed"] else "Could not summarize it (the summary model did not answer)."}
    except Exception as exc:  # noqa: BLE001
        return 500, {"ok": False, "error": "Summarizing failed: %s" % str(exc)[:200]}
    finally:
        state.release_busy(busy)


# ------------------------------------------------------------------ search + pins
def _words(q: str) -> list:
    return [w for w in re.split(r"\s+", str(q or "").lower().strip()) if w]


def _snippet(text: str, word: str, width: int = 70) -> str:
    low = text.lower()
    i = low.find(word)
    if i < 0:
        return " ".join(text.split())[:width * 2]
    start = max(0, i - width)
    out = " ".join(text[start:i + len(word) + width].split())
    return ("..." if start else "") + out + ("..." if i + len(word) + width < len(text) else "")


def search(agent: Any, query: str, limit: int = 40) -> dict:
    words = _words(query)
    if not words:
        return {"ok": True, "query": query, "results": []}
    try:
        convos = list(agent.list_conversations())[:300]
    except Exception:  # noqa: BLE001
        convos = []
    results = []
    for c in convos:
        cid = str(c.get("id", ""))
        title = str(c.get("title", "") or "New chat")
        if all(w in title.lower() for w in words):
            results.append({"id": cid, "title": title, "where": "title", "snippet": "", "role": "", "index": -1})
        try:
            messages = agent.conversation_messages(cid) or []
        except Exception:  # noqa: BLE001
            messages = []
        hits = 0
        for i, m in enumerate(messages):
            if m.get("role") not in ("user", "assistant"):
                continue
            text = str(m.get("content") or "")
            low = text.lower()
            if text and all(w in low for w in words):
                results.append({"id": cid, "title": title, "where": "message", "role": m.get("role"), "index": i,
                                "snippet": _snippet(text, words[0])})
                hits += 1
                if hits >= 3:
                    break
        if len(results) >= limit:
            break
    return {"ok": True, "query": query, "results": results[:limit]}


def prefs(agent: Any) -> dict:
    data = _read(data_dir(agent) / "prefs.json", {})
    return data if isinstance(data, dict) else {}


def set_pin(agent: Any, cid: str, pinned: bool) -> dict:
    data = prefs(agent)
    pins = [p for p in data.get("pins", []) if isinstance(p, str) and p != cid]
    if pinned and cid:
        pins.insert(0, cid)
    data["pins"] = pins[:50]
    _write(data_dir(agent) / "prefs.json", data)
    return {"ok": True, "pins": data["pins"]}


# ------------------------------------------------------------------ notifications + what happened
def notify(title: str, text: str, run: bool = True) -> dict:
    """A desktop notification (macOS osascript, Windows toast, Linux notify-send) - text never in a script."""
    try:
        import automations  # pylint: disable=import-outside-toplevel
        argv, extra = automations.notify_argv(str(title or "LOKI")[:120], str(text or "")[:600])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    if not run:                                     # a dry run shows the command, on any machine (tests, the doctor)
        return {"ok": True, "sent": False, "how": argv[0], "argv": argv, "env": extra, "found": bool(shutil.which(argv[0]))}
    if not shutil.which(argv[0]):
        return {"ok": True, "sent": False, "how": argv[0] + " not found"}

    def go() -> None:
        import subprocess  # pylint: disable=import-outside-toplevel
        try:
            subprocess.run(argv, env={**os.environ, **extra}, capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            pass

    threading.Thread(target=go, daemon=True, name="loki-qol-notify").start()
    return {"ok": True, "sent": True, "how": argv[0]}


def diagnose(state: Any) -> dict:
    """What happened: the last turn's errors and steps, the model route, provider health."""
    redact = getattr(sys.modules.get("loki_bridge"), "redact_line", None) or (lambda s: s)
    agent = state.agent
    with state.lock:
        events = list(getattr(state, "progress", []))[-60:]
    steps = [{"event": e.get("event"), "text": redact(str(e.get("text", "")))[:300]} for e in events
             if e.get("event") in ("error", "tool", "tool_result", "done", "thinking", "steer")
             and not str(e.get("text", "")).startswith("Still working")][-25:]
    errors = [s["text"] for s in steps if s["event"] == "error"]
    try:
        current = agent.active_model_name()
    except Exception:  # noqa: BLE001
        current = getattr(agent, "model_name", "")
    try:
        report = agent.smart_report() if hasattr(agent, "smart_report") else ""
    except Exception:  # noqa: BLE001
        report = ""
    out = {"ok": True, "engine_up_s": int(time.time() - STARTED), "model": getattr(agent, "model_name", ""),
           "using": current, "route": [redact(str(r))[:200] for r in list(getattr(agent, "ROUTE_TRACE", []))[-10:]],
           "providers": redact(str(report))[:3000], "steps": steps, "errors": errors[-5:],
           "busy": bool(getattr(state, "chat_request_lock", None) and state.chat_request_lock.locked()),
           "waiting_steers": len(STEERS), "session_rules": len(SESSION_RULES)}
    if errors:
        out["recovery"] = classify(errors[-1])
    return out


# ------------------------------------------------------------------ install into the running engine
def install(state: Any, agent: Any) -> bool:
    """Wrap the bridge's request_chat / request_approval and the agent's _trim_context. Idempotent."""
    if getattr(state, "_qol_installed", False):
        return False
    state._qol_installed = True  # noqa: SLF001
    inflight = Inflight(data_dir(agent))
    state.qol_inflight = inflight
    orig_chat = state.request_chat
    orig_approval = state.request_approval

    async def request_chat(prompt: str) -> dict:
        try:
            convo = agent.active_conversation_id()
        except Exception:  # noqa: BLE001
            convo = ""
        inflight.start(prompt, convo, getattr(agent, "model_name", ""))
        try:
            result = await orig_chat(prompt)
        finally:
            inflight.finish()
        left = take_steers()
        if isinstance(result, dict):
            if left:
                result["steers_left"] = [s["text"] for s in left]
            if not result.get("ok"):
                try:
                    result["recovery"] = recovery(agent, str(result.get("error", "")))
                except Exception:  # noqa: BLE001
                    pass
        return result

    async def request_approval(tool_name: str, details: str) -> bool:
        if session_allows(tool_name, details):
            state.push_progress(getattr(state, "progress_chat_id", ""), "thinking",
                                "Allowed without asking: you allowed this exact action (%s) for this session." % tool_name)
            return True
        return await orig_approval(tool_name, details)

    state.request_chat = request_chat
    state.request_approval = request_approval
    trim = getattr(agent, "_trim_context", None)
    if callable(trim) and not getattr(trim, "_qol", False):
        def _trim_context(*args: Any, **kwargs: Any) -> Any:
            if STEERS:
                try:
                    inject_steers(agent, state)
                except Exception as exc:  # noqa: BLE001 - a steer must never stop a turn
                    print("[qol] steer skipped: %s" % exc, flush=True)
            return trim(*args, **kwargs)
        _trim_context._qol = True  # type: ignore[attr-defined]  # noqa: SLF001
        agent._trim_context = _trim_context  # noqa: SLF001
    return True


# ------------------------------------------------------------------ routes
def handles(route: str) -> bool:
    return route.startswith("/qol/")


def route(state: Any, method: str, path: str, data: dict | None = None) -> tuple:
    data = data or {}
    parsed = urlparse(path)
    r = parsed.path
    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    agent = state.agent
    inflight = getattr(state, "qol_inflight", None) or Inflight(data_dir(agent))
    busy = bool(getattr(state, "chat_request_lock", None) and state.chat_request_lock.locked())
    if method == "GET":
        if r == "/qol/state":
            return 200, {"ok": True, "interrupted": inflight.interrupted(), "pins": prefs(agent).get("pins", []),
                         "busy": busy, "never_session": sorted(never_for_session()),
                         "session_rules": [dict(v) for v in SESSION_RULES.values()], "steers": len(STEERS),
                         "platform": sys.platform}
        if r == "/qol/context":
            return 200, context(agent)
        if r == "/qol/search":
            return 200, search(agent, query.get("q", ""))
        if r == "/qol/diagnose":
            return 200, diagnose(state)
        if r == "/qol/alternatives":
            return 200, {"ok": True, "alternatives": alternatives(agent)}
        return 404, {"ok": False, "error": "unknown"}
    if r == "/qol/classify":
        return 200, {"ok": True, **recovery(agent, str(data.get("error", "")), int(data.get("status") or 0))}
    if r == "/qol/interrupted/dismiss":
        inflight.dismiss()
        return 200, {"ok": True}
    if r == "/qol/steer":
        if not busy:
            return 409, {"ok": False, "error": "LOKI is not working on anything - send it as a normal message.",
                         "idle": True}
        return 200, add_steer(str(data.get("text", "")))
    if r == "/qol/steer/cancel":
        return 200, {"ok": True, "removed": cancel_steer(int(data.get("id") or 0))}
    if r == "/qol/approval":
        return allow_for_session(state, str(data.get("id", "")))
    if r == "/qol/approvals/clear":
        SESSION_RULES.clear()
        return 200, {"ok": True}
    if r == "/qol/compact":
        return compact(state)
    if r == "/qol/pin":
        return 200, set_pin(agent, str(data.get("id", "")), bool(data.get("pinned")))
    if r == "/qol/notify":
        return 200, notify(str(data.get("title", "LOKI")), str(data.get("text", "")))
    return 404, {"ok": False, "error": "unknown"}
