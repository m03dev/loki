"""Which model ids NVIDIA NIM really serves, so LOKI never asks for one it does not have.

NVIDIA lists DeepSeek V4.1 Flash under more than one name (deepseek-ai/deepseek-v4.1-flash on
build.nvidia.com, nvidia/deepseek-v4.1-flash in its API reference) and renames models now and
then. Asking for a name it does not serve answers HTTP 404 (the owner's Mac, 2026-10-17:
"error 404 http not found"). So before LOKI or Studio use the NIM driver, they read NIM's own
/models list once (cached) and, when the configured id is missing, switch to the first name
of the same model that is listed.

No key, no network, or an empty list: the configured id is kept as it is.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

NIM_URL = "https://integrate.api.nvidia.com/v1"
# the same model under its known names, best first; the older V4 Flash is the last resort
DEEPSEEK_FLASH = ["deepseek-ai/deepseek-v4.1-flash", "nvidia/deepseek-v4.1-flash", "deepseek-ai/deepseek-v4-flash"]
# Max mode's "strongest free model on the NVIDIA key", best first (2026-10 agentic rankings: GLM-5.3 is the top open
# model; DeepSeek V4 Pro where a key has it; Kimi K2.6; Nemotron 3 Ultra). The PC's key (2026-10-27) had no DeepSeek V4
# Pro - Max asked for it, got model_missing, and every Max job fell to weaker routes. The first one the key serves wins.
STRONGEST = ["z-ai/glm-5.3", "deepseek-ai/deepseek-v4-pro", "deepseek-ai/deepseek-v4-pro-0813", "moonshotai/kimi-k3",
             "moonshotai/kimi-k2.6", "nvidia/nemotron-3-ultra-550b-a55b", "nvidia/llama-3.1-nemotron-ultra-253b-v1"]
TTL_S = 3600.0
_cache: dict = {}            # base_url -> (time, [ids])
_lock = threading.Lock()


def served(base_url: str = NIM_URL, key: str = "", timeout: float = 6.0, opener=urllib.request.urlopen) -> list:
    """NIM's model ids (cached for an hour). [] when it cannot be read."""
    base = (base_url or NIM_URL).rstrip("/")
    with _lock:
        hit = _cache.get(base)
        if hit and time.time() - hit[0] < TTL_S:
            return list(hit[1])
    headers = {"Accept": "application/json", "User-Agent": "Loki/1.0"}
    if key:
        headers["Authorization"] = "Bearer " + key
    try:
        with opener(urllib.request.Request(base + "/models", headers=headers), timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except (OSError, ValueError, urllib.error.URLError):
        return []
    items = data.get("data", []) if isinstance(data, dict) else data
    ids = [str(i.get("id")) for i in (items or []) if isinstance(i, dict) and i.get("id")]
    if ids:
        with _lock:
            _cache[base] = (time.time(), ids)
    return ids


def cached(base_url: str = NIM_URL, key: str = "") -> list:
    """What served() last read, without waiting on the network; starts a read in the background
    when there is a key and nothing fresh yet (for callers that must answer instantly)."""
    base = (base_url or NIM_URL).rstrip("/")
    with _lock:
        hit = _cache.get(base)
    if hit and time.time() - hit[0] < TTL_S:
        return list(hit[1])
    if key and "integrate.api.nvidia.com" in base:
        threading.Thread(target=served, args=(base, key), daemon=True, name="loki-nim-models").start()
    return list(hit[1]) if hit else []


def family(model: str) -> list:
    """The other names of the same model (in preference order), or [] for a model we do not know."""
    low = str(model or "").lower()
    if "deepseek-v4" in low and "flash" in low:
        return DEEPSEEK_FLASH
    if model in STRONGEST:   # nvidia-pro (Max mode): whichever of the strongest ones this key serves
        return STRONGEST
    return []


def resolve(model: str, ids: list) -> str:
    """The id to send: `model` when it is served (or nothing is known), else a served alias."""
    if not ids or model in ids:
        return model
    for alt in family(model):
        if alt in ids:
            return alt
    return model


def fix(cfg, key: str = "", opener=urllib.request.urlopen) -> str:
    """Correct cfg.model in place (any object with base_url / model) and return what changed ('' = nothing)."""
    base = str(getattr(cfg, "base_url", "") or "")
    if "integrate.api.nvidia.com" not in base:
        return ""
    key = key or str(getattr(cfg, "api_key", "") or "")
    if not key:
        return ""
    model = str(getattr(cfg, "model", "") or "")
    better = resolve(model, served(base, key, opener=opener))
    if better != model:
        cfg.model = better
        return "%s -> %s" % (model, better)
    return ""


def fix_later(cfg, key: str = "", on_change=None) -> None:
    """fix() on a background thread, so a slow NVIDIA never delays a start."""
    def run():
        try:
            changed = fix(cfg, key)
        except Exception:  # noqa: BLE001
            return
        if changed and on_change is not None:
            try:
                on_change(changed)
            except Exception:  # noqa: BLE001
                pass
    threading.Thread(target=run, daemon=True, name="loki-nim-models").start()
