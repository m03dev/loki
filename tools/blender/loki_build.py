"""loki_build - build a finished model from a part spec. The model says WHAT the parts are and WHAT they attach to;
this file does all the 3D maths, so parts always touch, sit straight and look made (bevelled, smooth, real materials).

    blender --background --python-exit-code 1 --python scripts/loki_build.py -- scenes/<name>.json

Spec (JSON, metres):
{
  "name": "lantern",
  "materials": {"brass": "brass", "glass": "glass", "flame": {"color": "#ffb347", "emit": 8}},
  "parts": [
    {"id": "base",  "shape": "cylinder", "size": [0.20, 0.20, 0.03], "mat": "brass"},
    {"id": "glass", "shape": "tube",     "size": [0.16, 0.16, 0.24], "mat": "glass", "on": "base", "at": "top", "wall": 0.004},
    {"id": "post",  "shape": "cylinder", "size": [0.016, 0.016, 0.24], "mat": "brass", "on": "base", "at": "top",
     "repeat": {"count": 4, "around": 0.085}},
    {"id": "cap",   "shape": "cone",     "size": [0.22, 0.22, 0.09], "mat": "brass", "on": "glass", "at": "top", "top": 0.25},
    {"id": "ring",  "shape": "torus",    "size": [0.07, 0.07, 0.012], "mat": "brass", "on": "cap", "at": "top", "rotate": [90, 0, 0]},
    {"id": "flame", "shape": "sphere",   "size": [0.03, 0.03, 0.06], "mat": "flame", "on": "base", "at": "top", "offset": [0, 0, 0.04]}
  ]
}
size = the part's outer width (x), depth (y), height (z). +y is the back, the camera looks from -y (the front).
on / at: which part it attaches to and where - its touching face meets that face of the parent, centred:
  top, bottom, front, back, left, right, inside (on the parent's inner floor - for shell/tube), center.
  "align": for front/back/left/right: "bottom" | "center" | "top" (default bottom - stands level with the parent).
  "offset": [x, y, z] metres, after attaching.   "rotate": [x, y, z] degrees about its own centre (before attaching).
  "repeat": {"count": n, "around": radius} (a ring round the parent's centre) or {"count": n, "along": "x", "spacing": s}.
  "hinge": {"edge": "back", "angle": 100} opens the part (and everything attached to it) about that edge.
  "wrap": true keeps only what is outside the parent - make a band a little bigger than the part it goes round,
  at "center", and it becomes a strap hugging it (chest bands, barrel hoops, rims, collars).
shapes: box, cylinder, tube ("wall"), sphere, dome (half sphere), barrel (half cylinder along x - a chest lid), cone
  ("top": 0-1 top radius ratio), torus (size x/y = outer diameter, z = ring thickness), shell (open-top box, "wall"),
  wedge (slope down to the front), lathe ("profile": [[radius 0-1, height 0-1], ...] bottom to top), planks (box made of
  "count" boards along z).
  "bevel": edge rounding in metres (default: small, automatic); "smooth": true/false (default: true for round shapes).
materials: presets wood, oak, darkwood, iron, steel, gold, brass, copper, silver, stone, brick, concrete, marble, leather,
  fabric, velvet, glass, ceramic, plastic, rubber, paper, any colour word, or {"color": "#hex", "metal": 0-1,
  "rough": 0-1, "emit": strength}.
Writes scenes/<name>.blend, renders/<name>.png, renders/<name>_views.png (front/right/back/above), renders/<name>_info.json.
"""
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402  (first: bmesh and mathutils come with it)
import bmesh  # noqa: E402
from mathutils import Euler, Matrix, Vector  # noqa: E402

import loki_bpy as L  # noqa: E402

ROUND = {"cylinder", "tube", "sphere", "dome", "barrel", "cone", "torus", "lathe"}
ANCHORS = {"top", "bottom", "front", "back", "left", "right", "inside", "center"}


class SpecError(Exception):
    pass


# ---------------------------------------------------------------- materials

PRESET = {
    "wood": dict(pbr="wood_planks", color="#7a4e2a", rough=0.6), "oak": dict(pbr="oak_veneer", color="#9a6b3c", rough=0.55),
    "darkwood": dict(pbr="dark_wood", color="#4a2e1a", rough=0.55), "iron": dict(color="#3a3f45", metal=1.0, rough=0.45),
    "steel": dict(color="#a3abb5", metal=1.0, rough=0.25), "gold": dict(color="#e0aa2e", metal=1.0, rough=0.22),
    "brass": dict(color="#c9a043", metal=1.0, rough=0.3), "copper": dict(color="#c0703f", metal=1.0, rough=0.3),
    "silver": dict(color="#d6d6da", metal=1.0, rough=0.18), "stone": dict(pbr="rock_face", color="#7d7a73", rough=0.85),
    "brick": dict(pbr="brick_wall", color="#8a4a3a", rough=0.85), "concrete": dict(pbr="concrete", color="#8d8d88", rough=0.9),
    "marble": dict(pbr="marble", color="#e6e2dc", rough=0.2), "leather": dict(pbr="leather", color="#5a3a24", rough=0.55),
    "fabric": dict(pbr="fabric", color="#6b5a8a", rough=0.9), "velvet": dict(color="#6a1f2b", rough=0.95),
    "glass": dict(color="#dff1f7", rough=0.02, glass=True), "ceramic": dict(color="#ece7df", rough=0.25),
    "plastic": dict(color="#d8d8d8", rough=0.35), "rubber": dict(color="#202020", rough=0.9), "paper": dict(color="#efe6d2", rough=0.8),
}
COLOURS = {"red": "#b8322c", "green": "#3f8f4a", "blue": "#2f5fa8", "black": "#18181a", "white": "#e8e8e8", "yellow": "#e3b82f",
           "orange": "#e07a2c", "purple": "#6d3f9a", "grey": "#808080", "gray": "#808080", "brown": "#6b4a2b", "pink": "#e58fa8",
           "cream": "#efe3c8", "teal": "#2f8f8a", "navy": "#1f2d55"}


def make_material(name, spec):
    if isinstance(spec, str):
        key = spec.lower()
        if key in PRESET:
            spec = dict(PRESET[key])
        elif key in COLOURS:
            spec = {"color": COLOURS[key]}
        elif key.startswith("#"):
            spec = {"color": key}
        else:
            spec = {"color": "#9a9a9a"}
    spec = dict(spec)
    if "preset" in spec and spec["preset"] in PRESET:
        spec = {**PRESET[spec["preset"]], **{k: v for k, v in spec.items() if k != "preset"}}
    if spec.get("pbr"):
        m = L.pbr(name, spec["pbr"], scale=spec.get("scale", 3), fallback=spec.get("color", "#9a9a9a"))
    else:
        m = L.mat(name, spec.get("color", "#9a9a9a"), metal=spec.get("metal", 0.0), rough=spec.get("rough", 0.5),
                  emit=spec.get("emit", 0.0), emit_color=spec.get("emit_color"))
    if spec.get("glass"):
        b = next(x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED")
        for k in ("Transmission Weight", "Transmission"):
            if k in b.inputs:
                b.inputs[k].default_value = 1.0
        if "IOR" in b.inputs:
            b.inputs["IOR"].default_value = 1.45
    if spec.get("emit"):
        # a light source should also light the scene, not only glow
        m["loki_emit"] = float(spec["emit"])
    return m


# ---------------------------------------------------------------- shapes (built at unit size, then scaled to `size`)

def _obj_from_bm(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def _profile_solid(name, prof, segments=48):
    """Revolve [(r, z)] (unit) about z into a closed solid."""
    bm = bmesh.new()
    rings = [[bm.verts.new((r * math.cos(2 * math.pi * k / segments), r * math.sin(2 * math.pi * k / segments), z)) for k in range(segments)]
             if r > 1e-5 else [bm.verts.new((0, 0, z))] for r, z in prof]
    for a, b in zip(rings, rings[1:]):
        if len(a) == 1 and len(b) == 1:
            continue
        if len(a) == 1:
            for k in range(segments):
                bm.faces.new((a[0], b[k], b[(k + 1) % segments]))
        elif len(b) == 1:
            for k in range(segments):
                bm.faces.new((a[k], a[(k + 1) % segments], b[0]))
        else:
            for k in range(segments):
                bm.faces.new((a[k], a[(k + 1) % segments], b[(k + 1) % segments], b[k]))
    if len(rings[0]) > 1:
        bm.faces.new(list(reversed(rings[0])))
    if len(rings[-1]) > 1:
        bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _obj_from_bm(name, bm)


def make_shape(p):
    shape = p.get("shape", "box")
    name = p["_name"]
    x, y, z = p["size"]
    if shape in ("box", "wedge", "shell", "planks"):
        bpy.ops.mesh.primitive_cube_add(size=1)
        o = bpy.context.object
        o.name = name
        if shape == "wedge":
            bm = bmesh.new()
            bm.from_mesh(o.data)
            for v in bm.verts:
                if v.co.z > 0 and v.co.y < 0:
                    v.co.z = -0.5 + 0.08
            bm.to_mesh(o.data)
            bm.free()
        o.scale = (x, y, z)
        _apply(o)
        if shape == "shell":
            w = p.get("wall", max(0.008, min(x, y) * 0.06))
            _cut(o, (x - 2 * w, y - 2 * w, z), (0, 0, w))
        if shape == "planks":
            n = int(p.get("count", 4))
            for k in range(1, n):
                zz = -z / 2 + z * k / n
                _groove(o, x, y, zz, depth=min(0.004, min(x, y) * 0.03))
        return o
    if shape in ("cylinder", "tube"):
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.5, depth=1)
        o = bpy.context.object
        o.name = name
        o.scale = (x, y, z)
        _apply(o)
        if shape == "tube":
            w = p.get("wall", max(0.003, min(x, y) * 0.05))
            inner = _make_cyl(name + "_hole", x - 2 * w, y - 2 * w, z * 1.2)
            _boolean(o, inner)
        return o
    if shape in ("sphere", "dome"):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.5)
        o = bpy.context.object
        o.name = name
        if shape == "dome":
            bm = bmesh.new()
            bm.from_mesh(o.data)
            bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, 0, 0), plane_no=(0, 0, 1), clear_inner=True)
            edges = [e for e in bm.edges if e.is_boundary]
            if edges:
                bmesh.ops.edgeloop_fill(bm, edges=edges)
            for v in bm.verts:
                v.co.z = v.co.z * 2 - 0.5
            bm.to_mesh(o.data)
            bm.free()
        o.scale = (x, y, z)
        _apply(o)
        return o
    if shape == "barrel":
        prof = [(math.cos(math.pi * i / 32) * 0.5, math.sin(math.pi * i / 32)) for i in range(33)]
        bm = bmesh.new()
        left = [bm.verts.new((-0.5, py, pz - 0.5)) for py, pz in prof]
        right = [bm.verts.new((0.5, py, pz - 0.5)) for py, pz in prof]
        for i in range(32):
            bm.faces.new((left[i], left[i + 1], right[i + 1], right[i]))
        bm.faces.new(list(reversed(left)))
        bm.faces.new(right)
        bm.faces.new((left[0], right[0], right[-1], left[-1]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        o = _obj_from_bm(name, bm)
        o.scale = (x, y, z)
        _apply(o)
        return o
    if shape == "cone":
        top = float(p.get("top", 0.0))
        o = _profile_solid(name, [(0.5, -0.5), (0.5 * top, 0.5)])
        o.scale = (x, y, z)
        _apply(o)
        return o
    if shape == "torus":
        R = 0.5 - 0.5 * min(z / max(x, 1e-6), 0.45)
        r_tube = 0.5 - R
        bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r_tube, major_segments=64, minor_segments=20)
        o = bpy.context.object
        o.name = name
        o.scale = (x, y, z / (2 * r_tube))
        _apply(o)
        return o
    if shape == "lathe":
        prof = p.get("profile") or [[0.5, 0], [0.5, 1]]
        o = _profile_solid(name, [(float(r), float(h) - 0.5) for r, h in prof])
        o.scale = (x, y, z)
        _apply(o)
        return o
    raise SpecError(f"part '{p['id']}': unknown shape '{shape}' (box, cylinder, tube, sphere, dome, barrel, cone, torus, shell, wedge, lathe, planks)")


def _make_cyl(name, x, y, z):
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.5, depth=1)
    c = bpy.context.object
    c.name = name
    c.scale = (x, y, z)
    _apply(c)
    return c


def _apply(o):
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def _boolean(o, cutter):
    m = o.modifiers.new("cut", "BOOLEAN")
    m.operation = "DIFFERENCE"
    m.object = cutter
    m.solver = "EXACT"
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier=m.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def _cut(o, size, offset):
    bpy.ops.mesh.primitive_cube_add(size=1)
    c = bpy.context.object
    c.scale = size
    c.location = Vector(offset)
    _apply(c)
    _boolean(o, c)


def _groove(o, x, y, zz, depth):
    bpy.ops.mesh.primitive_cube_add(size=1)
    c = bpy.context.object
    c.scale = (x + 0.02, y + 0.02, depth * 1.2)
    c.location = (0, 0, zz)
    _apply(c)
    bpy.ops.mesh.primitive_cube_add(size=1)
    keep = bpy.context.object
    keep.scale = (x - 2 * depth, y - 2 * depth, depth * 2)
    keep.location = (0, 0, zz)
    _apply(keep)
    _boolean(c, keep)
    _boolean(o, c)


# ---------------------------------------------------------------- placement (all in world space, nothing rotated yet)

def bounds(o):
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def attach(o, parent, at, align="bottom", inset=None):
    """Move o so it touches `parent` at `at`."""
    lo, hi = bounds(o)
    plo, phi = bounds(parent)
    c, pc = (lo + hi) / 2, (plo + phi) / 2
    d = Vector((pc.x - c.x, pc.y - c.y, 0))
    if at == "top":
        d.z = phi.z - lo.z
    elif at == "bottom":
        d.z = plo.z - hi.z
    elif at == "inside":
        floor = plo.z + (inset if inset is not None else parent.get("loki_wall", 0.0))
        d.z = floor - lo.z
    elif at == "center":
        d.z = pc.z - c.z
    else:
        if at == "front":
            d.y = plo.y - hi.y
        elif at == "back":
            d.y = phi.y - lo.y
        elif at == "left":
            d.x = plo.x - hi.x
        elif at == "right":
            d.x = phi.x - lo.x
        d.z = {"bottom": plo.z - lo.z, "top": phi.z - hi.z}.get(align, pc.z - c.z)
    o.location += d
    bpy.context.view_layer.update()


def wrap_around(o, parent):
    """Keep only the part of `o` outside its parent: a band, strap or rim that hugs the parent's surface."""
    bpy.context.view_layer.update()
    if parent.get("loki_wall"):              # hollow parents: cut their whole outline, not just the walls
        lo, hi = bounds(parent)
        hi = hi + Vector((0, 0, 10))         # and never across its open top
        if parent.get("loki_open_both"):
            lo = lo - Vector((0, 0, 10))
        bpy.ops.mesh.primitive_cube_add(size=1)
        c = bpy.context.object
        c.scale = hi - lo
        c.location = (lo + hi) / 2
        _apply(c)
    else:
        c = parent.copy()
        c.data = parent.data.copy()
        c.modifiers.clear()
        bpy.context.scene.collection.objects.link(c)
        c.matrix_world = parent.matrix_world.copy()
    _boolean(o, c)


def hinge(o, edge, angle):
    """Rotate o (and its children) about its bottom edge on `edge`."""
    lo, hi = bounds(o)
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    a = math.radians(angle)
    if edge in ("back", "front"):
        pivot.y = hi.y if edge == "back" else lo.y
        rot = Matrix.Rotation(-a if edge == "back" else a, 4, "X")
    else:
        pivot.x = lo.x if edge == "left" else hi.x
        rot = Matrix.Rotation(-a if edge == "left" else a, 4, "Y")
    o.matrix_world = Matrix.Translation(pivot) @ rot @ Matrix.Translation(-pivot) @ o.matrix_world
    bpy.context.view_layer.update()


def finish_part(o, p, material):
    o.data.materials.clear()
    o.data.materials.append(material)
    x, y, z = p["size"]
    auto = min(0.015, max(0.001, min(x, y, z) * 0.06))
    bw = p.get("bevel", auto)
    if bw and p.get("shape") not in ("sphere", "torus"):
        m = o.modifiers.new("Bevel", "BEVEL")
        m.width = bw
        m.segments = 3
        m.limit_method = "ANGLE"
        m.harden_normals = False
    smooth = p.get("smooth", p.get("shape") in ROUND)
    for f in o.data.polygons:
        f.use_smooth = bool(smooth)
    if smooth:
        try:
            o.modifiers.new("Normals", "WEIGHTED_NORMAL").keep_sharp = True
        except Exception:  # noqa: BLE001
            pass
        if hasattr(o.data, "use_auto_smooth"):
            o.data.use_auto_smooth = True


# ---------------------------------------------------------------- build

def build(spec):
    if not isinstance(spec.get("parts"), list) or not spec["parts"]:
        raise SpecError("the spec needs a non-empty 'parts' list")
    mats = {k: make_material(k, v) for k, v in (spec.get("materials") or {}).items()}
    made = {}            # id -> [objects]
    first = {}           # id -> the object others attach to
    issues = []
    ids = [p.get("id") for p in spec["parts"]]
    for p in spec["parts"]:
        pid = p.get("id")
        if not pid:
            raise SpecError("every part needs an 'id'")
        if "size" not in p or len(p["size"]) != 3 or min(p["size"]) <= 0:
            raise SpecError(f"part '{pid}': 'size' must be [width x, depth y, height z] in metres, all > 0")
        on = p.get("on")
        if on and on not in first:
            raise SpecError(f"part '{pid}' is on '{on}', which is not defined before it (parts so far: {', '.join(x for x in ids[:ids.index(pid)])})")
        at = p.get("at", "top" if on else None)
        if at and at not in ANCHORS:
            raise SpecError(f"part '{pid}': at='{at}' - use one of {', '.join(sorted(ANCHORS))}")
        mname = p.get("mat") or p.get("material") or "plastic"
        if mname not in mats:
            mats[mname] = make_material(mname, mname)
        rep = p.get("repeat") or {}
        count = max(1, int(rep.get("count", 1)))
        objs = []
        for k in range(count):
            q = dict(p)
            q["_name"] = pid if count == 1 else f"{pid}_{k + 1}"
            o = make_shape(q)
            if p.get("rotate"):
                o.rotation_euler = Euler([math.radians(v) for v in p["rotate"]])
                _apply(o)
            if p.get("shape") == "tube":
                o["loki_open_both"] = 1
            if "wall" in p:
                o["loki_wall"] = float(p["wall"])
            elif p.get("shape") in ("shell", "tube"):
                o["loki_wall"] = max(0.008, min(p["size"][0], p["size"][1]) * 0.06)
            if on:
                attach(o, first[on], at, p.get("align", "bottom"), p.get("inset"))
            if rep.get("around"):
                ang = 2 * math.pi * k / count + math.radians(rep.get("start", 45 if count == 4 else 0))
                o.location += Vector((math.cos(ang) * rep["around"], math.sin(ang) * rep["around"], 0))
            elif count > 1:
                axis = {"x": 0, "y": 1, "z": 2}[rep.get("along", "x")]
                step = rep.get("spacing", p["size"][axis] * 1.5)
                d = [0, 0, 0]
                d[axis] = (k - (count - 1) / 2) * step
                o.location += Vector(d)
            if p.get("offset"):
                o.location += Vector(p["offset"])
            if p.get("wrap") and on:
                wrap_around(o, first[on])
            finish_part(o, p, mats[mname])
            objs.append(o)
        made[pid] = objs
        first[pid] = objs[0]
        # children follow their parent through hinges: parent after placement, keeping world transforms
        if on:
            for o in objs:
                par = first[on]
                o.parent = par
                o.matrix_parent_inverse = par.matrix_world.inverted()
    # hinges last, top-down: everything attached rides along
    for p in spec["parts"]:
        h = p.get("hinge")
        if h:
            for o in made[p["id"]]:
                hinge(o, h.get("edge", "back"), float(h.get("angle", 90)))
    # light sources light the scene
    for p in spec["parts"]:
        m = mats.get(p.get("mat") or p.get("material") or "plastic")
        if m is not None and m.get("loki_emit"):
            for o in made[p["id"]]:
                lo, hi = bounds(o)
                ld = bpy.data.lights.new(o.name + "_light", "POINT")
                ld.energy = 15 * m["loki_emit"]
                ld.color = tuple(m.diffuse_color[:3])
                ld.shadow_soft_size = max(0.01, (hi - lo).length / 4)
                lo_ = bpy.data.objects.new(o.name + "_light", ld)
                bpy.context.scene.collection.objects.link(lo_)
                lo_.location = (lo + hi) / 2
    return made, issues


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not args:
        raise SystemExit("usage: blender -b --python loki_build.py -- scenes/<name>.json")
    path = args[0] if os.path.isabs(args[0]) else os.path.join(os.path.dirname(HERE), args[0])
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    name = spec.get("name") or os.path.splitext(os.path.basename(path))[0]
    L.start(os.path.join(HERE, "loki_build.py"))
    t0 = time.time()
    try:
        made, issues = build(spec)
    except SpecError as e:
        print(f"LOKI_SPEC_ERROR {e}")
        raise SystemExit(2)
    lo, hi = L._scene_bounds()
    size = hi - lo
    L.ground(max(3.0, size.length * 5), L.mat("Floor", spec.get("floor", "#3b3b3b"), rough=0.85))
    L.frame(fill=1.2)
    L.lights()
    blend, png = L.finish(name)
    tris = 0
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o.name != "Ground":
            dg = o.evaluated_get(bpy.context.evaluated_depsgraph_get())
            tris += sum(len(pp.vertices) - 2 for pp in dg.data.polygons)
    info = {"name": name, "parts": sum(len(v) for v in made.values()), "triangles": tris,
            "size_m": [round(size.x, 3), round(size.y, 3), round(size.z, 3)], "build_s": round(time.time() - t0, 1),
            "floating": 0, "issues": issues}
    with open(os.path.join(L.ROOT, "renders", f"{name}_info.json"), "w") as f:
        json.dump(info, f, indent=1)
    print("LOKI_INFO " + json.dumps(info))


if __name__ == "__main__":
    main()
