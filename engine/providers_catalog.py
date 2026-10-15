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
import time
import urllib.error
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
    {"id": "vllm", "name": "vLLM", "group": "local", "auth": ["none"], "tools": True,
     "blurb": "vLLM OpenAI server (port 8000), for an NVIDIA GPU machine.",
     "signup": "https://docs.vllm.ai", "docs": "https://docs.vllm.ai/en/latest/features/tool_calling.html"},
    {"id": "jan", "name": "Jan", "group": "local", "auth": ["none"], "tools": True,
     "blurb": "Jan's local API server (port 1337).", "signup": "https://jan.ai", "docs": "https://jan.ai/docs"},
    {"id": "kyojin", "name": "Kyojin (Yamz Labs)", "group": "local", "auth": ["none"], "tools": False,
     "blurb": "ExLlamaV3 server for 100 GB-class GLM / Qwen packs on an AMD Strix Halo (128 GB). Set KYOJIN_BASE_URL to that machine.",
     "signup": "https://github.com/Yamz-Labs/kyojin", "docs": "https://github.com/Yamz-Labs/kyojin/blob/main/doc/models.md",
     "needs": "an AMD Ryzen AI Max+ 395 (gfx1151) with 128 GB; not the Mac mini or the RTX 3070 Ti"},
    # ----------------------------------------------------------------- free
    {"id": "openrouter", "name": "OpenRouter", "group": "free", "auth": ["oauth", "key"], "tools": True,
     "env": "OPENROUTER_API_KEY", "blurb": "Hundreds of models behind one key; :free models cost nothing (50 requests/day, 1,000 after a one-time $10 top-up).",
     "signup": "https://openrouter.ai", "keys": "https://openrouter.ai/keys", "docs": "https://openrouter.ai/docs"},
    {"id": "gemini", "name": "Google AI Studio (Gemini)", "group": "free", "auth": ["key"], "tools": True,
     "env": "GEMINI_API_KEY", "blurb": "Gemini Flash and Gemma models with a free tier. The free tier may use your prompts to improve Google products.",
     "signup": "https://aistudio.google.com", "keys": "https://aistudio.google.com/apikey", "docs": "https://ai.google.dev/gemini-api/docs/openai"},
    {"id": "groq", "name": "Groq", "group": "free", "auth": ["key"], "tools": True,
     "env": "GROQ_API_KEY", "blurb": "Very fast Llama, gpt-oss and Qwen models; per-model daily limits.",
     "signup": "https://console.groq.com", "keys": "https://console.groq.com/keys", "docs": "https://console.groq.com/docs/openai"},
    {"id": "mistral", "name": "Mistral La Plateforme", "group": "free", "auth": ["key"], "tools": True,
     "env": "MISTRAL_API_KEY", "blurb": "Free Experiment plan (needs phone verification and opting in to training use).",
     "signup": "https://console.mistral.ai", "keys": "https://console.mistral.ai/api-keys", "docs": "https://docs.mistral.ai"},
    {"id": "codestral", "name": "Codestral", "group": "free", "auth": ["key"], "tools": True,
     "env": "CODESTRAL_API_KEY", "blurb": "Mistral's coding model, free: 30 requests/min, 2,000/day.",
     "signup": "https://console.mistral.ai/codestral", "keys": "https://console.mistral.ai/codestral", "docs": "https://docs.mistral.ai/capabilities/code_generation/"},
    {"id": "nvidia", "name": "NVIDIA NIM", "group": "free", "auth": ["key"], "tools": True,
     "env": "NVIDIA_API_KEY", "blurb": "Free hosted Nemotron and other open models, 40 requests/min (phone verification).",
     "signup": "https://build.nvidia.com", "keys": "https://build.nvidia.com/settings/api-keys", "docs": "https://docs.api.nvidia.com"},
    {"id": "cloudflare", "name": "Cloudflare Workers AI", "group": "free", "auth": ["key"], "tools": True,
     "env": "CLOUDFLARE_API_TOKEN", "extra_env": ["CLOUDFLARE_ACCOUNT_ID"],
     "blurb": "10,000 Neurons/day free: gpt-oss, Kimi, GLM, Llama, Gemma. Needs your account ID too.",
     "signup": "https://dash.cloudflare.com", "keys": "https://dash.cloudflare.com/profile/api-tokens", "docs": "https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/"},
    {"id": "cohere", "name": "Cohere", "group": "free", "auth": ["key"], "tools": True,
     "env": "COHERE_API_KEY", "blurb": "Trial key: 20 requests/min, 1,000/month (Command A).",
     "signup": "https://dashboard.cohere.com", "keys": "https://dashboard.cohere.com/api-keys", "docs": "https://docs.cohere.com/docs/compatibility-api"},
    {"id": "huggingface", "name": "Hugging Face", "group": "free", "auth": ["device", "key"], "tools": True,
     "env": "HF_TOKEN", "blurb": "Inference Providers router with a small monthly credit; also where local models download from.",
     "signup": "https://huggingface.co/join", "keys": "https://huggingface.co/settings/tokens", "docs": "https://huggingface.co/docs/inference-providers"},
    {"id": "kilocode", "name": "Kilo Gateway", "group": "free", "auth": ["key"], "tools": True,
     "env": "KILOCODE_API_KEY", "blurb": "Free models (Nemotron, Ling, Step), 200 requests/hour. Free models may use prompts for training.",
     "signup": "https://kilo.ai", "keys": "https://app.kilo.ai", "docs": "https://kilo.ai/docs/gateway"},
    {"id": "opencode-zen", "name": "OpenCode Zen", "group": "free", "auth": ["key"], "tools": True,
     "env": "OPENCODE_API_KEY", "blurb": "Free coding models (DeepSeek V4 Flash, Qwen 3.6 Plus, MiniMax, Nemotron). Free models may be used to improve them.",
     "signup": "https://opencode.ai/zen", "keys": "https://opencode.ai/auth", "docs": "https://opencode.ai/docs/zen"},
    {"id": "sambanova", "name": "SambaNova Cloud", "group": "free", "auth": ["key"], "tools": True,
     "env": "SAMBANOVA_API_KEY", "blurb": "Fast open models; free tier plus starter credits.",
     "signup": "https://cloud.sambanova.ai", "keys": "https://cloud.sambanova.ai/apis", "docs": "https://docs.sambanova.ai"},
    {"id": "together", "name": "Together AI", "group": "free", "auth": ["key"], "tools": True,
     "env": "TOGETHER_API_KEY", "blurb": "Open models; some :Free endpoints.",
     "signup": "https://api.together.ai", "keys": "https://api.together.ai/settings/api-keys", "docs": "https://docs.together.ai"},
    {"id": "nous", "name": "Nous Portal", "group": "free", "auth": ["key"], "tools": True,
     "env": "NOUS_API_KEY", "blurb": "Hermes models; the $0 plan includes :free models.",
     "signup": "https://portal.nousresearch.com", "keys": "https://portal.nousresearch.com", "docs": "https://portal.nousresearch.com"},
    {"id": "unorouter", "name": "UnoRouter", "group": "free", "auth": ["key"], "tools": True,
     "env": "UNOROUTER_API_KEY", "blurb": "A large catalogue of :free routes, no card.",
     "signup": "https://unorouter.com", "keys": "https://unorouter.com", "docs": "https://unorouter.com"},
    {"id": "zai", "name": "Z.ai (GLM)", "group": "free", "auth": ["key"], "tools": True,
     "env": "ZAI_API_KEY", "blurb": "GLM Flash models free on Zhipu's open platform.",
     "signup": "https://open.bigmodel.cn", "keys": "https://open.bigmodel.cn/usercenter/apikeys", "docs": "https://open.bigmodel.cn/dev/api"},
    {"id": "modelscope", "name": "ModelScope", "group": "free", "auth": ["key"], "tools": True,
     "env": "MODELSCOPE_API_KEY", "blurb": "Free daily inference on Qwen models, and free Qwen-Image 2.1 pictures (about 250 a day with a verified Alibaba Cloud account) - LOKI's image tool uses it when the key is set.",
     "signup": "https://modelscope.cn", "keys": "https://modelscope.cn/my/myaccesstoken", "docs": "https://modelscope.cn/docs"},
    {"id": "siliconflow", "name": "SiliconFlow", "group": "free", "auth": ["key"], "tools": True,
     "env": "SILICONFLOW_API_KEY", "blurb": "Small Qwen models free.",
     "signup": "https://cloud.siliconflow.cn", "keys": "https://cloud.siliconflow.cn/account/ak", "docs": "https://docs.siliconflow.cn"},
    {"id": "ovh", "name": "OVHcloud AI Endpoints", "group": "free", "auth": ["key"], "tools": True,
     "env": "OVH_API_KEY", "blurb": "Open models; anonymous use is rate limited, a key raises it.",
     "signup": "https://endpoints.ai.cloud.ovh.net", "keys": "https://endpoints.ai.cloud.ovh.net", "docs": "https://endpoints.ai.cloud.ovh.net"},
    {"id": "vercel", "name": "Vercel AI Gateway", "group": "free", "auth": ["key"], "tools": True,
     "env": "AI_GATEWAY_API_KEY", "blurb": "$5 of free usage every month (as long as you never buy credits); provider/model names.",
     "signup": "https://vercel.com/ai-gateway", "keys": "https://vercel.com/d?to=%2F%5Bteam%5D%2F%7E%2Fai%2Fapi-keys", "docs": "https://vercel.com/docs/ai-gateway"},
    # ----------------------------------------------------------------- keyless
    {"id": "llm7", "name": "LLM7.io", "group": "keyless", "auth": ["none", "key"], "tools": True,
     "env": "LLM7_API_KEY", "blurb": "Answers without any account; a free token raises the limits. Prompts go to a third party.",
     "signup": "https://llm7.io", "keys": "https://token.llm7.io", "docs": "https://llm7.io"},
    {"id": "vireonix", "name": "Vireonix", "group": "keyless", "auth": ["none"], "tools": True,
     "blurb": "No key, no account, no card. Prompts and file contents go to a third party.",
     "signup": "https://vireonix.ai", "docs": "https://vireonix.ai"},
    {"id": "pollinations", "name": "Pollinations", "group": "keyless", "auth": ["none", "key"], "tools": False,
     "env": "POLLINATIONS_API_KEY", "blurb": "Free text and image generation with no sign-up (also LOKI's zero-setup image backend).",
     "signup": "https://pollinations.ai", "keys": "https://auth.pollinations.ai", "docs": "https://github.com/pollinations/pollinations/blob/master/APIDOCS.md"},
    # ----------------------------------------------------------------- trial
    {"id": "nebius", "name": "Nebius Token Factory", "group": "trial", "auth": ["key"], "tools": True,
     "env": "NEBIUS_API_KEY", "blurb": "$1 of starter credit; DeepSeek, Qwen, Llama.",
     "signup": "https://tokenfactory.nebius.com", "keys": "https://tokenfactory.nebius.com", "docs": "https://docs.tokenfactory.nebius.com"},
    {"id": "scaleway", "name": "Scaleway Generative APIs", "group": "trial", "auth": ["key"], "tools": True,
     "env": "SCALEWAY_API_KEY", "blurb": "1M free tokens: gpt-oss, GLM, Qwen 3.5, Devstral.",
     "signup": "https://console.scaleway.com", "keys": "https://console.scaleway.com/iam/api-keys", "docs": "https://www.scaleway.com/en/docs/generative-apis/"},
    {"id": "hyperbolic", "name": "Hyperbolic", "group": "trial", "auth": ["key"], "tools": True,
     "env": "HYPERBOLIC_API_KEY", "blurb": "$1 of credit: DeepSeek, Qwen3 Coder 480B.",
     "signup": "https://app.hyperbolic.ai", "keys": "https://app.hyperbolic.ai/settings", "docs": "https://docs.hyperbolic.xyz"},
    {"id": "novita", "name": "Novita AI", "group": "trial", "auth": ["key"], "tools": True,
     "env": "NOVITA_API_KEY", "blurb": "$0.50 of credit for a year.",
     "signup": "https://novita.ai", "keys": "https://novita.ai/settings/key-management", "docs": "https://novita.ai/docs"},
    {"id": "fireworks", "name": "Fireworks AI", "group": "trial", "auth": ["key"], "tools": True,
     "env": "FIREWORKS_API_KEY", "blurb": "$1 of credit; fast open models.",
     "signup": "https://fireworks.ai", "keys": "https://fireworks.ai/account/api-keys", "docs": "https://docs.fireworks.ai"},
    {"id": "dashscope", "name": "Alibaba Model Studio (Qwen)", "group": "trial", "auth": ["key"], "tools": True,
     "env": "DASHSCOPE_API_KEY", "blurb": "1M free tokens per Qwen model for 90 days (Singapore endpoint), plus a small free image allowance.",
     "signup": "https://bailian.console.alibabacloud.com", "keys": "https://bailian.console.alibabacloud.com/?apiKey=1", "docs": "https://www.alibabacloud.com/help/en/model-studio/"},
    {"id": "deepinfra", "name": "DeepInfra", "group": "trial", "auth": ["key"], "tools": True,
     "env": "DEEPINFRA_API_KEY", "blurb": "Cheap hosted open models (Llama, Qwen, DeepSeek); small starter credit.",
     "signup": "https://deepinfra.com", "keys": "https://deepinfra.com/dash/api_keys", "docs": "https://deepinfra.com/docs/openai_api"},
    {"id": "chutes", "name": "Chutes", "group": "trial", "auth": ["key"], "tools": True,
     "env": "CHUTES_API_KEY", "blurb": "Decentralised open-model hosting (DeepSeek, Qwen, GLM).",
     "signup": "https://chutes.ai", "keys": "https://chutes.ai/app/api", "docs": "https://chutes.ai/docs"},
    {"id": "baseten", "name": "Baseten Model APIs", "group": "trial", "auth": ["key"], "tools": True,
     "env": "BASETEN_API_KEY", "blurb": "$30 of credit: GLM-5.3, gpt-oss-120b, Kimi K3.",
     "signup": "https://app.baseten.co", "keys": "https://app.baseten.co/settings/api_keys", "docs": "https://docs.baseten.co/development/model-apis/overview"},
    {"id": "inference-net", "name": "Inference.net", "group": "trial", "auth": ["key"], "tools": True,
     "env": "INFERENCE_API_KEY", "blurb": "$1 of credit ($25 after a short survey): GLM, Gemini Flash, gpt-5-mini.",
     "signup": "https://inference.net", "keys": "https://inference.net/dashboard/api-keys", "docs": "https://docs.inference.net/api/api-quickstart"},
    {"id": "ai21", "name": "AI21 (Jamba)", "group": "trial", "auth": ["key"], "tools": True,
     "env": "AI21_API_KEY", "blurb": "$10 of credit for 3 months: Jamba models with long context.",
     "signup": "https://studio.ai21.com", "keys": "https://studio.ai21.com/account/api-key", "docs": "https://docs.ai21.com"},
    {"id": "upstage", "name": "Upstage (Solar)", "group": "trial", "auth": ["key"], "tools": True,
     "env": "UPSTAGE_API_KEY", "blurb": "$10 of credit for 3 months: Solar Pro and Solar Mini.",
     "signup": "https://console.upstage.ai", "keys": "https://console.upstage.ai/api-keys", "docs": "https://console.upstage.ai/docs"},
    {"id": "cerebras", "name": "Cerebras", "group": "trial", "auth": ["key"], "tools": True,
     "env": "CEREBRAS_API_KEY", "blurb": "Extremely fast; free per-model limits, needs a verified payment method.",
     "signup": "https://cloud.cerebras.ai", "keys": "https://cloud.cerebras.ai/platform", "docs": "https://inference-docs.cerebras.ai"},
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


def test(agent: Any, pid: str, timeout: float = 20.0, opener=urllib.request.urlopen) -> dict:
    """One tiny real request (1-token completion) so the card can say "works" honestly."""
    cfg = agent.MODELS.get(pid)
    if cfg is None:
        return {"ok": False, "error": "unknown provider"}
    started = time.monotonic()
    if cfg.base_url.startswith("cli-agent://"):
        ok = bool(agent.provider_configured(pid))
        result = {"ok": ok, "detail": "installed (sign-in is checked on first use)" if ok else "not installed"}
    else:
        try:
            status, data = _request(cfg.base_url.rstrip("/") + "/chat/completions", str(cfg.api_key or ""), timeout,
                                    body={"model": cfg.model, "max_tokens": 1,
                                          "messages": [{"role": "user", "content": "Say OK"}]}, opener=opener)
            model = data.get("model", cfg.model) if isinstance(data, dict) else cfg.model
            result = {"ok": 200 <= status < 300, "detail": "answered with %s" % model}
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
        except Exception as exc:  # noqa: BLE001
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
