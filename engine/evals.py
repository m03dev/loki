"""Evals: measure what LOKI actually does, so "better" is a number.

The shape is borrowed from Inspect (UK AISI): a **Task** is a dataset, a **solver** (how the
model is driven) and a **scorer** (how the answer is judged), kept separate so the same task
can be run under different strategies.

Why LOKI needs this: `experience.py` records what happened in production and
`tools/self_improve.py` promotes a model "only if it beats the current one" -- but nothing
MEASURES better, so improvement is neither comparable nor reversible, which the vision asks
for ("measurable, reversible improvement"). A Task fixes that: the same samples, driven the
same way, graded the same way, so two models, two prompts or two routing policies can be
compared on one number.

This module is pure: a task never calls a model itself. `run(task, solver)` asks the caller to
drive one sample, so tests use a scripted solver and the real trial wires in LOKI's agent loop.

A solver returns a small dict describing what happened:

    {"files": {"notes/hello.txt": "hi"}, "tools": ["write_file"], "answer": "..."}

so scorers stay trivial and testable.
"""
from __future__ import annotations

import time
from typing import Any, Callable


def sample(sid: str, **fields: Any) -> dict:
    """One case for a task. Everything but `id` is task-specific."""
    return {"id": sid, **fields}


def task(name: str, samples: list, scorer: Callable[[dict, Any], dict], *,
         solver: str = "", description: str = "", tags: tuple = ()) -> dict:
    """A dataset + a scorer (+ a named solver strategy the runner should use)."""
    return {"name": name, "samples": list(samples), "scorer": scorer, "solver": solver,
            "description": description, "tags": tuple(tags)}


def grade(passed: bool, detail: str = "") -> dict:
    """One scored sample."""
    return {"passed": bool(passed), "score": 1.0 if passed else 0.0, "detail": str(detail)[:300]}


def _short(value: Any, limit: int = 400) -> str:
    """A compact, log-safe view of whatever the solver returned."""
    try:
        text = value if isinstance(value, str) else repr(value)
    except Exception:  # noqa: BLE001 - a repr must never break an eval
        text = "<unprintable>"
    text = text.replace(chr(10), chr(92) + "n")
    return text if len(text) <= limit else text[:limit] + "..."


def run(one_task: dict, solver: Callable[[dict], Any], *,
        on_progress: Callable[[str], None] | None = None) -> dict:
    """Drive every sample with `solver` and grade it. Never raises on one bad sample."""
    results = []
    total = len(one_task["samples"])
    for index, case in enumerate(one_task["samples"], 1):
        if on_progress:
            on_progress("%s: %d/%d" % (one_task["name"], index, total))
        started = time.monotonic()
        out: Any = None
        failure = ""
        try:
            out = solver(case)
        except Exception as exc:  # noqa: BLE001 - a broken sample is a failed sample
            failure = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        try:
            graded = grade(False, failure) if failure else one_task["scorer"](case, out)
        except Exception as exc:  # noqa: BLE001 - a broken scorer fails the sample, not the run
            graded = grade(False, "scorer error: %s" % str(exc)[:160])
        used = (out or {}).get("tools") if isinstance(out, dict) else None
        results.append({"id": case.get("id", str(index)), **graded, "tools": len(used or []),
                        "ms": int((time.monotonic() - started) * 1000), "output": _short(out)})
    passed = sum(1 for r in results if r["passed"])
    return {"task": one_task["name"], "passed": passed, "total": total,
            "score": round(passed / total, 3) if total else 0.0, "results": results}


def run_all(names: list, registry: dict, solver: Callable[[dict], Any],
            on_progress: Callable[[str], None] | None = None) -> dict:
    """Run several tasks; returns {task: result} plus a combined score."""
    out = {}
    for name in names:
        one = registry.get(name)
        if one:
            out[name] = run(one, solver, on_progress=on_progress)
    graded = [r["score"] for r in out.values()]
    return {"tasks": out, "score": round(sum(graded) / len(graded), 3) if graded else 0.0}


def _files(out: Any) -> dict:
    files = (out or {}).get("files") if isinstance(out, dict) else None
    return files if isinstance(files, dict) else {}


def wrote_file(case: dict, out: Any) -> dict:
    """The named file exists and contains the expected text."""
    files = _files(out)
    target = case.get("target", "")
    if target not in files:
        return grade(False, "no %s (wrote: %s)" % (target, ", ".join(sorted(files)) or "nothing"))
    want = case.get("contains")
    if want is not None and want not in str(files[target]):
        return grade(False, "%s did not contain the expected text" % target)
    return grade(True, target)


def called_tool(case: dict, out: Any) -> dict:
    """The model used the tool the case demands (BFCL-style, name + argument check)."""
    tools = (out or {}).get("tools") if isinstance(out, dict) else None
    tools = tools or []
    want = case.get("tool", "")
    if want not in tools:
        return grade(False, "called %s, not %s" % (", ".join(tools) or "no tool", want))
    sent = (out or {}).get("tool_args") or {}
    for key, value in (case.get("args") or {}).items():
        if str(sent.get(key, "")).find(str(value)) < 0:
            return grade(False, "%s wanted %s=%s, got %r" % (want, key, value, sent.get(key)))
    return grade(True, want)


def answered(case: dict, out: Any) -> dict:
    """A question was answered with the expected fact, in text."""
    answer = str((out or {}).get("answer", "")) if isinstance(out, dict) else str(out or "")
    for needle in case.get("expect") or []:
        if needle.lower() not in answer.lower():
            return grade(False, "answer did not mention %r" % needle)
    return grade(True, "")


def _file_cases() -> list:
    return [
        sample("hello-txt", target="eval_out/hello.txt", contains="hello",
               prompt="Create eval_out/hello.txt containing the word hello."),
        sample("notes-md", target="eval_out/notes.md", contains="# Notes",
               prompt="Create eval_out/notes.md whose first line is # Notes."),
        sample("json", target="eval_out/data.json", contains='"ok"',
               prompt='Create eval_out/data.json with the single key "ok" set to true.'),
    ]


def _tool_cases() -> list:
    return [
        sample("list", tool="list_files", args={}, prompt="List the files in the workspace."),
        sample("read", tool="read_file", args={"path": "README"}, prompt="Read the README file."),
        sample("write", tool="write_file", args={"filename": "eval_out/a.txt"},
               prompt="Create eval_out/a.txt with the text hi."),
    ]


def _answer_cases() -> list:
    return [sample("self", expect=["LOKI"], prompt="In one sentence, what is this project?")]


REGISTRY: dict = {
    "make-a-file": task("make-a-file", _file_cases(), wrote_file, solver="agent",
                        description="A file the model must actually create.", tags=("tools", "local")),
    "call-the-right-tool": task("call-the-right-tool", _tool_cases(), called_tool, solver="agent",
                                description="Picks and calls the correct tool with the right argument.",
                                tags=("tools", "local", "bfcl")),
    "answer-from-the-project": task("answer-from-the-project", _answer_cases(), answered, solver="agent",
                                    description="Reads the project and answers from it.", tags=("context",)),
}

TRIAL_TASKS = ("call-the-right-tool", "make-a-file")


def summary() -> list:
    """What LOKI can measure today (for the UI and the System check)."""
    return [{"name": t["name"], "samples": len(t["samples"]), "tags": list(t["tags"]),
             "description": t["description"]} for t in REGISTRY.values()]


def report(results: dict) -> str:
    """One plain-English line per task, plus a combined score."""
    lines = []
    for name, res in (results.get("tasks") or {}).items():
        lines.append("%s: %d/%d (%s)" % (name, res["passed"], res["total"], res["score"]))
    if len(lines) > 1:
        lines.append("overall: %s" % results.get("score"))
    return "; ".join(lines) or "nothing ran"


def record(result: dict, provider: str, model: str = "", root=None,
           kind: str = "eval", seconds: float = 0.0) -> dict:
    """Log one eval run so the routing scorecard learns from it.

    Records `tool_calls` (so `experience.tool_stats` scores tool calling) but deliberately NO
    `files`, so `provider_stats`, which judges production file-writing work, cannot mistake a
    measured trial for a real job. `verified` only when every sample passed.
    """
    import experience  # pylint: disable=import-outside-toplevel - avoid an import cycle

    calls = sum(int(row.get("tools") or 0) for row in (result.get("results") or []))
    entry = {
        "kind": kind, "goal": "eval: " + str(result.get("task", "")), "provider": provider,
        "model": model, "status": "done",
        "outcome": "verified" if result.get("score") == 1.0 else "failed",
        "tool_calls": calls or (1 if result.get("passed") else 0),
        "files": [], "seconds": seconds,
    }
    return experience.record(entry, root=root)
