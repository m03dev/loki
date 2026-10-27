"""Client-side request pacing for providers with a requests-per-minute cap.

NVIDIA NIM's free tier allows about 40 requests a minute per account (DeepSeek V4.1 Flash,
LOKI's main driver). An agent loop, a background job and LOKI Studio can easily send more
than that together, and every request over the cap is a 429. So LOKI spaces its own requests
instead: `wait_s(provider)` says how long to wait before the next one, `take(provider)` books
a slot. The window is shared between processes (jobs, Studio) through a small file in the data
folder, so the account-wide cap is respected, not just one process's share; the file is best
effort (a lost race only means the provider's own 429 - which fails over - decides).

    LOKI_<PROVIDER>_RPM   the cap for a provider (LOKI_NVIDIA_RPM, default 36 = 40 minus headroom)
    LOKI_RATE_FILE_DIR    where the shared windows live (default <LOKI_DATA>/ratelimit)

Standard library only: LOKI Studio imports it from its pinned copy.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path

WINDOW_S = 60.0
# Default caps (requests per minute) - a little under the provider's own limit.
DEFAULT_RPM = {"nvidia": 36}
_lock = threading.Lock()
_local: dict = {}   # provider -> [timestamps] (this process)


def bucket(provider: str) -> str:
    """The account a provider's requests count against: every nvidia-* route (the main driver, nvidia-pro for Max
    mode) is the same NVIDIA key, so they share one window."""
    name = str(provider or "").strip().lower()
    return "nvidia" if name.startswith("nvidia") else name


def rpm(provider: str) -> int:
    """The requests-per-minute cap for `provider`; 0 = not paced."""
    name = bucket(provider)
    env = "LOKI_%s_RPM" % name.upper().replace("-", "_").replace(".", "_")
    raw = os.getenv(env, "")
    if raw.strip():
        try:
            return max(0, int(float(raw)))
        except ValueError:
            pass
    return int(DEFAULT_RPM.get(name, 0))


def _dir() -> Path:
    explicit = os.getenv("LOKI_RATE_FILE_DIR", "").strip()
    if explicit:
        return Path(explicit)
    data = os.getenv("LOKI_DATA", "").strip()
    return (Path(data) if data else Path(__file__).resolve().parent.parent / "harness_data") / "ratelimit"


def _file(provider: str) -> Path:
    return _dir() / ("%s.json" % "".join(c for c in provider if c.isalnum() or c in "-_"))


def _read_shared(provider: str, now: float) -> list:
    try:
        stamps = json.loads(_file(provider).read_text(encoding="utf-8"))
        return [float(t) for t in stamps if now - float(t) < WINDOW_S]
    except (OSError, ValueError, TypeError):
        return []


def _write_shared(provider: str, stamps: list) -> None:
    path = _file(provider)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".%d.tmp" % os.getpid())
        tmp.write_text(json.dumps(stamps[-500:]), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _window(provider: str, now: float) -> list:
    mine = [t for t in _local.get(provider, []) if now - t < WINDOW_S]
    _local[provider] = mine
    merged = sorted(set(mine) | set(_read_shared(provider, now)))
    return merged


def wait_s(provider: str, now: float | None = None) -> float:
    """Seconds to wait before the next request to `provider` fits its cap (0 = go now)."""
    provider = bucket(provider)
    cap = rpm(provider)
    if cap <= 0:
        return 0.0
    now = time.time() if now is None else now
    with _lock:
        stamps = _window(provider, now)
    if len(stamps) < cap:
        return 0.0
    # the oldest request inside the window has to age out first
    return max(0.0, stamps[-cap] + WINDOW_S - now + 0.05)


def take(provider: str, now: float | None = None) -> None:
    """Book a request to `provider` now."""
    provider = bucket(provider)
    if rpm(provider) <= 0:
        return
    now = time.time() if now is None else now
    with _lock:
        stamps = _window(provider, now)
        stamps.append(now)
        _local.setdefault(provider, []).append(now)
        _write_shared(provider, stamps)


def penalize(provider: str, seconds: float, now: float | None = None) -> None:
    """The provider answered 429 anyway (another program used the same key): treat the window
    as full for `seconds`, so the next requests wait instead of hammering it."""
    provider = bucket(provider)
    cap = rpm(provider)
    if cap <= 0:
        return
    now = time.time() if now is None else now
    seconds = max(1.0, min(WINDOW_S, float(seconds or 0)))
    with _lock:
        fake = [now - WINDOW_S + seconds + i * 1e-6 for i in range(cap)]   # distinct: windows are sets
        stamps = sorted(_window(provider, now) + fake)
        _local[provider] = stamps
        _write_shared(provider, stamps)


def acquire(provider: str, max_wait_s: float = 90.0, sleep=time.sleep, say=None) -> float:
    """Block until a request fits, then book it. Returns how long it waited."""
    waited = 0.0
    while True:
        delay = wait_s(provider)
        if delay <= 0 or waited >= max_wait_s:
            take(provider)
            return waited
        delay = min(delay, max_wait_s - waited)
        if say:
            say("%s allows about %d requests a minute; waiting %.0fs for a free slot." % (provider, rpm(provider), delay))
        sleep(delay)
        waited += delay


async def acquire_async(provider: str, max_wait_s: float = 90.0, say=None) -> float:
    """acquire() for an asyncio loop (the agent loop): never blocks the loop."""
    waited = 0.0
    while True:
        delay = wait_s(provider)
        if delay <= 0 or waited >= max_wait_s:
            take(provider)
            return waited
        delay = min(delay, max_wait_s - waited)
        if say:
            say("%s allows about %d requests a minute; waiting %.0fs for a free slot." % (provider, rpm(provider), delay))
        await asyncio.sleep(delay)
        waited += delay


def reset(provider: str = "") -> None:
    """Forget the windows (tests)."""
    with _lock:
        for name in ([provider] if provider else list(_local) + [p.stem for p in _dir().glob("*.json")]):
            _local.pop(name, None)
            try:
                _file(name).unlink()
            except OSError:
                pass
