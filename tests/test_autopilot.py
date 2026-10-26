"""Autopilot: LOKI works on its own when idle - health fixes, the [loki] inbox, the weekly
report - and never while the owner is active.

    python tests/test_autopilot.py

Everything the autopilot touches is injected, so this runs with no engine, no model and no
network: a fake clock, a fake system check, a fake team starter, a fake state.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]

import autopilot  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name: str, ok: bool, detail: object = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def section(title: str) -> None:
    print("\n" + title)


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def tick(self, seconds):
        self.t += seconds


class FakeJobs:
    def __init__(self, jobs=None):
        self.store = types.SimpleNamespace(all=lambda: list(jobs or []))


class FakeState:
    def __init__(self, busy=False, jobs=None, last_request_at=0.0):
        self._busy = busy
        self.jobs = FakeJobs(jobs)
        self.last_request_at = last_request_at

    def try_busy(self):
        return None if self._busy else ["lock"]

    @staticmethod
    def release_busy(held):
        pass


def make(tmp, **kw):
    clock = kw.pop("clock", Clock())
    auto = autopilot.Autopilot(data_dir=tmp, repo=REPO, clock=clock,
                               agent=kw.pop("agent", None), state=kw.pop("state", FakeState()),
                               run_check=kw.pop("run_check", None), apply_fix=kw.pop("apply_fix", None),
                               start_team=kw.pop("start_team", None))
    return auto, clock


import os  # noqa: E402

os.environ["LOKI_AUTOPILOT"] = "on"
os.environ["LOKI_FORGE_QA"] = "off"          # the real Forge QA sweep is not run here (tests/test_forge_qa_duty.py fakes it)

# ---------------------------------------------------------------------------- idle gate
section("acts only when LOKI is idle")
TMP = Path(tempfile.mkdtemp(prefix="loki-auto-"))
auto, clock = make(TMP, state=FakeState(busy=True))
check("not idle while a request is in flight", auto.idle()[0] is False)

auto, clock = make(TMP / "b", state=FakeState(jobs=[{"status": "working"}]))
check("not idle while a background job runs", auto.idle()[0] is False)

os.environ["LOKI_AUTOPILOT_IDLE_S"] = "600"
auto, clock = make(TMP / "c", state=FakeState(last_request_at=clock() - 60))
check("not idle 60s after the owner asked something", auto.idle()[0] is False)
auto, clock = make(TMP / "d", clock=Clock(), state=FakeState(last_request_at=0))
check("idle when nothing is happening", auto.idle()[0] is True, auto.idle())

# ---------------------------------------------------------------------------- health
section("health: applies only the always-safe fixes")
applied: list = []


def run_check():
    return {"results": [
        {"id": "models", "title": "Models", "status": "fail",
         "fix": {"action": "revive_providers", "args": {}}},
        {"id": "addons", "title": "Add-ons", "status": "fail",
         "fix": {"action": "approve_addon", "args": {"id": "x"}}},  # NOT a safe action
        {"id": "disk", "title": "Disk", "status": "ok"}],
        "summary": {"line": "2 of 3 systems work together."}}


def apply_fix(action, args):
    applied.append(action)
    return {"ok": True}


auto, clock = make(TMP / "h", clock=Clock(), state=FakeState(), run_check=run_check, apply_fix=apply_fix)
line = auto.duty_health()
check("the safe fix was applied", applied == ["revive_providers"], applied)
check("the unsafe fix was left for the owner", "approve_addon" not in applied)
check("the health line names what still needs the owner", "Add-ons" in line, line)
check("the run was logged", auto.data["log"] and auto.data["log"][-1]["duty"] == "health")

# ---------------------------------------------------------------------------- inbox
section("inbox: starts the oldest [loki] request once")
started: list = []
TASKS = TMP / "repo"
(TASKS).mkdir(parents=True, exist_ok=True)
(TASKS / "LOKI_TASKS.md").write_text(
    "## Requests\n\n"
    "- [ ] [loki] build a landing page and test it - owner (2026-10-15)\n"
    "- [x] [loki] done already - owner\n"
    "- [ ] [mac] not for LOKI\n"
    "- [ ] [loki] second job\n\n"
    "## Reports\n", encoding="utf-8")


def start_team(text):
    started.append(text)
    return "started team T%d (Researcher, Builder) on /ws" % len(started)


reqs = autopilot.inbox_requests(TASKS / "LOKI_TASKS.md")
check("only open [loki] requests are read, in order", [r["text"][:10] for r in reqs]
      == ["build a la", "second job"], reqs)

# a team that is still "working" holds the slot
auto = autopilot.Autopilot(data_dir=TMP / "i", repo=TASKS, clock=Clock(), state=FakeState(),
                           agent=types.SimpleNamespace(TEAMS=types.SimpleNamespace(get=lambda _id: {"status": "working"})),
                           start_team=start_team)
auto.duty_inbox()
check("the oldest request was started", started == ["build a landing page and test it - owner (2026-10-15)"], started)
auto.duty_inbox()
check("it is not started again while its team is working", len(started) == 1, started)

# a finished team frees the slot for the next request
auto.agent = types.SimpleNamespace(TEAMS=types.SimpleNamespace(get=lambda _id: {"status": "done"}))
auto.duty_inbox()
check("once the team finishes, the next request starts", len(started) == 2 and "second job" in started[1], started)

# ---------------------------------------------------------------------------- one duty per pass
section("one duty per pass, each on its own schedule")
# The PC-only duties (selftest, task_bench; auto = on for the PC) would run here and, once
# the bench starts, make the autopilot busy - this test is about the base duty rotation,
# so turn them off for it (they have their own suites).
_saved_env = {k: os.environ.get(k) for k in ("LOKI_SELFTEST", "LOKI_TASK_BENCH", "LOKI_AUTOPILOT_ALWAYS")}
os.environ["LOKI_SELFTEST"] = os.environ["LOKI_TASK_BENCH"] = os.environ["LOKI_AUTOPILOT_ALWAYS"] = "0"
clock = Clock()
calls: list = []
auto = autopilot.Autopilot(data_dir=TMP / "t", repo=TASKS, clock=clock, state=FakeState(),
                           agent=types.SimpleNamespace(TEAMS=None),
                           run_check=lambda: (calls.append("check") or {"results": [], "summary": {"line": "ok"}}),
                           apply_fix=lambda *a: {"ok": True},
                           start_team=lambda t: (calls.append("team") or "started team T1"))
ran = auto.tick()
check("the first pass runs exactly one duty", len(ran) == 1, ran)
drained = [auto.tick() for _ in range(5)]
done_duties = [r[0][0] for r in [ran] + drained if r]
check("across passes each duty runs once, then nothing", sorted(done_duties) == ["health", "inbox", "report"]
      and drained[-1] == [], (done_duties, drained[-1]))
for _k, _v in _saved_env.items():
    os.environ[_k] = _v if _v is not None else ""
    os.environ.pop(_k, None) if _v is None else None

# ---------------------------------------------------------------------------- report
section("weekly report: only measured facts")


class FakeExp:
    @staticmethod
    def entries(last=0):
        return [{"t": 1_000_000.0, "status": "done", "outcome": "verified", "provider": "local"},
                {"t": 1_000_000.0, "status": "done", "outcome": "failed", "provider": "gemini"}]

    @staticmethod
    def role_stats():
        return {"builder": {"local": {"requests": 8, "success_rate": 0.75}},
                "reviewer": {"gemini": {"requests": 6, "success_rate": 0.5}}}

    @staticmethod
    def new_examples():
        return 12

    @staticmethod
    def train_state():
        return {"history": [{"t": 1_000_000.0, "result": "trained; candidate registered"}]}


agent = types.SimpleNamespace(SMART_ORDER=("local", "gemini"),
                              routing_order=lambda o: ["gemini", "local"],
                              GUARD_STATS={"repaired": 3, "rejected": 1})
text, order = autopilot.learned_report(FakeExp, agent, ["local", "gemini"], 1_000_000.0)
check("report counts verified work", "1 with every changed file verified" in text, text[:300])
check("report names the best model per role", "builder: local" in text, text)
check("report notes the routing change", "Measured results changed" in text, text)
check("report counts tool-call repairs", "repaired 3" in text, text)
check("report states new training examples", "12 new verified example" in text, text)


# ------------------------------------------------------------------ standing goals keep the agents busy
_tasks = TASKS / "LOKI_TASKS.md"
_tasks.write_text("# x\n\n## Requests\n\n## Always\n\n- [loki] make promo art\n- [loki] write a devlog draft\n"
                  "- [loki] [%s] a job for another machine\n" % ("mac" if sys.platform == "win32" else "windows"))
check("standing goals are read from ## Always, other machines' left out",
      autopilot.always_goals(_tasks) == ["make promo art", "write a devlog draft"], autopilot.always_goals(_tasks))
_started = []
_ap = autopilot.Autopilot(data_dir=TMP / "always", repo=TASKS, clock=lambda: 1000.0,
                          start_team=lambda g: (_started.append(g), "started team T%d" % len(_started))[1])
_ap._team_running = lambda tid: False  # pylint: disable=protected-access
_ap.duty_always()
_ap.duty_always()
_ap.duty_always()
check("one standing goal per pass, in turn, round and round", [g.split(" (standing")[0] for g in _started]
      == ["make promo art", "write a devlog draft", "make promo art"], _started)
check("each is marked drafts-only (never publish)", all("never publish" in g for g in _started))
_ap._team_running = lambda tid: True  # pylint: disable=protected-access
check("not while one of them is still running", _ap.duty_always() == "" and len(_started) == 3)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
