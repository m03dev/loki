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
os.environ["LOKI_AUTOPILOT_STORAGE"] = "off"   # storage has its own suite (tests/test_storage.py)
os.environ["LOKI_AUTOPILOT_ALWAYS"] = "on"   # standing goals are off by default since 2026-10-27; this suite tests them
os.environ["LOKI_MACHINE_ROLE"] = "main"     # the slot tests are about the PC's 3 slots; the light default is checked below
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
os.environ["LOKI_AUTOPILOT_SLOTS"] = "1"
auto.duty_inbox()
check("one slot: the oldest request was started", started == ["build a landing page and test it - owner (2026-10-15)"], started)
auto.duty_inbox()
check("it is not started again while its team is working", len(started) == 1, started)

# a finished team frees the slot for the next request
auto.agent = types.SimpleNamespace(TEAMS=types.SimpleNamespace(get=lambda _id: {"status": "done"}))
auto.duty_inbox()
check("once the team finishes, the next request starts", len(started) == 2 and "second job" in started[1], started)

section("slots: several at once, the GPU one at a time")
os.environ["LOKI_AUTOPILOT_SLOTS"] = "3"
started.clear()
(TASKS / "LOKI_TASKS.md").write_text(
    "## Requests\n\n- [ ] [loki] write the devlog draft\n- [ ] [loki] render the dragon turntable\n"
    "- [ ] [loki] make a music loop for the menu\n- [ ] [loki] pixel art check on three pictures\n"
    "- [ ] [loki] research five ad ideas\n", encoding="utf-8")
auto = autopilot.Autopilot(data_dir=TMP / "slots", repo=TASKS, clock=Clock(), state=FakeState(),
                           agent=types.SimpleNamespace(TEAMS=types.SimpleNamespace(get=lambda _id: {"status": "working"})),
                           start_team=start_team)
auto.duty_inbox()
check("one pass fills the free slots, the GPU lane once (the music waits behind the render)",
      [t.split()[0] + " " + t.split()[1] for t in started] == ["write the", "render the", "pixel art"], started)
auto.duty_inbox()
check("full slots: nothing more starts", len(started) == 3, started)
check("lanes: renders, music and 3D need the GPU; writing and pixel art do not",
      autopilot.lane("render the dragon") == "gpu" and autopilot.lane("make a music loop") == "gpu"
      and autopilot.lane("make_3d a prop") == "gpu" and autopilot.lane("write a devlog") == "light"
      and autopilot.lane("pixelize three pictures with `loki-make pixel --size 64`") == "light")
auto.agent = types.SimpleNamespace(TEAMS=types.SimpleNamespace(get=lambda _id: {"status": "done"}))
auto.duty_inbox()
check("as they finish, the rest start", len(started) == 5 and any("music" in t for t in started[3:]), started)
os.environ.pop("LOKI_AUTOPILOT_SLOTS")

# ---------------------------------------------------------------------------- one duty per pass
section("one duty per pass, each on its own schedule")
# The PC-only duties (selftest, task_bench; auto = on for the PC) would run here and, once
# the bench starts, make the autopilot busy - this test is about the base duty rotation,
# so turn them off for it (they have their own suites).
# the upstream check (engine/agentsys/upstream.py) asks GitHub - it has its own suite (tests/test_agentsys.py)
_saved_env = {k: os.environ.get(k) for k in ("LOKI_SELFTEST", "LOKI_TASK_BENCH", "LOKI_AUTOPILOT_ALWAYS", "LOKI_UPSTREAM")}
os.environ["LOKI_SELFTEST"] = os.environ["LOKI_TASK_BENCH"] = os.environ["LOKI_AUTOPILOT_ALWAYS"] = "0"
os.environ["LOKI_UPSTREAM"] = "0"
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
_running = set()
_ap._team_running = lambda tid: tid in _running  # pylint: disable=protected-access
_ap.duty_always()
check("free slots: both standing goals start side by side", [g.split(" (standing")[0] for g in _started]
      == ["make promo art", "write a devlog draft"], _started)
check("each is marked drafts-only (never publish)", all("never publish" in g for g in _started))
_running.update({"T1", "T2"})
_ap.duty_always()
check("a goal never runs twice at once", len(_started) == 2, _started)
_running.discard("T1")
_ap.duty_always()
check("one finished: the next one in turn starts", [g.split(" (standing")[0] for g in _started][2:] == ["make promo art"],
      _started)
_running.update({"T3"})
os.environ["LOKI_AUTOPILOT_SLOTS"] = "2"
_ap.data["started"]["x"] = {"open": True, "team": "T9", "text": "other"}
_running.add("T9")
check("not while the slots are full", _ap.duty_always() == "" and len(_started) == 3)
os.environ.pop("LOKI_AUTOPILOT_SLOTS")

section("work goes on beside running jobs; updates and overdue checks get a quiet moment")


class _Jobs:
    class store:  # noqa: N801
        @staticmethod
        def all():
            return [{"status": "working"}]


_st = FakeState()
_st.jobs = _Jobs()
_w = []
_ap2 = autopilot.Autopilot(data_dir=TMP / "beside", repo=TASKS, clock=lambda: 10_000_000.0, state=_st,
                           start_team=lambda g: (_w.append(g), "started team W%d" % len(_w))[1])
_ap2._team_running = lambda tid: True  # pylint: disable=protected-access
_ap2.data["last"].update({"health": 10_000_000.0, "report": 10_000_000.0})
ran = _ap2.tick()
check("a background job running does not stop new work from starting", ran and ran[0][0] in ("inbox", "always"), ran)
_ap2.data["last"]["health"] = 1.0
check("a long-overdue health check drains: no new work until it ran", "health" in _ap2.drain())
import updater  # noqa: E402
_ap2.data["last"]["health"] = 10_000_000.0
updater.STATE["update_available"] = True
_saved_force = updater.force_enabled
updater.force_enabled = lambda: True
check("an update waiting drains too (so it can be applied)", "update" in _ap2.drain())
updater.STATE.pop("update_available")
updater.force_enabled = _saved_force
check("otherwise no drain", _ap2.drain() == "")

os.environ["LOKI_MACHINE_ROLE"] = "light"
os.environ.pop("LOKI_AUTOPILOT_SLOTS", None)
os.environ.pop("LOKI_AUTOPILOT_ALWAYS_S", None)
check("a light machine (the Mac) runs one job at a time by default", autopilot.slots() == 1, autopilot.slots())
check("... and standing goals at most once an hour", autopilot.always_every_s() == 3600, autopilot.always_every_s())
os.environ["LOKI_MACHINE_ROLE"] = "main"
check("the PC keeps 3 slots and 10-minute standing goals", autopilot.slots() == 3 and autopilot.always_every_s() == 600)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
