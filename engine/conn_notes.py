"""Notes connector: an Obsidian vault (a folder of Markdown files) or Notion.

Read actions: list, search, read. Write actions (each asks the owner; never from a background job):
write (a NEW note - never overwrites), append (adds to the end of a note / Notion page).
Obsidian: every path stays inside the vault; hidden folders (.obsidian, .git, .trash) are never touched.
Notion: an internal integration token (notion.so/profile/integrations), shared with the pages LOKI may
see; new pages go under NOTION_PARENT_PAGE. Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import connectors

SPEC = {
    "id": "notes",
    "label": "Notes (Obsidian vault or Notion)",
    "about": "Search and read your notes. Writing a new note or adding to one asks you first.",
    "tool": "notes",
    "writes": ["write", "append"],
    "help": "Obsidian: the vault folder on this computer. Notion: notion.so/profile/integrations > New integration "
            "(internal), copy its secret, then on each page LOKI may use: ... > Connections > add it. The parent page "
            "id is the 32 hex characters at the end of that page's link.",
    "fields": [
        {"key": "NOTES_KIND", "label": "Notes app", "kind": "choice", "choices": ["obsidian", "notion"], "default": "obsidian"},
        {"key": "OBSIDIAN_VAULT", "label": "Obsidian vault folder", "kind": "text"},
        {"key": "NOTION_TOKEN", "label": "Notion integration secret", "kind": "secret"},
        {"key": "NOTION_PARENT_PAGE", "label": "Notion page for new notes (id)", "kind": "text"},
    ],
}
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
OPENER = urllib.request.urlopen
READ_CHARS = 12000
MAX_FILES = 5000


class NotesError(Exception):
    pass


def kind(source: dict | None = None) -> str:
    return "notion" if connectors.get("NOTES_KIND", source, "obsidian").lower() == "notion" else "obsidian"


def vault(source: dict | None = None) -> Path | None:
    raw = connectors.get("OBSIDIAN_VAULT", source)
    return Path(os.path.expanduser(raw)).resolve() if raw else None


def status(source: dict | None = None) -> dict:
    if kind(source) == "notion":
        if not connectors.get("NOTION_TOKEN", source):
            return {"configured": False, "detail": "paste the Notion integration secret"}
        return {"configured": True, "detail": "Notion"}
    v = vault(source)
    if v is None:
        return {"configured": False, "detail": "choose the Obsidian vault folder"}
    if not v.is_dir():
        return {"configured": False, "detail": "the vault folder %s does not exist on this computer" % v}
    return {"configured": True, "detail": "Obsidian vault %s" % v.name}


# ------------------------------------------------------------------ Obsidian
def _hidden(rel: Path) -> bool:
    return any(part.startswith(".") for part in rel.parts)


def _in_vault(path: str, source: dict | None = None, must_exist: bool = True) -> Path:
    v = vault(source)
    if v is None or not v.is_dir():
        raise NotesError("the Obsidian vault is not set up (Settings > Tools > Notes)")
    name = str(path or "").strip().replace("\\", "/").lstrip("/")
    if not name:
        raise NotesError("give the note's path, e.g. path='Projects/LOKI.md'")
    if not name.lower().endswith(".md"):
        name += ".md"
    target = (v / name).resolve()
    try:
        rel = target.relative_to(v)
    except ValueError:
        raise NotesError("%s is outside the vault" % path) from None
    if _hidden(rel):
        raise NotesError("LOKI does not touch hidden folders in the vault (%s)" % rel)
    if must_exist and not target.is_file():
        found = [p for p in _notes(v) if p.stem.lower() == Path(name).stem.lower()]
        if found:
            return found[0]
        raise NotesError("no note %s in the vault (search first)" % rel)
    return target


def _notes(v: Path) -> list:
    out = []
    for root, dirs, files in os.walk(v):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.lower().endswith(".md"):
                out.append(Path(root) / f)
                if len(out) >= MAX_FILES:
                    return out
    return out


def obsidian_list(path: str = "", source: dict | None = None) -> str:
    v = vault(source)
    if v is None or not v.is_dir():
        return "error: the Obsidian vault is not set up"
    base = (v / str(path or "").strip("/")).resolve()
    try:
        base.relative_to(v)
    except ValueError:
        return "error: %s is outside the vault" % path
    notes = sorted(p for p in _notes(v) if str(p).startswith(str(base)))
    lines = ["%s  (%d KB)" % (p.relative_to(v).as_posix(), max(1, p.stat().st_size // 1024)) for p in notes[:200]]
    return "%d note(s)%s:\n%s%s" % (len(notes), (" in " + path) if path else "", "\n".join(lines),
                                    "\n... (%d more)" % (len(notes) - 200) if len(notes) > 200 else "")


def obsidian_search(query: str, source: dict | None = None, top: int = 8) -> str:
    v = vault(source)
    if v is None or not v.is_dir():
        return "error: the Obsidian vault is not set up"
    words = [w for w in re.findall(r"\w+", str(query or "").lower()) if len(w) > 1]
    if not words:
        return "error: search needs query='...'"
    scored = []
    for p in _notes(v):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        low, name = text.lower(), p.stem.lower()
        score = sum(low.count(w) + 5 * name.count(w) for w in words)
        if score and all(w in low or w in name for w in words[:3]):
            line = next((l.strip() for l in text.splitlines() if any(w in l.lower() for w in words)), "")
            scored.append((score, p, line))
    scored.sort(key=lambda t: -t[0])
    if not scored:
        return "no note mentions %r" % query
    return "\n".join("%s  - %s" % (p.relative_to(v).as_posix(), line[:160]) for _s, p, line in scored[:top])


def obsidian_read(path: str, source: dict | None = None) -> str:
    target = _in_vault(path, source)
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > READ_CHARS:
        text = text[:READ_CHARS] + "\n... (%d more characters)" % (len(text) - READ_CHARS)
    return connectors.untrusted("a note", "%s\n\n%s" % (target.relative_to(vault(source)).as_posix(), text))


def obsidian_write(path: str, text: str, append: bool, source: dict | None = None) -> str:
    target = _in_vault(path, source, must_exist=append)
    if not append and target.exists():
        return "error: %s already exists - use action='append' to add to it" % target.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with target.open("a", encoding="utf-8") as fh:
            fh.write(("\n" if not target.read_text(encoding="utf-8").endswith("\n") else "") + str(text or "") + "\n")
        return "added %d characters to %s" % (len(str(text or "")), target.relative_to(vault(source)).as_posix())
    target.write_text(str(text or "") + "\n", encoding="utf-8")
    return "wrote the new note %s" % target.relative_to(vault(source)).as_posix()


# ------------------------------------------------------------------ Notion
def notion(method: str, path: str, body: dict | None = None, source: dict | None = None) -> dict:
    token = connectors.get("NOTION_TOKEN", source)
    if not token:
        raise NotesError("Notion is not set up (Settings > Tools > Notes)")
    req = urllib.request.Request(NOTION_API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token, "Notion-Version": NOTION_VERSION,
                                          "Content-Type": "application/json"})
    try:
        with OPENER(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read().decode("utf-8") or "{}").get("message", "")
        except Exception:  # noqa: BLE001
            msg = ""
        hint = " (share the page with LOKI's integration: ... > Connections)" if exc.code in (403, 404) else ""
        raise NotesError("Notion answered HTTP %s %s%s" % (exc.code, msg, hint)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise NotesError("cannot reach Notion (%s)" % getattr(exc, "reason", exc)) from exc


def _title(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", [])) or "(untitled)"
    return "(untitled)"


def _plain(block: dict) -> str:
    kind_ = block.get("type", "")
    data = block.get(kind_) or {}
    text = "".join(t.get("plain_text", "") for t in data.get("rich_text", []) if isinstance(t, dict))
    prefix = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### ", "bulleted_list_item": "- ",
              "numbered_list_item": "1. ", "to_do": "[x] " if data.get("checked") else "[ ] ", "quote": "> "}.get(kind_, "")
    if kind_ == "child_page":
        return "(page) " + data.get("title", "")
    return (prefix + text) if text else ""


def _page_id(raw: str) -> str:
    m = re.search(r"([0-9a-f]{32})|([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", str(raw or "").lower())
    if not m:
        raise NotesError("give the Notion page id (from search, or the 32 characters at the end of its link)")
    return m.group(0)


def _paragraphs(text: str) -> list:
    blocks = []
    for para in [p for p in str(text or "").split("\n\n") if p.strip()][:90]:
        for i in range(0, len(para), 1900):
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": [{"type": "text", "text": {"content": para[i:i + 1900]}}]}})
    return blocks


def notion_search(query: str, source: dict | None = None) -> str:
    data = notion("POST", "/search", {"query": str(query or ""), "page_size": 15,
                                      "filter": {"property": "object", "value": "page"}}, source)
    items = data.get("results", [])
    return "\n".join("%s  %s (edited %s)" % (p.get("id", ""), _title(p), str(p.get("last_edited_time", ""))[:10])
                     for p in items) or "no Notion page matches %r (only pages shared with the integration are visible)" % query


def notion_read(page: str, source: dict | None = None) -> str:
    pid = _page_id(page)
    data = notion("GET", "/blocks/%s/children?page_size=100" % pid, None, source)
    text = "\n".join(t for t in (_plain(b) for b in data.get("results", [])) if t)
    return connectors.untrusted("a Notion page", text[:READ_CHARS] or "(the page is empty)")


def notion_write(title: str, text: str, source: dict | None = None) -> str:
    parent = connectors.get("NOTION_PARENT_PAGE", source)
    if not parent:
        return "error: set the Notion page for new notes in Settings > Tools > Notes"
    body = {"parent": {"page_id": _page_id(parent)},
            "properties": {"title": {"title": [{"text": {"content": str(title or "LOKI note")[:200]}}]}},
            "children": _paragraphs(text)}
    made = notion("POST", "/pages", body, source)
    return "created the Notion page %r (%s)" % (title, made.get("url", made.get("id", "")))


def notion_append(page: str, text: str, source: dict | None = None) -> str:
    pid = _page_id(page)
    notion("PATCH", "/blocks/%s/children" % pid, {"children": _paragraphs(text)}, source)
    return "added %d characters to the Notion page %s" % (len(str(text or "")), pid)


def test(source: dict | None = None) -> dict:
    st = status(source)
    if not st["configured"]:
        return {"ok": False, "detail": st["detail"]}
    try:
        if kind(source) == "notion":
            notion("POST", "/search", {"page_size": 1}, source)
            return {"ok": True, "detail": "Notion answered"}
        return {"ok": True, "detail": "%d notes in the vault" % len(_notes(vault(source)))}
    except NotesError as exc:
        return {"ok": False, "detail": str(exc)}


def preview(args: dict) -> str:
    target = args.get("path") or args.get("page") or args.get("title") or "?"
    return "NOTES %s %s: %s" % (str(args.get("action", "")).upper(), target, str(args.get("text", ""))[:300])


ACTIONS = ("list", "search", "read", "write", "append")


def tool(action: str = "search", query: str = "", path: str = "", title: str = "", text: str = "", page: str = "") -> str:
    """The `notes` tool."""
    action = str(action or "search").strip().lower()
    try:
        st = status()
        if not st["configured"]:
            return "error: notes are not set up: %s (Settings > Tools > Notes)" % st["detail"]
        if kind() == "notion":
            if action in ("search", "list"):
                return notion_search(query)
            if action == "read":
                return notion_read(page or path)
            if action == "write":
                return notion_write(title or path, text)
            if action == "append":
                return notion_append(page or path, text)
        else:
            if action == "list":
                return obsidian_list(path)
            if action == "search":
                return obsidian_search(query)
            if action == "read":
                return obsidian_read(path or title)
            if action in ("write", "append"):
                return obsidian_write(path or title, text, append=action == "append")
    except NotesError as exc:
        return "error: %s" % exc
    return "error: unknown action %r - use one of %s" % (action, ", ".join(ACTIONS))


connectors.register(__import__(__name__))
