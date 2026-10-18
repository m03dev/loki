"""engine/no_console.py: nothing LOKI starts on Windows opens a console window (owner, 2026-10-18: "the terminal
keeps popping up on my screen"). Runs anywhere: the Windows patch is checked with a fake Popen."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import no_console  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (detail,)))


check("a plain call gets CREATE_NO_WINDOW", no_console.flags(0) == 0x08000000)
check("a call's own flags are kept, plus no window", no_console.flags(0x00000200) == 0x08000200)
check("a detached process gets a hidden console instead (its own children then stay hidden too)",
      no_console.flags(0x00000008 | 0x00000200) == 0x08000200)
check("an asked-for new console is left as asked", no_console.flags(0x00000010) == 0x00000010)

seen = []


class FakePopen:
    def __init__(self, *args, **kwargs):
        seen.append(kwargs.get("creationflags"))


real = subprocess.Popen
subprocess.Popen = FakePopen
try:
    check("install() patches Popen on Windows", no_console.install("win32") is True)
    subprocess.Popen(["git", "status"])
    subprocess.Popen(["godot"], creationflags=0x00000008)
    check("every Popen (run, check_output...) starts without a console", seen == [0x08000000, 0x08000000], seen)
    check("installing twice is harmless", no_console.install("win32") is True)
finally:
    subprocess.Popen = real
check("nothing changes on macOS / Linux", no_console.install("darwin") is False)
for f in ("engine/loki.py", "engine/loki_bridge.py", "studio/studio_server.py", "studio/studio_app.py", "app/loki_app.py"):
    check("%s loads it first" % f, "import no_console" in (REPO / f).read_text(encoding="utf-8")[:4000])
check("ship.py runs this suite", '"test_no_console"' in (REPO / "tools" / "ship.py").read_text(encoding="utf-8"))

# a console-showing launcher an old setup left in Startup is retired, not just avoided
sys.path.insert(0, str(REPO / "app"))
import loki_app  # noqa: E402

startup = Path(tempfile.mkdtemp(prefix="loki-startup-"))
(startup / "LOKI.vbs").write_text("pythonw loki_app.py --background", encoding="utf-8")   # LOKI's own, hidden
(startup / "Loki.lnk").write_bytes("C:/Users/x/loki/Loki.cmd".encode("utf-16-le"))
(startup / "Loki python.lnk").write_bytes("C:/Users/x/loki/.venv/python.exe loki_app.py".encode("utf-16-le"))
(startup / "Other.lnk").write_bytes("C:/Program Files/Other/other.exe".encode("utf-16-le"))
(startup / "Ollama.lnk").write_bytes("C:/Users/x/ollama app.exe".encode("utf-16-le"))
_removed = loki_app.retire_console_launchers(startup)
check("a Startup shortcut to Loki.cmd (a batch = a black console at every logon) is removed",
      "Loki.lnk" in _removed, _removed)
check("LOKI's own hidden login item (LOKI.vbs) is kept", (startup / "LOKI.vbs").is_file())
check("another program's Startup shortcut is left alone",
      (startup / "Other.lnk").is_file() and (startup / "Ollama.lnk").is_file())
check("a shortcut that starts python.exe (a console) for LOKI is removed too",
      (startup / "Loki python.lnk").exists() is False)
check("running it again finds nothing", loki_app.retire_console_launchers(startup) == [])


print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
