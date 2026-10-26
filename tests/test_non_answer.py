"""A route that answers without working moves the job to the next provider (the PC, 2026-10-26: Vireonix 'auto'
replied "Unable to answer question due to internal guardrails" / "I don't see a specific team goal" to team jobs,
and they stopped there instead of reaching the next provider or the local abliterated model).

    python tests/test_non_answer.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-nonans-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ.setdefault("LOKI_USER_KEYS", "")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


import provider_speed  # noqa: E402

check("empty DeepSeek balance benches it for hours", provider_speed.mark_out(TMP, "deepseek", "Insufficient Balance (request_id: x)") >= 6 * 3600)
check("a free model that is down is benched", provider_speed.mark_out(TMP, "opencode-zen", '{"message":"Upstream request failed: Model is unavailable."}') > 0)
check("a route that hung the whole turn is benched", provider_speed.mark_out(TMP, "nvidia", "timed out after 1200s") > 0)
check("a non-answer is benched", provider_speed.mark_out(TMP, "vireonix", "non-answer: Unable to answer question due to internal guardrails") > 0)
check("an ordinary error is not", provider_speed.mark_out(TMP, "x", "some tool failed") == 0)

import opencode_engine  # noqa: E402

for reply in ("Unable to answer question due to internal guardrails",
              "I'm ready to work as the \"Builder\" agent. However, I don't see a specific team goal or project details "
              "in your message. Could you please provide:\n1. What project folder should I work in?"):
    check("non-answer: %s..." % reply[:40], opencode_engine.non_answer(reply), reply)
for reply in ("DONE: made sprites/knight.png (64x64) and checked it opens",
              "The project is already complete and verified across 5 rounds. npm test passes.", ""):
    check("real answer kept: %r" % reply[:40], not opencode_engine.non_answer(reply), reply)

src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("a local model runs with the sub-agent tool denied (it called `task` with made-up ids - PC 2026-10-26)",
      'task="deny"' in src and "cfg_local if is_local else cfg_path" in src)
check("moving to the next provider never tells the model 'the previous model was too slow' (it made that its task)",
      "the previous model was too slow). The goal" not in src)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
