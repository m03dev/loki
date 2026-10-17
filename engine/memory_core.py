"""Memory core: learn / recall / fetch / forget, and a bounded memory pack for every request.

Ported from the design and logic of OpenHuman's memory host (tinyhumansai/openhuman,
crates/openhuman-core/src/memory: the single `memory` tool `recall | fetch | learn | forget`,
lifecycle/prefetch "memory pack", tool_budget, guard::ScrubbingEngine), GPL-3.0 - see
engine/licenses/OpenHuman-GPL-3.0.txt. Re-written in Python on the standard library; OpenHuman
binds a remote engine (TinyHumans / CortexDB), LOKI keeps everything in one local JSONL file.

What it keeps from OpenHuman:

  * One tool, four verbs. `learn` stores a short learning and stamps it with what the HOST knows
    (workspace, agent/job id, source, time) - the model never chooses those. `recall` returns the
    evidence most relevant to a query, capped to a budget, whole entries in rank order, then a
    note on what was left out (capped_evidence). `fetch` pages through matches by cursor.
    `forget` removes by id (or every item matching a query, when asked to).
  * Every text is scrubbed of secrets BEFORE it is stored (ScrubbingEngine), so a key pasted in a
    chat never lands in memory.
  * Around every request the host builds a "memory pack" - the few memories that matter for this
    request - and adds it to the model request as an ephemeral instruction; it is never written
    into the transcript. The ids it used are the turn's citations: the reply metadata says which
    memories were used (`memories_used`).
  * A per-request call budget for the tool (8 calls), so a confused model cannot spend a whole
    request recalling.

Tiers (memory.py names them; this module adds the learned items to them):

    semantic    lasting facts and learnings     memory_core.jsonl (+ memory.md, owned by memory.py)
    episodic    what happened (notes, outcomes) memory_core.jsonl (+ reasoning_bank.py lessons)
    procedural  how to do things                learned SKILL.md files (skill_learning.py)
    working     the task in hand                project_state.py (memory.py)

Relevance: words shared with the query weighted by rarity (IDF, like reasoning_bank), divided by
sqrt(length), times a recency factor (half-life 30 days), a small boost for items that were
useful before (uses), and a tier weight. Pure functions; every entry point takes a `root` for
tests. LOKI_MEMORY_CORE=off turns the automatic pack off (the tool keeps working).
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import uuid
from pathlib import Path

TIERS = ("semantic", "episodic", "procedural", "working")
TIER_WEIGHT = {"semantic": 1.0, "episodic": 0.9, "procedural": 1.1, "working": 0.8}
HALF_LIFE_S = 30 * 86400
MAX_ITEMS = 5000
MAX_TEXT = 1200
EVIDENCE_CHARS = 2500 * 4          # OpenHuman: about 2,500 tokens of evidence for `recall`
PACK_CHARS = int(os.getenv("LOKI_MEMORY_PACK_CHARS", "1800") or 1800)   # the automatic pack stays small
PACK_ITEMS = 5
FETCH_TOP = 5
TOOL_BUDGET = 8                     # memory tool calls per request
SEPARATOR = "\n---\n"
STOP = set("""a an and are as at be but by can do for from has have how i in into is it its let
make me my of on or our please so that the their them then there this to up use using want was
we what when where which will with you your loki can could should would just also new add get
not no yes did does done""".split())
_LOCK = threading.Lock()


def enabled(env: dict | None = None) -> bool:
    return str((env if env is not None else os.environ).get("LOKI_MEMORY_CORE", "on")).strip().lower() \
        not in ("0", "off", "false", "no")


def data_dir(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def store_path(root: Path | None = None) -> Path:
    return data_dir(root) / "memory_core.jsonl"


def _stem(word: str) -> str:
    """A light suffix strip so "ships"/"shipped"/"shipping" meet "ship" (no dictionary needed)."""
    for suffix in ("ing", "ies", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix) and not word.endswith("ss"):
            word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    if len(word) > 4 and word[-1] == word[-2] and word[-1] not in "aeiouls":
        word = word[:-1]           # shipp -> ship
    return word


def words(text: str) -> list:
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9_.+-]{1,}", str(text).lower()):
        w = w.strip(".-+")
        if w in STOP or len(w) <= 2:
            continue
        out.append(w if any(c in w for c in "._+") or w.isdigit() else _stem(w))
    return out


def scrub(text: str) -> str:
    """Secrets out before anything is stored (OpenHuman's ScrubbingEngine)."""
    text = str(text or "")
    try:
        import experience  # pylint: disable=import-outside-toplevel
        text = experience.redact(text)
    except Exception:  # noqa: BLE001
        pass
    text = re.sub(r"(sk|gsk|xai|pk|rk|AIza|ghp|github_pat)[-_A-Za-z0-9]{12,}", "[secret]", text)
    text = re.sub(r"(?i)(password|passwd|api[_-]?key|token|secret)\s*[:=]\s*\S+", r"\1=[secret]", text)
    return text


# --------------------------------------------------------------------------- storage

def _read(root: Path | None = None) -> list:
    out = []
    try:
        for line in store_path(root).read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get("id"):
                out.append(item)
    except OSError:
        pass
    return out


def _write(items: list, root: Path | None = None) -> None:
    path = store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items[-MAX_ITEMS:]), encoding="utf-8")
    os.replace(tmp, path)


def items(root: Path | None = None, tier: str = "") -> list:
    return [i for i in _read(root) if not tier or i.get("tier") == tier]


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def learn(text: str, tier: str = "semantic", tags=None, root: Path | None = None, source: str = "agent",
          meta: dict | None = None, clock=time.time) -> dict:
    """Store one learning. Host facts (workspace, job, source, time) are stamped here, not by the model."""
    body = scrub(" ".join(str(text or "").split()))[:MAX_TEXT]
    tier = str(tier or "semantic").lower()
    if tier not in ("semantic", "episodic"):
        return {"ok": False, "error": "learn writes the semantic or episodic tier (procedural memory is "
                                      "learned skills; working memory is project_state)"}
    if len(body) < 4:
        return {"ok": False, "error": "nothing to learn"}
    tag_list = [str(t).strip().lower()[:40] for t in (tags if isinstance(tags, (list, tuple))
                                                      else str(tags or "").split(",")) if str(t).strip()][:8]
    host = {"workspace": os.getenv("LOKI_WORKSPACE", ""), "job": os.getenv("LOKI_JOB_ID", ""),
            "team": os.getenv("LOKI_TEAM_ID", "")}
    host.update({k: v for k, v in (meta or {}).items() if isinstance(v, (str, int, float, bool))})
    with _LOCK:
        pool = _read(root)
        for item in pool:      # the same learning again: refresh it instead of a duplicate
            if item.get("tier") == tier and _norm(item.get("text", "")) == _norm(body):
                item["t"] = clock()
                item["tags"] = sorted(set(item.get("tags") or []) | set(tag_list))
                _write(pool, root)
                return {"ok": True, "id": item["id"], "updated": True, "status": "saved; already known, refreshed"}
        item = {"id": "m" + uuid.uuid4().hex[:10], "tier": tier, "text": body, "tags": tag_list,
                "t": clock(), "uses": 0, "last_used": 0, "source": str(source or "agent")[:40],
                "meta": {k: v for k, v in host.items() if v}}
        pool.append(item)
        _write(pool, root)
    return {"ok": True, "id": item["id"], "status": "saved; searchable in recall now"}


def forget(item_id: str = "", query: str = "", root: Path | None = None, all_matches: bool = False) -> dict:
    """Remove one item by id, or (all_matches) every item whose text contains `query`."""
    item_id = str(item_id or "").strip()
    needle = _norm(query)
    if not item_id and not needle:
        return {"ok": False, "error": "say which memory to forget (id, or query with all=true)"}
    with _LOCK:
        pool = _read(root)
        if item_id:
            keep = [i for i in pool if i["id"] != item_id]
        else:
            hits = [i for i in pool if needle in _norm(i.get("text", ""))]
            if len(hits) > 1 and not all_matches:
                return {"ok": False, "error": "%d memories match; pass the id, or all=true to forget every one"
                        % len(hits), "matches": [{"id": i["id"], "text": i["text"][:120]} for i in hits[:10]]}
            ids = {i["id"] for i in hits}
            keep = [i for i in pool if i["id"] not in ids]
        removed = len(pool) - len(keep)
        if removed:
            _write(keep, root)
    return {"ok": removed > 0, "forgotten": removed, **({} if removed else {"error": "no such memory"})}


def edit(item_id: str, text: str, root: Path | None = None) -> dict:
    body = scrub(" ".join(str(text or "").split()))[:MAX_TEXT]
    with _LOCK:
        pool = _read(root)
        for item in pool:
            if item["id"] == item_id:
                item["text"] = body
                _write(pool, root)
                return {"ok": True, "id": item_id}
    return {"ok": False, "error": "no such memory"}


# --------------------------------------------------------------------------- relevance

def _candidates(root: Path | None, repo: Path | None, include_skills: bool) -> list:
    """Everything recall can see, as {id, tier, text, t, uses, source}."""
    pool = [dict(i) for i in _read(root)]
    if include_skills:
        try:
            import skill_learning  # pylint: disable=import-outside-toplevel
            for skill in skill_learning.learned(root):
                pool.append({"id": "skill:" + skill["id"], "tier": "procedural",
                             "text": "%s - %s" % (skill["name"], skill["description"]),
                             "t": skill.get("t", 0), "uses": skill.get("uses", 0),
                             "source": "learned-skill", "skill": skill["id"], "path": skill["path"]})
        except Exception:  # noqa: BLE001
            pass
    return pool


def score(query: str, pool: list, now: float | None = None) -> list:
    """[(score, item)] best first; items sharing no meaningful word with the query are left out."""
    q = set(words(query))
    if not q or not pool:
        return []
    now = time.time() if now is None else now
    docs = [set(words(i.get("text", "") + " " + " ".join(i.get("tags") or []))) for i in pool]
    df: dict = {}
    for d in docs:
        for w in d:
            df[w] = df.get(w, 0) + 1
    n = len(docs)
    out = []
    for item, d in zip(pool, docs):
        shared = q & d
        if not shared:
            continue
        need = 1 if len(q) <= 2 else 2
        if len(shared) < need and not (len(shared) == 1 and math.log(1 + n / df[next(iter(shared))]) > 1.5 and len(q) <= 4):
            continue
        rel = sum(math.log(1 + n / df[w]) for w in shared) / math.sqrt(len(d) or 1)
        age = max(0.0, now - float(item.get("t", now) or now))
        recency = 0.5 + 0.5 * (0.5 ** (age / HALF_LIFE_S))
        useful = 1.0 + 0.1 * min(int(item.get("uses", 0) or 0), 10)
        out.append((rel * recency * useful * TIER_WEIGHT.get(item.get("tier", "semantic"), 1.0), item))
    out.sort(key=lambda s: (-s[0], -float(s[1].get("t", 0) or 0)))
    return out


def cap_evidence(entries: list, budget: int) -> tuple:
    """(text, kept ids, left out) - whole entries in rank order, then whole lines of the next one,
    then a note on what was left out (OpenHuman capped_evidence). A line is never split."""
    out, kept, cut = "", [], False
    for idx, (item_id, entry) in enumerate(entries):
        joint = SEPARATOR if out else ""
        if len(out) + len(joint) + len(entry) <= budget:
            out += joint + entry
            kept.append(item_id)
            continue
        lines = entry.split("\n")
        taken = 0
        for line in lines:
            piece = (len(joint) if taken == 0 else 1) + len(line)
            if len(out) + piece > budget and out:
                break
            out += (joint if taken == 0 else "\n") + line
            taken += 1
        if taken == len(lines):
            kept.append(item_id)
        elif taken:
            out += "\n[...]"
            kept.append(item_id)
            cut = True
        left = len(entries) - len(kept)
        if left > 0 or cut:
            out += "\n(%d more not shown%s; use memory fetch with a cursor for the rest)" % (
                left, ", the last one shortened" if cut else "")
        return out, kept, left
    return out, kept, 0


def _render(item: dict) -> str:
    when = time.strftime("%Y-%m-%d", time.localtime(float(item.get("t", 0) or 0))) if item.get("t") else ""
    head = "[%s %s%s]" % (item.get("tier", "?"), item["id"], (" " + when) if when else "")
    return head + " " + str(item.get("text", "")).strip()


def recall(query: str, limit: int = 8, root: Path | None = None, repo: Path | None = None,
           budget: int = EVIDENCE_CHARS, include_skills: bool = True, mark_used: bool = True) -> dict:
    """{"evidence", "items": [ids], "note"} - the most relevant memories, capped to `budget` chars."""
    ranked = score(query, _candidates(root, repo, include_skills))[:max(1, int(limit))]
    if not ranked:
        return {"evidence": "", "items": [], "note": "Nothing relevant is stored in memory."}
    text, kept, left = cap_evidence([(i["id"], _render(i)) for _, i in ranked], budget)
    if mark_used:
        _mark_used(kept, root)
    return {"evidence": text, "items": kept, "left_out": left,
            "citations": [{"id": i["id"], "tier": i.get("tier"), "text": i.get("text", "")[:160]}
                          for _, i in ranked if i["id"] in kept]}


def fetch(query: str, cursor: int = 0, root: Path | None = None, repo: Path | None = None) -> dict:
    """Page through every match, FETCH_TOP at a time."""
    ranked = score(query, _candidates(root, repo, True))
    start = max(0, int(cursor or 0))
    page = ranked[start:start + FETCH_TOP]
    nxt = start + FETCH_TOP if start + FETCH_TOP < len(ranked) else None
    return {"items": [{"id": i["id"], "tier": i.get("tier"), "text": i.get("text", "")} for _, i in page],
            "total": len(ranked), "next_cursor": nxt}


def _mark_used(ids: list, root: Path | None = None) -> None:
    real = {i for i in ids if not str(i).startswith("skill:")}
    if real:
        with _LOCK:
            pool = _read(root)
            hit = False
            for item in pool:
                if item["id"] in real:
                    item["uses"] = int(item.get("uses", 0) or 0) + 1
                    item["last_used"] = time.time()
                    hit = True
            if hit:
                _write(pool, root)
    skills = [str(i)[6:] for i in ids if str(i).startswith("skill:")]
    if skills:
        try:
            import skill_learning  # pylint: disable=import-outside-toplevel
            for sid in skills:
                skill_learning.mark_used(sid, root)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- the per-request pack

def pack(query: str, root: Path | None = None, repo: Path | None = None, budget: int = PACK_CHARS,
         limit: int = PACK_ITEMS) -> dict:
    """The memory pack for one request: {"text", "used": [citations], "skills": [names]}.

    Bounded (`budget` chars, `limit` items) so it never crowds the window, labelled as context
    from memory (it may be incomplete or unrelated), and empty when nothing relevant is stored."""
    if not enabled():
        return {"text": "", "used": [], "skills": []}
    try:
        found = recall(query, limit=limit, root=root, repo=repo, budget=budget)
    except Exception:  # noqa: BLE001 - memory is advice; it must never break a request
        return {"text": "", "used": [], "skills": []}
    if not found["items"]:
        return {"text": "", "used": [], "skills": []}
    skills = []
    extra = ""
    try:
        import skill_learning  # pylint: disable=import-outside-toplevel
        for cite in found["citations"]:
            if cite["id"].startswith("skill:") and not skills:
                body = skill_learning.body(cite["id"][6:], root)
                if body:
                    skills.append(cite["id"][6:])
                    extra = ("\n\nLearned skill `%s` (a procedure that worked before; follow it if it fits, "
                             "and say \"used learned skill %s\" in your reply):\n%s"
                             % (cite["id"][6:], cite["id"][6:], body[:max(400, budget // 2)]))
    except Exception:  # noqa: BLE001
        pass
    text = ("# Memory (recalled for this request)\nContext from LOKI's memory, looked up for this request. It "
            "may be incomplete or unrelated - use what helps; the `memory` tool recalls more.\n"
            + found["evidence"] + extra)
    return {"text": text, "used": found["citations"], "skills": skills}


class Budget:
    """OpenHuman's tool budget: at most TOOL_BUDGET memory calls per request."""

    def __init__(self, calls: int = TOOL_BUDGET) -> None:
        self.calls = calls
        self.used = 0

    def reset(self) -> None:
        self.used = 0

    def take(self) -> str:
        if self.used >= self.calls:
            return ("memory budget used up for this request (%d calls). Continue without memory; do not "
                    "retry memory in this request." % self.calls)
        self.used += 1
        return ""


def stats(root: Path | None = None) -> dict:
    pool = _read(root)
    by: dict = {}
    for i in pool:
        by[i.get("tier", "?")] = by.get(i.get("tier", "?"), 0) + 1
    return {"items": len(pool), "by_tier": by, "enabled": enabled()}
