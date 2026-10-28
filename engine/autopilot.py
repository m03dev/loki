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
  inbox    take the oldest open `[loki]` request in LOKI_TASKS.md (the owner's channel for
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
  task_bench (LOKI_TASK_BENCH=on only - off by default since 2026-10-25) nightly, in LOKI_TASK_BENCH_HOURS (default 1-6, local
           time), at most every LOKI_TASK_BENCH_S (20h): tools/task_bench.py on the models in
           LOKI_TASK_BENCH_MODELS (default local,smart) - do LOKI's agents finish real tasks? Scores in
           Settings > Lab. auto = on on the Windows PC, off on the Mac. Nothing else starts while it runs.
  qa       (engine/forge_qa_duty.py, LOKI_FORGE_QA) LOKI tests Forge: every LOKI_FORGE_QA_S (6 h) a sweep over every
           menu, button and command in a headless browser, in the background; new problems become "LOKI's idea (Forge
           QA)" in Settings > Lab for evolve to fix (its own worktree, all tests, tools/ship.py).
  report   once a week, write "what LOKI learned": requests and verified work, the best
           provider per team role, routing changes since the last report, tool-call repairs,
           and whether there is enough verified work to train (tools/self_improve.py
           schedule does the training itself).

    LOKI_AUTOPILOT=on|off            (default on)
    LOKI_AUTOPILOT_IDLE_S            quiet time before it acts (default 600)
    LOKI_AUTOPILOT_HEALTH_S          (default 21600 = 6h)
    LOKI_AUTOPILOT_INBOX=on|off      (default on)   LOKI_AUTOPILOT_INBOX_S (default 120): requests, as slots free up
    LOKI_AUTOPILOT_REPORT_S          (default 604800 = a week)
    LOKI_AUTOPILOT_ALWAYS=on|off     (default OFF since 2026-10-27 - the owner: "pause them for now", focus on the
                                     pipeline's agents) LOKI_AUTOPILOT_ALWAYS_S (default 600): with the inbox empty,
                                     the next standing goals from LOKI_TASKS.md "## Always" (drafts and assets only)
    LOKI_AUTOPILOT_PIPELINE=on|off   (default on)   LOKI_AUTOPILOT_PIPELINE_S (default 120): the asset pipeline
                                     (engine/asset_pipeline.py) runs the next ready stage when none is running
    LOKI_AUTOPILOT_SLOTS             (default 3) requests and standing goals running side by side; work that needs
                                     the GPU (renders, 3D, music, video, installs) runs one at a time in its lane.
                                     New work keeps starting while jobs run (only a request from the owner, a recent
                                     ask, or a drain stops it); it drains when an update waits or a check is overdue
                                     by LOKI_AUTOPILOT_DRAIN_S (default 3600)

Everything outside is injected (state, agent, teams, check runner, clock), so
tests/test_autopilot.py runs it with fakes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
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


def task_bench_enabled() -> bool:
    """LOKI_TASK_BENCH=on to run the nightly test benchmark; off by default on every machine (owner 2026-10-25: "why
    do they keep making this stupid baker" - the bench's 33 test prompts, Dana's bakery among them, ran every night on
    the PC and showed up as work). A developer turns it on for one machine with LOKI_TASK_BENCH=on."""
    value = str(os.getenv("LOKI_TASK_BENCH", "off")).strip().lower()
    return value in ("1", "on", "true", "yes")


def in_hours(window: str, now: float) -> bool:
    """True when the local hour of `now` is inside "1-6" (wraps past midnight: "22-5"); "" = always."""
    window = str(window or "").strip()
    if not window or "-" not in window:
        return True
    try:
        start, end = (int(x) for x in window.split("-", 1))
    except ValueError:
        return True
    hour = time.localtime(now).tm_hour
    return start <= hour <= end if start <= end else (hour >= start or hour <= end)


def _this_os() -> str:
    return "windows" if sys.platform == "win32" else ("mac" if sys.platform == "darwin" else "linux")


def always_goals(path: Path) -> list:
    """The standing goals under "## Always" in LOKI_TASKS.md (`- [loki] ...` lines, [mac]/[windows] respected):
    the work LOKI's agents keep doing when nothing else is asked - drafts and assets, never anything published."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out, inside = [], False
    for line in lines:
        if line.startswith("## "):
            inside = line.strip().lower().startswith("## always")
            continue
        m = re.match(r"^\s*-\s*\[loki\]\s*(.+?)\s*$", line, re.I) if inside else None
        if not m:
            continue
        text = m.group(1)
        want = re.match(r"^\[(windows|mac|linux)\]\s*", text, re.I)
        if want and want.group(1).lower() != _this_os():
            continue
        out.append(text)
    return out


def inbox_requests(path: Path) -> list:
    """Open `[loki]` requests in LOKI_TASKS.md, oldest first: [{"id", "text"}]."""
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
            want = re.match(r"^\[(windows|mac|linux)\]\s*", text, re.I)   # a request for one machine only
            if want and want.group(1).lower() != _this_os():
                continue
            out.append({"id": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12], "text": text})
    return out


# ------------------------------------------------------------------------ work slots
# Owner 2026-10-25: "they can run two at a time or more depending on the task ... i want them making stuff".
# Requests and standing goals run side by side in SLOTS (LOKI_AUTOPILOT_SLOTS, default 3). A task that needs the GPU
# (ComfyUI renders, 3D, music, video, model installs) takes the GPU lane, and only one runs there at a time; light
# work (writing, research, pixel art, code) fills the other slots.
_GPU = re.compile(r"\b(render\w*|comfyui|make_3d|3d|trellis|pixal3d|turntable|music|song|loop|video|clip|trailer|"
                  r"upscale|install\w*|setup_trellis|train\w*|benchmark)\b", re.I)


def lane(text: str) -> str:
    """"gpu" for work that needs the graphics card or a big download, else "light"."""
    return "gpu" if _GPU.search(re.sub(r"`[^`]*`", " ", str(text or ""))) else "light"


def light_machine() -> bool:
    """The Mac mini (or any machine without an NVIDIA GPU) - the one that gives heavy work to the PC (offload.role)."""
    try:
        import offload  # pylint: disable=import-outside-toplevel
        return offload.role() == "light"
    except Exception:  # noqa: BLE001
        return False


def slots() -> int:
    """Work side by side. A light machine runs ONE at a time by default (owner 2026-10-26: "im using loki mac and its
    not very good so slow" - three agents plus standing goals beside the owner's own chat on a 16 GB Mac); the PC 3."""
    return max(1, int(_env_s("LOKI_AUTOPILOT_SLOTS", 1 if light_machine() else 3)))


def always_every_s() -> float:
    """How often standing goals may start: every 10 min on the PC, once an hour on a light machine."""
    return _env_s("LOKI_AUTOPILOT_ALWAYS_S", 3600 if light_machine() else 600)


class Autopilot:
    def __init__(self, state: Any = None, agent: Any = None, data_dir: Path | None = None,
                 repo: Path | None = None, clock: Callable[[], float] = time.time,
                 run_check: Callable[[], dict] | None = None,
                 apply_fix: Callable[[str, dict], dict] | None = None,
                 start_team: Callable[[str], str] | None = None,
                 evolve: Any = None, improve: Callable[[str], str] | None = None,
                 bench_start: Callable[[str], Any] | None = None,
                 qa_start: Callable[[], Any] | None = None) -> None:
        self.state = state
        self.agent = agent
        self.clock = clock
        base = data_dir or Path(getattr(agent, "DATA_DIR", None) or ".")
        self.path = Path(base) / "autopilot.json"
        self.reports = Path(base) / "reports"
        self.repo = repo or Path(__file__).resolve().parent.parent
        self.run_check = run_check
        self.apply_fix = apply_fix
        self.start_team = start_team or (getattr(agent, "start_team_background", None) or getattr(agent, "start_team", None)
                                         if agent is not None else None)
        self.evolve = evolve
        self.improve = improve or (getattr(agent, "improve_loki", None) if agent is not None else None)
        self.bench_start = bench_start      # models -> a Popen-like (tests inject one)
        self.bench_proc = None
        self.qa_start = qa_start            # () -> a Popen-like running tools/forge_qa.py (tests inject one)
        self.qa_proc = None
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
        data.setdefault("attempts", {})     # request id -> tries, why they failed, when the next one is (task_board)
        data.setdefault("goal_fails", {})   # standing goal -> failures in a row, resting until
        data.setdefault("dismissed", [])    # board rows the owner took off
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

    def idle(self, for_work: bool = False) -> tuple:
        """(idle, why not). Quiet means: no request in flight, no job running, no recent ask. `for_work`: may the
        autopilot start MORE work (requests, standing goals) - background jobs do not count then (the slots do)."""
        state = self.state
        if self.bench_running():
            return False, "the task benchmark is running"
        if self.qa_running():
            return False, "the Forge QA sweep is running"
        if state is not None and hasattr(state, "try_busy"):
            held = state.try_busy()
            if held is None:
                return False, "a request is running"
            state.release_busy(held)
        jobs = getattr(state, "jobs", None)
        if jobs is not None and not for_work:
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

    def running_work(self) -> list:
        """The autopilot's teams still at work: [{"key", "text", "lane"}]."""
        out = []
        for key, entry in self.data["started"].items():
            if entry.get("open") and entry.get("team") and self._team_running(entry["team"]):
                out.append({"key": key, "text": entry.get("text", ""), "lane": entry.get("lane") or lane(entry.get("text", ""))})
        return out

    def can_start(self, text: str, running: list | None = None) -> bool:
        running = self.running_work() if running is None else running
        if len(running) >= slots():
            return False
        return lane(text) != "gpu" or not any(r["lane"] == "gpu" for r in running)

    def drain(self) -> str:
        """Why no NEW work should start now (so the running work ends and the machine gets a quiet moment), or "".
        An update waiting to be applied, or a maintenance duty (health, self-test ...) long overdue."""
        try:
            import updater  # pylint: disable=import-outside-toplevel
            if updater.STATE.get("update_available") and updater.force_enabled():
                return "an update is waiting to be applied"
        except Exception:  # noqa: BLE001
            pass
        grace = _env_s("LOKI_AUTOPILOT_DRAIN_S", 3600)
        for name, every in (("health", _env_s("LOKI_AUTOPILOT_HEALTH_S", 21600)),
                            ("report", _env_s("LOKI_AUTOPILOT_REPORT_S", 604800))):
            last = float(self.data["last"].get(name, 0) or 0)
            if last and self.clock() - last > every + grace:
                return "%s is overdue" % name
        return ""

    def _start(self, key: str, text: str, kind: str, extra: dict | None = None) -> str:
        reply = str(self.start_team(text) or "")
        match = re.search(r"started team (\S+)", reply)
        self.data["started"][key] = dict({"text": text[:4000], "t": self.clock(), "team": match.group(1) if match else "",
                                          "open": bool(match), "reply": reply[:300], "lane": lane(text)}, **(extra or {}))
        return reply if match else ""

    # ------------------------------------------------------------ the task board (engine/task_board.py)
    def _teams_get(self, team_id: str):
        runner = getattr(self.agent, "TEAMS", None)
        try:
            return runner.get(team_id) if runner is not None else None
        except Exception:  # noqa: BLE001
            return None

    def _job_get(self, job_id: str):
        jobs = getattr(self.state, "jobs", None)
        try:
            return jobs.store.get(job_id) if jobs is not None else None
        except Exception:  # noqa: BLE001
            return None

    def settle(self) -> int:
        """Look at every started team that has finished and not been counted yet: a request that failed gets its next
        try planned (or is given up with the reason), a standing goal that keeps failing rests. Returns how many."""
        import task_board  # pylint: disable=import-outside-toplevel
        n = 0
        for key, entry in self.data["started"].items():
            if entry.get("settled") or not entry.get("team"):
                continue
            team = self._teams_get(entry["team"])
            if team is None or team.get("status") == "working":
                continue
            try:   # a picture it asked for waits for the owner's OK (engine/owner_review.py): not a failure, no retry
                import owner_review  # pylint: disable=import-outside-toplevel
                owner_cards = owner_review.waiting_for_jobs((team.get("jobs") or {}).values())
            except Exception:  # noqa: BLE001
                owner_cards = []
            if owner_cards and not key.startswith("always-"):
                att = self.data["attempts"].setdefault(key, {"n": 1})
                att.update(given_up=True, waiting_owner=[c["id"] for c in owner_cards][:5],
                           reasons=["Waits for your OK in Home > For you (%d card%s)" % (len(owner_cards),
                                                                                          "s" if len(owner_cards) > 1 else "")])
                self._log("inbox", "Waits for you: " + entry.get("text", "")[:160], request=key, team=entry["team"])
                entry.update(settled=True, open=False)
                n += 1
                continue
            ok = bool(task_board.verdict_ok(team.get("verdict"))) and team.get("status") != "cancelled"
            why = "" if ok else (task_board.why_failed(team, self._data_dir(), self._job_get)
                                 or task_board.plain(team.get("verdict"), team.get("status")))
            if ok:   # the team says done: check the outcome itself, not its word (engine/proof.py)
                full = next((it["text"] for it in inbox_requests(self.repo / "LOKI_TASKS.md") if it["id"] == key), "") \
                    or entry.get("goal") or ""
                entry["proof"] = task_board.prove(dict(entry, text=full or entry.get("text", "")), team, self._data_dir(),
                                                  self._job_get, self.agent)
                if not entry["proof"].get("ok"):
                    ok = False
                    why = "Said done, but " + "; ".join(entry["proof"].get("problems") or ["nothing real was made"])
            fin = float(team.get("finished") or self.clock())
            if not ok and not key.startswith("always-") and self.clock() - fin > _env_s("LOKI_TASK_RETRY_WINDOW_S", 172800):
                # failed long before this board existed (first start after the update): listed, not re-run
                att = self.data["attempts"].setdefault(key, {"n": 1})
                att.update(given_up=True, seen_finish=fin, reasons=[why[:300]])
                entry.update(settled=True, open=False)
                n += 1
                continue
            if key.startswith("always-"):
                task_board.note_goal(self.data["goal_fails"], entry.get("goal") or entry.get("text", ""), ok, fin)
            else:
                att = task_board.note_finished(self.data["attempts"], key, ok, fin, why)
                self._log("inbox", ("Finished: " if ok else ("Gave up after %d tries: " % att.get("n", 1)) if att.get("given_up")
                                    else "Failed (will try again): ") + entry.get("text", "")[:160] + ("" if ok else " - " + why[:160]),
                          request=key, team=entry["team"])
            entry["settled"] = True
            entry["open"] = False
            n += 1
        return n

    def board(self) -> dict:
        import task_board  # pylint: disable=import-outside-toplevel
        try:
            import offload  # pylint: disable=import-outside-toplevel
            machine = "this Mac" if sys.platform == "darwin" else ("this PC" if offload.role() == "main" else "this computer")
        except Exception:  # noqa: BLE001
            machine = "this computer"
        ws = Path(getattr(self.agent, "WORKSPACE", "") or "") if getattr(self.agent, "WORKSPACE", "") else None
        return task_board.build(self.data["started"], self.data["attempts"], self._teams_get, self._job_get,
                                self._data_dir(), ws, machine, set(self.data.get("dismissed") or []), self.clock())

    def write_board(self) -> str:
        import task_board  # pylint: disable=import-outside-toplevel
        try:
            return task_board.write_report(self.board(), self._data_dir())
        except Exception as exc:  # noqa: BLE001
            self._log("board", "could not write the task report: %s" % exc)
            return ""

    def retry(self, key: str) -> bool:
        """The owner's "Try again" on the board: plan the next try now (a given-up request gets one more)."""
        entry = self.data["attempts"].setdefault(key, {"n": 1})
        if key not in self.data["started"] or key.startswith("always-"):
            return False
        entry.update(given_up=False, last_ok=False, next=self.clock())
        self.data["started"][key]["settled"] = True
        self.data["last"]["inbox"] = 0
        return True

    def dismiss(self, key: str) -> bool:
        if key not in self.data["started"]:
            return False
        if key not in self.data["dismissed"]:
            self.data["dismissed"] = (self.data["dismissed"] + [key])[-500:]
        return True

    def _retry_waiting(self, running: list) -> list:
        """Requests whose next try is due (oldest first)."""
        import task_board  # pylint: disable=import-outside-toplevel
        now = self.clock()
        return [item for item in inbox_requests(self.repo / "LOKI_TASKS.md")
                if item["id"] in self.data["started"] and task_board.retry_due(self.data["attempts"], item["id"], now)]

    def duty_inbox(self) -> str:
        """Start every open request that fits in a free slot (the GPU lane one at a time) - new ones, and failed ones
        whose next try is due (told why the last one failed)."""
        if self.start_team is None:
            return ""
        import task_board  # pylint: disable=import-outside-toplevel
        self.settle()
        running, started = self.running_work(), []
        for item in self._retry_waiting(running):
            if not self.can_start(item["text"], running):
                continue
            att = self.data["attempts"].setdefault(item["id"], {"n": 1})
            prev = self.data["started"][item["id"]]
            att["n"] = int(att.get("n") or 1) + 1
            att.pop("next", None)
            reply = self._start(item["id"], task_board.retry_text(item["text"], self.data["attempts"], item["id"]), "inbox",
                                {"prev_teams": (prev.get("prev_teams") or []) + [prev.get("team", "")]})
            team = self.data["started"][item["id"]]["team"]
            self._log("inbox", ("Trying again (%d of %d): " % (att["n"], task_board.RETRIES + 1) if team else "Could not start: ")
                      + item["text"][:200], request=item["id"], team=team)
            if team:
                running.append({"key": item["id"], "text": item["text"], "lane": lane(item["text"])})
                started.append(reply)
        for item in inbox_requests(self.repo / "LOKI_TASKS.md"):
            if item["id"] in self.data["started"] or not self.can_start(item["text"], running):
                continue
            reply = self._start(item["id"], item["text"], "inbox")
            team = self.data["started"][item["id"]]["team"]
            self._log("inbox", ("Started a team for: " if team else "Could not start: ") + item["text"][:200],
                      request=item["id"], team=team)
            if team:
                running.append({"key": item["id"], "text": item["text"], "lane": lane(item["text"])})
                started.append(reply)
        return "\n".join(started)

    def duty_always(self) -> str:
        """Free slots and nothing waiting in the inbox: the next standing goals from LOKI_TASKS.md "## Always", in
        turn (owner 2026-10-25: "i want them to always be doing stuff"). A goal never runs twice at once; drafts and
        assets only - publishing always asks."""
        if self.start_team is None:
            return ""
        import task_board  # pylint: disable=import-outside-toplevel
        self.settle()
        running = self.running_work()
        if any(item["id"] not in self.data["started"] and self.can_start(item["text"], running)
               for item in inbox_requests(self.repo / "LOKI_TASKS.md")) or self._retry_waiting(running):
            return ""                # the inbox (and a request's next try) comes first
        goals = always_goals(self.repo / "LOKI_TASKS.md")
        if not goals:
            return ""
        busy = {r.get("goal") for r in (self.data["started"].get(x["key"]) or {} for x in running) if r.get("goal")}
        started = []
        for _ in range(len(goals)):
            if len(running) >= slots():
                break
            i = int(self.data.get("always_next") or 0) % len(goals)
            self.data["always_next"] = i + 1
            if goals[i] in busy or not self.can_start(goals[i], running) \
                    or task_board.goal_resting(self.data["goal_fails"], goals[i], self.clock()):
                continue   # a goal that failed again and again rests (task_board.GOAL_REST_S)
            goal = goals[i] + (" (standing goal, %s - make drafts and assets only; never publish or post)"
                               % time.strftime("%Y-%m-%d", time.localtime(self.clock())))
            key = "always-%d-%d" % (i, int(self.clock()))
            reply = self._start(key, goal, "always", {"goal": goals[i]})
            team = self.data["started"][key]["team"]
            self._log("always", ("Working on: " if team else "Could not start: ") + goals[i][:200], team=team)
            if team:
                running.append({"key": key, "text": goal, "lane": lane(goals[i])})
                busy.add(goals[i])
                started.append(reply)
        return "\n".join(started)

    def duty_pipeline(self) -> str:
        """The asset pipeline (engine/asset_pipeline.py): when no stage is running, start the next ready stage of the
        oldest asset in the background - its checks decide whether it is handed on or retried."""
        if self.agent is None or not hasattr(self.agent, "WORKSPACE"):
            return ""
        ws = Path(self.agent.WORKSPACE)
        try:   # new prompt cards go through the Prompt Expert before the owner sees them (engine/prompt_expert.py) -
            import owner_review  # pylint: disable=import-outside-toplevel   (a text call: it runs beside GPU work)
            owner_review.kick_expert(self.agent, ws)
        except Exception as exc:  # noqa: BLE001
            self._log("pipeline", "Prompt Expert could not start: %s" % str(exc)[:160])
        import asset_pipeline  # pylint: disable=import-outside-toplevel
        out = ""
        # The Concept Artist's proposal is a text call and a prompt card - nothing is drawn - so it never waits for the
        # GPU (on the PC a 3D job blocked every proposal for hours, 2026-10-27). propose() itself only runs when the
        # pipeline is empty and nothing waits for the owner.
        if _env_on("LOKI_PIPELINE_PROPOSE") and not asset_pipeline.unfinished(ws) \
                and self.due("propose", _env_s("LOKI_PIPELINE_PROPOSE_S", 1800)):
            self.data["last"]["propose"] = self.clock()
            try:
                made = asset_pipeline.propose(ws, self._concept_ask)
            except Exception as exc:  # noqa: BLE001
                made = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            if made.get("ok"):
                out = "Concept Artist proposed: %s (waits for your OK on its prompt)" % made["brief"][:160]
                try:   # queue its prompt card now (a card only: its prompt is not approved, so nothing is drawn)
                    import owner_review  # pylint: disable=import-outside-toplevel
                    if owner_review.on():
                        asset_pipeline.advance(ws, made["asset"])
                        owner_review.kick_expert(self.agent, ws)
                except Exception as exc:  # noqa: BLE001
                    self._log("pipeline", "could not queue the prompt card: %s" % str(exc)[:160])
            elif made.get("error"):
                self._log("pipeline", "Concept Artist could not propose: %s" % str(made["error"])[:200])
        if any(r["lane"] == "gpu" for r in self.running_work()):   # one GPU / memory-heavy thing at a time (the
            if out:                                                # Mac crashed 2026-10-26 with three at once)
                self._log("pipeline", out)
            return out
        out = asset_pipeline.tick(ws) or out
        if out:
            self._log("pipeline", out)
        return out

    def _concept_ask(self, prompt: str) -> str:
        """One short answer from the free cloud model (the main driver), for the Concept Artist's proposal. (Not
        _ask_model: that name is the self-review's - the clash broke the first proposal on the PC, 2026-10-27.)"""
        import asyncio  # pylint: disable=import-outside-toplevel
        agent = self.agent
        provider = "nvidia" if "nvidia" in getattr(agent, "MODELS", {}) and agent.provider_configured("nvidia") else ""
        if not provider:
            raise RuntimeError("no free cloud model is set up (an NVIDIA key)")
        client = agent.make_client(provider)

        async def go():
            r = await client.chat.completions.create(model=agent.MODELS[provider].model, max_tokens=300,
                                                     messages=[{"role": "user", "content": prompt}])
            return str(r.choices[0].message.content or "")
        return asyncio.run(go())

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
    # ------------------------------------------------------------ Forge QA (owner 2026-10-22: "use loki to test the forge")
    def qa_running(self) -> bool:
        return self.qa_proc is not None and self.qa_proc.poll() is None

    def duty_qa(self) -> str:
        """Start the Forge QA sweep in the background (it is settled on a later pass)."""
        if self.qa_running():
            return ""
        import forge_qa_duty  # pylint: disable=import-outside-toplevel
        starter = self.qa_start or (lambda: forge_qa_duty.start(self.repo, self._data_dir()))
        try:
            self.qa_proc = starter()
        except Exception as exc:  # noqa: BLE001
            self._log("qa", "Forge QA could not start: %s" % exc)
            return ""
        self._log("qa", "Forge QA sweep started (every menu, button and command, headless).")
        return "started the Forge QA sweep"

    def qa_settle(self) -> str:
        """The sweep finished: triage it and propose fixes (every pass, idle or not)."""
        if self.qa_proc is None or self.qa_proc.poll() is None:
            return ""
        self.qa_proc = None
        import forge_qa_duty  # pylint: disable=import-outside-toplevel
        line = forge_qa_duty.settle(self.evolve, self._data_dir(), now=self.clock())
        self._log("qa", line)
        return line

    # ------------------------------------------------------------ task bench (session 28)
    def bench_running(self) -> bool:
        proc = self.bench_proc
        return proc is not None and proc.poll() is None

    def _start_bench(self, models: str):
        """Start tools/task_bench.py in the background (its own process; output to bench/autopilot.log)."""
        import subprocess  # pylint: disable=import-outside-toplevel
        import sys  # pylint: disable=import-outside-toplevel
        out = self.path.parent / "bench"
        out.mkdir(parents=True, exist_ok=True)
        log = open(out / "autopilot.log", "ab")  # noqa: SIM115 - handed to the child
        kwargs: dict = {"cwd": str(self.repo), "stdout": log, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            return subprocess.Popen([sys.executable, str(self.repo / "tools" / "task_bench.py"), "--model", models],
                                    **kwargs)
        finally:
            log.close()

    def duty_task_bench(self) -> str:
        """Nightly: run the task-success benchmark on the local and the smart model, one run at a time."""
        if self.bench_running():
            return ""
        models = os.getenv("LOKI_TASK_BENCH_MODELS", "local,smart").strip() or "local,smart"
        self.bench_proc = (self.bench_start or self._start_bench)(models)
        self._log("task_bench", "Started the task-success benchmark (%s); scores appear in Settings > Lab." % models,
                  models=models)
        return "started task bench: %s" % models

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

    def duty_storage(self) -> str:
        """Keep LOKI inside its space (engine/storage.py): finished-job code copies, old job logs, agents' build
        leftovers and old Home deletes go; drafts and caches too when over budget or the drive is low; the trash
        empties itself after LOKI_TRASH_DAYS. Old finished jobs leave the job list (the newest 500 stay)."""
        import storage  # pylint: disable=import-outside-toplevel
        ws = Path(getattr(self.agent, "WORKSPACE", "") or "") if getattr(self.agent, "WORKSPACE", "") else None
        jobs = getattr(self.state, "jobs", None)
        res = storage.auto(self._data_dir(), ws, job_status=lambda j: str((self._job_get(j) or {}).get("status") or ""),
                           repo=self.repo)
        try:
            dropped = jobs.store.remove_finished(keep=500) if jobs is not None and hasattr(jobs.store, "remove_finished") else 0
        except Exception:  # noqa: BLE001
            dropped = 0
        text = "Storage: freed %.0f MB (%d items%s)%s%s" % (
            (res.get("freed", 0) + (res.get("trash") or {}).get("freed", 0)) / 1e6, res.get("removed", 0),
            ", over budget - drafts and caches too" if res.get("tight") else "",
            "; %d old jobs off the list" % dropped if dropped else "",
            "; " + "; ".join(res.get("errors") or [])[:200] if res.get("errors") else "")
        self._log("storage", text)
        return text

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

    def duty_upstream(self) -> str:
        """Check the open-source projects LOKI is built from (GitHub API, a batch per run) and put each one with
        something new in Home > For you: Adopt (an agent ports what matters, updates the pin, tests, ships), Skip,
        or Not now. The full table is harness_data/reports/upstream.md."""
        from agentsys import upstream  # pylint: disable=import-outside-toplevel
        res = upstream.check()
        ws = str(getattr(self.agent, "WORKSPACE", "") or self.repo)
        cards = upstream.queue_cards(res["new"], ws)
        text = "Upstream: checked %d of %d sources%s; %d with something new%s" % (
            res["checked"], res["total"], "" if res["token"] else " (no GitHub token: a batch per day)",
            len(res["new"]), (" - in For you: " + ", ".join(n["entry"]["repo"] for n in res["new"][:5])) if cards else "")
        self._log("upstream", text)
        return text

    def resume_orchestrations(self) -> str:
        """A delegation run that waited for the owner goes on once his cards are decided."""
        try:
            from agentsys import runtime  # pylint: disable=import-outside-toplevel
        except Exception:  # noqa: BLE001
            return ""
        ids = runtime.parked_orchestrations_ready() if runtime.STATE.get("state") is not None else []
        for rid in ids[:2]:
            runtime.resume_orchestration(rid)
        if ids:
            self._log("orchestrate", "resumed %s after the owner's OK" % ", ".join(ids[:2]))
        return ", ".join(ids[:2])

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
        cards: list = []

        def make(prompt, **kw):
            try:   # today's picture waits for the owner's OK on its prompt like every other one (engine/owner_review.py)
                import owner_review  # pylint: disable=import-outside-toplevel
                if owner_review.on():
                    card = owner_review.queue("prompt", "make_image", {"prompt": prompt, "style": str(kw.get("style") or "")},
                                              str(ws), who="Daily picture")
                    cards.append(card)
                    return {"ok": True, "id": card["id"]}
            except ImportError:
                pass
            return creations.make_image(self.agent, prompt, **kw)
        out = creative.daily_creation(make, creations.liked_meta(ws), clock=self.clock)
        if out and cards:
            out = "today's picture waits for your OK in Home > For you: %s" % cards[0]["args"]["prompt"][:160]
        if out:
            self._log("creation", out)
        return out

    # ------------------------------------------------------------ the loop
    def tick(self) -> list:
        """One pass: at most one duty (plus the storage clean-up when it is due). Returns [(duty, result)] for what ran."""
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
        try:   # a finished Forge QA sweep is triaged as soon as it is done, idle or not
            with self.lock:
                if self.qa_settle():
                    self._save()
        except Exception as exc:  # noqa: BLE001
            self._log("qa", "failed: %s: %s" % (type(exc).__name__, exc))
        try:   # finished work is counted (and the board rewritten) as soon as it ends, idle or not
            with self.lock:
                if self.settle():
                    self._save()
                    self.write_board()
        except Exception as exc:  # noqa: BLE001
            self._log("board", "failed: %s: %s" % (type(exc).__name__, exc))
        try:   # delegation runs that waited for the owner carry on as soon as he decided
            self.resume_orchestrations()
        except Exception as exc:  # noqa: BLE001
            self._log("orchestrate", "failed: %s: %s" % (type(exc).__name__, exc))
        cleaned: list = []
        try:   # storage runs on its own clock, busy or not - it only touches finished work (never idle on the PC).
            # It does NOT use up the tick (2026-10-27): it used to return here, so every start (and every 6 h) the
            # duty that was due - evolve, the inbox, a retry - waited a whole tick behind a clean-up.
            if _env_on("LOKI_AUTOPILOT_STORAGE") and self.due("storage", _env_s("LOKI_STORAGE_EVERY_S", 21600)):
                with self.lock:
                    self.data["last"]["storage"] = self.clock()
                    cleaned = [("storage", self.duty_storage())]
                    self._save()
        except Exception as exc:  # noqa: BLE001
            self._log("storage", "failed: %s: %s" % (type(exc).__name__, exc))
        return cleaned + self._tick_work()

    def _tick_work(self) -> list:
        """The rest of tick(): requests, goals, retries, then the idle duties."""
        work_ok, _ = self.idle(for_work=True)
        if work_ok and not self.drain():
            # requests and standing goals fill free slots side by side, even while other work runs
            work = []
            if _env_on("LOKI_AUTOPILOT_INBOX"):
                work.append(("inbox", _env_s("LOKI_AUTOPILOT_INBOX_S", 120), self.duty_inbox))
            if _env_on("LOKI_AUTOPILOT_ALWAYS", "off"):
                work.append(("always", always_every_s(), self.duty_always))
            if _env_on("LOKI_AUTOPILOT_PIPELINE"):
                work.append(("pipeline", _env_s("LOKI_AUTOPILOT_PIPELINE_S", 120), self.duty_pipeline))
            with self.lock:
                for name, every, fn in work:
                    if not self.due(name, every):
                        continue
                    self.data["last"][name] = self.clock()
                    try:
                        out = fn()
                    except Exception as exc:  # noqa: BLE001
                        out = ""
                        self._log(name, "failed: %s: %s" % (type(exc).__name__, exc))
                    self._save()
                    if out:
                        return [(name, out)]
        ok, _why = self.idle()
        if not ok:
            return []
        duties = [("health", _env_s("LOKI_AUTOPILOT_HEALTH_S", 21600), self.duty_health)]
        if self.evolve is not None:
            import evolve as _evolve  # pylint: disable=import-outside-toplevel
            if _evolve.enabled():
                duties.append(("evolve", _env_s("LOKI_EVOLVE_S", 14400), self.duty_evolve))
        try:
            import forge_qa_duty  # pylint: disable=import-outside-toplevel
            if self.qa_start is not None or (self.evolve is not None and forge_qa_duty.enabled()
                                             and (self.repo / "tools" / "forge_qa.py").is_file()):
                duties.append(("qa", _env_s("LOKI_FORGE_QA_S", 21600), self.duty_qa))
        except Exception:  # noqa: BLE001
            pass
        duties.append(("report", _env_s("LOKI_AUTOPILOT_REPORT_S", 604800), self.duty_report))
        if _env_on("LOKI_UPSTREAM"):
            # where LOKI's open-source code came from and what changed there (engine/agentsys/upstream.py; owner
            # 2026-10-28: "always check where he got what hes using and seeing if they made updates")
            duties.append(("upstream", _env_s("LOKI_UPSTREAM_S", 86400), self.duty_upstream))
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
        if task_bench_enabled() and in_hours(os.getenv("LOKI_TASK_BENCH_HOURS", "1-6"), self.clock()):
            # right after health: the nightly score comes before starting new self-improvement work
            duties.insert(1, ("task_bench", _env_s("LOKI_TASK_BENCH_S", 72000), self.duty_task_bench))
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
