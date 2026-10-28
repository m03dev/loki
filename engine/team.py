"""Agent teams: one sentence in, ONE core agent that builds it and a fresh-eyes reviewer that checks it.

You never build agents. For a goal, LOKI picks the roles it needs (Laya decides when it is
set up, rules otherwise), creates each agent with a fitting spec, and runs them in stages
on one shared project folder:

    plan     researcher, read-only, only when the goal needs facts looked up
    build    builder - the one core agent, with the owner's playbook + toolbox for the job; the only writer
    check    reviewer (fresh context: reads it, runs its checks, changes nothing); a browser tester for web work
    (architect / tester exist only for the "sparc:" method the owner can ask for by name)
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

class _Roles(dict):
    """A team saved with a role LOKI has since retired (2026-10-28, the PC: the manga specialists were removed and a
    saved team that named art_manga_writer broke the window's status call 78 times - KeyError) still shows and still
    runs: the retired role reads as itself and works as a Builder without commands."""

    def __missing__(self, key):
        name = str(key).split("#")[0].replace("art_", "").replace("_", " ").strip().title() or "Agent"
        return {"name": name + " (retired)", "stage": "build", "writes": True, "commands": False,
                "brief": "Do your part of the team's goal in the project folder and report what you made."}


ROLES = _Roles({
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
    "reviewer": {"name": "Reviewer", "stage": "check", "writes": False, "commands": True,
                 "brief": "Fresh eyes: you did not build this. Check what was made against the goal and the owner's "
                          "playbook for this job (its done-means and rules): open the files, run its tests or checks "
                          "(read-only - change nothing). Report each problem as FAIL (file, line or step, why, the "
                          "exact output) or say PASS."},
    "browser": {"name": "Browser tester", "stage": "check", "writes": False, "commands": True,
                "brief": "Open the built site or app in a browser (the conductor's browse role) and "
                         "check it works like a user would. Report PASS or FAIL with what you saw."},
})
# The art specialists (engine/art_specialists.py; owner 2026-10-27: "the builder is too vague. They need specialized
# agents"): an art goal gets the specialist for it, with its skill and its tool, never the coding Builder.
try:
    import art_specialists as _art
    for _k, _sp in _art.SPECIALISTS.items():
        ROLES["art_" + _k] = {"name": _sp["name"], "stage": "build", "writes": True, "commands": False,
                              "brief": "You are the %s. Deliver %s with the %s tool. Follow your skill (below) line by "
                                       "line: every prompt you write is technical and complete. Every picture waits "
                                       "for the owner's OK on its prompt in Home > For you - submit it and report what "
                                       "you submitted." % (_sp["name"], _sp["does"], _sp["tool"])}
except Exception:  # noqa: BLE001 - teams work without the art roles
    _art = None
STAGES = ["plan", "build", "check"]
ART_KINDS = (("character", r"\b(character|hero|warrior|knight|girl|boy|man|woman|kid|person)\b"),
             ("vehicle", r"\b(vehicle|car|ship|boat|tank|cart|bike)\b"),
             ("prop", r"\b(prop|sword|chest|weapon|shield|lamp|barrel|tool|item)\b"))


def art_kind(goal: str) -> str:
    for kind, rx in ART_KINDS:
        if re.search(rx, goal, re.I):
            return kind
    return "creature"
FINAL = {"done", "failed", "cancelled"}

ROLE_QUESTIONS = {
    "researcher": "Does doing this well require looking up facts, docs or examples first?",
    "browser": "Is the result a website or web app that should be checked in a real browser?",
}


# SPARC (Ruflo's method: Specification, Pseudocode, Architecture, Refinement, Completion) on
# LOKI's own team stages. Start a team with "sparc: <goal>" or set LOKI_TEAM_METHOD=sparc.
SPARC_PHASES = {
    "researcher": "SPARC phase S - Specification. Pin down the goal: users, inputs and outputs, "
                  "constraints, edge cases and acceptance criteria (each one testable). No secrets "
                  "or environment values hard-coded. Post the specification to the team board.",
    "architect": "SPARC phases P + A - Pseudocode and Architecture. In TEAM_PLAN.md write the "
                 "pseudocode of each part with TDD anchors (the test that proves it), then the "
                 "architecture: files, modules, boundaries and how data flows between them.",
    "builder": "SPARC phase R - Refinement. Work test-first: write the tests from the TDD anchors, "
               "watch them fail, implement until they pass, then refactor. Keep files small.",
    "tester": "SPARC phase C - Completion (verify). Run every test and the acceptance criteria from "
              "the specification. Report each criterion PASS or FAIL with the exact output.",
    "reviewer": "SPARC phase C - Completion (review). Check the code against the specification and "
                "TEAM_PLAN.md: correctness, security (input checks, no secrets), and that it is "
                "documented enough to run. Report FAIL (file, line, why) or PASS.",
    "browser": "SPARC phase C - Completion (in use). Use the result like a real user would and "
               "check the acceptance criteria that can be seen. Report PASS or FAIL.",
}


def team_method(goal: str) -> tuple:
    """(method, goal without its prefix): 'sparc' for "sparc: ..." or LOKI_TEAM_METHOD=sparc."""
    match = re.match(r"^\s*sparc\s*[:\-]\s*", goal or "", flags=re.IGNORECASE)
    if match:
        return "sparc", goal[match.end():].strip()
    method = os.getenv("LOKI_TEAM_METHOD", "").strip().lower()
    return ("sparc" if method == "sparc" else "standard"), goal


def _with_playbook(role: str, brief: str, goal: str = "") -> str:
    """LOKI's brief first (it is the rule), then the best premade specialist for the goal, then Ruflo's playbook."""
    premade = premade_specialist(role, brief, goal)
    if premade:
        brief = brief + "\n\n" + premade
    if os.getenv("LOKI_TEAM_PLAYBOOKS", "ruflo").strip().lower() in ("", "0", "off", "none"):
        return brief
    try:
        import ruflo_library  # pylint: disable=import-outside-toplevel
        extra = ruflo_library.playbook(role)
    except Exception:  # noqa: BLE001 - the library is optional
        extra = ""
    extra = clean_playbook(extra)
    if not extra:
        return brief
    return (brief + "\n\n## Playbook (from Ruflo, github.com/ruvnet/ruflo; your brief above wins "
            "where they differ)\n" + extra)


def premade_specialist(role: str, brief: str, goal: str = "") -> str:
    """The premade agent that fits this role and goal best, from the downloaded libraries (engine/specialist_library.py;
    owner 2026-10-28: "we need premade, just add them to loki") - a Builder on a FastAPI goal gets the FastAPI pro,
    a Reviewer on a Rust goal the Rust reviewer. Art roles keep their own skill."""
    if role.startswith("art_") or os.getenv("LOKI_TEAM_PREMADE", "on").strip().lower() in ("0", "off", "no"):
        return ""
    try:
        import specialist_library  # pylint: disable=import-outside-toplevel
        words = {"researcher": "research analyst", "architect": "architect architecture design",
                 "builder": "developer engineer pro", "tester": "test automation qa engineer",
                 "reviewer": "code reviewer review", "browser": "browser e2e test playwright"}.get(role, role)
        hits = specialist_library.best_specialists("%s %s" % (goal or brief[-600:], words), 1, "agent")
        if not hits or hits[0]["score"] < 6:
            return ""
        text = clean_playbook(specialist_library.specialist_text(hits[0], 3000))
    except Exception:  # noqa: BLE001 - the brief stands alone
        return ""
    if not text:
        return ""
    return ("## Specialist know-how (premade agent '%s' from %s; your brief above wins where they differ)\n%s"
            % (hits[0]["name"], hits[0]["lib"], text))


def clean_playbook(text: str, limit: int = 1500) -> str:
    """Ruflo's playbooks name tools LOKI's agents do not have (mcp__claude-flow__*, its memory API) and run to
    thousands of characters - small models then chase the tools or lose the task. Keep the guidance, drop the code
    and tool sections, cap the length."""
    text = re.sub(r"```.*?```", "", str(text or ""), flags=re.S)
    keep, skip = [], False
    for line in text.splitlines():
        if re.match(r"^#{1,4}\s", line):
            skip = bool(re.search(r"mcp|tool integration|memory|hooks?|coordination protocol|javascript|claude-flow",
                                  line, re.I))
        if not skip and "mcp__" not in line and "claude-flow" not in line:
            keep.append(line)
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()
    return out[:limit].rsplit("\n", 1)[0] if len(out) > limit else out


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

_BIG = re.compile(r"\b(build|design|architect\w*|implement|refactor|research|compare|campaign|several|multiple|"
                  r"function|class|module|unit tests?|tests)\b"
                  # a product noun counts only as the thing being made ("make a game", "create the app") - "game
                  # concept art" or "a sprite for the game" is one picture (2026-10-25: those got four agents)
                  r"|\b(?:make|create|develop|code|write|start)\s+(?:an?\s+|the\s+|my\s+|our\s+|new\s+|small\s+|simple\s+)*"
                  r"(?:\w+\s+)?(?:app|game|website|engine|system|feature|pipeline|platformer)\b", re.I)


def solo_goal(goal: str, triage: dict | None = None) -> bool:
    """True for a small, concrete goal one agent does start to finish."""
    if os.getenv("LOKI_TEAM_SOLO", "auto").strip().lower() in ("off", "0", "no"):
        return False
    t = triage or {}
    if int(t.get("difficulty") or 0) >= 3:
        return False
    text = re.sub(r"`[^`]*`", " ", str(goal or ""))
    return len(text) < 500 and not _BIG.search(text)


def choose_roles(goal: str, triage: dict | None = None, decide=None) -> list:
    """The roles this goal needs, in stage order. `decide` is laya.decide (or None)."""
    triage = triage or {}
    kind = triage.get("kind", "")
    text = goal.lower()
    # One core agent writes; helpers only read (docs/AGENT_SYSTEM.md "One core agent"): Google Research's study of 180
    # set-ups (2025) found every multi-agent split 39-70% worse on sequential work, and Cognition ships one writer +
    # a reviewer with a clean context. So: the builder (with the owner's playbook) does it all, a fresh-eyes reviewer
    # checks it; a researcher looks things up first when the goal needs facts; a browser checker for web work.
    roles = ["builder", "reviewer"]
    art = _art.for_goal(goal) if _art is not None else []
    if len(art) == 1:                       # one specialist does it (a concept, a render, a video)
        return ["art_" + art[0]]
    # a small, concrete job (a check, a conversion, one file) needs one agent, not four in turn (2026-10-25: a
    # "pixelize three pictures" request became an Architect writing a plan for 25 minutes on a 9B model)
    if solo_goal(goal, triage):
        return ["builder"]
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


# Owner 2026-10-22: QA teams wrote their own stand-in "forge_qa.py" that made bugs up from file-name hashes,
# saved a few lines of text as ".glb" models and reported the result as findings. Every agent gets this rule,
# and a team whose folder holds files that are not what their names say cannot finish as "verified".
HONESTY = ("Never invent results. Every result you report must come from a command you really ran, a file you "
           "really read or a tool you really called - quote its actual output. If a tool, file or program you "
           "were told to use is missing or does not work, say BLOCKED: and why; do not write your own stand-in "
           "with the same name, and do not simulate, guess or randomise its output. Never save text under a "
           "binary file type (.glb, .png, .jpg, .blend, .fbx, .obj, .wav, .mp4 ...) - a model or image must be "
           "made by a real tool (Forge, the image generator, the render studio).")

# file type -> the bytes a real file of that type starts with (a few formats are text by design: .obj, .svg)
MAGIC = {".glb": (b"glTF",), ".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8",), ".jpeg": (b"\xff\xd8",),
         ".gif": (b"GIF8",), ".webp": (b"RIFF",), ".wav": (b"RIFF",), ".mp4": None, ".mov": None,
         ".blend": (b"BLENDER",), ".fbx": (b"Kaydara FBX Binary", b"; FBX"), ".exr": (b"\x76\x2f\x31\x01",),
         ".zip": (b"PK",), ".pdf": (b"%PDF",)}


def fake_files(folder: str | Path, since: float = 0.0, limit: int = 2000) -> list:
    """Files changed since `since` whose name promises a binary format but whose bytes are something else
    (mostly: plain text an agent saved as a model or picture). Paths relative to `folder`."""
    root = Path(folder)
    out, seen = [], 0
    if not root.is_dir():
        return out
    for path in root.rglob("*"):
        seen += 1
        if seen > limit * 20 or len(out) >= limit:
            break
        ext = path.suffix.lower()
        if ext not in MAGIC or any(p.startswith(".") for p in path.relative_to(root).parts[:-1]):
            continue
        try:
            if not path.is_file() or path.stat().st_mtime < since:
                continue
            head = path.open("rb").read(64)
        except OSError:
            continue
        magic = MAGIC[ext]
        if magic is None:   # containers with a box header: real ones are binary, never all printable text
            bad = bool(head) and all(32 <= b < 127 or b in (9, 10, 13) for b in head)
        else:
            bad = not any(head.startswith(m) for m in magic)
        if bad:
            out.append(str(path.relative_to(root)))
    return out


SOLO_BRIEF = ("Do the team goal yourself, start to finish, in the project folder, with your tools - make the files it "
              "asks for. Then check the result (open it, list it, run it) and post what you made to the team board.")


def plan_file(team: dict) -> str:
    """This team's own plan, in the project folder (2026-10-25: every team shared one TEAM_PLAN.md, and a voice job
    on the Mac 'implemented' an older team's Forge plan instead of its own goal)."""
    return "team_plans/%s.md" % team["id"]


def brief(team: dict, role: str) -> str:
    spec = ROLES[role]
    if role == "builder" and "architect" not in team.get("roles", []):
        return SOLO_BRIEF
    return spec["brief"].replace("TEAM_PLAN.md", plan_file(team))


def agent_prompt(team: dict, role: str, extra: str = "") -> str:
    spec = ROLES[role]
    mates = ", ".join(ROLES[r]["name"] for r in team["roles"] if r != role)
    parts = [
        "You are the %s on a LOKI agent team (team %s)." % (spec["name"], team["id"]),
        "Team goal: %s" % team["goal"],
        ("Your teammates: %s. Talk to them on the team board: team_read to see it, team_post to "
         "add a note (to='all' or a role name)." % mates) if mates else
        "You work alone on this goal; post what you made with team_post.",
        "Your job: %s" % brief(team, role),
        "Work only on THIS team's goal. TEAM_PLAN.md, team_board.md and other files in team_plans/ are from earlier "
        "teams - ignore them unless the goal names them.",
    ]
    try:   # the owner's playbook + toolbox for this job (engine/agentsys/playbooks.py) - his workflow, it wins
        from agentsys import playbooks as _pbs  # pylint: disable=import-outside-toplevel
        _pb = _pbs.match(team["goal"])
        if _pb:
            parts.append(_pbs.brief(_pb, limit=5000))
    except Exception:  # noqa: BLE001
        pass
    if role.startswith("art_") and _art is not None:
        parts.append("Your skill:\n" + _art.skills_text(role[4:]))
    if team.get("method") == "sparc" and role in SPARC_PHASES:
        parts.append(SPARC_PHASES[role].replace("TEAM_PLAN.md", plan_file(team)))
    history = board_text(team["id"])
    if history:
        parts.append("The team board so far:\n" + history)
    if extra:
        parts.append(extra)
    parts.append(HONESTY)
    parts.append("When you finish, end with DONE: <what you did> or BLOCKED: <why>.")
    return "\n\n".join(parts)


# --- running a team -----------------------------------------------------------------

class TeamRunner:
    """Starts each stage's agents as background jobs and moves the team along.

    `jobs` is a workers.Supervisor (or anything with create/store.get/tick)."""

    def __init__(self, jobs, policy=None, decide=None, choose_model=None):
        self.jobs = jobs
        self.policy = policy
        self.decide = decide
        # role -> provider name ("" = smart routing). The agent factory: each role gets the
        # model that has measurably done THAT job best (experience.best_for_role). A model
        # the user pinned for the team always wins.
        self.choose_model = choose_model
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
    def start(self, goal: str, workspace: str, triage: dict | None = None, model: str = "",
              dry_run: bool = False) -> dict:
        """Start a team. dry_run (the System check): the board, the events and the world are
        exercised exactly as for a real team, but no agent is started and no model is asked."""
        goal = str(goal or "").strip()
        if not goal:
            raise ValueError("say what the team should build")
        if not workspace or not Path(workspace).is_dir():
            raise ValueError("the team needs an existing project folder")
        if self.policy is not None:
            verdict = self.policy.job("local", "loki")
            if not verdict.allowed:
                raise ValueError(verdict.reason)
        method, goal = team_method(goal)
        if not goal:
            raise ValueError("say what the team should build")
        if not dry_run and _art is not None and len(_art.for_goal(goal)) > 1 \
                and not _art.for_goal(goal)[0].startswith("manga_"):
            # a whole asset (concept -> turnaround -> 3D -> finish -> render): the specialist pipeline does it, each
            # specialist in turn, every prompt and hand-off waiting for the owner (engine/asset_pipeline.py)
            import asset_pipeline  # pylint: disable=import-outside-toplevel
            asset = asset_pipeline.start(Path(workspace), goal, kind=art_kind(goal))
            return {"id": "asset-" + asset.get("id", ""), "goal": goal, "workspace": str(workspace), "status": "pipeline",
                    "roles": ["art_" + k for k in _art.ORDER], "asset": asset.get("id"),
                    "verdict": "handed to the art pipeline: %s (Concept Artist first; its prompt waits in Home > For you)"
                               % asset.get("id")}
        roles = choose_roles(goal, triage, self.decide)
        if method == "sparc" and "researcher" not in roles:
            roles.insert(0, "researcher")       # SPARC always starts with the Specification
        team = {"id": uuid.uuid4().hex[:8], "goal": goal, "workspace": str(workspace), "method": method,
                "roles": roles, "stage": "", "status": "working",
                "fix_rounds": 0, "jobs": {}, "created": time.time(), "finished": 0, "model": model,
                "verdict": "", "dry_run": bool(dry_run)}
        post(team["id"], "LOKI", "Team started for: %s\nRoles: %s%s" %
             (goal, ", ".join(ROLES[r]["name"] for r in team["roles"]),
              "\nMethod: SPARC (Specification > Pseudocode > Architecture > Refinement > Completion)"
              if method == "sparc" else ""))
        with self.lock:
            teams = self._load()
            teams[team["id"]] = team
            self._save(teams)
        if dry_run:
            stages = [s for s in STAGES if self._stage_roles(team, s)]
            post(team["id"], "LOKI", "Dry run - no agents started. Stages: %s" % " > ".join(
                "%s (%s)" % (s, ", ".join(ROLES[r]["name"] for r in self._stage_roles(team, s))) for s in stages))
            with self.lock:
                teams = self._load()
                team = teams[team["id"]]
                team["stage"] = stages[0] if stages else ""
                self._finish(team, "done", "dry run: the team was planned, nothing was started")
                self._save(teams)
            return self.get(team["id"])
        self.tick()
        return self.get(team["id"])

    def forget(self, team_id: str) -> bool:
        """Remove a finished team and its board (the System check cleans up its dry run)."""
        with self.lock:
            teams = self._load()
            team = teams.get(team_id)
            if not team or team.get("status") not in FINAL:
                return False
            del teams[team_id]
            self._save(teams)
        folder = teams_dir() / _safe(team_id)
        try:
            for item in folder.glob("*"):
                item.unlink()
            folder.rmdir()
        except OSError:
            pass
        return True

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

    def model_for(self, team: dict, role: str) -> str:
        if team.get("model"):
            return team["model"]
        if self.choose_model is None:
            return ""
        try:
            return str(self.choose_model(role) or "")
        except Exception:  # noqa: BLE001 - a bad pick must never stop a team
            return ""

    def _spawn(self, team: dict, role: str, extra: str = "") -> str:
        spec = ROLES[role]
        model = self.model_for(team, role)
        team.setdefault("models", {})[role] = model or "smart"
        try:
            import events  # pylint: disable=import-outside-toplevel
            events.emit("task.assigned", "LOKI", {"role": spec["name"], "goal": team["goal"],
                        "stage": team.get("stage", ""), "model": model or "smart"},
                        team=team["id"], recipient=spec["name"])
        except Exception:  # noqa: BLE001
            pass
        job = self.jobs.create({
            "backend": "local", "agent": "loki", "workspace": team["workspace"],
            "isolate": False,               # one shared folder; stages never write at once
            "timeout_s": 3600, "allow_commands": spec["commands"], "model": model,
            "title": "Team %s · %s: %s" % (team["id"], spec["name"], team["goal"][:50]),
            "prompt": agent_prompt(team, role, extra), "team": team["id"],
            "profile": {"name": spec["name"], "role": role,
                        "instructions": _with_playbook(role, brief(team, role), team.get("goal", ""))},
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
                fakes = fake_files(team["workspace"], float(team.get("created") or 0))
                if fakes:
                    post(team["id"], "LOKI", "FAIL: these files are not what their names say (text saved as a "
                         "model or picture, or a broken file): %s. Make them with a real tool or remove them and "
                         "report BLOCKED." % ", ".join(fakes[:20]))
                    failed = failed or ["builder"]
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
    out = {k: team.get(k) for k in ("id", "goal", "status", "stage", "verdict", "created", "finished", "fix_rounds", "method")}
    out["roles"] = [ROLES[r]["name"] for r in team.get("roles", [])]
    members = []
    for key, job_id in (team.get("jobs") or {}).items():
        job = (jobs.store.get(job_id) if jobs is not None else None) or {}
        members.append({"role": ROLES[key.split("#")[0]]["name"], "round": key.split("#")[1] if "#" in key else "",
                        "job": job_id, "status": job.get("status", "")})
    out["members"] = members
    out["board"] = board(team["id"], last=30)
    return out
