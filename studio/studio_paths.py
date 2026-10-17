"""Where LOKI Studio runs from, and what it works on.

Studio usually runs from its PINNED copy (a git worktree of LOKI at the last known-good commit,
harness_data/studio/pinned - see pin.py), so a bad LOKI commit cannot break the tool that fixes
it. What it WORKS ON is always the owner's LOKI checkout (LOKI_STUDIO_REPO, set by the launcher
before it hands over to the pinned copy) and that checkout's data folder (LOKI_DATA).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # this copy's studio/
CODE = HERE.parent                               # this copy of LOKI (pinned, or the checkout itself)
ENGINE = CODE / "engine"                         # engine modules Studio uses as a library
UI = HERE / "ui"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))


def repo() -> Path:
    """The LOKI checkout Studio develops, starts and rolls back (never the pinned copy)."""
    return Path(os.getenv("LOKI_STUDIO_REPO") or CODE).resolve()


def data() -> Path:
    return Path(os.getenv("LOKI_DATA") or (repo() / "harness_data")).resolve()


def studio_data() -> Path:
    path = data() / "studio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def engine_python(base: Path | None = None) -> str:
    """LOKI's private Python (setup.sh / setup.bat make it), else this interpreter."""
    root = base or data()
    for candidate in (root / ".venv" / "bin" / "python3", root / ".venv" / "bin" / "python",
                      root / ".venv" / "Scripts" / "python.exe"):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def load_env_file(path: Path | None = None) -> None:
    """Provider keys from LOKI's .env into this process (never logged, never shown). Values already
    in the environment win."""
    path = path or (data() / ".env")
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")
