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
    hinge(lid, edge="+y", angle=40)              # opens 40 deg on its back edge (+y = back; the camera looks from -y)
    band = box("Band", (0.84, 0.54, 0.05), gold); place_on(band, body, z=-0.1)   # 0.1 m below the body's top
    coins(body, 40, gold)                        # a pile of coins inside the body
    frame(); lights(); finish("chest")           # camera, three-point light, save scenes/chest.blend, render renders/chest.png
                                                 # + renders/chest_views.png (front / side / back / top) for the vision check
Real surfaces (free CC0 scans from Poly Haven, cached on this machine; flat colour if offline):
    wood = pbr("Wood", "wood_planks")            # also: "rusty_metal_02", "brick_wall_001", "rock_face", "forest_ground_01" ...
    hdri("studio_small_09")                      # real studio light + reflections (lights() does this for you)
"""
import json
import math
import os
import random
import urllib.request

import bpy
from mathutils import Matrix, Vector

__all__ = ["start", "mat", "box", "cyl", "sphere", "cone", "ground", "bounds", "size_of", "place_on", "place_beside",
           "place_inside", "center_on", "hinge", "array", "coins", "planks", "join", "parent", "bevel", "frame", "lights",
           "world", "finish", "render", "save", "hdri", "pbr", "views", "tray", "ring", "dome", "lathe", "ROOT"]

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


# ---------------------------------------------------------------- real surfaces + light (Poly Haven, CC0)

UA = "LOKI/0.19 (+https://github.com/m03dev/loki; art pipeline)"   # Poly Haven asks for a unique User-Agent


def _cache():
    base = os.environ.get("LOKI_HOME") or os.path.join(ROOT, ".assets")
    d = os.path.join(base, "assets", "polyhaven")
    os.makedirs(d, exist_ok=True)
    return d


def _credit(asset, kind):
    """Poly Haven assets are CC0; LOKI still credits them next to the renders."""
    try:
        p = os.path.join(ROOT, "renders", "CREDITS.txt")
        line = f"{kind} '{asset}' by Poly Haven (CC0) - https://polyhaven.com/a/{asset}\n"
        if not os.path.exists(p) or line not in open(p, encoding="utf-8").read():
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


def _get(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return dest


def _resolve(asset, kind):
    """A close real asset id when the asked one doesn't exist ("rock_face" -> "rock_face_03"), from the cached catalogue."""
    cat = os.path.join(_cache(), f"_{kind}.json")
    if not os.path.exists(cat) or os.path.getsize(cat) < 100:
        _get(f"https://api.polyhaven.com/assets?t={kind}", cat)
    with open(cat, encoding="utf-8") as f:
        ids = list(json.load(f).keys())
    if asset in ids:
        return asset
    words = [w for w in asset.lower().replace("-", "_").split("_") if w and not w.isdigit()]
    hits = [i for i in ids if all(w in i for w in words)] or [i for i in ids if any(w in i for w in words)]
    if not hits:
        raise ValueError(f"no Poly Haven {kind} like '{asset}'")
    hits.sort(key=lambda i: (-sum(w in i for w in words), len(i)))
    return hits[0]


def _files(asset, kind="textures"):
    """The asset's file list (cached); a near name is matched to a real asset."""
    asset = _resolve(asset, kind)
    d = os.path.join(_cache(), asset)
    os.makedirs(d, exist_ok=True)
    meta = os.path.join(d, "files.json")
    if not os.path.exists(meta):
        _get(f"https://api.polyhaven.com/files/{asset}", meta)
    with open(meta, encoding="utf-8") as f:
        return d, json.load(f)


def hdri(asset="studio_small_09", strength=1.0, res="1k", rotate=0.0, show=False):
    """Light the scene with a real HDRI (studio, sky, interior). Returns the World, or None when offline.
    show=False keeps a plain dark backdrop behind the object while the HDRI still lights it and fills reflections."""
    try:
        d, files = _files(asset, "hdris")
        asset = os.path.basename(d)
        f = files["hdri"][res]
        ext = "hdr" if "hdr" in f else "exr"
        path = _get(f[ext]["url"], os.path.join(d, f"{asset}_{res}.{ext}"))
    except Exception as e:
        print(f"LOKI_WARN hdri {asset} unavailable ({e}); using the studio grey world")
        return None
    w = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = w
    try:
        w.use_nodes = True
    except Exception:
        pass
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(path, check_existing=True)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value[2] = math.radians(rotate)
    nt.links.new(coord.outputs["Generated"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    if show:
        nt.links.new(bg.outputs[0], out.inputs[0])
    else:
        # camera rays see a dark backdrop; everything else (light, reflections) sees the HDRI
        plain = nt.nodes.new("ShaderNodeBackground")
        plain.inputs["Color"].default_value = _hex("#202329")
        lp = nt.nodes.new("ShaderNodeLightPath")
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
        nt.links.new(bg.outputs[0], mix.inputs[1])
        nt.links.new(plain.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs[0])
    _credit(asset, "HDRI")
    return w


def _pick(files, *names):
    low = {k.lower(): k for k in files}
    for n in names:
        if n in low:
            return low[n]
    return None


def pbr(name, asset, scale=1.0, tint=None, res="1k", fallback="#9a8a78", metal=None):
    """A real scanned material from Poly Haven (wood_planks, rusty_metal_02, brick_wall_001, rock_face ...).
    Mapped by object position in metres (`scale` = texture repeats per metre), so it never stretches on
    resized parts. `tint` multiplies the colour. Offline or unknown asset -> a plain mat() in `fallback`."""
    try:
        d, files = _files(asset)
        asset = os.path.basename(d)
        maps = {}
        for role, names in (("color", ("diffuse", "diff", "albedo", "color")), ("normal", ("nor_gl", "normal", "nor")),
                            ("rough", ("rough", "roughness")), ("arm", ("arm",)), ("metal", ("metal", "metallic"))):
            k = _pick(files, *names)
            if not k or res not in files[k]:
                continue
            fm = files[k][res]
            ext = "jpg" if "jpg" in fm else "png" if "png" in fm else None
            if ext:
                maps[role] = _get(fm[ext]["url"], os.path.join(d, f"{asset}_{k}_{res}.{ext}"))
        if "color" not in maps:
            raise ValueError("no colour map")
    except Exception as e:
        print(f"LOKI_WARN texture {asset} unavailable ({e}); flat colour instead")
        return mat(name, fallback, metal=metal or 0.0, rough=0.6)
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(coord.outputs["Object"], mp.inputs["Vector"])

    def tex(path, data):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(path, check_existing=True)
        if data:
            try:
                t.image.colorspace_settings.name = "Non-Color"
            except Exception:
                pass
        t.projection = "BOX"          # no UVs needed: projected from the three axes, blended at the seams
        t.projection_blend = 0.25
        nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
        return t

    col = tex(maps["color"], False).outputs["Color"]
    if tint:
        mix = nt.nodes.new("ShaderNodeMix") if hasattr(bpy.types, "ShaderNodeMix") else None
        if mix is not None:
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs[0].default_value = 1.0
            nt.links.new(col, mix.inputs[6])
            mix.inputs[7].default_value = _hex(tint)
            col = mix.outputs[2]
    nt.links.new(col, bsdf.inputs["Base Color"])
    if "arm" in maps:
        sep = nt.nodes.new("ShaderNodeSeparateColor") if hasattr(bpy.types, "ShaderNodeSeparateColor") else nt.nodes.new("ShaderNodeSeparateRGB")
        nt.links.new(tex(maps["arm"], True).outputs["Color"], sep.inputs[0])
        nt.links.new(sep.outputs[1], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs[2], bsdf.inputs["Metallic"])
    elif "rough" in maps:
        nt.links.new(tex(maps["rough"], True).outputs["Color"], bsdf.inputs["Roughness"])
    if "metal" in maps and "arm" not in maps:
        nt.links.new(tex(maps["metal"], True).outputs["Color"], bsdf.inputs["Metallic"])
    if metal is not None and "arm" not in maps and "metal" not in maps:
        bsdf.inputs["Metallic"].default_value = metal
    if "normal" in maps:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(tex(maps["normal"], True).outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    m.diffuse_color = _hex(tint or fallback)
    _credit(asset, "Texture")
    return m


# ---------------------------------------------------------------- parts (metres, origin at bottom centre)

def _friendly(fn):
    """Accept the names models reach for: location= / loc= / position= for at=, mat= for material=."""
    import functools

    @functools.wraps(fn)
    def wrap(*a, **kw):
        for alias in ("location", "loc", "position", "pos"):
            if alias in kw and "at" not in kw:
                kw["at"] = kw.pop(alias)
        if "mat" in kw and "material" not in kw:
            kw["material"] = kw.pop("mat")
        return fn(*a, **kw)
    return wrap


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


@_friendly
def box(name, size=(1, 1, 1), material=None, at=(0, 0, 0), bevel=0.0):
    """A box `size` = (x, y, z) metres, standing on `at`."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    o = bpy.context.object
    o.scale = size
    o = _finish_part(o, name, material, bevel)
    o.location = Vector(at)
    return o


@_friendly
def tray(name, size=(1, 1, 1), wall=0.03, material=None, at=(0, 0, 0), bevel=0.0):
    """An open-top box (a chest body, crate, drawer, planter): floor + four walls `wall` m thick, one object.
    Things put in it with place_inside() / coins() sit inside, not on a solid lid."""
    x, y, z = size
    parts = [box(f"{name}_floor", (x, y, wall), None, at)]
    for sx, sy, w, d in ((0, -(y - wall) / 2, x, wall), (0, (y - wall) / 2, x, wall),
                         (-(x - wall) / 2, 0, wall, y - 2 * wall), ((x - wall) / 2, 0, wall, y - 2 * wall)):
        parts.append(box(f"{name}_w", (w, d, z - wall), None, (at[0] + sx, at[1] + sy, at[2] + wall)))
    o = join(parts, name)
    _finish_part(o, name, material, bevel)
    return o


@_friendly
def ring(name, size=(1, 1, 0.05), wall=0.01, material=None, at=(0, 0, 0)):
    """A rectangular band with no floor or lid (iron bands round a chest, a frame round a door): four thin walls."""
    x, y, z = size
    parts = []
    for sx, sy, w, d in ((0, -(y - wall) / 2, x, wall), (0, (y - wall) / 2, x, wall),
                         (-(x - wall) / 2, 0, wall, y - 2 * wall), ((x - wall) / 2, 0, wall, y - 2 * wall)):
        parts.append(box(f"{name}_w", (w, d, z), None, (at[0] + sx, at[1] + sy, at[2])))
    o = join(parts, name)
    _finish_part(o, name, material, 0)
    return o


@_friendly
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


@_friendly
def sphere(name, radius=0.5, material=None, at=(0, 0, 0), low=True):
    if low:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius, location=(0, 0, 0))
    else:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=(0, 0, 0))
    o = _finish_part(bpy.context.object, name, material, 0)
    o.location = Vector(at)
    return o


@_friendly
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


def hinge(o, edge="+y", angle=40.0):
    """Open `o` by `angle` degrees around its bottom edge on side `edge` ("+y" = back, "-y" = front - Blender's
    front view and frame() look from -y - "-x", "+x").
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


@_friendly
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
    # a hollow container (tray()) gets a bed of the same metal first, so the heap rests on something
    bpy.context.view_layer.update()
    c0 = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z + 0.01))
    inv = container.matrix_world.inverted()
    hit, lloc, *_ = container.ray_cast(inv @ c0, (inv.to_3x3() @ Vector((0, 0, -1))).normalized())   # this container only
    loc = container.matrix_world @ lloc
    if hit and (c0.z - loc.z) > (hi.z - lo.z) * 0.3:
        bed = box(f"{container.name}_hoard", ((hi.x - lo.x) * 0.9, (hi.y - lo.y) * 0.9, max(0.01, top - 0.03 - loc.z)), material,
                  (c0.x, c0.y, loc.z))
        out_bed = [bed]
    else:
        out_bed = []
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
    return out_bed + out


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
    # a real studio HDRI for reflections (metals need something to reflect, or gold reads black); grey if offline
    if hdri("studio_small_09", strength=0.8) is None:
        world("#3a3f4a", 1.0)
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
    # Eevee: metals (gold, iron) render black without ray-traced reflections; turn them on where they exist
    for attr, val in (("taa_render_samples", samples), ("use_raytracing", True), ("use_shadows", True),
                      ("use_gtao", True), ("use_ssr", True), ("use_ssr_refraction", False)):
        if hasattr(sc.eevee, attr):
            try:
                setattr(sc.eevee, attr, val)
            except Exception:
                pass
    try:
        sc.view_settings.view_transform = "AgX"
    except TypeError:
        pass
    p = name_or_path if os.path.isabs(str(name_or_path)) else os.path.join(ROOT, "renders", f"{name_or_path}.png")
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True)
    return p


def views(name, size=512, engine=None, samples=32):
    """One sheet of four views - front, right side, back, from above - as renders/<name>_views.png, so a reviewer
    (the vision check, or you) sees what one hero angle hides: floating parts, missing backs, wrong proportions."""
    sc = bpy.context.scene
    old_cam = sc.camera
    lo, hi = _scene_bounds()
    shots = [("front", 0, 12), ("right", 90, 12), ("back", 200, 18), ("top", 35, 70)]
    tiles = []
    for label, az, el in shots:
        cam = frame(azimuth=az, elevation=el, fill=1.1)
        cam.name = f"View_{label}"
        p = render(os.path.join(ROOT, "renders", f".{name}_{label}.png"), (size, size), engine, samples)
        tiles.append(p)
        bpy.data.objects.remove(cam, do_unlink=True)
    sc.camera = old_cam
    try:
        import numpy as np
        px = []
        for p in tiles:
            im = bpy.data.images.load(p)
            a = np.array(im.pixels[:], dtype=np.float32).reshape(size, size, 4)
            px.append(a)
            bpy.data.images.remove(im)
        # Blender pixels start bottom-left: top row = front, right; bottom row = back, top
        sheet = np.concatenate([np.concatenate([px[2], px[3]], axis=1), np.concatenate([px[0], px[1]], axis=1)], axis=0)
        out = bpy.data.images.new(f"{name}_views", size * 2, size * 2, alpha=True)
        out.pixels[:] = sheet.ravel()
        dest = os.path.join(ROOT, "renders", f"{name}_views.png")
        out.filepath_raw = dest
        out.file_format = "PNG"
        out.save()
        bpy.data.images.remove(out)
        for p in tiles:
            try:
                os.remove(p)
            except OSError:
                pass
        return dest
    except Exception as e:
        print(f"LOKI_WARN views sheet not made ({e}); single views kept")
        return tiles[0]


def finish(name, size=(1024, 1024), engine=None, samples=64, sheet=True):
    """Camera and lights if missing, then save scenes/<name>.blend, render renders/<name>.png and the four-view
    sheet renders/<name>_views.png (sheet=False skips it)."""
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = size
    if not sc.camera:
        frame()
    if not any(o.type == "LIGHT" for o in sc.objects):
        lights()
    blend = save(name)
    png = render(name, size, engine, samples)
    extra = ""
    if sheet:
        extra = " " + views(name, engine=engine)
        sc.render.resolution_x, sc.render.resolution_y = size
    print(f"LOKI_OUT {blend} {png}{extra}")
    return blend, png


# ---------------------------------------------------------------- shapes for kits

@_friendly
def dome(name, size=(1, 0.5, 0.2), material=None, at=(0, 0, 0), segments=16, bevel=0.0):
    """A half-round (barrel-top) lid: a half ellipse in Y/Z run along X. size = (length x, width y, rise z)."""
    import bmesh
    x, y, z = size
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    prof = [(y / 2 * math.cos(math.pi * i / segments), z * math.sin(math.pi * i / segments)) for i in range(segments + 1)]
    left = [bm.verts.new((-x / 2, py, pz)) for py, pz in prof]
    right = [bm.verts.new((x / 2, py, pz)) for py, pz in prof]
    for i in range(segments):
        bm.faces.new((left[i], left[i + 1], right[i + 1], right[i]))
    bm.faces.new(list(reversed(left)))
    bm.faces.new(right)
    bm.faces.new((left[0], right[0], right[-1], left[-1]))     # the flat bottom
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    o = _finish_part(o, name, material, bevel)
    o.location = Vector(at)
    return o


def _turn(objs, pivot, axis, degrees):
    """Rotate several objects together about a line through `pivot` along `axis` ("X"/"Y"/"Z")."""
    rot = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(degrees), 4, axis) @ Matrix.Translation(-pivot)
    for o in objs:
        o.matrix_world = rot @ o.matrix_world
    bpy.context.view_layer.update()


@_friendly
def lathe(name, profile, material=None, at=(0, 0, 0), segments=32, cap=True):
    """Spin a profile [(radius, z), ...] (bottom to top) round Z: barrels, vases, bottles, columns, lamp bases."""
    import bmesh
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    rings = []
    for r, z in profile:
        rings.append([bm.verts.new((r * math.cos(2 * math.pi * k / segments), r * math.sin(2 * math.pi * k / segments), z)) for k in range(segments)])
    for a, b in zip(rings, rings[1:]):
        for k in range(segments):
            bm.faces.new((a[k], a[(k + 1) % segments], b[(k + 1) % segments], b[k]))
    if cap:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    o = _finish_part(o, name, material, 0)
    o.location = Vector(at)
    return o
