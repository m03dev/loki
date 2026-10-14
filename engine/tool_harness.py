"""Any model can use any tool: the prompted tool-calling harness.

Most providers take an OpenAI `tools` list and answer with structured `tool_calls`. Many
do not: small local models (MLX, llama.cpp without --jinja, older Ollama models), keyless
endpoints and some free tiers either reject `tools` outright or ignore them. For those,
this module turns native tool calling into plain text and back, so the agent loop in
loki.py never knows the difference:

  outgoing  tools=[...]            -> a system block describing every tool, Hermes style:
                                      <tool_call>{"name": ..., "arguments": {...}}</tool_call>
            assistant tool_calls    -> the same <tool_call> text in the assistant message
            role=tool results       -> a user message wrapped in <tool_response>
  incoming  text with <tool_call>   -> real tool_calls objects on the response message

The format is the Hermes function-calling format that most open fine-tunes (Qwen, Hermes,
Llama-3 tool finetunes) were trained on, so even a 1-3B model follows it well. The parser
is forgiving: it also accepts ```json fences and bare {"name":..,"arguments":..} objects,
but only for names that are real tools, so ordinary JSON in a reply is left alone.

When is it used?
  - the provider is listed in LOKI_PROMPTED_TOOLS (comma list), or its catalog entry says
    tools=false (providers_catalog.py), or
  - a provider refused the tool list even when cut down to one tool (loki._model_request
    switches the rest of the session to prompted mode for that provider).
Pure functions; no network, no globals except the per-provider "learned" set.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

# Providers that have shown they cannot take a native tools list (learned this session).
LEARNED: set = set()

_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S | re.I)
_FENCE_RE = re.compile(r"```(?:json|tool_call|tool)?\s*(\{.*?\})\s*```", re.S | re.I)


def configured(provider: str) -> bool:
    """True when this provider should get tools as text instead of a native list."""
    name = (provider or "").strip().lower()
    if not name:
        return False
    if name in LEARNED:
        return True
    listed = {p.strip().lower() for p in os.getenv("LOKI_PROMPTED_TOOLS", "").split(",") if p.strip()}
    if name in listed:
        return True
    try:
        import providers_catalog  # pylint: disable=import-outside-toplevel
        entry = providers_catalog.get(name)
        return bool(entry) and entry.get("tools") is False
    except Exception:  # noqa: BLE001 - the catalog is optional here
        return False


def learn(provider: str) -> None:
    if provider:
        LEARNED.add(provider.strip().lower())


# --------------------------------------------------------------------------- outgoing
def _short_schema(params: Any) -> dict:
    """Keep the parameter schema small: small models drown in long JSON schemas."""
    if not isinstance(params, dict):
        return {}
    props = params.get("properties") or {}
    out = {}
    for key, spec in list(props.items())[:24]:
        if not isinstance(spec, dict):
            continue
        item = {"type": spec.get("type", "string")}
        if spec.get("description"):
            item["description"] = str(spec["description"])[:160]
        if spec.get("enum"):
            item["enum"] = spec["enum"][:12]
        out[key] = item
    result = {"type": "object", "properties": out}
    if params.get("required"):
        result["required"] = list(params["required"])
    return result


def tools_prompt(tools: list) -> str:
    """The system block that teaches any model to call these tools in text."""
    lines = []
    for tool in tools or []:
        fn = tool.get("function", tool) if isinstance(tool, dict) else {}
        name = fn.get("name")
        if not name:
            continue
        lines.append(json.dumps({"name": name, "description": str(fn.get("description", ""))[:300],
                                 "parameters": _short_schema(fn.get("parameters"))},
                                ensure_ascii=False))
    return (
        "You can call tools. Available tools (one JSON object per line):\n"
        "<tools>\n" + "\n".join(lines) + "\n</tools>\n\n"
        "To call a tool, reply with one or more blocks exactly like this and nothing else:\n"
        "<tool_call>\n{\"name\": \"TOOL_NAME\", \"arguments\": {\"arg\": \"value\"}}\n</tool_call>\n"
        "Results come back inside <tool_response>...</tool_response>. Use only the tools above, "
        "with valid JSON arguments. When you need no tool, answer normally in plain text.")


def _call_text(call: dict) -> str:
    fn = call.get("function") or {}
    args = fn.get("arguments", "{}")
    try:
        parsed = json.loads(args) if isinstance(args, str) else (args or {})
    except (ValueError, TypeError):
        parsed = {}
    return "<tool_call>\n%s\n</tool_call>" % json.dumps({"name": fn.get("name", ""), "arguments": parsed},
                                                       ensure_ascii=False)


def to_prompted(messages: list, tools: list) -> list:
    """A copy of `messages` with tool use written as text (for a provider without tools)."""
    out: list = []
    block = tools_prompt(tools)
    placed = False
    for raw in messages:
        msg = dict(raw) if isinstance(raw, dict) else dict(getattr(raw, "model_dump", lambda: {})())
        role = msg.get("role")
        if role == "system" and not placed:
            out.append({"role": "system", "content": (str(msg.get("content") or "") + "\n\n" + block).strip()})
            placed = True
            continue
        if role == "assistant" and msg.get("tool_calls"):
            text = str(msg.get("content") or "").strip()
            calls = "\n".join(_call_text(c if isinstance(c, dict) else c.model_dump()) for c in msg["tool_calls"])
            out.append({"role": "assistant", "content": (text + "\n" + calls).strip()})
            continue
        if role == "tool":
            body = str(msg.get("content") or "")
            # Merge consecutive tool results into one user turn (strict alternation).
            if out and out[-1].get("role") == "user" and str(out[-1].get("content", "")).startswith("<tool_response>"):
                out[-1]["content"] += "\n<tool_response>\n%s\n</tool_response>" % body
            else:
                out.append({"role": "user", "content": "<tool_response>\n%s\n</tool_response>" % body})
            continue
        clean = {"role": role, "content": msg.get("content") if msg.get("content") is not None else ""}
        out.append(clean)
    if not placed:
        out.insert(0, {"role": "system", "content": block})
    return out


def prepare(kwargs: dict) -> dict:
    """Request kwargs rewritten for prompted tools (no `tools`/`tool_choice` sent)."""
    new = dict(kwargs)
    tools = new.pop("tools", None) or []
    new.pop("tool_choice", None)
    new.pop("parallel_tool_calls", None)
    new["messages"] = to_prompted(list(new.get("messages") or []), tools)
    new["_prompted_tools"] = [((t.get("function") or t).get("name")) for t in tools if isinstance(t, dict)]
    return new


# --------------------------------------------------------------------------- incoming
def _candidates(text: str) -> list:
    found = _CALL_RE.findall(text)
    if found:
        return found
    found = _FENCE_RE.findall(text)
    if found:
        return found
    # Bare objects: the balanced {...} spans of the text.
    spans, depth, start = [], 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append(text[start:i + 1])
    return spans


def _loads(blob: str) -> Any:
    try:
        return json.loads(blob)
    except (ValueError, TypeError):
        # Common small-model slips: single quotes, trailing commas.
        fixed = re.sub(r",\s*([}\]])", r"\1", blob)
        if "'" in fixed and '"' not in fixed:
            fixed = fixed.replace("'", '"')
        try:
            return json.loads(fixed)
        except (ValueError, TypeError):
            return None


def parse(text: str, known: list | set | None = None) -> tuple:
    """(calls, remaining_text) from a model reply. calls = [(name, args_dict), ...]."""
    if not text:
        return [], text or ""
    names = set(known or [])
    calls = []
    for blob in _candidates(text):
        data = _loads(blob)
        if isinstance(data, list):
            items = data
        else:
            items = [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("function"), dict):
                item = item["function"]
            name = item.get("name") or item.get("tool")
            if not isinstance(name, str) or (names and name not in names):
                continue
            args = item.get("arguments", item.get("parameters", item.get("args", {})))
            if isinstance(args, str):
                args = _loads(args) or {}
            calls.append((name, args if isinstance(args, dict) else {}))
    rest = _CALL_RE.sub("", text).strip() if calls else text
    return calls, rest


def attach(response: Any, known: list) -> Any:
    """Turn <tool_call> text in an OpenAI response into real tool_calls, in place."""
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError):
        return response
    if getattr(message, "tool_calls", None):
        return response
    calls, rest = parse(message.content or "", known)
    if not calls:
        return response
    try:
        from openai.types.chat import ChatCompletionMessageToolCall  # pylint: disable=import-outside-toplevel
        objs = [ChatCompletionMessageToolCall(
            id="call_" + uuid.uuid4().hex[:12], type="function",
            function={"name": name, "arguments": json.dumps(args, ensure_ascii=False)}) for name, args in calls]
    except Exception:  # noqa: BLE001 - very old/new openai SDKs: fall back to a duck type
        class _Fn:
            def __init__(self, name, arguments):
                self.name, self.arguments = name, arguments

        class _Call:
            def __init__(self, name, args):
                self.id, self.type = "call_" + uuid.uuid4().hex[:12], "function"
                self.function = _Fn(name, json.dumps(args, ensure_ascii=False))

            def model_dump(self):
                return {"id": self.id, "type": "function",
                        "function": {"name": self.function.name, "arguments": self.function.arguments}}
        objs = [_Call(name, args) for name, args in calls]
    message.tool_calls = objs
    message.content = rest or None
    try:
        response.choices[0].finish_reason = "tool_calls"
    except Exception:  # noqa: BLE001
        pass
    return response
