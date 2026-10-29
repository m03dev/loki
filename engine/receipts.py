"""Receipts: what LOKI's tools REALLY printed, so a report can be checked against it (owner 2026-10-28: "fix whats
going on with loki" - the PC's qa reports were made up).

Seen on the PC (2026-10-28): qa/opencode-exe.md "proved" the Windows fix against job logs the agent had written itself
(01234567.log, 89abcdef.log) and listed a fake python.exe and engine/opencode_engine.py it had "created" in the
project folder; qa/for-you.md quoted port 3003 (LOKI runs on 8767) and `<concept-prompt>`; qa/agent-system.md was the
template `{{status_data}}`. engine/proof.py passed all three: they were text files over 120 characters. Research
("Tool Receipts, Not Zero-Knowledge Proofs", arXiv 2603.10060; mini-swe-agent's "the trajectory is the proof"): the
harness records every tool run, and a claim is checked against those records, never against the agent's own words.

  record(tool, command, output, exit_code)   called by every harness (OpenCode, LOKI's local agent, DeepSeek Harness)
                                              with the FULL output; one line in <data>/receipts/<job or chat>.jsonl
  corpus(ids)                                 everything those jobs' tools printed (normalised), for checking
  check_report(path, corpus)                  problems with a report: placeholders left in, outputs that no tool ever
                                              printed, files it says it created inside a fake copy of LOKI

Standard library only. Never raises into the caller.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

MAX_OUT = 64_000   # per tool run; enough for any test suite's output
_PLACEHOLDER = re.compile(r"\{\{\s*[\w.]+\s*\}\}|<(?:concept-prompt|engine token|port|output|paste[^>]*|result|"
                          r"command output|your [^>]{1,30}|insert [^>]{1,30}|todo)>", re.I)
# LOKI's own folders: an agent "creating" these in a project folder is building a fake LOKI to test against
_FAKE_LOKI = re.compile(r"(?:^|[\s`'\"(/\\-])((?:harness_data[/\\]\.venv[/\\]\S+|harness_data[/\\]tests[/\\]\S+|"
                        r"harness_data[/\\]jobs[/\\]\S+\.log|engine[/\\][\w]+\.py|tests[/\\]test_\w+\.py))", re.I)
_CREATED_HEAD = re.compile(r"^\s*#*\s*(files? (created|made|written)|created files?|i (created|made|wrote))\b", re.I)


def _dir() -> Path:
    base = os.environ.get("LOKI_DATA") or os.environ.get("LOKI_DATA_DIR") or ""
    if base:
        return Path(base) / "receipts"
    return Path(__file__).resolve().parent.parent / "harness_data" / "receipts"


def _key() -> str:
    job = os.environ.get("LOKI_JOB_ID", "").strip()
    return re.sub(r"[^\w-]", "", job)[:40] or "chat"


def record(tool: str, command: str, output: str, exit_code=None, key: str = "") -> None:
    """One tool run, as it really happened. Called with the whole output (not the 400-character view)."""
    try:
        out = str(output or "")
        d = _dir()
        d.mkdir(parents=True, exist_ok=True)
        line = {"t": round(time.time(), 2), "tool": str(tool or "")[:60], "command": str(command or "")[:2000],
                "exit": exit_code, "sha": hashlib.sha256(out.encode("utf-8", "replace")).hexdigest()[:16],
                "output": out[:MAX_OUT]}
        with (d / ("%s.jsonl" % (re.sub(r"[^\w-]", "", key)[:40] or _key()))).open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - a receipt never breaks the work
        pass


def _norm(text: str) -> str:
    t = str(text or "").replace("\\", "/").replace("\r", "")
    return re.sub(r"[ \t]+", " ", t).strip().lower()


def corpus(ids, data_dir=None) -> str:
    """Everything the tools of these jobs printed (and their logs), normalised. "" when nothing was recorded."""
    parts = []
    rd = Path(data_dir) / "receipts" if data_dir else _dir()
    for jid in ids or []:
        jid = re.sub(r"[^\w-]", "", str(jid or ""))[:40]
        if not jid:
            continue
        p = rd / ("%s.jsonl" % jid)
        try:
            for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                parts.append(str(rec.get("command") or ""))
                parts.append(str(rec.get("output") or ""))
        except OSError:
            pass
        if data_dir:   # the job's own log (what LOKI saw, shortened) counts as well
            try:
                parts.append((Path(data_dir) / "jobs" / ("%s.log" % jid)).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    return _norm("\n".join(parts))


def _blocks(text: str) -> list:
    """The fenced blocks of a report: [(heading-ish line before it, body)]."""
    out = []
    for m in re.finditer(r"(?:^|\n)([^\n]*)\n+```[^\n]*\n(.*?)\n```", text, re.S):
        out.append((m.group(1), m.group(2)))
    return out


def _distinct_lines(body: str) -> list:
    lines = []
    for ln in body.splitlines():
        s = ln.strip()
        if len(s) < 14 or s.startswith(("$ ", "> ", "#")) or re.fullmatch(r"[-=*_ .]+", s):
            continue
        lines.append(_norm(s))
    return lines


def check_report(path, corpus_text: str, loki_repo=None) -> list:
    """What is wrong with a written report. [] = nothing found. corpus_text = corpus(...) of the team's jobs.

    - a placeholder left in ({{status_data}}, <concept-prompt>, <engine token>)
    - a pasted output that no tool of this team ever printed (at least 2 distinct lines, under 40% found)
    - it says it CREATED LOKI's own files (a .venv python, engine/*.py, tests/test_*.py, harness_data/jobs/*.log) in
      a project folder - a fake LOKI to prove against
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ["cannot be read"]
    problems = []
    # a placeholder on a COMMAND line (curl -H "Bearer <engine token>") is the thing to fill in; anywhere else it is
    # an output that was never produced
    cmd_line = re.compile(r"^\s*(\$\s*)?(curl|python3?|harness_data|git|npm|npx|cd|uv|pip|\.\\|\./|\w:\\)", re.I)
    bad = sorted(set(m.group(0) for ln in text.splitlines() if not cmd_line.search(ln) and "`curl" not in ln
                     and "`python" not in ln and "`harness_data" not in ln for m in _PLACEHOLDER.finditer(ln)))
    if bad:
        problems.append("placeholders left in instead of real output: %s" % ", ".join(bad[:4]))
    if corpus_text:   # nothing recorded (a harness that hides its tool output): only the checks below apply
        unproven = 0
        checked = 0
        for head, body in _blocks(text):
            if re.search(r"\b(command|run this|i ran|ran:)\b", head, re.I) and not re.search(r"output|result|answer", head, re.I):
                continue   # the command itself, not its output
            lines = _distinct_lines(body)
            if len(lines) < 2:
                continue
            checked += 1
            found = sum(1 for ln in lines if ln in corpus_text)
            if found < 0.4 * len(lines):
                unproven += 1
        if checked and unproven:
            problems.append("%d of %d pasted outputs were never printed by any tool this team ran (made up)"
                            % (unproven, checked))
    fake = []
    in_created = False
    for ln in text.splitlines():
        if _CREATED_HEAD.search(ln):
            in_created = True
            continue
        if in_created and ln.strip().startswith("#"):
            in_created = False
        if in_created:
            fake += [m.group(1) for m in _FAKE_LOKI.finditer(ln)]
    if fake:
        problems.append("it says it created LOKI's own files in the project folder (a fake LOKI to test against): %s"
                        % ", ".join(sorted(set(fake))[:4]))
    return problems
