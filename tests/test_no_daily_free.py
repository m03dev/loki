"""No free models with a daily cap (owner 2026-10-27: "get rid of free models with daily limits we dont need them";
"nemotron is free in nvidia"). On the PC they ran out every day (OpenRouter free-models-per-day 429, Gemini quota,
Groq TPM) and every job failed over through them first. Checked here, no network:
  - OpenRouter :free, Gemini, Groq, Codestral, Cloudflare, ModelScope, SambaNova and Cerebras are not routes any more
    (MODELS, Smart / Online / Max / Fast orders, Connections catalog, Studio, onboarding)
  - Nemotron runs on the NVIDIA key (nvidia-nemotron) and leads Fast mode; OpenRouter's default is not a :free model
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


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILED.append(name)


GONE = ("nemotron-free", "gemini", "groq", "codestral", "cloudflare", "modelscope", "sambanova", "cerebras")

check("no daily-capped free provider in MODELS", not [p for p in GONE if p in loki.MODELS])
for order in ("SMART_ORDER", "ONLINE_ORDER", "MAX_ORDER", "FAST_ORDER"):
    check("none in %s" % order, not [p for p in GONE if p in getattr(loki, order)])
check("Connections lists none of them", not [p["id"] for p in providers_catalog.CATALOG if p["id"] in GONE])
check("OpenRouter's default model is not a :free one", ":free" not in loki.MODELS["openrouter"].model)
check("OpenRouter is a paid account in Connections", providers_catalog.get("openrouter")["group"] == "paid")

nem = loki.MODELS.get("nvidia-nemotron")
check("Nemotron is a route on the NVIDIA key", nem is not None and "integrate.api.nvidia.com" in nem.base_url
      and loki.PROVIDER_ENV_VARS.get("nvidia-nemotron") == "NVIDIA_API_KEY")
check("Fast mode tries Nemotron on NVIDIA first", loki.FAST_ORDER[:2] == ("nvidia-nemotron", "nvidia"))
check("Smart mode has Nemotron on NVIDIA", "nvidia-nemotron" in loki.SMART_ORDER)
check("Connections knows the NVIDIA Nemotron route", (providers_catalog.get("nvidia-nemotron") or {}).get("env") == "NVIDIA_API_KEY")

# old settings
check("nemotron-free -> nvidia-nemotron", loki.current_provider_name("nemotron-free") == "nvidia-nemotron")
check("gemini -> smart", loki.current_provider_name("gemini") == "smart")
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
    check("Studio offers none of them, and Nemotron on NVIDIA", not [p for p in GONE if p in ids_] and "nvidia-nemotron" in ids_)
except ImportError as exc:   # studio deps missing in a bare checkout
    print("SKIP studio_models: %s" % exc)

onb = (REPO / "app" / "ui" / "onboarding.js").read_text(encoding="utf-8")
check("onboarding offers no Groq / Gemini key", '["groq"' not in onb and '["gemini"' not in onb)

print("%d failed" % len(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
