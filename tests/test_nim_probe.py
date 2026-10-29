"""NVIDIA lists models a key cannot run (2026-10-28/29, the Mac: nemotron-3-super-120b and kimi-k2.6 answered 404
"Function ... Not found for account" while /models listed them). engine/nim_models.choose tries a listed id once with a
1-token call and skips the refused ones; the verdict is remembered for a day."""
import io
import json
import os
import sys
import tempfile
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
os.environ["LOKI_DATA"] = tempfile.mkdtemp(prefix="loki-nim-")
import nim_models  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % str(detail)[:300]))


LISTED = ["nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-3.5-lightning-30b-a3b", "z-ai/glm-5.3",
          "moonshotai/kimi-k2.6", "deepseek-ai/deepseek-v4.1-flash"]
REFUSED = {"nvidia/nemotron-3-super-120b-a12b", "moonshotai/kimi-k2.6"}
SLOW = {"z-ai/glm-5.3"}
calls = []


class Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(req, timeout=0):
    if req.full_url.endswith("/models"):
        return Resp(json.dumps({"data": [{"id": i} for i in LISTED]}).encode())
    model = json.loads(req.data)["model"]
    calls.append(model)
    if model in REFUSED:
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b'{"detail":"Function not found for account"}'))
    if model in SLOW:
        raise TimeoutError("timed out")
    return Resp(b'{"choices":[{"message":{"content":"ok"}}]}')


B, K = nim_models.NIM_URL, "nvapi-test"
ids = nim_models.served(B, K, opener=opener)
got = nim_models.choose("nvidia/nemotron-3-super-120b-a12b", ids, B, K, opener=opener)
check("a listed Nemotron the key refuses is skipped for one that runs", got == "nvidia/nemotron-3.5-lightning-30b-a3b", got)
got = nim_models.choose("moonshotai/kimi-k2.6", ids, B, K, opener=opener)
check("Max mode: a slow model (timeout) is not ruled out", got == "z-ai/glm-5.3", got)
n = len(calls)
nim_models.choose("moonshotai/kimi-k2.6", ids, B, K, opener=opener)
check("a refusal is remembered (no second call for it)", calls[n:].count("moonshotai/kimi-k2.6") == 0, calls[n:])
check("... on disk too", "kimi-k2.6" in (Path(os.environ["LOKI_DATA"]) / "nim_probe.json").read_text())
cfg = type("C", (), {"base_url": B, "model": "nvidia/nemotron-3-super-120b-a12b", "api_key": K})()
check("fix() corrects the route's model", "nemotron-3.5-lightning-30b-a3b" in nim_models.fix(cfg, opener=opener)
      and cfg.model == "nvidia/nemotron-3.5-lightning-30b-a3b", cfg.model)
check("nothing listed: the model is kept", nim_models.choose("x/y", [], B, K, opener=opener) == "x/y")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
