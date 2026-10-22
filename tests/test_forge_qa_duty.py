"""LOKI tests Forge (engine/forge_qa_duty.py + the autopilot's qa duty): the sweep runs in the background when idle,
its report is triaged against the last runs, new problems become Lab ideas (timing problems only when they repeat),
fixed ones are counted, and nothing is proposed twice. No browser here: the sweep is a fake process writing a report.

    python tests/test_forge_qa_duty.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]

import autopilot  # noqa: E402
import forge_qa_duty  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


class FakeEvolve:
    def __init__(self):
        self.items = []

    def ideas(self):
        return list(self.items)

    def add_idea(self, text, by="owner", approved=None, kind=""):
        item = {"id": "I%d" % (len(self.items) + 1), "title": text, "done": False, "source": by, "approved": bool(approved), "kind": kind}
        self.items.append(item)
        return {"ok": True, "idea": item}


class FakeProc:
    def __init__(self, data_dir, report):
        self.done = False
        out = Path(data_dir) / "qa" / "forge_qa.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report), encoding="utf-8")

    def poll(self):
        return 0 if self.done else None


class Idle:
    jobs = types.SimpleNamespace(store=types.SimpleNamespace(all=lambda: []))
    last_request_at = 0.0

    @staticmethod
    def try_busy():
        return ["lock"]

    @staticmethod
    def release_busy(held):
        pass


REPORT1 = {"menu_rows_checked": 300, "buttons_checked": 600, "commands_total": 210,
           "menus": [{"where": "Help > Hotkey Editor", "problem": "cannot be clicked: clipped by the window"}],
           "buttons": [{"where": "model: Freeze", "problem": "cannot be clicked: covered by fmy-pib"}],
           "hotbox": [], "commands": [{"id": "uvPlanar", "label": "Planar UVs", "problem": "slow: 4.5 s"},
                                      {"id": "bevel", "label": "Bevel", "problem": "page error: TypeError: x is undefined"}]}

for k in ("LOKI_FORGE_QA", "LOKI_FORGE_QA_IDEAS", "LOKI_SELFTEST", "LOKI_TASK_BENCH"):
    os.environ.pop(k, None)
os.environ["LOKI_SELFTEST"] = os.environ["LOKI_TASK_BENCH"] = "0"
os.environ["LOKI_AUTOPILOT"] = "on"
os.environ["LOKI_AUTOPILOT_INBOX"] = "off"
os.environ["LOKI_AUTOPILOT_HEALTH_S"] = "999999999"

tmp = Path(tempfile.mkdtemp(prefix="loki-qa-"))
print("\ntriage and proposals")
ev = FakeEvolve()
tri = forge_qa_duty.triage(REPORT1, tmp, now=1.0)
check("every problem in the report is seen", len(tri["problems"]) == 4, tri["problems"])
check("a timing problem is not ready on its first run (a busy machine is not a bug)",
      sorted(p["where"] for p in tri["ready"]) == ["Bevel", "Help > Hotkey Editor", "model: Freeze"], tri["ready"])
added = forge_qa_duty.propose(ev, tri, tmp, env={})
check("at most 3 ideas, tagged qa, approved at once (LOKI_FORGE_QA_IDEAS=auto)",
      len(added) == 3 and all(i["kind"] == "qa" and i["approved"] for i in added), added)
check("each idea says how to reproduce it", all("python tools/forge_qa.py --only" in i["title"] for i in added), added[0]["title"])

report2 = dict(REPORT1, menus=[], buttons=[])          # two fixed, the slow one again, the page error still there
tri2 = forge_qa_duty.triage(report2, tmp, now=2.0)
check("fixed problems are counted", len(tri2["fixed"]) == 2, tri2["fixed"])
added2 = forge_qa_duty.propose(ev, tri2, tmp, env={})
check("a repeating timing problem is proposed the second time; nothing is proposed twice",
      [i["title"].split(" - ")[0] for i in added2] == ["LOKI's idea (Forge QA): fix Planar UVs"], [i["title"] for i in added2])
ev_ask = FakeEvolve()
tmp2 = Path(tempfile.mkdtemp(prefix="loki-qa2-"))
added3 = forge_qa_duty.propose(ev_ask, forge_qa_duty.triage(REPORT1, tmp2), tmp2, env={"LOKI_FORGE_QA_IDEAS": "ask"})
check("LOKI_FORGE_QA_IDEAS=ask: the ideas wait for the owner's OK", added3 and not any(i["approved"] for i in added3))
check("LOKI_FORGE_QA=off switches it off; on switches it on", not forge_qa_duty.enabled({"LOKI_FORGE_QA": "off"}) and forge_qa_duty.enabled({"LOKI_FORGE_QA": "on"}))

print("\nthe autopilot's qa duty")
tmp3 = Path(tempfile.mkdtemp(prefix="loki-qa3-"))
procs = []
ev3 = FakeEvolve()
clock = [10_000_000.0]
ap = autopilot.Autopilot(state=Idle(), data_dir=tmp3, repo=REPO, clock=lambda: clock[0], evolve=ev3,
                         qa_start=lambda: procs.append(FakeProc(tmp3, REPORT1)) or procs[-1])
ran = []
for _ in range(6):                       # one duty per pass: the qa duty comes up among the others
    ran += ap.tick()
    if procs:
        break
check("when idle, the qa duty starts the sweep in the background", procs and any(d == "qa" for d, _ in ran), ran)
check("while it runs LOKI is not idle (nothing else starts)", ap.idle()[0] is False and "Forge QA" in ap.idle()[1], ap.idle())
procs[-1].done = True
ap.tick()
line = [e["text"] for e in ap.data["log"] if e["duty"] == "qa"][-1]
check("when it is done it is triaged on the next pass: problems counted, ideas proposed in the Lab",
      "Forge QA: 4 problem(s)" in line and "Settings > Lab" in line and len(ev3.items) == 3, line)
check("the full report stays in harness_data/qa", (tmp3 / "qa" / "forge_qa.json").is_file() and (tmp3 / "qa" / "known.json").is_file())

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + "; ".join(FAIL))
sys.exit(1 if FAIL else 0)
