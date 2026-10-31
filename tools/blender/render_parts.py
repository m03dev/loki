"""render_parts - turn mesh parts (STL / OBJ / GLB from any tool) into a finished render. Every job gets it in scripts/.

Any tool that makes meshes writes one file per material into parts/ (STL/OBJ in millimetres, GLB in metres):
    parts/wood.stl  parts/iron.stl  parts/gold.stl  parts/stone.stl  parts/glass.stl  parts/red.stl ...
Then:  blender --background --python-exit-code 1 --python scripts/render_parts.py -- parts <name>
It imports the parts, gives each its material (by file name; any colour word or #hex works too), adds ground, camera and
studio light, saves scenes/<name>.blend, renders renders/<name>.png + renders/<name>_views.png (front/right/back/above)
and writes renders/<name>_info.json (triangles, open edges, size in metres per part) - the info shown with the result.
"""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy, bmesh
from loki_bpy import *
from loki_bpy import _scene_bounds

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
parts_dir = os.path.join(os.path.dirname(HERE), args[0] if args else "parts")
name = args[1] if len(args) > 1 else "model"
PRESETS = {
    "wood": lambda n: pbr(n, "wood_planks", scale=3, fallback="#7a4e2a"), "oak": lambda n: pbr(n, "oak_veneer", scale=3, fallback="#9a6b3c"),
    "iron": lambda n: mat(n, "#3a3f45", metal=1.0, rough=0.42), "steel": lambda n: mat(n, "#9aa3ad", metal=1.0, rough=0.25),
    "gold": lambda n: mat(n, "#d9a521", metal=1.0, rough=0.25), "brass": lambda n: mat(n, "#b5913a", metal=1.0, rough=0.3),
    "copper": lambda n: mat(n, "#b8693f", metal=1.0, rough=0.3), "stone": lambda n: pbr(n, "rock_face", scale=2, fallback="#7d7a73"),
    "brick": lambda n: pbr(n, "brick_wall", scale=2, fallback="#8a4a3a"), "concrete": lambda n: pbr(n, "concrete", scale=2, fallback="#8d8d88"),
    "leather": lambda n: pbr(n, "leather", scale=4, fallback="#5a3a24"), "fabric": lambda n: pbr(n, "fabric", scale=4, fallback="#6b5a8a"),
    "glass": lambda n: _glass(n), "plastic": lambda n: mat(n, "#d8d8d8", rough=0.35), "rubber": lambda n: mat(n, "#202020", rough=0.9),
}
COLOURS = {"red": "#b8322c", "green": "#3f8f4a", "blue": "#2f5fa8", "black": "#18181a", "white": "#e8e8e8", "yellow": "#e3b82f",
           "orange": "#e07a2c", "purple": "#6d3f9a", "grey": "#808080", "gray": "#808080", "brown": "#6b4a2b"}


def _glass(n):
    m = mat(n, "#cfe8f0", rough=0.03)
    b = next(x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED")
    for k in ("Transmission Weight", "Transmission"):
        if k in b.inputs:
            b.inputs[k].default_value = 1.0
    return m


def material_for(stem):
    key = stem.lower().split("_")[0].split("-")[0]
    if key in PRESETS:
        return PRESETS[key](stem)
    if key in COLOURS:
        return mat(stem, COLOURS[key], rough=0.45)
    if key.startswith("#") or (len(key) == 6 and all(c in "0123456789abcdef" for c in key)):
        return mat(stem, "#" + key.lstrip("#"), rough=0.45)
    return mat(stem, "#9a9a9a", rough=0.5)


start(os.path.join(HERE, "render_parts.py"))
info = {"name": name, "parts": {}}
files = sorted(f for f in os.listdir(parts_dir) if f.lower().endswith((".stl", ".obj", ".glb"))) if os.path.isdir(parts_dir) else []
if not files:
    raise SystemExit(f"no parts in {parts_dir}: write parts/<material>.stl first")
for f in files:
    stem, ext = os.path.splitext(f)
    before = set(bpy.data.objects)
    p = os.path.join(parts_dir, f)
    if ext.lower() == ".stl":
        bpy.ops.wm.stl_import(filepath=p, global_scale=0.001)
    elif ext.lower() == ".obj":
        bpy.ops.wm.obj_import(filepath=p, global_scale=0.001)
    else:
        bpy.ops.import_scene.gltf(filepath=p)
    m = material_for(stem)
    for o in set(bpy.data.objects) - before:
        if o.type != "MESH":
            continue
        o.name = stem
        o.data.materials.clear()
        o.data.materials.append(m)
        bm = bmesh.new(); bm.from_mesh(o.data)
        lo, hi = bounds(o)
        info["parts"][stem] = {"triangles": sum(len(fc.verts) - 2 for fc in bm.faces), "open_edges": sum(1 for e in bm.edges if not e.is_manifold),
                               "size_m": [round(hi[i] - lo[i], 3) for i in range(3)], "file_kb": os.path.getsize(p) // 1024}
        bm.free()
lo, hi = _scene_bounds()
ground(max(4.0, (hi - lo).length * 4), mat("Floor", "#3b3b3b", rough=0.9))
frame(); lights()
t = time.time()
blend, png = finish(name)
info["render_s"] = round(time.time() - t, 1)
info["size_m"] = [round(hi[i] - lo[i], 3) for i in range(3)]
info["triangles"] = sum(p["triangles"] for p in info["parts"].values())
info["watertight"] = all(p["open_edges"] == 0 for p in info["parts"].values())
with open(os.path.join(ROOT, "renders", f"{name}_info.json"), "w") as f:
    json.dump(info, f, indent=1)
print("LOKI_INFO", json.dumps(info))
