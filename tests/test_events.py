"""The event stream and the world view: real events only, in order, from every part of LOKI.

    python tests/test_events.py

Also proves the decision layer runs BEFORE the model on every request (docs/VISION.md 5:
"the key test is whether every applicable request follows the required decision path
before model and tool execution").
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
TMP = Path(tempfile.mkdtemp())
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_WORKSPACE"] = str(TMP / "ws")
os.environ["LOKI_EXPERIENCE"] = "0"
os.environ["LOKI_PEER_NAME"] = "test-mac"
for key in ("LAYA_BASE_URL", "TYPESAFE_API_KEY", "LOKI_TEAM_ID"):
    os.environ.pop(key, None)
os.environ["LOKI_LAYA_LOCAL"] = "0"
(TMP / "data").mkdir()
(TMP / "ws").mkdir()
sys.path.insert(0, str(REPO / "engine"))

import events  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:300]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


section("events have one shape and stay in order")
a = events.emit("task.created", "LOKI", {"title": "x"}, task="t1")
b = events.emit("agent.message", "Builder", {"text": "hi"}, team="team1", recipient="Tester")
check("an event carries type, sender, recipient, task, team, machine, payload",
      all(k in b for k in ("seq", "t", "type", "sender", "recipient", "task", "team", "machine", "payload"))
      and b["machine"] == "test-mac" and b["recipient"] == "Tester")
check("sequence numbers only go up", b["seq"] > a["seq"])
check("read(after) returns only newer events", [e["type"] for e in events.read(a["seq"])] == ["agent.message"])
try:
    events.emit("made.up", "x")
    check("unknown event types are refused", False)
except ValueError:
    check("unknown event types are refused", True)
c = events.emit("agent.status", "LOKI", {"state": "idle", "api_key": "sk-secret", "note": "x" * 5000})
check("secrets never enter the stream", "api_key" not in c["payload"])
check("payloads stay small", len(c["payload"]["note"]) <= 2000)

section("long poll: a waiting client is woken by a new event")
got = {}


def waiter():
    got["events"] = events.wait(c["seq"], timeout=10)


th = threading.Thread(target=waiter)
th.start()
time.sleep(0.4)
events.emit("task.started", "Builder", {}, task="t1")
th.join(5)
check("the waiting client receives the new event", got.get("events") and got["events"][0]["type"] == "task.started", got)
started = time.monotonic()
check("an idle wait returns empty at its timeout", events.wait(events.latest_seq(), timeout=0.5) == []
      and time.monotonic() - started < 3)

section("background jobs and teams report themselves")
import workers  # noqa: E402

sup = workers.default_supervisor(TMP / "data" / "workers")
before = events.latest_seq()
job = sup.create({"backend": "local", "agent": "loki", "prompt": "build it", "workspace": str(TMP / "ws"),
                  "profile": {"name": "Builder"}, "team": "team1", "title": "Team team1 · Builder: build it"})
sup._set(job["id"], status="working")
# finished stamped as the real completion path does (so "done today" never hangs on the clock:
# the only other done job finished 2 h ago, which is yesterday just after midnight)
sup._set(job["id"], status="done", output="DONE: built", finished=time.time())
kinds = [(e["type"], e["sender"]) for e in events.read(before)]
check("a job's life is created -> started -> completed, by its role",
      kinds == [("task.created", "Builder"), ("task.started", "Builder"), ("task.completed", "Builder")], kinds)
check("job events carry the job and team ids", all(e["task"] == job["id"] and e["team"] == "team1" for e in events.read(before)))

import team  # noqa: E402

before = events.latest_seq()
team.post("team1", "Tester", "FAIL: button does nothing", "Builder")
msg = events.read(before)
check("a team board post is an agent.message from that agent to its recipient",
      msg and msg[0]["type"] == "agent.message" and msg[0]["sender"] == "Tester" and msg[0]["recipient"] == "Builder", msg)

section("the world: who is there and what they do, from real state only")
world = events.world(sup.store.all(), [], chat_busy=True, last_decision={"kind": "code"})
names = [a["name"] for a in world["agents"]]
check("LOKI itself is always there", names[0] == "LOKI" and world["agents"][0]["state"] == "working")
builder = [a for a in world["agents"] if a["name"] == "Builder"]
check("a team agent appears with its role, state and station",
      builder and builder[0]["state"] == "done" and builder[0]["station"] == "workshop" and builder[0]["team"] == "team1", builder)
team.post("team1", "Builder", "built the order page")
check("its last real board message is attached",
      [a for a in events.world(sup.store.all(), [], False)["agents"] if a["name"] == "Builder"][0]["last_message"] == "built the order page")
old = sup.create({"backend": "local", "agent": "loki", "prompt": "old", "workspace": str(TMP / "ws")})
sup.store.update(old["id"], status="done", finished=time.time() - 7200)
check("long-finished agents leave the world", not any(a["id"] == "job-" + old["id"] for a in
      events.world(sup.store.all(), [], False)["agents"]))
check("the world carries the event cursor for the next poll", world["cursor"] > 0)

section("the world stays cheap and exact as the log grows (the 3D view polls it every few seconds)")
team.post("team2", "Builder", "built the docs page")
w2 = events.world(sup.store.all(), [], False)
b1 = [a for a in w2["agents"] if a["name"] == "Builder" and a["team"] == "team1"]
check("two Builders in two teams keep their own lines (board message keyed by team)",
      b1 and b1[0]["last_message"] == "built the order page", b1)
check("the cursor is the newest seq, read incrementally", w2["cursor"] == events.read(0, limit=1)[-1]["seq"])
team.post("team1", "Builder", "half")
with open(events.log_path(), "a", encoding="utf-8") as fh:
    fh.write('{"seq": 9, "type": "agent.message", "sender": "Builder", "team": "team1", "payload": {"text": "torn')
check("a half-written last line is not read until it is complete",
      [a for a in events.world(sup.store.all(), [], False)["agents"] if a["team"] == "team1" and a["name"] == "Builder"][0]["last_message"] == "half")
with open(events.log_path(), "a", encoding="utf-8") as fh:
    fh.write('"}}\n')
team.post("team1", "Builder", "after the torn line")
check("once it is complete, scanning carries on",
      [a for a in events.world(sup.store.all(), [], False)["agents"] if a["team"] == "team1" and a["name"] == "Builder"][0]["last_message"] == "after the torn line")
events._rotate(events.log_path())
team.post("team1", "Builder", "after rotation")
check("a rotated (smaller) log is re-read from the start",
      [a for a in events.world(sup.store.all(), [], False)["agents"] if a["team"] == "team1" and a["name"] == "Builder"][0]["last_message"] == "after rotation")
calls = {"n": 0}
real_loads = events.json.loads
events.json.loads = lambda raw, *a, **k: (calls.__setitem__("n", calls["n"] + 1), real_loads(raw, *a, **k))[1]
try:
    events.world(sup.store.all(), [], False)
    events.world(sup.store.all(), [], False)
finally:
    events.json.loads = real_loads
check("polling with nothing new parses no log lines", calls["n"] == 0, calls)
w3 = events.world(sup.store.all(), [{"id": "team1", "goal": "g", "status": "working", "stage": "build",
                                      "roles": ["architect", "builder", "tester"]}], False)
t1 = w3["teams"][0]
check("a team carries the stages it really has, in order", t1["stages"] == ["plan", "build", "check"], t1)
check("agents carry when they started and their team's stage, from the job record",
      all("since" in a and "stage" in a for a in w3["agents"]) and
      any(a["team"] == "team1" and a["stage"] == "build" for a in w3["agents"]), w3["agents"][:2])
check("the world counts real work (working/waiting/blocked, done and failed today)",
      set(w3["stats"]) == {"working", "waiting", "blocked", "done_today", "failed_today"} and w3["stats"]["done_today"] >= 1, w3["stats"])

section("the decision is made BEFORE the model runs, on every request")
import loki  # noqa: E402

seen = {}


async def fake_turn(*_a, **_k):
    seen["triage"] = dict(loki.LAST_TRIAGE)
    seen["decisions"] = [e for e in events.read(seen["mark"]) if e["type"] == "decision.made"]
    return "DONE: answered"


loki.agent_turn = fake_turn
for text in ("what is this project?", "fix the crash in parser.py when the file is empty"):
    seen.clear()
    seen["mark"] = events.latest_seq()
    asyncio.run(loki.run_agent(text))
    check("decision recorded before the model call: %r" % text[:30],
          seen.get("triage", {}).get("kind") and len(seen.get("decisions", [])) == 1, seen)
seen.clear()
seen["mark"] = events.latest_seq()
result = asyncio.run(loki.pursue_goal("add a jump to the player"))
check("a model that says DONE without writing anything is stopped, not looped forever",
      result.startswith("BLOCKED") and "without changing any file" in result, result)
check("tasks (the goal loop) are decided first too", len(seen.get("decisions", [])) == 1, seen)


async def dir_only_turn(*_a, **_k):   # the S2 case: only make_dir, then a false DONE
    await loki.call_tool("make_dir", {"path": "notes"})
    return "DONE: Created notes/hello.txt with 'hi'"


async def failed_write_turn(*_a, **_k):   # a write that errored changed nothing
    await loki.call_tool("write_file", {"path": "../../outside/x.txt", "content": "hi"})
    return "DONE: wrote it"


loki.agent_turn = dir_only_turn
result = asyncio.run(loki.pursue_goal("create notes/hello.txt with hi, then list the folder"))
check("the main task loop does not accept DONE when only the folder was made for a named file",
      result.startswith("BLOCKED") and ("without changing any file" in result
                                        or "without making notes/hello.txt" in result), result)
check("...and the goal parser knows a named file from a folder or a web address",
      loki._goal_names_file("create notes/hello.txt") and not loki._goal_names_file("make a folder called notes")
      and not loki._goal_names_file("open https://example.com/a.html") and not loki._goal_names_file("e.g. make it faster"))
result = asyncio.run(loki.pursue_goal("make a folder called notes"))
check("a goal that only asks for a folder is done once the folder is made", result.startswith("DONE"), result)
loki.agent_turn = failed_write_turn
result = asyncio.run(loki.pursue_goal("create x.txt with hi"))
check("a tool call that returned an error does not count as a change", result.startswith("BLOCKED"), result)
loki.agent_turn = fake_turn
d = seen.get("decisions", [{}])[0].get("payload", {})
check("the decision is structured: intent, route, capabilities, risk, approval, rationale, fallback",
      all(k in d for k in ("intent", "route", "capabilities", "risk", "approval", "rationale", "fallback")), d)
check("without Laya or Jev the rules decide, and say so", d.get("source") == "rules" and "rules" in d.get("rationale", "").lower(), d)
status = [e["payload"].get("state") for e in events.read(seen["mark"]) if e["type"] == "agent.status"]
check("LOKI reports working, then idle", status[:1] == ["working"] and status[-1:] == ["idle"], status)

section("spending policy: never paid on its own, and a daily cap")
saved = (loki.provider_configured, loki.online, loki.local_ready, loki.model_name, loki.ALLOW_PAID)
loki.provider_configured = lambda name: name in ("deepseek", "nvidia-nemotron")
loki.online = lambda: True
loki.local_ready = lambda: False
loki.model_name = "smart"
loki._SMART_FAILED.clear()
loki.ALLOW_PAID = False
check("smart skips a configured paid provider and uses the free one", loki.active_model_name() == "nvidia-nemotron", loki.active_model_name())
loki._SMART_FAILED.add("nvidia-nemotron")
check("even when the free one is used up, it does not switch to paid by itself", loki.active_model_name() != "deepseek")
loki.ALLOW_PAID = True
check("paid is used only once you allow it", loki.active_model_name() == "deepseek")
loki.USAGE.record("deepseek", "x", 1, 1, 10)
loki.USAGE.path.write_text('{"t": %f, "provider": "deepseek", "model": "x", "in": 1, "out": 1, "ms": 10, "cost": 5.0, "free": false}\n' % time.time())
check("the daily dollar limit stops automatic paid use", loki.active_model_name() != "deepseek")
loki.provider_configured, loki.online, loki.local_ready, loki.model_name, loki.ALLOW_PAID = saved
loki._SMART_FAILED.clear()
check("the call path refuses paid calls past the daily limit", "hit the daily paid budget" in
      (REPO / "engine" / "loki.py").read_text(encoding="utf-8"))

section("machines advertise what they can really do")
import peer_link  # noqa: E402

caps = peer_link.machine_capabilities(None, local_models=[])
check("the basics are always there", {"model.chat", "code.edit", "agents.team"} <= set(caps), caps)
check("local inference is claimed only with a local model", "model.local-inference" not in caps
      and "model.local-inference" in peer_link.machine_capabilities(None, local_models=["qwen3:8b"]))

section("wired into the engine")
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("/events (long poll) and /world are served", 'route in ("/events", "/world")' in bridge and "events.wait(" in bridge)
check("approvals are events", '"approval.required"' in bridge)
check("the live view is documented where it is served (events.py), the old world client docs are gone",
      "GET /world" in (REPO / "engine" / "events.py").read_text(encoding="utf-8") and not (REPO / "docs" / "WORLD.md").exists())

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
