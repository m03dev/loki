---
name: gameready-retopo
description: Stage 2 of blender-gameready - rebuild an AI mesh as clean, even quads (voxel surface, QuadriFlow, Instant Meshes fallback, projected back), and read the topology report.
---

# Stage 2: retopology

`retopo` {faces: 8000, symmetric, voxel: 160, instant_meshes: <binary path, optional>}

What it does, per mesh:
1. Keeps the original as `<name>__high` (colour + detail source for the bake).
2. Applies scale, rebuilds a watertight voxel surface (diagonal / voxel), merges edges shorter than ~0.2 mm and
   recalculates normals until Blender's QuadriFlow check passes (`prep.rounds[-1].ok`). QuadriFlow refuses a mesh
   with any edge shorter than 1e-4 in local units - that is why AI meshes "fail as non-manifold" when they look fine.
3. QuadriFlow (seeds 0, 7, 42) -> `faces` quads. If it refuses: Instant Meshes (BSD) when its binary is set
   (LOKI_INSTANT_MESHES or instant_meshes=). If both fail: the clean voxel surface, decimated (`how: "voxel only"`).
4. Projects the quads back onto the voxel surface (shrinkwrap, relax, shrinkwrap).

Read the result (`objects.<name>`):

| Field | Pass |
|---|---|
| how | quadriflow or instant_meshes ("voxel only" = no quads: say so) |
| after.quad_pct | >= 95 |
| after.pole_pct | <= 8 (poles = verts with 3 or 5+ edges, where loops break) |
| after.nonmanifold / boundary | 0 / 0 |
| after.faces | within ~20% of `faces` |

Checked on the PC (Blender 5.2.3): a Forge fantasy character, 32,834 triangles, 0% quads, 92.6% poles ->
7,260 faces, 100% quads, 4.2% poles, 0 non-manifold, in ~6-12 s.

If it fails:
- prep never ok: raise `voxel` (200-240) for thin parts (capes, wings, fingers); lower it (120) for blobby shapes.
- thin parts got holes (cloth hems, ears): voxel too coarse - raise `voxel`.
- too blurry: more `faces`; detail comes back as the normal map in stage 3 anyway.
- Max 3 tries, one change each.

Limits: even quads, not hand-made edge loops (eye / mouth rings, extra loops at elbows and knees). Fine for games,
props, rigging tests; facial animation needs a human pass or QuadWild with guides (LOKI_TASKS.md).
