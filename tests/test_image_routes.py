"""Image routes that cannot work are benched, and a timeout moves on to the next NVIDIA model (2026-10-28 on the
Mac: every manga sheet waited 180 s on flux.2-klein, skipped flux.1-dev/schnell, then tried Gemini (free-tier
limit 0) and Hugging Face (HTTP 410) again)."""
import os
import sys
import tempfile
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine" / "runners"))
os.environ["LOKI_DATA"] = tempfile.mkdtemp()
os.environ["NVIDIA_API_KEY"] = "test-key"
import imagegen  # noqa: E402

PASSED = FAILED = 0


def check(name, ok):
    global PASSED, FAILED
    print(("  PASS " if ok else "  FAIL ") + name)
    PASSED, FAILED = PASSED + bool(ok), FAILED + (not ok)


t0 = time.time()
tried = []


def fake_call(url, key, body, headers, timeout):
    tried.append(url.rsplit("/", 1)[-1])
    if "klein" in url:
        raise TimeoutError("The read operation timed out")
    import base64
    return {"artifacts": [{"base64": base64.b64encode(b"\x89PNG fake").decode()}]}


out = tempfile.mkdtemp()
try:
    res = imagegen.nvidia("a fox", 1024, 1024, out, 7, request=fake_call, sleep=lambda s: None)
    ok = res.get("model", "").endswith("flux.1-dev")
except Exception as exc:  # noqa: BLE001
    ok, res = False, str(exc)
check("a timed-out NVIDIA model moves on to the next one", ok and tried[:2] == ["flux.2-klein-4b", "flux.1-dev"])
imagegen._bench_file().unlink(missing_ok=True)   # that timeout benched klein; the next checks start clean

check("all-410 is benched for days", imagegen.bench_for("FLUX.1-dev: HTTP 410; FLUX.1-schnell: HTTP 410")[0] >= 86400)
check("a free-tier limit of 0 is benched",
      imagegen.bench_for("HTTP 429 Rate limit exceeded (limit: 0 input tokens per minute on Free Tier)")[0] > 0)
check("a passing 429 is not benched", imagegen.bench_for("HTTP 429 rate limit, retry in 20s")[0] == 0)
check("one 410 among other errors is not benched", imagegen.bench_for("a: HTTP 410; b: HTTP 500")[0] == 0)

os.environ["HF_TOKEN"] = "hf_test"
imagegen.bench("huggingface", 3600, "every model answered HTTP 410 (retired)")
plan = imagegen.plan_order("auto")
check("a benched route leaves the order and says why",
      "huggingface" not in plan["order"] and "benched" in plan["skipped"].get("huggingface", ""))
check("a forced backend is still tried", imagegen.plan_order("huggingface")["order"] == ["huggingface"])
check("a 1536x1024 sheet is sent to FLUX.2 as 1024x672", imagegen.fit_side(1536, 1024, 1024) == (1024, 672))
check("a wide strip panel still gets FLUX.2's 512 px minimum", imagegen.fit_side(1536, 448, 1024, 512) == (1024, 512))
check("a 1024x1024 picture is left as it is", imagegen.fit_side(1024, 1024, 1024) == (1024, 1024))
sizes = []
imagegen.nvidia("a fox", 1536, 1024, tempfile.mkdtemp(), 3, sleep=lambda s: None,
                request=lambda u, k, b, h, t: sizes.append((b["width"], b["height"])) or
                {"artifacts": [{"base64": "iVBORw0KGgo="}]})
check("FLUX.2 gets the fitted size", sizes[:1] == [(1024, 672)])
long_prompt = "Character reference sheet for a manga: " + ", ".join("detail %d of the look" % i for i in range(80))
fp = imagegen.fit_prompt(long_prompt, 800)
check("a long prompt is cut to 800 characters at a clause", len(fp) <= 800 and fp.endswith("of the look"))
check("a short prompt is left alone", imagegen.fit_prompt("a fox", 800) == "a fox")
sent = []
imagegen.nvidia(long_prompt, 1024, 1024, tempfile.mkdtemp(), 3, sleep=lambda s: None,
                request=lambda u, k, b, h, t: sent.append((u.rsplit("/", 1)[-1], len(b["prompt"]))) or
                {"artifacts": [{"base64": "iVBORw0KGgo="}]})
check("FLUX.2 klein gets at most 800 characters", sent[:1] and sent[0][1] <= 800)
tried.clear()
imagegen._bench_file().unlink(missing_ok=True)
imagegen.bench("nvidia:black-forest-labs/flux.1-dev", 600, "it answered HTTP 500 a moment ago")
try:
    imagegen.nvidia("a fox", 1024, 1024, tempfile.mkdtemp(), 7, request=fake_call, sleep=lambda s: None)
except Exception:  # noqa: BLE001
    pass
check("a model that just failed is skipped for a while", "flux.1-dev" not in tried and "flux.1-schnell" in tried)
print("\n%d passed, %d failed (%.1f s)" % (PASSED, FAILED, time.time() - t0))
sys.exit(1 if FAILED else 0)
