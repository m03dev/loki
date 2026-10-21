# OptCuts for Forge (WebAssembly)

**What.** [OptCuts](https://github.com/liminchen/OptCuts) (Minchen Li, Danny M. Kaufman, Vladimir G. Kim, Justin
Solomon, Alla Sheffer: *OptCuts: Joint Optimization of Surface Cuts and Parameterization*, SIGGRAPH Asia 2018) -
one of the two CPU engines of UVgami - built to WebAssembly for Forge's UV unwrap. OptCuts adds and removes seams
while it minimises the symmetric Dirichlet distortion of the UV map, until the distortion meets a bound `b_d`
with the shortest seams it finds, optionally keeping the map bijective (no overlaps) with a scaffold mesh.

The output is `app/ui/vendor/optcuts/optcuts.wasm` (about 950 KB), used through
`app/ui/vendor/optcuts/optcuts_engine.js` (browser + node) and `app/ui/vendor/optcuts/optcuts_worker.js` (a Web Worker).

## Licences

| Folder | What | Licence |
| --- | --- | --- |
| `src/` | OptCuts' headless solver from upstream commit `cd23026` (2024-05-17): `Optimizer`, `TriMesh`, `Scaffold`, `Energy/` (symmetric Dirichlet), `LinSysSolver/` (the Eigen SimplicialLDLT back end only), `Utils/` (`IglUtils`, `Timer` (University of Reading, all-permissive notice in the file), `cut_to_disk` (a libigl function OptCuts copied in, MPL-2.0 upstream)). Left out: `main.cpp` (viewer, file I/O), the GLFW/OpenGL viewer, GIF/PNG output, `UnitTest/`, CHOLMOD and PARDISO back ends, the ARAP energy | MIT - `src/LICENSE.txt` |
| `third_party/libigl/` | 49 headers (with their .cpp) of the libigl bundled with OptCuts (v1.2.1, `include/igl/` top level only - the MPL-2.0-only part; nothing from `copyleft/`, `triangle/`, `opengl/`) | MPL-2.0 - `third_party/libigl/LICENSE.MPL2`, `LICENSE.md` |
| `third_party/eigen/` | [Eigen](https://eigen.tuxfamily.org) 3.4.1 headers (tag `3.4.1`, commit `d71c30c`, the github mirror of gitlab.com/libeigen/eigen) plus `unsupported/Eigen/SparseExtra` (libigl's `slice` needs it). 3.4.1, not the 3.3.7 in `native/sculpt/`: there the sparse Cholesky (SimplicialLDLT, AMD ordering) is LGPL and refused by `EIGEN_MPL2_ONLY`; since 3.4.1 its author relicensed it to MPL-2.0. Built with `EIGEN_MPL2_ONLY`. The CHOLMOD/SuiteSparse/PaStiX/... bindings and the AltiVec/ZVector/MSA/SYCL/SVE/AVX512/CUDA/HIP back ends were left out | MPL-2.0 (some files carry BSD/Apache/MINPACK notices, texts in `third_party/eigen/COPYING.*`) |
| `third_party/CDT/` | [CDT](https://github.com/artem-ogre/CDT) by Artem Amirkhanov, commit `53eff28`: constrained Delaunay triangulation, header-only, replaces Jonathan Shewchuk's Triangle (non-commercial licence, not usable in LOKI) for OptCuts' scaffold mesh. Includes Lenthe's robust predicates (BSD-3-Clause) and a libc++ `nth_element` (Apache-2.0 with LLVM exception) | MPL-2.0 - `third_party/CDT/LICENSE`, `LICENSE-predicates.txt`, `LICENSE-LLVM.txt` |
| `shim/`, `wasm/`, `test/`, `build.sh` | LOKI's port: TBB / Triangle / `igl::harmonic` stand-ins, the C API, tests | AGPL-3.0 (LOKI) |

### Changes to the upstream code (each marked `LOKI:` in the source)

* `src/Optimizer.cpp`, `src/Optimizer.hpp`: the two `try { factorize } catch` blocks (no C++ exceptions here)
  became a check of `factorize()`'s return value; every `exit(-1)` and a failed factorization call `oc_fatal()`
  (message + trap; the JS wrapper reports it and starts a fresh instance); `Optimizer::solve`'s function-static
  `lastPropagate` became a member, so repeated runs in one module are independent.
* `src/TriMesh.cpp`: the zero-area-triangle `exit(-1)` calls `oc_fatal()` (the C API refuses such meshes first).
* `third_party/CDT/`: `Triangulation::splitFixedEdges` (default true = CDT's behaviour). With false, refinement
  never splits a constraint edge, which is Triangle's `-Y` switch that OptCuts uses; `handleException` can call an
  error hook (`CDT_ERROR_HANDLER`) before it stops.
* Nothing else in `src/` changed; `main.cpp`'s driver is re-written in `wasm/optcuts_api.cpp` (below).

### The shims (`shim/`)

* `tbb/tbb.h`: `tbb::parallel_for` as a plain loop (single-threaded WebAssembly; OptCuts' loops write disjoint
  slots, so results are identical).
* `igl/triangle/triangulate.h`: libigl's Triangle wrapper with flags `qYQ` re-done on CDT: same input points
  first and in order, constraint edges kept unsplit, 20 degree quality refinement, chart interiors removed
  (CDT's even-depth regions instead of Triangle's hole points - the same regions for OptCuts' inputs).
* `igl/harmonic.h`: the `k = 1` harmonic map (Tutte embedding) as one SimplicialLDLT solve, instead of libigl's
  `min_quad_with_fixed` (which pulls SparseLU/SparseQR).
* `oc_compat.h` (force-included): a compile-only `std::thread` for libigl's `parallel_for` (forced serial) and the
  `oc_fatal` declaration.

## How it is called

The C API (`wasm/optcuts_api.cpp`, exported with `export_name`) ports OptCuts' headless mode (`main.cpp` mode 100:
initial cut + Tutte map, then `preDrawFunc` / `updateLambda_stationaryV` / `converge_preDrawFunc`) into a stepped
state machine:

```
oc_init(pos f32*, nv, tris i32*, nt, seams i32*, nseams, distortionBound, lambdaInit, useBijectivity,
        initialCut, maxIterations, timeBudgetMs, seed) -> 1 | 0 (oc_error())
oc_step(units, sliceMs) -> 0 running | 1 finished | -1 error   (a unit = one Newton step or one topology decision)
oc_iterations / oc_distortion / oc_topology_ops / oc_lambda / oc_phase_name    progress
oc_finish()   -> builds the result (after a budget stop: the best feasible map seen, if the current one breaks the bound)
oc_uv / oc_uv_count, oc_corner_uv / oc_corner_count, oc_seams / oc_seam_count, oc_result_distortion,
oc_seam_length, oc_flipped, oc_converged, oc_error, oc_alloc / oc_free, oc_reset
```

* Input: triangles only, manifold and consistently oriented (the caller triangulates polygons and keeps the map).
  Unused vertices are ignored. Refused with a message: out-of-range ids, repeated vertices, NaN, zero-area
  triangles, non-manifold edges/vertices, inconsistent orientation, `distortionBound <= 4`.
* `initialCut`: `0` OptCuts' default one-point cut on closed genus-0 parts (`cut_to_disk` for higher genus or
  open parts); `1` first cut along the caller's `seams` (vertex-id pairs), then OptCuts' cut for whatever is still
  not a disk; `2` OptCuts' farthest-point cut. `seed`: 0 starts the one-point cut where OptCuts does (the
  component's first vertex); another value picks another triangle, deterministically. Same input + seed = same
  result, bit for bit.
* Output: `uv` (u,v floats for the cut mesh's UV vertices, in OptCuts' units - not normalised to 0..1),
  `cornerUV` (3 per input triangle, indices into `uv`), `seams` (input vertex-id pairs of the edges whose sides
  got different UVs), the distortion (OptCuts' area-weighted symmetric Dirichlet, 4 = isometric), iterations,
  `converged` (false after a budget stop).

JavaScript (`optcuts_engine.js`):

```js
const eng = await OptCutsEngine.create("/ui/vendor/optcuts/optcuts.wasm");
const r = eng.unwrap(pos, tris, { distortionBound: 4.1, seed: 0, timeBudgetMs: 20000 }, (p) => {/* p.iter, p.distortion */});
// or eng.begin(pos, tris, opts); while (!eng.step(1 << 20, 100)) post(eng.progress()); const r = eng.result();
```

Worker (`optcuts_worker.js`): post `{t: "optcuts", seq, pos, tris, opts}`; it answers
`{t: "progress", seq, iter, distortion, topologyOps, phase}` after each slice (`opts.sliceMs`, default 100), then
`{t: "optcuts", seq, ok: true, uv, cornerUV, seams, distortion, iterations, topologyOps, seamLength, flipped,
converged, ms}` (buffers transferred) or `{t: "fail", seq, error}`. `{t: "cancel", seq}` stops a run and returns
the best map so far. LOKI serves the worker with the worker CSP (`engine/loki_bridge.py` `WORKER_PAGES`:
`script-src 'self' 'wasm-unsafe-eval'`); it loads only `optcuts_engine.js` and `optcuts.wasm`.

## Build

```
WASI_SDK=/path/to/wasi-sdk-25.0 bash native/optcuts/build.sh [out-dir]   # default out-dir: app/ui/vendor/optcuts
```

WASI SDK 25 (clang + libc++ for `wasm32-wasip1`), `-O2 -msimd128 -fno-exceptions`, single-threaded, about a
minute. Object files go to `$TMPDIR/loki-optcuts-obj` (set `OPTCUTS_OBJ` to change). The same sources build
natively with g++ (the native and WebAssembly runs give identical results).

## Tests

`node native/optcuts/test/test_optcuts.js` (also run by `tests/test_forge_optcuts.py`, a `tools/ship.py` suite):
icosphere, open cylinder and torus give valid layouts (every corner has a UV, 0 flipped triangles, distortion
within the bound, seams = exactly the split edges, charts are disks), determinism, options (looser bound gives
shorter seams, bijectivity off, initial seams from input), the step API and budget stop, 8 kinds of bad input,
the worker protocol, and timings at ~2k and ~10k triangles. About 22 s.

## Limits

* Speed: OptCuts is a research solver and this is a single thread. A 320-triangle icosphere takes ~4.5 s; a
  closed ~2k-triangle sphere is still improving after 4 s (most time is OptCuts' per-triangle 6x6 eigen
  projection of the Hessian and its topology queries); open or toroidal meshes are much faster (torus 10k: ~2.3 s).
  Use `timeBudgetMs` / `maxIterations`: a stopped run still returns a valid, flip-free map (the best feasible one
  if there is one).
* One mesh per instance at a time; ~32 MB initial memory, grows as needed.
* OptCuts' regional seam placement (`_selected.txt` vertex weights), EBCuts and the fixed-lambda / distortion-only
  methods are not exposed by the C API (the code for them is present).
* UVs are not packed or normalised; Forge does the packing (or use xatlas' packer in the sculpt engine).
