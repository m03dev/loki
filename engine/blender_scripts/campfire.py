# A low-poly campfire, built from scratch into the job's own scene (`scene` is given by loki_blender_core.cmd_python).
# Context-free on purpose (bmesh + bpy.data, no bpy.ops), and it never deletes anything outside its own scene.
import math
import random

import bmesh
import bpy
from mathutils import Vector

random.seed(7)
for o in list(scene.objects):                          # noqa: F821 - only this job's own scene is cleared
    bpy.data.objects.remove(o, do_unlink=True)


def mat(name, rgb, emit=0.0):
    m = bpy.data.materials.get("LOKI " + name) or bpy.data.materials.new("LOKI " + name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = 0.85
    if emit:
        key = "Emission Color" if "Emission Color" in b.inputs else "Emission"
        b.inputs[key].default_value = (*rgb, 1)
        b.inputs["Emission Strength"].default_value = emit
    m.diffuse_color = (*rgb, 1)
    return m


wood, bark, stone = mat("Wood", (0.42, 0.24, 0.12)), mat("Bark", (0.22, 0.13, 0.07)), mat("Stone", (0.45, 0.45, 0.48))
fire, ember, grass = mat("Flame", (1.0, 0.42, 0.06), 2.2), mat("Ember", (0.95, 0.12, 0.02), 1.6), mat("Ground", (0.18, 0.30, 0.12))
root = bpy.data.objects.new("Campfire", None)
scene.collection.objects.link(root)                   # noqa: F821


def obj(name, build, m, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(m)
    o = bpy.data.objects.new(name, me)
    scene.collection.objects.link(o)                  # noqa: F821
    o.location, o.rotation_euler, o.scale, o.parent = loc, rot, scale, root
    return o


def cyl(segs, r, d):
    return lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r, radius2=r, depth=d)


def cone(segs, r, d):
    return lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r, radius2=0, depth=d)


def ico(r):
    return lambda bm: bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r)


obj("Ground", cyl(24, 2.2, 0.1), grass, (0, 0, -0.05))
for i in range(9):                                     # a ring of stones
    a = i / 9 * math.tau
    obj("Stone.%02d" % i, ico(0.22), stone, (math.cos(a) * 0.85, math.sin(a) * 0.85, 0.1), (0, 0, random.random() * 3),
        (1.2, 0.9, 0.7))
for i in range(5):                                     # logs leaning into a teepee
    a = i / 5 * math.tau
    obj("Log.%02d" % i, cyl(7, 0.07, 1.1), wood if i % 2 else bark, (math.cos(a) * 0.28, math.sin(a) * 0.28, 0.38),
        (0, math.radians(32), a + math.pi))
for i, (h, r) in enumerate(((0.95, 0.24), (0.7, 0.16), (0.5, 0.11))):   # low-poly flames
    obj("Flame.%d" % i, cone(6, r, h), fire if i == 0 else ember, (0.05 * i - 0.05, 0.04 * i, 0.25 + h / 2), (0, 0, i * 0.6))


def light(name, kind, loc, energy, color=(1, 1, 1), rot=(0, 0, 0)):
    ld = bpy.data.lights.new("LOKI " + name, kind)
    ld.energy, ld.color = energy, color
    o = bpy.data.objects.new(name, ld)
    scene.collection.objects.link(o)                  # noqa: F821
    o.location, o.rotation_euler = loc, rot
    return o


light("Firelight", "POINT", (0, 0, 0.8), 220, (1, 0.55, 0.2)).parent = root
light("Moon", "SUN", (3, -3, 5), 1.2, (0.7, 0.8, 1.0), (math.radians(50), 0, math.radians(35)))
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("LOKI Camera"))
scene.collection.objects.link(cam)                    # noqa: F821
cam.location = (3.0, -3.2, 2.1)
cam.rotation_euler = (Vector((0, 0, 0.35)) - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam                                    # noqa: F821
w = bpy.data.worlds.get("LOKI Night") or bpy.data.worlds.new("LOKI Night")
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.03, 0.06, 1)
scene.world = w                                       # noqa: F821
result = {"meshes": sum(o.type == "MESH" for o in scene.objects)}   # noqa: F821
