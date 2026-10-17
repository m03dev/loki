"""Models & routing, the core system (session 28) - offline, fake servers only.

  1. provider health: every error shape a provider gives (429 rate / quota / per-day, 402, 401,
     413 size, context too long, timeout, empty reply) becomes a state with an end time, a
     reason and a one-line fix; it is remembered across processes; probes are free (GET only)
  2. task-aware routing: needs (kind, difficulty, tools, pictures, size, local only) x abilities
     (tools reliable? sees images? context?) x health x a learned success table per task kind
  3. loki's routing: background jobs get the best FREE capable model (not just local), dead
     providers are skipped with the reason, never a dead end, never paid on its own
  4. mid-task failover against a fake OpenAI-compatible server: 429, 402, 401, context too
     long, timeout, empty choices, 413 - the conversation is kept and the next provider finishes
  5. local models: Ollama version + Bonsai gate + upgrade commands, num_ctx made and verified,
     the condenser sized to the real window, MLX
  6. /models doctor and Settings > Connections

    python tests/test_routing_core.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="loki-routing-"))
WS = TMP / "ws"
WS.mkdir(parents=True, exist_ok=True)
HEALTH_FILE = TMP / "provider_health.json"
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_WORKSPACE"] = str(WS)
os.environ["LOKI_HEALTH_FILE"] = str(HEALTH_FILE)
os.environ["LOKI_HEALTH_PROBES"] = "0"
for _k in ("LOKI_JOB_ID", "LOKI_TEAM_ID", "LOKI_NO_ESCALATE", "LOKI_LOCAL_ONLY", "LOKI_MODEL", "LOKI_PREFER",
           "LOKI_ALLOW_PAID", "LOKI_DISABLED_PROVIDERS"):
    os.environ.pop(_k, None)
for _k in [k for k in os.environ if k.endswith("_API_KEY")]:
    os.environ.pop(_k)

import condenser  # noqa: E402
import experience  # noqa: E402
import loki  # noqa: E402
import model_setup  # noqa: E402
import portal_api  # noqa: E402
import provider_health  # noqa: E402
import providers_catalog  # noqa: E402
import routing  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def section(title):
    print("\n" + title)


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


# ================================================================== 1. provider health
section("1. provider health: every error shape -> a state, an end time, a reason, a fix")
NOW = 1_800_000_000.0
c = provider_health.classify
v = c("Rate limit reached for model qwen3 in organization org_x on requests per minute. Please try again in 7m12.5s.",
      429, now=NOW)
check("a 429 rate limit waits as long as the provider said ('try again in 7m12.5s')",
      v["state"] == "rate_limited" and abs(v["until"] - (NOW + 432.5)) < 1, v)
v = c("Too Many Requests", 429, header_retry="45", now=NOW)
check("...or its Retry-After header", v["state"] == "rate_limited" and v["until"] == NOW + 45, v)
v = c('{"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details.",'
      ' "status": "RESOURCE_EXHAUSTED", "details": [{"retryDelay": "37s"}]}}', 429, now=NOW)
check("Gemini's spent quota is a quota (not 'no credit' because it mentions billing), back after its retryDelay",
      v["state"] == "quota" and v["until"] == NOW + 37, v)
v = c("Quota exceeded for metric generate_content_free_tier_requests, limit: 250 PerDay", 429, now=NOW)
check("a per-day quota is spent until the next day", v["state"] == "quota" and v["until"] > NOW + 60 and
      v["until"] <= NOW + 86400 + 300 and int(v["until"] - 300) % 86400 == 0, v)
v = c("Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day", 429, now=NOW)
check("OpenRouter's free-models-per-day is a daily quota", v["state"] == "quota" and v["until"] > NOW + 60, v)
v = c("Insufficient Balance", 402, now=NOW)
check("402 = out of credit (deepseek), for hours", v["state"] == "no_credit" and v["until"] >= NOW + 3600, v)
v = c("Incorrect API key provided", 401, now=NOW)
check("401 = key rejected, until the key changes", v["state"] == "key_rejected" and v["until"] == 0, v)
v = c("[model error] mistral-large answered HTTP 401: Unauthorized", now=NOW)
check("...also from LOKI's own error text (status read from 'HTTP 401')", v["state"] == "key_rejected", v)
v = c("Request too large for model `qwen/qwen3.8-27b` in organization `org` service tier `on_demand` on tokens per minute "
      "(TPM): Limit 6000, Requested 9133, please reduce your message size and try again.", 413, now=NOW)
check("Groq's 413 = refuses requests over its limit (6000 tokens), not dead for small ones",
      v["state"] == "size_limited" and v["size"] == 6000, v)
v = c("This model's maximum context length is 32768 tokens. However, you requested 40000 tokens.", 400, now=NOW)
check("a context-too-long error records the window (32768)", v["state"] == "size_limited" and v["context"] == 32768
      and v["until"] == 0, v)
v = c("timed out: Request timed out.", 0, now=NOW)
check("a timeout = unreachable for a couple of minutes", v["state"] == "unreachable" and NOW < v["until"] <= NOW + 300, v)
v = c("[model error] x returned an empty reply (no choices)", 0, now=NOW)
check("an empty reply = failing for a minute", v["state"] == "error" and v["until"] == NOW + 60, v)
check("retry_after reads Groq's minutes, Gemini's retryDelay and plain seconds",
      provider_health.retry_after("please try again in 2m0s.") == 120
      and provider_health.retry_after('"retryDelay": "12s"') == 12
      and provider_health.retry_after("retry after 30 seconds") == 30
      and provider_health.retry_after("nothing here") == 0)

clock = Clock(NOW)
reg = provider_health.Registry(TMP / "h1.json", clock=clock)
reg.record_failure("gemini", "You exceeded your current quota RESOURCE_EXHAUSTED retryDelay: 600s", 429, key="AIzaKEY1")
reg.record_failure("mistral", "Unauthorized", 401, key="mkey-old")
reg.record_failure("groq", "Request too large ... (TPM): Limit 6000, Requested 9133", 413, key="gsk")
reg.record_success("openrouter", 420, key="or-key", request_tokens=12000)
ok, why = reg.usable("gemini", "AIzaKEY1")
check("a spent quota is skipped, with the reason and when it is back", not ok and "quota" in why and "back in 10 min" in why, why)
check("a rejected key is skipped...", not reg.usable("mistral", "mkey-old")[0])
check("...until a NEW key is pasted (then it is tried again)", reg.usable("mistral", "mkey-new")[0])
check("a size limit only blocks requests bigger than it (8k refused, 3k fine)",
      not reg.usable("groq", "gsk", need_tokens=8000)[0] and reg.usable("groq", "gsk", need_tokens=3000)[0],
      reg.usable("groq", "gsk", need_tokens=8000))
check("a working provider is usable and its latency is kept", reg.usable("openrouter")[0]
      and reg.get("openrouter")["latency_ms"] == 420)
other = provider_health.Registry(TMP / "h1.json", clock=clock)
check("another process (a background job) sees the same marks from the file",
      not other.usable("gemini", "AIzaKEY1")[0] and not other.usable("mistral", "mkey-old")[0])
snap = other.snapshot()
check("the snapshot gives a plain line per provider", "key rejected" in snap["mistral"]["line"]
      and snap["openrouter"]["live"] and not snap["mistral"]["live"], snap.get("mistral"))
clock.t += 601
check("the quota mark ends by itself when its time is up", reg.usable("gemini", "AIzaKEY1")[0])
reg.forget_session()
check("an in-process revive forgets this process's marks (mistral tried again)", reg.usable("mistral", "mkey-old")[0])
check("...but not the marks other processes made", not other.usable("mistral", "mkey-old")[0])
saved = json.loads((TMP / "h1.json").read_text())
check("no key is ever written to the file (only a short hash)",
      "AIzaKEY1" not in json.dumps(saved) and "mkey-old" not in json.dumps(saved), saved)
reg.record_failure("leaky", "Incorrect API key provided: sk-abcdefghijklmnopqrstuvwxyz", 401)
check("a key echoed in an error body is masked before it is stored",
      "abcdefghijklmnop" not in (TMP / "h1.json").read_text())
cat = providers_catalog.get("mistral")
fix = provider_health.fix_for("mistral", {"state": "key_rejected"}, cat)
check("a rejected key's fix says where to paste it and where to get one",
      "Settings > Connections" in fix and "MISTRAL_API_KEY" in fix and "console.mistral.ai" in fix, fix)
check("a spent quota needs nothing from you", "Nothing to do" in provider_health.fix_for("gemini", {"state": "quota"}))
check("no credit says add credit or switch it off",
      "Add credit" in provider_health.fix_for("deepseek", {"state": "no_credit"}, providers_catalog.get("deepseek")))

# ---- probes: free, GET only
SEEN: list = []


def fake_open(routes):
    def opener(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        method = req.get_method() if hasattr(req, "get_method") else "GET"
        SEEN.append((method, url))
        for prefix, (status, body) in routes.items():
            if url.endswith(prefix):
                if status >= 400:
                    raise urllib.error.HTTPError(url, status, "err", {}, io.BytesIO(json.dumps(body).encode()))

                class R:
                    def read(self):
                        return json.dumps(body).encode()

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False
                R.status = status
                return R()
        raise urllib.error.URLError("no route " + url)
    return opener


OR_MODELS = {"data": [{"id": "poolside/laguna-s-2.1:free", "context_length": 131072,
                       "supported_parameters": ["tools", "temperature"],
                       "architecture": {"input_modalities": ["text"]}, "pricing": {"prompt": "0", "completion": "0"}},
                      {"id": "google/gemma-4-26b:free", "context_length": 131072, "supported_parameters": ["temperature"],
                       "architecture": {"input_modalities": ["text", "image"]}}]}
SEEN.clear()
res = provider_health.probe("openrouter", "https://openrouter.ai/api/v1", "or-key", "poolside/laguna-s-2.1:free",
                            opener=fake_open({"/models": (200, OR_MODELS),
                                              "/key": (200, {"data": {"usage": 3.2, "limit": None, "limit_remaining": -0.4,
                                                                      "is_free_tier": False}})}))
check("an OpenRouter probe reads the model's context, tool calling and vision from /models",
      res["model_info"] == {"context": 131072, "tools": True, "vision": False, "free": True}, res.get("model_info"))
check("...and a NEGATIVE balance is 'no credit' (even :free models refuse then)", res["state"] == "no_credit", res)
check("a probe never sends a completion: GETs only, no /chat/completions",
      SEEN and all(m == "GET" and "chat/completions" not in u for m, u in SEEN), SEEN)
res = provider_health.probe("mistral", "https://api.mistral.ai/v1", "bad", "mistral-large-latest",
                            opener=fake_open({"/models": (401, {"message": "Unauthorized"})}))
check("a probe finds a rejected key", res["state"] == "key_rejected", res)
res = provider_health.probe("together", "https://api.together.xyz/v1", "k", "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
                            opener=fake_open({"/models": (200, [{"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo"}])}))
check("a probe notices the configured model is gone from the list (Together's -Free)", res["state"] == "model_missing", res)
res = provider_health.probe("deepseek", "https://api.deepseek.com", "k", "deepseek-flash",
                            opener=fake_open({"/models": (200, {"data": [{"id": "deepseek-flash"}]}),
                                              "/user/balance": (200, {"is_available": False})}))
check("DeepSeek with no balance is 'no credit' (its free balance endpoint)", res["state"] == "no_credit", res)
reg2 = provider_health.Registry(TMP / "h2.json", clock=Clock(NOW))
reg2.record_failure("cerebras", "Unauthorized", 401, key="k1")
reg2.record_probe("cerebras", {"state": "ok", "models": ["llama-3.3-70b"]}, key="k1")
check("a probe that gets in proves the key again", reg2.usable("cerebras", "k1")[0])
reg2.record_failure("gemini", "quota exceeded", 429, key="g")
reg2.record_probe("gemini", {"state": "ok"}, key="g")
check("...but a /models answer does not lift a spent quota early", not reg2.usable("gemini", "g")[0])

fake_agent = types.SimpleNamespace(
    MODELS={"groq": types.SimpleNamespace(base_url="https://api.groq.com/openai/v1", api_key="gsk_x", model="m"),
            "local": types.SimpleNamespace(base_url="http://localhost:11434/v1", api_key="ollama", model="q"),
            "claude-code": types.SimpleNamespace(base_url="cli-agent://claude-code", api_key="", model="c"),
            "nokey": types.SimpleNamespace(base_url="https://x.example/v1", api_key="", model="m"),
            "off": types.SimpleNamespace(base_url="https://y.example/v1", api_key="k", model="m")},
    provider_disabled=lambda p: p == "off")
SEEN.clear()
done = provider_health.refresh_once(fake_agent, reg2, opener=fake_open({"/models": (200, {"data": [{"id": "m"}]})}))
check("the refresher probes only configured, switched-on remote providers (never local, CLI or keyless)",
      done == ["groq"], done)
check("...and not again until it is due", provider_health.refresh_once(fake_agent, reg2,
                                                                     opener=fake_open({"/models": (200, {})})) == [])

# ================================================================== 2. task-aware routing
section("2. needs x abilities x health x what worked")
n = routing.needs_for({"kind": "question", "difficulty": 1})
check("a question is not tool-heavy", not n["tool_heavy"] and not n["vision"], n)
n = routing.needs_for({"kind": "chat"}, background=True)
check("a background job is tool-heavy whatever it is", n["tool_heavy"] and n["background"], n)
pic = [{"role": "user", "content": [{"type": "text", "text": "what is in this?"},
                                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}]}]
check("a picture in the message means the model must see", routing.needs_for({}, messages=pic)["vision"])
check("a 150k-token task is long", routing.needs_for({}, est_tokens=150_000)["long"])

loki.MODELS["fake-native"] = loki.ModelConfig(base_url="https://native.example/v1", api_key="k", model="qwen3-coder-big")
loki.MODELS["fake-prompted"] = loki.ModelConfig(base_url="https://prompted.example/v1", api_key="k", model="some-model")
loki.tool_harness.learn("fake-prompted")
ab = routing.abilities(loki, "fake-native", {})
check("a native tool caller with no bad record is reliable for tool-heavy work", ab["tools"] == "native"
      and ab["tools_reliable"] and ab["code"], ab)
ab = routing.abilities(loki, "fake-prompted", {})
check("a provider in prompted-tools mode is not reliable for tool-heavy work", ab["tools"] == "prompted"
      and not ab["tools_reliable"], ab)
ab = routing.abilities(loki, "claude-code", {})
check("Claude Code is a coding agent with its own tools", ab["tools"] == "agent" and ab["tools_reliable"], ab)
loki.MODELS["local-tiny"] = loki.ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen3.5:2b")
ab = routing.abilities(loki, "local-tiny", {})
check("a 2B local model is too small to call tools reliably", not ab["tools_reliable"], ab)
ab = routing.abilities(loki, "gemini", {"model_info": {"vision": True, "context": 1_048_576}})
check("abilities from the provider's own metadata beat name guesses", ab["vision"] and ab["context"] == 1_048_576
      and ab["source"] == "provider", ab)
check("fits(): a tool-heavy job does not fit a model that cannot call tools reliably",
      not routing.fits(routing.abilities(loki, "fake-prompted", {}), {"tool_heavy": True})[0])
check("fits(): a picture does not fit a text-only model",
      not routing.fits(routing.abilities(loki, "fake-native", {}), {"vision": True})[0])

# A learned success table from real outcomes (the experience log).
for i in range(6):
    experience.record({"id": "a%d" % i, "goal": "fix bug", "status": "done", "outcome": "verified", "provider": "groq",
                       "model": loki.MODELS["groq"].model, "triage": {"kind": "code"}, "files": ["a.py"], "tool_calls": 3})
    experience.record({"id": "b%d" % i, "goal": "fix bug", "status": "blocked", "outcome": "failed",
                       "provider": "mistral", "model": loki.MODELS["mistral"].model, "triage": {"kind": "code"},
                       "files": ["a.py"], "tool_calls": 2,
                       "route": [{"provider": "cerebras", "reason": "rate/size limit"}]})
routing.reset_caches()
table = routing.success_table()
check("the success table counts per (provider, task kind) from real outcomes",
      table[("groq", "code")]["rate"] == 1.0 and table[("mistral", "code")]["rate"] == 0.0, {k: v for k, v in table.items()})
check("a provider switched away from mid-request counts as a failure for that kind",
      table[("cerebras", "code")]["good"] == 0 and table[("cerebras", "code")]["n"] == 6)
for pid in ("mistral", "groq", "cerebras"):
    loki.MODELS[pid].api_key = "k-" + pid
reg3 = provider_health.Registry(TMP / "h3.json", clock=time.time)
ordered, notes = routing.order_for(loki, ["mistral", "groq"], routing.needs_for({"kind": "code"}), registry=reg3)
check("for code, the provider that did code best goes first (within the same cost tier)",
      ordered == ["groq", "mistral"], ordered)
ordered, notes = routing.order_for(loki, ["mistral", "groq"], routing.needs_for({"kind": "question"}), registry=reg3)
check("for another kind of task the code record changes nothing", ordered == ["mistral", "groq"], ordered)
ordered, notes = routing.order_for(loki, ["mistral", "groq", "cerebras"], routing.needs_for({"kind": "code"}),
                                   registry=reg3)
check("...and it never moves a provider across cost tiers (paid cerebras stays after the free ones)",
      ordered[-1] == "cerebras", ordered)
reg3.record_failure("mistral", "Unauthorized", 401, key="k-mistral")
ordered, notes = routing.order_for(loki, ["mistral", "groq"], routing.needs_for({"kind": "question"}), registry=reg3)
check("a dead provider is left out, and the notes say why", "mistral" not in ordered and "key rejected" in notes["mistral"],
      (ordered, notes))
ordered, notes = routing.order_for(loki, ["fake-prompted", "fake-native"], routing.needs_for({"kind": "code"}),
                                   registry=reg3)
check("tool-heavy work: a model that cannot call tools reliably goes LAST (not removed - no dead end)",
      ordered == ["fake-native", "fake-prompted"] and "tools" in notes["fake-prompted"], (ordered, notes))

# ================================================================== 3. loki's routing
section("3. loki: background jobs, health, pictures, local only, never a dead end, never paid")
saved = (loki.SMART_ORDER, loki.online, loki.local_ready, loki.provider_configured, loki.PREFER, loki.model_name)
fresh = provider_health.Registry(TMP / "h4.json")
provider_health.set_registry(fresh)
loki.SMART_ORDER = ("openrouter", "gemini", "groq", "vireonix", "claude-code", "local")
loki.online = lambda *a, **k: True
loki.local_ready = lambda: True
READY = {"openrouter", "gemini", "groq", "vireonix", "local"}
loki.provider_configured = lambda n: n in READY
loki.PREFER = "local"
loki.model_name = "smart"
loki._SMART_FAILED.clear()
loki.LAST_TRIAGE = {"kind": "question", "difficulty": 1}
loki.messages[:] = [{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]
for pid in ("openrouter", "gemini", "groq"):
    loki.MODELS[pid].api_key = "key-" + pid
loki.MODELS["gemini"].model = "gemini-2.5-flash"
routing.reset_caches()
check("easy chat stays local first (LOKI_PREFER=local)", loki.active_model_name() == "local", loki.active_model_name())
os.environ["LOKI_JOB_ID"] = "job-1"
loki.LAST_TRIAGE = {"kind": "code", "difficulty": 1}
pick = loki.active_model_name()
check("a background job (even 'easy') gets the best FREE capable model, not the 8B local one",
      pick == "openrouter", pick)
READY.discard("openrouter")
READY.discard("gemini")
READY.discard("groq")
check("...a job with only an anonymous keyless route set up stays local (vireonix has not earned it)",
      loki.active_model_name() == "local", loki.active_model_name())
READY.add("claude-code")
check("...and with only Claude Code it stays local too (an unattended job does not use up your plan)",
      loki.active_model_name() == "local", loki.active_model_name())
READY.discard("claude-code")
READY.update({"openrouter", "gemini", "groq"})
os.environ["LOKI_LOCAL_ONLY"] = "1"
check("local only (privacy) keeps even a background job on this computer", loki.active_model_name() == "local")
os.environ.pop("LOKI_LOCAL_ONLY")
os.environ.pop("LOKI_JOB_ID")

loki.PREFER = "cloud"
loki.LAST_TRIAGE = {"kind": "question", "difficulty": 1}
other_process = provider_health.Registry(TMP / "h4.json")
other_process.record_failure("openrouter", "Insufficient credits", 402, key="key-openrouter")
fresh.refresh()
pick = loki.active_model_name()
check("a provider another process found out of credit is skipped up front (no failed request first)",
      pick == "gemini", pick)
check("...and the routing notes say why", "credit" in loki.ROUTE_NOTES.get("openrouter", ""), loki.ROUTE_NOTES)
loki.MODELS["openrouter"].api_key = "a-new-key"
check("a new key brings it straight back", loki.active_model_name() == "openrouter", loki.active_model_name())
loki.MODELS["openrouter"].api_key = "key-openrouter"

loki.messages.append({"role": "user", "content": pic[0]["content"]})
fresh.record_probe("gemini", {"state": "ok", "model_info": {"vision": True, "context": 1_000_000}}, key="key-gemini")
loki.MODELS["groq"].model = "qwen/qwen3.8-27b"
order_before = loki.SMART_ORDER
loki.SMART_ORDER = ("groq", "gemini", "local")
pick = loki.active_model_name()
check("a picture goes to a model that can see (gemini), past one that cannot (groq)", pick == "gemini", pick)
loki.messages[:] = [{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]
check("without a picture the order is as before (groq first)", loki.active_model_name() == "groq")
loki.SMART_ORDER = order_before

for pid in ("gemini", "groq"):
    fresh.record_failure(pid, "quota exceeded RESOURCE_EXHAUSTED", 429, key="key-" + pid)
fresh.record_failure("vireonix", "rate limit", 429, key=loki.MODELS["vireonix"].api_key)
loki.provider_configured = lambda n: n in {"openrouter", "gemini", "groq", "vireonix"}
loki._SMART_FAILED.update({"openrouter"})
loki._SMART_FAILED.discard("x")
check("never a dead end: with everything spent, the one whose limit ends soonest is tried (not a missing local model)",
      loki.active_model_name() == "vireonix", loki.active_model_name())
loki._SMART_FAILED.clear()
check("clearing the used-up set (an in-process revive) also forgets this process's health marks",
      fresh.usable("gemini", "key-gemini")[0])
check("...while the other process's mark (openrouter's credit) stays", not fresh.usable("openrouter", "key-openrouter")[0])

loki.MODELS["paid-one"] = loki.ModelConfig(base_url="https://paid.example/v1", api_key="k", model="m")
loki._METERED_DEFAULT.add("paid-one")
loki.SMART_ORDER = ("paid-one", "groq")
loki.provider_configured = lambda n: n in {"paid-one", "groq"}
loki.ALLOW_PAID = False
check("a paid provider is never picked on its own", loki.active_model_name() == "groq")
loki.SMART_ORDER = ("openrouter", "gemini", "groq", "vireonix", "claude-code", "local")
loki.provider_configured = lambda n: n in READY

pid, why = loki.route_for(routing.needs_for({"kind": "code", "difficulty": 1}, background=True))
check("route_for explains a choice in words", pid and why, (pid, why))
loki.model_name = "groq"
check("a pinned model is reported as pinned", "pinned" in loki.route_for(routing.needs_for({}))[1])
loki.model_name = "smart"

# ================================================================== 4. mid-task failover, real HTTP
section("4. mid-task failover against a fake OpenAI-compatible server (the conversation is kept)")


class FakeCloud:
    """/<name>/v1/chat/completions answers from a script: a list of (status, body, headers, delay)."""

    def __init__(self):
        self.script: dict = {}
        self.calls: list = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                return

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                name = self.path.strip("/").split("/")[0]
                fake.calls.append((name, body))
                steps = fake.script.get(name) or [(500, {"error": "no script"}, {}, 0)]
                step = steps.pop(0) if len(steps) > 1 else steps[0]
                status, payload, headers, delay = step
                if delay:
                    time.sleep(delay)
                if callable(payload):
                    payload = payload(body)
                raw = json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    for k, v in (headers or {}).items():
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, name):
        return "http://127.0.0.1:%d/%s/v1" % (self.port, name)


def ok_text(text):
    return (200, {"id": "x", "object": "chat.completion", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}, {}, 0)


def ok_tool(name, args):
    return (200, {"id": "x", "object": "chat.completion", "choices": [{"index": 0, "finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}, {}, 0)


def err(status, message, headers=None, delay=0):
    return (status, {"error": {"message": message, "code": status}}, headers or {}, delay)


cloud = FakeCloud()
NAMES = ("openrouter", "gemini", "groq", "mistral")
for pid in NAMES:
    loki.MODELS[pid] = loki.ModelConfig(base_url=cloud.url(pid), api_key="key-" + pid, model="model-" + pid)
loki.SMART_ORDER = NAMES
loki.ONLINE_ORDER = NAMES
loki.provider_configured = lambda n: n in NAMES
loki.local_ready = lambda: False
loki.PREFER = "cloud"
loki.model_name = "smart"
loki.loki_progress_callback = lambda event, text: None
loki.RETRY_BASE_S = 0.05
loki.RETRY_MAX_S = 0.2
loki.RATE_LIMIT_WAIT_S = 0


def run_turn(prompt):
    loki.messages[:] = [{"role": "system", "content": "You are LOKI."}, {"role": "user", "content": prompt}]
    loki.ROUTE_TRACE.clear()
    loki._SMART_FAILED.clear()
    cloud.calls.clear()
    provider_health.set_registry(provider_health.Registry(TMP / ("h-%s.json" % time.time_ns())))
    routing.reset_caches()
    try:
        return asyncio.run(asyncio.wait_for(loki.agent_turn(), timeout=120))
    except Exception as exc:  # noqa: BLE001
        return "EXC %s: %s" % (type(exc).__name__, exc)


def tried():
    return [name for name, _ in cloud.calls]


cases = [
    ("429 with a long Retry-After", err(429, "Rate limit reached. Please try again in 2m0s.", {"Retry-After": "120"}),
     "rate_limited", "rate/size limit"),
    ("402 out of credit", err(402, "Insufficient credits. Add more using https://openrouter.ai/settings/credits"),
     "no_credit", "quota spent"),
    ("401 key rejected", err(401, "Incorrect API key provided"), "key_rejected", "key rejected"),
    ("Gemini's spent quota (429 RESOURCE_EXHAUSTED)", err(429, "You exceeded your current quota. RESOURCE_EXHAUSTED"),
     "quota", "quota spent"),
]
for label, failure, state, reason in cases:
    cloud.script = {"openrouter": [ok_tool("list_tree", {}), failure],
                    "gemini": [ok_text("DONE: finished on gemini")]}
    answer = run_turn("list the files")
    trail = tried()
    check("%s: the turn moved to the next provider and finished" % label, "finished on gemini" in answer, (answer, trail))
    got = [b for n, b in cloud.calls if n == "gemini"]
    check("%s: the next provider got the WHOLE conversation (the earlier tool result too)" % label,
          got and any(m.get("role") == "tool" for m in got[0]["messages"]) and
          any(m.get("role") == "user" and m.get("content") == "list the files" for m in got[0]["messages"]), got[:1])
    check("%s: no long back-off on the failing provider (at most one retry)" % label,
          trail.count("openrouter") <= 3, trail)
    h = provider_health.registry().get("openrouter")
    check("%s: health remembers it as %s" % (label, state), h.get("state") == state, h)
    check("%s: the route trace says '%s'" % (label, reason),
          loki.ROUTE_TRACE and loki.ROUTE_TRACE[0]["provider"] == "openrouter" and loki.ROUTE_TRACE[0]["reason"] == reason,
          loki.ROUTE_TRACE)
h = provider_health.registry().get("openrouter")

cloud.script = {"openrouter": [err(400, "This model's maximum context length is 8192 tokens. However, your messages "
                                        "resulted in 9000 tokens.")],
                "gemini": [ok_text("DONE: long one on gemini")]}
answer = run_turn("summarise this long thing")
check("context too long: fails over to a provider with room", "long one on gemini" in answer, (answer, tried()))
check("...and the window it named is remembered (8192)", provider_health.registry().get("openrouter").get("context") == 8192,
      provider_health.registry().get("openrouter"))
check("...the route says why", loki.ROUTE_TRACE and loki.ROUTE_TRACE[0]["reason"] == "context too long", loki.ROUTE_TRACE)

loki.MODEL_TIMEOUT_S = 1.0
cloud.script = {"openrouter": [ok_text("too late")[:3] + (3,)], "gemini": [ok_text("DONE: answered after a timeout")]}
started = time.monotonic()
answer = run_turn("hello")
took = time.monotonic() - started
check("a timeout: one retry, then the next provider answers", "answered after a timeout" in answer, (answer, tried()))
check("...without four slow retries (under ~10 s)", took < 10, took)
check("...health says it did not answer", provider_health.registry().get("openrouter").get("state") == "unreachable",
      provider_health.registry().get("openrouter"))
loki.MODEL_TIMEOUT_S = 180.0

empty = (200, {"id": "x", "object": "chat.completion", "choices": [], "usage": None}, {}, 0)
cloud.script = {"openrouter": [empty, empty], "gemini": [ok_text("DONE: not empty")]}
answer = run_turn("hello")
check("empty choices: asked again once, then failed over (no IndexError)", "not empty" in answer, (answer, tried()))
check("...an empty reply is named in the route", loki.ROUTE_TRACE and loki.ROUTE_TRACE[0]["reason"] == "empty reply",
      loki.ROUTE_TRACE)

cloud.script = {"openrouter": [err(413, "Request too large for model on tokens per minute (TPM): Limit 600, Requested "
                                        "900, please reduce your message size")],
                "gemini": [ok_text("DONE: big one")]}
answer = run_turn("x" * 4000)
check("413 (Groq's per-minute size limit): fails over", "big one" in answer, (answer, tried()))
check("...the limit is remembered", provider_health.registry().get("openrouter").get("max_request") == 600)
cloud.calls.clear()
loki._SMART_FAILED.clear()
loki.messages[:] = [{"role": "system", "content": "s"}, {"role": "user", "content": "y" * 4000}]
check("...and the next big request skips it up front", loki.active_model_name() == "gemini", loki.ROUTE_NOTES)
loki.messages[:] = [{"role": "system", "content": "s"}, {"role": "user", "content": "short"}]
loki._TOOL_CHARS["n"] = 100
check("...while a small one may still use it", loki.active_model_name() == "openrouter", loki.ROUTE_NOTES)
loki._TOOL_CHARS["n"] = 0

cloud.script = {"openrouter": [err(429, "Too Many Requests")], "gemini": [err(429, "Too Many Requests")],
                "groq": [err(401, "Invalid API Key")], "mistral": [ok_text("DONE: mistral saved the day")]}
answer = run_turn("hello")
check("a chain of failures (429, 429, 401) still ends on the one that works", "mistral saved the day" in answer,
      (answer, tried()))
check("...each hop recorded with its reason",
      [r["reason"] for r in loki.ROUTE_TRACE] == ["rate/size limit", "rate/size limit", "key rejected"], loki.ROUTE_TRACE)

# A background job is its own process: it must know what the engine learned.
shared = TMP / "shared_health.json"
provider_health.set_registry(provider_health.Registry(shared))
provider_health.registry().record_failure("openrouter", "You exceeded your current quota", 429, key="key-openrouter",
                                          session=False)
code = ("import sys; sys.path.insert(0, %r); import loki\n"
        "loki.online = lambda *a, **k: True\nloki.local_ready = lambda: False\n"
        "for p in %r:\n    loki.MODELS[p].api_key = 'key-' + p\n"
        "loki.SMART_ORDER = %r\nloki.provider_configured = lambda n: n in %r\nloki.PREFER='cloud'\n"
        "print('PICK=' + loki.active_model_name())\n") % (str(REPO / "engine"), NAMES, NAMES, NAMES)
env = dict(os.environ, LOKI_HEALTH_FILE=str(shared), LOKI_JOB_ID="job-x", LOKI_MODEL="smart")
out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
check("a new background-job process skips the provider the engine found spent", "PICK=gemini" in out.stdout,
      (out.stdout[-300:], out.stderr[-500:]))

# ================================================================== 5. local models
section("5. local models: Ollama version, Bonsai, num_ctx, the condenser, MLX")
check("versions parse", model_setup.parse_version("0.40.5") == (0, 40, 5)
      and model_setup.parse_version("ollama version is 0.40.6-rc1") == (0, 40, 6) and model_setup.parse_version("") == ())
bon = model_setup.bonsai_support("0.40.5", "win32")
check("Ollama 0.40.5 cannot run Bonsai 2, and the PC is told the one command (winget)",
      bon["ok"] is False and "0.40.6" in bon["message"] and bon["upgrade"]["command"] == "winget upgrade --id Ollama.Ollama -e", bon)
check("the Mac is told brew (or the app's own update)", "brew upgrade ollama" in model_setup.ollama_upgrade("darwin")["command"])
check("0.40.6 runs it; an unknown version blocks nothing", model_setup.bonsai_support("0.40.6")["ok"] is True
      and model_setup.bonsai_support("")["ok"] is None)
models = [{"name": "hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Ternary-Bonsai-2-9B-Q2_0", "size_gb": 2.6},
          {"name": "qwen3:8b", "size_gb": 5.2}]
caps = lambda n: ["completion", "tools"]  # noqa: E731
check("on Ollama 0.40.5 the best local model is NOT Bonsai (it would answer gibberish)",
      model_setup.best_installed(models, 7.0, caps=caps, version="0.40.5")["name"] == "qwen3:8b")
check("on 0.40.6 Bonsai 2 9B wins (83 vs 78)", "Bonsai" in model_setup.best_installed(models, 7.0, caps=caps, version="0.40.6")["name"])
machine = {"ram_gb": 32, "vram_gb": 8, "disk_free_gb": 200, "ollama_version": "0.40.5"}
rows = model_setup.plan(machine, [])["rows"]
check("the download plan never offers Bonsai to an Ollama that cannot run it", rows and not any(r.get("family") == "bonsai" for r in rows))
check("...and does once Ollama is new enough", any(r.get("family") == "bonsai" for r in
                                                    model_setup.plan(dict(machine, ollama_version="0.41.0"), [])["rows"]))
check("required_context: never less than LOKI's prompt + tools + room, 4k steps, 32k cap",
      model_setup.required_context(3500, {"budget_gb": 7}) == 8192
      and model_setup.required_context(9000, {"budget_gb": 7}) == 16384
      and model_setup.required_context(3500, {"budget_gb": 30}) == 32768
      and model_setup.required_context(90000, {"budget_gb": 7}) == 32768)

from fake_ollama import FakeOllama  # noqa: E402

fake = FakeOllama(models=["qwen3:8b", "hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Ternary-Bonsai-2-9B-Q2_0"],
                  port=0, version="0.40.5").start()
fake_url = "http://127.0.0.1:%d" % fake.server.server_address[1]
saved_ollama = model_setup.OLLAMA
model_setup.OLLAMA = fake_url
model_setup._CAPS.clear()
check("ollama_version reads /api/version", model_setup.ollama_version() == "0.40.5")
name = model_setup.ensure_context("qwen3:8b", 16384, model_setup.ollama_models())
made = fake.created.get("loki-qwen3-8b") or {}
check("ensure_context makes a loki-* variant with num_ctx (Ollama's OpenAI endpoint ignores it per request)",
      name == "loki-qwen3-8b" and made.get("parameters", {}).get("num_ctx") == 16384, (name, made))
ctx = model_setup.model_context("loki-qwen3-8b")
check("model_context reads the variant's real num_ctx and the model's trained maximum",
      ctx["num_ctx"] == 16384 and ctx["trained"] == 40960, ctx)
fake.created.clear()
fake.created["loki-qwen3-8b"] = {"model": "loki-qwen3-8b", "from": "qwen3:8b", "parameters": {"num_ctx": 4096}}
model_setup.ensure_context("qwen3:8b", 16384, model_setup.ollama_models())
check("an older variant with a smaller window is made again with the bigger one",
      fake.created["loki-qwen3-8b"]["parameters"]["num_ctx"] == 16384, fake.created)
fake.loaded_context["loki-qwen3-8b"] = 16384

saved_local = (loki.LOCAL_STATE.copy(), dict(loki.HARDWARE), loki.MODELS["local"])
loki.HARDWARE.clear()
loki.HARDWARE.update({"budget_gb": 7.0, "vram_gb": 8.0, "ram_gb": 32})
loki._CTX_DONE.clear()
loki.LOCAL_STATE["warm"] = "x"
saved_warm = model_setup.keep_warm
model_setup.keep_warm = lambda *a, **k: True
state = loki.resolve_local(force=True)
check("resolve_local on Ollama 0.40.5 skips the installed Bonsai and says why",
      "qwen3" in state["name"] and "Bonsai" in state.get("skipped", ""), state)
check("...the local model runs with a window that holds LOKI's prompt (loki-* variant, real context read back)",
      state["name"].startswith("loki-") and state["context"] >= 8192 and state["context"] >= state["wanted_context"], state)
check("...and the condenser keeps a local conversation inside that window",
      0 < condenser.LOCAL_WINDOW_TOKENS < state["context"]
      and condenser.limits(local=True, env={})[1] <= int(condenser.LOCAL_WINDOW_TOKENS * 3.5) + 1, condenser.LOCAL_WINDOW_TOKENS)
rep = loki.local_report()
check("local_report names the Ollama version and the Bonsai update in 'needs you'",
      rep["version"] == "0.40.5" and any("Bonsai" in x and "0.40.6" in x for x in rep["needs_you"]), rep)
fake.version = "0.40.6"
model_setup._CAPS.clear()
loki._CTX_DONE.clear()
state = loki.resolve_local(force=True)
check("after the update Bonsai 2 is the local model (with its own window)", "bonsai" in state["name"].lower()
      and state["name"].startswith("loki-"), state)
model_setup.keep_warm = saved_warm
check("MLX: the Bonsai 2 server command for Apple Silicon is known (mlx-vlm)",
      "mlx_vlm.server" in model_setup.mlx_status(opener=fake_open({}))["bonsai_command"])
env_mlx = os.environ.get("MLX_BASE_URL")
os.environ["MLX_BASE_URL"] = "http://127.0.0.1:1/v1"
srv = model_setup.other_servers(opener=fake_open({"/v1/models": (200, {"data": [{"id": "some/hf-cache-model"}]})}),
                                include_mlx=True)
check("an MLX server is a local fallback, asked for 'default_model' (its /models lists the HF cache)",
      any(s["key"] == "mlx" and s["models"] == ["default_model"] for s in srv), srv)
if env_mlx is None:
    os.environ.pop("MLX_BASE_URL", None)
else:
    os.environ["MLX_BASE_URL"] = env_mlx

# ================================================================== 6. doctor + Settings
section("6. /models doctor and Settings > Connections")
for pid in NAMES:
    loki.MODELS[pid].api_key = "key-" + pid
loki._SMART_FAILED.clear()
provider_health.set_registry(provider_health.Registry(TMP / "h-doctor.json"))
reg = provider_health.registry()
reg.record_failure("mistral", "Unauthorized", 401, key="key-mistral")
reg.record_failure("gemini", "quota exceeded per day", 429, key="key-gemini")
reg.record_probe("groq", {"state": "ok", "model_info": {"vision": False, "context": 131072, "tools": True}}, key="key-groq")
loki.online = lambda *a, **k: True
loki.local_ready = lambda: True
loki.PREFER = "local"
loki.model_name = "smart"
doc = routing.doctor(loki)
text = doc["text"]
print("\n".join("    | " + line for line in text.splitlines()))
check("the doctor answers for every kind of task", all(r["provider"] for r in doc["routes"])
      and [r["id"] for r in doc["routes"]] == ["chat", "code", "pictures", "long", "background", "hard"], doc["routes"])
check("...in plain words: '<task> -> <provider> (<model>), because ...'",
      "Chat and questions -> local" in text and "Background jobs -> " in text and "because" in text, text)
bg = next(r for r in doc["routes"] if r["id"] == "background")
check("background jobs are routed past the local model, and it says why", bg["provider"] != "local"
      and "background" in bg["why"], bg)
check("it lists what is skipped right now with the one-line fix",
      "mistral: key rejected" in text and "Fix: Paste a new" in text and "gemini: free quota used up" in text, text)
check("a rejected key is a 'needs you' item", any(x.startswith("mistral") for x in doc["needs_you"]), doc["needs_you"])
check("the local side is in it (Ollama version, Bonsai)", "Ollama 0.40.6" in text, text)
state_obj = types.SimpleNamespace(agent=loki)
code_, payload = portal_api.handle_get(state_obj, "/models/doctor")
check("GET /models/doctor serves it to the window", code_ == 200 and payload["text"] == routing.doctor(loki)["text"])
code_, payload = portal_api.handle_get(state_obj, "/providers")
cards = {p["id"]: p for p in payload["providers"]}
check("each Connections card carries the live health and the fix",
      cards["mistral"]["health"]["state"] == "key_rejected" and "Paste a new" in cards["mistral"]["health"]["fix"]
      and cards["groq"]["health"]["live"], cards["mistral"].get("health"))
code_, payload = portal_api.handle_get(state_obj, "/providers/health")
check("GET /providers/health returns the registry without keys", code_ == 200 and "mistral" in payload["providers"]
      and "key_fp" not in json.dumps(payload))
check("'Private: only models on this computer' is a General setting", "LOKI_LOCAL_ONLY" in portal_api.GENERAL)
html = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
js = (REPO / "app" / "ui" / "settings.js").read_text(encoding="utf-8")
wb = (REPO / "app" / "ui" / "workbench.js").read_text(encoding="utf-8")
check("Settings > Connections has 'Explain routing' and 'Re-check'", 'id="routing-doctor"' in html
      and 'id="routing-recheck"' in html and "/models/doctor" in js and "/providers/probe" in js)
check("the cards show health and the fix", "pcard-health" in js and "Fix: " in js)
check("'/models doctor' is a command in the message box", 'name: "models"' in wb and "/models/doctor" in wb)
buf = io.StringIO()
saved_stdout = sys.stdout
sys.stdout = buf
try:
    loki.handle_command("/models doctor")
finally:
    sys.stdout = saved_stdout
check("and in the terminal: /models doctor", "Background jobs ->" in buf.getvalue(), buf.getvalue()[:300])
ship_src = (REPO / "tools" / "ship.py").read_text(encoding="utf-8")
check("this suite runs in tools/ship.py, with its own health file per suite", '"test_routing_core"' in ship_src
      and "LOKI_HEALTH_FILE" in ship_src)

fake.stop()
model_setup.OLLAMA = saved_ollama
(loki.SMART_ORDER, loki.online, loki.local_ready, loki.provider_configured, loki.PREFER, loki.model_name) = saved

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
