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


def is_slow(data_dir, provider: str, now: float | None = None) -> bool:
    entry = _load(data_dir).get(provider) or {}
    return float(entry.get("slow_until") or 0) > (now or time.time())


def order(data_dir, names: list, now: float | None = None) -> list:
    """The same providers, the slow ones moved to the end (kept: better slow than nothing)."""
    fast = [n for n in names if not is_slow(data_dir, n, now)]
    return fast + [n for n in names if n not in fast]
