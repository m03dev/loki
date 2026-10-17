"""Structured output that a small model gets right: constrain, validate, re-ask.

The retry loop and its re-ask message are instructor's (567-labs/instructor: `max_retries`,
`reask_*` handlers - "Validation Error found: ... Recall the function correctly, fix the errors
found in the following attempt"), MIT - see engine/licenses/instructor-MIT.txt. instructor
validates with pydantic; LOKI validates with a small JSON Schema checker here (the subset models
and Ollama's `format` use: type, properties, required, enum, const, items, min/max,
minLength/maxLength, minItems/maxItems, additionalProperties, anyOf), so no dependency.

Three layers, each catching what the one before misses:
  1. constrained decoding - a local server (Ollama `format`, llama.cpp, LM Studio) given the
     schema as response_format can only emit JSON of that shape (`response_format(schema)`)
  2. lenient parsing - fences, prose around the object, trailing commas, single quotes
     (tool_guard.repair_json / json_object_spans, already in LOKI)
  3. validation + re-ask - every schema error is listed back to the model with its last attempt,
     instructor-style, up to `retries` times
Pure functions + one async loop over an injected `ask(prompt, schema=...)`; no network here.
"""
from __future__ import annotations

import json
import re

import tool_guard

DEFAULT_RETRIES = 2
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def strip_thinking(text: str) -> str:
    """Reasoning models (qwen3, deepseek-r1) wrap thoughts in <think>; they are not the answer."""
    text = _THINK.sub("", str(text or ""))
    if "<think>" in text and "</think>" not in text:   # cut off mid-thought
        text = text.split("<think>", 1)[0]
    return text.strip()


def response_format(schema: dict, name: str = "loki_output") -> dict:
    """The OpenAI-style response_format Ollama / llama.cpp / LM Studio accept for constrained JSON."""
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


def _type_ok(value, kind) -> bool:
    if isinstance(kind, list):
        return any(_type_ok(value, k) for k in kind)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    py = _TYPES.get(kind)
    return True if py is None else isinstance(value, py) and not (kind != "boolean" and isinstance(value, bool))


def validate(schema: dict, value, path: str = "$") -> list:
    """Every way `value` breaks `schema`, as readable lines (empty = valid)."""
    if not isinstance(schema, dict) or not schema:
        return []
    errors = []
    if "anyOf" in schema or "oneOf" in schema:
        options = schema.get("anyOf") or schema.get("oneOf") or []
        results = [validate(option, value, path) for option in options]
        if all(results):
            best = min(results, key=len)
            return ["%s matches none of the allowed shapes; closest: %s" % (path, "; ".join(best[:3]))]
        return []
    kind = schema.get("type")
    if kind and not _type_ok(value, kind):
        return ["%s should be %s, got %s" % (path, kind if isinstance(kind, str) else " or ".join(kind),
                                             type(value).__name__ if value is not None else "null")]
    if "const" in schema and value != schema["const"]:
        errors.append("%s must be %s" % (path, json.dumps(schema["const"])))
    if "enum" in schema and value not in schema["enum"]:
        errors.append("%s must be one of %s, got %s" % (path, json.dumps(schema["enum"]), json.dumps(value)))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append("%s is shorter than %d characters" % (path, schema["minLength"]))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append("%s is longer than %d characters" % (path, schema["maxLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append("%s does not match the pattern %s" % (path, schema["pattern"]))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append("%s must be >= %s" % (path, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append("%s must be <= %s" % (path, schema["maximum"]))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append("%s needs at least %d items" % (path, schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append("%s has more than %d items" % (path, schema["maxItems"]))
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                errors += validate(schema["items"], item, "%s[%d]" % (path, i))
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                errors.append("%s.%s is required but missing" % (path, key))
        for key, sub in props.items():
            if key in value:
                errors += validate(sub, value[key], "%s.%s" % (path, key))
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(props))
            if extra:
                errors.append("%s has properties that are not allowed: %s" % (path, ", ".join(extra)))
    return errors


def parse(text: str):
    """The JSON value in a model's reply (object or array), forgiving the usual small-model noise."""
    text = strip_thinking(text)
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    if text.lstrip().startswith("["):
        try:
            return json.loads(text[text.index("["):text.rindex("]") + 1])
        except ValueError:
            pass
    if not text:
        return None
    if text.lstrip().startswith("{"):
        repaired = tool_guard.repair_json(text)
        if repaired:
            return repaired
    for span in tool_guard.json_object_spans(text):
        fixed = tool_guard.repair_json(span)
        if fixed is not None:
            return fixed
    return None


def reask_message(errors: list, attempt: str) -> str:
    """instructor's re-ask, for a plain chat turn."""
    return ("Validation Error found:\n%s\nRecall the function correctly, fix the errors found in the "
            "following attempt:\n%s\nReply with the corrected JSON only."
            % ("\n".join("- " + e for e in errors[:12]), str(attempt)[:3000]))


def schema_prompt(instruction: str, schema: dict) -> str:
    return ("%s\n\nReply with ONE JSON value and nothing else. It must match this JSON Schema:\n%s"
            % (instruction.strip(), json.dumps(schema, indent=1)[:4000]))


async def ask_structured(ask, instruction: str, schema: dict, retries: int = DEFAULT_RETRIES) -> dict:
    """Ask until the answer validates. `ask(prompt, schema=...)` is an async model call returning text.

    Returns {"ok": bool, "value": ..., "attempts": n, "errors": [...]}."""
    prompt = schema_prompt(instruction, schema)
    errors: list = []
    value = None
    for attempt in range(1, int(retries) + 2):
        reply = await ask(prompt, schema=schema)
        value = parse(reply)
        if value is None:
            errors = ["the reply was not JSON"]
        else:
            errors = validate(schema, value)
            if not errors:
                return {"ok": True, "value": value, "attempts": attempt, "errors": []}
        prompt = schema_prompt(instruction, schema) + "\n\n" + reask_message(errors, reply)
    return {"ok": False, "value": value, "attempts": int(retries) + 1,
            "errors": errors}
