"""Task-aware model routing: the right model for THIS task, and never a dead end.

loki.active_model_name() asks this module, for each request, which providers can do the
work and in what order to try them. The inputs:

  needs      what the task needs (needs_for): its kind and difficulty (the first layer's
             triage), whether it is a background job, tool-heavy, has pictures in it, how
             many tokens it is, and whether it must stay on this computer (LOKI_LOCAL_ONLY)
  abilities  what each provider/model can do (abilities): calls tools natively / only as
             prompted text / reliably (MEASURED: experience.tool_score), sees images,
             context window, good at code - from the provider's own /models metadata when
             provider_health has it, else from what the model's name says
  health     provider_health: key rejected, quota spent until, rate limited, too-small
             request limit... (a dead provider is skipped and the reason is kept)
  success    a learned table per (provider, task kind) and (provider/model, kind) from real
             request and job outcomes (experience log): routing improves itself

The order never crosses cost tiers on its own (free stays ahead of paid; paid only when
allowed - loki decides that) and a provider that lacks an ability is moved to the END, not
removed, so there is always somewhere to go. `doctor()` explains the whole picture in plain
words: "pictures -> gemini, code -> openrouter, background jobs -> groq, because ...".
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import experience
import provider_health

TOOL_HEAVY_KINDS = ("code", "build", "ops", "browse", "research")
LONG_TOKENS = int(os.getenv("LOKI_LONG_CONTEXT_TOKENS", "32000") or 32000)
MIN_KIND_SAMPLES = int(os.getenv("LOKI_KIND_MIN_SAMPLES", "5") or 5)
RELIABLE_TOOL_SCORE = 0.5

# What a model's name says when the provider does not tell us (lower-case substrings).
VISION_HINTS = ("gemini", "gpt-4o", "gpt-4.1", "gpt-5", "claude", "gemma3", "gemma-3", "gemma4", "gemma-4", "llava",
                "-vl", "vl-", "_vl", "vision", "pixtral", "llama-4", "llama4", "mistral-medium", "mistral-small",
                "kimi-k2.5", "minicpm-v", "moondream")
CODE_HINTS = ("coder", "codestral", "devstral", "deepseek", "gpt-oss", "gpt-5", "claude", "glm", "kimi", "laguna",
              "qwen3", "codex", "nemotron", "hermes-4")
TINY_HINTS = (":0.6b", ":1b", ":1.5b", ":2b", ":3b", "-2b-", "-1b-", "0.6b", "1.5b", "-3b-", "-2b", "-3b")
# Context windows of the defaults when nobody says otherwise (tokens).
CONTEXT_HINTS = (("gemini", 1_000_000), ("deepseek-v4", 1_000_000), ("deepseek/deepseek-v4", 1_000_000),
                 ("deepseek-flash", 1_000_000), ("claude", 200_000), ("gpt-5", 400_000), ("gpt-oss", 131_072),
                 ("llama-3.3", 131_072), ("qwen3", 131_072), ("mistral-large", 131_072), ("codestral", 256_000),
                 ("laguna", 131_072), ("hermes-4", 131_072), ("nemotron", 131_072), ("glm", 131_072))


def _local_window() -> int:
    try:
        import condenser  # pylint: disable=import-outside-toplevel
        return int(getattr(condenser, "LOCAL_WINDOW_TOKENS", 0) or 0)
    except Exception:  # noqa: BLE001
        return 0


# --------------------------------------------------------------------- needs
def images_in(messages: list, last: int = 6) -> bool:
    """Is there a picture in the recent user messages (OpenAI content parts)?"""
    for m in (messages or [])[-last:]:
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, list) and any(isinstance(p, dict) and p.get("type") in ("image_url", "image", "input_image")
                                             for p in content):
            return True
    return False


def estimate_tokens(messages: list, extra_chars: int = 0) -> int:
    chars = extra_chars
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if isinstance(content, str):
            chars += len(content)
        elif content is not None:
            chars += len(json.dumps(content, default=str)) if not isinstance(content, list) else \
                sum(len(str(p.get("text", ""))) + (1000 if isinstance(p, dict) and p.get("type") != "text" else 0)
                    for p in content if isinstance(p, dict))
        for call in m.get("tool_calls") or []:
            chars += len(json.dumps(call, default=str)) if isinstance(call, dict) else 200
    return chars // 4


def needs_for(triage: dict | None = None, background: bool = False, messages: list | None = None,
              local_only: bool = False, est_tokens: int = 0, vision: bool | None = None) -> dict:
    """What this task needs from a model."""
    t = triage or {}
    kind = str(t.get("kind") or "")
    try:
        difficulty = int(t.get("difficulty"))
    except (TypeError, ValueError):
        difficulty = 1
    caps = [str(c) for c in (t.get("capabilities") or [])]
    seen = images_in(messages or []) if vision is None else bool(vision)
    seen = seen or any("vision" in c or "image.read" in c for c in caps)
    tool_heavy = bool(background or kind in TOOL_HEAVY_KINDS or t.get("route") in ("plan", "team"))
    return {"kind": kind or ("code" if background else ""), "difficulty": difficulty, "background": bool(background),
            "tool_heavy": tool_heavy, "vision": seen, "code": kind in ("code", "build"),
            "est_tokens": int(est_tokens or 0), "long": int(est_tokens or 0) > LONG_TOKENS,
            "local_only": bool(local_only)}


def local_only_setting() -> bool:
    return str(os.getenv("LOKI_LOCAL_ONLY", "0")).strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------- abilities
_STATS_CACHE: dict = {"t": 0.0, "stats": {}}


def tool_stats() -> dict:
    """experience.tool_stats(), cached for a minute (routing asks many times per turn)."""
    now = time.time()
    if now - _STATS_CACHE["t"] > 60:
        try:
            _STATS_CACHE["stats"] = experience.tool_stats()
        except Exception:  # noqa: BLE001
            _STATS_CACHE["stats"] = {}
        _STATS_CACHE["t"] = now
    return _STATS_CACHE["stats"]


def _hint(model: str, hints) -> bool:
    low = model.lower()
    return any(h in low for h in hints)


def _context_hint(model: str) -> int:
    low = model.lower()
    for needle, ctx in CONTEXT_HINTS:
        if needle in low:
            return ctx
    return 0


def abilities(agent: Any, pid: str, health: dict | None = None, tool_stats_arg: dict | None = None) -> dict:
    """What `pid` (as configured now) can do. Every field is a best guess unless `source` says so."""
    cfg = agent.MODELS.get(pid)
    model = str(getattr(cfg, "model", "") or "")
    base = str(getattr(cfg, "base_url", "") or "")
    try:
        tier = agent.provider_tier(pid)
    except Exception:  # noqa: BLE001
        tier = "free"
    health = health if health is not None else provider_health.registry().get(pid)
    info = (health or {}).get("model_info") or {}
    cli = base.startswith("cli-agent://")
    try:
        import providers_catalog  # pylint: disable=import-outside-toplevel
        cat = providers_catalog.get(pid) or {}
    except Exception:  # noqa: BLE001
        cat = {}
    try:
        import tool_harness  # pylint: disable=import-outside-toplevel
        prompted = tool_harness.configured(pid)
    except Exception:  # noqa: BLE001
        prompted = False
    if cli:
        tools = "agent"
    elif info.get("tools") is False or prompted or cat.get("tools") is False:
        tools = "prompted"
    else:
        tools = "native"
    measured = None
    try:
        stats = tool_stats_arg if tool_stats_arg is not None else tool_stats()
        key = ("local/" + model) if tier == "local" else (pid + "/" + model)
        measured = experience.tool_score(key, stats, 3)
        if measured is None:
            measured = experience.tool_score(pid, stats, 3)
    except Exception:  # noqa: BLE001
        measured = None
    tiny = tier == "local" and _hint(model, TINY_HINTS)
    if measured is not None:
        reliable = measured >= (0.7 if tools == "prompted" else RELIABLE_TOOL_SCORE)
        why_tools = "measured tool score %.2f" % measured
    elif tools == "agent":
        reliable, why_tools = True, "a coding agent with its own tools"
    elif tiny:
        reliable, why_tools = False, "too small to call tools reliably"
    elif tools == "native":
        reliable, why_tools = True, "calls tools natively"
    else:
        reliable, why_tools = False, "tools only as prompted text"
    local_caps = None
    if tier == "local":
        try:
            import model_setup  # pylint: disable=import-outside-toplevel
            local_caps = model_setup._CAPS.get(model)   # Ollama's own list, when already asked (no I/O here)
        except Exception:  # noqa: BLE001
            local_caps = None
    if "vision" in info:
        vision = bool(info["vision"])
    elif local_caps is not None:
        vision = "vision" in local_caps
    else:
        vision = _hint(model, VISION_HINTS) and not _hint(model, ("coder", "codestral"))
    ctx = int(info.get("context") or (health or {}).get("context") or 0)
    if not ctx:
        ctx = (_local_window() or 8192) if tier == "local" else (_context_hint(model) or 32768)
    return {"provider": pid, "model": model, "tier": tier, "tools": tools, "tools_reliable": reliable,
            "tools_why": why_tools, "tool_score": measured, "vision": vision, "context": ctx,
            "code": cli or _hint(model, CODE_HINTS), "local": tier == "local",
            "keyless": cat.get("group") == "keyless" and not (cfg is not None and cat.get("env")
                                                            and os.getenv(cat["env"], "").strip()),
            "source": "provider" if info else "name"}


def fits(ab: dict, needs: dict) -> tuple:
    """(True, "") or (False, why this model is a poor fit for this task)."""
    if needs.get("tool_heavy") and not ab["tools_reliable"]:
        return False, "cannot call tools reliably (%s)" % ab["tools_why"]
    if needs.get("vision") and not ab["vision"]:
        return False, "cannot see pictures"
    est = int(needs.get("est_tokens") or 0)
    if est and ab["context"] and est > int(ab["context"] * 0.9):
        return False, "has only a %dk context for ~%dk tokens" % (ab["context"] // 1000, est // 1000)
    return True, ""


# --------------------------------------------------------------------- what worked (learned)
_TABLE_CACHE: dict = {"t": 0.0, "table": {}}


def success_table(lines: list | None = None) -> dict:
    """{(provider, kind): {n, good, rate}} and {(provider/model, kind): ...} from real outcomes.

    good = verified, or done with no failed verification; a hop that was switched away from
    in that request counts as a failure for its provider. Chat answers (no outcome) count
    only by status.
    """
    if lines is None:
        now = time.time()
        if now - _TABLE_CACHE["t"] < 60:
            return _TABLE_CACHE["table"]
        try:
            lines = experience.entries(last=1000)
        except Exception:  # noqa: BLE001
            lines = []
        table = success_table(lines)
        _TABLE_CACHE.update(t=now, table=table)
        return table
    table: dict = {}

    def bump(key, good):
        b = table.setdefault(key, {"n": 0, "good": 0})
        b["n"] += 1
        b["good"] += 1 if good else 0

    for line in lines:
        kind = str((line.get("triage") or {}).get("kind") or "") or ("job" if line.get("role") else "")
        if not kind:
            continue
        for hop in line.get("route") or []:
            if hop.get("provider"):
                bump((hop["provider"], kind), False)
        pid = line.get("provider")
        if not pid:
            continue
        outcome, status = line.get("outcome"), line.get("status")
        good = outcome == "verified" or (status == "done" and outcome not in ("failed", "blocked"))
        bump((pid, kind), good)
        if line.get("model"):
            bump((pid + "/" + str(line["model"]), kind), good)
    for b in table.values():
        b["rate"] = round(b["good"] / b["n"], 3) if b["n"] else None
    return table


def kind_rate(table: dict, pid: str, model: str, kind: str, min_samples: int = MIN_KIND_SAMPLES):
    for key in ((pid + "/" + model, kind), (pid, kind)):
        b = table.get(key)
        if b and b["n"] >= min_samples:
            return b["rate"], b["n"]
    return None, 0


def reset_caches() -> None:
    _TABLE_CACHE.update(t=0.0, table={})
    _STATS_CACHE.update(t=0.0, stats={})


# --------------------------------------------------------------------- ordering
def order_for(agent: Any, order, needs: dict, key_of=None, table: dict | None = None,
              registry=None) -> tuple:
    """(ordered, notes): `order` for THIS task. Health-dead providers are left out (notes says
    why), providers lacking an ability the task needs go last (notes says why), and within a
    cost tier the ones that did this kind of task best go first."""
    reg = registry or provider_health.registry()
    reg.refresh()
    table = success_table() if table is None else table
    stats = tool_stats()
    key_of = key_of or (lambda p: str(getattr(agent.MODELS.get(p), "api_key", "") or ""))
    notes: dict = {}
    capable, weak = [], []
    for pid in order:
        if pid not in agent.MODELS:
            continue
        ok, why = reg.usable(pid, key_of(pid), int(needs.get("est_tokens") or 0))
        if not ok:
            notes[pid] = why
            continue
        ab = abilities(agent, pid, reg.get(pid), stats)
        good, why = fits(ab, needs)
        if needs.get("local_only") and not ab["local"]:
            notes[pid] = "not on this computer (local only is on)"
            continue
        (capable if good else weak).append(pid)
        if not good:
            notes[pid] = why
    kind = needs.get("kind") or ""

    def tiered(items: list) -> list:
        if not kind:
            return items
        out, i = [], 0
        while i < len(items):
            tier = agent.provider_tier(items[i])
            run = []
            while i < len(items) and agent.provider_tier(items[i]) == tier:
                run.append(items[i])
                i += 1
            rated = {p: kind_rate(table, p, str(getattr(agent.MODELS.get(p), "model", "")), kind)[0] for p in run}
            proven = sorted([p for p in run if rated[p] is not None], key=lambda p: -rated[p])
            it = iter(proven)
            out.extend(next(it) if rated[p] is not None else p for p in run)
        return out

    return tiered(capable) + tiered(weak), notes


def why_line(agent: Any, pid: str, needs: dict, table: dict | None = None) -> str:
    """'free, calls tools natively, sees pictures, 8/10 code tasks went well, 420 ms'."""
    reg = provider_health.registry()
    ab = abilities(agent, pid, reg.get(pid))
    parts = [{"local": "on this computer", "free": "free", "subscription": "your subscription",
              "paid": "paid"}.get(ab["tier"], ab["tier"])]
    if needs.get("tool_heavy"):
        parts.append(ab["tools_why"])
    if needs.get("vision"):
        parts.append("sees pictures" if ab["vision"] else "cannot see pictures")
    if needs.get("long") or needs.get("est_tokens", 0) > 16000:
        parts.append("%dk context" % (ab["context"] // 1000))
    table = success_table() if table is None else table
    if needs.get("kind"):
        rate, n = kind_rate(table, pid, ab["model"], needs["kind"])
        if rate is not None:
            parts.append("%d/%d %s tasks went well" % (round(rate * n), n, needs["kind"]))
    lat = reg.get(pid).get("latency_ms")
    if lat:
        parts.append("%d ms" % int(lat))
    return ", ".join(p for p in parts if p)


# --------------------------------------------------------------------- the doctor
SCENARIOS = [
    ("chat", "Chat and questions", {"kind": "question", "difficulty": 1}),
    ("code", "Code and builds", {"kind": "code", "difficulty": 2}),
    ("pictures", "Pictures (reading images)", {"kind": "question", "difficulty": 1, "vision": True}),
    ("long", "Long documents (~150k tokens)", {"kind": "research", "difficulty": 2, "est_tokens": 150_000}),
    ("background", "Background jobs", {"kind": "code", "difficulty": 1, "background": True}),
    ("hard", "Hard tasks", {"kind": "build", "difficulty": 3}),
]


def scenario_needs(spec: dict) -> dict:
    triage = {"kind": spec.get("kind", ""), "difficulty": spec.get("difficulty", 1)}
    return needs_for(triage, background=bool(spec.get("background")), local_only=local_only_setting(),
                     est_tokens=int(spec.get("est_tokens") or 0), vision=bool(spec.get("vision")))


def doctor(agent: Any) -> dict:
    """The current routing in plain words, plus what is dead and how to fix it."""
    reg = provider_health.registry()
    reg.refresh()
    table = success_table()
    routes = []
    for sid, label, spec in SCENARIOS:
        needs = scenario_needs(spec)
        try:
            pid, why = agent.route_for(needs)
        except Exception as exc:  # noqa: BLE001
            pid, why = "", "routing failed: %s" % exc
        model = str(getattr(agent.MODELS.get(pid), "model", "") or "")
        routes.append({"id": sid, "label": label, "provider": pid, "model": model, "why": why,
                       "text": "%s -> %s%s, because %s" % (label, pid or "nothing", (" (%s)" % model) if model else "",
                                                             why or "it is the first one ready")})
    try:
        import providers_catalog  # pylint: disable=import-outside-toplevel
    except Exception:  # noqa: BLE001
        providers_catalog = None
    dead, needs_you = [], []
    snap = reg.snapshot()
    for pid, e in sorted(snap.items()):
        if pid not in agent.MODELS or e.get("live"):
            continue
        cat = providers_catalog.get(pid) if providers_catalog else None
        fix = provider_health.fix_for(pid, e, cat)
        dead.append({"provider": pid, "state": e.get("state"), "line": e.get("line"), "fix": fix})
        if e.get("state") in ("key_rejected", "no_credit", "model_missing"):
            needs_you.append("%s: %s. %s" % (pid, e.get("line"), fix))
    local = {}
    try:
        local = agent.local_report()
    except Exception as exc:  # noqa: BLE001
        local = {"error": str(exc)}
    for line in local.get("needs_you") or []:
        needs_you.append(line)
    mode = getattr(agent, "model_name", "smart")
    head = ("Mode: %s%s. Paid providers: %s. Local only: %s." % (
        mode, "" if mode in ("smart", "online") else " (pinned - routing only steps in when it fails)",
        "allowed" if getattr(agent, "ALLOW_PAID", False) else "never picked automatically",
        "on" if local_only_setting() else "off"))
    driver = main_driver(agent)
    if driver.get("provider"):
        head += "\n" + driver["text"]
        if not driver["ready"] and driver.get("fix"):
            needs_you.insert(0, driver["fix"])
    lines = [head, ""] + ["- " + r["text"] for r in routes]
    if dead:
        lines += ["", "Skipped right now:"] + ["- %s: %s.%s" % (d["provider"], d["line"], (" Fix: " + d["fix"]) if d["fix"] else "")
                                             for d in dead]
    if local.get("lines"):
        lines += ["", "On this computer:"] + ["- " + x for x in local["lines"]]
    if needs_you:
        lines += ["", "Needs you:"] + ["- " + x for x in needs_you]
    return {"ok": True, "mode": mode, "routes": routes, "dead": dead, "local": local, "needs_you": needs_you,
            "main_driver": driver, "text": "\n".join(lines)}


def main_driver(agent: Any) -> dict:
    """LOKI's main driver (session 29: DeepSeek V4.1 Flash on NVIDIA NIM), whether it is driving
    now, and the one-line fix when it is not."""
    pid = str(getattr(agent, "MAIN_DRIVER", "") or "")
    if not pid or pid not in getattr(agent, "MODELS", {}):
        return {"provider": "", "ready": False, "text": "Main driver: off (LOKI_MAIN_DRIVER=off).", "fix": ""}
    model = str(getattr(agent.MODELS.get(pid), "model", "") or "")
    try:
        ready, why = agent.main_driver_ready({})
    except Exception as exc:  # noqa: BLE001
        ready, why = False, str(exc)
    mode = getattr(agent, "model_name", "smart")
    pinned = mode not in ("smart", "online") and mode != pid
    fix = ""
    if not ready and "key" in why:
        fix = ("Main driver %s needs its free key: get one at %s and paste it in Settings > Connections > "
               "NVIDIA NIM." % (model, getattr(agent, "MAIN_DRIVER_KEY_URL", "https://build.nvidia.com/settings/api-keys")))
    try:
        import ratelimit  # pylint: disable=import-outside-toplevel
        cap = ratelimit.rpm(pid)
    except Exception:  # noqa: BLE001
        cap = 0
    if ready:
        text = "Main driver: %s on %s - drives chat, background jobs, teams and self-improvement%s%s." % (
            model, pid, (" (paced at %d requests/min)" % cap) if cap else "",
            "; but you pinned %s, so it only steps in when that fails" % mode if pinned else "")
    else:
        text = "Main driver: %s on %s - not driving: %s. Every other provider is the fallback meanwhile." % (model, pid, why)
    return {"provider": pid, "model": model, "ready": bool(ready), "why": why, "pinned": pinned, "rpm": cap,
            "text": text, "fix": fix}
