"""Bonsai 2 in the model catalog, TimesFM-3 forecasting in the core (routing, memory guard,
spend outlook, the forecast_series tool) and Higgsfield images/video - all offline, with fakes.

    python tests/test_models_media.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import forecast  # noqa: E402
import higgsfield  # noqa: E402
import model_setup  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:240]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


# keep TimesFM out of the way whatever this machine has installed
forecast._MODEL["state"] = "missing"

section("forecast: the statistical fallback follows the series")
up = forecast.forecast([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], horizon=3)
check("a rising series keeps rising", up["median"][0] > 10 and up["median"][2] > up["median"][0], up)
check("the band is ordered q10 <= median <= q90",
      all(a <= b <= c for a, b, c in zip(up["q10"], up["median"], up["q90"])))
check("the backend is reported", up["backend"] == "statistical", up["backend"])
flat = forecast.forecast([5, 5, 5, 5, 5, 5], horizon=4)
check("a flat series stays flat", all(abs(x - 5) < 0.01 for x in flat["median"]), flat["median"])
few = forecast.forecast([3], horizon=2)
check("too few points repeats the last value", few["median"] == [3.0, 3.0] and few["backend"] == "too-few-points")
check("the horizon is bounded", len(forecast.forecast(list(range(20)), horizon=10000)["median"]) == 256)

section("forecast: routing moves a provider that is getting slow to the back")
now = time.time()
entries = [{"t": now - 60 * i, "provider": "fast", "ms": 900 + (i % 3) * 50} for i in range(12)]
entries += [{"t": now - 60 * i, "provider": "slow", "ms": 15000 + i * 100} for i in range(12)]
outlook = forecast.provider_outlook(entries)
check("an outlook per provider with enough calls", set(outlook) == {"fast", "slow"}, outlook)
check("slow is moved back, the rest keeps its order",
      forecast.reorder(["slow", "other", "fast"], outlook) == ["other", "fast", "slow"])
check("one known provider changes nothing", forecast.reorder(["slow", "x"], {"slow": outlook["slow"]}) == ["slow", "x"])
os.environ["LOKI_FORECAST"] = "off"
check("LOKI_FORECAST=off turns it off", forecast.reorder(["slow", "fast"], outlook) == ["slow", "fast"])
del os.environ["LOKI_FORECAST"]

section("forecast: the memory guard unloads idle models before the machine swaps")
forecast.MEMORY["samples"].clear()
forecast.MEMORY["actions"].clear()
freed = []
seq = iter([0.80, 0.83, 0.86, 0.88, 0.90, 0.91])
result = {}
for _ in range(6):
    result = forecast.memory_tick(False, lambda: freed.append("qwen") or ["qwen"], sample=lambda: next(seq))
check("climbing memory while idle frees models, once (then gives the OS time)", freed == ["qwen"], (freed, result))
check("the forecast peak is a share, never over 100%", 0 < result["forecast_peak"] <= 1.0, result)
forecast.MEMORY["samples"].clear()
forecast.MEMORY["actions"].clear()
freed.clear()
seq = iter([0.80, 0.83, 0.86, 0.88, 0.90, 0.91])
for _ in range(6):
    forecast.memory_tick(True, lambda: freed.append("qwen") or ["qwen"], sample=lambda: next(seq))
check("...but never while LOKI is working", freed == [])
check("an unreadable sample is reported, not raised", not forecast.memory_tick(False, list, sample=lambda: None)["ok"])

section("forecast: the agent tool")
import loki  # noqa: E402
out = loki.forecast_series([1, 2, 3, 4, 5, 6], 3)
check("forecast_series answers with a median and a band", "median:" in out and "90%:" in out, out)
check("...refuses non-numbers", loki.forecast_series(["a"], 2).startswith("error"))
check("forecast_series and generate_media are offered to the model",
      {"forecast_series", "generate_media"} <= loki.MODEL_TOOL_NAMES)
check("both are in a tool category", "forecast_series" in loki.TOOL_CATEGORIES["planning"]
      and "generate_media" in loki.TOOL_CATEGORIES["creative"])

section("Bonsai 2 in the model catalog")
tags = [m["tag"] if isinstance(m, dict) and "tag" in m else (m.get("name") if isinstance(m, dict) else m)
        for m in model_setup.CATALOG]
bonsai = [t for t in tags if t and "Ternary-Bonsai-2" in str(t)]
check("the 9B, 4B and 2B GGUF builds are listed", len(bonsai) == 3, bonsai)
check("a known quality score for Bonsai 2", any(k.startswith("bonsai-2") for k, _ in model_setup.KNOWN_SCORES))
check("every Bonsai tag names the Q2_0 FILE (the short :Q2_0 tag also matches the unloadable PQ2_0 pack)",
      all(":Ternary-Bonsai-2-" in str(t) and str(t).endswith("-Q2_0") for t in bonsai), bonsai)

section("more models: uncensored builds and your own entries")
check("uncensored builds carry a tag, roles and a why",
      bool(model_setup.UNCENSORED) and all(e.get("tag") and e.get("roles") and e.get("why")
                                           for e in model_setup.UNCENSORED), model_setup.UNCENSORED)
check("an out-of-date Ollama raises an update prompt",
      model_setup.ollama_advice("0.40.5")["needs_update"]
      and not model_setup.ollama_advice("0.40.6")["needs_update"]
      and model_setup.ollama_advice("0.40.5")["upgrade"].get("command"))
check("the uncensored family has a known quality score",
      any("abliterat" in k or "dolphin" in k for k, _ in model_setup.KNOWN_SCORES))
check("uncensored() reports what fits and what is installed",
      any(e["installed"] for e in model_setup.uncensored({"budget_gb": 16}, installed=["dolphin3:8b"])))
check("recommend() offers uncensored builds only when asked",
      any(e.get("family") in ("abliterated", "uncensored")
          for e in model_setup.recommend({"budget_gb": 16}, include_uncensored=True))
      and not any(e.get("family") in ("abliterated", "uncensored")
                  for e in model_setup.recommend({"budget_gb": 16})))
import tempfile as _tempfile  # noqa: E402
_custom = Path(_tempfile.mkdtemp()) / "models_custom.json"
_custom.write_text(json.dumps([{"tag": "my/model:7b", "size": 4, "need": 6, "score": 71, "why": "mine"},
                               {"nope": True}, "junk"]), encoding="utf-8")
_env = {"LOKI_MODELS_EXTRA": str(_custom)}
check("your own models load from the file, bad entries skipped",
      [e["tag"] for e in model_setup.extra_catalog(_env)] == ["my/model:7b"], model_setup.extra_catalog(_env))
check("...and they join the suggested catalog",
      any(e["tag"] == "my/model:7b" for e in model_setup.full_catalog(_env)))
check("recommend() includes your own model",
      any(e["tag"] == "my/model:7b" for e in model_setup.recommend({"budget_gb": 16}, env=_env)))


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def ollama(answer):
    return lambda req, timeout=0: Reply(json.dumps({"response": answer}).encode())


check("a sane answer passes the smoke test", model_setup.verify_runs("bonsai", opener=ollama("Blue."))[0])
bad = model_setup.verify_runs("bonsai", opener=ollama("#$%&@!#$%^&*"))
check("gibberish (an old runtime) fails it with a reason", not bad[0] and "instead" in bad[1], bad)

section("pinning a local model gives it an agent-sized context window")
_created: list = []


def _tags(models):
    return lambda req, timeout=0: Reply(json.dumps({"models": [{"name": n} for n in models]}).encode())


def _creator(req, timeout=0):
    _created.append(json.loads(req.data.decode()))
    return Reply(b"{}")


import urllib.request as _urllib  # noqa: E402
_hw = {"budget_gb": 16.0}
_listed = _tags(["qwen3.5:9b", "hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Ternary-Bonsai-2-9B-Q2_0"])
_kept = model_setup.with_long_context("hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Ternary-Bonsai-2-9B-Q2_0",
                                      info=_hw, opener=_listed)
check("a huge HF name becomes a usable loki-<name> variant", _kept.startswith("loki-hf.co-prism-ml")
      and _kept.endswith("q2_0"), _kept)


def _create_flow(model, info, models):
    """ensure_context's two calls: /api/tags is a plain URL, /api/create a Request."""
    def opener(req, timeout=0):
        url = getattr(req, "full_url", req)
        if "/api/create" in url:
            _created.append(json.loads(req.data.decode()))
            return Reply(b"{}")
        return Reply(json.dumps({"models": [{"name": n} for n in models]}).encode())
    return opener


_created.clear()
_kept2 = model_setup.with_long_context("qwen3.5:9b", info=_hw,
                                       opener=_create_flow("qwen3.5:9b", _hw, ["qwen3.5:9b"]))
check("it is created with num_ctx for this machine's memory", _created
      and _created[0]["parameters"]["num_ctx"] == model_setup.context_for(_hw), _created)
check("...and the variant, not the bare model, is what LOKI ends up running",
      _kept2 == model_setup.derived_name("qwen3.5:9b"), _kept2)
check("an existing variant is reused, not created again",
      model_setup.with_long_context(model_setup.derived_name("qwen3.5:9b"), info=_hw,
                                    opener=_tags([model_setup.derived_name("qwen3.5:9b")]))
      == model_setup.derived_name("qwen3.5:9b"))
check("a model Ollama does not serve (an MLX model) is left exactly as it was",
      model_setup.with_long_context("mlx-community/Qwen3-4B-4bit", info=_hw, opener=_listed)
      == "mlx-community/Qwen3-4B-4bit")
check("with Ollama down nothing is changed", model_setup.with_long_context(
    "qwen3.5:9b", info=_hw, opener=lambda req, timeout=0: (_ for _ in ()).throw(OSError("down")))
    == "qwen3.5:9b")

section("Higgsfield: the key is the user's, and only from LOKI's own settings")
check("no key, not configured", not higgsfield.configured({}))
check("HIGGSFIELD_KEY", higgsfield.credential({"HIGGSFIELD_KEY": "k:s"}) == "k:s")
check("the SDK's HF_API_KEY + HF_API_SECRET", higgsfield.credential({"HF_API_KEY": "k", "HF_API_SECRET": "s"}) == "k:s")
check("without a key it says where to paste one", "Settings" in higgsfield.submit("a/b", {}, env={})["error"])
check("an odd application id is refused", not higgsfield.submit("../../x", {}, env={"HIGGSFIELD_KEY": "k:s"})["ok"])

section("Higgsfield: submit, poll, download")
TMP = Path(tempfile.mkdtemp(prefix="loki-hf-"))
seen = []
polls = iter(["queued", "in_progress", "completed"])


def fake(req, timeout=0):
    seen.append((req.get_method(), req.full_url, req.headers.get("Authorization"), req.data))
    if req.get_method() == "POST":
        return Reply(json.dumps({"request_id": "r1", "status_url": higgsfield.BASE_URL + "/requests/r1/status",
                                 "cancel_url": higgsfield.BASE_URL + "/requests/r1/cancel"}).encode())
    if req.full_url.endswith("/status"):
        status = next(polls)
        body = {"status": status}
        if status == "completed":
            body["images"] = [{"url": "https://cdn.example/out.png"}]
        return Reply(json.dumps(body).encode())
    return Reply(b"\x89PNG fake")


r = higgsfield.generate("a lake at dawn", workspace=TMP, env={"HIGGSFIELD_KEY": "k:s"}, opener=fake, sleep=lambda s: None)
check("it finishes and saves the image in images/", r["ok"] and r["files"] and r["files"][0].startswith("images/"), r)
check("the file is really there", r["ok"] and (TMP / r["files"][0]).read_bytes().startswith(b"\x89PNG"))
post = seen[0]
check("the request goes to the application with the key header",
      post[0] == "POST" and post[1].endswith("/" + higgsfield.IMAGE_APP) and post[2] == "Key k:s", post[:3])
check("the prompt is in the body", json.loads(post[3])["prompt"] == "a lake at dawn")
check("the download does not carry the key", seen[-1][2] is None)
check("a video needs an application id", "model=" in higgsfield.generate("x", kind="video", env={"HIGGSFIELD_KEY": "k"})["error"])
check("a status URL outside Higgsfield is refused", not higgsfield.wait("https://evil.example/s", env={"HIGGSFIELD_KEY": "k"})["ok"])
polls = iter(["nsfw"])
r2 = higgsfield.generate("x", workspace=TMP, env={"HIGGSFIELD_KEY": "k:s"}, opener=fake, sleep=lambda s: None)
check("a refusal is reported plainly", not r2["ok"] and "NSFW" in r2["error"], r2)
shutil.rmtree(TMP, ignore_errors=True)

section("Settings never sends the Higgsfield key back to the window")
import portal_api  # noqa: E402
check("the key is a secret setting", portal_api.GENERAL["HIGGSFIELD_KEY"]["kind"] == "secret")
os.environ["HIGGSFIELD_KEY"] = "super:secret"


class FakeAgent:
    model_name = "x"


class FakeState:
    agent = FakeAgent()


code, body = portal_api.handle_get(FakeState(), "/settings/general")
check("GET /settings/general hides it and says it is saved",
      "super:secret" not in json.dumps(body) and body["secrets_saved"]["HIGGSFIELD_KEY"] is True)
del os.environ["HIGGSFIELD_KEY"]
ui = (REPO / "app" / "ui")
check("the window shows it as a password field", 'spec.kind === "secret"' in (ui / "settings.js").read_text(encoding="utf-8"))
check("/image is a workbench command", 'name: "image"' in (ui / "workbench.js").read_text(encoding="utf-8"))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
