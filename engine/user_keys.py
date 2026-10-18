"""Your keys, saved for YOU (this computer's user account), not for one copy of LOKI.

Owner, 2026-10-18: "why arnt my api keys saving ... it needs to save per user". Keys used to live
only in harness_data/.env inside one checkout - a reinstall, a moved drive, a new checkout, a job's
worktree or LOKI Studio's pinned copy each had their own harness_data, so a key typed once looked
"forgotten" elsewhere. Now every key is ALSO kept in one per-user file:

    macOS / Linux   ~/.loki/keys.env          (mode 600)
    Windows         %USERPROFILE%\\.loki\\keys.env

Every LOKI process on this account loads it (the engine, Studio, jobs). A key in a checkout's own
.env still wins, and a key saved there is copied here, so nothing already working changes.
Keys never leave this computer: they are not synced to other machines or committed anywhere.
LOKI_USER_KEYS points somewhere else (tests).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Names that are secrets about the PERSON (provider accounts), not about one machine or checkout.
# LOKI_PEER_SECRET and other LOKI_* settings stay per checkout on purpose.
_KEY_NAME = re.compile(r"^(?!LOKI_)[A-Z][A-Z0-9_]*(_API_KEY|_API_TOKEN|_ACCOUNT_ID)$|^(HF_TOKEN|GITHUB_TOKEN|GOOGLE_REFRESH_TOKEN)$")


def is_key(name: str) -> bool:
    return bool(_KEY_NAME.match(str(name or "").strip()))


def path() -> Path:
    custom = os.environ.get("LOKI_USER_KEYS", "").strip()
    if custom:
        return Path(custom)
    home = Path(os.environ.get("USERPROFILE") or Path.home()) if sys.platform == "win32" else Path.home()
    return home / ".loki" / "keys.env"


def read(where: Path | None = None) -> dict:
    """{NAME: value} of the saved keys (only non-empty key names)."""
    out: dict = {}
    try:
        lines = Path(where or path()).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if is_key(name) and value:
            out[name] = value
    return out


def _write(values: dict, where: Path | None = None) -> bool:
    target = Path(where or path())
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        body = ("# LOKI keys for this user account (engine/user_keys.py). Every copy of LOKI on this computer\n"
                "# uses them. Never commit or share this file.\n"
                + "".join("%s=%s\n" % (k, v) for k, v in sorted(values.items())))
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        if sys.platform != "win32":
            os.chmod(tmp, 0o600)
        os.replace(tmp, target)
        return True
    except OSError:
        return False


def update(changes: dict, where: Path | None = None) -> bool:
    """Save (value) or forget (None / "") keys. Names that are not keys are ignored."""
    changes = {k: v for k, v in (changes or {}).items() if is_key(k)}
    if not changes:
        return True
    current = read(where)
    before = dict(current)
    for name, value in changes.items():
        value = "" if value is None else str(value).strip()
        if value:
            current[name] = value
        else:
            current.pop(name, None)
    return True if current == before else _write(current, where)


def load_into(environ=None, where: Path | None = None) -> list:
    """Put saved keys into the environment where nothing set them yet. Returns the names loaded."""
    environ = os.environ if environ is None else environ
    loaded = []
    for name, value in read(where).items():
        if not str(environ.get(name, "") or "").strip():
            environ[name] = value
            loaded.append(name)
    return loaded


def adopt(env_file: Path, where: Path | None = None) -> list:
    """Copy keys a checkout's .env already has into the per-user file (once; never overwrites)."""
    try:
        lines = Path(env_file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    saved = read(where)
    new = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if is_key(name) and value and name not in saved:
            new[name] = value
    if new:
        update(new, where)
    return sorted(new)
