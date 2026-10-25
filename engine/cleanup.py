"""LOKI cleans itself up (owner 2026-10-25: "i want loki to clean itself up - there's a lot of test chats and memory
that needs to go, it should be able to remove that easily when i'm in the studio").

  scan(agent)                  what could go, each with WHY: test / check chats (titles like "UI check", "router
                               check", "M25 ...", "hello, in one short line"), empty chats, and memories that came from
                               tests or checks (test, smoke, probe, fake, scripted, dummy, lorem ...) or are exact
                               duplicates. Nothing is removed by a scan.
  remove(agent, ids)           removes exactly those ids ("chat:<id>", "memory:<id>"); the chat in use is never removed
  GET  /cleanup                 the scan        (LOKI Studio's Clean up panel, LOKI's Settings, the LOKI MCP tool)
  POST /cleanup/remove {ids}    the removal     (the window asks the owner first; the MCP tool is a risky tool)
"""
from __future__ import annotations

import re
from typing import Any

TEST_TITLE = re.compile(r"\b(test|tests|testing|check|smoke|probe|ping|demo|debug|scratch|sanity|router|bench|"
                        r"benchmark|sample|dummy|fake|lorem|ui check|m\d{2}|bonsai|long[- ]context|hello,? in one)\b", re.I)
TEST_MEMORY = re.compile(r"\b(test(ing)?|smoke|probe|fake|scripted|dummy|lorem|foo|bar baz|placeholder|example\.com|"
                         r"self[- ]test|unit test|fixture)\b", re.I)


def _memories(agent: Any) -> list:
    try:
        import memory_core  # pylint: disable=import-outside-toplevel
        return memory_core.all_items(getattr(agent, "DATA_DIR", None))
    except Exception:  # noqa: BLE001
        return []


def scan(agent: Any) -> dict:
    current = agent.active_conversation_id()
    chats = []
    for c in agent.list_conversations():
        if c["id"] == current:
            continue
        title = str(c.get("title") or "")
        why = ""
        if not c.get("count"):
            why = "empty"
        elif TEST_TITLE.search(title):
            why = "looks like a test or a check"
        chats.append({"id": "chat:" + c["id"], "title": title or "New chat", "count": c.get("count", 0),
                      "updated": c.get("updated", 0), "why": why, "suggest": bool(why)})
    mems, seen = [], {}
    for m in _memories(agent):
        text = str(m.get("text") or "")
        norm = re.sub(r"\W+", " ", text.lower()).strip()
        why = ""
        if norm and norm in seen:
            why = "duplicate"
        elif TEST_MEMORY.search(text) or str(m.get("source") or "").lower() in ("test", "bench", "scripted"):
            why = "looks like it came from a test"
        seen.setdefault(norm, m.get("id"))
        mems.append({"id": "memory:" + str(m.get("id")), "text": text[:300], "kind": m.get("kind") or m.get("tier") or "",
                     "why": why, "suggest": bool(why)})
    return {"ok": True, "chats": chats, "memories": mems,
            "suggested": sum(1 for x in chats + mems if x["suggest"]), "current_chat": current}


def remove(agent: Any, ids: list) -> dict:
    current = "chat:" + str(agent.active_conversation_id())
    gone_chats, gone_mems, skipped = [], [], []
    for raw in ids or []:
        rid = str(raw)
        if rid == current:
            skipped.append(rid)
            continue
        if rid.startswith("chat:"):
            if agent.delete_conversation(rid[5:]):
                gone_chats.append(rid)
        elif rid.startswith("memory:"):
            try:
                import memory_core  # pylint: disable=import-outside-toplevel
                out = memory_core.forget(rid[7:], root=getattr(agent, "DATA_DIR", None))
                if out.get("ok") and out.get("forgotten"):
                    gone_mems.append(rid)
            except Exception:  # noqa: BLE001
                skipped.append(rid)
    return {"ok": True, "removed_chats": len(gone_chats), "removed_memories": len(gone_mems), "skipped": skipped}


def route(state: Any, method: str, path: str, body: dict) -> tuple:
    agent = getattr(state, "agent", None)
    if agent is None:
        return 503, {"ok": False, "error": "the engine is not ready"}
    if method == "GET" and path == "/cleanup":
        return 200, scan(agent)
    if method == "POST" and path == "/cleanup/remove":
        ids = body.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return 400, {"ok": False, "error": "which ones? (ids)"}
        return 200, remove(agent, ids)
    return 404, {"ok": False, "error": "Unknown endpoint."}
