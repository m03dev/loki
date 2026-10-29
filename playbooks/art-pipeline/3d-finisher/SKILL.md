---
name: 3d-finisher
description: Make a generated mesh game-ready in Blender - retopology, UVs, baked maps, LODs, exports.
---
# 3D Finisher - game-ready in Blender

1. **Retopology**: clean quads (>= 95%), poles <= 8%, edge loops around eyes, mouth, joints; target face count by kind
   (character ~8k, creature ~8k, prop ~2k).
2. **UVs**: seams in hidden places, no overlaps, uniform texel density, 4 px padding.
3. **Bake**: high -> low: base colour and normal map (2048), optional AO.
4. **LODs**: LOD1 50%, LOD2 25%.
5. **Exports**: .glb .gltf .fbx .blend, scale 1 = 1 m, +Y up.
6. **QA**: report quad %, poles %, face count, UV overlap, file sizes.
Uses the library skills blender-gameready (cleanup, retopo, uv-bake, qa).
