"""One heavy job at a time on this computer, and never when memory is short (owner 2026-10-26, the Mac mini 16 GB:
"you crashed my computer ... you used all my vram"). That night LOKI ran, at the same time: an agent team trying a local
FLUX.2 model through mflux (~8 GB), the asset pipeline's Blender polish + renders, and other agents' pictures - all in the
Mac's one shared (unified) memory.

    with heavy.slot("blender polish"):   ...     waits for the machine-wide slot (a lock file in harness_data/), then
                                                  for enough free memory; raises Busy when it waited too long
    heavy.busy() -> "what holds it" | ""          for schedulers (the autopilot, the asset pipeline) to not even start
    heavy.available_gb() -> float | None          free memory now (macOS vm_stat, Linux MemAvailable, Windows API)

A slot is per process and re-entrant inside it (a stage that calls a tool that also asks for it does not deadlock).
A lock left by a process that died, or older than STALE_S, is taken over. Plain standard library.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

STALE_S = 2 * 3600
_LOCAL = threading.local()
_PROC_LOCK = threading.Lock()


class Busy(RuntimeError):
    pass


def lock_path() -> Path:
    return Path(os.environ.get("LOKI_DATA") or (Path(__file__).resolve().parent.parent / "harness_data")) / "heavy.lock"


def total_gb() -> float:
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout
            return int(out.strip()) / 2**30
        if sys.platform.startswith("linux"):
            for ln in Path("/proc/meminfo").read_text().splitlines():
                if ln.startswith("MemTotal:"):
                    return int(ln.split()[1]) / 2**20
        if sys.platform == "win32":
            st = _win_mem()
            return st.ullTotalPhys / 2**30 if st else 0.0
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def _win_mem():
    import ctypes  # pylint: disable=import-outside-toplevel

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    st = MS()
    st.dwLength = ctypes.sizeof(MS)
    return st if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)) else None


def available_gb(vm_stat: str | None = None) -> float | None:
    """Free memory now, in GB (None when it cannot be read). macOS: free + inactive + speculative pages."""
    try:
        if sys.platform == "darwin" or vm_stat is not None:
            text = vm_stat if vm_stat is not None else subprocess.run(["vm_stat"], capture_output=True, text=True,
                                                                        timeout=5).stdout
            page = int((re.search(r"page size of (\d+)", text) or [0, 16384])[1])
            pages = 0
            for key in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"):
                m = re.search(r"%s:\s+(\d+)" % key, text)
                pages += int(m.group(1)) if m else 0
            return round(pages * page / 2**30, 2)
        if sys.platform.startswith("linux"):
            for ln in Path("/proc/meminfo").read_text().splitlines():
                if ln.startswith("MemAvailable:"):
                    return round(int(ln.split()[1]) / 2**20, 2)
        if sys.platform == "win32":
            st = _win_mem()
            return round(st.ullAvailPhys / 2**30, 2) if st else None
    except Exception:  # noqa: BLE001
        return None
    return None


def min_free_gb() -> float:
    """The memory a heavy job needs free before it starts: LOKI_HEAVY_MIN_FREE_GB, else 5 GB on a machine with 16 GB
    or less (the Mac mini), else 3 GB."""
    env = os.environ.get("LOKI_HEAVY_MIN_FREE_GB")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    t = total_gb()
    return 5.0 if 0 < t <= 17 else 3.0


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid], capture_output=True, text=True, timeout=5).stdout
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def holder() -> dict:
    try:
        return json.loads(lock_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def busy() -> str:
    """What holds the heavy slot (another live process), or "" - this process's own hold does not count."""
    h = holder()
    if not h:
        return ""
    if int(h.get("pid") or 0) == os.getpid():
        return ""
    if not _alive(int(h.get("pid") or 0)) or time.time() - float(h.get("t") or 0) > STALE_S:
        return ""
    return "%s (pid %s, %ds)" % (h.get("what", "?"), h.get("pid"), int(time.time() - float(h.get("t") or 0)))


def _try_take(what: str) -> bool:
    p = lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    h = holder()
    if h and int(h.get("pid") or 0) != os.getpid() and _alive(int(h.get("pid") or 0)) \
            and time.time() - float(h.get("t") or 0) <= STALE_S:
        return False
    if h:                                  # stale or ours from before: take it over
        try:
            p.unlink()
        except OSError:
            pass
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"pid": os.getpid(), "what": what[:120], "t": time.time()}, fh)
    return True


@contextlib.contextmanager
def slot(what: str, wait_s: float = 1800, poll_s: float = 5.0, sleep=time.sleep, clock=time.time,
         free=None, need_gb: float | None = None):
    """Hold the machine's heavy slot while the body runs. Re-entrant per process."""
    depth = getattr(_LOCAL, "depth", 0)
    if depth or os.environ.get("LOKI_HEAVY", "on") == "off":
        _LOCAL.depth = depth + 1
        try:
            yield
        finally:
            _LOCAL.depth -= 1
        return
    end = clock() + wait_s
    need = min_free_gb() if need_gb is None else need_gb
    free = free or available_gb
    with _PROC_LOCK:
        while True:
            if _try_take(what):
                gb = free()
                if gb is None or gb >= need:
                    break
                try:                       # not enough memory: let go, wait, try again
                    lock_path().unlink()
                except OSError:
                    pass
                why = "only %.1f GB free (needs %.1f GB)" % (gb, need)
            else:
                why = "busy with " + (busy() or "another job")
            if clock() >= end:
                raise Busy("%s did not start: %s" % (what, why))
            sleep(poll_s)
    _LOCAL.depth = 1
    try:
        yield
    finally:
        _LOCAL.depth = 0
        h = holder()
        if int(h.get("pid") or 0) == os.getpid():
            try:
                lock_path().unlink()
            except OSError:
                pass
