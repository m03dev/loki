"""Keep agents out of the LOKI that is running - they work in their own folders, changes reach the machines only
through tools/ship.py -> master.

Owner 2026-10-27: "why did it get stuck in the first place ... have foresight and look what other people are doing".
What happened on the PC: a background job edited engine/opencode_engine.py in D:/loki (the running app) and a
self-test job committed "Add selftest_hello.txt" there. Every job folder (harness_data/selftest/..., worktrees, ...)
sits INSIDE LOKI's own git repo, so a plain `git commit` in a job folder lands in the running checkout. The updater
then refused to update (edits) or kept the commit on top (the PC's "patch 609" while the Mac had 608).

What the established tools do, and what LOKI does now:
  * The running app is never edited in place (Chrome / VS Code / Sparkle / Squirrel replace the whole app; Android
    and ChromeOS A/B slots). -> updater mirror mode: each machine runs exactly master, anything local is saved
    whole and set aside (engine/updater.py exact()).
  * Coding agents work in an isolated checkout, never the live one (Claude Code / Codex / Cursor background agents /
    OpenHands use git worktrees or sandboxes). -> improve_loki already uses harness_data/worktrees/<job>; here:
    1. GIT_CEILING_DIRECTORIES=<LOKI folder> for every agent shell: git started anywhere below LOKI's folder can no
       longer find LOKI's own repo (a worktree still finds its own .git first).
    2. OpenCode may not EDIT files in LOKI's folder (harness_data, where job folders and worktrees live, stays open).
    3. OpenCode bash may not run git commands that change LOKI's folder (commit/add/reset/checkout/stash/push...).
LOKI_LIVE_GUARD=0 turns 1-3 off (a developer editing LOKI with an agent on purpose).
"""
from __future__ import annotations

import os
from pathlib import Path

LIVE = Path(__file__).resolve().parent.parent
GIT_WRITES = ("commit", "add", "reset", "checkout", "switch", "restore", "stash", "push", "rebase", "merge", "rm",
              "clean", "apply", "am", "cherry-pick", "revert", "mv", "tag", "branch", "update-ref", "worktree")
BASH_VERBS = ("commit", "add", "reset", "checkout", "switch", "restore", "stash", "push", "rebase", "merge", "clean",
              "cherry-pick", "am", "apply")
BOUNDARY = (" ", "/", "\\", '"', "'", ";", "&")


def on(env: dict | None = None) -> bool:
    return str((env if env is not None else os.environ).get("LOKI_LIVE_GUARD", "1")).strip().lower() \
        not in ("0", "off", "false", "no")


def _variants(root: Path) -> list:
    """How one folder can be written in a command: D:\\loki, D:/loki, /d/loki (Git Bash), any drive case."""
    s = str(root)
    out = [s, s.replace("\\", "/")]
    if len(s) > 2 and s[1] == ":":                       # a Windows drive path
        drive, rest = s[0], s[2:].replace("\\", "/")
        for d in (drive.lower(), drive.upper()):
            out += [d + ":" + rest, d + ":" + rest.replace("/", "\\"), "/" + d.lower() + rest, "/" + d + rest]
    seen, uniq = set(), []
    for v in out:
        v = v.rstrip("/\\")
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def is_live(workspace, root: Path | None = None) -> bool:
    """The job IS working on LOKI's own folder (then the guard stays out of its way: someone chose that)."""
    root = root or LIVE
    try:
        return Path(workspace).resolve() == root.resolve()
    except (OSError, TypeError):
        return False


def git_env(env: dict, root: Path | None = None) -> dict:
    """Add LOKI's folder to GIT_CEILING_DIRECTORIES (keeps any the owner set)."""
    root = root or LIVE
    if not on(env):
        return env
    have = [p for p in str(env.get("GIT_CEILING_DIRECTORIES") or "").split(os.pathsep) if p]
    if str(root) not in have:
        env["GIT_CEILING_DIRECTORIES"] = os.pathsep.join(have + [str(root)])
    return env


def edit_rules(workspace="", root: Path | None = None, env: dict | None = None):
    """OpenCode `permission.edit`: allowed everywhere it was before, except LOKI's running code. Last match wins."""
    root = root or LIVE
    if not on(env) or (workspace and is_live(workspace, root)):
        return "allow"
    rules: dict = {"*": "allow"}
    for v in _variants(root):
        sep = "\\" if "\\" in v else "/"
        rules[v + sep + "*"] = "deny"
        rules[v + sep + "harness_data" + sep + "*"] = "allow"
    if workspace:
        for v in _variants(Path(workspace)):
            sep = "\\" if "\\" in v else "/"
            rules[v + sep + "*"] = "allow"
            if is_home_library(workspace):
                # no look-alike LOKI in the owner's library: on the PC agents built Home/engine/*.py,
                # Home/harness_data/.venv and fake job logs there and "proved" fixes against them (2026-10-27/28)
                for fake in ("engine", "harness_data", "tests"):
                    rules[v + sep + fake + sep + "*"] = "deny"
    return rules


def is_home_library(workspace) -> bool:
    """The owner's picture/model library (~/LOKI Projects/Home) - not a code project, never a copy of LOKI."""
    try:
        p = Path(workspace)
        return p.name.lower() == "home" and p.parent.name.lower() == "loki projects"
    except TypeError:
        return False


def bash_rules(workspace="", root: Path | None = None, env: dict | None = None) -> dict:
    """OpenCode bash deny rules: a git command that changes LOKI's own folder."""
    root = root or LIVE
    if not on(env) or (workspace and is_live(workspace, root)):
        return {}
    rules = {}
    seen = set()
    for v in _variants(root):          # OpenCode matches case-insensitively on Windows: one spelling per form
        if v.lower() in seen:
            continue
        seen.add(v.lower())
        for end in (" ", "\\" if "\\" in v else "/"):    # the folder itself, never D:/loki-other
            for verb in BASH_VERBS:
                rules["*%s%s*git *%s*" % (v, end, verb)] = "deny"
    return rules


def touches_live(command: str, workspace="", root: Path | None = None, env: dict | None = None) -> str:
    """For LOKI's built-in shell tool: a reason when `command` would change LOKI's own repo, else ""."""
    root = root or LIVE
    if not on(env) or (workspace and is_live(workspace, root)):
        return ""
    text = str(command or "")
    low = text.lower()
    if "git" not in low:
        return ""
    import re  # pylint: disable=import-outside-toplevel
    verbs = re.compile(r"\bgit\b[^;&|]*\b(%s)\b" % "|".join(re.escape(v) for v in GIT_WRITES))
    hit = re.compile("(%s)(%s|$)" % ("|".join(re.escape(v.lower()) for v in _variants(root)),
                                     "|".join(re.escape(e) for e in BOUNDARY)))
    if hit.search(low) and verbs.search(low):
        return ("refused: that git command would change LOKI's running copy (%s). Work in your own folder; "
                "changes to LOKI go through improve_loki / ship_loki (its own worktree -> master)." % root)
    return ""
