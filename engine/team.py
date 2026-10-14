"""Agent teams: one sentence in, a team that plans, builds, tests and reviews it.

You never build agents. For a goal, LOKI picks the roles it needs (Laya decides when it is
set up, rules otherwise), creates each agent with a fitting spec, and runs them in stages
on one shared project folder:

    plan     researcher (if the goal needs facts) + architect (writes TEAM_PLAN.md)
    build    builder (the only writer while it works)
    check    tester (runs it) + reviewer (reads it); a browser tester for web work
    fix      if a checker reports FAIL, the builder gets one round with their findings

Agents talk on a shared board (team_post / team_read tools; harness_data/teams/<id>/
board.jsonl). Each agent's final report is posted there too, and every later stage starts
by reading the board. The team is done when the checks pass (verified) or the fix round
is spent (needs you). Background jobs (workers.py) do the actual running; this module only
plans, starts the next stage, and keeps the board.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

ROLES = {
    "researcher": {"name": "Researcher", "stage": "plan", "writes": False, "commands": False,
                   "brief": "Find the facts the team needs (APIs, libraries, constraints, examples). "
                            "Do not build anything. Post your findings to the team board."},
    "architect": {"name": "Architect", "stage": "plan", "writes": True, "commands": False,
                  "brief": "Design the solution and write it to TEAM_PLAN.md in the project folder: "
                           "files to create, how they fit, how to test it, and what DONE means. "
                           "Keep it short and concrete. Do not implement it."},
    "builder": {"name": "Builder", "stage": "build", "writes": True, "commands": True,
                "brief": "Implement TEAM_PLAN.md in the project folder. Make it run. Write or update "
                         "tests. Post what you built and how to run it to the team board."},
    "tester": {"name": "Tester", "stage": "check", "writes": False, "commands": True,
               "brief": "Run what the builder made and its tests. Report each check as PASS or FAIL "
                        "with the exact output. Do not fix anything yourself."},
    "reviewer": {"name": "Reviewer", "stage": "check", "writes": False, "commands": False,
                 "brief": "Read the code against TEAM_PLAN.md. Report concrete problems as FAIL "
                          "(file, line, why) or say PASS. Do not change files."},
    "browser": {"name": "Browser tester", "stage": "check", "writes": False, "commands": True,
                "brief": "Open the built site or app in a browser (the conductor's browse role) and "
                         "check it works like a user would. Report PASS or FAIL with what you saw."},
}
STAGES = ["plan", "build", "check"]
FINAL = {"done", "failed", "cancelled"}

ROLE_QUESTIONS = {
    "researcher": "Does doing this well require looking up facts, docs or examples first?",
    "browser": "Is the result a website or web app that should be checked in a real browser?",
}


def _data_dir() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def teams_dir() -> Path:
    path = _data_dir() / "teams"
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- the board ---------------------------------------------------------------------

def post(team_id: str, author: str, text: str, to: str = "all") -> dict:
    """Add a message to a team's board (agents and the team runner both use this)."""
    team_id = _safe(team_id)
    entry = {"t": time.time(), "from": str(author)[:40], "to": str(to or "all")[:40],
             "text": str(text or "")[:6000]}
    path = teams_dir() / team_id
    path.mkdir(parents=True, exist_ok=True)
    with open(path / "board.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    try:
        import events  # pylint: disable=import-outside-toplevel
        events.emit("agent.message", entry["from"], {"text": entry["text"]}, team=team_id, recipient=entry["to"])
    except Exception:  # noqa: BLE001
        pass
    return entry


def board(team_id: str, last: int = 60) -> list:
    path = teams_dir() / _safe(team_id) / "board.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines()[-last:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def board_text(team_id: str, last: int = 40, limit: int = 12000) -> str:
    lines = ["[%s -> %s] %s" % (m["from"], m["to"], m["text"]) for m in board(team_id, last)]
    text = "\n\n".join(lines)
    return text[-limit:] if len(text) > limit else text


def _safe(team_id: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]", "", str(team_id or ""))[:40]
    if not value:
        raise ValueError("no team id")
    return value


# --- planning the team --------------------------------------------------------------

def choose_roles(goal: str, triage: dict | None = None, decide=None) -> list:
    """The roles this goal needs, in stage order. `decide` is laya.decide (or None)."""
    triage = triage or {}
    kind = triage.get("kind", "")
    text = goal.lower()
    roles = ["architect", "builder", "tester", "reviewer"]
    wants = {"researcher": kind == "research" or bool(re.search(r"\b(research|latest|compare|which|best)\b", text)),
             "browser": kind == "browse" or bool(re.search(r"\b(website|web app|landing page|site|browser|html)\b", text))}
    if decide is not None:
        try:
            answers = decide({k: {"type": "noul", "instructions": q} for k, q in ROLE_QUESTIONS.items()},
                             {"goal": goal[:2000]})
        except Exception:  # noqa: BLE001 - Laya is advice; the rules stand without it
            answers = {}
        for key in ROLE_QUESTIONS:
            p = (answers.get(key) or {}).get("noul")
            if isinstance(p, (int, float)):
                wants[key] = p >= 0.5
    if wants["researcher"]:
        roles.insert(0, "researcher")
    if wants["browser"]:
        roles.append("browser")
    return roles


def agent_prompt(team: dict, role: str, extra: str = "") -> str:
    spec = ROLES[role]
    mates = ", ".join(ROLES[r]["name"] for r in team["roles"] if r != role)
    parts = [
        "You are the %s on a LOKI agent team (team %s)." % (spec["name"], team["id"]),
        "Team goal: %s" % team["goal"],
        "Your teammates: %s. Talk to them on the team board: team_read to see it, team_post to "
        "add a note (to='all' or a role name)." % mates,
        "Your job: %s" % spec["brief"],
    ]
    history = board_text(team["id"])
    if history:
        parts.append("The team board so far:\n" + history)
    if extra:
        parts.append(extra)
    parts.append("When you finish, end with DONE: <what you did> or BLOCKED: <why>.")
    return "\n\n".join(parts)


# --- running a team -----------------------------------------------------------------

class TeamRunner:
    """Starts each stage's agents as background jobs and moves the team along.

    `jobs` is a workers.Supervisor (or anything with create/store.get/tick)."""

    def __init__(self, jobs, policy=None, decide=None):
        self.jobs = jobs
        self.policy = policy
        self.decide = decide
        self.lock = threading.Lock()
        self.path = teams_dir() / "teams.json"

    # persistence
    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, teams: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(teams, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def all(self) -> list:
        return sorted(self._load().values(), key=lambda t: t.get("created", 0), reverse=True)

    def get(self, team_id: str) -> dict | None:
        return self._load().get(team_id)

    # lifecycle
    def start(self, goal: str, workspace: str, triage: dict | None = None, model: str = "") -> dict:
        goal = str(goal or "").strip()
        if not goal:
            raise ValueError("say what the team should build")
        if not workspace or not Path(workspace).is_dir():
            raise ValueError("the team needs an existing project folder")
        if self.policy is not None:
            verdict = self.policy.job("local", "loki")
            if not verdict.allowed:
                raise ValueError(verdict.reason)
        team = {"id": uuid.uuid4().hex[:8], "goal": goal, "workspace": str(workspace),
                "roles": choose_roles(goal, triage, self.decide), "stage": "", "status": "working",
                "fix_rounds": 0, "jobs": {}, "created": time.time(), "finished": 0, "model": model,
                "verdict": ""}
        post(team["id"], "LOKI", "Team started for: %s\nRoles: %s" %
             (goal, ", ".join(ROLES[r]["name"] for r in team["roles"])))
        with self.lock:
            teams = self._load()
            teams[team["id"]] = team
            self._save(teams)
        self.tick()
        return self.get(team["id"])

    def cancel(self, team_id: str) -> dict | None:
        with self.lock:
            teams = self._load()
            team = teams.get(team_id)
            if not team:
                return None
            for job_id in team["jobs"].values():
                try:
                    self.jobs.cancel(job_id)
                except Exception:  # noqa: BLE001
                    pass
            team.update(status="cancelled", finished=time.time())
            self._save(teams)
        post(team_id, "LOKI", "Team cancelled.")
        return team

    def _spawn(self, team: dict, role: str, extra: str = "") -> str:
        spec = ROLES[role]
        try:
            import events  # pylint: disable=import-outside-toplevel
            events.emit("task.assigned", "LOKI", {"role": spec["name"], "goal": team["goal"],
                        "stage": team.get("stage", "")}, team=team["id"], recipient=spec["name"])
        except Exception:  # noqa: BLE001
            pass
        job = self.jobs.create({
            "backend": "local", "agent": "loki", "workspace": team["workspace"],
            "isolate": False,               # one shared folder; stages never write at once
            "timeout_s": 3600, "allow_commands": spec["commands"], "model": team.get("model", ""),
            "title": "Team %s · %s: %s" % (team["id"], spec["name"], team["goal"][:50]),
            "prompt": agent_prompt(team, role, extra), "team": team["id"],
            "profile": {"name": spec["name"], "instructions": spec["brief"]},
        })
        return job["id"]

    def _job(self, job_id: str) -> dict:
        return self.jobs.store.get(job_id) or {}

    def tick(self) -> None:
        """Advance every working team by one step. Safe to call often."""
        with self.lock:
            teams = self._load()
            changed = False
            for team in teams.values():
                if team.get("status") != "working":
                    continue
                changed |= self._advance(team)
            if changed:
                self._save(teams)
        try:
            self.jobs.tick()
        except Exception:  # noqa: BLE001
            pass

    def _stage_roles(self, team: dict, stage: str) -> list:
        return [r for r in team["roles"] if ROLES[r]["stage"] == stage]

    def _advance(self, team: dict) -> bool:
        stage = team.get("stage") or ""
        if stage:
            if stage == "fix":
                keys = [k for k in team["jobs"] if k == "builder#fix%d" % team["fix_rounds"]]
            elif stage == "fix-check":
                keys = [k for k in team["jobs"] if k.endswith("#recheck")]
            else:
                keys = [k for k in team["jobs"] if "#" not in k and k in self._stage_roles(team, stage)]
            states = {k: self._job(team["jobs"][k]) for k in keys}
            if any(j.get("status") not in FINAL for j in states.values()):
                return False
            for key, job in states.items():
                if not job.get("reported"):
                    post(team["id"], ROLES[key.split("#")[0]]["name"],
                         "Finished (%s):\n%s" % (job.get("status"), (job.get("output") or job.get("error") or "")[-3000:]))
                    try:
                        self.jobs.store.update(team["jobs"][key], reported=True)
                    except Exception:  # noqa: BLE001
                        pass
            if stage in ("plan", "build", "fix"):
                broken = [k for k, j in states.items()
                          if j.get("status") in ("failed", "cancelled") or re.search(r"^\s*BLOCKED", j.get("output") or "", re.M)]
                if broken:
                    return self._finish(team, "done", "needs you: %s could not finish (see the board)" %
                                        ", ".join(ROLES[k.split("#")[0]]["name"] for k in broken))
            if stage == "check" or stage == "fix-check":
                failed = [k for k, j in states.items() if _reports_failure(j)]
                if not failed:
                    return self._finish(team, "done", "verified: every check passed")
                if team["fix_rounds"] >= 1:
                    return self._finish(team, "done", "needs you: checks still fail after a fix round (%s)" %
                                        ", ".join(ROLES[k.split("#")[0]]["name"] for k in failed))
                team["fix_rounds"] += 1
                team["stage"] = "fix"
                team["jobs"]["builder#fix%d" % team["fix_rounds"]] = self._spawn(
                    team, "builder", "FIX ROUND: the checkers reported failures (see the board). Fix exactly "
                                     "those, re-run the tests, and post what you changed.")
                return True
            if stage == "fix":
                team["stage"] = "fix-check"
                for role in self._stage_roles(team, "check"):
                    team["jobs"]["%s#recheck" % role] = self._spawn(team, role, "Re-check after the fix round.")
                return True
            nxt = STAGES[STAGES.index(stage) + 1] if stage in STAGES and STAGES.index(stage) + 1 < len(STAGES) else ""
        else:
            nxt = STAGES[0]
        while nxt and not self._stage_roles(team, nxt):
            nxt = STAGES[STAGES.index(nxt) + 1] if STAGES.index(nxt) + 1 < len(STAGES) else ""
        if not nxt:
            return self._finish(team, "done", "finished")
        team["stage"] = nxt
        for role in self._stage_roles(team, nxt):
            team["jobs"][role] = self._spawn(team, role)
        post(team["id"], "LOKI", "Stage %s: %s" % (nxt, ", ".join(ROLES[r]["name"] for r in self._stage_roles(team, nxt))))
        return True

    def _finish(self, team: dict, status: str, verdict: str) -> bool:
        team.update(status=status, verdict=verdict, finished=time.time())
        try:
            import events  # pylint: disable=import-outside-toplevel
            events.emit("verification.completed", "LOKI", {"goal": team["goal"], "verdict": verdict,
                        "verified": verdict.startswith("verified")}, team=team["id"])
        except Exception:  # noqa: BLE001
            pass
        post(team["id"], "LOKI", "Team finished: %s" % verdict)
        return True

    def run_forever(self, every_s: float = 5.0) -> None:
        while True:
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - a team problem must never stop the engine
                print("[team] %s: %s" % (type(exc).__name__, exc), flush=True)
            time.sleep(every_s)


def _reports_failure(job: dict) -> bool:
    if job.get("status") in ("failed", "cancelled"):
        return True
    text = (job.get("output") or "")[-4000:]
    if re.search(r"^\s*BLOCKED", text, re.M):
        return True
    return bool(re.search(r"\bFAIL\b", text)) and not re.search(r"\b0 FAIL", text)


def present(team: dict, jobs=None) -> dict:
    out = {k: team.get(k) for k in ("id", "goal", "status", "stage", "verdict", "created", "finished", "fix_rounds")}
    out["roles"] = [ROLES[r]["name"] for r in team.get("roles", [])]
    members = []
    for key, job_id in (team.get("jobs") or {}).items():
        job = (jobs.store.get(job_id) if jobs is not None else None) or {}
        members.append({"role": ROLES[key.split("#")[0]]["name"], "round": key.split("#")[1] if "#" in key else "",
                        "job": job_id, "status": job.get("status", "")})
    out["members"] = members
    out["board"] = board(team["id"], last=30)
    return out
