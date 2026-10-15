"""Evals: a Task is a dataset + a solver + a scorer, so "better" becomes a number.

    python tests/test_evals.py

Unit checks on engine/evals.py with a scripted solver (no model, no network), then the
recording path that feeds the routing scorecard (experience.tool_stats).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "tests"), str(REPO / "engine")]

PASS: list = []
FAIL: list = []


def check(name: str, ok: bool, detail: object = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def section(title: str) -> None:
    print("\n" + title)


import evals  # noqa: E402
import experience  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="loki_eval_"))

section("the shape: dataset + solver + scorer")
check("grade() is 1.0 for a pass and 0.0 for a fail",
      evals.grade(True)["score"] == 1.0 and evals.grade(False)["score"] == 0.0)
_one_def = evals.task("x", [evals.sample("a"), evals.sample("b")], evals.answered, tags=("tools",))
check("a task carries its samples, scorer and tags",
      _one_def["name"] == "x" and len(_one_def["samples"]) == 2 and _one_def["tags"] == ("tools",))

section("running: a solver drives each sample, the scorer judges it")
SCRIPT = {}


def scripted(case):
    out = SCRIPT.get(case["id"], {})
    if isinstance(out, Exception):
        raise out
    return out


_demo = evals.task("demo", [evals.sample("ok", target="a.txt", contains="hi"),
                            evals.sample("missing", target="b.txt", contains="hi"),
                            evals.sample("boom", target="c.txt")], evals.wrote_file)
SCRIPT.clear()
SCRIPT.update({"ok": {"files": {"a.txt": "hi there"}}, "missing": {"files": {}},
               "boom": RuntimeError("model fell over")})
_result = evals.run(_demo, scripted)
check("one passes, one fails the scorer, one raises - and the run still finishes",
      _result["passed"] == 1 and _result["total"] == 3 and _result["score"] == 0.333, _result)
check("a raised solver error becomes that sample's reason, not a crash",
      "RuntimeError" in _result["results"][2]["detail"], _result["results"][2])
check("every result carries timing and a short output for the log",
      all(r["ms"] >= 0 and "output" in r for r in _result["results"]), _result["results"][0])
SCRIPT.clear()
SCRIPT.update({"ok": {"files": {"a.txt": "hi there"}}, "missing": {"files": {"b.txt": "wrong"}},
               "boom": {"files": {"c.txt": "hi"}}})
_partial = evals.run(_demo, scripted)
check("wrong file contents fails even though the file exists", _partial["passed"] == 2, _partial)
check("report() reads as plain English", "demo: 2/3" in evals.report({"tasks": {"demo": _partial}}),
      evals.report({"tasks": {"demo": _partial}}))


def angry_scorer(case, out):
    raise ValueError("bad scorer")


_bad = evals.run(evals.task("bad", [evals.sample("x")], angry_scorer), lambda c: {})
check("a broken scorer fails its sample instead of killing the run",
      _bad["total"] == 1 and _bad["passed"] == 0 and "scorer error" in _bad["results"][0]["detail"], _bad)

section("the scorers LOKI ships with")
check("wrote_file needs the named file AND its text",
      evals.wrote_file({"target": "a.txt", "contains": "hi"}, {"files": {"a.txt": "hi"}})["passed"]
      and not evals.wrote_file({"target": "a.txt", "contains": "hi"}, {"files": {"a.txt": "no"}})["passed"])
check("called_tool needs the right tool name",
      evals.called_tool({"tool": "list_files"}, {"tools": ["list_files"]})["passed"]
      and not evals.called_tool({"tool": "list_files"}, {"tools": ["write_file"]})["passed"])
check("called_tool also checks the argument it was given",
      evals.called_tool({"tool": "write_file", "args": {"filename": "eval_out/a.txt"}},
                        {"tools": ["write_file"], "tool_args": {"filename": "eval_out/a.txt"}})["passed"]
      and not evals.called_tool({"tool": "write_file", "args": {"filename": "eval_out/a.txt"}},
                                {"tools": ["write_file"], "tool_args": {"filename": "other.txt"}})["passed"])
check("answered looks for the expected facts, case-insensitively",
      evals.answered({"expect": ["loki"]}, {"answer": "This is LOKI."})["passed"]
      and not evals.answered({"expect": ["banana"]}, {"answer": "This is LOKI."})["passed"])

section("LOKI's own tasks")
check("the registry ships the three tasks LOKI can measure today",
      set(evals.REGISTRY) == {"make-a-file", "call-the-right-tool", "answer-from-the-project"},
      list(evals.REGISTRY))
check("every task has samples and a callable scorer",
      all(t["samples"] and callable(t["scorer"]) for t in evals.REGISTRY.values()))
check("the local trial uses the tool tasks", set(evals.TRIAL_TASKS) <= set(evals.REGISTRY))
check("summary() describes them for the UI",
      all({"name", "samples", "tags", "description"} <= set(row) for row in evals.summary()), evals.summary())

section("recording a run feeds the routing scorecard")
_good = evals.run(evals.REGISTRY["call-the-right-tool"], lambda case: {
    "tools": [case["tool"]], "tool_args": case.get("args") or {}})
evals.record(_good, "local", "test-model", root=TMP)
_after = experience.tool_stats(TMP)
check("an eval run is logged with the model that ran it",
      "local/test-model" in _after["by_model"], list(_after["by_model"]))
check("a perfect eval counts as a request that called a tool",
      _after["by_model"]["local/test-model"]["with_tools"] == 1
      and _after["by_model"]["local/test-model"]["tool_rate"] == 1.0, _after["by_model"])
check("an eval is NOT counted as production file work (it wrote no files)",
      experience.provider_stats(TMP).get("local", {}).get("requests", 0) == 0,
      experience.provider_stats(TMP))
check("a failed eval is recorded as failed",
      evals.record(evals.run(evals.task("bad", [evals.sample("x")], evals.wrote_file), lambda c: {"files": {}}),
                   "local", "test-model", root=TMP)["outcome"] == "failed")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
