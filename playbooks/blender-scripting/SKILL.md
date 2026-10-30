---
name: blender-scripting
description: Build, light and render a prop or scene from scratch with a Blender Python script (bpy) - models that hold together, sit on the ground, are framed by the camera and checked by LOKI's scene inspector.
---
# Blender scripting - props and scenes that hold together

Written from what went wrong in LOKI's first real jobs (floating lids, flames outside the frame, crashes on Blender 5.2).

**Script shape** (one script makes everything; run: `blender --background --python scripts/x.py`)
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
- `look:renders/x.png` - a vision model compares the render with the brief and scores it; fix what it lists.
