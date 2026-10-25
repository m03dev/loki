"""DeepSeek's tool-call markup leaking into a reply (owner 2026-10-25 11:55: LOKI answered with ten
"<｜DSML｜ calls>" lines and "No shell/Bash tool is available"). The markup means the provider never ran those calls:
LOKI redoes the turn with the next provider, starts installing DeepSeek Harness (once, in the background), never shows
the raw tags, and says NOT DONE when nothing ran at all. OpenCode is faked (opencode_engine.run_turn); under a minute.

    python tests/test_dsml_leak.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-dsml-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_DEEPSEEK_HARNESS"] = "off"
os.environ["LOKI_DSH_AUTOINSTALL"] = "1"
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


import opencode_engine  # noqa: E402

LEAK = ("I'll look at the folder.\n<｜DSML｜function_calls>\n<｜DSML｜invoke name=\"bash\">\n<｜DSML｜ calls>\n"
        "<|DSML|parameter name=\"command\">ls</|DSML|parameter>\n</｜DSML｜function_calls>\nDone.")
check("the markup is recognised (full-width and ASCII bars)", opencode_engine.leaked_tool_markup(LEAK)
      and opencode_engine.leaked_tool_markup("<|DSML|invoke>") and not opencode_engine.leaked_tool_markup("a <b> tag"))
clean = opencode_engine.strip_tool_markup(LEAK)
check("... and stripped: no tags, the words kept", "DSML" not in clean and "I'll look at the folder." in clean and "Done." in clean, clean)

try:
    import loki  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print("SKIP: the engine does not import here (%s)\n\n%d passed, %d failed" % (exc, len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)

calls, installs = [], []
loki._start_dsh_install = lambda: installs.append(1)
opencode_engine.find_opencode = lambda *a, **k: "/bin/true"
opencode_engine.ensure_index = lambda *a, **k: ""
loki.WORKSPACE = Path(tempfile.mkdtemp(prefix="loki-dsml-ws-"))
loki.AGENT_MODE = "build"
TWO = {"deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4.1", "key": "k"},
       "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3", "key": "k"}}


def fake(answers):
    def run_turn(prompt, ws, **kw):
        calls.append(kw.get("model"))
        return answers[min(len(calls) - 1, len(answers) - 1)]
    opencode_engine.run_turn = run_turn


def ask(text, providers):
    calls.clear(); installs.clear()
    loki._oc_providers = lambda first: providers
    return asyncio.run(asyncio.wait_for(loki.run_opencode(text), 30))


fake([{"text": LEAK, "tools": [], "session": "s1"}, {"text": "Here is what is in the folder: nothing yet.", "tools": [], "session": "s2"}])
out = ask("what is in this folder?", TWO)
check("leaked markup: the turn is redone with the next provider", calls == ["deepseek/deepseek-v4.1", "groq/llama-3.3"]
      or (len(calls) == 2 and "llama" in str(calls[1])), calls)
check("... the reply is the next provider's, no DSML tags", "nothing yet" in out and "DSML" not in out, out)
check("... and DeepSeek Harness starts installing for next time", installs, installs)

fake([{"text": LEAK, "tools": [], "session": "s1"}])
out = ask("what is in this folder?", {"deepseek": TWO["deepseek"]})
check("only DeepSeek, nothing ran: NOT DONE says why, no raw tags", out.startswith("NOT DONE") and "DSML" not in out.split("\n\n", 1)[-1]
      and "DeepSeek Harness" in out, out[:300])

check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
