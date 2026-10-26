---
name: gameready-uv-bake
description: Stage 3 of blender-gameready - UV the new quads and bake the original's colour and surface detail (normal map) onto them.
---

# Stage 3: UVs and bake

`bake` {size: 2048, normal: true, folder}

For each `<name>__high` left by repair / retopo:
1. A fresh `LOKI_UV` layer on the new mesh (smart project, 66 degrees, small margin).
2. Base colour: the original's Base Color (texture or value) is wired to an Emission shader for the bake and put back
   after. (A plain DIFFUSE bake comes out black on metallic glTF materials - found on the PC, 2026-10-26 - because
   glTF's default metallic is 1.0.)
3. Normal map (normal=true): tangent space, Non-Color, wired through a Normal Map node - the AI model's small detail
   on the light quads.
4. Metallic / roughness: copied when they are plain values; textured ones become 0 / 0.7.
5. The original is removed; the textures are saved as PNGs and packed.

Check the result: `baked[].texture` and `baked[].normal` exist. Look at the beauty render: black or grey = the colour
bake missed (cage too small: the model moved or was scaled after retopo); speckles = rays crossing between close
parts (fingers, cloth on body).

`uv` {mode: "missing"} afterwards only touches meshes with no UVs - never re-unwrap a baked mesh (it scrambles the
texture).
