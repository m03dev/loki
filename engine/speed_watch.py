"""Speed watch (EVOLVE E6): how long LOKI takes, step by step, so it can make the slowest step faster.

Every measurement is one line in <DATA_DIR>/speed/timings.jsonl:

    {"t": <unix time>, "phase": "model_call", "ms": 812.4, "job": "<job id or ''>", "note": "local"}

Phases:
    startup      engine start until the bridge answers (loki_bridge.serve)
    first_paint  the window's first contentful paint (app/ui/boot.js -> POST /ui/timing)
    ui_ready     the window connected to the engine (boot.js, LOKI_READY)
    triage       the first layer + memory pack for one request (loki._triage)
    model_call   one call to a model (loki.agent_turn)
    tools        one local tool call (loki.call_tool)
    verification checking the files a request changed (loki._verify_touched)
    request      a whole chat request or goal (loki.run_agent / pursue_goal)
    job          a whole background job (computed from the job store, not logged here)

summary() gives per phase: count, p50, p90, last and the last 30 values (the sparkline in
Settings > Lab). slowest() names the step with the highest median among the request phases;
once a week the autopilot turns it into an evolve idea (idea_for). Writes are tiny appends and
never raise; the file is trimmed to the newest MAX_LINES lines now and then.
Standard library only.  LOKI_SPEED_WATCH=off turns recording off.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

PHASES = ("startup", "first_paint", "ui_ready", "triage", "model_call", "tools", "verification", "request", "job")
REQUEST_PHASES = ("triage", "model_call", "tools", "verification")
LABELS = {"startup": "Engine start", "first_paint": "Window first paint", "ui_ready": "Window ready",
          "triage": "Triage (first layer + memory)", "model_call": "Model call", "tools": "Tool call",
          "verification": "Verification", "request": "Whole request", "job": "Background job"}
MAX_LINES = 6000
SPARK = 30
_LOCK = threading.Lock()
_WRITES = [0]


def enabled() -> bool:
    return str(os.getenv("LOKI_SPEED_WATCH", "on")).strip().lower() not in ("off", "0", "false", "no")


def _data_dir(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def path(root: Path | None = None) -> Path:
    return _data_dir(root) / "speed" / "timings.jsonl"


def record(phase: str, ms: float, root: Path | None = None, note: str = "", clock=time.time) -> bool:
    """Keep one measurement. Never raises; False when it was not kept."""
    if not enabled() or phase not in PHASES:
        return False
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return False
    if ms < 0 or ms > 7 * 86400 * 1000:
        return False
    line = {"t": round(float(clock()), 3), "phase": phase, "ms": round(ms, 1),
            "job": os.getenv("LOKI_JOB_ID", "")[:16], "note": str(note or "")[:60]}
    try:
        target = path(root)
        with _LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")
            _WRITES[0] += 1
            if _WRITES[0] % 500 == 0:
                _trim(target)
        return True
    except OSError:
        return False


def _trim(target: Path) -> None:
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_LINES:
            tmp = target.with_suffix(".tmp")
            tmp.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
            os.replace(tmp, target)
    except OSError:
        pass


class Timer:
    """with speed_watch.Timer("tools", note=name): ...  - records the block's wall time."""

    def __init__(self, phase: str, note: str = "", root: Path | None = None) -> None:
        self.phase, self.note, self.root = phase, note, root
        self.t0 = 0.0

    def __enter__(self):
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *exc) -> bool:
        record(self.phase, (time.monotonic() - self.t0) * 1000, root=self.root, note=self.note)
        return False


def since(t0_monotonic: float, phase: str, note: str = "", root: Path | None = None) -> None:
    """Record the time since a time.monotonic() stamp."""
    record(phase, (time.monotonic() - float(t0_monotonic)) * 1000, root=root, note=note)


def entries(root: Path | None = None, since_t: float = 0.0, last: int = MAX_LINES) -> list:
    try:
        lines = path(root).read_text(encoding="utf-8").splitlines()[-last:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("phase") in PHASES and float(row.get("t", 0) or 0) >= since_t:
            out.append(row)
    return out


def _quantile(values: list, q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def job_durations(jobs: list) -> list:
    """[(finished_t, seconds, job)] for finished background jobs (the 'job' phase)."""
    out = []
    for job in jobs or []:
        try:
            started, finished = float(job.get("started") or 0), float(job.get("finished") or 0)
        except (TypeError, ValueError):
            continue
        if started and finished >= started and job.get("status") in ("done", "failed", "cancelled"):
            out.append((finished, finished - started, job))
    return sorted(out, key=lambda r: r[0])


def summary(root: Path | None = None, jobs: list | None = None, window_s: float = 14 * 86400, now: float | None = None) -> dict:
    """{phases: [{phase, label, n, p50, p90, last, spark}], slowest: {...} | None, since}."""
    now = time.time() if now is None else now
    rows = entries(root, since_t=now - window_s)
    by: dict = {p: [] for p in PHASES}
    for row in rows:
        by[row["phase"]].append(float(row["ms"]))
    for finished, seconds, _job in job_durations(jobs or []):
        if finished >= now - window_s:
            by["job"].append(seconds * 1000)
    phases = []
    for phase in PHASES:
        values = by[phase]
        phases.append({"phase": phase, "label": LABELS[phase], "n": len(values),
                       "p50": round(_quantile(values, 0.5), 1), "p90": round(_quantile(values, 0.9), 1),
                       "last": round(values[-1], 1) if values else 0.0,
                       "spark": [round(v, 1) for v in values[-SPARK:]]})
    return {"ok": True, "enabled": enabled(), "phases": phases, "slowest": slowest(phases), "window_days": int(window_s // 86400)}


def slowest(phases: list, min_n: int = 3) -> dict | None:
    """The request step with the highest median (enough samples), plus the slow window start."""
    best = None
    for row in phases:
        if row["phase"] not in REQUEST_PHASES or row["n"] < min_n:
            continue
        if best is None or row["p50"] > best["p50"]:
            best = row
    startup = next((r for r in phases if r["phase"] == "startup"), None)
    # A start-up over 20 s (p50) is the slow step whatever the request phases say: the owner waits for it.
    if startup and startup["n"] >= 2 and startup["p50"] > 20000 and (best is None or startup["p50"] > best["p50"]):
        best = startup
    return dict(best) if best else None


def idea_for(slow: dict) -> str:
    """The evolve idea text for the slowest step (Settings > Lab, LOKI's idea)."""
    if not slow:
        return ""
    hints = {"model_call": "send fewer/shorter messages and tool schemas, keep the local model warm, prefer the "
                           "faster provider when the forecast says one is getting slow",
             "triage": "cache the first layer's verdict and the memory pack for similar requests, load Laya once",
             "tools": "find which tool is slow (the note on each timing names it) and make it do less or run in a thread",
             "verification": "verify only the files that changed and skip heavy checks for text files",
             "startup": "start MCP servers, Laya and the peer link lazily so the window opens sooner"}
    return ("Speed watch: make '%s' faster - it is LOKI's slowest step (median %.1f s, 90%% within %.1f s over %d "
            "measurements). Measure before and after with engine/speed_watch.py; ideas: %s."
            % (slow["label"], slow["p50"] / 1000.0, slow["p90"] / 1000.0, slow["n"],
               hints.get(slow["phase"], "find what it waits for and remove the wait")))


def tool_breakdown(root: Path | None = None, top: int = 6, window_s: float = 14 * 86400) -> list:
    """The slowest tools by median (from the notes on 'tools' timings): [{tool, n, p50}]."""
    now = time.time()
    per: dict = {}
    for row in entries(root, since_t=now - window_s):
        if row["phase"] == "tools" and row.get("note"):
            per.setdefault(row["note"], []).append(float(row["ms"]))
    out = [{"tool": k, "n": len(v), "p50": round(_quantile(v, 0.5), 1)} for k, v in per.items()]
    return sorted(out, key=lambda r: -r["p50"])[:top]


def propose(evolve_obj, root: Path | None = None, jobs: list | None = None, env: dict | None = None) -> dict:
    """The weekly speed duty: name the slowest step as an evolve idea (one open speed idea at a time).

    LOKI_SPEED_IDEAS=auto (default): the idea is approved at once - it is measured and narrow, so evolve
    may build it like a roadmap step; =ask: it waits for the owner's OK like the self-review's ideas."""
    env = env if env is not None else os.environ
    slow = summary(root, jobs=jobs, window_s=7 * 86400)["slowest"]
    if not slow:
        return {"ok": True, "added": None, "why": "not enough measurements yet"}
    if any(i.get("kind") == "speed" and not i.get("done") for i in evolve_obj.ideas()):
        return {"ok": True, "added": None, "why": "a speed idea is still open"}
    ask = str(env.get("LOKI_SPEED_IDEAS", "auto")).strip().lower() == "ask"
    out = evolve_obj.add_idea("LOKI's idea (speed watch): " + idea_for(slow), by="loki", approved=not ask, kind="speed")
    return {"ok": bool(out.get("ok")), "added": out.get("idea"), "slowest": slow}
