"""LOKI's offline agent for a model on this computer (engine/local_agent.py; owner 2026-10-25 12:37: "i want it to make
me a git repo with my offline local model ... get it done").

A fake Ollama on 127.0.0.1 answers the way a small local model does (a THOUGHT and a ```bash block; sometimes two
blocks, once no block at all). The commands REALLY run in a temp folder: the result is a real git repo with a real
commit, and LOKI's reply carries the `git log` LOKI ran itself. The request is lean (Ollama's /api/chat, think=false,
num_ctx 16384, no tool schemas, a short prompt). A model that only SAYS done gets NOT DONE; a dangerous command is
refused; the chat path (loki.run_opencode with a local model picked) goes to this agent, not OpenCode. Under a minute.

    python tests/test_local_agent.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-local-agent-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_LOCAL_AGENT_API"] = "ollama"
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:700],)))


import local_agent  # noqa: E402

GOOD = [
    "THOUGHT: First I make the folder and start a git repository in it.\n\n```bash\nmkdir -p loki-test-repo/src && cd loki-test-repo && git init -q && echo ok\n```",
    "I will write the files now.\n```bash\ncat > loki-test-repo/src/main.py <<'EOF'\nprint(\"hello\")\nEOF\n```\n```bash\necho second-block-should-not-run > loki-test-repo/NOPE\n```",
    "The README is next, then I commit.",                                     # no block: a format error
    "THOUGHT: README.md\n\n```bash\nprintf '# loki-test-repo\\n\\nPrints hello.\\n' > loki-test-repo/README.md && ls -R loki-test-repo\n```",
    "THOUGHT: commit it.\n```bash\ncd loki-test-repo && git add -A && git commit -q -m 'First commit: hello' && git log --oneline\n```",
    "THOUGHT: check it runs.\n```bash\ncd loki-test-repo && python3 src/main.py\n```",
    "All checked: the repo exists, has the files, and one commit.\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```",
]
LIAR = ["Done! I created loki-test-repo, wrote the files and committed them.\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"]
DANGER = ["THOUGHT: clean up.\n```bash\nrm -rf ~\n```", "OK, not that.\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"]
STATE = {"script": GOOD, "i": 0, "bodies": []}


class Ollama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        STATE["bodies"].append((self.path, body))
        text = STATE["script"][min(STATE["i"], len(STATE["script"]) - 1)]
        STATE["i"] += 1
        data = json.dumps({"model": body.get("model"), "message": {"role": "assistant", "content": text}, "done": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Ollama)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d/v1" % srv.server_address[1]
REQ = ("make a new git repo called loki-test-repo with a src folder, a README.md and src/main.py that prints hello, "
       "then commit it and show me git log")


def go(script, ws=None):
    STATE.update(script=script, i=0, bodies=[])
    ws = ws or Path(tempfile.mkdtemp(prefix="ws-", dir=TMP))
    seen = []
    res = local_agent.run(REQ, ws, BASE, "loki-qwen3.5-9b", deny=("rm -rf ~", "rm -rf /"),
                          progress=lambda k, t: seen.append((k, t)))
    return res, ws, seen


res, ws, seen = go(GOOD)
repo = ws / "loki-test-repo"
log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"], capture_output=True, text=True)
check("the commands REALLY ran: a git repo with one commit", log.returncode == 0 and "First commit: hello" in log.stdout, log.stdout + log.stderr)
check("... src/main.py prints hello, README.md is there", subprocess.run([sys.executable, str(repo / "src" / "main.py")], capture_output=True,
      text=True).stdout.strip() == "hello" and (repo / "README.md").is_file())
check("... a reply with two code blocks ran only the first", not (repo / "NOPE").exists())
check("... a reply with no command was answered with a format note and the work went on",
      any("Format error" in (m.get("content") or "") for m in STATE["bodies"][3][1]["messages"]), STATE["bodies"][3][1]["messages"][-1])
check("ok, and LOKI's reply has the git log LOKI ran itself and what changed", res["ok"] and "Checked by LOKI" in res["reply"]
      and "First commit: hello" in res["reply"] and "loki-test-repo/src/main.py" in res["reply"], res)
path, body = STATE["bodies"][0]
check("lean request: Ollama /api/chat, think=false, num_ctx 16384, no tool schemas", path == "/api/chat" and body["think"] is False
      and body["options"]["num_ctx"] == 16384 and "tools" not in body and body["stream"] is False, body)
check("... a short prompt (system + task under 2,500 characters, vs OpenCode's ~12,000 tokens)",
      sum(len(m["content"]) for m in body["messages"]) < 2500, sum(len(m["content"]) for m in body["messages"]))
check("... each command's real output goes back to the model", "<returncode>0</returncode>" in STATE["bodies"][1][1]["messages"][-1]["content"])
check("progress shows the commands as they run", any(k == "tool" and "git init" in t for k, t in seen), seen[:5])

res, ws, _ = go(LIAR)
check("a model that only SAYS done: NOT DONE, nothing made", res["reply"].startswith("NOT DONE") and not res["ok"]
      and not (ws / "loki-test-repo").exists(), res["reply"][:200])
res, ws, seen = go(DANGER)
check("a dangerous command (rm -rf ~) is refused, never run", any(k == "error" and "Refused" in t for k, t in seen)
      and "REFUSED by LOKI" in STATE["bodies"][1][1]["messages"][-1]["content"], seen)

# ---- through the chat: a local model picked -> this agent, not OpenCode
try:
    import loki  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print("SKIP chat part: the engine does not import here (%s)" % exc)
else:
    loki.MODELS["local"].base_url = BASE
    loki.MODELS["local"].model = "loki-qwen3.5-9b"
    loki.model_name = "local"
    loki.AGENT_MODE = "build"
    loki.WORKSPACE = Path(tempfile.mkdtemp(prefix="ws-chat-", dir=TMP))
    import opencode_engine  # noqa: E402
    opencode_engine.find_opencode = lambda *a, **k: (_ for _ in ()).throw(AssertionError("OpenCode must not be used"))
    STATE.update(script=GOOD, i=0, bodies=[])
    out = asyncio.run(asyncio.wait_for(loki.run_opencode(REQ), 40))
    log = subprocess.run(["git", "-C", str(loki.WORKSPACE / "loki-test-repo"), "log", "--oneline"], capture_output=True, text=True)
    check("chat with the local model picked: the offline agent made the repo (OpenCode never called)",
          "First commit: hello" in log.stdout and "Checked by LOKI" in out, out[:400])

check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
