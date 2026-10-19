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

# --- mix and match the local models, offline (the owner, 2026-10-18: "if one model cant you need
# to figure out a way to mix and match all the offline and free ones"). When one local model is
# stuck, LOKI tries the NEXT installed local model before ever reaching for the cloud.
_caps = lambda n: ["tools"]  # noqa: E731
pool = [{"name": "qwen3.5:9b", "size_gb": 6.6}, {"name": "qwen3:8b", "size_gb": 5.2},
        {"name": "huihui_ai/qwen3-abliterated:8b", "size_gb": 5.0},
        {"name": "nomic-embed-text:latest", "size_gb": 0.3}, {"name": "qwen3.5:35b", "size_gb": 22.0}]
nxt = ms.next_installed(["qwen3.5:9b"], pool, 7.0, caps=_caps)
check("the next local model is the best remaining tool-caller", nxt and nxt["name"] == "qwen3:8b", nxt)
check("each step moves to a model not yet tried",
      (ms.next_installed(["qwen3.5:9b", "qwen3:8b"], pool, 7.0, caps=_caps) or {}).get("name")
      == "huihui_ai/qwen3-abliterated:8b")
check("a loki-* long-context copy of a tried model is not a new choice",
      ms.next_installed(["loki-qwen3-8b"], [{"name": "qwen3:8b", "size_gb": 5.2}], 7.0, caps=_caps) is None)
check("when every local model is tried, nothing is left",
      ms.next_installed(["qwen3.5:9b", "qwen3:8b", "huihui_ai/qwen3-abliterated:8b"], pool, 7.0, caps=_caps) is None)
check("an embed model is never chosen",
      (ms.next_installed([], pool, 7.0, caps=_caps) or {}).get("name") != "nomic-embed-text:latest")
check("a model that does not fit is skipped",
      ms.next_installed([], [{"name": "qwen3.5:35b", "size_gb": 22.0}], 7.0, caps=_caps) is None)
check("a model without tool calling is skipped",
      ms.next_installed([], [{"name": "llama3.2:3b", "size_gb": 2.0}], 7.0, caps=lambda n: []) is None)

_esrc = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("the engine tries the next local model before the cloud",
      "_local_chain_next(" in _esrc and "model_setup.next_installed(" in _esrc
      and "staying offline and free" in _esrc)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
