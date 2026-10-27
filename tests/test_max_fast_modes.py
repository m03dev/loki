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
check("nvidia-pro is DeepSeek V4 Pro on the NVIDIA key", "deepseek-v4-pro" in loki.MODELS["nvidia-pro"].model
      and "integrate.api.nvidia.com" in loki.MODELS["nvidia-pro"].base_url)
check("fast starts with Cerebras and Groq", loki.FAST_ORDER[:2] == ("cerebras", "groq"), loki.FAST_ORDER[:3])
check("every smart provider is still behind max / fast (never a dead end)",
      all(p in loki.MAX_ORDER and p in loki.FAST_ORDER for p in loki.SMART_ORDER))

loki.model_name = "max"
READY.clear(); READY.update({"nvidia", "nvidia-pro", "gemini"})
check("max with only free keys picks DeepSeek V4 Pro, not the Flash main driver", loki.active_model_name() == "nvidia-pro", loki.active_model_name())
READY.add("claude-code")
check("max picks Claude Code when the plan is signed in", loki.active_model_name() == "claude-code")
loki._SMART_FAILED.add("claude-code")
check("... and fails over to the next strongest when it is used up", loki.active_model_name() == "nvidia-pro")
loki._SMART_FAILED.clear()
READY.clear(); READY.update({"gpt", "gemini"})
paid = loki.paid_allowed_automatically
loki.paid_allowed_automatically = lambda: False
check("max never picks a paid API on its own", loki.active_model_name() == "gemini", loki.active_model_name())
loki.paid_allowed_automatically = paid

kw = loki._provider_kwargs("nvidia-pro", loki.MODELS["nvidia-pro"], {"messages": []})
tmpl = (kw.get("extra_body") or {}).get("chat_template_kwargs") or {}
check("max on DeepSeek V4 Pro thinks (high)", tmpl.get("thinking") is True and tmpl.get("reasoning_effort") in ("high", "max"), tmpl)
loki.model_name = "smart"
kw = loki._provider_kwargs("nvidia", loki.MODELS["nvidia"], {"messages": []})
check("smart on the Flash main driver keeps thinking off", ((kw.get("extra_body") or {}).get("chat_template_kwargs") or {}).get("thinking") is False
      or loki.NVIDIA_THINKING not in ("off", ""))

loki.model_name = "fast"
READY.clear(); READY.update({"nvidia", "groq", "claude-code"})
check("fast picks Groq over the main driver and the subscriptions", loki.active_model_name() == "groq", loki.active_model_name())
pick, why = loki.route_for({"kind": "question", "difficulty": 1})
check("route_for explains fast", pick == "groq" and "Fast" in why, (pick, why))

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
check("... Max says what it is using now", mx["using"] and "V4 Pro" in mx["using"], mx)
check("... and the modes are not listed again as providers", names.count("max") == 1 and names.count("fast") == 1)
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
