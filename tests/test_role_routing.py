"""The agent factory: each team role gets the model that has measurably done THAT job
best (experience.best_for_role), and a team records the role each job ran as.

    python tests/test_role_routing.py

No model or network: fakes for the job store and a tiny outcome log on disk.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]

import experience  # noqa: E402
import team as teams  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name: str, ok: bool, detail: object = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def section(title: str) -> None:
    print("\n" + title)


TIERS = {"local": "local", "gemini": "free", "claude-code": "subscription", "gpt-paid": "paid"}


def tier_of(name):
    return TIERS.get(name, "free")


# ---------------------------------------------------------------------------- scoring
section("role_stats and best_for_role, from the outcome log")
ROOT = Path(tempfile.mkdtemp(prefix="loki-role-"))


def log(role, provider, outcome, status="done"):
    experience.record({"kind": "task", "role": role, "provider": provider,
                       "outcome": outcome, "status": status, "files": ["a.py"]}, root=ROOT)


# builder: local is strong (8/10 verified), gemini weak (1/5)
for _ in range(8):
    log("builder", "local", "verified")
for _ in range(2):
    log("builder", "local", "failed")
for _ in range(1):
    log("builder", "gemini", "verified")
for _ in range(4):
    log("builder", "gemini", "failed")
# reviewer: no files, judged on DONE; claude-code solid
for _ in range(6):
    log("reviewer", "claude-code", "verified", status="done")

stats = experience.role_stats(root=ROOT)
check("builder has both providers", set(stats.get("builder", {})) == {"local", "gemini"}, stats.get("builder"))
check("builder/local success rate ~0.8", abs(stats["builder"]["local"]["success_rate"] - 0.8) < 0.01,
      stats["builder"]["local"])

best = experience.best_for_role("builder", ["local", "gemini"], tier_of, min_samples=5, root=ROOT)
check("the stronger builder model is chosen", best == "local", best)

best = experience.best_for_role("reviewer", ["claude-code", "gemini"], tier_of, min_samples=5, root=ROOT)
check("a role with no competing data picks the one with evidence", best == "claude-code", best)

check("too little data returns empty (keep the default)",
      experience.best_for_role("tester", ["local"], tier_of, min_samples=5, root=ROOT) == "", "tester")

# cheaper tier wins a near-tie
for _ in range(10):
    log("coder", "local", "verified")
for _ in range(10):
    log("coder", "gpt-paid", "verified")
best = experience.best_for_role("coder", ["gpt-paid", "local"], tier_of, min_samples=5, root=ROOT)
check("a near-tie goes to the cheaper tier (local over paid)", best == "local", best)

# ---------------------------------------------------------------------------- team wiring
section("the team runner asks for a model per role and records it")


class FakeStore:
    def __init__(self):
        self.jobs = {}

    def get(self, jid):
        return self.jobs.get(jid)


class FakeJobs:
    def __init__(self):
        self.created = []
        self.store = FakeStore()

    def create(self, spec):
        spec = dict(spec, id="j%d" % len(self.created), status="working")
        self.created.append(spec)
        self.store.jobs[spec["id"]] = spec
        return spec


picked = {"builder": "local", "reviewer": "claude-code"}
runner = teams.TeamRunner(FakeJobs(), choose_model=lambda role: picked.get(role, ""))
team = {"id": "T1", "goal": "build a thing", "workspace": "/ws", "roles": ["builder"], "stage": "build"}

jid = runner._spawn(team, "builder")  # pylint: disable=protected-access
job = runner.jobs.created[-1]
check("the builder job carries the chosen model", job["model"] == "local", job["model"])
check("the job profile carries the role, so the outcome can be scored",
      job["profile"]["role"] == "builder", job["profile"])
check("the team records which model each role used", team["models"]["builder"] == "local", team.get("models"))

# an owner-pinned team model overrides the per-role pick
team2 = {"id": "T2", "goal": "x", "workspace": "/ws", "roles": ["builder"], "stage": "build", "model": "gemini"}
runner._spawn(team2, "builder")  # pylint: disable=protected-access
check("a pinned team model wins over the per-role pick", runner.jobs.created[-1]["model"] == "gemini",
      runner.jobs.created[-1]["model"])

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
