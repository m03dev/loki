"""Skill learning (roadmap E2): LOKI writes down a procedure that worked, and uses it next time.

After a request that was VERIFIED done (every changed file checked) and took more than
MIN_TOOL_CALLS tool calls, the steps that worked become a SKILL.md in
harness_data/skills/learned/<slug>/ - the same folder format every other skill uses
(agents.skills_catalog lists it under "learned"). The next similar request gets it in its
memory pack (memory_core.pack) and the reply says "used learned skill <id>".

What a learned skill holds (built only from what actually happened - no model is asked to
judge itself, the same rule as reasoning_bank.py):

    When to use       the request it came from
    Steps that worked the tool calls in order, with the file or argument that mattered,
                      repeats folded ("read_file engine/loki.py x3")
    Files             what it changed
    Pitfalls          tool errors on the way (so the next run avoids them)
    Result            the final DONE line

A request like an earlier learned skill (most of its words in common) refreshes that skill
instead of adding a near-copy. Secrets are masked; a skill that the safety scan would block
is not kept. LOKI_SKILL_LEARNING=off turns it off. Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

MIN_TOOL_CALLS = int(os.getenv("LOKI_SKILL_MIN_CALLS", "5") or 5)
MAX_STEPS = 24
SIMILAR = 0.6
_KEY_ARGS = ("filename", "path", "file", "subdir", "pattern", "suite", "url", "query", "role", "name",
             "command", "action")


def enabled(env: dict | None = None) -> bool:
    return str((env if env is not None else os.environ).get("LOKI_SKILL_LEARNING", "on")).strip().lower() \
        not in ("0", "off", "false", "no")


def _data(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def learned_dir(root: Path | None = None) -> Path:
    return _data(root) / "skills" / "learned"


def _index_path(root: Path | None = None) -> Path:
    return learned_dir(root) / "index.json"


def _index(root: Path | None = None) -> dict:
    try:
        return json.loads(_index_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_index(data: dict, root: Path | None = None) -> None:
    path = _index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _words(text: str) -> set:
    stop = {"the", "and", "for", "with", "that", "this", "from", "into", "loki", "make", "add", "please"}
    return {w for w in re.findall(r"[a-z0-9][a-z0-9_.-]{2,}", str(text).lower()) if w not in stop}


def slug(text: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", str(text).lower()) if len(w) > 2][:6]
    return ("-".join(words) or "skill")[:48].strip("-") or "skill"


def should_learn(status: str, outcome: str, tool_calls: int, min_calls: int = MIN_TOOL_CALLS) -> bool:
    return enabled() and status == "done" and outcome == "verified" and int(tool_calls or 0) > min_calls


def _scrub(text: str) -> str:
    try:
        import memory_core  # pylint: disable=import-outside-toplevel
        return memory_core.scrub(text)
    except Exception:  # noqa: BLE001
        return str(text)


def steps_from(messages: list) -> tuple:
    """([(tool, key argument)], [pitfalls], final line, [files changed]) from one request."""
    calls, by_id, pitfalls, files = [], {}, [], []
    for m in messages:
        if not isinstance(m, dict):
            continue
        for call in m.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") or {}
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            key = ""
            if isinstance(args, dict):
                for k in _KEY_ARGS:
                    if args.get(k):
                        key = str(args[k]).splitlines()[0][:80]
                        break
                if name in ("write_file", "edit_file", "append_file", "insert_lines") and args.get("filename"):
                    files.append(str(args["filename"]))
            calls.append((name, key))
            by_id[call.get("id", "")] = (name, key)
        if m.get("role") == "tool":
            text = str(m.get("content") or "").strip()
            low = text[:160].lower()
            if low.startswith(("error", "refused", "not allowed", "failed", "some failed", "not shipped")):
                name, key = by_id.get(m.get("tool_call_id", ""), ("tool", ""))
                line = "%s%s: %s" % (name, (" " + key) if key else "", re.sub(r"\s+", " ", text)[:140])
                if line not in pitfalls:
                    pitfalls.append(line)
    final = ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "assistant" and str(m.get("content") or "").strip():
            final = re.sub(r"\s+", " ", str(m["content"]).strip())[:240]
            break
    return calls, pitfalls[:6], final, list(dict.fromkeys(files))[:12]


def _fold(calls: list) -> list:
    out = []
    for name, key in calls:
        if out and out[-1][0] == name and out[-1][1] == key:
            out[-1][2] += 1
        else:
            out.append([name, key, 1])
    return out[:MAX_STEPS]


def render(goal: str, calls: list, pitfalls: list, final: str, files: list, sid: str, uses: int = 0) -> str:
    goal = _scrub(" ".join(str(goal).split()))
    desc = goal[:200].replace("\n", " ").replace(":", " -")
    lines = ["---", "name: %s" % sid, "description: Learned by LOKI from a verified request - %s" % desc,
             "source: learned", "---", "", "# %s" % goal[:120], "",
             "## When to use", "", "A request like: %s" % goal[:400], "",
             "## Steps that worked", ""]
    for i, (name, key, count) in enumerate(_fold(calls), 1):
        lines.append("%d. `%s`%s%s" % (i, name, (" " + _scrub(key)) if key else "", (" (x%d)" % count) if count > 1 else ""))
    if files:
        lines += ["", "## Files it changed", ""] + ["- %s" % f for f in files]
    if pitfalls:
        lines += ["", "## Pitfalls seen on the way (avoid them)", ""] + ["- %s" % _scrub(p) for p in pitfalls]
    if final:
        lines += ["", "## Result", "", _scrub(final)]
    return "\n".join(lines) + "\n"


def learned(root: Path | None = None) -> list:
    """[{id, name, description, path, t, uses}] for every learned skill."""
    base = learned_dir(root)
    if not base.is_dir():
        return []
    index = _index(root)
    out = []
    for md in sorted(base.glob("*/SKILL.md")):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta = {}
        if text.startswith("---"):
            for line in text.split("---", 2)[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
        sid = md.parent.name
        info = index.get(sid, {})
        out.append({"id": sid, "name": meta.get("name", sid), "description": meta.get("description", ""),
                    "path": str(md), "t": info.get("t", md.stat().st_mtime), "uses": info.get("uses", 0),
                    "goal": info.get("goal", "")})
    return out


def body(sid: str, root: Path | None = None) -> str:
    md = learned_dir(root) / re.sub(r"[^a-z0-9_-]", "", str(sid).lower()) / "SKILL.md"
    try:
        text = md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text.split("---", 2)[2].strip() if text.startswith("---") else text


def mark_used(sid: str, root: Path | None = None) -> None:
    index = _index(root)
    if sid in index:
        index[sid]["uses"] = int(index[sid].get("uses", 0)) + 1
        index[sid]["last_used"] = time.time()
        _save_index(index, root)


def similar(goal: str, root: Path | None = None) -> str:
    """The id of a learned skill for (nearly) the same request, or ""."""
    mine = _words(goal)
    if not mine:
        return ""
    for sid, info in _index(root).items():
        theirs = _words(info.get("goal", ""))
        if theirs and len(mine & theirs) / max(1, min(len(mine), len(theirs))) >= SIMILAR \
                and (learned_dir(root) / sid / "SKILL.md").is_file():
            return sid
    return ""


def learn_from(goal: str, messages: list, status: str, outcome: str, tool_calls: int,
               root: Path | None = None, clock=time.time) -> dict | None:
    """Write (or refresh) a learned skill for a verified multi-step success. None = nothing learned."""
    if not should_learn(status, outcome, tool_calls):
        return None
    calls, pitfalls, final, files = steps_from(messages)
    if len(calls) <= MIN_TOOL_CALLS:
        return None
    sid = similar(goal, root) or slug(goal)
    base = learned_dir(root)
    folder = base / sid
    if folder.exists() and sid not in _index(root):
        n = 2
        while (base / ("%s-%d" % (sid, n))).exists():
            n += 1
        sid = "%s-%d" % (sid, n)
        folder = base / sid
    folder.mkdir(parents=True, exist_ok=True)
    md = folder / "SKILL.md"
    md.write_text(render(goal, calls, pitfalls, final, files, sid), encoding="utf-8")
    try:   # the same safety scan every skill passes before it reaches a model
        import skill_scan  # pylint: disable=import-outside-toplevel
        if skill_scan.scan(md).get("verdict") == "blocked":
            md.unlink()
            folder.rmdir()
            return None
    except Exception:  # noqa: BLE001
        pass
    index = _index(root)
    entry = index.get(sid, {"uses": 0, "created": clock()})
    entry.update({"t": clock(), "goal": _scrub(goal)[:400], "steps": len(calls),
                  "times_learned": int(entry.get("times_learned", 0)) + 1})
    index[sid] = entry
    _save_index(index, root)
    return {"id": sid, "path": str(md), "steps": len(calls), "refreshed": entry["times_learned"] > 1}
