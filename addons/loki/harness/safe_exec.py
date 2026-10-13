"""Structured command execution - no shell, ever.

`run_command` used to hand a raw string to the OS shell (`shell=True`). That makes
every model-written command a shell program: pipes, redirects, `$(...)`, `;` and
backticks all execute. This module replaces it with argument-based execution:

  * The string is split into an argv with shlex - no shell sees it.
  * `&&` chains are supported as a sequence of separate argv runs that stops at the
    first failure (the one shell feature models genuinely need: `cd`-free "build && test").
  * Every other shell operator (| || ; & > >> < ` $( ${ newline) is refused with a
    readable reason. Quoted text containing those characters is fine - it is data.
  * The executable is resolved on PATH (or a path inside the workspace); it must exist.
  * Each step gets the timeout; output is captured, never interpreted.

Pure parsing (`parse`) is separate from running (`run`) so the policy engine can check
a command without executing it. Standard library only.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Tokens that only mean something to a shell. A token consisting of (or starting with)
# one of these, outside quotes, is refused.
_OPERATORS = ("||", "|", ";", "&", ">>", ">", "<<", "<", "2>", "1>", "&>")
_SUBSTITUTIONS = ("$(", "${", "`")
MAX_STEPS = 8


class CommandRejected(ValueError):
    """The command uses a shell feature Loki does not run."""


def _split(command: str) -> list[tuple[str, bool]]:
    """Tokens with a flag saying whether the token was (partly) quoted."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    if sys.platform == "win32":
        lexer.escape = ""  # keep C:\\path\\file intact
    tokens: list[tuple[str, bool]] = []
    try:
        for token in lexer:
            tokens.append((token, False))
    except ValueError as exc:  # unbalanced quotes
        raise CommandRejected("could not parse the command: %s" % exc) from exc
    return tokens


def _quoted_spans(command: str) -> list[tuple[int, int]]:
    spans, quote, start = [], "", 0
    for i, ch in enumerate(command):
        if quote:
            if ch == quote:
                spans.append((start, i))
                quote = ""
        elif ch in ("'", '"'):
            quote, start = ch, i
    return spans


def _unquoted(command: str) -> str:
    """The command with quoted regions blanked, so operator checks ignore data."""
    chars = list(command)
    for start, end in _quoted_spans(command):
        for i in range(start, end + 1):
            chars[i] = " "
    return "".join(chars)


def parse(command: str) -> list[list[str]]:
    """Split a command into argv steps (one per `&&` segment). Raises CommandRejected."""
    text = str(command or "").strip()
    if not text:
        raise CommandRejected("empty command")
    if "\n" in text or "\r" in text:
        raise CommandRejected("multi-line commands are not run; send one command at a time")
    bare = _unquoted(text)
    for token in _SUBSTITUTIONS:
        if token in bare:
            raise CommandRejected("shell substitution (%s) is not run - Loki executes commands without a shell" % token)
    steps: list[list[str]] = [[]]
    for token, _q in _split(text):
        if token == "&&":
            if not steps[-1]:
                raise CommandRejected("'&&' needs a command on both sides")
            steps.append([])
            continue
        if token in _OPERATORS or (token and set(token) <= set("|&;<>")):
            raise CommandRejected(
                "the shell operator %r is not run - Loki executes commands without a shell. "
                "Run one command (or 'a && b'), and read files with read_file instead of pipes/redirects"
                % token)
        steps[-1].append(token)
    if not steps[-1]:
        raise CommandRejected("'&&' needs a command on both sides")
    if len(steps) > MAX_STEPS:
        raise CommandRejected("at most %d chained commands" % MAX_STEPS)
    return steps


def resolve(argv0: str, cwd: str) -> str:
    """Absolute path of the executable, or raise CommandRejected."""
    candidate = Path(argv0)
    if candidate.parent != Path("."):
        target = (Path(cwd) / candidate).resolve() if not candidate.is_absolute() else candidate
        if target.is_file():
            return str(target)
        raise CommandRejected("no such program: %s" % argv0)
    found = shutil.which(argv0, path=os.environ.get("PATH"))
    if not found and sys.platform == "win32":
        builtins = {"dir", "type", "echo", "copy", "del", "move", "mkdir", "rmdir", "cd", "set", "ren"}
        if argv0.lower() in builtins:
            raise CommandRejected("%r is a cmd.exe built-in; use the file tools (list_files, read_file, "
                                  "write_file, move_file) instead" % argv0)
    if not found:
        raise CommandRejected("program not found on PATH: %s" % argv0)
    return found


def run(command: str, cwd: str, timeout: int = 120, runner=subprocess.run) -> tuple[int, str]:
    """Run the parsed steps in order without a shell. Returns (exit_code, combined_output)."""
    steps = parse(command)
    outputs: list[str] = []
    code = 0
    for argv in steps:
        argv = [resolve(argv[0], cwd), *argv[1:]]
        try:
            proc = runner(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, shell=False)
        except subprocess.TimeoutExpired:
            outputs.append("error: command timed out after %ds: %s" % (timeout, Path(argv[0]).name))
            return 124, "\n".join(outputs).strip()
        code = proc.returncode
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if len(steps) > 1:
            out = "$ %s\n%s" % (" ".join([Path(argv[0]).name, *argv[1:]]), out)
        outputs.append(out)
        if code != 0:
            break
    return code, "\n".join(o for o in outputs if o).strip()
