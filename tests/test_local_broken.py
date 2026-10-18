"""A local model Ollama cannot load is never used again on that Ollama (the Mac, 2026-10-17:
[model error] loki-hf.co-prism-ml-ternary-bonsai-2-9b-... HTTP 500 'read GGUF metadata ...
unsupported tensor "output.weight" size overflows').

    python tests/test_local_broken.py      (< 2 s, no Ollama needed)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ["LOKI_DATA"] = tempfile.mkdtemp(prefix="loki-broken-")
sys.path.insert(0, str(REPO / "engine"))
import model_setup as ms  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


MAC_ERROR = ('read GGUF metadata "/Users/x/.ollama/models/blobs/sha256-1f88": unsupported tensor "output.weight" '
             'size overflows')
check("the Mac's error is recognised as 'cannot load'", ms.is_load_error(MAC_ERROR))
check("a busy / rate error is not", not ms.is_load_error("model is busy, try again") and not ms.is_load_error("HTTP 429"))

base = "hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Ternary-Bonsai-2-9B-Q2_0"
derived = ms.derived_name(base)
check("the failing name is LOKI's long-context copy of Bonsai 2 9B",
      derived == "loki-hf.co-prism-ml-ternary-bonsai-2-9b-gguf-ternary-bonsai-2-9b-q2_0", derived)
ms.mark_broken(derived, MAC_ERROR, "0.41.0")
check("the copy is marked broken, and so is the model it came from",
      ms.is_broken(derived, "0.41.0") and ms.is_broken(base, "0.41.0"))
check("after an Ollama update it is tried again", not ms.is_broken(base, "0.42.0"))

models = [{"name": derived, "size_gb": 2.6}, {"name": base, "size_gb": 2.6}, {"name": "qwen3:8b", "size_gb": 5.2}]
pick = ms.best_installed(models, 16.0, caps=lambda n: ["tools"], version="0.41.0")
check("LOKI picks the next best model instead", pick and pick["name"] == "qwen3:8b", pick)
rec = [r["tag"] for r in ms.recommend({"budget_gb": 16.0})]
check("Bonsai 2 is not suggested for download again", not any("bonsai" in t.lower() for t in rec), rec)

src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("the engine marks it, switches at once and says so",
      "model_setup.mark_broken(" in src and "LOKI switched to" in src and "model_setup.is_broken(os.environ[\"LOKI_LOCAL_MODEL\"]" in src)

# --- a remote provider that dropped its model gets the one it serves now (the PC: pollinations)
import provider_health as ph  # noqa: E402
check("Pollinations without 'openai' moves to a model it still serves",
      ph.replacement("pollinations", "openai", ["mistral", "openai-fast"]) == "openai-fast")
check("NVIDIA's DeepSeek under its other name", ph.replacement("nvidia", "deepseek-ai/deepseek-v4.1-flash",
                                                                ["nvidia/deepseek-v4.1-flash"]) == "nvidia/deepseek-v4.1-flash")
check("a paid provider is never switched to a random model", ph.replacement("openai", "gpt-x", ["gpt-y"]) == "")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
