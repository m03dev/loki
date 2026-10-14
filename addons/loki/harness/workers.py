"""Background worker agents, and how Loki delegates to them.

A worker is one agent working one goal in its OWN Python process (worker.py). Process
isolation is deliberate: loki.py keeps a conversation, a list of touched files and a
budget in module state, so two agents in one process would corrupt each other.

Everything lives as plain files under <data>/workers/ so it survives a bridge restart and
any host (the bridge, the CLI, another worker) can read it:

    jobs/<id>.json          the job: role, goal, parent, status, result, usage, files
    jobs/<id>.events.jsonl  what happened, in order - the conversation between agents
    jobs/<id>.inbox.jsonl   messages TO this worker, read between its steps
    jobs/<id>.cancel        present = stop at the next safe point

Statuses follow sessions.py (Herdr's idea): queued -> working -> done | blocked | failed |
cancelled. A parent agent delegates with delegate(), waits with wait(), and reads the
child's report in the job's "result".

Cost rules: at most MAX_CONCURRENT workers run at once (default 2) and delegation depth is
capped (default 2), so one request cannot fan out into a swarm. Each worker also inherits
the paid-provider budget from loki.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent

STATUSES = ("queued", "working", "done", "blocked", "failed", "cancelled")
FINISHED = ("done", "blocked", "failed", "cancelled")
MAX_CONCURRENT = int(os.getenv("LOKI_WORKERS_MAX", "2"))
MAX_DEPTH = int(os.getenv("LOKI_WORKERS_MAX_DEPTH", "2"))

# A role is a specialist: a short brief added to the system prompt and the mode it runs
# in. "plan" mode is read-only (see loki.model_tool_schemas), which is what a reviewer or
# researcher should be.
ROLES = {
    "coder": {
        "mode": "build",
        "brief": ("You are the CODER. Implement exactly the goal you were given, in the "
                  "fewest correct changes. Verify with check_script/validate_scene."),
    },
    "tester": {
        "mode": "build",
        "brief": ("You are the TESTER. Exercise the feature you were given (play_scene, "
                  "probe_scene, check_script) and report precisely what works and what "
                  "fails, with the error text. Fix nothing unless the goal says so."),
    },
    "reviewer": {
        "mode": "plan",
        "brief": ("You are the REVIEWER. Read the relevant files and report concrete "
                  "problems (bugs, risks, missing pieces) with file names. Change nothing."),
    },
    "researcher": {
        "mode": "plan",
        "brief": ("You are the RESEARCHER. Find the facts the goal asks for in the project, "
                  "the Godot API and the skill libraries, and report them concisely with "
                  "where you found each one. Change nothing."),
    },
}
DEFAULT_ROLE = "coder"


def _data_dir() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    if explicit:
        return Path(explicit)
    for candidate in (HERE, *HERE.parents):
        if (candidate / "project.godot").is_file():
            return candidate / "harness_data"
    return HERE / "harness_data"


def jobs_dir(root: Path | None = None) -> Path:
    path = (root or _data_dir()) / "workers" / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> float:
    return time.time()


def _job_path(job_id: str, root: Path | None = None) -> Path:
    safe = "".join(ch for ch in str(job_id) if ch.isalnum())[:32]
    if not safe:
        raise ValueError("bad job id")
    return jobs_dir(root) / (safe + ".json")


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)   # atomic, so a reader never sees half a job


def load(job_id: str, root: Path | None = None) -> dict | None:
    try:
        return json.loads(_job_path(job_id, root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(job: dict, root: Path | None = None) -> None:
    job["updated"] = _now()
    _write_json(_job_path(job["id"], root), job)


def update(job_id: str, root: Path | None = None, **fields) -> dict | None:
    job = load(job_id, root)
    if job is None:
        return None
    job.update(fields)
    save(job, root)
    return job


def all_jobs(root: Path | None = None) -> list:
    jobs = []
    for path in sorted(jobs_dir(root).glob("*.json")):
        if "." in path.stem:   # <id>.conversation.json and friends are not jobs
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("id"):
            jobs.append(data)
    return sorted(jobs, key=lambda j: j.get("created", 0))


def event(job_id: str, kind: str, text: str, who: str = "", root: Path | None = None) -> None:
    """Append one line to a job's event log (best effort, never raises)."""
    try:
        line = {"t": _now(), "kind": kind, "who": who, "text": str(text)[:4000]}
        with open(jobs_dir(root) / (job_id + ".events.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
    except Exception:
        pass


def events(job_id: str, after: int = 0, root: Path | None = None) -> list:
    path = jobs_dir(root) / (job_id + ".events.jsonl")
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines()[after:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# --- creating, messaging, cancelling ---------------------------------------------------

def create(goal: str, role: str = DEFAULT_ROLE, parent: str = "", workspace: str = "",
           model: str = "", allow_dangerous: bool = False, root: Path | None = None) -> dict:
    """Queue a job. Raises ValueError for an empty goal or a delegation that is too deep."""
    goal = str(goal or "").strip()
    if not goal:
        raise ValueError("a worker needs a goal")
    role = role if role in ROLES else DEFAULT_ROLE
    depth = 0
    if parent:
        parent_job = load(parent, root)
        depth = int((parent_job or {}).get("depth", 0)) + 1
        if depth > MAX_DEPTH:
            raise ValueError("delegation depth %d exceeds LOKI_WORKERS_MAX_DEPTH=%d"
                             % (depth, MAX_DEPTH))
    job = {
        "id": uuid.uuid4().hex[:10],
        "role": role,
        "goal": goal[:4000],
        "parent": parent,
        "depth": depth,
        "workspace": str(workspace),
        "model": str(model),
        "allow_dangerous": bool(allow_dangerous),
        "status": "queued",
        "created": _now(),
        "started": 0,
        "finished": 0,
        "pid": 0,
        "result": "",
        "usage": "",
        "files": [],
        "verification": "",
    }
    save(job, root)
    event(job["id"], "created", "%s: %s" % (role, goal[:300]), who=parent or "user", root=root)
    return job


def send_message(job_id: str, text: str, sender: str = "user", root: Path | None = None) -> bool:
    """Leave a message for a running worker; it reads it before its next model call."""
    job = load(job_id, root)
    if job is None or job.get("status") in FINISHED:
        return False
    with open(jobs_dir(root) / (job_id + ".inbox.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": _now(), "from": sender, "text": str(text)[:4000]}) + "\n")
    event(job_id, "message", str(text)[:300], who=sender, root=root)
    return True


def drain_inbox(job_id: str, root: Path | None = None) -> list:
    """Read and clear a worker's inbox (called by the worker itself)."""
    path = jobs_dir(root) / (job_id + ".inbox.jsonl")
    if not path.is_file():
        return []
    claimed = path.with_suffix(".claimed")
    try:
        os.replace(path, claimed)
    except OSError:
        return []
    out = []
    for line in claimed.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    claimed.unlink(missing_ok=True)
    return out


def cancel(job_id: str, root: Path | None = None) -> bool:
    job = load(job_id, root)
    if job is None or job.get("status") in FINISHED:
        return False
    if job.get("status") == "queued":
        update(job_id, root, status="cancelled", finished=_now(), result="cancelled before it started")
        event(job_id, "cancelled", "cancelled before it started", root=root)
        return True
    (jobs_dir(root) / (job_id + ".cancel")).write_text("1", encoding="utf-8")
    event(job_id, "cancel", "cancel requested", root=root)
    return True


def cancel_requested(job_id: str, root: Path | None = None) -> bool:
    return (jobs_dir(root) / (job_id + ".cancel")).exists()


# --- the supervisor: start queued jobs, notice dead ones -------------------------------

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                                 capture_output=True, text=True, timeout=10).stdout
            return str(pid) in out
        except Exception:
            return True   # cannot tell - do not declare it dead
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:   # a finished child we started is a zombie until reaped
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True
    except OSError:
        return True


def reap(root: Path | None = None) -> list:
    """Mark jobs whose process died without reporting as failed. Returns their ids."""
    dead = []
    for job in all_jobs(root):
        if job.get("status") == "working" and not _pid_alive(int(job.get("pid") or 0)):
            update(job["id"], root, status="failed", finished=_now(),
                   result=job.get("result") or "the worker process exited without a report")
            event(job["id"], "failed", "worker process exited without a report", root=root)
            dead.append(job["id"])
    return dead


def running(root: Path | None = None) -> list:
    return [j for j in all_jobs(root) if j.get("status") == "working"]


def _launch(job: dict, root: Path | None) -> int:
    env = dict(os.environ)
    if root is not None:
        env["LOKI_DATA"] = str(root)
    if job.get("workspace"):
        env["LOKI_WORKSPACE"] = job["workspace"]
        env["GAME_PROJECT"] = job["workspace"]
    if job.get("model"):
        env["LOKI_MODEL"] = job["model"]
    log = open(jobs_dir(root) / (job["id"] + ".log"), "a", encoding="utf-8")
    kwargs = {"stdout": log, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL,
              "cwd": str(HERE), "env": env}
    if os.name == "nt":
        # Keep running if the editor/bridge closes, and never pop up a console window.
        kwargs["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, str(HERE / "worker.py"), job["id"]], **kwargs)
    return proc.pid


def start_pending(root: Path | None = None, launcher=None) -> list:
    """Start queued jobs, oldest first, up to MAX_CONCURRENT running. Returns started ids."""
    reap(root)
    launcher = launcher or _launch
    slots = max(0, MAX_CONCURRENT - len(running(root)))
    started = []
    for job in all_jobs(root):
        if slots <= 0:
            break
        if job.get("status") != "queued":
            continue
        update(job["id"], root, status="working", started=_now())
        try:
            pid = launcher(job, root)
        except Exception as exc:
            update(job["id"], root, status="failed", finished=_now(), result="could not start: %s" % exc)
            event(job["id"], "failed", "could not start: %s" % exc, root=root)
            continue
        update(job["id"], root, pid=pid)
        event(job["id"], "started", "pid %s" % pid, root=root)
        started.append(job["id"])
        slots -= 1
    return started


# --- what people and agents read -------------------------------------------------------

def report(job: dict) -> str:
    """A job as one block of text, for the dock, the CLI and a parent agent."""
    head = "[%s] %s %s - %s" % (job.get("id"), job.get("role"), job.get("status"),
                                str(job.get("goal", ""))[:160])
    lines = [head]
    if job.get("parent"):
        lines.append("  delegated by " + job["parent"])
    if job.get("result"):
        lines.append("  result: " + str(job["result"])[:1500])
    if job.get("verification"):
        lines.append("  " + str(job["verification"])[:400])
    if job.get("usage"):
        lines.append("  usage: " + str(job["usage"]))
    return "\n".join(lines)


def render(jobs: list) -> str:
    if not jobs:
        return "no background agents"
    icons = {"queued": ".", "working": "*", "done": "x", "blocked": "!", "failed": "E",
             "cancelled": "-"}
    lines = []
    for job in jobs:
        lines.append("%s %-10s %-10s %-9s %s" % (
            icons.get(job.get("status"), "?"), job.get("id"), job.get("role"),
            job.get("status"), str(job.get("goal", ""))[:80]))
    counts = {s: sum(1 for j in jobs if j.get("status") == s) for s in STATUSES}
    lines.append("")
    lines.append("   ".join("%s %d" % (s, counts[s]) for s in STATUSES if counts[s]))
    blocked = [j["id"] for j in jobs if j.get("status") == "blocked"]
    if blocked:
        lines.append("needs attention: " + ", ".join(blocked))
    return "\n".join(lines)


def children(parent: str, root: Path | None = None) -> list:
    return [j for j in all_jobs(root) if j.get("parent") == parent]
