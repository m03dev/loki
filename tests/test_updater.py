"""Same version everywhere: the updater, tools/ship.py and the peer version check.

    python tests/test_updater.py

Runs real git against a throwaway "GitHub" (a bare repository in a temp folder): a
plain-copy folder becomes a checkout, updates are fast-forward only and never overwrite
local work, old macos-app checkouts move to master, ship.py refuses to push failing or
conflicting changes, and linked machines are told about a new version.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "engine"))   # engine/peer_link.py, not tools/peer_link.py

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:300]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


def sh(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_TERMINAL_PROMPT="0")
    proc = subprocess.run(list(args), cwd=str(cwd), capture_output=True, text=True, env=env)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


if not shutil.which("git"):
    print("SKIP: git is not installed")
    sys.exit(0)

for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
    os.environ[key] = "t"
for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
    os.environ[key] = "t@t"

ORIGIN = TMP / "github.git"
sh(TMP, "git", "init", "-q", "--bare", "-b", "master", str(ORIGIN))
SEED = TMP / "seed"
SEED.mkdir()
sh(SEED, "git", "init", "-q", "-b", "master")
(SEED / "engine").mkdir()
(SEED / "engine" / "loki.py").write_text("VERSION = 1\n", encoding="utf-8")
(SEED / "README.md").write_text("loki\n", encoding="utf-8")
(SEED / "tests").mkdir()
(SEED / "tests" / "test_loki.py").write_text("print('1 passed, 0 failed')\n", encoding="utf-8")
(SEED / ".gitignore").write_text("harness_data/\n", encoding="utf-8")
sh(SEED, "git", "add", "-A")
sh(SEED, "git", "commit", "-q", "-m", "v1")
sh(SEED, "git", "remote", "add", "origin", str(ORIGIN))
sh(SEED, "git", "push", "-q", "origin", "master")
sh(SEED, "git", "push", "-q", "origin", "master:macos-app")

import updater  # noqa: E402

updater.REPO_URL = str(ORIGIN)


def publish(text: str, path: str = "engine/loki.py") -> str:
    sh(SEED, "git", "pull", "-q", "--rebase", "origin", "master")
    (SEED / path).write_text(text, encoding="utf-8")
    sh(SEED, "git", "commit", "-q", "-am", text.strip()[:30])
    sh(SEED, "git", "push", "-q", "origin", "master")
    return sh(SEED, "git", "rev-parse", "--short=12", "HEAD")[1]


section("a plain copy (no git history) becomes a checkout in place")
MAC = TMP / "mac-copy"
shutil.copytree(SEED, MAC, ignore=shutil.ignore_patterns(".git"))
(MAC / "README.md").unlink()                                   # a file the copy lost
(MAC / "harness_data").mkdir()
(MAC / "harness_data" / ".env").write_text("SECRET=keep\n", encoding="utf-8")
(MAC / "notes.txt").write_text("mine\n", encoding="utf-8")     # an untracked file of the user's
check("the copy starts without git", not updater.is_checkout(MAC))
note = updater.ensure_checkout(MAC)
check("it becomes a checkout", updater.is_checkout(MAC), note)
check("on branch master", updater.version(MAC)["branch"] == "master", updater.version(MAC))
check("a missing file is restored", (MAC / "README.md").is_file())
check("the user's data is untouched", (MAC / "harness_data" / ".env").read_text() == "SECRET=keep\n")
check("the user's own files are kept", (MAC / "notes.txt").is_file())
check("nothing differs from GitHub afterwards", updater.dirty_files(MAC) == [], updater.dirty_files(MAC))

section("an OLD copy is brought up to date; real local edits are kept")
OLD = TMP / "old-copy"
shutil.copytree(SEED, OLD, ignore=shutil.ignore_patterns(".git"))   # files of v1
publish("VERSION = 'newer'\n")                                         # GitHub moves on
(OLD / "README.md").write_text("my own notes in the readme\n", encoding="utf-8")
note = updater.ensure_checkout(OLD)
check("a file that is just an older version is updated", (OLD / "engine" / "loki.py").read_text() == "VERSION = 'newer'\n",
      (OLD / "engine" / "loki.py").read_text())
check("a file the user changed is kept", "my own notes" in (OLD / "README.md").read_text())
check("...and reported", "1 file(s) differ" in note, note)

section("updates are fast-forward only")
latest = publish("VERSION = 2\n")
state = updater.check(MAC)
check("check sees the new commits", state["ok"] and state["behind"] >= 1 and state["can_update"], state)
result = updater.update(MAC)
check("update applies it", result["updated"] and (MAC / "engine" / "loki.py").read_text() == "VERSION = 2\n", result)
check("the version is GitHub's", updater.version(MAC)["commit"] == latest)
check("a second update is a no-op", not updater.update(MAC)["updated"])

(MAC / "engine" / "loki.py").write_text("VERSION = 'my local edit'\n", encoding="utf-8")
publish("VERSION = 3\n")
result = updater.update(MAC)
check("local changes are never overwritten", not result["updated"]
      and "my local edit" in (MAC / "engine" / "loki.py").read_text(), result)
check("...and it says why", "local changes" in result["note"], result["note"])
sh(MAC, "git", "checkout", "--", "engine/loki.py")
check("once the edit is gone it updates", updater.update(MAC)["updated"])

(MAC / "local.txt").write_text("x\n", encoding="utf-8")
sh(MAC, "git", "add", "local.txt")
sh(MAC, "git", "commit", "-q", "-m", "unpushed")
publish("VERSION = 4\n")
result = updater.update(MAC)
check("unpushed commits block a diverged update", not result["updated"] and "push them" in result["note"], result)
sh(MAC, "git", "reset", "-q", "--hard", "origin/master")

section("an untracked file the update would add is kept, not lost")
(MAC / "HANDOFF.md").write_text("my own handoff notes\n", encoding="utf-8")
(SEED / "HANDOFF.md").write_text("tracked handoff\n", encoding="utf-8")
sh(SEED, "git", "pull", "-q", "--rebase", "origin", "master")
sh(SEED, "git", "add", "HANDOFF.md")
sh(SEED, "git", "commit", "-q", "-m", "add handoff")
sh(SEED, "git", "push", "-q", "origin", "master")
result = updater.update(MAC)
check("the update still applies", result["updated"] and (MAC / "HANDOFF.md").read_text() == "tracked handoff\n", result)
check("the user's file is kept beside it", (MAC / "HANDOFF.md.before-update").read_text() == "my own handoff notes\n")

section("an old macos-app checkout moves to master")
PC = TMP / "pc"
sh(TMP, "git", "clone", "-q", "-b", "macos-app", str(ORIGIN), str(PC))
publish("VERSION = 5\n")
result = updater.update(PC)
check("it is moved to master and updated", updater.version(PC)["branch"] == "master"
      and (PC / "engine" / "loki.py").read_text() == "VERSION = 5\n", result)
check("it says it moved", "moved from macos-app" in result["note"], result["note"])

section("check_now never changes files")
publish("VERSION = 6\n")
updater.REPO = PC
status = updater.check_now()
check("an update is reported as waiting", status["update_available"] and "restart LOKI" in status["note"], status)
check("...but not applied while running", (PC / "engine" / "loki.py").read_text() == "VERSION = 5\n")
updater.REPO = REPO
updater.update(PC)

section("tools/ship.py: test, commit, catch up, push")
sys.path.insert(1, str(REPO / "tools"))
import ship  # noqa: E402

ship.SUITES = ["test_loki"]
ship.MIRRORS = []
ship.tell_peers = lambda repo, say=print: []
WORK = TMP / "work"
sh(TMP, "git", "clone", "-q", str(ORIGIN), str(WORK))
(WORK / "feature.txt").write_text("new\n", encoding="utf-8")
lines = []
code = ship.ship(WORK, "add a feature", say=lines.append)
check("a passing change is pushed", code == 0 and "feature.txt" in sh(TMP, "git", "--git-dir", str(ORIGIN), "ls-tree",
      "-r", "--name-only", "master")[1], lines)

(WORK / "tests" / "test_loki.py").write_text("import sys; print('0 passed, 1 failed'); sys.exit(1)\n", encoding="utf-8")
before = sh(TMP, "git", "--git-dir", str(ORIGIN), "rev-parse", "master")[1]
lines = []
code = ship.ship(WORK, "break the tests", say=lines.append)
check("a failing change is NOT pushed", code == 1 and sh(TMP, "git", "--git-dir", str(ORIGIN), "rev-parse", "master")[1] == before, lines)
check("...and nothing was committed", "Tests failed - nothing was committed" in "\n".join(lines))
sh(WORK, "git", "checkout", "--", "tests/test_loki.py")

publish("VERSION = 'from the pc'\n")
(WORK / "engine" / "loki.py").write_text("VERSION = 'from the mac'\n", encoding="utf-8")
lines = []
code = ship.ship(WORK, "conflicting edit", say=lines.append)
check("a conflict with GitHub is NOT pushed", code == 1 and "conflicts" in "\n".join(lines), lines)
check("...and the rebase is undone", not (WORK / ".git" / "rebase-merge").exists() and not (WORK / ".git" / "rebase-apply").exists())
sh(WORK, "git", "reset", "-q", "--hard", "origin/master")
sh(WORK, "git", "pull", "-q", "origin", "master")

publish("VERSION = 'newer upstream'\n")
(WORK / "other.txt").write_text("independent\n", encoding="utf-8")
lines = []
code = ship.ship(WORK, "independent change", say=lines.append)
check("an independent change is rebased onto GitHub's and pushed", code == 0, lines)
check("...after re-running the tests on the combined result", any("testing the combined result" in l for l in lines), lines)

WT = TMP / "agent-worktree"
sh(WORK, "git", "worktree", "add", "-q", "-b", "loki/job-1", str(WT))
(WT / "agent.txt").write_text("made by an agent\n", encoding="utf-8")
code = ship.ship(WT, "agent change", say=lambda *_: None)
check("an agent's worktree branch ships to master", code == 0 and "agent.txt" in sh(TMP, "git", "--git-dir", str(ORIGIN),
      "ls-tree", "-r", "--name-only", "master")[1])

section("machines compare versions and tell each other")
import peer_link  # noqa: E402

called = []
updater.check_now = lambda: called.append("check") or {}
mine = updater.version()["commit"]
differ = peer_link.compare_versions([{"ok": True, "name": "pc", "hello": {"version": {"commit": "abc123"}}}])
check("a different version on a linked machine is noticed", mine == "" or (differ and differ[0]["name"] == "pc"), differ)
same = peer_link.compare_versions([{"ok": True, "name": "pc", "hello": {"version": {"commit": mine}}}])
check("the same version is not", same == [])
src = (REPO / "engine" / "peers.py").read_text(encoding="utf-8")
check("a linked machine can be told to check for an update (signed route)", '"/peer/update"' in src)
check("hello reports this machine's version", '"version": build' in (REPO / "engine" / "peer_link.py").read_text(encoding="utf-8"))

section("wired into the app, the engine and LOKI's own tools")
app = (REPO / "app" / "loki_app.py").read_text(encoding="utf-8")
check("the app updates before starting the engine", "auto_update()" in app and "updater.update(REPO" in app)
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the engine checks GitHub in the background", "updater.run_forever" in bridge)
check("/health reports the version", '"update": update_status()' in bridge)
loki_src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("LOKI can improve its own code", "def improve_loki" in loki_src and '"improve_loki"' in loki_src)
check("LOKI can ship its own code through ship.py", "def ship_loki" in loki_src and "tools\" / \"ship.py" in loki_src)
check("Ask and Plan modes cannot change or push LOKI", 'DELEGATING = {"delegate", "improve_loki", "ship_loki"}' in loki_src)
workflow = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
check("CI runs the tests on macOS and Windows on every push", "macos-latest" in workflow and "windows-latest" in workflow)
check("an AGENTS.md tells every agent the rules", (REPO / "AGENTS.md").is_file())

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
