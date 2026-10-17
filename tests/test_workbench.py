"""Workbench tests: checkpoints, rewind, @file mentions and file search (engine/workbench.py),
plus the UI wiring for /commands (app/ui/workbench.js).

    python tests/test_workbench.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import workbench  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:240]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


TMP = Path(tempfile.mkdtemp(prefix="loki-wb-"))
WS, STATE = TMP / "ws", TMP / "state"
(WS / "src").mkdir(parents=True)
STATE.mkdir()
(WS / "src" / "cart.py").write_text("def total(cart):\n    return sum(cart)\n", encoding="utf-8")
(WS / "README.md").write_text("shop\n", encoding="utf-8")
(WS / "node_modules").mkdir()
(WS / "node_modules" / "huge.js").write_text("x" * 100, encoding="utf-8")

if not shutil.which("git"):
    print("SKIP: git is not installed")
    sys.exit(0)

section("checkpoints live in a private store, never in the project")
cps = workbench.Checkpoints(WS, STATE / "checkpoints.git")
first = cps.take("before the change")
check("a checkpoint is taken", bool(first.get("id")), first)
check("the project folder does NOT become a git repository", not (WS / ".git").exists())
check("an unchanged workspace does not pile up checkpoints", cps.take("again")["id"] == first["id"])

section("what a request changed")
(WS / "src" / "cart.py").write_text("def total(cart, discount=0):\n    return max(0, sum(cart) - discount)\n", encoding="utf-8")
(WS / "NOTES.md").write_text("new\n", encoding="utf-8")
changed = cps.changes(first["id"])
paths = {f["path"] for f in changed["files"]}
check("changed and new files are listed with line counts", paths == {"src/cart.py", "NOTES.md"}, changed["files"])
check("a unified diff comes with it", "+def total(cart, discount=0):" in changed["diff"] and "-def total(cart):" in changed["diff"])
check("skipped folders (node_modules...) are never snapshotted", "node_modules" not in changed["diff"])

section("rewind, and undo the rewind")
back = cps.rewind(first["id"])
check("rewind puts the file back", back["ok"] and "discount" not in (WS / "src" / "cart.py").read_text())
check("...removes files the request created", not (WS / "NOTES.md").exists() and back["removed"] == ["NOTES.md"], back)
check("...and keeps the user's other files", (WS / "README.md").read_text() == "shop\n")
again = cps.rewind(back["undo"])
check("the rewind itself can be undone", again["ok"] and "discount" in (WS / "src" / "cart.py").read_text() and (WS / "NOTES.md").exists())
check("an unknown checkpoint is refused", not cps.rewind("nope")["ok"])
check("the list is newest first", cps.list()[0]["kind"] == "safety")

section("@file mentions")
text, attached = workbench.expand_mentions("why is @src/cart.py wrong? see @src/ too", WS)
check("@file attaches that file's contents", attached == ["src/cart.py", "src/"] and "def total(cart, discount=0)" in text, attached)
check("...a folder gets a listing", "cart.py" in text.split("--- @src/ ---")[1])
_, outside = workbench.expand_mentions("read @../../etc/passwd please", WS)
check("nothing outside the workspace is attached", outside == [])
same, none = workbench.expand_mentions("email me@example.com about it", WS)
check("an e-mail address is not a mention", none == [] and same == "email me@example.com about it")

section("file search for the @ picker")
check("finds by a fragment", workbench.search_files(WS, "cart") == ["src/cart.py"])
check("finds by letters in order", "src/cart.py" in workbench.search_files(WS, "scp"))
check("skips node_modules", not any("node_modules" in p for p in workbench.search_files(WS, "huge")))

section("the UI wiring")
ui = REPO / "app" / "ui"
js = (ui / "workbench.js").read_text(encoding="utf-8")
app_js = (ui / "app.js").read_text(encoding="utf-8")
html = (ui / "index.html").read_text(encoding="utf-8")
check("index.html loads workbench.js and glass.css", "/ui/workbench.js" in html and "/ui/glass.css" in html)
check("the composer hands /commands to the workbench before sending", "Workbench.handleSlash(text)" in app_js)
check("after a reply the changed files are offered for review/rewind", "Workbench.afterReply(data)" in app_js)
check("the commands exist", all(('name: "%s"' % c) in js for c in ("help", "plan", "build", "review", "rewind", "bg", "team", "model", "test", "commit")))
if shutil.which("node"):
    proc = subprocess.run(["node", "--check", str(ui / "workbench.js")], capture_output=True, text=True)
    check("workbench.js parses", proc.returncode == 0, proc.stderr)

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
