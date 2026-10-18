# Cozy Blanket (and Uniform) - research for Forge

The owner (2026-10-17): "add cozy blanket like 1:1, research, made in godot".

## What it is

- **CozyBlanket** is an iPad app by **Sparseal** (Pablo Dobarro, former Blender sculpt-tools lead,
  and Joan Fons, a Godot Engine contributor) for **retopology**: drawing a clean low-poly mesh over
  a high-resolution sculpt or photoscan. 2.0 added **UV unwrapping** and **baking**.
- **Commercial and closed source.** Free to download; saving/export is an in-app purchase
  ($19.99 unlock, $89.99 standard licence for 2.0, per 80.lv). No public source code or licence that
  would let LOKI take code or assets: **LOKI copies nothing from it** (AGENTS.md: no proprietary code).
- **"Made in Godot":** public articles do not say CozyBlanket is built on Godot. Its sister app
  **Uniform** (Sparseal's iPad sculpt/paint/retopo app, released May 2024, $49.99) *is*: Dobarro
  described it as "coded as a Godot 4 C++ module" using Godot's build system and RenderingDevice
  (80.lv). Likely the owner means one of the two (or both); this note covers both. Unverified:
  whether CozyBlanket 2.x shares Uniform's Godot base.

Sources: cgchannel.com (2022-05, 2023-11, 2024-05 Uniform 1.0), 80.lv (CozyBlanket 1.1, 1.3, 2.0
announced/released, Uniform pre-alpha), apps.apple.com/app/id1608079174.

## Workflow and UI ideas (from public pages)

CozyBlanket 2.0:
- **Three stages** in one app - Retopology -> Unwrapping -> Baking - and the same gestures mean
  the matching thing in each stage (tools change behaviour, the mesh is drawn differently).
- **Retopology by drawing:** pencil strokes on the high-res "target" surface make edge flows;
  *Build* (new quads), *Draw Strips*, *Extend Boundary* (ExtendB), *Bridge*, *PathD* (straighten a
  run of vertices), *SurfCut* (an arbitrary cut), *Relax*, *Move* with falloff measured across the
  surface, *Tweak*, vertex **pins**, merge vertex pairs, slide edges, split/merge faces.
- **Snapping** of new vertices to the target surface; hold an extra finger to snap to target
  vertices; symmetry.
- **Viewport:** smooth-shaded target with vertex colours/polypaint, the retopo mesh as a
  semi-transparent overlay with a GPU wireframe; multiple viewports side by side; a separate fast
  viewport for multi-million-polygon scans.
- **UVs:** draw/erase/extend **seams by drawing over edges in 3D**; Tweak moves/rotates/scales
  islands; grid, pixel and symmetry snapping; straighten UV grids, copy UVs between islands,
  automatic symmetrize and unfold; a tileable checker texture to judge stretch.
- **Baking:** tangent-space normal map + colour map from target to low-poly; cage editing (Tweak,
  Relax, Erase); a side-by-side target/bake view with a movable light; export a ZIP of maps + OBJ + MTL.
- **Touch-first, game-like feel** ("solving a puzzle"); customizable UI; finger or pen.
- A Python network API pulls the model, textures and UVs into desktop apps.

Uniform adds: volume sketching, sculpt brushes with stamps/alphas/VDMs, polypaint and texture
paint that work on the sculpt *and* the UV-unwrapped low-poly in one stroke (displacement baked in
real time), a layer stack with masks, PBR + NPR viewport with an on-screen shading-quality control,
OBJ/glTF with textures.

## How Forge can offer the same experience (our own code)

Forge is `app/ui/forge.js` + `engine/forge3d.py` (three.js viewer, sculpt brushes; another agent is
adding more sculpting and a Material Maker node editor). Concrete features, in build order:

1. **Stage bar: Sculpt / Retopo / UV / Bake / Paint** at the top of Forge; one tool set whose
   behaviour follows the stage (CozyBlanket's core idea), keyboard 1-5.
2. **Target + overlay:** the current sculpt becomes a locked, smooth-shaded "target"; a new
   retopo mesh draws over it semi-transparent with a wireframe (three.js `LineSegments` from an
   edge list, depth-offset), plus a toggle to hide either.
3. **Surface-snapped drawing:** raycast pointer strokes onto the target (BVH over the triangles),
   resample to an even spacing, and turn strokes into edge loops; *Build* closes 4 picked points
   into a quad; *Strip* makes a quad strip along a stroke with a width; *Extend* grows a boundary;
   *Bridge* joins two boundaries with the same vertex count.
4. **Relax / Move / Slide / Pin:** Laplacian relax of free vertices re-projected onto the target
   each step; Move with geodesic falloff (Dijkstra over the target's edges); pinned vertices never
   move; symmetry across X.
5. **Retopo mesh model:** a half-edge quad mesh in a Web Worker (`forge_retopo_worker.js`) with
   undo as snapshots; export .obj/.glb of the low-poly; tests on fixtures (quad count, manifold,
   undo restores exactly - as in EVOLVE E17).
6. **Seams by drawing:** strokes near target edges mark seams; islands from seams; unfold with
   LSCM (least-squares conformal maps, a small sparse solver in the worker); checker texture to
   show stretch; island Tweak (move/rotate/scale) in a 2D UV panel; grid snapping.
7. **Bake:** normal + base-colour maps by raycasting from the low-poly (with a cage offset) to the
   target on the GPU (a WebGL render-to-texture pass in UV space) or in the worker for small sizes;
   preview side by side with a draggable light; export maps + OBJ + MTL as one zip.
8. **Paint through to the low-poly:** Forge's paint brushes write to the baked texture as well as
   vertex colours, so one stroke updates both (Uniform's idea), feeding the Material Maker graph.
9. **Hand-off:** "Send to Godot" puts the low-poly .glb + maps into the project's assets via
   `engine/godot_assets.py` (EVOLVE E18), so a scan or sculpt becomes a game-ready asset.

Keep the window fast: heavy steps (BVH, relax, LSCM, bake) in Web Workers; nothing new vendored
except what is MIT/BSD/Apache and recorded in docs/THIRD_PARTY.md.
