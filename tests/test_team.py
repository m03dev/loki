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

section("roles are chosen for the goal")
check("a build gets architect, builder, tester, reviewer",
      team.choose_roles("build a todo app") == ["architect", "builder", "tester", "reviewer"])
check("a website also gets a browser tester", "browser" in team.choose_roles("build a landing page for my bakery"))
check("a research-heavy goal gets a researcher first", team.choose_roles("research the best GPU and build a picker")[0] == "researcher")
laya_says = lambda questions, state: {"researcher": {"noul": 0.9}, "browser": {"noul": 0.1}}
check("Laya's answer decides when it is available",
      team.choose_roles("make a website", decide=laya_says)[:1] == ["researcher"]
      and "browser" not in team.choose_roles("make a website", decide=laya_says))
check("a broken Laya leaves the rules in charge",
      team.choose_roles("build a site", decide=lambda *a: 1 / 0) == team.choose_roles("build a site"))

section("a team runs in stages and talks on the board")
jobs = FakeJobs()
runner = team.TeamRunner(jobs)
t = runner.start("build a landing page for my bakery", str(WS))
check("the team starts with the plan stage", t["stage"] == "plan" and jobs.working() == ["Architect"], jobs.working())
check("every agent shares the project folder (no separate copies)",
      all(j["workspace"] == str(WS) and j["isolate"] is False for j in jobs.created))
check("each agent knows its team (for team_post/team_read)", all(j["team"] == t["id"] for j in jobs.created))
check("the agent's prompt names its teammates and the board",
      "Builder" in jobs.created[0]["prompt"] and "team_post" in jobs.created[0]["prompt"])
team.post(t["id"], "Architect", "I will put the plan in TEAM_PLAN.md", "Builder")
jobs.finish("Architect", "DONE: wrote TEAM_PLAN.md")
runner.tick()
check("the builder starts only after the plan is done", jobs.working() == ["Builder"], jobs.working())
builder_prompt = [j for j in jobs.created if "Builder" in j["title"]][0]["prompt"]
check("the builder sees the board: the architect's note and report",
      "TEAM_PLAN.md" in builder_prompt and "Finished (done)" in builder_prompt)
check("only the builder writes while it works", sum(1 for j in jobs.created if j["status"] == "working") == 1)
jobs.finish("Builder", "DONE: built index.html")
runner.tick()
check("tester, reviewer and browser tester check it together",
      sorted(jobs.working()) == ["Browser tester", "Reviewer", "Tester"], jobs.working())

section("a failed check gets one fix round")
jobs.finish("Tester", "FAIL: the order button does nothing")
jobs.finish("Reviewer", "PASS")
jobs.finish("Browser tester", "PASS: page loads")
runner.tick()
t = runner.get(t["id"])
check("the builder is sent back with the findings", t["stage"] == "fix" and jobs.working() == ["Builder"], (t["stage"], jobs.working()))
fix_prompt = [j for j in jobs.created if j["status"] == "working"][0]["prompt"]
check("the fix round sees the failure on the board", "order button does nothing" in fix_prompt)
jobs.finish("Builder", "DONE: fixed the button")
runner.tick()
check("the checkers re-check after the fix", sorted(jobs.working()) == ["Browser tester", "Reviewer", "Tester"], jobs.working())
jobs.finish("Tester", "PASS: 4 checks, 0 FAIL")
jobs.finish("Reviewer", "PASS")
jobs.finish("Browser tester", "PASS")
runner.tick()
t = runner.get(t["id"])
check("the team is verified when every re-check passes", t["status"] == "done" and t["verdict"].startswith("verified"), t)
check("the board tells the whole story", any("Team finished" in m["text"] for m in team.board(t["id"])))

section("still failing after the fix round: it asks for you")
jobs2 = FakeJobs()
runner2 = team.TeamRunner(jobs2)
t2 = runner2.start("build a cli tool", str(WS))
jobs2.finish("Architect", "DONE")
runner2.tick()
jobs2.finish("Builder", "DONE")
runner2.tick()
jobs2.finish("Tester", "FAIL: crashes")
jobs2.finish("Reviewer", "PASS")
runner2.tick()
jobs2.finish("Builder", "DONE: tried")
runner2.tick()
jobs2.finish("Tester", "FAIL: still crashes")
jobs2.finish("Reviewer", "PASS")
runner2.tick()
t2 = runner2.get(t2["id"])
check("no endless loop: one fix round, then 'needs you'", t2["status"] == "done" and t2["verdict"].startswith("needs you"), t2)
check("a crashed or blocked agent counts as a failure", team._reports_failure({"status": "failed"})
      and team._reports_failure({"status": "done", "output": "BLOCKED: no model"}))
check("'0 FAIL' is not a failure", not team._reports_failure({"status": "done", "output": "PASS 5, 0 FAIL"}))

section("a stage that cannot finish stops the team")
jobs4 = FakeJobs()
runner4 = team.TeamRunner(jobs4)
t4 = runner4.start("build a thing", str(WS))
jobs4.finish("Architect", "BLOCKED: no model is available")
runner4.tick()
t4 = runner4.get(t4["id"])
check("a blocked architect stops the team instead of building blind",
      t4["status"] == "done" and "Architect could not finish" in t4["verdict"] and jobs4.working() == [], t4)

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
check("the UI view lists members and the board", shown["members"] and shown["board"] and shown["roles"][0] == "Architect")

section("no invented results (owner 2026-10-22: QA teams faked their findings)")
check("every agent is told not to invent results or write stand-ins",
      team.HONESTY in team.agent_prompt(runner.get(t["id"]), "tester") and "stand-in" in team.HONESTY)
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
