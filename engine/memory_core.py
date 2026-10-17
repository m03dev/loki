"""Memory core: learn / recall / fetch / forget, and a bounded memory pack for every request.

Ported from the design and logic of OpenHuman's memory host (tinyhumansai/openhuman,
crates/openhuman-core/src/memory: the single `memory` tool `recall | fetch | learn | forget`,
lifecycle/prefetch "memory pack", tool_budget, guard::ScrubbingEngine), GPL-3.0 - see
engine/licenses/OpenHuman-GPL-3.0.txt. Re-written in Python on the standard library; OpenHuman
binds a remote engine (TinyHumans / CortexDB), LOKI keeps everything in local files.

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

Session 28 (memory & knowledge) made this the ONE memory model:

  * every item has a KIND - profile, preference, person, project, decision, fact (semantic),
    episode, lesson (episodic), skill (procedural: the learned SKILL.md files) - an importance,
    and a status (active, or superseded by a newer item, with its history kept);
  * storage is memory_store.py: an append-only operation log with last-writer-wins per item id
    and tombstones for forget, so the Mac and the PC share one memory (memory_sync.py);
  * relevance is memory_search.py: hybrid BM25 + local embeddings when available, recency by
    kind, importance, usefulness, de-duplication and a token budget;
  * learning is careful: the same text refreshes, a near-duplicate merges, a contradiction
    supersedes the older item (history kept), secrets never land, memory_kinds.py names the kind.

Tiers (memory.py names them): semantic = the six fact kinds, episodic = episodes + lessons (+
reasoning_bank.py), procedural = learned skills, working = project_state.py.

Every entry point takes a `root` for tests. LOKI_MEMORY_CORE=off turns the automatic pack off
(the tool keeps working).
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import memory_kinds
import memory_search
import memory_store

TIERS = ("semantic", "episodic", "procedural", "working")
KINDS = memory_store.KINDS
MAX_ITEMS = 5000
MAX_TEXT = 1200
EVIDENCE_CHARS = 2500 * 4          # OpenHuman: about 2,500 tokens of evidence for `recall`
PACK_CHARS = int(os.getenv("LOKI_MEMORY_PACK_CHARS", "1800") or 1800)   # the automatic pack stays small
PACK_ITEMS = 5
FETCH_TOP = 5
TOOL_BUDGET = 8                     # memory tool calls per request
SEPARATOR = "\n---\n"


def enabled(env: dict | None = None) -> bool:
    return str((env if env is not None else os.environ).get("LOKI_MEMORY_CORE", "on")).strip().lower() \
        not in ("0", "off", "false", "no")


def data_dir(root: Path | None = None) -> Path:
    return memory_store.data_dir(root)


def store_path(root: Path | None = None) -> Path:
    """The operation log (session 26's memory_core.jsonl is migrated into it on first use)."""
    return memory_store.log_path(root)


def words(text: str) -> list:
    return memory_search.words(text)


def scrub(text: str) -> str:
    """Secrets out before anything is stored (OpenHuman's ScrubbingEngine)."""
    text = str(text or "")
    try:
        import experience  # pylint: disable=import-outside-toplevel
        text = experience.redact(text)
    except Exception:  # noqa: BLE001
        pass
    text = re.sub(r"(sk|gsk|xai|pk|rk|AIza|ghp|gho|github_pat|xox[abp]|hf)[-_A-Za-z0-9]{12,}", "[secret]", text)
    text = re.sub(r"(?i)\b(password|passwd|passcode|api[_ -]?key|token|secret|private key|seed phrase)"
                  r"(\s*(?:is|=|:)\s*)\S+", r"\1\2[secret]", text)
    text = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)", "[secret]", text)
    text = re.sub(r"\b(?:\d[ -]?){13,19}\b", "[number]", text)
    return text


def clean_item(item: dict) -> dict:
    """An item received from another machine, checked like one learned here."""
    item["text"] = scrub(" ".join(str(item.get("text") or "").split()))[:MAX_TEXT]
    if item.get("kind") not in KINDS:
        item["kind"] = "fact"
    item["tier"] = memory_store.KIND_TIER.get(item["kind"], "semantic")
    item["tags"] = [str(t)[:40] for t in (item.get("tags") or [])][:8]
    item["history"] = [{"text": scrub(str(h.get("text", "")))[:MAX_TEXT], "t": h.get("t", 0), "id": str(h.get("id", ""))[:40]}
                       for h in (item.get("history") or []) if isinstance(h, dict)][-10:]
    return item


# --------------------------------------------------------------------------- reading

def items(root: Path | None = None, tier: str = "", kind: str = "") -> list:
    """Active memories (oldest first), optionally one tier or one kind."""
    return [i for i in memory_store.items(root)
            if (not tier or i.get("tier") == tier) and (not kind or i.get("kind") == kind)]


def all_items(root: Path | None = None) -> list:
    """Active AND superseded memories, for Settings > Memory's history view."""
    return [i for i in memory_store.items(root, include_inactive=True) if i.get("status") != "doc"]


def get(item_id: str, root: Path | None = None) -> dict | None:
    return memory_store.get(item_id, root)


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


# --------------------------------------------------------------------------- writing

def learn(text: str, tier: str = "semantic", tags=None, root: Path | None = None, source: str = "agent",
          meta: dict | None = None, clock=time.time, kind: str = "", importance: float | None = None,
          review: bool = False) -> dict:
    """Store one learning. Host facts (workspace, job, source, time) are stamped here, not by the model.

    The same text again refreshes the item; a near-duplicate merges into it; a sentence that sets the
    same thing to a new value SUPERSEDES the older item (kept, marked superseded, with history).
    `review=True` marks it as learned automatically, for the owner's "LOKI learned N things" list."""
    body = scrub(" ".join(str(text or "").split()))[:MAX_TEXT]
    tier = str(tier or "semantic").lower()
    kind = str(kind or "").lower()
    if kind and kind not in KINDS:
        return {"ok": False, "error": "kind is one of %s" % ", ".join(KINDS)}
    if kind:
        tier = memory_store.KIND_TIER[kind]
    if tier not in ("semantic", "episodic") or kind == "skill":
        return {"ok": False, "error": "learn writes the semantic or episodic tier (procedural memory is "
                                      "learned skills; working memory is project_state)"}
    if len(body) < 4:
        return {"ok": False, "error": "nothing to learn"}
    kind = kind or memory_kinds.kind_of(body, tier, source)
    tag_list = [str(t).strip().lower()[:40] for t in (tags if isinstance(tags, (list, tuple))
                                                      else str(tags or "").split(",")) if str(t).strip()][:8]
    host = {"workspace": os.getenv("LOKI_WORKSPACE", ""), "job": os.getenv("LOKI_JOB_ID", ""),
            "team": os.getenv("LOKI_TEAM_ID", "")}
    host.update({k: v for k, v in (meta or {}).items() if isinstance(v, (str, int, float, bool))})
    now = clock()
    pool = items(root)
    same_tier = [i for i in pool if i.get("tier") == tier]
    for item in same_tier:      # the same learning again: refresh it instead of a duplicate
        if _norm(item.get("text", "")) == _norm(body):
            return _refresh(item, tag_list, now, root, "saved; already known, refreshed")
    for item in same_tier:      # a near-duplicate: keep the longer wording, one item
        if item.get("kind") == kind and memory_search.near_duplicate(item.get("text", ""), body):
            if len(body) > len(item.get("text", "")):
                item = dict(item, text=body)
            return _refresh(item, tag_list, now, root, "saved; merged with a memory that says the same")
    replaced = []
    if tier == "semantic":
        replaced = [i for i in pool if i.get("tier") == "semantic"
                    and memory_kinds.contradicts(body, i.get("text", ""))]
    new = {"id": memory_store.new_id(), "kind": kind, "tier": tier, "text": body, "tags": tag_list,
           "t": now, "updated": now, "source": str(source or "agent")[:40],
           "importance": round(float(importance if importance is not None
                                     else memory_store.IMPORTANCE.get(kind, 0.5)), 2),
           "status": "active", "meta": {k: v for k, v in host.items() if v},
           "origin": memory_store.host_name()}
    if review:
        new["review"] = "new"
    if replaced:
        new["supersedes"] = [r["id"] for r in replaced]
        new["history"] = [{"text": r["text"], "t": r.get("updated") or r.get("t", 0), "id": r["id"]}
                          for r in replaced][-10:]
    memory_store.put(new, root)
    for old in replaced:
        memory_store.put(dict(_bare(old), status="superseded", superseded_by=new["id"], updated=now), root)
    out = {"ok": True, "id": new["id"], "kind": kind, "status": "saved; searchable in recall now"}
    if replaced:
        out["superseded"] = [r["id"] for r in replaced]
        out["status"] = "saved; it replaces %d older memor%s (kept in its history)" % (
            len(replaced), "y" if len(replaced) == 1 else "ies")
    _nudge_sync()
    return out


def _bare(item: dict) -> dict:
    """An item without the local-only fields the store adds when reading."""
    return {k: v for k, v in item.items() if k not in ("uses", "last_used", "_v", "_host")}


def _refresh(item: dict, tags: list, now: float, root, status: str) -> dict:
    item = _bare(item)
    item["updated"] = now
    item["tags"] = sorted(set(item.get("tags") or []) | set(tags))
    memory_store.put(item, root)
    _nudge_sync()
    return {"ok": True, "id": item["id"], "updated": True, "kind": item.get("kind"), "status": status}


def forget(item_id: str = "", query: str = "", root: Path | None = None, all_matches: bool = False) -> dict:
    """Remove one item by id, or (all_matches) every item whose text contains `query`. A tombstone
    is written (so every linked machine forgets it too) and the text is redacted from the log."""
    item_id = str(item_id or "").strip()
    needle = _norm(query)
    if not item_id and not needle:
        return {"ok": False, "error": "say which memory to forget (id, or query with all=true)"}
    if item_id:
        ids = [item_id] if memory_store.get(item_id, root) else []
    else:
        hits = [i for i in items(root) if needle in _norm(i.get("text", ""))]
        if len(hits) > 1 and not all_matches:
            return {"ok": False, "error": "%d memories match; pass the id, or all=true to forget every one"
                    % len(hits), "matches": [{"id": i["id"], "text": i["text"][:120]} for i in hits[:10]]}
        ids = [i["id"] for i in hits]
    removed = sum(1 for i in ids if memory_store.delete(i, root))
    if removed:
        _nudge_sync()
    return {"ok": removed > 0, "forgotten": removed, **({} if removed else {"error": "no such memory"})}


def edit(item_id: str, text: str, root: Path | None = None, kind: str = "") -> dict:
    """Change an item's words or kind (the old wording goes into its history)."""
    item = memory_store.get(item_id, root)
    if not item:
        return {"ok": False, "error": "no such memory"}
    body = scrub(" ".join(str(text or "").split()))[:MAX_TEXT]
    if len(body) < 4:
        return {"ok": False, "error": "nothing to keep - use forget to remove it"}
    item = _bare(item)
    if body != item.get("text"):
        item["history"] = (list(item.get("history") or [])
                           + [{"text": item.get("text", ""), "t": item.get("updated") or item.get("t", 0)}])[-10:]
        item["text"] = body
    if kind and kind in KINDS and kind != "skill":
        item["kind"] = kind
        item["tier"] = memory_store.KIND_TIER[kind]
    item["updated"] = time.time()
    if item.get("review") == "new":
        item["review"] = "kept"
    memory_store.put(item, root)
    _nudge_sync()
    return {"ok": True, "id": item_id}


def keep(item_id: str, root: Path | None = None) -> dict:
    """The owner looked at an automatically learned memory and kept it."""
    item = memory_store.get(item_id, root)
    if not item:
        return {"ok": False, "error": "no such memory"}
    memory_store.put(dict(_bare(item), review="kept"), root)
    _nudge_sync()
    return {"ok": True, "id": item_id}


def restore(item_id: str, root: Path | None = None) -> dict:
    """Make a superseded memory current again (the newer one is superseded instead)."""
    old = memory_store.get(item_id, root)
    if not old or old.get("status") != "superseded":
        return {"ok": False, "error": "that memory is not superseded"}
    now = time.time()
    newer = memory_store.get(str(old.get("superseded_by") or ""), root)
    if newer and newer.get("status") == "active":
        memory_store.put(dict(_bare(newer), status="superseded", superseded_by=item_id, updated=now), root)
    memory_store.put(dict(_bare(old), status="active", superseded_by="", updated=now), root)
    _nudge_sync()
    return {"ok": True, "id": item_id}


def learned_since(since: float, root: Path | None = None) -> list:
    """What LOKI wrote by itself since `since`, newest first ("LOKI learned 3 things today")."""
    return [i for i in reversed(items(root)) if i.get("review") == "new" and float(i.get("t", 0) or 0) >= since]


def _nudge_sync() -> None:
    try:
        import memory_sync  # pylint: disable=import-outside-toplevel
        memory_sync.nudge()
    except Exception:  # noqa: BLE001 - syncing is best effort
        pass


# --------------------------------------------------------------------------- relevance

def _candidates(root: Path | None, repo: Path | None, include_skills: bool, kinds=None) -> list:
    """Everything recall can see, as {id, kind, tier, text, t, uses, source}."""
    pool = [dict(i) for i in items(root) if not kinds or i.get("kind") in kinds]
    if include_skills and (not kinds or "skill" in kinds):
        try:
            import skill_learning  # pylint: disable=import-outside-toplevel
            for skill in skill_learning.learned(root):
                pool.append({"id": "skill:" + skill["id"], "kind": "skill", "tier": "procedural",
                             "text": "%s - %s" % (skill["name"], skill["description"]),
                             "t": skill.get("t", 0), "uses": skill.get("uses", 0), "importance": 0.6,
                             "source": "learned-skill", "skill": skill["id"], "path": skill["path"]})
        except Exception:  # noqa: BLE001
            pass
    return pool


def score(query: str, pool: list, now: float | None = None, root: Path | None = None) -> list:
    """[(score, item)] best first; items without real evidence for the query are left out."""
    return [(s, i) for s, i, _ in memory_search.dedupe(memory_search.rank(query, pool, root=root, now=now))]


def cap_evidence(entries: list, budget: int) -> tuple:
    """(text, kept ids, left out) - whole entries in rank order, then whole lines of the next one,
    then a note on what was left out (OpenHuman capped_evidence). A line is never split."""
    out, kept, cut = "", [], False
    for item_id, entry in entries:
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


def render(item: dict) -> str:
    stamp = float(item.get("updated") or item.get("t") or 0)
    when = time.strftime("%Y-%m-%d", time.localtime(stamp)) if stamp else ""
    head = "[%s %s%s]" % (item.get("kind") or item.get("tier", "?"), item["id"], (" " + when) if when else "")
    return head + " " + str(item.get("text", "")).strip()


_render = render


def recall(query: str, limit: int = 8, root: Path | None = None, repo: Path | None = None,
           budget: int = EVIDENCE_CHARS, include_skills: bool = True, mark_used: bool = True,
           kinds=None) -> dict:
    """{"evidence", "items": [ids], "note"} - the most relevant memories, capped to `budget` chars."""
    ranked = score(query, _candidates(root, repo, include_skills, kinds), root=data_dir(root))[:max(1, int(limit))]
    if not ranked:
        return {"evidence": "", "items": [], "note": "Nothing relevant is stored in memory."}
    text, kept, left = cap_evidence([(i["id"], render(i)) for _, i in ranked], budget)
    if mark_used:
        _mark_used(kept, root)
    return {"evidence": text, "items": kept, "left_out": left,
            "citations": [{"id": i["id"], "kind": i.get("kind"), "tier": i.get("tier"), "text": i.get("text", "")[:160]}
                          for _, i in ranked if i["id"] in kept]}


def fetch(query: str, cursor: int = 0, root: Path | None = None, repo: Path | None = None) -> dict:
    """Page through every match, FETCH_TOP at a time."""
    ranked = score(query, _candidates(root, repo, True), root=data_dir(root))
    start = max(0, int(cursor or 0))
    page = ranked[start:start + FETCH_TOP]
    nxt = start + FETCH_TOP if start + FETCH_TOP < len(ranked) else None
    return {"items": [{"id": i["id"], "kind": i.get("kind"), "tier": i.get("tier"), "text": i.get("text", ""),
                       "score": round(s, 4)} for s, i in page],
            "total": len(ranked), "next_cursor": nxt}


def _mark_used(ids: list, root: Path | None = None) -> None:
    real = [i for i in ids if not str(i).startswith(("skill:", "note:", "doc:"))]
    if real:
        memory_store.mark_used(real, root)
    skills = [str(i)[6:] for i in ids if str(i).startswith("skill:")]
    if skills:
        try:
            import skill_learning  # pylint: disable=import-outside-toplevel
            for sid in skills:
                skill_learning.mark_used(sid, root)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- the ONE retrieval

def retrieve(query: str, root: Path | None = None, repo: Path | None = None, budget_tokens: int = 450,
             limit: int = PACK_ITEMS, kinds=None, include_skills: bool = True, extra: list | None = None,
             skip_texts=(), mark_used: bool = True) -> dict:
    """The memories for one query, ranked (hybrid), de-duplicated and cut to a TOKEN budget.

    `extra` adds candidates from elsewhere (memory.md notes beyond the always-on profile, ...);
    `skip_texts` leaves out what the prompt already carries. Returns {"items": [{id, kind, text,
    score, line, why}], "tokens", "left_out", "mode"}."""
    pool = _candidates(root, repo, include_skills, kinds) + list(extra or [])
    skip = {_norm(t) for t in skip_texts if t}
    if skip:
        pool = [i for i in pool if _norm(i.get("text", "")) not in skip]
    ranked = memory_search.dedupe(memory_search.rank(query, pool, root=data_dir(root)), keep=max(1, int(limit)))
    entries = [(render(i), i, s, d) for s, i, d in ranked]
    kept, used, left = memory_search.fit(entries, max(1, int(budget_tokens)))
    if mark_used:
        _mark_used([i["id"] for _, i, _, _ in kept], root)
    return {"items": [{"id": i["id"], "kind": i.get("kind"), "tier": i.get("tier"), "text": i.get("text", ""),
                       "score": round(s, 4), "line": line, "why": d} for line, i, s, d in kept],
            "tokens": used, "left_out": left, "mode": memory_search.status()["mode"]}


# --------------------------------------------------------------------------- the per-request pack

def pack(query: str, root: Path | None = None, repo: Path | None = None, budget: int = PACK_CHARS,
         limit: int = PACK_ITEMS, extra: list | None = None, skip_texts=()) -> dict:
    """The memory pack for one request: {"text", "used": [citations], "skills": [names], "tokens"}.

    Bounded (`budget` chars ~ budget/4 tokens, `limit` items) so it never crowds the window,
    labelled as context from memory (it may be incomplete or unrelated), and empty when nothing
    relevant is stored. memory.pack() wraps this with the lessons and the project's own docs."""
    empty = {"text": "", "used": [], "skills": [], "tokens": 0}
    if not enabled():
        return empty
    try:
        found = retrieve(query, root=root, repo=repo, budget_tokens=max(40, int(budget) // 4), limit=limit,
                         extra=extra, skip_texts=skip_texts)
    except Exception:  # noqa: BLE001 - memory is advice; it must never break a request
        return empty
    if not found["items"]:
        return empty
    skills = []
    more = ""
    try:
        import skill_learning  # pylint: disable=import-outside-toplevel
        for cite in found["items"]:
            if cite["id"].startswith("skill:") and not skills:
                body = skill_learning.body(cite["id"][6:], root)
                if body:
                    skills.append(cite["id"][6:])
                    more = ("\n\nLearned skill `%s` (a procedure that worked before; follow it if it fits, "
                            "and say \"used learned skill %s\" in your reply):\n%s"
                            % (cite["id"][6:], cite["id"][6:], body[:max(400, budget // 2)]))
    except Exception:  # noqa: BLE001
        pass
    text = ("# Memory (recalled for this request)\nContext from LOKI's memory, looked up for this request. It "
            "may be incomplete or unrelated - use what helps; the `memory` tool recalls more.\n"
            + "\n".join(i["line"] for i in found["items"]) + more)
    used = [{"id": i["id"], "kind": i["kind"], "tier": i["tier"], "text": i["text"][:160]} for i in found["items"]]
    return {"text": text, "used": used, "skills": skills, "tokens": memory_search.tokens_of(text)}


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
    pool = items(root)
    by: dict = {}
    kinds: dict = {}
    for i in pool:
        by[i.get("tier", "?")] = by.get(i.get("tier", "?"), 0) + 1
        kinds[i.get("kind", "?")] = kinds.get(i.get("kind", "?"), 0) + 1
    return {"items": len(pool), "by_tier": by, "by_kind": kinds, "enabled": enabled(),
            "superseded": sum(1 for i in all_items(root) if i.get("status") == "superseded"),
            "forgotten": memory_store.tombstones(root), "search": memory_search.status(),
            "host": memory_store.host_name()}
