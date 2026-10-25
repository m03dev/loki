"""LOKI's agent = OpenCode + CodeGraph (engine/opencode_engine.py, loki.run_opencode; owner 2026-10-25: "replace it
... just make my agent actually work").

A fake `opencode` executable (it speaks `opencode run --format json`: JSON lines on stdout) stands in for the real one:
  * "work" mode really does the job in the workspace (git init, folders, files, a commit) and reports each tool;
  * "liar" mode only says "Done! I created ..." - LOKI pushes once, then says NOT DONE;
  * "fail" mode errors - LOKI tries the next provider.
Checks: the config OpenCode gets (providers by env-var key, never the key itself; CodeGraph as MCP; LOKI's destructive
list denied; plan mode read-only), the argv (--format json --dir --session --model --agent plan), one session per
conversation, the window's progress gets every tool, and the not-installed message. Under a minute.

    python tests/test_opencode_engine.py
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


t0 = time.time()
import opencode_engine as oe  # noqa: E402

# ---- the config
cfg = oe.build_config({"groq": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-x", "key": "SECRET123"},
                       "codex": {"base_url": "cli-agent://codex", "model": "codex"}},
                      codegraph="/usr/bin/codegraph", deny=["rm -rf /", "shutdown"])
text = json.dumps(cfg)
check("config: an OpenAI-compatible provider per LOKI provider, the key by env var - never inlined",
      cfg["provider"]["loki-groq"]["options"]["apiKey"] == "{env:LOKI_OC_KEY_GROQ}" and "SECRET123" not in text
      and cfg["provider"]["loki-groq"]["npm"] == "@ai-sdk/openai-compatible" and "loki-codex" not in cfg["provider"])
check("config: CodeGraph is OpenCode's MCP code map", cfg["mcp"]["codegraph"]["command"] == ["/usr/bin/codegraph", "serve", "--mcp"])
check("config: LOKI's destructive list is denied, the rest of bash allowed, outside the workspace denied",
      cfg["permission"]["bash"]["*"] == "allow" and cfg["permission"]["bash"]["*rm -rf /*"] == "deny"
      and cfg["permission"]["external_directory"] == "deny")
plan = oe.build_config({}, plan=True)
check("plan mode: no edits, no bash", plan["permission"]["edit"] == "deny" and plan["permission"]["bash"] == "deny")
env = oe.env_for({"groq": {"key": "SECRET123"}}, base={"PATH": "/bin"})
check("the key goes to OpenCode in its env var", env["LOKI_OC_KEY_GROQ"] == "SECRET123")
check("events: tool_use parsed (name, status, command, output)",
      oe.tool_summary({"tool": "bash", "state": {"status": "completed", "input": {"command": "git init"}, "output": "ok"}})
      == ("bash", "completed", "git init", "ok"))
check("a bash call that exits non-zero is a failure", oe.tool_counts([("bash", "completed", "x", "exit 1\nboom"),
                                                                       ("write", "completed", "a", "ok")]) == (1, 1))

# ---- a fake opencode on PATH
D = Path(tempfile.mkdtemp(prefix="loki-oc-"))
FAKE = D / "opencode"
FAKE.write_text(r'''#!/usr/bin/env python3
import json, os, subprocess, sys, uuid
args = sys.argv[1:]
log = os.environ.get("FAKE_OC_LOG")
if log:
    with open(log, "a") as f: f.write(json.dumps({"argv": args, "config": os.environ.get("OPENCODE_CONFIG", ""),
                                                  "keys": sorted(k for k in os.environ if k.startswith("LOKI_OC_KEY_"))}) + "\n")
mode = os.environ.get("FAKE_OC_MODE", "work")
sid = args[args.index("--session") + 1] if "--session" in args else "ses_" + uuid.uuid4().hex[:8]
model = args[args.index("--model") + 1] if "--model" in args else ""
def out(kind, **kw): print(json.dumps({"type": kind, "timestamp": 0, "sessionID": sid, **kw}), flush=True)
if mode == "fail" or (mode == "fail-first" and "groq" in model):
    out("error", error={"name": "APIError", "data": {"message": "429 rate limited"}}); sys.exit(1)
if mode == "liar":
    out("text", part={"type": "text", "text": "Done! I created a new git repo called loki-test-repo and committed it."}); sys.exit(0)
out("step_start", part={"type": "step-start"})
cmd = ("git init -q loki-test-repo && mkdir -p loki-test-repo/src && cd loki-test-repo && printf '# t\n' > README.md && "
       "printf 'print(\"hello\")\n' > src/main.py && git add -A && git -c user.name=OC -c user.email=oc@x commit -q -m init && git log --oneline")
r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
out("tool_use", part={"type": "tool", "tool": "bash", "state": {"status": "completed", "input": {"command": cmd},
    "output": "exit %d\n%s" % (r.returncode, r.stdout + r.stderr) if r.returncode else r.stdout}})
out("text", part={"type": "text", "text": "Created loki-test-repo with src/main.py and README.md, committed:\n" + r.stdout})
out("step_finish", part={"type": "step-finish", "reason": "stop"})
''')
FAKE.chmod(FAKE.stat().st_mode | stat.S_IEXEC)
LOG = D / "argv.jsonl"
os.environ["LOKI_OPENCODE_EXE"] = str(FAKE)
os.environ["LOKI_CODEGRAPH_EXE"] = "/nonexistent"
os.environ["FAKE_OC_LOG"] = str(LOG)
os.environ.setdefault("LOKI_DATA", str(D / "data"))
check("the fake is found as LOKI's opencode", oe.find_opencode() == str(FAKE))

try:
    import loki  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print("  (skip the engine checks: %s)" % exc)
    loki = None

if loki:
    events = []
    loki.loki_progress_callback = lambda e, t: events.append((e, t))
    loki.provider_configured = lambda name: name in ("groq", "gemini")
    loki.MODELS["groq"].api_key = "gk-test"
    loki.MODELS["gemini"].api_key = "gm-test"
    loki.model_name = "groq"

    def turn(text, mode="work", ws=None, agent_mode="build", conv="c1"):
        os.environ["FAKE_OC_MODE"] = mode
        loki.WORKSPACE = ws or Path(tempfile.mkdtemp(prefix="loki-oc-ws-"))
        loki.AGENT_MODE = agent_mode
        loki.active_conversation = conv
        loki.clear_cancel()
        LOG.write_text("")
        out = asyncio.run(asyncio.wait_for(loki.run_opencode(text), 50))
        calls = [json.loads(x) for x in LOG.read_text().splitlines() if x.strip()]
        return out, loki.WORKSPACE, calls

    REQ = "use git bash to make a new git repo called loki-test-repo with a src folder, a README.md and src/main.py, commit it"
    out, ws, calls = turn(REQ)
    r = ws / "loki-test-repo"
    log = subprocess.run(["git", "-C", str(r), "log", "--oneline"], capture_output=True, text=True)
    check("OpenCode really made the repo: git init, src/, README.md, main.py, a commit", (r / "src" / "main.py").is_file()
          and (r / "README.md").is_file() and log.returncode == 0 and log.stdout.strip(), (out[:200], log.stderr))
    check("the reply is OpenCode's report + what ran", "Created loki-test-repo" in out and "Tools run: 1 ok" in out, out[-200:])
    a = calls[0]["argv"] if calls else []
    check("argv: run --format json --dir <workspace> --model loki-groq/<model> <text>",
          a[:3] == ["run", "--format", "json"] and a[a.index("--dir") + 1] == str(ws) and "--model" in a
          and a[a.index("--model") + 1].startswith("loki-groq/") and a[-1].startswith("use git bash"), a)
    check("OpenCode got LOKI's config file and the keys as env vars", calls and calls[0]["config"].endswith("opencode.json")
          and "LOKI_OC_KEY_GROQ" in calls[0]["keys"])
    written = (Path(loki.DATA_DIR) / "opencode" / "opencode.json").read_text()
    check("the config on disk has no key in it", "gk-test" not in written and "{env:LOKI_OC_KEY_GROQ}" in written)
    check("the window saw the tool as it ran", any(e == "tool" and "bash" in t for e, t in events)
          and any(e == "tool_result" for e, _ in events))
    sid = loki.OC_SESSIONS.get("c1")
    out2, _ws, calls2 = turn("now show me git log again", ws=ws)
    check("the next message in the same chat continues the same OpenCode session",
          bool(sid) and calls2 and "--session" in calls2[0]["argv"] and calls2[0]["argv"][calls2[0]["argv"].index("--session") + 1] == sid)

    out, ws, calls = turn(REQ, mode="liar", conv="c2")
    check("a model that only SAYS done: pushed once, then NOT DONE - and nothing on disk",
          out.startswith("NOT DONE") and len(calls) == 2 and not (ws / "loki-test-repo").exists(), (out[:160], len(calls)))

    out, ws, calls = turn(REQ, mode="fail-first", conv="c3")
    models = [c["argv"][c["argv"].index("--model") + 1] for c in calls if "--model" in c["argv"]]
    check("the first provider fails -> the next one does it", len(models) >= 2 and models[0].startswith("loki-groq/")
          and models[1].startswith("loki-gemini/") and (ws / "loki-test-repo" / "src" / "main.py").is_file(), models)

    out, ws, calls = turn("what does this project do?", agent_mode="plan", conv="c4")
    a = calls[0]["argv"]
    check("Plan / Ask mode: OpenCode's read-only plan agent", "--agent" in a and a[a.index("--agent") + 1] == "plan", a)

    os.environ["LOKI_OPENCODE_EXE"] = str(D / "missing")
    real_find = oe.find_opencode
    oe.find_opencode = lambda: ""
    out, ws, calls = turn(REQ, conv="c5")
    oe.find_opencode = real_find
    check("not installed: NOT DONE with how to install it (never the old loop pretending)",
          out.startswith("NOT DONE") and "npm i -g opencode-ai" in out and not calls, out[:200])
    os.environ["LOKI_OPENCODE_EXE"] = str(FAKE)
    check("the engine is OpenCode unless LOKI_AGENT_ENGINE=loki", oe.engine_choice({}) == "opencode"
          and oe.engine_choice({"LOKI_AGENT_ENGINE": "loki"}) == "loki")
    st = loki.engine_status()
    check("Settings > Agent status: the engine, where OpenCode is, the install commands", st["opencode"] == str(FAKE)
          and st["engine"] == "opencode" and "opencode" in st["install"])

check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
