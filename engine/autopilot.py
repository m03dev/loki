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

    def duty_evolve(self) -> str:
        if self.evolve is None or self.improve is None:
            return ""
        jobs = getattr(self.state, "jobs", None)

        def job_status(job_id: str):
            try:
                job = jobs.store.get(job_id) if jobs is not None else None
            except Exception:  # noqa: BLE001
                job = None
            return job.get("status") if job else None
        for item_id, outcome in self.evolve.settle(job_status):
            self._log("evolve", "%s %s" % (item_id, "shipped" if outcome == "shipped" else "did not ship; it will be tried again"))
        line = self.evolve.step(self.improve)
        if line:
            self._log("evolve", line)
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

    # ------------------------------------------------------------ the loop
    def tick(self) -> list:
        """One pass: at most one duty. Returns [(duty, result)] for what ran."""
        if not self.enabled():
            return []
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
