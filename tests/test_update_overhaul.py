"""Patching and updating clients, overhauled after the Mac's white window (2026-10-17).

  1. pre-flight: a new version is tried in a throwaway worktree (LOKI's self-test with this
     machine's Python, every window file present) BEFORE the machine switches to it; a version
     that fails is never applied and goes on the skip list with the reason;
  2. a fresh update is on trial until the engine AND the window work on it (POST /ui/ready); the
     window's rescue screen or silence rolls it back by itself and restarts the whole app;
  3. every update event is in an update history (Settings > Machines & updates).

    python tests/test_update_overhaul.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="loki-upd-"))
sys.path.insert(0, str(REPO / "engine"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_UPDATE_PREFLIGHT"] = "1"
for k in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
    os.environ[k] = "t"
for k in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
    os.environ[k] = "t@t"

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def section(title):
    print("\n" + title)


def sh(cwd, *args):
    proc = subprocess.run(list(args), cwd=str(cwd), capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


if not shutil.which("git"):
    print("SKIP: git is not installed")
    sys.exit(0)

import updater  # noqa: E402

GOOD_APP = ('import sys\nif "--self-test" in sys.argv:\n    print("Loki self-test: OK")\n    raise SystemExit(0)\n')
BAD_APP = ('import sys\nif "--self-test" in sys.argv:\n    print("Loki self-test: FAILED\\n  loki: ModuleNotFoundError: No module named \'nope\'")\n'
           '    raise SystemExit(1)\n')
INDEX = '<!doctype html><script src="/ui/boot.js"></script><link rel="stylesheet" href="/ui/app.css"><script src="/ui/app.js" defer></script>'

ORIGIN = TMP / "github.git"
sh(TMP, "git", "init", "-q", "--bare", "-b", "master", str(ORIGIN))
SEED = TMP / "seed"
SEED.mkdir()
sh(SEED, "git", "init", "-q", "-b", "master")
(SEED / "app" / "ui").mkdir(parents=True)
(SEED / "engine").mkdir()
(SEED / "app" / "loki_app.py").write_text(GOOD_APP, encoding="utf-8")
(SEED / "app" / "ui" / "index.html").write_text(INDEX, encoding="utf-8")
for f in ("boot.js", "app.css", "app.js"):
    (SEED / "app" / "ui" / f).write_text("/* ok */\n", encoding="utf-8")
(SEED / "engine" / "loki.py").write_text("VERSION = 1\n", encoding="utf-8")
(SEED / ".gitignore").write_text("harness_data/\n", encoding="utf-8")
sh(SEED, "git", "add", "-A")
sh(SEED, "git", "commit", "-q", "-m", "v1")
sh(SEED, "git", "remote", "add", "origin", str(ORIGIN))
sh(SEED, "git", "push", "-q", "origin", "master")
MACHINE = TMP / "mac"
sh(TMP, "git", "clone", "-q", str(ORIGIN), str(MACHINE))
updater.REPO_URL = str(ORIGIN)


def publish(path: str, text: str, msg: str) -> str:
    (SEED / path).write_text(text, encoding="utf-8")
    sh(SEED, "git", "add", "-A")
    sh(SEED, "git", "commit", "-q", "-m", msg)
    sh(SEED, "git", "push", "-q", "origin", "master")
    return sh(SEED, "git", "rev-parse", "HEAD")[1]


def head() -> str:
    return sh(MACHINE, "git", "rev-parse", "HEAD")[1]


section("pre-flight: a broken new version is never applied")
v1 = head()
bad = publish("app/loki_app.py", BAD_APP, "v2 broken (an import fails)")
r = updater.update(MACHINE, timeout=60)
check("the machine stays on the version that works", head() == v1 and not r.get("updated"), r)
check("it says why", "failed its self-test" in (r.get("error", "") + r.get("note", "")) and "No module named" in r.get("error", ""), r)
h = updater.health(MACHINE)
check("the broken commit is on the skip list with its reason", any(bad.startswith(c[:12]) for c in h.get("skip", []))
      and "self-test" in h.get("skip_reasons", {}).get(bad[:12], ""), h)
check("the refusal is in the update history", any(e.get("event") == "refused" for e in h.get("history", [])), h.get("history"))
check("no worktree is left behind", "preflight" not in sh(MACHINE, "git", "worktree", "list")[1])

section("pre-flight: a version whose window would not load is refused too")
publish("app/loki_app.py", GOOD_APP, "v3 app fixed")
missing = publish("app/ui/index.html", INDEX + '<script src="/ui/icons.js" defer></script>', "v4 loads a file it forgot")
r = updater.update(MACHINE, timeout=60)
check("a missing window file stops the update", head() == v1 and "window would not load" in r.get("error", "") and "icons.js" in r.get("error", ""), r)

section("pre-flight passes: the good version is applied and goes on trial")
(SEED / "app" / "ui" / "icons.js").write_text("/* ok */\n", encoding="utf-8")
good = publish("app/ui/icons.js", "/* ok */\n", "v5 complete")
r = updater.update(MACHINE, timeout=60)
check("it updates", head() == good and r.get("updated"), r)
check("the note says the pre-flight passed", "pre-flight passed" in r.get("note", ""), r.get("note"))
_cwd = os.getcwd()
os.chdir(MACHINE)
check("the new version is on trial (engine AND window still to prove it)", updater.on_trial(MACHINE))
os.chdir(_cwd)
check("the update is in the history", any(e.get("event") == "updated" for e in updater.health(MACHINE).get("history", [])))

section("the window decides: ready keeps it, a rescue screen or silence rolls back")
import loki_bridge  # noqa: E402


class FakeUpdater:
    def __init__(self):
        self.calls = []

    def mark_good(self):
        self.calls.append("good")

    def rollback(self, why=""):
        self.calls.append("rollback: " + why)
        return {"ok": True}


def reset():
    loki_bridge.UI_STATE["ready"].clear()
    loki_bridge.UI_STATE["rescue"] = ""


reset()
fu, restarts = FakeUpdater(), []
threading.Timer(0.3, loki_bridge.UI_STATE["ready"].set).start()
out = loki_bridge.update_trial_watch(fu, wait_s=10, restart=lambda: restarts.append(1))
check("the window says ready -> the version is good, no restart", out == "good" and fu.calls == ["good"] and not restarts, (out, fu.calls))
reset()
fu, restarts = FakeUpdater(), []
loki_bridge.UI_STATE["rescue"] = "rescue screen shown: app.js did not run"
out = loki_bridge.update_trial_watch(fu, wait_s=10, restart=lambda: restarts.append(1))
check("the rescue screen -> roll back (with the error as the reason) and restart the app",
      out == "rolled back" and fu.calls and "app.js did not run" in fu.calls[0] and restarts == [1], (out, fu.calls))
reset()
fu, restarts = FakeUpdater(), []
out = loki_bridge.update_trial_watch(fu, wait_s=2.5, restart=lambda: restarts.append(1))
check("silence (a white window) -> roll back and restart", out == "rolled back" and "did not become ready" in fu.calls[0]
      and restarts == [1], (out, fu.calls))
reset()

section("rollback for real: back to the last good version, the bad one skipped")
data = updater.health(MACHINE)
data.update({"last_good": v1, "pending": good})
updater._save_health(data, MACHINE)
_cwd = os.getcwd()
res = updater.rollback(MACHINE, why="its window did not become ready in 300 s")
check("the checkout goes back to the last good commit", res.get("ok") and head() == v1, res)
h = updater.health(MACHINE)
check("the bad commit is skipped, with the window's reason", any(good.startswith(c[:12]) for c in h.get("skip", []))
      and "window" in h.get("skip_reasons", {}).get(good[:12], ""), h)
r = updater.update(MACHINE, timeout=60)
check("and the next update does not apply it again", head() == v1 and not r.get("updated"), r)
check("the rollback is in the history", any(e.get("event") == "rolled back" for e in h.get("history", [])))

section("the pieces are wired in")
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
app_js = (REPO / "app" / "ui" / "app.js").read_text(encoding="utf-8")
app_py = (REPO / "app" / "loki_app.py").read_text(encoding="utf-8")
settings = (REPO / "app" / "ui" / "settings.js").read_text(encoding="utf-8")
check("the engine waits for the window before calling an update good (only when the app runs it)",
      "updater.on_trial()" in bridge and "update_trial_watch" in bridge and 'route == "/ui/ready"' in bridge)
check("the window says it is ready", 'api("/ui/ready"' in app_js)
check("the app's pre-flight uses the engine's own Python", "LOKI_ENGINE_PYTHON" in app_py)
check("Settings > Machines & updates shows the trial, the reasons and the history",
      "On trial:" in settings and "Update history on this computer" in settings and "skip_reasons" in settings)
check("the real repo's window files all exist (what the pre-flight checks)", updater.ui_missing(REPO) == [], updater.ui_missing(REPO))
real = subprocess.run([sys.executable, str(REPO / "app" / "loki_app.py"), "--self-test"], cwd=str(REPO), capture_output=True,
                      text=True, timeout=240, env={k: v for k, v in os.environ.items() if not k.startswith("LOKI_")}
                      | {"LOKI_DATA": str(TMP / "selftest"), "LOKI_TIMESFM_APPROVED": "0"})
check("this version passes its own self-test (what other machines run before taking it)",
      real.returncode == 0 and "OK" in real.stdout, (real.stdout + real.stderr)[-400:])

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
