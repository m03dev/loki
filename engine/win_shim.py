"""Windows npm shims: run the real program, not the .cmd wrapper.

`npm i -g opencode-ai` on Windows puts `opencode.cmd` on PATH: a 4-line batch file that forwards to
node_modules/opencode-ai/bin/opencode.exe. Anything started through a .cmd/.bat runs inside cmd.exe, which caps the
WHOLE command line at 8,191 characters (not CreateProcess's 32,767) and mangles newlines, %, ^, & and | in arguments.
On the PC (2026-10-27) every job whose prompt was over ~8 KB died with cmd.exe's "The command line is too long." on
every provider in 0.1 s. `real_exe()` reads the shim and returns the .exe it forwards to, so LOKI starts it directly.
Pure stdlib, safe on macOS/Linux (it only touches paths ending in .cmd/.bat).
"""
from __future__ import annotations

import re
from pathlib import Path

# cmd.exe's own limit is 8,191 characters for the whole line; keep room for the exe path and other arguments.
CMD_LINE_MAX = 7000

# npm's cmd-shim forms:   "%dp0%\node_modules\pkg\bin\x.exe"   %*
#                         "%_prog%"  "%dp0%\node_modules\pkg\bin\x.js" %*     (node script - handled below)
_TARGET = re.compile(r'"%~?dp0%?\\?([^"%]+?)"', re.IGNORECASE)


def is_batch(path: str) -> bool:
    return str(path or "").lower().endswith((".cmd", ".bat"))


def real_exe(path: str) -> str:
    """The native .exe an npm .cmd shim forwards to, or `path` unchanged when it is not such a shim (or on any
    error). Only an existing .exe is returned - a shim that runs a .js through node keeps the .cmd."""
    if not is_batch(path):
        return path
    try:
        shim = Path(path)
        text = shim.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return path
    for rel in _TARGET.findall(text):
        rel = rel.strip().lstrip("\\/")
        if not rel.lower().endswith(".exe"):
            continue
        target = shim.parent.joinpath(*re.split(r"[\\/]+", rel))
        if target.is_file():
            return str(target)
    return path


def argv_limit(exe: str, default: int) -> int:
    """How long one argument may be before it should go in a file instead: cmd.exe's limit for a batch file."""
    return min(default, CMD_LINE_MAX) if is_batch(exe) else default
