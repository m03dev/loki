"""Session 28, offline: LOKI improving itself - fakes only, no network, no real model.

  E9  tools LOKI writes for itself (engine/user_tools.py, the make_tool tool): folder format, static scan,
      check before enabling, sandboxed run, approval first, denied in a background job unless allowed,
      loaded without a restart, Settings > Tools routes
  E6  speed watch (engine/speed_watch.py): timings from the real request loop, the window's POST /ui/timing,
      sparklines, the slowest step, the weekly speed idea; forecasts on queued jobs (job_stats + forecast.py)
  E8  self-review (engine/self_review.py): up to 3 "LOKI's idea" proposals that wait for the owner's OK
  Jobs dashboard (engine/job_stats.py): success over time / by model / by kind, failure reasons, retry on a
      stronger model; the daily self-test (engine/selftest.py) through the real background-job runner
  E2E  autopilot -> evolve -> improve_loki -> the job (real goal loop, scripted model) -> check_loki ->
      ship_loki proof -> settled as shipped, roadmap line ticked, not built again

    python tests/test_self_systems.py
"""
from __future__ import annotations

import asyncio
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-self-"))
DATA = TMP / "data"
WS = TMP / "ws"
WS.mkdir(parents=True, exist_ok=True)
os.environ["LOKI_DATA"] = str(DATA)
os.environ["LOKI_WORKSPACE"] = str(WS)
for _k in ("LOKI_JOB_ID", "LOKI_TEAM_ID", "LOKI_EVOLVE", "LOKI_SELFTEST", "LOKI_SPEED_IDEAS", "LOKI_SPEED_WATCH",
           "LOKI_AUTOPILOT_IDLE_S", "HARNESS_AUTO_APPROVE"):
    os.environ.pop(_k, None)
os.environ["LOKI_SELF_REVIEW_MODEL"] = "off"

import autopilot  # noqa: E402
import evolve  # noqa: E402
import job_stats  # noqa: E402
import self_api  # noqa: E402
import self_review  # noqa: E402
import selftest  # noqa: E402
import speed_watch  # noqa: E402
import user_tools  # noqa: E402
import loki  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def section(title):
    print("\n== " + title)


def fake_model(steps, seen=None):
    steps = list(steps)

    class _C:
        async def create(self, **kwargs):
            if seen is not None:
                seen.append(kwargs)
            step = steps.pop(0) if steps else {"content": "BLOCKED: the script ended"}
            calls = None
            if step.get("tool"):
                fn = types.SimpleNamespace(name=step["tool"], arguments=json.dumps(step.get("args", {})))
                calls = [types.SimpleNamespace(id="c%d" % len(steps), type="function", function=fn)]
            msg = types.SimpleNamespace(role="assistant", content=step.get("content", ""), tool_calls=calls)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)],
                                         usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=5))
    return lambda: types.SimpleNamespace(chat=types.SimpleNamespace(completions=_C()))


async def _noop(*a, **k):
    return []


class Store:
    def __init__(self):
        self.jobs = {}

    def all(self):
        return list(self.jobs.values())

    def get(self, job_id):
        return self.jobs.get(job_id)


class FakeJobs:
    def __init__(self):
        self.store = Store()
        self.created = []

    def create(self, spec):
        job_id = "j%03d" % (len(self.created) + 1)
        job = {"id": job_id, "status": "queued", "created": time.time(), "started": 0, "finished": 0,
               "title": spec.get("title", ""), "run_dir": spec.get("workspace", ""), "output": "", "error": "", **spec}
        self.created.append(job)
        self.store.jobs[job_id] = job
        return job

    def tick(self):
        pass

    def status(self):
        jobs = sorted(self.store.all(), key=lambda j: j.get("created", 0), reverse=True)
        return {"jobs": [{"id": j["id"], "title": j.get("title", ""), "status": j["status"]} for j in jobs],
                "counts": {}, "backends": {}, "running": True}


class FakeState:
    def __init__(self, agent=None):
        self.jobs = FakeJobs()
        self.last_request_at = 0
        self.agent = agent or types.SimpleNamespace(DATA_DIR=str(DATA))
        self.evolve = None

    def try_busy(self):
        return object()

    def release_busy(self, held):
        pass


LOOP_SAVED = None


def script_loop():
    """Point LOKI's real loop at scripted fakes (restored by restore_loop)."""
    global LOOP_SAVED
    LOOP_SAVED = (loki.make_client, loki.refresh_mcp_tools, loki.provider_configured, loki.model_name, loki.MODEL_RETRIES,
                  loki.local_ready, loki.online, loki.PREFER, loki.save_history, loki.first_layer.triage, loki.approve)
    loki.refresh_mcp_tools = _noop
    loki.provider_configured = lambda n: n == "openrouter"
    loki.model_name = "smart"
    loki.MODEL_RETRIES = 0
    loki.local_ready = lambda: False
    loki.online = lambda *a, **k: True
    loki.PREFER = "online"
    loki.save_history = lambda: None
    loki.first_layer.triage = lambda text, mode: {"route": "agent", "source": "rules", "kind": "build"}
    loki.loki_progress_callback = lambda event, text: None


def restore_loop():
    (loki.make_client, loki.refresh_mcp_tools, loki.provider_configured, loki.model_name, loki.MODEL_RETRIES,
     loki.local_ready, loki.online, loki.PREFER, loki.save_history, loki.first_layer.triage, loki.approve) = LOOP_SAVED


def run_job_inline(job: dict, workspace: Path) -> tuple:
    """loki.run_job (the background-job entry point) in this process, on `workspace`."""
    job_file = DATA / "jobs" / ("%s.job.json" % job["id"])
    job_file.parent.mkdir(parents=True, exist_ok=True)
    job = dict(job, result_path=str(DATA / "jobs" / ("%s.result.txt" % job["id"])))
    job_file.write_text(json.dumps(job), encoding="utf-8")
    saved_ws, saved_approve = loki.WORKSPACE, loki.approve
    os.environ["LOKI_JOB_ID"] = job["id"]
    loki.WORKSPACE = Path(workspace)
    try:
        code = asyncio.run(loki.run_job(str(job_file)))
    finally:
        loki.WORKSPACE, loki.approve = saved_ws, saved_approve
        os.environ.pop("LOKI_JOB_ID", None)
    return code, Path(job["result_path"]).read_text(encoding="utf-8") if Path(job["result_path"]).is_file() else ""


# =========================================================================== E9
section("E9 tools LOKI writes for itself")
WORD_COUNT = 'def run(args):\n    words = str(args.get("text", "")).split()\n    seen = []\n    for w in words:\n        if w in seen:\n            seen.remove(w)\n        seen.append(w)\n    return str(len(words))\n'
check("scan: a plain tool passes (list.remove is fine)", user_tools.scan(WORD_COUNT) == [], user_tools.scan(WORD_COUNT))
for bad, why in (("import subprocess\ndef run(args):\n    return subprocess.run(['ls'])\n", "subprocess"),
                 ("import os\ndef run(args):\n    os.system('rm -rf /')\n", "system"),
                 ("def run(args):\n    return eval(args['x'])\n", "eval"),
                 ("import shutil\ndef run(args):\n    shutil.rmtree('/')\n", "rmtree"),
                 ("import os\ndef run(args):\n    os.remove('x')\n", "remove"),
                 ("def nope(args):\n    return 1\n", "no top-level def run"),
                 ("def run(args)\n    return 1\n", "does not compile")):
    probs = user_tools.scan(bad)
    check("scan refuses: %s" % why, any(why in p for p in probs), probs)
net = "import urllib.request\ndef run(args):\n    return urllib.request.urlopen(args['u']).read()[:10]\n"
check("network code needs \"network\": true", any("network" in p for p in user_tools.scan(net)) and user_tools.scan(net, network=True) == [])

out = loki.make_tool("word_count", "Count the words in a text.", WORD_COUNT,
                     parameters={"text": {"type": "string", "description": "the text"}}, required=["text"],
                     tests=[{"args": {"text": "a b c"}, "expect": "3"}, {"args": {"text": ""}, "expect": "0"}])
check("make_tool writes, checks and loads a tool (no restart)", out.startswith("made tool word_count") and
      "word_count" in loki.LOCAL_TOOLS and any(t["function"]["name"] == "word_count" for t in loki.TOOL_SCHEMAS)
      and "word_count" in loki.MODEL_TOOL_NAMES, out)
folder = DATA / "tools" / "word_count"
meta = json.loads((folder / "tool.json").read_text(encoding="utf-8"))
check("the folder format: tool.json + one tool.py", (folder / "tool.py").is_file() and meta["name"] == "word_count"
      and meta["check"]["ok"] and meta["enabled"] and meta["created_by"] == "loki" and len(meta["tests"]) == 2, meta)
check("its schema says it asks before it runs", "asks before it runs" in user_tools.schema_of(user_tools.listing(DATA)[0])["function"]["description"])
check("it is offered to a local model right away (find_tools list)", "word_count" in loki.FOUND_TOOLS)
check("make_tool itself asks first (policy: dangerous)", loki.POLICY.tool_call("make_tool", {}).decision == "ask")
check("a built-in tool name is refused", "built-in" in loki.make_tool("read_file", "Read a file again here.", WORD_COUNT,
                                                                    tests=[{"args": {}, "expect": "0"}]))
check("code that fails the scan is not saved", loki.make_tool("bad_tool", "Runs a shell command badly.",
                                                              "import subprocess\ndef run(a):\n    return 1\n",
                                                              tests=[{"args": {}, "expect": "1"}]).startswith("error: the code was not saved")
      and not (DATA / "tools" / "bad_tool").exists())
res = loki.make_tool("wrong_math", "Adds two numbers (badly).", "def run(args):\n    return str(int(args['a']) - int(args['b']))\n",
                     parameters={"a": {"type": "integer"}, "b": {"type": "integer"}},
                     tests=[{"args": {"a": 2, "b": 2}, "expect": "4"}])
check("a tool whose tests fail is saved but switched OFF", res.startswith("error: saved but switched off") and
      "wrong_math" not in loki.LOCAL_TOOLS and not [t for t in user_tools.listing(DATA) if t["name"] == "wrong_math"][0]["enabled"], res)
check("a tool without tests cannot be enabled", not user_tools.make("no_tests", "A tool with no tests at all.",
                                                                     "def run(a):\n    return 'x'\n", root=DATA)["ok"])

# the sandbox
os.environ["GROQ_API_KEY"] = "gsk_secret_should_not_leak_1234"
leak = user_tools.make("env_peek", "Shows the environment the tool sees.",
                       "import os\ndef run(args):\n    return ' '.join(sorted(os.environ))\n",
                       tests=[{"args": {}, "expect": "PYTHON"}], root=DATA)
ok, text = user_tools.execute(DATA / "tools" / "env_peek", {}, WS)
check("the tool process gets no API keys and no LOKI_* settings", ok and "GROQ_API_KEY" not in text and "LOKI_DATA" not in text, text)
os.environ.pop("GROQ_API_KEY")
(WS / "notes.txt").write_text("hello", encoding="utf-8")
user_tools.make("read_notes", "Read notes.txt from the workspace.", "def run(args):\n    return open('notes.txt').read()\n",
                tests=[{"args": {}, "expect": ""}], root=DATA)
ok, text = user_tools.execute(DATA / "tools" / "read_notes", {}, WS)
check("it runs in the workspace (like run_command)", ok and text.strip() == "hello", text)
slow = DATA / "tools" / "spin"
slow.mkdir(parents=True)
(slow / "tool.py").write_text("def run(args):\n    while True:\n        pass\n", encoding="utf-8")
(slow / "tool.json").write_text(json.dumps({"name": "spin", "description": "spins forever"}), encoding="utf-8")
t0 = time.monotonic()
ok, text = user_tools.execute(slow, {}, WS, timeout=1)
check("a tool that runs too long is stopped", not ok and "longer than 1s" in text and time.monotonic() - t0 < 10, text)
ok, text = user_tools.execute(folder, {"text": "x y"}, WS)
check("printed output and the result are kept apart", ok and text.strip() == "2", text)

# approval first, in the window
asked = []


async def approve_yes(kind, detail, decidable=True):
    asked.append((kind, detail, decidable))
    return True


async def approve_no(kind, detail, decidable=True):
    asked.append((kind, detail, decidable))
    return False
saved_approve = loki.approve
loki.approve = approve_yes
try:
    got = asyncio.run(loki.call_tool("word_count", {"text": "one two three four"}))
    check("a call asks the owner first - never auto-decided - then runs", got.strip() == "4" and asked[-1][0] == "user_tool"
          and asked[-1][2] is False and "word_count" in asked[-1][1], (got, asked[-1:]))
    loki.approve = approve_no
    got = asyncio.run(loki.call_tool("word_count", {"text": "x"}))
    check("a refused call does not run", got.startswith("DENIED"), got)
finally:
    loki.approve = saved_approve

# Settings > Tools routes, and switching off / on / delete without a restart
state = FakeState(agent=types.SimpleNamespace(DATA_DIR=str(DATA), USER_TOOLS=loki.USER_TOOLS))
code, out = self_api.route(state, "GET", "/user_tools", {})
names = [t["name"] for t in out["tools"]]
check("GET /user_tools lists every tool with its check state", code == 200 and "word_count" in names and "wrong_math" in names
      and any(t["name"] == "wrong_math" and t["checked"] and not t["check_ok"] for t in out["tools"]), out)
code, out = self_api.route(state, "POST", "/user_tools/toggle", {"name": "word_count", "enabled": False})
check("Disable removes it from LOKI's tools at once", code == 200 and "word_count" not in loki.LOCAL_TOOLS
      and not any(t["function"]["name"] == "word_count" for t in loki.MODEL_TOOL_SCHEMAS), out)
code, out = self_api.route(state, "POST", "/user_tools/toggle", {"name": "word_count", "enabled": True})
check("Enable brings it back (re-checked)", code == 200 and "word_count" in loki.LOCAL_TOOLS, out)
check("only one schema per tool after toggling", sum(1 for t in loki.TOOL_SCHEMAS if t["function"]["name"] == "word_count") == 1)
code, out = self_api.route(state, "POST", "/user_tools/toggle", {"name": "wrong_math", "enabled": True})
check("a tool that fails its check cannot be enabled", code == 400 and "check" in out["error"], out)
(folder / "tool.py").write_text(WORD_COUNT.replace("return str(len(words))", "return 'nope'"), encoding="utf-8")
check("a tool changed since its check is off until it passes again",
      not [t for t in user_tools.listing(DATA) if t["name"] == "word_count"][0]["enabled"] and
      "word_count" not in loki.USER_TOOLS.sync())
code, out = self_api.route(state, "POST", "/user_tools/check", {"name": "word_count"})
check("Check runs its tests (the changed code fails them)", code == 400 and "test 1 failed" in out["error"], out)
(folder / "tool.py").write_text(WORD_COUNT, encoding="utf-8")
code, out = self_api.route(state, "POST", "/user_tools/check", {"name": "word_count"})
code2, _ = self_api.route(state, "POST", "/user_tools/toggle", {"name": "word_count", "enabled": True})
check("fixed code passes the check and can be switched on", code == 200 and code2 == 200 and "word_count" in loki.LOCAL_TOOLS, out)
code, out = self_api.route(state, "POST", "/user_tools/delete", {"name": "env_peek"})
check("Delete removes the folder", code == 200 and not (DATA / "tools" / "env_peek").exists())
check("names are checked (no paths)", self_api.route(state, "POST", "/user_tools/delete", {"name": "../x"})[0] == 400)
check("Settings > Tools has a 'my_tools' group", "my_tools" in loki.categories_state()["categories"])

# a background job: denied unless it was started with commands allowed
section("E9 in a background job (the real loki.run_job)")
script_loop()
seen_results = []
real_call_tool = loki.call_tool


async def recording_call_tool(name, args):
    result = await real_call_tool(name, args)
    seen_results.append((name, str(result)))
    return result
loki.call_tool = recording_call_tool
try:
    loki.make_client = fake_model([{"tool": "word_count", "args": {"text": "a b"}}, {"content": "BLOCKED: test over"}])
    run_job_inline({"id": "deny1", "prompt": "Count the words in 'a b' with your word_count tool.", "allow_commands": False}, WS)
    check("a background job may NOT run LOKI's own tool unless allowed", seen_results and seen_results[-1][0] == "word_count"
          and seen_results[-1][1].startswith("DENIED"), seen_results[-1:])
    loki.make_client = fake_model([{"tool": "word_count", "args": {"text": "a b"}}, {"content": "BLOCKED: test over"}])
    run_job_inline({"id": "allow1", "prompt": "Count the words in 'a b' with your word_count tool.", "allow_commands": True}, WS)
    check("a job started with commands allowed runs it", seen_results[-1] == ("word_count", "2"), seen_results[-1:])
finally:
    loki.call_tool = real_call_tool
    restore_loop()

# =========================================================================== E6
section("E6 speed watch")
SPD = TMP / "speed"
clock = [1_700_000_000.0]
for i, ms in enumerate([100, 120, 900, 110, 130]):
    speed_watch.record("tools", ms, root=SPD, note="read_file" if ms < 500 else "deep_research", clock=lambda: clock[0] + i)
for ms in (2500, 3000, 2800, 9000):
    speed_watch.record("model_call", ms, root=SPD, note="local", clock=lambda: clock[0])
speed_watch.record("triage", 40, root=SPD, clock=lambda: clock[0])
check("unknown phases and silly values are not kept", not speed_watch.record("nope", 1, root=SPD)
      and not speed_watch.record("tools", -5, root=SPD) and not speed_watch.record("tools", "x", root=SPD))
summ = speed_watch.summary(SPD, now=clock[0] + 10)
by = {p["phase"]: p for p in summ["phases"]}
check("summary: count, median, 90%, last per phase", by["tools"]["n"] == 5 and by["tools"]["p50"] == 120 and
      by["model_call"]["last"] == 9000 and by["model_call"]["p50"] == 2900, by["tools"])
check("each phase carries its last values for the sparkline", by["model_call"]["spark"] == [2500, 3000, 2800, 9000])
check("the slowest request step is named (needs 3+ samples)", summ["slowest"]["phase"] == "model_call", summ["slowest"])
check("the slowest tools come from the timing notes", speed_watch.tool_breakdown(SPD, window_s=10 ** 10)[0]["tool"] == "deep_research")
idea = speed_watch.idea_for(summ["slowest"])
check("the speed idea names the step and how it was measured", "Model call" in idea and "median 2.9 s" in idea, idea)
jobs_for_speed = [{"status": "done", "started": clock[0] - 300, "finished": clock[0] - 60}]
check("job durations are a phase too (from the job store)",
      {p["phase"]: p for p in speed_watch.summary(SPD, jobs=jobs_for_speed, now=clock[0])["phases"]}["job"]["p50"] == 240000)
os.environ["LOKI_SPEED_WATCH"] = "off"
check("LOKI_SPEED_WATCH=off records nothing", not speed_watch.record("tools", 5, root=SPD))
os.environ.pop("LOKI_SPEED_WATCH")

# the weekly speed idea goes to evolve
FAKE_REPO = TMP / "repo"
(FAKE_REPO / "docs").mkdir(parents=True)
(FAKE_REPO / "docs" / "EVOLVE.md").write_text("- [x] E1 done\n- [ ] E9 Tools LOKI writes for itself - a folder format\n", encoding="utf-8")
ev = evolve.Evolve(FAKE_REPO, TMP / "evspeed")
for ms in (5000, 6000, 7000):
    speed_watch.record("model_call", ms, root=TMP / "evspeed")
out = speed_watch.propose(ev, TMP / "evspeed")
check("the slowest step becomes an evolve idea marked LOKI's, approved (measured, narrow)",
      out["added"] and out["added"]["source"] == "loki" and out["added"]["kind"] == "speed" and out["added"]["approved"], out)
check("one open speed idea at a time", speed_watch.propose(ev, TMP / "evspeed")["added"] is None)
ev2 = evolve.Evolve(FAKE_REPO, TMP / "evspeed2")
for ms in (5000, 6000, 7000):
    speed_watch.record("model_call", ms, root=TMP / "evspeed2")
out = speed_watch.propose(ev2, TMP / "evspeed2", env={"LOKI_SPEED_IDEAS": "ask"})
check("LOKI_SPEED_IDEAS=ask makes it wait for the owner's OK", out["added"] and out["added"]["approved"] is False)

# the real request loop records its phases
script_loop()
try:
    before = len(speed_watch.entries())
    loki.make_client = fake_model([{"tool": "write_file", "args": {"filename": "speed.txt", "content": "fast\n"}},
                                   {"content": "DONE: wrote speed.txt"}])
    loki.messages[:] = [{"role": "system", "content": "sys"}]
    reply = asyncio.run(loki.pursue_goal("Write speed.txt containing fast"))
    phases = {e["phase"] for e in speed_watch.entries()[before:]}
    check("a real request records triage, model calls, tools, verification and the whole request",
          {"triage", "model_call", "tools", "verification", "request"} <= phases, (reply, phases))
    tool_rows = [e for e in speed_watch.entries()[before:] if e["phase"] == "tools"]
    check("a tool timing names the tool", tool_rows and tool_rows[0]["note"] == "write_file", tool_rows[:1])
finally:
    restore_loop()

# the window's timings and GET /speed
state = FakeState()
code, out = self_api.route(state, "POST", "/ui/timing", {"first_paint_ms": 420, "ready_ms": 1300, "ua": "Mozilla"})
check("POST /ui/timing keeps first paint and ready", code == 200 and out["kept"] == ["first_paint", "ui_ready"], out)
check("nonsense timings are dropped", self_api.route(state, "POST", "/ui/timing", {"first_paint_ms": -1, "ready_ms": "x"})[1]["kept"] == [])
code, out = self_api.route(state, "GET", "/speed", {})
fp = [p for p in out["phases"] if p["phase"] == "first_paint"][0]
check("GET /speed shows them with the request phases", code == 200 and fp["n"] >= 1 and fp["last"] == 420, fp)
boot = (REPO / "app" / "ui" / "boot.js").read_text(encoding="utf-8")
check("boot.js posts first paint + ready once the window is ready", "/ui/timing" in boot and "first-contentful-paint" in boot
      and "LOKI_READY" in boot)
bridge_src = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the bridge times its own start-up", 'speed_watch.record("startup"' in bridge_src and "ENGINE_T0" in bridge_src)

# =========================================================================== jobs dashboard
section("Jobs: success dashboard, failure reasons, forecasts, retry on a stronger model")
JD = TMP / "jobsdata"
(JD / "jobs").mkdir(parents=True)
now = time.time()


def mk(jid, status, title, days_ago=0.0, secs=120.0, model="", log="", result="", error="", team="", exit_code=None):
    t = now - days_ago * 86400
    if log:
        (JD / "jobs" / ("%s.log" % jid)).write_text(log, encoding="utf-8")
    if result:
        (JD / "jobs" / ("%s.result.txt" % jid)).write_text(result, encoding="utf-8")
    return {"id": jid, "status": status, "title": title, "prompt": title, "model": model, "agent": "loki",
            "backend": "local", "started": t - secs, "finished": t, "created": t - secs - 5, "error": error,
            "output": "", "team": team, "exit_code": exit_code}
JOBS = [
    mk("a1", "done", "Make a picture of a fox in the snow", 1, 400, log="[loki-job] a1 | model local | workspace x\n", result="DONE: made images/fox.png"),
    mk("a2", "failed", "Make an image of a cat", 1, 600, log="[loki-job] a2 | model local | workspace x\n  [thinking] The local model is stuck (it kept returning empty replies) - switching this task to groq.\n",
       result="The model returned empty replies repeatedly; task halted.", exit_code=0),
    mk("a3", "failed", "Research the best free image models", 2, 900, error="timed out after 900s"),
    mk("a4", "done", "Build a landing page for the bakery", 3, 1200, log="[loki-job] a4 | model groq | workspace x\n", result="DONE: built it"),
    mk("a5", "failed", "Build a game with a fox", 3, 300, log="[loki-job] a5 | model local | workspace x\n",
       result="BLOCKED: Builder's role unavailable 3f9a2b1c", exit_code=2),
    mk("a6", "done", "Builder: write the tests", 0.5, 200, team="t1", result="DONE: tests written"),
    mk("a7", "done", "Write the summary", 0.2, 50, result="BLOCKED: I need a key"),
    mk("a8", "failed", "Make a video of the island", 40, 100),
]
check("kinds: picture / research / build / team / selftest",
      [job_stats.kind_of(j) for j in JOBS[:6]] == ["picture", "picture", "research", "build", "build", "team"]
      and job_stats.kind_of({"title": "Self-test: write a file"}) == "selftest", [job_stats.kind_of(j) for j in JOBS])
files = job_stats.job_files(JOBS[1], JD)
check("the model a job really ran on comes from its log", job_stats.model_of(JOBS[1], files) == "local"
      and job_stats.model_of(JOBS[3], job_stats.job_files(JOBS[3], JD)) == "groq")
check("an escalation to a stronger model is seen", job_stats.escalated_to(JOBS[1], files) == "groq")
check("a DONE job whose last line is BLOCKED is not a success", not job_stats.succeeded(JOBS[6], job_stats.job_files(JOBS[6], JD)))
reasons = {j["id"]: job_stats.reason_of(j, job_stats.job_files(j, JD)) for j in JOBS}
check("failure reasons are normalised", reasons["a2"] == "the model returned empty replies" and reasons["a3"] == "timed out"
      and reasons["a5"] == "a specialist (role) was unavailable" and reasons["a1"] == "", reasons)
st = job_stats.stats(JOBS, JD, days=30, now=now)
check("overall success over the window (older jobs left out)", st["overall"]["n"] == 7 and st["overall"]["ok"] == 3, st["overall"])
check("success per day, one bar per day", len(st["per_day"]) == 30 and sum(d["n"] for d in st["per_day"]) == 7)
kinds = {k["kind"]: k for k in st["by_kind"]}
check("success by kind", kinds["picture"]["n"] == 2 and kinds["picture"]["ok"] == 1 and kinds["team"]["rate"] == 1.0, kinds)
models = {m["model"]: m for m in st["by_model"]}
check("success by model", models["local"]["n"] == 3 and models["local"]["ok"] == 1 and models["groq"]["ok"] == 1, models)
rs = {r["reason"]: r["n"] for r in st["reasons"]}
check("top failure reasons include the escalation messages", rs.get("escalated from the small model to groq") == 1
      and rs.get("timed out") == 1, rs)
check("recent failures are listed newest first", [f["id"] for f in st["failures"]][:2] == ["a7", "a2"], st["failures"][:2])

queued = {"id": "q1", "status": "queued", "title": "Make a picture of a dog", "prompt": "Make a picture of a dog"}
hist = job_stats.rows(JOBS, JD)
fc = job_stats.outlook(queued, hist)
check("a queued job gets a duration + failure-risk forecast (forecast.py)", fc["minutes"] and 0 < fc["risk"] < 1 and
      fc["backend"] in ("statistical", "median") or fc["backend"].startswith("timesfm"), fc)
check("the forecast line is plain words", fc["line"].startswith("Forecast: ~") and "failure risk" in fc["line"], fc["line"])
status = {"jobs": [{"id": "q1", "status": "queued"}, {"id": "a1", "status": "done"}]}
job_stats.annotate(status, JOBS + [queued], JD)
check("GET /jobs adds the forecast to queued jobs only", "forecast" in status["jobs"][0] and "forecast" not in status["jobs"][1])
app_js = (REPO / "app" / "ui" / "app.js").read_text(encoding="utf-8")
check("the job strip shows it", "job.forecast.line" in app_js)

agent = types.SimpleNamespace(
    DATA_DIR=str(JD), MODELS={"local": 1, "groq": 1, "gemini": 1, "openai": 1}, SMART_ORDER=["local", "groq", "gemini", "openai"],
    routing_order=lambda order: list(order), provider_tier=lambda n: "paid" if n == "openai" else "free",
    paid_allowed_automatically=lambda: False, provider_configured=lambda n: n in ("local", "groq", "gemini", "openai"))
check("stronger model: the first free online one set up, not the one it ran on or escalated to",
      job_stats.stronger_model(agent, JOBS[1], files) == "gemini" and job_stats.stronger_model(agent, JOBS[4]) == "groq")
agent.provider_configured = lambda n: n in ("local", "openai")
check("never a paid model on its own", job_stats.stronger_model(agent, JOBS[4]) == "")
agent.provider_configured = lambda n: n in ("local", "groq", "gemini", "openai")
rstate = FakeState(agent=agent)
for j in JOBS:
    rstate.jobs.store.jobs[j["id"]] = j
made = []


def fake_job_action(state_, route_, spec):
    made.append(spec)
    return 200, {"ok": True, "id": "new%d" % len(made)}
code, out = self_api.route(rstate, "POST", "/jobs/retry_stronger", {"id": "a5"}, fake_job_action)
check("one click: the same prompt as a new job on the stronger model (through job_action)", code == 200 and out["model"] == "groq"
      and made[-1]["model"] == "groq" and made[-1]["prompt"] == JOBS[4]["prompt"] and "allow_commands" not in made[-1], (out, made[-1:]))
check("retry of an unknown job -> 404", self_api.route(rstate, "POST", "/jobs/retry_stronger", {"id": "zz"}, fake_job_action)[0] == 404)
code, out = self_api.route(rstate, "GET", "/jobs/stats?days=7", {})
check("GET /jobs/stats answers the dashboard", code == 200 and out["days"] == 7 and "by_model" in out and "selftest" in out
      and "waiting" in out, out.keys())
check("it is JSON-serialisable", bool(json.dumps(out)))

# =========================================================================== self-test
section("daily self-test: three cheap jobs, checked from their files")
check("auto = on only on the Windows PC", selftest.enabled({}, "win32") and not selftest.enabled({}, "darwin")
      and selftest.enabled({"LOKI_SELFTEST": "on"}, "darwin") and not selftest.enabled({"LOKI_SELFTEST": "off"}, "win32"))
STD = TMP / "stdata"
sclock = [2_000_000_000.0]
stest = selftest.Selftest(STD, clock=lambda: sclock[0])
sjobs = FakeJobs()
line = stest.start(sjobs.create)
check("start queues 3 jobs in their own seeded folders (never the owner's project)", line.startswith("started") and
      len(sjobs.created) == 3 and all(str(STD) in j["workspace"] and j["isolate"] is False for j in sjobs.created)
      and (Path(sjobs.created[1]["workspace"]) / "numbers.txt").is_file(), (line, sjobs.created))
check("one run at a time", stest.start(sjobs.create) == "")
check("not settled while jobs run", stest.settle(sjobs.store.get) is None)
run = stest.open_run()
nums = [int(x) for x in (Path(sjobs.created[1]["workspace"]) / "numbers.txt").read_text().split()]
(Path(sjobs.created[0]["workspace"]) / "selftest_hello.txt").write_text("LOKI self-test OK\n", encoding="utf-8")
(Path(sjobs.created[1]["workspace"]) / "sum.txt").write_text(str(sum(nums)), encoding="utf-8")
(Path(sjobs.created[2]["workspace"]) / "colours.md").write_text("- red\n- green\n", encoding="utf-8")
for j in sjobs.created:
    j.update(status="done", started=sclock[0], finished=sclock[0] + 30)
res = stest.settle(sjobs.store.get)
check("checked from the files, not from what the model said", res and res["rate"] == round(2 / 3, 3)
      and [r["ok"] for r in res["results"]] == [True, True, False] and "missing a colour" in res["results"][2]["why"], res)
sclock[0] += 86400
sjobs2 = FakeJobs()
stest.start(sjobs2.create)
for j in sjobs2.created:
    j.update(status="failed", error="timed out after 900s")
res2 = stest.settle(sjobs2.store.get)
check("a run worse than the last one is a REGRESSION", res2["regression"] and res2["rate"] == 0.0
      and "timed out" in res2["results"][0]["why"], res2)
check("status keeps the history for the Lab", [h["rate"] for h in stest.status()["history"]] == [round(2 / 3, 3), 0.0])

# one self-test task through the REAL background-job runner and goal loop, on a scripted model
script_loop()
try:
    stest3 = selftest.Selftest(TMP / "st3")
    j3 = FakeJobs()
    stest3.start(j3.create)
    job = j3.created[0]
    loki.make_client = fake_model([{"tool": "write_file", "args": {"filename": "selftest_hello.txt", "content": "LOKI self-test OK\n"}},
                                   {"content": "DONE: wrote selftest_hello.txt"}])
    code, result = run_job_inline({"id": job["id"], "prompt": job["prompt"], "allow_commands": False}, Path(job["workspace"]))
    ok, why = selftest.check("write", Path(job["workspace"]), {})
    check("the 'write' self-test passes through loki.run_job when the model does the work", code == 0 and ok and
          result.startswith("DONE"), (code, result, why))
    loki.make_client = fake_model([{"content": "DONE: wrote it"}, {"content": "DONE: wrote it"}, {"content": "DONE: wrote it"},
                                   {"content": "DONE: wrote it"}])
    sub = Path(j3.created[2]["workspace"])
    run_job_inline({"id": j3.created[2]["id"], "prompt": j3.created[2]["prompt"], "allow_commands": False}, sub)
    check("a model that only SAYS it is done fails the check", not selftest.check("list", sub, {})[0])
finally:
    restore_loop()

# the autopilot runs it daily and settles it as soon as the jobs finish
os.environ["LOKI_SELFTEST"] = "on"
APD = TMP / "apdata"
aclock = [3_000_000_000.0]
astate = FakeState()
ap = autopilot.Autopilot(state=astate, agent=types.SimpleNamespace(DATA_DIR=APD), data_dir=APD, repo=FAKE_REPO,
                         clock=lambda: aclock[0])
ap.data["last"].update({"health": aclock[0], "inbox": aclock[0], "report": aclock[0], "selftest": 0})
first = ap.tick()
check("an idle autopilot starts the daily self-test", first and first[0][0] == "selftest" and len(astate.jobs.created) == 3, first)
for j in astate.jobs.created:
    j.update(status="done")
(Path(astate.jobs.created[0]["workspace"]) / "selftest_hello.txt").write_text("LOKI self-test OK", encoding="utf-8")
ap.tick()
log = [e for e in ap.data["log"] if e["duty"] == "selftest"]
check("its result is logged when the jobs finish (1 of 3 here)", log and "1 of 3 jobs worked" in log[-1]["text"], log[-1:])
os.environ.pop("LOKI_SELFTEST")

# =========================================================================== E8
section("E8 self-review: up to 3 proposals, waiting for the owner's OK")
RV = TMP / "review"
(RV / "reports").mkdir(parents=True)
(RV / "reports" / "learned-2026-10-17.md").write_text("# What LOKI learned this week\n- 9 requests, 2 finished\n", encoding="utf-8")
import memory_core  # noqa: E402
memory_core.learn("Reflexion: the job failed because write_file was used for a PNG; use the image role instead.",
                  tier="episodic", tags="reflexion", root=RV, source="reflexion")
rjobs = [dict(j) for j in JOBS[:7]]
(RV / "jobs").mkdir(parents=True)
for name in os.listdir(JD / "jobs"):
    shutil.copy(JD / "jobs" / name, RV / "jobs" / name)
facts = self_review.gather(RV, jobs=rjobs)
check("the review reads the report, lessons and the job dashboard", facts["report"].startswith("# What LOKI learned")
      and facts["lessons"] and facts["jobs"]["overall"]["n"] == 7, {k: facts.get(k) for k in ("lessons", "jobs")})
props = self_review.rule_proposals(facts)
check("rules turn measurements into proposals that name their source", props and "3 of 7 jobs" in props[0]["title"]
      and props[0]["why"] == "job dashboard", props[:1])
rev = evolve.Evolve(FAKE_REPO, RV)
out = self_review.review(rev, RV, jobs=rjobs)
ideas = rev.ideas()
check("at most 3 'LOKI's idea' proposals are added", 1 <= len(out["added"]) <= 3 and len(ideas) == len(out["added"]), out["added"])
check("they wait for the owner's OK (evolve skips them)", all(i["source"] == "loki" and i["approved"] is False and i["kind"] == "review"
                                                               for i in ideas) and (rev.next_item() or {}).get("source") != "loki")
check("the same proposals are not made again next week", self_review.review(rev, RV, jobs=rjobs)["added"] == [])
rev.approve(ideas[0]["id"], True)
check("'Build it' makes it the next step", (rev.next_item() or {}).get("id") == ideas[0]["id"])
RV2 = TMP / "review2"
rev2 = evolve.Evolve(FAKE_REPO, RV2)
out = self_review.review(rev2, RV2, jobs=[], ask=lambda prompt: 'Here: ["Teach the small model to call make_tool for repeated steps (facts: 12 repeated calls).", "Cache the memory pack between turns because triage is slow."]')
check("with a model, its JSON proposals are used (and say they came from the review)", out["source"] == "model" and len(out["added"]) == 2
      and "make_tool" in out["added"][0]["title"], out)
out = self_review.review(evolve.Evolve(FAKE_REPO, TMP / "review3"), RV, jobs=rjobs, ask=lambda prompt: "I have no idea")
check("an unusable model answer falls back to the rules", out["source"] == "rules" and out["added"])
lab = (REPO / "app" / "ui" / "lab.js").read_text(encoding="utf-8")
check("the Lab marks them LOKI's idea with Build it / No", "LOKI's idea" in lab and '"Build it"' in lab and "/self_review/run" in lab)

os.environ["LOKI_EVOLVE"] = "on"
ap2 = autopilot.Autopilot(state=FakeState(), agent=types.SimpleNamespace(DATA_DIR=RV), data_dir=RV, repo=FAKE_REPO,
                          clock=time.time, evolve=evolve.Evolve(FAKE_REPO, RV), improve=lambda task: "error: not now")
ap2.data["last"].update({"health": time.time(), "inbox": time.time(), "report": time.time(), "evolve": time.time()})
ran = ap2.tick()
check("the weekly review is an autopilot duty (where evolve runs)", ran and ran[0][0] == "review", ran)
ran = ap2.tick()
check("so is the weekly speed check", ran and ran[0][0] == "speed", ran)
os.environ.pop("LOKI_EVOLVE")

# =========================================================================== E2E
section("end to end: autopilot -> evolve -> improve_loki -> job -> check_loki -> ship_loki proof")
E2E_REPO = TMP / "e2e_repo"
(E2E_REPO / "docs").mkdir(parents=True)
ROAD = "- [x] E1 Memory\n- [ ] E9 Tools LOKI writes for itself - tool.json + tool.py\n- [ ] E10 Phone channel\n"
(E2E_REPO / "docs" / "EVOLVE.md").write_text(ROAD, encoding="utf-8")
eclock = [4_000_000_000.0]
eev = evolve.Evolve(E2E_REPO, DATA, clock=lambda: eclock[0])
estate = FakeState(agent=loki)
saved_jobs = loki.JOBS
loki.JOBS = estate.jobs
os.environ["LOKI_EVOLVE"] = "on"
eap = autopilot.Autopilot(state=estate, agent=loki, data_dir=DATA, repo=E2E_REPO, clock=lambda: eclock[0],
                          evolve=eev, improve=loki.improve_loki)


def evolve_tick():
    eap.data["last"].update({"health": eclock[0], "inbox": eclock[0], "report": eclock[0], "review": eclock[0],
                             "speed": eclock[0], "selftest": eclock[0], "task_bench": eclock[0], "evolve": 0})
    return eap.tick()
runs = []
shipped_with_tick = []
WT = TMP / "harness" / "worktrees" / "e2e"


def fake_run(argv, **kw):
    if not any(str(a).endswith("ship.py") for a in argv):
        return saved_run(argv, **kw)          # anything that is not tools/ship.py: the real thing
    runs.append(argv)
    if "--check" in argv:
        return types.SimpleNamespace(returncode=0, stdout="  test_self_systems   99 passed, 0 failed\nALL PASSED", stderr="")
    shipped_with_tick.append("- [x] E9" in (WT / "docs" / "EVOLVE.md").read_text(encoding="utf-8"))
    return types.SimpleNamespace(returncode=0, stdout="1. tests ok\n  pushed 1a2b3c4 to master\nShipped 1a2b3c4.", stderr="")
saved_run = loki.subprocess.run
try:
    first = evolve_tick()
    job = estate.jobs.created[0] if estate.jobs.created else {}
    check("the idle autopilot hands the next roadmap step to the REAL improve_loki", first and first[0][0] == "evolve"
          and job.get("title", "").startswith("Improve LOKI") and "E9" in job.get("prompt", "") and eev.busy(), (first, job.get("title")))
    check("the job is a LOKI agent with commands allowed (it must test and ship)", job.get("agent") == "loki"
          and job.get("allow_commands") is True and job.get("model") in ("smart", "online"), job)
    # the job runs: a worktree of LOKI with the roadmap, the real goal loop, a scripted model
    (WT / "engine").mkdir(parents=True)
    (WT / "engine" / "loki.py").write_text("# loki\n", encoding="utf-8")
    (WT / ".git").write_text("gitdir: x\n", encoding="utf-8")
    (WT / "tools").mkdir()
    (WT / "tools" / "ship.py").write_text("# ship\n", encoding="utf-8")
    (WT / "docs").mkdir()
    (WT / "docs" / "EVOLVE.md").write_text(ROAD, encoding="utf-8")
    script_loop()
    loki.subprocess.run = fake_run
    job.update(status="working", started=time.time())
    loki.make_client = fake_model([
        {"tool": "task_tracker", "args": {"command": "plan", "task_list": [{"title": "build E9"}, {"title": "tick, test, ship"}]}},
        {"tool": "read_file", "args": {"filename": "docs/EVOLVE.md"}},
        {"tool": "edit_file", "args": {"filename": "docs/EVOLVE.md", "old": "- [ ] E9 Tools", "new": "- [x] E9 Tools"}},
        {"tool": "check_loki", "args": {}},
        {"tool": "ship_loki", "args": {"message": "E9 tools LOKI writes for itself; all suites pass"}},
        {"content": "DONE: shipped E9 - every suite passed"}])
    code, result = run_job_inline({"id": job["id"], "prompt": job["prompt"], "allow_commands": True, "model": job["model"]}, WT)
    restore_loop()
    loki.subprocess.run = saved_run
    check("the improve job ran check_loki then ship_loki (the worktree's own ship.py)",
          any("--check" in r for r in runs) and any("-m" in r for r in runs) and all(str(WT / "tools" / "ship.py") in r for r in runs), runs)
    check("it ticked the roadmap line in the same change it shipped", shipped_with_tick == [True]
          and "- [x] E9" in (WT / "docs" / "EVOLVE.md").read_text(encoding="utf-8"))
    check("ship_loki left its proof for evolve", loki.ship_marker(job["id"]).is_file())
    check("the job ended DONE", code == 0 and result.startswith("DONE: shipped"), (code, result))
    job.update(status="done", finished=time.time())
    eclock[0] += 600
    evolve_tick()
    e9 = [a for a in eev.state()["attempts"] if a["id"] == "E9"]
    check("the next autopilot pass settles it as SHIPPED (proof, not just 'done')", e9 and e9[-1]["outcome"] == "shipped"
          and "shipped E9" in e9[-1]["detail"], e9)
    check("a shipped step is not built again; the next pass moved on to E10",
          len(estate.jobs.created) == 2 and "by one step: E10 " in estate.jobs.created[1]["prompt"],
          [j["title"] for j in estate.jobs.created])
    check("the outcome is in LOKI's memory for later attempts",
          "E9" in memory_core.recall("self-improvement step E9 tools", root=DATA, include_skills=False)["evidence"])
    dash = job_stats.stats(estate.jobs.store.all(), DATA)
    check("the dashboard counts the improve job as a successful build job",
          any(k["kind"] == "build" and k["ok"] >= 1 for k in dash["by_kind"]), dash["by_kind"])
finally:
    loki.subprocess.run = saved_run
    loki.JOBS = saved_jobs
    os.environ.pop("LOKI_EVOLVE", None)

# =========================================================================== bridge + UI
section("the bridge over HTTP, the Lab UI, docs")
import loki_bridge  # noqa: E402
loki_bridge.PORT = 0
bagent = types.SimpleNamespace(DATA_DIR=str(JD), USER_TOOLS=None)
bstate = loki_bridge.BridgeState(bagent, "self-secret")
bstate.jobs = FakeJobs()
for j in JOBS + [queued]:
    bstate.jobs.store.jobs[j["id"]] = dict(j)
bserver = loki_bridge.BridgeHTTPServer(bstate)
threading.Thread(target=bserver.serve_forever, daemon=True).start()


def http_call(method, path, body=None, token="self-secret"):
    conn = http.client.HTTPConnection("127.0.0.1", bserver.server_address[1], timeout=20)
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read() or b"{}")
try:
    code, out = http_call("GET", "/jobs/stats")
    check("GET /jobs/stats over HTTP", code == 200 and out["overall"]["n"] == 7, (code, str(out)[:200]))
    code, out = http_call("GET", "/jobs")
    q = [j for j in out.get("jobs", []) if j["id"] == "q1"]
    check("GET /jobs over HTTP carries the queued job's forecast", code == 200 and q and "forecast" in q[0], q)
    code, out = http_call("POST", "/ui/timing", {"first_paint_ms": 300, "ready_ms": 900})
    check("POST /ui/timing over HTTP", code == 200 and out["kept"] == ["first_paint", "ui_ready"], out)
    code, out = http_call("GET", "/speed")
    check("GET /speed over HTTP", code == 200 and any(p["phase"] == "first_paint" and p["n"] for p in out["phases"]), out.get("phases", [])[:2])
    check("a wrong token is refused", http_call("GET", "/speed", token="nope")[0] == 401)
    code, out = http_call("GET", "/user_tools")
    check("GET /user_tools over HTTP", code == 200 and out["ok"], out)
finally:
    bserver.shutdown()
    bserver.server_close()

index = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
css = (REPO / "app" / "ui" / "glass.css").read_text(encoding="utf-8")
check("Settings > Tools has the list of LOKI's own tools", 'id="user-tools"' in index and "loadUserTools" in lab
      and "loadUserTools" in app_js and "/user_tools/toggle" in lab and "/user_tools/delete" in lab and "/user_tools/check" in lab)
check("Settings > Lab draws the speed watch (sparklines) and the jobs view", all(w in lab for w in (
    "renderSpeed", "sparkline", "renderJobsView", "dayBars", "/jobs/retry_stronger", "Retry on a stronger model",
    "/selftest/start", "/speed", "/jobs/stats")))
check("no CDN or remote script in the Lab", "http://" not in lab.replace("http://www.w3.org/2000/svg", "") and "https://" not in lab)
check("the new views have their styles", all(c in css for c in (".lab-card", ".daybars", ".spark", ".meter", ".lab-table")))
ship_src = (REPO / "tools" / "ship.py").read_text(encoding="utf-8")
check("ship.py runs this suite", '"test_self_systems"' in ship_src)
road = (REPO / "docs" / "EVOLVE.md").read_text(encoding="utf-8")
check("roadmap E6, E8 and E9 are ticked", all("- [x] %s " % e in road for e in ("E6", "E8", "E9")))

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
