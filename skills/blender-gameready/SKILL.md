---
name: blender-gameready
description: Turn an AI-made 3D model (TRELLIS, Pixal3D, Hunyuan, TripoSR, a free asset) into a workable game asset in Blender - clean quad topology, UVs, baked colour + normal map, FBX/GLB/glTF - and prove it with numbers and renders. Use whenever a model must be edited, rigged, animated, exported, or "cleaned up".
---

# Game-ready in Blender (router)

AI meshes are triangle soup: 0% quads, ~90% poles, holes, flipped faces, floaters. They render but cannot be edited,
rigged or animated. This pipeline rebuilds them. Every stage is a LOKI Blender command (engine/blender_link.py ->
engine/blender_scripts/loki_blender_core.py), run through the `blender` tool.

## The one call that does it all

`blender` action=polish, path=models/<file>.glb, retopo=8000 (quads; 3000 a prop, 8000 a creature, 15000 a hero),
symmetric=true for front-facing creatures. Result: `topology` {verdict, quad_pct, pole_pct, faces, retopo}, `quality`,
files (.glb .gltf .fbx .blend + LODs + a render). Forge's Clean up button and every new Forge model do the same.

## Stages (one skill each - load the one you are on)

| # | Stage | Commands | Gate to pass before the next |
|---|---|---|---|
| 1 | gameready-cleanup | import, cleanup, normalize, repair | one main shell (largest_share >= 0.85), verdict not "garbage" |
| 2 | gameready-retopo | retopo | `quads: true`, quad_pct >= 95, pole_pct <= 8, nonmanifold 0 |
| 3 | gameready-uv-bake | bake (normal=true), uv | baked colour not black, normal map written |
| 4 | gameready-qa | topology, render, export, lods | SHIP / NO-SHIP verdict with numbers + renders |

Custom chains: action=run, commands=[{type, params}] with the same types (each params needs `scene`).

## Rules

- Never claim. Show the `topology` JSON and a beauty + wireframe render (the report in gameready-qa).
- Keep the original: retopo leaves it as `<name>__high`; bake uses it; export never ships it.
- Free assets (assets/ from free_assets) must be changed (`edits`) before export - never shipped as they are.
- Try at most 3 times per stage (change one thing: faces, voxel, symmetric). Then NO-SHIP with the reasons.
- Numbers decide hard failures; looks (silhouette, seams, colour) are judged on the renders.
- Automatic retopology gives clean, even quads - not artist edge loops around eyes, mouth and joints. Say so when a
  model is meant for close-up facial animation: that still needs a human pass.

## Budgets (triangles, quads x2)

Prop 1-6k, creature / NPC 15-40k, hero 50-100k, mobile hero 15-30k. LODs 100 / 50 / 20 %.
