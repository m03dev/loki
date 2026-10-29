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
check("a 1024x1024 picture is left as it is", imagegen.fit_side(1024, 1024, 1024) == (1024, 1024))
sizes = []
imagegen.nvidia("a fox", 1536, 1024, tempfile.mkdtemp(), 3, sleep=lambda s: None,
                request=lambda u, k, b, h, t: sizes.append((b["width"], b["height"])) or
                {"artifacts": [{"base64": "iVBORw0KGgo="}]})
check("FLUX.2 gets the fitted size", sizes[:1] == [(1024, 672)])
print("\n%d passed, %d failed (%.1f s)" % (PASSED, FAILED, time.time() - t0))
sys.exit(1 if FAILED else 0)
