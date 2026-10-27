"""One library on every machine: the pictures, sprites, turnarounds, renders, 3D models and videos LOKI made on the Mac
show up on the PC, and the other way round (owner 2026-10-27: "i found the fox on mac its weird they dont share the
same library we gotta fix that").

The same signed peer link as memory (engine/peers.py, HMAC-signed, replay-guarded). Each machine PULLS what it lacks:

    this machine                                    the other machine
    POST /peer/library {op: "list"}            ->   {files: [{rel, size, t}]}   (its library, newest first)
    POST /peer/library {op: "read", rel, offset} -> {data: <base64 chunk>, size} (4 MB at a time)

Rules - additive only, nothing is ever deleted or overwritten:
  - a file this machine already has under that name is left alone (the two copies may differ; both are kept)
  - a file this machine put in its trash (`<workspace>/trash/<kind>/`) is never pulled back
  - a sidecar (`<kind>/.meta/<file>.json`: prompt, style, likes, ratings) is copied when missing, and replaced only
    by a NEWER one from the other machine (a thumbs-up on the PC shows on the Mac); its time is kept, so the two
    machines never ping-pong
  - the download goes to a hidden `.part` file and is renamed only when complete; a file larger than
    LOKI_LIBRARY_SYNC_MAX_MB (200) is skipped, and nothing is pulled while the disk has less than
    LOKI_LIBRARY_SYNC_MIN_FREE_GB (5) free (the Mac's drive is nearly full)
  - the serving side answers only for the library folders, one plain file name, never a hidden file, never a folder
    outside them

When: 60 s after start, then every LOKI_LIBRARY_SYNC_S (600) while machines are linked. LOKI_LIBRARY_SYNC=off stops it.
Standard library only.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

KINDS = ("images", "sketches", "sprites", "turnarounds", "renders", "models", "videos")
META_DIR = ".meta"
TRASH = "trash"
CHUNK = 4 * 1024 * 1024            # raw bytes per request: its base64 stays under peers.MAX_BODY (8 MB)
LIST_MAX = 5000
STATE_NAME = "library_sync.json"
_LOCK = threading.Lock()
_RUNNING = {"on": False}
_NAME = re.compile(r"^[^/\\:*?\"<>|\x00-\x1f]{1,200}$")


def on(env=None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("LOKI_LIBRARY_SYNC", "on")).strip().lower() not in ("0", "off", "false", "no")


def _max_bytes() -> int:
    return int(float(os.environ.get("LOKI_LIBRARY_SYNC_MAX_MB", "200") or 200) * 1024 * 1024)


def _min_free() -> int:
    return int(float(os.environ.get("LOKI_LIBRARY_SYNC_MIN_FREE_GB", "5") or 5) * 1024 ** 3)


# ----------------------------------------------------------------------------- paths
def safe_rel(workspace: Path, rel: str) -> Path | None:
    """'images/fox.png' or 'images/.meta/fox.png.json' -> the file in this workspace, or None if it is anything else."""
    parts = str(rel or "").split("/")
    if len(parts) == 2:
        kind, name = parts
        meta = False
    elif len(parts) == 3 and parts[1] == META_DIR:
        kind, name = parts[0], parts[2]
        meta = True
    else:
        return None
    if kind not in KINDS or not _NAME.match(name) or name.startswith(".") or name in ("..",) or name.endswith(" "):
        return None
    if meta and not name.endswith(".json"):
        return None
    base = (Path(workspace) / kind).resolve()
    p = (base / META_DIR / name) if meta else (base / name)
    try:
        p.resolve().relative_to(base)
    except (OSError, ValueError):
        return None
    return p


def listing(workspace: Path) -> list:
    """This machine's library: [{rel, size, t}], newest first (files, then their sidecars)."""
    out = []
    for kind in KINDS:
        folder = Path(workspace) / kind
        for sub, prefix in ((folder, kind + "/"), (folder / META_DIR, kind + "/" + META_DIR + "/")):
            if not sub.is_dir():
                continue
            try:
                entries = list(sub.iterdir())
            except OSError:
                continue
            for p in entries:
                if p.name.startswith(".") or not p.is_file():
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                out.append({"rel": prefix + p.name, "size": st.st_size, "t": st.st_mtime})
    out.sort(key=lambda f: f["t"], reverse=True)
    return out[:LIST_MAX]


def trashed(workspace: Path, rel: str) -> bool:
    """Did the owner put this file (or its picture, for a sidecar) in this machine's trash?"""
    parts = rel.split("/")
    kind, name = parts[0], parts[-1]
    if len(parts) == 3:
        name = name[:-len(".json")]
    folder = Path(workspace) / TRASH / kind
    if not folder.is_dir():
        return False
    if (folder / name).exists():
        return True
    stem, ext = os.path.splitext(name)
    return any(folder.glob("%s-[0-9]*%s" % (glob_escape(stem), glob_escape(ext))))


def glob_escape(text: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", text)


# ----------------------------------------------------------------------------- serving side
def serve(workspace: Path, data: dict) -> tuple:
    """POST /peer/library on this machine. Returns (code, payload)."""
    if not on():
        return 404, {"ok": False, "error": "library sync is off on this machine"}
    op = str((data or {}).get("op") or "")
    if op == "list":
        return 200, {"ok": True, "files": listing(workspace)}
    if op == "read":
        p = safe_rel(workspace, str(data.get("rel") or ""))
        if p is None or not p.is_file():
            return 404, {"ok": False, "error": "no such file in the library"}
        off = max(0, int(data.get("offset") or 0))
        size = p.stat().st_size
        with p.open("rb") as fh:
            fh.seek(off)
            raw = fh.read(CHUNK)
        return 200, {"ok": True, "data": base64.b64encode(raw).decode("ascii"), "size": size, "t": p.stat().st_mtime}
    return 400, {"ok": False, "error": "op must be list or read"}


# ----------------------------------------------------------------------------- pulling side
def _want(workspace: Path, f: dict) -> str:
    """'' if this machine should pull the file, else why not."""
    p = safe_rel(workspace, str(f.get("rel") or ""))
    if p is None:
        return "not a library file"
    if trashed(workspace, f["rel"]):
        return "in this machine's trash"
    if int(f.get("size") or 0) > _max_bytes():
        return "too big"
    if p.exists():
        if p.parent.name == META_DIR and p.is_file():
            try:
                if float(f.get("t") or 0) > p.stat().st_mtime + 1:
                    return ""                       # a newer sidecar (a like, a rating) from the other machine
            except OSError:
                pass
        return "already here"
    return ""


def _fetch(peer: dict, workspace: Path, f: dict, call) -> int:
    p = safe_rel(workspace, f["rel"])
    p.parent.mkdir(parents=True, exist_ok=True)
    part = p.with_name("." + p.name + ".part")
    got, size, t = 0, None, None
    try:
        with part.open("wb") as out:
            while size is None or got < size:
                reply = call(peer, "POST", "/peer/library", {"op": "read", "rel": f["rel"], "offset": got}, timeout=120)
                raw = base64.b64decode(str(reply.get("data") or ""), validate=True)
                size, t = int(reply.get("size") or 0), reply.get("t")
                if not raw and got < size:
                    raise RuntimeError("the other machine sent an empty chunk")
                out.write(raw)
                got += len(raw)
                if got > _max_bytes():
                    raise RuntimeError("too big")
        if p.exists() and p.parent.name != META_DIR:     # made here while we downloaded: keep ours
            part.unlink()
            return 0
        os.replace(part, p)
        if t:
            os.utime(p, (float(t), float(t)))
        return got
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass


def _state_file(data_dir: Path | None) -> Path | None:
    return Path(data_dir) / STATE_NAME if data_dir else None


def _record(data_dir: Path | None, name: str, **fields) -> None:
    f = _state_file(data_dir)
    if f is None:
        return
    try:
        state = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    except (OSError, ValueError):
        state = {}
    state.setdefault("peers", {}).setdefault(name, {}).update(fields)
    try:
        f.write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError:
        pass


def pull(peer: dict, workspace: Path, call=None, data_dir: Path | None = None, budget_s: float = 300) -> dict:
    """Copy what this machine lacks from one linked machine. Returns {peer, pulled, bytes, skipped, error}."""
    if call is None:
        import peers  # pylint: disable=import-outside-toplevel
        call = peers.call
    name = peer.get("name") or "peer"
    out = {"peer": name, "pulled": 0, "bytes": 0, "skipped": 0, "error": ""}
    with _LOCK:
        try:
            files = call(peer, "POST", "/peer/library", {"op": "list"}, timeout=60).get("files") or []
            want = [f for f in files if isinstance(f, dict) and not _want(workspace, f)]
            out["skipped"] = len(files) - len(want)
            # pictures before their sidecars, so the wall never shows a prompt without its picture
            want.sort(key=lambda f: (f["rel"].count("/"), -float(f.get("t") or 0)))
            t0 = time.time()
            for f in want:
                if time.time() - t0 > budget_s:
                    out["error"] = "time is up - the rest comes next round"
                    break
                try:
                    free = shutil.disk_usage(Path(workspace)).free
                except OSError:
                    free = 0
                if free - int(f.get("size") or 0) < _min_free():
                    out["error"] = "less than %d GB free here - stopped" % (_min_free() // 1024 ** 3)
                    break
                n = _fetch(peer, workspace, f, call)
                if n or f["rel"].count("/") == 2:
                    out["pulled"] += 1
                    out["bytes"] += n
        except Exception as exc:  # noqa: BLE001 - record why; the next round tries again
            out["error"] = str(exc)[:200]
    _record(data_dir, name, t=time.time(), pulled=out["pulled"], bytes=out["bytes"], error=out["error"])
    return out


def sync_all(workspace: Path, peer_list: list | None = None, call=None, data_dir: Path | None = None) -> list:
    if peer_list is None:
        import peers  # pylint: disable=import-outside-toplevel
        peer_list = peers.peers()
    return [pull(p, workspace, call, data_dir) for p in peer_list]


def status(data_dir: Path | None) -> dict:
    f = _state_file(data_dir)
    try:
        state = json.loads(f.read_text(encoding="utf-8")) if f and f.is_file() else {}
    except (OSError, ValueError):
        state = {}
    return {"on": on(), "peers": state.get("peers") or {}}


def run_forever(agent) -> None:
    """Background: 60 s after start, then every LOKI_LIBRARY_SYNC_S. One loop per process; never dies."""
    if _RUNNING["on"]:
        return
    _RUNNING["on"] = True
    import peers  # pylint: disable=import-outside-toplevel
    time.sleep(60)
    while True:
        try:
            if on() and peers.peers():
                data = getattr(agent, "DATA_DIR", "") or None
                sync_all(Path(getattr(agent, "WORKSPACE", ".")), data_dir=Path(data) if data else None)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(max(60, int(os.environ.get("LOKI_LIBRARY_SYNC_S", "600") or 600)))
