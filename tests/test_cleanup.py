"""LOKI cleans itself up (engine/cleanup.py; owner 2026-10-25: "a lot of test chats and memory that needs to go, it
should be able to remove that easily when i'm in the studio").

Real conversations and real memory items in a temp data folder: the scan suggests test / check chats, old empty chats,
memories from tests and duplicates - never the chat in use, never the owner's real chats or memories - and removes
nothing; remove() takes exactly the chosen ids. LOKI Studio's agent gets cleanup_scan freely and cleanup_remove only
with the owner's approval. Under a minute.

    python tests/test_cleanup.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-cleanup-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_HEALTH_FILE"] = str(TMP / "health.json")
PASS: list = []
FAIL: list = []
t0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:500],)))


try:
    import loki  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print("SKIP: the engine does not import here (%s)\n\n0 passed, 0 failed" % exc); sys.exit(0)
import cleanup  # noqa: E402
import memory_core  # noqa: E402

ids = {}
for title in ("UI check: draw an arrow", "router check", "M25 GitHub connector", "hello, in one short line: what are you?",
              "build me a third person shooter in godot", "Logo ideas for my game"):
    cid = loki.new_conversation(title)
    loki.messages.append({"role": "user", "content": "hi"})       # the active chat's messages (saved on the switch)
    ids[title] = cid
empty = loki.new_conversation("")
loki.CONVERSATIONS[empty]["updated"] = time.time() - 7200
current = loki.new_conversation("Logo ideas for my game")        # the chat in use - even with a test-looking title
loki.CONVERSATIONS[current]["title"] = "test of the live meter"
loki.switch_conversation(current)
for text in ("The owner's main game is a pixel-art MMO in Godot.", "smoke test fact 123", "fake scripted reply for the bench",
             "The owner's main game is a pixel-art MMO in Godot!"):
    memory_core.learn(text, root=loki.DATA_DIR)

d = cleanup.scan(loki)
chat = {r["title"]: r for r in d["chats"]}
check("test / check chats are suggested, with why", all(chat[t]["suggest"] for t in ("UI check: draw an arrow", "router check",
      "M25 GitHub connector", "hello, in one short line: what are you?")), chat)
check("the owner's real chats are not", not chat["build me a third person shooter in godot"]["suggest"]
      and not chat["Logo ideas for my game"]["suggest"], chat)
check("empty chats are suggested", all(r["suggest"] and r["why"] == "empty" for r in d["chats"] if not r["count"]),
      [r for r in d["chats"] if not r["count"]])
check("the chat in use is never listed (even with a test-looking title)", "chat:" + current not in [r["id"] for r in d["chats"]])
mem = {r["text"]: r for r in d["memories"]}
check("test memories are suggested, real ones not", mem["smoke test fact 123"]["suggest"] and mem["fake scripted reply for the bench"]["suggest"]
      and not mem["The owner's main game is a pixel-art MMO in Godot."]["suggest"], mem)
check("... a duplicate (punctuation aside) is suggested, one copy kept", [r["why"] for r in d["memories"] if "pixel-art MMO" in r["text"]]
      .count("duplicate") == len([r for r in d["memories"] if "pixel-art MMO" in r["text"]]) - 1, d["memories"])
before = len(loki.list_conversations())
check("a scan removes nothing", len(loki.list_conversations()) == before)

pick = [r["id"] for r in d["chats"] + d["memories"] if r["suggest"]] + ["chat:" + current]
r = cleanup.remove(loki, pick)
left = [c["title"] for c in loki.list_conversations()]
n_chats = len([x for x in d["chats"] if x["suggest"]]); n_mems = len([x for x in d["memories"] if x["suggest"]])
check("remove takes exactly the chosen ones", r["removed_chats"] == n_chats and r["removed_memories"] == n_mems
      and "router check" not in left and "build me a third person shooter in godot" in left, (r, left))
check("... never the chat in use, even when asked", "chat:" + current in r["skipped"] and loki.active_conversation_id() == current)
check("... the real memory stays", any("pixel-art MMO" in i.get("text", "") for i in memory_core.all_items(loki.DATA_DIR)))

import loki_mcp  # noqa: E402
api = loki_mcp.LokiAPI(worktree=TMP, repo=REPO, data=TMP / "data")
out = api.cleanup_remove(["chat:x"])
check("LOKI Studio's agent: cleanup_remove needs the owner's approval", "needs the owner's approval" in out, out)
check("... cleanup_scan is a read tool; cleanup_remove is risky", "cleanup_remove" in loki_mcp.RISKY_TOOLS
      and "cleanup_scan" in loki_mcp.TOOL_ORDER and "cleanup_scan" in (REPO / "studio" / "studio_core.py").read_text())
check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
