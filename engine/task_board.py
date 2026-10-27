"""The task board: what LOKI's agents were asked to do, what they finished, what failed and why - in one place
(owner 2026-10-27: "why hasnt windows been working by itself ... there should be a clear finished jobs and tasks i
dont understand what theyve been doing").

What was wrong (the PC, 2026-10-27): the autopilot started each LOKI_TASKS.md request ONCE. When its team ended with
"needs you: Builder could not finish" (159 of 281 teams), nothing noticed - the request was never tried again, never
reported, the box never changed - and the four standing goals filled the night. This module is the record:

  rows      one per request or standing goal the autopilot started: what, which machine, the team, running / done /
            failed / waiting to retry, how many tries, the verdict in plain words, what it made (files) and its answer
  retry     a request whose team failed is tried again (RETRIES more times, RETRY_AFTER_S apart), told why the last
            try failed; after that it is "failed - needs you" with the reason, never silently dropped
  goals     a standing goal that failed GOAL_FAILS times in a row rests GOAL_REST_S, so requests and working goals
            get the machine
  report    <data>/reports/tasks.md - the same board as plain text, rewritten whenever it changes

Served at GET /tasks/board (loki_bridge), shown in Lab > Tasks (app/ui/task_board.js). POST /tasks/retry {id} tries one
again now, POST /tasks/dismiss {id} takes a finished row off the board. Never edits LOKI_TASKS.md (a tracked file: a
machine that edits it blocks its own updates).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

RETRIES = int(os.getenv("LOKI_TASK_RETRIES", "2") or 2)               # tries after the first
RETRY_AFTER_S = float(os.getenv("LOKI_TASK_RETRY_S", "1200") or 1200)  # 20 min between tries
GOAL_FAILS = int(os.getenv("LOKI_GOAL_FAILS", "3") or 3)
GOAL_REST_S = float(os.getenv("LOKI_GOAL_REST_S", "21600") or 21600)  # 6 h
KEEP = 300
# what an agent makes lands in these folders of the workspace (LOKI Projects/Home)
MADE_DIRS = ("images", "sprites", "models", "renders", "turnarounds", "music", "audio", "video", "videos", "brand",
             "scenes", "qa", "pipeline", "docs", "library")
MADE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".glb", ".gltf", ".fbx", ".obj", ".blend", ".mp4", ".webm",
            ".wav", ".mp3", ".ogg", ".flac", ".md", ".txt", ".json", ".svg", ".pdf"}


def verdict_ok(verdict: str) -> bool | None:
    """True = the team finished its work, False = it did not, None = not finished yet / unknown."""
    v = str(verdict or "").strip().lower()
    if not v:
        return None
    if v.startswith(("needs you", "failed", "cancelled", "blocked")):
        return False
    return True   # "verified: every check passed", "finished", "dry run ..."


def plain(verdict: str, status: str) -> str:
    """The verdict in words the owner reads at a glance."""
    v = str(verdict or "")
    m = re.match(r"needs you: (\w+) could not finish", v)
    if m:
        return "The %s could not finish its part." % m.group(1)
    if v.startswith("needs you: checks still fail"):
        return "Built, but its checks still fail after a fix round."
    if v.startswith("verified"):
        return "Done and checked."
    if v == "finished":
        return "Done."
    if status == "cancelled":
        return "Stopped."
    return v[:200]


def _answer(job_id: str, data_dir: Path, job_get: Callable[[str], Any]) -> str:
    """A job's last answer: its result file, else the end of its log (DONE:/BLOCKED: marker kept as the first word)."""
    text = ""
    try:
        text = (Path(data_dir) / "jobs" / (job_id + ".result.txt")).read_text(encoding="utf-8").strip()
    except OSError:
        pass
    if not text:
        job = job_get(job_id) or {}
        out = str(job.get("output") or job.get("error") or "")
        m = re.search(r"((?:DONE|BLOCKED|NOT DONE)\b[\s\S]{0,900})\s*$", out)
        text = (m.group(1) if m else out[-600:]).strip()
    return re.sub(r"\n{3,}", "\n\n", text)[:900]


def why_failed(team: dict, data_dir: Path, job_get: Callable[[str], Any]) -> str:
    """The first concrete reason a team's work failed: the failing job's BLOCKED line or error."""
    for role, job_id in (team.get("jobs") or {}).items():
        job = job_get(job_id) or {}
        if job.get("status") not in ("failed", "cancelled"):
            continue
        text = _answer(job_id, data_dir, job_get) or str(job.get("error") or "")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        line = next((ln for ln in lines if ln.startswith(("BLOCKED", "NOT DONE"))), lines[0] if lines else "")
        return ("%s: %s" % (role.split("#")[0].capitalize(), line))[:300]
    return ""


def made_files(workspace: Path, since: float, until: float, most: int = 12) -> list:
    """Files an agent made in the workspace between since and until (relative paths, newest first)."""
    if not workspace or not since:
        return []
    until = until or time.time()
    found = []
    for name in MADE_DIRS:
        root = Path(workspace) / name
        if not root.is_dir():
            continue
        try:
            for p in root.rglob("*"):
                if p.suffix.lower() not in MADE_EXT or not p.is_file() or any(x.startswith(".") for x in p.parts):
                    continue
                t = p.stat().st_mtime
                if since - 5 <= t <= until + 60:
                    found.append((t, str(p.relative_to(workspace)).replace("\\", "/")))
        except OSError:
            continue
    found.sort(reverse=True)
    return [rel for _, rel in found[:most]]


def row_for(key: str, entry: dict, attempts: dict, team: dict | None, data_dir: Path, workspace: Path | None,
            job_get: Callable[[str], Any], machine: str, now: float) -> dict:
    kind = "request" if not key.startswith("always-") else "goal"
    tries = attempts.get(key) or {}
    row = {"id": key, "kind": kind, "text": entry.get("text", ""), "goal": entry.get("goal", ""), "machine": machine,
           "team": entry.get("team", ""), "started": entry.get("t", 0), "finished": 0, "tries": int(tries.get("n") or 1),
           "max_tries": RETRIES + 1 if kind == "request" else 1, "status": "running", "summary": "", "why": "",
           "answer": "", "files": [], "next_try": 0}
    if not entry.get("team"):
        row.update(status="failed", summary="Could not start a team.", why=str(entry.get("reply") or "")[:300],
                   finished=entry.get("t", 0))
        return row
    if team is None:
        row.update(status="unknown", summary="This team's record is gone (LOKI was reinstalled or cleaned up).")
        return row
    row["finished"] = team.get("finished") or 0
    ok = verdict_ok(team.get("verdict")) if team.get("status") != "working" else None
    if team.get("status") == "working":
        row.update(status="running", summary="Working - stage %s." % (team.get("stage") or "plan"))
    elif team.get("status") == "cancelled":
        row.update(status="failed", summary="Stopped.")
    elif ok and (entry.get("proof") or {}).get("ok") is False:
        # the team said done; the outcome says otherwise (engine/proof.py)
        problems = (entry.get("proof") or {}).get("problems") or ["nothing real was made"]
        row.update(status="failed", summary="Said it was done - it was not.", why="; ".join(problems)[:300], proof=entry["proof"])
        if kind == "request" and row["tries"] < row["max_tries"] and not tries.get("given_up"):
            row.update(status="retrying", next_try=float(tries.get("next") or 0) or (row["finished"] + RETRY_AFTER_S))
    elif ok:
        pr = entry.get("proof") or {}
        row.update(status="done", summary=plain(team.get("verdict"), team.get("status"))
                   + (" Proven: %s." % ", ".join(pr["evidence"][:3]) if pr.get("evidence") else ""), proof=pr or None)
    else:
        row.update(status="failed", summary=plain(team.get("verdict"), team.get("status")),
                   why=why_failed(team, data_dir, job_get))
        nxt = float(tries.get("next") or 0)
        if kind == "request" and row["tries"] < row["max_tries"] and not tries.get("given_up"):
            row.update(status="retrying", next_try=nxt or (row["finished"] + RETRY_AFTER_S))
    builder = next((j for r, j in (team.get("jobs") or {}).items() if r.startswith(("builder", "artist", "maker"))),
                   None) or next(iter((team.get("jobs") or {}).values()), None)
    if builder and row["status"] in ("done", "failed", "retrying"):
        row["answer"] = _answer(builder, data_dir, job_get)
    if workspace is not None and row["status"] != "running":
        row["files"] = made_files(Path(team.get("workspace") or workspace), row["started"], row["finished"])
    return row


def prove(entry: dict, team: dict, data_dir: Path, job_get: Callable[[str], Any], agent: Any = None) -> dict:
    """engine/proof.py on a team that says it is done: what was asked, what appeared in its folder, what it answered."""
    import proof  # pylint: disable=import-outside-toplevel
    ws = Path(team.get("workspace") or getattr(agent, "WORKSPACE", "") or ".")
    files = made_files(ws, float(entry.get("t") or team.get("created") or 0), float(team.get("finished") or time.time()), most=40)
    answers = []
    for role, job_id in (team.get("jobs") or {}).items():
        answers.append(_answer(job_id, Path(data_dir), job_get))
    try:
        return proof.check(entry.get("text", ""), files, "\n".join(answers), ws)
    except Exception as exc:  # noqa: BLE001 - a broken check never blocks the board; it says so
        return {"ok": True, "problems": [], "evidence": [], "error": "proof check failed: %s" % exc}


def build(started: dict, attempts: dict, teams_get: Callable[[str], Any], job_get: Callable[[str], Any],
          data_dir: Path, workspace: Path | None, machine: str = "", dismissed=(), now: float | None = None) -> dict:
    """The board: newest first, plus counts."""
    now = time.time() if now is None else now
    rows = []
    for key, entry in sorted(started.items(), key=lambda kv: kv[1].get("t", 0), reverse=True)[:KEEP]:
        if key in dismissed:
            continue
        team = None
        if entry.get("team"):
            try:
                team = teams_get(entry["team"])
            except Exception:  # noqa: BLE001
                team = None
        rows.append(row_for(key, entry, attempts, team, Path(data_dir), workspace, job_get, machine, now))
    counts: dict = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"ok": True, "machine": machine, "rows": rows, "counts": counts, "updated": now}


def report_text(board: dict) -> str:
    """The board as plain text (<data>/reports/tasks.md)."""
    def when(t):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "-"
    groups = [("Needs you (failed after every try)", "failed"), ("Trying again soon", "retrying"), ("Working now", "running"),
              ("Finished", "done")]
    out = ["# LOKI tasks on %s" % (board.get("machine") or "this computer"),
           "", "Updated %s. %s" % (when(board.get("updated")), ", ".join("%d %s" % (n, k) for k, n in sorted(board["counts"].items()))), ""]
    for title, status in groups:
        rows = [r for r in board["rows"] if r["status"] == status and r["kind"] == "request"]
        goals = [r for r in board["rows"] if r["status"] == status and r["kind"] == "goal"]
        if not rows and not goals:
            continue
        out.append("## %s" % title)
        for r in rows + goals[:15]:
            out.append("- %s **%s** (%s, try %d/%d) - %s" % (when(r["finished"] or r["started"]), r["text"][:140],
                                                             "request" if r["kind"] == "request" else "standing goal",
                                                             r["tries"], r["max_tries"], r["summary"]))
            if r["why"]:
                out.append("  - why: %s" % r["why"])
            if r["files"]:
                out.append("  - made: %s" % ", ".join(r["files"][:6]))
        out.append("")
    return "\n".join(out) + "\n"


def write_report(board: dict, data_dir: Path) -> str:
    path = Path(data_dir) / "reports" / "tasks.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report_text(board), encoding="utf-8")
        (Path(data_dir) / "task_board.json").write_text(json.dumps(board, indent=1)[:4_000_000], encoding="utf-8")
        return str(path)
    except OSError:
        return ""


# ------------------------------------------------------------------ the autopilot's side
def note_finished(attempts: dict, key: str, ok: bool, finished: float, why: str = "") -> dict:
    """A request's team ended: count the try, plan the next one or give up. Returns its attempts entry."""
    entry = attempts.setdefault(key, {"n": 1})
    if entry.get("seen_finish") == finished:
        return entry
    entry["seen_finish"] = finished
    entry["last_ok"] = bool(ok)
    if ok:
        entry.pop("next", None)
        return entry
    entry.setdefault("reasons", []).append(why[:300])
    entry["reasons"] = entry["reasons"][-4:]
    if int(entry.get("n") or 1) > RETRIES:
        entry["given_up"] = True
        entry.pop("next", None)
    else:
        entry["next"] = finished + RETRY_AFTER_S
    return entry


def retry_due(attempts: dict, key: str, now: float) -> bool:
    entry = attempts.get(key) or {}
    return bool(entry.get("next")) and not entry.get("given_up") and not entry.get("last_ok") and now >= float(entry["next"])


def retry_text(text: str, attempts: dict, key: str) -> str:
    """The request again, with why the last tries failed - so the next team does not repeat it. Call it after the
    try is counted (attempts[key]["n"] is the try about to start)."""
    reasons = [r for r in (attempts.get(key) or {}).get("reasons", []) if r]
    if not reasons:
        return text
    return text + ("\n\n(Try %d of %d. Earlier tries failed - do NOT repeat this: %s. Use another approach, a different tool "
                   "or model, and check the result exists before you say DONE.)"
                   % (int((attempts.get(key) or {}).get("n") or 1), RETRIES + 1, " | ".join(r.rstrip(". ") for r in reasons[-2:])))


def goal_resting(goal_fails: dict, goal: str, now: float) -> bool:
    entry = goal_fails.get(goal) or {}
    return float(entry.get("rest_until") or 0) > now


def note_goal(goal_fails: dict, goal: str, ok: bool, finished: float) -> None:
    entry = goal_fails.setdefault(goal, {"fails": 0})
    if entry.get("seen") == finished:
        return
    entry["seen"] = finished
    if ok:
        entry.update(fails=0, rest_until=0)
        return
    entry["fails"] = int(entry.get("fails") or 0) + 1
    if entry["fails"] >= GOAL_FAILS:
        entry.update(fails=0, rest_until=finished + GOAL_REST_S)
