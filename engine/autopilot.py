"""Autopilot: LOKI keeps working when nobody is asking it anything.

The owner's goal is an app that runs itself like a company: healthy without being told,
learning from its own work, and picking up the jobs it was given. The autopilot is the
small loop that does that on every machine running the engine. It only acts when LOKI is
IDLE (no chat or task in flight, no background job running, no request for a while), does
one duty per pass, and every action is an event (`autopilot.*`) the work strip and the
world show, plus a line in harness_data/autopilot.json.

Duties, each on its own interval:

  health   run the System check; apply only the fixes that are always safe (bring
           providers back, warm Laya, start Ollama, restart the job runner). Never switches
           a provider off, approves anything, updates or spends - those stay with the owner.
  inbox    take the oldest open `[loki]` request in ZIVA_TASKS.md (the owner's channel for
           "a job for LOKI's own agents") and start it as a team. One at a time; each
           request is started once. The repo file is never edited (that would block the
           updater); what was started is recorded in autopilot.json and as an event.
  evolve   (LOKI_EVOLVE, engine/evolve.py) take the next step of LOKI growing its own
           personal-agent core - docs/EVOLVE.md and the owner's ideas from Settings > Lab - and
           hand it to improve_loki (own worktree, all tests, ship). One at a time; outcomes are
           kept and fed to the next attempt, so it learns what works.
  schedules  (session 27, engine/schedules.py - Hermes Agent's cron) the owner's scheduled tasks
           ("every weekday at 9am ...", tool `schedule_task`): a due one becomes a background job
           at its time, idle or not (one per pass; a schedule never runs twice at once).
  review   (session 28, engine/self_review.py, where evolve is on) once a week, read what LOKI learned
           and add up to 3 "LOKI's idea" proposals to Settings > Lab; they wait for the owner's OK.
  speed    (session 28, engine/speed_watch.py, where evolve is on) once a week, the slowest measured
           step becomes an evolve idea.
  selftest (session 28, engine/selftest.py, LOKI_SELFTEST auto = the PC) once a day, 3 cheap background
           jobs checked from their files; settled every pass; a worse run is a regression.
  creation (session 28, engine/creative.py) one picture a day from the owner's starred styles and
           subjects (a fox by default) - LOKI_DAILY_CREATION on|off|auto (auto: on with an NVIDIA GPU,
           off on the Mac).
  report   once a week, write "what LOKI learned": requests and verified work, the best
           provider per team role, routing changes since the last report, tool-call repairs,
           and whether there is enough verified work to train (tools/self_improve.py
           schedule does the training itself).

    LOKI_AUTOPILOT=on|off            (default on)
    LOKI_AUTOPILOT_IDLE_S            quiet time before it acts (default 600)
    LOKI_AUTOPILOT_HEALTH_S          (default 21600 = 6h)
    LOKI_AUTOPILOT_INBOX=on|off      (default on)   LOKI_AUTOPILOT_INBOX_S (default 900)
    LOKI_AUTOPILOT_REPORT_S          (default 604800 = a week)

Everything outside is injected (state, agent, teams, check runner, clock), so
tests/test_autopilot.py runs it with fakes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

AUTO_FIXES = ("revive_providers", "laya_warm", "start_ollama", "jobs_start")
ACTIVE_JOB = ("queued", "starting", "working")
_INBOX_RE = re.compile(r"^\s*-\s*\[\s\]\s*\[loki\]\s*(.+?)\s*$", re.I)


def _env_on(name: str, default: str = "on") -> bool:
    return str(os.getenv(name, default)).strip().lower() not in ("0", "off", "false", "no")


def _env_s(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _emit(kind: str, payload: dict) -> None:
    try:
        import events  # pylint: disable=import-outside-toplevel
        events.emit(kind, "LOKI autopilot", payload)
    except Exception:  # noqa: BLE001 - observing must never break the loop
        pass


def inbox_requests(path: Path) -> list:
    """Open `[loki]` requests in ZIVA_TASKS.md, oldest first: [{"id", "text"}]."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    in_requests = False
    for line in lines:
        if line.startswith("## "):
            in_requests = line.strip().lower().startswith("## requests")
            continue
        if not in_requests:
            continue
        match = _INBOX_RE.match(line)
        if match:
            text = match.group(1).strip()
            out.append({"id": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12], "text": text})
    return out


class Autopilot:
    def __init__(self, state: Any = None, agent: Any = None, data_dir: Path | None = None,
                 repo: Path | None = None, clock: Callable[[], float] = time.time,
                 run_check: Callable[[], dict] | None = None,
                 apply_fix: Callable[[str, dict], dict] | None = None,
                 start_team: Callable[[str], str] | None = None,
                 evolve: Any = None, improve: Callable[[str], str] | None = None) -> None:
        self.state = state
        self.agent = agent
        self.clock = clock
        base = data_dir or Path(getattr(agent, "DATA_DIR", None) or ".")
        self.path = Path(base) / "autopilot.json"
        self.reports = Path(base) / "reports"
        self.repo = repo or Path(__file__).resolve().parent.parent
        self.run_check = run_check
        self.apply_fix = apply_fix
        self.start_team = start_team or (getattr(agent, "start_team", None) if agent is not None else None)
        self.evolve = evolve
        self.improve = improve or (getattr(agent, "improve_loki", None) if agent is not None else None)
        self.lock = threading.Lock()
        self.data = self._load()
        self.schedules = None
        try:   # scheduled tasks (engine/schedules.py); optional
            import schedules as _schedules  # pylint: disable=import-outside-toplevel
            self.schedules = _schedules.Schedules(Path(base) / "schedules.json", clock=self.clock)
        except Exception:  # noqa: BLE001
            self.schedules = None

    # ------------------------------------------------------------ persistence
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data.setdefault("last", {})
        data.setdefault("started", {})
        data.setdefault("log", [])
        data.setdefault("order", [])
        return data

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def _log(self, duty: str, text: str, **extra: Any) -> None:
        entry = {"t": self.clock(), "duty": duty, "text": text[:400]}
        entry.update(extra)
        self.data["log"] = (self.data["log"] + [entry])[-60:]
        _emit("autopilot.%s" % duty, dict(entry))

    # ------------------------------------------------------------ when to act
    @staticmethod
    def enabled() -> bool:
        return _env_on("LOKI_AUTOPILOT")

    def idle(self) -> tuple:
        """(idle, why not). Quiet means: no request in flight, no job running, no recent ask."""
        state = self.state
        if state is not None and hasattr(state, "try_busy"):
            held = state.try_busy()
            if held is None:
                return False, "a request is running"
            state.release_busy(held)
        jobs = getattr(state, "jobs", None)
        if jobs is not None:
            try:
                if any(j.get("status") in ACTIVE_JOB for j in jobs.store.all()):
                    return False, "a background job is running"
            except Exception:  # noqa: BLE001
                pass
        quiet = _env_s("LOKI_AUTOPILOT_IDLE_S", 600)
        last = float(getattr(state, "last_request_at", 0) or 0)
        if last and self.clock() - last < quiet:
            return False, "the owner asked something %ds ago" % int(self.clock() - last)
        return True, ""

    def due(self, duty: str, every_s: float) -> bool:
        return self.clock() - float(self.data["last"].get(duty, 0) or 0) >= every_s

    # ------------------------------------------------------------ duties
    def duty_health(self) -> str:
        if self.run_check is None:
            return ""
        report = self.run_check() or {}
        fixed, left = [], []
        for row in report.get("results") or []:
            if row.get("status") != "fail":
                continue
            action = ((row.get("fix") or {}).get("action") or "")
            if action in AUTO_FIXES and self.apply_fix is not None:
                outcome = self.apply_fix(action, (row.get("fix") or {}).get("args") or {})
                (fixed if outcome.get("ok") else left).append(row.get("title", row.get("id", "?")))
            else:
                left.append(row.get("title", row.get("id", "?")))
        line = (report.get("summary") or {}).get("line", "checked")
        if fixed:
            line += " Fixed on its own: %s." % ", ".join(fixed)
        if left:
            line += " Needs the owner: %s." % ", ".join(left)
        self._log("health", line, fixed=fixed, needs_owner=left)
        return line

    def duty_inbox(self) -> str:
        if self.start_team is None:
            return ""
        for team_id in [v.get("team") for v in self.data["started"].values() if v.get("open")]:
            if team_id and self._team_running(team_id):
                return ""            # one autopilot team at a time
        for item in inbox_requests(self.repo / "ZIVA_TASKS.md"):
            if item["id"] in self.data["started"]:
                continue
            reply = str(self.start_team(item["text"]) or "")
            match = re.search(r"started team (\S+)", reply)
            self.data["started"][item["id"]] = {"text": item["text"][:300], "t": self.clock(),
                                                "team": match.group(1) if match else "",
                                                "open": bool(match), "reply": reply[:300]}
            self._log("inbox", ("Started a team for: " if match else "Could not start: ") + item["text"][:200],
                      request=item["id"], team=match.group(1) if match else "")
            return reply
        return ""

    def duty_schedules(self) -> str:
        """Start the first due scheduled task as a background job (one per pass)."""
        jobs = getattr(self.state, "jobs", None)
        if self.schedules is None or jobs is None or not hasattr(jobs, "create"):
            return ""
        due = self.schedules.due()
        if not due:
            return ""
        item = due[0]
        last = str(item.get("last_job") or "")
        if last:
            try:
                running = (jobs.store.get(last) or {}).get("status") in ACTIVE_JOB
            except Exception:  # noqa: BLE001
                running = False
            if running:       # still busy with the last run: skip this one, never pile up
                self.schedules.mark_run(item["id"], last)
                self._log("schedules", "Skipped '%s': its last run is still going" % item["title"][:80])
                return ""
        workspace = str(getattr(self.agent, "WORKSPACE", "") or "")
        try:
            job = jobs.create({"backend": "local", "agent": "loki", "prompt": item["prompt"],
                               "title": "Scheduled: " + item["title"], "workspace": workspace})
            job_id = str(job.get("id", ""))
        except Exception as exc:  # noqa: BLE001
            self.schedules.mark_run(item["id"], "")
            self._log("schedules", "Could not start '%s': %s" % (item["title"][:80], exc))
            return ""
        self.schedules.mark_run(item["id"], job_id)
        self._log("schedules", "Started scheduled task '%s' as job %s" % (item["title"][:80], job_id),
                  schedule=item["id"], job=job_id)
        return "started job %s for scheduled task %s" % (job_id, item["id"])

    def duty_evolve(self) -> str:
        if self.evolve is None or self.improve is None:
            return ""
        jobs = getattr(self.state, "jobs", None)

        def job_of(job_id: str):
            try:
                return jobs.store.get(job_id) if jobs is not None else None
            except Exception:  # noqa: BLE001
                return None

        def job_status(job_id: str):
            job = job_of(job_id)
            return job.get("status") if job else None

        def shipped(job_id: str):
            """True when ship_loki left its marker for this job; None when this engine cannot tell."""
            marker = getattr(self.agent, "ship_marker", None)
            if marker is None:
                return None
            try:
                return Path(marker(job_id)).is_file()
            except Exception:  # noqa: BLE001
                return None

        def detail(job_id: str) -> str:
            job = job_of(job_id) or {}
            text = str(job.get("error") or "")
            result = Path(getattr(self.agent, "DATA_DIR", ".")) / "jobs" / ("%s.result.txt" % job_id)
            try:
                text = (result.read_text(encoding="utf-8") or text) if result.is_file() else text
            except OSError:
                pass
            if not text:
                text = str(job.get("output") or "")[-400:]
            lines = [ln for ln in text.strip().splitlines() if ln.strip()]
            final = next((ln for ln in reversed(lines) if ln.strip().upper().startswith(("DONE", "BLOCKED"))), "")
            return final or (lines[-1] if lines else "")
        for item_id, outcome in self.evolve.settle(job_status, shipped=shipped, detail=detail):
            self._log("evolve", "%s %s" % (item_id, "shipped" if outcome == "shipped" else "did not ship; it will be tried again"))
        line = self.evolve.step(self.improve)
        if line:
            self._log("evolve", line)
        return line

    # ------------------------------------------------------------ session 28: LOKI improving itself
    def _store_jobs(self) -> list:
        jobs = getattr(self.state, "jobs", None)
        try:
            return list(jobs.store.all()) if jobs is not None else []
        except Exception:  # noqa: BLE001
            return []

    def _data_dir(self) -> Path:
        return self.path.parent

    def selftest_settle(self) -> str:
        """Close the open daily self-test run once its jobs finished (every pass, idle or not)."""
        jobs = getattr(self.state, "jobs", None)
        if jobs is None:
            return ""
        import selftest as _selftest  # pylint: disable=import-outside-toplevel
        run = _selftest.Selftest(self._data_dir(), clock=self.clock).settle(jobs.store.get)
        if not run:
            return ""
        good = sum(1 for r in run["results"] if r["ok"])
        line = "Daily self-test: %d of %d jobs worked%s." % (
            good, len(run["results"]), " - a REGRESSION (fewer than last time)" if run.get("regression") else "")
        bad = [r for r in run["results"] if not r["ok"]]
        if bad:
            line += " Failed: " + "; ".join("%s (%s)" % (r["task"], r.get("why", "")[:80]) for r in bad)
        self._log("selftest", line, rate=run["rate"], regression=bool(run.get("regression")))
        return line

    def duty_selftest(self) -> str:
        """Once a day: three cheap background jobs on the usual job model (engine/selftest.py)."""
        jobs = getattr(self.state, "jobs", None)
        if jobs is None or not hasattr(jobs, "create"):
            return ""
        import selftest as _selftest  # pylint: disable=import-outside-toplevel
        line = _selftest.Selftest(self._data_dir(), clock=self.clock).start(jobs.create)
        if line:
            self._log("selftest", line)
            if hasattr(jobs, "tick"):
                threading.Thread(target=jobs.tick, daemon=True).start()
        return line

    def _ask_model(self):
        """One plain model call for the self-review (agent._port_ask), or None (rules only)."""
        fn = getattr(self.agent, "_port_ask", None)
        if fn is None or not _env_on("LOKI_SELF_REVIEW_MODEL"):
            return None

        def ask(prompt: str) -> str:
            import asyncio  # pylint: disable=import-outside-toplevel
            return asyncio.run(asyncio.wait_for(fn(prompt, max_tokens=1200), 180))
        return ask

    def duty_review(self) -> str:
        """Once a week (EVOLVE E8): read what LOKI learned, propose up to 3 changes ("LOKI's idea")."""
        if self.evolve is None:
            return ""
        import self_review  # pylint: disable=import-outside-toplevel
        out = self_review.review(self.evolve, self._data_dir(), jobs=self._store_jobs(), ask=self._ask_model(),
                                 now=self.clock())
        titles = [i["id"] for i in out["added"]]
        line = ("Self-review: proposed %s in Settings > Lab (waiting for your OK)." % ", ".join(titles)
                if titles else "Self-review: nothing new to propose this week.")
        self._log("review", line, added=titles, source=out.get("source", ""))
        return line

    def duty_speed(self) -> str:
        """Once a week (EVOLVE E6): the slowest measured step becomes an evolve idea."""
        if self.evolve is None:
            return ""
        import speed_watch  # pylint: disable=import-outside-toplevel
        out = speed_watch.propose(self.evolve, self._data_dir(), jobs=self._store_jobs())
        if out.get("added"):
            line = "Speed watch: the slowest step is %s - added %s to the Lab." % (
                out["slowest"]["label"], out["added"]["id"])
        else:
            line = "Speed watch: %s." % out.get("why", "nothing to add")
        self._log("speed", line)
        return line

    def _team_running(self, team_id: str) -> bool:
        runner = getattr(self.agent, "TEAMS", None)
        try:
            team = runner.get(team_id) if runner is not None else None
        except Exception:  # noqa: BLE001
            team = None
        if team is None:
            # Cannot tell (no runner, or it was lost on a restart): assume it is still
            # going, so the autopilot never starts a second team on top of a live one.
            return True
        running = team.get("status") == "working"
        if not running:
            for entry in self.data["started"].values():
                if entry.get("team") == team_id:
                    entry["open"] = False
        return running

    def duty_report(self) -> str:
        try:
            import experience  # pylint: disable=import-outside-toplevel
        except Exception:  # noqa: BLE001
            return ""
        text, order = learned_report(experience, self.agent, self.data.get("order") or [], self.clock())
        self.data["order"] = order
        try:
            self.reports.mkdir(parents=True, exist_ok=True)
            name = "learned-%s.md" % time.strftime("%Y-%m-%d", time.localtime(self.clock()))
            (self.reports / name).write_text(text, encoding="utf-8")
        except OSError:
            name = ""
        self._log("report", "Wrote what LOKI learned this week (%s)." % (name or "not saved"), file=name)
        return text

    @staticmethod
    def _daily_on() -> bool:
        try:
            import creative  # pylint: disable=import-outside-toplevel
            return creative.daily_enabled()
        except Exception:  # noqa: BLE001
            return False

    def duty_creation(self) -> str:
        """Session 28: one picture a day from the owner's starred styles and subjects (a fox by
        default), when idle. LOKI_DAILY_CREATION on/off; auto = on with an NVIDIA GPU (the PC), off
        on the Mac. engine/creative.py daily_creation; the picture lands in Settings > Creations."""
        if self.agent is None or not hasattr(self.agent, "WORKSPACE"):
            return ""
        import creations  # pylint: disable=import-outside-toplevel
        import creative  # pylint: disable=import-outside-toplevel
        ws = Path(self.agent.WORKSPACE)
        out = creative.daily_creation(lambda prompt, **kw: creations.make_image(self.agent, prompt, **kw),
                                      creations.liked_meta(ws), clock=self.clock)
        if out:
            self._log("creation", out)
        return out

    # ------------------------------------------------------------ the loop
    def tick(self) -> list:
        """One pass: at most one duty. Returns [(duty, result)] for what ran."""
        if not self.enabled():
            return []
        try:   # scheduled tasks run at their time, idle or not
            with self.lock:
                fired = self.duty_schedules()
                if fired:
                    self._save()
            if fired:
                return [("schedules", fired)]
        except Exception as exc:  # noqa: BLE001
            self._log("schedules", "failed: %s: %s" % (type(exc).__name__, exc))
        try:   # the daily self-test is checked as soon as its jobs finish, idle or not
            with self.lock:
                if self.selftest_settle():
                    self._save()
        except Exception as exc:  # noqa: BLE001
            self._log("selftest", "failed: %s: %s" % (type(exc).__name__, exc))
        ok, _why = self.idle()
        if not ok:
            return []
        duties = [("health", _env_s("LOKI_AUTOPILOT_HEALTH_S", 21600), self.duty_health)]
        if _env_on("LOKI_AUTOPILOT_INBOX"):
            duties.append(("inbox", _env_s("LOKI_AUTOPILOT_INBOX_S", 900), self.duty_inbox))
        if self.evolve is not None:
            import evolve as _evolve  # pylint: disable=import-outside-toplevel
            if _evolve.enabled():
                duties.append(("evolve", _env_s("LOKI_EVOLVE_S", 14400), self.duty_evolve))
        duties.append(("report", _env_s("LOKI_AUTOPILOT_REPORT_S", 604800), self.duty_report))
        if self.evolve is not None and __import__("evolve").enabled():
            # session 28: LOKI reviews itself and its speed every week - where evolve builds the ideas
            duties.append(("review", _env_s("LOKI_AUTOPILOT_REVIEW_S", 604800), self.duty_review))
            duties.append(("speed", _env_s("LOKI_AUTOPILOT_SPEED_S", 604800), self.duty_speed))
        try:
            import selftest as _selftest  # pylint: disable=import-outside-toplevel
            if _selftest.enabled():
                duties.append(("selftest", _env_s("LOKI_SELFTEST_S", 86400), self.duty_selftest))
        except Exception:  # noqa: BLE001
            pass
        if self.agent is not None and hasattr(self.agent, "WORKSPACE") and self._daily_on():
            duties.append(("creation", _env_s("LOKI_DAILY_CREATION_CHECK_S", 3600), self.duty_creation))
        with self.lock:
            for name, every, fn in duties:
                if not self.due(name, every):
                    continue
                self.data["last"][name] = self.clock()
                try:
                    out = fn()
                except Exception as exc:  # noqa: BLE001 - one bad duty must not stop the rest
                    out = ""
                    self._log(name, "failed: %s: %s" % (type(exc).__name__, exc))
                self._save()
                return [(name, out)]
        return []

    def status(self) -> dict:
        ok, why = self.idle() if self.enabled() else (False, "switched off (LOKI_AUTOPILOT=off)")
        return {"enabled": self.enabled(), "idle": ok, "waiting_for": why,
                "last": dict(self.data["last"]), "log": list(self.data["log"][-20:]),
                "started": dict(self.data["started"])}

    def run_forever(self, every_s: float = 60.0) -> None:
        while True:
            time.sleep(every_s)
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                print("[autopilot] %s" % exc, flush=True)


# ------------------------------------------------------------------------ the report

def learned_report(experience: Any, agent: Any, last_order: list, now: float) -> tuple:
    """(markdown, current routing order). Plain words, only measured facts."""
    week = [e for e in experience.entries(last=5000) if now - float(e.get("t", 0) or 0) <= 7 * 86400]
    done = sum(1 for e in week if e.get("status") == "done")
    verified = sum(1 for e in week if e.get("outcome") == "verified")
    failed = sum(1 for e in week if e.get("outcome") == "failed")
    lines = ["# What LOKI learned this week", "",
             time.strftime("%Y-%m-%d", time.localtime(now)), "",
             "## Work", "",
             "- %d requests, %d finished, %d with every changed file verified, %d with failed checks."
             % (len(week), done, verified, failed)]
    used: dict = {}
    for e in week:
        if e.get("provider"):
            used[e["provider"]] = used.get(e["provider"], 0) + 1
    if used:
        lines.append("- Models that did the work: " + ", ".join(
            "%s (%d)" % (k, v) for k, v in sorted(used.items(), key=lambda kv: -kv[1])[:8]) + ".")
    lines += ["", "## Best model per team role", ""]
    roles = experience.role_stats()
    if roles:
        for role, per in sorted(roles.items()):
            best = max(per.items(), key=lambda kv: ((kv[1].get("success_rate") or 0), kv[1]["requests"]))
            lines.append("- %s: %s, %d of %d jobs good (%s%%)." % (
                role, best[0], round((best[1].get("success_rate") or 0) * best[1]["requests"]),
                best[1]["requests"], int((best[1].get("success_rate") or 0) * 100)))
    else:
        lines.append("- No team jobs yet, so every role still uses smart routing.")
    order = []
    try:
        order = list(agent.routing_order(agent.SMART_ORDER)) if agent is not None else []
    except Exception:  # noqa: BLE001
        order = []
    lines += ["", "## Routing", ""]
    if order and last_order and order != last_order:
        moved = [p for i, p in enumerate(order[:8]) if p not in last_order[:8] or last_order.index(p) != i]
        lines.append("- Measured results changed the provider order. Now first: %s. Moved: %s."
                     % (", ".join(order[:5]), ", ".join(moved[:6]) or "-"))
    elif order:
        lines.append("- Order unchanged: %s." % ", ".join(order[:5]))
    else:
        lines.append("- Not available in this engine.")
    stats = getattr(agent, "GUARD_STATS", None) if agent is not None else None
    if stats:
        lines += ["", "## Tool calls", "",
                  "- The tool guard repaired %d malformed call(s) and rejected %d with a precise "
                  "error (since the engine started)." % (stats.get("repaired", 0), stats.get("rejected", 0))]
    try:
        fresh = experience.new_examples()
        state = experience.train_state()
    except Exception:  # noqa: BLE001
        fresh, state = 0, {}
    lines += ["", "## Training", "",
              "- %d new verified example(s) since the last training run." % fresh]
    history = state.get("history") or []
    if history:
        last = history[-1]
        lines.append("- Last run: %s, result: %s." % (
            time.strftime("%Y-%m-%d", time.localtime(float(last.get("t", now)))),
            last.get("result", "unknown")))
    else:
        lines.append("- No training run recorded yet (tools/self_improve.py schedule runs it nightly on the PC).")
    return "\n".join(lines) + "\n", order
