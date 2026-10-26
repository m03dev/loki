---
name: gameready-qa
description: Stage 4 of blender-gameready - measure the finished model (topology report), render it, export GLB/glTF/FBX/.blend + LODs, and give a SHIP / NO-SHIP verdict with proof.
---

# Stage 4: QA and export

1. `topology` - per mesh: faces, quad_pct, tri_pct, ngons, poles, pole_pct, nonmanifold, boundary, sliver_pct,
   uv_layers, verdict ("quads" / "mixed" / "soup").
2. `shade`, `stage` {style: studio}, `render` {path: renders/<name>.png}.
3. A wireframe view: action=run with a python command that copies each mesh with a WIREFRAME modifier (thickness
   ~0.1% of the size, dark material) and renders again to renders/<name>_wire.png.
4. `export` {path} for .glb, .gltf, .fbx, .blend; `lods` {stem, ratios: [1, 0.5, 0.2]}.

## Verdict

SHIP when all hold:
- topology verdict "quads", quad_pct >= 95, pole_pct <= 8, nonmanifold 0;
- triangles (faces x2) inside the budget for its kind;
- the beauty render shows the colours (not black, not grey) and the silhouette matches the source picture;
- the files exist: .glb, .gltf, .fbx (+ LODs).

Otherwise NO-SHIP, listing each failed line with its number and what to try (stage 2's table).

## Report (what the owner sees)

```
<name>: SHIP
  before: 32,834 tris, 0% quads, 92.6% poles (soup)
  after:  7,260 quads, 100% quads, 4.2% poles, 0 non-manifold (QuadriFlow, 9 s)
  files:  models/<name>.glb .gltf .fbx .blend, LODs 50/20%
  renders: renders/<name>.png, renders/<name>_wire.png
```

Show the renders in the reply. Never write "should work": say where it ran (PC / Mac / cloud).
