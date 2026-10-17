"""Files on your other machines, over LOKI's signed peer link (engine/peers.py).

The asking side: the `peer_files` tool - machines, list, read, write (write asks the owner, and never
runs from a background job). The answering side: `POST /peer/files` on the peer server, which only
serves its SHARED folder (LOKI_PEER_FILES_ROOT, default ~/LOKI Projects), never a hidden file or folder
(.env, .ssh, .git ...) and never harness_data; it accepts writes only when THAT machine's owner turned
them on (LOKI_PEER_FILES_WRITE=1, Settings > Tools > Files on my machines). Reads are text up to 200 KB.
Every request is HMAC-signed with the shared peer secret - the same link the jobs use.
"""
from __future__ import annotations

import os
from pathlib import Path

import connectors

SPEC = {
    "id": "peer_files",
    "label": "Files on my machines (peer link)",
    "about": "List and read files in the shared folder of your other LOKI machines (Mac <-> PC). Writing a file "
             "there asks you first, and the other machine must allow writes.",
    "tool": "peer_files",
    "writes": ["write"],
    "help": "Link the machines first (Settings > Machines). Each machine shares only its shared folder.",
    "fields": [
        {"key": "LOKI_PEER_FILES_ROOT", "label": "Folder this machine shares (blank = ~/LOKI Projects)", "kind": "text"},
        {"key": "LOKI_PEER_FILES_WRITE", "label": "Let my other machines write into it", "kind": "bool", "default": "0"},
    ],
}
READ_BYTES = 200_000
WRITE_BYTES = 1_000_000
LIST_MAX = 300
CALL = None          # tests inject a fake peers.call


def root(source: dict | None = None) -> Path:
    raw = connectors.get("LOKI_PEER_FILES_ROOT", source)
    return Path(os.path.expanduser(raw)).resolve() if raw else (Path.home() / "LOKI Projects").resolve()


def writes_allowed(source: dict | None = None) -> bool:
    return connectors.get("LOKI_PEER_FILES_WRITE", source) in ("1", "true", "on", "yes")


def _peers(source: dict | None = None) -> list:
    import peers  # pylint: disable=import-outside-toplevel
    return peers.peers(source)


def status(source: dict | None = None) -> dict:
    try:
        linked = _peers(source)
    except Exception:  # noqa: BLE001
        linked = []
    if not linked:
        return {"configured": False, "detail": "no other machine is linked (Settings > Machines)"}
    return {"configured": True, "detail": "%d machine(s): %s; sharing %s%s" % (
        len(linked), ", ".join(p["name"] for p in linked), root(source), " (others may write)" if writes_allowed(source) else "")}


def test(source: dict | None = None) -> dict:
    st = status(source)
    if not st["configured"]:
        return {"ok": False, "detail": st["detail"]}
    out = tool("list", machine=_peers(source)[0]["name"], path="")
    return {"ok": not out.startswith("error"), "detail": out.splitlines()[0][:200]}


# ------------------------------------------------------------------ the answering side
def _safe(rel: str, base: Path) -> Path:
    name = str(rel or "").replace("\\", "/").strip().lstrip("/")
    target = (base / name).resolve() if name else base
    try:
        inside = target.relative_to(base)
    except ValueError:
        raise ValueError("that path is outside the shared folder") from None
    if any(part.startswith(".") or part.lower() == "harness_data" for part in inside.parts):
        raise ValueError("hidden files and LOKI's data folder are never shared")
    return target


def serve(origin: str, data: dict, source: dict | None = None) -> tuple:
    """POST /peer/files on this machine: {op: list|read|write, path, text}. Returns (code, payload)."""
    base = root(source)
    op = str(data.get("op") or "list").lower()
    if not base.is_dir():
        return 404, {"ok": False, "error": "this machine has no shared folder at %s" % base}
    try:
        target = _safe(str(data.get("path") or ""), base)
    except ValueError as exc:
        return 403, {"ok": False, "error": str(exc)}
    rel = target.relative_to(base).as_posix() if target != base else "."
    if op == "list":
        if not target.is_dir():
            return 404, {"ok": False, "error": "no folder %s" % rel}
        items = []
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name.startswith(".") or child.name.lower() == "harness_data":
                continue
            try:
                items.append({"name": child.name, "dir": child.is_dir(), "size": 0 if child.is_dir() else child.stat().st_size})
            except OSError:
                continue
            if len(items) >= LIST_MAX:
                break
        return 200, {"ok": True, "path": rel, "items": items}
    if op == "read":
        if not target.is_file():
            return 404, {"ok": False, "error": "no file %s" % rel}
        size = target.stat().st_size
        raw = target.read_bytes()[:READ_BYTES]
        if b"\x00" in raw[:4096]:
            return 415, {"ok": False, "error": "%s is a binary file (%d bytes); only text is sent" % (rel, size)}
        return 200, {"ok": True, "path": rel, "size": size, "text": raw.decode("utf-8", "replace"),
                     "truncated": size > READ_BYTES}
    if op == "write":
        if not writes_allowed(source):
            return 403, {"ok": False, "error": "this machine does not let other machines write (Settings > Tools > Files on my machines)"}
        text = str(data.get("text") or "")
        if len(text.encode("utf-8")) > WRITE_BYTES:
            return 413, {"ok": False, "error": "too big (1 MB at most)"}
        if target == base or target.is_dir():
            return 400, {"ok": False, "error": "give a file path"}
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.with_name(target.name + ".bak").write_bytes(target.read_bytes())
        target.write_text(text, encoding="utf-8")
        return 200, {"ok": True, "path": rel, "written": len(text), "from": origin}
    return 400, {"ok": False, "error": "op must be list, read or write"}


# ------------------------------------------------------------------ the asking side
def _call(peer: dict, payload: dict) -> dict:
    if CALL is not None:
        return CALL(peer, "POST", "/peer/files", payload)
    import peers  # pylint: disable=import-outside-toplevel
    return peers.call(peer, "POST", "/peer/files", payload, timeout=30)


def _find(machine: str) -> dict | None:
    want = str(machine or "").strip().lower()
    linked = _peers()
    if not want and len(linked) == 1:
        return linked[0]
    for p in linked:
        if p["name"].lower() == want:
            return p
    close = [p for p in linked if want and (p["name"].lower().startswith(want) or want in p["name"].lower())]
    return close[0] if len(close) == 1 else None      # "pc" finds "mohameds-pc"; an ambiguous name finds none


def preview(args: dict) -> str:
    return "WRITE FILE %s on %s (%d characters)" % (args.get("path", "?"), args.get("machine", "?"), len(str(args.get("text", ""))))


def tool(action: str = "machines", machine: str = "", path: str = "", text: str = "") -> str:
    """The `peer_files` tool."""
    action = str(action or "machines").strip().lower()
    if action in ("machines", "peers"):
        linked = _peers()
        return ("linked machines: " + ", ".join(p["name"] for p in linked)) if linked else \
            "error: no other machine is linked (Settings > Machines)"
    peer = _find(machine)
    if peer is None:
        names = ", ".join(p["name"] for p in _peers()) or "none linked"
        return "error: give machine='<name>' (linked: %s)" % names
    if action not in ("list", "read", "write"):
        return "error: unknown action %r - use machines, list, read or write" % action
    try:
        answer = _call(peer, {"op": action, "path": path, "text": text if action == "write" else ""})
    except Exception as exc:  # noqa: BLE001 - peers.PeerError and network errors
        return "error: %s" % connectors.redact(exc)[:240]
    if not answer.get("ok"):
        return "error: %s: %s" % (peer["name"], answer.get("error", "refused"))
    if action == "list":
        rows = ["%s%s" % (i["name"], "/" if i["dir"] else "  (%d bytes)" % i["size"]) for i in answer.get("items", [])]
        return "%s:%s\n%s" % (peer["name"], answer.get("path", "."), "\n".join(rows) or "(empty)")
    if action == "read":
        return connectors.untrusted("a file on " + peer["name"], "%s:%s (%d bytes%s)\n\n%s" % (
            peer["name"], answer.get("path"), answer.get("size", 0), ", first 200 KB" if answer.get("truncated") else "",
            answer.get("text", "")))
    return "wrote %s on %s (%d characters)" % (answer.get("path"), peer["name"], answer.get("written", 0))


connectors.register(__import__(__name__))
