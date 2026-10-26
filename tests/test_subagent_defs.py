"""Named subagents (engine/agent_defs.py, shinpr/sub-agents-skills' format) and the sharper sub-agent loop
(engine/subagent.py). Offline, seconds.

    python tests/test_subagent_defs.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-subdefs-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import agent_defs  # noqa: E402
import subagent  # noqa: E402

# ------------------------------------------------------------------ definitions
names = [a["name"] for a in agent_defs.list_all(TMP)]
check("LOKI's built-in subagents are there", {"researcher", "code-reviewer", "bug-investigator", "file-finder",
                                              "checker", "writer"} <= set(names), names)
r = agent_defs.load("researcher")
check("a built-in agent runs on LOKI, read-only, with its own tools",
      r["run_agent"] == "loki" and r["permission"] == "read-only" and "read_web" in r["tools"]
      and "write_file" not in r["tools"] and "## Done When" in r["system"], r)
w = agent_defs.load("writer")
check("safe-edit gives the edit tools but no shell", "write_file" in w["tools"] and "run_command" not in w["tools"], w)
ws = TMP / "proj"
(ws / ".agents").mkdir(parents=True)
(ws / ".agents" / "code-reviewer.md").write_text("---\nrun-agent: opencode\nmodel: x/y\npermission: read-only\n---\n\n"
                                                 "# My Reviewer\n\nReview like we do here.\n", encoding="utf-8")
(ws / ".agents" / "shipper.md").write_text("---\nrun-agent: loki\npermission: yolo\n---\n\n# Shipper\n\nShip it.\n",
                                           encoding="utf-8")
mine = agent_defs.load("code-reviewer", ws)
check("the project's .agents/ definition wins over the built-in one", mine["run_agent"] == "opencode"
      and "Review like we do here." in mine["system"], mine)
check("yolo gives the shell", "run_command" in agent_defs.load("shipper", ws)["tools"])
check("the list shows project agents and the rest of the built-ins",
      {"shipper", "code-reviewer", "checker"} <= {a["name"] for a in agent_defs.list_all(ws)})
for bad in ("../etc/passwd", "nope-missing"):
    try:
        agent_defs.load(bad, ws)
        check("a bad or unknown name is refused: %s" % bad, False)
    except (FileNotFoundError, ValueError) as exc:
        check("a bad or unknown name is refused: %s" % bad, True, exc)
check("an external backend that is not installed is reported as not ready",
      not agent_defs.cli_ready("no-such-cli-backend"))
res = agent_defs.run_external(dict(mine, run_agent="not-a-backend"), "review", ws, timeout_s=5)
check("an unknown backend comes back as an error, not a crash", not res["ok"] and res.get("error"), res)


# ------------------------------------------------------------------ the loop
def fake(replies):
    it = iter(replies)
    seen = []

    async def request(msgs, schemas):
        seen.append([dict(m) for m in msgs])
        return next(it)
    return request, seen


async def tool(name, args):
    return "contents of %s" % args.get("filename", "?")

req, seen = fake([{"content": "RESULT: the bug is in auth.py line 3"},
                  {"content": "", "tool_calls": [{"id": "1", "function": {"name": "read_file",
                                                                           "arguments": json.dumps({"filename": "auth.py"})}}]},
                  {"content": "RESULT: auth.py line 3 compares with = instead of =="}])
out = asyncio.run(subagent.run("find the auth bug", ["read_file"], [{"function": {"name": "read_file"}}], req, tool))
check("an answer from nowhere is sent back once to be checked with the tools",
      out["ok"] and out["tools_used"] == ["read_file"] and "==" in out["result"]
      and any("without using any of your tools" in m["content"] for m in seen[1] if m["role"] == "user"), out)
req, _ = fake([{"content": "RESULT: incomplete - I have no tool for that"}])
out = asyncio.run(subagent.run("x", ["read_file"], [], req, tool))
check("an honest 'incomplete' is not nudged", out["turns"] == 1 and "incomplete" in out["result"], out)
req, seen = fake([{"content": "", "tool_calls": [{"id": "1", "function": {"name": "read_file",
                                                                           "arguments": "{}"}}]},
                  {"content": "RESULT: ok"}])
asyncio.run(subagent.run("x", ["read_file"], [], req, tool, role="# Checker\n## Done When\n- all checked"))
sys_prompt = seen[0][0]["content"]
check("the agent's role is in its system prompt, with the honesty rules", "# Checker" in sys_prompt
      and "Never claim anything you did not see in a tool result" in sys_prompt
      and "tells nothing about what the agent" in sys_prompt, sys_prompt[-600:])


async def big(name, args):
    return "x" * 50000

req, seen = fake([{"content": "", "tool_calls": [{"id": "1", "function": {"name": "read_file", "arguments": "{}"}}]},
                  {"content": "RESULT: ok"}])
asyncio.run(subagent.run("x", ["read_file"], [], req, big, context_chars=12000))
tool_msg = next(m for m in seen[1] if m["role"] == "tool")
check("a small window gets small tool results (and says only the view is cut)",
      len(tool_msg["content"]) < 2600 and "only this view is cut" in tool_msg["content"], len(tool_msg["content"]))

running, peak = [0], [0]


async def slow_req(msgs, schemas):
    running[0] += 1
    peak[0] = max(peak[0], running[0])
    await asyncio.sleep(0.01)
    running[0] -= 1
    return {"content": "RESULT: incomplete - x"}

asyncio.run(subagent.run_many(["a", "b", "c"], ["read_file"], [], slow_req, tool, parallel=1))
check("a parallel limit is kept (a local model: LOKI_LOCAL_PARALLEL, default 2)", peak[0] == 1, peak)
peak[0] = 0
asyncio.run(subagent.run_many(["a", "b", "c"], ["read_file"], [], slow_req, tool, parallel=2))
check("two at a time when allowed", peak[0] == 2, peak)

# ------------------------------------------------------------------ in the engine
try:
    import loki  # noqa: E402
except ModuleNotFoundError:
    loki = None
if loki is not None:
    listing = asyncio.run(loki.run_subagent(agent="list"))
    check("run_subagent agent=list lists them", "researcher" in listing and "checker" in listing, listing[:300])
    check("an unknown agent is an error with the list", "no subagent called" in asyncio.run(
        loki.run_subagent(task="x", agent="nope")))
    local = next(n for n in loki.MODELS if loki._cfg_is_local(loki.MODELS[n]))  # pylint: disable=protected-access
    online_one = next(n for n in loki.MODELS if not loki._cfg_is_local(loki.MODELS[n]))  # pylint: disable=protected-access
    loki.active_model_name = lambda: local
    loki.online = lambda *a, **k: True
    loki._free_capable_online = lambda needs: online_one  # pylint: disable=protected-access
    loki.provider_configured = lambda n: True
    check("a helper started from a local-model chat runs on a capable online model", loki.subagent_model() == online_one)
    os.environ["LOKI_SUBAGENT_MODEL"] = "same"
    check("LOKI_SUBAGENT_MODEL=same keeps it local", loki.subagent_model() == local)
    os.environ.pop("LOKI_SUBAGENT_MODEL")
    check("a definition's own model wins", loki.subagent_model(local) == local)
    schema = next(s for s in loki.TOOL_SCHEMAS if s["function"]["name"] == "run_subagent")
    check("the tool offers named agents", "agent" in schema["function"]["parameters"]["properties"]
          and "checker" in schema["function"]["description"])
else:
    print("  (the engine's openai dependency is missing here: the engine checks are skipped)")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
