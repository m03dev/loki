"""LOKI's proxy trims old tool output when a request grows (engine/dsml_proxy.trim_body).

2026-10-29, the Mac's real jobs: an OpenCode job resent its whole history every step (19.6k tokens at step 1, 535k by
step 16) and each step on NVIDIA's free tier took 200-900 s."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import dsml_proxy  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % str(detail)[:300]))


os.environ.pop("LOKI_CONTEXT_TRIM", None)
big = "x" * 9000
msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "do the task"}]
for i in range(10):
    msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": "c%d" % i}]})
    msgs.append({"role": "tool", "tool_call_id": "c%d" % i, "content": "result %d " % i + big})
body = json.dumps({"model": "m", "messages": msgs}).encode()
out = json.loads(dsml_proxy.trim_body(body))
tools = [m for m in out["messages"] if m["role"] == "tool"]
check("the request got smaller", len(json.dumps(out)) < len(body) / 2, len(json.dumps(out)))
check("the newest 4 tool results stay whole", all(len(t["content"]) > 9000 for t in tools[-4:]))
check("older ones keep their start and say they were trimmed",
      all(t["content"].startswith("result %d" % i) and "LOKI trimmed" in t["content"] for i, t in enumerate(tools[:-4])))
check("system, task and tool-call ids are untouched", out["messages"][0]["content"] == "sys"
      and out["messages"][1]["content"] == "do the task" and [t["tool_call_id"] for t in tools] == ["c%d" % i for i in range(10)])
again = dsml_proxy.trim_body(json.dumps(out).encode())
check("a trimmed history is not trimmed again (stable for prompt caches)",
      [m["content"][:500] for m in json.loads(again)["messages"]][:12] == [m["content"][:500] for m in out["messages"]][:12])
small = json.dumps({"model": "m", "messages": msgs[:4]}).encode()
check("a small request passes through byte for byte", dsml_proxy.trim_body(small) == small)
huge = json.dumps({"messages": [{"role": "user", "content": "t"}, {"role": "tool", "content": "a" * 100000}]}).encode()
h = json.loads(dsml_proxy.trim_body(huge))["messages"][1]["content"]
check("one huge result keeps its start and end", len(h) < 30000 and h.startswith("aaa") and h.endswith("aaa"), len(h))
parts = json.dumps({"messages": [{"role": "tool", "content": [{"type": "text", "text": "p" * 9000}]} for _ in range(12)]})
pp = json.loads(dsml_proxy.trim_body(parts.encode()))["messages"]
check("list-style content is trimmed too", "LOKI trimmed" in pp[0]["content"][0]["text"])
os.environ["LOKI_CONTEXT_TRIM"] = "off"
check("LOKI_CONTEXT_TRIM=off passes everything", dsml_proxy.trim_body(body) == body)
check("not JSON passes through", dsml_proxy.trim_body(b"x" * 70000) == b"x" * 70000)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
