"""Folders LOKI's agents may READ besides their own workspace (owner, 2026-10-22: "my agents should have
the tools to check other folders").

Before, every file tool resolved inside the job's workspace (loki.resolve_in_workspace), so an agent
team working in ~/LOKI Projects/Home could not read LOKI's own code, its QA results
(<data>/qa/forge_qa.json) or another project - and made results up. Now the READ tools (read_file,
list_tree, search_files, read_document) and run_command's cwd may also use:

  loki      LOKI's own folder (the install / repo)                          read-only
  data      LOKI's data folder (harness_data, logs, jobs, qa results)       read-only, never the secrets
  projects  every folder under ~/LOKI Projects (LOKI_PROJECTS_DIR)          read-only here
  extra     folders the owner lists: env LOKI_AGENT_FOLDERS (os.pathsep-separated) or the
            "agent_folders" key of <data>/loki_settings.json (a list, or one os.pathsep string)

Writing stays where it was: write/edit/move/delete only inside the workspace (engine/policy.py).
Never readable, wherever they are: secrets (.env, keys.env, private keys, token/secret/credential
files, LOKI's phone and channel pairings, the API vault), VCS internals (.git), credential stores
(~/.ssh, ~/.gnupg, ~/.aws, Keychains ...) and system folders. An extra folder that is (or holds)
one of those is ignored. Pure functions; no LOKI import (tests/test_agent_folders.py).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SECRET_NAMES = {
    ".env", "keys.env", ".netrc", "_netrc", ".npmrc", ".pypirc", ".git-credentials", ".pgpass",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "authorized_keys", "known_hosts",
    "api_vault_extra.json", "phones.json", "credentials", "credentials.json", "client_secret.json",
    "service_account.json", "token.json", "tokens.json", "secrets.json", "secrets.yaml", "secrets.yml",
}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk", ".kdbx", ".keychain",
                   ".keychain-db", ".gpg", ".asc", ".env"}
SECRET_WORDS = re.compile(r"secret|credential|passw(or)?d|(^|[._-])tokens?([._-]|$)|api[_-]?keys?([._-]|$)", re.I)
SECRET_DIRS = {".git", ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".loki", "keychains", "gcloud"}
# Inside LOKI's data folder: the pairings (signing keys, bot owners) are secret too.
DATA_SECRET_DIRS = {"phone", "channels"}
# Not searched (huge or not code): search_files and list_tree skip these outside the workspace.
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".godot", "pw-browsers"}
SEARCH_MAX_BYTES = 2_000_000


def projects_dir(env=None) -> Path:
    env = os.environ if env is None else env
    raw = str(env.get("LOKI_PROJECTS_DIR") or "").strip()
    return Path(os.path.expanduser(raw)) if raw else Path.home() / "LOKI Projects"


def _system_folders(env=None) -> list:
    """Folders no agent reads, whatever the settings say: the OS and the credential stores."""
    env = os.environ if env is None else env
    home = Path.home()
    out = [home / ".ssh", home / ".gnupg", home / ".aws", home / ".azure", home / ".kube", home / ".docker",
           home / ".loki", home / ".config" / "gcloud", home / "Library" / "Keychains"]
    if sys.platform == "win32":
        for key, default in (("SystemRoot", r"C:\Windows"), ("ProgramFiles", r"C:\Program Files"),
                             ("ProgramFiles(x86)", r"C:\Program Files (x86)"), ("ProgramData", r"C:\ProgramData")):
            out.append(Path(str(env.get(key) or default)))
        out.append(home / "AppData" / "Roaming" / "Microsoft" / "Credentials")
        out.append(home / "AppData" / "Local" / "Microsoft" / "Credentials")
    else:
        out += [Path(p) for p in ("/etc", "/System", "/Library", "/usr", "/bin", "/sbin", "/dev", "/proc", "/sys",
                                  "/boot", "/root", "/private/etc", "/private/var/db", "/var/db", "/var/root")]
    return out


def _resolved(path: Path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except (OSError, RuntimeError):
        return Path(os.path.abspath(os.path.expanduser(str(path))))


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def blocked(path: Path, env=None) -> str:
    """Why a path may never be read by an agent ('' when it may)."""
    p = _resolved(path)
    for sys_dir in _system_folders(env):
        if _within(p, _resolved(sys_dir)):
            return "%s is a system or credential folder" % sys_dir
    return ""


def secret_name(rel: Path) -> bool:
    """True when a path (relative to a readable folder) names keys, tokens, passwords, private keys or
    .git internals: any part of it counts."""
    for part in Path(rel).parts:
        low = part.lower()
        if low in SECRET_DIRS or low in SECRET_NAMES or low.startswith(".env") \
                or Path(low).suffix in SECRET_SUFFIXES or SECRET_WORDS.search(part):
            return True
    return False


def is_secret(path: Path, root: Path | None = None, data_dir: Path | None = None) -> bool:
    """secret_name() for the part of `path` below `root` (all of it when no root), plus LOKI's pairings
    (<data>/phone, <data>/channels)."""
    p = _resolved(path)
    if root is not None and _within(p, _resolved(root)):
        rel = p.relative_to(_resolved(root))
    else:
        rel = Path(*p.parts[1:]) if len(p.parts) > 1 else Path(p.name)
    if secret_name(rel):
        return True
    if data_dir is not None:
        rd = _resolved(data_dir)
        if _within(p, rd) and p != rd and p.relative_to(rd).parts[0].lower() in DATA_SECRET_DIRS:
            return True
    return False


def extra_folders(env=None, settings_file: Path | None = None) -> list:
    """The owner's extra folders: LOKI_AGENT_FOLDERS plus settings "agent_folders"."""
    env = os.environ if env is None else env
    raw = [p for p in str(env.get("LOKI_AGENT_FOLDERS") or "").split(os.pathsep) if p.strip()]
    if settings_file is not None:
        try:
            value = json.loads(Path(settings_file).read_text(encoding="utf-8")).get("agent_folders")
        except (OSError, ValueError, AttributeError):
            value = None
        if isinstance(value, str):
            raw += [p for p in value.split(os.pathsep) if p.strip()]
        elif isinstance(value, list):
            raw += [str(p) for p in value if str(p).strip()]
    out = []
    for item in raw:
        p = _resolved(Path(item.strip()))
        if not p.is_dir() or p.parent == p or p == _resolved(Path.home()) or blocked(p, env):
            continue          # a drive, the whole home folder or a system/credential folder: never
        if any(_within(_resolved(s), p) for s in _system_folders(env)):
            continue          # a folder that HOLDS ~/.ssh and the like
        if p not in out:
            out.append(p)
    return out


def roots(repo: Path, data_dir: Path, env=None, settings_file: Path | None = None) -> list:
    """[(label, folder)] an agent may read besides its workspace, in that order."""
    out = [("loki", _resolved(repo)), ("data", _resolved(data_dir)), ("projects", _resolved(projects_dir(env)))]
    out += [("extra", p) for p in extra_folders(env, settings_file)]
    seen, unique = set(), []
    for label, p in out:
        if p not in seen:
            seen.add(p)
            unique.append((label, p))
    return unique


def resolve_readable(name: str, workspace: Path, folders: list, data_dir: Path | None = None,
                     env=None) -> Path:
    """The path to READ: inside the workspace (as before), or inside one of `folders` and not a secret.

    A relative name is taken from the workspace; an absolute (or ~) one stands for itself. Raises
    ValueError with the reason otherwise."""
    cleaned = str(name).strip().strip('"').strip("'").strip()
    for prefix in ("res://", "res:/", "./"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    ws = _resolved(workspace)
    raw = Path(os.path.expanduser(cleaned)) if cleaned else Path(".")
    path = _resolved(raw if raw.is_absolute() else ws / raw)
    if _within(path, ws):
        return path
    why = blocked(path, env)
    if why:
        raise ValueError("refused: %s" % why)
    for _label, root in folders:
        if _within(path, root):
            if is_secret(path, root, data_dir):
                raise ValueError("refused: %s is a secret (keys, tokens, passwords) - agents never read those" % name)
            return path
    raise ValueError("path escapes workspace and the readable folders (call folders to list them): %s" % name)


def outside(path: Path, workspace: Path) -> bool:
    return not _within(_resolved(path), _resolved(workspace))


def show(path: Path, workspace: Path) -> str:
    """A path as the agent should write it back: relative inside the workspace, else absolute."""
    p, ws = _resolved(path), _resolved(workspace)
    return p.relative_to(ws).as_posix() if _within(p, ws) and p != ws else str(p)


def describe(workspace: Path, folders: list, python: str = "") -> str:
    """The short prompt section / folders tool text."""
    names = {"loki": "LOKI's own folder (code, tools/, tests/, docs/)",
             "data": "LOKI's data folder (logs, jobs/, qa/ results; secrets hidden)",
             "projects": "LOKI Projects (every project of the owner)", "extra": "the owner's extra folder"}
    lines = ["# Folders you can read",
             "Your workspace (read + write): %s" % _resolved(workspace),
             "Read-only, with read_file / list_tree / search_files / read_document and an ABSOLUTE path:"]
    for label, root in folders:
        lines.append("- %s: %s" % (names.get(label, label), root))
    loki = next((r for lab, r in folders if lab == "loki"), None)
    if loki is not None:
        lines.append("Run LOKI's own tools with run_command, e.g. command='%s %s' cwd='%s'. Writing outside "
                     "the workspace is refused; secret files (.env, keys, tokens) are never readable."
                     % (python or "python", Path(loki, "tools", "forge_qa.py"), loki))
    return "\n".join(lines)
