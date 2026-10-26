"""Runs INSIDE Blender (engine/blender_link.py proof): loads the vendored MCP for Blender add-on and drives it with the
same commands its MCP server sends (ping, execute_code, get_scene_info) - no socket needed - to build a low-poly
campfire from scratch, then renders a still and exports a .glb. Proves the add-on works in THIS Blender.

    blender --background --factory-startup --python mcp_proof.py -- <addon.py> <out.glb> <out.png>
"""
import importlib.util
import json
import sys

import bpy

addon_path, out_glb, out_png = sys.argv[sys.argv.index("--") + 1:][:3]
spec = importlib.util.spec_from_file_location("blender_mcp", addon_path)
addon = importlib.util.module_from_spec(spec)
sys.modules["blender_mcp"] = addon
spec.loader.exec_module(addon)
addon.register()
server = addon.BlenderMCPServer(port=9876)          # not started: commands are called directly, like the socket does
report = {"blender": bpy.app.version_string}


def cmd(kind, **params):
    res = server.execute_command({"type": kind, "params": params})
    if res.get("status") != "success":
        raise SystemExit("LOKI_PROOF_FAIL %s: %s" % (kind, json.dumps(res)[:600]))
    return res.get("result")


report["ping"] = cmd("ping")
BUILD = r'''
import bpy, bmesh, math, random
from mathutils import Matrix, Vector
random.seed(7)
# context-free on purpose: MCP commands run from a timer, where bpy.context.object / most operators are missing
scene = bpy.data.scenes[0]
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
def mat(name, rgb, emit=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = 0.85
    if emit:
        key = "Emission Color" if "Emission Color" in b.inputs else "Emission"
        b.inputs[key].default_value = (*rgb, 1)
        b.inputs["Emission Strength"].default_value = emit
    m.diffuse_color = (*rgb, 1)
    return m
wood, bark, stone, fire, ember, grass = (mat("Wood", (0.42, 0.24, 0.12)), mat("Bark", (0.22, 0.13, 0.07)),
    mat("Stone", (0.45, 0.45, 0.48)), mat("Flame", (1.0, 0.45, 0.08), 6.0), mat("Ember", (1.0, 0.15, 0.02), 3.0),
    mat("Ground", (0.18, 0.30, 0.12)))
root = bpy.data.objects.new("Campfire", None); scene.collection.objects.link(root)
def obj(name, build, m, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    me = bpy.data.meshes.new(name); bm = bmesh.new(); build(bm); bm.to_mesh(me); bm.free()
    me.materials.append(m)
    o = bpy.data.objects.new(name, me); scene.collection.objects.link(o)
    o.location, o.rotation_euler, o.scale, o.parent = loc, rot, scale, root
    return o
cyl = lambda segs, r, d: (lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r, radius2=r, depth=d))
cone = lambda segs, r, d: (lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r, radius2=0, depth=d))
ico = lambda r: (lambda bm: bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r))
obj("Ground", cyl(24, 2.2, 0.1), grass, (0, 0, -0.05))
for i in range(9):                                     # ring of stones
    a = i / 9 * math.tau
    obj("Stone.%02d" % i, ico(0.22), stone, (math.cos(a) * 0.85, math.sin(a) * 0.85, 0.1), (0, 0, random.random() * 3), (1.2, 0.9, 0.7))
for i in range(5):                                     # logs leaning into a teepee
    a = i / 5 * math.tau
    obj("Log.%02d" % i, cyl(7, 0.07, 1.1), wood if i % 2 else bark, (math.cos(a) * 0.28, math.sin(a) * 0.28, 0.38),
        (0, math.radians(32), a + math.pi))
for i, (h, r) in enumerate(((0.95, 0.24), (0.7, 0.16), (0.5, 0.11))):   # low-poly flames
    obj("Flame.%d" % i, cone(6, r, h), fire if i == 0 else ember, (0.05 * i - 0.05, 0.04 * i, 0.25 + h / 2), (0, 0, i * 0.6))
def light(name, kind, loc, energy, color=(1, 1, 1), rot=(0, 0, 0)):
    ld = bpy.data.lights.new(name, kind); ld.energy = energy; ld.color = color
    o = bpy.data.objects.new(name, ld); scene.collection.objects.link(o); o.location = loc; o.rotation_euler = rot
    return o
light("Firelight", "POINT", (0, 0, 0.8), 220, (1, 0.55, 0.2)).parent = root
light("Moon", "SUN", (3, -3, 5), 1.2, (0.7, 0.8, 1.0), (math.radians(50), 0, math.radians(35)))
cd = bpy.data.cameras.new("Camera"); cam = bpy.data.objects.new("Camera", cd); scene.collection.objects.link(cam)
cam.location = (3.0, -3.2, 2.1)
cam.rotation_euler = (Vector((0, 0, 0.35)) - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam
w = bpy.data.worlds.get("Night") or bpy.data.worlds.new("Night"); w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.03, 0.06, 1)
scene.world = w
print(len([o for o in bpy.data.objects if o.type == "MESH"]), "meshes")
'''
report["build"] = cmd("execute_code", code=BUILD)
info = cmd("get_scene_info")
report["objects"] = info.get("object_count", len(info.get("objects", [])))
scene = bpy.context.scene
for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES", "BLENDER_WORKBENCH"):   # 4.2-4.x / 5.x+3.x / any
    try:
        scene.render.engine = eng
    except TypeError:                                   # not an engine in this Blender
        continue
    if eng == "CYCLES":
        scene.cycles.samples = 24
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    scene.render.filepath = out_png
    try:
        bpy.ops.render.render(write_still=True)
        report["render_engine"] = eng
        break
    except Exception as exc:  # noqa: BLE001 - e.g. no GPU context for Eevee: try the next engine
        report.setdefault("render_errors", []).append("%s: %s" % (eng, exc))
bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB", use_selection=False)
tris = sum(len(p.vertices) - 2 for o in bpy.data.objects if o.type == "MESH" for p in o.data.polygons)
report.update(triangles=tris, glb=out_glb, png=out_png if report.get("render_engine") else "")
print("LOKI_PROOF " + json.dumps(report))
