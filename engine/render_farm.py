"""Studio's render farm manager - a Deadline / Eclipse-style queue over LOKI's GPU workers.

Owner 2026-10-25: "i want the render to be more like a render farm and management software like eclipse using ai and
other similar using gpu". Eclipse (the background render manager for Houdini / Blender) keeps a local job queue that
renders one after another, tracks each job live, watches for failures and keeps a render history; Deadline adds
priorities, pools, dependencies, per-worker error limits (a worker that keeps failing a job is blacklisted for it) and
a Monitor with Jobs / Workers / Tasks. This module is that, for LOKI:

  * WORKERS are GPU render nodes - a ComfyUI server each (the AI Renderer's engine, engine/ai_renderer.py). Found by
    themselves: the Studio's saved ComfyUI, every linked LOKI machine (engine/peers.py) on ComfyUI's port, and any you
    add. Each is probed (GPU, VRAM, queue) every few seconds, so the Monitor shows what is online, busy or idle.
  * JOBS wrap an AI Renderer job (its passes uploaded from Forge). Priority 0-100, a pool (gpu / any / a name),
    dependencies (start after another job finishes), max errors, suspend / resume / requeue / cancel / delete.
  * The SCHEDULER (a daemon thread, `tick()` every 2 s - pure planning in `plan()`, so tests drive it) hands the best
    queued job (priority, then age) to the best idle worker (online, enabled, in the pool, not blacklisted, most free
    VRAM, fewest errors), starts it there (ai_renderer.start(url=worker)), follows its status, and on a failure
    blacklists that worker after 2 errors and requeues on another until `max_errors`.
  * The AI part - the FARM DOCTOR: every failure is read and explained with the fix (out of VRAM, worker offline,
    a missing ComfyUI node or model, a failed preflight ...), offline and instant (rule-based, no model needed), and
    an ETA per job from the farm's own history (seconds per frame per worker and workflow).
  * HISTORY: every finished job, kept (last 500), so the Studio keeps its render history across restarts.

    GET  /farm/status                       {workers, jobs, history, stats}
    POST /farm/submit   {render_job, name?, priority?, pool?, depends?, max_errors?}
    POST /farm/job      {id, action: suspend|resume|requeue|cancel|delete|priority, value?}
    POST /farm/worker   {url?, name?, enabled?, pools?, remove?}
    POST /farm/diagnose {id}                the farm doctor's reading of a job's failures

Standard library only. State in <data>/farm/farm.json.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import ai_renderer

STATES = ("queued", "active", "suspended", "failed", "completed", "cancelled")
DONE = ("completed", "failed", "cancelled")
COMFY_PORT = 8188
PROBE_EVERY = 5.0
BLACKLIST_AFTER = 2
_LOCK = threading.RLock()
_FARMS: dict = {}


def _now() -> float:
    return time.time()


# ------------------------------------------------------------------ the farm doctor (the AI reading of a failure)
DOCTOR = [
    (r"out of memory|CUDA out of memory|OOM|allocat\w* .*memory|not enough (video )?memory",
     "The GPU ran out of video memory.",
     "Render smaller (size or frames), use a smaller GGUF quant (Q4 instead of Q8), or send it to the worker with the most free VRAM; close other GPU apps on that machine."),
    (r"connection refused|timed out|timeout|unreachable|no route|name or service|getaddrinfo|ECONNRESET|connection reset",
     "The worker could not be reached.",
     "Start ComfyUI on that machine with --listen (so the LAN can reach it), check it is awake and on the network, or disable the worker."),
    (r"missing node|node type|class_type|not found in comfyui|unknown node|no such node",
     "The worker's ComfyUI is missing a node this workflow uses.",
     "Install the workflow's custom nodes on that worker (ComfyUI-Manager > Install Missing Custom Nodes), restart ComfyUI, then Requeue."),
    (r"(model|ckpt|checkpoint|gguf|lora|vae|clip|unet)\b.*(not found|missing|no such)|value not in list",
     "A model file the workflow needs is not on the worker.",
     "Download the model into that worker's ComfyUI models folder (the preflight report names it), or pin the job to a worker that has it (pool)."),
    (r"preflight",
     "The preflight check stopped the job before it used the GPU.",
     "Open the job's preflight report in Studio - it lists exactly what is missing - fix that and Requeue."),
    (r"passes|no frames|upload",
     "The job has no input passes.",
     "Render the passes from a Forge camera first (Studio > Render passes), then submit again."),
    (r"cancel",
     "The job was cancelled.",
     "Requeue it if that was a mistake."),
]


def diagnose(errors: list) -> list:
    """What went wrong and how to fix it, per distinct cause, newest first. Never invents a cause it can't see."""
    out, seen = [], set()
    for e in reversed(errors or []):
        msg = str(e.get("msg") if isinstance(e, dict) else e)
        for pat, cause, fix in DOCTOR:
            if re.search(pat, msg, re.I):
                if cause not in seen:
                    seen.add(cause)
                    out.append({"cause": cause, "fix": fix, "seen": msg[:200], "worker": e.get("worker") if isinstance(e, dict) else None})
                break
        else:
            if "unknown" not in seen:
                seen.add("unknown")
                out.append({"cause": "Not a failure the doctor knows yet.", "fix": "Read the job's log in Studio; Requeue on another worker to see if it is the machine or the job.",
                            "seen": msg[:200], "worker": e.get("worker") if isinstance(e, dict) else None})
    return out


# ------------------------------------------------------------------ pure scheduling
def eligible(jobs: dict) -> list:
    """Queued jobs whose dependencies are done, best first: priority (high first), then submitted (old first)."""
    out = []
    for j in jobs.values():
        if j["status"] != "queued":
            continue
        deps = [jobs.get(d) for d in j.get("depends") or []]
        if any(d is not None and d["status"] != "completed" for d in deps):
            continue
        out.append(j)
    out.sort(key=lambda j: (-int(j.get("priority", 50)), j.get("submitted", 0)))
    return out


def worker_fits(job: dict, w: dict) -> bool:
    if not w.get("enabled", True) or not w.get("online") or w.get("busy"):
        return False
    if w["url"] in (job.get("blacklist") or []):
        return False
    pool = job.get("pool") or "gpu"
    return pool == "any" or pool in (w.get("pools") or ["gpu"])


def worker_score(w: dict, stats: dict | None = None) -> float:
    """More free VRAM is better; a loaded GPU and past failures are worse."""
    free = float(w.get("vram_free") or 0) / 1e9
    st = (stats or {}).get(w["url"], {})
    ok, bad = st.get("ok", 0), st.get("failed", 0)
    rate = (ok + 1) / (ok + bad + 2)                 # Laplace: an unknown worker starts at 0.5
    return free * 10 + rate * 20 - float(w.get("queue", 0)) * 5


def plan(jobs: dict, workers: list, stats: dict | None = None) -> list:
    """[(job id, worker url)] - each idle worker gets at most one job, best job to best worker."""
    free = [dict(w) for w in workers]
    out = []
    for j in eligible(jobs):
        fit = [w for w in free if worker_fits(j, w)]
        if not fit:
            continue
        best = max(fit, key=lambda w: worker_score(w, stats))
        best["busy"] = True
        out.append((j["id"], best["url"]))
    return out


def eta(job: dict, history: list, now: float | None = None) -> float | None:
    """Seconds left, from this farm's own seconds-per-frame for the workflow (on that worker when it has history)."""
    frames = max(1, int(job.get("frames") or 1))
    rates = [h["secs"] / max(1, h.get("frames") or 1) for h in history
             if h.get("status") == "completed" and h.get("secs") and h.get("workflow") == job.get("workflow")
             and (not job.get("worker") or h.get("worker") == job.get("worker"))]
    if not rates:
        return None
    total = frames * sum(rates[-10:]) / len(rates[-10:])
    if job.get("status") == "active" and job.get("started"):
        return max(0.0, total - ((now or _now()) - job["started"]))
    return total


# ------------------------------------------------------------------ the farm
class Farm:
    def __init__(self, state: Any = None, probe: Callable[[str], dict] | None = None,
                 starter: Callable[..., dict] | None = None, env: dict | None = None):
        self.state = state
        self.env = env
        self.dir = ai_renderer.data_dir(state) / "farm"
        self.file = self.dir / "farm.json"
        self.probe = probe or self._probe
        self.starter = starter or (lambda st, job, url: ai_renderer.start(st, job, url=url))
        self.live: dict = {}               # url -> probe result
        self.probed = 0.0
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.data = self._load()

    # ---- storage
    def _load(self) -> dict:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        d.setdefault("jobs", {}); d.setdefault("workers", {}); d.setdefault("history", []); d.setdefault("stats", {})
        return d

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        tmp.replace(self.file)

    # ---- workers
    def candidates(self) -> list:
        """Every ComfyUI the farm knows: the saved one, the linked machines (on ComfyUI's port), the added ones."""
        seen, out = set(), []

        def add(url: str, name: str, source: str) -> None:
            url = str(url or "").rstrip("/")
            if not url or url in seen:
                return
            seen.add(url)
            out.append({"url": url, "name": name, "source": source})
        s = ai_renderer.settings(self.state)
        w = ai_renderer.where(s["url"], self.env)
        add(s["url"], w.get("peer") or ("This computer" if w["place"] == "local" else urlparse(s["url"]).hostname or "ComfyUI"), "studio")
        try:
            import peers  # pylint: disable=import-outside-toplevel
            for p in peers.peers(self.env):
                host = urlparse(p.get("url") or "").hostname
                if host and not p.get("relay"):
                    add("http://%s:%d" % (host, COMFY_PORT), p.get("name") or host, "linked machine")
        except Exception:  # noqa: BLE001 - peers is optional
            pass
        for url, cfg in self.data["workers"].items():
            add(url, cfg.get("name") or urlparse(url).hostname or url, cfg.get("source") or "added")
        return out

    def _probe(self, url: str) -> dict:
        cl = ai_renderer.Comfy(url, timeout=3.0)
        st = cl.system_stats()
        dev = (st.get("devices") or [{}])[0]
        try:
            q = cl.queue()
            queue = len(q.get("queue_running") or []) + len(q.get("queue_pending") or [])
        except Exception:  # noqa: BLE001
            queue = 0
        return {"online": True, "gpu": dev.get("name") or "", "vram_total": dev.get("vram_total") or 0,
                "vram_free": dev.get("vram_free") or 0, "queue": queue,
                "os": (st.get("system") or {}).get("os") or "", "comfyui": (st.get("system") or {}).get("comfyui_version") or ""}

    def refresh_workers(self, force: bool = False) -> None:
        if not force and _now() - self.probed < PROBE_EVERY:
            return
        self.probed = _now()
        for c in self.candidates():
            try:
                r = self.probe(c["url"])
            except Exception as exc:  # noqa: BLE001 - offline is a state, not an error
                r = {"online": False, "why": str(exc)[:160]}
            r["seen"] = _now() if r.get("online") else (self.live.get(c["url"], {}).get("seen") or 0)
            self.live[c["url"]] = r

    def workers(self) -> list:
        busy = {j["worker"] for j in self.data["jobs"].values() if j["status"] == "active" and j.get("worker")}
        out = []
        for c in self.candidates():
            cfg = self.data["workers"].get(c["url"], {})
            live = self.live.get(c["url"], {"online": False, "why": "not probed yet"})
            st = self.data["stats"].get(c["url"], {})
            out.append({**c, **live, "name": cfg.get("name") or c["name"], "enabled": cfg.get("enabled", True),
                        "pools": cfg.get("pools") or ["gpu"], "busy": c["url"] in busy or bool(live.get("queue")),
                        "rendering": next((j["id"] for j in self.data["jobs"].values() if j["status"] == "active" and j.get("worker") == c["url"]), None),
                        "ok": st.get("ok", 0), "failed": st.get("failed", 0)})
        return out

    def set_worker(self, data: dict) -> dict:
        url = str(data.get("url") or "").strip().rstrip("/")
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.path not in ("", "/"):
            raise ai_renderer.RenderError("A worker is a ComfyUI address like http://192.168.1.50:8188")
        with _LOCK:
            if data.get("remove"):
                self.data["workers"].pop(url, None)
            else:
                cfg = self.data["workers"].setdefault(url, {"source": "added"})
                if "name" in data:
                    cfg["name"] = str(data["name"] or "")[:60]
                if "enabled" in data:
                    cfg["enabled"] = bool(data["enabled"])
                if "pools" in data:
                    pools = data["pools"] if isinstance(data["pools"], list) else str(data["pools"]).split(",")
                    cfg["pools"] = [x.strip()[:24] for x in pools if str(x).strip()][:8] or ["gpu"]
            self.save()
        self.refresh_workers(force=True)
        return {"workers": self.workers()}

    # ---- jobs
    def submit(self, data: dict) -> dict:
        rj = str(data.get("render_job") or "")
        m = ai_renderer.manifest(self.state, rj)
        if m is None:
            raise ai_renderer.RenderError("no such render job - render its passes in Studio first")
        if m.get("kind") != "ai":
            raise ai_renderer.RenderError("path-traced jobs render in Forge's window; the farm runs AI Renderer jobs")
        with _LOCK:
            jid = "farm-%s-%s" % (time.strftime("%m%d%H%M%S"), secrets.token_hex(2))
            deps = [d for d in (data.get("depends") or []) if d in self.data["jobs"]]
            job = {"id": jid, "name": str(data.get("name") or m.get("name") or rj)[:120], "render_job": rj, "kind": "ai",
                   "workflow": m.get("workflow"), "frames": int(m.get("frames") or 0), "status": "queued",
                   "priority": max(0, min(100, int(data.get("priority", 50)))), "pool": str(data.get("pool") or "gpu")[:24],
                   "depends": deps, "max_errors": max(1, min(20, int(data.get("max_errors", 3)))), "errors": [], "blacklist": [],
                   "attempts": [rj], "submitted": _now(), "started": None, "finished": None, "worker": None, "progress": 0.0,
                   "log": [[_now(), "submitted"]]}
            self.data["jobs"][jid] = job
            self.save()
        return job

    def _log(self, job: dict, msg: str) -> None:
        job["log"] = (job.get("log") or [])[-60:] + [[_now(), msg[:300]]]

    def action(self, jid: str, act: str, value: Any = None) -> dict:
        with _LOCK:
            job = self.data["jobs"].get(jid)
            if not job:
                raise ai_renderer.RenderError("no such farm job")
            if act == "suspend" and job["status"] == "queued":
                job["status"] = "suspended"
            elif act == "resume" and job["status"] == "suspended":
                job["status"] = "queued"
            elif act == "priority":
                job["priority"] = max(0, min(100, int(value)))
            elif act == "requeue" and job["status"] in DONE + ("suspended",):
                self._fresh_attempt(job)
                job.update(status="queued", errors=[], blacklist=[], worker=None, progress=0.0, finished=None)
            elif act == "cancel" and job["status"] not in DONE:
                if job["status"] == "active":
                    try:
                        ai_renderer.cancel(self.state, job["attempts"][-1])
                    except ai_renderer.RenderError:
                        pass
                job.update(status="cancelled", finished=_now())
                self._archive(job)
            elif act == "delete" and job["status"] != "active":
                self.data["jobs"].pop(jid)
                self.save()
                return {"deleted": jid}
            else:
                raise ai_renderer.RenderError("can't %s a job that is %s" % (act, job["status"]))
            self._log(job, act + ("" if value is None else " %s" % value))
            self.save()
            return job

    def _fresh_attempt(self, job: dict) -> None:
        """A run can't be restarted in place (ai_renderer): a retry copies its passes into a new render job."""
        last = job["attempts"][-1]
        m = ai_renderer.manifest(self.state, last)
        if m and m.get("status") != "idle":
            job["attempts"].append(ai_renderer.retry(self.state, last)["job"])

    def _archive(self, job: dict) -> None:
        secs = (job["finished"] - job["started"]) if job.get("started") and job.get("finished") else None
        self.data["history"] = (self.data["history"] + [{"id": job["id"], "name": job["name"], "status": job["status"],
                                "worker": job.get("worker"), "workflow": job.get("workflow"), "frames": job.get("frames"),
                                "secs": secs, "finished": job.get("finished"), "render_job": job["attempts"][-1]}])[-500:]

    def _stat(self, url: str, key: str) -> None:
        st = self.data["stats"].setdefault(url, {"ok": 0, "failed": 0})
        st[key] = st.get(key, 0) + 1

    # ---- the loop
    def sync(self) -> None:
        """Follow every active job's render (ai_renderer manifest) and react to how it ended."""
        for job in self.data["jobs"].values():
            if job["status"] != "active":
                continue
            m = ai_renderer.manifest(self.state, job["attempts"][-1]) or {}
            job["progress"] = float(m.get("progress") or job.get("progress") or 0)
            st = m.get("status")
            if st == "succeeded":
                job.update(status="completed", finished=_now(), progress=1.0)
                self._stat(job["worker"], "ok")
                self._log(job, "completed on %s" % job["worker"])
                self._archive(job)
            elif st in ("failed", "cancelled"):
                msg = ((m.get("log") or [{}])[-1].get("msg") or st)
                if st == "cancelled" and not job["errors"]:
                    job.update(status="cancelled", finished=_now())
                    self._archive(job)
                    continue
                job["errors"].append({"worker": job["worker"], "msg": msg, "t": _now()})
                self._stat(job["worker"], "failed")
                if sum(1 for e in job["errors"] if e["worker"] == job["worker"]) >= BLACKLIST_AFTER:
                    job["blacklist"] = sorted(set(job["blacklist"]) | {job["worker"]})
                    self._log(job, "blacklisted %s for this job" % job["worker"])
                if len(job["errors"]) >= job["max_errors"]:
                    job.update(status="failed", finished=_now())
                    self._log(job, "failed: %s" % msg)
                    self._archive(job)
                else:
                    self._fresh_attempt(job)
                    job.update(status="queued", worker=None)
                    self._log(job, "error %d/%d (%s) - requeued" % (len(job["errors"]), job["max_errors"], msg[:120]))

    def tick(self) -> list:
        with _LOCK:
            self.refresh_workers()
            self.sync()
            started = []
            for jid, url in plan(self.data["jobs"], self.workers(), self.data["stats"]):
                job = self.data["jobs"][jid]
                try:
                    self.starter(self.state, job["attempts"][-1], url)
                    job.update(status="active", worker=url, started=_now(), progress=0.0)
                    self._log(job, "started on %s" % url)
                    started.append((jid, url))
                except ai_renderer.RenderError as exc:
                    job["errors"].append({"worker": url, "msg": str(exc), "t": _now()})
                    self._log(job, "could not start on %s: %s" % (url, exc))
                    if len(job["errors"]) >= job["max_errors"]:
                        job.update(status="failed", finished=_now())
                        self._archive(job)
            self.save()
            return started

    def run(self, every: float = 2.0) -> None:
        if self.thread and self.thread.is_alive():
            return

        def loop():
            while not self.stop.wait(every):
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 - the scheduler never dies on one bad tick
                    pass
        self.thread = threading.Thread(target=loop, name="loki-render-farm", daemon=True)
        self.thread.start()

    def status(self) -> dict:
        with _LOCK:
            jobs = sorted(self.data["jobs"].values(), key=lambda j: (j["status"] in DONE, -j.get("priority", 50), j.get("submitted", 0)))
            hist = self.data["history"]
            out = []
            for j in jobs:
                e = eta(j, hist)
                out.append({**j, "eta": e, "log": j.get("log", [])[-8:],
                            "doctor": diagnose(j["errors"])[:3] if j["errors"] else []})
            ws = self.workers()
            return {"ok": True, "workers": ws, "jobs": out, "history": hist[-50:][::-1],
                    "stats": {"online": sum(1 for w in ws if w.get("online")), "workers": len(ws),
                              "active": sum(1 for j in jobs if j["status"] == "active"),
                              "queued": sum(1 for j in jobs if j["status"] == "queued"),
                              "failed": sum(1 for j in jobs if j["status"] == "failed"),
                              "vram_free": sum(float(w.get("vram_free") or 0) for w in ws if w.get("online"))}}


def farm(state: Any = None) -> Farm:
    key = str(ai_renderer.data_dir(state))
    with _LOCK:
        f = _FARMS.get(key)
        if f is None:
            f = _FARMS[key] = Farm(state)
            f.run()
        return f


def route(state: Any, method: str, path: str, body: dict | None = None) -> tuple:
    route_ = urlparse(path).path
    body = body or {}
    try:
        f = farm(state)
        if method == "GET" and route_ == "/farm/status":
            f.refresh_workers()
            return 200, f.status()
        if method == "POST" and route_ == "/farm/submit":
            return 200, {"ok": True, "job": f.submit(body)}
        if method == "POST" and route_ == "/farm/job":
            return 200, {"ok": True, "job": f.action(str(body.get("id") or ""), str(body.get("action") or ""), body.get("value"))}
        if method == "POST" and route_ == "/farm/worker":
            return 200, {"ok": True, **f.set_worker(body)}
        if method == "POST" and route_ == "/farm/diagnose":
            j = f.data["jobs"].get(str(body.get("id") or ""))
            if not j:
                return 404, {"ok": False, "error": "no such farm job"}
            return 200, {"ok": True, "doctor": diagnose(j["errors"])}
    except (ai_renderer.RenderError, ValueError, TypeError) as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}
