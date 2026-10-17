"""HTTP routes for LOKI's self-improvement systems (session 28), kept out of loki_bridge.py.

  GET  /speed                    speed watch: per-phase timings + sparklines (EVOLVE E6)
  GET  /jobs/stats[?days=30]     job success dashboard (success over time, by model, by kind, reasons,
                                 recent failures, the daily self-test, queued jobs with forecasts)
  GET  /user_tools               tools LOKI wrote for itself (EVOLVE E9)
  POST /ui/timing                {first_paint_ms, ready_ms} from app/ui/boot.js
  POST /jobs/retry_stronger      {id[, model]} - the same job again on a stronger (free) model
  POST /user_tools/toggle        {name, enabled}   (enabling re-checks a changed tool)
  POST /user_tools/check         {name}
  POST /user_tools/delete        {name}
  POST /selftest/start           start the daily self-test now
  POST /self_review/run          run the weekly self-review now (rules only: fast, no model call)

Each handler returns (status, payload). The bridge calls route(state, method, path, data, job_action).
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

GET_ROUTES = ("/speed", "/jobs/stats", "/user_tools")
POST_ROUTES = ("/ui/timing", "/jobs/retry_stronger", "/user_tools/toggle", "/user_tools/check",
               "/user_tools/delete", "/selftest/start", "/self_review/run")


def handles(method: str, path: str) -> bool:
    route = urlparse(path).path
    return route in (GET_ROUTES if method == "GET" else POST_ROUTES)


def _data_dir(state) -> Path:
    return Path(getattr(getattr(state, "agent", None), "DATA_DIR", "") or ".")


def _jobs(state) -> list:
    jobs = getattr(state, "jobs", None)
    try:
        return list(jobs.store.all()) if jobs is not None else []
    except Exception:  # noqa: BLE001
        return []


def _sync_tools(state) -> None:
    reg = getattr(getattr(state, "agent", None), "USER_TOOLS", None)
    if reg is not None:
        try:
            reg.sync()
        except Exception:  # noqa: BLE001
            pass


def route(state, method: str, path: str, data: dict | None, job_action=None) -> tuple:
    import job_stats  # pylint: disable=import-outside-toplevel
    import selftest  # pylint: disable=import-outside-toplevel
    import speed_watch  # pylint: disable=import-outside-toplevel
    import user_tools  # pylint: disable=import-outside-toplevel
    route_ = urlparse(path).path
    data = data if isinstance(data, dict) else {}
    root = _data_dir(state)
    if method == "GET":
        if route_ == "/speed":
            out = speed_watch.summary(root, jobs=_jobs(state))
            out["tools"] = speed_watch.tool_breakdown(root)
            return 200, out
        if route_ == "/jobs/stats":
            query = parse_qs(urlparse(path).query)
            try:
                days = max(1, min(int((query.get("days") or ["30"])[0]), 90))
            except ValueError:
                days = 30
            jobs = _jobs(state)
            out = job_stats.stats(jobs, root, days=days, selftest=selftest.Selftest(root).status())
            history = job_stats.rows(jobs, root)
            out["waiting"] = [{"id": j.get("id"), "title": j.get("title", ""), "status": j.get("status"),
                               "forecast": job_stats.outlook(j, history)}
                              for j in jobs if j.get("status") in ("queued", "starting", "working")][:10]
            return 200, out
        if route_ == "/user_tools":
            return 200, {"ok": True, "tools": user_tools.listing(root), "folder": str(user_tools.tools_dir(root))}
        return 404, {"ok": False, "error": "Unknown endpoint."}
    if route_ == "/ui/timing":
        kept = []
        for key, phase in (("first_paint_ms", "first_paint"), ("ready_ms", "ui_ready")):
            try:
                value = float(data.get(key))
            except (TypeError, ValueError):
                continue
            if 0 < value < 600000 and speed_watch.record(phase, value, root=root, note=str(data.get("ua", ""))[:40]):
                kept.append(phase)
        return 200, {"ok": True, "kept": kept}
    if route_ == "/jobs/retry_stronger":
        if job_action is None:
            return 503, {"ok": False, "error": "jobs are not available"}
        return job_stats.retry_stronger(state, data, job_action)
    if route_.startswith("/user_tools/"):
        name = str(data.get("name", ""))
        if route_ == "/user_tools/toggle":
            out = user_tools.set_enabled(name, bool(data.get("enabled")), root=root)
        elif route_ == "/user_tools/check":
            try:
                out = user_tools.check(name, root=root)
            except ValueError as exc:
                out = {"ok": False, "error": str(exc)}
            if not out.get("ok") and not out.get("error"):
                out["error"] = "; ".join(out.get("problems") or []) or "the check failed"
        else:
            out = user_tools.delete(name, root=root)
        _sync_tools(state)
        return (200 if out.get("ok") else 400), out
    if route_ == "/selftest/start":
        jobs = getattr(state, "jobs", None)
        if jobs is None:
            return 503, {"ok": False, "error": "Background jobs are not running."}
        line = selftest.Selftest(root).start(jobs.create)
        if not line:
            return 409, {"ok": False, "error": "a self-test is already running"}
        return (200 if line.startswith("started") else 400), {"ok": line.startswith("started"), "line": line}
    if route_ == "/self_review/run":
        ev = getattr(state, "evolve", None)
        if ev is None:
            return 503, {"ok": False, "error": "evolve is not running"}
        import self_review  # pylint: disable=import-outside-toplevel
        out = self_review.review(ev, root, jobs=_jobs(state))
        return 200, {"ok": True, "added": out["added"], "source": out["source"]}
    return 404, {"ok": False, "error": "Unknown endpoint."}
