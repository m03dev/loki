"""Two tools the agent was missing (owner 2026-10-25: "is it calling out tools? to read and write files and use
gitbash and itch.io").

  bash   a real shell: pipes, redirects, globs, `&&`, `$(...)`. That is Git Bash on Windows, so the same commands
         work on the Mac and on Windows. run_command stays the no-shell, argv-only runner. bash goes through the
         same command policy (loki.command_policy), the OpenHands risk analyzer (HIGH always asks a human, and is
         refused in an unattended job) and approval, because it is in loki.DANGEROUS.
  itch   itch.io through butler, itch's own command-line uploader:
           version              is butler there, and which version
           login                is there a key (BUTLER_API_KEY, or butler's saved credentials)? It says how to add one.
           status  target       the channels and builds of user/game
           push    path target  upload a folder or zip to user/game:channel (optional userversion). Always asks.
           install              download butler from itch's broth server into LOKI's data folder. Always asks.

Finding things, the same way on every system:
  bash    LOKI_BASH, then Git for Windows next to `git` (Git\\bin\\bash.exe, never WSL's System32\\bash.exe), the usual
          Git install folders, then bash on PATH, then /bin/bash.
  butler  LOKI_BUTLER, butler on PATH, LOKI's own copy (<data>/bin/butler), then the itch app's copy
          (~/Library/Application Support/itch/apps/butler, %APPDATA%\\itch\\apps\\butler, ~/.config/itch/apps/butler).
Standard library only. The functions return the text the model reads ("exit N" + output, or "error: ...").
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

NO_WINDOW = 0x08000000 if os.name == "nt" else 0      # CREATE_NO_WINDOW: no console flashes up on Windows
TARGET_RE = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+(:[A-Za-z0-9._-]+)?$")


# ------------------------------------------------------------------ bash
def find_bash(env: dict | None = None, platform: str | None = None, exists: Callable[[str], bool] = os.path.isfile,
              which: Callable[[str], str | None] = shutil.which) -> str:
    """The bash to run commands in, or "" when there is none."""
    env = os.environ if env is None else env
    platform = platform or sys.platform
    own = str(env.get("LOKI_BASH", "") or "").strip()
    if own and exists(own):
        return own
    if platform == "win32":
        tries = []
        git = which("git")
        if git:
            root = Path(git).resolve().parent.parent          # ...\Git\cmd\git.exe -> ...\Git
            tries += [str(root / "bin" / "bash.exe"), str(root.parent / "bin" / "bash.exe")]
        for base in (env.get("ProgramFiles", r"C:\Program Files"), env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.path.join(env.get("LOCALAPPDATA", ""), "Programs") if env.get("LOCALAPPDATA") else ""):
            if base:
                tries.append(os.path.join(base, "Git", "bin", "bash.exe"))
        for t in tries:
            if exists(t):
                return t
        found = which("bash") or ""
        if found and "system32" not in found.lower():      # System32\bash.exe is WSL: another machine, other paths
            return found
        return ""
    found = which("bash") or ""
    if found:
        return found
    return "/bin/bash" if exists("/bin/bash") else ""


def run_bash(command: str, cwd: str, timeout: int = 120, bash_path: str = "") -> tuple:
    """(exit code, output) of `command` in bash, in folder cwd. Raises FileNotFoundError when there is no bash."""
    sh = bash_path or find_bash()
    if not sh:
        raise FileNotFoundError("no bash here - on Windows install Git for Windows (git-scm.com, it brings Git Bash) "
                                "or set LOKI_BASH to bash.exe")
    env = dict(os.environ)
    env.setdefault("CHERE_INVOKING", "1")                # Git Bash: stay in cwd
    env.setdefault("GIT_TERMINAL_PROMPT", "0")           # git never waits for a password nobody can type
    env.setdefault("GIT_PAGER", "cat"); env.setdefault("PAGER", "cat")
    proc = subprocess.run([sh, "-c", command], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=max(1, int(timeout)), stdin=subprocess.DEVNULL, env=env,
                          creationflags=NO_WINDOW)
    out = ((proc.stdout or "") + (("\n" if proc.stdout and proc.stderr else "") + (proc.stderr or ""))).strip()
    return proc.returncode, out


# ------------------------------------------------------------------ itch.io / butler
def butler_candidates(data_dir: str = "", env: dict | None = None, platform: str | None = None) -> list:
    env = os.environ if env is None else env
    platform = platform or sys.platform
    exe = "butler.exe" if platform == "win32" else "butler"
    home = Path(env.get("HOME") or env.get("USERPROFILE") or Path.home())
    out = []
    if env.get("LOKI_BUTLER"):
        out.append(env["LOKI_BUTLER"])
    if data_dir:
        out.append(str(Path(data_dir) / "bin" / exe))
    if platform == "darwin":
        out.append(str(home / "Library" / "Application Support" / "itch" / "apps" / "butler" / exe))
    elif platform == "win32":
        if env.get("APPDATA"):
            out.append(str(Path(env["APPDATA"]) / "itch" / "apps" / "butler" / exe))
    else:
        out.append(str(home / ".config" / "itch" / "apps" / "butler" / exe))
    return out


def find_butler(data_dir: str = "", env: dict | None = None, platform: str | None = None,
                exists: Callable[[str], bool] = os.path.isfile, which: Callable[[str], str | None] = shutil.which) -> str:
    cands = butler_candidates(data_dir, env, platform)
    if cands and (env or os.environ).get("LOKI_BUTLER") and exists(cands[0]):
        return cands[0]
    found = which("butler")
    if found:
        return found
    for c in cands:
        if exists(c):
            return c
    return ""


def broth_channel(platform: str | None = None, machine: str = "") -> str:
    """butler's download channel on itch's broth server for this system."""
    platform = platform or sys.platform
    import platform as _pf
    machine = (machine or _pf.machine() or "").lower()
    if platform == "win32":
        return "windows-amd64" if machine in ("amd64", "x86_64", "arm64") else "windows-386"
    if platform == "darwin":
        return "darwin-amd64"                             # a universal-enough build; Apple silicon runs it via Rosetta
    return "linux-amd64"


def butler_logged_in(env: dict | None = None, platform: str | None = None) -> str:
    """Where butler's key comes from: "BUTLER_API_KEY", "saved credentials", or ""."""
    env = os.environ if env is None else env
    if str(env.get("BUTLER_API_KEY", "") or "").strip():
        return "BUTLER_API_KEY"
    platform = platform or sys.platform
    home = Path(env.get("HOME") or env.get("USERPROFILE") or Path.home())
    if platform == "darwin":
        creds = home / "Library" / "Application Support" / "itch" / "butler_creds"
    elif platform == "win32":
        creds = Path(env.get("APPDATA", str(home))) / "itch" / "butler_creds"
    else:
        creds = home / ".config" / "itch" / "butler_creds"
    return "saved credentials" if creds.is_file() else ""


def itch(action: str, target: str = "", path: str = "", userversion: str = "", *, data_dir: str = "",
         resolve_path: Callable[[str], Path] | None = None, timeout: int = 600, shorten: Callable[[str], str] = lambda s: s) -> str:
    action = str(action or "").strip().lower()
    butler = find_butler(data_dir)
    if action == "install":
        if butler:
            return "butler is already here: %s" % butler
        return install_butler(data_dir)
    if action == "login":
        how = butler_logged_in()
        if how:
            return "itch.io: logged in through %s." % how + ("" if butler else " butler itself is not installed yet: itch action=install.")
        return ("itch.io: no key yet. Make one at https://itch.io/user/settings/api-keys and add it as BUTLER_API_KEY "
                "(Settings > Connections > API keys), or run `butler login` once in a terminal.")
    if not butler:
        return ("error: butler (itch.io's uploader) is not installed. Run itch with action=install (it asks first), "
                "or install it from https://itch.io/docs/butler/installing.html, or set LOKI_BUTLER.")
    if action == "version":
        return _butler([butler, "-V"], timeout=30, shorten=shorten)
    if action == "status":
        if not TARGET_RE.match(target or ""):
            return "error: target must be user/game (for example mohamed/my-game)"
        return _butler([butler, "status", target], timeout=60, shorten=shorten)
    if action == "push":
        if not TARGET_RE.match(target or "") or ":" not in target:
            return "error: target must be user/game:channel (for example mohamed/my-game:windows)"
        if not path:
            return "error: path to the build folder or .zip is needed"
        where = resolve_path(path) if resolve_path else Path(path)
        if not where.exists():
            return "error: no such build: %s" % path
        if not butler_logged_in():
            return "error: itch.io is not logged in - itch action=login says how"
        cmd = [butler, "push", str(where), target]
        if userversion:
            cmd += ["--userversion", str(userversion)[:60]]
        return _butler(cmd, timeout=timeout, shorten=shorten)
    return "error: action must be version, login, status, push or install"


def _butler(cmd: list, timeout: int, shorten: Callable[[str], str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return "error: butler timed out after %ss" % timeout
    except OSError as exc:
        return "error: could not run butler: %s" % exc
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return ("exit %d\n%s" % (proc.returncode, shorten(out))) if out else "exit %d" % proc.returncode


def install_butler(data_dir: str, channel: str = "", fetch: Callable[[str], bytes] | None = None) -> str:
    """Download butler from itch's broth server into <data>/bin (the documented way to get it without the itch app)."""
    if not data_dir:
        return "error: no data folder to install into"
    channel = channel or broth_channel()
    urls = ["https://broth.itch.zone/butler/%s/LATEST/archive/default" % channel,
            "https://broth.itch.ovh/butler/%s/LATEST/archive/default" % channel]
    fetch = fetch or (lambda u: urllib.request.urlopen(u, timeout=60).read())   # noqa: S310 - fixed https hosts
    last = ""
    for url in urls:
        try:
            blob = fetch(url)
            break
        except Exception as exc:  # noqa: BLE001 - try the other host, then report
            last = str(exc)[:200]
    else:
        return "error: could not download butler (%s). Install it by hand: https://itch.io/docs/butler/installing.html" % last
    dest = Path(data_dir) / "bin"
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for name in z.namelist():
                base = os.path.basename(name)
                if not base:
                    continue
                if base.startswith(("butler", "7z", "c7zip", "libc7zip")):
                    (dest / base).write_bytes(z.read(name))
                    if os.name != "nt":
                        os.chmod(dest / base, 0o755)
    except zipfile.BadZipFile:
        return "error: the butler download was not a zip"
    exe = dest / ("butler.exe" if sys.platform == "win32" else "butler")
    return ("butler installed: %s (itch action=login next)" % exe) if exe.is_file() else "error: butler was not in the download"
