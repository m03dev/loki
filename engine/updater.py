"""Keep every machine on the same LOKI: GitHub's `master` is the one version.

The Mac and the PC must never drift apart. Each LOKI updates itself from GitHub:

  - when the app starts (before the engine starts, so the new code runs at once);
  - while it runs, it checks every LOKI_UPDATE_EVERY_S seconds (default 30 min) and when a
    linked machine reports a different version, and tells you an update is waiting (a
    running engine never swaps its own code; the next start applies it).

An update is a fast-forward only. It never overwrites your work: if this checkout has
uncommitted changes to tracked files, or commits that are not on GitHub yet, it stops and
says so (commit and push them with tools/ship.py first). A folder that is a plain copy with
no git history (how the Mac's copy started) is turned into a checkout in place: the files
stay, missing ones are restored, and nothing is deleted.

Publishing goes the other way through tools/ship.py: test, commit, push, then tell the
linked machines to update. Set LOKI_AUTO_UPDATE=0 to turn automatic updates off.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPO_URL = os.getenv("LOKI_REPO_URL", "https://github.com/m03dev/loki.git")
BRANCH = os.getenv("LOKI_BRANCH", "master")
OLD_BRANCHES = ("macos-app", "integrate")   # branches older checkouts may still be on

STATE = {"checked": 0.0, "current": "", "latest": "", "behind": 0, "ahead": 0, "dirty": [],
         "updated_to": "", "update_available": False, "note": "", "error": ""}
_lock = threading.Lock()


def enabled() -> bool:
    return str(os.getenv("LOKI_AUTO_UPDATE", "1")).strip().lower() not in ("0", "false", "off", "no")


def git_exe() -> str:
    return shutil.which("git") or ""


def git(repo: Path, *args: str, timeout: float = 60.0) -> tuple:
    """(returncode, stdout+stderr) of one git command; never raises."""
    exe = git_exe()
    if not exe:
        return 127, "git is not installed"
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="", LC_ALL="C")
    try:
        proc = subprocess.run([exe, "-C", str(repo), *args], capture_output=True, text=True,
                              timeout=timeout, env=env)
        return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).rstrip()
    except subprocess.TimeoutExpired:
        return 124, "git %s timed out" % args[0]
    except OSError as exc:
        return 126, str(exc)


def is_checkout(repo: Path | None = None) -> bool:
    repo = repo or REPO
    return (repo / ".git").exists()


def version(repo: Path | None = None) -> dict:
    """What this machine runs: commit, branch, local changes. Cheap; no network."""
    repo = repo or REPO
    if not is_checkout(repo):
        return {"git": False, "commit": "", "branch": "", "dirty": False}
    _, commit = git(repo, "rev-parse", "--short=12", "HEAD")
    _, branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return {"git": True, "commit": commit.strip()[:12], "branch": branch.strip(),
            "dirty": bool(dirty_files(repo))}


def dirty_files(repo: Path | None = None) -> list:
    repo = repo or REPO
    code, out = git(repo, "status", "--porcelain", "--untracked-files=no")
    return [line[3:] for line in out.splitlines() if line.strip()] if code == 0 else []


def _is_old_version(repo: Path, path: str) -> bool:
    """True when the file on disk is byte-identical to this path in some commit on GitHub."""
    code, blob = git(repo, "hash-object", "--", path)
    if code != 0 or not blob.strip():
        return False
    _, history = git(repo, "log", "--no-abbrev", "--raw", "--pretty=format:", "-n", "400",
                     "origin/" + BRANCH, "--", path)
    known = set()
    for line in history.splitlines():
        parts = line.split()
        if len(parts) >= 4 and line.startswith(":"):
            known.update(parts[2:4])
    return blob.strip() in known


def ensure_checkout(repo: Path | None = None) -> str:
    """Turn a plain copy of LOKI into a git checkout of BRANCH without touching its files."""
    repo = repo or REPO
    if is_checkout(repo):
        return ""
    steps = (("init",), ("remote", "add", "origin", REPO_URL),
             ("fetch", "--quiet", "origin", BRANCH))
    for step in steps:
        code, out = git(repo, *step, timeout=180)
        if code != 0:
            return "could not make a git checkout here (%s): %s" % (" ".join(step[:2]), out[-200:])
    # --mixed: point at GitHub's commit but keep every file in the folder as it is.
    code, out = git(repo, "reset", "--mixed", "--quiet", "origin/" + BRANCH)
    if code != 0:
        return "could not adopt GitHub's history: %s" % out[-200:]
    git(repo, "branch", "-M", BRANCH)          # whatever `git init` named it
    git(repo, "branch", "--set-upstream-to=origin/" + BRANCH, BRANCH)
    # Restore files that are missing from the copy; never overwrite ones that exist.
    _, deleted = git(repo, "ls-files", "--deleted")
    missing = [f for f in deleted.splitlines() if f.strip()]
    if missing:
        git(repo, "checkout", "--", *missing)
    # A file that is just an OLDER version of LOKI (it matches that file in some earlier
    # commit) is brought up to date; a file that matches no version is the user's own edit
    # and is kept as it is.
    stale = [f for f in dirty_files(repo) if _is_old_version(repo, f)]
    if stale:
        git(repo, "checkout", "--", *stale)
    changed = dirty_files(repo)
    return ("this folder is now a git checkout of %s%s" %
            (BRANCH, (" (%d file(s) differ from GitHub and were kept as they are)" % len(changed))
             if changed else ""))


def check(repo: Path | None = None, fetch: bool = True, timeout: float = 120.0) -> dict:
    """How this checkout compares with GitHub. Fetches unless fetch=False."""
    repo = repo or REPO
    if not is_checkout(repo):
        return {"ok": False, "error": "not a git checkout", "can_update": False}
    if fetch:
        code, out = git(repo, "fetch", "--quiet", "origin", BRANCH, timeout=timeout)
        if code != 0:
            return {"ok": False, "error": "cannot reach GitHub: %s" % out[-200:], "can_update": False}
    target = "origin/" + BRANCH
    _, counts = git(repo, "rev-list", "--left-right", "--count", "HEAD..." + target)
    try:
        ahead, behind = (int(x) for x in counts.split())
    except ValueError:
        ahead, behind = 0, 0
    _, latest = git(repo, "rev-parse", "--short=12", target)
    dirty = dirty_files(repo)
    info = version(repo)
    can = behind > 0 and ahead == 0 and not dirty
    reason = ""
    if behind and dirty:
        reason = "local changes to %d file(s); commit and push them (tools/ship.py) first" % len(dirty)
    elif behind and ahead:
        reason = "this machine has %d commit(s) GitHub does not; push them (tools/ship.py) first" % ahead
    return {"ok": True, "current": info["commit"], "branch": info["branch"], "latest": latest.strip()[:12],
            "ahead": ahead, "behind": behind, "dirty": dirty, "can_update": can, "reason": reason}


def _move_aside_untracked(repo: Path) -> list:
    """Untracked files that the update would add are renamed, never overwritten or lost."""
    _, added = git(repo, "diff", "--name-only", "--diff-filter=A", "HEAD", "origin/" + BRANCH)
    moved = []
    for rel in [r for r in added.splitlines() if r.strip()]:
        path = repo / rel
        if path.is_file():
            target = path.with_name(path.name + ".before-update")
            n = 1
            while target.exists():
                n += 1
                target = path.with_name("%s.before-update-%d" % (path.name, n))
            try:
                path.rename(target)
                moved.append(rel)
            except OSError:
                pass
    return moved


def _requirements_changed(repo: Path, old: str, new: str) -> bool:
    _, out = git(repo, "diff", "--name-only", old, new, "--", "engine/requirements.txt",
                 "app/requirements.txt")
    return bool(out.strip())


def _install_requirements(repo: Path) -> str:
    python = sys.executable
    code_all = []
    for req in ("engine/requirements.txt", "app/requirements.txt"):
        try:
            proc = subprocess.run([python, "-m", "pip", "install", "-q", "-r", str(repo / req)],
                                  capture_output=True, text=True, timeout=600)
            code_all.append(proc.returncode)
        except (OSError, subprocess.SubprocessError):
            code_all.append(1)
    return "dependencies updated" if not any(code_all) else "some dependencies did not install"


def update(repo: Path | None = None, timeout: float = 120.0) -> dict:
    """Bring this checkout up to GitHub's BRANCH, fast-forward only. Never raises."""
    repo = repo or REPO
    with _lock:
        notes = []
        boot = ensure_checkout(repo)
        if boot:
            notes.append(boot)
            if not is_checkout(repo):
                return _done(False, "; ".join(notes), error=boot)
        # Older checkouts sit on macos-app; move them to the one branch when that is safe.
        _, branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        branch = branch.strip()
        if branch != BRANCH:
            git(repo, "fetch", "--quiet", "origin", BRANCH, timeout=120)
            code, _ = git(repo, "merge-base", "--is-ancestor", "HEAD", "origin/" + BRANCH)
            if branch in OLD_BRANCHES and code == 0 and not dirty_files(repo):
                code, out = git(repo, "checkout", "-q", "-B", BRANCH, "origin/" + BRANCH)
                if code == 0:
                    git(repo, "branch", "--set-upstream-to=origin/" + BRANCH, BRANCH)
                    notes.append("moved from %s to %s" % (branch, BRANCH))
                else:
                    return _done(False, "could not switch to %s: %s" % (BRANCH, out[-200:]))
            else:
                return _done(False, "on branch %s, not %s; left alone" % (branch, BRANCH))
        before = version(repo)["commit"]
        state = check(repo, timeout=timeout)
        if not state.get("ok"):
            return _done(False, "; ".join(notes), error=state.get("error", ""))
        if not state["behind"]:
            STATE.update({"current": state["current"], "latest": state["latest"], "ahead": state["ahead"],
                          "behind": 0, "dirty": state["dirty"]})
            return _done(False, "; ".join(notes + ["up to date (%s)" % state["current"]]))
        if not state["can_update"]:
            STATE.update({k: state[k] for k in ("current", "latest", "ahead", "behind", "dirty")})
            return _done(False, "; ".join(notes + ["update waiting: " + state["reason"]]))
        moved = _move_aside_untracked(repo)
        if moved:
            notes.append("kept your untracked %s as *.before-update" % ", ".join(moved))
        code, out = git(repo, "merge", "--ff-only", "--quiet", "origin/" + BRANCH)
        if code != 0:
            return _done(False, "; ".join(notes), error="update failed: %s" % out[-200:])
        after = version(repo)["commit"]
        notes.append("updated %s -> %s" % (before, after))
        if _requirements_changed(repo, before, after):
            notes.append(_install_requirements(repo))
        STATE.update({"current": after, "latest": after, "behind": 0, "ahead": 0, "dirty": [],
                      "updated_to": after, "update_available": False})
        return _done(True, "; ".join(notes))


def _done(updated: bool, note: str, error: str = "") -> dict:
    STATE.update({"checked": time.time(), "note": note, "error": error})
    print("[loki-update] %s%s" % (note, (" - " + error) if error else ""), flush=True)
    return {"updated": updated, "note": note, "error": error}


def status() -> dict:
    return {"enabled": enabled(), "branch": BRANCH, **version(REPO), **{k: v for k, v in STATE.items()}}


def check_now() -> dict:
    """Look at GitHub without changing anything; record whether an update is waiting.

    A running engine never swaps its own code (half-old, half-new modules would be worse
    than either); the update is applied the next time LOKI starts (app/loki_app.py)."""
    with _lock:
        state = check(REPO)
    if state.get("ok"):
        STATE.update({k: state[k] for k in ("current", "latest", "ahead", "behind", "dirty")})
        STATE.update({"checked": time.time(), "error": "",
                      "update_available": bool(state["behind"]),
                      "note": ("update %s -> %s waiting; restart LOKI to use it" % (state["current"], state["latest"])
                               if state["behind"] and state["can_update"] else state.get("reason") or "up to date")})
    else:
        STATE.update({"checked": time.time(), "error": state.get("error", "")})
    return status()


def run_forever(every_s: float | None = None) -> None:
    """Background loop for the engine: check GitHub now and then (never applies)."""
    every = every_s if every_s is not None else float(os.getenv("LOKI_UPDATE_EVERY_S", "1800") or 1800)
    time.sleep(30)
    while True:
        if enabled() and is_checkout(REPO):
            try:
                check_now()
            except Exception as exc:  # noqa: BLE001 - updates must never take the engine down
                STATE.update({"error": "%s: %s" % (type(exc).__name__, exc)})
        time.sleep(max(60.0, every))
