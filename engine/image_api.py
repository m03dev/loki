"""The picture viewer's routes (app/ui/image_viewer.js): settings, remake with settings, thumbs up / down.

    GET  /image/settings              the settings list (engine/image_settings.py) + this computer's image backends
    GET  /image/info?path=            a picture's sidecar (prompt, seed, size, model, settings) + its rating
    POST /image/remake {path, settings}   a new picture from this one's prompt with these settings (a job)
    GET  /image/remake?job=           that job: running / done {files} / failed {error}
    POST /image/rate {path, rating, reasons[], note}   thumbs up (+1) / down (-1) / clear (0) - engine/image_feedback.py
    GET  /image/feedback              what the owner liked and disliked, and the reasons (engine/image_feedback.py)
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

ROUTES = {("GET", "/image/settings"), ("GET", "/image/info"), ("POST", "/image/remake"), ("GET", "/image/remake"),
          ("POST", "/image/rate"), ("GET", "/image/feedback")}
JOBS: dict = {}


def _ws(state) -> Path:
    return Path(getattr(getattr(state, "agent", None), "WORKSPACE", ".") or ".")


def _rel(ws: Path, path: str) -> str:
    rel = str(path or "").replace("\\", "/").strip("/")
    if rel.startswith("creations/"):
        rel = rel[len("creations/"):]
    p = (ws / rel).resolve()
    return rel if ws.resolve() in p.parents and p.is_file() else ""


def info(ws: Path, rel: str) -> dict:
    import creations  # pylint: disable=import-outside-toplevel
    import image_feedback  # pylint: disable=import-outside-toplevel
    meta = creations.read_meta(ws, rel)
    size = None
    try:
        from PIL import Image  # pylint: disable=import-outside-toplevel
        with Image.open(ws / rel) as im:
            size = list(im.size)
    except Exception:  # noqa: BLE001
        pass
    row = image_feedback.ratings(ws).get(rel) or {}
    return {"ok": True, "path": rel, "size": size, "meta": meta, "rating": int(row.get("rating") or 0),
            "reasons": row.get("reasons") or [], "note": row.get("note") or ""}


def remake(ws: Path, rel: str, settings: dict, maker=None, thread: bool = True) -> dict:
    """A new picture from `rel`'s own prompt with `settings` (engine/image_settings.normalize). from_picture: this
    picture is the starting point (image-to-image / a reference edit). Saved beside the others, parent = rel."""
    import creations  # pylint: disable=import-outside-toplevel
    import image_settings  # pylint: disable=import-outside-toplevel
    meta = creations.read_meta(ws, rel)
    prompt = str((settings or {}).get("prompt") or meta.get("idea") or meta.get("prompt") or
                 creations.title_of(Path(rel).name)).strip()
    job, notes = image_settings.normalize(settings or {}, str((settings or {}).get("backend") or "auto"))
    args = {"prompt": prompt, "folder": rel.split("/")[0] if rel.split("/")[0] in ("images", "sprites", "turnarounds")
            else "images"}
    args.update({k: v for k, v in job.items() if k not in ("backend",)})
    if job.get("backend") and job["backend"] != "auto":
        args["backend"] = job["backend"]
    if (settings or {}).get("from_picture"):
        args["reference"] = [rel]
    if maker is None:
        import make_mcp  # pylint: disable=import-outside-toplevel

        def maker(a, cwd):
            import os  # pylint: disable=import-outside-toplevel
            old = os.environ.get("LOKI_IMAGE_BACKEND")
            if a.get("backend"):
                os.environ["LOKI_IMAGE_BACKEND"] = a["backend"]
            try:
                return make_mcp.make_image(a, cwd)
            finally:
                if a.get("backend"):
                    if old is None:
                        os.environ.pop("LOKI_IMAGE_BACKEND", None)
                    else:
                        os.environ["LOKI_IMAGE_BACKEND"] = old
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"status": "running", "t": time.time(), "notes": notes, "prompt": prompt}

    def work():
        try:
            res = maker(dict(args), ws) or {}
            if not res.get("ok"):
                JOBS[jid].update(status="failed", error=str(res.get("error") or "not made")[:400])
                return
            for f in res.get("files") or []:
                creations.write_meta(ws, str(f).replace("\\", "/"), parent=rel, settings=job)
            JOBS[jid].update(status="done", files=res.get("files") or [], backend=res.get("backend", ""),
                             model=res.get("model", ""), seed=res.get("seed"))
        except Exception as exc:  # noqa: BLE001
            JOBS[jid].update(status="failed", error="%s: %s" % (type(exc).__name__, str(exc)[:300]))

    if thread:
        threading.Thread(target=work, daemon=True, name="loki-remake").start()
    else:
        work()
    return {"ok": True, "job": jid, "notes": notes, "settings": job}


def route(state, method: str, route_: str, q: dict, data: dict) -> tuple:
    ws = _ws(state)
    if (method, route_) == ("GET", "/image/settings"):
        import image_settings  # pylint: disable=import-outside-toplevel
        out = {"ok": True, "settings": image_settings.schema(), "aspects": list(image_settings.ASPECTS)}
        try:
            import sys  # pylint: disable=import-outside-toplevel
            sys.path.insert(0, str(Path(__file__).resolve().parent / "runners"))
            import imagegen  # pylint: disable=import-outside-toplevel
            out["backends"] = imagegen.plan_order("auto")
        except Exception as exc:  # noqa: BLE001
            out["backends"] = {"order": [], "error": str(exc)[:200]}
        return 200, out
    if (method, route_) == ("GET", "/image/feedback"):
        import image_feedback  # pylint: disable=import-outside-toplevel
        return 200, {"ok": True, "preferences": image_feedback.preferences(ws), "reasons": image_feedback.REASONS}
    if (method, route_) == ("GET", "/image/remake"):
        j = JOBS.get(str(q.get("job") or ""))
        return (200, dict(j, ok=True)) if j else (404, {"ok": False, "error": "no such job"})
    rel = _rel(ws, (data or {}).get("path") if method == "POST" else q.get("path"))
    if not rel:
        return 404, {"ok": False, "error": "no such picture in the workspace"}
    if (method, route_) == ("GET", "/image/info"):
        return 200, info(ws, rel)
    if (method, route_) == ("POST", "/image/rate"):
        import image_feedback  # pylint: disable=import-outside-toplevel
        out = image_feedback.rate(ws, rel, int(data.get("rating") or 0), data.get("reasons") or [], data.get("note") or "")
        return (200 if out.get("ok") else 400), out
    if (method, route_) == ("POST", "/image/remake"):
        return 200, remake(ws, rel, data.get("settings") or {})
    return 404, {"ok": False, "error": "unknown route"}
