"""Agent teams: roles picked for a goal, stages in order, a shared board, one fix round.

    python tests/test_team.py

A stand-in job runner plays the agents (each 'job' finishes with the output the test
chooses), so every path of engine/team.py runs offline and deterministically.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["LOKI_DATA"] = str(TMP / "data")
sys.path.insert(0, str(REPO / "engine"))

import team  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:300]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


class Store:
    def __init__(self):
        self.jobs = {}

    def get(self, job_id):
        return self.jobs.get(job_id)

    def update(self, job_id, **fields):
        self.jobs[job_id].update(fields)
        return self.jobs[job_id]


class FakeJobs:
    """Each created job stays 'working' until the test finishes it."""

    def __init__(self):
        self.store = Store()
        self.created = []
        self.n = 0

    def create(self, spec):
        self.n += 1
        job = dict(spec, id="j%d" % self.n, status="working", output="")
        self.store.jobs[job["id"]] = job
        self.created.append(job)
        return job

    def cancel(self, job_id):
        self.store.jobs[job_id]["status"] = "cancelled"

    def tick(self):
        pass

    def finish(self, title_part, output, status="done"):
        for job in self.created:
            if title_part in job["title"] and job["status"] == "working":
                job.update(status=status, output=output)
                return job
        raise AssertionError("no working job like %r" % title_part)

    def working(self):
        return [j["title"].split("·")[1].split(":")[0].strip() for j in self.created if j["status"] == "working"]


WS = TMP / "project"
WS.mkdir()

section("one core agent (owner 2026-10-28: 'change the style ... no more 5')")
check("a build gets ONE core agent - no reviewer, tester, researcher or browser tester",
      team.choose_roles("build a todo app") == ["builder"])
check("... a website too", team.choose_roles("build a landing page for my bakery") == ["builder"])
check("... and a research-heavy goal (the core agent has the research tools itself)",
      team.choose_roles("research the best GPU and build a picker") == ["builder"])
check("Laya's role advice no longer splits the work",
      team.choose_roles("make a website", decide=lambda q, s: {"researcher": {"noul": 0.9}}) == ["builder"])

section("the core agent does it start to finish")
jobs = FakeJobs()
runner = team.TeamRunner(jobs)
t = runner.start("build a landing page for my bakery", str(WS))
check("the core agent starts building at once", t["stage"] == "build" and jobs.working() == ["Builder"], jobs.working())
check("it works in the project folder (no separate copy)",
      all(j["workspace"] == str(WS) and j["isolate"] is False for j in jobs.created))
check("it knows its board (team_post/team_read)", all(j["team"] == t["id"] for j in jobs.created)
      and "team_post" in jobs.created[0]["prompt"])
builder_prompt = [j for j in jobs.created if "Builder" in j["title"]][0]["prompt"]
check("it plans and checks it itself", "start to finish" in builder_prompt, builder_prompt[:400])
jobs.finish("Builder", "DONE: built index.html")
runner.tick()
t = runner.get(t["id"])
check("when it is done the team is done - one model call chain, no second agent re-reading it",
      t["status"] == "done" and len(jobs.created) == 1 and not t["verdict"].startswith("needs you"), (t, len(jobs.created)))
check("the board tells the story", any("Team finished" in m["text"] for m in team.board(t["id"])))
check("a crashed or blocked agent counts as a failure", team._reports_failure({"status": "failed"})
      and team._reports_failure({"status": "done", "output": "BLOCKED: no model"}))
check("'0 FAIL' is not a failure", not team._reports_failure({"status": "done", "output": "PASS 5, 0 FAIL"}))

section("a stage that cannot finish stops the team")
jobs4 = FakeJobs()
runner4 = team.TeamRunner(jobs4)
t4 = runner4.start("build a thing", str(WS))
jobs4.finish("Builder", "BLOCKED: no model is available")
runner4.tick()
t4 = runner4.get(t4["id"])
check("a blocked builder stops the team instead of reviewing nothing",
      t4["status"] == "done" and "Builder could not finish" in t4["verdict"] and jobs4.working() == [], t4)

section("cancel, inputs, persistence")
jobs3 = FakeJobs()
runner3 = team.TeamRunner(jobs3)
t3 = runner3.start("build a thing", str(WS))
runner3.cancel(t3["id"])
check("cancelling stops its agents", all(j["status"] == "cancelled" for j in jobs3.created) and runner3.get(t3["id"])["status"] == "cancelled")
for bad, why in (("", "empty goal"), ("x", "missing folder")):
    try:
        runner3.start(bad, str(TMP / "nope") if bad else str(WS))
        check("refuses: " + why, False)
    except ValueError:
        check("refuses: " + why, True)
check("teams survive a restart (saved to disk)", team.TeamRunner(jobs3).get(t3["id"]) is not None)
check("team ids cannot escape the teams folder", team._safe("../../etc") == "etc")
shown = team.present(runner.get(t["id"]), jobs)
check("the UI view lists members and the board", shown["members"] and shown["board"] and shown["roles"][0] == "Builder")

section("no invented results (owner 2026-10-22: QA teams faked their findings)")
check("every agent is told not to invent results or write stand-ins",
      team.HONESTY in team.agent_prompt(runner.get(t["id"]), "builder") and "stand-in" in team.HONESTY)
FK = TMP / "fakes"; (FK / "models").mkdir(parents=True, exist_ok=True); (FK / ".hidden").mkdir(exist_ok=True)
(FK / "models" / "chair.glb").write_text("# Chair - Default Aspect\nFormat: GLB (Forge export)\n")
(FK / "models" / "real.glb").write_bytes(b"glTF\x02\x00\x00\x00" + b"\x00" * 40)
(FK / "hero.png").write_text("a picture of a hero")
(FK / "real.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
(FK / "notes.md").write_text("plain notes are fine")
(FK / ".hidden" / "x.glb").write_text("hidden folders are LOKI's own")
found = sorted(team.fake_files(FK))
check("a text file saved as .glb / .png is caught, real ones and notes are not",
      found == [str(Path("hero.png")), str(Path("models") / "chair.glb")], found)
check("only files changed since the team started count", team.fake_files(FK, since=time.time() + 60) == [])
src = (REPO / "engine" / "team.py").read_text(encoding="utf-8")
check("the check stage fails a team that left fake files", "fakes = fake_files(team[\"workspace\"]" in src)

section("wired in")
loki_src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("LOKI has start_team, team_post and team_read", all('"%s"' % n in loki_src for n in ("start_team", "team_post", "team_read")))
check("starting a team asks you once (like delegate)", '"delegate", "start_team"}' in loki_src)
check("Ask and Plan cannot start a team", '"start_team"}' in loki_src.split("DELEGATING =")[1].split("\n")[0])
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the engine runs teams and serves /teams", "TeamRunner(" in bridge and 'route == "/teams"' in bridge)
workers_src = (REPO / "engine" / "workers.py").read_text(encoding="utf-8")
check("a team agent knows its team and role", "LOKI_TEAM_ID=" in workers_src and "LOKI_TEAM_ROLE=" in workers_src)
ui = (REPO / "app" / "ui" / "app.js").read_text(encoding="utf-8")
check("the work strip shows teams with their board", "renderTeams" in ui and "Team board" in ui)
fl = (REPO / "engine" / "first_layer.py").read_text(encoding="utf-8")
check("a 'team' triage tells LOKI to start a team", "start_team" in fl)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
