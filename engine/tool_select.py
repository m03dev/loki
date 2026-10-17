"""Tool retrieval: let a small model FIND the tool it needs instead of reading all of them.

The idea and flow are langgraph-bigtool's (langchain-ai/langgraph-bigtool,
langgraph_bigtool/graph.py and tools.py: a `retrieve_tools` tool the model calls with a query; the
matching tools are bound to the model for the following turns, `limit` tools per search), MIT -
see engine/licenses/langgraph-bigtool-MIT.txt.

LOKI has ~80 tools plus MCP tools, and a local model is only shown its 22 core tools
(loki.LOCAL_MAX_TOOLS): every schema costs 50-150 prompt tokens and a 7-9B model picks worse
from a long list. So everything else was invisible to it. Now the model calls
`find_tools("make a song")` and the best matches join its list from the next turn on.

bigtool searches an embedding store. LOKI ranks with BM25 over each tool's name (split into
words), description and argument names - no model, no index files, instant, works offline - and
a few synonyms so "song" finds music and "picture" finds images. Pure functions.
"""
from __future__ import annotations

import math
import re
from collections import Counter

K1, B = 1.5, 0.75
DEFAULT_LIMIT = 3       # bigtool's default retrieves 2; 3 suits LOKI's wider tool names
MAX_UNLOCKED = 6        # how many found tools stay added to a local model's list at once

SYNONYMS = {
    "song": "music audio", "music": "song audio", "melody": "music", "beat": "music",
    "picture": "image", "photo": "image", "draw": "image sketch", "art": "image",
    "voice": "speech speak audio", "speak": "voice speech", "read aloud": "speak voice", "say": "speak",
    "website": "web page url", "internet": "web", "google": "web search", "look up": "search web",
    "research": "search web report", "report": "research", "sources": "research web",
    "code": "file edit repo", "codebase": "repo map file", "project": "repo map file",
    "remember": "memory", "recall": "memory", "plan": "planning task", "todo": "task tracker",
    "json": "structured extract", "extract": "structured", "fix": "edit", "change": "edit",
    "patch": "edit apply", "diff": "edit apply", "video": "media render", "movie": "video",
    "mistake": "reflect lesson", "failed": "reflect lesson", "learn": "memory reflect",
}
_WORD = re.compile(r"[a-z0-9]+")


def _stem(word: str) -> str:
    for suffix in ("ing", "ies", "es", "s", "ed"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[:-len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def words(text: str) -> list:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text or "")).replace("_", " ").lower()
    return [_stem(w) for w in _WORD.findall(text) if len(w) > 1]


def expand(query: str) -> list:
    q = str(query or "").lower()
    extra = " ".join(v for k, v in SYNONYMS.items() if k in q)
    return words(q + " " + extra)


def document(schema: dict) -> list:
    fn = schema.get("function", schema) if isinstance(schema, dict) else {}
    name = str(fn.get("name", ""))
    params = ((fn.get("parameters") or {}).get("properties") or {})
    # the name counts three times: it is the strongest signal of what a tool does
    return words(name) * 3 + words(fn.get("description", "")) + words(" ".join(params))


def rank(query: str, schemas: list, limit: int = DEFAULT_LIMIT, exclude=()) -> list:
    """[(name, score)] best first, BM25 over the schemas; tools in `exclude` are skipped."""
    docs = []
    for schema in schemas or []:
        fn = schema.get("function", schema) if isinstance(schema, dict) else {}
        name = fn.get("name")
        if name and name not in exclude:
            docs.append((name, document(schema)))
    if not docs:
        return []
    q = expand(query)
    if not q:
        return []
    n = len(docs)
    avg = sum(len(d) for _, d in docs) / n or 1.0
    df = Counter()
    for _, d in docs:
        df.update(set(d))
    scored = []
    for name, d in docs:
        tf = Counter(d)
        score = 0.0
        for term in set(q):
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * (K1 + 1) / (tf[term] + K1 * (1 - B + B * len(d) / avg))
        if score > 0:
            scored.append((name, round(score, 4)))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored[:max(1, int(limit or DEFAULT_LIMIT))]


def promote(priority: list, names: list, anchor: str = "find_tools", keep: int = MAX_UNLOCKED,
            unlocked: list | None = None) -> list:
    """Put `names` right after `anchor` in a local model's priority list (in place), keeping at most
    `keep` found tools there: the oldest found tool goes back to where it was. Returns the unlocked list."""
    unlocked = unlocked if unlocked is not None else []
    for name in names:
        if name in priority and name not in unlocked:
            continue    # a core tool: already on the list in its own place
        if name in unlocked:
            unlocked.remove(name)
        unlocked.append(name)
    while len(unlocked) > keep:
        old = unlocked.pop(0)
        if old in priority:
            priority.remove(old)
    for name in list(unlocked):
        if name in priority:
            priority.remove(name)
    at = priority.index(anchor) + 1 if anchor in priority else 0
    priority[at:at] = list(unlocked)
    return unlocked


def describe(schemas: list, names: list) -> str:
    by_name = {}
    for schema in schemas or []:
        fn = schema.get("function", schema) if isinstance(schema, dict) else {}
        if fn.get("name"):
            by_name[fn["name"]] = fn
    lines = []
    for name in names:
        fn = by_name.get(name)
        if not fn:
            continue
        params = (fn.get("parameters") or {}).get("properties") or {}
        required = set((fn.get("parameters") or {}).get("required") or [])
        args = ", ".join(("%s*" % p) if p in required else p for p in params)
        lines.append("- %s(%s): %s" % (name, args, str(fn.get("description", ""))[:220]))
    return "\n".join(lines)
