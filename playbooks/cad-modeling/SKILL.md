---
name: cad-modeling
description: Model a 3D object as real CAD solids with build123d or FreeCAD (exact sizes, joints, fillets, booleans), then render it in Blender with cad_render.py - props, furniture, tools, weapons, chests, buildings, machines.
---
# CAD modeling - real solids, then a render

Build the object in CAD (millimetres), one STL per material in `parts/`, then render with `scripts/cad_render.py`.
CAD does the geometry exactly (no floating parts: things are unioned, cut and placed by dimensions); Blender only adds
material, light and camera. Plan these steps:

1. `scripts/model.py` - the CAD script (template below). Name every number (W, D, H, wall ...) at the top.
2. Run it: build123d `"<LOKI_CAD_PY>" scripts/model.py`, FreeCAD `"<LOKI_FREECAD>" scripts/model.py` (exact paths are
   in MACHINE TOOLS). It must print `valid: True`.
3. Render: `"<blender>" --background --python-exit-code 1 --python scripts/cad_render.py -- parts <name>` ->
   renders/<name>.png, renders/<name>_views.png (four sides), renders/<name>_info.json.
4. Checks: `file:renders/<name>_info.json` and `look:renders/<name>.png` (the vision check reads the four-view sheet).

Part file names pick the material: wood, oak, iron, steel, gold, brass, copper, stone, brick, concrete, leather, fabric,
glass, plastic, rubber, a colour (red, blue ...) or a hex (`b8322c.stl`). Several parts may share one file.

**build123d** (algebra mode: `+` union, `-` cut, `Pos(x,y,z) * shape`, `Rot(x,y,z) * shape`)
```python
import os
from build123d import *
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "parts"); os.makedirs(OUT, exist_ok=True)
W, D, H, WALL = 800, 500, 420, 30
BASE = (Align.CENTER, Align.CENTER, Align.MIN)                 # stand on z=0
body = Box(W, D, H, align=BASE)
body = fillet(body.edges().filter_by(Axis.Z), 12)              # round the vertical edges
body -= Pos(0, 0, WALL) * Box(W - 2 * WALL, D - 2 * WALL, H, align=BASE)   # hollow it
lid = Pos(0, 0, H) * Box(W, D, 60, align=BASE)
pivot = (0, D / 2, H)                                          # hinge line along X at the back top edge
lid = Pos(*pivot) * Rot(-100, 0, 0) * Pos(-pivot[0], -pivot[1], -pivot[2]) * lid   # opened 100 degrees
handle = Pos(0, -D / 2 - 15, H * 0.6) * Rot(90, 0, 0) * Torus(40, 8)
for name, shapes in {"wood": [body, lid], "iron": [handle]}.items():
    export_stl(Compound(children=shapes), os.path.join(OUT, f"{name}.stl"), tolerance=0.3, angular_tolerance=0.2)
print("valid:", all(s.is_valid for s in [body, lid, handle]))
```
Useful: `Cylinder(r, h)`, `Sphere(r)`, `Cone(r1, r2, h)`, `Torus(R, r)`, `extrude(Plane.YZ * Ellipse(a, b), amount=L/2, both=True)`,
`chamfer(edges, d)`, `scale(shape, (sx, sy, sz))`, `revolve(Plane.XZ * Polyline(...) ...)`, `mirror(shape, Plane.YZ)`.

**FreeCAD** (headless; `Part.makeBox(x, y, z, Vector(corner))`, `.fuse()`, `.cut()`, `.makeFillet(r, edges)`)
```python
import os, Part, MeshPart
from FreeCAD import Vector as V
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "parts"); os.makedirs(OUT, exist_ok=True)
W, D, H, WALL = 800, 500, 420, 30
def box(x, y, z, at=(0, 0, 0)): return Part.makeBox(x, y, z, V(at[0] - x / 2, at[1] - y / 2, at[2]))
body = box(W, D, H)
body = body.makeFillet(12, [e for e in body.Edges if abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) > 1]).cut(box(W - 2 * WALL, D - 2 * WALL, H, (0, 0, WALL)))
lid = box(W, D, 60, (0, 0, H)); lid.rotate(V(0, D / 2, H), V(1, 0, 0), -100)
for name, shapes in {"wood": [body, lid]}.items():
    MeshPart.meshFromShape(Shape=Part.makeCompound(shapes), LinearDeflection=0.3, AngularDeflection=0.2).write(os.path.join(OUT, f"{name}.stl"))
print("valid:", all(s.isValid() for s in [body, lid]))
```
Useful: `Part.makeCylinder(r, h, V(base), V(dir))`, `Part.makeSphere(r)`, `Part.makeCone(r1, r2, h)`, `Part.makeTorus(R, r)`,
`shape.rotate(V(pivot), V(axis), deg)`, `shape.translate(V(x, y, z))` (both change the shape), `shape.copy()`.

**What makes it good:** real proportions in mm; hollow what holds things; round or chamfer every outside edge (2-15 mm);
joints that really touch (hinge pins on the hinge line, legs into the seat); detail as cut grooves, studs, rims, bands;
coins and loose things rest on a surface you computed, never at a guessed height.
