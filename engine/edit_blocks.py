"""SEARCH/REPLACE edit blocks: the edit format small models get right most often.

Ported from aider's EditBlockCoder (Aider-AI/aider, aider/coders/editblock_coder.py:
find_original_update_blocks, find_filename, strip_filename, replace_most_similar_chunk,
perfect_or_whitespace, replace_part_with_missing_leading_whitespace, try_dotdotdots,
find_similar_lines and the "SearchReplaceNoExactMatch" error text), Apache-2.0 - see
engine/licenses/Aider-Apache-2.0.txt.

A 7-9B model writing JSON tool arguments has to escape every quote and newline of the code it
edits - the most common way a local model's edit fails. aider's format is plain text:

    path/to/file.py
    <<<<<<< SEARCH
    exact lines that are in the file now
    =======
    the lines that replace them
    >>>>>>> REPLACE

Several blocks (several files) go in one call. Matching is forgiving the way aider's is: exact,
then ignoring a uniform leading-whitespace difference, then without a spurious first blank line,
then `...` elision; an empty SEARCH creates a file or appends. A block that does not match is
reported with the closest real lines ("did you mean"), and the blocks that did apply are kept
and named so the model only resends the failures.

LOKI keeps CRLF files CRLF and records every changed file in file_editor's undo history, so
undo_edit reverts an apply_edits change too. Pure functions + the file writes; no network.
"""
from __future__ import annotations

import difflib
import re
from difflib import SequenceMatcher
from pathlib import Path

import file_editor

HEAD = r"^<{5,9} SEARCH>?\s*$"
DIVIDER = r"^={5,9}\s*$"
UPDATED = r"^>{5,9} REPLACE\s*$"
HEAD_ERR, DIVIDER_ERR, UPDATED_ERR = "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"
FENCE = ("```", "```")
MAX_BLOCKS = 40

FORMAT_HELP = (
    "Each edit is a SEARCH/REPLACE block: the file path alone on a line, then\n"
    "<<<<<<< SEARCH\n<the exact current lines, enough to be unique>\n=======\n<the new lines>\n>>>>>>> REPLACE\n"
    "An empty SEARCH section creates the file (or appends to it).")


class BlockError(ValueError):
    pass


# --------------------------------------------------------------------------- parsing (aider)

def strip_filename(filename: str, fence=FENCE):
    filename = filename.strip()
    if filename == "..." or not filename or any(re.match(p, filename) for p in (HEAD, DIVIDER, UPDATED)):
        return None     # LOKI: a previous block's marker is not a file name (the next block reuses the last one)
    for start in (fence[0], "```"):
        if filename.startswith(start):
            candidate = filename[len(start):]
            if candidate and ("." in candidate or "/" in candidate):
                return candidate
            return None
    filename = filename.rstrip(":").lstrip("#").strip().strip("`").strip("*")
    return filename or None


def find_filename(lines: list, valid_fnames=None, fence=FENCE):
    valid_fnames = list(valid_fnames or [])
    lines = list(reversed(lines))[:3]
    filenames = []
    for line in lines:
        name = strip_filename(line, fence)
        if name:
            filenames.append(name)
        if not line.startswith(fence[0]) and not line.startswith("```"):
            break
    if not filenames:
        return None
    for name in filenames:
        if name in valid_fnames:
            return name
    for name in filenames:
        for valid in valid_fnames:
            if name == Path(valid).name:
                return valid
    for name in filenames:
        close = difflib.get_close_matches(name, valid_fnames, n=1, cutoff=0.8)
        if len(close) == 1:
            return close[0]
    for name in filenames:
        if "." in name:
            return name
    return filenames[0]


def parse(content: str, valid_fnames=None, fence=FENCE) -> list:
    """[(filename, original, updated)] from the text. Raises BlockError on a malformed block."""
    lines = content.splitlines(keepends=True)
    head, divider, updated = re.compile(HEAD), re.compile(DIVIDER), re.compile(UPDATED)
    blocks, i, current = [], 0, None
    while i < len(lines):
        if head.match(lines[i].strip()):
            try:
                if i + 1 < len(lines) and divider.match(lines[i + 1].strip()):
                    filename = find_filename(lines[max(0, i - 3):i], None, fence)
                else:
                    filename = find_filename(lines[max(0, i - 3):i], valid_fnames, fence)
                if not filename:
                    if not current:
                        raise BlockError("Bad/missing filename. The filename must be alone on the line before "
                                         "<<<<<<< SEARCH")
                    filename = current
                current = filename
                original = []
                i += 1
                while i < len(lines) and not divider.match(lines[i].strip()):
                    original.append(lines[i])
                    i += 1
                if i >= len(lines) or not divider.match(lines[i].strip()):
                    raise BlockError("Expected `%s`" % DIVIDER_ERR)
                new = []
                i += 1
                while i < len(lines) and not (updated.match(lines[i].strip()) or divider.match(lines[i].strip())):
                    new.append(lines[i])
                    i += 1
                if i >= len(lines):
                    raise BlockError("Expected `%s` or `%s`" % (UPDATED_ERR, DIVIDER_ERR))
                blocks.append((filename, "".join(original), "".join(new)))
                if len(blocks) > MAX_BLOCKS:
                    raise BlockError("too many blocks in one call (at most %d)" % MAX_BLOCKS)
            except BlockError as exc:
                shown = "".join(lines[max(0, i - 6):i + 1])
                raise BlockError("%s\n^^^ %s" % (shown, exc)) from None
        i += 1
    return blocks


# --------------------------------------------------------------------------- matching (aider)

def _prep(content: str):
    if content and not content.endswith("\n"):
        content += "\n"
    return content, content.splitlines(keepends=True)


def perfect_replace(whole_lines, part_lines, replace_lines):
    part = tuple(part_lines)
    n = len(part_lines)
    for i in range(len(whole_lines) - n + 1):
        if tuple(whole_lines[i:i + n]) == part:
            return "".join(whole_lines[:i] + replace_lines + whole_lines[i + n:])
    return None


def match_but_for_leading_whitespace(whole_lines, part_lines):
    if not all(whole_lines[i].lstrip() == part_lines[i].lstrip() for i in range(len(whole_lines))):
        return None
    add = {whole_lines[i][:len(whole_lines[i]) - len(part_lines[i])]
           for i in range(len(whole_lines)) if whole_lines[i].strip()}
    if len(add) != 1:
        return None
    return add.pop()


def replace_part_with_missing_leading_whitespace(whole_lines, part_lines, replace_lines):
    leading = ([len(p) - len(p.lstrip()) for p in part_lines if p.strip()]
               + [len(p) - len(p.lstrip()) for p in replace_lines if p.strip()])
    if leading and min(leading):
        cut = min(leading)
        part_lines = [p[cut:] if p.strip() else p for p in part_lines]
        replace_lines = [p[cut:] if p.strip() else p for p in replace_lines]
    n = len(part_lines)
    for i in range(len(whole_lines) - n + 1):
        add = match_but_for_leading_whitespace(whole_lines[i:i + n], part_lines)
        if add is None:
            continue
        replace_lines = [add + r if r.strip() else r for r in replace_lines]
        return "".join(whole_lines[:i] + replace_lines + whole_lines[i + n:])
    return None


def perfect_or_whitespace(whole_lines, part_lines, replace_lines):
    return (perfect_replace(whole_lines, part_lines, replace_lines)
            or replace_part_with_missing_leading_whitespace(whole_lines, part_lines, replace_lines))


def try_dotdotdots(whole: str, part: str, replace: str):
    dots = re.compile(r"(^\s*\.\.\.\n)", re.MULTILINE | re.DOTALL)
    part_pieces, replace_pieces = re.split(dots, part), re.split(dots, replace)
    if len(part_pieces) != len(replace_pieces):
        raise ValueError("Unpaired ... in SEARCH/REPLACE block")
    if len(part_pieces) == 1:
        return None
    if not all(part_pieces[i] == replace_pieces[i] for i in range(1, len(part_pieces), 2)):
        raise ValueError("Unmatched ... in SEARCH/REPLACE block")
    for p, r in zip(part_pieces[0::2], replace_pieces[0::2]):
        if not p and not r:
            continue
        if not p and r:
            whole = (whole if whole.endswith("\n") else whole + "\n") + r
            continue
        if whole.count(p) != 1:
            raise ValueError("a ... piece does not match exactly once")
        whole = whole.replace(p, r, 1)
    return whole


def replace_most_similar_chunk(whole: str, part: str, replace: str):
    whole, whole_lines = _prep(whole)
    part, part_lines = _prep(part)
    replace, replace_lines = _prep(replace)
    res = perfect_or_whitespace(whole_lines, part_lines, replace_lines)
    if res:
        return res
    if len(part_lines) > 2 and not part_lines[0].strip():
        res = perfect_or_whitespace(whole_lines, part_lines[1:], replace_lines)
        if res:
            return res
    try:
        return try_dotdotdots(whole, part, replace)
    except ValueError:
        return None


def strip_quoted_wrapping(text: str, fname: str = "", fence=FENCE) -> str:
    if not text:
        return text
    lines = text.splitlines()
    if fname and lines and lines[0].strip().endswith(Path(fname).name):
        lines = lines[1:]
    if lines and lines[0].startswith(fence[0]) and lines[-1].startswith(fence[1]):
        lines = lines[1:-1]
    out = "\n".join(lines)
    return out + "\n" if out and not out.endswith("\n") else out


def find_similar_lines(search: str, content: str, threshold: float = 0.6) -> str:
    search_lines, content_lines = search.splitlines(), content.splitlines()
    best_ratio, best_i = 0.0, -1
    for i in range(len(content_lines) - len(search_lines) + 1):
        ratio = SequenceMatcher(None, search_lines, content_lines[i:i + len(search_lines)]).ratio()
        if ratio > best_ratio:
            best_ratio, best_i = ratio, i
    if best_ratio < threshold or best_i < 0:
        return ""
    best = content_lines[best_i:best_i + len(search_lines)]
    if best and search_lines and best[0] == search_lines[0] and best[-1] == search_lines[-1]:
        return "\n".join(best)
    return "\n".join(content_lines[max(0, best_i - 5):min(len(content_lines), best_i + len(search_lines) + 5)])


# --------------------------------------------------------------------------- applying

def apply(text: str, resolve, valid_fnames=None, dry_run: bool = False) -> dict:
    """Apply every block in `text`. `resolve(name) -> Path` keeps paths inside the workspace.

    Returns {"applied": [names], "failed": [(name, why)], "created": [names], "report": str}."""
    try:
        blocks = parse(text, valid_fnames)
    except BlockError as exc:
        return {"applied": [], "failed": [("", str(exc))], "created": [],
                "report": "error: %s\n%s" % (exc, FORMAT_HELP)}
    if not blocks:
        return {"applied": [], "failed": [("", "no blocks")], "created": [],
                "report": "error: no SEARCH/REPLACE blocks found.\n" + FORMAT_HELP}
    pending: dict = {}      # path -> (text, newline, original text or None for a new file)
    applied, failed, created = [], [], []
    for fname, original, updated in blocks:
        try:
            path = Path(resolve(fname))
        except Exception as exc:  # noqa: BLE001 - outside the workspace
            failed.append((fname, "refused: %s" % exc))
            continue
        before = strip_quoted_wrapping(original, fname)
        after = strip_quoted_wrapping(updated, fname)
        if path in pending:
            content, newline, first = pending[path]
        elif path.is_file():
            try:
                content, newline = file_editor._read(path)  # noqa: SLF001
            except file_editor.EditError as exc:
                failed.append((fname, str(exc)))
                continue
            first = content
        else:
            if before.strip():
                failed.append((fname, "no such file (an empty SEARCH section creates a new file)"))
                continue
            content, newline, first = "", "\n", None
        if not before.strip():
            new = content + after
        else:
            new = replace_most_similar_chunk(content, before, after)
        if new is None:
            why = "SearchReplaceNoExactMatch: this SEARCH block failed to exactly match lines in %s" % fname
            hint = find_similar_lines(before, content)
            if hint:
                why += "\nDid you mean to match some of these actual lines from %s?\n```\n%s\n```" % (fname, hint)
            if after.strip() and after in content:
                why += "\nAre you sure you need this block? The REPLACE lines are already in %s!" % fname
            failed.append((fname, why))
            continue
        pending[path] = (new, newline, first)
        applied.append(fname)
        if first is None and fname not in created:
            created.append(fname)
    if not dry_run:
        for path, (new, newline, first) in pending.items():
            if first is not None:
                file_editor._remember(path, first, newline)  # noqa: SLF001 - undo_edit reverts it
            path.parent.mkdir(parents=True, exist_ok=True)
            file_editor._write(path, new, newline)  # noqa: SLF001
    lines = []
    if applied:
        lines.append("applied %d block(s): %s" % (len(applied), ", ".join(sorted(set(applied)))))
    if created:
        lines.append("created: %s" % ", ".join(created))
    if failed:
        lines.append("# %d SEARCH/REPLACE block(s) failed to match!" % len(failed))
        for name, why in failed:
            lines.append("\n## %s\n%s" % (name or "(block)", why))
        lines.append("\nThe SEARCH section must exactly match existing lines, including whitespace and comments.")
        if applied:
            lines.append("The other blocks were applied - do not resend them; send fixed versions of the failed "
                         "blocks only.")
    report = "\n".join(lines)
    if failed and not applied:
        report = "error: " + report
    return {"applied": applied, "failed": failed, "created": created, "report": report}
