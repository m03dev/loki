"""ReasoningBank: what worked and what failed on similar past tasks, in the next prompt.

Ruflo (github.com/ruvnet/ruflo) gives its agents a "ReasoningBank": every finished task leaves
a short memory - the strategy that worked or the mistake that sank it - and a new task gets the
closest ones before it starts. LOKI's version is built only from what actually happened (no
model is asked to judge itself), on the standard library, beside experience/log.jsonl:

  remember()  - after each request: goal, outcome, the tools in the order they were used, the
                tool errors that repeated (e.g. "conductor: not allowed in a background job x5")
                and the final DONE/BLOCKED line. Secrets are masked.
  recall()    - the most similar past items for a new goal (word overlap weighted by rarity,
                newer first on ties). Failures are kept too: they are the useful warnings.
  prompt_for()- those items as a short "Lessons from similar past tasks" note, which LOKI adds
                to the system prompt for that one request.

LOKI_REASONING_BANK=off turns it off. Every function takes an optional root for tests.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path

import experience

MAX_ITEMS = 2000
STOP = set("""a an and are as at be but by can do for from has have how i in into is it its let
make me my of on or our please so that the their them then there this to up use using want was
we what when where which will with you your loki can could should would just also new add get
""".split())


def _path(root: Path | None = None) -> Path:
    return experience.root_dir(root) / "reasoning_bank.jsonl"


def enabled() -> bool:
    return os.getenv("LOKI_REASONING_BANK", "on").strip().lower() not in ("0", "off", "false", "no")


def words(text: str) -> list:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9_.+-]{2,}", str(text).lower()) if w not in STOP]


def _tool_story(messages: list) -> tuple:
    """(tool names in order, {"tool: error": count}) from one request's messages."""
    names, by_id, errors = [], {}, {}
    for m in messages:
        if not isinstance(m, dict):
            continue
        for call in m.get("tool_calls") or []:
            if isinstance(call, dict):
                name = (call.get("function") or {}).get("name", "")
                if name:
                    names.append(name)
                    by_id[call.get("id", "")] = name
        if m.get("role") == "tool":
            text = str(m.get("content") or "").strip()
            low = text[:200].lower()
            if low.startswith(("error", "not allowed", "blocked", "refused", "failed", "no such", "unknown")) \
                    or "traceback" in low:
                key = "%s: %s" % (by_id.get(m.get("tool_call_id", ""), "tool"),
                                  re.sub(r"\s+", " ", text.splitlines()[0] if text else "")[:90])
                errors[key] = errors.get(key, 0) + 1
    return names, errors


def _compress(names: list, limit: int = 8) -> str:
    """read_file x3 > edit_file > check_loki - repeats folded, at most `limit` steps."""
    steps = []
    for name in names:
        if steps and steps[-1][0] == name:
            steps[-1][1] += 1
        else:
            steps.append([name, 1])
    text = " > ".join(n + (" x%d" % c if c > 1 else "") for n, c in steps[:limit])
    return text + (" > ..." if len(steps) > limit else "")


def _final_line(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "assistant" and (m.get("content") or "").strip():
            text = str(m["content"]).strip()
            match = re.search(r"\b(DONE|BLOCKED)\s*:\s*(.+)", text)
            line = (match.group(1) + ": " + match.group(2)) if match else text
            return re.sub(r"\s+", " ", line)[:200]
    return ""


def remember(goal: str, status: str, outcome: str, messages: list, root: Path | None = None,
             extra: dict | None = None) -> dict | None:
    """Keep one memory of a finished request. Returns it, or None when there is nothing to learn."""
    goal = experience.redact(str(goal or "")).strip()
    if not enabled() or len(words(goal)) < 2:
        return None
    names, errors = _tool_story(messages)
    final = experience.redact(_final_line(messages))
    # experience.outcome_of labels every finished request that wrote no checkable file
    # "unverified" (a chat answer, an image, a report). That is a request that worked; only a
    # failed verification or a blocked/errored request is a lesson in what NOT to do.
    worked = status == "done" and outcome in ("verified", "unverified", "done", "ok", "answered", "")
    if not names and not final:
        return None
    item = {"t": time.time(), "goal": goal[:300], "status": status, "outcome": outcome,
            "worked": bool(worked), "steps": _compress(names), "tool_calls": len(names),
            "errors": sorted(errors.items(), key=lambda kv: -kv[1])[:4], "final": final}
    if extra:
        item.update({k: v for k, v in extra.items() if k in ("kind", "provider", "files", "seconds")})
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(item) + "\n")
    _trim(path)
    return item


def _trim(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_ITEMS * 1.2:
            path.write_text("\n".join(lines[-MAX_ITEMS:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def items(root: Path | None = None) -> list:
    found = []
    try:
        for line in _path(root).read_text(encoding="utf-8").splitlines():
            try:
                found.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return found


def recall(goal: str, k: int = 3, root: Path | None = None, min_shared: int = 2) -> list:
    """The k past items most like `goal` (at least `min_shared` meaningful words in common)."""
    query = set(words(goal))
    pool = items(root)
    if not query or not pool:
        return []
    docs = [set(words(i.get("goal", ""))) for i in pool]
    df = {}
    for d in docs:
        for w in d:
            df[w] = df.get(w, 0) + 1
    n = len(docs)
    scored = []
    for idx, (item, d) in enumerate(zip(pool, docs)):
        shared = query & d
        if len(shared) < min(min_shared, len(query)):
            continue
        score = sum(math.log(1 + n / df[w]) for w in shared) / math.sqrt(len(d) or 1)
        scored.append((score, idx, item))
    scored.sort(key=lambda s: (-s[0], -s[1]))
    picked, seen = [], set()
    for _, _, item in scored:
        key = (item.get("goal", "").lower(), item.get("worked"))
        if key in seen:
            continue
        seen.add(key)
        picked.append(item)
        if len(picked) >= k:
            break
    return picked


def prompt_for(goal: str, k: int = 3, root: Path | None = None, limit: int = 1400) -> str:
    """A short system-prompt note of lessons for this goal ("" when there are none)."""
    if not enabled():
        return ""
    try:
        found = recall(goal, k, root)
    except Exception:  # noqa: BLE001 - lessons are advice, never a failure
        return ""
    if not found:
        return ""
    lines = ["Lessons from similar past tasks (LOKI's ReasoningBank - what really happened before; "
             "use what worked, do not repeat what failed):"]
    for item in found:
        when = time.strftime("%Y-%m-%d", time.localtime(item.get("t", 0)))
        if item.get("worked"):
            line = "- WORKED (%s) \"%s\": %s" % (when, item["goal"][:90], item.get("steps") or "no tools")
            if item.get("final"):
                line += " -> " + item["final"][:120]
        else:
            line = "- FAILED (%s, %s) \"%s\": %s" % (when, item.get("status", ""), item["goal"][:90],
                                                     item.get("final", "")[:120] or "no result")
            errs = "; ".join("%s (x%d)" % (e, c) for e, c in item.get("errors") or [] if c)
            if errs:
                line += ". Repeated errors: " + errs[:240]
            if item.get("tool_calls", 0) >= 20:
                line += ". It took %d tool calls - plan first and stop repeating calls that fail." % item["tool_calls"]
        lines.append(line)
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0]


def summary(root: Path | None = None) -> dict:
    pool = items(root)
    return {"items": len(pool), "worked": sum(1 for i in pool if i.get("worked")),
            "failed": sum(1 for i in pool if not i.get("worked")), "enabled": enabled()}
