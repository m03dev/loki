"""Loopback API for Forge (the 3D panel, app/ui/forge.js); engine/loki_bridge.py only routes here.
Every route needs the bridge's bearer token (the window fetches models with it, so no open file route).

  GET  /forge/status?id=          a job: {stage, progress, done, result}; without id: backends + jobs
  GET  /forge/list                the models in <workspace>/models/, newest first (+ sidecar: prompt, backend...)
  GET  /forge/file/<name>         one .glb/.obj from models/ (nothing else, no folders, no '..')
  POST /forge/image  {prompt, options?}  text -> picture (the image specialist); a job, result {image: "images/x.png"}
  POST /forge/make   {image | drawing | prompt, backend?, options?}   picture -> 3D; a job, result {name, backend, ...}
                     options = the Output panel's values (forge3d.OPTIONS: resolution, keep, thickness, smooth,
                     texture_size, image_size, foreground, cutout, symmetry, seed); each backend reads its own
                     image = a workspace path ("images/x.png"), drawing = a data:image URL (canvas or a
                     dropped picture), prompt = describe it (picture first, then 3D)
  POST /forge/save?name=x.glb     raw body: a sculpted/exported .glb/.obj, a material .png or a .ptex project,
                                  saved into models/ (never overwrites)
  GET  /forge/mm                  Material Maker on this computer: {installed, path, download}
  POST /forge/mm/open {name}      open models/<name> (.ptex / .glb / .obj) in Material Maker
  GET  /forge/creature            the anyCreature engine here: {ok, engine, outline, node}
  GET  /forge/creature/view?name=&view=   one of the four silhouette PNGs (front | side | top | hero)
  POST /forge/creature {spec, name?}  an anyCreature ACS spec -> a creature .glb in models/ (a job),
       or {preset, size?, smooth?, shape? {legs, body, girth, neck, head, snout, ears, tail, legthick},
           coat?, colors? {id: #hex}} - the form's controls (engine/anycreature.schema())
                                  result {name, bytes, views: {front, side, top, hero}} (engine/anycreature.py)
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
    return lambda prompt, options=None: forge3d.default_image_maker(prompt, workspace(state), options)


def _judge(state):
    """E19: the judge the build hands its model to, or None when judging is off / no vision model.
    LOKI_FORGE_JUDGE=0 turns it off; off by default only when LOKI_LOCAL_ONLY is set with no local
    vision model, since the judge is what tells which backend works best on this machine."""
    import os  # pylint: disable=import-outside-toplevel
    if str(os.environ.get("LOKI_FORGE_JUDGE", "1")).strip() == "0":
        return None
    maker = getattr(state.agent, "forge_judge", None)
    if callable(maker):
        return maker
    try:
        import forge_judge  # pylint: disable=import-outside-toplevel
    except Exception:  # noqa: BLE001 - judging is a bonus, never a reason a build fails to start
        return None
    if not forge_judge.vision_ready():   # no vision model here: never make a build wait to find out
        return None
    return forge_judge.judge_one


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
    if route == "/forge/mm":
        import forge_mm  # pylint: disable=import-outside-toplevel
        return 200, {"ok": True, **forge_mm.status()}
    if route == "/forge/list":
        return 200, {"ok": True, "items": forge3d.list_models(models_dir(state)), "folder": "models"}
    if route == "/forge/creature":
        import anycreature  # pylint: disable=import-outside-toplevel
        return 200, {"ok": True, **anycreature.available(), **anycreature.schema()}
    if route == "/forge/creature/view":
        import anycreature  # pylint: disable=import-outside-toplevel
        view = q.get("view", "")
        if view not in anycreature.VIEWS:
            return 400, {"ok": False, "error": "view must be one of: " + ", ".join(anycreature.VIEWS)}
        stem = Path(re.sub(r"[^A-Za-z0-9._-]", "", q.get("name", ""))).stem
        png = models_dir(state) / (stem + ".views") / ("sil_%s.png" % view)
        if not stem or not png.is_file():
            return 404, {"ok": False, "error": "no such view"}
        return 200, png.read_bytes(), "image/png"
    if route.startswith("/forge/file/"):
        name = unquote(route[len("/forge/file/"):])
        found = forge3d.model_file(models_dir(state), name)
        if found is None:
            return 404, {"ok": False, "error": "Not found."}
        kind = {".glb": "model/gltf-binary", ".png": "image/png", ".ptex": "application/json"}.get(
            found.suffix.lower(), "text/plain; charset=utf-8")
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
    options = forge3d.clean_options(data.get("options")) if isinstance(data.get("options"), dict) else None
    if route == "/forge/mm/open":
        import forge_mm  # pylint: disable=import-outside-toplevel
        found = forge3d.model_file(models_dir(state), str(data.get("name") or ""))
        if found is None:
            return 404, {"ok": False, "error": "no such file in models/"}
        return 200, forge_mm.open_in_mm(found)
    if route == "/forge/image":
        prompt = str(data.get("prompt") or "").strip()[:800]
        if not prompt:
            return 400, {"ok": False, "error": "describe what to make"}
        maker = _image_maker(state)

        def work(progress):
            progress("making the picture", 0.1)
            try:
                file = forge3d.call_image_maker(maker, prompt, options)
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
        judge = _judge(state)

        def work(progress):
            # E19: judge the model against the source picture and keep the score; the judge renders
            # the four angles itself when the model is not a creature (which has its own views).
            res = forge3d.make_3d(source, out_dir, prompt, backend, image_maker=maker, progress=progress,
                                  options=options, judge=judge)
            if res.get("ok") and res.get("image"):
                res["image"] = _rel(state, res["image"])
            out = {k: v for k, v in res.items() if k not in ("glb", "obj")} | (
                {"obj": Path(res["obj"]).name if res.get("obj") else ""} if res.get("ok") else {})
            v = out.get("judge")                       # the paths inside the verdict are local: hide them
            if isinstance(v, dict):
                out["judge"] = {k: val for k, val in v.items() if k != "views"}
            return out
        return 200, forge3d.start_job(work, kind="model", label=prompt or "drawing", thread=thread)
    if route == "/forge/creature":
        import anycreature  # pylint: disable=import-outside-toplevel
        spec = data.get("spec")
        controls = {k: data[k] for k in ("size", "smooth", "colors", "shape", "coat") if k in data}
        if data.get("preset"):
            controls["preset"] = data["preset"]
        if not controls and (not isinstance(spec, (dict, str)) or not spec):
            return 400, {"ok": False, "error": "pick a starter (preset), or give a spec"}
        name = str(data.get("name") or "creature")
        out_dir = models_dir(state)

        def work(progress):
            progress("shaping the creature", 0.15)
            try:
                res = (anycreature.make_from_controls(controls, out_dir, name, progress) if controls
                       else anycreature.make(spec, out_dir, name))
            except anycreature.AnyCreatureError as exc:
                return {"ok": False, "error": str(exc)}
            progress("drawing the front / side / top views", 0.9)
            return {"ok": True, "name": res["name"], "bytes": res.get("bytes", 0),
                    "size": res.get("size"), "asked_size": res.get("asked_size"), "size_moved": res.get("size_moved", False),
                    "shape": res.get("shape"), "eased": res.get("eased", False), "ease": res.get("ease", 0),
                    "fixes": res.get("fixes", 0), "views": {v: "creature/view?name=%s&view=%s" % (res["stem"], v)
                                                            for v in res.get("views", {})}}
        return 200, forge3d.start_job(work, kind="creature", label=name, thread=thread)
    return 404, {"ok": False, "error": "Unknown endpoint."}


def save(state, name: str, body: bytes) -> tuple:
    """A file the window exported (sculpted mesh, material map, .ptex) -> models/<name>, never overwriting."""
    name = re.sub(r"[^A-Za-z0-9._ -]+", "-", Path(str(name or "")).name).strip(" .")[:80]
    suffix = Path(name).suffix.lower()
    if suffix not in forge3d.SAVE_EXTS or not Path(name).stem:
        return 400, {"ok": False, "error": "only .glb, .obj, .png or .ptex"}
    if not body:
        return 400, {"ok": False, "error": "empty file"}
    if suffix == ".glb" and body[:4] != b"glTF":
        return 400, {"ok": False, "error": "not a .glb"}
    if suffix == ".png" and body[:8] != b"\x89PNG\r\n\x1a\n":
        return 400, {"ok": False, "error": "not a .png"}
    if suffix == ".ptex":
        try:
            if not isinstance(json.loads(body.decode("utf-8")), dict):
                raise ValueError
        except (UnicodeDecodeError, ValueError):
            return 400, {"ok": False, "error": "not a .ptex project"}
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
