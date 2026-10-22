"""LOKI tests Forge (owner 2026-10-22: "start using loki to test the forge and everything, use it to send out
different agents"). The autopilot's `qa` duty, on every machine running the engine:

  1. sweep    when LOKI is idle, every LOKI_FORGE_QA_S (default 6 h), run tools/forge_qa.py in the background: every
              menu row, button, hotbox / wheel entry and command of Forge, in a real (headless) browser
  2. triage   compare the report with the last runs (harness_data/qa/known.json): what is new, what is fixed, what
              keeps coming back. Timing problems (slow / hangs) count only when they repeat - a busy machine is not a bug
  3. propose  up to MAX_IDEAS new problems become "LOKI's idea (Forge QA)" in Settings > Lab, each with how to reproduce
              it. LOKI_FORGE_QA_IDEAS=auto (default): approved at once, like the speed watch's measured ideas, so evolve's
              improve agent fixes them in its own worktree with every test and ships through tools/ship.py; =ask: they
              wait for the owner's "Build it".
  4. report   one line in the autopilot log + the full JSON report; the owner sees both in the work strip

Nothing here edits the repo or ships by itself - the fixing goes through evolve, which already has the rules
(own worktree, all tests, tools/ship.py).

    LOKI_FORGE_QA=auto|on|off      auto (default): on where Playwright is installed
    LOKI_FORGE_QA_S                seconds between sweeps (default 21600)
    LOKI_FORGE_QA_IDEAS=auto|ask   (default auto)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

MAX_IDEAS = 3
TIMING = ("slow:", "hangs")


def enabled(env: dict | None = None) -> bool:
    env = env if env is not None else os.environ
    v = str(env.get("LOKI_FORGE_QA", "auto")).strip().lower()
    if v in ("off", "0", "no", "false"):
        return False
    if v in ("on", "1", "yes", "true"):
        return True
    try:
        import importlib.util  # pylint: disable=import-outside-toplevel
        return importlib.util.find_spec("playwright") is not None
    except Exception:  # noqa: BLE001
        return False


def qa_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "qa"


def start(repo: Path, data_dir: Path):
    """The sweep as a background process (it takes a minute or three); returns a Popen."""
    out = qa_dir(data_dir) / "forge_qa.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    log = open(qa_dir(data_dir) / "forge_qa.log", "w", encoding="utf-8")  # noqa: SIM115 - the process owns it
    return subprocess.Popen([sys.executable, str(Path(repo) / "tools" / "forge_qa.py"), "--out", str(out)],
                            cwd=str(repo), stdout=log, stderr=subprocess.STDOUT)


def problems(report: dict) -> list:
    """Every problem in a report as {"part", "where", "problem", "sig"}."""
    out = []
    for part in ("menus", "buttons", "hotbox", "commands"):
        for it in report.get(part) or []:
            where = str(it.get("where") or it.get("label") or it.get("id") or part)
            prob = str(it.get("problem", ""))
            # the signature ignores numbers (sizes, seconds, counts), so the same problem matches run to run
            sig = re.sub(r"\d+(\.\d+)?", "#", part + "|" + where + "|" + prob.split(":")[0])
            out.append({"part": part, "where": where, "problem": prob, "sig": sig})
    return out


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def triage(report: dict, data_dir: Path, now: float | None = None) -> dict:
    """New / fixed / repeating problems against the last runs; known.json is updated."""
    now = time.time() if now is None else now
    path = qa_dir(data_dir) / "known.json"
    known = _load(path)
    seen = known.get("seen", {})
    probs = problems(report)
    sigs = {p["sig"] for p in probs}
    fixed = [s for s, v in seen.items() if v.get("last_run") == known.get("runs", 0) and s not in sigs]
    runs = int(known.get("runs", 0)) + 1
    ready = []
    for p in probs:
        rec = seen.setdefault(p["sig"], {"count": 0, "first": now})
        rec["count"] = int(rec.get("count", 0)) + 1
        rec["last_run"] = runs
        rec["last"] = now
        rec["text"] = (p["where"] + ": " + p["problem"])[:300]
        timing = any(p["problem"].startswith(t) for t in TIMING)
        if not rec.get("proposed") and (rec["count"] >= 2 or not timing):
            ready.append(p)
    known.update({"seen": seen, "runs": runs, "t": now})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(known, indent=1), encoding="utf-8")
    return {"problems": probs, "ready": ready, "fixed": fixed, "runs": runs}


def idea_text(p: dict) -> str:
    return ("LOKI's idea (Forge QA): fix %s - %s. Reproduce: python tools/forge_qa.py --only %s (report in "
            "harness_data/qa/forge_qa.json); add a test that fails before the fix." % (p["where"][:160], p["problem"][:200], p["part"]))


def propose(evolve_obj, tri: dict, data_dir: Path, env: dict | None = None) -> list:
    """Up to MAX_IDEAS ready problems become Lab ideas (not ones already open)."""
    env = env if env is not None else os.environ
    if evolve_obj is None:
        return []
    ask = str(env.get("LOKI_FORGE_QA_IDEAS", "auto")).strip().lower() == "ask"
    open_titles = {i.get("title", "") for i in evolve_obj.ideas() if i.get("kind") == "qa" and not i.get("done")}
    path = qa_dir(data_dir) / "known.json"
    known = _load(path)
    added = []
    for p in tri["ready"]:
        if len(added) >= MAX_IDEAS:
            break
        text = idea_text(p)
        if any(p["where"][:60] in t for t in open_titles):
            continue
        out = evolve_obj.add_idea(text, by="loki", approved=not ask, kind="qa")
        if out.get("ok"):
            added.append(out["idea"])
            known.setdefault("seen", {}).setdefault(p["sig"], {})["proposed"] = out["idea"].get("id", True)
    if added:
        path.write_text(json.dumps(known, indent=1), encoding="utf-8")
    return added


def settle(evolve_obj, data_dir: Path, env: dict | None = None, now: float | None = None) -> str:
    """After a sweep finished: triage, propose, and the one line for the autopilot log."""
    report = _load(qa_dir(data_dir) / "forge_qa.json")
    if not report:
        return "Forge QA: the sweep left no report (see harness_data/qa/forge_qa.log)."
    tri = triage(report, data_dir, now=now)
    added = propose(evolve_obj, tri, data_dir, env=env)
    checked = "%s menu rows, %s buttons, %s commands" % (report.get("menu_rows_checked", "?"), report.get("buttons_checked", "?"),
                                                         report.get("commands_total", "?"))
    line = "Forge QA: %d problem(s) over %s" % (len(tri["problems"]), checked)
    if tri["fixed"]:
        line += "; %d fixed since the last run" % len(tri["fixed"])
    if added:
        line += "; proposed %s in Settings > Lab" % ", ".join(i.get("id", "?") for i in added)
    return line + "."
