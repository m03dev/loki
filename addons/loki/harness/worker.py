"""Run ONE background job to completion:  python worker.py <job_id>

Started by workers.start_pending() in its own process (see workers.py for why). The job
runs through loki.pursue_goal - so it gets the same routing, failover, paid budget and
DONE verification as a task you start yourself - with four differences that make it safe
to leave alone:

* its conversation is its own (never your chats), saved next to the job;
* it cannot ask you to approve anything, so a dangerous tool is DENIED (unless the job
  was created with allow_dangerous) and it is told to report BLOCKED instead;
* messages sent to it (workers.send_message) are read before each model call;
* a cancel request stops it at the next safe point.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time

os.environ["LOKI_AUTO_APPROVE"] = "0"   # never auto-approve in the background

import workers  # noqa: E402


def _classify(reply: str) -> str:
    head = (reply or "").strip().upper()
    if head.startswith("DONE"):
        return "done"
    if head.startswith("BLOCKED"):
        return "blocked"
    return "blocked"   # stopped without a verdict: a human should look


def _verification_line(reply: str) -> str:
    for line in reversed((reply or "").splitlines()):
        if line.startswith("Verification:"):
            return line
    return ""


def prepare(loki, job: dict) -> None:
    """Point a freshly imported loki at this job: own conversation, role, approvals, hooks."""
    job_id = job["id"]
    role = workers.ROLES.get(job.get("role"), workers.ROLES[workers.DEFAULT_ROLE])
    loki.set_mode(role["mode"])
    os.environ["LOKI_JOB_ID"] = job_id
    loki.CURRENT_JOB_ID = job_id
    brief = (role["brief"] + "\n\nYou are a BACKGROUND agent (job %s). Nobody is watching "
             "live and nobody can approve anything for you. Work the goal to the end, then "
             "reply 'DONE: <what you did and how you verified it>' or 'BLOCKED: <exactly "
             "what you need>'. Your final message is your report to whoever delegated "
             "this, so make it self-contained." % job_id)
    loki.messages[:] = [{"role": "system", "content": loki.system_prompt() + "\n\n" + brief}]

    convo_path = workers.jobs_dir() / (job_id + ".conversation.json")

    def save_history() -> None:
        try:
            convo_path.write_text(json.dumps(loki._sanitize_history(loki.messages)[-80:],
                                             indent=1), encoding="utf-8")
        except Exception:
            pass

    loki.save_history = save_history

    async def approve(kind: str, detail: str) -> bool:
        if job.get("allow_dangerous"):
            workers.event(job_id, "approved", "%s (job allows dangerous tools): %s" % (kind, detail[:200]))
            return True
        workers.event(job_id, "denied", "%s needs approval, which a background agent cannot get: %s"
                      % (kind, detail[:200]))
        return False

    loki.approve = approve

    def progress(kind: str, text: str) -> None:
        workers.event(job_id, kind, text, who=job.get("role", ""))

    loki.loki_progress_callback = progress

    def inbox() -> list:
        return ["Message from %s: %s" % (m.get("from", "someone"), m.get("text", ""))
                for m in workers.drain_inbox(job_id)]

    loki.INBOX_HOOK = inbox


def _watch_cancel(loki, job_id: str, stop: threading.Event) -> None:
    while not stop.wait(1.0):
        if workers.cancel_requested(job_id):
            loki.request_cancel()
            return


def run(job_id: str) -> int:
    job = workers.load(job_id)
    if job is None:
        print("no such job: %s" % job_id)
        return 2
    import loki  # noqa: E402 - after the environment is set for this job

    prepare(loki, job)
    stop = threading.Event()
    threading.Thread(target=_watch_cancel, args=(loki, job_id, stop), daemon=True).start()
    started = time.time()
    status, result = "failed", ""
    try:
        result = asyncio.run(loki.pursue_goal(job["goal"]))
        status = _classify(result)
    except loki.BudgetExhausted as exc:
        status = "cancelled" if workers.cancel_requested(job_id) else "blocked"
        result = "stopped: %s" % exc.reason
    except loki.ModelUnavailable as exc:
        status, result = "failed", "no model available: %s" % loki.short_error(str(exc), 300)
    except Exception as exc:   # noqa: BLE001 - a worker must always report
        status, result = "failed", "%s: %s" % (type(exc).__name__, exc)
    finally:
        stop.set()
    workers.update(job_id, status=status, finished=time.time(), result=result[:6000],
                   usage=loki.usage_summary(), files=list(loki._task_files),
                   verification=_verification_line(result), route=list(loki.ROUTE_TRACE),
                   seconds=round(time.time() - started, 1))
    workers.event(job_id, status, result[:1500], who=job.get("role", ""))
    try:
        workers.start_pending()   # keep the queue moving even with no bridge running
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(run(sys.argv[1]))
