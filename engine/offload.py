"""Give heavy work to the PC (owner 2026-10-26: "why cant i send work to my pc from here most of these jobs should be done
there the mac isnt the power house ... the mac should always try to give windows work thats the entire thing it needs to
give windows work without pushing git").

The Mac mini (16 GB shared memory) is where the owner works; the PC (RTX 3070 Ti) is the power house. Picture making, area
edits, 3D models and Blender clean-ups run on the PC when it is linked, sent over the signed peer link (engine/peers.py,
LAN or the relay) - files go up, the job runs there, the results come back into the Mac's own folders. Nothing goes
through git or GitHub.

    target(kind)                     the linked machine that should do `kind`, or None (do it here)
    run(kind, params, inputs, dest)  send it, wait, download the results into dest -> {"files", "result", "peer"}
    status()                         this machine's role and each linked machine's work kinds (Settings, Home)

Which machine works:
  * LIGHT machines give work away: a Mac, or any machine without an NVIDIA GPU (LOKI_MACHINE_ROLE=light|main overrides).
  * A linked machine takes a kind only when its hello lists it (`work`: what it can really run - an image model, sd.cpp,
    a real 3D backend, Blender). An older LOKI there lists nothing: the Mac asks it once an hour to update itself.
  * LOKI_OFFLOAD=off keeps everything here; =always gives work away even from a strong machine.
  * A job that came FROM another machine never goes on to a third (no ping-pong).

The serving side (`serve`, POST /peer/work) only runs the kinds in KINDS with their own whitelisted settings - a peer
picks WHAT (a prompt, a size), never a program, a path or a keyword it was not given. Uploaded files are plain names in
<data>/offload/<id>/in, results are read back only from <id>/out, everything older than a day is removed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

CHUNK = 4 * 1024 * 1024            # raw bytes per request: base64 of it stays under peers.MAX_BODY (8 MB)
MAX_FILE = 400 * 1024 * 1024       # one uploaded file
MAX_JOB = 1024 * 1024 * 1024       # everything one job uploads
KEEP_S = 24 * 3600
HELLO_TTL = 60.0
UPDATE_ASK_EVERY = 3600.0
POLL_S = 3.0

# kind -> (settings a peer may give, how long it may take)
KINDS = {
    "image": ({"prompt", "negative", "width", "height", "seed", "count", "steps", "cfg", "sampler", "strength"}, 1800),
    "img2img": ({"prompt", "width", "height", "strength", "seed"}, 1800),
    "make_3d": ({"prompt", "backend", "options"}, 2400),
    "polish": ({"name", "size", "target", "style", "lods", "turntable", "remesh", "edits", "formats", "repair",
                "symmetric", "retopo"}, 2400),
}
LABEL = {"image": "make pictures", "img2img": "edit an area of a picture", "make_3d": "make 3D models",
         "polish": "clean up models in Blender"}


class OffloadError(Exception):
    pass


_LOCAL = threading.local()          # set while this machine runs a job FOR another one
_HELLO: dict = {}                   # peer name -> (time, hello or None, error)
_ASKED_UPDATE: dict = {}
JOBS: dict = {}
_LOCK = threading.Lock()


def _data(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("LOKI_DATA") or (Path(__file__).resolve().parent.parent / "harness_data"))


def _clean_id(text) -> str:
    return "".join(ch for ch in str(text or "") if ch.isalnum())[:16]


def _clean_name(text) -> str:
    """A plain file name or a short relative path of plain names (results keep their folders: renders/x.png)."""
    parts = [p for p in str(text or "").replace("\\", "/").split("/") if p not in ("", ".", "..")]
    parts = [re.sub(r"[^A-Za-z0-9._ -]", "_", p)[:120].lstrip(".") for p in parts][:6]
    return "/".join(p for p in parts if p)


# ----------------------------------------------------------------------------- who works
def role(env: dict | None = None, info: dict | None = None) -> str:
    """'light' (gives heavy work away) or 'main' (does it)."""
    env = os.environ if env is None else env
    forced = str(env.get("LOKI_MACHINE_ROLE", "")).strip().lower()
    if forced in ("light", "main"):
        return forced
    if info is None:
        try:
            import creative  # pylint: disable=import-outside-toplevel
            info = creative.machine()
        except Exception:  # noqa: BLE001
            info = {"os": sys.platform}
    if (info.get("os") or sys.platform) == "darwin" or info.get("apple_silicon"):
        return "light"
    return "main" if info.get("nvidia") else "light"


def serving() -> bool:
    return bool(getattr(_LOCAL, "serving", False))


def mode(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    m = str(env.get("LOKI_OFFLOAD", "auto")).strip().lower()
    return m if m in ("auto", "off", "always") else "auto"


def hello_of(peer: dict, call: Callable | None = None, clock=time.time) -> tuple:
    """(hello, error) for a linked machine, cached for a minute (a failure for 20 s)."""
    name = peer.get("name", "")
    hit = _HELLO.get(name)
    if hit and clock() - hit[0] < (HELLO_TTL if hit[1] else 20.0):
        return hit[1], hit[2]
    import peers  # pylint: disable=import-outside-toplevel
    try:
        got = (call or peers.call)(peer, "GET", "/peer/hello", timeout=8.0)
        _HELLO[name] = (clock(), got, "")
    except Exception as exc:  # noqa: BLE001 - offline is an answer
        _HELLO[name] = (clock(), None, str(exc)[:200])
    return _HELLO[name][1], _HELLO[name][2]


def target(kind: str, env: dict | None = None, call: Callable | None = None, linked: list | None = None,
           info: dict | None = None) -> dict | None:
    """The linked machine to give `kind` to, or None to run it here."""
    if kind not in KINDS or serving():
        return None
    m = mode(env)
    if m == "off" or (m == "auto" and role(env, info) != "light"):
        return None
    try:
        import peers  # pylint: disable=import-outside-toplevel
        linked = peers.peers(env) if linked is None else linked
    except Exception:  # noqa: BLE001
        return None
    for peer in linked:
        hello, _err = hello_of(peer, call)
        if hello and kind in (hello.get("work") or []):
            return peer
        if hello and "work" not in hello:
            _ask_update(peer, call)
    return None


def why_not(kind: str, env: dict | None = None, call: Callable | None = None, linked: list | None = None) -> str:
    """Plain words: why `kind` is not going to another machine right now ("" when it is)."""
    if mode(env) == "off":
        return "giving work to other machines is off (LOKI_OFFLOAD=off)"
    try:
        import peers  # pylint: disable=import-outside-toplevel
        linked = peers.peers(env) if linked is None else linked
    except Exception:  # noqa: BLE001
        linked = []
    if not linked:
        return "no other machine is linked (Settings > Machines: paste the PC's link code)"
    out = []
    for peer in linked:
        hello, err = hello_of(peer, call)
        if hello is None:
            out.append("%s is not answering (%s) - is LOKI open on it?" % (peer["name"], err or "offline"))
        elif "work" not in hello:
            out.append("%s runs an older LOKI that cannot take work yet - it was asked to update itself" % peer["name"])
        elif kind not in hello["work"]:
            out.append("%s cannot %s right now (%s)" % (peer["name"], LABEL.get(kind, kind),
                                                        (hello.get("work_why") or {}).get(kind) or "not set up there"))
        else:
            return ""
    return "; ".join(out)


def _ask_update(peer: dict, call: Callable | None = None, clock=time.time) -> None:
    """An older LOKI on the PC: ask it (once an hour) to update from GitHub and restart - its own updater decides."""
    name = peer.get("name", "")
    if clock() - _ASKED_UPDATE.get(name, 0) < UPDATE_ASK_EVERY:
        return
    _ASKED_UPDATE[name] = clock()
    import peers  # pylint: disable=import-outside-toplevel

    def ask():
        try:
            (call or peers.call)(peer, "POST", "/peer/update/apply", {}, timeout=20.0)
            print("[loki-offload] %s runs an older LOKI; asked it to update so it can take work" % name, flush=True)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=ask, daemon=True).start()


# ----------------------------------------------------------------------------- the light machine's side
def run(kind: str, params: dict, inputs: dict, dest: Path, peer: dict | None = None, call: Callable | None = None,
        progress: Callable | None = None, timeout: float | None = None, sleep=time.sleep, clock=time.time) -> dict:
    """Send `kind` to `peer` (default: target(kind)), wait for it, download its files into `dest` (keeping their
    sub-folders). Returns {"ok", "peer", "result", "files": [local paths], "seconds"}; raises OffloadError."""
    if kind not in KINDS:
        raise OffloadError("unknown kind of work: %s" % kind)
    peer = peer or target(kind, call=call)
    if peer is None:
        raise OffloadError(why_not(kind, call=call) or "no machine to give this to")
    import peers  # pylint: disable=import-outside-toplevel
    send = call or peers.call
    say = progress or (lambda msg: None)
    allowed, limit = KINDS[kind]
    params = {k: v for k, v in (params or {}).items() if k in allowed and v is not None}
    job = secrets.token_hex(8)
    t0 = clock()

    def post(payload, tries=3, wait=60.0):
        last = None
        for n in range(tries):
            try:
                got = send(peer, "POST", "/peer/work", payload, timeout=wait)
            except Exception as exc:  # noqa: BLE001 - the relay drops a request now and then
                last = exc
                if payload.get("op") == "start" or "HTTP 4" in str(exc):
                    break        # never start twice; an old LOKI will not learn the route by asking again
                sleep(1.0 + n)
                continue
            if not got.get("ok", True):
                raise OffloadError("%s: %s" % (peer["name"], got.get("error") or "refused"))
            return got
        msg = str(last)
        if "unknown peer endpoint" in msg:
            _ask_update(peer, call)
            raise OffloadError("%s runs an older LOKI that cannot take work yet - asked it to update" % peer["name"])
        if " answered HTTP " in msg:      # it answered: its own reason (no such job, cannot run that here ...)
            raise OffloadError(msg[:300])
        raise OffloadError("could not reach %s: %s" % (peer["name"], msg[:200]))

    for name, path in (inputs or {}).items():
        path = Path(path)
        if not path.is_file():
            raise OffloadError("input missing: %s" % path)
        say("sending %s to %s" % (path.name, peer["name"]))
        size = path.stat().st_size
        with path.open("rb") as fh:
            off = 0
            while True:
                data = fh.read(CHUNK)
                post({"op": "put", "id": job, "name": _clean_name(name), "offset": off, "total": size,
                      "data": base64.b64encode(data).decode("ascii")})
                off += len(data)
                if off >= size:
                    break
    post({"op": "start", "id": job, "kind": kind, "params": params}, tries=1)
    say("%s is working on it" % peer["name"])
    deadline = t0 + float(timeout or limit) + 120
    st = {}
    while clock() < deadline:
        st = post({"op": "status", "id": job}, tries=4, wait=30.0)
        if st.get("status") in ("done", "failed"):
            break
        if st.get("note"):
            say("%s: %s" % (peer["name"], st["note"]))
        sleep(POLL_S)
    else:
        try:
            post({"op": "cancel", "id": job}, tries=1)
        except OffloadError:
            pass
        raise OffloadError("%s did not finish in time" % peer["name"])
    if st.get("status") == "failed":
        raise OffloadError("%s: %s" % (peer["name"], st.get("error") or "the job failed"))
    dest = Path(dest)
    files = []
    for f in st.get("files") or []:
        rel = _clean_name(f.get("path"))
        if not rel:
            continue
        local = _free_path(dest / rel)
        local.parent.mkdir(parents=True, exist_ok=True)
        part = local.with_name(local.name + ".part")
        with part.open("wb") as out:
            off = 0
            while True:
                got = post({"op": "get", "id": job, "path": rel, "offset": off, "size": CHUNK}, tries=4, wait=90.0)
                data = base64.b64decode(got.get("data") or "")
                out.write(data)
                off += len(data)
                if got.get("eof") or not data:
                    break
        if f.get("sha256") and _sha(part) != f["sha256"]:
            part.unlink()
            raise OffloadError("%s came back damaged from %s" % (rel, peer["name"]))
        os.replace(part, local)
        files.append(str(local))
    try:
        post({"op": "done", "id": job}, tries=1)
    except OffloadError:
        pass
    return {"ok": True, "peer": peer["name"], "result": st.get("result") or {}, "files": files,
            "rel": [_clean_name(f.get("path")) for f in st.get("files") or []], "seconds": round(clock() - t0, 1)}


def _free_path(p: Path) -> Path:
    if not p.exists():
        return p
    for n in range(2, 1000):
        q = p.with_name("%s_%d%s" % (p.stem, n, p.suffix))
        if not q.exists():
            return q
    return p


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ----------------------------------------------------------------------------- what this machine can take
_SERVES: dict = {}


def serves(env: dict | None = None, clock=time.time) -> tuple:
    """(kinds this machine can run for another one, {kind: why not}) - only what is really installed here. Cached
    30 s (every hello asks)."""
    if env is None and _SERVES and clock() - _SERVES["t"] < 30:
        return _SERVES["v"]
    v = _serves(os.environ if env is None else env)
    if env is None:
        _SERVES.update(t=clock(), v=v)
    return v


def _serves(env: dict) -> tuple:
    if str(env.get("LOKI_OFFLOAD_SERVE", "on")).lower() in ("off", "0", "no"):
        return [], {k: "taking work is off here (LOKI_OFFLOAD_SERVE=off)" for k in KINDS}
    if role(env) == "light" and str(env.get("LOKI_OFFLOAD_SERVE", "")).lower() not in ("on", "1", "yes"):
        return [], {k: "a light machine does not take heavy work" for k in KINDS}
    kinds, why = [], {}
    try:
        import creative  # pylint: disable=import-outside-toplevel
        st = creative.local_image_status()
        if st.get("ready"):
            kinds += ["image", "img2img"]
        else:
            why["image"] = why["img2img"] = st.get("why") or "no image model"
    except Exception as exc:  # noqa: BLE001
        why["image"] = why["img2img"] = str(exc)[:120]
    try:
        import forge3d  # pylint: disable=import-outside-toplevel
        import comfy_autostart  # pylint: disable=import-outside-toplevel
        comfy = (comfy_autostart.comfy_root() / "ComfyUI" / "main.py").is_file()   # started when a job needs it
        if comfy or forge3d.hunyuan_ready() or forge3d.triposr_ready():
            kinds.append("make_3d")
        else:             # the online Space alone: the light machine can call that itself
            why["make_3d"] = "no 3D model of its own here (ComfyUI, Hunyuan3D or TripoSR)"
    except Exception as exc:  # noqa: BLE001
        why["make_3d"] = str(exc)[:120]
    try:
        import blender_link  # pylint: disable=import-outside-toplevel
        if blender_link.find_blender():
            kinds.append("polish")
        else:
            why["polish"] = "Blender is not installed here"
    except Exception as exc:  # noqa: BLE001
        why["polish"] = str(exc)[:120]
    return kinds, why


# ----------------------------------------------------------------------------- the PC's side
def _root(env=None) -> Path:
    return _data(env) / "offload"


def _prune(env=None, clock=time.time) -> None:
    root = _root(env)
    if not root.is_dir():
        return
    for d in root.iterdir():
        try:
            if d.is_dir() and clock() - d.stat().st_mtime > KEEP_S:
                shutil.rmtree(d, ignore_errors=True)
                JOBS.pop(d.name, None)
        except OSError:
            pass


def serve(origin: str, data: dict, env: dict | None = None, runner: Callable | None = None) -> tuple:
    """POST /peer/work from a linked machine: put / start / status / get / cancel / done."""
    op = str(data.get("op") or "")
    job = _clean_id(data.get("id"))
    if not job:
        return 400, {"ok": False, "error": "a job id is needed"}
    base = _root(env) / job
    if op == "put":
        name = _clean_name(data.get("name"))
        if not name or "/" in name:
            return 400, {"ok": False, "error": "a plain file name is needed"}
        try:
            raw = base64.b64decode(str(data.get("data") or ""), validate=True)
        except ValueError:
            return 400, {"ok": False, "error": "the file data is not base64"}
        off, total = int(data.get("offset") or 0), int(data.get("total") or 0)
        if total > MAX_FILE or off + len(raw) > MAX_FILE:
            return 413, {"ok": False, "error": "file too large"}
        if job not in JOBS:
            _prune(env)
        inbox = base / "in"
        inbox.mkdir(parents=True, exist_ok=True)
        used = sum(p.stat().st_size for p in inbox.iterdir() if p.is_file())
        if used + len(raw) > MAX_JOB:
            return 413, {"ok": False, "error": "this job sends too much"}
        path = inbox / name
        if off == 0:
            path.write_bytes(b"")
        elif not path.is_file() or path.stat().st_size != off:
            return 409, {"ok": False, "error": "chunk out of order"}
        with path.open("ab") as fh:
            fh.write(raw)
        with _LOCK:
            JOBS.setdefault(job, {"id": job, "status": "receiving", "origin": origin, "t": time.time()})
        return 200, {"ok": True, "size": path.stat().st_size}
    rec = JOBS.get(job)
    if op == "start":
        kind = str(data.get("kind") or "")
        if kind not in KINDS:
            return 400, {"ok": False, "error": "unknown kind of work: %s" % kind}
        kinds, why = serves(env)
        if kind not in kinds:
            return 409, {"ok": False, "error": "this machine cannot %s right now (%s)" % (LABEL[kind], why.get(kind, "?"))}
        if rec and rec.get("status") not in ("receiving",):
            return 409, {"ok": False, "error": "already started"}
        allowed, _limit = KINDS[kind]
        params = {k: v for k, v in (data.get("params") or {}).items() if k in allowed}
        rec = {"id": job, "kind": kind, "status": "running", "origin": origin, "t": time.time(), "note": ""}
        with _LOCK:
            JOBS[job] = rec
        (base / "in").mkdir(parents=True, exist_ok=True)
        threading.Thread(target=_work, args=(rec, base, params, runner), name="loki-offload-" + job,
                         daemon=True).start()
        print("[loki-offload] %s gave this machine work: %s (%s)" % (origin, LABEL[kind], job), flush=True)
        return 200, {"ok": True, "id": job, "status": "running"}
    if rec is None:
        return 404, {"ok": False, "error": "no such job here (did LOKI restart?)"}
    if op == "status":
        return 200, {"ok": True, **{k: rec.get(k) for k in ("id", "kind", "status", "error", "note", "result", "files")}}
    if op == "get":
        rel = _clean_name(data.get("path"))
        out = (base / "out").resolve()
        path = (out / rel).resolve()
        if out not in path.parents or not path.is_file():
            return 404, {"ok": False, "error": "no such result"}
        off, size = max(0, int(data.get("offset") or 0)), min(CHUNK, max(1, int(data.get("size") or CHUNK)))
        with path.open("rb") as fh:
            fh.seek(off)
            raw = fh.read(size)
        return 200, {"ok": True, "data": base64.b64encode(raw).decode("ascii"),
                     "eof": off + len(raw) >= path.stat().st_size}
    if op in ("cancel", "done"):
        if op == "cancel" and rec.get("status") == "running":
            rec["cancelled"] = True       # the job finishes on its own; its result is thrown away
        if rec.get("status") != "running":
            shutil.rmtree(base, ignore_errors=True)
            JOBS.pop(job, None)
        return 200, {"ok": True}
    return 400, {"ok": False, "error": "unknown op"}


def _work(rec: dict, base: Path, params: dict, runner: Callable | None) -> None:
    out = base / "out"
    out.mkdir(parents=True, exist_ok=True)
    _LOCAL.serving = True
    try:
        inputs = {p.name: p for p in (base / "in").iterdir() if p.is_file()}
        result = (runner or RUNNERS[rec["kind"]])(params, inputs, out, rec)
        files = []
        for p in sorted(out.rglob("*")):
            if p.is_file() and ".meta" not in p.relative_to(out).parts and not p.name.endswith(".part"):
                files.append({"path": p.relative_to(out).as_posix(), "size": p.stat().st_size, "sha256": _sha(p)})
        rec.update(status="done", result=_portable(result, out), files=files)
    except Exception as exc:  # noqa: BLE001 - the other machine shows why
        why = str(exc) if isinstance(exc, (OffloadError, RuntimeError)) else "%s: %s" % (type(exc).__name__, exc)
        rec.update(status="failed", error=why[:600])
    finally:
        _LOCAL.serving = False
        if rec.get("cancelled"):
            shutil.rmtree(base, ignore_errors=True)
            JOBS.pop(rec["id"], None)


def _portable(value, out: Path):
    """A result with this machine's paths turned into paths relative to the job's out folder (or dropped)."""
    root = str(out.resolve())
    if isinstance(value, dict):
        return {k: _portable(v, out) for k, v in value.items() if not callable(v)}
    if isinstance(value, (list, tuple)):
        return [_portable(v, out) for v in value]
    if isinstance(value, str) and (os.sep in value or "/" in value):
        try:
            p = Path(value).resolve()
            if str(p).startswith(root):
                return p.relative_to(out.resolve()).as_posix()
        except (OSError, ValueError):
            pass
        return Path(value).name if Path(value).is_absolute() else value
    if isinstance(value, (int, float, bool)) or value is None or isinstance(value, str):
        return value
    return str(value)


# the runners: (params, inputs {name: path}, out folder, record) -> result dict; files written under `out`
def _run_image(params: dict, inputs: dict, out: Path, rec: dict) -> dict:
    import creative  # pylint: disable=import-outside-toplevel
    refs = [str(p) for n, p in sorted(inputs.items()) if n.startswith("ref")]
    init = next((str(p) for n, p in inputs.items() if n.startswith("init")), None)
    rec["note"] = "making the picture"
    res = creative.run_local_image(str(params.get("prompt") or ""), str(params.get("negative") or ""),
                                   int(params.get("width") or 1024), int(params.get("height") or 1024),
                                   int(params.get("seed") or 0), max(1, min(8, int(params.get("count") or 1))), out,
                                   steps=params.get("steps"), cfg=params.get("cfg"), sampler=params.get("sampler"),
                                   init_image=init, strength=params.get("strength"), edit_refs=refs or None)
    return {k: res.get(k) for k in ("files", "seeds", "backend", "model", "seconds", "reference")}


def _run_img2img(params: dict, inputs: dict, out: Path, rec: dict) -> dict:
    import region_edit  # pylint: disable=import-outside-toplevel
    if "init.png" not in inputs or "mask.png" not in inputs:
        raise OffloadError("an area edit needs init.png and mask.png")
    rec["note"] = "editing the area"
    made = region_edit.local_img2img(inputs["init.png"], inputs["mask.png"], str(params.get("prompt") or ""),
                                     int(params.get("width") or 1024), int(params.get("height") or 1024),
                                     float(params.get("strength") or 0.75), int(params.get("seed") or 1),
                                     out / "out.png")
    return {"file": str(made)}


def _run_make_3d(params: dict, inputs: dict, out: Path, rec: dict) -> dict:
    import forge3d  # pylint: disable=import-outside-toplevel
    src = next(iter(inputs.values()), None)
    if src is None:
        raise OffloadError("a 3D model needs a picture")
    backend = str(params.get("backend") or "auto")
    if backend in ("online", "lift"):
        backend = "auto"
    res = forge3d.make_3d(str(src), out, prompt=str(params.get("prompt") or ""), backend=backend,
                          options=params.get("options") if isinstance(params.get("options"), dict) else None,
                          progress=lambda stage, frac: rec.update(note=stage))
    if not res.get("ok"):
        raise OffloadError(res.get("error") or "no model was made")
    meta = res.get("meta") or {}
    return {"glb": res.get("glb"), "obj": res.get("obj"), "backend": res.get("backend"),
            "meta": {k: meta.get(k) for k in ("backend", "cutout", "fallbacks", "triangles", "vertices", "note",
                                              "licence", "licence_url", "no_training", "options")}}


def _run_polish(params: dict, inputs: dict, out: Path, rec: dict) -> dict:
    import blender_link  # pylint: disable=import-outside-toplevel
    model = next((p for n, p in inputs.items() if not n.endswith(".json")), None)
    if model is None:
        raise OffloadError("polish needs a model file")
    rec["note"] = "cleaning it up in Blender"
    kw = dict(params)
    for k in ("lods", "formats", "edits"):
        if k in kw and kw[k] is not None:
            kw[k] = tuple(kw[k]) if k != "edits" else list(kw[k])
    res = blender_link.polish(model, out, **kw)
    if not res.get("ok"):
        raise OffloadError(res.get("error") or "Blender could not finish it")
    info = next((r.get("result") for r in res.get("results", []) if r.get("type") == "scene_info"), {}) or {}
    return {"files": res.get("files"), "quality": res.get("quality"), "topology": res.get("topology"), "info": info}


RUNNERS = {"image": _run_image, "img2img": _run_img2img, "make_3d": _run_make_3d, "polish": _run_polish}


# ----------------------------------------------------------------------------- the window
def status(env: dict | None = None, call: Callable | None = None) -> dict:
    import peers  # pylint: disable=import-outside-toplevel
    out = {"ok": True, "role": role(env), "mode": mode(env), "me": peers.my_name(env), "machines": [],
           "here": serves(env)[0], "running_for_others": [
               {k: r.get(k) for k in ("id", "kind", "status", "origin", "note")} for r in JOBS.values()
               if r.get("status") == "running"]}
    for peer in peers.peers(env):
        hello, err = hello_of(peer, call)
        out["machines"].append({"name": peer["name"], "online": hello is not None, "error": err,
                                "work": (hello or {}).get("work"), "work_why": (hello or {}).get("work_why"),
                                "gpu": ((hello or {}).get("machine") or {}).get("gpu")})
    out["gives"] = {k: (target(k, env, call) or {}).get("name", "") for k in KINDS}
    return out


def route(state: Any, method: str, path: str, query: dict, body: dict) -> tuple:
    if method == "GET" and path == "/offload/status":
        return 200, status()
    return 404, {"ok": False, "error": "unknown route"}
