"""loki_bpy - reliable building blocks for LOKI's Blender scripts (Blender 4.2 - 5.x).

Free models are bad at 3D maths (a lid "on" a chest floated 2.9 m up). These helpers do the maths: parts are made in
metres with their origin at the bottom centre, placed against each other by MEASURED bounds, hinged on a real edge,
framed by a camera computed from the scene's bounds. Use them instead of guessing coordinates.

    import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from loki_bpy import *
    ROOT = start(__file__)                       # clean scene, renders/ and scenes/ folders next to scripts/
    wood = mat("Wood", "#8a5a2b", rough=0.7)
    gold = mat("Gold", "#d4a017", metal=1.0, rough=0.3)
    ground(8, mat("Floor", "#3b3b3b"))
    body = box("Body", (0.8, 0.5, 0.45), wood, bevel=0.02)
    lid = box("Lid", (0.82, 0.52, 0.12), wood, bevel=0.02)
    place_on(lid, body)                          # lid sits exactly on the body
    hinge(lid, edge="-y", angle=40)              # opens 40 deg on its back edge
    band = box("Band", (0.84, 0.54, 0.05), gold); place_on(band, body, z=-0.1)   # 0.1 m below the body's top
    coins(body, 40, gold)                        # a pile of coins inside the body
    frame(); lights(); finish("chest")           # camera, three-point light, save scenes/chest.blend, render renders/chest.png
"""
import math
import os
import random

import bpy
from mathutils import Matrix, Vector

__all__ = ["start", "mat", "box", "cyl", "sphere", "cone", "ground", "bounds", "size_of", "place_on", "place_beside",
           "place_inside", "center_on", "hinge", "array", "coins", "planks", "join", "parent", "bevel", "frame", "lights",
           "world", "finish", "render", "save", "ROOT"]

ROOT = os.getcwd()
_parts = []


# ---------------------------------------------------------------- setup

def start(script_file=None, units="METRIC"):
    """Empty scene; ROOT = the job folder (the parent of scripts/); renders/ and scenes/ exist."""
    global ROOT
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if script_file:
        here = os.path.dirname(os.path.abspath(script_file))
        ROOT = os.path.dirname(here) if os.path.basename(here) == "scripts" else here
    for d in ("renders", "scenes"):
        os.makedirs(os.path.join(ROOT, d), exist_ok=True)
    bpy.context.scene.unit_settings.system = units
    _parts.clear()
    return ROOT


def _hex(c):
    if isinstance(c, str):
        c = c.lstrip("#")
        r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
        # sRGB -> linear, as Blender colours are linear
        return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in (r, g, b)) + (1.0,)
    return tuple(c) + ((1.0,) if len(c) == 3 else ())


def mat(name, color="#bbbbbb", metal=0.0, rough=0.5, emit=0.0, emit_color=None):
    """A Principled material. `emit` > 0 makes it glow (fire: emit=5, emit_color="#ff7a1a")."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = m.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    col = _hex(color)
    bsdf.inputs["Base Color"].default_value = col
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Roughness"].default_value = rough
    if emit:
        for key in ("Emission Color", "Emission"):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = _hex(emit_color or color)
                break
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = emit
    m.diffuse_color = col
    return m


# ---------------------------------------------------------------- parts (metres, origin at bottom centre)

def _finish_part(o, name, material, bevel_w, segments=2):
    o.name = name
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    # origin to the bottom centre, so z=0 means "standing on the ground"
    lo, hi = bounds(o, local=True)
    off = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    o.data.transform(Matrix.Translation(-off))
    o.location += o.matrix_world.to_3x3() @ off
    if material:
        o.data.materials.clear()
        o.data.materials.append(material)
    if bevel_w:
        bevel(o, bevel_w, segments)
    _parts.append(o)
    return o


def box(name, size=(1, 1, 1), material=None, at=(0, 0, 0), bevel=0.0):
    """A box `size` = (x, y, z) metres, standing on `at`."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    o = bpy.context.object
    o.scale = size
    o = _finish_part(o, name, material, bevel)
    o.location = Vector(at)
    return o


def cyl(name, radius=0.5, depth=1.0, material=None, at=(0, 0, 0), axis="Z", verts=24, bevel=0.0):
    """A cylinder. axis "X"/"Y" lays it down (logs, bars, hinges); origin at the bottom centre after turning."""
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=radius, depth=depth, location=(0, 0, 0))
    o = bpy.context.object
    if axis.upper() == "X":
        o.rotation_euler = (0, math.radians(90), 0)
    elif axis.upper() == "Y":
        o.rotation_euler = (math.radians(90), 0, 0)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    o = _finish_part(o, name, material, bevel)
    o.location = Vector(at)
    return o


def sphere(name, radius=0.5, material=None, at=(0, 0, 0), low=True):
    if low:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius, location=(0, 0, 0))
    else:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=(0, 0, 0))
    o = _finish_part(bpy.context.object, name, material, 0)
    o.location = Vector(at)
    return o


def cone(name, radius=0.5, depth=1.0, material=None, at=(0, 0, 0), verts=12, radius_top=0.0):
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=radius, radius2=radius_top, depth=depth, location=(0, 0, 0))
    o = _finish_part(bpy.context.object, name, material, 0)
    o.location = Vector(at)
    return o


def ground(size=10, material=None, name="Ground"):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, 0))
    o = bpy.context.object
    o.name = name
    if material:
        o.data.materials.append(material)
    return o


def bevel(o, width=0.02, segments=2):
    """Round hard edges (what makes a box read as a made object)."""
    m = o.modifiers.new("Bevel", "BEVEL")
    m.width = width
    m.segments = segments
    m.limit_method = "ANGLE"
    return o


# ---------------------------------------------------------------- measuring and placing

def bounds(o, local=False):
    """(min, max) corners in world space (or the object's own space with local=True), modifiers included."""
    pts = [Vector(c) for c in o.bound_box]
    if not local:
        bpy.context.view_layer.update()
        pts = [o.matrix_world @ p for p in pts]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def size_of(o):
    lo, hi = bounds(o)
    return hi - lo


def _move_by(o, d):
    o.location += d
    bpy.context.view_layer.update()


def place_on(o, target, x=0.0, y=0.0, z=0.0):
    """Stand `o` on top of `target`, centred (x, y shift it; z < 0 sinks it in, e.g. a band around a body)."""
    lo, hi = bounds(o)
    tlo, thi = bounds(target)
    c, tc = (lo + hi) / 2, (tlo + thi) / 2
    _move_by(o, Vector((tc.x - c.x + x, tc.y - c.y + y, thi.z - lo.z + z)))
    return o


def place_beside(o, target, side="+x", gap=0.0, align="bottom"):
    """Put `o` against one side of `target` ("+x", "-x", "+y", "-y"), touching (gap 0), bottoms level."""
    lo, hi = bounds(o)
    tlo, thi = bounds(target)
    c, tc = (lo + hi) / 2, (tlo + thi) / 2
    d = Vector((tc.x - c.x, tc.y - c.y, (tlo.z - lo.z) if align == "bottom" else (tc.z - c.z)))
    axis, sign = side[1], side[0]
    i = "xyz".index(axis)
    if sign == "+":
        d[i] = thi[i] - lo[i] + gap
    else:
        d[i] = tlo[i] - hi[i] - gap
    _move_by(o, d)
    return o


def place_inside(o, target, depth=0.0):
    """Centre `o` in `target` with its bottom `depth` m below the target's top (things in a box)."""
    lo, hi = bounds(o)
    tlo, thi = bounds(target)
    c, tc = (lo + hi) / 2, (tlo + thi) / 2
    _move_by(o, Vector((tc.x - c.x, tc.y - c.y, thi.z - depth - lo.z)))
    return o


def center_on(o, target):
    lo, hi = bounds(o)
    tlo, thi = bounds(target)
    _move_by(o, (tlo + thi) / 2 - (lo + hi) / 2)
    return o


def hinge(o, edge="-y", angle=40.0):
    """Open `o` by `angle` degrees around its bottom edge on side `edge` ("-y" = back, "+y" = front, "-x", "+x").
    Positive angles open upward. The part stays attached at the hinge edge."""
    lo, hi = bounds(o)
    axis = edge[1]
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    i = "xyz".index(axis)
    pivot[i] = lo[i] if edge[0] == "-" else hi[i]
    a = math.radians(angle)
    if axis == "y":
        rot = Matrix.Rotation(a if edge[0] == "-" else -a, 4, "X")
    else:
        rot = Matrix.Rotation(-a if edge[0] == "-" else a, 4, "Y")
    o.matrix_world = Matrix.Translation(pivot) @ rot @ Matrix.Translation(-pivot) @ o.matrix_world
    bpy.context.view_layer.update()
    return o


def array(o, count, offset=(1, 0, 0), relative=True):
    """Repeat a part (planks, tiles, coins in a row). relative offsets are in the part's own sizes."""
    m = o.modifiers.new("Array", "ARRAY")
    m.count = count
    m.use_relative_offset = relative
    m.use_constant_offset = not relative
    if relative:
        m.relative_offset_displace = offset
    else:
        m.constant_offset_displace = offset
    return o


def planks(name, size=(1, 0.5, 0.4), n=4, material=None, gap=0.006, axis="z", bevel_w=0.008):
    """A panel made of `n` planks (wood reads as wood). Returns the joined object, origin bottom centre."""
    i = "xyz".index(axis)
    each = list(size)
    each[i] = (size[i] - gap * (n - 1)) / n
    parts = []
    for k in range(n):
        p = box(f"{name}_{k}", tuple(each), material, bevel=bevel_w)
        off = [0, 0, 0]
        off[i] = k * (each[i] + gap) - (size[i] - each[i]) / 2 * (1 if i != 2 else 0)
        p.location = Vector(off)
        p.scale = (1, 1, 1)
        parts.append(p)
    return join(parts, name)


def join(objs, name):
    for m in [m for o in objs for m in o.modifiers]:
        pass
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    o = bpy.context.object
    o.name = name
    return o


def parent(child, par):
    m = child.matrix_world.copy()
    child.parent = par
    child.matrix_world = m
    return child


def coins(container, n=30, material=None, radius=0.03, thickness=0.006, fill=0.7, seed=7):
    """A heap of coins inside the top of `container` (a chest, a bowl). Returns the coins."""
    rnd = random.Random(seed)
    lo, hi = bounds(container)
    out = []
    span_x, span_y = (hi.x - lo.x) * fill / 2, (hi.y - lo.y) * fill / 2
    top = hi.z
    for k in range(n):
        x = rnd.uniform(-span_x, span_x)
        y = rnd.uniform(-span_y, span_y)
        r = (x / span_x) ** 2 + (y / span_y) ** 2 if span_x and span_y else 0
        heap = max(0.0, 1 - r) * min(span_x, span_y) * 0.6     # higher in the middle
        c = cyl(f"Coin_{k}", radius, thickness, material, verts=12)
        c.location = Vector(((lo.x + hi.x) / 2 + x, (lo.y + hi.y) / 2 + y, top - 0.02 + heap * rnd.uniform(0.3, 1)))
        c.rotation_euler = (rnd.uniform(-0.6, 0.6), rnd.uniform(-0.6, 0.6), rnd.uniform(0, 6.28))
        out.append(c)
    bpy.context.view_layer.update()
    return out


# ---------------------------------------------------------------- camera, light, output

def _scene_bounds(objs=None):
    objs = objs or [o for o in bpy.context.scene.objects if o.type == "MESH" and o.name != "Ground" and o.visible_get()]
    los, his = zip(*(bounds(o) for o in objs)) if objs else ((Vector((0, 0, 0)),), (Vector((1, 1, 1)),))
    lo = Vector((min(v.x for v in los), min(v.y for v in los), min(v.z for v in los)))
    hi = Vector((max(v.x for v in his), max(v.y for v in his), max(v.z for v in his)))
    return lo, hi


def frame(objs=None, lens=60, azimuth=35, elevation=22, fill=1.15):
    """A camera that sees everything in `objs` (default: every mesh but the ground), from the front-right."""
    lo, hi = _scene_bounds(objs)
    centre = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.05)
    sc = bpy.context.scene
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = lens
    cam = bpy.data.objects.new("Camera", cam_data)
    sc.collection.objects.link(cam)
    sensor = cam_data.sensor_width
    fov = 2 * math.atan(sensor / (2 * lens))
    aspect = sc.render.resolution_y / max(1, sc.render.resolution_x)
    fov = min(fov, 2 * math.atan(math.tan(fov / 2) * (aspect if aspect < 1 else 1)))
    dist = radius / math.sin(fov / 2) / fill
    az, el = math.radians(azimuth), math.radians(elevation)
    cam.location = centre + Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))) * dist
    direction = centre - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam_data.clip_end = max(100, dist * 4)
    sc.camera = cam
    return cam


def lights(power=1.0, warm="#ffd2a1", cool="#a8c4ff"):
    """Three-point light around the scene: warm key front-left, cool fill front-right, rim behind."""
    lo, hi = _scene_bounds()
    centre = (lo + hi) / 2
    r = max((hi - lo).length, 1.0)
    rigs = [("Key", (-1.2, -1.4, 1.6), 900, warm, 1.0), ("Fill", (1.5, -1.0, 0.8), 300, cool, 1.4), ("Rim", (0.4, 1.6, 1.4), 600, "#ffffff", 0.8)]
    out = []
    for name, d, watts, col, size in rigs:
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = watts * power * (r / 2) ** 2
        ld.color = _hex(col)[:3]
        ld.size = size * r * 0.5
        lo_ = bpy.data.objects.new(name, ld)
        bpy.context.scene.collection.objects.link(lo_)
        lo_.location = centre + Vector(d) * r
        lo_.rotation_euler = (centre - lo_.location).to_track_quat("-Z", "Y").to_euler()
        out.append(lo_)
    world("#1a1c22", 0.6)
    return out


def world(color="#20232b", strength=0.6):
    w = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = w
    try:
        w.use_nodes = True
    except Exception:
        pass
    bg = next((n for n in w.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg is None:
        bg = w.node_tree.nodes.new("ShaderNodeBackground")
        out = next((n for n in w.node_tree.nodes if n.type == "OUTPUT_WORLD"), None) or w.node_tree.nodes.new("ShaderNodeOutputWorld")
        w.node_tree.links.new(bg.outputs[0], out.inputs[0])
    bg.inputs[0].default_value = _hex(color)
    bg.inputs[1].default_value = strength
    return w


def _engine(sc, want):
    names = [e.identifier for e in type(sc.render).bl_rna.properties["engine"].enum_items]
    for e in ([want] if want else []) + ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES", "BLENDER_WORKBENCH"]:
        if e in names:
            sc.render.engine = e
            return e
    return sc.render.engine


def save(name_or_path):
    p = name_or_path if os.path.isabs(str(name_or_path)) else os.path.join(ROOT, "scenes", f"{name_or_path}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=p)
    return p


def render(name_or_path, size=(1024, 1024), engine=None, samples=64):
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = size
    sc.render.resolution_percentage = 100
    used = _engine(sc, engine)
    if used == "CYCLES":
        sc.cycles.samples = samples
        try:
            sc.cycles.device = "GPU"
        except Exception:
            pass
    for attr, val in (("taa_render_samples", samples),):
        if hasattr(sc.eevee, attr):
            setattr(sc.eevee, attr, val)
    try:
        sc.view_settings.view_transform = "AgX"
    except TypeError:
        pass
    p = name_or_path if os.path.isabs(str(name_or_path)) else os.path.join(ROOT, "renders", f"{name_or_path}.png")
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True)
    return p


def finish(name, size=(1024, 1024), engine=None, samples=64):
    """Camera and lights if missing, then save scenes/<name>.blend and render renders/<name>.png."""
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = size
    if not sc.camera:
        frame()
    if not any(o.type == "LIGHT" for o in sc.objects):
        lights()
    blend = save(name)
    png = render(name, size, engine, samples)
    print(f"LOKI_OUT {blend} {png}")
    return blend, png
