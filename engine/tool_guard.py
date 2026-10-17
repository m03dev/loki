"""Tool-call guard: make small and local models reliable at calling tools.

A 3-9B local model usually knows WHAT to do; it fails on the last inch - the shape of the
call. Before this module, any of these ended the step with an error the model then had to
puzzle out on its own (and often repeated):

  bad JSON        {'path': 'a.txt',}      single quotes, trailing comma, ```json fence,
                                           True/None, unquoted keys
  near-miss name  create_file, writeFile,  a tool that does not exist, but obviously means
                  ls, cat, mkdir, bash     one that does
  wrong types     {"line": "12"}           a number as a string, "true" for a bool
  missing args    write_file(path=...)     a required argument left out
  python syntax   write_file(path="a",     a call written as code instead of JSON
                  content="hi")

The guard fixes what it can deterministically (never with a model, never by guessing a
value the model did not give) and, when it cannot, returns ONE precise sentence naming
what is wrong and the exact schema, which is what a small model needs to repair the call
on its next turn.

It also builds a JSON schema for CONSTRAINED decoding: a local server (Ollama, llama.cpp,
LM Studio, vLLM) given `response_format={"type": "json_schema", ...}` can only produce a
well-formed call to a real tool or a final answer - the call shape can no longer fail at
all. `constrained_format()` builds it; `decode_constrained()` turns the reply back into
(tool calls, text). loki._model_request uses it for local providers in prompted mode.

Pure functions; no network, no LOKI globals. Tested in tests/test_tool_guard.py.
"""
from __future__ import annotations

import ast
import difflib
import json
import os
import re
from typing import Any

# --------------------------------------------------------------------------- arguments

_FENCE = re.compile(r"^\s*```(?:json|javascript|js|python|tool_call)?\s*(.*?)\s*```\s*$", re.S | re.I)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_UNQUOTED_KEY = re.compile(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_\-]*)\s*:')


def repair_json(raw: Any) -> dict | None:
    """Arguments as a dict, from a string a small model produced. None if hopeless.

    Tries strict JSON first, then the common slips in order of safety. Never invents
    content: every value in the result was in the model's text.
    """
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    text = str(raw).strip()
    if not text:
        return {}
    fence = _FENCE.match(text)
    if fence:
        text = fence.group(1).strip()
    for attempt in (text, _TRAILING_COMMA.sub(r"\1", text)):
        try:
            value = json.loads(attempt)
            if isinstance(value, str):          # double-encoded: "{\"path\": ...}"
                value = json.loads(value)
            return value if isinstance(value, dict) else None
        except (ValueError, TypeError):
            pass
    # Python literal syntax: single quotes, True/False/None, trailing commas.
    try:
        value = ast.literal_eval(text)
        if isinstance(value, dict):
            return {str(k): v for k, v in value.items()}
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        pass
    # Unquoted keys: {path: "a.txt", content: "x"}
    quoted = _UNQUOTED_KEY.sub(r'\1"\2":', _TRAILING_COMMA.sub(r"\1", text))
    try:
        value = json.loads(quoted)
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError):
        pass
    # The object is buried in prose: take the first balanced {...} (braces inside strings
    # - CSS, JS, code in a write_file - do not count).
    start = text.find("{")
    if start > 0:
        spans = json_object_spans(text[start:])
        if spans:
            return repair_json(spans[0])
    # The model stopped before the last closing braces (common on long write_file calls):
    # close what is open. Nothing is invented - only the missing } / ] at the very end.
    closed = close_truncated(text)
    if closed and closed != text:
        try:
            value = json.loads(closed)
            return value if isinstance(value, dict) else None
        except (ValueError, TypeError):
            pass
    return None


def _scan(text: str):
    """Walk JSON-ish text, yielding (index, char, quoted): quoted is True for every
    character of a "string", its quotes included. Backslash escapes are honoured."""
    in_str, esc = False, False
    for index, char in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif char == "\\":
                esc = True
            elif char == '"':
                in_str = False
            yield index, char, True
        elif char == '"':
            in_str = True
            yield index, char, True
        else:
            yield index, char, False


def _string_left_open(text: str) -> bool:
    in_str, esc = False, False
    for char in text:
        if in_str:
            if esc:
                esc = False
            elif char == "\\":
                esc = True
            elif char == '"':
                in_str = False
        elif char == '"':
            in_str = True
    return in_str


def json_object_spans(text: str) -> list:
    """Every balanced top-level {...} in a string; braces inside "strings" are ignored."""
    spans, depth, start = [], 0, -1
    for index, char, quoted in _scan(text):
        if quoted:
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                spans.append(text[start:index + 1])
                start = -1
    return spans


def close_truncated(text: str) -> str | None:
    """The object with the closers it is missing at its very end, or None.

    Only for text that starts an object, has every string closed, closes in the right
    order as far as it goes, and lacks at most four closers - so a truncated call is
    finished, and nothing that is merely broken is guessed at."""
    text = text.strip()
    if not text.startswith("{") or _string_left_open(text):
        return None
    stack = []
    for _, char, quoted in _scan(text):
        if quoted:
            continue
        if char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]":
            if not stack or stack[-1] != char:
                return None
            stack.pop()
    if not stack or len(stack) > 4:
        return None
    return text + "".join(reversed(stack))


# --------------------------------------------------------------------------- tool names

# Names small models reach for, mapped to LOKI's tools. Only used when the target exists.
NAME_ALIASES = {
    "create_file": "write_file", "writefile": "write_file", "save_file": "write_file",
    "write": "write_file", "new_file": "write_file", "file_write": "write_file",
    "create": "write_file", "touch": "write_file", "put_file": "write_file",
    "read": "read_file", "cat": "read_file", "open_file": "read_file", "view_file": "read_file",
    "readfile": "read_file", "file_read": "read_file", "get_file": "read_file",
    "show_file": "read_file",
    "edit": "edit_file", "modify_file": "edit_file", "update_file": "edit_file",
    "replace_in_file": "edit_file", "str_replace": "edit_file", "patch_file": "edit_file",
    "ls": "list_tree", "list_files": "list_tree", "list_dir": "list_tree", "listdir": "list_tree",
    "list_directory": "list_tree", "tree": "list_tree", "dir": "list_tree", "list": "list_tree",
    "grep": "search_files", "search": "search_files", "find": "search_files",
    "find_in_files": "search_files", "rg": "search_files", "search_code": "search_files",
    "bash": "run_command", "shell": "run_command", "exec": "run_command", "run": "run_command",
    "execute": "run_command", "terminal": "run_command", "cmd": "run_command",
    "run_shell": "run_command", "execute_command": "run_command", "sh": "run_command",
    "mkdir": "make_dir", "create_dir": "make_dir", "create_directory": "make_dir",
    "make_directory": "make_dir", "makedirs": "make_dir",
    "mv": "move_file", "rename": "move_file", "rename_file": "move_file", "move": "move_file",
    "rm": "delete_file", "remove": "delete_file", "remove_file": "delete_file",
    "delete": "delete_file", "unlink": "delete_file",
    "append": "append_file", "append_to_file": "append_file",
    "remember": "save_memory", "memory": "save_memory", "note": "save_memory",
    "add_todo": "todo_add", "todo": "todo_add",
}


def _norm(name: str) -> str:
    """writeFile / Write-File / write file / functions.write_file -> write_file."""
    text = str(name or "").strip()
    if "." in text:                      # functions.write_file, tools.read
        text = text.rsplit(".", 1)[-1]
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return re.sub(r"[\s\-]+", "_", text).strip("_").lower()


def resolve_name(name: str, known) -> str:
    """The real tool a model meant, or "" when it is not clear. Never a wild guess."""
    tools = set(known or ())
    if name in tools:
        return name
    norm = _norm(name)
    if norm in tools:
        return norm
    alias = NAME_ALIASES.get(norm)
    if alias in tools:
        return alias
    # A close spelling (wirte_file, read_flie). High cutoff: a wrong tool is worse than
    # an error the model can read.
    close = difflib.get_close_matches(norm, sorted(tools), n=1, cutoff=0.86)
    return close[0] if close else ""


# --------------------------------------------------------------------------- validation

def _coerce(value: Any, kind: str) -> Any:
    """Turn a string the model sent into the declared type, only when it is unambiguous."""
    if kind == "integer" and isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value.strip())
    if kind == "integer" and isinstance(value, float) and value.is_integer():
        return int(value)
    if kind == "number" and isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return value
    if kind == "boolean" and isinstance(value, str) and value.strip().lower() in ("true", "false", "yes", "no", "1", "0"):
        return value.strip().lower() in ("true", "yes", "1")
    if kind == "string" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if kind == "string" and isinstance(value, (dict, list)):
        # A model sometimes passes a JSON file's content as an object.
        return json.dumps(value, indent=2, ensure_ascii=False)
    if kind == "array" and isinstance(value, str):
        parsed = repair_json('{"v": %s}' % value) if value.strip().startswith("[") else None
        if parsed and isinstance(parsed.get("v"), list):
            return parsed["v"]
        return [value]
    # Session 27 (Hermes Agent tools/arg_coercion.py, MIT - engine/licenses/HermesAgent-MIT.txt):
    # an object sent as a JSON string, and "null" for a value the model meant to leave out.
    if kind == "object" and isinstance(value, str) and value.strip().startswith("{"):
        parsed = repair_json(value)
        return parsed if isinstance(parsed, dict) else value
    if kind in ("integer", "number", "boolean", "object", "array") and isinstance(value, str) \
            and value.strip().lower() in ("null", "none"):
        return None
    return value


def _coerce_items(value: Any, spec: dict) -> Any:
    """Hermes arg_coercion: array items given as JSON strings where the schema wants objects,
    or numbers/booleans as strings, are converted one by one."""
    items = (spec or {}).get("items") if isinstance(spec, dict) else None
    kind = items.get("type") if isinstance(items, dict) else None
    if not isinstance(value, list) or kind not in ("object", "integer", "number", "boolean"):
        return value
    return [_coerce(v, kind) if isinstance(v, str) else v for v in value]


def _kind_ok(value: Any, kind: str) -> bool:
    return {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }.get(kind, True)


def signature(name: str, params: dict | None) -> str:
    """write_file(path: string, content: string, [mode: string]) - for error messages."""
    params = params or {}
    props = params.get("properties") or {}
    required = set(params.get("required") or [])
    parts = []
    for key, spec in props.items():
        kind = (spec or {}).get("type", "any") if isinstance(spec, dict) else "any"
        parts.append(("%s: %s" if key in required else "[%s: %s]") % (key, kind))
    return "%s(%s)" % (name, ", ".join(parts))


def validate(name: str, args: dict, params: dict | None) -> tuple:
    """(args, error). Coerces obvious type slips; error is "" when the call is good.

    Unknown extra arguments are dropped (a Python tool would crash on them); a missing
    required argument is an error - the guard never fills a value in itself.
    """
    if not isinstance(args, dict):
        return {}, "arguments must be a JSON object. Call it as %s" % signature(name, params)
    params = params or {}
    props = params.get("properties") or {}
    if not props:
        return args, ""
    out, dropped = {}, []
    for key, value in args.items():
        if key not in props:
            dropped.append(key)
            continue
        kind = (props[key] or {}).get("type") if isinstance(props[key], dict) else None
        out[key] = _coerce(value, kind) if kind else value
        if kind == "array":
            out[key] = _coerce_items(out[key], props[key])
    missing = [k for k in params.get("required") or [] if k not in out or out[k] is None]
    if missing:
        hint = " (you sent: %s)" % ", ".join(sorted(args)) if args else ""
        return out, "missing required argument%s %s%s. Call it as %s" % (
            "s" if len(missing) > 1 else "", ", ".join(missing), hint, signature(name, params))
    wrong = []
    for key, value in out.items():
        spec = props.get(key) or {}
        kind = spec.get("type") if isinstance(spec, dict) else None
        if kind and value is not None and not _kind_ok(value, kind):
            wrong.append("%s must be %s, got %s" % (key, kind, type(value).__name__))
        enum = spec.get("enum") if isinstance(spec, dict) else None
        if enum and value not in enum:
            wrong.append("%s must be one of %s" % (key, ", ".join(map(str, enum[:12]))))
    if wrong:
        return out, "; ".join(wrong) + ". Call it as %s" % signature(name, params)
    return out, ""


class Fix:
    """What the guard did to one call: the final name/args, notes, and an error if any."""

    __slots__ = ("name", "args", "notes", "error")

    def __init__(self, name: str, args: dict, notes: list, error: str):
        self.name, self.args, self.notes, self.error = name, args, notes, error

    @property
    def ok(self) -> bool:
        return not self.error


def check_call(name: str, raw_args: Any, schemas: dict) -> Fix:
    """Repair and validate one tool call. `schemas` maps tool name -> parameters schema."""
    notes = []
    real = resolve_name(name, schemas.keys())
    if not real:
        near = difflib.get_close_matches(_norm(name), sorted(schemas), n=3, cutoff=0.5)
        return Fix(name, {}, notes, "there is no tool called %r.%s" % (
            name, (" Did you mean " + " or ".join(near) + "?") if near else ""))
    if real != name:
        notes.append("tool %r -> %s" % (name, real))
    args = repair_json(raw_args)
    if args is None:
        return Fix(real, {}, notes, "the arguments are not valid JSON (%s). Send a JSON object, "
                                    "for example %s" % (str(raw_args)[:120], signature(real, schemas.get(real))))
    if not isinstance(raw_args, dict) and raw_args not in (None, "") and str(raw_args).strip():
        try:
            json.loads(str(raw_args))
        except (ValueError, TypeError):
            notes.append("repaired the JSON arguments")
    args, error = validate(real, args, schemas.get(real))
    return Fix(real, args, notes, error)


# --------------------------------------------------------------------------- calls in text

_PY_CALL = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*$", re.S | re.M)


def parse_function_syntax(text: str, known) -> list:
    """[(name, args)] for calls written as code: write_file(path="a.txt", content="hi").

    Only names that resolve to a real tool, and only keyword arguments (positional ones
    are ambiguous), so prose with parentheses is ignored.
    """
    tools = set(known or ())
    if not text or "(" not in text or not tools:
        return []
    body = text
    fence = re.search(r"```(?:python|py|tool_code)?\s*(.*?)```", text, re.S)
    if fence:
        body = fence.group(1)
    calls = []
    for line in body.splitlines():
        line = line.strip()
        if not line or "(" not in line:
            continue
        try:
            node = ast.parse(line, mode="eval").body
        except SyntaxError:
            continue
        if not isinstance(node, ast.Call) or node.args:
            continue
        func = node.func
        raw = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        real = resolve_name(raw, tools)
        if not real:
            continue
        try:
            args = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords if kw.arg}
        except (ValueError, SyntaxError):
            continue
        calls.append((real, args))
    return calls


# --------------------------------------------------------------------------- constrained decoding

CONSTRAINED_ENV = "LOKI_CONSTRAINED_TOOLS"   # auto (default) | on | off


def constrained_mode() -> str:
    value = (os.getenv(CONSTRAINED_ENV, "auto") or "auto").strip().lower()
    return value if value in ("auto", "on", "off") else "auto"


def _arg_schema(params: dict | None) -> dict:
    params = params or {}
    props = {}
    for key, spec in list((params.get("properties") or {}).items())[:16]:
        if not isinstance(spec, dict):
            continue
        kind = spec.get("type", "string")
        item: dict = {"type": kind if kind in ("string", "integer", "number", "boolean", "array", "object") else "string"}
        if spec.get("enum"):
            item["enum"] = list(spec["enum"])[:16]
        if item["type"] == "array":
            item["items"] = spec.get("items") if isinstance(spec.get("items"), dict) else {"type": "string"}
        props[key] = item
    schema: dict = {"type": "object", "properties": props}
    required = [r for r in params.get("required") or [] if r in props]
    if required:
        schema["required"] = required
    return schema


def constrained_format(tools: list) -> dict:
    """An OpenAI `response_format` that only allows a real tool call or a final answer.

    Shape the model must produce (one action per turn - small models do best that way):
        {"action": "call", "tool": "<name>", "arguments": {...}}
        {"action": "answer", "text": "..."}
    """
    variants = []
    for tool in tools or []:
        fn = tool.get("function", tool) if isinstance(tool, dict) else {}
        name = fn.get("name")
        if not name:
            continue
        variants.append({"type": "object",
                         "properties": {"action": {"const": "call"}, "tool": {"const": name},
                                        "arguments": _arg_schema(fn.get("parameters"))},
                         "required": ["action", "tool", "arguments"]})
    variants.append({"type": "object",
                     "properties": {"action": {"const": "answer"}, "text": {"type": "string"}},
                     "required": ["action", "text"]})
    return {"type": "json_schema",
            "json_schema": {"name": "loki_step", "strict": True, "schema": {"anyOf": variants}}}


CONSTRAINED_PROMPT = (
    "Reply with exactly ONE JSON object and nothing else.\n"
    "To use a tool: {\"action\": \"call\", \"tool\": \"<tool name>\", \"arguments\": {...}}\n"
    "When the task is finished or you only need to talk: {\"action\": \"answer\", \"text\": \"...\"}\n"
    "One tool per reply; the result comes back and you continue.")


def decode_constrained(text: str, known) -> tuple:
    """(calls, answer_text) from a constrained reply. Falls back to the text as-is."""
    data = repair_json(text)
    if not isinstance(data, dict):
        return [], text or ""
    action = str(data.get("action", "")).lower()
    tool = data.get("tool") or data.get("name")
    if action == "call" or (tool and "arguments" in data):
        real = resolve_name(str(tool or ""), known)
        if real:
            args = data.get("arguments")
            args = repair_json(args) if not isinstance(args, dict) else args
            return [(real, args or {})], ""
    if "text" in data or action == "answer":
        return [], str(data.get("text") or "")
    return [], text or ""
