"""Loopback API for Forge (the 3D panel, app/ui/forge.js); engine/loki_bridge.py only routes here.
Every route needs the bridge's bearer token (the window fetches models with it, so no open file route).

  GET  /forge/status?id=          a job: {stage, progress, done, result}; without id: backends + jobs
  GET  /forge/list                the models in <workspace>/models/, newest first (+ sidecar: prompt, backend...)
  GET  /forge/file/<name>         one .glb/.obj from models/ (nothing else, no folders, no '..')
  POST /forge/image  {prompt}     text -> picture (the image specialist); a job, result {image: "images/x.png"}
  POST /forge/make   {image | drawing | prompt, backend?}   picture -> 3D; a job, result {name, backend, ...}
                     image = a workspace path ("images/x.png"), drawing = a data:image URL (canvas or a
                     dropped picture), prompt = describe it (picture first, then 3D)
  POST /forge/save?name=x.glb     raw body: a sculpted/exported .glb or .obj saved into models/ (never overwrites)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import forge3d

MAX_BODY = 30_000_000        # a drawing as a data URL, or a sculpted mesh being saved


def owns(route: str) -> bool:
    return route == "/forge" or route.startswith("/forge/")


def workspace(state) -> Path:
    return Path(getattr(state.agent, "WORKSPACE", "."))


def models_dir(state) -> Path:
    return workspace(state) / "models"


def _in_workspace(state, rel: str) -> Path | None:
    ws = workspace(state).resolve()
    try:
        p = (ws / str(rel).replace("\\", "/").lstrip("/")).resolve()
        p.relative_to(ws)
    except (OSError, ValueError):
        return None
    return p if p.is_file() else None


def _image_maker(state):
    agent = state.agent
    maker = getattr(agent, "forge_image_maker", None)
    if callable(maker):
        return maker
    return lambda prompt: forge3d.default_image_maker(prompt, workspace(state))


def _rel(state, path: str) -> str:
    try:
        return Path(path).resolve().relative_to(workspace(state).resolve()).as_posix()
    except (OSError, ValueError):
        return ""


def handle_get(state, path: str) -> tuple:
    """(status, json) or (status, bytes, content_type) for a model file."""
    route = urlparse(path).path
    q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
    if route == "/forge/status":
        if q.get("id"):
            found = forge3d.job(q["id"])
            return (200, {"ok": True, **found}) if found else (404, {"ok": False, "error": "no such job"})
        return 200, {"ok": True, "backends": forge3d.status(), "order": forge3d.plan("auto"), "jobs": forge3d.jobs()}
    if route == "/forge/list":
        return 200, {"ok": True, "items": forge3d.list_models(models_dir(state)), "folder": "models"}
    if route.startswith("/forge/file/"):
        name = unquote(route[len("/forge/file/"):])
        found = forge3d.model_file(models_dir(state), name)
        if found is None:
            return 404, {"ok": False, "error": "Not found."}
        kind = "model/gltf-binary" if found.suffix.lower() == ".glb" else "text/plain; charset=utf-8"
        return 200, found.read_bytes(), kind
    return 404, {"ok": False, "error": "Unknown endpoint."}


def handle_post(state, path: str, body: bytes, thread: bool = True) -> tuple:
    route = urlparse(path).path
    q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
    if route == "/forge/save":
        return save(state, q.get("name", ""), body)
    try:
        data = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        return 400, {"ok": False, "error": "Invalid JSON body."}
    if not isinstance(data, dict):
        return 400, {"ok": False, "error": "JSON body must be an object."}
    if route == "/forge/image":
        prompt = str(data.get("prompt") or "").strip()[:800]
        if not prompt:
            return 400, {"ok": False, "error": "describe what to make"}
        maker = _image_maker(state)

        def work(progress):
            progress("making the picture", 0.1)
            try:
                file = maker(prompt)
            except forge3d.ForgeError as exc:
                return {"ok": False, "error": str(exc)}
            rel = _rel(state, file)
            return {"ok": bool(rel), "image": rel, "error": "" if rel else "the picture is outside the workspace"}
        return 200, forge3d.start_job(work, kind="image", label=prompt, thread=thread)
    if route == "/forge/make":
        backend = str(data.get("backend") or "auto")
        if backend not in forge3d.BACKENDS:
            return 400, {"ok": False, "error": "unknown backend"}
        prompt = str(data.get("prompt") or "").strip()[:800]
        source = ""
        if data.get("drawing"):
            source = str(data["drawing"])
            if not source.startswith("data:image/"):
                return 400, {"ok": False, "error": "a drawing must be a data:image URL"}
        elif data.get("image"):
            found = _in_workspace(state, str(data["image"]))
            if found is None:
                return 400, {"ok": False, "error": "no such picture in the workspace"}
            source = str(found)
        elif not prompt:
            return 400, {"ok": False, "error": "give a drawing, a picture or a description"}
        maker = _image_maker(state)
        out_dir = models_dir(state)

        def work(progress):
            res = forge3d.make_3d(source, out_dir, prompt, backend, image_maker=maker, progress=progress)
            if res.get("ok") and res.get("image"):
                res["image"] = _rel(state, res["image"])
            return {k: v for k, v in res.items() if k not in ("glb", "obj")} | (
                {"obj": Path(res["obj"]).name if res.get("obj") else ""} if res.get("ok") else {})
        return 200, forge3d.start_job(work, kind="model", label=prompt or "drawing", thread=thread)
    return 404, {"ok": False, "error": "Unknown endpoint."}


def save(state, name: str, body: bytes) -> tuple:
    """A file the window exported (sculpted) -> models/<name>, never overwriting."""
    name = re.sub(r"[^A-Za-z0-9._ -]+", "-", Path(str(name or "")).name).strip(" .")[:80]
    suffix = Path(name).suffix.lower()
    if suffix not in forge3d.MODEL_EXTS or not Path(name).stem:
        return 400, {"ok": False, "error": "only .glb or .obj"}
    if not body:
        return 400, {"ok": False, "error": "empty file"}
    if suffix == ".glb":
        if body[:4] != b"glTF":
            return 400, {"ok": False, "error": "not a .glb"}
    folder = models_dir(state)
    folder.mkdir(parents=True, exist_ok=True)
    target, n = folder / name, 2
    while target.exists():
        target = folder / ("%s-%d%s" % (Path(name).stem, n, suffix))
        n += 1
    target.write_bytes(body)
    if suffix == ".glb":
        try:
            forge3d.read_glb(target)
        except (forge3d.ForgeError, ValueError):
            target.unlink(missing_ok=True)
            return 400, {"ok": False, "error": "not a valid .glb"}
    return 200, {"ok": True, "name": target.name, "path": "models/" + target.name}
