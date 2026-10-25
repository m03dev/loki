"""The window's chat never shows a fake "done" (owner 2026-10-25: "it said it did it but I checked my repo and nothing
was done. This has been the main issue with LOKI: it says but it doesn't actually do").

The REAL chat path (loki.run_agent - what the window's Send runs) with a scripted fake model:
  * a model that claims "Done! I created the repo" without calling a tool is pushed back once; if it still calls
    nothing, the reply says NOT DONE (and the conversation remembers that, not the fake success);
  * pushed back, a model that then really calls bash makes the repo - git init, folders, files, commit - on disk;
  * an honest model that calls bash first gets one pass, no pushback;
  * Ask mode: a claim is NOT DONE at once and says to switch to Build;
  * a question is never flagged; a shell command that exits non-zero is a failed call, not a success.
Under a minute.

    python tests/test_honest_chat.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


t0 = time.time()
DATA = tempfile.mkdtemp(prefix="loki-honest-data-")
os.environ.setdefault("LOKI_DATA", DATA)
try:
    import loki  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print("SKIP: the engine does not import here (%s)\n\n0 passed, 0 failed" % exc)
    sys.exit(0)

FAKE_DONE = ("Done! I created a new git repo called `loki-test-repo` with src/main.py and README.md and committed "
             "them. Git log: root commit 3857bb7.")
REQUEST = ("use git bash to make a new git repo called loki-test-repo with a src folder, a README.md and src/main.py "
           "that prints hello, then commit it and show me git log")
MAKE = ("git init -q loki-test-repo && mkdir -p loki-test-repo/src && cd loki-test-repo && "
        "printf '# loki-test-repo\\n' > README.md && printf 'print(\"hello\")\\n' > src/main.py && git add -A && "
        "git -c user.name=LOKI -c user.email=loki@localhost commit -q -m 'First commit' && git log --oneline")


def reply(content="", calls=None):
    tool_calls = None
    if calls:
        tool_calls = [types.SimpleNamespace(id="call_" + uuid.uuid4().hex[:8], type="function",
                                            function=types.SimpleNamespace(name=n, arguments=json.dumps(a)))
                      for n, a in calls]
    msg = types.SimpleNamespace(role="assistant", content=content or ("" if calls else ""), tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")],
                                 usage=types.SimpleNamespace(prompt_tokens=100, completion_tokens=20))


class Fake:
    def __init__(self, steps):
        self.steps = list(steps)
        self.seen = []

    async def create(self, **kwargs):
        self.seen.append([m.get("content") if isinstance(m, dict) else "" for m in kwargs.get("messages") or []][-1])
        step = self.steps.pop(0) if self.steps else {"content": "(out of script)"}
        return reply(step.get("content", ""), step.get("calls"))


def run(steps, mode="build", request=REQUEST):
    ws = Path(tempfile.mkdtemp(prefix="loki-honest-ws-"))
    fake = Fake(steps)
    loki.WORKSPACE = ws
    loki.make_client = lambda: types.SimpleNamespace(chat=types.SimpleNamespace(completions=fake))
    loki.provider_configured = lambda name: name in ("local", "local-small")
    if hasattr(loki, "model_setup"):
        loki.model_setup.keep_warm = lambda *a, **k: None

    async def yes(*_a, **_k):
        return True
    loki.approve = yes
    loki.AGENT_MODE = mode
    loki.messages[:] = loki.messages[:1] if loki.messages else []
    try:
        out = asyncio.run(asyncio.wait_for(loki.run_agent(request), 40))
    except Exception as exc:  # noqa: BLE001
        out = "EXC %s: %s" % (type(exc).__name__, exc)
    return out, ws, fake


def repo_ok(ws: Path) -> bool:
    r = ws / "loki-test-repo"
    if not (r / ".git").is_dir() or not (r / "src" / "main.py").is_file() or not (r / "README.md").is_file():
        return False
    log = subprocess.run(["git", "-C", str(r), "log", "--oneline"], capture_output=True, text=True)
    return log.returncode == 0 and bool(log.stdout.strip())


# 1. the bug the owner hit: "Done!" twice, no tool -> NOT DONE, nothing on disk, history says NOT DONE
out, ws, fake = run([{"content": FAKE_DONE}, {"content": FAKE_DONE}])
check("a claim with no tool behind it -> pushed back once (a self-check message went to the model)",
      len(fake.seen) >= 2 and "NO tool was called" in str(fake.seen[1]), fake.seen[-1:])
check("... still no tool -> the reply says NOT DONE, plainly", out.startswith("NOT DONE"), out[:200])
check("... and nothing was made", not (ws / "loki-test-repo").exists())
check("... the conversation remembers NOT DONE, not the fake success",
      any(isinstance(m, dict) and m.get("role") == "assistant" and str(m.get("content", "")).startswith("NOT DONE")
          for m in loki.messages) and not any(isinstance(m, dict) and m.get("role") == "assistant"
                                               and str(m.get("content", "")).startswith("Done! I created") for m in loki.messages))

# 2. pushed back, it really does it with bash
out, ws, fake = run([{"content": FAKE_DONE}, {"calls": [("bash", {"command": MAKE})]},
                     {"content": "Made loki-test-repo with git init, src/main.py and README.md, committed (git log above)."}])
check("pushed back, the model calls bash: the repo is REALLY there (git init, src/, README.md, a commit)", repo_ok(ws), out[:200])
check("... and the reply is its real report, not NOT DONE", not out.startswith("NOT DONE"), out[:200])

# 3. an honest model: bash first, one pass
out, ws, fake = run([{"calls": [("bash", {"command": MAKE})]}, {"content": "Done: committed loki-test-repo."}])
check("an honest model: bash makes the repo, no pushback", repo_ok(ws) and len(fake.seen) == 2, (out[:120], len(fake.seen)))

# 4. Ask mode cannot change anything: a claim is NOT DONE at once and says to switch to Build
out, ws, fake = run([{"content": FAKE_DONE}], mode="ask")
check("Ask mode: a claimed action is NOT DONE and says to switch to Build", out.startswith("NOT DONE") and "Build" in out
      and len(fake.seen) == 1, out[:200])

# 5. a question is answered, never flagged
out, ws, fake = run([{"content": "Done is a word; git init creates a repository."}], request="what does git init do?")
check("a question is never flagged", not out.startswith("NOT DONE"), out[:120])

# 6. a failing command is a failed call: "exit 1" + a claim -> NOT DONE
out, ws, fake = run([{"calls": [("bash", {"command": "exit 1"})]}, {"content": FAKE_DONE},
                     {"calls": [("bash", {"command": "false"})]}, {"content": FAKE_DONE}])
check("a command that exits non-zero counts as failed: the claim is NOT DONE", out.startswith("NOT DONE")
      and "failed" in out, out[:200])

loki.AGENT_MODE = "build"
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
