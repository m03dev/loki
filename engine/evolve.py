"""Evolve - LOKI grows its own "OpenHuman" inside itself, and keeps learning.

The owner wants LOKI to build its own personal-agent core (the things OpenHuman does - memory
you can see, skills it learns, channels, voice, subagents) inside LOKI's own interface, and to
change and learn by itself. This module is that loop:

  * The roadmap is docs/EVOLVE.md in the repo (the same on every machine): one line per change
    LOKI should make to itself, `- [ ] E<n> title - what and why`. LOKI ticks a line itself
    (`- [x]`) in the commit that ships it, so a finished item is finished everywhere.
  * The owner's own ideas (Settings > Lab, "Add an idea") are kept on this machine
    (harness_data/evolve_ideas.json) and go FIRST.
  * When LOKI is idle the autopilot's `evolve` duty takes the next item and hands it to
    improve_loki: a background LOKI agent changes LOKI's code in its own git worktree, runs
    every test suite and ships it only if they all pass (tools/ship.py), then every machine
    updates. One change at a time; an item that did not ship is tried again after 3 days.
  * Learning: every attempt (shipped or not) is recorded with its outcome; the agent's prompt
    carries the last outcomes, so it builds on what worked and avoids what failed. The weekly
    "what LOKI learned" report (autopilot) feeds the same file.

LOKI_EVOLVE: auto (default: on only on Windows - the PC is on 24/7; the 16 GB Mac is not asked
to build itself), on, off.  LOKI_EVOLVE_S: how often it may start one (default 4 h).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROADMAP = "docs/EVOLVE.md"
RETRY_S = 3 * 86400
_ITEM = re.compile(r"^\s*-\s*\[( |x|X)\]\s*(E\d+)\s+(.+?)\s*$")


def enabled(env: dict | None = None, platform: str = "") -> bool:
    value = str((env if env is not None else os.environ).get("LOKI_EVOLVE", "auto")).strip().lower()
    if value in ("on", "1", "true", "yes"):
        return True
    if value in ("off", "0", "false", "no"):
        return False
    return (platform or sys.platform) == "win32"


def roadmap(repo: Path) -> list:
    """[{id, title, done}] from docs/EVOLVE.md, in order."""
    try:
        lines = (Path(repo) / ROADMAP).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        m = _ITEM.match(line)
        if m:
            out.append({"id": m.group(2), "title": m.group(3), "done": m.group(1).lower() == "x", "source": "roadmap"})
    return out


class Evolve:
    def __init__(self, repo: Path, data_dir: Path, clock=time.time) -> None:
        self.repo = Path(repo)
        self.path = Path(data_dir) / "evolve.json"
        self.ideas_path = Path(data_dir) / "evolve_ideas.json"
        self.clock = clock

    # ------------------------------------------------------------ state
    def _read(self, path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _write(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def state(self) -> dict:
        data = self._read(self.path, {})
        data.setdefault("attempts", [])
        return data

    def ideas(self) -> list:
        return self._read(self.ideas_path, [])

    def add_idea(self, text: str, by: str = "owner", approved: bool | None = None, kind: str = "") -> dict:
        """The owner's ideas are approved by being added; LOKI's own (by="loki") wait for approve()
        unless the caller says otherwise (approved=True: the speed watch's measured speed-ups).
        kind tags where a LOKI idea came from ("review", "speed"), for the Lab and for de-duplication."""
        text = " ".join(str(text or "").split())[:600]
        if len(text) < 8:
            return {"ok": False, "error": "say a little more about the idea"}
        ideas = self.ideas()
        item = {"id": "I%d" % (len(ideas) + 1), "title": text, "done": False, "source": by,
                "approved": (by == "owner") if approved is None else bool(approved), "t": self.clock()}
        if kind:
            item["kind"] = str(kind)[:20]
        ideas.append(item)
        self._write(self.ideas_path, ideas)
        return {"ok": True, "idea": item}

    def approve(self, item_id: str, yes: bool = True) -> dict:
        ideas = self.ideas()
        for idea in ideas:
            if idea["id"] == item_id:
                if yes:
                    idea["approved"] = True
                else:
                    idea["done"] = True
                    idea["declined"] = True
                self._write(self.ideas_path, ideas)
                return {"ok": True, "idea": idea}
        return {"ok": False, "error": "no idea %s" % item_id}

    def record(self, item_id: str, outcome: str, detail: str = "", job: str = "") -> None:
        data = self.state()
        data["attempts"] = (data["attempts"] + [{"id": item_id, "t": self.clock(), "outcome": outcome,
                                                 "detail": str(detail)[:400], "job": job}])[-80:]
        self._write(self.path, data)
        if outcome == "shipped":
            ideas = self.ideas()
            for idea in ideas:
                if idea["id"] == item_id:
                    idea["done"] = True
            self._write(self.ideas_path, ideas)

    # ------------------------------------------------------------ what next
    def items(self) -> list:
        """Owner ideas first, then the roadmap; each with its last attempt."""
        attempts = self.state()["attempts"]
        last = {}
        for a in attempts:
            last[a["id"]] = a
        out = []
        for item in self.ideas() + roadmap(self.repo):
            row = dict(item)
            row["last"] = last.get(item["id"])
            out.append(row)
        return out

    def next_item(self) -> dict | None:
        now = self.clock()
        for item in self.items():
            if item["done"] or item.get("approved") is False:
                continue
            last = item.get("last")
            if last and last["outcome"] == "shipped":
                # It shipped; this checkout's roadmap is ticked only after the next update, so
                # do not build the same step again in the meantime.
                continue
            if last and last["outcome"] in ("started", "failed") and now - last["t"] < RETRY_S:
                continue
            return item
        return None

    def lessons(self, n: int = 6) -> str:
        """The last outcomes, in plain words, for the agent's prompt (what worked, what did not)."""
        rows = [a for a in self.state()["attempts"] if a["outcome"] != "started"][-n:]
        if not rows:
            return "No earlier attempts yet."
        return "\n".join("- %s: %s%s" % (a["id"], a["outcome"], (" - " + a["detail"]) if a.get("detail") else "") for a in rows)

    def task_for(self, item: dict) -> str:
        tick = ("tick its line in docs/EVOLVE.md (`- [ ] %s` -> `- [x] %s`) in the same change" % (item["id"], item["id"])
                if item["source"] == "roadmap" else "say in the commit message that it does owner idea %s" % item["id"])
        return ("Grow LOKI's own personal-agent core (its own 'OpenHuman', inside LOKI's own window) by one step: "
                "%s %s\n\nRules: keep everything that exists working - never remove a feature to make room; keep it "
                "light (no new heavy dependency without need; nothing slows the window); both macOS and Windows; add a "
                "check to the tests for what you build; %s; ship with ship_loki only when every suite passes.\n\n"
                "What happened in earlier attempts (learn from it):\n%s"
                % (item["id"], item["title"], tick, self.lessons()))

    # ------------------------------------------------------------ the duty
    def step(self, improve) -> str:
        """Start the next item with improve(task) -> reply. Returns what happened."""
        if self.busy():
            return ""                      # one change to itself at a time
        item = self.next_item()
        if item is None:
            return ""
        reply = str(improve(self.task_for(item)) or "")
        ok = reply.startswith("started")
        m = re.search(r"started job (\S+?):?\s", reply + " ")
        self.record(item["id"], "started" if ok else "failed", reply[:300], job=m.group(1).rstrip(":") if m else "")
        return ("Evolving %s: %s" % (item["id"], item["title"][:120])) if ok else ("Could not start %s: %s" % (item["id"], reply[:200]))

    def busy(self) -> bool:
        """An attempt is still running (started and not settled)."""
        last = {}
        for a in self.state()["attempts"]:
            last[a["id"]] = a
        return any(a["outcome"] == "started" for a in last.values())

    def settle(self, job_status, shipped=None, detail=None) -> list:
        """Close started attempts whose job finished: job_status(job_id) -> status or None.

        shipped(job_id) -> True/False/None says whether the job REALLY pushed (ship_loki leaves a
        marker); a job that only ended "done" - the model said DONE without shipping, or ship_loki
        refused - is a failure with its reason, not a success. detail(job_id) -> the job's last
        words (its DONE/BLOCKED line or error), kept as the lesson for the next attempt.
        Without `shipped` (older callers), a job that ended "done" counts as shipped."""
        closed = []
        last = {}
        for a in self.state()["attempts"]:
            last[a["id"]] = a
        for item_id, a in last.items():
            if a["outcome"] != "started":
                continue
            job = a.get("job", "")
            st = job_status(job) if job else None
            why = ""
            if detail is not None and job:
                try:
                    why = " ".join(str(detail(job) or "").split())[:300]
                except Exception:  # noqa: BLE001
                    why = ""
            if st in ("done", "finished", "succeeded"):
                really = shipped(job) if (shipped is not None and job) else True
                if really is False:
                    self.record(item_id, "failed", "the job finished without shipping" + (": " + why if why else ""), job=job)
                    self._lesson(item_id, "failed", "finished without shipping. " + why)
                    closed.append((item_id, "failed"))
                    continue
                self.record(item_id, "shipped", "shipped" + (": " + why if why else ""), job=job)
                self._lesson(item_id, "shipped", why)
                closed.append((item_id, "shipped"))
            elif st in ("failed", "error", "cancelled", "canceled", "stopped") or (
                    st is None and self.clock() - a["t"] > 6 * 3600):
                self.record(item_id, "failed", "the job ended as %s" % (st or "lost") + (": " + why if why else ""), job=job)
                self._lesson(item_id, "failed", "the job ended as %s. %s" % (st or "lost", why))
                closed.append((item_id, "failed"))
        return closed

    def _lesson(self, item_id: str, outcome: str, why: str) -> None:
        """Keep the outcome in LOKI's memory too (memory_core, episodic), so the next improve job
        recalls it in its memory pack - not only the evolve prompt's last-outcomes list."""
        try:
            import memory_core  # pylint: disable=import-outside-toplevel
            title = next((i["title"] for i in self.items() if i["id"] == item_id), item_id)
            memory_core.learn("Self-improvement step %s (%s) %s. %s" % (item_id, title[:140], outcome, why[:300]),
                              tier="episodic", tags="evolve,self-improvement,%s" % item_id.lower(),
                              root=self.path.parent, source="evolve")
        except Exception:  # noqa: BLE001 - learning must never break the duty
            pass

    def status(self) -> dict:
        return {"ok": True, "enabled": enabled(), "items": self.items(), "lessons": self.lessons(),
                "next": (self.next_item() or {}).get("id", "")}
