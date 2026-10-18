"""No console windows on Windows - ever (owner, 2026-10-18: "the terminal keeps popping up on my screen").

LOKI runs without a console (pythonw), so every console program it starts - git, nvidia-smi, ollama, python, Godot's
command-line runs, a job's tests - gets a NEW black console window that flashes up on the owner's screen, unless the
call passes CREATE_NO_WINDOW. Many calls did not. install() makes it the default for every subprocess this process
starts: a call's own creationflags are kept (NEW_PROCESS_GROUP...), DETACHED_PROCESS is swapped for CREATE_NO_WINDOW
(see flags()), an asked-for new console is left alone. Imported first by the engine, the jobs, Studio and the app.
LOKI_SHOW_CONSOLES=1 turns it off (debugging)."""
from __future__ import annotations

import os
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_CONSOLE = 0x00000010


def flags(given: int) -> int:
    """The creationflags a call ends up with. DETACHED_PROCESS becomes CREATE_NO_WINDOW: a detached process has NO
    console, so every console program IT starts (node's git, a CLI's shell) pops a new visible one; with a hidden
    console they inherit it and stay invisible. A GUI app (the Godot editor) ignores both. An asked-for console stays."""
    given = int(given or 0)
    if given & CREATE_NEW_CONSOLE:
        return given
    return (given & ~DETACHED_PROCESS) | CREATE_NO_WINDOW


def install(platform: str | None = None) -> bool:
    if (platform or sys.platform) != "win32" or os.getenv("LOKI_SHOW_CONSOLES", "") == "1":
        return False
    popen = subprocess.Popen
    if getattr(popen, "_loki_no_console", False):
        return True
    original = popen.__init__

    def __init__(self, *args, **kwargs):  # noqa: N807
        if len(args) < 14:                # creationflags is Popen's 14th parameter; positional use is unheard of
            kwargs["creationflags"] = flags(kwargs.get("creationflags", 0))
        original(self, *args, **kwargs)

    popen.__init__ = __init__
    popen._loki_no_console = True
    return True


install()
