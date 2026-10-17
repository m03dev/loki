"""Options - "did you mean...?" done properly.

When a request is short and open ("make me a game", "improve the website", "ideas for the
launch"), LOKI first offers 3 or 4 DIFFERENT readings of what you might mean, each with what it
would do, and you pick one (or send it as written). The picked option is sent as a precise
request, so the agent starts from the right goal instead of guessing.

LOKI_OPTIONS (Settings > General): "auto" (default - only when a request looks open), "always",
or "off". "/options <text>" asks for them on purpose.

The decision is cheap and local (`looks_open`); only when it says yes is a model asked, once,
for JSON. A model that fails or answers badly just means no options: the request goes ahead.
"""
from __future__ import annotations

import json
import os
import re

MIN, MAX = 3, 4

_OPEN_WORDS = re.compile(
    r"\b(make|build|create|design|improve|redo|rework|upgrade|better|idea|ideas|suggest|suggestions|options|"
    r"plan|write|draft|start|help me|something|thing|app|game|website|site|logo|brand|name|story|video|"
    r"marketing|launch|feature|features|fix everything|what should|which|how should|could you|can you)\b", re.I)
_ALWAYS = re.compile(r"\b(options|alternatives|suggestions|ideas|different ways|what could|what should i)\b", re.I)
_SPECIFIC = re.compile(r"(```|https?://|@[\w./-]+|\b[\w-]+\.(py|js|ts|tsx|css|html|json|md|gd|cs|cpp|go|rs|java|yml|yaml|toml)\b|"
                       r"\berror\b|traceback|line \d+|\d{3,})", re.I)
_FACTUAL = re.compile(r"^(what|when|who|where|why|how many|how much|is|are|does|do|did)\b.*\?$", re.I)


def mode(env: dict | None = None) -> str:
    value = str((env if env is not None else os.environ).get("LOKI_OPTIONS", "auto")).strip().lower()
    return value if value in ("auto", "always", "off") else "auto"


def looks_open(text: str) -> bool:
    """True when the request is short, open-ended and names nothing concrete."""
    t = (text or "").strip()
    if not t or t.startswith("/") or "\n\n" in t:
        return False
    words = t.split()
    if len(words) < 2 or len(words) > 40:
        return False
    if _SPECIFIC.search(t):
        return False
    if _ALWAYS.search(t):
        return True
    if _FACTUAL.match(t) and len(words) <= 12:
        return False          # a plain question gets a plain answer
    return len(words) <= 25 and bool(_OPEN_WORDS.search(t))


def should_offer(text: str, force: bool = False, env: dict | None = None) -> bool:
    if force:
        return bool((text or "").strip())
    m = mode(env)
    if m == "off":
        return False
    if m == "always":
        t = (text or "").strip()
        return bool(t) and not t.startswith("/") and len(t.split()) <= 60
    return looks_open(text)


def prompt(text: str, context: str = "") -> str:
    ctx = ("\nWhat LOKI knows about the situation:\n" + context.strip()[:1500] + "\n") if context.strip() else ""
    return (
        "You are LOKI, a desktop AI agent that can write code, edit files, research, plan and run agent teams.\n"
        "The user wrote this request:\n<<<\n%s\n>>>\n%s\n"
        "It can be read in more than one way. Give %d or %d genuinely DIFFERENT readings of what they most likely "
        "mean - different goals or scopes, not the same thing reworded - most likely first. For each: a short title "
        "(2-5 words), what you think they mean (one sentence), what LOKI would do (one sentence), and the request "
        "rewritten so it is specific and unambiguous, written as the user would say it.\n"
        "Answer with JSON only, no other text:\n"
        '{"options": [{"title": "...", "meaning": "...", "plan": "...", "prompt": "..."}]}'
    ) % (text.strip()[:2000], ctx, MIN, MAX)


def parse(raw: str) -> list:
    """The options in a model reply; [] when there are fewer than two usable ones."""
    raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S)
    start, end = raw.find("{"), raw.rfind("}")
    items = None
    if start >= 0 and end > start:
        try:
            items = json.loads(raw[start:end + 1]).get("options")
        except (ValueError, AttributeError):
            items = None
    if items is None:
        start, end = raw.find("["), raw.rfind("]")
        if start >= 0 and end > start:
            try:
                items = json.loads(raw[start:end + 1])
            except ValueError:
                items = None
    out, seen = [], set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()[:60]
        request = str(item.get("prompt", "")).strip()[:1200]
        if not title or not request or request.lower() in seen:
            continue
        seen.add(request.lower())
        out.append({"title": title, "meaning": str(item.get("meaning", "")).strip()[:300],
                    "plan": str(item.get("plan", "")).strip()[:300], "prompt": request})
        if len(out) == MAX:
            break
    return out if len(out) >= 2 else []


async def suggest(text: str, complete, context: str = "") -> dict:
    """complete(prompt) -> reply text (async). Returns {"options": [...], "error": ""}."""
    try:
        reply = await complete(prompt(text, context))
    except Exception as exc:  # noqa: BLE001 - no options is a fine outcome
        return {"options": [], "error": "could not get options: %s" % str(exc)[:200]}
    found = parse(reply)
    return {"options": found, "error": "" if found else "the model did not give usable options"}
