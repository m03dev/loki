---
name: 3d-artist
description: Turn an orthographic front view into a textured 3D mesh and check it against the side and back views.
---
# 3D Artist - image to mesh

1. **Input**: the turnaround's FRONT view (clean background) is the mesh source; side and back are the check.
2. **Engine order**: TRELLIS.2 (ComfyUI on the PC) first, Pixal3D second, TripoSR / online only as fallback.
3. **Target**: watertight textured .glb, real-world scale (metres), +Y up, facing -Z, origin at the feet.
4. **Check**: silhouette from the side and back matches those views; no floating fragments; triangle count above
   the stage minimum; texture is not smeared across the back.
5. **Hand-off**: the .glb, the engine and seed used, and what does not match yet.
