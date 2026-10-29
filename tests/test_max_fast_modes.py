"""Max and Fast modes (owner 2026-10-26: "whats our strongest model and fastest. we need a mode for that to get hard
tasks done"). Max = the strongest model that is ready (subscriptions, then DeepSeek V4 Pro on NVIDIA with thinking on),
Fast = the quickest capable one. No network: provider_configured / health are faked.

    python tests/test_max_fast_modes.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]
os.environ.setdefault("LOKI_DATA", tempfile.mkdtemp(prefix="loki-maxfast-"))
os.environ["LOKI_RATE_FILE_DIR"] = tempfile.mkdtemp(prefix="loki-rl-")
T0 = time.time()

import loki  # noqa: E402
from nim_models import STRONGEST as nim_models_STRONGEST  # noqa: E402
import ratelimit  # noqa: E402
import loki_bridge  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


READY: set = set()
loki.provider_configured = lambda n: n in READY


class _Reg:
    def usable(self, pid, key="", need_tokens=0):
        return (True, "")

    def get(self, pid):
        return {}


loki.provider_health.registry = lambda: _Reg()
loki._SMART_FAILED.clear()

check("max and fast are auto-routing modes", "max" in loki.AUTO_ROUTING_MODES and "fast" in loki.AUTO_ROUTING_MODES)
check("max starts with the owner's subscriptions, then DeepSeek V4 Pro", loki.MAX_ORDER[:3] == ("claude-code", "codex", "nvidia-pro"), loki.MAX_ORDER[:4])
check("nvidia-pro is the strongest model on the NVIDIA key (GLM-5.3 by default)", loki.MODELS["nvidia-pro"].model in nim_models_STRONGEST
      and "integrate.api.nvidia.com" in loki.MODELS["nvidia-pro"].base_url, loki.MODELS["nvidia-pro"].model)
check("fast starts with Nemotron on NVIDIA, then the main driver", loki.FAST_ORDER[:2] == ("nvidia-nemotron", "nvidia"), loki.FAST_ORDER[:3])
check("every smart provider is still behind max / fast (never a dead end)",
      all(p in loki.MAX_ORDER and p in loki.FAST_ORDER for p in loki.SMART_ORDER))

loki.model_name = "max"
READY.clear(); READY.update({"nvidia", "nvidia-pro", "nvidia-nemotron"})
check("max with only free keys picks DeepSeek V4 Pro, not the Flash main driver", loki.active_model_name() == "nvidia-pro", loki.active_model_name())
READY.add("claude-code")
check("max picks Claude Code when the plan is signed in", loki.active_model_name() == "claude-code")
loki._SMART_FAILED.add("claude-code")
check("... and fails over to the next strongest when it is used up", loki.active_model_name() == "nvidia-pro")
loki._SMART_FAILED.clear()
READY.clear(); READY.update({"gpt", "nvidia-nemotron"})
paid = loki.paid_allowed_automatically
loki.paid_allowed_automatically = lambda: False
check("max never picks a paid API on its own", loki.active_model_name() == "nvidia-nemotron", loki.active_model_name())
loki.paid_allowed_automatically = paid

_pro = loki.MODELS["nvidia-pro"].model
loki.MODELS["nvidia-pro"].model = "deepseek-ai/deepseek-v4-pro"   # a key that has DeepSeek V4 Pro
kw = loki._provider_kwargs("nvidia-pro", loki.MODELS["nvidia-pro"], {"messages": []})
loki.MODELS["nvidia-pro"].model = _pro
tmpl = (kw.get("extra_body") or {}).get("chat_template_kwargs") or {}
check("max on DeepSeek V4 Pro (where a key has it) thinks (high)", tmpl.get("thinking") is True and tmpl.get("reasoning_effort") in ("high", "max"), tmpl)
loki.model_name = "smart"
kw = loki._provider_kwargs("nvidia", loki.MODELS["nvidia"], {"messages": []})
check("smart on the Flash main driver keeps thinking off", ((kw.get("extra_body") or {}).get("chat_template_kwargs") or {}).get("thinking") is False
      or loki.NVIDIA_THINKING not in ("off", ""))

loki.model_name = "fast"
READY.clear(); READY.update({"nvidia", "nvidia-nemotron", "claude-code"})
check("fast picks Nemotron over the main driver and the subscriptions", loki.active_model_name() == "nvidia-nemotron", loki.active_model_name())
pick, why = loki.route_for({"kind": "question", "difficulty": 1})
check("route_for explains fast", pick == "nvidia-nemotron" and "Fast" in why, (pick, why))

check("nvidia-pro shares NVIDIA's per-minute window (one key)", ratelimit.bucket("nvidia-pro") == "nvidia" and ratelimit.rpm("nvidia-pro") == ratelimit.rpm("nvidia"))
ratelimit.reset()
ratelimit.take("nvidia-pro")
check("... a request on nvidia-pro counts for nvidia", len(ratelimit._window("nvidia", time.time())) == 1)


class _Agent:
    MODELS = loki.MODELS
    model_name = "max"

    def active_model_name(self):
        return "nvidia-pro"

    def provider_configured(self, n):
        return n in READY

    def provider_tier(self, n):
        return loki.provider_tier(n)


menu = loki_bridge.model_menu(_Agent())
names = [e["name"] for e in menu["entries"]]
check("the model menu offers Max and Fast with Smart", names[:4] == ["smart", "online", "max", "fast"], names[:5])
mx = next(e for e in menu["entries"] if e["name"] == "max")
check("... Max says what it is using now", mx["using"] and any(k in mx["using"] for k in ("V4 Pro", "GLM", "Kimi")), mx)
check("... and the modes are not listed again as providers", names.count("max") == 1 and names.count("fast") == 1)
import nim_models  # noqa: E402
PC_KEY = ["deepseek-ai/deepseek-v4.1-flash", "moonshotai/kimi-k2.6", "z-ai/glm-5.3", "nvidia/nemotron-3-ultra-550b-a55b"]
check("Max on NVIDIA asks for a model the key really serves (the PC's key has no DeepSeek V4 Pro)",
      nim_models.resolve("deepseek-ai/deepseek-v4-pro", PC_KEY) == "z-ai/glm-5.3")
check("... GLM-5.3 by default", loki.MODELS["nvidia-pro"].model == "z-ai/glm-5.3" or os.getenv("NVIDIA_PRO_MODEL"))
check("... and Kimi K2.6 when the key has no GLM", nim_models.resolve("z-ai/glm-5.3", ["moonshotai/kimi-k2.6"]) == "moonshotai/kimi-k2.6")
READY.clear(); READY.update({"nvidia", "nvidia-nemotron", "local", "local-fast"})
loki.model_name = "smart"
provs = loki._oc_providers("nvidia")
check("modes (smart / online / max / fast) are never handed to OpenCode as providers",
      not any(m in provs for m in loki.AUTO_ROUTING_MODES), list(provs))
os.environ["LOKI_JOB_ID"] = "test-job"
try:
    import provider_speed  # noqa: E402
    provider_speed.record(loki.DATA_DIR, "nvidia", 500.0)   # NVIDIA crawling, as on the PC overnight
    job_order = list(loki._oc_providers("nvidia"))
finally:
    os.environ.pop("LOKI_JOB_ID", None)
check("in a background job a slow capable route stays ahead of the small local / weak free models",
      job_order.index("nvidia") < min(job_order.index(x) for x in ("local", "local-fast") if x in job_order), job_order)
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
