# Forge - UVgami's seam intelligence, ported (app/ui/forge_uvgami.js)

Owner 2026-10-21: "https://github.com/danielboxer/UVgami use that code". UVgami (Daniel Boxer, 2022-2026, GPL-3.0,
compatible with LOKI's AGPL-3.0) is an automatic UV unwrapping add-on for another 3D package ("the original add-on"
below). It has two halves: **its own seam and island logic** (pure Python, `src/seams/`, `src/similar.py`, parts of
`src/ops/island.py`), and **flatten engines** it runs as separate programs (OptCuts and xatlas, both MIT, and
PartUV, whose segmentation is non-commercial). Forge takes the first half, ported line by line to JavaScript as
`window.ForgeUVgami`. The engines come in through LOKI's C++ engine (`window.ForgeGeom`: xatlas, the LSCM/ARAP
unfold, packing) behind one hook, `opts.flatten`. PartUV is not used.

The licence is `app/ui/licenses/UVgami-LICENSE.txt`. The row is in docs/THIRD_PARTY.md. The port keeps the original's
comments (shortened) and its constant names (camelCase), so each function can be checked against its Python.

## The original add-on, module by module

| Module | What it does | In Forge |
| --- | --- | --- |
| `seams/mesh.py` | Basics: weighted face normals, `turn_angle` (degrees between two faces), edge -> faces map, islands from a seam set, loose parts, UV seams from a UV map, island layout and fit helpers | ported |
| `seams/regions.py` | **Regions.** `partition` (faces joined across edges turning under 10 deg), `detect_width` (the narrow-band floor: 2 x the 90th-percentile region width, capped at 5 % of the diagonal), `absorb` (dissolve bevel bands narrower than that into their neighbours, carrying the turn), `merge_smooth` (merge across boundaries that turn under the angle, e.g. cylinder segments), `merge_flat` (merge while the union stays inside a 30 deg spherical cap), `close_rings` (merge two halves of a ring when the cut-open wall is a compact strip), `unfold_hinges` (keep two flat panels joined along a straight fold when unfolding them can't overlap: a box becomes a cross). All merges keep every region a disk (`keeps_topology`) and never cross a forced (hand-marked) edge | ported |
| `seams/sweeps.py` | **Sweep rims.** Finds walls swept around an axis (cylinders, tubes, bent tubes cut into straight runs, flat bars split into panels at their soft ridges), cuts their rims off the caps (`sweep_rims`), and splits a region into wall and cap (`split_sweeps`). Also trims handles through a wall (`trim_genus`) and leaves hoops alone | ported |
| `seams/boundaries.py` | **Teeth and reroute.** `flatten_teeth` (a face sticking into the other region by all but one edge moves over), `reroute_boundaries` (each run of boundary between two regions is replaced by the cheapest path between its junctions in a 2-ring corridor, priced by `crease_relief`, when that keeps both sides disks and never trades a crease for a shortcut) | ported |
| `seams/cuts.py` | **Cuts.** `crease_relief` (an edge on a crease costs less: concave down to 0.5, convex 0.7, at 45 deg), `cut_path` (Dijkstra/A*, with turn penalties when relief is on), painted seam restrictions (`RESTRICT_COST` 9), `connect_loops` / `disk_cuts` (a region with a hole gets the shortest cut joining its boundary loops), `snap_paths` (cuts redrawn on another mesh) | ported |
| `seams/pipeline.py` | **The pipeline.** `seam_edges(angle = 30)`: rims -> regions -> absorb -> merge smooth -> merge flat -> close rings -> split sweeps -> teeth -> reroute -> absorb again -> hinges -> boundary edges + disk cuts + forced. If a closed mesh gets no seams at a high angle it reruns at 30. `is_hard_surface`: hard vs organic from the shares of creased boundary, spread curvature and coplanar edges | ported |
| `seams/parallel.py` | the same per loose part on worker processes | ported without processes (`seamEdgesParts`); a Web Worker can run it |
| `seams/preseed.py` | **The hard-surface flow.** `hard_faces` (the parts that read hard, or touch a marked seam), `preseed_uvs` (seams at the hard-surface angle 66 deg, mirrored if symmetric, then the engine flattens the parts a seam opens: `_flattenable`), `FlattenEngine` (writes an OBJ, runs the engine binary, reads the UVs back) | logic ported (`hardSurfaceSeams`, `hardFaces`, `unwrap`); the engine process is the `opts.flatten` hook |
| `seams/islands.py` | **After the flatten.** `uv_topology` (an island's Euler characteristic and boundary loops through the UV map), `island_ruined` (flipped faces, not a disk, or crossing borders), `split_islands` (cut long or folded islands at their necks or into even pieces, the cut straightened, tiny fragments re-absorbed), `split_moves` (shrink the new pieces 2 % toward their centres) | ported |
| `seams/rectify.py` + `ops/island.py rectify_islands` | **Rectify.** An island whose border is a rectangle-ish loop (fills 80 % of its box, or is an elongated strip) gets four corners (the sharpest 90 deg turns that make a consistent rectangle) and its border mapped onto a rectangle. A strip with real corners unbends along its spine keeping its width profile. A flip relax follows, then a pinned re-solve. The result is rejected if it crushes a face, changes the area more than 2x, or adds more than 1.0 distortion | ported. The pinned re-solve (the host's own unwrapper there) is a uniform harmonic solve here; see below |
| `seams/symmetry.py` | **Symmetry.** `mirror_seams` (close a seam set under the mirror maps), `half_faces` / `interface_edges` (which half is dropped and where the halves meet), `open_merged` (re-open an island the mirroring closed into a ring, along the shortest interface arc), `stack_mirrored` (put mirrored islands on top of each other) | ported |
| `similar.py` | **Similar pieces.** `find_twins` (pieces that are rigid copies, by an index-for-index fit or a PCA alignment + vertex matching + face-cycle check), `mirror_matches` / `mirror_permutations` (vertex mirror maps across axis planes through the centre), `find_stacks` (islands whose UVs are already identical) | ported (`rigid_fit` uses Horn's quaternion method instead of numpy's SVD, same result) |
| `reroute_seams.py` | the old "preserve mesh" step: after a triangulated unwrap, re-joins quads along seams by rotating triangles in the OBJ. It is commented out in the original (`manager.py`) | not ported (dead code there). "Reroute seams" in Forge is `rerouteSeams` = `reroute_boundaries` |
| `seams/proxy_transfer.py`, `seams/uv_transfer.py`, `proxy.py` | **Proxy for dense meshes.** Decimate to `proxy_faces` triangles (the host's Decimate modifier), unwrap the proxy, then transfer the cuts and UVs back to the dense mesh (BVH/KD lookups, affine maps per proxy face, tear detection, weld, flip relax, seam straightening) | not ported; see below |
| `unwrap.py`, `job.py`, `batch.py`, `manager.py`, `engines/*`, `ops/*`, `ui/*` | Running the engine processes, progress, OBJ import/export, the host's operators and panels | not portable (host API + processes); `unwrap()` here is the same flow without the host |

## Settings (src/ui/props.py and the OptCuts engine) and where they went

`ForgeUVgami.DEFAULTS` (frozen) has the original's defaults. The UI owns its own copy. Every entry point takes an
options object merged over these.

| Original | Default | Meaning | `DEFAULTS` key |
| --- | --- | --- | --- |
| `optcuts.surface_mode` | Organic | Organic: the engine places every seam. Hard Surface: cut seams on sharp features first. Auto: per loose part, by `is_hard_surface` | `surfaceMode` `"organic"`/`"hard"`/`"auto"` |
| `HARD_SURFACE_ANGLE` | 66 | degrees, what counts as a sharp feature in hard-surface mode | `hardAngle` |
| `seam_edges(angle)` | 30 | the pipeline's own feature angle | `angle` |
| `priority` | Balanced | Less Stretch / Balanced / Fewer Seams = the engine's distortion bound 4.05 / 4.2 / 5.0 | `priority`, `PRIORITY_BOUND`; passed to `opts.flatten` as `{priority, bound}` |
| `use_weights`, `weight_mode`, `weight_value` | off, Avoid Seams, 3 | painted seam restrictions (vertex weight 0..1, a cut there costs up to 10x), or "reduce stretching" there (an engine option); value 1..5 is the engine's weight 25..200 | `useWeights`, `weightMode`, `weightValue`, `weights` (Map / object / array vertex -> 0..1) |
| `use_symmetry`, `sym_axes`, `sym_merge` | off, X, on | symmetric seams across planes through the bounding-box centre; merge = overlap the mirrored halves' UVs | `useSymmetry`, `symAxes` `["x"]`, `symMerge`, `center` |
| `stack_similar` | off | unwrap one of each set of repeated pieces and copy it | `stackSimilar` |
| `area_expand` | 1 | grow a face selection by rings before an area unwrap | `areaExpand`, `growFaces()` |
| `margin`, `fix_scale`, `pack_after_unwrap` | 0.001, on, on | packing | `margin`, `fixScale`, `packAfterUnwrap`; passed to `opts.pack` |
| `use_proxy`, `proxy_faces` | off, 20000 | decimated proxy for dense meshes | `useProxy`, `proxyFaces` (kept so settings round-trip; not acted on) |
| `import_uvs`, `combine_uvs`, `transfer_uvs`, `max_cores`, `unwrap_timeout`, `engine`, grid settings, preferences | | host / engine process settings | not applicable (Forge's UV workspace has its own) |
| marked seams NONE / ADD / ONLY | NONE | what the mesh's existing seams do | `marked` (the cage's interior UV seams), `forced` (an extra Set) |
| Forge additions | | `rectify` (on), `axisAlign` (on: the rectangle lands on the UV axes; the original keeps the island's angle), `rectifyMode` `"rectangle"` (the border goes exactly onto the rectangle) or `"spine"` (the original's), `splitPasses` (1; 3 with symmetry like the original's rebuild) | |

## The API (`window.ForgeUVgami`)

All functions take a ForgeUV cage `{v, f, uv?, fuv?}` and an options object, and never change the cage. A **seam
set** is a `Set` of `"a,b"` vertex keys (a < b, `ForgeUV.ekey`), the kind `ForgeUV.rebuild` / `cut` take.

| Function | Returns |
| --- | --- |
| `hardSurfaceSeams(cage, opts)` | seam Set. Hard-surface mode by default (`surfaceMode` `"hard"`, 66 deg); `"auto"` only seams parts that read hard; `"organic"` only forced/marked. With `useSymmetry` the set is mirrored |
| `seamEdges(cage, opts)` | seam Set: the full pipeline at `opts.angle` (30), `rims`, `weights`, `forced`, `marked`, `faces` (a subset, widths read off the whole mesh) |
| `isHardSurface(cage)` / `hardFaces(cage, opts)` | boolean / Set of face indices of the hard loose parts |
| `islands(cage, seams)` / `topology(cage, faces, seams)` | face lists / `{euler, loops, disk}` |
| `applySeams(cage, seams)` | new cage whose UV indices split exactly along the seams (`ForgeUV.rebuild`; gives a cage with no UVs a placeholder map first) |
| `markedSeams(cage)` | the cage's interior UV seams |
| `mirrorMaps(cage, {symAxes, center})` | `[Map v -> mirrored v]` per axis, or null |
| `symmetrySeams(cage, seams, opts)` | seam Set closed under the mirrors, rings re-opened |
| `stackMirrored(cage, opts)` | new cage: mirrored shells overlap their originals |
| `rerouteSeams(cage, seams?, opts)` | seam Set: boundaries moved onto creases / shorter paths (teeth flattened first; `opts.teeth: false` skips that), islands kept disks, `forced` kept |
| `splitIslands(cage, opts)` | extra seam Set: necks / over-long strips of a flattened map |
| `finishSplit(cage)` | new cage: those cuts made, the pieces shrunk 2 % apart (`uvInfo.split`) |
| `flattenDistortion(cage, faces?)` / `islandIsRuined(cage, faces)` | symmetric Dirichlet (4 = isometric) / boolean |
| `rectify(cage, {faces, axisAlign, rectifyMode})` | new cage, quad-ish islands made rectangles (`uvInfo.rectified`) |
| `similarIslands(cage, {by: "shells" \| "parts"})` | `[{rep: {faces}, twins: [{faces, matrix (4x4 rows), exact, mirrored, vertexMap}]}]` |
| `stackSimilar(cage, opts)` / `findStacks(cage)` | new cage, twins take their rep's UVs / `[{kept, duplicates}]` |
| `flattenRigid(cage)` (async) / `flattenRigidSync` | the fallback flatten (below) |
| `growFaces(cage, faces, rings)` | the selection grown (area_expand) |
| `unwrap(cage, opts)` (async) | the whole flow: seams -> symmetric seams -> cut -> **`opts.flatten`** -> split (re-flatten when symmetric) -> rectify -> stack mirrored -> stack similar -> **`opts.pack`**. `uvInfo: {seams, split, flattened, ms, ...}` |
| `core` | the ported internals on plain `verts` / `faces` lists (for tests and other flows) |

### The engine hook (wire this to the C++ engine)

`opts.flatten(cage, {priority, bound, weights}) -> Promise<cage>` gets a cage whose seams are already cut (one UV
index per shell corner). It must return a cage with the **same faces** and new `uv`/`fuv` (re-indexing is fine).
This is where the original ran OptCuts (`-flatten` with the seams, `-u <bound> -s <weight>`) or xatlas. In Forge
it should call `ForgeUV.unfold` (LSCM + ARAP, `ForgeGeom.uvUnfold`), or the xatlas parameterizer for each shell.
`opts.pack(cage, {margin, fixScale}) -> Promise<cage>` is the packer (`ForgeUV.layout` / `ForgeGeom.uvLayout`).
Without `opts.flatten`, `unwrap` uses `flattenRigid`. That one unfolds each shell face by face, gluing every face
rigidly onto a placed neighbour. It is exact for developable islands of flat faces (boxes, prisms, cylinder walls,
most of what hard-surface mode makes), but curved islands come out distorted and may overlap. It is a fallback, not
the solver. Without an engine the original also skips closed parts no seam opens (`_flattenable`); here
`uvInfo.flattened` counts the faces that would be flattened.

## What is not ported, and why

- **The flatten engines** (OptCuts, xatlas, PartUV): separate native programs. OptCuts and xatlas go into LOKI's C++
  engine (another agent; `native/`). PartUV is non-commercial and is never used.
- **The proxy for dense meshes** (`proxy.py`, `proxy_transfer.py`, `uv_transfer.py`, about 1 800 lines): it needs
  the host's decimator and BVH / KD trees and moves engine UVs between meshes. The portable piece, `snap_paths`
  (redraw coarse cuts on the dense mesh), is ported (`core.snapPaths`). A full port needs Forge's own decimate
  (meshoptimizer is in the C++ engine) and belongs with the C++ unfold.
- **`reroute_seams.py`** (re-joining triangles after a triangulated unwrap): commented out in the original.
- **The host's pinned re-solve inside rectify**: the original pins the rectangle border and runs the host's
  conformal + angle-based unwrap. Here the pinned border goes into a uniform harmonic (Tutte) solve. The border is
  convex, so no face can flip. The original's acceptance checks (crush, area 0.5x-2x, +1.0 distortion) still decide.
  Swapping in the C++ unfold with pins would be closer.
- **Host operators**: the guides paint mode, the viewer, island re-unwrap/relax/combine (these call the engine on a
  sub-mesh: with `opts.flatten` that is `unwrap(subCage)`), batch processing, progress, the engine installer.

## Tests

`tests/js/test_forge_uvgami.js` (node, under 1 s) runs through `tests/test_forge_uvgami.py` (in `tools/ship.py`
SUITES). It checks that a hard-surface cube gets the 7-seam cross, that its shells are disks (Euler 1, one boundary
loop) and flatten with no overlap or flip, and that a 3x3 cube's seams sit only on the cube edges. A capped cylinder
gets 3 disk shells and an open tube one axial seam. The original add-on's own tests run again on the port: the
16-sided tube, the n-gon cylinder's [1, 1, 32] islands, the 4- and 8-sided tubes, the bump reroute and its forced
chain, crease relief, mirror seams across two maps, splitting the 30-quad strip into 4, and Dirichlet 4 at isometry.
It also covers symmetric seams closed under the mirror, stacking mirrored faces, rectify (a bent, wobbly strip
becomes an axis-aligned rectangle with all 4 corners, a blob is left alone), and similar islands (a box's 6 faces
are 1 rep + 5 twins with correct matrices, 3 copies of a cylinder are found, a different shape is not). Finally the
flatten and pack hooks, a torus and a quad sphere opened into disks, no input ever mutated, and no eval.
