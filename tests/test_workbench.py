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

section("options: 3-4 readings of an open request (engine/options.py)")
import asyncio  # noqa: E402
import options  # noqa: E402
check("an open request looks open", options.looks_open("make me a game") and options.looks_open("improve the website"))
check("a specific one does not", not options.looks_open("fix the bug in src/app.py line 40")
      and not options.looks_open("read https://example.com and summarise it"))
check("a plain question gets a plain answer", not options.looks_open("what is the capital of France?"))
check("asking for ideas always offers", options.looks_open("give me some ideas"))
check("off means never, force means yes", not options.should_offer("make me a game", env={"LOKI_OPTIONS": "off"})
      and options.should_offer("fix line 40 in a.py", force=True))
good = ('<think>hmm</think> Sure: {"options": [{"title": "Browser game", "meaning": "m", "plan": "p", "prompt": "Build a browser game"},'
        ' {"title": "Godot prototype", "prompt": "Make a Godot 3D prototype"}, {"title": "dup", "prompt": "build a browser game"},'
        ' {"title": "GDD", "prompt": "Write a design doc"}, {"title": "Fifth", "prompt": "e"}, {"title": "Sixth", "prompt": "f"}]}')
got = options.parse(good)
check("the reply is parsed, duplicates dropped, at most 4", [o["title"] for o in got] == ["Browser game", "Godot prototype", "GDD", "Fifth"], got)
check("one option is not a choice", options.parse('{"options": [{"title": "a", "prompt": "b"}]}') == [])
check("garbage gives none", options.parse("I think you mean a game.") == [])


async def _fake(prompt_text):
    assert "make me a game" in prompt_text
    return good


async def _boom(prompt_text):
    raise RuntimeError("no model")
check("suggest() asks once and returns the options", len(asyncio.run(options.suggest("make me a game", _fake))["options"]) == 4)
check("a failing model just means no options", asyncio.run(options.suggest("make me a game", _boom))["options"] == [])
check("the window offers them before sending", "Workbench.offerOptions(text, false)" in app_js and "offerOptions" in js)
check("/options is a command", 'name: "options"' in js)

section("the drawing pad (app/ui/sketch.js)")
sk = (ui / "sketch.js").read_text(encoding="utf-8")
check("index.html loads sketch.js", "/ui/sketch.js" in html)
check("pen pressure, undo, attach", "e.pressure" in sk and "Undo" in sk and "/sketch" in sk)
check("the drawing rides along with the next message", "Sketch.take(text)" in app_js)
bridge_src = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the engine saves it as a PNG in the workspace", 'route == "/sketch"' in bridge_src and 'b"\\x89PNG"' in bridge_src)
if shutil.which("node"):
    proc = subprocess.run(["node", "--check", str(ui / "sketch.js")], capture_output=True, text=True)
    check("sketch.js parses", proc.returncode == 0, proc.stderr)

section("LOKI World: benches face the pool")
wj = (ui / "world.js").read_text(encoding="utf-8")
check("benches are built in their own frame (length along the ring)", "function benchFrame(b)" in wj and "benchFrame(b)" in wj.split("function seatPos")[1][:200])

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
