"""LOKI scene inspector - real facts about a .blend, so a job is judged on what it made, not on its own word.

Run by the driver:  blender --background <scene.blend> --python-exit-code 1 --python inspect_scene.py -- <out.json>

Reports per mesh: polygons, triangles, size, materials, non-manifold edges, loose parts; and scene problems:
  - floating parts (a mesh touching neither the ground nor any other mesh - e.g. a lid hovering over a chest)
  - parts outside the camera view, no camera, no lights, missing materials, empty scene
  - degenerate geometry (zero-area faces), unapplied huge/negative scale
Each problem has a level: "error" (the scene is wrong) or "warn" (worth a look).
"""
import json
import sys

import bmesh
import bpy
from mathutils import Vector

GAP = 0.02          # metres: closer than this counts as touching
out_path = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else None
sc = bpy.context.scene
deps = bpy.context.evaluated_depsgraph_get()
report = {"file": bpy.data.filepath, "engine": sc.render.engine, "resolution": [sc.render.resolution_x, sc.render.resolution_y],
          "meshes": [], "problems": [], "counts": {}}


def problem(level, text, obj=None):
    report["problems"].append({"level": level, "text": text, **({"object": obj} if obj else {})})


def world_bbox(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def touching(a, b, gap=GAP):
    (alo, ahi), (blo, bhi) = a, b
    return all(alo[i] - gap <= bhi[i] and blo[i] - gap <= ahi[i] for i in range(3))


meshes = [o for o in sc.objects if o.type == "MESH" and o.visible_get()]
boxes = {}
total_tris = 0
for o in meshes:
    ev = o.evaluated_get(deps)
    me = ev.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    total_tris += tris
    non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    degenerate = sum(1 for f in bm.faces if f.calc_area() < 1e-10)
    # loose parts: connected components
    seen, parts = set(), 0
    for v in bm.verts:
        if v.index in seen:
            continue
        parts += 1
        stack = [v]
        while stack:
            x = stack.pop()
            if x.index in seen:
                continue
            seen.add(x.index)
            stack.extend(e.other_vert(x) for e in x.link_edges)
    bm.free()
    ev.to_mesh_clear()
    lo, hi = world_bbox(o)
    boxes[o.name] = (lo, hi)
    mats = [s.material.name for s in o.material_slots if s.material]
    size = [round(hi[i] - lo[i], 3) for i in range(3)]
    report["meshes"].append({"name": o.name, "polygons": len(o.data.polygons), "triangles": tris, "size_m": size,
                             "min_z": round(lo.z, 3), "materials": mats, "non_manifold_edges": non_manifold, "parts": parts})
    if not mats:
        problem("warn", f"{o.name} has no material (renders grey)", o.name)
    if degenerate:
        problem("warn", f"{o.name} has {degenerate} zero-area faces", o.name)
    s = o.scale
    if min(s) < 0:
        problem("warn", f"{o.name} has negative scale {tuple(round(x, 2) for x in s)} (flipped normals)", o.name)

report["counts"] = {"meshes": len(meshes), "triangles": total_tris,
                    "lights": sum(1 for o in sc.objects if o.type == "LIGHT"), "cameras": sum(1 for o in sc.objects if o.type == "CAMERA")}

if not meshes:
    problem("error", "the scene has no visible meshes")

# ground = the lowest large flat mesh, if any; everything else must rest on it or touch something
ground = None
if meshes:
    flat = [o for o in meshes if (boxes[o.name][1].z - boxes[o.name][0].z) < 0.05 * max(1e-6, max(boxes[o.name][1].x - boxes[o.name][0].x, boxes[o.name][1].y - boxes[o.name][0].y))]
    if flat:
        ground = min(flat, key=lambda o: boxes[o.name][0].z)
floor_z = boxes[ground.name][1].z if ground else min(boxes[o.name][0].z for o in meshes) if meshes else 0.0
emissive_words = ("flame", "fire", "spark", "glow", "light", "torch", "particle", "smoke", "star", "sky", "cloud")
for o in meshes:
    if o is ground:
        continue
    lo, hi = boxes[o.name]
    on_floor = lo.z <= floor_z + GAP
    near = [n for n, b in boxes.items() if n != o.name and touching((lo, hi), b)]
    if not on_floor and not near and not any(w in o.name.lower() for w in emissive_words):
        gap = lo.z - floor_z
        # the nearest other part, and how far / which way to move to touch it
        best = None
        for n, (blo, bhi) in boxes.items():
            if n == o.name or (ground and n == ground.name):
                continue
            d = [max(blo[i] - hi[i], lo[i] - bhi[i], 0.0) for i in range(3)]
            dist = (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5
            if best is None or dist < best[1]:
                best = (n, dist, d, (blo, bhi))
        hint = ""
        if best:
            n, dist, d, (blo, bhi) = best
            axis = max(range(3), key=lambda i: d[i])
            where = {0: "x", 1: "y", 2: "z"}[axis]
            if axis == 2:
                hint = f"; nearest part {n} is {dist:.2f} m away - move it {'down' if lo.z > bhi.z else 'up'} {d[2]:.2f} m so it sits on {n} (top at z={bhi.z:.2f})"
            else:
                hint = f"; nearest part {n} is {dist:.2f} m away along {where}"
        problem("error", f"{o.name} is floating: it touches nothing (bottom {gap:.2f} m above the floor{hint})", o.name)

cam = sc.camera
if not cam:
    problem("error", "no camera: nothing to render from")
else:
    from bpy_extras.object_utils import world_to_camera_view
    span = max(max(b[1][i] - b[0][i] for b in boxes.values()) for i in range(3)) if boxes else 1.0
    for o in meshes:
        if o is ground:
            continue
        lo, hi = boxes[o.name]
        big = max(hi[i] - lo[i] for i in range(3)) > 0.35 * span   # walls and floors run past the frame on purpose
        corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
        uv = [world_to_camera_view(sc, cam, c) for c in corners]
        inside = [0 <= p.x <= 1 and 0 <= p.y <= 1 and p.z > 0 for p in uv]
        if not any(inside):
            problem("warn", f"{o.name} is outside the camera view", o.name)
        elif not all(inside) and not big:
            problem("warn", f"{o.name} is cut off at the frame edge", o.name)
if report["counts"]["lights"] == 0 and not (sc.world and sc.world.use_nodes):
    problem("warn", "no lights and no world lighting: the render will be dark")

report["ok"] = not any(p["level"] == "error" for p in report["problems"])
text = json.dumps(report, indent=1)
if out_path:
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
print("LOKI_INSPECT " + json.dumps({"ok": report["ok"], "problems": len(report["problems"])}))
