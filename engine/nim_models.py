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
# Nemotron on the NVIDIA key (owner 2026-10-27: "nemotron is free in nvidia"), fastest first - Fast mode's pick. Ids
# change between releases, so when none of these is served, any chat Nemotron the key lists is taken (NEMOTRON_SKIP
# filters out the embedding / reward / safety / vision ones).
NEMOTRON = ["nvidia/nemotron-3.5-lightning-30b-a3b", "nvidia/nemotron-3.5-lightning", "nvidia/nemotron-3-nano-30b-a3b", "nvidia/nemotron-3-super-120b-a12b",
            "nvidia/llama-3.3-nemotron-super-49b-v1.5", "nvidia/llama-3.3-nemotron-super-49b-v1",
            "nvidia/nemotron-3-ultra-550b-a55b", "nvidia/llama-3.1-nemotron-ultra-253b-v1"]
NEMOTRON_SKIP = ("embed", "reward", "safety", "guard", "-vl", "vlm", "parse", "rerank", "retriever", "content", "nano-vl")
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
    if "nemotron" in low:    # nvidia-nemotron (Fast mode)
        return NEMOTRON
    return []


def resolve(model: str, ids: list) -> str:
    """The id to send: `model` when it is served (or nothing is known), else a served alias."""
    if not ids or model in ids:
        return model
    fam = family(model)
    for alt in fam:
        if alt in ids:
            return alt
    if fam is NEMOTRON:   # a newer Nemotron than this list knows: any chat Nemotron the key serves
        for i in ids:
            low = i.lower()
            if "nemotron" in low and not any(k in low for k in NEMOTRON_SKIP):
                return i
    return model


# ------------------------------------------------------------------ does the key really run it?
# NVIDIA's /models lists models a key cannot run: 2026-10-28/29 the Mac's key got HTTP 404 "Function ... Not found for
# account" for nemotron-3-super-120b and kimi-k2.6 while /models still listed them, so Fast and Max asked for them for
# days (the PC's key ran nemotron-3.5-lightning-30b-a3b in 7 s a step). So a listed id is tried once with a 1-token
# call; a 404/422 rules it out for a day (remembered on disk), a timeout or 429 says nothing (kept).
PROBE_TTL_S = 86400.0
_probes: dict = {}            # (base, model) -> (time, True | False)


def _probe_file():
    import os  # pylint: disable=import-outside-toplevel
    from pathlib import Path  # pylint: disable=import-outside-toplevel
    data = os.environ.get("LOKI_DATA") or os.environ.get("LOKI_DATA_DIR")
    return Path(data) / "nim_probe.json" if data else None


def _load_probes() -> None:
    f = _probe_file()
    if f is None or _probes:
        return
    try:
        for k, v in json.loads(f.read_text(encoding="utf-8")).items():
            base, _, model = k.partition("|")
            _probes[(base, model)] = (float(v[0]), bool(v[1]))
    except (OSError, ValueError, TypeError, IndexError):
        pass


def _save_probes() -> None:
    f = _probe_file()
    if f is None:
        return
    try:
        f.write_text(json.dumps({"%s|%s" % k: list(v) for k, v in _probes.items()}), encoding="utf-8")
    except OSError:
        pass


def runs(base_url: str, key: str, model: str, timeout: float = 25.0, opener=urllib.request.urlopen):
    """True: the key runs `model`; False: NVIDIA says it does not (404/422/400 model error); None: unknown."""
    base = (base_url or NIM_URL).rstrip("/")
    with _lock:
        _load_probes()
        hit = _probes.get((base, model))
    if hit and time.time() - hit[0] < PROBE_TTL_S:
        return hit[1]
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": "Reply with ok."}],
                       "max_tokens": 1, "stream": False}).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                          "User-Agent": "Loki/1.0"})
    verdict = None
    try:
        with opener(req, timeout=timeout) as resp:
            verdict = 200 <= int(getattr(resp, "status", 200) or 200) < 300
    except urllib.error.HTTPError as exc:
        verdict = False if exc.code in (400, 404, 410, 422) else None
    except Exception:  # noqa: BLE001 - slow or offline: no verdict
        verdict = None
    if verdict is not None:
        with _lock:
            _probes[(base, model)] = (time.time(), verdict)
            _save_probes()
    return verdict


def choose(model: str, ids: list, base_url: str, key: str, opener=urllib.request.urlopen, max_probes: int = 5) -> str:
    """The first id of `model`'s family that is listed AND not refused when tried; `model` when nothing better."""
    if not ids:
        return model
    fam = family(model)
    order = ([model] if model in ids else []) + [a for a in fam if a in ids and a != model]
    if fam is NEMOTRON:
        order += [i for i in ids if "nemotron" in i.lower() and not any(k in i.lower() for k in NEMOTRON_SKIP)
                  and i not in order]
    for cand in order[:max_probes]:
        if runs(base_url, key, cand, opener=opener) is not False:
            return cand
    return resolve(model, ids)


def fix(cfg, key: str = "", opener=urllib.request.urlopen) -> str:
    """Correct cfg.model in place (any object with base_url / model) and return what changed ('' = nothing)."""
    base = str(getattr(cfg, "base_url", "") or "")
    if "integrate.api.nvidia.com" not in base:
        return ""
    key = key or str(getattr(cfg, "api_key", "") or "")
    if not key:
        return ""
    model = str(getattr(cfg, "model", "") or "")
    better = choose(model, served(base, key, opener=opener), base, key, opener=opener)
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
