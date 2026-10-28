"""An update never gets stuck on local work (owner 2026-10-27: "windows isnt updating i told u to fix").

The PC sat on "update waiting: local changes to 1 file(s) (engine/opencode_engine.py)" forever: it had an agent's
uncommitted edit AND one local commit, and the updater only carried edits across when there were no local commits.
Real git repos:
  1. local commit + uncommitted edit -> updates; the commit stays on top; the edit is saved (patch + copy) and put back
  2. the edit conflicts with GitHub's change -> still updates to GitHub's version; the edit is saved, never lost
  3. a local commit that conflicts with GitHub -> moves to GitHub's version; the commit is saved as a patch

    python tests/test_updater_unstuck.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_COMMITTER_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_EMAIL", "t@t")):
    os.environ[k] = v
os.environ["LOKI_PEER_UPDATES"] = "off"
import updater  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def sh(cwd, *args):
    p = subprocess.run(list(args), cwd=str(cwd), capture_output=True, text=True)
    return (p.stdout + p.stderr).strip()


def world(name):
    t = Path(tempfile.mkdtemp(prefix="loki-unstuck-%s-" % name))
    origin = t / "github.git"
    sh(t, "git", "init", "-q", "--bare", "-b", "master", str(origin))
    seed = t / "seed"
    sh(t, "git", "clone", "-q", str(origin), str(seed))
    (seed / "engine").mkdir()
    (seed / "engine" / "opencode_engine.py").write_text("A = 1\nB = 2\nC = 3\n")
    (seed / "engine" / "loki.py").write_text("VERSION = 1\n")
    (seed / ".gitignore").write_text("harness_data/\n")
    sh(seed, "git", "add", "-A")
    sh(seed, "git", "commit", "-qm", "v1")
    sh(seed, "git", "push", "-q", "origin", "HEAD:master")
    pc = t / "pc"
    sh(t, "git", "clone", "-q", str(origin), str(pc))
    return t, seed, pc


def kept(pc):
    return list((pc / "harness_data" / "update_kept").rglob("*")) if (pc / "harness_data" / "update_kept").exists() else []


# 1. the PC's case: a local commit + an uncommitted edit that does not clash
t, seed, pc = world("one")
(seed / "engine" / "loki.py").write_text("VERSION = 2\n")
sh(seed, "git", "commit", "-qam", "v2 on GitHub")
sh(seed, "git", "push", "-q", "origin", "HEAD:master")
(pc / "notes.txt").write_text("pc note\n")
sh(pc, "git", "add", "notes.txt")
sh(pc, "git", "commit", "-qm", "a local commit on the PC")
(pc / "engine" / "opencode_engine.py").write_text("A = 1\nB = 20  # agent's edit\nC = 3\n")
res = updater.update(pc)
check("local commit + uncommitted edit: the PC updates (it used to wait forever)",
      res.get("updated") and (pc / "engine" / "loki.py").read_text() == "VERSION = 2\n", res)
check("... the local commit stays on top", (pc / "notes.txt").is_file() and "a local commit" in sh(pc, "git", "log", "-1", "--format=%s"))
check("... the agent's edit is back in the file", "B = 20" in (pc / "engine" / "opencode_engine.py").read_text())
check("... and saved (patch + copy) in harness_data/update_kept", any(p.name == "edits.patch" for p in kept(pc)), kept(pc))

# 2. the edit clashes with GitHub's change to the same line
t, seed, pc = world("two")
(seed / "engine" / "opencode_engine.py").write_text("A = 1\nB = 200  # GitHub\nC = 3\n")
sh(seed, "git", "commit", "-qam", "GitHub changes B")
sh(seed, "git", "push", "-q", "origin", "HEAD:master")
(pc / "engine" / "opencode_engine.py").write_text("A = 1\nB = 20  # agent's edit\nC = 3\n")
res = updater.update(pc)
check("a clashing edit no longer blocks: GitHub's version is installed", res.get("updated")
      and "B = 200" in (pc / "engine" / "opencode_engine.py").read_text(), res)
saved = [p for p in kept(pc) if p.name == "opencode_engine.py"]
check("... the agent's edit is kept whole, never lost", saved and "B = 20  #" in saved[0].read_text(), kept(pc))
check("... no half-merged file left behind", "<<<<<<<" not in (pc / "engine" / "opencode_engine.py").read_text())

# 3. a local commit that conflicts with GitHub
t, seed, pc = world("three")
(seed / "engine" / "loki.py").write_text("VERSION = 3  # GitHub\n")
sh(seed, "git", "commit", "-qam", "GitHub v3")
sh(seed, "git", "push", "-q", "origin", "HEAD:master")
(pc / "engine" / "loki.py").write_text("VERSION = 99  # pc\n")
sh(pc, "git", "commit", "-qam", "pc's own version bump")
res = updater.update(pc)
check("a conflicting local commit no longer blocks: GitHub's version is installed", res.get("updated")
      and "VERSION = 3" in (pc / "engine" / "loki.py").read_text(), res)
check("... the commit is saved as a patch", any(p.suffix == ".patch" and "commits" in p.parts for p in kept(pc)), kept(pc))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
