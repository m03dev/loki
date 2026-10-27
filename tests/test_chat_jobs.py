"""Several chats at once + updates that never get stuck (owner 2026-10-26). Engine side, no network:
  - a chat made while another answers is parked (saved, listed, not active); a turn can be added to it
  - a chat job (Run in background, or a message sent while another chat answers) gets the chat so far, its message is
    in the chat at once, and its answer is written into THAT chat when it ends - once; an answer for the chat that is
    answering in front waits until it is done
  - updater.ready_to_apply: idle -> go; busy with jobs -> wait, but after LOKI_UPDATE_MAX_WAIT_S only a chat in
    progress holds it back

    python tests/test_chat_jobs.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]
DATA = Path(tempfile.mkdtemp(prefix="loki-chatjobs-"))
os.environ["LOKI_DATA"] = str(DATA)
T0 = time.time()

import loki  # noqa: E402
import loki_bridge  # noqa: E402
import updater  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


loki.CONVERSATIONS_FILE = DATA / "conversations.json"
loki.CONVERSATIONS.clear()
first = loki.new_conversation("first")
loki.append_to_conversation(first, "user", "make a dragon")
loki.append_to_conversation(first, "assistant", "here is the dragon")
parked = loki.park_conversation("")
check("a parked chat is listed", parked in [c["id"] for c in loki.list_conversations()])
check("... but the active chat stays the one answering", loki.active_conversation_id() == first)
check("... and the active chat's history is untouched", [m["content"] for m in loki.messages if m["role"] != "system"] == ["make a dragon", "here is the dragon"])
check("append to a parked chat titles it", loki.append_to_conversation(parked, "user", "a sprite of a knight")
      and next(c for c in loki.list_conversations() if c["id"] == parked)["title"].startswith("a sprite"))
check("context is the chat so far", "make a dragon" in loki.conversation_context(first) and "here is the dragon" in loki.conversation_context(first))


class _Jobs:
    def __init__(self):
        self.on_change = None
        self.made = []

    def create(self, spec):
        job = {"id": "j%d" % (len(self.made) + 1), "status": "queued", "conversation_id": spec.get("conversation_id", ""), "prompt": spec["prompt"]}
        self.made.append(job)
        return job

    def status(self):
        return {"jobs": self.made}

    def tick(self):
        pass


class _State:
    def __init__(self):
        self.agent = loki
        self.jobs = _Jobs()
        self.project = DATA
        self.lock = threading.Lock()
        self.chat_lock = asyncio.Lock()


state = _State()
code, out = loki_bridge.job_action(state, "/jobs", {"backend": "local", "agent": "loki", "prompt": "and a sword?", "conversation_id": first})
job = state.jobs.made[-1]
check("a chat job is created", code == 200 and out.get("ok"), out)
check("... with the chat so far in its prompt", "make a dragon" in job["prompt"] and "and a sword?" in job["prompt"], job["prompt"][:200])
check("... its message is in the chat at once", loki.conversation_messages(first)[-1]["content"] == "and a sword?")
check("... and the supervisor is watched", state.jobs.on_change is not None)

(DATA / "jobs").mkdir(exist_ok=True)
(DATA / "jobs" / (job["id"] + ".result.txt")).write_text("DONE: here is the sword", encoding="utf-8")
loki.DATA_DIR = DATA
state.jobs.on_change(dict(job, status="working"))
check("a job still working writes nothing", loki.conversation_messages(first)[-1]["content"] == "and a sword?")


async def busy_then_free():
    async with state.chat_lock:   # the same chat is answering in front
        state.jobs.on_change(dict(job, status="done"))
        held = loki.conversation_messages(first)[-1]["content"]
    loki_bridge.flush_chat_jobs(state)
    return held


held = asyncio.run(busy_then_free())
check("while that chat answers in front, the answer waits", held == "and a sword?", held)
check("... and lands when it is done, without the DONE marker", loki.conversation_messages(first)[-1] == {"role": "assistant", "content": "here is the sword"},
      loki.conversation_messages(first)[-1])
state.jobs.on_change(dict(job, status="done"))
check("... once", sum(1 for m in loki.conversation_messages(first) if m["content"] == "here is the sword") == 1)
check("the active chat's in-memory history has it too (its next turn sees it)", loki.messages[-1]["content"] == "here is the sword")

failed = {"id": "j9", "status": "failed", "conversation_id": parked, "output": "boom"}
loki_bridge.chat_job_done(state, failed)
check("a failed chat job says so in its chat", "stopped (failed)" in loki.conversation_messages(parked)[-1]["content"])

# ---- updates that never get stuck
calls = []


def idle(strict=True):
    calls.append(strict)
    return not strict   # jobs always running, nobody chatting


now = time.time()
os.environ["LOKI_UPDATE_MAX_WAIT_S"] = "1200"
check("an update waits while background jobs run", not updater.ready_to_apply(idle, now - 60, now))
check("... but goes in after the max wait when nobody is chatting", updater.ready_to_apply(idle, now - 1300, now))
check("... never during a chat", not updater.ready_to_apply(lambda strict=True: False, now - 99999, now))
check("an old idle() without the relaxed form keeps waiting", not updater.ready_to_apply(lambda: False, now - 99999, now))
check("idle applies at once", updater.ready_to_apply(lambda strict=True: True, now, now))
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
