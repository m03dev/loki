"""Chat actions every good chat app has and LOKI lacked (research round 3): edit a message and send
it again, regenerate an answer, branch a new chat from any point, export and import chats.

Open WebUI, LibreChat and Lobe Chat keep a message TREE; LOKI keeps one list per chat. So here:
  - edit / regenerate  = cut the chat just before that user message (the UI then sends the new or
                         the same text through the normal /chat path, so modes, approvals and
                         tools all work as usual);
  - branch             = a NEW chat holding the messages up to that point (the original is kept -
                         that is LibreChat's "fork" and the reason people branch at all).
The UI names a message by its text and which occurrence it is (the window's turns and the stored
turns are not always the same list: LOKI drops its own steering turns and DONE lines when it
saves), and `locate` finds it in what is stored.

`agent` is the loki module (CONVERSATIONS, active_conversation, _activate, save_conversations,
_new_conversation, save_history).
"""
from __future__ import annotations

import time
from typing import Any

import chat_io


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split())[:4000]


def locate(stored: list, role: str, text: str, occurrence: int = 0) -> int:
    """Index in `stored` of the `occurrence`-th (0-based) message of `role` whose text is `text`;
    -1 when it is not there. Exact (whitespace-insensitive) first, then the stored text starting the
    same way (LOKI trims and cleans what it stores)."""
    want = _norm(text)
    if not want:
        return -1
    for exact in (True, False):
        seen = 0
        for i, m in enumerate(stored):
            if m.get("role") != role or not isinstance(m.get("content"), str):
                continue
            have = _norm(m["content"])
            hit = have == want if exact else (have[:200] == want[:200] and len(want) >= 8)
            if hit:
                if seen == max(0, int(occurrence or 0)):
                    return i
                seen += 1
    return -1


def _visible(convo: dict) -> list:
    return [{"role": m["role"], "content": m["content"]} for m in convo.get("messages") or []
            if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]


def _sync_active(agent: Any) -> None:
    """The open chat's live history first goes into its stored copy (what the window shows)."""
    try:
        agent.save_history()
    except Exception:  # noqa: BLE001 - nothing to save yet
        pass


def cut_before(agent: Any, cid: str, text: str, occurrence: int = 0) -> dict:
    """Edit / regenerate: keep everything before that user message; return the kept messages."""
    _sync_active(agent)
    convo = agent.CONVERSATIONS.get(cid or agent.active_conversation)
    if convo is None:
        return {"ok": False, "error": "no such chat"}
    idx = locate(convo["messages"], "user", text, occurrence)
    if idx < 0:
        return {"ok": False, "error": "that message is not in the saved chat any more"}
    convo["messages"] = convo["messages"][:idx]
    convo["updated"] = time.time()
    if convo["id"] == agent.active_conversation:
        agent._activate(convo["id"])          # noqa: SLF001 - the model's view = the cut chat
    agent.save_conversations()
    return {"ok": True, "id": convo["id"], "messages": _visible(convo)}


def branch(agent: Any, cid: str, role: str = "assistant", text: str = "", occurrence: int = 0,
           title: str = "") -> dict:
    """A new chat with everything up to and including that message (the whole chat when `text` is
    empty); it becomes the open chat. The original stays as it was."""
    _sync_active(agent)
    convo = agent.CONVERSATIONS.get(cid or agent.active_conversation)
    if convo is None:
        return {"ok": False, "error": "no such chat"}
    upto = len(convo["messages"])
    if text:
        idx = locate(convo["messages"], role if role in ("user", "assistant") else "assistant", text, occurrence)
        if idx < 0:
            return {"ok": False, "error": "that message is not in the saved chat any more"}
        upto = idx + 1
    new = agent._new_conversation(title or ("Branch of " + str(convo.get("title") or "chat"))[:60])  # noqa: SLF001
    new["messages"] = [dict(m) for m in convo["messages"][:upto]]
    new["branched_from"] = convo["id"]
    agent.CONVERSATIONS[new["id"]] = new
    agent._activate(new["id"])                 # noqa: SLF001
    agent.save_conversations()
    return {"ok": True, "id": new["id"], "messages": _visible(new)}


def add_chats(agent: Any, chats: list) -> list:
    """Imported chats join LOKI's list (new ids; nothing existing is replaced). Returns the new ids."""
    ids = []
    for chat in chats:
        new = agent._new_conversation(chat.get("title") or "Imported chat")   # noqa: SLF001
        new["messages"] = [{"role": m["role"], "content": m["content"]} for m in chat.get("messages") or []]
        new["created"] = float(chat.get("created") or time.time())
        new["updated"] = new["created"]
        new["imported_from"] = chat.get("source", "")
        agent.CONVERSATIONS[new["id"]] = new
        ids.append(new["id"])
    if ids:
        agent.save_conversations()
    return ids


def export(agent: Any, cid: str = "", fmt: str = "md", everything: bool = False) -> dict:
    """{ok, name, text, mime} for one chat (md | html | json) or all chats (json)."""
    _sync_active(agent)
    if everything:
        convos = sorted(agent.CONVERSATIONS.values(), key=lambda c: c.get("updated", 0), reverse=True)
        return {"ok": True, "name": chat_io.filename_for("loki-chats", "json"), "mime": "application/json",
                "text": chat_io.export_json(convos), "count": len(convos)}
    convo = agent.CONVERSATIONS.get(cid or agent.active_conversation)
    if convo is None:
        return {"ok": False, "error": "no such chat"}
    fmt = (fmt or "md").lower()
    if fmt == "json":
        return {"ok": True, "name": chat_io.filename_for(convo["title"], "json"), "mime": "application/json",
                "text": chat_io.export_json([convo]), "count": 1}
    if fmt == "html":
        return {"ok": True, "name": chat_io.filename_for(convo["title"], "html"), "mime": "text/html",
                "text": chat_io.export_html(convo), "count": 1}
    return {"ok": True, "name": chat_io.filename_for(convo["title"], "md"), "mime": "text/markdown",
            "text": chat_io.export_markdown(convo), "count": 1}
