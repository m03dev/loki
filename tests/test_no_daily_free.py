"""The lean provider set (owner 2026-10-27: "get rid of free models with daily limits we dont need them"; "nemotron is
free in nvidia"; "its these providers that are doing the same thing we dont need the reduncency ... if those get capped
in a day within a few hours we dont need them"). On the PC they ran out every day (OpenRouter free-models-per-day 429, Gemini quota,
Groq TPM) and every job failed over through them first. Checked here, no network:
  - only the lean set is left: NVIDIA (DeepSeek / GLM-5.3 / Nemotron), Claude Code, Codex, local servers, 9Router, paid
    OpenAI / Anthropic / DeepSeek - none of the ~40 removed ones in MODELS, any order, Connections, Studio or onboarding
  - OpenRouter's browser sign-in is gone with it (route, callback, buttons)
  - Nemotron runs on the NVIDIA key (nvidia-nemotron) and leads Fast mode
  - an old setting that names a removed provider goes to its replacement instead of failing
  - nim_models picks the Nemotron the NVIDIA key really serves (listed name, else any chat Nemotron)

    python tests/test_no_daily_free.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine"), str(REPO / "studio")]
os.environ.pop("LOKI_FAST_ORDER", None)
os.environ.pop("LOKI_MAX_ORDER", None)
os.environ.pop("OPENROUTER_MODEL", None)
import loki  # noqa: E402
import nim_models  # noqa: E402
import providers_catalog  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok or not detail else "  <- %s" % (detail,)))
    if not ok:
        FAILED.append(name)


GONE = ("nemotron-free", "gemini", "groq", "codestral", "cloudflare", "modelscope", "sambanova", "cerebras", "openrouter",
        "deepseek-4.1", "gpt6-luna", "mistral", "together", "vireonix", "unorouter", "nous", "omniroute", "aion", "cohere",
        "zai", "kilocode", "llm7", "ollama-cloud", "ovh", "siliconflow", "opencode-zen", "vercel", "nebius", "scaleway",
        "hyperbolic", "novita", "fireworks", "dashscope", "deepinfra", "chutes", "baseten", "inference-net", "ai21",
        "upstage", "kyojin")
LEAN = {"nvidia", "nvidia-pro", "nvidia-nemotron", "claude-code", "codex", "9router", "deepseek", "gpt", "claude",
        "colibri", "lmstudio", "llamacpp", "mlx", "vllm", "jan", "huggingface", "opencode", "loki-tuned",
        "smart", "online", "max", "fast"}

check("no removed provider in MODELS", not [p for p in GONE if p in loki.MODELS])
check("MODELS is only the lean set (+ local Ollama variants)",
      not [p for p in loki.MODELS if p not in LEAN and not p.startswith("local")], sorted(set(loki.MODELS) - LEAN))
for order in ("SMART_ORDER", "ONLINE_ORDER", "MAX_ORDER", "FAST_ORDER"):
    check("none in %s" % order, not [p for p in GONE if p in getattr(loki, order)])
check("Connections lists none of them", not [p["id"] for p in providers_catalog.CATALOG if p["id"] in GONE])
check("every one maps to a replacement", all(loki.current_provider_name(p) in loki.MODELS for p in GONE))
import portal_api  # noqa: E402
import signin  # noqa: E402
check("OpenRouter's sign-in is gone (engine)", not hasattr(signin, "openrouter_start")
      and "/signin/openrouter" not in (REPO / "engine" / "portal_api.py").read_text(encoding="utf-8")
      and "/oauth/openrouter" not in (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8"))
check("OpenRouter's sign-in is gone (window)", "signInOpenRouter" not in (REPO / "app" / "ui" / "settings.js").read_text(encoding="utf-8")
      and "/signin/openrouter" not in (REPO / "app" / "ui" / "onboarding.js").read_text(encoding="utf-8"))

nem = loki.MODELS.get("nvidia-nemotron")
check("Nemotron is a route on the NVIDIA key", nem is not None and "integrate.api.nvidia.com" in nem.base_url
      and loki.PROVIDER_ENV_VARS.get("nvidia-nemotron") == "NVIDIA_API_KEY")
check("Fast mode tries Nemotron on NVIDIA first", loki.FAST_ORDER[:2] == ("nvidia-nemotron", "nvidia"))
check("Smart mode has Nemotron on NVIDIA", "nvidia-nemotron" in loki.SMART_ORDER)
check("Connections knows the NVIDIA Nemotron route", (providers_catalog.get("nvidia-nemotron") or {}).get("env") == "NVIDIA_API_KEY")

# old settings
check("nemotron-free -> nvidia-nemotron", loki.current_provider_name("nemotron-free") == "nvidia-nemotron")
check("gemini -> smart", loki.current_provider_name("gemini") == "smart")
check("openrouter / deepseek-4.1 -> nvidia (the same DeepSeek, free)", loki.current_provider_name("openrouter") == "nvidia"
      and loki.current_provider_name("deepseek-4.1") == "nvidia")
check("a real provider is unchanged", loki.current_provider_name("nvidia") == "nvidia")
saved = loki.model_name
try:
    loki.model_name = "groq"   # set at run time by an old window / setting
    pick = loki.active_model_name()
    check("a pinned removed provider routes like Smart (got %s)" % pick, pick in loki.MODELS and pick not in GONE)
    loki.model_name = "nemotron-free"
    check("a pinned nemotron-free uses nvidia-nemotron", loki.active_model_name() == "nvidia-nemotron")
finally:
    loki.model_name = saved

# which Nemotron the key serves
ids = ["deepseek-ai/deepseek-v4.1-flash", "nvidia/nemotron-3-super-120b-a12b", "nvidia/llama-3.2-nemoretriever-300m-embed-v1"]
check("a listed Nemotron name is used", nim_models.resolve("nvidia/nemotron-3.5-lightning", ids) == "nvidia/nemotron-3-super-120b-a12b")
newer = ["nvidia/nemotron-4-safety-guard", "nvidia/nemotron-4-flash", "z-ai/glm-5.3"]
check("an unknown newer chat Nemotron is used, never a guard/embed one",
      nim_models.resolve("nvidia/nemotron-3.5-lightning", newer) == "nvidia/nemotron-4-flash")
check("nothing listed: the configured name is kept", nim_models.resolve("nvidia/nemotron-3.5-lightning", []) == "nvidia/nemotron-3.5-lightning")
check("DeepSeek resolving is unchanged", nim_models.resolve("deepseek-ai/deepseek-v4.1-flash", ["nvidia/deepseek-v4.1-flash"])
      == "nvidia/deepseek-v4.1-flash")

try:
    import studio_models  # noqa: E402
    ids_ = [p.id for p in studio_models.providers({"NVIDIA_API_KEY": "nvapi-x"})]
    check("Studio offers none of them, and Nemotron on NVIDIA", not [p for p in GONE if p in ids_] and "nvidia-nemotron" in ids_, ids_)
except ImportError as exc:   # studio deps missing in a bare checkout
    print("SKIP studio_models: %s" % exc)

onb = (REPO / "app" / "ui" / "onboarding.js").read_text(encoding="utf-8")
check("onboarding offers only NVIDIA", '["groq"' not in onb and '["gemini"' not in onb and '["openrouter"' not in onb
      and '["nvidia"' in onb)

print("%d failed" % len(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
