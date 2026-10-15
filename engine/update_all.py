"""One click updates every machine: the Mac, the PC, and any other linked LOKI.

Settings > Machines (and the banner that appears when a machine is behind) has one button,
"Update everything". Pressing it on ANY machine:

  1. checks GitHub for the newest `master` (engine/updater.py; fast-forward only);
  2. asks every linked machine to update and restart (signed peer call
     POST /peer/update/apply); each one applies the update, restarts its engine, and is
     watched until its hello reports the new commit (or the step times out);
  3. then updates and restarts THIS machine last, so the window you clicked in comes back
     on the new version and can show how the others did.

A machine never loses work: the updater refuses when there are local edits or unpushed
commits, and says so. A version that fails to start is rolled back on that machine by the
app (updater.rollback) and skipped until a newer one exists.

Progress lives in PROGRESS (GET /update/everywhere) so the window can draw it live.
Pure orchestration: the network calls are injected, so tests run it with fakes.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

PROGRESS: dict = {"running": False, "started": 0.0, "finished": 0.0, "target": "", "steps": [], "note": ""}
_lock = threading.Lock()


def _step(name: str, **fields: Any) -> dict:
    for step in PROGRESS["steps"]:
        if step["machine"] == name:
            step.update(fields, updated=time.time())
            return step
    step = {"machine": name, "status": "waiting", "from": "", "to": "", "note": "", "updated": time.time()}
    step.update(fields)
    PROGRESS["steps"].append(step)
    return step


def overview(updater: Any, peer_statuses: list) -> dict:
    """Every machine's version against GitHub's newest: who is behind, who is fine."""
    mine = updater.version()
    local = updater.check(fetch=False) if hasattr(updater, "check") else {}
    latest = (local.get("latest") if local.get("ok") else "") or updater.STATE.get("latest", "") or ""
    machines = [{"machine": "this computer", "self": True, "commit": mine.get("commit", ""),
                 "dirty": mine.get("dirty", False), "online": True}]
    for peer in peer_statuses:
        hello = peer.get("hello") or {}
        version = hello.get("version") or {}
        machines.append({"machine": peer.get("name", "?"), "self": False, "online": bool(peer.get("ok")),
                         "commit": version.get("commit", ""), "dirty": bool(version.get("dirty")),
                         "error": peer.get("error", "")})
    commits = {m["commit"] for m in machines if m["online"] and m["commit"]}
    behind_of = getattr(updater, "is_behind", None)
    for m in machines:
        if m["self"] and local.get("ok"):
            m["behind"] = int(local.get("behind") or 0) > 0       # git knows exactly
        elif behind_of is not None:
            m["behind"] = bool(m["online"] and behind_of(m["commit"], latest))
        else:
            m["behind"] = bool(latest and m["commit"] and m["online"] and not latest.startswith(m["commit"][:12])
                               and not m["commit"].startswith(latest[:12]))
    return {"latest": latest, "machines": machines, "in_step": len(commits) <= 1 and not any(m["behind"] for m in machines),
            "progress": PROGRESS}


def run(updater: Any, peer_list: list, call: Callable[..., dict], hello: Callable[[dict], dict],
        restart_self: Callable[[], None], wait_s: float = 240.0, poll_s: float = 5.0,
        sleep: Callable[[float], None] = time.sleep) -> dict:
    """Update every linked machine, then this one. Returns PROGRESS when done.

    call(peer, method, path, payload) -> dict      a signed peer call (peers.call)
    hello(peer) -> dict                              that peer's hello (raises when offline)
    restart_self()                                   restart this engine on the new code
    """
    with _lock:
        if PROGRESS["running"]:
            return PROGRESS
        PROGRESS.update({"running": True, "started": time.time(), "finished": 0.0, "steps": [], "note": ""})
    try:
        state = updater.check(fetch=True)
        if not state.get("ok"):
            PROGRESS["note"] = "cannot reach GitHub: " + str(state.get("error", ""))
            return PROGRESS
        target = state.get("latest", "")
        PROGRESS["target"] = target
        for peer in peer_list:
            _step(peer["name"], status="asking")
        _step("this computer", status="waiting", **{"from": state.get("current", ""), "to": target})
        # 1) the other machines
        for peer in peer_list:
            name = peer["name"]
            try:
                reply = call(peer, "POST", "/peer/update/apply", {"target": target})
            except Exception as exc:  # noqa: BLE001 - an offline machine updates on its next start
                _step(name, status="offline", note="not reachable (%s); it updates on its next start" % type(exc).__name__)
                continue
            if not reply.get("ok", True) and reply.get("error"):
                _step(name, status="failed", note=str(reply.get("error"))[:200])
                continue
            before = (reply.get("version") or {}).get("commit", "")
            note = str(reply.get("note") or "")
            if reply.get("restarting"):
                _step(name, status="restarting", note=note, **{"from": before, "to": target})
            elif reply.get("up_to_date"):
                _step(name, status="done", note="already up to date", **{"from": before, "to": before})
                continue
            else:
                _step(name, status="failed", note=note or "it did not update", **{"from": before})
                continue
            deadline = time.monotonic() + wait_s
            while True:
                sleep(poll_s)
                try:
                    commit = ((hello(peer) or {}).get("version") or {}).get("commit", "")
                except Exception:  # noqa: BLE001 - still restarting
                    commit = ""
                if commit and target and (target.startswith(commit[:12]) or commit.startswith(target[:12])):
                    _step(name, status="done", note="running %s" % commit)
                    break
                if time.monotonic() >= deadline:
                    _step(name, status="failed",
                          note="did not come back on %s in %ds (it may have rolled back)" % (target, int(wait_s)))
                    break
        # 2) this machine, last
        result = updater.update()
        if result.get("error"):
            _step("this computer", status="failed", note=result["error"])
            return PROGRESS
        if result.get("updated") or updater.restart_needed():
            _step("this computer", status="restarting", note=result.get("note", ""))
            PROGRESS["finished"] = time.time()
            PROGRESS["running"] = False
            restart_self()
            return PROGRESS
        _step("this computer", status="done", note=result.get("note") or "already up to date")
        return PROGRESS
    finally:
        if PROGRESS["running"]:
            PROGRESS["running"] = False
            PROGRESS["finished"] = time.time()


def apply_here(updater: Any, restart_self: Callable[[], None]) -> dict:
    """What a machine does when asked (by a peer or its own window) to update now."""
    before = updater.version()
    result = updater.update()
    if result.get("error"):
        return {"ok": False, "error": result["error"], "version": before}
    if result.get("updated") or updater.restart_needed():
        threading.Timer(1.0, restart_self).start()   # reply first, then restart
        return {"ok": True, "restarting": True, "note": result.get("note", ""), "version": before}
    note = result.get("note", "")
    return {"ok": True, "up_to_date": "up to date" in note, "note": note, "version": before}
