"""After an update the old copy of the app always goes (app/loki_app.py leave_soon; owner 2026-10-25: "update ...
needs to close the launcher after it updates - sometimes it does, sometimes it doesn't").

The cause: the exit timer was started AFTER close_window(), and closing a pywebview window from a worker thread can
hang on macOS - then the timer never started and the old window stayed. Now the timer starts first: even with a
close that hangs forever, the process exits. Every update / relaunch / quit path does it in that order. Under a minute.

    python tests/test_app_leave.py
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app"))
os.environ.pop("LOKI_APP_TEST", None)
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


import loki_app  # noqa: E402

exits = []
loki_app.os._exit = lambda code: exits.append(code)          # record instead of exiting this test


class Hangs:
    def destroy(self):
        threading.Event().wait()                              # Cocoa from a worker thread: never returns


loki_app.WINDOW["window"] = Hangs()


def update_path():
    loki_app.leave_soon(0, 0.2)
    loki_app.close_window()                                   # hangs forever


threading.Thread(target=update_path, daemon=True).start()
time.sleep(0.6)
check("the window close hangs, yet the app exits (the timer was started first)", exits == [0], exits)

src = (REPO / "app" / "loki_app.py").read_text(encoding="utf-8")
blocks = re.findall(r"leave_soon\([^)]*\)[^\n]*\n\s*close_window\(\)", src)
check("every update / relaunch / quit path starts the exit before closing the window (4 places)", len(blocks) == 4, len(blocks))
check("no exit timer is started after a close any more", not re.search(r"close_window\(\)\s*\n\s*if os\.environ\.get\(\"LOKI_APP_TEST\"", src))
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
