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
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent
REPO = ADDON_DIR.parent.parent
HARNESS = REPO / "harness"
VENV = HARNESS / ".venv"
REQUIREMENTS = HARNESS / "requirements.txt"
BRIDGE = ADDON_DIR / "loki_bridge.py"
LOG = REPO / ".godot" / "loki_bridge.log"


def log(message: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"[loki-setup] {message}\n")
    except OSError:
        pass


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
    python = ensure_environment()
    if python is None:
        log("setup failed; trying the current interpreter anyway")
        python = Path(sys.executable)
    log(f"starting the bridge with {python}")
    try:
        return subprocess.call([str(python), str(BRIDGE)] + sys.argv[1:])
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
