"""Ship a change to LOKI: test it, commit it, push it, and tell your other machines.

This is the ONE way changes reach GitHub, for you and for every agent (LOKI's own agents,
Ziva, Claude Code, Codex). It keeps the Mac and the PC on the same version:

    python tools/ship.py -m "what changed"            test, commit everything, push
    python tools/ship.py -m "..." --repo <worktree>   ship from an agent's git worktree
    python tools/ship.py --check                       just run the tests

Steps, and it stops at the first one that fails (nothing is pushed then):
  1. run the offline test suites (Mac and Windows run the same ones; CI runs them on both)
  2. commit all changes (git add -A; .gitignore keeps your data out)
  3. catch up with GitHub: rebase onto origin/master; a conflict stops here and is undone
  4. if GitHub had new commits, run the tests again on the combined result
  5. push to master (and mirror to the old macos-app branch while machines still use it)
  6. tell every linked machine a new version is out (they check at once and apply it on
     their next start; engine/updater.py)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REPO = HERE.parent
REPO_DEFAULT = DEFAULT_REPO  # alias used by _suite_env()
BRANCH = os.getenv("LOKI_BRANCH", "master")
MIRRORS = [b for b in os.getenv("LOKI_MIRROR_BRANCHES", "macos-app").split(",") if b.strip()]
SUITES = ["test_loki", "test_hardening", "test_integrations", "test_workers",
          "test_offline_e2e", "test_peers", "test_first_layer", "test_updater", "test_team", "test_events",
          "test_portal", "test_phone_link", "test_systems",
          "test_tool_guard", "test_autopilot", "test_role_routing", "test_stubs", "test_evals", "test_relay", "test_workbench", "test_models_media"]


def _suite_env() -> dict:
    """The environment a suite runs in, with the temp dir pinned to a safe absolute path.

    The suites make their scratch work with tempfile.mkdtemp(). If TMPDIR is missing or points
    into the checkout (seen after a killed run), that work lands in the tree and `git add -A`
    would commit it - so never let a suite inherit a temp dir inside REPO.
    """
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    root = (os.environ.get("TEMP") or "") if os.name == "nt" else "/tmp"
    if not root or not os.path.isdir(root) or not os.access(root, os.W_OK):
        root = tempfile.gettempdir()
    if os.path.abspath(root) != os.path.abspath(str(REPO_DEFAULT)) and not str(root).startswith(str(REPO_DEFAULT)):
        env["TMPDIR"] = env["TEMP"] = env["TMP"] = root
    return env


def run(repo: Path, *args: str, timeout: float = 300.0) -> tuple:
    env = _suite_env()
    try:
        proc = subprocess.run(list(args), cwd=str(repo), capture_output=True, text=True,
                              timeout=timeout, env=env)
        return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 124, "%s timed out" % args[0]
    except OSError as exc:
        return 126, str(exc)


def git(repo: Path, *args: str, timeout: float = 120.0) -> tuple:
    return run(repo, "git", *args, timeout=timeout)


def run_tests(repo: Path, say=print) -> bool:
    ok = True
    for suite in SUITES:
        path = repo / "tests" / (suite + ".py")
        if not path.is_file():
            continue
        started = time.monotonic()
        code, out = run(repo, sys.executable, str(path), timeout=1500)
        tail = [line for line in out.splitlines() if "passed," in line]
        say("  %-20s %s (%.0fs)" % (suite, tail[-1].strip() if tail else ("exit %d" % code),
                                     time.monotonic() - started))
        if code != 0:
            ok = False
            fails = [line for line in out.splitlines() if line.strip().startswith("FAIL") or "Error" in line]
            for line in fails[:8]:
                say("      " + line.strip())
            if os.getenv("GITHUB_ACTIONS"):
                # Shown on the run's page and readable through the API without the full log.
                detail = (" | ".join(f.strip() for f in fails if f.strip().startswith("FAIL"))[:900]
                          + " || tail: " + out[-900:].replace("\n", " | "))
                print("::error title=%s failed::%s" % (suite, detail[:1500]), flush=True)
    return ok


def version_label(repo: Path) -> str:
    """"v0.16 · patch 412" for what was shipped (engine/updater.py's label)."""
    sys.path.insert(0, str(HERE.parent / "engine"))
    try:
        import updater  # noqa: E402  pylint: disable=import-outside-toplevel
        return updater.version(repo).get("label", "")
    except Exception:  # noqa: BLE001 - a label must never stop a ship
        return ""


def tell_peers(repo: Path, say=print) -> list:
    """Ask linked machines to check for the new version (best effort)."""
    sys.path.insert(0, str(repo / "engine"))
    env_file = Path(os.getenv("LOKI_DATA") or (DEFAULT_REPO / "harness_data")) / ".env"
    if env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    try:
        import peer_link  # noqa: E402  pylint: disable=import-outside-toplevel
        told = peer_link.ask_peers_to_check_update()
    except Exception as exc:  # noqa: BLE001
        say("  could not reach linked machines: %s" % exc)
        return []
    say("  told: %s" % (", ".join(told) if told else "no linked machine answered (they update on their next start)"))
    return told


def ship(repo: Path, message: str, tests: bool = True, say=print) -> int:
    if not (repo / ".git").exists():
        say("Not a git checkout: %s (start LOKI once; it turns the folder into one)" % repo)
        return 2
    say("1. tests")
    if tests and not run_tests(repo, say):
        say("Tests failed - nothing was committed or pushed.")
        return 1
    say("2. commit")
    git(repo, "add", "-A")
    code, staged = git(repo, "diff", "--cached", "--name-only")
    if staged.strip():
        code, out = git(repo, "commit", "-q", "-m", message)
        if code != 0:
            say("Commit failed: " + out[-400:])
            return 1
        say("  committed %d file(s)" % len(staged.split()))
    else:
        say("  nothing new to commit")
    say("3. catch up with GitHub")
    code, out = git(repo, "fetch", "-q", "origin", BRANCH)
    if code != 0:
        say("Cannot reach GitHub: " + out[-300:])
        return 1
    _, before = git(repo, "rev-parse", "HEAD")
    code, out = git(repo, "rebase", "-q", "origin/" + BRANCH)
    if code != 0:
        git(repo, "rebase", "--abort")
        say("Your change conflicts with what is on GitHub. Nothing was pushed; the rebase was undone.")
        say(out[-600:])
        return 1
    _, after = git(repo, "rev-parse", "HEAD")
    _, ahead = git(repo, "rev-list", "--count", "origin/%s..HEAD" % BRANCH)
    if ahead.strip() == "0":
        say("Nothing to push: GitHub already has all of this.")
        return 0
    if tests and before.strip() != after.strip():
        say("4. GitHub had new commits - testing the combined result")
        if not run_tests(repo, say):
            say("Tests fail after combining with GitHub's changes - nothing was pushed.")
            return 1
    say("5. push")
    code, out = git(repo, "push", "-q", "origin", "HEAD:refs/heads/" + BRANCH, timeout=300)
    if code != 0:
        say("Push failed: " + out[-400:])
        return 1
    for mirror in MIRRORS:
        git(repo, "push", "-q", "origin", "HEAD:refs/heads/" + mirror.strip(), timeout=300)
    _, short = git(repo, "rev-parse", "--short=12", "HEAD")
    label = version_label(repo)
    say("  pushed %s%s to %s" % (short.strip(), (" (%s)" % label) if label else "", BRANCH))
    say("6. tell the other machines")
    tell_peers(repo, say)
    say("Shipped %s%s. Every machine runs it after its next LOKI start."
        % ((label + ", ") if label else "", short.strip()))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-m", "--message", default="")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="checkout or agent worktree to ship from")
    ap.add_argument("--check", action="store_true", help="only run the tests")
    ap.add_argument("--only", default="", help="with --check: just these suites (comma list, e.g. test_portal)")
    ap.add_argument("--no-tests", action="store_true", help="skip the tests (not for agents)")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    if args.check:
        if args.only.strip():
            wanted = [s.strip() for s in args.only.split(",") if s.strip()]
            unknown = [s for s in wanted if s not in SUITES]
            if unknown:
                ap.error("unknown suite(s): %s (known: %s)" % (", ".join(unknown), ", ".join(SUITES)))
            SUITES[:] = wanted
        return 0 if run_tests(repo) else 1
    if not args.message.strip():
        ap.error("-m/--message is required: say what changed")
    return ship(repo, args.message.strip(), tests=not args.no_tests)


if __name__ == "__main__":
    sys.exit(main())
