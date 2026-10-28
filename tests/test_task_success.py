"""Do LOKI's agents finish real tasks? (session 28) - offline, scripted fake models only.

Runs the task-success benchmark (tools/task_bench.py, tasks in tests/tasks/) with scripted
fakes that reproduce what small models did in the PC's job logs - empty and <think>-only
replies, ```json and code-style tool calls, wrong tool and argument names, DONE before doing
anything or in the last line of a long reply, BLOCKED guesses, questions nobody can answer,
huge replies and tool results, a call cut off mid-way, a stuck repeated call, a job that never
ends, a team whose tester finds a bug - each through the REAL loki.run_job in its own
workspace, and checks the real result. Every task must be finished (or honestly BLOCKED), and
a model that never does the work must never be scored as a success. Plus the goal-loop
helpers, the nightly autopilot duty, GET /bench and the Settings > Lab section.

    python tests/test_task_success.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "tools"))
TMP = Path(tempfile.mkdtemp(prefix="loki-tasksuccess-"))
WS = TMP / "ws"
WS.mkdir(parents=True, exist_ok=True)
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_LOCAL_AGENT"] = "off"      # this bench measures LOKI's own tool loop (a local model's shell agent has its own suite)
os.environ["LOKI_WORKSPACE"] = str(WS)
for _k in ("LOKI_JOB_ID", "LOKI_TEAM_ID", "LOKI_NO_ESCALATE", "LOKI_TASK_BENCH"):
    os.environ.pop(_k, None)

import autopilot  # noqa: E402
import loki  # noqa: E402
import task_bench  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def section(title):
    print("\n" + title)


# =========================================================================== the benchmark
section("every realistic task is finished through the real job loop, despite small-model behaviours")
OUT = TMP / "bench"
started = time.monotonic()
result = task_bench.run_bench(["local"], scripted=True, scenario="small", out=OUT, say=lambda *_a: None)
run = result["runs"]["scripted-small"]
tasks = task_bench._tasks_module().TASKS
check("the catalog has about 30 tasks across every kind", len(tasks) >= 30 and {t.kind for t in tasks} >= {
    "doc", "code", "research", "picture", "summary", "plan", "build", "team", "assume", "blocked"}, len(tasks))
for row in run["tasks"]:
    check("%s (%s): %s" % (row["id"], row["behaviour"] or row["kind"], row["status"]), row["ok"],
          "%s | final: %s | log: %s" % (row["reason"], row["final"][:160], row["log"]))
check("all %d tasks finished (%.0fs)" % (run["total"], time.monotonic() - started), run["passed"] == run["total"],
      "%d/%d" % (run["passed"], run["total"]))
by = {r["id"]: r for r in run["tasks"]}
check("a stuck small model was handed to a stronger model (research-frameworks)",
      by.get("research-frameworks", {}).get("escalated") == task_bench.STRONG, by.get("research-frameworks"))
check("the team found the bug, fixed it in the fix round and re-checked (team-primes)",
      [m["role"] for m in ((by.get("team-primes") or {}).get("team") or {}).get("members", [])][-3:]
      == ["builder#fix", "tester#recheck", "reviewer#recheck"], by.get("team-primes"))
check("a job that never ends stops at its deadline and keeps the partial work (timeout-partial)",
      by.get("timeout-partial", {}).get("status") == "blocked" and "chapter1.md" in by["timeout-partial"]["final"],
      by.get("timeout-partial"))
check("a 120,000-character reply did not fill the model's context (code-wordcount)",
      0 < by.get("code-wordcount", {}).get("max_prompt_chars", 0) <= 60000, by.get("code-wordcount"))
check("steps, time and tokens are recorded per task", all(r["steps"] > 0 and r["seconds"] > 0 for r in run["tasks"])
      and sum(r["tokens"] for r in run["tasks"]) > 0)

section("a model that never does the work is never scored as a success")
cheat = task_bench.run_bench(["local"], scripted=True, scenario="cheat", out=TMP / "cheat", say=lambda *_a: None)
crun = cheat["runs"]["scripted-cheat"]
check("cheat scripts exist for several kinds", crun["total"] >= 4, crun["total"])
for row in crun["tasks"]:
    check("cheat %s fails: %s" % (row["id"], row["reason"][:90]), not row["ok"], row)
check("a cheating picture job ends BLOCKED, not DONE (a .txt is not a picture)",
      {r["id"]: r["status"] for r in crun["tasks"]}.get("pic-fox") == "blocked", crun["tasks"])

section("the report: harness_data/bench/<date>.json, latest.json and a markdown table")
saved = json.loads((OUT / ("%s.json" % result["date"])).read_text(encoding="utf-8"))
check("the dated report and latest.json are written", (OUT / "latest.json").is_file() and "scripted-small" in saved["runs"])
md = (OUT / ("%s.md" % result["date"])).read_text(encoding="utf-8")
check("the markdown table has a summary row and a row per task",
      "| scripted-small | %d/%d |" % (run["passed"], run["total"]) in md and md.count("| PASS |") == run["total"], md[:300])
task_bench.save({"other-model": dict(run, model="other")}, OUT, result["date"])
check("a second model run the same day is added, not overwritten",
      set(json.loads((OUT / "latest.json").read_text(encoding="utf-8"))["runs"]) >= {"scripted-small", "other-model"})
lat = task_bench.latest(OUT)
check("latest() gives Settings > Lab the score per model", lat["ok"] and {r["model"] for r in lat["runs"]} >= {
    "scripted-small", "other-model"} and all("passed" in r and "failed" in r for r in lat["runs"]), lat)
check("latest() with no report is empty, not an error", task_bench.latest(TMP / "nothing") == {"ok": True, "date": "", "runs": []})
check("the outcome line is found anywhere in a reply", task_bench.outcome_line("I did it.\n\n**DONE:** wrote a", "DONE")
      == "**DONE:** wrote a" and task_bench.outcome_line("nothing", "DONE") == "")

# =========================================================================== the loop's helpers
section("goal-loop helpers (engine/loki.py)")
check("DONE on the first line, in any case, as before", loki.reply_outcome("Done: it") == "done")
check("DONE in the last line of a long reply counts", loki.reply_outcome("I wrote the file.\n\nDONE: wrote a.md") == "done")
check("**BLOCKED:** in markdown counts", loki.reply_outcome("Tried.\n**BLOCKED:** need a key") == "blocked")
check("a sentence that only mentions done does not", loki.reply_outcome("When it is DONE I will say so.") == "")
check("the job's status uses it too", loki._status_of_reply("ok\nDONE: x") == "done")
(WS / "report.txt").write_text("r", encoding="utf-8")
check("a file the goal asks for is an output; an existing one is an input",
      loki._goal_outputs("Summarize report.txt in 5 bullets into summary.md.") == ["summary.md"])
check("a file the goal only mentions is not an output (read AGENTS.md first)",
      loki._goal_outputs("Read AGENTS.md first and follow it.") == [])
check("a domain is not a file", loki._goal_outputs("Buy the domain danas-bakery.com and save it as a note") == [])
check("save it as / write ... to", loki._goal_outputs("save it as docs/plan.md, then write the total to total.txt")
      == ["docs/plan.md", "total.txt"])
check("a picture request wants a real picture", loki._goal_wants_picture("Make a picture of a red fox")
      and not loki._goal_wants_picture("fix resize_image in image.py") and not loki._goal_wants_picture("write a poem"))
clipped = loki._clip_reply("x" * 100000)
check("a huge reply is kept short in the history", len(clipped) < 30000 and "left out" in clipped)
check("a normal reply is untouched", loki._clip_reply("DONE: ok") == "DONE: ok")
saved_role = loki.JOB_ROLE
loki.JOB_ROLE = "tester"
check("a tester's DONE is a report (it writes nothing)", loki._role_writes() is False)
loki.JOB_ROLE = "builder"
check("a builder writes", loki._role_writes() is True)
loki.JOB_ROLE = saved_role
fix = loki._guard_call("image", json.dumps({"prompt": "a fox"}))
check("a native call to the role name 'image' becomes conductor(role='image') (the guard used to reject it)",
      fix.ok and fix.name == "conductor" and fix.args.get("role") == "image" and fix.args.get("task") == "a fox",
      (fix.name, fix.args, fix.error))
fix = loki._guard_call("generate_image", json.dumps({"description": "a cat"}))
check("generate_image too", fix.ok and fix.name == "conductor" and fix.args.get("task") == "a cat", fix.args)
check("an unknown name is still refused with a hint", not loki._guard_call("google_search", "{}").ok)
(WS / "bad.py").write_text("def f(:\n    pass\n", encoding="utf-8")
(WS / "good.py").write_text("def f():\n    return 1\n", encoding="utf-8")
(WS / "app.js").write_text("function f() {\n  return 1;\n", encoding="utf-8")
rep = loki.verify_files(["bad.py", "good.py", "app.js"])
check("verification compiles Python: a syntax error fails DONE (it was 'no automatic check')",
      [p for p, _ in rep["failed"]] == ["bad.py", "app.js"] and rep["ok"] == ["good.py"], rep)
loki._task_files[:] = ["out/a.md"]
check("the partial-work note names what was saved", "out/a.md" in loki._partial_note())
loki._task_files.clear()
check("...and says so when nothing was", "Nothing was saved" in loki._partial_note())
loki.JOB_DEADLINE_AT = time.monotonic() - 1
try:
    loki._check_job_deadline()
    check("a job past its deadline stops", False)
except loki.BudgetExhausted as exc:
    check("a job past its deadline stops with BudgetExhausted", "time limit" in str(exc))
loki.JOB_DEADLINE_AT = 0.0
src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("halted jobs end BLOCKED (they exited 0 and looked finished - a team counted a halted tester as a PASS)",
      '"BLOCKED: the model returned empty replies repeatedly' in src
      and '"BLOCKED: the model stopped calling tools after several nudges' in src)
check("a job allowed to run commands is OFFERED run_command (it was never offered to any model)",
      'MODEL_TOOL_NAMES.update({"run_command", "bash"})' in src and 'CATEGORIES["system"] = True' in src)
check("team agents on a local model reach their board", 'name in ("team_read", "team_post") and os.getenv("LOKI_TEAM_ID")' in src)
check("workers hand every job its deadline", '"deadline_s": max(60,' in (REPO / "engine" / "workers.py").read_text(encoding="utf-8"))

section("run_job writes a BLOCKED result with the partial work when it is stopped from outside")
job = TMP / "j.json"
res = TMP / "j.result.txt"
job.write_text(json.dumps({"id": "t-stop", "prompt": "write notes.md", "result_path": str(res), "model": "local"}),
               encoding="utf-8")
saved_pursue = loki.pursue_goal


async def _stopped(goal):
    loki._task_files[:] = ["notes.md"]
    raise loki.BudgetExhausted("hit the job's time limit (deadline)")
loki.pursue_goal = _stopped
try:
    code = asyncio.run(loki.run_job(str(job)))
finally:
    loki.pursue_goal = saved_pursue
text = res.read_text(encoding="utf-8") if res.is_file() else ""
check("exit 4, and the result file says BLOCKED, why, and what was kept",
      code == 4 and text.startswith("BLOCKED: hit the job's time limit") and "notes.md" in text, (code, text))
loki._task_files.clear()

# =========================================================================== nightly on the PC
section("the nightly benchmark is OFF unless asked for (owner 2026-10-25: its test bakery showed up as work)")
saved_platform = sys.platform
try:
    os.environ.pop("LOKI_TASK_BENCH", None)
    sys.platform = "win32"
    check("no setting: off on the Windows PC", not autopilot.task_bench_enabled())
    sys.platform = "darwin"
    check("...and off on the Mac", not autopilot.task_bench_enabled())
    os.environ["LOKI_TASK_BENCH"] = "auto"
    check("'auto' (the old default) is off too", not autopilot.task_bench_enabled())
    os.environ["LOKI_TASK_BENCH"] = "on"
    check("on: on anywhere", autopilot.task_bench_enabled())
finally:
    sys.platform = saved_platform
night = time.mktime((2026, 10, 18, 2, 30, 0, 0, 0, -1))
day = time.mktime((2026, 10, 18, 14, 0, 0, 0, 0, -1))
check("the nightly window is 1-6 local time", autopilot.in_hours("1-6", night) and not autopilot.in_hours("1-6", day))
check("a window past midnight wraps", autopilot.in_hours("22-5", night) and not autopilot.in_hours("22-5", day))


class FakeProc:
    def __init__(self):
        self.done = False

    def poll(self):
        return 0 if self.done else None


started_runs = []


def fake_start(models):
    proc = FakeProc()
    started_runs.append((models, proc))
    return proc


clock = {"t": night}
for name in ("LOKI_AUTOPILOT_HEALTH_S", "LOKI_AUTOPILOT_REPORT_S"):
    os.environ[name] = "999999999"
os.environ["LOKI_AUTOPILOT_INBOX"] = "off"
os.environ["LOKI_SELFTEST"] = "0"   # the PC self-test duty would fire on this fake clock
os.environ["LOKI_UPSTREAM"] = "off"   # the daily upstream check (engine/agentsys/upstream.py) has its own suite
ap = autopilot.Autopilot(state=None, agent=None, data_dir=TMP / "ap", clock=lambda: clock["t"], bench_start=fake_start)
ap.data["last"].update({"health": night, "report": night})
out = ap.tick()
check("at night, idle: the benchmark starts on local and smart", out == [("task_bench", "started task bench: local,smart")]
      and started_runs and started_runs[0][0] == "local,smart", (out, started_runs))
check("while it runs LOKI is not idle (nothing else starts on the GPU)", ap.idle() == (False, "the task benchmark is running"))
clock["t"] = night + 600
check("it is not started twice", ap.tick() == [] and len(started_runs) == 1)
started_runs[0][1].done = True
clock["t"] = night + 3600
check("once a night: not again an hour later", ap.tick() == [] and len(started_runs) == 1)
clock["t"] = day + 86400
check("not in the daytime", ap.tick() == [] and len(started_runs) == 1)
clock["t"] = night + 86400
check("the next night it runs again", ap.tick() and len(started_runs) == 2)
os.environ["LOKI_TASK_BENCH"] = "off"
clock["t"] = night + 3 * 86400
check("LOKI_TASK_BENCH=off: never", ap.tick() == [] and len(started_runs) == 2)
os.environ.pop("LOKI_TASK_BENCH", None)

# =========================================================================== Settings > Lab
section("GET /bench and the Lab section")
import loki_bridge  # noqa: E402
(TMP / "data" / "bench").mkdir(parents=True, exist_ok=True)
(TMP / "data" / "bench" / "latest.json").write_text((OUT / "latest.json").read_text(encoding="utf-8"), encoding="utf-8")
state = types.SimpleNamespace(agent=types.SimpleNamespace(DATA_DIR=str(TMP / "data")),
                              autopilot=types.SimpleNamespace(bench_running=lambda: True))
got = loki_bridge.bench_latest(state)
check("GET /bench: the latest scores, whether it is running, whether nightly runs are on",
      got.get("ok") and got.get("running") is True and "enabled" in got and got.get("runs"), got)
bridge_src = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the route is wired", 'if route == "/bench":' in bridge_src)
html = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
js = (REPO / "app" / "ui" / "bench.js").read_text(encoding="utf-8")
app_js = (REPO / "app" / "ui" / "app.js").read_text(encoding="utf-8")
check("index.html loads bench.js and has the bench panel in the Lab", '/ui/bench.js' in html and 'id="bench-panel"' in html)
check("opening the Lab loads it", 'typeof loadBench === "function") loadBench()' in app_js)
check("bench.js reads /bench and shows a table, with the failures", 'api("/bench")' in js and "bench-row" in js
      and "did not finish" in js and "innerHTML" not in js)
ship_src = (REPO / "tools" / "ship.py").read_text(encoding="utf-8")
check("this suite runs on every ship (tools/ship.py SUITES)", '"test_task_success"' in ship_src)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + "; ".join(FAIL[:10]))
sys.exit(1 if FAIL else 0)
