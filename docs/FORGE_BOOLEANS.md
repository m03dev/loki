# Forge: Booleans, soft selection Surface mode, and what is copied from where

## Mesh > Booleans
Union, Difference, Difference (B - A), Intersection - Maya's Mesh > Booleans. Pick two or more meshes (the first
picked is the one the others act on), run the command: they become one new object (`polySurface1`) in world space,
the pivot at its middle; one undo brings the originals back.

- CSG: **three-bvh-csg** (github.com/gkjohnson/three-bvh-csg @7f00d37, MIT), vendored in `app/ui/vendor/three-bvh-csg`
  by `tools/vendor_csg.py` (imports rewritten like `tools/vendor_pathtracer.py`; nothing upstream is executed).
- LOKI's part (`app/ui/forge_boolean.js`): Forge mesh -> triangles -> CSG -> welded mesh, coplanar triangle pairs
  joined back into quads (`quadrangulate`, 1 degree). Scene side: `worldPolys` / `replaceWith` in `forge_scene.js`.
- Not yet: Slice, Hole Punch, Cut Out (Maya's other three). Upgrade path: **Manifold** (elalish/manifold, Apache-2.0,
  WASM) in a worker with `'wasm-unsafe-eval'` like the sculpt worker - more robust on hard cases (ZIVA_TASKS.md).
- Tests: `tests/test_forge_boolean_ui.py` (volumes 1.75 / 0.75 / 0.75 / 0.25 for two half-overlapping unit cubes).

## Soft selection Falloff mode
Tool Settings > Selection > **Falloff mode: Volume / Surface** (Maya's names). Surface measures the distance along the
mesh's edges (multi-source Dijkstra, `ForgePoly.weightsSurface`), as Blockbench's "connected" proportional edit and
Wings 3D's magnet do - a lip moves without the other lip. Test: `tests/js/test_forge_softsel.js`.

## Research (2026-10-25): what to copy for the rest
No mature open-source polygon-modeling kernel runs in the browser. The plan the research gave:
- **Booleans**: three-bvh-csg now, Manifold (WASM) next.
- **Subdivision with creases**: OpenSubdiv (Pixar, modified Apache 2.0) built to WASM with `-sEMBIND_AOT
  -sDYNAMIC_EXECUTION=0`; pmp-library (MIT) for Catmull-Clark / remesh / hole filling / LSCM if a C++ kernel is added.
- **Modeling ops** (bevel with segments + profile, inset, bridge, loop cut, edge slide, dissolve, knife): port from
  Blender BMesh (`source/blender/bmesh`, GPL-2.0+, e.g. `tools/bmesh_bevel.cc`) and Wings 3D (`src/wings_*`, BSD-style);
  Blockbench (GPL-3.0) is closest to Forge's data model for extrude / inset / loop cut / knife.
- **Editor**: three.js editor's `History.js` + `Command.js` (MIT) for the command stack, three-mesh-bvh's box / lasso
  (`example/src/computeSelectedTriangles.js`, MIT), camera-controls (MIT) for Maya Alt navigation, Godot
  `node_3d_editor_plugin.cpp` / PlayCanvas `src/extras/gizmo` (MIT) for pivot / snapping maths.
- Construction history, the Channel Box, marking menus and the hotbox exist in no open project: they stay LOKI's own.

## Fixed on the way
`.gitignore`'s `build/` had kept `app/ui/vendor/three-mesh-bvh/core/build/` out of git, so on a fresh checkout every
three-mesh-bvh import failed - Forge's path-traced Render could not load. The vendor folders are excluded from that rule
now, and every relative import under `app/ui` resolves to a tracked file.
