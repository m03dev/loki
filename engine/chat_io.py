"""Chats in and out of LOKI (research round 3; the idea from Open WebUI, LibreChat and Lobe Chat).

Export one chat (or all of them) as Markdown, JSON or a standalone HTML page; import chats people
already have elsewhere:

  - ChatGPT        `conversations.json` from Settings > Data controls > Export (a list of
                   conversations, each a `mapping` graph of nodes {id, parent, children, message};
                   the visible branch is followed from `current_node` back to the root - LibreChat's
                   importer does the same - and, without it, from the root along the LAST child)
  - Claude         `conversations.json` from claude.ai's export ({name, chat_messages: [{sender:
                   human|assistant, text | content: [{type: text, text}]}]})
  - Open WebUI     its "Export chats" JSON ([{chat: {title, messages: [{role, content}]}}] or
                   history.messages keyed by id with parentId and currentId)
  - LibreChat      its export ({conversationId, title, messages: [{sender|isCreatedByUser, text}]})
  - LOKI           LOKI's own JSON export (this module's `export_json`)
  - Markdown       "## You" / "## LOKI" (or "**User:**" / "**Assistant:**") sections

Everything here is pure: text in, plain {title, messages: [{role, content}]} out. The caller adds
the chats to LOKI (`loki._r3_add_conversation`); importing never replaces an existing chat.
"""
from __future__ import annotations

import html
import json
import re
import time
from typing import Any, Iterable

MAX_IMPORT_CHATS = 2000          # a ChatGPT export can hold thousands; LOKI keeps the newest
MAX_MESSAGES = 400               # per chat on import (LOKI itself keeps the last 40 in the model's view)
MAX_CHARS = 60_000               # per message


def _text(value: Any) -> str:
    """Text out of the many shapes exports use for a message body."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(t for t in (_text(v) for v in value) if t.strip())
    if isinstance(value, dict):
        if value.get("type") in ("image", "image_url", "image_asset_pointer", "tool_use", "tool_result"):
            return ""
        for key in ("parts", "text", "content", "value", "result"):
            if key in value:
                return _text(value[key])
    return ""


def _clean(role: str, content: str) -> dict | None:
    content = str(content or "").replace("\r\n", "\n").strip()
    if not content:
        return None
    return {"role": role, "content": content[:MAX_CHARS]}


def _role(raw: Any) -> str:
    word = str(raw or "").strip().lower()
    if word in ("user", "human", "you", "me", "prompt"):
        return "user"
    if word in ("assistant", "ai", "bot", "model", "gpt", "chatgpt", "claude", "loki", "gemini"):
        return "assistant"
    return word


def _chat(title: Any, msgs: Iterable[dict | None], created: Any = None, source: str = "") -> dict | None:
    out = [m for m in msgs if m and m["role"] in ("user", "assistant")][:MAX_MESSAGES]
    if not out:
        return None
    first_user = next((m["content"] for m in out if m["role"] == "user"), out[0]["content"])
    name = str(title or "").strip() or first_user.splitlines()[0][:48]
    try:
        when = float(created) if created not in (None, "") else time.time()
        if when > 1e12:            # milliseconds
            when /= 1000.0
    except (TypeError, ValueError):
        when = _iso_time(str(created)) or time.time()
    return {"title": name[:60], "messages": out, "created": when, "source": source}


def _iso_time(text: str) -> float:
    from datetime import datetime  # pylint: disable=import-outside-toplevel
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------------------- readers
def _chatgpt_one(conv: dict) -> dict | None:
    mapping = conv.get("mapping") or {}
    if not isinstance(mapping, dict) or not mapping:
        return None
    chain: list = []
    node_id = conv.get("current_node")
    seen: set = set()
    if node_id in mapping:                       # the branch the person was looking at
        while node_id and node_id in mapping and node_id not in seen:
            seen.add(node_id)
            chain.append(mapping[node_id])
            node_id = mapping[node_id].get("parent")
        chain.reverse()
    else:                                        # no current_node: root -> last child each time
        roots = [n for n in mapping.values() if not n.get("parent") or n.get("parent") not in mapping]
        node = roots[0] if roots else None
        while node is not None and node.get("id") not in seen:
            seen.add(node.get("id"))
            chain.append(node)
            kids = [k for k in (node.get("children") or []) if k in mapping]
            node = mapping[kids[-1]] if kids else None
    msgs = []
    for node in chain:
        message = node.get("message") or {}
        if not message:
            continue
        role = _role((message.get("author") or {}).get("role"))
        if role not in ("user", "assistant"):
            continue
        content = message.get("content") or {}
        if content.get("content_type") not in (None, "text", "multimodal_text", "code"):
            continue
        if (message.get("metadata") or {}).get("is_visually_hidden_from_conversation"):
            continue
        msgs.append(_clean(role, _text(content.get("parts") if "parts" in content else content.get("text"))))
    return _chat(conv.get("title"), msgs, conv.get("create_time"), "chatgpt")


def _claude_one(conv: dict) -> dict | None:
    msgs = []
    for m in conv.get("chat_messages") or []:
        if not isinstance(m, dict):
            continue
        body = m.get("text") if str(m.get("text") or "").strip() else _text(m.get("content"))
        msgs.append(_clean(_role(m.get("sender")), body))
    return _chat(conv.get("name"), msgs, conv.get("created_at"), "claude")


def _webui_one(item: dict) -> dict | None:
    chat = item.get("chat") if isinstance(item.get("chat"), dict) else item
    history = (chat.get("history") or {}) if isinstance(chat, dict) else {}
    msgs = []
    by_id = history.get("messages") if isinstance(history.get("messages"), dict) else None
    if by_id and history.get("currentId") in by_id:
        chain, node, seen = [], by_id[history["currentId"]], set()
        while node and node.get("id") not in seen:
            seen.add(node.get("id"))
            chain.append(node)
            node = by_id.get(node.get("parentId"))
        msgs = [_clean(_role(n.get("role")), _text(n.get("content"))) for n in reversed(chain)]
    else:
        msgs = [_clean(_role(m.get("role")), _text(m.get("content"))) for m in (chat.get("messages") or [])
                if isinstance(m, dict)]
    return _chat(chat.get("title") or item.get("title"), msgs, item.get("created_at") or chat.get("timestamp"), "openwebui")


def _librechat_one(conv: dict) -> dict | None:
    msgs = []
    for m in conv.get("messages") or []:
        if not isinstance(m, dict):
            continue
        if "isCreatedByUser" in m:
            role = "user" if m.get("isCreatedByUser") else "assistant"
        else:
            role = _role(m.get("sender") or m.get("role"))
        msgs.append(_clean(role, m.get("text") if m.get("text") else _text(m.get("content"))))
    return _chat(conv.get("title"), msgs, conv.get("createdAt"), "librechat")


def _loki_one(conv: dict) -> dict | None:
    msgs = [_clean(_role(m.get("role")), _text(m.get("content"))) for m in (conv.get("messages") or [])
            if isinstance(m, dict)]
    return _chat(conv.get("title"), msgs, conv.get("created"), "loki")


def detect(data: Any) -> str:
    """Which app made this export: chatgpt | claude | openwebui | librechat | loki | ''."""
    items = data.get("conversations") if isinstance(data, dict) and isinstance(data.get("conversations"), list) else data
    if isinstance(data, dict) and data.get("format") == "loki-chats":
        return "loki"
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or not items:
        return ""
    first = next((i for i in items if isinstance(i, dict)), {})
    if "mapping" in first:
        return "chatgpt"
    if "chat_messages" in first:
        return "claude"
    if "chat" in first or "history" in first:
        return "openwebui"
    if "conversationId" in first or any("isCreatedByUser" in m for m in (first.get("messages") or [])
                                        if isinstance(m, dict)):
        return "librechat"
    if "messages" in first:
        return "loki"
    return ""


READERS = {"chatgpt": _chatgpt_one, "claude": _claude_one, "openwebui": _webui_one,
           "librechat": _librechat_one, "loki": _loki_one}


def parse_markdown(text: str, title: str = "") -> list:
    """A Markdown transcript: '## You' / '## LOKI' headings, or '**User:**' / 'Assistant:' lines."""
    head = re.compile(r"^(?:#{1,4}\s*|\*\*)?\s*(you|user|me|human|loki|assistant|ai|chatgpt|claude|gpt)\s*:?\s*(?:\*\*)?\s*:?\s*$|"
                      r"^(?:\*\*)?(you|user|human|loki|assistant|ai|chatgpt|claude)(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.+)$", re.I)
    msgs: list = []
    role, buf = "", []
    name = title
    for line in str(text or "").splitlines():
        if not name and line.startswith("# ") and not msgs and not buf:
            name = line[2:].strip()
            continue
        m = head.match(line.strip())
        if m:
            if role:
                msgs.append(_clean(role, "\n".join(buf)))
            role = _role(m.group(1) or m.group(2))
            buf = [m.group(3)] if m.group(3) else []
            continue
        if role:
            buf.append(line)
    if role:
        msgs.append(_clean(role, "\n".join(buf)))
    chat = _chat(name, msgs, None, "markdown")
    return [chat] if chat else []


def parse(text: str, filename: str = "") -> dict:
    """{ok, source, chats: [{title, messages, created, source}], skipped} or {ok: False, error}."""
    raw = str(text or "")
    if not raw.strip():
        return {"ok": False, "error": "the file is empty"}
    stripped = raw.lstrip()
    if filename.lower().endswith((".md", ".markdown", ".txt")) or not stripped.startswith(("[", "{")):
        chats = parse_markdown(raw)
        if not chats:
            return {"ok": False, "error": "no '## You' / '## LOKI' (or 'User:' / 'Assistant:') turns found"}
        return {"ok": True, "source": "markdown", "chats": chats, "skipped": 0}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "not valid JSON (%s)" % exc.msg}
    source = detect(data)
    if not source:
        return {"ok": False, "error": "this is not a ChatGPT, Claude, Open WebUI, LibreChat or LOKI chat export"}
    items = data.get("conversations") if isinstance(data, dict) and isinstance(data.get("conversations"), list) else data
    if isinstance(items, dict):
        items = [items]
    chats, skipped = [], 0
    for item in items[:MAX_IMPORT_CHATS]:
        chat = READERS[source](item) if isinstance(item, dict) else None
        if chat:
            chats.append(chat)
        else:
            skipped += 1
    skipped += max(0, len(items) - MAX_IMPORT_CHATS)
    if not chats:
        return {"ok": False, "error": "found a %s export but no chat with text in it" % source}
    return {"ok": True, "source": source, "chats": chats, "skipped": skipped}


# ---------------------------------------------------------------------------------------- writers
def _when(ts: Any) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError):
        return ""


def export_markdown(convo: dict) -> str:
    lines = ["# " + str(convo.get("title") or "Chat"), ""]
    when = _when(convo.get("created"))
    if when:
        lines += ["_Exported from LOKI - started %s_" % when, ""]
    for m in convo.get("messages") or []:
        if m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str):
            continue
        lines += ["## " + ("You" if m["role"] == "user" else "LOKI"), "", m["content"].strip(), ""]
    return "\n".join(lines).rstrip() + "\n"


def export_json(convos: list) -> str:
    out = []
    for c in convos:
        out.append({"id": c.get("id", ""), "title": c.get("title", ""), "created": c.get("created"),
                    "updated": c.get("updated"),
                    "messages": [{"role": m["role"], "content": m["content"]} for m in c.get("messages") or []
                                 if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]})
    return json.dumps({"format": "loki-chats", "version": 1, "exported": time.time(), "conversations": out},
                      ensure_ascii=False, indent=1)


def export_html(convo: dict) -> str:
    """One self-contained page (no script, no remote file) - opens in any browser, prints well."""
    rows = []
    for m in convo.get("messages") or []:
        if m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str):
            continue
        who = "You" if m["role"] == "user" else "LOKI"
        body = html.escape(m["content"].strip())
        body = re.sub(r"```[^\n]*\n(.*?)```", lambda x: "<pre>" + x.group(1) + "</pre>", body, flags=re.S)
        rows.append('<section class="%s"><h2>%s</h2><div>%s</div></section>'
                    % (m["role"], who, body.replace("\n", "<br>").replace("<pre><br>", "<pre>")))
    title = html.escape(str(convo.get("title") or "Chat"))
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>%s</title><style>"
            "body{font:15px/1.55 system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#1d1d1f}"
            "h1{font-size:1.4rem}h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:#666;margin:0 0 .3rem}"
            "section{padding:.8rem 1rem;border-radius:10px;margin:.6rem 0}section.user{background:#eef3ff}"
            "section.assistant{background:#f6f6f6}pre{background:#fff;padding:.6rem;overflow:auto;border-radius:6px}"
            "</style></head><body><h1>%s</h1><p><small>Exported from LOKI %s</small></p>%s</body></html>"
            % (title, title, html.escape(_when(convo.get("created"))), "".join(rows)))


def filename_for(title: str, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9 _.-]+", "", str(title or "chat")).strip().replace(" ", "-")[:50] or "chat"
    return "%s-%s.%s" % (stem, time.strftime("%Y%m%d-%H%M%S"), ext)
