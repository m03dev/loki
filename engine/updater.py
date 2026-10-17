"""Keep every machine on the same LOKI: GitHub's `master` is the one version.

The Mac and the PC must never drift apart. Each LOKI updates itself from GitHub:

  - when the app starts (before the engine starts, so the new code runs at once);
  - while it runs, it checks every LOKI_UPDATE_EVERY_S seconds (default 10 min) and when a
    linked machine reports a different version; a waiting update is applied as soon as LOKI
    is idle and the WHOLE app restarts on it (LOKI_FORCE_UPDATE=0: only tell you, apply at
    the next start).

An update never overwrites your work. Genuinely edited tracked files stop it (named in the
reason; commit and push them with tools/ship.py first); files that only hold another LOKI
version are restored. Local commits that GitHub already has are dropped, other local
commits are replayed on top of GitHub's version and stay unpushed (a conflict undoes that
and is reported); a backup ref refs/loki/backup/<time> is kept either way. Why the last
attempt failed (sign-in, network, missing disk, ...) is in status()["error"/"problem"],
which /health shows. A folder that is a plain copy with
no git history (how the Mac's copy started) is turned into a checkout in place: the files
stay, missing ones are restored, and nothing is deleted.

Publishing goes the other way through tools/ship.py: test, commit, push, then tell the
linked machines to update. Set LOKI_AUTO_UPDATE=0 to turn automatic updates off.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPO_URL = os.getenv("LOKI_REPO_URL", "https://github.com/m03dev/loki.git")
BRANCH = os.getenv("LOKI_BRANCH", "master")
OLD_BRANCHES = ("macos-app", "integrate")   # branches older checkouts may still be on

STATE = {"checked": 0.0, "current": "", "latest": "", "behind": 0, "ahead": 0, "dirty": [],
         "updated_to": "", "update_available": False, "note": "", "error": "", "problem": ""}
# Problems a later successful fetch shows are gone (the next start will update).
TRANSIENT_PROBLEMS = ("GitHub sign-in needed", "GitHub unreachable", "git missing", "folder ownership",
                      "update failed")
_lock = threading.Lock()
# The commit this process started on. A running engine never swaps its own code, so when
# the checkout moves past this, a restart is what applies it (restart_needed()).
RUNNING_COMMIT = ""
RESTART_EXIT_CODE = 75      # "restart me": app/loki_app.py starts the engine again


def _release_mod():
    import release_update  # pylint: disable=import-outside-toplevel
    return release_update


def _release(repo: Path | None = None) -> bool:
    """True in an installed LOKI (LOKI_RELEASE_ROOT, set by packaging/installer/loki_launch.py) for this
    machine's own tree; a git checkout and the suites' throwaway repos keep the git path."""
    if not os.environ.get("LOKI_RELEASE_ROOT", "").strip():
        return False
    return repo is None or Path(repo).resolve() == REPO.resolve()


def _release_check_now() -> dict:
    info = _release_mod().check()
    STATE.update({"checked": time.time(), "update_available": bool(info.get("update_available")),
                  "latest": info.get("latest", ""), "current": info.get("current", ""),
                  "error": "" if info.get("ok") else info.get("error", ""),
                  "problem": "" if info.get("ok") else info.get("problem", ""),
                  "note": ("update %s -> %s waiting" % (info.get("current"), info.get("latest")))
                  if info.get("update_available") else ("up to date" if info.get("ok") else "")})
    return {**_release_mod().status(), **STATE}


def _data_dir() -> Path:
    return Path(os.getenv("LOKI_DATA") or (REPO / "harness_data"))


def _health_file(repo: Path | None = None) -> Path:
    """The health record lives with the checkout it describes (inside .git, never committed),
    so a test that updates a throwaway repo can never touch the real machine's record."""
    repo = repo or REPO
    if (repo / ".git").is_dir():
        return repo / ".git" / "loki_update_health.json"
    return _legacy_health_file()


def _legacy_health_file() -> Path:
    return _data_dir() / "app" / "update_health.json"


def health(repo: Path | None = None) -> dict:
    """{last_good, pending, skip:[...]} - what started fine here, what is on trial, what failed."""
    if _release(repo):   # an installed LOKI (no git): release zips, engine/release_update.py
        return _release_mod().state()
    try:
        import json  # pylint: disable=import-outside-toplevel
        data = json.loads(_health_file(repo).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_health(data: dict, repo: Path | None = None) -> None:
    import json  # pylint: disable=import-outside-toplevel
    path = _health_file(repo)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def mark_good(repo: Path | None = None) -> dict:
    """The engine started and answered: this commit is good on this machine."""
    if _release(repo):   # an installed LOKI (no git): release zips, engine/release_update.py
        return _release_mod().mark_good()
    commit = version(repo or REPO).get("commit", "")
    data = health(repo)
    if commit:
        was_trial = bool(data.get("pending"))
        data.update({"last_good": commit, "pending": "", "good_at": time.time()})
        _save_health(data, repo)
        if was_trial:
            note_history("good", repo, commit=commit)
    return data


def on_trial(repo: Path | None = None) -> bool:
    """This machine runs a fresh update that has not proved itself yet (engine AND window)."""
    if _release(repo):   # an installed LOKI (no git): release zips, engine/release_update.py
        return _release_mod().on_trial()
    data = health(repo)
    current = version(repo or REPO).get("commit", "")
    return bool(data.get("pending") and current and data["pending"].startswith(current[:12]))


def rollback(repo: Path | None = None, why: str = "it did not start") -> dict:
    """The new version did not start: go back to the last good commit and skip the bad one.

    Only this checkout moves (`git reset --keep`, which refuses to touch local edits);
    nothing is pushed. The bad commit is remembered so the next start does not apply it
    again; any NEWER commit on GitHub (the fix) is applied normally."""
    if _release(repo):   # an installed LOKI (no git): release zips, engine/release_update.py
        return _release_mod().rollback(why)
    repo = repo or REPO
    data = health(repo)
    current = version(repo).get("commit", "")
    good, bad = data.get("last_good", ""), data.get("pending", "")
    if not bad or not current or not bad.startswith(current[:12]):
        # Only a version that is still on trial (updated, never started) is rolled back;
        # an engine that fails for another reason keeps the version it has.
        return {"ok": False, "error": "the running version is not a fresh update; nothing to roll back"}
    if not good or good == bad:
        return {"ok": False, "error": "no earlier good version is known on this machine"}
    code, out = git(repo, "reset", "--keep", good)
    if code != 0:
        return {"ok": False, "error": "could not go back to %s: %s" % (good, out[-200:])}
    skip = [c for c in data.get("skip", []) if c][-20:]
    if bad and bad not in skip:
        skip.append(bad)
    data.update({"pending": "", "skip": skip, "rolled_back_at": time.time(), "rolled_back_from": bad})
    reasons = dict(data.get("skip_reasons", {}))
    reasons[bad[:12]] = why[:400]
    data["skip_reasons"] = reasons
    _save_health(data, repo)
    note_history("rolled back", repo, **{"from": bad, "to": good, "why": why})
    STATE.update({"note": "went back to %s: %s %s" % (good, bad, why)})
    return {"ok": True, "from": bad, "to": good}


def is_behind(commit: str, latest: str, repo: Path | None = None) -> bool:
    """True when `commit` is an older commit of `latest` (a newer or unknown one is not behind)."""
    repo = repo or REPO
    if not commit or not latest or latest.startswith(commit[:12]) or commit.startswith(latest[:12]):
        return False
    code, _ = git(repo, "merge-base", "--is-ancestor", commit, latest)
    return code == 0


def restart_needed() -> bool:
    current = version(REPO).get("commit", "")
    return bool(RUNNING_COMMIT and current and current != RUNNING_COMMIT)


def enabled() -> bool:
    return str(os.getenv("LOKI_AUTO_UPDATE", "1")).strip().lower() not in ("0", "false", "off", "no")


# Finder, launchd and login items start apps with a bare PATH (/usr/bin:/bin:...). git
# itself is then /usr/bin/git (fine), but the credential helper that `gh auth setup-git`
# configured (`gh auth git-credential`) lives in Homebrew's bin and may not be found:
# fetch then fails with "could not read Username" although it works in Terminal.
EXTRA_TOOL_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin")
UNIX_BASE_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
WINDOWS_GIT = (r"%ProgramFiles%\Git\cmd\git.exe", r"%ProgramFiles(x86)%\Git\cmd\git.exe",
               r"%LocalAppData%\Programs\Git\cmd\git.exe")
# Command-line config is protected config (git >= 2.38 honours safe.directory given with
# `-c`; checked with 2.43): a checkout on an external volume, a disk image or a folder
# owned by another account must never stop updates with "detected dubious ownership"
# (also when it is reached through a symlink). It applies to LOKI's own git calls only.
SAFE_DIRECTORY = ("-c", "safe.directory=*")


def tool_path(base: str | None = None, platform: str | None = None) -> str:
    """PATH for git and its helpers: on macOS/Linux the usual tool folders come first (as
    tools/macos/launcher.sh does); on Windows PATH is left exactly as it is."""
    platform = platform or sys.platform
    base = os.environ.get("PATH", "") if base is None else base
    if platform.startswith("win"):
        return base
    parts = [os.path.expanduser(d) for d in EXTRA_TOOL_DIRS]
    parts += [p for p in base.split(":") if p]
    parts += list(UNIX_BASE_DIRS)
    seen, out = set(), []
    for part in parts:
        if part not in seen:
            seen.add(part)
            out.append(part)
    return ":".join(out)


def git_env(platform: str | None = None) -> dict:
    platform = platform or sys.platform
    # Never a sign-in window: GIT_TERMINAL_PROMPT only stops the terminal prompt; Git
    # Credential Manager (Windows, also on macOS) shows its own "Select an account" dialog
    # unless told not to, and that dialog blocked LOKI from starting (2026-10-16 on the PC).
    # Without stored credentials the fetch now fails fast and the reason is shown instead.
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="", LC_ALL="C",
               GCM_INTERACTIVE="never", GCM_GUI_PROMPT="false", GIT_CREDENTIAL_MANAGER_INTERACTIVE="never",
               SSH_ASKPASS="", GIT_SSH_COMMAND=os.environ.get("GIT_SSH_COMMAND") or "ssh -o BatchMode=yes")
    env["PATH"] = tool_path(env.get("PATH", ""), platform)
    if not env.get("HOME") and not platform.startswith("win"):
        env["HOME"] = str(Path.home())   # git and gh read their config from HOME
    return env


def git_exe(platform: str | None = None) -> str:
    platform = platform or sys.platform
    found = shutil.which("git")
    if not found and not platform.startswith("win"):
        found = shutil.which("git", path=tool_path("", platform))
    if found:
        return found
    if platform.startswith("win"):
        for raw in WINDOWS_GIT:
            candidate = os.path.expandvars(raw)
            if "%" not in candidate and Path(candidate).is_file():
                return candidate
    return ""


_GITHUB_OWNER: dict = {}


def github_account(repo: Path) -> list:
    """`-c credential.https://github.com.username=<owner>` for the GitHub account that owns
    this checkout (from origin's URL, or LOKI_GITHUB_USER). With two GitHub accounts stored,
    Git Credential Manager otherwise stops to ask "Select an account" - which it may not do
    here (GCM_INTERACTIVE=never), so the fetch would just fail."""
    key = str(repo)
    if key not in _GITHUB_OWNER:
        owner = (os.environ.get("LOKI_GITHUB_USER") or "").strip()
        if not owner:
            try:
                text = (Path(repo) / ".git" / "config").read_text(encoding="utf-8", errors="replace")
                import re as _re  # pylint: disable=import-outside-toplevel
                found = _re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*https://github\.com/([A-Za-z0-9-]+)/', text)
                owner = found.group(1) if found else ""
            except OSError:
                owner = ""
        _GITHUB_OWNER[key] = owner
    owner = _GITHUB_OWNER[key]
    return ["-c", "credential.https://github.com.username=%s" % owner] if owner else []


def git(repo: Path, *args: str, timeout: float = 60.0) -> tuple:
    """(returncode, stdout+stderr) of one git command; never raises."""
    exe = git_exe()
    if not exe:
        return 127, "git is not installed"
    account = github_account(repo) if args and args[0] in ("fetch", "pull", "push", "ls-remote", "clone") else []
    try:
        proc = subprocess.run([exe, *SAFE_DIRECTORY, *account, "-C", str(repo), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              env=git_env(), stdin=subprocess.DEVNULL)
        return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).rstrip()
    except subprocess.TimeoutExpired:
        return 124, "git %s timed out" % args[0]
    except OSError as exc:
        return 126, str(exc)


def is_checkout(repo: Path | None = None) -> bool:
    repo = repo or REPO
    try:
        return (repo / ".git").exists()
    except OSError:
        return False


def unreachable(repo: Path | None = None) -> str:
    """Why the checkout folder cannot be reached ("" when it can). On the Mac the checkout
    sits on a disk image that must be attached after a reboot, or the path dangles."""
    repo = Path(repo or REPO)
    try:
        if repo.is_dir():
            return ""
    except OSError:
        pass
    target = ""
    try:
        if repo.is_symlink():
            target = os.readlink(str(repo))
    except OSError:
        pass
    parts = Path(target or str(repo)).parts
    disk = (" (is the disk %s attached?)" % parts[2]) if len(parts) > 2 and parts[1] == "Volumes" else ""
    if target:
        return "the LOKI folder %s points to %s, which is missing%s" % (repo, target, disk)
    return "the LOKI folder %s is missing%s" % (repo, disk)


def read_version_file(repo: Path | None = None) -> str:
    """The human version from VERSION at the repo root (e.g. "0.16")."""
    try:
        lines = ((repo or REPO) / "VERSION").read_text(encoding="utf-8").strip().splitlines()
        return lines[0].strip() if lines else ""
    except OSError:
        return ""


_PATCH_CACHE: dict = {}


def patch_number(repo: Path, commit: str = "") -> int:
    """How many commits lead to HEAD (the 412 in "patch 412"). 0 when unknown or when the
    checkout is shallow (a shallow clone counts only what it downloaded)."""
    key = (str(repo), commit)
    if commit and key in _PATCH_CACHE:
        return _PATCH_CACHE[key]
    count = 0
    code, shallow = git(repo, "rev-parse", "--is-shallow-repository")
    if code == 0 and shallow.strip() == "false":
        code, out = git(repo, "rev-list", "--count", "HEAD")
        try:
            count = int(out.strip()) if code == 0 else 0
        except ValueError:
            count = 0
    if commit:
        _PATCH_CACHE[key] = count
    return count


def version_label(ver: str, patch: int, commit: str = "") -> str:
    """"v0.16 · patch 412" (U+00B7 middle dot); without a patch number, the commit."""
    head = ("v" + ver) if ver else "LOKI"
    if patch:
        return "%s · patch %d" % (head, patch)
    return ("%s · %s" % (head, commit[:7])) if commit else head


def version(repo: Path | None = None) -> dict:
    """What this machine runs: commit, branch, local changes and the human label
    ("v0.16 · patch 412" = VERSION file + commits on HEAD). Cheap; no network."""
    repo = repo or REPO
    ver = read_version_file(repo)
    if not is_checkout(repo):
        return {"git": False, "commit": "", "branch": "", "dirty": False, "version": ver,
                "patch": 0, "label": version_label(ver, 0)}
    code, commit = git(repo, "rev-parse", "--short=12", "HEAD")
    commit = commit.strip()[:12] if code == 0 else ""
    _, branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    patch = patch_number(repo, commit) if commit else 0
    return {"git": True, "commit": commit, "branch": branch.strip(),
            "dirty": bool(dirty_files(repo)), "version": ver, "patch": patch,
            "label": version_label(ver, patch, commit)}


def dirty_files(repo: Path | None = None) -> list:
    repo = repo or REPO
    code, out = git(repo, "status", "--porcelain", "-z", "--untracked-files=no")
    if code != 0:
        return []
    files, entries = [], out.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        files.append(entry[3:])
        if entry[0] in "RC":     # a rename/copy is followed by its old name
            i += 1
    return files


def _deleted(repo: Path, path: str) -> bool:
    try:
        return not (repo / path).exists() and not (repo / path).is_symlink()
    except OSError:
        return False


def classify_dirty(repo: Path, new: str = "") -> tuple:
    """(restorable, kept): changed tracked files that hold nothing of the user's - a file
    that is byte-identical to GitHub's NEW version (`new`) or to any OLDER committed one,
    or a tracked file that was deleted - versus genuine edits, which are never touched."""
    restorable, kept = [], []
    for path in dirty_files(repo):
        if _deleted(repo, path) or _is_old_version(repo, path) or (new and _same_as(repo, path, new)):
            restorable.append(path)
        else:
            kept.append(path)
    return restorable, kept


def _same_as(repo: Path, path: str, rev: str) -> bool:
    code, blob = git(repo, "hash-object", "--", path)
    if code != 0 or not blob.strip():
        return False
    code, theirs = git(repo, "rev-parse", "--verify", "--quiet", "%s:%s" % (rev, path))
    return code == 0 and theirs.strip() == blob.strip()


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


AUTH_SIGNS = ("authentication failed", "could not read username", "could not read password",
              "terminal prompts disabled", "repository not found", "invalid username or password",
              "permission denied (publickey)", "requested url returned error: 401",
              "requested url returned error: 403", "403 forbidden", "bad credentials",
              "support for password authentication was removed")
NETWORK_SIGNS = ("could not resolve host", "failed to connect", "connection timed out",
                 "connection refused", "network is unreachable", "timed out", "operation timed out",
                 "ssl", "unable to access")


def sign_in_hint(platform: str | None = None) -> str:
    platform = platform or sys.platform
    if platform == "darwin":
        return ("GitHub sign-in needed on this Mac: in Terminal run `gh auth login` then "
                "`gh auth setup-git`, then restart LOKI")
    if platform.startswith("win"):
        return ("GitHub sign-in needed on this PC: run `gh auth login` then `gh auth setup-git` "
                "(or `git fetch` in the LOKI folder once and sign in), then restart LOKI")
    return "GitHub sign-in needed on this machine: run `gh auth login` then `gh auth setup-git`, then restart LOKI"


def explain_git_error(out: str, platform: str | None = None) -> tuple:
    """(problem, error): a short label for the UI and an actionable sentence for a failed
    fetch/merge, from git's own output."""
    platform = platform or sys.platform
    text = (out or "").lower()
    tail = " ".join((out or "").split())[-200:]
    if "git is not installed" in text or "invalid active developer path" in text:
        fix = ("install Apple's command line tools: `xcode-select --install`" if platform == "darwin"
               else "install Git for Windows (https://git-scm.com)" if platform.startswith("win")
               else "install git")
        return "git missing", "git was not found; %s" % fix
    if "dubious ownership" in text:
        return ("folder ownership", "git refuses this folder (owned by another account): run "
                "`git config --global --add safe.directory '*'` - %s" % tail)
    if any(sign in text for sign in AUTH_SIGNS):
        return "GitHub sign-in needed", "%s (git said: %s)" % (sign_in_hint(platform), tail)
    if any(sign in text for sign in NETWORK_SIGNS):
        return "GitHub unreachable", "cannot reach GitHub (no network?): %s" % tail
    return "update failed", "cannot reach GitHub: %s" % tail


def check(repo: Path | None = None, fetch: bool = True, timeout: float = 120.0) -> dict:
    """How this checkout compares with GitHub. Fetches unless fetch=False."""
    if _release(repo):   # an installed LOKI (no git): release zips, engine/release_update.py
        return _release_mod().check(timeout=min(timeout, 30.0))
    repo = repo or REPO
    gone = unreachable(repo)
    if gone:
        return {"ok": False, "error": gone, "problem": "LOKI folder missing", "can_update": False}
    if not is_checkout(repo):
        return {"ok": False, "error": "not a git checkout", "problem": "not a git checkout",
                "can_update": False}
    if fetch:
        code, out = git(repo, "fetch", "--quiet", "origin", BRANCH, timeout=timeout)
        if code != 0:
            problem, error = explain_git_error(out)
            return {"ok": False, "error": error, "problem": problem, "can_update": False}
    target = "origin/" + BRANCH
    _, counts = git(repo, "rev-list", "--left-right", "--count", "HEAD..." + target)
    try:
        ahead, behind = (int(x) for x in counts.split())
    except ValueError:
        ahead, behind = 0, 0
    _, latest = git(repo, "rev-parse", "--short=12", target)
    dirty = dirty_files(repo)
    restorable, kept = classify_dirty(repo, target) if (dirty and behind) else ([], dirty)
    info = version(repo)
    # Local commits do not block: update() replays them on top of GitHub's version (or drops
    # them when GitHub already has the same changes). Only genuine local edits block.
    can = behind > 0 and not kept
    reason = ""
    if behind and kept:
        reason = ("local changes to %d file(s) (%s); commit and push them (tools/ship.py) first"
                  % (len(kept), _names(kept)))
    return {"ok": True, "current": info["commit"], "branch": info["branch"], "latest": latest.strip()[:12],
            "ahead": ahead, "behind": behind, "dirty": dirty, "blocking": kept if behind else [],
            "restorable": restorable, "can_update": can, "reason": reason}


def _carry_plan(repo: Path, edited: list, target: str) -> tuple:
    """({path: merged bytes} for edited files GitHub also changed, "") when every one merges
    cleanly, or (None, why). Files GitHub did not touch need nothing: the fast-forward keeps
    them. Line endings are normalised for the merge and put back as the file had them."""
    _, changed = git(repo, "diff", "--name-only", "HEAD", target)
    upstream = set(changed.split())
    plan = {}
    for path in edited:
        if path not in upstream:
            continue
        if _deleted(repo, path):
            return None, "%s was deleted here and changed on GitHub" % path
        try:
            ours = (repo / path).read_bytes()
        except OSError as exc:
            return None, "cannot read %s (%s)" % (path, exc)
        code_b, base = _blob(repo, "HEAD", path)
        code_t, theirs = _blob(repo, target, path)
        if code_b != 0 or code_t != 0:
            return None, "%s is new or removed on one side" % path
        crlf = b"\r\n" in ours
        lf = lambda b: b.replace(b"\r\n", b"\n")   # noqa: E731
        merged = _merge3(lf(ours), lf(base), lf(theirs))
        if merged is None:
            return None, "%s was changed here AND on GitHub in the same place" % path
        plan[path] = merged.replace(b"\n", b"\r\n") if crlf else merged
    return plan, ""


def _blob(repo: Path, rev: str, path: str) -> tuple:
    try:
        proc = subprocess.run([git_exe(), "-C", str(repo), "-c", "safe.directory=*", "show", "%s:%s" % (rev, path)],
                              capture_output=True, timeout=60, env=git_env())
        return proc.returncode, proc.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, b""


def _merge3(ours: bytes, base: bytes, theirs: bytes) -> bytes | None:
    """git merge-file on three byte strings; None when there is a conflict."""
    with tempfile.TemporaryDirectory(prefix="loki-merge-") as tmp:
        files = []
        for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
            target = Path(tmp) / name
            target.write_bytes(data)
            files.append(str(target))
        try:
            proc = subprocess.run([git_exe(), "merge-file", "-p", *files], capture_output=True, timeout=60, env=git_env())
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout if proc.returncode == 0 else None


def _backup_edits(repo: Path) -> str:
    """Keep the uncommitted edits as a commit object under refs/loki/backup/ (the work tree
    is not touched), so carrying them can never lose anything."""
    code, sha = git(repo, "stash", "create", "LOKI: edits before an update")
    sha = sha.strip()
    if code != 0 or not sha:
        return ""
    ref = "refs/loki/backup/edits-%d" % int(time.time())
    code, _ = git(repo, "update-ref", ref, sha)
    return ref if code == 0 else ""


def _names(files: list, most: int = 5) -> str:
    shown = ", ".join(files[:most])
    return shown + (" and %d more" % (len(files) - most) if len(files) > most else "")


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
    python = os.getenv("LOKI_ENGINE_PYTHON") or sys.executable
    code_all = []
    for req in ("engine/requirements.txt", "app/requirements.txt"):
        try:
            proc = subprocess.run([python, "-m", "pip", "install", "-q", "-r", str(repo / req)],
                                  capture_output=True, text=True, timeout=600)
            code_all.append(proc.returncode)
        except (OSError, subprocess.SubprocessError):
            code_all.append(1)
    return "dependencies updated" if not any(code_all) else "some dependencies did not install"


def preflight(repo: Path, target: str, timeout: float = 240.0) -> tuple:
    """(ok, why) - try the NEW version before this machine switches to it.

    The target commit is checked out into a throwaway git worktree and LOKI's own self-test runs
    there with this machine's Python (every engine module imports, the app starts its checks, every
    script the window loads exists). If the new version needs packages it lists in its
    requirements, they are installed first (installs only add). A version that fails is never
    applied here: it goes on the skip list with the reason, and the next newer one is tried.
    LOKI_UPDATE_PREFLIGHT=0 turns this off."""
    if str(os.getenv("LOKI_UPDATE_PREFLIGHT", "1")).strip().lower() in ("0", "off", "false", "no"):
        return True, "pre-flight off"
    python = os.getenv("LOKI_ENGINE_PYTHON") or sys.executable   # the engine's own venv, not the app's
    tmp = Path(tempfile.mkdtemp(prefix="loki-preflight-"))
    tree = tmp / "tree"
    try:
        code, out = git(repo, "worktree", "add", "--detach", "--force", str(tree), target, timeout=120)
        if code != 0:
            return True, "pre-flight skipped (could not check out %s: %s)" % (target, out[-120:])
        if not (tree / "app" / "loki_app.py").is_file():
            return True, "pre-flight skipped (not a LOKI app checkout)"
        for req in ("engine/requirements.txt", "app/requirements.txt"):
            new_req, old_req = tree / req, repo / req
            try:
                if new_req.is_file() and (not old_req.is_file() or new_req.read_bytes() != old_req.read_bytes()):
                    subprocess.run([python, "-m", "pip", "install", "-q", "-r", str(new_req)],
                                   capture_output=True, text=True, timeout=600)
            except (OSError, subprocess.SubprocessError):
                pass
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LOKI_", "HARNESS_"))}
        env.update(LOKI_DATA=str(tmp / "data"), LOKI_WORKSPACE=str(tmp / "ws"), LOKI_TIMESFM_APPROVED="0",
                   PYTHONDONTWRITEBYTECODE="1")
        (tmp / "ws").mkdir(exist_ok=True)
        try:
            proc = subprocess.run([python, str(tree / "app" / "loki_app.py"), "--self-test"], cwd=str(tree),
                                  env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, "the new version's self-test did not finish in %ds" % timeout
        except OSError as exc:
            return True, "pre-flight skipped (%s)" % exc
        text = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0 or "FAILED" in text:
            return False, "the new version failed its self-test here: " + " ".join(text.split())[-400:]
        missing = ui_missing(tree)
        if missing:
            return False, "the new version's window would not load: missing " + ", ".join(missing[:5])
        return True, "pre-flight passed"
    finally:
        git(repo, "worktree", "remove", "--force", str(tree))
        git(repo, "worktree", "prune")
        shutil.rmtree(tmp, ignore_errors=True)


def ui_missing(tree: Path) -> list:
    """Every /ui/... file the window's index.html loads, that is not in the tree."""
    import re as _re  # pylint: disable=import-outside-toplevel
    index = tree / "app" / "ui" / "index.html"
    try:
        html = index.read_text(encoding="utf-8")
    except OSError:
        return ["app/ui/index.html"]
    wanted = set(_re.findall(r'(?:src|href)="/ui/([^"?#]+)"', html))
    return sorted(w for w in wanted if not (tree / "app" / "ui" / w).is_file())


def note_history(event: str, repo: Path | None = None, **info) -> None:
    """The last 30 update events on this machine (updated, rolled back, refused, good) - shown in
    Settings > Machines & updates so nothing about an update is ever a mystery."""
    data = health(repo)
    hist = [h for h in data.get("history", []) if isinstance(h, dict)][-29:]
    hist.append(dict(info, event=event, t=time.time()))
    data["history"] = hist
    _save_health(data, repo)


def skip_commit(commit: str, why: str, repo: Path | None = None) -> None:
    data = health(repo)
    skip = [c for c in data.get("skip", []) if c][-20:]
    if commit and commit not in skip:
        skip.append(commit)
    data["skip"] = skip
    reasons = dict(data.get("skip_reasons", {}))
    reasons[commit[:12]] = why[:400]
    data["skip_reasons"] = dict(list(reasons.items())[-20:])
    _save_health(data, repo)


def _in_progress(repo: Path) -> str:
    """A rebase or merge someone left half-done (it needs a person: it may hold their work)."""
    code, gitdir = git(repo, "rev-parse", "--git-dir")
    if code != 0:
        return ""
    base = Path(gitdir.strip())
    if not base.is_absolute():
        base = repo / base
    for name, what in (("rebase-merge", "rebase"), ("rebase-apply", "rebase"), ("MERGE_HEAD", "merge")):
        if (base / name).exists():
            return what
    return ""


def _backup(repo: Path, label: str = "") -> str:
    """Keep the current commit reachable before LOKI moves the branch: refs/loki/backup/<time>."""
    stamp = time.strftime("%Y%m%d-%H%M%S") + (("-" + label) if label else "")
    ref = "refs/loki/backup/" + stamp
    code, _ = git(repo, "update-ref", ref, "HEAD")
    return ref if code == 0 else ""


def _identity_args(repo: Path) -> tuple:
    """A rebase writes commits; without user.name/email git refuses. Supply a neutral one
    for that command only (the author of each commit is kept)."""
    _, email = git(repo, "config", "user.email")
    _, name = git(repo, "config", "user.name")
    args = []
    if not name.strip():
        args += ["-c", "user.name=LOKI updater"]
    if not email.strip():
        args += ["-c", "user.email=loki-updater@localhost"]
    return tuple(args)


def _local_commits(repo: Path, target: str) -> tuple:
    """(unique, already_upstream): local commits GitHub does not have, split by whether an
    identical change is already on GitHub (`git cherry` marks those with '-')."""
    code, out = git(repo, "cherry", target, "HEAD")
    if code != 0:
        return [], []
    unique = [line[2:].strip() for line in out.splitlines() if line.startswith("+")]
    same = [line[2:].strip() for line in out.splitlines() if line.startswith("-")]
    return unique, same


def update(repo: Path | None = None, timeout: float = 120.0) -> dict:
    """Bring this checkout up to GitHub's BRANCH. Never raises; never loses local work.

    - files that only hold an older (or the new) LOKI version, or tracked files that were
      deleted, are restored; genuinely edited files stop the update, named in the reason;
    - local commits whose changes GitHub already has are dropped (a backup ref is kept);
    - other local commits are replayed on top of GitHub's version (rebase; backup ref kept)
      and stay unpushed; a conflict undoes the rebase and is reported;
    - otherwise it is a fast-forward."""
    if _release(repo):   # an installed LOKI (no git): release zips, engine/release_update.py
        return _release_mod().update(timeout)
    repo = repo or REPO
    with _lock:
        notes = []
        gone = unreachable(repo)
        if gone:
            return _done(False, "", error=gone, problem="LOKI folder missing", repo=repo)
        boot = ensure_checkout(repo)
        if boot:
            notes.append(boot)
            if not is_checkout(repo):
                return _done(False, "; ".join(notes), error=boot, problem="not a git checkout", repo=repo)
        busy = _in_progress(repo)
        if busy:
            return _done(False, "; ".join(notes), repo=repo, problem="unfinished %s" % busy,
                         error="a %s was left unfinished in %s; finish it or run `git %s --abort` there"
                               % (busy, repo, busy))
        # Older checkouts sit on macos-app; move them to the one branch when that is safe.
        _, branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        branch = branch.strip()
        if branch != BRANCH:
            git(repo, "fetch", "--quiet", "origin", BRANCH, timeout=timeout)
            code, _ = git(repo, "merge-base", "--is-ancestor", "HEAD", "origin/" + BRANCH)
            if branch in OLD_BRANCHES and code == 0 and not dirty_files(repo):
                code, out = git(repo, "checkout", "-q", "-B", BRANCH, "origin/" + BRANCH)
                if code == 0:
                    git(repo, "branch", "--set-upstream-to=origin/" + BRANCH, BRANCH)
                    notes.append("moved from %s to %s" % (branch, BRANCH))
                else:
                    return _done(False, "could not switch to %s" % BRANCH, repo=repo, problem="wrong branch",
                                 error="could not switch to %s: %s" % (BRANCH, out[-200:]))
            else:
                return _done(False, "on branch %s, not %s; left alone" % (branch, BRANCH), repo=repo,
                             problem="not on %s" % BRANCH,
                             error="this checkout is on %s, not %s; switch with `git checkout %s` to get updates"
                                   % (branch or "no branch", BRANCH, BRANCH))
        before = version(repo)["commit"]
        state = check(repo, timeout=timeout)
        if not state.get("ok"):
            return _done(False, "; ".join(notes), error=state.get("error", ""),
                         problem=state.get("problem", "update failed"), repo=repo)
        target = "origin/" + BRANCH
        if not state["behind"]:
            STATE.update({"current": state["current"], "latest": state["latest"], "ahead": state["ahead"],
                          "behind": 0, "dirty": state["dirty"], "update_available": False})
            if state["ahead"]:
                notes.append("%d local commit(s) are not on GitHub yet; publish them with tools/ship.py"
                             % state["ahead"])
            return _done(False, "; ".join(notes + ["up to date (%s)" % state["current"]]), repo=repo)
        if state["latest"] and any(state["latest"].startswith(c[:12]) for c in health(repo).get("skip", []) if c):
            return _done(False, "; ".join(notes + ["%s did not start on this machine before; waiting for "
                                                   "a newer version" % state["latest"]]), repo=repo)
        # Try the new version before switching to it: a version that cannot start here (a missing
        # package, a broken import, a window file missing) is never applied - the Mac's white window.
        ok, why = preflight(repo, target)
        if not ok:
            skip_commit(state["latest"], why, repo)
            note_history("refused", repo, commit=state["latest"], why=why)
            STATE.update({"update_available": False})
            return _done(False, "; ".join(notes + ["did not apply %s: %s" % (state["latest"][:12], why)]), repo=repo,
                         problem="new version failed its pre-flight", error="did not apply %s: %s"
                         % (state["latest"][:12], why))
        notes.append(why)
        # Files that hold nothing of the user's are put back first, so they never block.
        if state.get("restorable"):
            code, out = git(repo, "checkout", "HEAD", "--", *state["restorable"])
            if code == 0:
                notes.append("restored %d file(s) that only held another LOKI version (%s)"
                             % (len(state["restorable"]), _names(state["restorable"])))
        carried = {}
        if not state["can_update"] and state.get("blocking") and not state["ahead"]:
            # Uncommitted edits (an agent mid-task on this machine) used to stop EVERY update,
            # so this machine fell behind the other one all day. Carry them across instead when
            # git can merge them cleanly; a real conflict still blocks, exactly as before.
            carried, why = _carry_plan(repo, state["blocking"], target)
            if carried is not None:
                backup = _backup_edits(repo)
                git(repo, "checkout", "HEAD", "--", *carried.keys())   # clean them for the move
                state["can_update"] = True
                notes.append("carried %d edited file(s) across the update (%s; old state kept as %s)"
                             % (len(state["blocking"]), _names(state["blocking"]), backup or "-"))
            else:
                state["reason"] += "; " + why
        if not state["can_update"]:
            STATE.update({k: state[k] for k in ("current", "latest", "ahead", "behind", "dirty")})
            STATE["update_available"] = True
            return _done(False, "; ".join(notes + ["update waiting: " + state["reason"]]), repo=repo,
                         problem="local edits block the update",
                         error="update waiting: " + state["reason"])
        moved = _move_aside_untracked(repo)
        if moved:
            notes.append("kept your untracked %s as *.before-update" % ", ".join(moved))
        if state["ahead"]:
            unique, same = _local_commits(repo, target)
            backup = _backup(repo)
            if not unique:
                # Every local commit is already on GitHub (e.g. ship.py pushed a rebased copy):
                # nothing of the user's is lost by moving to GitHub's version.
                code, out = git(repo, "reset", "--keep", "--quiet", target)
                if code != 0:
                    return _done(False, "; ".join(notes), repo=repo, problem="update failed",
                                 error="could not move past %d already-published local commit(s): %s"
                                       % (len(same), out[-200:]))
                notes.append("%d local commit(s) were already on GitHub; moved to GitHub's version "
                             "(old state kept as %s)" % (len(same), backup or "-"))
            else:
                code, out = git(repo, *_identity_args(repo), "rebase", "--quiet", target, timeout=timeout)
                if code != 0:
                    git(repo, "rebase", "--abort")
                    STATE.update({k: state[k] for k in ("current", "latest", "ahead", "behind", "dirty")})
                    STATE["update_available"] = True
                    return _done(False, "; ".join(notes), repo=repo, problem="local commits conflict",
                                 error="%d local commit(s) that are not on GitHub conflict with GitHub's version; "
                                       "nothing was changed. Resolve with `git rebase origin/%s` in %s, then "
                                       "publish with tools/ship.py (%s)"
                                       % (len(unique), BRANCH, repo, " ".join(out.split())[-160:]))
                notes.append("kept %d local commit(s) that are not on GitHub yet on top of GitHub's version "
                             "(publish them with tools/ship.py; old state kept as %s)" % (len(unique), backup or "-"))
        else:
            code, out = git(repo, "merge", "--ff-only", "--quiet", target)
            if code != 0:
                problem, error = explain_git_error(out)
                return _done(False, "; ".join(notes), repo=repo,
                             problem="update failed" if problem == "GitHub unreachable" else problem,
                             error="update failed: %s" % " ".join(out.split())[-200:])
        for path, data in carried.items():   # the merged edits go back on top of the new version
            try:
                (repo / path).write_bytes(data)
            except OSError as exc:
                notes.append("could not put back %s (%s); it is in the backup ref" % (path, exc))
        after = version(repo)["commit"]
        notes.append("updated %s -> %s" % (before, after))
        trial = health(repo)  # `before` is what ran here until now: the version to go back to
        trial.update({"last_good": before or trial.get("last_good", ""), "pending": after, "pending_at": time.time()})
        _save_health(trial, repo)
        note_history("updated", repo, **{"from": before, "to": after})
        if _requirements_changed(repo, before, after):
            notes.append(_install_requirements(repo))
        _, ahead = git(repo, "rev-list", "--count", "%s..HEAD" % target)
        STATE.update({"current": after, "latest": state["latest"], "behind": 0,
                      "ahead": int(ahead.strip()) if ahead.strip().isdigit() else 0, "dirty": dirty_files(repo),
                      "updated_to": after, "update_available": False})
        return _done(True, "; ".join(notes), repo=repo)


def _last_file(repo: Path | None = None) -> Path | None:
    repo = repo or REPO
    try:
        if (repo / ".git").is_dir():
            return repo / ".git" / "loki_update_last.json"
    except OSError:
        pass
    return None


def last_result(repo: Path | None = None) -> dict:
    """The last update attempt on this checkout. The app updates in its own process before
    the engine starts, so the engine reads the outcome from here to show it in /health."""
    path = _last_file(repo)
    if not path:
        return {}
    try:
        import json  # pylint: disable=import-outside-toplevel
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _done(updated: bool, note: str, error: str = "", problem: str = "", repo: Path | None = None) -> dict:
    if error and not problem:
        problem = "update failed"
    now = time.time()
    STATE.update({"checked": now, "note": note, "error": error, "problem": problem})
    print("[loki-update] %s%s" % (note, (" - " + error) if error and error not in note else ""), flush=True)
    path = _last_file(repo)
    if path:
        try:
            import json  # pylint: disable=import-outside-toplevel
            path.write_text(json.dumps({"at": now, "updated": updated, "note": note, "error": error,
                                        "problem": problem}, indent=2), encoding="utf-8")
        except OSError:
            pass
    return {"updated": updated, "note": note, "error": error, "problem": problem}


def status() -> dict:
    """Version + update state for /health. `error`/`problem` say why the last update attempt
    (at start, in the app's process, or a later check) did not work; both are "" when fine."""
    if _release():   # an installed LOKI (no git): release zips, engine/release_update.py
        return _release_mod().status()
    state = {k: v for k, v in STATE.items()}
    last = last_result(REPO)
    if last and float(last.get("at") or 0) > float(state.get("checked") or 0):
        state.update({"checked": float(last.get("at") or 0), "note": last.get("note", ""),
                      "error": last.get("error", ""), "problem": last.get("problem", "")})
    gone = unreachable(REPO)
    if gone:
        state.update({"error": gone, "problem": "LOKI folder missing"})
    state.setdefault("problem", "")
    return {"enabled": enabled(), "branch": BRANCH, **version(REPO), **state}


def check_now() -> dict:
    """Look at GitHub without changing anything; record whether an update is waiting.

    A running engine never swaps its own code (half-old, half-new modules would be worse
    than either); the update is applied the next time LOKI starts (app/loki_app.py)."""
    if _release():   # an installed LOKI (no git): release zips, engine/release_update.py
        return _release_check_now()
    with _lock:
        state = check(REPO)
    if state.get("ok"):
        STATE.update({k: state[k] for k in ("current", "latest", "ahead", "behind", "dirty")})
        blocked = bool(state["behind"] and not state["can_update"])
        note = "up to date"
        if state["behind"] and state["can_update"]:
            note = "update %s -> %s waiting; restart LOKI to use it" % (state["current"], state["latest"])
            if state["ahead"]:
                note += " (your %d unpublished commit(s) stay on top)" % state["ahead"]
        elif blocked:
            note = state.get("reason") or "update blocked"
        elif state["ahead"]:
            note = "up to date; %d local commit(s) are not on GitHub yet" % state["ahead"]
        error, problem = (("update waiting: " + state["reason"]), "local edits block the update") if blocked else ("", "")
        last = last_result(REPO)
        if (not blocked and state["behind"] and last.get("error")
                and last.get("problem") not in TRANSIENT_PROBLEMS):
            # e.g. local commits that conflict: fetching works, but the start-up update
            # still cannot apply, so keep saying why.
            error, problem = last.get("error", ""), last.get("problem", "")
            note = last.get("note") or note
        STATE.update({"checked": time.time(), "update_available": bool(state["behind"]), "note": note,
                      "error": error, "problem": problem})
    else:
        STATE.update({"checked": time.time(), "error": state.get("error", ""),
                      "problem": state.get("problem", "update failed")})
    return status()


def force_enabled() -> bool:
    """LOKI_FORCE_UPDATE (default on): a waiting update is applied as soon as LOKI is idle and the
    whole app restarts on it - every machine stays on the newest LOKI without anyone clicking."""
    return str(os.getenv("LOKI_FORCE_UPDATE", "1")).strip().lower() not in ("0", "false", "off", "no")


def run_forever(every_s: float | None = None, idle=None, apply=None) -> None:
    """Background loop for the engine: check GitHub now and then. When an update is waiting,
    `idle()` says LOKI is not busy and force updates are on, `apply()` updates and restarts."""
    every = every_s if every_s is not None else float(os.getenv("LOKI_UPDATE_EVERY_S", "600") or 600)
    time.sleep(30)
    while True:
        if enabled() and (is_checkout(REPO) or _release()):
            try:
                check_now()
                if STATE.get("update_available") and force_enabled() and idle and apply and idle():
                    STATE["note"] = "applying the update and restarting LOKI"
                    apply()
            except Exception as exc:  # noqa: BLE001 - updates must never take the engine down
                STATE.update({"error": "%s: %s" % (type(exc).__name__, exc)})
        time.sleep(max(60.0, every))
