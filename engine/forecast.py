"""Forecasting in LOKI's core: TimesFM-3 (Google Research) when installed, a small statistical
forecaster otherwise. LOKI uses it to look a little ahead before it decides:

  * routing   - each provider's latency is forecast from its recent calls (usage.jsonl); the
                smart route moves a provider that is getting slow behind the ones that are not
                (loki.routing_order), instead of finding out on your next request;
  * memory    - this machine's memory use is sampled every minute and forecast; when it is about
                to run out while LOKI is idle, idle local models are unloaded BEFORE the machine
                starts swapping (what froze the Mac on 2026-10-15/16);
  * spend     - today's cost is projected to the end of the day and compared with the daily limit;
  * a tool    - `forecast_series` lets an agent forecast any numbers it is working with.

TimesFM-3 (google/timesfm-3.0-pytorch, 330M parameters): the weights are under Google's
TimesFM Non-Commercial License (personal, non-production use). LOKI never downloads them on
its own: POST /forecast/install does it when you ask (pip `timesfm[mlx]` on Apple Silicon,
`timesfm[torch]` elsewhere, then the checkpoint from Hugging Face on first use).
LOKI_FORECAST=off turns every forecast-driven decision off.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

CHECKPOINT = "google/timesfm-3.0-pytorch"
_MODEL: dict = {"state": "idle", "model": None, "kind": "", "error": "", "loaded_at": 0.0}
_LOCK = threading.Lock()
INSTALL: dict = {"running": False, "done": False, "ok": False, "log": [], "started": 0.0}


def enabled() -> bool:
    return (os.getenv("LOKI_FORECAST") or "on").strip().lower() not in ("off", "0", "false", "no")


def timesfm_available() -> bool:
    return importlib.util.find_spec("timesfm3") is not None


def _apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() in ("arm64", "aarch64")


def backend() -> str:
    if _MODEL["state"] == "ready":
        return "timesfm-3 (%s)" % _MODEL["kind"]
    return "statistical"


def _load_timesfm() -> None:
    """Load TimesFM-3 once, in the background; until it is ready the statistical forecaster answers."""
    with _LOCK:
        if _MODEL["state"] in ("loading", "ready") or not timesfm_available():
            return
        _MODEL["state"] = "loading"

    def work() -> None:
        try:
            if _apple_silicon() and importlib.util.find_spec("mlx") is not None:
                from timesfm3.mlx import TimesFM3Forecaster  # type: ignore
                model, kind = TimesFM3Forecaster.from_pretrained(CHECKPOINT), "mlx"
            else:
                from timesfm3 import ModelConfig, TimesFM3Evaluator  # type: ignore
                device = "cpu"
                try:
                    import torch  # type: ignore
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except Exception:  # noqa: BLE001
                    pass
                model, kind = TimesFM3Evaluator(ModelConfig(checkpoint_path=CHECKPOINT, per_core_batch_size=8, device=device)), device
            _MODEL.update(model=model, kind=kind, state="ready", loaded_at=time.time(), error="")
        except Exception as exc:  # noqa: BLE001 - the statistical forecaster stays in charge
            _MODEL.update(state="failed", error="%s: %s" % (type(exc).__name__, str(exc)[:300]))
    threading.Thread(target=work, daemon=True, name="loki-timesfm").start()


# --- the statistical forecaster (always available) ----------------------------------

def _holt(series: list, horizon: int, alpha: float = 0.6, beta: float = 0.35, phi: float = 0.98) -> tuple:
    """Damped-trend exponential smoothing: (forecast list, residual std)."""
    level, trend = series[0], (series[1] - series[0]) if len(series) > 1 else 0.0
    errors = []
    for x in series[1:]:
        predicted = level + phi * trend
        errors.append(x - predicted)
        new_level = alpha * x + (1 - alpha) * predicted
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    out, damp = [], 0.0
    for h in range(1, horizon + 1):
        damp += phi ** h
        out.append(level + damp * trend)
    spread = math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else abs(level) * 0.1
    return out, spread


def _statistical(series: list, horizon: int) -> dict:
    median, spread = _holt(series, horizon)
    widen = [spread * math.sqrt(h) for h in range(1, horizon + 1)]
    return {"median": median, "q10": [m - 1.2816 * w for m, w in zip(median, widen)],
            "q90": [m + 1.2816 * w for m, w in zip(median, widen)]}


def forecast(series: list, horizon: int = 12) -> dict:
    """{median, q10, q90, backend}: the next `horizon` values of `series` (oldest first)."""
    values = [float(v) for v in series if v is not None and not (isinstance(v, float) and math.isnan(v))]
    horizon = max(1, min(int(horizon), 256))
    if len(values) < 3:
        last = values[-1] if values else 0.0
        return {"median": [last] * horizon, "q10": [last] * horizon, "q90": [last] * horizon, "backend": "too-few-points"}
    if _MODEL["state"] == "idle":
        _load_timesfm()
    if _MODEL["state"] == "ready" and len(values) >= 8:
        try:
            import numpy as np  # type: ignore
            arr = np.asarray(values[-2048:], dtype=np.float32)
            model = _MODEL["model"]
            if _MODEL["kind"] == "mlx":
                out = model.predict(arr, horizon=horizon, return_quantiles=True)
            else:
                out = list(model.predict_batch([arr], horizon=horizon, return_quantiles=True, use_symmetric_averaging=False))[0]
            q = out.quantiles   # (horizon, 9): deciles 0.1 .. 0.9
            return {"median": [float(x) for x in out.forecast], "q10": [float(r[0]) for r in q],
                    "q90": [float(r[8]) for r in q], "backend": backend()}
        except Exception as exc:  # noqa: BLE001
            _MODEL["error"] = "forecast failed, using statistics: %s" % str(exc)[:200]
    return {**_statistical(values, horizon), "backend": "statistical"}


# --- routing: which providers are getting slow -------------------------------------

def provider_outlook(entries: list, min_points: int = 6, window_s: float = 3 * 86400) -> dict:
    """provider -> {p50_ms, p90_ms, last_ms, n} for the next calls, from recent latencies."""
    now = time.time()
    by: dict = {}
    for e in entries:
        if e.get("t", 0) >= now - window_s and e.get("ms"):
            by.setdefault(e.get("provider", "?"), []).append(float(e["ms"]))
    out = {}
    for provider, ms in by.items():
        if len(ms) < min_points:
            continue
        f = forecast(ms[-200:], horizon=3)
        out[provider] = {"p50_ms": int(max(0, sum(f["median"]) / 3)), "p90_ms": int(max(0, max(f["q90"]))),
                         "last_ms": int(ms[-1]), "n": len(ms), "backend": f["backend"]}
    return out


def reorder(order: list, outlook: dict, factor: float = 2.5) -> list:
    """`order` with providers forecast to be much slower than the best forecast moved back.
    Order is otherwise kept (it already encodes tiers and what has worked)."""
    if not enabled() or not outlook:
        return list(order)
    known = [outlook[p]["p50_ms"] for p in order if p in outlook and outlook[p]["p50_ms"] > 0]
    if len(known) < 2:
        return list(order)
    best = min(known)
    slow = [p for p in order if p in outlook and outlook[p]["p50_ms"] > factor * best and outlook[p]["p50_ms"] > 4000]
    return [p for p in order if p not in slow] + slow


# --- memory: unload before the machine swaps ---------------------------------------

MEMORY: dict = {"samples": [], "last": {}, "actions": []}


def memory_used() -> float | None:
    """Fraction of RAM in use right now (0..1), from the OS's own tools; None if unknown."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "kern.memorystatus_level"], capture_output=True, text=True, timeout=5).stdout.strip()
            return 1 - int(out) / 100.0 if out.isdigit() else None
        if sys.platform == "win32":
            import ctypes  # pylint: disable=import-outside-toplevel

            class MEM(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
                           [(n, ctypes.c_ulonglong) for n in ("total", "avail", "pagefile", "availpage", "virt", "availvirt", "ext")]
            m = MEM()
            m.dwLength = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.dwMemoryLoad / 100.0
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                key, value = line.split(":", 1)
                info[key] = float(value.split()[0])
        return 1 - info["MemAvailable"] / info["MemTotal"]
    except Exception:  # noqa: BLE001
        return None


def memory_tick(busy: bool, unload, sample=memory_used, limit: float = 0.92, now: float | None = None) -> dict:
    """One minute of the memory guard: sample, forecast the next 10 minutes, and when memory is
    about to run out while LOKI is idle, call unload() (which frees idle local models)."""
    now = now or time.time()
    used = sample()
    if used is None:
        return {"ok": False, "error": "memory use is not readable here"}
    samples = MEMORY["samples"]
    samples.append(round(used, 4))
    del samples[:-240]
    f = forecast(samples, horizon=10) if len(samples) >= 5 else {"median": [used] * 10, "q90": [used] * 10, "backend": "warming-up"}
    peak = min(1.0, max(f["median"]))
    result = {"ok": True, "used": used, "forecast_peak": round(peak, 3), "backend": f["backend"], "action": ""}
    recent = MEMORY["actions"] and now - MEMORY["actions"][-1]["t"] < 120     # give the OS time to reclaim
    if enabled() and not busy and not recent and used >= limit - 0.08 and peak >= limit:
        freed = unload()
        if freed:
            result["action"] = "unloaded %s (memory heading to %d%%)" % (", ".join(freed), round(peak * 100))
            MEMORY["actions"].append({"t": now, "used": used, "peak": peak, "freed": freed})
            del MEMORY["actions"][:-20]
    MEMORY["last"] = result
    return result


def ollama_unload_idle(base: str = "http://127.0.0.1:11434", opener=None) -> list:
    """Unload every model Ollama has loaded (keep_alive=0). Returns their names."""
    import json  # pylint: disable=import-outside-toplevel
    import urllib.request  # pylint: disable=import-outside-toplevel
    opener = opener or urllib.request.urlopen
    try:
        with opener(base + "/api/ps", timeout=4) as resp:
            loaded = [m.get("name") for m in json.loads(resp.read().decode()).get("models", []) if m.get("name")]
    except Exception:  # noqa: BLE001
        return []
    freed = []
    for name in loaded:
        try:
            req = urllib.request.Request(base + "/api/generate", data=json.dumps({"model": name, "keep_alive": 0}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with opener(req, timeout=10):
                freed.append(name)
        except Exception:  # noqa: BLE001
            pass
    return freed


# --- spend: where today is heading -------------------------------------------------

def spend_outlook(entries: list, daily_limit: float = 0.0, now: float | None = None) -> dict:
    now = now or time.time()
    start = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    hours = [0.0] * 24
    for e in entries:
        if e.get("t", 0) >= start:
            hours[min(23, int((e["t"] - start) // 3600))] += float(e.get("cost") or 0)
    current_hour = min(23, int((now - start) // 3600))
    spent = sum(hours[:current_hour + 1])
    remaining = 23 - current_hour
    projected = spent
    if remaining > 0 and current_hour >= 2:
        f = forecast(hours[:current_hour + 1], horizon=remaining)
        projected = spent + sum(max(0.0, x) for x in f["median"])
    out = {"spent_today": round(spent, 4), "projected_today": round(projected, 4)}
    if daily_limit > 0:
        out["limit"] = daily_limit
        out["will_exceed"] = projected > daily_limit
    return out


# --- installing TimesFM-3 (only when asked) ---------------------------------------

def install(python: str = sys.executable) -> dict:
    """pip install timesfm[mlx|torch] into LOKI's own Python, in the background."""
    if INSTALL["running"]:
        return {"ok": True, "running": True}
    extra = "mlx" if _apple_silicon() else "torch"
    INSTALL.update(running=True, done=False, ok=False, log=["pip install timesfm[%s] (Google TimesFM; the 3.0 weights "
                                                             "are for non-commercial use)" % extra], started=time.time())

    def work() -> None:
        try:
            proc = subprocess.run([python, "-m", "pip", "install", "--upgrade", "timesfm[%s]" % extra],
                                  capture_output=True, text=True, timeout=3600)
            INSTALL["log"].extend((proc.stdout + proc.stderr).splitlines()[-20:])
            INSTALL["ok"] = proc.returncode == 0
            if INSTALL["ok"]:
                importlib.invalidate_caches()
                _MODEL["state"] = "idle"
                _load_timesfm()
        except Exception as exc:  # noqa: BLE001
            INSTALL["log"].append("failed: %s" % exc)
        finally:
            INSTALL.update(running=False, done=True)
    threading.Thread(target=work, daemon=True, name="loki-timesfm-install").start()
    return {"ok": True, "running": True}


APPROVALS = Path(__file__).with_name("data") / "owner_approvals.json"


def approved() -> bool:
    """The owner allowed TimesFM-3 (its weights are non-commercial; LOKI is his private tool):
    engine/data/owner_approvals.json, or LOKI_TIMESFM_APPROVED=1. LOKI_TIMESFM_APPROVED=0 says no."""
    flag = os.getenv("LOKI_TIMESFM_APPROVED", "").strip().lower()
    if flag in ("0", "no", "false", "off"):
        return False
    if flag in ("1", "yes", "true", "on"):
        return True
    try:
        return bool(json.loads(APPROVALS.read_text(encoding="utf-8")).get("timesfm"))
    except (OSError, ValueError):
        return False


def install_if_approved() -> dict:
    """At start-up: install TimesFM once, in the background, if approved and not there yet."""
    if not approved() or timesfm_available() or INSTALL["running"] or INSTALL["done"]:
        return {"ok": True, "skipped": True}
    return install()


def status() -> dict:
    return {"enabled": enabled(), "backend": backend(), "timesfm_installed": timesfm_available(),
            "timesfm": {k: _MODEL[k] for k in ("state", "kind", "error", "loaded_at")}, "install": dict(INSTALL),
            "memory": MEMORY["last"], "memory_actions": MEMORY["actions"][-5:],
            "licence": "TimesFM 3.0 weights: TimesFM Non-Commercial License v1.0 (personal, non-production use)"}
