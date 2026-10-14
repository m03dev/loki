"""Ollama worker federation - use the other machines' GPUs when they are up.

Configure the machines in harness_data/.env:

    LOKI_WORKERS=pc=http://192.168.1.50:11434,mac=http://127.0.0.1:11434

Each worker is an Ollama server. `health()` asks each one for /api/tags with a short
timeout and reports whether it is up and which models it has. `route()` picks where a
local-model request should go: the configured endpoint when it is up and has the model,
otherwise the first healthy worker that has it. Nothing is routed to a host that is not
listed in LOKI_WORKERS, and nothing here runs code on a worker.

On the worker: run `ollama serve` with OLLAMA_HOST=0.0.0.0 so the LAN can reach it, and
pull the model (`ollama pull qwen2.5-coder:7b`). The RTX 3070 Ti (8 GB) runs 7-8B models at
Q4 comfortably.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

PROBE_TIMEOUT_S = 2.0
CACHE_S = 20.0
_cache: dict[str, tuple[float, dict]] = {}


def workers(env: dict | None = None) -> list[dict]:
    """[{name, base}] from LOKI_WORKERS ("name=url,name=url" or bare urls)."""
    env = env if env is not None else os.environ
    out = []
    for i, item in enumerate(str(env.get("LOKI_WORKERS", "")).split(",")):
        item = item.strip()
        if not item:
            continue
        name, _, url = item.partition("=") if "=" in item else ("worker%d" % (i + 1), "", item)
        url = url.strip().rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.hostname:
            out.append({"name": name.strip() or "worker%d" % (i + 1), "base": url})
    return out


def _ollama_root(base_url: str) -> str:
    url = base_url.rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


def probe(base: str, timeout: float = PROBE_TIMEOUT_S, opener=urllib.request.urlopen,
          use_cache: bool = True) -> dict:
    """{ok, models, ms, error} for one Ollama server."""
    root = _ollama_root(base)
    cached = _cache.get(root)
    if use_cache and cached and time.time() - cached[0] < CACHE_S:
        return cached[1]
    started = time.time()
    try:
        with opener(root + "/api/tags", timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
        models = sorted(m.get("name", "") for m in data.get("models", []) if isinstance(m, dict))
        result = {"ok": True, "models": models, "ms": int((time.time() - started) * 1000), "error": ""}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result = {"ok": False, "models": [], "ms": int((time.time() - started) * 1000), "error": str(exc)[:160]}
    _cache[root] = (time.time(), result)
    return result


def has_model(models: list[str], wanted: str) -> bool:
    """Ollama names carry a tag; 'qwen3:8b' matches 'qwen3:8b', 'qwen3' matches 'qwen3:latest'."""
    wanted = wanted.strip()
    if ":" not in wanted:
        wanted += ":latest"
    return wanted in models


def health(env: dict | None = None, opener=urllib.request.urlopen) -> list[dict]:
    return [{**w, **probe(w["base"], opener=opener)} for w in workers(env)]


def route(base_url: str, model: str, env: dict | None = None, opener=urllib.request.urlopen) -> tuple[str, str]:
    """(base_url to use, note). Only ever returns the configured URL or a listed worker."""
    if not workers(env):
        return base_url, ""
    here = probe(base_url, opener=opener)
    if here["ok"] and has_model(here["models"], model):
        return base_url, ""
    for worker in workers(env):
        if _ollama_root(worker["base"]) == _ollama_root(base_url):
            continue
        state = probe(worker["base"], opener=opener)
        if state["ok"] and has_model(state["models"], model):
            return worker["base"] + "/v1", "routed %s to worker %s" % (model, worker["name"])
    return base_url, ""


def is_ollama(base_url: str) -> bool:
    return ":11434" in base_url or "ollama" in base_url.lower() and "ollama.com" not in base_url.lower()
