"""After a chat or a job: the few durable things worth remembering, and nothing else.

LOKI learns from what the OWNER says (his own messages in the request, never the model's replies or
tool output, which are full of guesses and pasted content). The rules below catch the statements
people make about themselves and their work:

    "my name is Sam" / "call me Sam"                      -> profile / preference
    "I prefer short answers" / "I hate light themes"       -> preference
    "always answer in English" / "never push on Fridays"   -> preference (how LOKI should behave)
    "my editor is Zed" / "my PC has an RTX 3070 Ti"         -> profile
    "Mia is my sister" / "my boss is Dana"                  -> person
    "I'm working on Waypoint, a Maya companion"            -> project
    "we decided to use Godot for the racing game"           -> decision
    "remember that the relay port is 41234"                 -> whatever kind it is

Every candidate is rewritten in the third person ("The owner prefers short answers"), then filtered:
no secrets at all (the whole sentence is dropped - memory_kinds.is_secret), no questions, no small
talk, nothing only about "right now", nothing too short or too long, at most MAX_PER_REQUEST per
request. memory_core.learn then dedupes, merges near-duplicates and supersedes contradictions.
Everything learned here is marked review="new" so Settings > Memory can say "LOKI learned 3 things
today" with Undo next to each one.

A model can do the same job (LOKI_MEMORY_EXTRACT=model and an `ask` function): it gets a strict
prompt, returns JSON, and its answers pass the very same filters. LOKI_MEMORY_EXTRACT=off stops
automatic learning; the default is the rules (free, offline, instant).
"""
from __future__ import annotations

import json
import os
import re

import memory_kinds

MAX_PER_REQUEST = 3
MODEL_PROMPT = """From the user's message below, list the durable facts worth remembering about the user,
their projects, people, preferences and decisions - things still true next month. Not tasks, not questions,
not anything only about today, never passwords, keys or other secrets. Write each in the third person
starting with "The owner" (or a person's name). Answer with JSON only: {"facts": [{"text": "...",
"kind": "profile|preference|person|project|decision|fact"}]} - an empty list when there is nothing.

User message:
"""

_SENT = re.compile(r"(?<=[.!?;])\s+|\n+")
_PEOPLE = memory_kinds.PEOPLE
RULES = [
    (re.compile(r"^(?:please\s+)?(?:remember|note|keep in mind)\s+(?:that\s+)?(?P<x>.+)$", re.I), "", None),
    (re.compile(r"^my name is (?P<x>[A-Z][\w'-]+(?: [A-Z][\w'-]+)?)\b", re.I), "profile", "The owner's name is {x}"),
    (re.compile(r"^(?:you can )?call me (?P<x>[A-Z][\w'-]+)\b", re.I), "preference", "The owner wants to be called {x}"),
    (re.compile(r"^(?P<who>[A-Z][a-z]+) is my (?P<rel>%s)\b(?P<rest>.*)$" % _PEOPLE, re.I), "person",
     "{who} is the owner's {rel}{rest}"),
    (re.compile(r"^my (?P<rel>%s)(?:'s name)? is (?P<who>[A-Z][\w'-]+)(?P<rest>.*)$" % _PEOPLE, re.I), "person",
     "{who} is the owner's {rel}{rest}"),
    (re.compile(r"^(?:we|i)(?: have| had|'ve)? (?:decided|agreed|chose|settled on|are going with|will go with|"
                r"'re going with|went with|picked)\s+(?P<x>.+)$", re.I), "decision", "The owner decided {x}"),
    (re.compile(r"^(?:from now on|going forward),?\s+(?P<x>.+)$", re.I), "preference", "From now on, the owner wants: {x}"),
    (re.compile(r"^(?P<adv>always|never|don'?t ever|do not ever)\s+(?P<x>.+)$", re.I), "preference",
     "The owner wants LOKI to {adv} {x}"),
    (re.compile(r"^i (?P<v>prefer|like|love|hate|dislike|enjoy|can'?t stand|always|never)\s+(?P<x>.+)$", re.I),
     "preference", "The owner {v_s} {x}"),
    (re.compile(r"^i(?:'m| am) (?:working on|building|making|developing)\s+(?P<x>.+)$", re.I), "project",
     "The owner is working on {x}"),
    (re.compile(r"^my (?:project|app|game|startup|company|repo|business) (?P<x>.+)$", re.I), "project",
     "The owner's project {x}"),
    (re.compile(r"^i (?P<v>live|work|use|run|own|have|speak|study)\s+(?P<x>.+)$", re.I), "profile", "The owner {v_s} {x}"),
    (re.compile(r"^i(?:'m| am) (?P<x>(?:a|an|based|from|in) .+)$", re.I), "profile", "The owner is {x}"),
    (re.compile(r"^my (?P<what>[a-z][\w -]{1,30}?) (?P<v>is|are|was) (?P<x>.+)$", re.I), "profile",
     "The owner's {what} {v} {x}"),
]
_THIRD = {"prefer": "prefers", "like": "likes", "love": "loves", "hate": "hates", "dislike": "dislikes",
          "enjoy": "enjoys", "can't stand": "can't stand", "cant stand": "can't stand", "always": "always",
          "never": "never", "live": "lives", "work": "works", "use": "uses", "run": "runs", "own": "owns",
          "have": "has", "speak": "speaks", "study": "studies"}


def mode(env: dict | None = None) -> str:
    value = str((env if env is not None else os.environ).get("LOKI_MEMORY_EXTRACT", "rules")).strip().lower()
    return value if value in ("rules", "model", "off") else "rules"


def third_person(text: str) -> str:
    """'my' -> "the owner's", 'I'/'me' -> 'the owner' - inside an already-matched sentence."""
    text = re.sub(r"\bI'm\b|\bI am\b", "the owner is", text)
    text = re.sub(r"\bmy\b", "the owner's", text, flags=re.I)
    text = re.sub(r"\b(I|me)\b", "the owner", text)
    text = re.sub(r"\bmine\b", "the owner's", text, flags=re.I)
    return text


def _tidy(text: str) -> str:
    text = " ".join(str(text).split()).strip(" ,;:-")
    text = re.sub(r"\s+([.,!])", r"\1", text)
    if text and text[-1] not in ".!":
        text += "."
    return text[0].upper() + text[1:] if text else text


def sentences(text: str) -> list:
    out = []
    for raw in _SENT.split(str(text or "")):
        s = raw.strip().strip("\"'`").strip()
        s = re.sub(r"^(?:also|and|btw|by the way|oh|ok|okay|so|fyi|note:)\s*,?\s+", "", s, flags=re.I)
        if s:
            out.append(s)
    return out


def from_rules(text: str) -> list:
    """[(sentence, kind)] candidates from one message of the owner."""
    out = []
    for s in sentences(text):
        if memory_kinds.is_secret(s):
            continue                    # never remember a sentence that carries a secret
        core = s.rstrip(".!")
        for pattern, kind, template in RULES:
            m = pattern.match(core)
            if not m:
                continue
            groups = {k: (v or "").strip() for k, v in m.groupdict().items()}
            if template is None:        # "remember that ...": keep the sentence, find its kind
                body = third_person(groups["x"])
                kind = memory_kinds.kind_of(body)
            else:
                v = groups.get("v", "").lower()
                groups["v_s"] = _THIRD.get(v, v)
                groups["x"] = third_person(groups.get("x", ""))
                rest = third_person(groups.get("rest", ""))
                groups["rest"] = (" " + rest) if rest and rest[0].isalnum() else rest
                groups["what"] = groups.get("what", "").lower()
                groups["rel"] = groups.get("rel", "").lower()
                groups["adv"] = groups.get("adv", "").lower().replace("don't ever", "never").replace("do not ever", "never")
                body = template.format(**groups)
            body = _tidy(body)
            if not memory_kinds.is_junk(body) and not memory_kinds.is_secret(body):
                out.append((body, kind))
            break
    return out


def from_model(text: str, ask) -> list:
    """[(sentence, kind)] from a model's JSON answer, through the same filters as the rules."""
    try:
        raw = ask(MODEL_PROMPT + str(text)[:4000])
        start, end = raw.find("{"), raw.rfind("}")
        facts = json.loads(raw[start:end + 1]).get("facts") if start >= 0 else []
    except Exception:  # noqa: BLE001 - a model that answers badly teaches nothing
        return []
    out = []
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        body = _tidy(str(fact.get("text", "")))
        kind = str(fact.get("kind", "fact")).lower()
        if kind not in ("profile", "preference", "person", "project", "decision", "fact"):
            kind = memory_kinds.kind_of(body)
        if body and not memory_kinds.is_junk(body) and not memory_kinds.is_secret(body):
            out.append((body, kind))
    return out


def owner_messages(messages: list) -> list:
    """The owner's own words in one request (not tool results, not the model)."""
    out = []
    for m in messages or []:
        if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
            out.append(m["content"])
    return out


def extract(messages: list, ask=None, env: dict | None = None) -> list:
    """[(sentence, kind)] worth remembering from one request, at most MAX_PER_REQUEST."""
    how = mode(env)
    if how == "off":
        return []
    found: list = []
    for text in owner_messages(messages):
        if len(text) > 6000 or text.lstrip().startswith(("/", "```")):
            continue                    # a pasted file or a command, not something said
        if how == "model" and ask is not None:
            found += from_model(text, ask)
        else:
            found += from_rules(text)
    seen, out = set(), []
    for body, kind in found:
        key = body.lower()
        if key not in seen:
            seen.add(key)
            out.append((body, kind))
    return out[:MAX_PER_REQUEST]
