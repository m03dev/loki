"""Self-review (EVOLVE E8): once a week LOKI reads what it learned and proposes how to get better.

Inputs, all measured (nothing invented):
  * the newest "what LOKI learned this week" report (autopilot.duty_report -> reports/learned-*.md)
  * the experience log (engine/experience.py): requests, verified / failed work, tool-call repairs
  * reflexion lessons and evolve outcomes kept in LOKI's memory (memory_core, tags reflexion / evolve)
  * the job dashboard (engine/job_stats.py): success by kind and model, top failure reasons
  * the speed watch (engine/speed_watch.py): the slowest step
  * the daily self-test (engine/selftest.py)

Output: up to 3 proposals added to Settings > Lab as "LOKI's idea" (evolve.add_idea(by="loki")):
they WAIT for the owner's OK ("Build it" / "No") before evolve builds them. A proposal that is
already open (or was declined) is not proposed again.

Two ways to write them: `ask(prompt) -> text` (one model call, when the caller passes it) turns
the facts into proposals; without it - or when its answer is unusable - fixed rules over the same
facts do. Either way every proposal names the measurement it comes from.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

MAX_PROPOSALS = 3


def latest_report(data_dir: Path) -> str:
    folder = Path(data_dir) / "reports"
    try:
        newest = max(folder.glob("learned-*.md"), key=lambda p: p.name, default=None)
        return newest.read_text(encoding="utf-8")[:6000] if newest else ""
    except OSError:
        return ""


def lessons(data_dir: Path, n: int = 8) -> list:
    """Recent reflexion / evolve lessons from memory_core, newest first."""
    try:
        import memory_core  # pylint: disable=import-outside-toplevel
        items = memory_core.items(Path(data_dir), tier="episodic")
    except Exception:  # noqa: BLE001
        return []
    keep = []
    for item in reversed(items):
        tags = item.get("tags") or []
        tags = tags if isinstance(tags, list) else str(tags).split(",")
        if any(t in ("reflexion", "evolve") for t in tags) or item.get("source") in ("reflexion", "evolve"):
            keep.append(str(item.get("text", ""))[:300])
        if len(keep) >= n:
            break
    return keep


def gather(data_dir: Path, jobs: list | None = None, experience_mod=None, now: float | None = None) -> dict:
    """Every fact the review uses, as plain data (also what the model is shown)."""
    now = time.time() if now is None else now
    facts: dict = {"report": latest_report(data_dir), "lessons": lessons(data_dir)}
    try:
        exp = experience_mod
        if exp is None:
            import experience as exp  # pylint: disable=import-outside-toplevel
        week = [e for e in exp.entries(root=Path(data_dir), last=5000) if now - float(e.get("t", 0) or 0) <= 7 * 86400]
        facts["requests"] = len(week)
        facts["verified"] = sum(1 for e in week if e.get("outcome") == "verified")
        facts["failed_checks"] = sum(1 for e in week if e.get("outcome") == "failed")
        facts["blocked"] = sum(1 for e in week if e.get("outcome") in ("blocked", "error"))
        facts["repaired_calls"] = sum(int(e.get("repaired") or 0) for e in week)
        facts["rejected_calls"] = sum(int(e.get("rejected") or 0) for e in week)
        facts["no_tool_requests"] = sum(1 for e in week if e.get("kind") != "chat" and not e.get("tool_calls"))
    except Exception:  # noqa: BLE001
        pass
    try:
        import job_stats  # pylint: disable=import-outside-toplevel
        js = job_stats.stats(jobs or [], Path(data_dir), days=7, now=now)
        facts["jobs"] = {"overall": js["overall"], "by_kind": js["by_kind"], "by_model": js["by_model"][:5],
                         "reasons": js["reasons"][:5]}
    except Exception:  # noqa: BLE001
        pass
    try:
        import speed_watch  # pylint: disable=import-outside-toplevel
        facts["slowest"] = speed_watch.summary(Path(data_dir), jobs=jobs, window_s=7 * 86400, now=now)["slowest"]
    except Exception:  # noqa: BLE001
        pass
    try:
        import selftest  # pylint: disable=import-outside-toplevel
        facts["selftest"] = selftest.Selftest(Path(data_dir)).status().get("last")
    except Exception:  # noqa: BLE001
        pass
    return facts


def rule_proposals(facts: dict) -> list:
    """Proposals from fixed rules, most valuable first: [{title, why}]."""
    out = []
    jobs = facts.get("jobs") or {}
    overall = jobs.get("overall") or {}
    reasons = jobs.get("reasons") or []
    if overall.get("n", 0) >= 3 and (overall.get("rate") or 0) < 0.8:
        top = reasons[0]["reason"] if reasons else "unknown"
        out.append({"title": "Make background jobs succeed more often: only %d of %d jobs worked this week (%d%%); the "
                             "most common failure was \"%s\" (%d times). Find its cause in the job logs and fix it, "
                             "with a test that reproduces it." % (overall["ok"], overall["n"], int((overall.get("rate") or 0) * 100),
                                                                 top, reasons[0]["n"] if reasons else 0),
                    "why": "job dashboard"})
    for row in jobs.get("by_kind") or []:
        if row.get("n", 0) >= 3 and (row.get("rate") or 0) < 0.5 and row["kind"] not in ("selftest", "other"):
            out.append({"title": "Make %s jobs work: %d of %d failed this week. Look at how a %s job is set up "
                                 "(tools offered, prompt, model) and change what makes it fail." % (
                                     row["kind"], row["n"] - row["ok"], row["n"], row["kind"]),
                        "why": "job dashboard by kind"})
    st = facts.get("selftest") or {}
    if st and st.get("rate") is not None and st["rate"] < 1:
        bad = [r for r in st.get("results") or [] if not r.get("ok")]
        out.append({"title": "Fix the daily self-test: %d of %d tasks failed (%s). The job loop has a regression; "
                             "reproduce it with tests/test_self_systems.py-style fakes and fix it." % (
                                 len(bad), len(st.get("results") or []), "; ".join("%s: %s" % (r["task"], r.get("why", ""))
                                                                                  for r in bad)[:200]),
                    "why": "self-test"})
    if facts.get("repaired_calls", 0) + facts.get("rejected_calls", 0) >= 10:
        out.append({"title": "Fewer broken tool calls: the tool guard repaired %d and rejected %d calls this week. "
                             "Find the tools whose schemas the models get wrong most and make them simpler." % (
                                 facts.get("repaired_calls", 0), facts.get("rejected_calls", 0)),
                    "why": "experience log"})
    if facts.get("requests", 0) >= 5 and facts.get("failed_checks", 0) * 4 >= facts.get("requests", 1):
        out.append({"title": "Better first attempts: %d of %d requests this week had changed files fail their checks. "
                             "Make LOKI check its own change (run the check before DONE) and say what failed." % (
                                 facts["failed_checks"], facts["requests"]),
                    "why": "experience log"})
    slow = facts.get("slowest")
    if slow and slow.get("p50", 0) > 4000:
        out.append({"title": "Speed: '%s' is the slowest step (median %.1f s). Make it faster and measure it with the "
                             "speed watch." % (slow.get("label", slow.get("phase")), slow["p50"] / 1000.0),
                    "why": "speed watch"})
    if facts.get("lessons"):
        out.append({"title": "Use what LOKI learned: a recent lesson says \"%s\". Turn it into a lasting fix (code or a "
                             "rule in the prompt) so the same mistake cannot happen again." % facts["lessons"][0][:220],
                    "why": "reflexion / evolve lessons"})
    return out


REVIEW_PROMPT = """You are LOKI reviewing your own week. Below are measured facts about how you worked.
Propose at most 3 concrete changes to your OWN code or behaviour that would make the most difference
(jobs that succeed, fewer failures, faster steps). Each proposal: one or two sentences, name the fact
it comes from, and say what to change. Reply ONLY with a JSON list of strings.

Facts:
%s
"""


def model_proposals(facts: dict, ask) -> list:
    """Ask a model to write the proposals; [] when the answer is unusable."""
    try:
        text = str(ask(REVIEW_PROMPT % json.dumps(facts, default=str, indent=1)[:9000]) or "")
    except Exception:  # noqa: BLE001
        return []
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except ValueError:
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        line = " ".join(str(item.get("title") if isinstance(item, dict) else item).split())
        if 20 <= len(line) <= 600:
            out.append({"title": line, "why": "LOKI's weekly self-review"})
    return out[:MAX_PROPOSALS]


def _similar(a: str, b: str) -> bool:
    wa = set(re.findall(r"[a-z]{4,}", a.lower()))
    wb = set(re.findall(r"[a-z]{4,}", b.lower()))
    if not wa or not wb:
        return False
    return len(wa & wb) / float(min(len(wa), len(wb))) >= 0.6


def review(evolve_obj, data_dir: Path, jobs: list | None = None, ask=None, now: float | None = None) -> dict:
    """Add up to 3 new 'LOKI's idea' proposals (waiting for the owner's OK). Returns what was added."""
    facts = gather(data_dir, jobs=jobs, now=now)
    proposals = model_proposals(facts, ask) if ask is not None else []
    source = "model" if proposals else "rules"
    if not proposals:
        proposals = rule_proposals(facts)
    existing = [i for i in evolve_obj.ideas() if i.get("source") == "loki"]
    open_count = sum(1 for i in existing if not i.get("done"))
    added = []
    for p in proposals:
        if len(added) >= MAX_PROPOSALS or open_count + len(added) >= 6:
            break                      # never bury the owner in proposals
        if any(_similar(p["title"], i.get("title", "")) for i in existing) or any(_similar(p["title"], a["title"]) for a in added):
            continue
        out = evolve_obj.add_idea("LOKI's idea (%s): %s" % (p["why"], p["title"]), by="loki", kind="review")
        if out.get("ok"):
            added.append(out["idea"])
    return {"ok": True, "added": added, "source": source, "facts": {k: v for k, v in facts.items() if k != "report"}}
