"""Experience: what Loki did, how it went, and what it can learn from it.

This is the memory that lets Loki improve slowly over time WITHOUT pretending:

1. Every request leaves one line in experience/log.jsonl - kind, provider(s), tool calls,
   cost, files, and the verification outcome. Nothing else is inferred.
2. provider_stats() turns that into measured success rates, and learned_order() uses them
   to reorder providers - but only WITHIN a cost tier, and only once a provider has enough
   samples. Free stays ahead of paid no matter what.
3. A request that finished DONE with every changed file verified OK is a trustworthy
   example; its trajectory is kept (secrets masked, the user's memory/profile replaced by a
   generic prompt) and build_dataset() turns those into train/eval JSONL for LoRA
   fine-tuning a small local model (tools/train_lora.py on a GPU such as an RTX 3070 Ti).

Standard library only. Every function takes an optional root so tests use a temp dir.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The system prompt a trained model sees. The user's real prompt carries their memory and
# profile; that must not be baked into weights, and a short stable prompt trains better.
TRAIN_SYSTEM = ("You are LOKI, a senior Godot 4 game developer working in the user's project "
                "through tools. Read before you change, make the smallest correct change, "
                "verify it, then reply 'DONE: <summary>' or 'BLOCKED: <what you need>'.")

_SECRET = re.compile(r"(sk|gsk|xai|pk|rk|AIza)[-_A-Za-z0-9]{12,}|Bearer\s+[-._A-Za-z0-9]{12,}")
MAX_TRAJECTORY_MESSAGES = 60
MAX_MESSAGE_CHARS = 6000


def _data_dir() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    if explicit:
        return Path(explicit)
    return HERE.parent / "harness_data"


def root_dir(root: Path | None = None) -> Path:
    path = (root or _data_dir()) / "experience"
    (path / "trajectories").mkdir(parents=True, exist_ok=True)
    return path


def redact(text) -> str:
    return _SECRET.sub("[redacted]", str(text))


# --- the log -----------------------------------------------------------------------

def outcome_of(status: str, verification: dict | None) -> str:
    """'verified' | 'unverified' | 'failed' | 'blocked' | 'error' - one honest label."""
    if status in ("error", "budget", "cancelled"):
        return "error" if status == "error" else "blocked"
    if status == "blocked":
        return "blocked"
    if verification:
        if verification.get("failed"):
            return "failed"
        if verification.get("ok") and not verification.get("unverified"):
            return "verified"
    return "unverified"


def record(entry: dict, root: Path | None = None) -> dict:
    """Append one request to the log. Returns the stored line."""
    line = {
        "t": time.time(),
        "id": entry.get("id") or hashlib.sha1(str(time.time_ns()).encode()).hexdigest()[:12],
        "kind": entry.get("kind", "chat"),
        # The team role this request was done in (builder, tester, ...); "" for a chat.
        "role": str(entry.get("role", "") or "")[:40],
        "goal": redact(entry.get("goal", ""))[:300],
        "status": entry.get("status", ""),
        "outcome": entry.get("outcome", ""),
        "provider": entry.get("provider", ""),
        "providers": entry.get("providers", []),
        "tool_calls": int(entry.get("tool_calls", 0) or 0),
        "model": str(entry.get("model", "") or "")[:80],
        "repaired": int(entry.get("repaired", 0) or 0),
        "rejected": int(entry.get("rejected", 0) or 0),
        "files": list(entry.get("files", []))[:30],
        "usage": entry.get("usage", {}),
        "route": entry.get("route", []),
        "seconds": round(float(entry.get("seconds", 0) or 0), 1),
        "trajectory": bool(entry.get("trajectory", False)),
        "triage": {k: v for k, v in (entry.get("triage") or {}).items()
                   if k in ("source", "kind", "route", "difficulty", "risk", "confidence", "ms",
                            "actual_route", "missing_info", "capabilities")},
    }
    with open(root_dir(root) / "log.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    return line


def entries(root: Path | None = None, last: int = 0) -> list:
    path = root_dir(root) / "log.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if last > 0:
        lines = lines[-last:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# --- measured routing --------------------------------------------------------------

def provider_stats(root: Path | None = None, window: int = 500) -> dict:
    """Per provider: requests, verified, failed, blocked, and a success rate.

    Only requests that wrote files count towards success (a chat answer is not evidence
    either way). A provider that was SWITCHED AWAY from in a route counts as a failure.
    """
    stats: dict = {}

    def bucket(name):
        return stats.setdefault(name, {"requests": 0, "verified": 0, "failed": 0,
                                       "blocked": 0, "skipped": 0})

    for line in entries(root, last=window):
        for hop in line.get("route") or []:
            if hop.get("provider"):
                bucket(hop["provider"])["skipped"] += 1
        name = line.get("provider")
        if not name or not line.get("files"):
            continue
        b = bucket(name)
        b["requests"] += 1
        outcome = line.get("outcome")
        if outcome == "verified":
            b["verified"] += 1
        elif outcome == "failed":
            b["failed"] += 1
        elif outcome == "blocked":
            b["blocked"] += 1
    for b in stats.values():
        judged = b["verified"] + b["failed"] + b["blocked"] + b["skipped"]
        b["success_rate"] = round(b["verified"] / judged, 3) if judged else None
        b["samples"] = judged
    return stats


def tool_stats(root: Path | None = None, window: int = 500) -> dict:
    """How well each provider, and each provider/model, actually CALLS tools.

    provider_stats() only counts requests that wrote files, so a model that narrates
    instead of acting looked the same as one that was never asked. This is the signal
    model selection needed: did it call a tool, and how often did the tool guard have to
    repair or reject one? Returns {"by_provider": {name: b}, "by_model": {"p/model": b}}.
    """
    by_provider: dict = {}
    by_model: dict = {}

    def bucket(store, key):
        return store.setdefault(key, {"requests": 0, "with_tools": 0, "calls": 0,
                                      "repaired": 0, "rejected": 0})

    for line in entries(root, last=window):
        name = line.get("provider")
        if not name:
            continue
        calls = int(line.get("tool_calls") or 0)
        repaired = int(line.get("repaired") or 0)
        rejected = int(line.get("rejected") or 0)
        keys = [("by_provider", name)]
        model = str(line.get("model") or "")
        if model:
            keys.append(("by_model", name + "/" + model))
        for store_name, key in keys:
            b = bucket(by_model if store_name == "by_model" else by_provider, key)
            b["requests"] += 1
            if calls:
                b["with_tools"] += 1
            b["calls"] += calls
            b["repaired"] += repaired
            b["rejected"] += rejected
    for store in (by_provider, by_model):
        for b in store.values():
            b["tool_rate"] = round(b["with_tools"] / b["requests"], 3) if b["requests"] else None
            bad = b["repaired"] + b["rejected"]
            b["clean_rate"] = round(1 - bad / b["calls"], 3) if b["calls"] else None
    return {"by_provider": by_provider, "by_model": by_model}


def tool_score(key: str, stats: dict | None = None, min_samples: int = 3,
               root: Path | None = None) -> float | None:
    """A 0..1 score of how well `key` calls tools; None means "not enough evidence yet".

    `key` is a provider name, or "provider/model" to score one local model on its own.
    Nothing is invented: too few requests returns None, and the caller keeps its default.
    """
    data = tool_stats(root) if stats is None else stats
    b = (data.get("by_model") or {}).get(key) or (data.get("by_provider") or {}).get(key)
    if not b or b.get("requests", 0) < min_samples or b.get("tool_rate") is None:
        return None
    clean = b["clean_rate"] if b.get("clean_rate") is not None else 1.0
    return round(0.75 * float(b["tool_rate"]) + 0.25 * float(clean), 3)


def role_stats(root: Path | None = None, window: int = 1000) -> dict:
    """{role: {provider: stats}} - the same evidence as provider_stats, split by team role.

    A model that is a strong builder can be a weak reviewer; the agent factory (team.py)
    uses this to give each role the model that has done THAT job best.
    """
    out: dict = {}
    for line in entries(root, last=window):
        role = line.get("role")
        name = line.get("provider")
        if not role or not name:
            continue
        b = out.setdefault(role, {}).setdefault(name, {"requests": 0, "verified": 0, "failed": 0,
                                                       "blocked": 0, "done": 0})
        b["requests"] += 1
        outcome, status = line.get("outcome"), line.get("status")
        if outcome == "verified":
            b["verified"] += 1
        elif outcome == "failed":
            b["failed"] += 1
        elif outcome == "blocked" or status == "blocked":
            b["blocked"] += 1
        if status == "done":
            b["done"] += 1
    for providers in out.values():
        for b in providers.values():
            # Roles that do not write files (researcher, reviewer) have no verification;
            # for them a DONE that the team accepted is the evidence.
            good = b["verified"] if (b["verified"] + b["failed"]) else b["done"]
            b["success_rate"] = round(good / b["requests"], 3) if b["requests"] else None
    return out


TIER_RANK = {"local": 0, "free": 1, "subscription": 2, "paid": 3}


def best_for_role(role: str, candidates, tier_of, stats: dict | None = None,
                  min_samples: int = 5, root: Path | None = None) -> str:
    """The candidate provider with the best measured success for `role`, or "".

    Only providers with at least `min_samples` jobs in that role count. Ties and close
    calls (within 5 points) go to the cheaper tier, so a free model that is nearly as good
    beats a paid one. "" means "not enough evidence yet": the caller keeps its default.
    """
    stats = role_stats(root) if stats is None else stats
    per = stats.get(role) or {}
    ranked = []
    for name in candidates:
        b = per.get(name)
        if not b or b["requests"] < min_samples or b.get("success_rate") is None:
            continue
        ranked.append((b["success_rate"], name))
    if not ranked:
        return ""
    top = max(rate for rate, _ in ranked)
    close = [name for rate, name in ranked if rate >= top - 0.05]
    return min(close, key=lambda n: (TIER_RANK.get(tier_of(n), 9), -per[n]["success_rate"]))


def learned_order(order, tier_of, stats: dict, min_samples: int = 10) -> list:
    """Reorder providers by measured success, never across tiers.

    `tier_of(name)` names a provider's cost tier ("free", "subscription", "local",
    "paid"...). Runs of the same tier in `order` are sorted by success rate, best first;
    a provider with fewer than `min_samples` judged requests keeps its place relative to
    the others (it has not earned a move). Ties keep the original order.
    """
    order = list(order)
    out: list = []
    index = 0
    while index < len(order):
        tier = tier_of(order[index])
        run = []
        while index < len(order) and tier_of(order[index]) == tier:
            run.append(order[index])
            index += 1
        proven = [p for p in run if (stats.get(p) or {}).get("samples", 0) >= min_samples]
        ranked = sorted(proven, key=lambda p: -float(stats[p]["success_rate"] or 0.0))
        it = iter(ranked)
        out.extend(next(it) if p in proven else p for p in run)
    return out


def summary(root: Path | None = None) -> dict:
    lines = entries(root)
    outcomes: dict = {}
    for line in lines:
        outcomes[line.get("outcome", "")] = outcomes.get(line.get("outcome", ""), 0) + 1
    return {"requests": len(lines), "outcomes": outcomes,
            "trajectories": len(list((root_dir(root) / "trajectories").glob("*.json"))),
            "triage": triage_stats(root)}


def triage_stats(root: Path | None = None, window: int = 500) -> dict:
    """How well the first layer predicted each request, per source (laya / rules).

    A prediction counts as right when the predicted route matches what the request actually
    needed (no tools = answer, 1-2 tools = one_step, more = plan, delegated = team), and as
    "close" when it was off by one step on that ladder.
    """
    ladder = ["answer", "one_step", "plan", "team"]
    out: dict = {}
    for line in entries(root, last=window):
        t = line.get("triage") or {}
        source, predicted, actual = t.get("source"), t.get("route"), t.get("actual_route")
        if not source or predicted not in ladder or actual not in ladder:
            continue
        b = out.setdefault(source, {"requests": 0, "right": 0, "close": 0, "ms": 0.0,
                                    "verified": 0, "routes": {}})
        b["requests"] += 1
        gap = abs(ladder.index(predicted) - ladder.index(actual))
        b["right"] += gap == 0
        b["close"] += gap == 1
        b["ms"] += float(t.get("ms") or 0)
        b["verified"] += line.get("outcome") == "verified"
        b["routes"][predicted] = b["routes"].get(predicted, 0) + 1
    for b in out.values():
        n = b["requests"]
        b["accuracy"] = round(b["right"] / n, 3) if n else None
        b["within_one"] = round((b["right"] + b["close"]) / n, 3) if n else None
        b["avg_ms"] = round(b.pop("ms") / n, 1) if n else None
    return out


# --- training data -----------------------------------------------------------------

def _clean_message(message: dict) -> dict | None:
    role = message.get("role")
    if role not in ("user", "assistant", "tool"):
        return None
    out = {"role": role}
    content = message.get("content")
    if isinstance(content, list):   # multimodal parts - keep the text only
        content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    out["content"] = redact(content or "")[:MAX_MESSAGE_CHARS]
    if role == "assistant" and message.get("tool_calls"):
        calls = []
        for call in message["tool_calls"]:
            fn = (call or {}).get("function") or {}
            args = fn.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except ValueError:
                    return None   # a malformed call is not something to learn
            calls.append({"id": str(call.get("id", "")), "type": "function",
                          "function": {"name": str(fn.get("name", "")),
                                       "arguments": json.loads(redact(json.dumps(args)))}})
        out["tool_calls"] = calls
    if role == "tool":
        out["tool_call_id"] = str(message.get("tool_call_id", ""))
    return out


def save_trajectory(request_id: str, goal: str, messages: list, tool_names: list,
                    meta: dict | None = None, root: Path | None = None) -> Path | None:
    """Keep a verified request as a training example. Returns the file, or None."""
    turns = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        cleaned = _clean_message(message)
        if cleaned is not None:
            turns.append(cleaned)
    turns = turns[-MAX_TRAJECTORY_MESSAGES:]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    if not turns or not any(t["role"] == "assistant" for t in turns):
        return None
    record_data = {"id": request_id, "goal": redact(goal)[:500], "t": time.time(),
                   "tools": sorted(set(tool_names)),
                   "messages": [{"role": "system", "content": TRAIN_SYSTEM}] + turns,
                   "meta": meta or {}}
    path = root_dir(root) / "trajectories" / (request_id + ".json")
    path.write_text(json.dumps(record_data), encoding="utf-8")
    return path


def trajectories(root: Path | None = None) -> list:
    out = []
    for path in sorted((root_dir(root) / "trajectories").glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def build_dataset(out_dir: Path, tool_schemas: dict, holdout: float = 0.1, seed: int = 3407,
                  root: Path | None = None) -> dict:
    """Write train.jsonl / eval.jsonl ({"messages", "tools"} per line). Dedupes by goal.

    `tool_schemas` maps a tool name to its OpenAI-style schema; each example carries the
    schemas of the tools it actually used, so the model learns the real call format.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    seen, rows = set(), []
    for item in trajectories(root):
        key = hashlib.sha1(item.get("goal", "").strip().lower().encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        tools = [tool_schemas[n] for n in item.get("tools", []) if n in tool_schemas]
        rows.append({"id": item.get("id"), "messages": item["messages"], "tools": tools})
    random.Random(seed).shuffle(rows)
    n_eval = max(1, int(len(rows) * holdout)) if len(rows) >= 10 else 0
    eval_rows, train_rows = rows[:n_eval], rows[n_eval:]
    for name, part in (("train.jsonl", train_rows), ("eval.jsonl", eval_rows)):
        with open(out_dir / name, "w", encoding="utf-8") as fh:
            for row in part:
                fh.write(json.dumps(row) + "\n")
    info = {"train": len(train_rows), "eval": len(eval_rows), "built": time.time()}
    (out_dir / "dataset.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


# --- training state ----------------------------------------------------------------

def train_state(root: Path | None = None) -> dict:
    path = root_dir(root) / "train_state.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"trained_on": 0, "history": []}


def save_train_state(state: dict, root: Path | None = None) -> None:
    (root_dir(root) / "train_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def new_examples(root: Path | None = None) -> int:
    """Verified examples gathered since the last training run."""
    return max(0, len(trajectories(root)) - int(train_state(root).get("trained_on", 0)))


# --- sharing verified work between your machines (see peers.py) -------------------

_ID_SAFE = "abcdefghijklmnopqrstuvwxyz0123456789-_"


def _safe_id(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch in _ID_SAFE)[:60]


def unsent(peer: str, root: Path | None = None, limit: int = 200) -> list:
    """Local verified trajectories not yet sent to `peer` (never re-sends a peer's own)."""
    sent = set(_sent_ids(peer, root))
    out = []
    for item in trajectories(root):
        if item.get("id") in sent or str(item.get("origin", "")) == peer:
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _sent_path(root: Path | None = None) -> Path:
    return root_dir(root) / "peer_sent.json"


def _sent_ids(peer: str, root: Path | None = None) -> list:
    try:
        return list(json.loads(_sent_path(root).read_text(encoding="utf-8")).get(peer, []))
    except (OSError, ValueError):
        return []


def mark_sent(peer: str, ids: list, root: Path | None = None) -> None:
    try:
        data = json.loads(_sent_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    known = list(dict.fromkeys(list(data.get(peer, [])) + [str(i) for i in ids]))
    data[peer] = known[-20000:]
    _sent_path(root).write_text(json.dumps(data), encoding="utf-8")


def import_trajectories(origin: str, items: list, root: Path | None = None) -> dict:
    """Accept another machine's verified work as training data.

    Everything is re-cleaned here: only user/assistant/tool turns survive, secrets are
    masked again, the system prompt is replaced by TRAIN_SYSTEM, and the file name is
    derived from the origin + id so one peer can never overwrite local or other files.
    """
    origin = _safe_id(origin) or "peer"
    saved, skipped = 0, 0
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("messages"), list):
            skipped += 1
            continue
        local_id = "%s-%s" % (origin, _safe_id(item.get("id", "")) or uuid_hex())
        target = root_dir(root) / "trajectories" / (local_id + ".json")
        if target.exists():
            skipped += 1
            continue
        tools = [str(t)[:80] for t in (item.get("tools") or []) if isinstance(t, str)]
        path = save_trajectory(local_id, str(item.get("goal", "")), item["messages"], tools,
                               meta={"origin": origin, **{k: v for k, v in (item.get("meta") or {}).items()
                                                          if k in ("kind", "provider")}}, root=root)
        if path is None:
            skipped += 1
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data["origin"] = origin
        path.write_text(json.dumps(data), encoding="utf-8")
        saved += 1
    return {"saved": saved, "skipped": skipped, "total": len(trajectories(root))}


def uuid_hex() -> str:
    return hashlib.sha1(str(time.time_ns()).encode()).hexdigest()[:12]
