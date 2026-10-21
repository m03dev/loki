# Forge - UV, Retopology and Baking workspaces (plan + status)

Owner 2026-10-21 04:30-04:41: LOKI turns towards "game engine, render studio, AI farm hive". Alpaca3D (Retopology,
UV and Bake "labs") is Windows-only and closed source (its licence keeps the code with its author), so Forge gets
those features rebuilt - "those all go into Forge, don't make them their own thing ... a tab within Forge like a
workspace ... camera based, then select edges, cut, select UV shell, unfold and layout ... settings ... everything
modular, a real system, not placeholders". Then: "https://github.com/danielboxer/UVgami use that code" - UVgami is
GPL-3.0 (compatible with LOKI's AGPL-3.0); its CPU engines are OptCuts (MIT) and xatlas (MIT). Its GPU engine
(PartUV) is non-commercial and is NOT used.

## Workspaces (top right of Forge: Workspace)

| Workspace | What | Status |
| --- | --- | --- |
| Modeling | the viewport, Outliner, Channel Box (what Forge was) | done |
| UV Editing | the viewport + the UV Editor beside it (resizable, %) | phase 1 - this file |
| Retopology | a live low-poly drawn over the high-poly / sculpt (quad draw, relax, symmetry), live bake preview | phase 2 |
| Baking | high -> low maps: normal, AO, curvature, thickness, position, ID; automatic cage + cage editing; export | phase 3 |

## Phase 1: UV Editing

**Data** (app/ui/forge_uv.js, `window.ForgeUV`): the pro tool's map UVs on the modelled cage - `uv` points and
`fuv` (per face, one UV index per corner). Seams are implicit (adjacent faces with different UV indices), shells are
faces joined through shared UV indices. Every operation returns a new cage, so undo is Forge's normal cage undo.
The GPU mesh is one vertex per face corner (forge.js showPoly), so seams need nothing special. Modelling steps keep
UVs (`carry`): faces that survive keep their UV indices exactly; new faces get a small planar map off to the side
(listed in `uvNew`, flagged in the editor). Exports (glTF, OBJ ...) take the GPU mesh's UVs.

**Operations** (JS unless marked C++):
- Create UVs: Camera-based (the viewport's projection), Planar (best plane / X / Y / Z), Cylindrical, Spherical,
  Automatic (3 / 4 / 6 planes, then Layout). On the selected faces, else all.
- Cut / Sew / Move and Sew on the viewport's edge selection (a cut opens a shell once it reaches a border or seam).
- Unfold (C++, native/sculpt uv_unwrap.cpp: LSCM + ARAP iterations, pins kept, world scale) - `ForgeGeom.uvUnfold`.
- Layout (C++: rotate to the tightest box, uniform texel density, skyline packing, padding in px at a texture size)
  - `ForgeGeom.uvLayout`; a plain JS shelf packer (`ForgeUV.layoutBasic`) when the engine build lacks it.
- Auto Unwrap (C++, xatlas: charts + parameterization + packing) - `ForgeGeom.uvAuto` (in progress).
- OptCuts (C++ -> its own WebAssembly module, joint seams + distortion bound) - in progress (native/optcuts).
- UVgami's seam intelligence ported to JS (hard-surface seams, seam pipeline, symmetry, rectify, reroute, similar
  islands) - app/ui/forge_uvgami.js (in progress), docs/FORGE_UVGAMI.md.
- Transform: move / rotate / scale by dragging (w / e / r over the editor), flip U / V, rotate 90, pin / unpin.
- Texel density get / set (px per unit at a texture size), distortion shading (stretch, flipped), a checker on the
  model, select faces / shells (double-click) / UV points, box select with Shift / Ctrl like the viewport.

**Settings** (the gear; localStorage `loki-forge-uv`): unfold iterations; layout padding px, texture size, rotate
(none / 90 / free), scale (uniform density / keep / none), margin; planar axis, cylinder axis, automatic planes;
density px per unit + texture size; checker tiles, grid, snap moves to pixels.

**Tests**: tests/js/test_forge_uv.js (the model, node), tests/test_forge_uv_ui.py (the workspace in Chromium),
native/sculpt/wasm/test/test_uv.js (the C++ unfold / layout / xatlas).

## Phase 2: Retopology (next)
Quad Draw on a live surface: the high-poly (a sculpt or any object) is made "live" (R layer / Make Live) and
becomes the snapping surface; click to place points on it, Shift-click to fill a quad, Ctrl to delete, Tab-drag to
extend an edge loop, Shift-drag relax, symmetry across X. The engine's BVH (native/sculpt) does the projection.
Then Quad Remesh (already in the sculpt engine) as the automatic path, with guides. The low-poly is an ordinary
cage, so UVs (phase 1) and baking (phase 3) work on it directly.

## Phase 3: Baking (after)
C++ baker in native/sculpt: for each low-poly texel, cast along the (smoothed) cage normal into the high-poly BVH:
tangent-space normal, object normal, AO (hemisphere rays), curvature, thickness, height, position, material / mesh
ID; an automatic cage (push by a distance) with per-vertex editing; anti-aliasing; dilation; PNG export; a live
preview on the low-poly in the viewport. Then render-farm jobs (the PC worker) for big bakes.
