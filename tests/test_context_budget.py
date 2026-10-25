"""What LOKI sends the model each turn (engine/context_budget.py): observation masking in cache-friendly batches,
old huge tool arguments cut, one huge tool result capped, the provider's cached-token count read, and - the point - a
simulated 40-step task sends far fewer characters than the old 'send everything' harness. Pure, a second.

    python tests/test_context_budget.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import context_budget as CB  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def task(steps: int, size: int = 6000) -> list:
    msgs = [{"role": "system", "content": "You are LOKI."}, {"role": "user", "content": "fix the bug"}]
    for i in range(steps):
        args = json.dumps({"path": "f%d.py" % i, "content": "y" * (3000 if i % 5 == 0 else 20)})
        msgs.append({"role": "assistant", "content": None, "tool_calls": [{"id": "c%d" % i, "type": "function",
                     "function": {"name": "write_file" if i % 5 == 0 else "read_file", "arguments": args}}]})
        msgs.append({"role": "tool", "tool_call_id": "c%d" % i, "content": ("line %d of output\n" % i) + "x" * size})
    return msgs


m = task(20)
view, st = CB.mask(m)
tools = [v for v in view if v["role"] == "tool"]
check("the newest 4+ tool results go in full", all(len(t["content"]) > 6000 for t in tools[-4:]))
check("older ones become a one-line stub naming the tool and what it said",
      tools[0]["content"].startswith("[cleared to save context: write_file said: line 0 of output") and len(tools[0]["content"]) < 300, tools[0]["content"])
check("masked in batches of 6: 20 results - 4 kept = 16 -> 12 masked", st["masked"] == 12, st)
check("the history itself is not changed", len(m[3]["content"]) > 6000 and view is not m and len(view) == len(m))
check("every tool_call keeps its result (the providers' pairing rule)", [v.get("tool_call_id") for v in view if v["role"] == "tool"] == ["c%d" % i for i in range(20)])
old_write = view[2]["tool_calls"][0]["function"]["arguments"]
check("an old call's huge arguments (a whole file) are cut", "_cleared" in old_write and st["args_cut"] >= 2, old_write[:120])
check("small results are never stubbed", CB.mask(task(20, size=100))[1]["masked"] == 0)

# cache-friendliness: the masked prefix is byte-identical for several turns in a row
prefixes = []
for n in range(20, 26):
    v, _ = CB.mask(task(n))
    prefixes.append(json.dumps(v[:2 + 2 * 12]))
check("the prefix sent stays identical while the boundary has not moved (prefix cache hits)", len(set(prefixes[:6])) == 1, len(set(prefixes)))
check("no masking for a short task", CB.mask(task(4))[1]["masked"] == 0)


def sent_chars(steps: int, masked: bool) -> int:
    total = 0
    for n in range(1, steps + 1):
        msgs = task(n)
        if masked:
            msgs, _ = CB.mask(msgs)
        total += len(json.dumps(msgs))
    return total


before, after = sent_chars(40, False), sent_chars(40, True)
check("a 40-step task sends far less (at least 2.5x fewer characters over the task)", after * 2.5 < before, (before, after))
print("    (40 steps: %.1fM characters sent before, %.1fM now)" % (before / 1e6, after / 1e6))

# one huge tool result
big = "HEAD " + "z" * 60000 + " TAIL"
capped = CB.cap_result(big, 24000)
check("a huge tool result keeps its start and end with a note", len(capped) < 25000 and capped.startswith("HEAD") and capped.endswith("TAIL") and "characters cut" in capped)
check("small results and non-strings pass through", CB.cap_result("ok", 100) == "ok" and CB.cap_result({"a": 1}, 1) == {"a": 1})

# cached tokens, every way providers report them
check("DeepSeek: prompt_cache_hit_tokens", CB.cached_tokens(SimpleNamespace(prompt_cache_hit_tokens=900, prompt_tokens=1000)) == 900)
check("OpenAI-style: prompt_tokens_details.cached_tokens", CB.cached_tokens({"prompt_tokens_details": {"cached_tokens": 512}}) == 512)
check("not reported -> None", CB.cached_tokens(SimpleNamespace(prompt_tokens=5)) is None and CB.cached_tokens(None) is None)
check("settings: LOKI_MASK=off turns it off; keep / step read", CB.settings({"LOKI_MASK": "off"})["on"] is False and CB.settings({"LOKI_MASK_KEEP": "2", "LOKI_MASK_STEP": "3"})["keep"] == 2)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
