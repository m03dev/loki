"""Shrink a big tool result so the model keeps what matters: errors, summaries, structure.

Ported into LOKI (session 27 harvest) from Headroom (github.com/chopratejas/headroom),
Apache-2.0, Copyright 2025 Headroom Contributors - see engine/licenses/Headroom-Apache-2.0.txt
and Headroom-NOTICE.txt:
  - SmartCrusher (transforms/smart_crusher.py, crates/headroom-core/src/transforms/smart_crusher):
    a long JSON array keeps its first and last items plus every item that carries an error
    keyword (error_keywords.rs: error, exception, failed, failure, critical, fatal, crash,
    panic, abort, timeout, denied, rejected), with a note of how many rows were dropped and the
    fields every row has;
  - LogCompressor (transforms/log_compressor.py, LogCompressorConfig defaults: max_errors 10,
    error_context_lines 3, keep first and last error, max_stack_traces 3 of 20 lines,
    max_warnings 5 de-duplicated by their shape, summary lines kept, max_total_lines 100):
    build/test/command output keeps its errors with context, its stack traces and its
    summary ("3 failed, 120 passed"), not the 2,000 lines of progress before them;
  - repeated identical lines collapse to one "(repeated N times)" line.
Headroom does this in Rust behind a proxy; here it is a few pure functions LOKI applies at its
one tool-result choke point (`loki._elide`) before falling back to head + tail.
"""
from __future__ import annotations

import json
import re

ERROR_KEYWORDS = ("error", "exception", "failed", "failure", "critical", "fatal", "crash", "panic", "abort",
                  "timeout", "denied", "rejected")
MAX_ERRORS = 10
ERROR_CONTEXT = 3
MAX_TRACES = 3
TRACE_LINES = 20
MAX_WARNINGS = 5
MAX_LINES = 100
KEEP_HEAD = 3
KEEP_TAIL = 2
MAX_ERROR_ITEMS = 6

_LEVEL_ERR = re.compile(r"\b(ERROR|FATAL|CRITICAL|FAIL(?:ED|URE)?|Traceback|panicked|Exception|error(?:\[E\d+\])?:)\b|"
                        r"^E\s{2,}|^\s*\w+(Error|Exception):", re.I)
_LEVEL_WARN = re.compile(r"\b(WARN(?:ING)?|DeprecationWarning|deprecated)\b", re.I)
_SUMMARY = re.compile(r"(\d+\s+(passed|failed|skipped|errors?|warnings?|tests?)\b|^=+ .* =+$|^-{3,}|"
                      r"\bTotal\b|\bSummary\b|^(OK|FAILED)\b|Ran \d+ tests?|exit (code|status)|\b\d+ passing\b|"
                      r"\b\d+ failing\b|test result:|Build (succeeded|failed)|BUILD (SUCCESS|FAILURE)|npm ERR!)", re.I)
_TRACE_START = re.compile(r"^(Traceback \(most recent call last\)|\s+at \S+.*\(.*:\d+(:\d+)?\)|thread '.*' panicked|"
                          r"Exception in thread|Caused by:)")
_TRACE_LINE = re.compile(r"^(\s+File \".*\", line \d+|\s+at |\s{2,}\S|\w+(\.\w+)*(Error|Exception)\b|Caused by:)")


def _has_error(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in ERROR_KEYWORDS)


# --------------------------------------------------------------------------- JSON (SmartCrusher)
def _crush_list(items: list, path: str = "") -> tuple:
    """(kept list, note) for one array."""
    n = len(items)
    if n <= KEEP_HEAD + KEEP_TAIL + 2:
        return items, ""
    keep = set(range(KEEP_HEAD)) | set(range(n - KEEP_TAIL, n))
    err = [i for i, it in enumerate(items) if i not in keep and _has_error(json.dumps(it, default=str)[:4000])]
    keep |= set(err[:MAX_ERROR_ITEMS])
    kept = [items[i] for i in sorted(keep)]
    fields = ""
    if all(isinstance(it, dict) for it in items):
        common = set(items[0])
        for it in items[1:]:
            common &= set(it)
        if common:
            fields = "; every row has: " + ", ".join(sorted(common)[:20])
    note = "%s%d of %d items shown (first %d, last %d%s)%s" % (
        (path + ": ") if path else "", len(kept), n, KEEP_HEAD, KEEP_TAIL,
        (", %d with errors" % len(err[:MAX_ERROR_ITEMS])) if err else "", fields)
    return kept, note


def crush_json(text: str) -> str:
    """A long JSON array (top level or one level down) cut to its telling rows, or ""."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return ""
    try:
        data = json.loads(stripped)
    except ValueError:
        return ""
    notes = []
    if isinstance(data, list):
        data, note = _crush_list(data)
        if note:
            notes.append(note)
    elif isinstance(data, dict):
        for key, value in list(data.items()):
            if isinstance(value, list):
                data[key], note = _crush_list(value, key)
                if note:
                    notes.append(note)
    if not notes:
        return ""
    body = json.dumps(data, indent=1, ensure_ascii=False, default=str)
    return body + "\n[compressed: " + "; ".join(notes) + ". Ask for a narrower query to see other rows.]"


# --------------------------------------------------------------------------- logs (LogCompressor)
def _shape(line: str) -> str:
    """A warning's shape: numbers, hex and paths after its first ':' or '=' normalised (the
    conservative Rust dedupe - the message id before it stays distinct)."""
    m = re.search(r"[:=]", line)
    head, tail = (line[:m.start() + 1], line[m.start() + 1:]) if m else ("", line)
    tail = re.sub(r"0x[0-9a-fA-F]+", "H", tail)
    tail = re.sub(r"/[\w./-]+/", "/P/", tail)
    tail = re.sub(r"\d+", "N", tail)
    return head + tail


def collapse_repeats(lines: list) -> list:
    out, prev, count = [], None, 0
    for line in lines + [None]:
        if line == prev:
            count += 1
            continue
        if prev is not None:
            out.append(prev if count == 1 else "%s   (repeated %d times)" % (prev, count))
        prev, count = line, 1
    return out


def compress_log(text: str, max_lines: int = MAX_LINES) -> str:
    """Errors with context, stack traces, summary lines and the end of the output; or ""."""
    lines = collapse_repeats(text.splitlines())
    n = len(lines)
    if n <= max_lines:
        return "\n".join(lines) if n < len(text.splitlines()) else ""
    keep: set = set()
    errors = [i for i, l in enumerate(lines) if _LEVEL_ERR.search(l)]
    if not errors and not any(_SUMMARY.search(l) for l in lines):
        return ""                      # not a log - leave it to the caller's head + tail
    chosen = errors[:MAX_ERRORS - 1] + (errors[-1:] if len(errors) >= MAX_ERRORS else [])
    for i in chosen:
        keep.update(range(max(0, i - ERROR_CONTEXT), min(n, i + ERROR_CONTEXT + 1)))
    traces = 0
    i = 0
    while i < n and traces < MAX_TRACES:
        if _TRACE_START.search(lines[i]):
            j = i + 1
            while j < n and (_TRACE_LINE.search(lines[j]) or not lines[j].strip()) and j - i < 200:
                j += 1
            span = list(range(i, min(j + 1, n)))
            if len(span) > TRACE_LINES:      # head frames, then the last frames (where it failed)
                span = span[:5] + span[-(TRACE_LINES - 5):]
            keep.update(span)
            traces += 1
            i = j
        i += 1
    seen_warn, warns = set(), 0
    for i, l in enumerate(lines):
        if _LEVEL_WARN.search(l) and i not in keep and warns < MAX_WARNINGS:
            shape = _shape(l)
            if shape not in seen_warn:
                seen_warn.add(shape)
                keep.add(i)
                warns += 1
        if _SUMMARY.search(l):
            keep.add(i)
    keep.update(range(max(0, n - 8), n))   # the end: totals and exit codes live there
    keep.update(range(0, min(3, n)))       # the start: the command / header
    ordered = sorted(keep)
    if len(ordered) > max_lines:          # errors first, then the end
        must = set(range(max(0, n - 8), n)) | set(chosen[:3])
        ordered = sorted(set(ordered[: max_lines - len(must)]) | must)
    out, last = [], -1
    for i in ordered:
        if i != last + 1:
            out.append("... [%d lines]" % (i - last - 1))
        out.append(lines[i])
        last = i
    if last < n - 1:
        out.append("... [%d lines]" % (n - 1 - last))
    return ("[compressed output: %d of %d lines kept - errors with context, stack traces, warnings, summary]\n"
            % (len(ordered), n)) + "\n".join(out)


def compress(text: str, limit: int) -> str:
    """The best compressed form of `text` that fits `limit`, or "" (caller falls back)."""
    body = str(text)
    if len(body) <= limit:
        return ""
    for fn in (crush_json, compress_log):
        try:
            out = fn(body)
        except Exception:  # noqa: BLE001 - compression must never break a tool result
            out = ""
        if out and len(out) <= limit:
            return out
        if out and fn is compress_log and len(out) > limit:
            shorter = compress_log(body, max_lines=max(20, MAX_LINES * limit // max(len(out), 1)))
            if shorter and len(shorter) <= limit:
                return shorter
    return ""
