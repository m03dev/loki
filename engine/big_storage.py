"""Where LOKI puts anything big - never on the Mac's internal drive.

Owner 2026-10-26: "u crashed my mac with ur voice studio install i told u to move it to xero everything should be in
xero we dont have room". The internal drive was at 91%; 18 GB of it was one model cache (~/.cache/huggingface:
VoiceStudio's OmniVoice and Whisper models among them).

    big_dir()        the external drive Xero (/Volumes/Xero/loki) when it is mounted, else LOKI's data folder on
                     its own drive (<data>/big) - LOKI_BIG_DIR overrides both
    apply(env)       points every downloader LOKI and its tools start at big_dir(): Hugging Face (HF_HOME), PyTorch
                     (TORCH_HOME), pip and uv caches, npm's cache, the Tool Shelf (LOKI_TOOLS_DIR) - set only where
                     the owner has not set them himself
    home_drive_free() bytes free on the internal (home) drive, and low_space() when it is under LOKI_MIN_FREE_GB
                     (default 25): installers refuse to start then, instead of filling the drive

Apps LOKI does not start itself (VoiceStudio.app, Ollama) keep their own folders; for those the folder is moved and a
link left in its place (see docs/STORAGE.md).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

XERO = Path("/Volumes/Xero")


def _data_dir(env: dict | None = None) -> Path:
    explicit = str((env if env is not None else os.environ).get("LOKI_DATA", "") or "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def big_dir(env: dict | None = None) -> Path:
    env = env if env is not None else os.environ
    if str(env.get("LOKI_BIG_DIR") or "").strip():
        return Path(env["LOKI_BIG_DIR"])
    if sys.platform == "darwin" and XERO.is_dir():
        return XERO / "loki"
    return _data_dir(env) / "big"


def apply(env: dict | None = None) -> dict:
    """Set the download locations (only those not set already). Returns what it set."""
    env = env if env is not None else os.environ
    base = big_dir(env)
    wanted = {"HF_HOME": base / "huggingface", "TORCH_HOME": base / "torch", "PIP_CACHE_DIR": base / "pip-cache",
              "UV_CACHE_DIR": base / "uv-cache", "npm_config_cache": base / "npm-cache",
              "LOKI_TOOLS_DIR": base / "tools"}
    done = {}
    for key, path in wanted.items():
        if str(env.get(key) or "").strip():
            continue
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue                    # a drive that is not writable: leave the default
        env[key] = str(path)
        done[key] = str(path)
    return done


def home_drive_free() -> int:
    try:
        return shutil.disk_usage(str(Path.home())).free
    except OSError:
        return 1 << 62


def low_space(env: dict | None = None) -> bool:
    env = env if env is not None else os.environ
    try:
        floor = float(env.get("LOKI_MIN_FREE_GB", "25") or 25)
    except ValueError:
        floor = 25.0
    return home_drive_free() < floor * 1024 ** 3


def install_note(what: str) -> str:
    """The refusal an installer gives when the home drive is low."""
    return ("not installing %s: the internal drive has only %.0f GB free (LOKI keeps %s GB free). Big things go on %s"
            % (what, home_drive_free() / 1024 ** 3, os.environ.get("LOKI_MIN_FREE_GB", "25"), big_dir()))
