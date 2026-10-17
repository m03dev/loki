"""Job success dashboard: did LOKI's background jobs work, on which model, for what kind of task,
and why did the others fail? (Settings > Lab > Jobs; GET /jobs/stats.)

The owner's rule after session 27: jobs must SUCCEED. This module only measures and explains;
it never changes a job. From the job store (harness_data/jobs.json) plus each job's own files
(harness_data/jobs/<id>.log, <id>.result.txt):

  * success    a job that ended "done" whose final line is not BLOCKED (exit 0 from loki.run_job)
  * kind       picture / research / build / team / selftest / other, from the job itself
  * model      what the job really ran on: the "[loki-job] <id> | model X" line of its log, and the
               model it escalated to ("switching this task to X") when the small model got stuck
  * reasons    the failure, normalised so the same cause counts once ("timed out", "empty replies",
               "stuck in a loop", "BLOCKED: ...", "escalated to a stronger model"...)
  * forecast   for a queued job: how long similar jobs took (engine/forecast.py: TimesFM-3 when
               installed, statistical otherwise) and the recent failure rate of jobs of that kind
  * retry      "retry on a stronger model": the same prompt as a new job, on the best FREE online
               model that is set up (never a paid one on its own) - through the bridge's job_action,
               so the policy decides as for any job.

Standard library only (forecast.py is standard library too unless TimesFM is installed).
"""
from __future__ import annotations

import re
import time
from pathlib import Path

KINDS = ("picture", "research", "build", "team", "selftest", "other")
_PICTURE = re.compile(r"\b(picture|image|photo|drawing|draw|paint|illustrat\w*|png|jpe?g|portrait|wallpaper|video|clip|animation)\b", re.I)
_RESEARCH = re.compile(r"\b(research|find out|look up|search|summari[sz]e|compare|report on|what is|who is|investigate|read about)\b", re.I)
_BUILD = re.compile(r"\b(build|make|create|implement|write|fix|code|add|refactor|website|landing page|game|app|improve loki|feature|test)\b", re.I)
_MODEL_LINE = re.compile(r"\[loki-job\]\s+\S+\s*\|\s*model\s+(\S+)")
_ESCALATED = re.compile(r"switching this task to (\S+?)\.?(?:\s|$)")
FINAL = ("done", "failed", "cancelled")
REASONS = [
    (re.compile(r"timed out", re.I), "timed out"),
    (re.compile(r"empty repl|stopped responding|gave no message", re.I), "the model returned empty replies"),
    (re.compile(r"stuck in a loop|kept repeating", re.I), "stuck in a loop"),
    (re.compile(r"step limit|turn budget|safety ceiling|time budget", re.I), "ran out of steps or time"),
    (re.compile(r"daily paid budget|paid-provider budget", re.I), "hit the paid budget"),
    (re.compile(r"role unavailable|no specialist", re.I), "a specialist (role) was unavailable"),
    (re.compile(r"unavailable|cannot reach|connection refused|not installed|no provider|not configured", re.I), "a model or backend was unavailable"),
    (re.compile(r"not allowed in a background job|DENIED", re.I), "a tool was denied in the background job"),
    (re.compile(r"restarted while|finished while Loki was closed|lost", re.I), "LOKI restarted during the job"),
    (re.compile(r"verif\w* failed|checks? failed|not a real", re.I), "its result failed verification"),
    (re.compile(r"cancelled|canceled", re.I), "cancelled"),
]


def kind_of(job: dict) -> str:
    if job.get("selftest") or str(job.get("title", "")).startswith("Self-test"):
        return "selftest"
    if job.get("team"):
        return "team"
    text = "%s %s" % (job.get("title", ""), str(job.get("prompt", ""))[:600])
    if str(job.get("title", "")).startswith("Improve LOKI"):
        return "build"
    making = re.search(r"\b(make|draw|paint|generate|create|render|build|implement|fix|code)\b", text, re.I)
    if _RESEARCH.search(text) and not making:
        return "research"          # "research the best image models" is research, not a picture
    if _PICTURE.search(text):
        return "picture"
    if _BUILD.search(text):
        return "build"
    return "other"


def _read_tail(path: Path, limit: int = 12000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", "replace")


def _head(path: Path, limit: int = 4000) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def job_files(job: dict, data_dir: Path) -> dict:
    """{log_head, log_tail, result} for a job; '' where missing."""
    base = Path(data_dir) / "jobs"
    jid = re.sub(r"[^A-Za-z0-9_-]", "", str(job.get("id", "")))
    return {"log_head": _head(base / ("%s.log" % jid)), "log_tail": _read_tail(base / ("%s.log" % jid)),
            "result": _read_tail(base / ("%s.result.txt" % jid), 3000)}


def final_line(text: str) -> str:
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.upper().startswith(("DONE", "BLOCKED")):
            return ln[:300]
    return lines[-1][:300] if lines else ""


def succeeded(job: dict, files: dict | None = None) -> bool:
    if job.get("status") != "done":
        return False
    files = files or {}
    last = final_line(files.get("result") or job.get("output") or "")
    return not last.upper().startswith("BLOCKED")


def model_of(job: dict, files: dict | None = None) -> str:
    """The model the job really used (its log), else the one it asked for, else 'default'."""
    files = files or {}
    found = _MODEL_LINE.search(files.get("log_head") or "") or _MODEL_LINE.search(str(job.get("output") or ""))
    model = found.group(1) if found else (str(job.get("model") or "") or (job.get("agent") if job.get("agent") not in ("", "loki") else "") or "default")
    return model[:60]


def escalated_to(job: dict, files: dict | None = None) -> str:
    files = files or {}
    found = _ESCALATED.search((files.get("log_tail") or "") + "\n" + str(job.get("output") or ""))
    return found.group(1).rstrip(".") if found else ""


def reason_of(job: dict, files: dict | None = None) -> str:
    """One normalised failure reason (empty for a success)."""
    files = files or {}
    if succeeded(job, files):
        return ""
    if job.get("status") not in FINAL:
        return ""
    text = " ".join([str(job.get("error") or ""), final_line(files.get("result") or ""),
                     final_line(job.get("output") or ""), (files.get("log_tail") or "")[-1500:]])
    for pattern, label in REASONS:
        if pattern.search(text):
            return label
    last = final_line(files.get("result") or job.get("output") or job.get("error") or "")
    if last.upper().startswith("BLOCKED"):
        words = re.sub(r"[0-9a-f]{6,}|\d+", "#", last[8:].strip(" :-"))
        return "BLOCKED: " + " ".join(words.split()[:10])
    if job.get("exit_code") not in (None, 0):
        return "exited with code %s" % job.get("exit_code")
    return "ended without a DONE line" if job.get("status") == "done" else "failed (no reason recorded)"


def rows(jobs: list, data_dir: Path) -> list:
    """One record per finished job: {id, t, kind, model, ok, reason, escalated, seconds, title}."""
    out = []
    for job in jobs or []:
        if job.get("status") not in FINAL:
            continue
        files = job_files(job, data_dir)
        started, finished = float(job.get("started") or 0), float(job.get("finished") or job.get("updated") or 0)
        out.append({"id": job.get("id", ""), "t": finished or float(job.get("created") or 0),
                    "kind": kind_of(job), "model": model_of(job, files), "ok": succeeded(job, files),
                    "reason": reason_of(job, files), "escalated": escalated_to(job, files),
                    "seconds": round(finished - started, 1) if started and finished >= started else None,
                    "title": str(job.get("title", ""))[:80], "status": job.get("status", "")})
    return sorted(out, key=lambda r: r["t"])


def _rate(items: list) -> dict:
    n = len(items)
    good = sum(1 for r in items if r["ok"])
    return {"n": n, "ok": good, "rate": round(good / n, 3) if n else None}


def stats(jobs: list, data_dir: Path, days: int = 30, now: float | None = None, selftest: dict | None = None) -> dict:
    """The whole dashboard: overall, per day, by model, by kind, top reasons, recent failures."""
    now = time.time() if now is None else now
    recs = [r for r in rows(jobs, data_dir) if r["t"] >= now - days * 86400]
    per_day = []
    for d in range(days - 1, -1, -1):
        start = now - (d + 1) * 86400
        day = [r for r in recs if start <= r["t"] < start + 86400]
        per_day.append({"day": time.strftime("%m-%d", time.localtime(start + 86400)), **_rate(day)})
    by_model: dict = {}
    by_kind: dict = {k: [] for k in KINDS}
    reasons: dict = {}
    for r in recs:
        by_model.setdefault(r["model"], []).append(r)
        by_kind.setdefault(r["kind"], []).append(r)
        if r["reason"]:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
        if r["escalated"]:
            key = "escalated from the small model to %s" % r["escalated"]
            reasons[key] = reasons.get(key, 0) + 1
    failures = [r for r in reversed(recs) if not r["ok"]][:12]
    return {"ok": True, "days": days, "overall": _rate(recs), "per_day": per_day,
            "by_model": sorted(({"model": m, **_rate(v)} for m, v in by_model.items()), key=lambda x: -x["n"]),
            "by_kind": [{"kind": k, **_rate(v)} for k, v in by_kind.items() if v],
            "reasons": sorted(({"reason": k, "n": v} for k, v in reasons.items()), key=lambda x: -x["n"])[:8],
            "failures": failures, "selftest": selftest or {}}


# ------------------------------------------------------------------ forecasts for queued jobs

def outlook(job: dict, history: list, forecaster=None) -> dict:
    """{minutes, minutes_q90, risk, n, backend, line} for a job that has not finished yet."""
    kind = kind_of(job)
    same = [r for r in history if r["kind"] == kind and r["seconds"] is not None][-40:]
    if len(same) < 3:
        same = [r for r in history if r["seconds"] is not None][-40:]
    durations = [r["seconds"] for r in same]
    minutes = minutes_q90 = None
    backend = "none"
    if durations:
        if forecaster is None:
            try:
                import forecast as forecaster  # pylint: disable=import-outside-toplevel
            except Exception:  # noqa: BLE001
                forecaster = None
        if forecaster is not None and len(durations) >= 3:
            try:
                out = forecaster.forecast(durations, horizon=1)
                minutes = max(0.1, float(out["median"][0]) / 60.0)
                minutes_q90 = max(minutes, float(out["q90"][0]) / 60.0)
                backend = out.get("backend", "statistical")
            except Exception:  # noqa: BLE001
                minutes = None
        if minutes is None:
            ordered = sorted(durations)
            minutes = ordered[len(ordered) // 2] / 60.0
            minutes_q90 = ordered[int((len(ordered) - 1) * 0.9)] / 60.0
            backend = "median"
    outcomes = [r for r in history if r["kind"] == kind][-20:]
    # Laplace-smoothed recent failure rate, so one job is not "100% risk".
    risk = round((sum(1 for r in outcomes if not r["ok"]) + 1) / (len(outcomes) + 2), 2)
    line = "Forecast: %s · failure risk %d%% (%s, %d similar job%s)" % (
        ("~%s" % _fmt_minutes(minutes)) + (" (up to %s)" % _fmt_minutes(minutes_q90) if minutes_q90 and minutes_q90 > minutes * 1.2 else "")
        if minutes is not None else "no timing yet", int(risk * 100), kind, len(outcomes), "" if len(outcomes) == 1 else "s")
    return {"minutes": round(minutes, 1) if minutes is not None else None,
            "minutes_q90": round(minutes_q90, 1) if minutes_q90 is not None else None,
            "risk": risk, "n": len(outcomes), "kind": kind, "backend": backend, "line": line}


def _fmt_minutes(m: float | None) -> str:
    if m is None:
        return "?"
    if m < 1:
        return "%d s" % max(1, round(m * 60))
    if m < 90:
        return "%d min" % round(m)
    return "%.1f h" % (m / 60.0)


def annotate(status: dict, store_jobs: list, data_dir: Path, forecaster=None) -> dict:
    """Add `forecast` to every queued/starting job in a Supervisor.status() payload (GET /jobs)."""
    try:
        waiting = {j.get("id"): j for j in store_jobs or [] if j.get("status") in ("queued", "starting")}
        if not waiting:
            return status
        history = rows(store_jobs, data_dir)
        for shown in status.get("jobs") or []:
            raw = waiting.get(shown.get("id"))
            if raw is not None:
                shown["forecast"] = outlook(raw, history, forecaster)
    except Exception:  # noqa: BLE001 - a forecast must never break the jobs list
        pass
    return status


# ------------------------------------------------------------------ retry on a stronger model

def stronger_model(agent, job: dict, files: dict | None = None) -> str:
    """The model to retry a job on: the first FREE online provider that is set up (in LOKI's own
    routing order), never the one it already ran on and never paid on its own. '' when none."""
    used = model_of(job, files)
    escalated = escalated_to(job, files)
    try:
        order = list(agent.routing_order(agent.SMART_ORDER))
    except Exception:  # noqa: BLE001
        order = list(getattr(agent, "ONLINE_ORDER", []) or [])
    for name in order:
        if name in ("local", used, escalated) or name not in getattr(agent, "MODELS", {}):
            continue
        try:
            if agent.provider_tier(name) == "paid" and not agent.paid_allowed_automatically():
                continue
            if not agent.provider_configured(name):
                continue
        except Exception:  # noqa: BLE001
            continue
        return name
    return ""


def retry_stronger(state, data: dict, job_action) -> tuple:
    """POST /jobs/retry_stronger {id}: start the job again on a stronger model."""
    import presence  # pylint: disable=import-outside-toplevel
    jobs = getattr(state, "jobs", None)
    if jobs is None:
        return 503, {"ok": False, "error": "Background jobs are not running."}
    job_id = "".join(ch for ch in str(data.get("id") or "") if ch.isalnum())[:16]
    job = jobs.store.get(job_id)
    if not job:
        return 404, {"ok": False, "error": "no such job"}
    data_dir = Path(getattr(state.agent, "DATA_DIR", ".") or ".")
    model = str(data.get("model") or "") or stronger_model(state.agent, job, job_files(job, data_dir))
    if not model:
        return 400, {"ok": False, "error": "no stronger free model is set up here - connect one in Settings > Connections"}
    try:
        spec = presence.retry_spec(job, model)
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    spec["title"] = ("Retry on %s: %s" % (model, job.get("title") or ""))[:80]
    code, out = job_action(state, "/jobs", spec)
    if out.get("ok"):
        out["model"] = model
    return code, out
