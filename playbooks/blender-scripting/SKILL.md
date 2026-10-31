---
name: blender-scripting
description: Build, light and render a prop or scene from scratch in Blender, live in a session, step by step (bpy) - models that hold together, sit on the ground, are framed by the camera and checked by LOKI's scene inspector.
---
# Blender scripting - props and scenes that hold together

Written from what went wrong in LOKI's first real jobs (floating lids, flames outside the frame, crashes on Blender 5.2).

**Work live, step by step** (the way the best agents on the BlenderWorld benchmark work): use the `session` tool with
kind `blender`. The scene stays open between calls, so build one part, check it, adjust, then the next:

```python
# call 1                                         # call 2: check before moving on
start()                                          scene()          # names, sizes, positions
wood = pbr("Wood", "wood_planks", scale=2)       # call 3: look from four sides when a part is in place
body = tray("Body", (0.8, 0.5, 0.45), wall=0.04, material=wood, bevel=0.01)
ground(6, mat("Floor", "#4a4744", rough=0.9))    look("step1")    # -> renders/step1_views.png, then `look` it
# ... more parts, measured from the ones before (place_on, place_beside, hinge) ...
save("scenes/chest.blend"); finish("chest")      # final render + four-view sheet
```
Look at your own views about every few parts (not after every line - effective feedback beats lots of it).
Everything sizes in metres; parts stand on their bottom centre; +y is the back, the camera looks from -y.

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
