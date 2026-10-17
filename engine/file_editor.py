"""File editing with precise semantics: view with line ranges, unique str_replace, insert, undo.

Ported from OpenHands' file editor (OpenHands/software-agent-sdk,
openhands-tools/openhands/tools/file_editor/editor.py: view / str_replace / insert / undo_edit,
SNIPPET_CONTEXT_WINDOW, MAX_RESPONSE_LEN_CHAR), MIT - see engine/licenses/OpenHands-MIT.txt.
Re-written on the standard library; LOKI's tool names stay (read_file, edit_file) and gain
these semantics, plus insert_lines and undo_edit.

  view       `cat -n` style numbered lines for [start, end] (end -1 = to the end); a range past
             the end is clipped with a note; a whole file over MAX_RESPONSE_LEN is cut with a
             note to use a range.
  replace    old text must appear EXACTLY ONCE (unless replace_all): none -> retry with the old
             text stripped of outer whitespace, still none -> a precise error; several -> an error
             naming their line numbers. The result shows a numbered snippet around the edit.
  insert     new text after line N (0 = at the top), N within [0, number of lines].
  undo       the file as it was before the last edit made here (5 kept per file).

Line endings are kept: a CRLF file (Windows) stays CRLF; matching works on LF either way.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

SNIPPET_CONTEXT_WINDOW = 4
MAX_RESPONSE_LEN = 16000
HISTORY_DEPTH = 5
_HISTORY: dict = {}


class EditError(ValueError):
    pass


def _read(path: Path) -> tuple:
    """(text with LF line endings, newline the file uses)."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise EditError("cannot edit %s: it is not UTF-8 text" % path) from None
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), newline


def _write(path: Path, text: str, newline: str) -> None:
    data = text.replace("\n", newline) if newline != "\n" else text
    path = Path(path)
    tmp = path.with_name(path.name + ".loki-tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _remember(path: Path, text: str, newline: str) -> None:
    key = str(Path(path).resolve())
    stack = _HISTORY.setdefault(key, [])
    stack.append((text, newline))
    del stack[:-HISTORY_DEPTH]


def numbered(text: str, start_line: int = 1) -> str:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join("%6d\t%s" % (i + start_line, line) for i, line in enumerate(lines))


def _truncate(text: str, limit: int = MAX_RESPONSE_LEN) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit("\n", 1)[0]
    return cut + ("\n<response clipped: the file is longer than %d characters. Read the rest with a line "
                  "range (start_line/end_line), or search_files for the line you need.>" % limit)


def view(path: Path, start_line: int | None = None, end_line: int | None = None, label: str = "") -> str:
    path = Path(path)
    if not path.is_file():
        raise EditError("no file %s" % (label or path))
    text, _nl = _read(path)
    label = label or str(path)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    total = len(lines)
    if start_line is None and end_line is None:
        return "Here's the result of running `cat -n` on %s (%d lines):\n%s\n" % (
            label, total, _truncate(numbered(text)))
    start = 1 if start_line is None else int(start_line)
    end = -1 if end_line is None else int(end_line)
    if start < 1 or start > max(total, 1):
        raise EditError("start_line %d should be within the lines of the file: [1, %d]" % (start, total))
    note = ""
    if end == -1:
        end = total
    elif end > total:
        note = "NOTE: only %d lines in this file, so up to %d is shown.\n" % (total, total)
        end = total
    if end < start:
        raise EditError("end_line %d should be greater than or equal to start_line %d" % (end, start))
    body = "\n".join(lines[start - 1:end])
    return "%sHere's the result of running `cat -n` on %s, lines %d-%d of %d:\n%s\n" % (
        note, label, start, end, total, _truncate(numbered(body, start)))


def _snippet(text: str, line: int, extra_lines: int, label: str) -> str:
    lines = text.split("\n")
    start = max(0, line - 1 - SNIPPET_CONTEXT_WINDOW)
    end = min(len(lines), line + SNIPPET_CONTEXT_WINDOW + extra_lines)
    body = "\n".join(lines[start:end])
    return "Here's a snippet of %s (cat -n):\n%s\n" % (label, numbered(body, start + 1))


def str_replace(path: Path, old: str, new: str, replace_all: bool = False, label: str = "") -> tuple:
    """(message, count). Raises EditError when nothing (or not one thing) matches."""
    path = Path(path)
    label = label or str(path)
    if not path.is_file():
        raise EditError("no file %s" % label)
    if old == "":
        raise EditError("old text is empty; use insert_lines or write_file to add text")
    text, newline = _read(path)
    old_n = str(old).replace("\r\n", "\n")
    new_n = str(new or "").replace("\r\n", "\n")
    hits = [m.start() for m in re.finditer(re.escape(old_n), text)]
    if not hits:
        stripped = old_n.strip()
        if stripped and stripped != old_n:
            hits = [m.start() for m in re.finditer(re.escape(stripped), text)]
            if hits:
                old_n = stripped
    if not hits:
        raise EditError("no replacement was made: that exact text does not appear in %s. Read the lines "
                        "again (read_file with start_line/end_line) and copy them exactly." % label)
    if len(hits) > 1 and not replace_all:
        lines = sorted({text.count("\n", 0, h) + 1 for h in hits})
        raise EditError("no replacement was made: the text appears %d times in %s (lines %s). Include more "
                        "surrounding lines so it is unique, or pass replace_all=true to change every one."
                        % (len(hits), label, lines[:20]))
    _remember(path, text, newline)
    first_line = text.count("\n", 0, hits[0]) + 1
    if replace_all:
        updated = text.replace(old_n, new_n)
    else:
        updated = text[:hits[0]] + new_n + text[hits[0] + len(old_n):]
    _write(path, updated, newline)
    return _snippet(updated, first_line, new_n.count("\n"), label), len(hits) if replace_all else 1


def insert(path: Path, insert_line: int, new_text: str, label: str = "") -> str:
    path = Path(path)
    label = label or str(path)
    if not path.is_file():
        raise EditError("no file %s" % label)
    text, newline = _read(path)
    lines = text.split("\n")
    trailing = bool(lines) and lines[-1] == ""
    if trailing:
        lines.pop()
    n = int(insert_line)
    if n < 0 or n > len(lines):
        raise EditError("insert_line %d should be within [0, %d] (0 = before the first line)" % (n, len(lines)))
    _remember(path, text, newline)
    piece = str(new_text or "").replace("\r\n", "\n")
    if piece.endswith("\n"):
        piece = piece[:-1]
    new_lines = piece.split("\n")
    lines[n:n] = new_lines
    updated = "\n".join(lines) + ("\n" if trailing or not lines else "")
    _write(path, updated, newline)
    return _snippet(updated, n + 1, len(new_lines), label)


def undo(path: Path, label: str = "") -> str:
    path = Path(path)
    label = label or str(path)
    stack = _HISTORY.get(str(path.resolve()), [])
    if not stack:
        raise EditError("no edit of %s to undo (only edits made in this session are kept)" % label)
    text, newline = stack.pop()
    _write(path, text, newline)
    return "undid the last edit of %s" % label


def count_lines(path: Path) -> int:
    text, _nl = _read(path)
    return len(text.split("\n")) - (1 if text.endswith("\n") else 0)
