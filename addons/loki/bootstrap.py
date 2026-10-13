"""Zero-setup launcher for the Loki bridge.

The dock runs this with whatever Python it can find. It makes sure the harness
dependencies are present in a local virtual environment - creating and
populating one on first run - then hands over to loki_bridge.py using that
interpreter. The user never installs or configures anything by hand.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent
REPO = ADDON_DIR.parent.parent


def _harness_dir() -> Path:
    """The agent code, which ships INSIDE the addon so a project needs nothing else.

    The repo-root fallback keeps an older checkout working, where the code still
    lived in a top-level harness/ folder.
    """
    bundled = ADDON_DIR / "harness"
    if (bundled / "loki.py").is_file():
        return bundled
    legacy = REPO / "harness"
    if (legacy / "loki.py").is_file():
        return legacy
    return bundled


HARNESS = _harness_dir()
# Secrets, memory, plans, downloads and the venv live outside the addon so they are
# never shipped with it, and never get copied into a project.
DATA = REPO / "harness_data"
VENV = DATA / ".venv"
MIN_PYTHON = (3, 11)
REQUIREMENTS = HARNESS / "requirements.txt"
BRIDGE = ADDON_DIR / "loki_bridge.py"
LOG = REPO / ".godot" / "loki_bridge.log"
LOCK = REPO / ".godot" / "loki_bridge.launch"
LOCK_TTL_S = 60


def log(message: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"[loki-setup] {message}\n")
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    """Whether `pid` is a live process. Used to tell a held lock from a stale one."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def release_launch_lock() -> None:
    """Drop the lock if we still own it, so a restart never waits on a dead PID."""
    try:
        if LOCK.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK.unlink()
    except OSError:
        pass


def take_launch_lock() -> bool:
    """Atomically claim the single launch slot; False if someone else holds it.

    Two dock instances exist briefly (this plugin is re-entered on a filesystem
    rescan) and each calls bootstrap, and they can arrive in the same millisecond.
    A plain "does the file exist?" check loses that race, and on Windows the bridge
    does NOT reliably refuse a second bind, so two bridges end up serving one port.
    O_CREAT|O_EXCL is atomic, so exactly one launcher wins. A stale lock (older than
    LOCK_TTL_S) is cleared, so a genuine restart still works.
    """
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # The lock is held only while the launcher that wrote it is alive.
            # A PID check beats a plain TTL because the launcher now runs in the
            # foreground for the bridge's whole life: a first start with MCP
            # servers still downloading easily outlives LOCK_TTL_S, and a second
            # dock-triggered launch then saw a "stale" lock, took it, and served a
            # second bridge on the same port. The TTL remains only as a fallback
            # for a lock whose PID cannot be read.
            try:
                holder = int(LOCK.read_text(encoding="utf-8").strip() or "0")
            except (OSError, ValueError):
                holder = 0
            if holder and _pid_alive(holder):
                return False
            if not holder:
                try:
                    if (time.time() - LOCK.stat().st_mtime) < LOCK_TTL_S:
                        return False
                except OSError:
                    return False
            try:
                LOCK.unlink()
            except OSError:
                return False
            handle = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(handle, "w") as stream:
            stream.write(str(os.getpid()))
        return True
    except OSError:
        # Cannot lock at all (odd permissions): never block the user over it.
        return True


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def deps_ok(python: Path) -> bool:
    if not python.exists():
        return False
    try:
        probe = subprocess.run(
            [str(python), "-c", "import mcp, openai, pydantic"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return probe.returncode == 0
    except OSError:
        return False


def ensure_environment() -> Path | None:
    """Return an interpreter that can run the harness, setting one up if needed."""
    python = venv_python()
    if deps_ok(python):
        return python

    if not python.exists():
        if sys.version_info < MIN_PYTHON:
            # e.g. Apple's /usr/bin/python3 (3.9): a venv built from it can never
            # install the harness deps, and would be preferred on every later launch.
            log("Python %d.%d is too old to build Loki's environment (needs %d.%d+); "
                "install a newer Python 3 (python.org or Homebrew) or run setup.sh"
                % (sys.version_info[:2] + MIN_PYTHON))
            return None
        log(f"creating a private Python environment at {VENV} (one time)")
        try:
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        except Exception as exc:
            log(f"could not create the environment: {exc}")
            return None

    log("installing Loki dependencies (one time; needs internet)")
    try:
        with LOG.open("a", encoding="utf-8") as handle:
            subprocess.run([str(python), "-m", "pip", "install",
                            "--disable-pip-version-check", "-r", str(REQUIREMENTS)],
                           check=False, stdout=handle, stderr=subprocess.STDOUT)
    except Exception as exc:
        log(f"dependency install failed: {exc}")
        return None

    if not deps_ok(python):
        log("dependencies are still missing after install")
        return None
    return python


def main() -> int:
    if not take_launch_lock():
        log("another Loki launch is already in progress; standing down")
        return 0
    python = ensure_environment()
    if python is None and sys.version_info < MIN_PYTHON:
        release_launch_lock()
        return 2
    if python is None:
        log("setup failed; trying the current interpreter anyway")
        python = Path(sys.executable)
    log(f"starting the bridge with {python}")
    # Tell the harness where its data lives; it cannot infer this reliably once the
    # code sits inside the addon.
    os.environ["LOKI_DATA"] = str(DATA)
    try:
        return subprocess.call([str(python), str(BRIDGE)] + sys.argv[1:])
    except KeyboardInterrupt:
        return 0
    finally:
        release_launch_lock()


if __name__ == "__main__":
    raise SystemExit(main())
