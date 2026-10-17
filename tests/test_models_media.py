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
