"""Scheduled tasks: "every weekday at 9am summarise my inbox", "in 30m remind me", cron lines.

Ported into LOKI (session 27 harvest) from Hermes Agent's cron (github.com/NousResearch/
hermes-agent, cron/jobs.py: parse_schedule, parse_duration, _parse_clock_time,
_natural_every_to_cron, normalize_repeat_value; the once / interval / cron kinds and the
"in 30m" = once vs "30m" = recurring contract), MIT License, Copyright (c) 2025 Nous Research -
see engine/licenses/HermesAgent-MIT.txt. Hermes needs the `croniter` package for cron
expressions; LOKI matches the 5 cron fields itself (numbers, *, lists, ranges, steps, JAN-DEC,
SUN-SAT), so nothing extra is installed.

A due schedule becomes a background job (the autopilot's `schedules` duty, engine/autopilot.py):
LOKI does the task with its tools and the result shows in the job list like any other job.
Times are this computer's local time. Store: harness_data/schedules.json.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

MAX_SCHEDULES = 50
MIN_INTERVAL_MIN = 5
_DURATION = {"m": 1, "h": 60, "d": 1440}
_DOW = {"sunday": "0", "sun": "0", "monday": "1", "mon": "1", "tuesday": "2", "tue": "2", "tues": "2",
        "wednesday": "3", "wed": "3", "weds": "3", "thursday": "4", "thu": "4", "thur": "4", "thurs": "4",
        "friday": "5", "fri": "5", "saturday": "6", "sat": "6"}
_DAYSPEC = {"day": "*", "daily": "*", "everyday": "*", "weekday": "1-5", "weekdays": "1-5",
            "weekend": "0,6", "weekends": "0,6"}
_MONTHS = {m: str(i) for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DOW_NAMES = {k[:3]: v for k, v in _DOW.items()}


# --------------------------------------------------------------------------- parsing (Hermes)
def parse_duration(s: str) -> int:
    """"30m" -> 30, "2h" -> 120, "1d" -> 1440, a bare "hour" -> 60 (minutes)."""
    s = s.strip().lower()
    m = re.match(r"^(\d*)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$", s)
    if not m:
        raise ValueError("Invalid duration '%s'. Use '30m', '2h', '1d'." % s)
    return (int(m.group(1)) if m.group(1) else 1) * _DURATION[m.group(2)[0]]


def parse_clock(text: str):
    t = text.strip().lower().replace(" ", "")
    if t in ("noon", "midday"):
        return 12, 0
    if t == "midnight":
        return 0, 0
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", t)
    if not m:
        return None
    hour, minute, mer = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if mer:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if mer == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def natural_to_cron(rest: str):
    """"monday 9am" / "weekdays at 9am" / "mon, wed at 18:30" -> "M H * * DOW" (or None)."""
    toks = rest.lower().replace(",", " ").split()
    if not toks:
        return None
    dow = _DAYSPEC.get(toks[0])
    idx = 1
    if dow is None:
        days, idx = [], len(toks)
        for i, tok in enumerate(toks):
            if tok == "and":
                continue
            mapped = _DOW.get(tok)
            if mapped is None:
                idx = i
                break
            if mapped not in days:
                days.append(mapped)
        if not days:
            return None
        dow = ",".join(days)
    time_toks = toks[idx:]
    if time_toks and time_toks[0] == "at":
        time_toks = time_toks[1:]
    if not time_toks:
        return None
    parsed = parse_clock(" ".join(time_toks))
    if parsed is None:
        return None
    return "%d %d * * %s" % (parsed[1], parsed[0], dow)


def parse_schedule(schedule: str, now: datetime | None = None) -> dict:
    """{"kind": "once"|"interval"|"cron", "run_at"|"minutes"|"expr", "display"}."""
    now = now or datetime.now()
    original = str(schedule or "").strip()
    low = original.lower()
    if not original:
        raise ValueError("give a schedule, e.g. 'every weekday at 9am', 'in 30m', 'every 2h', '0 9 * * 1-5'")
    is_every = low.startswith("every ")
    rest = original[6:].strip() if is_every else low
    expr = natural_to_cron(rest)
    if expr is not None:
        cron_fields(expr)
        return {"kind": "cron", "expr": expr, "display": original}
    if is_every:
        minutes = parse_duration(rest)
        return {"kind": "interval", "minutes": max(MIN_INTERVAL_MIN, minutes), "display": "every %dm" % max(MIN_INTERVAL_MIN, minutes)}
    parts = original.split()
    if len(parts) == 5 and all(re.match(r"^[A-Za-z\d\*\-,/]+$", p) for p in parts):
        cron_fields(original)
        return {"kind": "cron", "expr": original, "display": original}
    if "T" in original or re.match(r"^\d{4}-\d{2}-\d{2}", original):
        try:
            dt = datetime.fromisoformat(original.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Invalid timestamp '%s': %s" % (original, exc)) from None
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return {"kind": "once", "run_at": dt.timestamp(), "display": "once at %s" % dt.strftime("%Y-%m-%d %H:%M")}
    if low.startswith("in "):
        minutes = parse_duration(original[3:].strip())
        at = now + timedelta(minutes=minutes)
        return {"kind": "once", "run_at": at.timestamp(), "display": "once in %s" % original[3:].strip()}
    try:
        minutes = parse_duration(original)
        return {"kind": "interval", "minutes": max(MIN_INTERVAL_MIN, minutes), "display": "every %dm" % max(MIN_INTERVAL_MIN, minutes)}
    except ValueError:
        pass
    raise ValueError("Invalid schedule '%s'. Use: 'every 30m' / '2h' (repeating), 'in 30m' (once), "
                     "'every monday 9am' / 'weekdays at 9am', a cron line '0 9 * * *', or a time "
                     "'2026-11-03T14:00'." % original)


# --------------------------------------------------------------------------- cron (replaces croniter)
def _field(spec: str, lo: int, hi: int, names: dict) -> set:
    out = set()
    for part in spec.lower().split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError("bad step")
        for name, num in names.items():
            part = re.sub(r"\b%s\b" % name, num, part)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a_s, b_s = part.split("-", 1)
            a, b = int(a_s), int(b_s)
        else:
            a = b = int(part)
            if step > 1:
                b = hi
        if a < lo or b > hi or a > b:
            raise ValueError("value out of range %d-%d" % (lo, hi))
        out.update(range(a, b + 1, step))
    return out


def cron_fields(expr: str) -> tuple:
    parts = str(expr).split()
    if len(parts) != 5:
        raise ValueError("a cron line has 5 fields: minute hour day month weekday")
    try:
        minute = _field(parts[0], 0, 59, {})
        hour = _field(parts[1], 0, 23, {})
        dom = _field(parts[2], 1, 31, {})
        month = _field(parts[3], 1, 12, _MONTHS)
        dow = {d % 7 for d in _field(parts[4], 0, 7, _DOW_NAMES)}
    except ValueError as exc:
        raise ValueError("Invalid cron expression '%s': %s" % (expr, exc)) from None
    return minute, hour, dom, month, dow, parts[2] == "*", parts[4] == "*"


def cron_matches(expr: str, dt: datetime) -> bool:
    minute, hour, dom, month, dow, dom_any, dow_any = cron_fields(expr)
    if dt.minute not in minute or dt.hour not in hour or dt.month not in month:
        return False
    day_ok, wd_ok = dt.day in dom, ((dt.weekday() + 1) % 7) in dow
    if dom_any or dow_any:       # cron: when one day field is restricted, only it counts
        return day_ok and wd_ok
    return day_ok or wd_ok       # both restricted: either matches (classic cron)


def next_cron(expr: str, after: datetime, limit_days: int = 400):
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = after + timedelta(days=limit_days)
    minute, hour, *_ = cron_fields(expr)
    while t <= end:
        if t.hour not in hour:
            t = (t + timedelta(hours=1)).replace(minute=0)
            continue
        if cron_matches(expr, t):
            return t
        t += timedelta(minutes=1)
    return None


def next_run(sched: dict, after: float) -> float | None:
    kind = sched.get("kind")
    if kind == "once":
        return float(sched["run_at"]) if float(sched["run_at"]) > after - 1 else None
    if kind == "interval":
        return after + 60 * int(sched["minutes"])
    if kind == "cron":
        nxt = next_cron(sched["expr"], datetime.fromtimestamp(after))
        return nxt.timestamp() if nxt else None
    return None


# --------------------------------------------------------------------------- store
class Schedules:
    def __init__(self, path: Path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.lock = threading.Lock()

    def _load(self) -> list:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, items: list) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, prompt: str, schedule: str, title: str = "", repeat=None) -> dict:
        prompt = str(prompt or "").strip()
        if not prompt:
            raise ValueError("say what to do (prompt)")
        now = self.clock()
        sched = parse_schedule(schedule, datetime.fromtimestamp(now))
        if repeat is not None and str(repeat).strip().lower() not in ("", "forever", "none"):
            repeat = 1 if str(repeat).strip().lower() in ("once", "1x") else max(1, int(repeat))
        else:
            repeat = 1 if sched["kind"] == "once" else None
        nxt = sched["run_at"] if sched["kind"] == "once" else next_run(sched, now)
        if nxt is None:
            raise ValueError("that schedule never comes round")
        if sched["kind"] == "once" and nxt < now - 60:
            raise ValueError("that time has already passed")
        with self.lock:
            items = self._load()
            if len(items) >= MAX_SCHEDULES:
                raise ValueError("there are already %d scheduled tasks; remove one first" % MAX_SCHEDULES)
            item = {"id": uuid.uuid4().hex[:6], "title": (title or prompt.splitlines()[0])[:80], "prompt": prompt[:4000],
                    "schedule": sched, "repeat": repeat, "runs": 0, "next": nxt, "paused": False,
                    "created": now, "last": 0, "last_job": ""}
            items.append(item)
            self._save(items)
        return item

    def list(self) -> list:
        return self._load()

    def remove(self, sid: str) -> bool:
        with self.lock:
            items = self._load()
            keep = [i for i in items if i["id"] != str(sid).strip()]
            self._save(keep)
            return len(keep) != len(items)

    def pause(self, sid: str, paused: bool = True) -> bool:
        with self.lock:
            items = self._load()
            hit = False
            for i in items:
                if i["id"] == str(sid).strip():
                    i["paused"] = bool(paused)
                    if not paused:
                        i["next"] = next_run(i["schedule"], self.clock()) or i["next"]
                    hit = True
            self._save(items)
            return hit

    def due(self) -> list:
        now = self.clock()
        return [i for i in self._load() if not i.get("paused") and i.get("next") and float(i["next"]) <= now]

    def mark_run(self, sid: str, job_id: str = "") -> dict | None:
        """Record a run and move `next` on; a schedule with no runs left is removed."""
        now = self.clock()
        with self.lock:
            items = self._load()
            out = None
            for i in list(items):
                if i["id"] != sid:
                    continue
                i["runs"] = int(i.get("runs", 0)) + 1
                i["last"], i["last_job"] = now, job_id
                done = i.get("repeat") is not None and i["runs"] >= int(i["repeat"])
                nxt = None if done else next_run(i["schedule"], now)
                if nxt is None:
                    items.remove(i)
                else:
                    i["next"] = nxt
                out = i
            self._save(items)
            return out


def describe(item: dict) -> str:
    nxt = datetime.fromtimestamp(float(item["next"])).strftime("%a %Y-%m-%d %H:%M") if item.get("next") else "-"
    reps = "" if item.get("repeat") is None else " (%d of %d runs done)" % (item.get("runs", 0), item["repeat"])
    return "%s  %s  [%s]%s  next: %s%s" % (item["id"], item["title"], item["schedule"].get("display"), reps, nxt,
                                          "  PAUSED" if item.get("paused") else "")
