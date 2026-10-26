---
name: gameready-cleanup
description: Stage 1 of blender-gameready - import an AI model, size it, remove floaters, fill holes, fix normals, and score how broken it is before retopology.
---

# Stage 1: clean up

Commands (blender action=run, all with the same `scene`):

1. `clear` - empty the job's own scene (never the owner's).
2. `import` {path} - .glb .gltf .obj .fbx .stl .ply .usd*. Note `triangles` and `free_asset`.
3. `cleanup` - merge doubles, delete loose verts/edges.
4. `normalize` {size: 2.0} - tallest side = size metres, feet on the ground, centred.
5. `repair` {symmetric, remesh: false when retopo follows} - drops floaters (< 2% of the area), fills holes up to 64
   sides, recalculates normals; returns before/after numbers and a verdict.

Read `repair`'s numbers:

| Number | Good | Means when bad |
|---|---|---|
| largest_share | >= 0.85 | broken into pieces - the model may be several objects; check the render |
| open_ratio | <= 0.01 | holes / torn surface - retopo's voxel pass will close it |
| thin_ratio | <= 0.2 | sliver triangles - normal for AI soup |
| noise_deg | <= 12 | bumpy, marching-cubes surface - repair smooths it |
| verdict | clean / rough | garbage: < 500 faces or 3+ problems - regenerate instead of fixing |

Gate: verdict is not "garbage". A garbage model is not worth retopology - make it again (Forge make, a better
picture, another backend) and say why.

Symmetric creatures (seen from the front): pass symmetric=true here and in retopo. Do not for asymmetric things
(a creature holding a sword in one hand).
