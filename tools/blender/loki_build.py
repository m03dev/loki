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
  band - straps round an earlier part, sized for you: {"shape": "band", "on": "body", "count": 2, "mat": "iron"}
         (optional width, thickness, axis "x"|"y"); on a barrel lid they follow the curve.
  rod - a round bar between parts: {"shape": "rod", "between": "leg", "height": 0.35, "diameter": 0.02} joins each
        copy of a repeated part to the next (rungs); or "from": "leg_1", "to": "leg_2". height = 0-1 up the parts.
  heap - a mound covered in small pieces: {"shape": "heap", "size": [0.7, 0.4, 0.25], "on": "body", "at": "inside",
         "mat": "gold", "count": 120, "pieces": "coin"|"ball"} (treasure, gems, apples, gravel).
  "repeat": {"count": 3, "around": 0.1, "splay": 12} spreads copies round the parent and leans them out (legs).
The finished model always stands on the floor (its lowest point at z = 0).
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
DERIVED = {"band", "rod", "heap"}   # shapes sized from other parts, not from "size"


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
        # see-through in every engine: mostly transparent, glossy, a faint tint (transmission alone renders black/white
        # in Eevee without per-material ray tracing)
        b = next(x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED")
        if "Alpha" in b.inputs:
            b.inputs["Alpha"].default_value = float(spec.get("alpha", 0.18))
        b.inputs["Roughness"].default_value = 0.02
        for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND"), ("use_backface_culling", False),
                          ("show_transparent_back", True)):
            if hasattr(m, attr):
                try:
                    setattr(m, attr, val)
                except Exception:  # noqa: BLE001
                    pass
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


def _axis_point(o, frac):
    """A point on the part's long axis, `frac` of the way up from its lowest end (works for tilted legs)."""
    me = o.data
    pts = [o.matrix_world @ v.co for v in me.vertices]
    lo = min(pts, key=lambda q: q.z)
    hi = max(pts, key=lambda q: q.z)
    zlo = [q for q in pts if q.z <= lo.z + 0.002]
    zhi = [q for q in pts if q.z >= hi.z - 0.002]
    a = sum(zlo, Vector()) / len(zlo)
    b = sum(zhi, Vector()) / len(zhi)
    return a.lerp(b, frac)


def _bvh(o):
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    verts = [o.matrix_world @ v.co for v in me.vertices]
    polys = [tuple(pl.vertices) for pl in me.polygons]
    ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys), verts


def gap(a, b):
    """Shortest distance between two parts' surfaces (0 when they touch or cross)."""
    ta, va = _bvh(a)
    tb, vb = _bvh(b)
    if ta.overlap(tb):
        return 0.0
    best = 1e9
    for v in va[:: max(1, len(va) // 400)]:
        hit = tb.find_nearest(v)
        if hit[0] is not None:
            best = min(best, hit[3])
    for v in vb[:: max(1, len(vb) // 400)]:
        hit = ta.find_nearest(v)
        if hit[0] is not None:
            best = min(best, hit[3])
    return best


def check_contacts(spec, made, first):
    """Nothing floats: every attached part must touch what it is on. A gap is an error the model fixes."""
    bad = []
    for p in spec["parts"]:
        on = p.get("on")
        if not on or p.get("shape") in DERIVED or p["id"] not in made:
            continue
        others = [x for q in spec["parts"] if q["id"] != p["id"] and q["id"] in made and q.get("shape") != "heap" for x in made[q["id"]][:12]]
        for o in made[p["id"]]:
            g = gap(o, first[on])
            if g > 0.004:
                # it may rest on something else instead (a band on the posts around a base)
                g = min([g] + [gap(o, x) for x in others])
            if g > 0.004:
                bad.append(f"'{o.name}' floats {g * 100:.1f} cm away from '{on}' (and everything else)")
    if bad:
        raise SpecError("; ".join(bad[:6]) + ". Parts must touch what they are on: drop or shrink the offset, pick the "
                        "anchor that puts them there (top/bottom/front/back/left/right/inside), use \"band\" for straps "
                        "and \"rod\" for bars between parts.")


def make_derived(p, first, made, mats):
    """band: straps round another part; rod: a round bar between two parts (rungs, rails, chains)."""
    pid = p["id"]
    mname = p.get("mat") or p.get("material") or "iron"
    if mname not in mats:
        mats[mname] = make_material(mname, mname)
    shape = p["shape"]
    objs = []
    if shape == "band":
        on = p.get("on")
        if on not in first:
            raise SpecError(f"band '{pid}' needs \"on\": an earlier part to go round")
        par = first[on]
        lo, hi = bounds(par)
        n = max(1, int(p.get("count", 2)))
        w = float(p.get("width", min(0.06, (hi.x - lo.x) * 0.07)))
        t = float(p.get("thickness", 0.006))
        axis = p.get("axis", "x")
        for k in range(n):
            f = 0.5 if n == 1 else 0.18 + 0.64 * k / (n - 1)
            q = {"id": f"{pid}_{k + 1}", "_name": f"{pid}_{k + 1}", "shape": "barrel" if par.get("loki_shape") == "barrel" else "box"}
            if axis == "x":
                q["size"] = [w, hi.y - lo.y + 2 * t, hi.z - lo.z + (t if q["shape"] == "barrel" else 2 * t)]
                at = Vector((lo.x + (hi.x - lo.x) * f, (lo.y + hi.y) / 2, 0))
            else:
                q["size"] = [hi.x - lo.x + 2 * t, w, hi.z - lo.z + 2 * t]
                at = Vector(((lo.x + hi.x) / 2, lo.y + (hi.y - lo.y) * f, 0))
            o = make_shape(q)
            olo, ohi = bounds(o)
            o.location = Vector((at.x, at.y, lo.z - (t if q["shape"] != "barrel" else 0) - olo.z))
            bpy.context.view_layer.update()
            wrap_around(o, par)
            finish_part(o, {**q, "bevel": 0.001}, mats[mname])
            o.parent = par
            o.matrix_parent_inverse = par.matrix_world.inverted()
            objs.append(o)
        return objs
    if shape == "heap":
        # a mound with many small pieces lying on its surface (coins, gems, apples, gravel)
        if "size" not in p:
            raise SpecError(f"heap '{pid}' needs a size [x, y, height]")
        x, y, z = p["size"]
        q = {**p, "shape": "dome", "_name": pid, "size": [x, y, z * 0.8]}
        mound = make_shape(q)
        fillers = []
        on = p.get("on")
        if on:
            if on not in first:
                raise SpecError(f"heap '{pid}' is on '{on}', which is not defined before it")
            attach(mound, first[on], p.get("at", "top"), "bottom", p.get("inset"))
            if p.get("at") == "inside" and not p.get("keep_low"):
                # a heap in a container fills it and crowns just over the rim (a full chest, a fruit bowl)
                mlo, mhi = bounds(mound)
                plo, phi = bounds(first[on])
                rise = (phi.z + (mhi.z - mlo.z) * 0.3) - mhi.z
                if rise > 0:
                    mound.location.z += rise
                    filler = _make_cyl(pid + "_fill", x * 0.98, y * 0.98, max(0.001, rise))
                    bpy.ops.object.select_all(action="DESELECT")
                    filler.location = Vector(((mlo.x + mhi.x) / 2, (mlo.y + mhi.y) / 2, mlo.z + rise / 2))
                    sq = filler.scale
                    filler.scale = (sq.x, sq.y, sq.z)
                    finish_part(filler, {"shape": "cylinder", "size": [x, y, rise], "bevel": 0}, mats[mname])
                    filler.parent = first[on]
                    filler.matrix_parent_inverse = first[on].matrix_world.inverted()
                    fillers.append(filler)
                bpy.context.view_layer.update()
        finish_part(mound, {**q, "bevel": 0}, mats[mname])
        objs.append(mound)
        objs.extend(fillers)
        lo, hi = bounds(mound)
        c = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
        a, b, h = x / 2, y / 2, z * 0.8
        piece = float(p.get("piece", max(0.02, min(0.05, min(x, y) * 0.09))))
        import random as _r
        rnd = _r.Random(int(p.get("seed", 7)))
        n = int(p.get("count", 140))
        balls = p.get("pieces", "coin") != "coin"
        for k in range(n):
            # an even spread over the mound, each piece lying along the surface (tilted by its normal)
            u, v = rnd.uniform(-1, 1), rnd.uniform(-1, 1)
            q2 = 1 - u * u - v * v
            if q2 <= 0.0:
                continue
            w = math.sqrt(q2)
            pos = Vector((c.x + u * a, c.y + v * b, c.z + h * w))
            normal = Vector((u / a, v / b, w / h)).normalized()
            if balls:
                bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=piece / 2)
                item = bpy.context.object
                item.name = f"{pid}_piece{k}"
            else:
                item = _make_cyl(f"{pid}_piece{k}", piece, piece, piece * 0.15)
                tilt = Euler((rnd.uniform(-0.35, 0.35), rnd.uniform(-0.35, 0.35), rnd.uniform(0, 6.28)))
                item.matrix_world = normal.to_track_quat("Z", "Y").to_matrix().to_4x4() @ tilt.to_matrix().to_4x4()
            item.location = pos + normal * piece * 0.05
            finish_part(item, {"shape": "cylinder", "size": [piece, piece, piece * 0.15], "bevel": 0.0008}, mats[mname])
            item.parent = mound
            item.matrix_parent_inverse = mound.matrix_world.inverted()
            objs.append(item)
        if on:
            mound.parent = first[on]
            mound.matrix_parent_inverse = first[on].matrix_world.inverted()
        return objs
    # rod
    d = float(p.get("diameter", (p.get("size") or [0.02])[0]))
    height = float(p.get("height", 0.4))
    pairs = []
    if p.get("between"):
        base = p["between"]
        copies = made.get(base)
        if not copies or len(copies) < 2:
            raise SpecError(f"rod '{pid}': between '{base}' needs a repeated part (count >= 2) defined before it")
        loop = len(copies) > 2 and p.get("loop", True)
        pairs = [(copies[i], copies[(i + 1) % len(copies)]) for i in range(len(copies) if loop else len(copies) - 1)]
    else:
        a, b = p.get("from"), p.get("to")
        if a not in first or b not in first:
            raise SpecError(f"rod '{pid}': needs \"from\" and \"to\" (earlier part ids, copies are id_1, id_2 ...) or \"between\": a repeated part")
        pairs = [(first[a], first[b])]
    for k, (oa, ob) in enumerate(pairs):
        pa, pb = _axis_point(oa, height), _axis_point(ob, height)
        L_ = (pb - pa).length
        if L_ < 1e-4:
            raise SpecError(f"rod '{pid}': its two ends are at the same place")
        name = pid if len(pairs) == 1 else f"{pid}_{k + 1}"
        o = _make_cyl(name, d, d, L_)
        o.matrix_world = Matrix.Translation((pa + pb) / 2) @ (pb - pa).to_track_quat("Z", "Y").to_matrix().to_4x4()
        bpy.context.view_layer.update()
        finish_part(o, {"shape": "cylinder", "size": [d, d, L_]}, mats[mname])
        o.parent = oa
        o.matrix_parent_inverse = oa.matrix_world.inverted()
        objs.append(o)
    return objs


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


def hinge(o, edge, angle, parent=None):
    """Rotate o (and its children) about its bottom edge on `edge` - where it meets its parent, so an overhanging lid
    still turns on the body's edge."""
    lo, hi = bounds(o)
    if parent is not None:
        plo, phi = bounds(parent)
        lo = Vector((max(lo.x, plo.x), max(lo.y, plo.y), lo.z))
        hi = Vector((min(hi.x, phi.x), min(hi.y, phi.y), hi.z))
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
        if p.get("shape") in DERIVED:
            objs = make_derived(p, first, made, mats)
            made[pid] = objs
            first[pid] = objs[0]
            for k, o in enumerate(objs):
                first[f"{pid}_{k + 1}"] = o
            continue
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
        unknown = set(rep) - {"count", "around", "along", "spacing", "start", "splay"}
        if unknown:
            raise SpecError(f"part '{pid}': repeat takes count with around (a ring) or along/spacing (a row), plus splay - "
                            f"not {', '.join(sorted(unknown))}. Bars between repeated parts: {{\"shape\": \"rod\", \"between\": \"{p.get('on') or 'leg'}\"}}")
        count = max(1, int(rep.get("count", 1)))
        objs = []
        for k in range(count):
            q = dict(p)
            q["_name"] = pid if count == 1 else f"{pid}_{k + 1}"
            o = make_shape(q)
            o["loki_shape"] = p.get("shape", "box")
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
                if rep.get("splay"):
                    # lean outward (legs): tilt about the end that touches the parent
                    lo_, hi_ = bounds(o)
                    top_end = at != "top"
                    pivot = Vector(((lo_.x + hi_.x) / 2, (lo_.y + hi_.y) / 2, hi_.z if top_end else lo_.z))
                    axis = Vector((-math.sin(ang), math.cos(ang), 0))
                    tilt = -math.radians(float(rep["splay"])) * (1 if top_end else -1)   # free end swings outward
                    o.matrix_world = Matrix.Translation(pivot) @ Matrix.Rotation(tilt, 4, axis) @ Matrix.Translation(-pivot) @ o.matrix_world
                    bpy.context.view_layer.update()
            elif count > 1:
                axis = {"x": 0, "y": 1, "z": 2}[rep.get("along", "x")]
                step = rep.get("spacing", p["size"][axis] * 1.5)
                d = [0, 0, 0]
                d[axis] = (k - (count - 1) / 2) * step
                o.location += Vector(d)
            if p.get("offset"):
                o.location += Vector(p["offset"])
            if p.get("wrap") and on:
                plo, phi = bounds(first[on])
                psize, osize = phi - plo, Vector(p["size"])
                if all(osize[i] >= psize[i] * 0.9 for i in range(3)):
                    raise SpecError(f"part '{pid}': a wrap as big as '{on}' would cover it completely - for straps use "
                                    f'{{"shape": "band", "on": "{on}", "count": 2}}')
                wrap_around(o, first[on])
            finish_part(o, p, mats[mname])
            objs.append(o)
        made[pid] = objs
        first[pid] = objs[0]
        if len(objs) > 1:
            for k, o in enumerate(objs):
                first[f"{pid}_{k + 1}"] = o
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
                hinge(o, h.get("edge", "back"), float(h.get("angle", 90)), first.get(p.get("on")))
    check_contacts(spec, made, first)   # after hinges: what touched the shut lid must still touch something
    # real light sources (a flame, a bulb: emit >= 1.5) light the scene - one light per part, not per copy or coin;
    # a faint glow (gold with emit 0.4) only glows
    for p in spec["parts"]:
        m = mats.get(p.get("mat") or p.get("material") or "plastic")
        if m is None or m.get("loki_emit", 0) < 1.5 or p["id"] not in made:
            continue
        objs = made[p["id"]][:8]
        for o in objs:
            lo, hi = bounds(o)
            ld = bpy.data.lights.new(o.name + "_light", "POINT")
            ld.energy = 15 * m["loki_emit"] / len(objs)
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
    # the model stands on the floor: lift or drop everything so its lowest point is at z = 0
    roots = [o for o in bpy.context.scene.objects if o.parent is None and o.type in ("MESH", "LIGHT")]
    lo, hi = L._scene_bounds()
    for o in roots:
        o.location.z -= lo.z
    bpy.context.view_layer.update()
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
