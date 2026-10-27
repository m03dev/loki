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
  remix (tint / lowpoly / taper / bend / twist / displace / bevel / scale / material): free assets imported from
    assets/ are marked and export / lods REFUSE them until remix changed them
    "execute_code" (the MCP add-on's own name for "python") is run here too; any other type goes to the MCP add-on.

Also, in a window: a watchdog keeps the MCP for Blender add-on registered and its socket (9876) up - whatever turned
it off (seen on the PC 2026-10-26: unregistered between two jobs, cause unknown) - unless blender/mcp_off exists; and
the add-on's execute_code runs in a window + 3D-view context, so MCP clients can use bpy.ops too.
"""
import contextlib
import io
import json
import os
import sys
import time
import traceback
from pathlib import Path

import bpy

VERSION = "2026-10-26.16"
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


def _asset_objects(sc):
    """What a model file should hold: everything but the stage (LOKI Camera / Key / Fill / Rim / Ground), the bake's
    originals (__high), retopo's helpers (__vox) and wireframe preview copies (__wire). Found on the PC 2026-10-26:
    every exported .glb / .fbx carried the studio's ground plane."""
    return [o for o in sc.objects if not o.name.startswith("LOKI ")
            and not o.name.endswith(("__high", "__vox", "__wire")) and o.type in ("MESH", "ARMATURE", "EMPTY", "CURVE")]


def _op(fn, **kw):
    """Call an operator, dropping keywords this Blender does not know (they differ between versions) instead of
    falling back to bare defaults (found on the PC: FBX has no use_active_scene, so every FBX lost its embedded
    textures and settings)."""
    import re  # pylint: disable=import-outside-toplevel
    for _ in range(len(kw) + 1):
        try:
            return fn(**kw)
        except TypeError as exc:
            m = re.search(r'keyword "(\w+)" unrecognized', str(exc))
            if not m or m.group(1) not in kw:
                raise
            kw.pop(m.group(1))
    return fn(**kw)


def cmd_export(p):
    path = str(p.get("path") or "")
    if not path:
        raise ValueError("export needs a path (.glb .gltf .fbx .obj .blend)")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ext = Path(path).suffix.lower()
    with job_context(p.get("scene")) as sc:
        for h in [o for o in sc.objects if o.name.endswith("__high")]:   # repair's leftovers never ship
            bpy.data.objects.remove(h, do_unlink=True)
        raw = _unmodified_free([o for o in sc.objects if o.type == "MESH"])
        if raw:
            raise RuntimeError("these are free assets used as they are - change them first (remix): %s" % ", ".join(raw[:8]))
        if ext == ".blend":
            bpy.data.libraries.write(path, {sc}, fake_user=True)   # only this scene and what it uses
        else:
            ship = _asset_objects(sc)                       # the model only: never the stage's ground, lights, camera
            if not ship:
                raise RuntimeError("nothing to export in %s" % sc.name)
            vl = sc.view_layers[0]
            for o in sc.objects:
                try:
                    o.select_set(o in ship)
                except RuntimeError:
                    pass
            vl.objects.active = ship[0]
            with bpy.context.temp_override(selected_objects=ship, active_object=ship[0], object=ship[0]):
                if ext in (".glb", ".gltf"):
                    _op(bpy.ops.export_scene.gltf, filepath=path, use_selection=True, use_active_scene=True,
                        export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE", export_yup=True, export_apply=True)
                elif ext == ".fbx":                         # game-engine friendly: metres, Y up, textures inside
                    _op(bpy.ops.export_scene.fbx, filepath=path, use_selection=True,
                        object_types={"MESH", "ARMATURE", "EMPTY"}, apply_unit_scale=True,
                        apply_scale_options="FBX_SCALE_ALL", path_mode="COPY", embed_textures=True,
                        mesh_smooth_type="FACE", add_leaf_bones=False, axis_forward="-Z", axis_up="Y",
                        use_mesh_modifiers=True)
                elif ext == ".obj":
                    _op(bpy.ops.wm.obj_export, filepath=path, export_selected_objects=True)
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
    """Bake one modifier into the mesh without operators (works from timers and in the background). Evaluated in the
    depsgraph of the scene the object is in - the context's one does not see a temporary scene (the PC 2026-10-26:
    every LOD came out identical to the full model)."""
    sc = o.users_scene[0] if o.users_scene else None
    dg = sc.view_layers[0].depsgraph if sc is not None else None
    if dg is None and sc is not None:                  # a scene made this job has no depsgraph until updated
        sc.view_layers[0].update()
        dg = sc.view_layers[0].depsgraph
    if dg is None:
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
        src = _free_asset_source(path)
        for o in new:                                     # a free asset is raw material: it must be changed first
            if src:
                o["loki_free_asset"] = src
        return {"scene": sc.name, "imported": [o.name for o in new], "free_asset": src or None,
                "meshes": sum(o.type == "MESH" for o in new), "triangles": _tris([o for o in new if o.type == "MESH"])}


def _free_asset_source(path):
    """'polyhaven/cannon_01' when the file is a downloaded free asset (engine/free_assets.py: assets/<source>/<id>/,
    loki_asset.json beside it), else ''."""
    p = Path(path).resolve()
    for d in [p.parent] + list(p.parents)[:3]:
        side = d / "loki_asset.json"
        if side.is_file():
            try:
                info = json.loads(side.read_text(encoding="utf-8"))
                return "%s/%s" % (info.get("source", "?"), info.get("id", d.name))
            except ValueError:
                return d.name
    parts = [x.lower() for x in p.parts]
    if "assets" in parts and parts.index("assets") + 2 < len(parts):
        i = parts.index("assets")
        return "%s/%s" % (p.parts[i + 1], p.parts[i + 2])
    return ""


def _unmodified_free(objs):
    return [o.name for o in objs if o.get("loki_free_asset") and not o.get("loki_modified")]


def cmd_remix(p):
    """Change free-asset parts so they become LOKI's own (owner 2026-10-26: "they can download them but must edit them
    never just use free assets as is"). `edits`: a list of
      {"op": "tint", "color": [r,g,b], "amount": 0.6}        recolour every material (mix toward the colour)
      {"op": "lowpoly", "ratio": 0.25}                         stylise: fewer faces, flat shading
      {"op": "taper" | "bend" | "twist", "factor": 0.4}        reshape (Simple Deform, baked)
      {"op": "displace", "strength": 0.05, "scale": 0.4}       roughen the surface with noise (baked)
      {"op": "bevel", "width": 0.01}                           soften every edge
      {"op": "scale", "xyz": [1.2, 0.8, 1.0]}                  re-proportion
      {"op": "material", "path": ".../Color.jpg"}              a new base-colour texture (e.g. an ambientCG one)
    Each changed object records what was done (custom property loki_modified); export refuses unchanged free assets."""
    edits = list(p.get("edits") or [])
    if not edits:
        raise ValueError("remix needs edits - free assets must be changed, never used as they are")
    import bmesh  # pylint: disable=import-outside-toplevel
    done = {}
    with job_context(p.get("scene")) as sc:
        objs = _meshes(sc, p.get("objects"))
        shape_ops = {"taper", "bend", "twist", "displace", "scale"}
        if len(objs) > 1 and any(str(e.get("op")) in shape_ops for e in edits):
            # one mesh first: a reshape works over each object's own bounds, so separate parts would drift apart
            # (PC 2026-10-26: a tapered Poly Haven cannon lost its wheels)
            keep = objs[0]
            for o in objs:
                o.select_set(True)
            with _with_active(sc, keep):
                for o in objs:
                    o.select_set(True)
                with bpy.context.temp_override(active_object=keep, object=keep, selected_objects=objs,
                                               selected_editable_objects=objs):
                    bpy.ops.object.join()
            objs = _meshes(sc, [keep.name])        # the joined mesh keeps the first part's free-asset mark
        for e in edits:
            op = str(e.get("op") or "")
            for o in objs:
                if op == "tint":
                    col = tuple(float(c) for c in (e.get("color") or [0.6, 0.3, 0.2]))[:3]
                    amt = float(e.get("amount") or 0.6)
                    for slot in o.material_slots:
                        m = slot.material
                        if m is None:
                            continue
                        m = m.copy() if m.users > 1 else m
                        slot.material = m
                        m.diffuse_color = tuple(a * (1 - amt) + b * amt for a, b in zip(m.diffuse_color[:3], col)) + (1,)
                        nt = getattr(m, "node_tree", None)
                        bsdf = nt.nodes.get("Principled BSDF") if nt else None
                        if bsdf is not None:
                            inp = bsdf.inputs["Base Color"]
                            mix = nt.nodes.new("ShaderNodeMix")
                            mix.data_type = "RGBA"
                            mix.blend_type = "MULTIPLY" if e.get("multiply") else "MIX"
                            mix.inputs["Factor"].default_value = amt
                            mix.inputs[7].default_value = (*col, 1)            # B (colour)
                            if inp.links:
                                nt.links.new(inp.links[0].from_socket, mix.inputs[6])   # A (colour)
                            else:
                                mix.inputs[6].default_value = inp.default_value
                            nt.links.new(mix.outputs[2], inp)
                elif op in ("taper", "bend", "twist"):
                    m = o.modifiers.new("LOKI " + op, "SIMPLE_DEFORM")
                    m.deform_method = op.upper()
                    m.factor = float(e.get("factor") or 0.3)
                    m.deform_axis = str(e.get("axis") or "Z").upper()
                    _apply_modifier(o, m)
                elif op == "displace":
                    tex = bpy.data.textures.new("LOKI noise", "CLOUDS")
                    tex.noise_scale = float(e.get("scale") or 0.4)
                    m = o.modifiers.new("LOKI displace", "DISPLACE")
                    m.texture, m.strength = tex, float(e.get("strength") or 0.04)
                    _apply_modifier(o, m)
                elif op == "bevel":
                    m = o.modifiers.new("LOKI bevel", "BEVEL")
                    m.width, m.segments = float(e.get("width") or 0.01), int(e.get("segments") or 2)
                    m.limit_method = "ANGLE"
                    _apply_modifier(o, m)
                elif op == "lowpoly":
                    m = o.modifiers.new("LOKI lowpoly", "DECIMATE")
                    m.ratio = float(e.get("ratio") or 0.25)
                    _apply_modifier(o, m)
                    for poly in o.data.polygons:
                        poly.use_smooth = False
                elif op == "scale":
                    from mathutils import Matrix  # pylint: disable=import-outside-toplevel
                    x, y, z = [float(v) for v in (e.get("xyz") or [1.1, 1.1, 1.1])][:3]
                    o.data.transform(Matrix.Diagonal((x, y, z, 1.0)))
                    o.data.update()
                elif op == "material":
                    img_path = str(e.get("path") or "")
                    if not Path(img_path).is_file():
                        raise FileNotFoundError(img_path)
                    m = bpy.data.materials.new("LOKI remix")
                    try:
                        m.use_nodes = True
                    except AttributeError:
                        pass
                    nt = m.node_tree
                    tex = nt.nodes.new("ShaderNodeTexImage")
                    tex.image = bpy.data.images.load(img_path, check_existing=True)
                    nt.links.new(tex.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
                    o.data.materials.clear()
                    o.data.materials.append(m)
                else:
                    raise ValueError("unknown remix op %r" % op)
                rec = list(o.get("loki_modified") or [])
                rec.append(op)
                o["loki_modified"] = rec
                done.setdefault(o.name, []).append(op)
    return {"changed": done}


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
        src = _meshes(sc, p.get("objects")) if p.get("objects") else [o for o in _asset_objects(sc) if o.type == "MESH"]
        raw = _unmodified_free(src)
        if raw:
            raise RuntimeError("these are free assets used as they are - change them first (remix): %s" % ", ".join(raw[:8]))
        for i, r in enumerate(ratios):
            tmp = bpy.data.scenes.new("%s LOD%d" % (sc.name, i))
            copies = []
            for o in src:
                c = o.copy()
                c.data = o.data.copy()
                sc.collection.objects.link(c)              # decimated in the job's scene (it has a depsgraph -
                copies.append(c)                           # a new scene has none: the PC, 2026-10-26)
            try:
                if r < 0.999:
                    for c in copies:
                        m = c.modifiers.new("LOKI lod", "DECIMATE")
                        m.ratio = r
                        _apply_modifier(c, m)
                for c in copies:
                    sc.collection.objects.unlink(c)
                    tmp.collection.objects.link(c)
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


# ----------------------------------------------------------------------------- repair: AI mesh garbage -> clean surface
# Owner 2026-10-26: "some of the models come out like garbage clean it up do research". Recipe from that research:
# floaters (small loose pieces) out, small holes filled, broken / open / paper-thin surfaces rebuilt watertight by a
# voxel remesh (the original kept as "<name>__high" so `bake` moves its texture onto the new surface), marching-cube
# bumps relaxed (Laplacian, volume kept), optional upright + symmetry, and a quality score so garbage is named.
def _components(bm):
    seen, comps = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, comp = [f], []
        seen.add(f.index)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for e in cur.edges:
                for nf in e.link_faces:
                    if nf.index not in seen:
                        seen.add(nf.index)
                        stack.append(nf)
        comps.append(comp)
    return comps


def _quality(bm):
    """Numbers that tell a clean model from garbage (research thresholds, unverified starting points)."""
    import bmesh  # pylint: disable=import-outside-toplevel
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    edges = len(bm.edges) or 1
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    nonmanifold = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
    thin = 0
    faces = list(bm.faces)
    step = max(1, len(faces) // 20000)
    sample = faces[::step]
    noise = []
    for f in sample:
        if min((l.calc_angle() for l in f.loops), default=1.0) < 0.0873:      # < 5 degrees
            thin += 1
        nb = [lf for e in f.edges for lf in e.link_faces if lf is not f]
        if nb:
            avg = sum((x.normal for x in nb), f.normal * 0)
            if avg.length > 1e-9:
                noise.append(f.normal.angle(avg.normalized(), 0.0))
    comps = _components(bm)
    areas = sorted((sum(x.calc_area() for x in c) for c in comps), reverse=True)
    total = sum(areas) or 1.0
    import math
    return {"faces": len(bm.faces), "components": len(comps), "largest_share": round(areas[0] / total, 3) if areas else 0,
            "boundary_edges": boundary, "nonmanifold_edges": nonmanifold, "open_ratio": round((boundary + nonmanifold) / edges, 4),
            "thin_ratio": round(thin / max(1, len(sample)), 3),
            "noise_deg": round(math.degrees(sum(noise) / len(noise)), 2) if noise else 0.0}


def _verdict(q):
    bad, warn = [], []
    if q["faces"] < 500:
        bad.append("too few faces (%d)" % q["faces"])
    if q["largest_share"] < 0.85:
        warn.append("broken into pieces (largest part %d%%)" % int(q["largest_share"] * 100))
    if q["open_ratio"] > 0.01:
        warn.append("open / broken surface (%.1f%% edges)" % (q["open_ratio"] * 100))
    if q["thin_ratio"] > 0.2:
        warn.append("many sliver triangles (%d%%)" % int(q["thin_ratio"] * 100))
    if q["noise_deg"] > 12:
        warn.append("bumpy surface (%.0f deg)" % q["noise_deg"])
    return {"verdict": "garbage" if bad or len(warn) >= 3 else "rough" if warn else "clean", "problems": bad + warn}


def _has_texture(o):
    for slot in o.material_slots:
        m = slot.material
        if m and m.node_tree and any(n.type in ("TEX_IMAGE", "ATTRIBUTE", "VERTEX_COLOR") for n in m.node_tree.nodes):
            return True
    return bool(getattr(o.data, "color_attributes", None) and len(o.data.color_attributes))


def cmd_repair(p):
    """keep: drop loose pieces under this share of the area (0.02); holes: fill holes up to this many sides (64);
    remesh: "auto" (rebuild when the surface is open/broken), true, false; voxel: divisions of the size (200);
    smooth: Laplacian iterations, "auto" = only when bumpy (default); upright: rotate the tallest side to up;
    symmetric: mirror the left half onto the right (creatures seen from the front)."""
    import bmesh  # pylint: disable=import-outside-toplevel
    from mathutils import Matrix  # pylint: disable=import-outside-toplevel
    keep = float(p.get("keep", 0.02))
    sides = int(p.get("holes", 64))
    remesh = p.get("remesh", "auto")
    out = {}
    with job_context(p.get("scene")) as sc:
        for o in _meshes(sc, p.get("objects")):
            if o.name.endswith("__high"):
                continue
            bm = bmesh.new()
            bm.from_mesh(o.data)
            before = _quality(bm)
            comps = _components(bm)
            areas = [sum(f.calc_area() for f in c) for c in comps]
            total = sum(areas) or 1.0
            drop = [f for c, a in zip(comps, areas) if a < keep * total for f in c]
            if drop and len(drop) < len(bm.faces):
                bmesh.ops.delete(bm, geom=drop, context="FACES")
                loose = [v for v in bm.verts if not v.link_faces]
                if loose:
                    bmesh.ops.delete(bm, geom=loose, context="VERTS")
            boundary = [e for e in bm.edges if e.is_boundary]
            if boundary and sides:
                bmesh.ops.holes_fill(bm, edges=boundary, sides=sides)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            mid = _quality(bm)
            bm.to_mesh(o.data)
            bm.free()
            o.data.update()
            rebuilt = False
            if remesh is True or (remesh == "auto" and (mid["open_ratio"] > 0.005 or mid["thin_ratio"] > 0.25)):
                dims = o.dimensions
                size = max(max(dims), 1e-6) / float(p.get("voxel") or 200)
                if _has_texture(o):                       # keep the original: `bake` moves its colours across
                    high = o.copy()
                    high.data = o.data.copy()
                    high.name = o.name + "__high"
                    sc.collection.objects.link(high)
                    high.hide_render = True
                m = o.modifiers.new("LOKI rebuild", "REMESH")
                m.mode, m.voxel_size, m.use_smooth_shade = "VOXEL", size, True
                _apply_modifier(o, m)
                rebuilt = True
            it = p.get("smooth", "auto")
            if it == "auto":
                it = 4 if mid["noise_deg"] > 12 or rebuilt else 0
            if int(it):
                m = o.modifiers.new("LOKI smooth", "LAPLACIANSMOOTH")
                m.iterations, m.lambda_factor, m.use_volume_preserve, m.use_normalized = int(it), 0.5, True, True
                _apply_modifier(o, m)
            if p.get("upright"):
                d = o.dimensions
                if d.x > d.z * 1.3 and d.x >= d.y:
                    o.data.transform(Matrix.Rotation(1.5708, 4, "Y"))
                elif d.y > d.z * 1.3 and d.y > d.x:
                    o.data.transform(Matrix.Rotation(-1.5708, 4, "X"))
            if p.get("symmetric"):
                bm = bmesh.new()
                bm.from_mesh(o.data)
                bmesh.ops.symmetrize(bm, input=bm.verts[:] + bm.edges[:] + bm.faces[:], direction="X", dist=1e-4)
                bm.to_mesh(o.data)
                bm.free()
            bm = bmesh.new()
            bm.from_mesh(o.data)
            after = _quality(bm)
            bm.free()
            out[o.name] = {"before": before, "after": after, "removed_faces": len(drop), "rebuilt": rebuilt,
                           "smoothed": int(it), **_verdict(after), "verdict_before": _verdict(before)["verdict"]}
        # floaters that are whole OBJECTS (an AI model's stray bit exported as its own mesh - the Mac's dragon had a cyan
        # blob beside it): drop any mesh under `keep` of the biggest one's surface
        objs = [o for o in _meshes(sc, p.get("objects")) if not o.name.endswith("__high")]
        if len(objs) > 1:
            def area(o):
                return sum(poly.area for poly in o.data.polygons) * max(o.scale) ** 2
            areas = {o.name: area(o) for o in objs}
            top = max(areas.values()) or 1.0
            for o in objs:
                if areas[o.name] < keep * top:
                    data = o.data
                    bpy.data.objects.remove(o, do_unlink=True)
                    if data.users == 0:
                        bpy.data.meshes.remove(data)
                    out.pop(o.name, None)
    worst = max((v["verdict"] for v in out.values() if isinstance(v, dict)), key=["clean", "rough", "garbage"].index,
                default="clean")
    return {"objects": out, "verdict": worst}


def _principled(mat):
    if not (mat and mat.use_nodes and mat.node_tree):
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def _surface_values(o):
    """Metallic / roughness of the original's first Principled BSDF when they are plain values (a texture there is not
    carried over: 0 / 0.7)."""
    for slot in o.material_slots:
        b = _principled(slot.material)
        if b is not None:
            m, r = b.inputs["Metallic"], b.inputs["Roughness"]
            return (0.0 if m.is_linked else float(m.default_value)), (0.7 if r.is_linked else float(r.default_value))
    return 0.0, 0.7


@contextlib.contextmanager
def _emit_base_colour(o):
    """Bake the original's BASE COLOUR, whatever its metallic: a DIFFUSE colour bake is black for metallic surfaces
    (found on the PC 2026-10-26 - glTF's default metallic is 1.0, so a Forge character baked to pure black). Each
    material's Base Color (texture or value) is wired to an Emission shader for the bake, then put back."""
    undo = []
    try:
        for slot in o.material_slots:
            mat = slot.material
            b = _principled(mat)
            if b is None or any(u[0] is mat for u in undo):
                continue
            nt = mat.node_tree
            outp = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output),
                        next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None))
            if outp is None:
                continue
            surf = outp.inputs["Surface"]
            old = surf.links[0].from_socket if surf.links else None
            em = nt.nodes.new("ShaderNodeEmission")
            em.inputs["Strength"].default_value = 1.0
            base = b.inputs["Base Color"]
            if base.links:
                nt.links.new(base.links[0].from_socket, em.inputs["Color"])
            else:
                em.inputs["Color"].default_value = base.default_value
            nt.links.new(em.outputs["Emission"], surf)
            undo.append((mat, em, surf, old))
        yield
    finally:
        for mat, em, surf, old in undo:
            nt = mat.node_tree
            nt.nodes.remove(em)
            if old is not None:
                nt.links.new(old, surf)


def cmd_bake(p):
    """Move the original's colours onto a rebuilt surface: for each "<name>__high" left by repair, UV the new mesh,
    bake DIFFUSE colour (Cycles, selected -> active) into a `size` texture, give it a clean material, drop the
    original. Headless-safe."""
    import math  # pylint: disable=import-outside-toplevel
    size = int(p.get("size") or 2048)
    folder = Path(str(p.get("folder") or (_out_dir() / "models" / "textures")))
    folder.mkdir(parents=True, exist_ok=True)
    done = []
    with job_context(p.get("scene")) as sc:
        prev_engine = sc.render.engine
        sc.render.engine = "CYCLES"
        sc.cycles.samples = int(p.get("samples") or 8)
        try:
            sc.cycles.device = "GPU"
        except TypeError:
            pass
        try:
            for high in [o for o in sc.objects if o.name.endswith("__high")]:
                low = sc.objects.get(high.name[:-6])
                if low is None:
                    bpy.data.objects.remove(high, do_unlink=True)
                    continue
                diag = max(low.dimensions.length, 1e-4)
                layers = low.data.uv_layers
                for lay in list(layers):
                    layers.remove(lay)
                layers.new(name="LOKI_UV")
                with _with_active(sc, low):
                    bpy.ops.object.mode_set(mode="EDIT")
                    try:
                        bpy.ops.mesh.select_all(action="SELECT")
                        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.003)
                    finally:
                        bpy.ops.object.mode_set(mode="OBJECT")
                img = bpy.data.images.new("%s_baked" % low.name, size, size)
                mat = bpy.data.materials.new("LOKI baked %s" % low.name)
                mat.use_nodes = True
                nt = mat.node_tree
                bsdf = nt.nodes.get("Principled BSDF")
                tex = nt.nodes.new("ShaderNodeTexImage")
                tex.image = img
                nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
                bsdf.inputs["Roughness"].default_value = 0.7
                nt.nodes.active = tex
                low.data.materials.clear()
                low.data.materials.append(mat)
                high.hide_render = False
                for x in sc.objects:
                    try:
                        x.select_set(x in (high, low))
                    except RuntimeError:
                        pass
                sc.view_layers[0].objects.active = low
                metal, rough = _surface_values(high)
                bsdf.inputs["Metallic"].default_value = metal
                bsdf.inputs["Roughness"].default_value = rough
                with _emit_base_colour(high), bpy.context.temp_override(
                        active_object=low, object=low, selected_objects=[high, low], selected_editable_objects=[high, low]):
                    bpy.ops.object.bake(type="EMIT", use_selected_to_active=True,
                                        cage_extrusion=0.01 * diag, max_ray_distance=0.03 * diag, margin=16)
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in low.name)
                path = folder / ("%s_baked.png" % safe)
                img.filepath_raw = str(path)
                img.file_format = "PNG"
                img.save()
                img.pack()
                nrm_path = None
                if p.get("normal"):                     # retopo: the original's detail as a tangent-space normal map
                    nimg = bpy.data.images.new("%s_normal" % low.name, size, size)
                    nimg.colorspace_settings.name = "Non-Color"
                    ntex = nt.nodes.new("ShaderNodeTexImage")
                    ntex.image = nimg
                    nmap = nt.nodes.new("ShaderNodeNormalMap")
                    nt.nodes.active = ntex
                    with bpy.context.temp_override(active_object=low, object=low, selected_objects=[high, low],
                                                   selected_editable_objects=[high, low]):
                        bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", use_selected_to_active=True,
                                            cage_extrusion=0.01 * diag, max_ray_distance=0.03 * diag, margin=16)
                    nt.links.new(ntex.outputs["Color"], nmap.inputs["Color"])
                    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
                    nrm_path = folder / ("%s_normal.png" % safe)
                    nimg.filepath_raw = str(nrm_path)
                    nimg.file_format = "PNG"
                    nimg.save()
                    nimg.pack()
                data = high.data
                bpy.data.objects.remove(high, do_unlink=True)
                if data.users == 0:
                    bpy.data.meshes.remove(data)
                done.append({"object": low.name, "texture": str(path), "normal": str(nrm_path) if nrm_path else None})
        finally:
            sc.render.engine = prev_engine
    return {"baked": done}



def topology_report(o):
    """How workable a mesh is (owner 2026-10-26: "models to be improved with working topology"): quad share, triangles,
    n-gons, poles (vertices with 3 or 5+ edges - where edge loops break), non-manifold / boundary edges, sliver faces,
    UV layers. A verdict: "quads" (animation-ready flow), "mixed", "soup" (AI triangles: needs retopology)."""
    import bmesh  # pylint: disable=import-outside-toplevel
    bm = bmesh.new()
    bm.from_mesh(o.data)
    f = len(bm.faces) or 1
    quads = sum(1 for x in bm.faces if len(x.verts) == 4)
    tris = sum(1 for x in bm.faces if len(x.verts) == 3)
    inner = [v for v in bm.verts if not v.is_boundary and v.link_edges]
    poles = sum(1 for v in inner if len(v.link_edges) != 4)
    nonman = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    slivers = 0
    for x in bm.faces:
        ls = [e.calc_length() for e in x.edges]
        if ls and min(ls) > 0 and max(ls) / min(ls) > 8:
            slivers += 1
    r = {"faces": len(bm.faces), "quad_pct": round(100.0 * quads / f, 1), "tri_pct": round(100.0 * tris / f, 1),
         "ngons": len(bm.faces) - quads - tris, "poles": poles, "pole_pct": round(100.0 * poles / max(1, len(inner)), 1),
         "nonmanifold": nonman, "boundary": boundary, "sliver_pct": round(100.0 * slivers / f, 1),
         "uv_layers": [u.name for u in o.data.uv_layers]}
    bm.free()
    r["verdict"] = ("quads" if r["quad_pct"] >= 90 and r["pole_pct"] <= 15 and not r["nonmanifold"] else
                    "soup" if r["tri_pct"] >= 70 else "mixed")
    return r


def cmd_topology(p):
    with job_context(p.get("scene")) as sc:
        return {o.name: topology_report(o) for o in _meshes(sc, p.get("objects")) if not o.name.endswith("__high")}


# ----------------------------------------------------------------------------- retopo: AI soup -> clean quads
# Owner 2026-10-26: "the entire point of blender is so it can edit the mesh and make em workable ... i need the models
# to be improved with working topology". Research (docs/PIPELINE_RESEARCH_2026-10-26.md, "Retopology"): watertight
# voxel surface first, then QuadriFlow (built in; Instant Meshes, BSD, when its binary is given), project back onto the
# surface, then `bake` moves colour + a normal map from the original. Found on the PC (Blender 5.2.3): QuadriFlow
# refuses a voxel mesh my manifold check passed - Blender's own check (object_remesh.cc mesh_is_manifold_consistent)
# also fails on any edge shorter than 1e-4 in LOCAL coordinates (compare_v3v3), and marching voxels make such edges.
def qf_problems(me) -> dict:
    """Blender's QuadriFlow pre-check, counted instead of stopping at the first problem: edges in >2 faces, faces
    flipped against a neighbour, wire edges (no face), edges shorter than 1e-4 on every axis (local coordinates)."""
    n = len(me.edges)
    count = [0] * n
    first = [-1] * n
    flips = gt2 = 0
    for lp in me.loops:
        e, v = lp.edge_index, lp.vertex_index
        count[e] += 1
        if count[e] > 2:
            gt2 += 1
        if first[e] == -1:
            first[e] = v
        elif first[e] == v:
            flips += 1
    co = me.vertices
    short = 0
    for ed in me.edges:
        a, b = co[ed.vertices[0]].co, co[ed.vertices[1]].co
        if abs(a.x - b.x) <= 1e-4 and abs(a.y - b.y) <= 1e-4 and abs(a.z - b.z) <= 1e-4:
            short += 1
    r = {"gt2": gt2, "flips": flips, "wire": sum(1 for c in count if c == 0), "short": short}
    r["ok"] = not any(r.values())
    return r


def _apply_scale(o):
    """Scale into the mesh (QuadriFlow's check and lengths are in local units); location / rotation stay."""
    from mathutils import Matrix  # pylint: disable=import-outside-toplevel
    s = o.scale
    if max(abs(s.x - 1), abs(s.y - 1), abs(s.z - 1)) > 1e-6:
        if o.data.users > 1:
            o.data = o.data.copy()
        o.data.transform(Matrix.Diagonal((s.x, s.y, s.z, 1.0)))
        o.scale = (1.0, 1.0, 1.0)


def _clean_for_quads(me, dist):
    import bmesh  # pylint: disable=import-outside-toplevel
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=dist)
    wire = [e for e in bm.edges if not e.link_faces]
    if wire:
        bmesh.ops.delete(bm, geom=wire, context="EDGES")
    loose = [v for v in bm.verts if not v.link_edges]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bad = [e for e in bm.edges if len(e.link_faces) > 2]       # rare after a voxel pass: cut the fins off
    if bad:
        bmesh.ops.delete(bm, geom=list({f for e in bad for f in e.link_faces}), context="FACES")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()


def prep_for_quads(o, voxel_div=160) -> dict:
    """Make `o` a surface QuadriFlow accepts: scale applied, voxel rebuilt (watertight, one shell), tiny edges merged,
    normals one way. Returns the pre-check after each round."""
    _apply_scale(o)
    d = o.dimensions
    diag = max((d.x * d.x + d.y * d.y + d.z * d.z) ** 0.5, 1e-4)
    m = o.modifiers.new("LOKI voxel", "REMESH")
    m.mode, m.voxel_size, m.use_smooth_shade = "VOXEL", diag / float(voxel_div), True
    _apply_modifier(o, m)
    rounds = []
    dist = max(2e-4, diag * 2e-5)
    for _ in range(4):
        _clean_for_quads(o.data, dist)
        chk = qf_problems(o.data)
        rounds.append(dict(chk, dist=round(dist, 6)))
        if chk["ok"]:
            break
        dist *= 3
    return {"voxel": round(diag / float(voxel_div), 5), "faces": len(o.data.polygons), "rounds": rounds,
            "ok": rounds[-1]["ok"]}


def _obj_write(me, path):
    with open(path, "w", encoding="utf-8") as fh:
        for v in me.vertices:
            fh.write("v %.6f %.6f %.6f\n" % tuple(v.co))
        for poly in me.polygons:
            fh.write("f " + " ".join(str(i + 1) for i in poly.vertices) + "\n")


def _obj_read(path):
    verts, faces = [], []
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            if ln.startswith("v "):
                verts.append(tuple(float(x) for x in ln.split()[1:4]))
            elif ln.startswith("f "):
                faces.append([int(t.split("/")[0]) - 1 for t in ln.split()[1:]])
    return verts, faces


def instant_meshes(o, exe, faces, timeout=240) -> dict:
    """Instant Meshes (BSD-3, wjakob) as a subprocess: pure quads, seconds even on dense input."""
    import subprocess  # pylint: disable=import-outside-toplevel
    import tempfile  # pylint: disable=import-outside-toplevel
    tmp = Path(tempfile.mkdtemp(prefix="loki-im-"))
    src, dst = tmp / "in.obj", tmp / "out.obj"
    _obj_write(o.data, src)
    kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}          # no console window
    try:
        cp = subprocess.run([str(exe), str(src), "-o", str(dst), "-f", str(int(faces)), "-d", "-S", "2", "-b",
                             "-r", "4", "-p", "4"], capture_output=True, text=True, timeout=timeout, check=False, **kw)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "why": str(exc)}
    if cp.returncode or not dst.is_file():
        return {"ok": False, "why": (cp.stderr or cp.stdout or "no output")[-400:]}
    verts, polys = _obj_read(dst)
    if not polys:
        return {"ok": False, "why": "empty result"}
    me = bpy.data.meshes.new(o.data.name + "_im")
    me.from_pydata(verts, [], polys)
    me.update()
    old = o.data
    o.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return {"ok": True}


def _quadriflow(sc, o, faces, symmetric, seeds=(0, 7, 42)) -> dict:
    tries = []
    o.data.use_mirror_x = bool(symmetric)
    for seed in seeds:
        before = len(o.data.polygons)
        with _with_active(sc, o):
            ret = bpy.ops.object.quadriflow_remesh(mode="FACES", target_faces=int(faces), seed=seed,
                                                   use_mesh_symmetry=bool(symmetric), use_preserve_sharp=False,
                                                   use_preserve_boundary=False, smooth_normals=True)
        after = len(o.data.polygons)
        tries.append({"seed": seed, "ret": sorted(ret), "faces": after})
        if "FINISHED" in ret and after and after != before:
            return {"ok": True, "tries": tries}
    return {"ok": False, "tries": tries}


def _project(o, target, rounds=2):
    """Pull the new quads onto `target`'s surface, relax, pull again (keeps the flow even)."""
    for i in range(rounds):
        m = o.modifiers.new("LOKI project", "SHRINKWRAP")
        m.target, m.wrap_method, m.wrap_mode, m.offset = target, "NEAREST_SURFACEPOINT", "ON_SURFACE", 0.0
        _apply_modifier(o, m)
        if i < rounds - 1:
            m = o.modifiers.new("LOKI relax", "SMOOTH")
            m.factor, m.iterations = 0.5, 1
            _apply_modifier(o, m)


def cmd_retopo(p):
    """faces: quads wanted (8000 - a game creature; 3000 a prop, 15000 a hero); symmetric: mirror flow on X;
    voxel: surface rebuild divisions of the diagonal (160); instant_meshes: path of its binary (optional, tried when
    QuadriFlow refuses); fallback_tris: when no quads come out, the clean voxel surface decimated to this.
    The original stays as "<name>__high" so `bake` (normal=True) moves its colours and detail onto the quads."""
    faces = int(p.get("faces") or 8000)
    out = {}
    with job_context(p.get("scene")) as sc:
        for o in _meshes(sc, p.get("objects")):
            if o.name.endswith(("__high", "__vox")):
                continue
            t0 = time.time()
            before = topology_report(o)
            if sc.objects.get(o.name + "__high") is None:            # the original: colour + detail source for bake
                high = o.copy()
                high.data = o.data.copy()
                high.name = o.name + "__high"
                sc.collection.objects.link(high)
                high.hide_render = True
            prep = prep_for_quads(o, int(p.get("voxel") or 160))
            vox = o.copy()                                           # the clean surface the quads are projected onto
            vox.data = o.data.copy()
            vox.name = o.name + "__vox"
            sc.collection.objects.link(vox)
            vox.hide_render = True
            how, tries = None, {}
            if prep["ok"]:
                qf = _quadriflow(sc, o, faces, p.get("symmetric"))
                tries["quadriflow"] = qf["tries"]
                how = "quadriflow" if qf["ok"] else None
            exe = p.get("instant_meshes") or os.environ.get("LOKI_INSTANT_MESHES")
            if how is None and exe and Path(exe).is_file():
                im = instant_meshes(o, exe, faces)
                tries["instant_meshes"] = im
                how = "instant_meshes" if im["ok"] else None
            if how:
                _project(o, vox)
            else:                                                    # no quads: still a clean, light surface
                limit = int(p.get("fallback_tris") or 20000)
                tris = _tris([o])
                if tris > limit:
                    m = o.modifiers.new("LOKI decimate", "DECIMATE")
                    m.ratio = limit / float(tris)
                    _apply_modifier(o, m)
                how = "voxel only"
            vdata = vox.data
            bpy.data.objects.remove(vox, do_unlink=True)
            if vdata.users == 0:
                bpy.data.meshes.remove(vdata)
            for poly in o.data.polygons:
                poly.use_smooth = True
            out[o.name] = {"how": how, "quads": how in ("quadriflow", "instant_meshes"), "prep": prep, "tries": tries,
                           "before": before, "after": topology_report(o), "seconds": round(time.time() - t0, 1)}
    return {"objects": out, "quads": all(v["quads"] for v in out.values()) if out else False}



COMMANDS.update({"retopo": cmd_retopo, "topology": cmd_topology, "repair": cmd_repair, "bake": cmd_bake, "remix": cmd_remix, "import": cmd_import, "cleanup": cmd_cleanup, "normalize": cmd_normalize, "decimate": cmd_decimate,
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


def _prune(root, keep=40):
    """Keep blender/outbox and done/ small: the newest `keep` answers/jobs (owner 2026-10-26: "clean up everything")."""
    for d in ("outbox", "done"):
        try:
            files = sorted((p for p in (root / d).iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for old in files[keep:]:
            try:
                old.unlink()
            except OSError:
                pass


def _inbox_once():
    root = _S["root"]
    if root is None:
        return
    if _S["jobs"] % 20 == 0 and time.time() - _S.get("pruned", 0) > 600:
        _S["pruned"] = time.time()
        _prune(root)
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
