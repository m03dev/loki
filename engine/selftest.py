"""Daily self-test: three cheap background jobs that prove LOKI's job loop still works.

Session 27 found every LOKI job failing on the small local model (qwen3:8b) and fixed it. So that a
regression is caught the day it happens, not weeks later, the autopilot (PC by default) starts this
small job set once a day on the model background jobs normally use, and records whether each one
really did its task - checked from the files it had to write, not from what the model said:

  write   write a file with an exact line                        (write_file)
  sum     read numbers from a file and write their sum           (read_file + a little reasoning)
  list    write a markdown list that must contain three words    (write_file, instructions)

History: <DATA_DIR>/selftest.json {"runs": [{t, day, jobs: {task: job_id}, results: [...], rate}]}.
A run whose success rate is below the previous run's is a regression (shown in Settings > Lab > Jobs
and in the autopilot log). Jobs run in <DATA_DIR>/selftest/<day>/, never in the owner's project.

    LOKI_SELFTEST=auto|on|off   auto (default) = only on Windows (the PC is on 24/7)
    LOKI_SELFTEST_S             how often (default 86400 = daily)
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from pathlib import Path

TASKS = [
    {"id": "write", "title": "Self-test: write a file",
     "prompt": "Create the file selftest_hello.txt containing exactly this one line: LOKI self-test OK\n"
               "Use write_file. Then reply DONE: wrote selftest_hello.txt"},
    {"id": "sum", "title": "Self-test: read and add",
     "prompt": "Read the file numbers.txt (one whole number per line), add the numbers up, and write only the "
               "total (digits, nothing else) into the file sum.txt with write_file. Then reply DONE: <the total>"},
    {"id": "list", "title": "Self-test: follow instructions",
     "prompt": "Create the file colours.md: a markdown bullet list ('- ' lines) of the three primary colours of "
               "paint: red, yellow and blue, one per line. Use write_file. Then reply DONE: wrote colours.md"},
]
FINAL = ("done", "failed", "cancelled")


def enabled(env: dict | None = None, platform: str = "") -> bool:
    value = str((env if env is not None else os.environ).get("LOKI_SELFTEST", "auto")).strip().lower()
    if value in ("on", "1", "true", "yes"):
        return True
    if value in ("off", "0", "false", "no"):
        return False
    return (platform or sys.platform) == "win32"


def check(task_id: str, folder: Path, expected: dict) -> tuple:
    """(ok, why) from the files in the job's folder."""
    def read(name):
        try:
            return (folder / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    if task_id == "write":
        text = read("selftest_hello.txt")
        if text is None:
            return False, "selftest_hello.txt was not written"
        return (text.strip() == "LOKI self-test OK"), ("" if text.strip() == "LOKI self-test OK" else "wrong content: %r" % text[:60])
    if task_id == "sum":
        text = read("sum.txt")
        if text is None:
            return False, "sum.txt was not written"
        digits = re.findall(r"-?\d+", text)
        ok = bool(digits) and int(digits[0]) == int(expected.get("sum", -1))
        return ok, "" if ok else "wrong total %r (expected %s)" % (text.strip()[:30], expected.get("sum"))
    if task_id == "list":
        text = read("colours.md")
        if text is None:
            return False, "colours.md was not written"
        lines = [ln.strip().lower() for ln in text.splitlines() if ln.strip().startswith(("-", "*"))]
        ok = all(any(c in ln for ln in lines) for c in ("red", "yellow", "blue"))
        return ok, "" if ok else "the list is missing a colour"
    return False, "unknown task"


class Selftest:
    def __init__(self, data_dir: Path, clock=time.time) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "selftest.json"
        self.clock = clock

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data.setdefault("runs", [])
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def open_run(self) -> dict | None:
        runs = self._read()["runs"]
        return runs[-1] if runs and runs[-1].get("results") is None else None

    def start(self, create_job, model: str = "") -> str:
        """Seed a folder and queue the three jobs with create_job(spec) -> job dict. One run at a time."""
        if self.open_run() is not None:
            return ""
        day = time.strftime("%Y-%m-%d-%H%M", time.localtime(self.clock()))
        folder = self.data_dir / "selftest" / day
        folder.mkdir(parents=True, exist_ok=True)
        rng = random.Random(int(self.clock()))
        numbers = [rng.randint(2, 99) for _ in range(5)]
        (folder / "numbers.txt").write_text("\n".join(str(n) for n in numbers) + "\n", encoding="utf-8")
        expected = {"sum": sum(numbers)}
        started: dict = {}
        errors = []
        for task in TASKS:
            sub = folder / task["id"]
            sub.mkdir(exist_ok=True)
            if task["id"] == "sum":
                (sub / "numbers.txt").write_text((folder / "numbers.txt").read_text(encoding="utf-8"), encoding="utf-8")
            spec = {"backend": "local", "agent": "loki", "prompt": task["prompt"], "title": task["title"],
                    "workspace": str(sub), "isolate": False, "timeout_s": 900}
            if model:
                spec["model"] = model
            try:
                job = create_job(spec)
                started[task["id"]] = str(job.get("id", ""))
            except Exception as exc:  # noqa: BLE001
                errors.append("%s: %s" % (task["id"], exc))
        if not started:
            return "could not start the self-test: " + "; ".join(errors)
        data = self._read()
        data["runs"] = (data["runs"] + [{"t": self.clock(), "day": day, "folder": str(folder), "jobs": started,
                                         "expected": expected, "results": None, "rate": None}])[-60:]
        self._write(data)
        return "started the daily self-test (%d jobs)" % len(started)

    def settle(self, get_job) -> dict | None:
        """When every job of the open run has finished, check the files and close the run."""
        data = self._read()
        if not data["runs"] or data["runs"][-1].get("results") is not None:
            return None
        run = data["runs"][-1]
        jobs = {tid: get_job(jid) for tid, jid in run["jobs"].items()}
        lost = self.clock() - float(run["t"]) > 6 * 3600
        if not lost and any(j is not None and j.get("status") not in FINAL for j in jobs.values()):
            return None
        results = []
        for tid, job in jobs.items():
            folder = Path(run["folder"]) / tid
            if job is None:
                results.append({"task": tid, "ok": False, "why": "the job is gone", "job": run["jobs"][tid]})
                continue
            ok, why = check(tid, Path(job.get("run_dir") or folder), run.get("expected") or {})
            if job.get("status") != "done" and not ok:
                why = "job %s: %s" % (job.get("status"), (job.get("error") or why)[:160])
            seconds = None
            if job.get("started") and job.get("finished"):
                seconds = round(float(job["finished"]) - float(job["started"]), 1)
            results.append({"task": tid, "ok": bool(ok), "why": why, "job": job.get("id", ""),
                            "model": str(job.get("model") or "default"), "seconds": seconds})
        rate = round(sum(1 for r in results if r["ok"]) / len(results), 3) if results else 0.0
        previous = next((r for r in reversed(data["runs"][:-1]) if r.get("rate") is not None), None)
        run.update(results=results, rate=rate, settled=self.clock(),
                   regression=bool(previous is not None and rate < float(previous["rate"])))
        self._write(data)
        return run

    def status(self) -> dict:
        runs = self._read()["runs"]
        done = [r for r in runs if r.get("rate") is not None]
        return {"enabled": enabled(), "running": self.open_run() is not None,
                "last": done[-1] if done else None,
                "history": [{"day": r["day"], "rate": r["rate"], "regression": r.get("regression", False)} for r in done[-30:]]}
