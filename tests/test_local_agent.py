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
        if text == "__500__":      # Ollama's parser choking on the model's output (the Mac, 2026-10-25 13:53)
            data = b'{"error":"failed to parse tool call"}'
            self.send_response(500); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            return
        data = json.dumps({"model": body.get("model"), "message": {"role": "assistant", "content": text}, "done": True,
                           "prompt_eval_count": 1000, "eval_count": 50, "eval_duration": int(2.5e9)}).encode()
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
check("... a short prompt (system + task under 3,500 characters, vs OpenCode's ~12,000 tokens)",
      sum(len(m["content"]) for m in body["messages"]) < 3500, sum(len(m["content"]) for m in body["messages"]))
check("... each command's real output goes back to the model", "<returncode>0</returncode>" in STATE["bodies"][1][1]["messages"][-1]["content"])
check("progress shows the commands as they run", any(k == "tool" and "git init" in t for k, t in seen), seen[:5])
meters = [json.loads(t) for k, t in seen if k == "usage"]
check("the live meter: after every step the model, 'this computer', tokens so far and tok/s", meters and meters[-1]["model"] == "loki-qwen3.5-9b"
      and meters[-1]["where"] == "this computer" and meters[-1]["input"] == 1000 * len(meters) and meters[-1]["output"] == 50 * len(meters)
      and meters[-1]["tps"] == 20.0, meters[-1:])

res, ws, _ = go(LIAR)
check("a model that only SAYS done: NOT DONE, nothing made", res["reply"].startswith("NOT DONE") and not res["ok"]
      and not (ws / "loki-test-repo").exists(), res["reply"][:200])
res, ws, seen = go(DANGER)
check("a dangerous command (rm -rf ~) is refused, never run", any(k == "error" and "Refused" in t for k, t in seen)
      and "REFUSED by LOKI" in STATE["bodies"][1][1]["messages"][-1]["content"], seen)

ROOTGIT = ["THOUGHT: init here.\n```bash\ngit init -q && git add -A && git commit -qm init && git log --oneline\n```",
           "Done.\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"]
wsr = Path(tempfile.mkdtemp(prefix="ws-root-", dir=TMP)); (wsr / ".loki").mkdir(); (wsr / ".loki" / "loki_conversations.json").write_text("{}")
res, wsr, _ = go(ROOTGIT, wsr)
tracked = subprocess.run(["git", "-C", str(wsr), "ls-files"], capture_output=True, text=True).stdout
check("a git repo made around the workspace never takes .loki/ (the private chats)", ".loki" not in tracked
      and (wsr / ".loki" / ".gitignore").is_file(), tracked)
check("... and the reply says the whole working folder became a repo (not asked for)", "turned the whole working folder" in res["reply"], res["reply"][-300:])

res, ws, seen = go(["__500__"] + GOOD)
check("Ollama answers 500 on a step (its parser choked): asked again, and the work still gets done",
      res["ok"] and (ws / "loki-test-repo" / "src" / "main.py").is_file() and any("asking again" in t for k, t in seen)
      and "could not be read" in STATE["bodies"][1][1]["messages"][-1]["content"], res["reply"][:300])

# stuck: the same failure three times -> stop and say it (the Mac: 30 steps of 'git push ... 403')
STUCK = ["THOUGHT: push.\n```bash\ngit push origin main\n```"] * 10
res, ws, _ = go(STUCK)
check("the same error three times: stops after 3 commands with BLOCKED and the error (no 30 steps)",
      res["exit"] == "stuck" and res["commands"] == 3 and res["reply"].startswith("BLOCKED") and "fatal" in res["reply"], res["reply"][:300])
# a question for the owner: stops and asks
ASK = ["THOUGHT: look.\n```bash\nls\n```", "QUESTION: The repo m03dev/loki-test already exists on GitHub - push into it?"]
res, ws, _ = go(ASK)
check("QUESTION: the agent stops and asks the owner (not 'NOT DONE')", res["exit"] == "question"
      and res["reply"].startswith("QUESTION: The repo m03dev/loki-test already exists"), res["reply"][:200])
assert "GitHub: `gh auth status` first" in local_agent.SYSTEM and "gh auth setup-git" in local_agent.SYSTEM
# publish: LOKI asks the remote itself whether the commit is there
PUBREQ = "push loki-test to github"
wsp = Path(tempfile.mkdtemp(prefix="ws-pub-", dir=TMP))
bare = TMP / ("remote-%d.git" % int(time.time() * 1000)); subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
PUB = ["THOUGHT: repo.\n```bash\nmkdir loki-test && cd loki-test && git init -q -b main && echo hi > README.md && git add -A && "
       "git -c user.name=t -c user.email=t@t commit -qm first && git remote add origin %s && git push -q origin main\n```" % bare,
       "Pushed.\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"]
STATE.update(script=PUB, i=0, bodies=[])
res = local_agent.run(PUBREQ, wsp, BASE, "m", deny=())
check("after a push LOKI checks the remote itself: 'pushed' with the commit", res["ok"] and "pushed." in res["reply"], res["reply"][-300:])
wsn = Path(tempfile.mkdtemp(prefix="ws-nopub-", dir=TMP))
bare2 = TMP / ("remote2-%d.git" % int(time.time() * 1000)); subprocess.run(["git", "init", "-q", "--bare", str(bare2)], check=True)
NOPUB = [PUB[0].replace(" && git push -q origin main", "").replace(str(bare), str(bare2)), PUB[1]]
STATE.update(script=NOPUB, i=0, bodies=[])
res = local_agent.run(PUBREQ, wsn, BASE, "m", deny=())
check("... a 'pushed!' that never reached the remote: NOT DONE", res["reply"].startswith("NOT DONE - the push did not reach")
      and "NOT pushed" in res["reply"], res["reply"][:300])

# removing anything asks the owner first (the Mac 16:05: "remove chats" -> rm -rf .loki with no prompt)
RM = ["THOUGHT: The old notes are not needed - I will delete junk/.\n```bash\nrm -rf junk\n```",
      "OK.\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"]
asked = []
for allow in (False, True):
    STATE.update(script=RM, i=0, bodies=[])
    wsr = Path(tempfile.mkdtemp(prefix="ws-rm-", dir=TMP)); (wsr / "junk").mkdir(); (wsr / "junk" / "a.txt").write_text("x")
    local_agent.run("delete the junk folder", wsr, BASE, "m", deny=(), approve=lambda c, w, a=allow: (asked.append((c, w)), a)[1])
    if not allow:
        check("rm asks the owner first, with the command and why; Deny -> nothing removed", (wsr / "junk" / "a.txt").exists()
              and asked and asked[0][0] == "rm -rf junk" and "old notes" in asked[0][1], asked)
    else:
        check("... Allow -> removed", not (wsr / "junk").exists())
STATE.update(script=RM, i=0, bodies=[])
wsr = Path(tempfile.mkdtemp(prefix="ws-rm-", dir=TMP)); (wsr / "junk").mkdir()
local_agent.run("delete the junk folder", wsr, BASE, "m", deny=())
check("... nobody there to ask (no approve) -> not removed", (wsr / "junk").is_dir())
check("what counts as removing / overwriting", all(local_agent.needs_ok(c) for c in (
    "rm -f a", "cd x && rm -r y", "git reset --hard HEAD~1", "git push --force origin main", "git clean -fd", "find . -name '*.tmp' -delete",
    "loki chats delete --all", "sudo rm x")) and not any(local_agent.needs_ok(c) for c in (
    "ls -la", "git status", "git push origin main", "echo firm > notes.txt", "python3 -m pip install form", "grep -r alarm .")))
DOTLOKI = ["THOUGHT: remove chats.\n```bash\nrm -rf .loki\n```", "```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"]
STATE.update(script=DOTLOKI, i=0, bodies=[])
wsd = Path(tempfile.mkdtemp(prefix="ws-dl-", dir=TMP)); (wsd / ".loki").mkdir(); (wsd / ".loki" / "loki_conversations.json").write_text("{}")
local_agent.run("remove all the other chats", wsd, BASE, "m", deny=(), approve=lambda c, w: True)
check("the .loki folder (the chats) is never touched, even when allowed - 'loki chats' is offered instead",
      (wsd / ".loki" / "loki_conversations.json").exists() and "loki chats" in STATE["bodies"][1][1]["messages"][-1]["content"])

code, out = local_agent.run_command("loki-make machines", TMP)
check("the shell agent has LOKI's makers as a command: `loki-make machines` answers", code == 0 and '"machines"' in out, out[:300])
code, out = local_agent.run_command("loki-make nonsense", TMP)
check("... `loki-make` with a wrong word prints how to use it", code == 2 and "usage: loki-make image" in out, out[:200])
check("... and the prompt tells the model to draw with loki-make, not with text", "loki-make image" in local_agent.SYSTEM)

# ---- through the chat: a local model picked -> this agent, not OpenCode
try:
    import loki  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print("SKIP chat part: the engine does not import here (%s)" % exc)
else:
    # colibri (big MoE models, offloaded): found when `coli serve` answers, its model read from /v1/models
    class Coli(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            data = json.dumps({"data": [{"id": "qwen36-35b"}]}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    csrv = ThreadingHTTPServer(("127.0.0.1", 0), Coli)
    threading.Thread(target=csrv.serve_forever, daemon=True).start()
    loki.MODELS["colibri"].base_url = "http://127.0.0.1:%d/v1" % csrv.server_address[1]
    check("colibri is a local provider: found when it answers, its model read from it, run by the shell agent",
          loki.local_server_up("colibri") and loki.MODELS["colibri"].model == "qwen36-35b" and loki._local_agent_for("colibri")
          and "colibri" in loki.SMART_ORDER, loki.MODELS["colibri"])
    check("Smart tries Nemotron on NVIDIA first after your main driver (NVIDIA DeepSeek)",
          [p for p in loki.SMART_ORDER if p != loki.MAIN_DRIVER][0] == "nvidia-nemotron", loki.SMART_ORDER[:3])
    import loki_bridge  # noqa: E402
    loki_bridge._STARTUP.update(t0=time.time(), last=time.time(), steps=[], cur="a")
    loki_bridge._startup_mark("b"); time.sleep(0.05); loki_bridge._startup_mark("done"); loki_bridge._startup_report()
    st = json.loads((Path(os.environ["LOKI_DATA"]) / "app" / "startup.json").read_text())
    check("startup timing: each step timed and saved to startup.json (Windows slow start)", [x[0] for x in st["steps"]] == ["a", "b"]
          and st["steps"][1][1] >= 0.04, st)
    # `loki chats` - the real chat list
    keep = loki.active_conversation_id()
    others = [loki.new_conversation("old %d" % i) for i in range(2)]
    loki.switch_conversation(keep)
    code, out = loki._chats_command("loki chats list")
    check("`loki chats list` lists LOKI's chats, marks the one in use", code == 0 and "(this chat)" in out and "old 1" in out, out)
    code, out = loki._chats_command("loki chats delete --all")
    check("`loki chats delete --all` deletes the others, keeps the chat in use", "deleted" in out
          and [c["id"] for c in loki.list_conversations()] == [keep], (out, loki.list_conversations()))
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

src_l = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
src_s = (REPO / "studio" / "studio_core.py").read_text(encoding="utf-8")
check("Home LOKI is told its focus is the owner's work OUTSIDE the app, LOKI Studio that it is the INSIDE agent",
      "Your job (Home): the owner's work OUTSIDE this app" in src_l and "you are the INSIDE agent" in src_s
      and "outside the LOKI app" in local_agent.SYSTEM)
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
