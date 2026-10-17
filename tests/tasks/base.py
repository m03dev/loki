"""The task-success benchmark's building blocks (tools/task_bench.py runs them).

A Task is one realistic thing the owner asks LOKI to do in the background: the prompt, the
files the throwaway workspace starts with, what the outcome must be ("done", "blocked" or
"answer"), and checks that look at the REAL result - files on disk, tests that run, pictures
that are pictures, sources that came from a tool, a DONE line that does not lie.

`scripts` are scripted fake models for machines without a model (CI, the cloud): each lane
is a list of steps a small model really produced in the PC's job logs (empty replies,
<think>-only replies, ```json tool calls, wrong tool names, premature DONE, BLOCKED guesses,
huge outputs...). Lane "small" is the model the job starts on; lane "strong" answers after
LOKI escalates to a stronger model; a team task has one lane per role. A step is a dict
(see the helpers below) or a function(messages) -> step, for a model that reacts to what
LOKI told it.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ----------------------------------------------------------------------------- the task


@dataclass
class Task:
    id: str
    kind: str                       # doc | code | research | picture | summary | plan | build | team | assume | blocked
    prompt: str
    expect: str = "done"            # done | blocked | answer
    files: dict = field(default_factory=dict)       # path -> text (or bytes) the workspace starts with
    checks: list = field(default_factory=list)      # [check(ws, result) -> "" (ok) or a reason]
    scripts: dict = field(default_factory=dict)     # scenario -> {lane: [steps]}
    allow_commands: bool = False
    team: bool = False
    web: dict = field(default_factory=dict)         # scripted web: {"results": [...], "pages": {url: text}}
    image: str = "ok"                               # scripted image specialist: ok | fail
    deadline_s: float = 0.0                         # per-task job deadline (0 = the bench default)
    behaviour: str = ""                             # what the "small" script reproduces (for the table)
    needs: tuple = ()                               # real-mode needs: ("web",), ("image",), ...


# ----------------------------------------------------------------------------- scripted steps

def call(name: str, **args) -> dict:
    """A real (native) tool call."""
    return {"calls": [(name, args)]}


def calls(*pairs) -> dict:
    """Several native tool calls in one reply: calls(("read_file", {...}), ("write_file", {...}))."""
    return {"calls": [(n, a) for n, a in pairs]}


def say(text: str) -> dict:
    return {"content": text}


def empty() -> dict:
    return {"content": ""}


def think_only(text: str = "Let me think about how to approach this task step by step...") -> dict:
    """qwen3's thinking ate the answer: only a <think> block comes back."""
    return {"content": "<think>%s</think>" % text}


def json_block(name: str, **args) -> dict:
    """A tool call written as a ```json block instead of being called."""
    return {"content": "I will do that now.\n```json\n%s\n```" % json.dumps({"name": name, "arguments": args})}


def py_text(name: str, **args) -> dict:
    """A tool call written as code: write_file(filename="a", content="b")."""
    return {"content": "%s(%s)" % (name, ", ".join("%s=%s" % (k, json.dumps(v)) for k, v in args.items()))}


def huge(chars: int, then: str = "") -> dict:
    """A huge prose reply (a small model reciting a whole file or its reasoning)."""
    unit = "This is a very long explanation of what I am going to do and why. "
    body = (unit * (chars // len(unit) + 1))[:chars]
    return {"content": body + ("\n\n" + then if then else "")}


def cut(name: str, split: float = 0.5, **args) -> list:
    """A text tool call cut off by the output limit, then its continuation (two steps)."""
    text = json.dumps({"name": name, "arguments": args})
    at = max(12, int(len(text) * split))
    return [{"content": text[:at]}, {"content": text[at:]}]


def slow(step: dict, seconds: float) -> dict:
    return dict(step, sleep=seconds)


def done(text: str) -> dict:
    return {"content": "DONE: " + text}


def blocked(text: str) -> dict:
    return {"content": "BLOCKED: " + text}


def last_user(messages: list) -> str:
    """The newest user (LOKI) message text - what a reacting script reads."""
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            return str(m.get("content") or "")
    return ""


def told(messages: list, *words: str) -> bool:
    """True when LOKI's newest message (or a tool result after it) contains one of `words`."""
    tail = []
    for m in reversed(messages or []):
        if not isinstance(m, dict):
            continue
        tail.append(str(m.get("content") or ""))
        if m.get("role") == "user":
            break
    text = "\n".join(tail).lower()
    return any(w.lower() in text for w in words)


# ----------------------------------------------------------------------------- checks
# A check is check(ws: Path, result: dict) -> "" when it passes, else the reason it failed.
# result: {"status": done|blocked|answer|error|timeout, "final": <the job's final text>, ...}

def _read(ws: Path, rel: str) -> str:
    try:
        return (ws / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def exists(*paths: str) -> Callable:
    def check(ws, result):
        missing = [p for p in paths if not (ws / p).is_file()]
        return ("missing: " + ", ".join(missing)) if missing else ""
    check.__name__ = "exists(%s)" % ", ".join(paths)
    return check


def missing(*paths: str) -> Callable:
    """The job must NOT have made these (a fake summary of a file that is not there...)."""
    def check(ws, result):
        made = [p for p in paths if (ws / p).exists()]
        return ("should not exist: " + ", ".join(made)) if made else ""
    check.__name__ = "missing(%s)" % ", ".join(paths)
    return check


def contains(path: str, *needles: str, any_of: bool = False, case: bool = False) -> Callable:
    def check(ws, result):
        text = _read(ws, path)
        if not text:
            return "%s is missing or empty" % path
        hay = text if case else text.lower()
        found = [n for n in needles if (n if case else n.lower()) in hay]
        if any_of:
            return "" if found else "%s mentions none of %s" % (path, ", ".join(needles))
        lost = [n for n in needles if n not in found]
        return ("%s does not mention %s" % (path, ", ".join(lost))) if lost else ""
    check.__name__ = "contains(%s)" % path
    return check


def unchanged(path: str, original: str) -> Callable:
    def check(ws, result):
        return "" if _read(ws, path) == original else "%s was changed (it must not be)" % path
    check.__name__ = "unchanged(%s)" % path
    return check


def min_words(path: str, n: int) -> Callable:
    def check(ws, result):
        words = len(re.findall(r"\w+", _read(ws, path)))
        return "" if words >= n else "%s has %d words (needs %d)" % (path, words, n)
    check.__name__ = "min_words(%s, %d)" % (path, n)
    return check


def py_compiles(*paths: str) -> Callable:
    def check(ws, result):
        for p in paths:
            try:
                ast.parse(_read(ws, p) or "\0", filename=p)
            except SyntaxError as exc:
                return "%s does not compile: %s (line %s)" % (p, exc.msg, exc.lineno)
        return ""
    check.__name__ = "py_compiles(%s)" % ", ".join(paths)
    return check


# The Python that exists ON THIS MACHINE. macOS (and modern Linux) have no `python`, only
# `python3` - and LOKI's safe_exec refuses a program that is not on PATH ("program not found on
# PATH: python"), so a scripted job that ran "python todo.py add buy milk" never produced its
# evidence, the DONE claim was rightly rejected for missing todos.json, the script ran out of steps
# and the run ended BLOCKED: that is why tests/test_task_success.py failed on the Mac (build-todo,
# team-primes) while passing in the cloud. `runs()` already used sys.executable for its checks;
# `pycmd()` gives the scripted models the same interpreter.
PY_BIN = shutil.which("python") or sys.executable or "python3"


def pycmd(command: str) -> str:
    """A run_command string with a Python the machine actually has (see PY_BIN)."""
    return re.sub(r"(?<![\w./-])python(?![\w./-])", PY_BIN, str(command))


def runs(argv: list, expect_in: str = "", timeout: float = 60.0) -> Callable:
    """Run a command in the workspace with THIS Python (argv[0] == "python"): exit 0 and,
    optionally, expect_in in the output."""
    def check(ws, result):
        cmd = [sys.executable if a == "python" else a for a in argv]
        env = {k: v for k, v in os.environ.items() if not k.startswith("LOKI_")}
        try:
            proc = subprocess.run(cmd, cwd=str(ws), capture_output=True, text=True, timeout=timeout, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "%s: %s" % (" ".join(argv), exc)
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            return "%s exited %d: %s" % (" ".join(argv), proc.returncode, out.strip()[-300:])
        if expect_in and expect_in.lower() not in out.lower():
            return "%s output lacks %r: %s" % (" ".join(argv), expect_in, out.strip()[-200:])
        return ""
    check.__name__ = "runs(%s)" % " ".join(argv)
    return check


def valid_json(path: str, **expected) -> Callable:
    def check(ws, result):
        try:
            data = json.loads(_read(ws, path))
        except ValueError as exc:
            return "%s is not valid JSON: %s" % (path, exc)
        for k, v in expected.items():
            if not isinstance(data, dict) or data.get(k) != v:
                return "%s: %s should be %r" % (path, k, v)
        return ""
    check.__name__ = "valid_json(%s)" % path
    return check


MAGIC = {".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
         ".webp": (b"RIFF",), ".gif": (b"GIF8",)}


def real_picture(folder: str = "") -> Callable:
    """At least one real picture (magic bytes) somewhere in the workspace (or `folder`)."""
    def check(ws, result):
        base = ws / folder if folder else ws
        pics = [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in MAGIC and ".loki" not in p.parts]
        good = [p for p in pics if p.read_bytes()[:4].startswith(MAGIC[p.suffix.lower()])]
        return "" if good else ("no real picture was made" + (" (%d fake)" % len(pics) if pics else ""))
    check.__name__ = "real_picture(%s)" % folder
    return check


def no_fake_media(ws: Path, result: dict) -> str:
    """Every .png/.jpg/... in the workspace really is one (a description written into a .png fails)."""
    for p in ws.rglob("*"):
        if p.is_file() and p.suffix.lower() in MAGIC and ".loki" not in p.parts:
            if not p.read_bytes()[:4].startswith(MAGIC[p.suffix.lower()]):
                return "fake media: %s is not a real %s" % (p.relative_to(ws).as_posix(), p.suffix)
    return ""


_PATHISH = re.compile(r"(?<![\w@/:.-])((?:[\w-]+/)*[\w-]+\.(?:md|txt|py|json|html|css|js|csv|png|jpg|jpeg|toml|yaml|yml))\b")


def honest_final_line(ws: Path, result: dict) -> str:
    """The DONE line does not claim a file that is not there."""
    line = result.get("done_line") or ""
    if not line:
        return ""
    text = re.sub(r"\b\w+://\S+", " ", line)
    for name in _PATHISH.findall(text):
        name = name.strip("./")
        if not (ws / name).exists() and not any(p.name == Path(name).name for p in ws.rglob(Path(name).name)):
            return "the DONE line names %s, which does not exist" % name
    return ""


def final_mentions(*words: str, any_of: bool = True) -> Callable:
    def check(ws, result):
        text = (result.get("final") or "").lower()
        found = [w for w in words if w.lower() in text]
        if any_of:
            return "" if found else "the final answer mentions none of: %s" % ", ".join(words)
        lost = [w for w in words if w not in found]
        return ("the final answer does not mention %s" % ", ".join(lost)) if lost else ""
    check.__name__ = "final_mentions(%s)" % ", ".join(words)
    return check


def sources(path: str, n: int = 2) -> Callable:
    """At least n distinct http(s) links; in a scripted run every link must have come from a
    tool result (no invented sources)."""
    def check(ws, result):
        text = _read(ws, path) if path else (result.get("final") or "")
        urls = sorted(set(u.rstrip(").,]") for u in re.findall(r"https?://[^\s)>\]]+", text)))
        if len(urls) < n:
            return "%s has %d source link(s) (needs %d)" % (path or "the answer", len(urls), n)
        known = result.get("known_urls")
        if known is not None:
            invented = [u for u in urls if u not in known]
            if invented:
                return "invented source(s) not returned by any tool: %s" % ", ".join(invented[:3])
        return ""
    check.__name__ = "sources(%s, %d)" % (path, n)
    return check


def team_verified(ws: Path, result: dict) -> str:
    """The team says verified AND every agent really finished (a halted tester is not a PASS)."""
    team = result.get("team") or {}
    verdict = str(team.get("verdict") or "")
    if not verdict.startswith("verified"):
        return "team verdict: %s" % (verdict or "none")
    unfinished = [m["role"] for m in team.get("members") or [] if m.get("status") not in ("done", "blocked")]
    if unfinished:
        return "team said verified, but %s ended without DONE/BLOCKED" % ", ".join(unfinished)
    return ""


def bounded_context(limit: int) -> Callable:
    """No request sent to the model was longer than `limit` characters (a small model's context)."""
    def check(ws, result):
        size = int(result.get("max_prompt_chars") or 0)
        return "" if size <= limit else "a request to the model held %d characters (limit %d)" % (size, limit)
    check.__name__ = "bounded_context(%d)" % limit
    return check


# Checks every task gets, after its own.
ALWAYS = [no_fake_media, honest_final_line]
