"""Receipts: a report is checked against what LOKI's tools really printed (owner 2026-10-28: "fix whats going on
with loki" - the PC's qa reports were made up and LOKI counted them as done). Uses the PC's real fake reports
(tests/data/receipts/fake_*.md, copied from C:/Users/macul/LOKI Projects/Home/qa on 2026-10-28). Under a minute.

    python tests/test_receipts.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-receipts-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
PASS: list = []
FAIL: list = []
T0 = time.time()
DATA = REPO / "tests" / "data" / "receipts"


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import receipts  # noqa: E402
import proof  # noqa: E402

# what the PC's tools really printed for the OpenCode proof (the shim suite really ran)
REAL_SUITE = "13 of 13 checks passed\n  PASS test_opencode_cmd_resolves_to_exe\n  PASS test_js_shim_keeps_cmd\n"
os.environ["LOKI_JOB_ID"] = "job1"
receipts.record("bash", r"harness_data\.venv\Scripts\python.exe tests\test_win_shim.py", REAL_SUITE, 0)
receipts.record("bash", "python -c print(find_opencode())",
                r"C:\Users\macul\AppData\Roaming\npm\node_modules\opencode-ai\bin\opencode.exe", 0)
os.environ.pop("LOKI_JOB_ID")
seen = receipts.corpus(["job1"], TMP / "data")
check("a receipt keeps the whole output of a tool run", "test_js_shim_keeps_cmd" in seen)

p = receipts.check_report(DATA / "fake_opencode_exe.md", seen)
check("the PC's qa/opencode-exe.md fails: outputs no tool printed (its own fake job logs)",
      any("never printed" in x for x in p), p)
check("... and it says it created LOKI's own files (python.exe, engine/opencode_engine.py, job logs) in the project",
      any("fake LOKI" in x for x in p), p)
p = receipts.check_report(DATA / "fake_agent_system.md", seen)
check("the PC's qa/agent-system.md fails: the template {{status_data}}", any("placeholder" in x for x in p), p)
p = receipts.check_report(DATA / "fake_for_you.md", seen)
check("the PC's qa/for-you.md fails: <concept-prompt> in its answers", any("placeholder" in x for x in p), p)

real = TMP / "ws" / "qa" / "real.md"
real.parent.mkdir(parents=True)
real.write_text("# Proof\n\nCommand:\n\n```\nharness_data\\.venv\\Scripts\\python.exe tests\\test_win_shim.py\n```\n\n"
                "Output:\n\n```\n" + REAL_SUITE + "```\n\nOutput of find_opencode():\n\n```\n"
                "C:\\Users\\macul\\AppData\\Roaming\\npm\\node_modules\\opencode-ai\\bin\\opencode.exe\n"
                "C:\\Users\\macul\\AppData\\Roaming\\npm\\node_modules\\opencode-ai\\bin\\opencode.exe\n```\n",
                encoding="utf-8")
p = receipts.check_report(real, seen)
check("a report that pastes what the tools really printed passes", p == [], p)
_c = TMP / "ws" / "qa" / "c.md"
_c.write_text("Command:\n\n```\ncurl -H \"Authorization: Bearer <engine token>\" http://127.0.0.1:8767/review\n```\n",
              encoding="utf-8")
check("a command line naming <engine token> is fine (only outputs count)", receipts.check_report(_c, seen) == [],
      receipts.check_report(_c, seen))
check("no receipts at all (a harness that hides its output): pasted outputs are not called made up",
      not any("never printed" in x for x in receipts.check_report(real, "")))

res = proof.check("[loki] [windows] DO FIRST - prove it. qa/real.md: both outputs word for word.", ["qa/real.md"],
                  "DONE", TMP / "ws", seen)
check("the proof check passes a real report", res["ok"], res)
fake = TMP / "ws" / "qa" / "opencode-exe.md"
fake.write_text((DATA / "fake_opencode_exe.md").read_text(encoding="utf-8"), encoding="utf-8")
res = proof.check("[loki] [windows] DO FIRST - prove OpenCode starts. qa/opencode-exe.md: both outputs word for word.",
                  ["qa/opencode-exe.md"], "DONE", TMP / "ws", seen)
check("the proof check fails the PC's fake report (it was counted as done)", not res["ok"]
      and any("opencode-exe.md" in x for x in res["problems"]), res)
import proof_runner  # noqa: E402
_tasks = (REPO / "LOKI_TASKS.md").read_text(encoding="utf-8")
_oc = next(ln for ln in _tasks.splitlines() if "prove OpenCode starts from its real .exe" in ln)
_cmds = proof_runner.commands(_oc)
check("the runner takes a request's own read-only checks (the OpenCode proof: the shim suite and find_opencode)",
      len(_cmds) == 2 and "test_win_shim.py" in _cmds[0] and "find_opencode" in _cmds[1], _cmds)
_mx = next(ln for ln in _tasks.splitlines() if "Mac -> PC work hand-off" in ln)
check("... never ship.py, git, installs or POSTs",
      not any(k in c for c in proof_runner.commands(_mx) + proof_runner.commands(
          "`curl -s -X POST -H \"Authorization: Bearer <engine token>\" http://127.0.0.1:<port>/agentsys/upstream/check -d \"{}\"` "
          "`pip install manga` `harness_data\\.venv\\Scripts\\python.exe tools\\ship.py -m x`") for k in ("ship.py", "POST", "pip")),
      proof_runner.commands(_mx))
check("... and a GET to this LOKI with the engine token",
      proof_runner.commands("`curl -s -H \"Authorization: Bearer <engine token>\" http://127.0.0.1:<port>/review`") != [])


class _Done:
    def __init__(self, out): self.stdout, self.stderr, self.returncode = out, "", 0


_ran = []
_note = proof_runner.run(_oc, "abc123", TMP / "data", TMP / "ws2",
                         runner=lambda argv, **kw: (_ran.append((argv, kw.get("cwd"))), _Done(REAL_SUITE))[1])
_loki_ran = TMP / "ws2" / "qa" / "opencode-exe.loki-ran.md"
check("LOKI runs them in its OWN folder (never the project folder) and writes qa/<name>.loki-ran.md",
      _ran and all(cwd == str(proof_runner.ROOT) for _, cwd in _ran) and _loki_ran.is_file(), _ran)
check("... the team is told the outputs are there and not to rebuild LOKI", "do NOT write any engine/" in _note
      and "opencode-exe.loki-ran.md" in _note, _note)
_pre = receipts.corpus(["pre-abc123"], TMP / "data")
_copy = TMP / "ws2" / "qa" / "opencode-exe.md"
_copy.write_text("Output:\n\n```\n" + REAL_SUITE + "```\n", encoding="utf-8")
check("a report that copies LOKI's own run passes the receipts check", receipts.check_report(_copy, _pre) == [],
      receipts.check_report(_copy, _pre))
check("LOKI's own .loki-ran.md passes too", receipts.check_report(_loki_ran, _pre) == [], receipts.check_report(_loki_ran, _pre))
import live_guard  # noqa: E402
_home = Path("C:/Users/macul/LOKI Projects/Home")
_rules = live_guard.edit_rules(str(_home), root=Path("D:/loki"))
check("agents may not write engine/, harness_data/ or tests/ into the Home library (the PC's fake LOKI)",
      isinstance(_rules, dict) and any(k.endswith("engine/*") and v == "deny" for k, v in _rules.items())
      and any(k.endswith("harness_data/*") and v == "deny" for k, v in _rules.items()), _rules)
_proj = live_guard.edit_rules("C:/Users/macul/LOKI Projects/my-game", root=Path("D:/loki"))
check("... a real code project keeps its own engine/ and tests/", not any(k.endswith("engine/*") and v == "deny"
                                                                        and "my-game" in k for k, v in _proj.items()))
check("this suite stays under 60 s", time.time() - T0 < 60, time.time() - T0)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
