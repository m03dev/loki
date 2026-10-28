"""Agents can no longer change the LOKI that is running (the PC's stray "Add selftest_hello.txt" commit, 2026-10-27).

Real git: a "LOKI folder" repo with a job folder inside harness_data, like the PC's self-test job.
  1. without the guard, `git commit` in the job folder lands in LOKI's repo (what happened)
  2. with live_guard.git_env, git in the job folder cannot find LOKI's repo -> nothing is committed there
  3. a job worktree (harness_data/worktrees/<job>) still finds its own repo and can commit
  4. OpenCode's config: edits to LOKI's code denied, harness_data + the job folder allowed; git writes on LOKI denied
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import live_guard  # noqa: E402

FAILS = []
PASSES = 0


def check(name, ok, detail=""):
    global PASSES
    if ok:
        PASSES += 1
        print("  PASS", name)
    else:
        FAILS.append(name)
        print("  FAIL", name, " <-", str(detail)[:200])


def git(cwd, *args, env=None):
    e = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    e.pop("GIT_CEILING_DIRECTORIES", None)
    if env:
        e.update(env)
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=e)
    return p.returncode, (p.stdout + p.stderr).strip()


tmp = Path(tempfile.mkdtemp())
live = tmp / "loki"
(live / "engine").mkdir(parents=True)
(live / "engine" / "loki.py").write_text("VERSION = 1\n")
(live / ".gitignore").write_text("harness_data/\n")
git(live, "init", "-q", "-b", "master")
git(live, "add", "-A")
git(live, "commit", "-q", "-m", "seed")
head0 = git(live, "rev-parse", "HEAD")[1]
job = live / "harness_data" / "selftest" / "day" / "write"
job.mkdir(parents=True)

# 1. the hole
(job / "selftest_hello.txt").write_text("LOKI self-test OK\n")
code, out = git(job, "rev-parse", "--show-toplevel")
check("without the guard a job folder inside LOKI finds LOKI's own repo (how the PC got its stray commit)",
      code == 0 and Path(out).resolve() == live.resolve(), out)

# 2. the guard
env = live_guard.git_env({}, root=live)
code, out = git(job, "rev-parse", "--show-toplevel", env=env)
check("with the guard git in the job folder cannot find LOKI's repo", code != 0, out)
git(job, "add", "-A", env=env)
git(job, "commit", "-q", "-m", "Add selftest_hello.txt", env=env)
check("... so an agent's `git add && git commit` there never lands in LOKI",
      git(live, "rev-parse", "HEAD")[1] == head0)
code, out = git(job, "init", "-q", env=env)
git(job, "add", "-A", env=env)
code, _ = git(job, "commit", "-q", "-m", "job's own repo", env=env)
check("... a job may still make its OWN repo in its folder and commit there", code == 0)
check("... and LOKI's repo is still untouched", git(live, "rev-parse", "HEAD")[1] == head0)

# 3. worktrees keep working
wt = live / "harness_data" / "worktrees" / "job1"
git(live, "worktree", "add", "-q", "-b", "loki/job1", str(wt))
(wt / "engine" / "loki.py").write_text("VERSION = 2\n")
code, out = git(wt, "commit", "-q", "-am", "improve", env=env)
check("an improve_loki worktree still commits on its own branch", code == 0, out)
check("... the running checkout's master is untouched", git(live, "rev-parse", "master")[1] == head0)

# 4. OpenCode rules
rules = live_guard.edit_rules(str(job), root=live, env={})
deny_key = str(live).replace("\\", "/") + "/*"
check("OpenCode: edits to LOKI's own folder are denied", rules.get(deny_key) == "deny", rules)
check("OpenCode: harness_data (job folders, worktrees) stays editable",
      rules.get(str(live).replace("\\", "/") + "/harness_data/*") == "allow", rules)
check("OpenCode: the job's own folder is editable", rules.get(str(job).replace("\\", "/") + "/*") == "allow")
check("OpenCode: deny rules come before the allows that re-open folders (last match wins)",
      list(rules).index(deny_key) < list(rules).index(str(live).replace("\\", "/") + "/harness_data/*"))
br = live_guard.bash_rules(str(job), root=live, env={})
check("OpenCode: `git -C <LOKI> commit` is denied", ("*%s *git *commit*" % str(live).replace("\\", "/")) in br, list(br)[:3])
check("a sibling folder with a longer name (D:/loki-other) is not LOKI",
      not live_guard.touches_live("git -C %s-other commit -am x" % live, str(job), root=live, env={}))
check("a job that IS working on LOKI's folder on purpose is left alone",
      live_guard.edit_rules(str(live), root=live, env={}) == "allow" and not live_guard.bash_rules(str(live), root=live, env={}))
check("LOKI_LIVE_GUARD=0 turns it off", live_guard.edit_rules(str(job), root=live, env={"LOKI_LIVE_GUARD": "0"}) == "allow")
win = live_guard._variants(Path("D:\\loki")) if os.name != "nt" else []
check("Windows spellings are all covered (D:\\loki, D:/loki, /d/loki)",
      os.name == "nt" or {"D:\\loki", "D:/loki", "/d/loki", "d:/loki"} <= set(win), win)
check("the built-in shell tool refuses `git -C <LOKI> commit`",
      bool(live_guard.touches_live("git -C %s commit -am x" % live, str(job), root=live, env={})))
check("... but not an ordinary git command in the job folder",
      not live_guard.touches_live("git status && git commit -am x", str(job), root=live, env={}))

print("\n%d passed, %d failed" % (PASSES, len(FAILS)))
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    sys.exit(1)
