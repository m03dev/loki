"""LOKI's memory store: one append-only operation log, the same on every machine.

Every change to a memory is an OPERATION appended to `harness_data/memory_log.jsonl`:

    {"op": "put", "id": "m1a2b3", "item": {...the whole item...}, "host": "mac", "n": 17, "v": 1760.1}
    {"op": "del", "id": "m1a2b3", "host": "pc", "n": 4, "v": 1761.9}          (a tombstone)

`host` is the machine that made the change and `n` counts that machine's operations (1, 2, 3...),
so (host, n) names an operation everywhere. `v` is a hybrid logical clock: wall time, but never
lower than any `v` this machine has seen, so a change made after receiving another machine's
change always sorts after it even when the clocks disagree.

The current state of an item is its WINNING operation: the one with the largest (v, host, n) -
last writer wins, per item id. A tombstone wins like any other operation, so a memory forgotten on
the PC stays forgotten on the Mac, and a stale copy arriving late cannot bring it back. Merging is
order-independent (a CRDT: an LWW map), which is what makes the sync conflict-free.

Sync between machines (memory_sync.py) is a vector exchange: "I have mac up to 17 and pc up to 4"
-> "here are the operations you lack". Forgetting also REDACTS the text of the item's older
operations in the local log (the ids stay, so the vectors stay right): forget means forget.

Local-only, never synced: how often an item was used (memory_uses.json) and the embedding cache.
Standard library only; every function takes the data folder, so tests use a temp folder.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path

LOG_NAME = "memory_log.jsonl"
USES_NAME = "memory_uses.json"
SYNC_NAME = "memory_sync.json"
OLD_NAME = "memory_core.jsonl"            # session 26's snapshot file, migrated on first use
MAX_OP_BYTES = 16_000
_LOCK = threading.RLock()


class _FileLock:
    """One writer at a time across processes too (the engine and a background job both write
    memory): fcntl on macOS/Linux, msvcrt on Windows. Re-entrant inside one process via _LOCK."""

    depth = 0

    def __init__(self, root: Path | None) -> None:
        self.path = data_dir(root) / (LOG_NAME + ".lock")
        self.fh = None

    def __enter__(self):
        _LOCK.acquire()
        _FileLock.depth += 1
        if _FileLock.depth == 1:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.fh = open(self.path, "a+b")
                if sys.platform == "win32":
                    import msvcrt  # pylint: disable=import-outside-toplevel
                    self.fh.seek(0)
                    for _ in range(200):
                        try:
                            msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError:
                            time.sleep(0.02)
                else:
                    import fcntl  # pylint: disable=import-outside-toplevel
                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
            except OSError:
                self.fh = None
        return self

    def __exit__(self, *exc):
        try:
            if _FileLock.depth == 1 and self.fh is not None:
                try:
                    if sys.platform == "win32":
                        import msvcrt  # pylint: disable=import-outside-toplevel
                        self.fh.seek(0)
                        msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl  # pylint: disable=import-outside-toplevel
                        fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
                self.fh.close()
        finally:
            _FileLock.depth -= 1
            _LOCK.release()
_CACHE: dict = {}                          # log path -> (stamp, ops, view)
_CLOCK = {"v": 0.0}

KINDS = ("profile", "preference", "person", "project", "decision", "fact", "episode", "lesson", "skill")
KIND_TIER = {"profile": "semantic", "preference": "semantic", "person": "semantic", "project": "semantic",
             "decision": "semantic", "fact": "semantic", "episode": "episodic", "lesson": "episodic",
             "skill": "procedural"}
KIND_LABEL = {"profile": "About you", "preference": "Preferences", "person": "People", "project": "Projects",
              "decision": "Decisions", "fact": "Facts", "episode": "Past work", "lesson": "Lessons",
              "skill": "Skills"}
IMPORTANCE = {"profile": 0.8, "preference": 0.8, "person": 0.7, "project": 0.7, "decision": 0.75,
              "fact": 0.5, "episode": 0.4, "lesson": 0.6, "skill": 0.6}


def host_name() -> str:
    """This machine's name on the peer link (peers.my_name), else the computer's name."""
    try:
        import peers  # pylint: disable=import-outside-toplevel
        name = peers.my_name()
    except Exception:  # noqa: BLE001
        import platform  # pylint: disable=import-outside-toplevel
        name = platform.node() or "this-machine"
    return re.sub(r"[^A-Za-z0-9_.-]", "", str(name))[:40] or "this-machine"


def data_dir(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def log_path(root: Path | None = None) -> Path:
    return data_dir(root) / LOG_NAME


def tick(seen: float = 0.0) -> float:
    """The hybrid logical clock: now, but always after everything seen so far."""
    with _LOCK:
        _CLOCK["v"] = max(time.time(), _CLOCK["v"] + 1e-6, float(seen or 0) + 1e-6)
        return round(_CLOCK["v"], 6)


def _observe(v: float) -> None:
    with _LOCK:
        _CLOCK["v"] = max(_CLOCK["v"], float(v or 0))


# --------------------------------------------------------------------------- the log

def _stamp(path: Path):
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _parse(lines) -> list:
    out = []
    for line in lines:
        try:
            op = json.loads(line)
        except ValueError:
            continue
        if isinstance(op, dict) and op.get("op") in ("put", "del") and op.get("id") and op.get("host"):
            out.append(op)
    return out


def _migrate(root: Path | None) -> None:
    """Session 26 kept a snapshot (memory_core.jsonl). Turn it into put operations, once."""
    old = data_dir(root) / OLD_NAME
    path = log_path(root)
    if path.exists() or not old.is_file():
        return
    host = host_name()
    lines = []
    n = 0
    for raw in old.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(item, dict) or not item.get("id"):
            continue
        n += 1
        item.setdefault("kind", "episode" if item.get("tier") == "episodic" else "fact")
        item.setdefault("status", "active")
        uses = {"uses": item.pop("uses", 0), "last_used": item.pop("last_used", 0)}
        if uses["uses"]:
            _set_use(root, item["id"], uses)
        lines.append(json.dumps({"op": "put", "id": item["id"], "item": item, "host": host, "n": n,
                                 "v": float(item.get("t") or time.time())}, ensure_ascii=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    try:
        os.replace(old, old.with_suffix(".jsonl.migrated"))
    except OSError:
        pass


def ops(root: Path | None = None) -> list:
    return _load(root)[0]


def _load(root: Path | None = None) -> tuple:
    """(ops, view) - cached until the file changes."""
    path = log_path(root)
    with _LOCK:
        _migrate(root)
        stamp = _stamp(path)
        cached = _CACHE.get(str(path))
        if cached and cached[0] == stamp and stamp is not None:
            return cached[1], cached[2]
        try:
            all_ops = _parse(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            all_ops = []
        view = _materialize(all_ops)
        for op in all_ops[-50:]:
            _observe(op.get("v", 0))
        _CACHE[str(path)] = (stamp, all_ops, view)
        return all_ops, view


def _key(op: dict) -> tuple:
    return (float(op.get("v") or 0), str(op.get("host") or ""), int(op.get("n") or 0))


def _materialize(all_ops: list) -> dict:
    """id -> the winning operation (last writer wins; a tombstone is an operation like any other)."""
    view: dict = {}
    for op in all_ops:
        cur = view.get(op["id"])
        if cur is None or _key(op) > _key(cur):
            view[op["id"]] = op
    return view


def _append(root: Path | None, lines: list) -> None:
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    before = _stamp(path)
    with open(path, "a", encoding="utf-8") as fh:
        for op in lines:
            fh.write(json.dumps(op, ensure_ascii=False) + "\n")
    cached = _CACHE.get(str(path))
    if cached and cached[0] == before and before is not None:
        # nobody else wrote in between (we hold the file lock): extend the cache instead of re-reading
        all_ops, view = cached[1], cached[2]
        for op in lines:
            all_ops.append(op)
            cur = view.get(op["id"])
            if cur is None or _key(op) > _key(cur):
                view[op["id"]] = op
        _CACHE[str(path)] = (_stamp(path), all_ops, view)
    else:
        _CACHE.pop(str(path), None)


def _next_n(all_ops: list, host: str, root: Path | None) -> int:
    floor = int((sync_state(root).get("floor") or {}).get(host, 0) or 0)
    return max([int(o.get("n") or 0) for o in all_ops if o.get("host") == host] + [floor]) + 1


def put(item: dict, root: Path | None = None) -> dict:
    """Write (or rewrite) one item. Returns the operation."""
    with _FileLock(root):
        all_ops, view = _load(root)
        host = host_name()
        seen = float(view[item["id"]].get("v") or 0) if item["id"] in view else 0.0
        op = {"op": "put", "id": item["id"], "item": item, "host": host,
              "n": _next_n(all_ops, host, root), "v": tick(seen)}
        _append(root, [op])
        _maybe_compact(root)
        return op


def delete(item_id: str, root: Path | None = None) -> dict | None:
    """A tombstone for one item, and its text redacted from the local log."""
    with _FileLock(root):
        all_ops, view = _load(root)
        if item_id not in view or view[item_id]["op"] == "del":
            return None
        host = host_name()
        op = {"op": "del", "id": item_id, "host": host, "n": _next_n(all_ops, host, root),
              "v": tick(float(view[item_id].get("v") or 0))}
        _append(root, [op])
        _redact(root, {item_id})
        return op


def _redact(root: Path | None, ids: set) -> None:
    """Remove the text of forgotten items from every older operation (ids and counters stay)."""
    all_ops, view = _load(root)
    changed = False
    for op in all_ops:
        if op["id"] in ids and op["op"] == "put" and not (op.get("item") or {}).get("redacted"):
            op["item"] = {"id": op["id"], "redacted": True}
            changed = True
    if changed:
        _rewrite(root, all_ops)


def _rewrite(root: Path | None, all_ops: list) -> None:
    path = log_path(root)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in all_ops), encoding="utf-8")
    os.replace(tmp, path)
    _CACHE.pop(str(path), None)


def _maybe_compact(root: Path | None, slack: int = 400) -> bool:
    """Keep only each item's winning operation once the log is mostly old revisions. The highest
    counter per machine is remembered (the floor), so vectors never go backwards."""
    all_ops, view = _load(root)
    if len(all_ops) <= 2 * len(view) + slack:
        return False
    vec = vector(root)
    state = sync_state(root)
    state["floor"] = vec
    save_sync_state(state, root)
    keep = {id(op) for op in view.values()}
    _rewrite(root, [op for op in all_ops if id(op) in keep])
    return True


def compact(root: Path | None = None) -> bool:
    with _FileLock(root):
        return _maybe_compact(root, slack=0)


# --------------------------------------------------------------------------- items

def get(item_id: str, root: Path | None = None) -> dict | None:
    op = _load(root)[1].get(item_id)
    if not op or op["op"] != "put" or (op.get("item") or {}).get("redacted"):
        return None
    return dict(op["item"], _v=op.get("v"), _host=op.get("host"))


def items(root: Path | None = None, include_inactive: bool = False) -> list:
    """Live items in creation order (superseded ones too when asked), with local use counts."""
    view = _load(root)[1]
    uses = _uses(root)
    out = []
    for op in view.values():
        item = op.get("item") or {}
        if op["op"] != "put" or item.get("redacted"):
            continue
        if not include_inactive and item.get("status", "active") != "active":
            continue
        u = uses.get(op["id"]) or {}
        out.append(dict(item, uses=int(u.get("uses", 0) or 0), last_used=float(u.get("last_used", 0) or 0),
                        _v=op.get("v"), _host=op.get("host")))
    out.sort(key=lambda i: (float(i.get("t") or 0), i["id"]))
    return out


def tombstones(root: Path | None = None) -> int:
    return sum(1 for op in _load(root)[1].values() if op["op"] == "del")


def new_id() -> str:
    return "m" + uuid.uuid4().hex[:10]


# --------------------------------------------------------------------------- use counts (local)

def _uses(root: Path | None = None) -> dict:
    try:
        data = json.loads((data_dir(root) / USES_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _set_use(root: Path | None, item_id: str, value: dict) -> None:
    data = _uses(root)
    data[item_id] = value
    path = data_dir(root) / USES_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def mark_used(ids: list, root: Path | None = None) -> None:
    with _LOCK:
        data = _uses(root)
        now = time.time()
        for item_id in ids:
            row = data.get(item_id) or {}
            data[item_id] = {"uses": int(row.get("uses", 0) or 0) + 1, "last_used": now}
        path = data_dir(root) / USES_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)


# --------------------------------------------------------------------------- sync (vectors)

def sync_state(root: Path | None = None) -> dict:
    try:
        data = json.loads((data_dir(root) / SYNC_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_sync_state(state: dict, root: Path | None = None) -> None:
    path = data_dir(root) / SYNC_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def vector(root: Path | None = None) -> dict:
    """{host: highest operation counter held} - what this machine has, per machine."""
    out = dict((sync_state(root).get("floor") or {}))
    for op in _load(root)[0]:
        h = op["host"]
        out[h] = max(int(out.get(h, 0) or 0), int(op.get("n") or 0))
    return out


def ops_since(have: dict, root: Path | None = None, limit: int = 2000) -> list:
    """The operations a machine holding `have` lacks (oldest first, at most `limit`)."""
    have = have if isinstance(have, dict) else {}
    lacking = [op for op in _load(root)[0] if int(op.get("n") or 0) > int(have.get(op["host"], 0) or 0)]
    lacking.sort(key=_key)
    return lacking[:max(1, int(limit))]


def _valid(op) -> bool:
    if not isinstance(op, dict) or op.get("op") not in ("put", "del"):
        return False
    if not re.fullmatch(r"[A-Za-z0-9:_.-]{1,64}", str(op.get("id") or "")):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", str(op.get("host") or "")):
        return False
    try:
        int(op.get("n")), float(op.get("v"))
    except (TypeError, ValueError):
        return False
    if op["op"] == "put":
        item = op.get("item")
        if not isinstance(item, dict) or item.get("id") != op["id"]:
            return False
        if len(json.dumps(item)) > MAX_OP_BYTES:
            return False
    return True


def merge(incoming: list, root: Path | None = None, clean=None) -> dict:
    """Add another machine's operations. Idempotent and order-independent (an LWW map).

    `clean(item) -> item` re-checks a received item (secrets scrubbed) before it is stored."""
    with _FileLock(root):
        all_ops, view = _load(root)
        have = {(o["host"], int(o.get("n") or 0)) for o in all_ops}
        floor = sync_state(root).get("floor") or {}
        fresh, dropped = [], 0
        for op in incoming or []:
            if not _valid(op):
                dropped += 1
                continue
            ident = (op["host"], int(op["n"]))
            if ident in have:
                continue
            if int(op["n"]) <= int(floor.get(op["host"], 0) or 0) and not _beats(op, view):
                continue      # we had it once and compacted it away: it lost already
            op = {k: op[k] for k in ("op", "id", "item", "host", "n", "v") if k in op}
            if op["op"] == "put" and clean is not None and not op["item"].get("redacted"):
                op["item"] = clean(dict(op["item"]))
            fresh.append(op)
            have.add(ident)
            _observe(op["v"])
        if fresh:
            _append(root, fresh)
            gone = {op["id"] for op in fresh if op["op"] == "del"}
            view = _load(root)[1]
            late = {op["id"] for op in fresh if op["op"] == "put" and view.get(op["id"], {}).get("op") == "del"}
            if gone or late:
                _redact(root, gone | late)
        changed = sorted({op["id"] for op in fresh})
        return {"received": len(fresh), "dropped": dropped, "ids": changed}


def _beats(op: dict, view: dict) -> bool:
    cur = view.get(op["id"])
    return cur is None or _key(op) > _key(cur)
