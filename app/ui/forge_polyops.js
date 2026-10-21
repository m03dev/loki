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
//   extrudeFaces(m, faces, { thickness=0, offset=0, keepTogether=true })   -> the extruded caps (faces)
//       keepTogether: edge-connected faces move as one region (no inner walls); false: each face on its own.
//       thickness moves along the (averaged) normal, offset pulls the cap's border inward in its plane.
//   extrudeEdges(m, edges, { thickness=0, offset=0 })                      -> the new outer edges
//       each edge gets a quad to a copy of itself; connected edges share the new vertices. Border edges grow the
//       surface (offset = outward in the face's plane); an INTERIOR edge makes a fin (that edge then has 3 faces,
//       as in the pro tool). thickness 0 + offset 0: the new edges sit on the old (zero-area quads to be dragged).
//   extrudeVerts(m, verts, { width=0.1, length=0 })                        -> the tip vertices
//       width: fraction of each edge (max 0.49); every face around the vertex is cut and a triangle fan rises to
//       the vertex, moved `length` along its normal.
//   bevel(m, edges | { e } | { f }, { fraction=0.5, segments=1 })          -> the new bevel faces
//       width = fraction * 0.49 * the shortest edge at the bevelled vertices. Corners where 3+ bevelled edges meet
//       get a cap polygon; a cube with all 12 edges bevelled has 26 faces. segments > 1 rounds the profile.
//       faces: their border edges are bevelled. Border edges of the mesh cannot be bevelled.
//   bridge(m, edges, { divisions=0 })                                      -> the bridge faces
//       two border chains (open or closed) with the same edge count, joined by quads (closed loops twist-aligned).
//   appendPolygon(m, verts)                                                -> the new face
//   fillHole(m, borderEdges)                                               -> the new faces
//   poke(m, faces, { offset=0 })                                           -> the new triangles
//   wedge(m, faces, hingeEdge, { angle=90, divisions=4 })                  -> the swung caps
//   chamferVerts(m, verts, { width=0.25 })                                 -> the new corner faces
//   collapse(m, { e } | { f })                                             -> the merged vertices
//   connect(m, { v } | { e })                                              -> the new edges
//       edges: midpoints; a face with 2 of them is split, with 3+ they meet at a new centre vertex.
//       verts: a face with 2 (not neighbours) is split between them; with 3+ an inner polygon joins them.
//   detach(m, { v } | { e })                                               -> the split vertices / both sides' edges
//   dissolveEdges(m, edges, { cleanVerts=false })                          -> nothing (the pro Delete clears it)
//       the pro Delete on edges: the two faces merge into one n-gon; a border edge deletes its face; cleanVerts
//       (Ctrl+Delete) also removes the winged vertices (2 edges) left behind. (P.deleteEdges stays: it deletes faces.)
//   dissolveVerts(m, verts)                                                -> nothing
//       a winged vertex leaves its faces; an interior vertex's faces merge into one n-gon without it.
//   offsetEdgeLoop(m, edge(s), { distance=0.25 })                          -> the two new loops
//       distance: fraction of the side edges (max 0.95).
//   multiCut(m, points)                                                    -> the new edges
//       points in order, each { v: id } or { e: [a, b], t: 0..1 from a }; consecutive points must share a face.
//   sliceFaces(m, faces, planePoint, planeNormal)                          -> the new edges ([] faces = all)
//   triangulateFaces(m, faces)  (P.triangulate is the GPU fan; kept)       -> the triangles ([] = all)
//   quadrangulate(m, faces, { angle=30 })                                  -> the resulting faces ([] = all)
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

  // ------------------------------------------------------------------ extrude
  P.extrudeFaces = (m0, faces, o) => {
    o = o || {};
    const th = num(o.thickness, 0), off = num(o.offset, 0), together = o.keepTogether !== false;
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
      const top = new Map();
      for (const [i, ns] of nrm) {
        let p = add(m0.v[i], mul(norm(ns), th));
        const w = inward.get(i);
        if (off && w) {          // a mitred inset: every border edge moves `off` inward
          const mi = norm(w.reduce((s, q) => add(s, q), [0, 0, 0]));
          const c = Math.max(0.25, w.reduce((s, q) => s + dot(mi, q), 0) / w.length);
          p = add(p, mul(mi, off / c));
        }
        top.set(i, m.v.length); m.v.push(p);
      }
      for (const [a, b] of bnd) m.f.push([a, b, top.get(b), top.get(a)]);
      for (const fi of g) m.f[fi] = m0.f[fi].map((i) => top.get(i));
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
    const nv = new Map();
    for (const [i, n] of nrm) {
      let p = add(m0.v[i], mul(norm(n), th));
      const ou = out.get(i);
      if (off && ou) p = add(p, mul(norm(ou), off));
      nv.set(i, m.v.length); m.v.push(p);
    }
    const newE = [];
    for (const [x, y] of spans) { m.f.push([y, x, nv.get(x), nv.get(y)]); newE.push([nv.get(x), nv.get(y)]); }
    return finish(m, edgeSel(newE));
  };

  // cut every face corner at the given vertices `t` along its two edges (chamfer), or raise a spike (vertex extrude)
  function cornerCut(m0, verts, t, tip) {
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
      if (ring.length >= 3) { newF.push(m.f.length); m.f.push(ring); }
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
    const r = cornerCut(m0, verts, clamp(num(o.width, 0.25), 0.001, 0.49), null);
    if (!r) return fail(m0, "Chamfer Vertex: select one or more vertices that belong to faces.");
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
    const d = frac * 0.49 * minLen;
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
        const K = add(m0.v[p], mul(ax, dot(sub(mid, m0.v[p]), ax) / (dot(ax, ax) || 1)));
        for (let i = 1; i < segs; i++) {
          const s = i / segs;
          pts.push(newPt(add(add(mul(pa, (1 - s) * (1 - s)), mul(K, 2 * s * (1 - s))), mul(pb, s * s)), v));
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
    return finish(m, faceSel(m, newF));
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
    const m = cp(m0), R = [];
    for (let r = 0; r <= D + 1; r++) {
      R.push([]);
      for (let i = 0; i < count; i++) {
        const a = A.vs[i], b = B.vs[pairOf(i)];
        if (r === 0) R[r].push(a);
        else if (r === D + 1) R[r].push(b);
        else { R[r].push(m.v.length); m.v.push(lerp(m0.v[a], m0.v[b], r / (D + 1))); }
      }
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
  P.connect = (m0, c) => {
    c = comp(c);
    const T = P.topology(m0), m = cp(m0), newE = [];
    if (c.e && c.e.length) {
      const ids = edgeIds(m0, T, c.e);
      if (!ids.length) return fail(m0, "Connect: select edges or vertices.");
      const mids = new Set(), touched = new Set();
      for (const ei of ids) {
        const e = T.edges[ei], id = m.v.length;
        m.v.push(lerp(m0.v[e.a], m0.v[e.b], 0.5));
        mids.add(id);
        insertOnEdge(m, e.a, e.b, [id], e.faces);
        e.faces.forEach((fi) => touched.add(fi));
      }
      for (const fi of [...touched].sort((a, b) => a - b)) {
        const f = m.f[fi], pos = [];
        f.forEach((x, k) => { if (mids.has(x)) pos.push(k); });
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
    const T = P.topology(m0), cands = [];
    for (const e of T.edges) {
      if (e.faces.length !== 2) continue;
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
    const m = cp(m0), pts = new Map(), onEdge = new Map(), jobs = [];
    const pt = (x, y) => {
      const k = x + ">" + y;
      if (!pts.has(k)) {
        const ei = T.edge(x, y), t = loopV.has(y) ? Math.min(t0, 0.49) : t0, id = m.v.length;
        m.v.push(lerp(m0.v[x], m0.v[y], t));
        pts.set(k, id);
        push(onEdge, ei, { id, d: T.edges[ei].a === x ? t : 1 - t });
      }
      return pts.get(k);
    };
    for (const ei of loop) for (const fi of T.edges[ei].faces) {
      const e = T.edges[ei], f = m0.f[fi], n = f.length;
      if (n < 4) return fail(m0, "Offset Edge Loop: a triangle touches the loop; it needs quads (or bigger) either side.");
      const k0 = f.indexOf(e.a), [x, y] = f[(k0 + 1) % n] === e.b ? [e.a, e.b] : [e.b, e.a], k = f.indexOf(x);
      const px = f[(k + n - 1) % n], ny = f[(k + 2) % n];
      jobs.push({ fi, sx: pt(x, px), sy: pt(y, ny) });
    }
    for (const [ei, l] of onEdge) {
      l.sort((p, q) => p.d - q.d);
      insertOnEdge(m, T.edges[ei].a, T.edges[ei].b, l.map((p) => p.id), T.edges[ei].faces);
    }
    const newE = [];
    for (const j of jobs) {
      const f = m.f[j.fi], [A, B] = splitAt(f, f.indexOf(j.sx), f.indexOf(j.sy));
      m.f[j.fi] = A; m.f.push(B); newE.push([j.sx, j.sy]);
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

  root.ForgePoly = P;
  if (typeof module !== "undefined" && module.exports) module.exports = P;
})(typeof window !== "undefined" ? window : globalThis);
