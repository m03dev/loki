"""LOKI's Blender core - loaded by the loader (loki_blender_startup.py) inside a Blender window, or by run_job.py in a
background Blender (no window). Hot-reloaded: writing this file is enough to update a running Blender.

Jobs: a JSON command or list of commands, from <LOKI Projects>/Home/blender/inbox/<name>.json (window), or a file
given to run_job.py (background). Answers: blender/outbox/<name>.json. Commands (all run in the right context, in
the job's OWN scene - the scene the owner is working in is never touched):
    {"type": "python", "params": {"code": "...", "scene": "Campfire"}}   bpy, bmesh, scene, OUT (output folder) and
         log() are ready; `result = {...}` in the code is returned; print() output is returned too
    {"type": "render", "params": {"scene": .., "path": ".../x.png", "width": 1280, "height": 720, "samples": 32}}
    {"type": "export", "params": {"scene": .., "path": ".../x.glb|.gltf|.fbx|.obj|.blend"}}
    {"type": "scene_info", "params": {"scene": ..}}          {"type": "ping"}
    "execute_code" (the MCP add-on's own name for "python") is run here too; any other type goes to the MCP add-on.

Also, in a window: a watchdog keeps the MCP for Blender add-on registered and its socket (9876) up - whatever turned
it off (seen on the PC 2026-10-26: unregistered between two jobs, cause unknown) - unless blender/mcp_off exists; and
the add-on's execute_code runs in a window + 3D-view context, so MCP clients can use bpy.ops too.
"""
import contextlib
import io
import json
import os
import time
import traceback
from pathlib import Path

import bpy

VERSION = "2026-10-26.3"
WATCH_S = 5.0
_S = {"log": print, "root": None, "last_watch": 0.0, "patched": None, "jobs": 0, "last_job": "", "mcp": False}


# ----------------------------------------------------------------------------- lifecycle (called by the loader)
def start(log, root):
    _S.update(log=log, root=None if bpy.app.background else Path(root))
    if not bpy.app.background:                           # a background run has no inbox: it runs one job file
        for d in ("inbox", "outbox", "done"):
            (Path(root) / d).mkdir(parents=True, exist_ok=True)
    if not bpy.app.background:
        _patch_addon()
        _watch(force=True)
    log("core", VERSION, "started", "(background)" if bpy.app.background else "(window)")


def stop():
    _unpatch_addon()


def status():
    return {"core_version": VERSION, "mcp_socket": _S["mcp"], "jobs_done": _S["jobs"], "last_job": _S["last_job"],
            "port": 9876}


def tick():
    if not bpy.app.background:
        _watch()
    _inbox_once()


# ----------------------------------------------------------------------------- the MCP add-on: keep it on
def _addon_ok():
    return hasattr(bpy.types.Scene, "blendermcp_use_polyhaven") and hasattr(bpy.types.Scene, "blendermcp_port")


def _watch(force=False):
    if not force and time.time() - _S["last_watch"] < WATCH_S:
        return
    _S["last_watch"] = time.time()
    root = _S["root"]
    if root is not None and (root / "mcp_off").exists():
        _S["mcp"] = False
        return
    log = _S["log"]
    if not _addon_ok():
        errs = []
        try:
            import addon_utils  # pylint: disable=import-outside-toplevel
            addon_utils.enable("blender_mcp", default_set=True, persistent=True,
                               handle_error=lambda exc: errs.append(repr(exc)))
        except Exception:  # noqa: BLE001
            errs.append(traceback.format_exc()[-400:])
        if not _addon_ok():
            try:
                import blender_mcp  # pylint: disable=import-outside-toplevel
                blender_mcp.register()
            except Exception:  # noqa: BLE001
                errs.append(traceback.format_exc()[-400:])
        log("watchdog: MCP add-on was off ->", "on" if _addon_ok() else "STILL OFF", *errs)
        _patch_addon()
    srv = getattr(bpy.types, "blendermcp_server", None)
    if _addon_ok() and (srv is None or not getattr(srv, "running", False)):
        try:
            import blender_mcp  # pylint: disable=import-outside-toplevel
            srv = srv or blender_mcp.BlenderMCPServer(port=9876)
            bpy.types.blendermcp_server = srv
            srv.start()
            log("watchdog: MCP socket 9876", "up" if getattr(srv, "running", False) else "DID NOT START")
        except Exception:  # noqa: BLE001
            log("watchdog: MCP socket failed:", traceback.format_exc()[-400:])
    _S["mcp"] = bool(srv is not None and getattr(srv, "running", False))


def _patch_addon():
    """The add-on's execute_code, in a window + 3D-view context (MCP commands run from a timer, where
    bpy.context.object and most operators are missing - seen on the PC 2026-10-26)."""
    try:
        import blender_mcp  # pylint: disable=import-outside-toplevel
    except Exception:  # noqa: BLE001
        return
    cls = blender_mcp.BlenderMCPServer
    if getattr(cls.execute_code, "_loki", False):
        return
    orig = cls.execute_code

    def execute_code(self, code):
        with job_context(None):
            return orig(self, code)
    execute_code._loki = True
    _S["patched"] = (cls, orig)
    cls.execute_code = execute_code


def _unpatch_addon():
    if _S["patched"]:
        cls, orig = _S["patched"]
        cls.execute_code = orig
        _S["patched"] = None


# ----------------------------------------------------------------------------- context
def _scene(name, new_ok=True):
    if not name:
        return bpy.context.scene
    sc = bpy.data.scenes.get(name)
    if sc is None and new_ok:
        sc = bpy.data.scenes.new(name)
    return sc


@contextlib.contextmanager
def job_context(scene_name):
    """Run with a window, screen, a 3D view area/region and the job's scene active, then put the owner's scene back.
    In a background Blender (no window) the job's scene becomes the context scene directly."""
    wm = bpy.context.window_manager
    win = wm.windows[0] if wm and len(wm.windows) else None
    if win is None:
        sc = _scene(scene_name) if scene_name else bpy.context.scene
        if scene_name and bpy.context.scene != sc:
            with bpy.context.temp_override(scene=sc, view_layer=sc.view_layers[0]):
                yield sc
        else:
            yield sc
        return
    prev = win.scene
    sc = _scene(scene_name) if scene_name else prev
    if sc != prev:
        win.scene = sc
    try:
        area = next((a for a in win.screen.areas if a.type == "VIEW_3D"), None) or win.screen.areas[0]
        region = next((r for r in area.regions if r.type == "WINDOW"), area.regions[0])
        with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region, scene=sc,
                                       view_layer=sc.view_layers[0]):
            yield sc
    finally:
        if win.scene != prev:
            win.scene = prev


# ----------------------------------------------------------------------------- commands
def _out_dir():
    root = _S["root"] or (Path.home() / "LOKI Projects" / "Home" / "blender")
    return root.parent


def cmd_python(p):
    code = p.get("code") or ""
    buf = io.StringIO()
    with job_context(p.get("scene")) as sc:
        ns = {"bpy": bpy, "scene": sc, "OUT": str(_out_dir()), "log": _S["log"], "__name__": "loki_job"}
        try:
            import bmesh  # pylint: disable=import-outside-toplevel
            ns["bmesh"] = bmesh
        except ImportError:
            pass
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<loki job>", "exec"), ns)  # noqa: S102 - the owner's own inbox / LOKI only
    res = ns.get("result")
    try:
        json.dumps(res)
    except (TypeError, ValueError):
        res = repr(res)
    return {"stdout": buf.getvalue()[-8000:], "result": res, "scene": sc.name}


def _set_engine(sc, want=None):
    order = ([want] if want else []) + ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES", "BLENDER_WORKBENCH"]
    for eng in order:
        try:
            sc.render.engine = eng
            return eng
        except TypeError:
            continue
    return sc.render.engine


def cmd_render(p):
    path = str(p.get("path") or (_out_dir() / "renders" / ("blender_%s.png" % time.strftime("%Y%m%d-%H%M%S"))))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    errors = []
    with job_context(p.get("scene")) as sc:
        if sc.camera is None:
            raise RuntimeError("scene %r has no camera" % sc.name)
        sc.render.resolution_x = int(p.get("width") or 1280)
        sc.render.resolution_y = int(p.get("height") or 720)
        sc.render.resolution_percentage = 100
        sc.render.image_settings.file_format = "PNG"
        sc.render.filepath = path
        tried = []
        for eng in ([p["engine"]] if p.get("engine") else []) + ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES",
                                                               "BLENDER_WORKBENCH"]:
            if eng in tried:
                continue
            tried.append(eng)
            try:
                sc.render.engine = eng
            except TypeError:
                continue
            if eng == "CYCLES":
                sc.cycles.samples = int(p.get("samples") or 32)
                sc.cycles.device = "GPU" if p.get("gpu", True) else "CPU"
            try:
                bpy.ops.render.render(write_still=True, scene=sc.name)
            except Exception:  # noqa: BLE001
                errors.append("%s: %s" % (eng, traceback.format_exc()[-300:]))
                continue
            if Path(path).is_file():
                return {"path": path, "engine": eng, "errors": errors}
            errors.append("%s: no file written" % eng)
    raise RuntimeError("render failed: " + " | ".join(errors))


def cmd_export(p):
    path = str(p.get("path") or "")
    if not path:
        raise ValueError("export needs a path (.glb .gltf .fbx .obj .blend)")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ext = Path(path).suffix.lower()
    with job_context(p.get("scene")) as sc:
        if ext == ".blend":
            bpy.data.libraries.write(path, {sc}, fake_user=True)   # only this scene and what it uses
        elif ext in (".glb", ".gltf"):
            kw = dict(filepath=path, export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE")
            try:
                bpy.ops.export_scene.gltf(use_active_scene=True, **kw)
            except TypeError:
                bpy.ops.export_scene.gltf(**kw)
        elif ext == ".fbx":
            bpy.ops.export_scene.fbx(filepath=path)
        elif ext == ".obj":
            bpy.ops.wm.obj_export(filepath=path)
        else:
            raise ValueError("unknown export type %s" % ext)
    if not Path(path).is_file():
        raise RuntimeError("export wrote nothing: %s" % path)
    return {"path": path, "bytes": Path(path).stat().st_size}


def cmd_scene_info(p):
    sc = _scene(p.get("scene"), new_ok=False) or bpy.context.scene
    objs = list(sc.objects)
    tris = sum(len(poly.vertices) - 2 for o in objs if o.type == "MESH" for poly in o.data.polygons)
    return {"scene": sc.name, "objects": len(objs), "meshes": sum(o.type == "MESH" for o in objs), "triangles": tris,
            "camera": sc.camera.name if sc.camera else None, "names": [o.name for o in objs][:60]}


COMMANDS = {"python": cmd_python, "execute_code": cmd_python, "render": cmd_render, "export": cmd_export,
            "scene_info": cmd_scene_info, "ping": lambda p: {"pong": True, "core": VERSION}}


def run_commands(commands):
    results = []
    for c in commands:
        t0 = time.time()
        kind = (c or {}).get("type")
        try:
            fn = COMMANDS.get(kind)
            if fn is not None:
                res = {"status": "success", "result": fn((c or {}).get("params") or {})}
            else:                                          # the add-on's other tools (Poly Haven, screenshots ...)
                if not bpy.app.background:
                    _watch(force=True)
                import blender_mcp  # pylint: disable=import-outside-toplevel
                srv = getattr(bpy.types, "blendermcp_server", None) or blender_mcp.BlenderMCPServer(port=0)
                res = srv.execute_command(c)
        except Exception as exc:  # noqa: BLE001 - the answer says exactly what broke
            res = {"status": "error", "message": "%s: %s" % (type(exc).__name__, exc),
                   "traceback": traceback.format_exc()[-3000:]}
        res["type"], res["seconds"] = kind, round(time.time() - t0, 2)
        results.append(res)
        if res.get("status") != "success":
            break
    return results


def run_job_file(path):
    path = Path(path)
    if path.suffix == ".py":
        commands = [{"type": "python", "params": {"code": path.read_text(encoding="utf-8")}}]
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        commands = data if isinstance(data, list) else data.get("commands", [data]) if isinstance(data, dict) else []
    results = run_commands(commands)
    return {"job": path.name, "ok": bool(results) and all(r.get("status") == "success" for r in results),
            "results": results, "blender": bpy.app.version_string, "core": VERSION,
            "mode": "background" if bpy.app.background else "window", "at": time.time()}


def _inbox_once():
    root = _S["root"]
    if root is None:
        return
    inbox, outbox, done = root / "inbox", root / "outbox", root / "done"
    try:
        jobs = sorted(p for p in inbox.iterdir() if p.suffix in (".json", ".py") and p.is_file())
    except OSError:
        return
    for job in jobs[:1]:                                   # one per tick: the window stays responsive
        try:
            if time.time() - job.stat().st_mtime < 1.0:    # still being written
                return
        except OSError:
            return
        _S["log"]("job", job.name)
        try:
            answer = run_job_file(job)
        except Exception:  # noqa: BLE001
            answer = {"job": job.name, "ok": False, "error": traceback.format_exc()[-2000:]}
        _S["jobs"] += 1
        _S["last_job"] = "%s %s" % (job.name, "ok" if answer.get("ok") else "FAILED")
        _S["log"]("job", _S["last_job"])
        outbox.mkdir(parents=True, exist_ok=True)
        done.mkdir(parents=True, exist_ok=True)
        tmp = outbox / (job.stem + ".json.part")
        tmp.write_text(json.dumps(answer, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, outbox / (job.stem + ".json"))     # readers never see half an answer
        try:
            os.replace(job, done / job.name)
        except OSError:
            try:
                job.unlink()
            except OSError:
                pass
