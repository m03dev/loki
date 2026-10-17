"""Lint-on-edit: an edit that BREAKS a file is not applied, and the model is told why.

Ported into LOKI (session 27 harvest) from SWE-agent (github.com/SWE-agent/SWE-agent,
tools/windowed_edit_replace/bin/edit and bin/insert: lint before, lint after, keep only the
errors the edit introduced, undo the edit, show "how your edit would have looked" next to the
original), MIT License, Copyright (c) 2024 John Yang, Carlos E. Jimenez, Alexander Wettig,
Kilian Lieret, Shunyu Yao, Karthik Narasimhan, Ofir Press - see engine/licenses/SWE-agent-MIT.txt.

SWE-agent runs flake8; LOKI has no linter installed on every machine, so the checks here are
standard-library parsers (Python, JSON, TOML, XML/SVG) plus a bracket balance for C-like code
(JS/TS/CSS/Java/C/Go/Rust/...): the most common way a small model breaks a file is a dropped
or extra closing brace. Errors that were already in the file before the edit are not blamed on
it (the SWE-agent rule), so a file that was broken stays editable.

Pure functions; LOKI_EDIT_LINT=0 turns the guard off.
"""
from __future__ import annotations

import ast
import json
import os
import re
import xml.etree.ElementTree as ET

LINT_ERROR_TEMPLATE = """Your proposed edit has introduced new syntax error(s). Please read this error message carefully and then retry editing the file.

ERRORS:
{errors}

This is how your edit would have looked if applied
------------------------------------------------
{window_applied}
------------------------------------------------

This is the original code before your edit
------------------------------------------------
{window_original}
------------------------------------------------

Your changes have NOT been applied. Please fix your edit command and try again.
DO NOT re-run the same failed edit command. Running it again will lead to the same error."""

C_LIKE = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css", ".scss", ".less", ".java", ".c", ".h",
          ".cc", ".cpp", ".hpp", ".cs", ".go", ".rs", ".swift", ".kt", ".kts", ".php", ".dart"}
PAIRS = {"{": "}", "(": ")", "[": "]"}
WINDOW = 5


def enabled() -> bool:
    return str(os.getenv("LOKI_EDIT_LINT", "1")).strip().lower() not in ("0", "false", "off", "no")


def _suffix(name: str) -> str:
    return os.path.splitext(str(name or "").lower())[1]


def _strip_c_like(text: str) -> str:
    """Code with strings and comments blanked, so brackets inside them do not count."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch == "#" and (i == 0 or text[i - 1] == "\n"):   # preprocessor / shell-style line
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch in "\"'`":
            quote, i = ch, i + 1
            while i < n and text[i] != quote:
                if text[i] == "\\":
                    i += 1
                elif text[i] == "\n" and quote != "`":
                    break
                i += 1
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def bracket_errors(text: str) -> list:
    """Unbalanced (), [], {} in C-like code (strings and comments ignored)."""
    code = _strip_c_like(text)
    stack, errors = [], []
    closers = {v: k for k, v in PAIRS.items()}
    line = 1
    for ch in code:
        if ch == "\n":
            line += 1
        elif ch in PAIRS:
            stack.append((ch, line))
        elif ch in closers:
            if not stack or stack[-1][0] != closers[ch]:
                errors.append("line %d: unexpected '%s'" % (line, ch))
                if len(errors) >= 3:
                    return errors
            else:
                stack.pop()
    for ch, ln in stack[-3:]:
        errors.append("line %d: '%s' is never closed" % (ln, ch))
    return errors


def check(name: str, text: str) -> list:
    """Syntax errors in `text` for a file called `name` ([] = fine or not checkable)."""
    suffix = _suffix(name)
    try:
        if suffix in (".py", ".pyw"):
            compile(text, name, "exec", dont_inherit=True)
        elif suffix == ".json":
            json.loads(text)
        elif suffix == ".toml":
            try:
                import tomllib  # Python 3.11+
            except ImportError:
                return []
            tomllib.loads(text)
        elif suffix in (".xml", ".svg", ".plist", ".xhtml"):
            ET.fromstring(text.encode("utf-8"))
        elif suffix in C_LIKE:
            return bracket_errors(text)
        else:
            return []
    except SyntaxError as exc:
        where = ("line %s: " % exc.lineno) if getattr(exc, "lineno", None) else ""
        return ["%s%s: %s" % (where, type(exc).__name__, exc.msg if hasattr(exc, "msg") else exc)]
    except ValueError as exc:   # json.JSONDecodeError, tomllib.TOMLDecodeError
        return ["%s: %s" % (type(exc).__name__, exc)]
    except ET.ParseError as exc:
        return ["XML: %s" % exc]
    except Exception as exc:  # noqa: BLE001 - a parser crash is not the model's fault
        return [] if not str(exc) else ["%s: %s" % (type(exc).__name__, str(exc)[:200])]
    return []


def _key(error: str) -> str:
    """An error without its line number, so a shifted pre-existing error is still recognised."""
    return re.sub(r"line \d+", "line N", error)


def introduced(name: str, before: str, after: str) -> list:
    """Errors present after the edit that were not there before it (SWE-agent's rule)."""
    if not enabled():
        return []
    new = check(name, after)
    if not new:
        return []
    old = {_key(e) for e in check(name, before)}
    return [e for e in new if _key(e) not in old]


def window(text: str, line: int, extra: int = 0) -> str:
    lines = text.split("\n")
    start = max(0, line - 1 - WINDOW)
    end = min(len(lines), line + WINDOW + extra)
    return "\n".join("%6d\t%s" % (i + 1, lines[i]) for i in range(start, end))


def report(errors: list, before: str, after: str, line: int, new_lines: int = 0, old_lines: int = 0) -> str:
    return LINT_ERROR_TEMPLATE.format(errors="\n".join("- " + e for e in errors[:6]),
                                      window_applied=window(after, line, new_lines),
                                      window_original=window(before, line, old_lines))
