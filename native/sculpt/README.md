# LOKI's sculpting engine

The C++ sculpting core behind Forge's Sculpt mode, built to one WebAssembly module that runs in a Web Worker
inside LOKI's window (no native install, the same file on macOS and Windows).

| Folder | What |
| --- | --- |
| `core/` | the engine: mesh + BVH, 40 brush kernels (`brush.cpp`), dynamic detail (`dyntopo.cpp`), voxel remesh (`voxel_remesh.cpp`, dual contouring), field-aligned quad remesh (`quad_remesh.cpp` + `instant_meshes.cpp`), subdivision levels (`multires.cpp`, Catmull-Clark with per-level detail in tangent frames), cluster LOD, paged store, SDF volumes, and `cage_subdiv.cpp` - Catmull-Clark of Forge's modelling cage for the 2 / 3 smooth preview (the JS ForgePoly.smooth result exactly, ~6x faster; Forge runs it in its own worker, app/ui/forge_geom.js) ; and `uv_unwrap.cpp` - map-UV unwrapping of a cage (`uvUnfold`: LSCM with pins + ARAP rounds per UV shell, flips and stretch reported; `uvLayout`: density / rotation / skyline packing into 0-1; `uvAuto`: [xatlas](https://github.com/jpcy/xatlas) cuts and packs, or keeps the existing seams) |
| `wasm/` | the WebAssembly build: `sculpt_api.cpp` (the C API), `st_compat.h` (single-thread stand-ins for std::thread/mutex), `sculpt_engine.js` (JS wrapper, browser + node), `sculpt_worker.js` (the worker Forge talks to), `build.sh`, `test/test_engine.js`, `test/test_cage.js`, `test/test_uv.js` |
| `brushes/` | the brush library (212 presets over the kernels) and its alpha stamps |
| `tools/gen_matcaps.py` | draws the six matcaps procedurally (numpy + PIL) into `app/ui/vendor/sculpt/matcaps/` |
| `third_party/` | Instant Meshes (BSD-3), Eigen (MPL-2.0, headers), meshoptimizer (MIT), xatlas (MIT) - notices in `THIRD_PARTY_NOTICES.md` |

The built files Forge loads are committed in `app/ui/vendor/sculpt/` (`sculpt.wasm`, `sculpt_engine.js`,
`sculpt_worker.js`, `brushes.json`, `matcaps/`), so no machine needs a compiler.

## Rebuild

Needs the [WASI SDK](https://github.com/WebAssembly/wasi-sdk) (clang + libc++ for wasm32; release 25 is what
built the committed file):

```
WASI_SDK=/path/to/wasi-sdk-25.0 bash native/sculpt/wasm/build.sh /tmp/sculpt-build
node native/sculpt/wasm/test/test_engine.js /tmp/sculpt-build/sculpt.wasm     # every engine call, ~4 s
node native/sculpt/wasm/test/test_cage.js /tmp/sculpt-build/sculpt.wasm       # the cage subdivision vs the JS, ~2 s
node native/sculpt/wasm/test/test_uv.js /tmp/sculpt-build/sculpt.wasm         # UV unfold / layout / auto (xatlas), ~5 s
cp /tmp/sculpt-build/sculpt.wasm native/sculpt/wasm/sculpt_engine.js native/sculpt/wasm/sculpt_worker.js app/ui/vendor/sculpt/
```

## Speed (single thread, node 22, x86-64)

| Mesh | Load | Clay dab | Standard dab | Move dab |
| --- | --- | --- | --- | --- |
| 526k vertices | 1.3 s | 0.6 ms | 0.3 ms | 0.07 ms |
| 2.1M vertices | 5.0 s | 1.3 ms | 0.9 ms | 0.5 ms |

The window only receives the vertices a stroke moved (plus their one-ring, whose normals change), copied
straight into the GPU buffers' update range - no whole-mesh normal pass or re-upload per dab.

### Dense meshes and staying smooth (2026-10-21)

Measured on a 1.05M-vertex sphere, Clay r = 0.3 (node 22, one thread), before -> after:

| What | Before | After |
| --- | --- | --- |
| Worker work per reply (it padded the engine's list with another one-ring, which the engine already includes) | 1.5-2.7 ms | 0.02 ms |
| GPU upload per dab (position + normal) | 4.4 MB (one lowest..highest id span) | 0.33 MB (~90 runs of changed ids) |
| Vertices sent for a wide front-faces-only dab (zero-weight vertices dropped before the kernel) | 8383 of 8385 | 4255 of 8385 |
| Engine instructions per dab, 262k verts r = 0.6 (callgrind; BVH refit order without a sort, cheaper weights) | 197M | 189M (Smooth: 213M -> 237M, it now runs the HC pass) |
| Patch radius after 4 Smooth strokes on a noisy unit sphere | 0.9899 (shrinks 1%) | 1.0003 with `smoothVolume` 1 |
| Clay roughness on a 33k sphere, without / with `autoSmooth` 0.15 | 1.1e-2 | 5.7e-3 |

- **Smooth** blends the umbrella Laplacian with the HC step (Vollmer, Mencl & Mueller 1999, alpha 0, beta 0.5):
  preset key `smoothVolume` 0..1 (default 0.5; `Smooth Classic` = 0, `Smooth Volume` = 1). `autoSmoothVolume` does
  the same for auto-smooth (default 0 = the classic pass, as before).
- **Auto-smooth** follows the dab's falloff, front-face test and mask (it was one uniform pass over the whole brush
  sphere, back faces included); Forge's Draw (Clay), Inflate and Flatten buttons use a little of it by default.
- **Tube** and **Insert Mesh** (ByHand has both): `ks_tube` sweeps `curve_tube.cpp` along the stroke's surface
  points, `ks_insert` drops a sphere or cube at the surface; each is one undo step, the existing quads are kept.
- **Stroke** (app/ui/forge_sculpt.js `ForgeStroke`): lazy-mouse stabiliser, dabs at an even arc length (the preset's
  `spacing`, the same number the engine scales a dab's height by - the window used a fixed 0.12), every coalesced
  pointer sample, pen pressure interpolated per dab; Stabilize / Auto smooth / Falloff controls in the panel;
  Screen detail turns dynamic detail into "N pixels on screen" (zoom in = finer).
- New presets: Bulge, Hook, Chisel, Tube, Insert Sphere (Basic), Smooth Classic, Smooth Volume, Insert Cube.

- **Radial symmetry** (`radial` / `radialAxis` on the Brush, `ks_brush_radial`, `setRadial`): the dab is repeated
  `radial` times around an object-space axis at 360/radial degree steps, composing with the mirror planes; the
  window's Symmetry menu (right-click the status button) sets 3 / 4 / 6 / 8 and the axis. Checked by
  `native/sculpt/wasm/test/test_engine.js` ("radial symmetry: 4 copies about Y").


`build.sh` now also recompiles every object when any engine header changed (before, a changed class layout linked
stale objects into a module that crashed); the committed `sculpt.wasm` is byte-identical to a fresh build of this
source with wasi-sdk 25.

## How Forge uses it

`app/ui/forge_sculpt.js`: loads the worker, keeps the engine's mesh equal to Forge's `view.sm` (welded
vertices; Forge's undo and transform tools are noticed and sent over), sends one ray per dab spaced along the
cursor's path, applies the replies, and adds the sculpt panel (brush library, dynamic detail, remesh, quad
remesh, subdivision levels, matcaps). The worker has its own Content-Security-Policy
(`engine/loki_bridge.py` `SCULPT_WORKER_CSP`): WebAssembly is allowed for that one script only; LOKI's pages
keep `UI_CSP`.
