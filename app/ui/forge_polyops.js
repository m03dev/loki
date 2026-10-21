// Forge poly ops: the Edit Mesh / Modeling Toolkit operations of the pro tools (the reference modeller), on ForgePoly's
// { v, f } meshes. LOKI's own code, written from the tools' documented behaviour (no third-party code copied).
// Loads right after forge_poly.js (index.html) or with require() in node (tests/test_forge_polyops.py) and adds its
// functions onto the same ForgePoly object. Pure functions: no DOM, no three.js, the input mesh is never changed.
//
// Every op returns { m, sel, warn }:
//   m    - the NEW mesh (when the op cannot run: warn is set and m === the input mesh, unchanged)
//   sel  - what the pro tool leaves selected afterwards: { v: [vertIds], e: [[a, b], ...], f: [faceIds] } in m's ids
//          (edges are vertex pairs, so they stay meaningful across topology changes)
//   warn - "" or a short message like the one the pro tool prints (an op that ran in part also warns)
// Inputs: edges may be [a, b] vertex pairs, { a, b } or edge indices of P.topology(m); faces / verts are ids.
// Ops that take "components" accept { v } | { e } | { f } (an array of pairs counts as { e }, of numbers as { v }).
// Untouched faces keep their ids; new faces are appended at the end. Ops that remove faces (dissolve, collapse,
// weld, quadrangulate) shift the ids after the removed ones. Vertices that end up unused are dropped (ids compact).
// m.creases / m.hard (Map edgeKey -> value) are carried through every op (remapped, and dropped with their edge).
//
// THE OPS (signature -> what is selected afterwards)
//   extrudeFaces(m, faces, { thickness=0, offset=0, keepTogether=true,      -> the extruded caps (faces)
//                            divisions=1, taper=1, twist=0, localTranslate=[0,0,0] })
//       keepTogether: edge-connected faces move as one region (no inner walls); false: each face on its own.
//       thickness moves along the (averaged) normal, offset pulls the cap's border inward in its plane.
//       divisions: rings of walls along the extrusion; taper: the cap's scale (0..100, the rings in between go
//       linearly); twist: degrees the cap turns round the extrusion axis; localTranslate: x / y in the face's
//       plane (x along its first edge), z along the normal (adds to thickness).
//   extrudeEdges(m, edges, { thickness=0, offset=0, divisions=1, taper=1, twist=0, localTranslate=[0,0,0] })
//       -> the new outer edges. Each connected chain: x along it, y outward, z its normal; taper / twist work
//       round the way it moves.
//       each edge gets a quad to a copy of itself; connected edges share the new vertices. Border edges grow the
//       surface (offset = outward in the face's plane); an INTERIOR edge makes a fin (that edge then has 3 faces,
//       as in the pro tool). thickness 0 + offset 0: the new edges sit on the old (zero-area quads to be dragged).
//   extrudeVerts(m, verts, { width=0.1, length=0 })                        -> the tip vertices
//       width: fraction of each edge (max 0.49); every face around the vertex is cut and a triangle fan rises to
//       the vertex, moved `length` along its normal.
//   bevel(m, edges | { e } | { f }, { fraction=0.5, segments=1,            -> the new bevel faces
//         offsetAsFraction=true, offset=0.2, depth=1, chamfer=true, mitering="basic" })
//       width = fraction * 0.49 * the shortest edge at the bevelled vertices (offsetAsFraction false: width =
//       offset, limited to that maximum with a warning). depth -1..1 scales the rounded profile (segments > 1):
//       0 flat, negative hollow. chamfer false: a true circular arc instead of the quadratic profile.
//       Corners where 3+ bevelled edges meet
//       get a cap polygon; a cube with all 12 edges bevelled has 26 faces. segments > 1 rounds the profile.
//       faces: their border edges are bevelled. Border edges of the mesh cannot be bevelled.
//   bridge(m, edges, { divisions=0, bridgeType="linear", twist=0, taper=1, curve=[] })   -> the bridge faces
//       two border chains (open or closed) with the same edge count, joined by quads (closed loops twist-aligned).
//       bridgeType "smooth": the rows follow a curve leaving each border square to its faces; "curve": smooth and
//       the middle passes through the `curve` points. twist (degrees) / taper (the middle's width) on any type.
//   appendPolygon(m, verts)                                                -> the new face
//   fillHole(m, borderEdges)                                               -> the new faces
//   poke(m, faces, { offset=0 })                                           -> the new triangles
//   wedge(m, faces, hingeEdge, { angle=90, divisions=4 })                  -> the swung caps
//   chamferVerts(m, verts, { width=0.25, removeFace=false })               -> the new corner faces
//       removeFace: the corners are left open (then the new border edges are selected).
//   collapse(m, { e } | { f })                                             -> the merged vertices
//   connect(m, { v } | { e }, { edgeCount=1, slide=0.5 })                  -> the new edges
//       edges: midpoints; a face with 2 of them is split, with 3+ they meet at a new centre vertex.
//       edgeCount: parallel cuts per edge (evenly spaced); slide 0..1 moves them along the edges.
//       verts: a face with 2 (not neighbours) is split between them; with 3+ an inner polygon joins them.
//   detach(m, { v } | { e })                                               -> the split vertices / both sides' edges
//   dissolveEdges(m, edges, { cleanVerts=false })                          -> nothing (the pro Delete clears it)
//       the pro Delete on edges: the two faces merge into one n-gon; a border edge deletes its face; cleanVerts
//       (Ctrl+Delete) also removes the winged vertices (2 edges) left behind. (P.deleteEdges stays: it deletes faces.)
//   dissolveVerts(m, verts)                                                -> nothing
//       a winged vertex leaves its faces; an interior vertex's faces merge into one n-gon without it.
//   offsetEdgeLoop(m, edge(s), { distance=0.25, count=1, equalDistance=false })   -> the new loops
//       distance: fraction of the side edges (max 0.95); count: loops each side, out to distance; equalDistance:
//       distance is an absolute length on every side edge (limited by the shortest).
//   insertEdgeLoop(m, edge, { t=0.5, count=1, equalDistance=false, distance })   -> the new loop(s)
//       cuts the edge's ring of quads (P.loopCut stays); t from the given edge's first vertex; count > 1: evenly
//       spaced loops; equalDistance: the same absolute distance on every ring edge.
//   merge(m, verts, { threshold=0, alwaysMergeTwo=false })                 -> the merged vertices ([] = all)
//   multiCut(m, points)                                                    -> the new edges
//       points in order, each { v: id } or { e: [a, b], t: 0..1 from a }; consecutive points must share a face.
//   sliceFaces(m, faces, planePoint, planeNormal)                          -> the new edges ([] faces = all)
//   triangulateFaces(m, faces)  (P.triangulate is the GPU fan; kept)       -> the triangles ([] = all)
//   quadrangulate(m, faces, { angle=30, keepHardEdges=false })             -> the resulting faces ([] = all)
//   duplicateFaces(m, faces)                                               -> the copies
//   extractFaces(m, faces)                                                 -> the extracted faces (same ids)
//   averageVerts(m, verts, { iterations=1 }) / relax(m, verts, { iterations=1 })   -> the same vertices
//       relax pins border vertices and moves half way each pass; average moves all the way.
//   targetWeld(m, from, to)                                                -> the `to` vertex
//   circularize(m, { v } | { e } | { f })                                  -> the same components
//   spinEdge(m, edges, dir=+1)                                             -> the spun edges
//   slideEdge(m, edges, t)                                                 -> the same edges (t -1..1)
//   crease(m, edges, value=1) / setHard(m, edges, hard=true) / softHard(m, edges, { angle=30 })  -> the edges
//   meshCheck(m) -> { ok, closed, volume, border, nonManifold, flipped, degenerate, duplicate, unused, zeroArea }
//   cleanup(m, { op="cleanup"|"select", quads, nsided, concave, holed, nonPlanar (off), lamina, nonManifold,
//            zeroEdges, zeroFaces (on), lengthTol=1e-5, areaTol=1e-5, planarTol=1 })  -> { m, sel, warn, report }
//   meshStats(m) -> { verts, edges, faces, tris, quads, ngons, border, nonManifoldEdges, nonManifoldVerts, lamina, ... }
//   rules: P.polyRules (text) and P.canRun(op, m, ...args) (true when the op would run without a warning).
"use strict";

(function (root) {
  const P = typeof module !== "undefined" && module.exports && typeof require === "function"
    ? require("./forge_poly.js") : root.ForgePoly;

  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const len = (a) => Math.hypot(a[0], a[1], a[2]);
  const norm = (a) => { const l = len(a); return l > 1e-12 ? [a[0] / l, a[1] / l, a[2] / l] : [0, 0, 0]; };
  const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  const dist = (a, b) => len(sub(a, b));
  const ekey = P.edgeKey;
  const num = (x, d) => (x == null || !Number.isFinite(+x) ? d : +x);
  const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
  const uniq = (a) => [...new Set(a)];
  const push = (map, k, x) => { let l = map.get(k); if (!l) { l = []; map.set(k, l); } l.push(x); };

  // ------------------------------------------------------------------ plumbing
  function cp(m) {
    const o = { v: m.v.map((p) => p.slice()), f: m.f.map((f) => f.slice()) };
    if (m.creases instanceof Map) o.creases = new Map(m.creases);
    if (m.hard instanceof Map) o.hard = new Map(m.hard);
    return o;
  }
  const NONE = () => ({ v: [], e: [], f: [] });
  const fail = (m, warn) => ({ m, sel: NONE(), warn });
  // the result: unused vertices dropped (unless keep), selection + crease/hard maps remapped and checked
  function finish(m, sel, warn, keep) {
    const map = new Int32Array(m.v.length).fill(-1), v = [];
    let f;
    // unused vertices go, the rest keep their order (so ids only shift past a removed vertex)
    const used = new Uint8Array(m.v.length);
    if (keep) used.fill(1); else for (const face of m.f) for (const i of face) used[i] = 1;
    m.v.forEach((p, i) => { if (used[i]) { map[i] = v.length; v.push(p); } });
    f = keep ? m.f : m.f.map((face) => face.map((i) => map[i]));
    const at = (i) => (Number.isInteger(i) && i >= 0 && i < map.length ? map[i] : -1);
    const out = { v, f }, keys = new Set();
    for (const face of f) for (let k = 0; k < face.length; k++) keys.add(ekey(face[k], face[(k + 1) % face.length]));
    for (const name of ["creases", "hard"]) {
      if (!(m[name] instanceof Map)) continue;
      const mp = new Map();
      for (const [key, val] of m[name]) {
        const [a, b] = String(key).split(",").map(Number), A = at(a), B = at(b);
        if (A >= 0 && B >= 0 && keys.has(ekey(A, B))) mp.set(ekey(A, B), val);
      }
      out[name] = mp;
    }
    const s = sel || {}, seen = new Set(), e = [];
    for (const pr of s.e || []) {
      const A = at(pr[0]), B = at(pr[1]), k = ekey(A, B);
      if (A >= 0 && B >= 0 && keys.has(k) && !seen.has(k)) { seen.add(k); e.push([A, B]); }
    }
    return {
      m: out,
      sel: { v: uniq((s.v || []).map(at).filter((i) => i >= 0)), e, f: uniq((s.f || []).filter((i) => i >= 0 && i < f.length)) },
      warn: warn || "",
    };
  }
  function faceSel(m, fids) {
    const v = new Set(), e = new Map();
    for (const fi of fids) {
      const f = m.f[fi];
      if (!f) continue;
      for (let k = 0; k < f.length; k++) { const a = f[k], b = f[(k + 1) % f.length]; v.add(a); e.set(ekey(a, b), [a, b]); }
    }
    return { v: [...v], e: [...e.values()], f: fids.slice() };
  }
  const edgeSel = (pairs) => ({ v: uniq(pairs.flat()), e: pairs, f: [] });
  function edgeIds(m, T, edges) {
    const out = new Set();
    for (const x of edges || []) {
      let ei;
      if (typeof x === "number") ei = T.edges[x] ? x : undefined;
      else if (Array.isArray(x)) ei = T.edge(x[0], x[1]);
      else if (x && x.a != null) ei = T.edge(x.a, x.b);
      if (ei !== undefined) out.add(ei);
    }
    return [...out];
  }
  const faceIds = (m, faces) => uniq((faces || []).filter((i) => Number.isInteger(i) && i >= 0 && i < m.f.length));
  const vertIds = (m, verts) => uniq((verts || []).filter((i) => Number.isInteger(i) && i >= 0 && i < m.v.length));
  function comp(x) {
    if (!x) return {};
    if (Array.isArray(x)) return x.length && (Array.isArray(x[0]) || (x[0] && typeof x[0] === "object")) ? { e: x } : { v: x };
    return x;
  }
  function UF() {
    const p = new Map();
    const find = (x) => {
      if (!p.has(x)) p.set(x, x);
      let r = x;
      while (p.get(r) !== r) r = p.get(r);
      while (p.get(x) !== r) { const n = p.get(x); p.set(x, r); x = n; }
      return r;
    };
    return { find, union: (a, b) => { a = find(a); b = find(b); if (a !== b) p.set(a, b); } };
  }
  function cyc(face, i, j) {          // face[i..j] going forward, both ends included
    const out = [], n = face.length;
    for (let k = i; ; k = (k + 1) % n) { out.push(face[k]); if (k === j) break; }
    return out;
  }
  const splitAt = (face, i, j) => [cyc(face, i, j), cyc(face, j, i)];
  const adjacentIn = (face, i, j) => { const n = face.length; return (j - i + n) % n === 1 || (i - j + n) % n === 1; };
  function dedupeCyc(face) {
    const g = [];
    for (const i of face) if (g[g.length - 1] !== i) g.push(i);
    while (g.length > 1 && g[0] === g[g.length - 1]) g.pop();
    return g;
  }
  // a face that touches itself is split into simple loops; loops under 3 vertices go
  function cleanFace(face) {
    const g = dedupeCyc(face);
    for (let i = 0; i < g.length; i++) for (let j = i + 1; j < g.length; j++) {
      if (g[i] === g[j]) return [...cleanFace(g.slice(i, j)), ...cleanFace(g.slice(j).concat(g.slice(0, i)))];
    }
    return g.length >= 3 ? [g] : [];
  }
  function sameCycle(A, B) {
    if (A.length !== B.length) return false;
    const k = B.indexOf(A[0]);
    if (k < 0) return false;
    for (let i = 0; i < A.length; i++) if (A[i] !== B[(k + i) % B.length]) return false;
    return true;
  }
  // after merging vertices: simple loops only, and two faces on the same vertices go (back to back: both; twins: one)
  function cleanMesh(faces) {
    const out = [];
    for (const f of faces) out.push(...cleanFace(f));
    const byKey = new Map();
    out.forEach((f, i) => push(byKey, f.slice().sort((a, b) => a - b).join(","), i));
    const drop = new Set();
    for (const list of byKey.values()) {
      if (list.length < 2) continue;
      for (let x = 0; x < list.length; x++) {
        if (drop.has(list[x])) continue;
        for (let y = x + 1; y < list.length; y++) {
          if (drop.has(list[y])) continue;
          const A = out[list[x]], B = out[list[y]];
          if (sameCycle(A, B.slice().reverse())) { drop.add(list[x]); drop.add(list[y]); break; }
          if (sameCycle(A, B)) drop.add(list[y]);
        }
      }
    }
    return out.filter((_, i) => !drop.has(i));
  }
  // the border loops of a set of faces (each a->b as the faces run); err when a vertex is pinched (bowtie)
  function regionLoops(m, fids) {
    const dir = new Set();
    for (const fi of fids) { const f = m.f[fi]; for (let k = 0; k < f.length; k++) dir.add(f[k] + ">" + f[(k + 1) % f.length]); }
    const next = new Map();
    for (const fi of fids) {
      const f = m.f[fi];
      for (let k = 0; k < f.length; k++) {
        const a = f[k], b = f[(k + 1) % f.length];
        if (dir.has(b + ">" + a)) continue;
        if (next.has(a)) return { err: "the merged faces would touch themselves at a vertex" };
        next.set(a, b);
      }
    }
    const loops = [], seen = new Set();
    for (const s of next.keys()) {
      if (seen.has(s)) continue;
      const L = [];
      let x = s;
      while (x !== undefined && !seen.has(x)) { seen.add(x); L.push(x); x = next.get(x); }
      if (x !== s) return { err: "the border does not close" };
      loops.push(L);
    }
    return { loops };
  }
  // put new vertices (ordered from a to b) into every face that uses the edge a-b
  function insertOnEdge(m, a, b, ids, faceList) {
    for (const fi of faceList) {
      const f = m.f[fi], n = f.length;
      for (let k = 0; k < n; k++) {
        const x = f[k], y = f[(k + 1) % n];
        if (x === a && y === b) { f.splice(k + 1, 0, ...ids); break; }
        if (x === b && y === a) { f.splice(k + 1, 0, ...ids.slice().reverse()); break; }
      }
    }
  }
  function neighbours(m) {
    const nb = m.v.map(() => new Set());
    for (const f of m.f) for (let k = 0; k < f.length; k++) { const a = f[k], b = f[(k + 1) % f.length]; nb[a].add(b); nb[b].add(a); }
    return nb;
  }
  function vertNormal(m, T, x) {
    let n = [0, 0, 0];
    for (const fi of uniq(T.vertFaces[x])) n = add(n, P.faceNormal(m, m.f[fi]));
    return norm(n);
  }
  function newellArea(m, f) {
    let n = [0, 0, 0];
    for (let i = 0; i < f.length; i++) {
      const a = m.v[f[i]], b = m.v[f[(i + 1) % f.length]];
      n = add(n, [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])]);
    }
    return len(n) / 2;
  }

  // ------------------------------------------------------------------ the rules the pro tools follow
  P.polyRules = {
    extrudeFaces: "Needs faces. Keep Faces Together moves edge-connected faces as one piece; off, every face gets its own walls.",
    extrudeEdges: "Needs edges. A border edge grows the surface; an interior edge makes a fin (non-manifold, like the pro tool).",
    extrudeVerts: "Needs vertices; each becomes a spike (triangle fan) with its base on the edges around it.",
    bevel: "Needs interior edges (or faces: their border edges). Border edges of the mesh cannot be bevelled.",
    bridge: "Needs exactly two border chains (edges with one face each) with the same number of edges; both open or both closed loops. They must not touch.",
    appendPolygon: "Needs 3+ different vertices; none of the new face's edges may already have two faces.",
    fillHole: "Needs border edges; the border loops through them get a face each.",
    poke: "Needs faces.",
    wedge: "Needs faces and one hinge edge on the border of those faces.",
    chamferVerts: "Needs vertices.",
    collapse: "Needs edges or faces; each connected group becomes one vertex at its centre.",
    connect: "Edges: two selected edges of the same face are joined through their midpoints. Vertices: they must share a face and not already be joined by an edge.",
    detach: "Vertices: every face gets its own copy. Edges: a chain only opens where it reaches a border or closes a loop.",
    dissolveEdges: "Interior edge: its two faces become one (a merged region needs exactly one border loop). Border edge: its face goes.",
    dissolveVerts: "A winged vertex (2 edges) is removed; an interior vertex merges its faces. A corner vertex of a single face cannot be deleted without deleting the face.",
    offsetEdgeLoop: "Needs an edge whose loop has quads on both sides.",
    multiCut: "Every two consecutive cut points must lie on the same face.",
    triangulateFaces: "Any faces (none selected: the whole mesh).",
    quadrangulate: "Merges neighbouring triangles when the quad is convex and the triangles bend less than the angle.",
    duplicateFaces: "Needs faces.",
    extractFaces: "Needs faces that share vertices with faces outside the selection.",
    averageVerts: "Needs vertices.",
    relax: "Border vertices stay pinned.",
    targetWeld: "Needs two different vertices of the mesh.",
    circularize: "Needs a closed loop of vertices or edges, or a patch of faces with one border.",
    spinEdge: "Needs interior edges between two faces; the spun edge must not exist already and each end keeps at least 2 edges.",
    slideEdge: "Needs edges; each end slides along a side edge of the faces beside it (borders stay put on their open side).",
    crease: "Edges get a crease weight for the subdivision preview (0 removes it).",
    softHard: "Edges whose faces meet at more than the angle become hard; the others soft. Border edges are hard.",
    insertEdgeLoop: "Needs an edge with a quad beside it; the loop runs across the ring of quads and stops at other faces.",
    merge: "Needs two or more vertices closer than the threshold (or exactly two with Always Merge).",
    cleanup: "Select finds the faces / edges / vertices that match; Cleanup fixes them. Non-manifold fixes run last.",
  };
  P.canRun = (op, m, ...args) => { try { return typeof P[op] === "function" && !P[op](m, ...args).warn; } catch (e) { return false; } };

  // ------------------------------------------------------------------ mesh check (the tests and the UI use it)
  P.meshCheck = (m) => {
    const r = { faces: m.f.length, verts: m.v.length, degenerate: 0, duplicate: 0, unused: 0, badIndex: 0, border: 0,
      nonManifold: 0, flipped: 0, zeroArea: 0 };
    const used = new Uint8Array(m.v.length), dir = new Map(), und = new Map(), keys = new Set();
    for (const f of m.f) {
      if (f.length < 3 || new Set(f).size !== f.length) r.degenerate++;
      if (f.some((i) => !(Number.isInteger(i) && i >= 0 && i < m.v.length))) { r.badIndex++; continue; }
      const k = f.slice().sort((a, b) => a - b).join(",");
      if (keys.has(k)) r.duplicate++; keys.add(k);
      if (newellArea(m, f) < 1e-12) r.zeroArea++;
      for (let i = 0; i < f.length; i++) {
        const a = f[i], b = f[(i + 1) % f.length];
        used[a] = 1;
        dir.set(a + ">" + b, (dir.get(a + ">" + b) || 0) + 1);
        und.set(ekey(a, b), (und.get(ekey(a, b)) || 0) + 1);
      }
    }
    for (const u of used) if (!u) r.unused++;
    for (const c of dir.values()) if (c > 1) r.flipped++;
    for (const c of und.values()) { if (c === 1) r.border++; else if (c > 2) r.nonManifold++; }
    r.closed = r.border === 0 && r.nonManifold === 0 && r.flipped === 0;
    r.volume = P.volume(m);
    r.ok = !r.degenerate && !r.duplicate && !r.unused && !r.badIndex && !r.flipped && !r.nonManifold;
    return r;
  };

  // ------------------------------------------------------------------ shaping helpers (taper / twist / frames)
  const DEG = Math.PI / 180;
  const vec3 = (x) => (Array.isArray(x) && x.length === 3 && x.every((y) => Number.isFinite(+y)) ? x.map(Number) : [0, 0, 0]);
  function perp(n) {                                   // any unit vector perpendicular to n
    const a = Math.abs(n[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
    return norm(sub(a, mul(n, dot(a, n))));
  }
  function rotAxis(p, c, axis, th) {                   // p turned th radians round the axis through c
    const v = sub(p, c), cs = Math.cos(th), sn = Math.sin(th);
    return add(c, add(add(mul(v, cs), mul(cross(axis, v), sn)), mul(axis, dot(axis, v) * (1 - cs))));
  }
  // p scaled by f about c across the axis (the part along the axis is kept), then turned th round it
  function taperTwist(p, c, axis, f, th) {
    let v = sub(p, c);
    const h = dot(v, axis);
    v = add(mul(axis, h), mul(sub(v, mul(axis, h)), f));
    const q = add(c, v);
    return th ? rotAxis(q, c, axis, th) : q;
  }
  const centreOf = (pts) => mul(pts.reduce((s, p) => add(s, p), [0, 0, 0]), 1 / (pts.length || 1));
  function shapeOpts(o, dDef) {
    const D = clamp(Math.round(num(o.divisions, dDef)), dDef === 0 ? 0 : 1, 256);
    const taper = clamp(num(o.taper, 1), 0, 100), twist = clamp(num(o.twist, 0), -3600, 3600) * DEG;
    return { D, taper, twist, lt: vec3(o.localTranslate), shaped: taper !== 1 || twist !== 0 };
  }

  // ------------------------------------------------------------------ extrude
  // the extra options (pro Extrude option box): divisions (segments along the extrusion), taper (scale of the cap,
  // 1 = none, the middle segments go linearly), twist (degrees round the extrusion axis, spread over the segments),
  // localTranslate [x, y, z] in the face frame (z = along the normal, adds to thickness; x along the first edge).
  P.extrudeFaces = (m0, faces, o) => {
    o = o || {};
    const th = num(o.thickness, 0), off = num(o.offset, 0), together = o.keepTogether !== false;
    const S = shapeOpts(o, 1);
    const sel = faceIds(m0, faces);
    if (!sel.length) return fail(m0, "Extrude: select one or more faces.");
    const T = P.topology(m0), m = cp(m0), inSel = new Set(sel);
    let groups;
    if (together) {
      const uf = UF();
      for (const fi of sel) {
        uf.find(fi);
        for (const ei of T.faceEdges[fi]) for (const g of T.edges[ei].faces) if (g !== fi && inSel.has(g)) uf.union(fi, g);
      }
      const gm = new Map();
      for (const fi of sel) push(gm, uf.find(fi), fi);
      groups = [...gm.values()];
    } else groups = sel.map((fi) => [fi]);
    for (const g of groups) {
      const gs = new Set(g), nrm = new Map(), inward = new Map(), bnd = [];
      for (const fi of g) {
        const f = m0.f[fi], n = P.faceNormal(m0, f);
        for (const i of f) nrm.set(i, add(nrm.get(i) || [0, 0, 0], n));
        for (let k = 0; k < f.length; k++) {
          const a = f[k], b = f[(k + 1) % f.length], ei = T.edge(a, b);
          if (T.edges[ei].faces.filter((x) => gs.has(x)).length !== 1) continue;
          bnd.push([a, b]);
          const p = norm(cross(n, sub(m0.v[b], m0.v[a])));       // into the face, in its plane
          for (const x of [a, b]) push(inward, x, p);
        }
      }
      // the group's frame: z = the averaged normal, x = along its first face's first edge
      let gn = [0, 0, 0];
      for (const fi of g) gn = add(gn, P.faceNormal(m0, m0.f[fi]));
      gn = norm(gn);
      if (!len(gn)) gn = [0, 1, 0];
      const f0 = m0.f[g[0]];
      let gu = sub(m0.v[f0[1]], m0.v[f0[0]]);
      gu = norm(sub(gu, mul(gn, dot(gu, gn))));
      if (!len(gu)) gu = perp(gn);
      const gw = cross(gn, gu), shift = add(add(mul(gu, S.lt[0]), mul(gw, S.lt[1])), mul(gn, S.lt[2]));
      const end = new Map();
      for (const [i, ns] of nrm) {
        let p = add(m0.v[i], mul(norm(ns), th));
        const w = inward.get(i);
        if (off && w) {          // a mitred inset: every border edge moves `off` inward
          const mi = norm(w.reduce((s, q) => add(s, q), [0, 0, 0]));
          const c = Math.max(0.25, w.reduce((s, q) => s + dot(mi, q), 0) / w.length);
          p = add(p, mul(mi, off / c));
        }
        end.set(i, S.lt[0] || S.lt[1] || S.lt[2] ? add(p, shift) : p);
      }
      const layers = [];
      for (let k = 1; k <= S.D; k++) {
        const s = k / S.D, pos = new Map(), L = new Map();
        for (const [i, p] of end) pos.set(i, k === S.D ? p : lerp(m0.v[i], p, s));
        const c = S.shaped ? centreOf([...pos.values()]) : null;
        for (const [i, p] of pos) {
          L.set(i, m.v.length);
          m.v.push(S.shaped ? taperTwist(p, c, gn, 1 + (S.taper - 1) * s, S.twist * s) : p);
        }
        layers.push(L);
      }
      const at = (k, i) => (k === 0 ? i : layers[k - 1].get(i));
      for (const [a, b] of bnd) for (let k = 0; k < S.D; k++) m.f.push([at(k, a), at(k, b), at(k + 1, b), at(k + 1, a)]);
      for (const fi of g) m.f[fi] = m0.f[fi].map((i) => at(S.D, i));
    }
    return finish(m, faceSel(m, sel));
  };

  P.extrudeEdges = (m0, edges, o) => {
    o = o || {};
    const th = num(o.thickness, 0), off = num(o.offset, 0);
    const T = P.topology(m0), ids = edgeIds(m0, T, edges).filter((ei) => T.edges[ei].faces.length >= 1);
    if (!ids.length) return fail(m0, "Extrude: select one or more edges.");
    const m = cp(m0), nrm = new Map(), out = new Map(), spans = [];
    for (const ei of ids) {
      const e = T.edges[ei], f0 = m0.f[e.faces[0]], k = f0.indexOf(e.a);
      const fwd = f0[(k + 1) % f0.length] === e.b, x = fwd ? e.a : e.b, y = fwd ? e.b : e.a;   // x->y in faces[0]
      let n = [0, 0, 0];
      for (const fi of e.faces) n = add(n, P.faceNormal(m0, m0.f[fi]));
      for (const i of [x, y]) nrm.set(i, add(nrm.get(i) || [0, 0, 0], n));
      if (e.faces.length === 1) {
        const ou = norm(cross(sub(m0.v[y], m0.v[x]), P.faceNormal(m0, f0)));   // away from the face
        for (const i of [x, y]) out.set(i, add(out.get(i) || [0, 0, 0], ou));
      }
      spans.push([x, y]);
    }
    const S = shapeOpts(o, 1), end = new Map();
    for (const [i, n] of nrm) {
      let p = add(m0.v[i], mul(norm(n), th));
      const ou = out.get(i);
      if (off && ou) p = add(p, mul(norm(ou), off));
      end.set(i, p);
    }
    // each connected chain gets a frame (z = its averaged normal, x = along the chain, y = outward) for
    // localTranslate, and an axis (the way it moves) that taper and twist work round
    const pos = new Map();                                 // i -> the positions of its copies, layer 1..D
    const moved = S.shaped || S.lt[0] || S.lt[1] || S.lt[2];
    if (!moved) for (const [i, p] of end) pos.set(i, Array.from({ length: S.D }, (_, k) => (k + 1 === S.D ? p : lerp(m0.v[i], p, (k + 1) / S.D))));
    else {
      const uf = UF();
      for (const [x, y] of spans) uf.union(x, y);
      const comps = new Map();
      for (const i of nrm.keys()) push(comps, uf.find(i), i);
      for (const [root, vs] of comps) {
        let z = [0, 0, 0], ou = [0, 0, 0];
        for (const i of vs) { z = add(z, nrm.get(i)); if (out.has(i)) ou = add(ou, out.get(i)); }
        z = norm(z);
        if (!len(z)) z = [0, 1, 0];
        const sp = spans.find(([x]) => uf.find(x) === root);
        let x = sub(m0.v[sp[1]], m0.v[sp[0]]);
        x = norm(sub(x, mul(z, dot(x, z))));
        if (!len(x)) x = perp(z);
        let y = cross(z, x);
        if (dot(y, ou) < 0) y = mul(y, -1);
        const shift = add(add(mul(x, S.lt[0]), mul(y, S.lt[1])), mul(z, S.lt[2]));
        let disp = [0, 0, 0];
        for (const i of vs) disp = add(disp, sub(add(end.get(i), shift), m0.v[i]));
        const axis = len(disp) > 1e-12 ? norm(disp) : z;
        for (const i of vs) pos.set(i, []);
        for (let k = 1; k <= S.D; k++) {
          const s = k / S.D, lay = vs.map((i) => lerp(m0.v[i], add(end.get(i), shift), s)), c = centreOf(lay);
          vs.forEach((i, j) => pos.get(i).push(S.shaped ? taperTwist(lay[j], c, axis, 1 + (S.taper - 1) * s, S.twist * s) : lay[j]));
        }
      }
    }
    const lay = [];                                       // lay[k]: i -> id (k = 1..D), ids made in today's order
    for (let k = 1; k <= S.D; k++) {
      const L = new Map();
      for (const i of nrm.keys()) { L.set(i, m.v.length); m.v.push(pos.get(i)[k - 1]); }
      lay[k] = L;
    }
    const at = (k, i) => (k === 0 ? i : lay[k].get(i));
    const newE = [];
    for (const [x, y] of spans) {
      for (let k = 0; k < S.D; k++) m.f.push([at(k, y), at(k, x), at(k + 1, x), at(k + 1, y)]);
      newE.push([at(S.D, x), at(S.D, y)]);
    }
    return finish(m, edgeSel(newE));
  };

  // cut every face corner at the given vertices `t` along its two edges (chamfer), or raise a spike (vertex extrude)
  function cornerCut(m0, verts, t, tip, noFace) {
    const T = P.topology(m0), S = new Set(vertIds(m0, verts).filter((x) => T.vertFaces[x].length));
    if (!S.size) return null;
    const m = cp(m0), pt = new Map(), around = new Map(), newF = [], tips = [];
    const at = (x, y) => {
      const k = x + ">" + y;
      if (!pt.has(k)) { pt.set(k, m.v.length); m.v.push(lerp(m0.v[x], m0.v[y], t)); }
      return pt.get(k);
    };
    m.f = m0.f.map((f) => {
      const out = [], n = f.length;
      for (let k = 0; k < n; k++) {
        const x = f[k];
        if (!S.has(x)) { out.push(x); continue; }
        const a = at(x, f[(k + n - 1) % n]), b = at(x, f[(k + 1) % n]);
        out.push(a, b); push(around, x, [a, b]);          // this face now runs a -> b past the corner
      }
      return out;
    });
    for (const x of S) {
      const list = around.get(x) || [];
      if (tip) {
        m.v[x] = add(m0.v[x], mul(vertNormal(m0, T, x), tip.length));
        for (const [a, b] of list) { newF.push(m.f.length); m.f.push([b, a, x]); }
        tips.push(x);
        continue;
      }
      const nx = new Map(), incoming = new Set();
      for (const [a, b] of list) { nx.set(b, a); incoming.add(a); }
      let start = [...nx.keys()].find((k) => !incoming.has(k));     // an open fan (border vertex) starts at its end
      if (start === undefined) start = list.length ? list[0][1] : undefined;
      if (start === undefined) continue;
      const loop = [];
      for (let y = start, g = 0; y !== undefined && g <= list.length; g++) { loop.push(y); y = nx.get(y); if (y === start) break; }
      const ring = uniq(loop);
      if (ring.length >= 3 && !noFace) { newF.push(m.f.length); m.f.push(ring); }
    }
    return { m, newF, tips };
  }
  P.extrudeVerts = (m0, verts, o) => {
    o = o || {};
    const r = cornerCut(m0, verts, clamp(num(o.width, 0.1), 0.001, 0.49), { length: num(o.length, 0) });
    if (!r) return fail(m0, "Extrude: select one or more vertices that belong to faces.");
    return finish(r.m, { v: r.tips, e: [], f: [] });
  };
  P.chamferVerts = (m0, verts, o) => {
    o = o || {};
    // removeFace (the pro "Remove the face after chamfer"): the cut corners are left open (border edges)
    const r = cornerCut(m0, verts, clamp(num(o.width, 0.25), 0.001, 0.49), null, !!o.removeFace);
    if (!r) return fail(m0, "Chamfer Vertex: select one or more vertices that belong to faces.");
    if (o.removeFace) {
      const T = P.topology(r.m), e = T.edges.filter((x) => x.faces.length === 1 && x.a >= m0.v.length && x.b >= m0.v.length).map((x) => [x.a, x.b]);
      return finish(r.m, edgeSel(e));
    }
    return finish(r.m, faceSel(r.m, r.newF));
  };

  // ------------------------------------------------------------------ delete (dissolve) edges / vertices
  function removeWinged(v, faces, cand) {
    const nb = new Map(), fc = new Map();
    faces.forEach((f, fi) => {
      for (let k = 0; k < f.length; k++) {
        const a = f[k], b = f[(k + 1) % f.length];
        if (!nb.has(a)) nb.set(a, new Set()); if (!nb.has(b)) nb.set(b, new Set());
        nb.get(a).add(b); nb.get(b).add(a); push(fc, a, fi);
      }
    });
    for (const x of cand) {
      const n = nb.get(x), fs = fc.get(x) || [];
      if (!n || n.size !== 2 || fs.length > 2 || !fs.length) continue;
      if (fs.length === 1) {                                     // on a border: only when it is a straight run
        const [a, b] = [...n], da = norm(sub(v[a], v[x])), db = norm(sub(v[b], v[x]));
        if (dot(da, db) > -0.99) continue;
      }
      if (fs.some((fi) => faces[fi].length <= 3)) continue;
      for (const fi of fs) faces[fi] = faces[fi].filter((y) => y !== x);
    }
    return faces;
  }
  P.dissolveEdges = (m0, edges, o) => {
    o = o || {};
    const T = P.topology(m0), ids = edgeIds(m0, T, edges);
    if (!ids.length) return fail(m0, "Delete Edge: select one or more edges.");
    const uf = UF(), joined = new Set(), drop = new Set(), touched = new Set(), warns = [];
    for (const ei of ids) {
      const e = T.edges[ei];
      touched.add(e.a); touched.add(e.b);
      if (e.faces.length === 2 && e.faces[0] !== e.faces[1]) { uf.union(e.faces[0], e.faces[1]); joined.add(e.faces[0]); joined.add(e.faces[1]); }
      else if (e.faces.length === 1) drop.add(e.faces[0]);
      else warns.push("a non-manifold edge was skipped");
    }
    const groups = new Map();
    for (const fi of joined) push(groups, uf.find(fi), fi);
    const f = m0.f.map((x) => x.slice()), gone = new Set();
    let changed = false;
    for (const g of groups.values()) {
      if (g.some((fi) => drop.has(fi))) { g.forEach((fi) => gone.add(fi)); changed = true; continue; }
      const r = regionLoops(m0, g);
      if (r.err || r.loops.length !== 1) {
        warns.push(r.err ? "some edges were kept: " + r.err : r.loops.length ? "some edges were kept: the merged face would have a hole" : "some edges were kept: that would delete the whole surface");
        continue;
      }
      g.sort((a, b) => a - b);
      f[g[0]] = r.loops[0];
      g.slice(1).forEach((fi) => gone.add(fi));
      changed = true;
    }
    for (const fi of drop) if (!gone.has(fi)) { gone.add(fi); changed = true; }
    if (!changed) return fail(m0, "Delete Edge: " + (warns[0] || "nothing to delete").replace(/^some edges were kept: /, "cannot delete - "));
    let nf = f.filter((_, i) => !gone.has(i));
    if (o.cleanVerts) nf = removeWinged(m0.v, nf, touched);
    const m = cp(m0); m.f = nf;
    return finish(m, NONE(), warns.length ? "Delete Edge: " + uniq(warns).join("; ") + "." : "");
  };
  P.dissolveVerts = (m0, verts) => {
    const vs = vertIds(m0, verts);
    if (!vs.length) return fail(m0, "Delete Vertex: select one or more vertices.");
    const T = P.topology(m0), W = new Set(), D = new Set(), warns = [];
    for (const x of vs) {
      const fs = uniq(T.vertFaces[x]), val = T.vertEdges[x].length;
      if (!fs.length) { warns.push("vertex " + x + " has no faces"); continue; }
      if (val === 2 && fs.length === 2) { W.add(x); continue; }
      if (fs.length === 1) {
        const f = m0.f[fs[0]], k = f.indexOf(x), a = f[(k + f.length - 1) % f.length], b = f[(k + 1) % f.length];
        const straight = dot(norm(sub(m0.v[a], m0.v[x])), norm(sub(m0.v[b], m0.v[x]))) < -0.99;
        if (val === 2 && straight && f.length > 3) W.add(x);
        else warns.push("vertex " + x + " is the corner of a single face - delete the face instead");
        continue;
      }
      D.add(x);
    }
    const uf = UF();
    for (const x of D) { const fs = uniq(T.vertFaces[x]); for (const fi of fs) uf.union(fs[0], fi); }
    const groups = new Map();
    for (const x of D) for (const fi of uniq(T.vertFaces[x])) push(groups, uf.find(fi), fi);
    const f = m0.f.map((x) => x.slice()), gone = new Set();
    let done = 0;
    for (const g0 of groups.values()) {
      const g = uniq(g0).sort((a, b) => a - b), r = regionLoops(m0, g);
      if (r.err || r.loops.length !== 1) { warns.push("some vertices were kept: " + (r.err || "their faces would leave a hole")); continue; }
      const loop = r.loops[0].filter((x) => !D.has(x) && !W.has(x));
      if (loop.length < 3) { warns.push("some vertices were kept: too few vertices would be left"); continue; }
      f[g[0]] = loop;
      g.slice(1).forEach((fi) => gone.add(fi));
      done++;
    }
    for (let fi = 0; fi < f.length; fi++) {
      if (gone.has(fi)) continue;
      const keep = f[fi].filter((x) => !W.has(x));
      if (keep.length === f[fi].length) continue;
      if (keep.length < 3) { warns.push("a winged vertex on a triangle was kept"); continue; }
      f[fi] = keep; done++;
    }
    if (!done) return fail(m0, "Delete Vertex: " + (warns[0] || "nothing to delete") + ".");
    const m = cp(m0); m.f = f.filter((_, i) => !gone.has(i));
    return finish(m, NONE(), warns.length ? "Delete Vertex: " + uniq(warns).join("; ") + "." : "");
  };

  // ------------------------------------------------------------------ bevel
  P.bevel = (m0, items, o) => {
    o = o || {};
    const T = P.topology(m0);
    let ids;
    if (items && !Array.isArray(items) && items.f) {
      const fs = new Set(faceIds(m0, items.f)), c = new Map();
      for (const fi of fs) for (const ei of T.faceEdges[fi]) c.set(ei, (c.get(ei) || 0) + 1);
      ids = [...c].filter(([, n]) => n === 1).map(([ei]) => ei);
    } else ids = edgeIds(m0, T, items && !Array.isArray(items) ? items.e : items);
    ids = ids.filter((ei) => T.edges[ei].faces.length === 2 && T.edges[ei].faces[0] !== T.edges[ei].faces[1]);
    if (!ids.length) return fail(m0, "Bevel: select interior edges or faces (border edges cannot be bevelled).");
    const frac = clamp(num(o.fraction, 0.5), 0.01, 1), segs = clamp(Math.round(num(o.segments, 1)), 1, 32);
    const S = new Set(ids), BV = new Set();
    for (const ei of ids) { BV.add(T.edges[ei].a); BV.add(T.edges[ei].b); }
    let minLen = Infinity;
    for (const x of BV) for (const ei of T.vertEdges[x]) minLen = Math.min(minLen, dist(m0.v[T.edges[ei].a], m0.v[T.edges[ei].b]));
    // offsetAsFraction (default true): width = fraction of the shortest edge; false: `offset` is an absolute width
    // (limited so the bevel cannot turn inside out). depth (1) scales the rounded profile's bulge (0 flat, -1 hollow);
    // chamfer (true) keeps the quadratic profile, false gives a true circular (fillet) arc. mitering: "basic" only.
    let d = frac * 0.49 * minLen;
    const warnB = [];
    if (o.offsetAsFraction === false) {
      const want = Math.max(1e-9, num(o.offset, 0.2));
      d = Math.min(want, 0.49 * minLen);
      if (want > d + 1e-12) warnB.push("the offset was limited to " + +d.toFixed(6) + " so the bevel cannot turn inside out");
    }
    const depth = clamp(num(o.depth, 1), -1, 1), arc = o.chamfer === false;
    const miter = String(o.mitering == null ? "basic" : o.mitering).toLowerCase();
    if (!["basic", "uniform", "auto"].includes(miter)) warnB.push("only basic mitering is supported (used basic)");
    const m = cp(m0), slideD = new Map(), corners = [], owner = new Map();
    m0.f.forEach((f, fi) => {
      const n = f.length;
      for (let k = 0; k < n; k++) {
        const v = f[k];
        if (!BV.has(v)) continue;
        const pv = f[(k + n - 1) % n], nx = f[(k + 1) % n], ein = T.edge(pv, v), eout = T.edge(v, nx);
        const a = norm(sub(m0.v[pv], m0.v[v])), b = norm(sub(m0.v[nx], m0.v[v])), s = Math.max(0.2, len(cross(a, b)));
        const sIn = S.has(ein), sOut = S.has(eout);
        if (sIn && !sOut) push(slideD, eout + "|" + v, d / s);
        if (!sIn && sOut) push(slideD, ein + "|" + v, d / s);
        corners.push({ fi, v, ein, eout, sIn, sOut, a, b, s });
      }
    });
    const newPt = (p, v) => { const id = m.v.length; m.v.push(p); owner.set(id, v); return id; };
    for (const x of BV) owner.set(x, x);
    const slideId = new Map();
    for (const [key, ds] of slideD) {         // the point where the bevel's side meets an edge it does not bevel
      const [ei, v] = key.split("|").map(Number), e = T.edges[ei], u = e.a === v ? e.b : e.a, L = dist(m0.v[v], m0.v[u]);
      const t = Math.min(ds.reduce((x, y) => x + y, 0) / ds.length, 0.49 * L);
      slideId.set(key, newPt(lerp(m0.v[v], m0.v[u], L ? t / L : 0), v));
    }
    const rep = new Map();
    for (const c of corners) {
      let r;
      if (c.sIn && c.sOut) r = [newPt(add(m0.v[c.v], mul(add(c.a, c.b), d / c.s)), c.v)];
      else if (c.sIn) r = [slideId.get(c.eout + "|" + c.v)];
      else if (c.sOut) r = [slideId.get(c.ein + "|" + c.v)];
      else {
        const si = slideId.get(c.ein + "|" + c.v), so = slideId.get(c.eout + "|" + c.v);
        r = si !== undefined && so !== undefined ? [si, so] : [si, c.v, so].filter((x) => x !== undefined);
      }
      rep.set(c.fi + "|" + c.v, r);
    }
    m.f = m0.f.map((f, fi) => { const out = []; for (const v of f) { const r = rep.get(fi + "|" + v); if (r) out.push(...r); else out.push(v); } return out; });
    const dirs = new Set();
    for (const f of m.f) for (let k = 0; k < f.length; k++) dirs.add(f[k] + ">" + f[(k + 1) % f.length]);
    const profile = new Map();
    // the strip's path past original vertex v, from point A to point B (in the strip's own direction)
    const endPath = (A, B, v, p, q) => {
      if (dirs.has(B + ">" + v) && dirs.has(v + ">" + A)) {        // v stays (an unbevelled sector): the strip runs through it
        return segs === 1 ? { pts: [A, B], extra: [[v]] } : { pts: [A, ...Array(segs - 1).fill(v), B] };
      }
      if (profile.has(A + ">" + B)) return { pts: profile.get(A + ">" + B) };
      if (profile.has(B + ">" + A)) return { pts: profile.get(B + ">" + A).slice().reverse() };
      const pts = [A];
      if (segs > 1) {
        const pa = m.v[A], pb = m.v[B], mid = lerp(pa, pb, 0.5), ax = sub(m0.v[q], m0.v[p]);
        const K0 = add(m0.v[p], mul(ax, dot(sub(mid, m0.v[p]), ax) / (dot(ax, ax) || 1)));
        const K = depth === 1 ? K0 : add(mid, mul(sub(K0, mid), depth));
        // a rational quadratic with the weight cos(chord, tangent) lies on a circle (chamfer off); weight 1 is today's
        const w = arc ? clamp(dot(norm(sub(K, pa)), norm(sub(pb, pa))), 0, 1) : 1;
        for (let i = 1; i < segs; i++) {
          const s = i / segs, b0 = (1 - s) * (1 - s), b1 = 2 * s * (1 - s) * w, b2 = s * s;
          const pq = add(add(mul(pa, b0), mul(K, b1)), mul(pb, b2));
          pts.push(newPt(w === 1 ? pq : mul(pq, 1 / (b0 + b1 + b2)), v));
        }
      }
      pts.push(B);
      profile.set(A + ">" + B, pts);
      return { pts };
    };
    const newF = [];
    for (const ei of ids) {
      const e = T.edges[ei], Fl = e.faces[0], Fr = e.faces[1], f0 = m0.f[Fl], k0 = f0.indexOf(e.a);
      const [p, q] = f0[(k0 + 1) % f0.length] === e.b ? [e.a, e.b] : [e.b, e.a];      // Fl runs p -> q
      const L = (r) => r[r.length - 1], F = (r) => r[0];
      const clp = L(rep.get(Fl + "|" + p)), clq = F(rep.get(Fl + "|" + q)), crp = F(rep.get(Fr + "|" + p)), crq = L(rep.get(Fr + "|" + q));
      const PP = endPath(clp, crp, p, p, q), QQ = endPath(crq, clq, q, p, q);
      for (let i = 0; i < segs; i++) {
        const poly = dedupeCyc([QQ.pts[segs - i], PP.pts[i], ...(PP.extra ? PP.extra[i] : []), PP.pts[i + 1],
          QQ.pts[segs - i - 1], ...(QQ.extra ? QQ.extra[segs - 1 - i] : [])]);
        if (poly.length >= 3) { newF.push(m.f.length); m.f.push(poly); }
      }
    }
    // the corners: the holes left around each bevelled vertex get a cap
    const dset = new Set();
    for (const f of m.f) for (let k = 0; k < f.length; k++) dset.add(f[k] + ">" + f[(k + 1) % f.length]);
    const caps = new Map(), faceOf = new Map(), strips = new Set(newF);
    m.f.forEach((f, fi) => { for (let k = 0; k < f.length; k++) faceOf.set(f[k] + ">" + f[(k + 1) % f.length], fi); });
    // a hole that borders exactly one face that is not a bevel strip belongs to that face (a rounded profile ending
    // on an unbevelled side: the side face takes the curve), any other hole becomes a corner cap
    const capOrMerge = (g) => {
      const own = g.map((x, i) => faceOf.get(g[(i + 1) % g.length] + ">" + x));
      const other = own.map((fi, i) => [fi, i]).filter(([fi]) => fi !== undefined && !strips.has(fi));
      if (other.length === 1 && g.length > 3) {
        const [fi, i] = other[0], y = g[i], x = g[(i + 1) % g.length], f = m.f[fi], k = f.indexOf(x);
        if (k >= 0 && f[(k + 1) % f.length] === y) {
          const path = [];
          for (let j = (i + 2) % g.length; j !== i; j = (j + 1) % g.length) path.push(g[j]);
          f.splice(k + 1, 0, ...path);
          return;
        }
      }
      newF.push(m.f.length); m.f.push(g);
    };
    for (const f of m.f) for (let k = 0; k < f.length; k++) {
      const a = f[k], b = f[(k + 1) % f.length], oa = owner.get(a);
      if (dset.has(b + ">" + a) || oa === undefined || oa !== owner.get(b)) continue;
      if (!caps.has(oa)) caps.set(oa, new Map());
      push(caps.get(oa), b, a);
    }
    for (const nx of caps.values()) {
      for (const start of [...nx.keys()]) {
        while ((nx.get(start) || []).length) {
          const loop = [start];
          let x = nx.get(start).pop(), guard = 0;
          while (x !== start && guard++ < 100000) {
            loop.push(x);
            const l = nx.get(x);
            if (!l || !l.length) { x = undefined; break; }
            x = l.pop();
          }
          if (x === start) for (const g of cleanFace(loop)) capOrMerge(g);
        }
      }
    }
    return finish(m, faceSel(m, newF), warnB.length ? "Bevel: " + warnB.join("; ") + "." : "");
  };

  // ------------------------------------------------------------------ bridge / append / fill
  P.bridge = (m0, edges, o) => {
    o = o || {};
    const T = P.topology(m0), all = edgeIds(m0, T, edges);
    if (all.length < 2) return fail(m0, "Bridge: select two border edge chains.");
    if (all.some((ei) => T.edges[ei].faces.length !== 1)) return fail(m0, "Bridge: every selected edge must be a border edge (an edge with one face).");
    const next = new Map(), prev = new Map();
    for (const ei of all) {
      const e = T.edges[ei], f = m0.f[e.faces[0]], k = f.indexOf(e.a);
      const [x, y] = f[(k + 1) % f.length] === e.b ? [e.a, e.b] : [e.b, e.a];
      if (next.has(x) || prev.has(y)) return fail(m0, "Bridge: the selected edges branch; select two simple chains.");
      next.set(x, y); prev.set(y, x);
    }
    const chains = [], seen = new Set();
    for (const x of next.keys()) if (!prev.has(x)) {
      const c = [x];
      let y = x;
      while (next.has(y)) { y = next.get(y); c.push(y); }
      c.forEach((z) => seen.add(z));
      chains.push({ vs: c, closed: false });
    }
    for (const x of next.keys()) if (!seen.has(x)) {
      const c = [];
      let y = x;
      while (!seen.has(y)) { seen.add(y); c.push(y); y = next.get(y); }
      chains.push({ vs: c, closed: true });
    }
    if (chains.length !== 2) return fail(m0, "Bridge: select exactly two separate border chains (found " + chains.length + ").");
    const [A, B] = chains;
    if (A.closed !== B.closed) return fail(m0, "Bridge: cannot bridge a closed border loop to an open chain.");
    const ne = (c) => (c.closed ? c.vs.length : c.vs.length - 1);
    if (ne(A) !== ne(B)) return fail(m0, "Bridge: both chains need the same number of edges (" + ne(A) + " and " + ne(B) + ").");
    const count = A.vs.length, D = clamp(Math.round(num(o.divisions, 0)), 0, 64);
    let pairOf;
    if (!A.closed) pairOf = (i) => count - 1 - i;
    else {
      let best = Infinity, bs = 0;
      for (let s = 0; s < count; s++) {
        let sum = 0;
        for (let i = 0; i < count; i++) sum += dist(m0.v[A.vs[i]], m0.v[B.vs[(((s - i) % count) + count) % count]]);
        if (sum < best) { best = sum; bs = s; }
      }
      pairOf = (i) => (((bs - i) % count) + count) % count;
    }
    // bridgeType "linear" (default: straight rows), "smooth" (a curve that leaves each border at right angles to
    // its faces, in the faces' plane - the pro "Smooth path"), "curve" (smooth + `curve`: points the middle of the
    // bridge passes through). twist (degrees, spread along the bridge) and taper (the width in the middle, 1 = none)
    // work on every type here (the pro tool greys them out for a linear path).
    const type = String(o.bridgeType || o.curveType || "linear").toLowerCase();
    const smooth = type !== "linear" && type !== "0";
    const taper = clamp(num(o.taper, 1), 0, 100), twist = clamp(num(o.twist, 0), -3600, 3600) * DEG;
    const curvePts = Array.isArray(o.curve) ? o.curve.filter((p) => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite)) : [];
    const plain = !smooth && taper === 1 && !twist && !curvePts.length;
    const cA = centreOf(A.vs.map((i) => m0.v[i])), cB = centreOf(B.vs.map((i) => m0.v[i]));
    const outDir = (c) => {                     // away from the chain's faces, in their plane
      let ou = [0, 0, 0];
      const ne = c.closed ? c.vs.length : c.vs.length - 1;
      for (let i = 0; i < ne; i++) {
        const x = c.vs[i], y = c.vs[(i + 1) % c.vs.length], e = T.edges[T.edge(x, y)];
        ou = add(ou, norm(cross(sub(m0.v[y], m0.v[x]), P.faceNormal(m0, m0.f[e.faces[0]]))));
      }
      return norm(ou);
    };
    const Ld = dist(cA, cB), TA = mul(outDir(A), Ld), TB = mul(outDir(B), -Ld);
    const herm = (a, ta, b, tb, s) => {
      const s2 = s * s, s3 = s2 * s;
      return add(add(mul(a, 2 * s3 - 3 * s2 + 1), mul(ta, s3 - 2 * s2 + s)), add(mul(b, -2 * s3 + 3 * s2), mul(tb, s3 - s2)));
    };
    const hermD = (a, ta, b, tb, s) => {
      const s2 = s * s;
      return add(add(mul(a, 6 * s2 - 6 * s), mul(ta, 3 * s2 - 4 * s + 1)), add(mul(b, -6 * s2 + 6 * s), mul(tb, 3 * s2 - 2 * s)));
    };
    const poly = [cA, ...curvePts, cB], segL = [];
    let tot = 0;
    for (let i = 0; i + 1 < poly.length; i++) { segL.push(dist(poly[i], poly[i + 1])); tot += segL[i]; }
    const along = (s) => {                      // the curve's point at fraction s of its length
      let want = s * tot;
      for (let i = 0; i < segL.length; i++) {
        if (want <= segL[i] || i === segL.length - 1) return lerp(poly[i], poly[i + 1], segL[i] ? clamp(want / segL[i], 0, 1) : 0);
        want -= segL[i];
      }
      return cB;
    };
    const m = cp(m0), R = [];
    for (let r = 0; r <= D + 1; r++) {
      R.push([]);
      const s = r / (D + 1), row = [];
      for (let i = 0; i < count; i++) {
        const a = A.vs[i], b = B.vs[pairOf(i)];
        if (r === 0) R[r].push(a);
        else if (r === D + 1) R[r].push(b);
        else if (plain) { R[r].push(m.v.length); m.v.push(lerp(m0.v[a], m0.v[b], s)); }
        else row.push(smooth ? herm(m0.v[a], TA, m0.v[b], TB, s) : lerp(m0.v[a], m0.v[b], s));
      }
      if (!row.length) continue;
      const H = smooth ? herm(cA, TA, cB, TB, s) : lerp(cA, cB, s);
      const shift = curvePts.length ? sub(along(s), H) : [0, 0, 0];
      let axis = smooth ? norm(hermD(cA, TA, cB, TB, s)) : norm(sub(cB, cA));
      if (!len(axis)) axis = [0, 1, 0];
      const c = centreOf(row), f = 1 + (taper - 1) * Math.sin(Math.PI * s);
      for (const p of row) { R[r].push(m.v.length); m.v.push(add(taperTwist(p, c, axis, f, twist * s), shift)); }
    }
    const newF = [], quads = A.closed ? count : count - 1;
    for (let r = 0; r <= D; r++) for (let i = 0; i < quads; i++) {
      const i2 = (i + 1) % count;
      newF.push(m.f.length);
      m.f.push([R[r][i2], R[r][i], R[r + 1][i], R[r + 1][i2]]);
    }
    return finish(m, faceSel(m, newF));
  };
  P.appendPolygon = (m0, verts) => {
    const vs = (verts || []).filter((i) => Number.isInteger(i) && i >= 0 && i < m0.v.length);
    if (vs.length < 3 || new Set(vs).size !== vs.length) return fail(m0, "Append to Polygon: pick 3 or more different vertices.");
    const T = P.topology(m0), dirs = new Set();
    for (const f of m0.f) for (let k = 0; k < f.length; k++) dirs.add(f[k] + ">" + f[(k + 1) % f.length]);
    let same = 0, opp = 0;
    for (let k = 0; k < vs.length; k++) {
      const a = vs[k], b = vs[(k + 1) % vs.length], ei = T.edge(a, b);
      if (ei !== undefined && T.edges[ei].faces.length >= 2) return fail(m0, "Append to Polygon: edge " + a + "-" + b + " already has two faces.");
      if (dirs.has(a + ">" + b)) same++;
      if (dirs.has(b + ">" + a)) opp++;
    }
    const face = same > opp ? vs.slice().reverse() : vs.slice();
    if (same && opp) return fail(m0, "Append to Polygon: the new face would face two ways at once.");
    const m = cp(m0); m.f.push(face);
    return finish(m, faceSel(m, [m.f.length - 1]), "", true);
  };
  P.fillHole = (m0, edges) => {
    const T = P.topology(m0), ids = edgeIds(m0, T, edges).filter((ei) => T.edges[ei].faces.length === 1);
    if (!ids.length) return fail(m0, "Fill Hole: select border edges.");
    const r = P.fillHoles(m0, uniq(ids.flatMap((ei) => [T.edges[ei].a, T.edges[ei].b])));
    if (!r.filled) return fail(m0, "Fill Hole: no closed border runs through the selected edges.");
    const m = cp(m0); m.f = r.f.map((f) => f.slice());
    const nf = [];
    for (let i = m0.f.length; i < m.f.length; i++) nf.push(i);
    return finish(m, faceSel(m, nf), "", true);
  };

  // ------------------------------------------------------------------ poke / wedge
  P.poke = (m0, faces, o) => {
    o = o || {};
    const fs = faceIds(m0, faces);
    if (!fs.length) return fail(m0, "Poke Face: select one or more faces.");
    const m = cp(m0), newF = [], off = num(o.offset, 0);
    for (const fi of fs) {
      const f = m0.f[fi], c = m.v.length;
      m.v.push(add(P.centroid(m0, f), mul(P.faceNormal(m0, f), off)));
      f.forEach((x, k) => {
        const tri = [x, f[(k + 1) % f.length], c];
        if (k === 0) { m.f[fi] = tri; newF.push(fi); } else { newF.push(m.f.length); m.f.push(tri); }
      });
    }
    return finish(m, faceSel(m, newF));
  };
  P.wedge = (m0, faces, edge, o) => {
    o = o || {};
    const fs = faceIds(m0, faces);
    if (!fs.length) return fail(m0, "Wedge: select faces and one hinge edge.");
    const ang = (clamp(num(o.angle, 90), -360, 360) * Math.PI) / 180, D = clamp(Math.round(num(o.divisions, 4)), 1, 64);
    if (!ang) return fail(m0, "Wedge: the angle must not be 0.");
    const hv = Array.isArray(edge) ? edge : edge && edge.a != null ? [edge.a, edge.b] : null;
    const T = P.topology(m0), hi = hv ? T.edge(hv[0], hv[1]) : typeof edge === "number" ? edge : undefined;
    if (hi === undefined || !T.edges[hi]) return fail(m0, "Wedge: pick a hinge edge.");
    const inS = new Set(fs), dir = new Set(), bnd = [];
    for (const fi of fs) { const f = m0.f[fi]; for (let k = 0; k < f.length; k++) dir.add(f[k] + ">" + f[(k + 1) % f.length]); }
    for (const fi of fs) { const f = m0.f[fi]; for (let k = 0; k < f.length; k++) { const a = f[k], b = f[(k + 1) % f.length]; if (!dir.has(b + ">" + a)) bnd.push([a, b]); } }
    const hk = ekey(T.edges[hi].a, T.edges[hi].b), hinge = bnd.find(([a, b]) => ekey(a, b) === hk);
    if (!hinge || !inS.size) return fail(m0, "Wedge: the hinge edge must be on the border of the selected faces.");
    const [ha, hb] = hinge, o0 = m0.v[ha];
    let u = norm(sub(m0.v[hb], o0));
    const R = uniq(fs.flatMap((fi) => m0.f[fi])), c = mul(R.reduce((s, x) => add(s, m0.v[x]), [0, 0, 0]), 1 / R.length);
    let n = [0, 0, 0];
    for (const fi of fs) n = add(n, P.faceNormal(m0, m0.f[fi]));
    if (dot(cross(u, sub(c, o0)), n) < 0) u = mul(u, -1);     // positive angles swing the faces out along their normal
    const rot = (p, th) => {
      const v = sub(p, o0), cs = Math.cos(th), sn = Math.sin(th);
      return add(o0, add(add(mul(v, cs), mul(cross(u, v), sn)), mul(u, dot(u, v) * (1 - cs))));
    };
    const m = cp(m0), layer = [new Map(R.map((x) => [x, x]))];
    for (let k = 1; k <= D; k++) {
      const L = new Map();
      for (const x of R) {
        if (x === ha || x === hb) L.set(x, x);
        else { L.set(x, m.v.length); m.v.push(rot(m0.v[x], (ang * k) / D)); }
      }
      layer.push(L);
    }
    for (const [x, y] of bnd) {
      if (ekey(x, y) === hk) continue;
      for (let k = 0; k < D; k++) {
        const g = dedupeCyc([layer[k].get(x), layer[k].get(y), layer[k + 1].get(y), layer[k + 1].get(x)]);
        if (g.length >= 3) m.f.push(g);
      }
    }
    for (const fi of fs) m.f[fi] = m0.f[fi].map((x) => layer[D].get(x));
    return finish(m, faceSel(m, fs));
  };

  // ------------------------------------------------------------------ collapse / target weld
  function mergeGroups(m0, groups, keepPos) {
    const m = cp(m0), map = m0.v.map((_, i) => i), reps = [];
    for (const g of groups) {
      if (g.length < 2) continue;
      const rep = keepPos != null ? keepPos : Math.min(...g);
      if (keepPos == null) m.v[rep] = mul(g.reduce((s, x) => add(s, m0.v[x]), [0, 0, 0]), 1 / g.length);
      for (const x of g) map[x] = rep;
      reps.push(rep);
    }
    m.f = cleanMesh(m0.f.map((f) => f.map((x) => map[x])));
    return { m, reps };
  }
  P.collapse = (m0, c) => {
    c = comp(c);
    const T = P.topology(m0), uf = UF(), touched = new Set();
    for (const fi of faceIds(m0, c.f)) { const f = m0.f[fi]; for (const x of f) { uf.union(f[0], x); touched.add(x); } }
    for (const ei of edgeIds(m0, T, c.e)) { const e = T.edges[ei]; uf.union(e.a, e.b); touched.add(e.a); touched.add(e.b); }
    if (!touched.size) return fail(m0, "Collapse: select edges or faces.");
    const groups = new Map();
    for (const x of touched) push(groups, uf.find(x), x);
    const r = mergeGroups(m0, [...groups.values()]);
    return finish(r.m, { v: r.reps, e: [], f: [] });
  };
  P.targetWeld = (m0, from, to) => {
    const ok = (i) => Number.isInteger(i) && i >= 0 && i < m0.v.length;
    if (!ok(from) || !ok(to) || from === to) return fail(m0, "Target Weld: pick two different vertices.");
    const r = mergeGroups(m0, [[from, to]], to);
    return finish(r.m, { v: [to], e: [], f: [] });
  };

  // ------------------------------------------------------------------ connect / multi-cut / slice
  // edges: o.edgeCount (1) cuts per edge, evenly spaced; o.slide (0.5) moves them along the edges (0..1, measured
  // the same way round the faces the cuts cross, from the first vertex of the first given edge)
  P.connect = (m0, c, o) => {
    c = comp(c);
    o = o || {};
    const T = P.topology(m0), m = cp(m0), newE = [];
    if (c.e && c.e.length) {
      const ids = edgeIds(m0, T, c.e);
      if (!ids.length) return fail(m0, "Connect: select edges or vertices.");
      const n = clamp(Math.round(num(o.edgeCount != null ? o.edgeCount : o.segments, 1)), 1, 64);
      const lim = 1 / (n + 1) - 0.01, sh = clamp(num(o.slide, 0.5) - 0.5, -lim, lim);
      const ts = Array.from({ length: n }, (_, i) => (i + 1) / (n + 1) + sh);
      const start = new Map();
      if (sh !== 0) {                          // which end each edge's slide is measured from, consistent across faces
        const first = new Map(), inF = new Map();
        for (const x of c.e) {
          const pr = Array.isArray(x) ? x : x && x.a != null ? [x.a, x.b] : null;
          if (pr) { const ei = T.edge(pr[0], pr[1]); if (ei !== undefined && !first.has(ei)) first.set(ei, pr[0]); }
        }
        for (const ei of ids) for (const fi of T.edges[ei].faces) push(inF, fi, ei);
        const faceDir = (f, ei) => { const e = T.edges[ei], k = f.indexOf(e.a); return f[(k + 1) % f.length] === e.b ? [e.a, e.b] : [e.b, e.a]; };
        for (const root of ids) {
          if (start.has(root)) continue;
          start.set(root, first.has(root) ? first.get(root) : T.edges[root].a);
          const queue = [root];
          while (queue.length) {
            const ei = queue.shift(), s = start.get(ei);
            for (const fi of T.edges[ei].faces) {
              const list = uniq(inF.get(fi) || []);
              if (list.length !== 2) continue;
              const other = list[0] === ei ? list[1] : list[0];
              if (start.has(other)) continue;
              const f = m0.f[fi], [u1] = faceDir(f, ei), [u2, v2] = faceDir(f, other);
              start.set(other, s === u1 ? v2 : u2);       // opposite sides of a face run opposite ways
              queue.push(other);
            }
          }
        }
      }
      const mids = new Set(), touched = new Set(), edgeOf = new Map();
      for (const ei of ids) {
        const e = T.edges[ei], s = start.has(ei) ? start.get(ei) : e.a, oth = s === e.a ? e.b : e.a;
        const list = ts.map((t) => { const id = m.v.length; m.v.push(lerp(m0.v[s], m0.v[oth], t)); mids.add(id); edgeOf.set(id, ei); return id; });
        insertOnEdge(m, e.a, e.b, s === e.a ? list : list.slice().reverse(), e.faces);
        e.faces.forEach((fi) => touched.add(fi));
      }
      for (const fi of [...touched].sort((a, b) => a - b)) {
        let f = m.f[fi], pos = [];
        if (n > 1) {
          const es = uniq(f.filter((x) => edgeOf.has(x)).map((x) => edgeOf.get(x)));
          if (es.length < 2) continue;
          if (es.length === 2) {                // n parallel cuts: strips, pairing the k-th cut with the k-th from the far end
            const Pp = f.filter((x) => edgeOf.get(x) === es[0]), Qq = f.filter((x) => edgeOf.get(x) === es[1]);
            const pieces = [];
            let cur = f;
            for (let i = 0; i < n; i++) {
              const p = Pp[i], q = Qq[n - 1 - i], [A, B] = splitAt(cur, cur.indexOf(p), cur.indexOf(q));
              pieces.push(B); newE.push([p, q]); cur = A;
            }
            pieces.push(cur);
            m.f[fi] = pieces[0];
            pieces.slice(1).forEach((pc) => m.f.push(pc));
            continue;
          }
          // 3+ cut edges in one face: the middle cut of each meets a centre vertex (the others stay on the edges)
          const pick = new Set(es.map((ei) => f.filter((x) => edgeOf.get(x) === ei)[Math.floor((n - 1) / 2)]));
          f.forEach((x, k) => { if (pick.has(x)) pos.push(k); });
        } else f.forEach((x, k) => { if (mids.has(x)) pos.push(k); });
        if (pos.length < 2) continue;
        if (pos.length === 2) {
          const [A, B] = splitAt(f, pos[0], pos[1]);
          m.f[fi] = A; m.f.push(B); newE.push([f[pos[0]], f[pos[1]]]);
          continue;
        }
        const cid = m.v.length;
        m.v.push(P.centroid(m0, m0.f[fi]));
        const pieces = pos.map((p, j) => [...cyc(f, p, pos[(j + 1) % pos.length]), cid]);
        m.f[fi] = pieces[0];
        pieces.slice(1).forEach((pc) => m.f.push(pc));
        pos.forEach((p) => newE.push([f[p], cid]));
      }
      if (!newE.length) return fail(m0, "Connect: select at least two edges of the same face.");
      return finish(m, edgeSel(newE));
    }
    const vs = new Set(vertIds(m0, c.v));
    if (vs.size < 2) return fail(m0, "Connect: select two or more vertices (or edges) on the same face.");
    for (let fi = 0, n0 = m0.f.length; fi < n0; fi++) {
      const f = m0.f[fi], pos = [];
      f.forEach((x, k) => { if (vs.has(x)) pos.push(k); });
      if (pos.length < 2 || pos.length === f.length) continue;
      if (pos.length === 2) {
        if (adjacentIn(f, pos[0], pos[1])) continue;
        const [A, B] = splitAt(f, pos[0], pos[1]);
        m.f[fi] = A; m.f.push(B); newE.push([f[pos[0]], f[pos[1]]]);
        continue;
      }
      const pieces = [];
      pos.forEach((p, j) => {
        const q = pos[(j + 1) % pos.length], pc = cyc(f, p, q);
        if (pc.length >= 3) { pieces.push(pc); newE.push([f[p], f[q]]); }
      });
      if (!pieces.length) continue;
      m.f[fi] = pos.map((k) => f[k]);
      pieces.forEach((pc) => m.f.push(pc));
    }
    if (!newE.length) return fail(m0, "Connect: the selected vertices must share a face and not already be joined by an edge.");
    return finish(m, edgeSel(newE));
  };
  P.multiCut = (m0, points) => {
    if (!Array.isArray(points) || points.length < 2) return fail(m0, "Multi-Cut: place at least two cut points.");
    const T = P.topology(m0), m = cp(m0), ids = new Array(points.length), onEdge = new Map();
    for (let i = 0; i < points.length; i++) {
      const p = points[i];
      if (p && Number.isInteger(p.v) && p.v >= 0 && p.v < m0.v.length) { ids[i] = p.v; continue; }
      if (!p || !p.e) return fail(m0, "Multi-Cut: point " + (i + 1) + " is neither a vertex nor on an edge.");
      const a0 = Array.isArray(p.e) ? p.e[0] : p.e.a, ei = edgeIds(m0, T, [p.e])[0];
      if (ei === undefined) return fail(m0, "Multi-Cut: point " + (i + 1) + " is not on an edge of this mesh.");
      const e = T.edges[ei];
      let t = clamp(num(p.t, 0.5), 0, 1);
      if (a0 !== e.a) t = 1 - t;                                   // measured from e.a from here on
      if (t < 1e-6) ids[i] = e.a;
      else if (t > 1 - 1e-6) ids[i] = e.b;
      else push(onEdge, ei, { t, i });
    }
    for (const [ei, list] of onEdge) {
      const e = T.edges[ei], made = [];
      list.sort((x, y) => x.t - y.t);
      let lastT = -1;
      for (const it of list) {
        if (made.length && Math.abs(it.t - lastT) < 1e-9) { ids[it.i] = made[made.length - 1]; continue; }
        const id = m.v.length;
        m.v.push(lerp(m0.v[e.a], m0.v[e.b], it.t));
        made.push(id); ids[it.i] = id; lastT = it.t;
      }
      insertOnEdge(m, e.a, e.b, made, e.faces);
    }
    const newE = [];
    for (let i = 0; i + 1 < ids.length; i++) {
      const x = ids[i], y = ids[i + 1];
      if (x === y) continue;
      let best = -1, adjacent = false;
      for (let fi = 0; fi < m.f.length; fi++) {
        const f = m.f[fi], a = f.indexOf(x);
        if (a < 0) continue;
        const b = f.indexOf(y);
        if (b < 0) continue;
        if (adjacentIn(f, a, b)) { adjacent = true; break; }
        if (best < 0) best = fi;
      }
      if (adjacent) continue;
      if (best < 0) return fail(m0, "Multi-Cut: cut points " + (i + 1) + " and " + (i + 2) + " do not share a face.");
      const f = m.f[best], [A, B] = splitAt(f, f.indexOf(x), f.indexOf(y));
      m.f[best] = A; m.f.push(B); newE.push([x, y]);
    }
    if (!newE.length && !onEdge.size) return fail(m0, "Multi-Cut: nothing to cut.");
    return finish(m, { v: uniq(ids), e: newE, f: [] });
  };
  P.sliceFaces = (m0, faces, point, normal) => {
    const fs = faces && faces.length ? faceIds(m0, faces) : m0.f.map((_, i) => i), n = norm(normal || [0, 0, 0]);
    if (!fs.length || !len(n) || !point) return fail(m0, "Slice: select faces and give a plane.");
    const sd = (p) => dot(sub(p, point), n), eps = 1e-7;
    const T = P.topology(m0), m = cp(m0), cut = new Set(), done = new Set();
    for (const fi of fs) for (const ei of T.faceEdges[fi]) {
      if (done.has(ei)) continue;
      done.add(ei);
      const e = T.edges[ei], da = sd(m0.v[e.a]), db = sd(m0.v[e.b]);
      if (Math.abs(da) < eps || Math.abs(db) < eps || da * db > 0) continue;
      const id = m.v.length;
      m.v.push(lerp(m0.v[e.a], m0.v[e.b], da / (da - db)));
      cut.add(id);
      insertOnEdge(m, e.a, e.b, [id], e.faces);
    }
    const newE = [];
    for (const fi of fs) {
      const f = m.f[fi], pos = [];
      f.forEach((x, k) => { if (cut.has(x) || (x < m0.v.length && Math.abs(sd(m0.v[x])) < eps)) pos.push(k); });
      if (pos.length !== 2 || adjacentIn(f, pos[0], pos[1])) continue;
      const [A, B] = splitAt(f, pos[0], pos[1]);
      m.f[fi] = A; m.f.push(B); newE.push([f[pos[0]], f[pos[1]]]);
    }
    if (!newE.length) return fail(m0, "Slice: the plane does not cross the selected faces.");
    return finish(m, edgeSel(newE));
  };

  // ------------------------------------------------------------------ detach / duplicate / extract
  P.detach = (m0, c) => {
    c = comp(c);
    const T = P.topology(m0), m = cp(m0);
    let verts, cut = null;
    if (c.e && c.e.length) {
      const ids = edgeIds(m0, T, c.e);
      cut = new Set(ids);
      verts = uniq(ids.flatMap((ei) => [T.edges[ei].a, T.edges[ei].b]));
    } else verts = vertIds(m0, c.v);
    if (!verts.length) return fail(m0, "Detach: select vertices or edges.");
    const faceMap = new Map(), copies = [];
    let split = 0;
    for (const x of verts) {
      const fs = uniq(T.vertFaces[x]);
      if (fs.length < 2) continue;
      const uf = UF();
      fs.forEach((fi) => uf.find(fi));
      if (cut) for (const ei of T.vertEdges[x]) {
        if (cut.has(ei)) continue;
        const ef = T.edges[ei].faces;
        for (let i = 1; i < ef.length; i++) uf.union(ef[0], ef[i]);
      }
      const groups = new Map();
      for (const fi of fs) push(groups, uf.find(fi), fi);
      if (groups.size < 2) continue;
      [...groups.values()].forEach((g, gi) => {
        let id = x;
        if (gi > 0) { id = m.v.length; m.v.push(m0.v[x].slice()); split++; }
        copies.push(id);
        for (const fi of g) { faceMap.set(fi + "|" + x, id); if (id !== x) m.f[fi] = m.f[fi].map((y) => (y === x ? id : y)); }
      });
    }
    if (!split) return fail(m0, "Detach: nothing to split - an edge chain must reach a border or close a loop.");
    if (!cut) return finish(m, { v: copies, e: [], f: [] });
    const e = [];
    for (const ei of cut) {
      const ed = T.edges[ei];
      for (const fi of ed.faces) e.push([faceMap.get(fi + "|" + ed.a) ?? ed.a, faceMap.get(fi + "|" + ed.b) ?? ed.b]);
    }
    return finish(m, edgeSel(e));
  };
  P.duplicateFaces = (m0, faces) => {
    const fs = faceIds(m0, faces);
    if (!fs.length) return fail(m0, "Duplicate Face: select one or more faces.");
    const m = cp(m0), map = new Map(), newF = [];
    for (const fi of fs) {
      newF.push(m.f.length);
      m.f.push(m0.f[fi].map((x) => { if (!map.has(x)) { map.set(x, m.v.length); m.v.push(m0.v[x].slice()); } return map.get(x); }));
    }
    return finish(m, faceSel(m, newF));
  };
  P.extractFaces = (m0, faces) => {
    const fs = faceIds(m0, faces);
    if (!fs.length) return fail(m0, "Extract: select one or more faces.");
    const T = P.topology(m0), m = cp(m0), inS = new Set(fs), shared = new Map();
    for (const fi of fs) for (const x of m0.f[fi]) {
      if (shared.has(x) || !T.vertFaces[x].some((g) => !inS.has(g))) continue;
      shared.set(x, m.v.length); m.v.push(m0.v[x].slice());
    }
    if (!shared.size) return fail(m0, "Extract: the faces are already a piece of their own.");
    for (const fi of fs) m.f[fi] = m0.f[fi].map((x) => (shared.has(x) ? shared.get(x) : x));
    return finish(m, faceSel(m, fs));
  };

  // ------------------------------------------------------------------ triangulate / quadrangulate
  function earClip(m, f) {
    if (f.length === 3) return [f.slice()];
    const n = P.faceNormal(m, f);
    let u = [0, 0, 0];
    for (let k = 1; k < f.length && !len(u); k++) u = norm(sub(m.v[f[k]], m.v[f[0]]));
    const w = cross(n, u), p2 = f.map((i) => { const d = sub(m.v[i], m.v[f[0]]); return [dot(d, u), dot(d, w)]; });
    const ar = (a, b, c) => (p2[b][0] - p2[a][0]) * (p2[c][1] - p2[a][1]) - (p2[b][1] - p2[a][1]) * (p2[c][0] - p2[a][0]);
    const idx = f.map((_, i) => i), tris = [];
    for (let guard = 0; idx.length > 3 && guard < 100000; guard++) {
      let cutAt = -1, bestQ = -Infinity;
      for (let i = 0; i < idx.length; i++) {
        const a = idx[(i + idx.length - 1) % idx.length], b = idx[i], c = idx[(i + 1) % idx.length], A = ar(a, b, c);
        if (A <= 1e-12) continue;
        if (idx.some((q) => q !== a && q !== b && q !== c && ar(a, b, q) >= 0 && ar(b, c, q) >= 0 && ar(c, a, q) >= 0)) continue;
        const e2 = (x, y) => (p2[x][0] - p2[y][0]) ** 2 + (p2[x][1] - p2[y][1]) ** 2;
        const q = A / (e2(a, b) + e2(b, c) + e2(c, a));        // the best-shaped ear first
        if (q > bestQ) { bestQ = q; cutAt = i; }
      }
      if (cutAt < 0) cutAt = 0;
      const a = idx[(cutAt + idx.length - 1) % idx.length], b = idx[cutAt], c = idx[(cutAt + 1) % idx.length];
      tris.push([f[a], f[b], f[c]]);
      idx.splice(cutAt, 1);
    }
    tris.push(idx.map((i) => f[i]));
    return tris;
  }
  P.triangulateFaces = (m0, faces) => {
    const fs = faces && faces.length ? faceIds(m0, faces) : m0.f.map((_, i) => i);
    if (!fs.length) return fail(m0, "Triangulate: nothing to triangulate.");
    const m = cp(m0), newF = [];
    for (const fi of fs) {
      const tris = earClip(m0, m0.f[fi]);
      m.f[fi] = tris[0]; newF.push(fi);
      for (const t of tris.slice(1)) { newF.push(m.f.length); m.f.push(t); }
    }
    return finish(m, faceSel(m, newF));
  };
  P.quadrangulate = (m0, faces, o) => {
    o = o || {};
    const fs = faces && faces.length ? faceIds(m0, faces) : m0.f.map((_, i) => i);
    const inS = new Set(fs.filter((fi) => m0.f[fi].length === 3)), maxA = clamp(num(o.angle, 30), 0, 180);
    if (!inS.size) return fail(m0, "Quadrangulate: select triangles.");
    // keepHardEdges (false here; the pro tool's default is on): an edge marked hard (m.hard) is never merged away
    const T = P.topology(m0), cands = [], keepHard = !!o.keepHardEdges && m0.hard instanceof Map;
    for (const e of T.edges) {
      if (e.faces.length !== 2) continue;
      if (keepHard && m0.hard.has(ekey(e.a, e.b))) continue;
      let [f1, f2] = e.faces;
      if (f1 === f2 || !inS.has(f1) || !inS.has(f2)) continue;
      const A = m0.f[f1], k = A.indexOf(e.a);
      const [a, b] = A[(k + 1) % 3] === e.b ? [e.a, e.b] : [e.b, e.a];
      const t1 = cyc(A, A.indexOf(a), (A.indexOf(a) + 2) % 3), B = m0.f[f2], t2 = cyc(B, B.indexOf(b), (B.indexOf(b) + 2) % 3);
      const c = t1[2], d = t2[2];
      if (c === d) continue;
      const n1 = P.faceNormal(m0, A), n2 = P.faceNormal(m0, B);
      if ((Math.acos(clamp(dot(n1, n2), -1, 1)) * 180) / Math.PI > maxA + 1e-9) continue;
      const quad = [a, d, b, c], qn = norm(add(n1, n2));
      let score = 0, convex = true;
      for (let i = 0; i < 4; i++) {
        const p = m0.v[quad[(i + 3) % 4]], x = m0.v[quad[i]], q = m0.v[quad[(i + 1) % 4]];
        const u = norm(sub(q, x)), w = norm(sub(p, x));
        if (dot(cross(u, w), qn) <= 1e-9) convex = false;
        score += Math.abs((Math.acos(clamp(dot(u, w), -1, 1)) * 180) / Math.PI - 90);
      }
      if (convex) cands.push({ f1, f2, quad, score });
    }
    cands.sort((x, y) => x.score - y.score);
    const used = new Set(), f = m0.f.map((x) => x.slice()), gone = new Set();
    for (const c of cands) {
      if (used.has(c.f1) || used.has(c.f2)) continue;
      used.add(c.f1); used.add(c.f2);
      const keep = Math.min(c.f1, c.f2);
      f[keep] = c.quad; gone.add(Math.max(c.f1, c.f2));
    }
    if (!gone.size) return fail(m0, "Quadrangulate: no neighbouring triangles make a good quad.");
    const remap = new Map(), nf = [];
    f.forEach((x, i) => { if (!gone.has(i)) { remap.set(i, nf.length); nf.push(x); } });
    const m = cp(m0); m.f = nf;
    return finish(m, faceSel(m, fs.filter((fi) => remap.has(fi)).map((fi) => remap.get(fi))));
  };

  // ------------------------------------------------------------------ average / relax / circularize
  function smoothVerts(m0, vs, iters, factor, pinBorder) {
    const nb = neighbours(m0), T = pinBorder ? P.topology(m0) : null;
    const pinned = new Set();
    if (T) for (const e of T.edges) if (e.faces.length === 1) { pinned.add(e.a); pinned.add(e.b); }
    let pos = m0.v.map((p) => p.slice());
    for (let it = 0; it < iters; it++) {
      const nxt = pos.map((p) => p.slice());
      for (const x of vs) {
        if (pinned.has(x) || !nb[x].size) continue;
        const avg = mul([...nb[x]].reduce((s, y) => add(s, pos[y]), [0, 0, 0]), 1 / nb[x].size);
        nxt[x] = lerp(pos[x], avg, factor);
      }
      pos = nxt;
    }
    const m = cp(m0); m.v = pos;
    return m;
  }
  P.averageVerts = (m0, verts, o) => {
    o = o || {};
    const vs = vertIds(m0, verts);
    if (!vs.length) return fail(m0, "Average Vertices: select vertices.");
    return finish(smoothVerts(m0, vs, clamp(Math.round(num(o.iterations, 1)), 1, 200), 1, false), { v: vs, e: [], f: [] }, "", true);
  };
  P.relax = (m0, verts, o) => {
    o = o || {};
    const vs = verts && verts.length ? vertIds(m0, verts) : m0.v.map((_, i) => i);
    if (!vs.length) return fail(m0, "Relax: select vertices.");
    return finish(smoothVerts(m0, vs, clamp(Math.round(num(o.iterations, 1)), 1, 200), 0.5, true), { v: vs, e: [], f: [] }, "", true);
  };
  P.circularize = (m0, c, o) => {
    c = comp(c);
    const T = P.topology(m0);
    let loop, inner = [], selOut;
    if (c.f && c.f.length) {
      const fs = faceIds(m0, c.f), r = regionLoops(m0, fs);
      if (r.err || r.loops.length !== 1) return fail(m0, "Circularize: the faces must make one patch with one border.");
      loop = r.loops[0];
      const on = new Set(loop);
      inner = uniq(fs.flatMap((fi) => m0.f[fi])).filter((x) => !on.has(x));
      selOut = { v: [], e: [], f: fs };
    } else {
      const vs = c.e && c.e.length ? uniq(edgeIds(m0, T, c.e).flatMap((ei) => [T.edges[ei].a, T.edges[ei].b])) : vertIds(m0, c.v);
      if (vs.length < 3) return fail(m0, "Circularize: select a loop of 3 or more vertices or edges.");
      const S = new Set(vs), nb = new Map(vs.map((x) => [x, T.vertEdges[x].map((ei) => (T.edges[ei].a === x ? T.edges[ei].b : T.edges[ei].a)).filter((y) => S.has(y))]));
      if (vs.every((x) => nb.get(x).length === 2)) {
        loop = [vs[0]];
        let prev = -1, x = vs[0];
        for (let g = 0; g < vs.length; g++) {
          const y = nb.get(x).find((z) => z !== prev);
          if (y === undefined || y === vs[0]) break;
          loop.push(y); prev = x; x = y;
        }
      }
      if (!loop || loop.length !== vs.length) {            // not a clean loop: go round the centre in the best-fit plane
        const cen = P.median(m0, vs);
        let n = [0, 0, 0];
        for (const x of vs) n = add(n, vertNormal(m0, T, x));
        n = norm(n);
        if (!len(n)) return fail(m0, "Circularize: cannot find the plane of the selection.");
        let u = [0, 0, 0];
        for (const x of vs) { u = sub(m0.v[x], cen); u = norm(sub(u, mul(n, dot(u, n)))); if (len(u)) break; }
        const w = cross(n, u), angle = (x) => { const d = sub(m0.v[x], cen); return Math.atan2(dot(d, w), dot(d, u)); };
        loop = vs.slice().sort((a, b) => angle(a) - angle(b));
      }
      let fn = [0, 0, 0];                                         // run the loop the way the surface faces
      for (const x of loop) fn = add(fn, vertNormal(m0, T, x));
      if (dot(P.faceNormal(m0, loop), fn) < 0) loop.reverse();
      selOut = { v: vs, e: c.e || [], f: [] };
    }
    const k = loop.length, cen = P.median(m0, loop), n = P.faceNormal(m0, loop);
    if (!len(n)) return fail(m0, "Circularize: the selection has no plane.");
    let u = sub(m0.v[loop[0]], cen);
    u = norm(sub(u, mul(n, dot(u, n))));
    if (!len(u)) return fail(m0, "Circularize: the selection has no size.");
    const w = cross(n, u);
    let r = 0;
    for (const x of loop) { const d = sub(m0.v[x], cen); r += len(sub(d, mul(n, dot(d, n)))); }
    r /= k;
    const m = cp(m0);
    loop.forEach((x, i) => { const a = (2 * Math.PI * i) / k; m.v[x] = add(cen, add(mul(u, r * Math.cos(a)), mul(w, r * Math.sin(a)))); });
    if (inner.length) {                                        // faces: the inside follows, relaxed onto the new rim
      const nb = neighbours(m0);
      for (let it = 0; it < 20; it++) {
        const nxt = m.v.map((p) => p.slice());
        for (const x of inner) nxt[x] = mul([...nb[x]].reduce((s, y) => add(s, m.v[y]), [0, 0, 0]), 1 / nb[x].size);
        m.v = nxt;
      }
    }
    return finish(m, selOut, "", true);
  };

  // ------------------------------------------------------------------ spin / slide / offset loop
  P.spinEdge = (m0, edges, dir) => {
    dir = dir < 0 ? -1 : 1;
    const T0 = P.topology(m0), pairs = edgeIds(m0, T0, edges).map((ei) => [T0.edges[ei].a, T0.edges[ei].b]);
    if (!pairs.length) return fail(m0, "Spin Edge: select interior edges.");
    const m = cp(m0), newE = [], warns = [];
    for (const [a0, b0] of pairs) {
      const T = P.topology(m), ei = T.edge(a0, b0);
      if (ei === undefined) continue;
      const e = T.edges[ei];
      if (e.faces.length !== 2 || e.faces[0] === e.faces[1]) { warns.push("border edges cannot spin"); continue; }
      let [F1, F2] = e.faces;
      const f1 = m.f[F1], k = f1.indexOf(e.a);
      const [a, b] = f1[(k + 1) % f1.length] === e.b ? [e.a, e.b] : [e.b, e.a];       // F1 runs a -> b
      const r1 = cyc(f1, f1.indexOf(a), (f1.indexOf(a) + f1.length - 1) % f1.length);
      const f2 = m.f[F2], r2 = cyc(f2, f2.indexOf(b), (f2.indexOf(b) + f2.length - 1) % f2.length);
      const X = r1.slice(2), Y = r2.slice(2);
      if (r2[1] !== a || !X.length || !Y.length) { warns.push("an edge between badly wound faces was skipped"); continue; }
      if (T.vertEdges[a].length < 3 || T.vertEdges[b].length < 3) { warns.push("an end would be left with one edge"); continue; }
      let u, w, n1, n2;
      if (dir > 0) { u = X[0]; w = Y[0]; n1 = [...X, a, Y[0]]; n2 = [...Y, b, X[0]]; }
      else { u = X[X.length - 1]; w = Y[Y.length - 1]; n1 = [Y[Y.length - 1], b, ...X]; n2 = [X[X.length - 1], a, ...Y]; }
      if (u === w || T.edge(u, w) !== undefined) { warns.push("the spun edge already exists"); continue; }
      m.f[F1] = n1; m.f[F2] = n2; newE.push([u, w]);
    }
    if (!newE.length) return fail(m0, "Spin Edge: " + (warns[0] || "nothing to spin") + ".");
    return finish(m, edgeSel(newE), warns.length ? "Spin Edge: " + uniq(warns).join("; ") + "." : "", true);
  };
  P.slideEdge = (m0, edges, t) => {
    const T = P.topology(m0), given = [];
    for (const x of edges || []) {
      const pr = Array.isArray(x) ? x : x && x.a != null ? [x.a, x.b] : typeof x === "number" && T.edges[x] ? [T.edges[x].a, T.edges[x].b] : null;
      if (pr && T.edge(pr[0], pr[1]) !== undefined) given.push(pr.slice());
    }
    if (!given.length) return fail(m0, "Edge Slide: select edges.");
    // orient the chains head to tail so "left" means the same side all along a loop
    const byV = new Map();
    given.forEach((pr, i) => { push(byV, pr[0], i); push(byV, pr[1], i); });
    const done = new Set(), oriented = [];
    for (let s = 0; s < given.length; s++) {
      if (done.has(s)) continue;
      done.add(s); oriented[s] = given[s];
      const stack = [s];
      while (stack.length) {
        const i = stack.pop(), [x, y] = oriented[i];
        for (const at of [x, y]) for (const j of byV.get(at)) {
          if (done.has(j)) continue;
          done.add(j);
          const [p, q] = given[j];
          oriented[j] = at === y ? (p === y ? [p, q] : [q, p]) : (q === x ? [p, q] : [q, p]);
          stack.push(j);
        }
      }
    }
    const dirs = new Map();
    m0.f.forEach((f, fi) => { for (let k = 0; k < f.length; k++) dirs.set(f[k] + ">" + f[(k + 1) % f.length], fi); });
    const Lt = new Map(), Rt = new Map();
    for (const [x, y] of oriented) {
      const L = dirs.get(x + ">" + y), R = dirs.get(y + ">" + x);
      if (L !== undefined) { const f = m0.f[L], n = f.length, k = f.indexOf(x); push(Lt, x, f[(k + n - 1) % n]); push(Lt, y, f[(k + 2) % n]); }
      if (R !== undefined) { const f = m0.f[R], n = f.length, k = f.indexOf(y); push(Rt, y, f[(k + n - 1) % n]); push(Rt, x, f[(k + 2) % n]); }
    }
    const s = clamp(num(t, 0), -1, 1), side = s >= 0 ? Lt : Rt, m = cp(m0), sel = new Set(oriented.flat());
    for (const [x, list] of side) {
      const ts = uniq(list).filter((y) => !sel.has(y));
      if (!ts.length) continue;
      const target = mul(ts.reduce((acc, y) => add(acc, m0.v[y]), [0, 0, 0]), 1 / ts.length);
      m.v[x] = lerp(m0.v[x], target, Math.abs(s));
    }
    return finish(m, edgeSel(oriented), "", true);
  };
  P.offsetEdgeLoop = (m0, edge, o) => {
    o = o || {};
    const T = P.topology(m0);
    const list = Array.isArray(edge) && edge.length === 2 && typeof edge[0] === "number" ? [edge] : Array.isArray(edge) ? edge : [edge];
    const start = edgeIds(m0, T, list);
    if (!start.length) return fail(m0, "Offset Edge Loop: select an edge.");
    const loop = new Set();
    for (const ei of start) for (const x of P.edgeLoop(m0, T, ei)) loop.add(x);
    const t0 = clamp(num(o.distance, 0.25), 0.01, 0.95), loopV = new Set();
    for (const ei of loop) { loopV.add(T.edges[ei].a); loopV.add(T.edges[ei].b); }
    const perFace = new Map();
    for (const ei of loop) for (const fi of T.edges[ei].faces) perFace.set(fi, (perFace.get(fi) || 0) + 1);
    if ([...perFace.values()].some((c) => c > 1)) return fail(m0, "Offset Edge Loop: the loop runs through a face twice; it needs quads either side.");
    // count (1): that many loops each side, evenly spaced out to `distance`; equalDistance (false): `distance` is an
    // absolute length on every side edge (limited by the shortest one) instead of a fraction of each
    const cnt = clamp(Math.round(num(o.count, 1)), 1, 32), sides = [];
    for (const ei of loop) for (const fi of T.edges[ei].faces) {
      const e = T.edges[ei], f = m0.f[fi], n = f.length;
      if (n < 4) return fail(m0, "Offset Edge Loop: a triangle touches the loop; it needs quads (or bigger) either side.");
      const k0 = f.indexOf(e.a), [x, y] = f[(k0 + 1) % n] === e.b ? [e.a, e.b] : [e.b, e.a], k = f.indexOf(x);
      sides.push({ fi, x, px: f[(k + n - 1) % n], y, ny: f[(k + 2) % n] });
    }
    const cap = (y) => (loopV.has(y) ? Math.min(t0, 0.49) : t0);
    let dAbs = 0;
    if (o.equalDistance) {
      dAbs = Math.max(1e-9, num(o.distance, 0.25));
      for (const j of sides) for (const [a, b] of [[j.x, j.px], [j.y, j.ny]]) dAbs = Math.min(dAbs, (loopV.has(b) ? 0.49 : 0.95) * dist(m0.v[a], m0.v[b]));
    }
    const m = cp(m0), pts = new Map(), onEdge = new Map(), jobs = [];
    const pt = (x, y) => {                     // the cnt new points on x-y, nearest x first
      const k = x + ">" + y;
      if (!pts.has(k)) {
        const ei = T.edge(x, y), L = dist(m0.v[x], m0.v[y]);
        const t = o.equalDistance ? (L ? Math.min(dAbs / L, 0.95) : 0.5) : cap(y), ids = [];
        for (let j = 1; j <= cnt; j++) {
          const tj = cnt === 1 ? t : (t * j) / cnt, id = m.v.length;
          m.v.push(lerp(m0.v[x], m0.v[y], tj));
          ids.push(id);
          push(onEdge, ei, { id, d: T.edges[ei].a === x ? tj : 1 - tj });
        }
        pts.set(k, ids);
      }
      return pts.get(k);
    };
    for (const j of sides) jobs.push({ fi: j.fi, sx: pt(j.x, j.px), sy: pt(j.y, j.ny) });
    for (const [ei, l] of onEdge) {
      l.sort((p, q) => p.d - q.d);
      insertOnEdge(m, T.edges[ei].a, T.edges[ei].b, l.map((p) => p.id), T.edges[ei].faces);
    }
    const newE = [];
    for (const j of jobs) {
      // split at the outermost pair first; the face keeps the innermost piece (as with one loop)
      let cur = m.f[j.fi];
      const outer = [];
      for (let i = cnt - 1; i >= 0; i--) {
        const [A, B] = splitAt(cur, cur.indexOf(j.sx[i]), cur.indexOf(j.sy[i]));
        outer.push(B); newE.push([j.sx[i], j.sy[i]]); cur = A;
      }
      m.f[j.fi] = cur;
      for (const pc of outer) m.f.push(pc);
    }
    return finish(m, edgeSel(newE));
  };

  // ------------------------------------------------------------------ crease / hard and soft edges (flags only)
  function flagOp(m0, edges, name, fn) {
    const T = P.topology(m0), ids = edges && edges.length ? edgeIds(m0, T, edges) : T.edges.map((_, i) => i);
    if (!ids.length) return null;
    const m = cp(m0);
    m[name] = m[name] instanceof Map ? m[name] : new Map();
    const pairs = [];
    for (const ei of ids) { const e = T.edges[ei]; fn(m[name], ekey(e.a, e.b), e); pairs.push([e.a, e.b]); }
    return { m, sel: edgeSel(pairs), warn: "" };
  }
  P.crease = (m0, edges, value) => {
    const v = clamp(num(value, 1), 0, 10);
    return flagOp(m0, edges, "creases", (mp, k) => { if (v > 0) mp.set(k, v); else mp.delete(k); }) || fail(m0, "Crease: select edges.");
  };
  P.setHard = (m0, edges, hard) => {
    const h = hard !== false;
    return flagOp(m0, edges, "hard", (mp, k) => { if (h) mp.set(k, 1); else mp.delete(k); }) || fail(m0, "Soften/Harden: select edges.");
  };
  P.softHard = (m0, edges, o) => {
    const lim = clamp(num((o || {}).angle, 30), 0, 180);
    return flagOp(m0, edges, "hard", (mp, k, e) => {
      let hard = e.faces.length !== 2;
      if (!hard) {
        const a = P.faceNormal(m0, m0.f[e.faces[0]]), b = P.faceNormal(m0, m0.f[e.faces[1]]);
        hard = (Math.acos(clamp(dot(a, b), -1, 1)) * 180) / Math.PI > lim + 1e-9;
      }
      if (hard) mp.set(k, 1); else mp.delete(k);
    }) || fail(m0, "Soften/Harden: select edges.");
  };

  // ------------------------------------------------------------------ insert edge loop (P.loopCut stays: the old one)
  // the edge's ring of quads is cut across. t (0.5): where on each ring edge, measured the same way round the ring
  // from the first vertex of the given edge. equalDistance (false): the cut sits the same absolute distance
  // (t * the given edge's length, or `distance`) from that side on every ring edge, limited by the shortest.
  // count (1): more than 1 inserts that many evenly spaced loops (t / equalDistance are then not used).
  P.insertEdgeLoop = (m0, edge, o) => {
    o = o || {};
    const T = P.topology(m0);
    const pr = Array.isArray(edge) && edge.length === 2 && typeof edge[0] === "number" ? edge : edge && edge.a != null ? [edge.a, edge.b] : null;
    const ei = typeof edge === "number" ? (T.edges[edge] ? edge : undefined) : pr ? T.edge(pr[0], pr[1]) : undefined;
    if (ei === undefined) return fail(m0, "Insert Edge Loop: pick an edge of the mesh.");
    const ring = P.edgeRing(m0, T, ei);
    if (!ring.faces.length) return fail(m0, "Insert Edge Loop: the edge needs a quad beside it (the loop runs across quads).");
    const n = clamp(Math.round(num(o.count, 1)), 1, 64), t = clamp(num(o.t != null ? o.t : o.weight, 0.5), 0.01, 0.99);
    const ringF = new Set(ring.faces), start = new Map([[ei, pr ? pr[0] : T.edges[ei].a]]), queue = [ei];
    while (queue.length) {                     // across a quad q0 q1 q2 q3 (cut q0-q1 and q2-q3): q0 pairs with q3
      const e = queue.shift(), s = start.get(e);
      for (const fi of T.edges[e].faces) {
        if (!ringF.has(fi)) continue;
        const f = m0.f[fi], fe = T.faceEdges[fi], k = fe.indexOf(e), opp = fe[(k + 2) % 4];
        if (start.has(opp)) continue;
        start.set(opp, s === f[k] ? f[(k + 3) % 4] : f[(k + 2) % 4]);
        queue.push(opp);
      }
    }
    const eq = !!o.equalDistance && n === 1;
    let dAbs = 0;
    if (eq) {
      const e0 = T.edges[ei];
      dAbs = o.distance != null ? Math.max(1e-9, num(o.distance, 0)) : t * dist(m0.v[e0.a], m0.v[e0.b]);
      for (const e of ring.edges) dAbs = Math.min(dAbs, 0.99 * dist(m0.v[T.edges[e].a], m0.v[T.edges[e].b]));
    }
    const m = cp(m0), pts = new Map();
    for (const e of ring.edges) {
      const ed = T.edges[e], s = start.has(e) ? start.get(e) : ed.a, oth = s === ed.a ? ed.b : ed.a, L = dist(m0.v[s], m0.v[oth]);
      const ts = n > 1 ? Array.from({ length: n }, (_, i) => (i + 1) / (n + 1)) : [eq ? (L ? clamp(dAbs / L, 0.01, 0.99) : 0.5) : t];
      pts.set(e, { s, list: ts.map((x) => { const id = m.v.length; m.v.push(lerp(m0.v[s], m0.v[oth], x)); return id; }) });
      const others = ed.faces.filter((fi) => !ringF.has(fi));
      if (others.length) insertOnEdge(m, s, oth, pts.get(e).list, others);
    }
    const newE = [];
    for (const fi of ring.faces) {
      const f = m0.f[fi], fe = T.faceEdges[fi];
      const k = [0, 1].find((j) => pts.has(fe[j]) && pts.has(fe[j + 2]));
      if (k === undefined) continue;
      const q = [0, 1, 2, 3].map((j) => f[(k + j) % 4]), A = pts.get(fe[k]), B = pts.get(fe[k + 2]);
      const Pp = A.s === q[0] ? A.list : A.list.slice().reverse(), Qq = B.s === q[3] ? B.list : B.list.slice().reverse();
      const pieces = [[q[0], Pp[0], Qq[0], q[3]]];
      for (let i = 1; i < Pp.length; i++) pieces.push([Pp[i - 1], Pp[i], Qq[i], Qq[i - 1]]);
      pieces.push([Pp[Pp.length - 1], q[1], q[2], Qq[Qq.length - 1]]);
      m.f[fi] = pieces[0];
      pieces.slice(1).forEach((pc) => m.f.push(pc));
      Pp.forEach((p, i) => newE.push([p, Qq[i]]));
    }
    return finish(m, edgeSel(newE));
  };

  // ------------------------------------------------------------------ merge (P.mergeVerts stays: the old one)
  // the given vertices (none: all) closer than `threshold` (0: only where they coincide) become one, at their middle.
  // alwaysMergeTwo: exactly two selected vertices merge whatever the distance.
  P.merge = (m0, verts, o) => {
    o = o || {};
    const vs = verts && verts.length ? vertIds(m0, verts) : m0.v.map((_, i) => i);
    if (vs.length < 2) return fail(m0, "Merge: select two or more vertices.");
    const th = Math.max(0, num(o.threshold != null ? o.threshold : o.distance, 0));
    let groups;
    if (o.alwaysMergeTwo && vs.length === 2) groups = [vs];
    else {
      const cell = Math.max(th, 1e-9), grid = new Map(), uf = UF(), key = (p) => p.map((x) => Math.floor(x / cell));
      for (const i of vs) { const k = key(m0.v[i]).join(","); push(grid, k, i); }
      for (const i of vs) {
        const [x, y, z] = key(m0.v[i]);
        for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (let c = -1; c <= 1; c++) {
          for (const j of grid.get([x + a, y + b, z + c].join(",")) || []) if (j > i && dist(m0.v[i], m0.v[j]) <= th + 1e-12) uf.union(i, j);
        }
      }
      const gm = new Map();
      for (const i of vs) push(gm, uf.find(i), i);
      groups = [...gm.values()].filter((g) => g.length > 1);
    }
    if (!groups.length) return fail(m0, "Merge: no selected vertices are within the threshold of each other.");
    const r = mergeGroups(m0, groups);
    return finish(r.m, { v: r.reps, e: [], f: [] });
  };

  // ------------------------------------------------------------------ Mesh > Cleanup and the heads-up statistics
  function facePlane(m, f) {                  // { n, c, u, w } (n by Newell; u, w span the plane)
    let n = [0, 0, 0];
    for (let i = 0; i < f.length; i++) {
      const a = m.v[f[i]], b = m.v[f[(i + 1) % f.length]];
      n = add(n, [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])]);
    }
    n = norm(n);
    const c = centreOf(f.map((i) => m.v[i]));
    const u = len(n) ? perp(n) : [1, 0, 0];
    return { n, c, u, w: cross(n, u) };
  }
  function isConcave(m, f) {
    if (f.length < 4) return false;
    const { n } = facePlane(m, f);
    if (!len(n)) return false;
    for (let k = 0; k < f.length; k++) {
      const p = m.v[f[(k + f.length - 1) % f.length]], x = m.v[f[k]], q = m.v[f[(k + 1) % f.length]];
      if (dot(cross(sub(x, p), sub(q, x)), n) < -1e-12 * (dist(p, x) * dist(x, q) + 1e-30)) return true;
    }
    return false;
  }
  function planarDeviation(m, f) {            // degrees: the most any corner leans out of the face's plane
    if (f.length < 4) return 0;
    const { n, c } = facePlane(m, f);
    if (!len(n)) return 0;
    let worst = 0;
    for (const i of f) {
      const d = sub(m.v[i], c), l = len(d);
      if (l > 1e-12) worst = Math.max(worst, Math.asin(clamp(Math.abs(dot(d, n)) / l, 0, 1)) / DEG);
    }
    return worst;
  }
  // ear clipping that tolerates a face touching itself (a hole joined by a bridge edge): corners that are the same
  // vertex never block an ear
  function earClipWeak(m, f) {
    const { n, u, w } = facePlane(m, f), o0 = m.v[f[0]];
    const p2 = f.map((i) => { const d = sub(m.v[i], o0); return [dot(d, u), dot(d, w)]; });
    const ar = (a, b, c) => (p2[b][0] - p2[a][0]) * (p2[c][1] - p2[a][1]) - (p2[b][1] - p2[a][1]) * (p2[c][0] - p2[a][0]);
    void n;
    const idx = f.map((_, i) => i), tris = [];
    for (let guard = 0; idx.length > 3 && guard < 100000; guard++) {
      let cutAt = -1, bestQ = -Infinity;
      for (let i = 0; i < idx.length; i++) {
        const a = idx[(i + idx.length - 1) % idx.length], b = idx[i], c = idx[(i + 1) % idx.length], A = ar(a, b, c);
        if (A <= 1e-12) continue;
        const ids = new Set([f[a], f[b], f[c]]);
        if (idx.some((q) => !ids.has(f[q]) && ar(a, b, q) >= 0 && ar(b, c, q) >= 0 && ar(c, a, q) >= 0)) continue;
        const e2 = (x, y) => (p2[x][0] - p2[y][0]) ** 2 + (p2[x][1] - p2[y][1]) ** 2;
        const q = A / (e2(a, b) + e2(b, c) + e2(c, a));
        if (q > bestQ) { bestQ = q; cutAt = i; }
      }
      if (cutAt < 0) cutAt = 0;
      const a = idx[(cutAt + idx.length - 1) % idx.length], b = idx[cutAt], c = idx[(cutAt + 1) % idx.length];
      tris.push([f[a], f[b], f[c]]);
      idx.splice(cutAt, 1);
    }
    tris.push(idx.map((i) => f[i]));
    return tris.filter((t) => new Set(t).size === 3);
  }
  // triangles of one face merged back across their inner diagonals while the piece stays convex (Hertel-Mehlhorn);
  // maxSides 4: quads and triangles only
  function convexPieces(m, face, tris, maxSides) {
    const { n } = facePlane(m, face);
    let polys = tris.map((t) => t.slice());
    const convex = (g) => {
      for (let k = 0; k < g.length; k++) {
        const p = m.v[g[(k + g.length - 1) % g.length]], x = m.v[g[k]], q = m.v[g[(k + 1) % g.length]];
        if (dot(cross(sub(x, p), sub(q, x)), n) <= 1e-12) return false;
      }
      return true;
    };
    const outer = new Set();
    for (let k = 0; k < face.length; k++) outer.add(face[k] + ">" + face[(k + 1) % face.length]);
    for (let changed = true; changed;) {
      changed = false;
      const owner = new Map();
      polys.forEach((g, gi) => { for (let k = 0; k < g.length; k++) owner.set(g[k] + ">" + g[(k + 1) % g.length], gi); });
      const cands = [];
      polys.forEach((g, gi) => {
        for (let k = 0; k < g.length; k++) {
          const a = g[k], b = g[(k + 1) % g.length], gj = owner.get(b + ">" + a);
          if (gj === undefined || gj <= gi || outer.has(a + ">" + b)) continue;
          const h = polys[gj], ka = h.indexOf(b);
          // g runs a->b, h runs b->a: g's path b..a (without the diagonal) then h's path a..b
          const pa = cyc(g, (k + 1) % g.length, k), pb = cyc(h, (ka + 1) % h.length, ka);
          const merged = dedupeCyc([...pa, ...pb.slice(1, -1)]);
          if (merged.length > maxSides || new Set(merged).size !== merged.length || !convex(merged)) continue;
          cands.push({ gi, gj, merged, score: merged.length === 4 ? 0 : 1 });
        }
      });
      cands.sort((x, y) => x.score - y.score);
      if (cands.length) {
        const c = cands[0];
        polys = polys.filter((_, i) => i !== c.gi && i !== c.gj).concat([c.merged]);
        changed = true;
      }
    }
    return polys;
  }
  function analyse(m, o) {
    const T = P.topology(m), lt = Math.max(0, num(o.lengthTol, 1e-5)), at = Math.max(0, num(o.areaTol, 1e-5));
    const pt = Math.max(0, num(o.planarTol, 1));
    const r = { quads: [], nsided: [], concave: [], holed: [], nonPlanar: [], lamina: [], zeroFaces: [], zeroEdges: [], nmEdges: [], nmVerts: [], flipped: [] };
    const seen = new Map();
    m.f.forEach((f, fi) => {
      const holed = new Set(f).size !== f.length;
      if (holed) r.holed.push(fi);
      if (f.length === 4 && !holed) r.quads.push(fi);
      if (f.length > 4 && !holed) r.nsided.push(fi);
      if (!holed && isConcave(m, f)) r.concave.push(fi);
      if (!holed && planarDeviation(m, f) > pt + 1e-9) r.nonPlanar.push(fi);
      if (newellArea(m, f) <= at) r.zeroFaces.push(fi);
      const k = f.slice().sort((a, b) => a - b).join(",");
      if (seen.has(k)) r.lamina.push(fi); else seen.set(k, fi);
    });
    const dir = new Map();
    m.f.forEach((f) => { for (let k = 0; k < f.length; k++) { const d = f[k] + ">" + f[(k + 1) % f.length]; dir.set(d, (dir.get(d) || 0) + 1); } });
    T.edges.forEach((e, ei) => {
      if (dist(m.v[e.a], m.v[e.b]) <= lt) r.zeroEdges.push(ei);
      if (e.faces.length > 2) r.nmEdges.push(ei);
      if ((dir.get(e.a + ">" + e.b) || 0) > 1 || (dir.get(e.b + ">" + e.a) || 0) > 1) r.flipped.push(ei);
    });
    r.nmVerts = fanSplit(m, T).verts;
    return { T, r, lt, at };
  }
  // the fans round every vertex: faces joined across an edge they share properly. At an edge with 3+ faces each face
  // that runs a->b is paired with the next face round the edge (on its inner side) that runs b->a, so two solids
  // that touch along an edge come apart. A vertex with 2+ fans is non-manifold; `split` gives each extra fan a copy.
  function edgeLinks(m, T) {
    return T.edges.map((e) => {
      const fs = uniq(e.faces);
      if (fs.length < 2) return [];
      if (fs.length === 2) return [[fs[0], fs[1]]];        // a plain edge (or a flipped one: still one surface)
      const d = norm(sub(m.v[e.b], m.v[e.a])), e1 = perp(d), e2 = cross(d, e1), info = [];
      for (const fi of fs) {
        const f = m.f[fi], k = f.indexOf(e.a), fwd = f[(k + 1) % f.length] === e.b;
        let r = sub(P.centroid(m, f), m.v[e.a]);
        r = sub(r, mul(d, dot(r, d)));
        const n = P.faceNormal(m, f), ang = Math.atan2(dot(r, e2), dot(r, e1));
        info.push({ fi, fwd, ang, sense: dot(cross(r, mul(n, -1)), d) >= 0 ? 1 : -1 });
      }
      const out = [], used = new Set();
      for (const a of info) {
        if (!a.fwd || used.has(a.fi)) continue;
        let best = null, bd = Infinity;
        for (const b of info) {
          if (b.fwd || used.has(b.fi)) continue;
          let da = (b.ang - a.ang) * a.sense;
          while (da <= 1e-9) da += 2 * Math.PI;
          if (da < bd) { bd = da; best = b; }
        }
        if (best) { used.add(a.fi); used.add(best.fi); out.push([a.fi, best.fi]); }
      }
      return out;
    });
  }
  function fanSplit(m, T, split) {
    const links = edgeLinks(m, T), verts = [];
    const out = split ? { v: m.v.map((p) => p.slice()), f: m.f.map((f) => f.slice()) } : null;
    m.v.forEach((_, x) => {
      const fs = uniq(T.vertFaces[x]);
      if (fs.length < 2) return;
      const uf = UF();
      fs.forEach((fi) => uf.find(fi));
      for (const ei of T.vertEdges[x]) for (const [a, b] of links[ei]) uf.union(a, b);
      const groups = new Map();
      for (const fi of fs) push(groups, uf.find(fi), fi);
      if (groups.size < 2) return;
      verts.push(x);
      if (!out) return;
      [...groups.values()].slice(1).forEach((g) => {
        const id = out.v.length;
        out.v.push(m.v[x].slice());
        for (const fi of g) out.f[fi] = out.f[fi].map((y) => (y === x ? id : y));
      });
    });
    return { verts, m: out };
  }
  function orientShells(m) {                   // conform normals: neighbours agree, closed shells point outward
    const T = P.topology(m), seen = new Int8Array(m.f.length), flips = [];
    for (let s0 = 0; s0 < m.f.length; s0++) {
      if (seen[s0]) continue;
      const shell = [s0];
      seen[s0] = 1;
      for (let qi = 0; qi < shell.length; qi++) {
        const fi = shell[qi], f = m.f[fi];
        for (let k = 0; k < f.length; k++) {
          const a = f[k], b = f[(k + 1) % f.length], e = T.edges[T.edge(a, b)];
          if (e.faces.length !== 2) continue;
          const g = e.faces[0] === fi ? e.faces[1] : e.faces[0];
          if (g === fi || seen[g]) continue;
          const h = m.f[g], j = h.indexOf(a);
          if (h[(j + 1) % h.length] === b) { m.f[g] = h.slice().reverse(); flips.push(g); }
          seen[g] = 1; shell.push(g);
        }
      }
      const sub2 = { v: m.v, f: shell.map((fi) => m.f[fi]) };
      if (P.meshCheck(sub2).closed && P.volume(sub2) < 0) for (const fi of shell) { m.f[fi] = m.f[fi].slice().reverse(); flips.push(fi); }
    }
    return uniq(flips).length;
  }
  // P.cleanup(m, opts) -> { m, sel, warn, report }
  //   op: "cleanup" (default: fix what is found) | "select" (m unchanged; sel = the offending faces / edges / verts)
  //   Fix by tessellation (all off by default): quads (4-sided -> triangles), nsided (n-gons -> quads + triangles),
  //   concave (-> convex pieces), holed (a face that touches itself -> triangulated without filling the hole),
  //   nonPlanar (corners leaning more than planarTol degrees (1) out of the plane -> triangles)
  //   Remove geometry (on by default): lamina (a face on the same vertices as another; one copy stays),
  //   nonManifold (true | "normals": also conform normals | "geometry": split only), zeroEdges (shorter than
  //   lengthTol 1e-5: collapsed), zeroFaces (area under areaTol 1e-5: removed, their vertices merged / the
  //   sliver's points passed to the neighbour). zeroMap is not available (Forge meshes carry no UVs).
  //   report: how many of each were found (select) or fixed (cleanup).
  P.cleanup = (m0, o) => {
    o = o || {};
    const on = (k, d) => (o[k] == null ? d : !!o[k]);
    const want = { quads: on("quads", false), nsided: on("nsided", false), concave: on("concave", false), holed: on("holed", false),
      nonPlanar: on("nonPlanar", false), lamina: on("lamina", true), nonManifold: on("nonManifold", true), zeroEdges: on("zeroEdges", true), zeroFaces: on("zeroFaces", true) };
    const nmMode = o.nonManifold === "geometry" ? "geometry" : "normals";
    const { T, r } = analyse(m0, o);
    const report = { quads: 0, nsided: 0, concave: 0, holed: 0, nonPlanar: 0, lamina: 0, nonManifoldEdges: 0, nonManifoldVerts: 0, flipped: 0, zeroEdges: 0, zeroFaces: 0 };
    if (o.op === "select") {
      const fs = new Set(), es = new Set(), vs = new Set();
      for (const k of ["quads", "nsided", "concave", "holed", "nonPlanar", "lamina", "zeroFaces"]) if (want[k]) { report[k] = r[k].length; r[k].forEach((fi) => fs.add(fi)); }
      if (want.zeroEdges) { report.zeroEdges = r.zeroEdges.length; r.zeroEdges.forEach((ei) => es.add(ei)); }
      if (want.nonManifold) {
        report.nonManifoldEdges = r.nmEdges.length; report.nonManifoldVerts = r.nmVerts.length;
        r.nmEdges.forEach((ei) => es.add(ei)); r.nmVerts.forEach((x) => vs.add(x));
        if (nmMode === "normals") { report.flipped = r.flipped.length; r.flipped.forEach((ei) => es.add(ei)); }
      }
      const pairs = [...es].map((ei) => [T.edges[ei].a, T.edges[ei].b]);
      return { m: m0, sel: { v: [...vs], e: pairs, f: [...fs].sort((a, b) => a - b) }, warn: "", report };
    }
    let m = cp(m0);
    const warns = [];
    const compact = (mm) => { const x = finish(mm, NONE()).m; return x; };
    // 1. lamina: the later copies of a face go
    if (want.lamina && r.lamina.length) {
      const drop = new Set(r.lamina);
      report.lamina = drop.size;
      m.f = m.f.filter((_, i) => !drop.has(i));
    }
    // 2. zero-length edges collapse (their ends merge at the middle)
    if (want.zeroEdges || want.zeroFaces) {
      const lt = Math.max(0, num(o.lengthTol, 1e-5)), Tm = P.topology(m), uf = UF(), hit = new Set();
      Tm.edges.forEach((e) => { if (dist(m.v[e.a], m.v[e.b]) <= lt) { uf.union(e.a, e.b); hit.add(e.a); hit.add(e.b); if (want.zeroEdges) report.zeroEdges++; } });
      if (want.zeroFaces && !want.zeroEdges) {      // only the short edges of zero-area faces merge
        const at = Math.max(0, num(o.areaTol, 1e-5)), keep = new Set();
        m.f.forEach((f) => { if (newellArea(m, f) <= at) for (const x of f) keep.add(x); });
        for (const x of [...hit]) if (!keep.has(x)) hit.delete(x);
      }
      if (hit.size) {
        const before = m.f.length, gm = new Map();
        for (const x of hit) push(gm, uf.find(x), x);
        const mg = mergeGroups(m, [...gm.values()]);
        m = mg.m;
        if (want.zeroFaces) report.zeroFaces += Math.max(0, before - m.f.length);
      }
    }
    // 3. zero-area faces left (slivers: long but flat): the face goes, its middle points join the neighbour across
    //    its longest edge, so the surface stays closed
    if (want.zeroFaces) {
      const at = Math.max(0, num(o.areaTol, 1e-5));
      let slivers = 0;
      for (let pass = 0; pass < 100000; pass++) {
        const fi = m.f.findIndex((f) => newellArea(m, f) <= at);
        if (fi < 0) break;
        const f = m.f[fi];
        let best = -1, bl = -1;
        for (let k = 0; k < f.length; k++) { const l = dist(m.v[f[k]], m.v[f[(k + 1) % f.length]]); if (l > bl) { bl = l; best = k; } }
        const w = f[best], u = f[(best + 1) % f.length], mids = cyc(f, (best + 2) % f.length, (best + f.length - 1) % f.length);
        // the face runs u -> mids -> w and closes with w -> u
        const order = [u, ...(f.length > 2 ? mids : []), w];
        const Tm = P.topology(m), ei = Tm.edge(u, w), nb = ei === undefined ? [] : Tm.edges[ei].faces.filter((g) => g !== fi);
        m.f.splice(fi, 1);
        const nbIds = nb.map((g) => (g > fi ? g - 1 : g));
        if (nbIds.length === 1 && order.length > 2) insertOnEdge(m, u, w, order.slice(1, -1), nbIds);
        else if (nbIds.length !== 1) warns.push("a zero-area face on a border or non-manifold edge was removed (it leaves a gap)");
        report.zeroFaces++;
        slivers++;
      }
      if (slivers) m.f = cleanMesh(m.f);
    }
    // 4. tessellation
    const tess = (test, key, fn) => {
      if (!want[key]) return;
      const nf = [];
      m.f.forEach((f) => {
        if (!test(f)) { nf.push(f); return; }
        const pieces = fn(f);
        if (pieces.length > 1 || (pieces[0] && pieces[0].length !== f.length)) report[key]++;
        nf.push(...pieces);
      });
      m.f = nf;
    };
    tess((f) => new Set(f).size !== f.length, "holed", (f) => convexPieces(m, f, earClipWeak(m, f), 4));
    tess((f) => isConcave(m, f), "concave", (f) => convexPieces(m, f, earClip(m, f), Infinity));
    tess((f) => f.length > 4, "nsided", (f) => convexPieces(m, f, earClip(m, f), 4));
    const pt = Math.max(0, num(o.planarTol, 1));
    tess((f) => planarDeviation(m, f) > pt + 1e-9, "nonPlanar", (f) => earClip(m, f));
    tess((f) => f.length === 4, "quads", (f) => earClip(m, f));
    // 5. non-manifold last (the pro tools' advice): every vertex with 2+ fans is split, then normals conformed
    if (want.nonManifold) {
      m = compact(m);
      const Tm = P.topology(m);
      report.nonManifoldEdges = Tm.edges.filter((e) => e.faces.length > 2).length;
      const fs = fanSplit(m, Tm, true);
      report.nonManifoldVerts = fs.verts.length;
      if (fs.m) m = { ...fs.m, creases: m.creases, hard: m.hard };
      if (nmMode === "normals") report.flipped = orientShells(m);
      const left = P.topology(m).edges.filter((e) => e.faces.length > 2).length;
      if (left) warns.push(left + " non-manifold edges could not be split");
    }
    if (!warns.length && Object.values(report).every((x) => !x)) return { m: m0, sel: NONE(), warn: "", report };   // nothing to fix
    const res = finish(m, NONE(), warns.length ? "Cleanup: " + uniq(warns).join("; ") + "." : "");
    res.report = report;
    return res;
  };
  // the heads-up display: what the mesh is made of
  P.meshStats = (m) => {
    const T = P.topology(m), { r } = analyse(m, {});
    let tris = 0, quads = 0, ngons = 0;
    for (const f of m.f) { if (f.length === 3) tris++; else if (f.length === 4) quads++; else if (f.length > 4) ngons++; }
    return { verts: m.v.length, edges: T.edges.length, faces: m.f.length, tris, quads, ngons,
      border: T.edges.filter((e) => e.faces.length === 1).length, nonManifoldEdges: r.nmEdges.length, nonManifoldVerts: r.nmVerts.length,
      lamina: r.lamina.length, concave: r.concave.length, nonPlanar: r.nonPlanar.length, zeroEdges: r.zeroEdges.length, zeroFaces: r.zeroFaces.length,
      shells: P.shells(m).length };
  };

  root.ForgePoly = P;
  if (typeof module !== "undefined" && module.exports) module.exports = P;
})(typeof window !== "undefined" ? window : globalThis);
