"""The tool health map: every tool, MCP server, add-on, connector and the computer/browser, with a live status
and a one-click fix - and dead tools hidden from the model so a small model does not waste steps on them.

For each item: installed? configured? last success, last error (secrets scrubbed), calls/failures, and a fix
the window can run (GET /tools/health, POST /tools/health/fix; Settings > Tools).

When is a tool DEAD (hidden from the model)?
  - it needs something that is not there: a connector that is not set up, a missing key or add-on
    (`requirement()` - cheap checks, cached 30 s); or
  - its last 3 calls failed for a reason of the ENVIRONMENT (cannot reach, not installed, not set up,
    401/403, no module ...): hidden for 30 minutes, then offered again (a half-open circuit breaker).
    A failure that is the model's fault (bad arguments, a file that does not exist) never hides a tool.
A DENIED (policy / owner said no) is not a failure. Persisted in harness_data/tool_health.json.
"""
from __future__ import annotations

import atexit
import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

DEAD_AFTER = int(os.getenv("LOKI_TOOL_DEAD_AFTER", "3"))
COOLDOWN_S = float(os.getenv("LOKI_TOOL_COOLDOWN_S", "1800"))
PROBE_TTL_S = 30.0
ENV_MARKERS = ("not installed", "is not set up", "not set up", "cannot reach", "could not reach", "connection refused",
               "timed out", "timeout", "no module named", "not available", "not configured", "unauthorized",
               "http 401", "http 403", "refused the sign-in", "nothing is listening", "needs a key", "no api key",
               "not signed in", "is not running", "name or service not known", "getaddrinfo failed", "unreachable",
               "is not enabled", "not on path", "cannot find the program")


def classify(result: Any) -> tuple:
    """('ok' | 'fail' | 'denied', environmental: bool) for one tool result."""
    text = str(result if result is not None else "").strip()
    low = text[:400].lower()
    if low.startswith(("denied", "stopped")):
        return "denied", False
    if low.startswith(("error", "traceback", "blocked")) or low.startswith("failed"):
        if low.startswith("error: unknown tool"):
            return "denied", False
        return "fail", any(m in low for m in ENV_MARKERS)
    return "ok", False


class Health:
    def __init__(self, path: Path | None = None, redact: Callable[[str], str] | None = None) -> None:
        self.path = Path(path) if path else None
        self.redact = redact or (lambda s: s)
        self.data: dict = {"tools": {}}
        self.lock = threading.Lock()
        self._dirty_at = 0.0
        self._saved_at = 0.0
        if self.path and self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("tools"), dict):
                    self.data = loaded
            except (OSError, ValueError):
                pass

    def _rec(self, name: str) -> dict:
        return self.data["tools"].setdefault(name, {"calls": 0, "fails": 0, "streak": 0, "env_streak": 0, "denied": 0,
                                                    "last_ok": 0.0, "last_err_t": 0.0, "last_err": "", "hidden_until": 0.0})

    def record(self, name: str, result: Any, now: float | None = None) -> str:
        now = now or time.time()
        kind, env = classify(result)
        with self.lock:
            rec = self._rec(str(name))
            rec["calls"] += 1
            rec["t"] = now
            if kind == "ok":
                rec.update(last_ok=now, streak=0, env_streak=0, hidden_until=0.0)
            elif kind == "denied":
                rec["denied"] += 1
            else:
                rec["fails"] += 1
                rec["streak"] += 1
                rec["env_streak"] = rec["env_streak"] + 1 if env else 0
                rec["last_err_t"] = now
                rec["last_err"] = self.redact(str(result))[:300]
                if rec["env_streak"] >= DEAD_AFTER:
                    rec["hidden_until"] = now + COOLDOWN_S
            self._dirty_at = now
        self.save(force=kind == "fail")
        return kind

    def reset(self, name: str) -> None:
        with self.lock:
            rec = self._rec(str(name))
            rec.update(streak=0, env_streak=0, hidden_until=0.0, t=time.time())
        self.save(force=True)

    def failing(self, name: str, now: float | None = None) -> str:
        rec = self.data["tools"].get(str(name))
        if not rec:
            return ""
        if rec.get("hidden_until", 0) > (now or time.time()):
            return "failed %d times in a row: %s" % (rec.get("env_streak", 0), rec.get("last_err", "")[:160])
        return ""

    def get(self, name: str) -> dict:
        return dict(self.data["tools"].get(str(name)) or {})

    def save(self, force: bool = False) -> None:
        if not self.path:
            return
        now = time.time()
        if not force and now - self._saved_at < 5:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".%d.tmp" % os.getpid())
            with self.lock:
                # The engine and its background jobs (separate processes) share this file: keep, per tool,
                # whichever record was updated last, so one process never wipes what another learned.
                try:
                    disk = json.loads(self.path.read_text(encoding="utf-8")).get("tools", {})
                except (OSError, ValueError, AttributeError):
                    disk = {}
                for name, rec in disk.items():
                    mine = self.data["tools"].get(name)
                    if isinstance(rec, dict) and (mine is None or rec.get("t", 0) > mine.get("t", 0)):
                        self.data["tools"][name] = rec
                tmp.write_text(json.dumps(self.data, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self.path)
            self._saved_at = now
        except OSError:
            pass


# ------------------------------------------------------------------ requirements (cheap probes)
_PROBES: dict = {}
REQUIREMENTS: dict = {}          # tool name -> callable() -> "" or a reason (registered by loki.py / connectors)


def require(name: str, check: Callable[[], str]) -> None:
    REQUIREMENTS[name] = check


def _cached(name: str, fn: Callable[[], str]) -> str:
    hit = _PROBES.get(name)
    if hit and time.time() - hit[0] < PROBE_TTL_S:
        return hit[1]
    try:
        reason = str(fn() or "")
    except Exception as exc:  # noqa: BLE001
        reason = "check failed: %s" % exc
    _PROBES[name] = (time.time(), reason)
    return reason


def clear_probes() -> None:
    _PROBES.clear()


def requirement(name: str) -> str:
    fn = REQUIREMENTS.get(name)
    return _cached(name, fn) if fn else ""


def port_open(url: str, timeout: float = 0.25) -> bool:
    parsed = urlparse(url if "://" in url else "http://" + url)
    try:
        with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or (443 if parsed.scheme == "https" else 80)), timeout):
            return True
    except OSError:
        return False


HEALTH: Health | None = None


def default(data_dir: Path | None = None, redact: Callable | None = None) -> Health:
    global HEALTH
    if HEALTH is None:
        HEALTH = Health(Path(data_dir) / "tool_health.json" if data_dir else None, redact=redact)
        atexit.register(lambda: HEALTH.save(force=True) if HEALTH is not None else None)   # the last records too
    return HEALTH


def offerable(name: str) -> bool:
    """False when the tool is dead right now (its requirement is missing, or it keeps failing)."""
    if requirement(name):
        return False
    return not (HEALTH is not None and HEALTH.failing(name))


def why_hidden(name: str) -> str:
    return requirement(name) or (HEALTH.failing(name) if HEALTH is not None else "")


# ------------------------------------------------------------------ the map
def _item(id_: str, kind: str, label: str, installed: bool, configured: bool, status: str, detail: str = "",
          fix: dict | None = None, **extra) -> dict:
    out = {"id": id_, "kind": kind, "label": label, "installed": bool(installed), "configured": bool(configured),
           "status": status, "detail": detail, "fix": fix or {}}
    out.update(extra)
    return out


def _with_stats(item: dict, health: Health | None, name: str) -> dict:
    rec = health.get(name) if health else {}
    item.update(calls=rec.get("calls", 0), fails=rec.get("fails", 0), last_ok=rec.get("last_ok", 0.0),
                last_err_t=rec.get("last_err_t", 0.0), last_err=rec.get("last_err", ""))
    failing = health.failing(name) if health else ""
    if failing and item["status"] == "ok":
        item["status"] = "failing"
        item["detail"] = failing
        item["fix"] = {"action": "reset", "label": "Try it again"}
    return item


def build(agent: Any, health: Health | None = None, extra: list | None = None) -> dict:
    """Every tool/MCP server/add-on/connector, one dict each, plus a summary. `agent` is the loki module."""
    health = health or HEALTH
    items: list = []
    offered = set(getattr(agent, "MODEL_TOOL_NAMES", set()))
    categories = getattr(agent, "TOOL_CATEGORIES", {})
    enabled_cat = getattr(agent, "CATEGORIES", {})
    cap_tools = {}
    try:
        import policy  # pylint: disable=import-outside-toplevel
        cap_tools = dict(policy.CAPABILITY_TOOLS)
    except Exception:  # noqa: BLE001
        pass
    registry = getattr(agent, "CAPABILITIES", None)
    category_of = {t: c for c, names in categories.items() for t in names}
    godot = getattr(agent, "GODOT_ONLY_TOOLS", set())
    in_godot = bool(getattr(agent, "is_godot_workspace", lambda: False)())
    for name in sorted(getattr(agent, "LOCAL_TOOLS", {})):
        if name not in offered:
            continue
        cat = category_of.get(name, "")
        status, detail, fix = "ok", "", {}
        configured = True
        if name in godot and not in_godot:
            status, detail = "idle", "only inside a Godot project"
        elif cat and not enabled_cat.get(cat, True):
            status, detail, fix = "off", "the %s group is switched off" % cat, {"action": "enable_category", "arg": cat,
                                                                              "label": "Turn %s on" % cat}
        elif name in cap_tools and registry is not None and not registry.is_enabled(cap_tools[name]):
            status, detail = "off", "needs the %s add-on" % cap_tools[name]
            fix = {"action": "enable_addon", "arg": cap_tools[name], "label": "Turn on %s" % cap_tools[name]}
        else:
            reason = requirement(name)
            if reason:
                configured = False
                status, detail = "needs_setup", reason
                fix = {"action": "configure", "arg": name, "label": "Set up"}
        items.append(_with_stats(_item(name, "tool", name, True, configured, status, detail, fix, category=cat), health, name))
    # MCP servers
    try:
        config = json.loads(Path(agent.MCP_CONFIG).read_text(encoding="utf-8")).get("mcpServers", {})
    except Exception:  # noqa: BLE001
        config = {}
    connected = getattr(agent, "MCP_SESSIONS_BY_SERVER", {})
    for name, spec in sorted(config.items()):
        if not isinstance(spec, dict):
            continue
        try:
            reason = agent._server_skip_reason(spec, name)   # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            reason = str(exc)
        if name in connected:
            status, detail, fix = "ok", "connected", {}
        elif reason.startswith("disabled"):
            status, detail, fix = "off", reason, {"action": "enable_mcp", "arg": name, "label": "Turn on (restart LOKI)"}
        elif reason.startswith("needs '"):
            status, detail, fix = "missing", reason, {"action": "hint", "label": "How to install",
                                                     "arg": "install %s, then restart LOKI" % spec.get("requires_cmd", "")}
        elif reason:
            status, detail, fix = "needs_setup", reason, {"action": "hint", "label": "How to set up", "arg": reason}
        else:
            status, detail, fix = "broken", "not connected (starting, or it failed - see the engine log)", {
                "action": "hint", "label": "Details", "arg": "The engine log (harness_data/logs) has the [mcp] line for %s." % name}
        items.append(_item("mcp:" + name, "mcp", name, status not in ("missing",), not reason, status, detail, fix,
                           source=str(spec.get("command", "") or spec.get("url", ""))))
    # add-ons (capabilities)
    if registry is not None:
        try:
            import addons_install  # pylint: disable=import-outside-toplevel
        except Exception:  # noqa: BLE001
            addons_install = None
        for entry in registry.entries():
            name = entry.get("name", "")
            st = entry.get("status", "")
            missing = entry.get("missing", [])
            plan = addons_install.plan(name) if addons_install else {"pip": [], "manual": ""}
            if st == "enabled":
                status, detail, fix = "ok", "on", {}
            elif st == "missing":
                status, detail = "missing", "missing " + ", ".join(missing)
                fix = ({"action": "install", "arg": name, "label": "Install"} if plan.get("pip") else
                       {"action": "hint", "label": "How to install", "arg": plan.get("manual") or entry.get("install", "")})
            elif st == "changed":
                status, detail, fix = "needs_setup", "changed since you turned it on - review it", {
                    "action": "enable_addon", "arg": name, "label": "Review and turn on"}
            elif st in ("invalid", "reference"):
                status, detail, fix = "idle", st, {}
            else:
                status, detail, fix = "off", "off", {"action": "enable_addon", "arg": name, "label": "Turn on"}
            items.append(_item("addon:" + name, "addon", name, st != "missing", st == "enabled", status, detail, fix,
                               high_risk=bool(set(entry.get("manifest", {}).get("permissions", []) or entry.get("permissions", []))
                                              & {"network", "process:spawn", "computer:host"})))
    for item in extra or []:
        items.append(item)
    summary: dict = {}
    for it in items:
        summary[it["status"]] = summary.get(it["status"], 0) + 1
    hidden = sorted(n for n in getattr(agent, "LOCAL_TOOLS", {}) if n in offered and not offerable(n))
    return {"items": items, "summary": summary, "hidden": hidden, "total": len(items)}
