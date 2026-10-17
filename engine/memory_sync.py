"""One memory on every machine: LOKI's memory log, exchanged over the signed peer link.

A memory learned on the Mac is known on the PC (and the other way round), through the same signed
link (peers.py: HMAC-signed, replay-guarded, LAN or the relay) that already carries jobs and updates.

    this machine                                  the other machine
    POST /peer/memory {have: {mac: 17, pc: 4},  ->  merge the ops it lacks, then answer with
                       ops: [ops it lacks]}          {have: {...}, ops: [ops this machine lacks]}

`have` is a vector: the highest operation counter held per machine (memory_store.vector). Each
side sends only what the other lacks, merging is order-independent (last writer wins per item id,
tombstones for forget - memory_store.merge), so the exchange is conflict-free and can repeat,
fail half-way or run through a third machine without harm. Received items are scrubbed again
(memory_core.clean_item) before they are stored.

The owner's notes file (memory.md, Settings > Memory's text box) rides along as one document
item: the newer edit wins and the older text is kept in its history.

When: a few seconds after something is learned or forgotten (nudge), and every LOKI_MEMORY_SYNC_S
seconds (default 300) while peers are linked. Settings > Memory shows when each machine last
synced and "Sync now".
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

import memory_store

SYNC_EVERY_S = int(os.getenv("LOKI_MEMORY_SYNC_S", "300") or 300)
BATCH = 1000
NOTES_ID = "doc-memory-md"
_EVENT = threading.Event()
_RUNNING = {"on": False}
_SYNC_LOCK = threading.Lock()


def nudge() -> None:
    """Something changed: sync soon (the background loop waits a few seconds to batch changes)."""
    _EVENT.set()


def _clean(item: dict) -> dict:
    import memory_core  # pylint: disable=import-outside-toplevel
    if item.get("id") == NOTES_ID:
        item["text"] = memory_core.scrub(str(item.get("text") or ""))[:12000]
        item["status"] = "doc"
        item["kind"] = "profile"
        return item
    return memory_core.clean_item(item)


def _hash(text: str) -> str:
    return hashlib.sha1(str(text).replace("\r\n", "\n").strip().encode("utf-8", "replace")).hexdigest()[:16]


def sync_notes(root: Path | None = None, notes_file: Path | None = None) -> str:
    """Keep memory.md the same everywhere. Returns "pushed", "pulled" or ""."""
    notes = Path(notes_file) if notes_file else memory_store.data_dir(root) / "memory.md"
    try:
        local = notes.read_text(encoding="utf-8") if notes.is_file() else ""
    except OSError:
        return ""
    state = memory_store.sync_state(root)
    last = state.get("notes_hash")            # None: this machine never synced its notes
    doc = memory_store.get(NOTES_ID, root)
    doc_text = str((doc or {}).get("text") or "")
    local_h, doc_h = _hash(local), (_hash(doc_text) if doc else None)

    def remember_hash(text: str) -> None:
        fresh = memory_store.sync_state(root)
        fresh["notes_hash"] = _hash(text)
        memory_store.save_sync_state(fresh, root)

    if doc_h == local_h:
        if last != local_h:
            remember_hash(local)
        return ""
    if last is None and local.strip() and doc_text.strip():
        # the first sync of two machines that both had notes: keep every line of both
        lines = local.rstrip().splitlines()
        have = {ln.strip() for ln in lines}
        merged = "\n".join(lines + [ln for ln in doc_text.splitlines() if ln.strip() and ln.strip() not in have])
        notes.write_text(merged.rstrip() + "\n", encoding="utf-8")
        local, local_h = notes.read_text(encoding="utf-8"), _hash(merged)
        changed_here = True
    else:
        changed_here = bool(local.strip()) if last is None else local_h != last
    if changed_here:
        history = list((doc or {}).get("history") or [])
        if doc_text:
            history = (history + [{"text": doc_text[:4000], "t": (doc or {}).get("updated", 0)}])[-5:]
        import memory_core  # pylint: disable=import-outside-toplevel
        memory_store.put({"id": NOTES_ID, "kind": "profile", "tier": "semantic", "status": "doc",
                          "text": memory_core.scrub(local)[:12000], "updated": time.time(), "t": time.time(),
                          "history": history, "source": "owner"}, root)
        remember_hash(local)
        return "pushed"
    if doc is not None:
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text(doc_text.rstrip() + "\n" if doc_text.strip() else "", encoding="utf-8")
        remember_hash(notes.read_text(encoding="utf-8"))
        return "pulled"
    return ""


def _record(name: str, root: Path | None, **fields) -> None:
    state = memory_store.sync_state(root)
    peers_state = state.setdefault("peers", {})
    row = peers_state.setdefault(name, {})
    row.update(fields)
    memory_store.save_sync_state(state, root)


def receive(origin: str, data: dict, root: Path | None = None, notes_file: Path | None = None) -> dict:
    """The peer-server side of POST /peer/memory."""
    ops = data.get("ops") if isinstance(data, dict) else None
    if not isinstance(ops, list):
        raise ValueError("ops must be a list")
    have = data.get("have") if isinstance(data.get("have"), dict) else {}
    with _SYNC_LOCK:
        got = memory_store.merge(ops[:BATCH], root, clean=_clean)
        sync_notes(root, notes_file)
        lacking = memory_store.ops_since(have, root, limit=BATCH)
        mine = memory_store.vector(root)
    _record(origin, root, t=time.time(), received=got["received"], sent=len(lacking), error="", direction="in")
    return {"have": mine, "ops": lacking, "more": len(lacking) >= BATCH, "received": got["received"],
            "host": memory_store.host_name()}


def exchange(peer: dict, root: Path | None = None, notes_file: Path | None = None, call=None,
             rounds: int = 5) -> dict:
    """Sync with one linked machine. Returns {"sent", "received", "peer"} or raises peers.PeerError."""
    if call is None:
        import peers  # pylint: disable=import-outside-toplevel
        call = peers.call
    name = peer["name"]
    sent = received = 0
    with _SYNC_LOCK:
        sync_notes(root, notes_file)
    try:
        for _ in range(max(1, rounds)):
            state = memory_store.sync_state(root)
            known = ((state.get("peers") or {}).get(name) or {}).get("have") or {}
            mine = memory_store.ops_since(known, root, limit=BATCH)
            reply = call(peer, "POST", "/peer/memory", {"have": memory_store.vector(root), "ops": mine}, timeout=30)
            with _SYNC_LOCK:
                got = memory_store.merge(reply.get("ops") or [], root, clean=_clean)
                sync_notes(root, notes_file)
            sent += len(mine)
            received += got["received"]
            _record(name, root, have=reply.get("have") or {}, t=time.time(), sent=sent, received=received,
                    error="", direction="out")
            if not reply.get("more") and len(mine) < BATCH:
                break
    except Exception as exc:  # noqa: BLE001 - record why, then let the caller decide
        _record(name, root, t=time.time(), error=str(exc)[:200])
        raise
    return {"peer": name, "sent": sent, "received": received}


def sync_all(root: Path | None = None, notes_file: Path | None = None, peer_list: list | None = None,
             call=None) -> list:
    """Sync with every linked machine; one that cannot be reached is skipped (and recorded)."""
    if peer_list is None:
        import peers  # pylint: disable=import-outside-toplevel
        peer_list = peers.peers()
    out = []
    for peer in peer_list:
        try:
            out.append(dict(exchange(peer, root, notes_file, call), ok=True))
        except Exception as exc:  # noqa: BLE001
            out.append({"peer": peer.get("name"), "ok": False, "error": str(exc)[:200]})
    return out


def status(root: Path | None = None) -> dict:
    state = memory_store.sync_state(root)
    try:
        import peers  # pylint: disable=import-outside-toplevel
        linked = [p["name"] for p in peers.peers()]
    except Exception:  # noqa: BLE001
        linked = []
    rows = []
    for name, row in sorted((state.get("peers") or {}).items()):
        rows.append({"peer": name, "t": row.get("t", 0), "sent": row.get("sent", 0),
                     "received": row.get("received", 0), "error": row.get("error", ""),
                     "linked": name in linked})
    for name in linked:
        if not any(r["peer"] == name for r in rows):
            rows.append({"peer": name, "t": 0, "sent": 0, "received": 0, "error": "", "linked": True})
    return {"host": memory_store.host_name(), "peers": rows, "every_s": SYNC_EVERY_S,
            "ops": len(memory_store.ops(root)), "vector": memory_store.vector(root)}


def run_forever(agent) -> None:
    """Background: sync after changes (batched for 5 s) and every SYNC_EVERY_S. One loop per process."""
    if _RUNNING["on"]:
        return
    _RUNNING["on"] = True
    import peers  # pylint: disable=import-outside-toplevel
    time.sleep(25)       # let the engine and the peer link finish starting
    while True:
        changed = _EVENT.wait(SYNC_EVERY_S)
        if changed:
            time.sleep(5)
        _EVENT.clear()
        if not peers.peers():
            continue
        try:
            sync_all(Path(getattr(agent, "DATA_DIR", "") or memory_store.data_dir()),
                     getattr(agent, "MEMORY_FILE", None))
        except Exception:  # noqa: BLE001 - the loop must never die
            pass
