"""Tool use that small models get right: short descriptions, one worked example per tool, and errors that teach.

A 7-9B model fixes a bad call when the error shows a CORRECT call, not when it shows a schema. So:
  - `EXAMPLES`: one real example call per tool (the core file/web tools and every tool this session added);
  - `repair(name, args)`: maps the action words small models reach for (send_email, inbox, open_application,
    get_events ...) onto the tool's real `action` values BEFORE validation - never invents a value;
  - `teach(name, error)`: appends "Example: <call>" (and, for a bad action, the valid ones) to the tool guard's
    error. tool_guard.py stays as it is; loki.py wraps its `_guard_call` with these two (one hook).
Pure functions, no LOKI globals. Tested in tests/test_tools_core.py.
"""
from __future__ import annotations

import difflib
import json
from typing import Any

EXAMPLES = {
    "read_file": '{"filename": "src/app.py", "start_line": 1, "end_line": 80}',
    "write_file": '{"filename": "notes/todo.md", "content": "- buy milk\\n"}',
    "edit_file": '{"filename": "src/app.py", "old": "print(\'hi\')", "new": "print(\'hello\')"}',
    "search_files": '{"pattern": "def main", "subdir": "."}',
    "list_tree": '{"subdir": ".", "max_depth": 2}',
    "web_search": '{"query": "python 3.13 release notes"}',
    "read_web": '{"url": "https://example.com/page", "query": "pricing"}',
    "browse_page": '{"action": "open", "url": "https://duckduckgo.com/html/"}',
    "email": '{"action": "search", "query": "from:alice invoice"}',
    "calendar": '{"action": "list", "days": 7}',
    "github": '{"action": "issues", "repo": "owner/name"}',
    "notes": '{"action": "search", "query": "meeting notes"}',
    "peer_files": '{"action": "list", "machine": "pc", "path": "Home"}',
    "computer": '{"action": "find", "text": "Save", "role": "button"}',
    "run_command": '{"command": "python -m pytest -q"}',
    "memory": '{"action": "recall", "query": "owner preferences"}',
}

# action words small models use -> the real action, per tool
ACTION_SYNONYMS = {
    "email": {"inbox": "list", "list_emails": "list", "get_emails": "list", "recent": "list", "read_email": "read",
              "open": "read", "get": "read", "search_emails": "search", "find": "search", "send_email": "send",
              "compose": "draft", "write": "draft", "create_draft": "draft", "reply": "draft"},
    "calendar": {"events": "list", "get_events": "list", "agenda": "list", "schedule": "list", "view": "list",
                 "add": "create", "add_event": "create", "create_event": "create", "new": "create", "book": "create"},
    "github": {"list_issues": "issues", "get_issues": "issues", "get_issue": "issue", "read_issue": "issue",
               "list_prs": "prs", "pulls": "prs", "pull_requests": "prs", "get_pr": "pr", "pull": "pr",
               "list_repos": "repos", "repositories": "repos", "new_issue": "create_issue", "open_issue": "create_issue",
               "add_comment": "comment", "close": "close_issue", "open_pr": "create_pr", "new_pr": "create_pr"},
    "notes": {"find": "search", "get": "read", "open": "read", "create": "write", "new": "write", "add": "append",
              "ls": "list"},
    "peer_files": {"ls": "list", "dir": "list", "get": "read", "cat": "read", "open": "read", "put": "write",
                   "save": "write", "peers": "machines", "list_machines": "machines"},
    "computer": {"tree": "elements", "list_elements": "elements", "get_elements": "elements", "ui": "elements",
                 "state": "elements", "observe": "elements", "locate": "find", "search": "find", "tap": "click",
                 "left_click": "click", "doubleclick": "double_click", "rightclick": "right_click",
                 "type_text": "type", "write": "type", "input": "type", "press": "key", "hotkey": "key",
                 "press_key": "key", "keys": "key", "open_application": "open_app", "launch": "open_app",
                 "launch_app": "open_app", "start_app": "open_app", "open": "open_app", "describe": "look",
                 "see": "look", "capture": "screenshot", "take_screenshot": "screenshot", "list_apps": "apps",
                 "windows": "apps", "sleep": "wait"},
    "browse_page": {"goto": "open", "navigate": "open", "visit": "open", "go": "open", "fill": "type",
                    "input": "type", "press": "key", "state": "view", "show": "view", "enter": "submit"},
}

DESCRIPTIONS = {
    "email": ("Your email (IMAP/SMTP). action: list | search (query: words, from:x, subject:y, unread) | read (id) | "
              "draft (to, subject, body - saved locally, not sent) | send (to, subject, body, or draft=<file> - ALWAYS "
              "asks the owner). Example: {\"action\": \"search\", \"query\": \"from:alice invoice\"}"),
    "calendar": ("The owner's calendar. action: list (days, or start/end) | create (title, start like "
                 "'2026-10-20 15:00' or 'tomorrow 3pm', duration_min, location - asks the owner). "
                 "Example: {\"action\": \"list\", \"days\": 7}"),
    "github": ("GitHub repos, issues and pull requests. action: repos | issues | issue (number) | prs | pr (number) | "
               "search (query) | create_issue (title, body) | comment (number, body) | close_issue (number) | "
               "create_pr (title, head, base) - writes ask the owner. repo='owner/name' (default from Settings). "
               "Example: {\"action\": \"issues\", \"repo\": \"m03dev/loki\"}"),
    "notes": ("The owner's notes (Obsidian vault or Notion). action: list | search (query) | read (path or page) | "
              "write (path/title, text - a NEW note) | append (path or page, text) - writes ask the owner. "
              "Example: {\"action\": \"search\", \"query\": \"project ideas\"}"),
    "peer_files": ("Files on the owner's OTHER LOKI machine (Mac <-> PC) over the peer link, inside its shared "
                   "folder. action: machines | list (machine, path) | read (machine, path) | write (machine, path, "
                   "text - asks the owner). Example: {\"action\": \"list\", \"machine\": \"pc\", \"path\": \"\"}"),
    "computer": ("Control THIS computer's desktop apps (no API): see the focused window's controls numbered, then act. "
                 "action: elements | find (text, role) | click (index, or text) | double_click | right_click | "
                 "type (text, optional index) | key (keys: 'enter', 'ctrl+s', 'cmd+space') | scroll (direction) | "
                 "open_app (app) | apps | screenshot | look (question; uses a vision model) | wait (seconds). "
                 "Always: elements first, then click/type by index. The owner approves each app once. "
                 "Example: {\"action\": \"open_app\", \"app\": \"Notepad\"} then {\"action\": \"elements\"}"),
}


def _args(raw: Any) -> dict | None:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        import tool_guard  # pylint: disable=import-outside-toplevel
        return tool_guard.repair_json(raw)
    except Exception:  # noqa: BLE001
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return None


def repair(name: str, raw_args: Any) -> Any:
    """`raw_args` with a synonym action replaced by the real one (other values untouched)."""
    table = ACTION_SYNONYMS.get(str(name or ""))
    if not table:
        return raw_args
    args = _args(raw_args)
    if not isinstance(args, dict):
        return raw_args
    action = args.get("action")
    if isinstance(action, str):
        low = action.strip().lower().replace("-", "_").replace(" ", "_")
        if low in table:
            args["action"] = table[low]
            return args
        if low != action:
            args["action"] = low
            return args
    return raw_args


def valid_actions(name: str, params: dict | None) -> list:
    spec = ((params or {}).get("properties") or {}).get("action") or {}
    return list(spec.get("enum") or [])


def teach(name: str, error: str, params: dict | None = None, given: Any = None) -> str:
    """The guard's error plus what a small model needs to fix the call next turn."""
    error = str(error or "")
    if not error or "Example:" in error:
        return error
    extra = []
    actions = valid_actions(name, params)
    if actions and given is not None:
        args = _args(given) or {}
        bad = args.get("action")
        if isinstance(bad, str) and bad not in actions:
            near = difflib.get_close_matches(bad.lower(), actions, n=1, cutoff=0.4)
            extra.append("action %r is not one of: %s%s." % (bad, ", ".join(actions), (" - did you mean %r?" % near[0]) if near else ""))
    example = EXAMPLES.get(name)
    if example:
        extra.append("Example: %s(%s)" % (name, example))
    return error + ((" " + " ".join(extra)) if extra else "")


def concise(text: str, limit: int = 600) -> str:
    """A tool description cut at a sentence end, for small models (they read every schema every turn)."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:end + 1] if end > limit // 2 else cut.rstrip() + "...")
