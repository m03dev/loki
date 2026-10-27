"""Every model provider LOKI can connect to, described for the Connections portal.

The portal (Settings > Connections) shows one card per provider: what it is, whether it is
free, how to connect (paste a key, sign in, scan a QR code on your phone, nothing at all),
a switch to turn it on or off, a Test button, and the models it offers. This module is the
data behind those cards plus the few actions they need. The endpoints themselves stay in
loki.MODELS; this file only describes them and checks them.

Groups (shown as sections):
  local         runs on your own machine (Ollama, LM Studio, llama.cpp, MLX, vLLM, Jan, Kyojin)
  free          a standing free tier (no card)
  keyless       works with no account at all (prompts go to a third party)
  trial         free credits that run out
  subscription  a coding agent you already pay for (Claude Code, Codex, OpenCode)
  paid          pay per token

Facts were checked in October 2026 (cheahjs/free-llm-api-resources, provider docs);
limits change often, so every card links to the provider's own page.
GitHub Models was retired on 2026-07-30 and is deliberately not listed.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# auth: "key" paste a key | "oauth" sign in in the browser (OpenRouter PKCE) |
#       "device" sign in with a code (RFC 8628, needs LOKI_<ID>_CLIENT_ID) |
#       "none" nothing to set up | "cli" a signed-in command-line agent
CATALOG: list[dict] = [
    # ----------------------------------------------------------------- local
    {"id": "local", "name": "Ollama", "group": "local", "auth": ["none"], "tools": True,
     "blurb": "Local models on this computer. Works offline. LOKI picks the best installed model.",
     "signup": "https://ollama.com/download", "docs": "https://docs.ollama.com"},
    {"id": "9router", "name": "9Router", "group": "local", "auth": ["key"], "tools": True, "env": "NINEROUTER_API_KEY",
     "blurb": "One local router for your Claude Code / Codex / Copilot subscriptions, free tiers and keys, with fallback "
              "chains. Install: python tools/setup_extras.py 9router; LOKI starts it on 127.0.0.1:20128. Paste the key "
              "from its dashboard (http://127.0.0.1:20128/dashboard); name a combo 'loki' to pick what LOKI uses.",
     "signup": "https://github.com/decolua/9router", "docs": "https://github.com/decolua/9router#readme"},
    {"id": "lmstudio", "name": "LM Studio", "group": "local", "auth": ["none"], "tools": True,
     "blurb": "Local server from LM Studio (Developer tab > Start server, port 1234).",
     "signup": "https://lmstudio.ai", "docs": "https://lmstudio.ai/docs/app/api"},
    {"id": "llamacpp", "name": "llama.cpp server", "group": "local", "auth": ["none"], "tools": True,
     "blurb": "llama-server on port 8080. Start it with --jinja for native tool calls; without it LOKI uses prompted tools.",
     "signup": "https://github.com/ggml-org/llama.cpp", "docs": "https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md"},
    {"id": "mlx", "name": "MLX (Apple Silicon)", "group": "local", "auth": ["none"], "tools": False, "platform": "darwin",
     "blurb": "mlx_lm.server on the Mac: fastest local inference on Apple Silicon. Tools go through LOKI's prompted harness.",
     "signup": "https://github.com/ml-explore/mlx-lm", "docs": "https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md",
     "setup": "pip install mlx-lm && mlx_lm.server --model mlx-community/Qwen3-4B-4bit --port 8082"},
    {"id": "colibri", "name": "colibri (big models, offloaded)", "group": "local", "auth": ["none"], "tools": True,
     "blurb": "Big MoE models with the experts offloaded to the SSD and GPU - Qwen3.6-35B at ~25-30 tok/s on an 8 GB RTX card. Start it with `coli serve` (port 8000).",
     "signup": "https://github.com/JustVugg/colibri", "docs": "https://github.com/JustVugg/colibri#readme"},
    {"id": "vllm", "name": "vLLM", "group": "local", "auth": ["none"], "tools": True,
     "blurb": "vLLM OpenAI server (port 8000), for an NVIDIA GPU machine.",
     "signup": "https://docs.vllm.ai", "docs": "https://docs.vllm.ai/en/latest/features/tool_calling.html"},
    {"id": "jan", "name": "Jan", "group": "local", "auth": ["none"], "tools": True,
     "blurb": "Jan's local API server (port 1337).", "signup": "https://jan.ai", "docs": "https://jan.ai/docs"},
    # ----------------------------------------------------------------- free
    {"id": "nvidia", "name": "NVIDIA NIM", "group": "free", "auth": ["key"], "tools": True,
     "env": "NVIDIA_API_KEY", "main_driver": True,
     "setup": "Get a free key at build.nvidia.com (Settings > API Keys) and paste it here - that is all.",
     "blurb": "LOKI's main driver: DeepSeek V4.1 Flash, free (about 40 requests/min, LOKI paces itself), "
              "1M context, calls tools. Get a free key at build.nvidia.com and paste it here.",
     "signup": "https://build.nvidia.com", "keys": "https://build.nvidia.com/settings/api-keys", "docs": "https://docs.api.nvidia.com"},
    {"id": "huggingface", "name": "Hugging Face", "group": "free", "auth": ["device", "key"], "tools": True,
     "env": "HF_TOKEN", "blurb": "Your token for downloading local models (some need it). Not used for chat.",
     "signup": "https://huggingface.co/join", "keys": "https://huggingface.co/settings/tokens", "docs": "https://huggingface.co/docs/inference-providers"},
    # ----------------------------------------------------------------- keyless
    # ----------------------------------------------------------------- trial
    # ----------------------------------------------------------------- subscription
    {"id": "claude-code", "name": "Claude Code", "group": "subscription", "auth": ["cli"], "tools": True,
     "blurb": "Your Claude subscription as a coding agent. Install, then run `claude` and /login once.",
     "signup": "https://claude.com/product/claude-code", "docs": "https://docs.claude.com/en/docs/claude-code/overview",
     "setup": "npm install -g @anthropic-ai/claude-code"},
    {"id": "codex", "name": "Codex", "group": "subscription", "auth": ["cli"], "tools": True,
     "blurb": "Your ChatGPT subscription as a coding agent. Install, then `codex login`.",
     "signup": "https://developers.openai.com/codex", "docs": "https://developers.openai.com/codex", "setup": "npm install -g @openai/codex"},
    {"id": "opencode", "name": "OpenCode", "group": "subscription", "auth": ["cli"], "tools": True,
     "blurb": "Open-source coding agent; works with any provider (including Zen's free models). Install, then `opencode auth login`.",
     "signup": "https://opencode.ai", "docs": "https://opencode.ai/docs/cli/", "setup": "npm i -g opencode-ai@latest"},
    # ----------------------------------------------------------------- paid
    {"id": "deepseek", "name": "DeepSeek", "group": "paid", "auth": ["key"], "tools": True,
     "env": "DEEPSEEK_API_KEY", "blurb": "DeepSeek V4.1 Flash, very cheap ($0.15/M in off-peak).",
     "signup": "https://platform.deepseek.com", "keys": "https://platform.deepseek.com/api_keys", "docs": "https://api-docs.deepseek.com"},
    {"id": "gpt", "name": "OpenAI", "group": "paid", "auth": ["key"], "tools": True, "env": "OPENAI_API_KEY",
     "blurb": "GPT models, pay per token.", "signup": "https://platform.openai.com", "keys": "https://platform.openai.com/api-keys",
     "docs": "https://platform.openai.com/docs"},
    {"id": "claude", "name": "Anthropic API", "group": "paid", "auth": ["key"], "tools": True, "env": "ANTHROPIC_API_KEY",
     "blurb": "Claude models, pay per token.", "signup": "https://console.anthropic.com", "keys": "https://console.anthropic.com/settings/keys",
     "docs": "https://docs.claude.com"},
]

GROUPS = [("local", "On this computer"), ("free", "Free tiers"), ("keyless", "No account needed"),
          ("trial", "Free credits"), ("subscription", "Your subscriptions"), ("paid", "Pay per use")]

_BY_ID = {p["id"]: p for p in CATALOG}
# Same NVIDIA key, a second model: the strongest open one (GLM-5.3) for Max mode (loki.py MAX_ORDER). Looked up by id for its name and
# blurb, but not a row in CATALOG - Connections keeps ONE NVIDIA key field.
_BY_ID["nvidia-pro"] = dict(_BY_ID["nvidia"], id="nvidia-pro", name="GLM-5.3 (NVIDIA)", main_driver=False,
                            blurb="The strongest free open model your NVIDIA key serves (GLM-5.3 by default, "
                                  "nim_models.STRONGEST): calls tools, thinks before it answers. Slower than Flash - "
                                  "Max mode uses it for hard tasks.")
# Nemotron on the same key (owner 2026-10-27: "nemotron is free in nvidia"): Fast mode's first pick, no daily cap.
_BY_ID["nvidia-nemotron"] = dict(_BY_ID["nvidia"], id="nvidia-nemotron", name="Nemotron (NVIDIA)", main_driver=False,
                                 blurb="NVIDIA's own fast Nemotron model on your NVIDIA key - free, only the per-minute "
                                       "limit LOKI already paces, no daily cap. Fast mode uses it first.")
_TESTS: dict = {}          # id -> {"ok", "detail", "at", "ms"}
_MODELS_CACHE: dict = {}   # id -> (at, [model ids])


def get(provider_id: str) -> dict | None:
    return _BY_ID.get((provider_id or "").strip().lower())


def disabled(env: dict | None = None) -> set:
    env = env if env is not None else os.environ
    return {p.strip().lower() for p in str(env.get("LOKI_DISABLED_PROVIDERS", "")).split(",") if p.strip()}


def env_var(provider_id: str) -> str:
    entry = get(provider_id) or {}
    return entry.get("env", "")


def present(agent: Any, env: dict | None = None) -> dict:
    """The portal: every provider with its live state. Never includes a key."""
    env = env if env is not None else os.environ
    off = disabled(env)
    current = getattr(agent, "model_name", "")
    try:
        resolved = agent.active_model_name()
    except Exception:  # noqa: BLE001
        resolved = current
    order = list(getattr(agent, "SMART_ORDER", ()))
    try:
        import provider_health  # pylint: disable=import-outside-toplevel
        health = provider_health.registry().snapshot()
    except Exception:  # noqa: BLE001 - the cards work without it
        provider_health, health = None, {}
    cards = []
    for entry in CATALOG:
        pid = entry["id"]
        if entry.get("platform") and entry["platform"] != __import__("sys").platform and pid not in agent.MODELS:
            continue
        cfg = agent.MODELS.get(pid)
        try:
            configured = bool(agent.provider_configured(pid)) if cfg is not None else False
        except Exception:  # noqa: BLE001
            configured = False
        has_key = bool(entry.get("env") and str(env.get(entry["env"], "")).strip())
        card = {k: v for k, v in entry.items()}
        card.update({
            "available": cfg is not None, "configured": configured, "has_key": has_key,
            "enabled": pid not in off, "metered": bool(getattr(agent, "is_metered", lambda _n: False)(pid)),
            "in_smart": pid in order, "default": pid == current, "active": pid == resolved,
            "model": cfg.model if cfg is not None else "",
            "base_url": cfg.base_url if cfg is not None and not cfg.base_url.startswith("cli-agent://") else "",
            "test": _TESTS.get(pid),
            "prompted_tools": _prompted(pid),
        })
        h = health.get(pid)
        if h and provider_health is not None:
            # The live state routing uses: "free quota used up (back in 40 min)" + a one-line fix.
            card["health"] = {"state": h.get("state"), "label": h.get("label"), "line": h.get("line"),
                              "live": h.get("live"), "fix": provider_health.fix_for(pid, h, entry),
                              "latency_ms": h.get("latency_ms"), "model_info": h.get("model_info") or {},
                              "probe_at": h.get("probe_at"), "at": h.get("at")}
        cards.append(card)
    connected = sum(1 for c in cards if c["configured"] and c["enabled"])
    return {"providers": cards, "groups": [{"id": g, "label": label} for g, label in GROUPS],
            "connected": connected, "default": current, "active": resolved}


def _prompted(pid: str) -> bool:
    try:
        import tool_harness  # pylint: disable=import-outside-toplevel
        return tool_harness.configured(pid)
    except Exception:  # noqa: BLE001
        return False


def _request(url: str, key: str, timeout: float, body: dict | None = None,
             opener=urllib.request.urlopen) -> tuple:
    headers = {"User-Agent": "Loki/1.0", "Accept": "application/json"}
    if key and key not in ("none", "ollama"):
        headers["Authorization"] = "Bearer " + key
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    with opener(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8") or "{}")


def list_models(agent: Any, pid: str, timeout: float = 8.0, opener=urllib.request.urlopen,
                max_age: float = 600.0) -> dict:
    """The model ids a provider offers (its /models list), cached for a few minutes."""
    cfg = agent.MODELS.get(pid)
    if cfg is None or cfg.base_url.startswith("cli-agent://"):
        return {"ok": False, "error": "this provider has no model list"}
    cached = _MODELS_CACHE.get(pid)
    if cached and time.time() - cached[0] < max_age:
        return {"ok": True, "models": cached[1], "cached": True}
    try:
        _, data = _request(cfg.base_url.rstrip("/") + "/models", str(cfg.api_key or ""), timeout, opener=opener)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": "the provider answered HTTP %d" % exc.code}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "could not reach it (%s)" % type(exc).__name__}
    items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
    ids = []
    for item in items or []:
        mid = item.get("id") or item.get("name") if isinstance(item, dict) else str(item)
        if mid:
            ids.append(str(mid))
    ids = sorted(set(ids), key=lambda m: (":free" not in m and "free" not in m, m))[:400]
    _MODELS_CACHE[pid] = (time.time(), ids)
    return {"ok": True, "models": ids}


def _test_body(pid: str, cfg) -> dict:
    """The Test request: what a real chat sends, cut down to one short answer. DeepSeek on NVIDIA
    NIM gets the same thinking-off switch the agent uses (loki._provider_kwargs) - without it the
    model reasons first and the free queue made Test time out although the key was fine."""
    body = {"model": cfg.model, "max_tokens": 8, "messages": [{"role": "user", "content": "Say OK"}]}
    model, url = str(cfg.model or "").lower(), str(cfg.base_url or "")
    if "deepseek" in model and (pid == "nvidia" or "integrate.api.nvidia.com" in url):
        body["chat_template_kwargs"] = {"thinking": False}
    return body


def _diagnose_timeout(pid: str, cfg, opener) -> str:
    """After a timed-out Test: can we reach the provider at all, and does it offer this model?"""
    try:
        _, data = _request(cfg.base_url.rstrip("/") + "/models", str(cfg.api_key or ""), 10.0, opener=opener)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return "the provider is reachable but refused the key (HTTP %d)" % exc.code
        return "the provider is reachable (HTTP %d on its model list) but did not answer in time" % exc.code
    except Exception as exc:  # noqa: BLE001
        host = urllib.parse.urlparse(cfg.base_url).hostname or cfg.base_url
        return ("this computer cannot reach %s (%s) - check the internet connection, a VPN, or a "
                "firewall/antivirus blocking LOKI's Python" % (host, type(exc).__name__))
    items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
    ids = [str((i.get("id") or i.get("name")) if isinstance(i, dict) else i) for i in (items or [])]
    if ids and cfg.model not in ids:
        family = str(cfg.model).split("/")[-1].split("-")[0].lower()
        close = [m for m in ids if family and family in m.lower()][:4]
        return ("%s is not in this provider's model list%s - pick another model in the list next to Test"
                % (cfg.model, (" (it offers " + ", ".join(close) + ")") if close else ""))
    return ("the key and the connection work, but %s took too long to answer (the free queue is busy) - "
            "LOKI keeps it and retries; press Test again in a minute" % cfg.model)


def test(agent: Any, pid: str, timeout: float = 45.0, opener=urllib.request.urlopen) -> dict:
    """One tiny real request (a few-token completion) so the card can say "works" honestly."""
    cfg = agent.MODELS.get(pid)
    if cfg is None:
        return {"ok": False, "error": "unknown provider"}
    started = time.monotonic()
    if cfg.base_url.startswith("cli-agent://"):
        ok = bool(agent.provider_configured(pid))
        result = {"ok": ok, "detail": "installed (sign-in is checked on first use)" if ok else "not installed"}
    else:
        try:   # NVIDIA renames models; use the name it really serves (engine/nim_models.py)
            import nim_models  # pylint: disable=import-outside-toplevel
            nim_models.fix(cfg, opener=opener)
        except Exception:  # noqa: BLE001
            pass
        try:
            status, data = _request(cfg.base_url.rstrip("/") + "/chat/completions", str(cfg.api_key or ""), timeout,
                                    body=_test_body(pid, cfg), opener=opener)
            model = data.get("model", cfg.model) if isinstance(data, dict) else cfg.model
            result = {"ok": 200 <= status < 300, "detail": "answered with %s" % model}
            if result["ok"]:
                try:
                    import provider_health  # pylint: disable=import-outside-toplevel
                    provider_health.registry().record_success(pid, (time.monotonic() - started) * 1000,
                                                              key=str(cfg.api_key or ""))
                except Exception:  # noqa: BLE001
                    pass
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read().decode("utf-8", "replace")).get("error", "")
                if isinstance(detail, dict):
                    detail = detail.get("message", "")
            except Exception:  # noqa: BLE001
                pass
            hint = {401: "the key was rejected", 403: "the key has no access to this model",
                    404: "the model name is not available here", 429: "rate limited right now (the key works)",
                    402: "no credit left"}.get(exc.code, "HTTP %d" % exc.code)
            result = {"ok": exc.code == 429, "detail": (hint + (": " + str(detail)[:140] if detail else ""))}
            try:   # what the Test button learned steers routing too (provider_health)
                import provider_health  # pylint: disable=import-outside-toplevel
                provider_health.registry().record_failure(pid, "HTTP %d: %s" % (exc.code, detail), exc.code,
                                                          key=str(cfg.api_key or ""), session=False)
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            reason = getattr(exc, "reason", exc)
            if isinstance(exc, TimeoutError) or isinstance(reason, (TimeoutError, socket.timeout)):
                result = {"ok": False, "detail": "no answer in %d s: %s" % (timeout, _diagnose_timeout(pid, cfg, opener))}
            else:
                result = {"ok": False, "detail": "could not reach %s (%s)" % (cfg.base_url, type(exc).__name__)}
    result.update({"at": time.time(), "ms": int((time.monotonic() - started) * 1000)})
    _TESTS[pid] = result
    return {"ok": True, "provider": pid, "test": result}


def set_enabled(pid: str, on: bool, write_env, env: dict | None = None) -> dict:
    """Turn a provider on or off (LOKI_DISABLED_PROVIDERS); off ones are never routed to."""
    if get(pid) is None:
        return {"ok": False, "error": "unknown provider"}
    off = disabled(env)
    if on:
        off.discard(pid)
    else:
        off.add(pid)
    write_env({"LOKI_DISABLED_PROVIDERS": ",".join(sorted(off)) or None})
    return {"ok": True, "provider": pid, "enabled": on}


def set_model(agent: Any, pid: str, model: str, write_env) -> dict:
    """Pick which model a provider uses (<PROVIDER>_MODEL)."""
    cfg = agent.MODELS.get(pid)
    model = str(model or "").strip()
    if cfg is None or not model or len(model) > 200:
        return {"ok": False, "error": "pick a provider and a model"}
    cfg.model = model
    write_env({pid.upper().replace("-", "_") + "_MODEL": model})
    return {"ok": True, "provider": pid, "model": model}


def disconnect(agent: Any, pid: str, write_env) -> dict:
    var = env_var(pid)
    if not var:
        return {"ok": False, "error": "this provider has no saved key"}
    write_env({var: None})
    cfg = agent.MODELS.get(pid)
    if cfg is not None:
        cfg.api_key = ""
    _TESTS.pop(pid, None)
    return {"ok": True, "provider": pid}
