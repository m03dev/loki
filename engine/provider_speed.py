"""How fast each online provider is answering RIGHT NOW, per agent step - so work moves off one that crawls.

Owner 2026-10-25: "they need to use tools and make things stop wasting time and get it done". On the Mac, NVIDIA's free
DeepSeek 4.1 took 302 s for ONE agent step: a one-picture task would have taken an hour. Every OpenCode step reports
how long it took; a step slower than SLOW_S (LOKI_SLOW_STEP_S, default 120) marks that provider slow for COOL_S
(LOKI_SLOW_COOL_S, default 45 min): the running turn moves to the next provider (same OpenCode session, nothing lost)
and the next turns put it last. State in <data>/provider_speed.json, shared by every LOKI process on the machine.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

SLOW_S = float(os.getenv("LOKI_SLOW_STEP_S", "120") or 120)
COOL_S = float(os.getenv("LOKI_SLOW_COOL_S", "2700") or 2700)


def _file(data_dir) -> Path:
    return Path(data_dir) / "provider_speed.json"


def _load(data_dir) -> dict:
    try:
        return json.loads(_file(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record(data_dir, provider: str, step_s: float, now: float | None = None) -> bool:
    """One step took step_s seconds on this provider. Returns True when that makes it slow."""
    if not provider:
        return False
    data = _load(data_dir)
    entry = data.get(provider) or {}
    slow = step_s > SLOW_S
    entry.update(t=now or time.time(), last_step_s=round(float(step_s), 1))
    entry.pop("out", None)                  # it answered: whatever it said before is over
    if slow:
        entry["slow_until"] = (now or time.time()) + COOL_S
    elif step_s < SLOW_S / 2:
        entry.pop("slow_until", None)       # answering briskly again
    data[provider] = entry
    try:
        _file(data_dir).parent.mkdir(parents=True, exist_ok=True)
        _file(data_dir).write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass
    return slow


def mark_out(data_dir, provider: str, error: str, now: float | None = None) -> float:
    """A provider that said it is OUT - 402 (no credit) or a daily cap (429 free-models-per-day) - goes last for hours,
    so the next jobs do not start on it again (2026-10-25: three Mac jobs in a row hit OpenRouter's 402). Returns
    the seconds it is benched (0 = not an out-of-quota error)."""
    text = str(error or "").lower()
    if '"code":402' in text.replace(" ", "") or "402" in text and "credit" in text:
        hold = 6 * 3600.0
    elif "per-day" in text or "per day" in text or "daily" in text:
        hold = 12 * 3600.0
    elif "request too large" in text or "tokens per minute" in text:
        hold = 12 * 3600.0          # Groq's free tier: OpenCode's prompt alone is over its per-minute limit
    elif "resource_exhausted" in text or "too many requests" in text or "quota" in text:
        hold = 3600.0               # Gemini's free quota
    elif "429" in text or "rate limit" in text:
        hold = 10 * 60.0
    elif "insufficient balance" in text or "insufficient_quota" in text or "out of credit" in text:
        hold = 12 * 3600.0          # DeepSeek's own API with an empty balance (the PC, 2026-10-26)
    elif ("not found for account" in text or "function '" in text and "not found" in text
          or "model_not_found" in text or "does not exist" in text and "model" in text):
        hold = 24 * 3600.0          # this key cannot run that model at all (NVIDIA 404 "Function ... Not found for
                                    # account", the Mac 2026-10-28: every job tried Nemotron and Kimi first and died)
    elif "timed out after" in text:
        # SLOW, not out (2026-10-28, the Mac: NVIDIA - the only route that worked - was benched "out" for one long
        # turn, so every job fell to the 9B local model): it goes to the end of the line, it is never left off
        if not provider:
            return 0.0
        data = _load(data_dir)
        entry = data.get(provider) or {}
        entry.update(t=now or time.time(), slow_until=(now or time.time()) + 3600.0, last_timeout=str(error)[:200])
        entry.pop("out", None)
        data[provider] = entry
        try:
            _file(data_dir).parent.mkdir(parents=True, exist_ok=True)
            _file(data_dir).write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError:
            pass
        return 0.0
    elif "model is unavailable" in text or "non-answer" in text:
        hold = 3600.0               # a free model that is down, or one that answered without working (a guardrail
                                    # refusal) - the PC, 2026-10-26
    else:
        return 0.0
    if not provider:
        return 0.0
    data = _load(data_dir)
    entry = data.get(provider) or {}
    entry.update(t=now or time.time(), slow_until=(now or time.time()) + hold, out=str(error)[:200])
    data[provider] = entry
    try:
        _file(data_dir).parent.mkdir(parents=True, exist_ok=True)
        _file(data_dir).write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass
    return hold


def is_out(data_dir, provider: str, now: float | None = None) -> bool:
    """Benched because it said it is out (credit, a daily or per-minute cap) - not merely slow. A timeout recorded by
    an older LOKI ("out": "timed out after ...") counts as slow only."""
    entry = _load(data_dir).get(provider) or {}
    if "timed out after" in str(entry.get("out") or ""):
        return False
    return bool(entry.get("out")) and float(entry.get("slow_until") or 0) > (now or time.time())


def is_slow(data_dir, provider: str, now: float | None = None) -> bool:
    entry = _load(data_dir).get(provider) or {}
    return float(entry.get("slow_until") or 0) > (now or time.time())


_DEAD = ("402", "credit", "insufficient balance", "insufficient_quota", "not found for account", "model_not_found",
         "does not exist", "per-day", "per day", "daily", "request too large", "tokens per minute")


def is_dead(data_dir, provider: str, now: float | None = None) -> bool:
    """Out for real while its bench lasts: no credit, a daily cap, or this key cannot run that model. A 429, a model
    that was down or one stuck turn is NOT dead - it is only tried later."""
    if not is_out(data_dir, provider, now):
        return False
    text = str((_load(data_dir).get(provider) or {}).get("out") or "").lower()
    return any(k in text for k in _DEAD)


def order(data_dir, names: list, now: float | None = None, keep=()) -> list:
    """The same providers: the working ones first, slow ones after them, ones benched for a moment (a 429, a model
    that was down) after those - tried before giving up (owner 2026-10-28: "you should go through models that are
    available try diffrent things before giving up"). Only DEAD ones are left off (no credit, a daily cap, a model the
    key cannot run). `keep` (the local model) is never left off. If everything is dead, all are kept."""
    live = [n for n in names if n in keep or not is_dead(data_dir, n, now)] or list(names)
    benched = [n for n in live if n not in keep and is_out(data_dir, n, now)]
    rest = [n for n in live if n not in benched]
    fast = [n for n in rest if not is_slow(data_dir, n, now)]
    return fast + [n for n in rest if n not in fast] + benched
