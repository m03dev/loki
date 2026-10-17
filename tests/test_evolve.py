"""LOKI growing itself (engine/evolve.py + the autopilot's evolve duty), and the app restarting a
crashed engine (app/loki_app.py supervise).

    python tests/test_evolve.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "app"))
import autopilot  # noqa: E402
import evolve  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:240]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


TMP = Path(tempfile.mkdtemp(prefix="loki-evolve-"))
FAKE_REPO = TMP / "repo"
(FAKE_REPO / "docs").mkdir(parents=True)
(FAKE_REPO / "docs" / "EVOLVE.md").write_text(
    "# x\n- [x] E1 Memory you can see\n- [ ] E2 Learn skills\n- [ ] E3 Subagents\nnot an item\n", encoding="utf-8")

section("the real roadmap")
real = evolve.roadmap(REPO)
check("docs/EVOLVE.md has steps LOKI can take", len(real) >= 8 and all(i["id"].startswith("E") for i in real), real[:2])
check("its own game engine and more island life are on it",
      any("game engine" in i["title"] for i in real) and any("fox" in i["title"] for i in real))

section("what next: the owner's ideas first, then the roadmap; done steps skipped")
clock = [1000.0]
ev = evolve.Evolve(FAKE_REPO, TMP / "data", clock=lambda: clock[0])
check("a finished roadmap step is skipped", ev.next_item()["id"] == "E2")
check("a too-short idea is refused", not ev.add_idea("hi")["ok"])
idea = ev.add_idea("Make the fox follow the cursor in LOKI World")["idea"]
check("the owner's idea goes first", ev.next_item()["id"] == idea["id"])
loki_idea = ev.add_idea("A rabbit burrow by the pond", by="loki")["idea"]
check("LOKI's own idea waits for the owner's OK", loki_idea["approved"] is False
      and all(i["id"] != loki_idea["id"] for i in [ev.next_item()]))

section("one change at a time, with lessons from earlier attempts")
asked = []


def improve(task):
    asked.append(task)
    return "started job j1: a LOKI agent is making the change in its own worktree"
line = ev.step(improve)
check("it hands the step to improve_loki", line.startswith("Evolving " + idea["id"]) and "fox follow" in asked[0], line)
check("the task keeps every feature and the pixel look, and needs tests", "never remove a feature" in asked[0]
      and "add a check to the tests" in asked[0])
check("while that job runs nothing else starts", ev.busy() and ev.step(improve) == "" and len(asked) == 1)
check("a finished job means shipped", ev.settle(lambda j: "done" if j == "j1" else None) == [(idea["id"], "shipped")])
check("the shipped idea is done", all(not (i["id"] == idea["id"] and not i["done"]) for i in ev.items()))
check("next is the roadmap again", ev.next_item()["id"] == "E2")
ev.step(lambda t: "started job j2: ...")
check("a failed job is recorded and the lesson kept", ev.settle(lambda j: "failed") == [("E2", "failed")]
      and "E2: failed" in ev.lessons())
check("a failed step waits 3 days before the retry", ev.next_item()["id"] == "E3")
clock[0] += evolve.RETRY_S + 1
check("...and then comes back", ev.next_item()["id"] == "E2")
check("the retry carries what went wrong", "E2: failed" in ev.task_for(ev.next_item()))
check("a job that cannot even start is a failure, not a hang",
      ev.step(lambda t: "error: LOKI may not change its own code here") .startswith("Could not") and not ev.busy())
check("an approved LOKI idea becomes buildable", ev.approve(loki_idea["id"])["ok"]
      and any(i["id"] == loki_idea["id"] and i["approved"] for i in ev.items()))

section("on by default only on the Windows PC (on 24/7); the setting wins")
check("auto: on on Windows", evolve.enabled({}, "win32"))
check("auto: off on the Mac", not evolve.enabled({}, "darwin"))
check("on / off", evolve.enabled({"LOKI_EVOLVE": "on"}, "darwin") and not evolve.enabled({"LOKI_EVOLVE": "off"}, "win32"))

section("the autopilot runs it when idle")


class State:
    last_request_at = 0
    jobs = None

    def try_busy(self):
        return object()

    def release_busy(self, held):
        pass


import os  # noqa: E402
os.environ["LOKI_EVOLVE"] = "on"
ev2 = evolve.Evolve(FAKE_REPO, TMP / "data2")
started = []
pilot = autopilot.Autopilot(state=State(), data_dir=TMP / "ap", repo=FAKE_REPO, evolve=ev2,
                            improve=lambda t: started.append(t) or "started job k1: ok")
pilot.data["last"].update({"health": 9e18, "inbox": 9e18})
ran = pilot.tick()
check("the evolve duty starts the next step", ran and ran[0][0] == "evolve" and len(started) == 1, ran)
check("and logs it for the Lab", any(e["duty"] == "evolve" for e in pilot.data["log"]))
os.environ["LOKI_EVOLVE"] = "off"
pilot.data["last"]["evolve"] = 0
check("LOKI_EVOLVE=off stops it", all(d != "evolve" for d, _ in pilot.tick()))
del os.environ["LOKI_EVOLVE"]

section("the window: Settings > Lab and the routes")
ui = REPO / "app" / "ui"
html = (ui / "index.html").read_text(encoding="utf-8")
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("a Lab tab and lab.js", 'data-tab="lab"' in html and "/ui/lab.js" in html)
check("GET /evolve and POST /evolve/idea|start|approve", 'route == "/evolve"' in bridge and '"/evolve/approve"' in bridge)
check("the autopilot is given the evolve loop", "evolve=state.evolve, improve=loki.improve_loki" in bridge)

section("a crashed engine is started again (the window sat dead all night)")
import loki_app  # noqa: E402


class Proc:
    def __init__(self, code):
        self.code = code

    def poll(self):
        return self.code


starts, shown = [], []
loki_app.start_and_wait = lambda py, ws, gd: (starts.append(1) or (Proc(None), "tok"))
loki_app.show_url = lambda url: shown.append(url)
stop = threading.Event()
holder = {"process": Proc(1)}
waits = []
stop.wait = lambda s=None: waits.append(s) or (len(starts) >= 1 and stop.set()) or False
loki_app.supervise(holder, Path("py"), Path("ws"), "", stop)
check("an unexpected exit is restarted and the window reloaded", starts == [1] and shown and "tok" in shown[0], (starts, shown))
stop2 = threading.Event()
holder2 = {"process": Proc(1), "crashes": [9e18] * 5}
starts.clear()
import time as _t  # noqa: E402
holder2["crashes"] = [_t.time()] * 5
loki_app.supervise(holder2, Path("py"), Path("ws"), "", stop2)
check("but not forever: 5 crashes in 10 minutes and it stops trying", starts == [])

# Update everything restarts the whole client on every machine, not only the engine
os.environ["LOKI_APP_TEST"] = "1"   # no hard exit of the test process after a relaunch
launched, closed = [], []
loki_app.subprocess.Popen = lambda cmd, **kw: launched.append((cmd, kw.get("env", {}).get("LOKI_APP_WAIT_PID")))
loki_app.close_window = lambda: closed.append(1)
starts.clear()
stop3 = threading.Event()
loki_app.supervise({"process": Proc(loki_app.RESTART_EXIT_CODE)}, Path("py"), Path("ws"), "", stop3)
check("an update restart relaunches the whole app (it waits for this one) and closes this window",
      launched and launched[0][1] == str(os.getpid()) and closed == [1] and stop3.is_set() and starts == [],
      (launched, closed, starts))
check("a relaunched app waits for the old one to exit", "wait_for_old_app()" in (REPO / "app" / "loki_app.py").read_text(encoding="utf-8"))

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
