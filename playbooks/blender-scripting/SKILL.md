---
name: blender-scripting
description: Build, light and render a prop or scene from scratch in Blender, live in a session, step by step (bpy) - models that hold together, sit on the ground, are framed by the camera and checked by LOKI's scene inspector.
---
# Blender scripting - props and scenes that hold together

Written from what went wrong in LOKI's first real jobs (floating lids, flames outside the frame, crashes on Blender 5.2).

**Use the `build` tool for any object.** Write a part spec - what each part is, its size, what it sits on - and LOKI
does every coordinate, bevel, material, light and render. Parts attach face to face, so nothing floats. Think like a
modeller: main body first, then what sits on it, then details (rims, bands, handles, feet). Real sizes in metres.

```json
{"name": "lantern", "materials": {"brass": "brass", "glass": "glass", "flame": {"color": "#ffb347", "emit": 8}},
 "parts": [
  {"id": "base",   "shape": "lathe",    "size": [0.20, 0.20, 0.04], "mat": "brass", "profile": [[0.5,0],[0.5,0.3],[0.44,0.45],[0.44,1]]},
  {"id": "glass",  "shape": "tube",     "size": [0.15, 0.15, 0.22], "mat": "glass", "on": "base", "at": "top", "wall": 0.003},
  {"id": "post",   "shape": "cylinder", "size": [0.014, 0.014, 0.22], "mat": "brass", "on": "base", "at": "top", "repeat": {"count": 4, "around": 0.08}},
  {"id": "band",   "shape": "torus",    "size": [0.17, 0.17, 0.012], "mat": "brass", "on": "base", "at": "top", "offset": [0, 0, 0.1]},
  {"id": "collar", "shape": "cylinder", "size": [0.19, 0.19, 0.02], "mat": "brass", "on": "glass", "at": "top"},
  {"id": "cap",    "shape": "cone",     "size": [0.21, 0.21, 0.09], "mat": "brass", "on": "collar", "at": "top", "top": 0.18},
  {"id": "ring",   "shape": "torus",    "size": [0.08, 0.08, 0.012], "mat": "brass", "on": "cap", "at": "top", "rotate": [90, 0, 0]},
  {"id": "burner", "shape": "cylinder", "size": [0.05, 0.05, 0.03], "mat": "brass", "on": "base", "at": "top"},
  {"id": "flame",  "shape": "sphere",   "size": [0.025, 0.025, 0.055], "mat": "flame", "on": "burner", "at": "top"}]}
```
A chest: body `shell` (open top, "wall"), `band` on the body (count 2, iron), lock plate `box` on the body "front"
"align": "top", lid `barrel` on the body "top" with "hinge": {"edge": "back", "angle": 105}, `band` on the lid,
treasure `heap` on the body "inside" with no size (it takes the body's shape and fills to just over the rim; "pieces": "coin" or "ball"). Metals shine, they never need "emit".
A stool or table: seat `cylinder`/`box`, legs on the seat "bottom" with "repeat": {"count": 3, "around": 0.11,
"splay": 12}, rungs `rod` "between": "leg", "height": 0.35. Never place a part with offsets when an anchor says it.
After building, `look` at renders/<name>_views.png, fix the spec (sizes, what's missing) and build again.

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
