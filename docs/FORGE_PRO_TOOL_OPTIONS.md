# Forge: the pro tools' option boxes (and Mesh > Cleanup)

What the reference modeller's polygon tools offer in their option boxes, written down in our own words from its
public online help and command reference (sources at the end), and how each option maps onto LOKI Forge's
polygon library (`app/ui/forge_polyops.js`, tested by `tests/test_forge_polyops.py`). Every Forge op takes an
`opts` object; the keys below are new keys in it. **Every default gives the result the op gave before these
options existed** - where the reference tool's default differs, that is noted.

Forge meshes are `{ v, f }` (positions + faces as vertex loops), no UVs, no per-object history, no scene. Options that
depend on those (UV/map area, construction history, "apply to all objects", world/local space) have no meaning
here and are listed as gaps.

## Mesh > Cleanup

The reference tool's Cleanup window has three parts.

**Cleanup effect**
- *Operation*: "cleanup matching polygons" (the default: fix them) or "select matching polygons" (only select them,
  so you can look before you fix).
- *Scope*: the selected objects (default) or every polygon object in the scene; an option keeps construction history.
  The help warns that cleaning an object and its instances at the same time misbehaves.

**Fix by tessellation** - faces with an unwanted property are cut into smaller faces:
4-sided faces, faces with more than 4 sides (n-gons), concave faces, faces with holes, non-planar faces.

**Remove geometry**
- *Lamina faces*: faces that share all their edges with another face (typically a duplicate face lying on top of
  another after a vertex merge). They are removed.
- *Non-manifold geometry*: vertices / edges shared by surfaces that should be separate. Two modes: "normals and
  geometry" (also makes the normals agree) and "geometry only". The help advises turning it on only on the last
  pass, because repeated cleanups can themselves leave non-manifold results.
- *Edges with zero length*: edges shorter than a length tolerance are removed (their ends merge).
- *Faces with zero geometry area*: faces smaller than an area tolerance are removed by merging their vertices; the
  edge-length tolerance decides which vertices merge.
- *Faces with zero map area*: faces whose UVs cover less than an area tolerance.
- *Invalid components*: loose edges, vertices and UVs.
- The help gives no numeric defaults for the tolerances; the command's argument list commonly carries `1e-05`.

### Forge: `P.cleanup(m, opts) -> { m, sel, warn, report }`

| key | type | default | range / values | what it does in Forge |
| --- | --- | --- | --- | --- |
| `op` | string | `"cleanup"` | `"cleanup"`, `"select"` | select: `m` is returned unchanged (same object), `sel` holds the matches (`f` faces, `e` edges as vertex pairs, `v` non-manifold vertices), `report` counts them |
| `quads` | bool | false | | 4-sided faces -> triangles |
| `nsided` | bool | false | | n-gons -> quads + triangles (ear clipped, then merged back into convex quads) |
| `concave` | bool | false | | concave faces -> convex pieces (Hertel-Mehlhorn: triangles merged while convex) |
| `holed` | bool | false | | a face that touches itself (a hole joined by a bridge edge - the only way a `{v,f}` face can have a hole) -> triangulated round the hole, then merged into convex quads; the hole stays open |
| `nonPlanar` | bool | false | | faces with a corner leaning more than `planarTol` out of their plane -> triangles |
| `lamina` | bool | true | | the later copies of a face on the same vertices go (one copy stays, so the surface is kept) |
| `nonManifold` | bool / string | true | `true` = `"normals"`, `"geometry"` | every vertex whose faces form 2+ separate fans gets a copy per fan (at an edge with 3+ faces, faces are paired by angle round the edge, so two solids touching on an edge come apart); `"normals"` then makes neighbours agree and closed shells point outward. Runs last, as the help advises |
| `zeroEdges` | bool | true | | edges shorter than `lengthTol` collapse to their middle |
| `zeroFaces` | bool | true | | faces with area under `areaTol`: their short edges merge; a sliver that is still left (long but flat) is removed and its middle points are put into the neighbour across its longest edge, so a closed mesh stays closed |
| `lengthTol` | number | 1e-5 | >= 0 | |
| `areaTol` | number | 1e-5 | >= 0 | |
| `planarTol` | number (degrees) | 1 | >= 0 | |

`report`: `{ quads, nsided, concave, holed, nonPlanar, lamina, nonManifoldEdges, nonManifoldVerts, flipped,
zeroEdges, zeroFaces }` - found (select) or fixed (cleanup). A clean mesh returns the same `m` object, all zeros,
no warning. The order of a cleanup pass: lamina, zero edges, zero faces, tessellation (holes, concave, n-gons,
non-planar, quads), non-manifold.

`P.meshStats(m)` (for a heads-up display): `{ verts, edges, faces, tris, quads, ngons, border, nonManifoldEdges,
nonManifoldVerts, lamina, concave, nonPlanar, zeroEdges, zeroFaces, shells }`.

Gaps: zero map area and invalid UVs (no UVs in Forge), scope / history (no scene objects), faces with real holes
(a `{v,f}` face cannot carry an inner loop except as a self-touching keyhole).

## Extrude (faces, edges, vertices)

Reference options: *thickness* (depth, 0), *offset* (the extruded border moves in, giving a bevel-like inset, 0),
*divisions* (segments along the extrusion, 1), *keep faces together* (on: connected faces move as one piece; off:
every face gets its own walls), *local translate / rotate / scale* (in the face's own frame), *taper* (scale of the
end, 1) and *twist* (rotation along the way, 0) - the help ties taper and twist to extruding along a curve (selected
or generated along the averaged normal) - and *smoothing angle* (30 degrees: new edges softer than it are soft).
Vertex extrude has *width* (base of the spike) and *length* (along the normal) and divisions.

| op | key | type | default | range |
| --- | --- | --- | --- | --- |
| `extrudeFaces` | `thickness`, `offset`, `keepTogether` | (existing) | 0, 0, true | |
| | `divisions` | int | 1 | 1..256: rings of walls along the extrusion |
| | `taper` | number | 1 | 0..100: the cap's scale across the axis; the rings between go linearly |
| | `twist` | number (degrees) | 0 | -3600..3600: the cap turns round the group's averaged normal, spread over the rings |
| | `localTranslate` | [x, y, z] | [0, 0, 0] | face frame: z = the averaged normal (adds to thickness), x = along the first face's first edge, y = z cross x |
| `extrudeEdges` | `thickness`, `offset` | (existing) | 0, 0 | |
| | `divisions`, `taper`, `twist` | as above | 1, 1, 0 | per connected chain; taper / twist work round the direction the chain moves |
| | `localTranslate` | [x, y, z] | [0, 0, 0] | chain frame: x along the chain, y outward (the offset side), z the averaged normal |
| `extrudeVerts` | `width`, `length` | (existing) | 0.1, 0 | |

Gaps: extruding along a curve (Forge has no curves; taper / twist work along the straight extrusion instead),
local rotate / scale (use the transform tools), smoothing angle (use `softHard` afterwards), vertex-extrude divisions.

## Bridge

Reference options: *bridge type* - linear path (straight, twist and taper greyed out), smooth path (a curve implied
from each border, at right angles to the averaged surface normals, so the bridge leaves each border smoothly), smooth
path + curve (an editable curve as well); *direction* (automatic, or source / target sides by hand); *twist* (0);
*taper* (1 = none: the width along the bridge); *divisions* (0: equal segments between the borders); *smoothing
angle* (180: soft); a start-vertex offset to change which vertices pair up.

| key | type | default | range |
| --- | --- | --- | --- |
| `divisions` | int (existing) | 0 | 0..64 |
| `bridgeType` (alias `curveType`) | string | `"linear"` | `"linear"`, `"smooth"` (Hermite curve leaving each border away from its faces, in their plane), `"curve"` (smooth + `curve`) |
| `curve` | [[x, y, z], ...] | [] | points the middle of the bridge passes through (with `"curve"`; the rows shift so their centre follows the polyline) |
| `twist` | number (degrees) | 0 | -3600..3600, spread along the bridge round its path (full turns close cleanly) |
| `taper` | number | 1 | 0..100: the width in the middle (sine falloff to the borders) |

Unlike the reference tool, twist and taper also work on a linear path here. Gaps: manual direction / start-vertex
offset (the pairing is chosen by the least distance), smoothing angle.

## Bevel

Reference options: *offset type* fractional (default: the width is capped by the shortest edge so the bevel cannot
turn inside out) or absolute (a distance, uncapped); *fraction* 0..1; *offset as fraction*; *offset space* world /
local; *segments* (1); *depth* (1; negative pushes inward, -1 the deepest); *mitering* (auto, uniform, patch, radial,
none) and *miter along* (auto, center, edge, hard edge); *chamfer* (on: sloped bevel faces); *smoothing angle* (30);
*auto fit* / *roundness* (0.5 when auto fit is off).

| key | type | default | range |
| --- | --- | --- | --- |
| `fraction`, `segments` | (existing) | 0.5, 1 | 0.01..1, 1..32 |
| `offsetAsFraction` | bool | true | true: width = fraction x 0.49 x the shortest edge at the bevelled vertices; false: width = `offset` |
| `offset` | number | 0.2 | > 0; limited to the fractional maximum, with a warning, so the result stays valid |
| `depth` | number | 1 | -1..1: scales the rounded profile's bulge (segments > 1): 0 flat, negative hollow |
| `chamfer` | bool | true | true: today's quadratic profile; false: a true circular (fillet) arc through the same tangent points |
| `mitering` | string | `"basic"` | `"basic"` (aliases `"uniform"`, `"auto"`): the corner caps Forge always made; any other value warns and uses basic |

The reference default is absolute offset 0.2; Forge keeps fractional as its default so earlier results do not
change. Gaps: patch / radial / none mitering, miter along, offset space, auto fit / roundness (depth covers the
profile shape), smoothing angle.

## Poke, Chamfer Vertex, Wedge

- **Poke**: the reference node offers a translate of the new centre vertex (world or local). Forge: `poke(m, faces,
  { offset=0 })` (existing) moves it along the face normal.
- **Chamfer Vertex**: *width* (how far back from the vertex the cut sits) and *remove the face after chamfer*
  (default off: the corner is left open). Forge: `chamferVerts(m, verts, { width=0.25 (0.001..0.49), removeFace=false })`;
  with `removeFace` the open corners' border edges are selected.
- **Wedge**: *arc angle* (degrees round the hinge edge) and *divisions* (segments round the arc). Forge (existing):
  `wedge(m, faces, hinge, { angle=90 (-360..360), divisions=4 (1..64) })`.

## Insert Edge Loop, Offset Edge Loop, Multi-Cut, Connect

- **Insert Edge Loop**: *maintain position* relative distance (default: the same fraction of every ring edge) or
  equal distance (the same length on every ring edge; the shortest edge limits it); *multiple edge loops* with
  *number of loops* (2 when on; 1 = one loop half way), the distance settings are unavailable then; *use equal
  multiplier*, *auto complete* (on), *fix quads* (off), *smoothing angle* (180), *insert with edge flow* (off).
  Forge: new `insertEdgeLoop(m, edge, { t=0.5 (0.01..0.99), count=1 (1..64), equalDistance=false, distance })` -
  t is measured from the given edge's first vertex and carried round the ring consistently; `count > 1` spaces the
  loops evenly; `equalDistance` uses `distance` (or t x the given edge's length) on every ring edge, limited to
  0.99 x the shortest. (`P.loopCut` stays as it was.)
- **Offset Edge Loop**: *delete edge* (keep quads at the ends of a partial loop), *edge offset* (0.5 of the way to
  the neighbours), *start / end vertex offset* (0), *smoothing angle* (180), *maintain position* relative / equal,
  *insert with edge flow*. Forge: `offsetEdgeLoop(m, edge, { distance=0.25 (0.01..0.95), count=1 (1..32),
  equalDistance=false })` - count: that many loops each side, out to `distance`; equalDistance: `distance` is a length.
- **Multi-Cut**: *snap step* (25 %), *smoothing angle* (180), *edge flow*, *subdivisions* (vertices along each new
  edge); its slice mode can delete or extract one side. Forge's `multiCut(m, points)` takes exact points (snapping
  is the UI's job); `sliceFaces` is the slice.
- **Connect**: *slide* (0.5: where across the face the new edge goes), *segments* (1: how many edges), *pinch*
  (spacing of several segments). Forge: `connect(m, { e }, { edgeCount=1 (1..64), slide=0.5 (0..1) })` - parallel
  cuts are paired across each face; slide is carried consistently round faces with two cut edges. Gap: pinch.

## Quadrangulate, Triangulate, Average Vertices, Merge

- **Quadrangulate**: *angle threshold* (30 degrees, 0..180), *keep face group border* (on), *keep hard edges* (on),
  *keep texture borders* (on), *world space* (off). Forge: `quadrangulate(m, faces, { angle=30, keepHardEdges=false })`
  - keepHardEdges never merges across an edge in `m.hard`; off by default so earlier results stay. Gaps: face groups,
  texture borders.
- **Triangulate**: no options. Forge: `triangulateFaces(m, faces)` (ear clipping, best-shaped ear first).
- **Average Vertices**: *iterations*. Forge (existing): `averageVerts(m, verts, { iterations=1 (1..200) })`.
- **Merge**: *threshold* distance (0: only coincident vertices merge), *always merge two vertices* (off), texture
  sewing (on). Forge: new `merge(m, verts, { threshold=0 (>= 0), alwaysMergeTwo=false })` ([] = all vertices) - merged
  groups go to their middle; faces that collapse or meet back to back go. (`P.mergeVerts` stays.)

## Duplicate / Extract

The reference chip-off / extract node has *duplicate* (on: copy, off: move them out), *keep faces together* (on),
*offset* (0: shrinks each piece's border), and local translate / rotate / scale for the separated faces; the menu
items add *separate* (make a new object). Forge: `duplicateFaces(m, faces)` and `extractFaces(m, faces)` (existing).
Gaps: offset / local transform of the pieces (use extrude offset or the transform tools), separate (Forge has no
objects inside one mesh; `P.shells` lists the pieces).

## Sources

- Cleanup Options: https://help.autodesk.com/cloudhelp/2017/ENU/Maya/files/GUID-AB60C982-C96E-4947-8CF3-5152406B6A40.htm
- Mesh > Cleanup: https://help.autodesk.com/cloudhelp/2015/ENU/MayaLT/files/Mesh__Cleanup.htm
- cleanup argument list (example): https://forums.autodesk.com/t5/maya-programming-forum/polycleanupargs-in-python/m-p/8113303
- Extrude Options: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Modeling/files/GUID-0026EDC2-E6F7-4C57-A22F-CA6D440CE4AD.htm
- extrude facet command: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polyExtrudeFacet.html
- Bridge Options: https://help.autodesk.com/cloudhelp/2017/ENU/Maya/files/GUID-FF2E45FA-F41A-488B-9426-FB0179DA9338.htm
- bridge edge command: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polyBridgeEdge.html
- Bevel Options: https://help.autodesk.com/cloudhelp/2017/ENU/Maya/files/GUID-A1C5EC72-AD48-4A7D-8577-1823B3832E14.htm
- bevel command: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polyBevel3.html
- poke command: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polyPoke.html
- Chamfer Vertices Options: https://help.autodesk.com/cloudhelp/2016/ENU/Maya/files/GUID-4735C74C-E9D1-46DE-AE8D-B7330FE9DCEB.htm
- Wedge Options: https://help.autodesk.com/cloudhelp/2016/ENU/Maya/files/GUID-8CCE10BD-F3DA-48C4-A09B-F8EF232EBE88.htm
- wedge command: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polyWedgeFace.html
- Insert Edge Loop Tool Options: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Modeling/files/GUID-226AECD6-F2C0-48D7-BE16-39E52EE7F075.htm
- split ring command: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polySplitRing.html
- Offset Edge Loop Tool Options: https://help.autodesk.com/cloudhelp/2017/ENU/Maya/files/GUID-40524144-6362-472D-A5BC-76DD9C52E299.htm
- duplicate edge command: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polyDuplicateEdge.html
- Multi-Cut Tool Options: https://help.autodesk.com/cloudhelp/2022/ENU/Maya-Modeling/files/GUID-B038B745-267E-4EDF-8201-EED826DC6837.htm
- Connect Tool Options: https://help.autodesk.com/cloudhelp/2017/ENU/Maya/files/GUID-2CC9A2F6-A3CA-436E-A39E-187B35BFAB46.htm
- quadrangulate command: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polyQuad.html
- average vertex command: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polyAverageVertex.html
- merge vertex command: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polyMergeVertex.html
- chip-off command: https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polyChipOff.html
