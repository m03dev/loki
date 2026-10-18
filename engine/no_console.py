"""No console windows on Windows - ever (owner, 2026-10-18: "the terminal keeps popping up on my screen").

LOKI runs without a console (pythonw), so every console program it starts - git, nvidia-smi, ollama, python, Godot's
command-line runs, a job's tests - gets a NEW black console window that flashes up on the owner's screen, unless the
call passes CREATE_NO_WINDOW. Many calls did not. install() makes it the default for every subprocess this process
starts: a call that sets its own creationflags (Godot editor: DETACHED_PROCESS; a job: NEW_PROCESS_GROUP...) keeps
them, plus CREATE_NO_WINDOW unless it is detached. Imported first by the engine, the jobs, Studio and the app.
LOKI_SHOW_CONSOLES=1 turns it off (debugging)."""
from __future__ import annotations

import os
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_CONSOLE = 0x00000010


def flags(given: int) -> int:
    """The creationflags a call ends up with: a detached process or an asked-for console stays as asked."""
    given = int(given or 0)
    if given & (DETACHED_PROCESS | CREATE_NEW_CONSOLE):
        return given
    return given | CREATE_NO_WINDOW


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
