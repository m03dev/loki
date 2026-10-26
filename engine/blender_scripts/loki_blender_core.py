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
  the toolkit (AI mesh -> usable asset): import (.glb .gltf .obj .fbx .stl .ply .usd*), cleanup, normalize (size),
    decimate (ratio | target), remesh (voxel), uv (smart project), shade (smooth + sharp angle | flat), stage
    (camera + 3 lights + ground + world; studio | night | outdoor), turntable (frames -> folder), lods (ratios ->
    <stem>_lodN.glb), clear (a LOKI scene); render takes view_transform ("Standard" for saturated emission)
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

VERSION = "2026-10-26.7"
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
        if p.get("view_transform"):                      # "Standard" keeps bright emission saturated (AgX desaturates)
            try:
                sc.view_settings.view_transform = p["view_transform"]
            except TypeError:
                pass
        if p.get("exposure") is not None:
            sc.view_settings.exposure = float(p["exposure"])
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


# ----------------------------------------------------------------------------- the toolkit: AI mesh -> usable asset
# Context-free where Blender allows it (bmesh, evaluated meshes, mesh.transform); edit-mode operators (UV unwrap) run
# with the object active inside job_context. Every command works on `objects` (names) or every mesh in the scene.
import math as _math


def _meshes(sc, names=None):
    objs = [o for o in sc.objects if o.type == "MESH"]
    if names:
        want = set(names)
        objs = [o for o in objs if o.name in want]
    return objs


def _apply_modifier(o, mod):
    """Bake one modifier into the mesh without operators (works from timers and in the background)."""
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    new = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
    old = o.data
    o.modifiers.remove(mod)
    o.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)


def _tris(objs):
    return sum(len(p.vertices) - 2 for o in objs for p in o.data.polygons)


def cmd_import(p):
    path = str(p.get("path") or "")
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    ext = Path(path).suffix.lower()
    with job_context(p.get("scene")) as sc:
        before = set(o.name for o in sc.objects)
        if ext in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=path)
        elif ext == ".obj":
            bpy.ops.wm.obj_import(filepath=path)
        elif ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=path)
        elif ext == ".stl":
            bpy.ops.wm.stl_import(filepath=path)
        elif ext == ".ply":
            bpy.ops.wm.ply_import(filepath=path)
        elif ext in (".usd", ".usda", ".usdc", ".usdz"):
            bpy.ops.wm.usd_import(filepath=path)
        else:
            raise ValueError("cannot import %s" % ext)
        new = [o for o in sc.objects if o.name not in before]
        return {"scene": sc.name, "imported": [o.name for o in new],
                "meshes": sum(o.type == "MESH" for o in new), "triangles": _tris([o for o in new if o.type == "MESH"])}


def cmd_cleanup(p):
    """Merge duplicate vertices, drop loose bits and degenerate faces, make normals point out."""
    import bmesh  # pylint: disable=import-outside-toplevel
    dist = float(p.get("merge_distance") or 0.0001)
    out = {}
    with job_context(p.get("scene")) as sc:
        for o in _meshes(sc, p.get("objects")):
            bm = bmesh.new()
            bm.from_mesh(o.data)
            v0 = len(bm.verts)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
            bmesh.ops.dissolve_degenerate(bm, dist=dist, edges=bm.edges)
            loose = [v for v in bm.verts if not v.link_edges]
            if loose:
                bmesh.ops.delete(bm, geom=loose, context="VERTS")
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            bm.to_mesh(o.data)
            o.data.update()
            out[o.name] = {"verts_before": v0, "verts_after": len(bm.verts)}
            bm.free()
    return out


def cmd_normalize(p):
    """Bake transforms, then scale the whole set to `size` (longest side, metres), centred, standing on the ground."""
    from mathutils import Matrix, Vector  # pylint: disable=import-outside-toplevel
    size = float(p.get("size") or 2.0)
    with job_context(p.get("scene")) as sc:
        objs = _meshes(sc, p.get("objects"))
        if not objs:
            raise RuntimeError("no meshes in %s" % sc.name)
        for o in objs:
            mw = o.matrix_world.copy()
            o.parent = None
            if o.data.users > 1:
                o.data = o.data.copy()
            o.data.transform(mw)
            o.matrix_world = Matrix.Identity(4)
        pts = [v.co for o in objs for v in o.data.vertices]
        lo = Vector((min(c.x for c in pts), min(c.y for c in pts), min(c.z for c in pts)))
        hi = Vector((max(c.x for c in pts), max(c.y for c in pts), max(c.z for c in pts)))
        dims = hi - lo
        k = size / max(dims.x, dims.y, dims.z, 1e-9)
        mv = Matrix.Diagonal((k, k, k, 1.0)) @ Matrix.Translation(Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z)))
        for o in objs:
            o.data.transform(mv)
            o.data.update()
        for o in [x for x in sc.objects if x.type == "EMPTY" and not x.children]:
            bpy.data.objects.remove(o, do_unlink=True)    # importers' leftover empty parents
        return {"size": size, "scale": k, "dimensions": [round(d * k, 4) for d in dims]}


def cmd_decimate(p):
    """Fewer triangles: `ratio` (0-1) or `target` triangles for the whole set."""
    with job_context(p.get("scene")) as sc:
        objs = _meshes(sc, p.get("objects"))
        before = _tris(objs)
        ratio = float(p["ratio"]) if p.get("ratio") else min(1.0, float(p.get("target") or 20000) / max(before, 1))
        if ratio < 0.999:
            for o in objs:
                m = o.modifiers.new("LOKI decimate", "DECIMATE")
                m.ratio = ratio
                m.use_collapse_triangulate = True
                _apply_modifier(o, m)
        return {"triangles_before": before, "triangles_after": _tris(objs), "ratio": round(ratio, 4)}


def cmd_remesh(p):
    """Voxel remesh: one watertight, even surface (AI meshes with holes and slivers). voxel = size in metres."""
    with job_context(p.get("scene")) as sc:
        objs = _meshes(sc, p.get("objects"))
        if p.get("mode") == "quad":                        # QuadriFlow (built into Blender): clean quads
            for o in objs:
                with _with_active(sc, o):
                    bpy.ops.object.quadriflow_remesh(target_faces=int(p.get("faces") or 5000), use_mesh_symmetry=False,
                                                     use_preserve_sharp=True, use_preserve_boundary=True)
            return {"triangles": _tris(objs), "mode": "quad"}
        for o in objs:
            m = o.modifiers.new("LOKI remesh", "REMESH")
            m.mode = "VOXEL"
            m.voxel_size = float(p.get("voxel") or 0.01)
            m.use_smooth_shade = True
            _apply_modifier(o, m)
        return {"triangles": _tris(objs)}


def _with_active(sc, o):
    sc.view_layers[0].objects.active = o
    for x in sc.objects:
        try:
            x.select_set(x == o)
        except RuntimeError:
            pass
    return bpy.context.temp_override(active_object=o, object=o, selected_objects=[o], selected_editable_objects=[o],
                                     edit_object=o)


def cmd_uv(p):
    """Smart UV project. mode: "missing" (default - only meshes with no UVs: an AI model's own UVs carry its texture;
    found on the PC 2026-10-26: re-unwrapping scrambled a textured model), "new" (a separate LOKI_UV layer, the
    original stays the one used for rendering - for baking), "replace" (overwrite)."""
    angle = _math.radians(float(p.get("angle") or 66))
    margin = float(p.get("margin") or 0.02)
    mode = str(p.get("mode") or "missing")
    done, kept = [], []
    with job_context(p.get("scene")) as sc:
        for o in _meshes(sc, p.get("objects")):
            layers = o.data.uv_layers
            if mode == "missing" and len(layers):
                kept.append(o.name)
                continue
            render_layer = next((l.name for l in layers if l.active_render), None)
            if mode == "new" or not len(layers):
                lay = layers.get("LOKI_UV") or layers.new(name="LOKI_UV")
                layers.active = lay
            with _with_active(sc, o):
                bpy.ops.object.mode_set(mode="EDIT")
                try:
                    bpy.ops.mesh.select_all(action="SELECT")
                    bpy.ops.uv.smart_project(angle_limit=angle, island_margin=margin)
                finally:
                    bpy.ops.object.mode_set(mode="OBJECT")
            if mode == "new" and render_layer:
                layers[render_layer].active_render = True
            done.append(o.name)
    return {"unwrapped": done, "kept_own_uvs": kept, "mode": mode}


def cmd_shade(p):
    """Smooth shading with sharp edges kept above `angle` degrees (or flat=True for the low-poly look)."""
    angle = _math.radians(float(p.get("angle") or 35))
    with job_context(p.get("scene")) as sc:
        objs = _meshes(sc, p.get("objects"))
        for o in objs:
            me = o.data
            if p.get("flat"):
                for poly in me.polygons:
                    poly.use_smooth = False
                continue
            if hasattr(me, "shade_smooth"):
                me.shade_smooth()
            else:
                for poly in me.polygons:
                    poly.use_smooth = True
            if hasattr(me, "set_sharp_from_angle"):
                me.set_sharp_from_angle(angle=angle)
        return {"objects": len(objs), "flat": bool(p.get("flat"))}


def _bounds(objs):
    from mathutils import Vector  # pylint: disable=import-outside-toplevel
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(v.x for v in pts), min(v.y for v in pts), min(v.z for v in pts)))
    hi = Vector((max(v.x for v in pts), max(v.y for v in pts), max(v.z for v in pts)))
    return lo, hi


def cmd_stage(p):
    """A camera framing the meshes, three lights, a ground and a world: ready to render. style: studio | night |
    outdoor. Replaces this scene's previous LOKI stage."""
    from mathutils import Vector  # pylint: disable=import-outside-toplevel
    import bmesh  # pylint: disable=import-outside-toplevel
    style = str(p.get("style") or "studio")
    with job_context(p.get("scene")) as sc:
        for o in [x for x in sc.objects if x.get("loki_stage")]:
            bpy.data.objects.remove(o, do_unlink=True)
        objs = _meshes(sc, p.get("objects"))
        if not objs:
            raise RuntimeError("nothing to stage in %s" % sc.name)
        lo, hi = _bounds(objs)
        centre, size = (lo + hi) / 2, max((hi - lo).length, 1e-3)

        def add(name, data):
            o = bpy.data.objects.new(name, data)
            sc.collection.objects.link(o)
            o["loki_stage"] = True
            return o
        cam = add("LOKI Camera", bpy.data.cameras.new("LOKI Camera"))
        cam.data.lens = float(p.get("lens") or 50)
        direction = Vector(p.get("direction") or (1.0, -1.25, 0.65)).normalized()
        fov = cam.data.angle
        dist = (size / 2) / _math.tan(fov / 2) * float(p.get("margin") or 1.15)
        cam.location = centre + direction * dist
        cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam.data.clip_end = dist * 10
        sc.camera = cam
        tone = {"studio": ((1, 1, 1), 1000, (0.05, 0.05, 0.055)), "night": ((0.7, 0.8, 1.0), 300, (0.01, 0.015, 0.03)),
                "outdoor": ((1.0, 0.95, 0.85), 800, (0.4, 0.55, 0.8))}.get(style, ((1, 1, 1), 1000, (0.05, 0.05, 0.055)))
        # key / fill / rim, energy scaled by distance squared (an area light falls off with it); the key no longer
        # blows out the ground (PC render 2026-10-26: floor white, front dark)
        for name, off, k in (("Key", (1.0, -1.1, 1.2), 0.30), ("Fill", (-1.3, -0.9, 0.5), 0.22), ("Rim", (-0.3, 1.5, 1.2), 0.30)):
            ld = bpy.data.lights.new("LOKI " + name, "AREA")
            ld.energy = tone[1] * k * (size * 1.2 * Vector(off).length / 2) ** 2
            ld.color = tone[0]
            ld.size = size * 0.8
            L = add("LOKI " + name, ld)
            L.location = centre + Vector(off) * size * 1.2
            L.rotation_euler = (centre - L.location).to_track_quat("-Z", "Y").to_euler()
        if p.get("ground", True):
            me = bpy.data.meshes.new("LOKI Ground")
            bm = bmesh.new()
            bmesh.ops.create_circle(bm, cap_ends=True, segments=64, radius=size * 4)
            bm.to_mesh(me)
            bm.free()
            g = add("LOKI Ground", me)
            g.location = (centre.x, centre.y, lo.z)
            gm = bpy.data.materials.get("LOKI Ground") or bpy.data.materials.new("LOKI Ground")
            gm.diffuse_color = (*([0.025] * 3), 1)
            try:
                gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.025, 0.025, 0.028, 1)
                gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
            except (AttributeError, KeyError):
                pass
            me.materials.append(gm)
        w = bpy.data.worlds.get("LOKI " + style) or bpy.data.worlds.new("LOKI " + style)
        try:
            w.node_tree.nodes["Background"].inputs[0].default_value = (*tone[2], 1)
        except (AttributeError, KeyError):
            w.color = tone[2]
        sc.world = w
        for vt in ([p["view_transform"]] if p.get("view_transform") else []) + ["Khronos PBR Neutral", "AgX", "Standard"]:
            try:
                sc.view_settings.view_transform = vt
                break
            except TypeError:
                continue
        return {"camera": cam.name, "distance": round(dist, 3), "style": style,
                "view_transform": sc.view_settings.view_transform}


def cmd_turntable(p):
    """`frames` stills circling the meshes (the camera orbits; nothing is keyframed), into `folder` as
    frame_0001.png ... - blender_link.py turns them into an mp4 with ffmpeg."""
    from mathutils import Matrix, Vector  # pylint: disable=import-outside-toplevel
    folder = Path(str(p.get("folder") or (_out_dir() / "renders" / ("turntable_%s" % time.strftime("%Y%m%d-%H%M%S")))))
    folder.mkdir(parents=True, exist_ok=True)
    frames = max(4, min(240, int(p.get("frames") or 36)))
    with job_context(p.get("scene")) as sc:
        cam = sc.camera
        if cam is None:
            raise RuntimeError("stage the scene first (no camera)")
        objs = _meshes(sc, p.get("objects"))
        lo, hi = _bounds(objs)
        centre = (lo + hi) / 2
        start = cam.matrix_world.copy()
        sc.render.resolution_x = int(p.get("width") or 960)
        sc.render.resolution_y = int(p.get("height") or 540)
        sc.render.image_settings.file_format = "PNG"
        _set_engine(sc, p.get("engine"))
        try:
            for i in range(frames):
                rot = Matrix.Translation(centre) @ Matrix.Rotation(_math.tau * i / frames, 4, "Z") @ Matrix.Translation(-centre)
                cam.matrix_world = rot @ start
                sc.render.filepath = str(folder / ("frame_%04d.png" % (i + 1)))
                bpy.ops.render.render(write_still=True, scene=sc.name)
        finally:
            cam.matrix_world = start
    made = sorted(folder.glob("frame_*.png"))
    return {"folder": str(folder), "frames": len(made)}


def cmd_lods(p):
    """Export level-of-detail copies: `ratios` like [1, 0.5, 0.25] -> <stem>_lod0.glb, _lod1.glb ..."""
    stem = str(p.get("stem") or "")
    if not stem:
        raise ValueError("lods needs a stem (path without extension)")
    ratios = [float(r) for r in (p.get("ratios") or [1.0, 0.5, 0.25])]
    out = []
    with job_context(p.get("scene")) as sc:
        src = _meshes(sc, p.get("objects"))
        for i, r in enumerate(ratios):
            tmp = bpy.data.scenes.new("%s LOD%d" % (sc.name, i))
            copies = []
            for o in src:
                c = o.copy()
                c.data = o.data.copy()
                tmp.collection.objects.link(c)
                copies.append(c)
            try:
                if r < 0.999:
                    for c in copies:
                        m = c.modifiers.new("LOKI lod", "DECIMATE")
                        m.ratio = r
                        _apply_modifier(c, m)
                path = "%s_lod%d.glb" % (stem, i)
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                with job_context(tmp.name):
                    try:
                        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_active_scene=True)
                    except TypeError:
                        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB")
                out.append({"path": path, "ratio": r, "triangles": _tris(copies)})
            finally:
                for c in copies:
                    data = c.data
                    bpy.data.objects.remove(c, do_unlink=True)
                    if data.users == 0:
                        bpy.data.meshes.remove(data)
                bpy.data.scenes.remove(tmp)
    return {"lods": out}


def cmd_clear(p):
    """Remove one of LOKI's own scenes (name must start with 'LOKI'); the owner's scenes are never touched."""
    name = str(p.get("scene") or "")
    if not name.startswith("LOKI"):
        raise ValueError("only LOKI's own scenes (named 'LOKI ...') can be cleared")
    sc = bpy.data.scenes.get(name)
    if sc is None:
        return {"cleared": False}
    for o in list(sc.objects):
        if len(o.users_scene) <= 1:
            bpy.data.objects.remove(o, do_unlink=True)
    if len(bpy.data.scenes) > 1:
        wm = bpy.context.window_manager
        for win in (wm.windows if wm else []):
            if win.scene == sc:
                win.scene = next(s for s in bpy.data.scenes if s != sc)
        bpy.data.scenes.remove(sc)
    return {"cleared": True}


COMMANDS.update({"import": cmd_import, "cleanup": cmd_cleanup, "normalize": cmd_normalize, "decimate": cmd_decimate,
                 "remesh": cmd_remesh, "uv": cmd_uv, "shade": cmd_shade, "stage": cmd_stage, "turntable": cmd_turntable,
                 "lods": cmd_lods, "clear": cmd_clear})


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
                params = (c or {}).get("params") or {}
                with job_context(params.get("scene")) as sc:  # downloads land in the job's scene, not the owner's
                    if str(kind).endswith("polyhaven_asset") or "polyhaven" in str(kind) or kind == "set_texture":
                        sc.blendermcp_use_polyhaven = True       # Poly Haven: CC0, free
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
