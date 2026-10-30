---
name: blender-scripting
description: Build, light and render a prop or scene from scratch with a Blender Python script (bpy) - models that hold together, sit on the ground, are framed by the camera and checked by LOKI's scene inspector.
---
# Blender scripting - props and scenes that hold together

Written from what went wrong in LOKI's first real jobs (floating lids, flames outside the frame, crashes on Blender 5.2).

**Kits first.** If loki_bpy has a kit for the object, use it - kits are whole objects built and checked from four
sides, with real hinges and joints: `chest(...)` (open_deg, domed, hoard, size, your own materials). Only build from
parts what no kit covers, and never a hinged thing without hinge hardware.

```python
from loki_bpy import *
start(__file__)
ground(6, pbr("Floor", "rough_concrete", fallback="#4a4744"))
chest("Chest", width=0.8, open_deg=105, domed=True, hoard=80)
frame(); lights(); finish("chest")
```

**Use loki_bpy** (it is in every job's scripts/ folder): it places parts by their measured bounds, hinges lids on a
real edge, frames the camera from the scene's bounds and renders with the right engine for this Blender. A whole chest:

```python
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from loki_bpy import *
start(__file__)
wood = pbr("Wood", "wood_planks", scale=2)              # a real scanned surface (Poly Haven, CC0), never a flat colour
iron = pbr("Iron", "rusty_metal_02", fallback="#4a4f55", metal=1.0)
gold = mat("Gold", "#d4a017", metal=1.0, rough=0.25)
ground(6, pbr("Floor", "rough_concrete", fallback="#4a4744"))
body = tray("Body", (0.8, 0.5, 0.45), wall=0.04, material=wood, bevel=0.01)   # open-top: things go IN it
lid = box("Lid", (0.82, 0.52, 0.1), wood, bevel=0.015); place_on(lid, body)
for z in (0.08, 0.32):
    ring(f"Band{z}", (0.82, 0.52, 0.05), wall=0.012, material=iron, at=(0, 0, z))  # bands wrap the sides only
plate = box("Lock", (0.1, 0.02, 0.12), gold, bevel=0.004); place_beside(plate, body, side="-y", align="top")
coins(body, 60, gold, fill=0.8)          # in a tray it lays a gold bed first, so the heap rests on something
hinge(lid, edge="+y", angle=55)          # back hinge (+y), front lifts; the camera looks from -y (the front)
frame(); lights(); finish("chest")       # lights() = studio HDRI + three-point; finish() also writes chest_views.png
```

**Quality, in order of what matters** (from research on LLM-made 3D: LL3M, BlenderLLM, BlenderRAG):
- Real surfaces: `pbr(name, asset)` loads a Poly Haven scan (wood_planks, rusty_metal_02, brick_wall_001,
  rock_face, forest_ground_01, rough_concrete, painted_plaster_wall ...); unknown or offline -> a flat `fallback`.
  `hdri("studio_small_09")` (in lights()) gives real reflections; outdoors try "kloofendal_48d_partly_cloudy".
- Real shapes: tray() for anything that holds things, ring() for bands and frames, planks() for wood panels,
  bevel every hard edge. A solid block with things on top reads as a toy.
- Check every side: `renders/<name>_views.png` (front, right, back, above) is what the `look:` check scores - a part
  floating at the back fails it. Look at the sheet yourself before you call a step done.

**Script shape without the helpers** (one script makes everything; run: `blender --background --python scripts/x.py`)
1. Start clean: `bpy.ops.wm.read_factory_settings(use_empty=True)`; real units (metres): a chest ~0.8 x 0.5 x 0.5.
2. Paths from the script's own folder: `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`;
   `os.makedirs(os.path.join(ROOT, "renders"), exist_ok=True)`. Never relative `//` paths (they follow the .blend).
3. Build in this order: ground, main body, then parts placed FROM the body's measured bounds (top = body z + height/2),
   so parts touch. A lid sits on the body (rotate it open around a hinge at the body's back-top edge, `origin_set`
   or parent to an empty at the hinge) - never place parts by guessed numbers.
4. Shape, not boxes: Bevel modifier (width 0.01-0.03, segments 2-3) on hard edges; Solidify for planks/bands; Array for
   repeats (planks, coins, tiles); a few loop cuts + slight random offsets for hand-made wear. Apply scale.
5. Materials: Principled BSDF for every mesh (base colour, roughness, metallic 1.0 for gold/iron); emission strength
   3-10 for fire. Every visible mesh gets a material.
6. Camera: frame from the scene's bounds - aim at the bounds centre (Track To constraint on an empty), distance so
   the subject fills ~70% of the frame height, 50-85 mm lens. Everything the brief names must be inside the frame.
7. Light: three-point (key warm 45 deg front-left strongest, fill cool at 1/3, rim behind) or a sun + world colour.
8. Save the .blend, then render: `scene.render.filepath = ...; bpy.ops.render.render(write_still=True)`.

**Blender 5.2 API facts** (each one crashed a real job)
- Render engine is `'BLENDER_EEVEE'` (not `BLENDER_EEVEE_NEXT`); `scene.eevee.use_gtao` no longer exists.
- Circles: `bpy.ops.mesh.primitive_circle_add(vertices=32, radius=r, fill_type='NGON')`.
- `Material.use_nodes` is deprecated (still works); new materials already have a Principled node.

**Prove it** (the driver checks these; plan tasks with them):
- `blend:scenes/x.blend` - LOKI's inspector: fails on floating parts, no camera, empty scene; reports parts outside
  the frame and missing materials. Fix every error it lists.
- `look:renders/x.png` - a vision model scores the four-view sheet (renders/x_views.png) against the brief; fix
  everything it lists, then render again.
