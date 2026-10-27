"""Nothing LOKI needs is ever missing (owner 2026-10-26: "make sure there are no missing dependencies and loki
installs whatever it needs").

The updater installs engine/requirements.txt and app/requirements.txt only when the files CHANGE between versions,
so one failed pip run (offline, a full disk, a sign-in) left a package missing for good - the Mac ran without
gradio_client that way and its online 3D fell back to a flat lift. This runs once at every start, in the background:
it reads both files, asks importlib.metadata which requirements are not installed (or too old), and pip-installs only
those into LOKI's own Python. Nothing is removed or downgraded; a failure is reported in status() (Settings > System
check / GET /health) and tried again at the next start, never in a loop.

    python engine/deps_check.py          what is missing on this computer (installs nothing)
    python engine/deps_check.py install  install what is missing

Standard library only. LOKI_DEPS_CHECK=off turns the start-up install off.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FILES = ("engine/requirements.txt", "app/requirements.txt")
STATE: dict = {"checked": 0.0, "missing": [], "installed": [], "failed": "", "running": False}
_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(?:>=\s*([0-9][0-9a-zA-Z.]*))?")


def requirements(repo: Path | None = None) -> list:
    """[(line, name, min_version or "")] from LOKI's requirement files (comments, markers and blank lines skipped)."""
    out = []
    for rel in FILES:
        path = Path(repo or REPO) / rel
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            if ";" in line:   # an environment marker: pip decides; only check it where it applies
                req, marker = line.split(";", 1)
                if "darwin" in marker and sys.platform != "darwin" or "win32" in marker and sys.platform != "win32":
                    continue
                line = req.strip()
            m = _REQ.match(line)
            if m:
                out.append((line, m.group(1), m.group(3) or ""))
    return out


def _vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def missing(repo: Path | None = None) -> list:
    """The requirement lines that are not installed here, or older than their >= version."""
    out = []
    for line, name, low in requirements(repo):
        try:
            have = metadata.version(name)
        except metadata.PackageNotFoundError:
            out.append(line)
            continue
        except Exception:  # noqa: BLE001 - a broken install record: let pip look at it
            out.append(line)
            continue
        if low and _vtuple(have) < _vtuple(low):
            out.append(line)
    return out


def install(lines: list, python: str = "", timeout: float = 900.0) -> tuple:
    """(ok, text) - pip install exactly these requirement lines into LOKI's Python."""
    if not lines:
        return True, "nothing to install"
    python = python or os.getenv("LOKI_ENGINE_PYTHON") or sys.executable
    cmd = [python, "-m", "pip", "install", "-q", "--disable-pip-version-check", *lines]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    text = " ".join((proc.stdout + proc.stderr).split())[-600:]
    return proc.returncode == 0, text or "installed"


def check_and_install(repo: Path | None = None, run=install) -> dict:
    STATE.update(running=True, failed="")
    try:
        need = missing(repo)
        STATE["missing"] = need
        if need:
            ok, text = run(need)
            if ok:
                STATE["installed"] = need
                STATE["missing"] = missing(repo)
            else:
                STATE["failed"] = text
        STATE["checked"] = time.time()
        return status()
    finally:
        STATE["running"] = False


def status() -> dict:
    return {"ok": not STATE["missing"] and not STATE["failed"], **{k: v for k, v in STATE.items()}}


def start_background(repo: Path | None = None, delay_s: float = 20.0) -> bool:
    """At engine start: after the window is up, once. False when turned off."""
    if str(os.getenv("LOKI_DEPS_CHECK", "on")).strip().lower() in ("0", "off", "no", "false"):
        return False

    def go() -> None:
        time.sleep(delay_s)
        try:
            result = check_and_install(repo)
            if result.get("installed") or result.get("failed"):
                print("[loki-deps] %s" % ("installed: " + ", ".join(result["installed"]) if result.get("installed")
                                         else "could not install %s: %s" % (", ".join(result["missing"]), result["failed"])), flush=True)
        except Exception as exc:  # noqa: BLE001 - never takes the engine down
            STATE["failed"] = str(exc)

    threading.Thread(target=go, name="loki-deps", daemon=True).start()
    return True


if __name__ == "__main__":
    if sys.argv[1:2] == ["install"]:
        print(check_and_install())
    else:
        need = missing()
        print("nothing missing" if not need else "missing: " + ", ".join(need))
