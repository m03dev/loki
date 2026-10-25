// Forge poly modelling + DynaMesh (owner 2026-10-18: "primitives, dynamesh ... poly modeling ... take their code").
// Pure functions, no DOM and no three.js, so tests/test_forge_poly.js runs them in node.
//
// A poly mesh is { v: [[x, y, z], ...], f: [[i0, i1, i2, i3...], ...] }: n-gon faces, counter-clockwise seen from
// outside. Primitives, extrude, inset, subdivide, delete and flip follow GoBuild's mesh operations
// (github.com/marcel-b-roodt/GoBuild, addons/go_build/mesh/operations/*.gd, GPL-3.0 - LOKI is AGPL-3.0; see
// docs/THIRD_PARTY.md): extrude keeps the face and adds side quads [bottom_a, bottom_b, top_b, top_a]; inset pulls
// a ring toward the centroid. Extrude here moves a whole connected selection as one region (GoBuild extrudes each
// face on its own, which leaves inner walls). Smooth is Catmull-Clark (1978). DynaMesh is ZBrush's idea, done the
// open way: voxelise the model (ray parity along all three axes, majority vote, so small holes do not leak),
// then naive Surface Nets (Gibson 1998) - which gives QUADS, so poly tools work again on a remeshed sculpt.
"use strict";

(function (root) {
  const P = {};
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const len = (a) => Math.hypot(a[0], a[1], a[2]);
  const norm = (a) => { const l = len(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
  // per-edge flags (crease weights, hard edges: Map edgeKey -> value, set by forge_polyops.js) travel with the copy
  const clone = (m) => {
    const o = { v: m.v.map((p) => p.slice()), f: m.f.map((f) => f.slice()) };
    if (m.creases instanceof Map) o.creases = new Map(m.creases);
    if (m.hard instanceof Map) o.hard = new Map(m.hard);
    return o;
  };
  P.clone = clone;

  // Newell's method, as GoBuildMesh.compute_face_normal
  P.faceNormal = (m, f) => {
    let n = [0, 0, 0];
    for (let i = 0; i < f.length; i++) {
      const a = m.v[f[i]], b = m.v[f[(i + 1) % f.length]];
      n = add(n, [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])]);
    }
    return norm(n);
  };
  P.centroid = (m, f) => mul(f.reduce((s, i) => add(s, m.v[i]), [0, 0, 0]), 1 / f.length);

  // ------------------------------------------------------------------ primitives (GoBuild shape_creation_catalog)
  // Every primitive fits in a unit box centred on the origin. opts: segments / sides / rings with sensible defaults.
  P.PRIMITIVES = {
    cube: { name: "Cube", what: "A box made of quads. Segments splits every side.", params: { segments: [1, 1, 8], baseline: [0, -1, 1] } },
    plane: { name: "Plane", what: "A flat grid of quads, one sided.", params: { segments: [4, 1, 32], baseline: [0, -1, 1] } },
    sphere: { name: "Sphere", what: "A UV sphere: rings and segments.", params: { segments: [24, 6, 64], rings: [12, 3, 48], baseline: [0, -1, 1] } },
    quadsphere: { name: "Quad sphere", what: "A subdivided cube pushed round: even quads, best for sculpting.", params: { segments: [6, 1, 24], baseline: [0, -1, 1] } },
    cylinder: { name: "Cylinder", what: "Sides and height segments, capped.", params: { sides: [16, 3, 64], segments: [1, 1, 16], baseline: [0, -1, 1] } },
    cone: { name: "Cone", what: "A capped cone.", params: { sides: [16, 3, 64], baseline: [0, -1, 1] } },
    torus: { name: "Torus", what: "A ring: ring segments and tube sides; thickness sets the tube.", params: { segments: [32, 3, 96], sides: [12, 3, 48], thickness: [0.3, 0.05, 0.45], baseline: [0, -1, 1] } },
  };
  // float attributes (the rest are whole counts); the step the editors use for each
  P.PRIM_FLOAT = { thickness: 0.01, baseline: 0.05 };
  function opt(kind, o, k) {
    const d = P.PRIMITIVES[kind].params[k];
    const x = o && o[k] != null ? +o[k] : d[0];
    return Math.min(d[2], Math.max(d[1], P.PRIM_FLOAT[k] ? x : Math.round(x)));
  }
  function grid(n, at) {   // an (n+1)^2 vertex grid over a face of the unit cube; at(u, v) -> point
    const v = [], f = [];
    for (let j = 0; j <= n; j++) for (let i = 0; i <= n; i++) v.push(at(i / n, j / n));
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const a = j * (n + 1) + i;
      f.push([a, a + 1, a + n + 2, a + n + 1]);
    }
    return { v, f };
  }
  function merge(parts) {
    const out = { v: [], f: [] };
    for (const p of parts) { const o = out.v.length; out.v.push(...p.v); out.f.push(...p.f.map((f) => f.map((i) => i + o))); }
    return P.weld(out, 1e-6);
  }
  function cubeSides(n) {
    const h = 0.5;   // each side's (u, v) runs so that u x v points outward: counter-clockwise from outside
    return [
      grid(n, (u, v) => [h, -h + v, h - u]), grid(n, (u, v) => [-h, -h + v, -h + u]),
      grid(n, (u, v) => [-h + u, h, h - v]), grid(n, (u, v) => [-h + u, -h, -h + v]),
      grid(n, (u, v) => [-h + u, -h + v, h]), grid(n, (u, v) => [h - u, -h + v, -h]),
    ];
  }
  // Baseline (owner 2026-10-25: "when I press t I should be able to adjust baseline height negative or positive so it
  // goes on the grid. Right now it's .5, I should be able to get 0-1"): the height of the object's BASE above the grid,
  // -1..1. 0 = it sits on the grid (its pivot, the origin, at its base); the old centred cube is baseline -0.5. Only
  // when opts.baseline is given - the kernel's own callers (booleans, tests) still get the unit box centred on the origin.
  P.primitive = (kind, o) => {
    const m = primitiveCentred(kind, o);
    if (!o || o.baseline == null || !isFinite(+o.baseline)) return m;
    let lo = Infinity;
    for (const p of m.v) if (p[1] < lo) lo = p[1];
    const b = Math.max(-1, Math.min(1, +o.baseline)), lift = b - (isFinite(lo) ? lo : 0);   // the lowest point lands on b
    if (lift) m.v = m.v.map((p) => [p[0], p[1] + lift, p[2]]);
    return m;
  };
  const primitiveCentred = (kind, o) => {
    if (!P.PRIMITIVES[kind]) throw new Error("no primitive " + kind);
    if (kind === "cube") return merge(cubeSides(opt(kind, o, "segments")));
    if (kind === "plane") { const n = opt(kind, o, "segments"); return grid(n, (u, v) => [-0.5 + u, 0, 0.5 - v]); }
    if (kind === "quadsphere") {
      const m = merge(cubeSides(opt(kind, o, "segments")));
      m.v = m.v.map((p) => mul(norm(p), 0.5));
      return m;
    }
    if (kind === "sphere") {
      const s = opt(kind, o, "segments"), r = opt(kind, o, "rings"), v = [[0, 0.5, 0]], f = [];
      for (let j = 1; j < r; j++) {
        const t = (Math.PI * j) / r;
        for (let i = 0; i < s; i++) { const p = (2 * Math.PI * i) / s; v.push([0.5 * Math.sin(t) * Math.cos(p), 0.5 * Math.cos(t), -0.5 * Math.sin(t) * Math.sin(p)]); }
      }
      v.push([0, -0.5, 0]);
      const ring = (j, i) => 1 + (j - 1) * s + (i % s), bottom = v.length - 1;
      for (let i = 0; i < s; i++) f.push([0, ring(1, i), ring(1, i + 1)]);
      for (let j = 1; j < r - 1; j++) for (let i = 0; i < s; i++) f.push([ring(j, i), ring(j + 1, i), ring(j + 1, i + 1), ring(j, i + 1)]);
      for (let i = 0; i < s; i++) f.push([ring(r - 1, i), bottom, ring(r - 1, i + 1)]);
      return { v, f };
    }
    if (kind === "cylinder" || kind === "cone") {
      const s = opt(kind, o, "sides"), h = kind === "cone" ? 1 : opt(kind, o, "segments"), v = [], f = [];
      for (let j = 0; j <= h; j++) {
        const y = -0.5 + j / h, rad = kind === "cone" ? 0.5 * (1 - j / h) : 0.5;
        if (kind === "cone" && j === h) { v.push([0, 0.5, 0]); break; }
        for (let i = 0; i < s; i++) { const p = (2 * Math.PI * i) / s; v.push([rad * Math.cos(p), y, -rad * Math.sin(p)]); }
      }
      const at = (j, i) => j * s + (i % s);
      if (kind === "cone") { const tip = v.length - 1; for (let i = 0; i < s; i++) f.push([at(0, i), at(0, i + 1), tip]); }
      else for (let j = 0; j < h; j++) for (let i = 0; i < s; i++) f.push([at(j, i), at(j, i + 1), at(j + 1, i + 1), at(j + 1, i)]);
      f.push([...Array(s).keys()].reverse().map((i) => at(0, i)));                  // bottom cap, facing down
      if (kind === "cylinder") f.push([...Array(s).keys()].map((i) => at(h, i)));    // top cap, facing up
      return { v, f };
    }
    // torus
    const s = opt(kind, o, "segments"), t = opt(kind, o, "sides"), th = opt(kind, o, "thickness"), R = 0.5 - th / 2, v = [], f = [];
    for (let i = 0; i < s; i++) {
      const a = (2 * Math.PI * i) / s;
      for (let j = 0; j < t; j++) {
        const b = (2 * Math.PI * j) / t, rr = R + (th / 2) * Math.cos(b);
        v.push([rr * Math.cos(a), (th / 2) * Math.sin(b), -rr * Math.sin(a)]);
      }
    }
    const at = (i, j) => (i % s) * t + (j % t);
    for (let i = 0; i < s; i++) for (let j = 0; j < t; j++) f.push([at(i, j), at(i + 1, j), at(i + 1, j + 1), at(i, j + 1)]);
    return { v, f };
  };

  // GoBuild weld_operation: merge vertices closer than eps (and drop faces that collapse)
  P.weld = (m, eps) => {
    const key = (p) => p.map((x) => Math.round(x / eps)).join(",");
    const seen = new Map(), map = [], v = [];
    m.v.forEach((p, i) => { const k = key(p); if (!seen.has(k)) { seen.set(k, v.length); v.push(p.slice()); } map[i] = seen.get(k); });
    const f = [];
    for (const face of m.f) {
      const g = [];
      for (const i of face) { const j = map[i]; if (g[g.length - 1] !== j) g.push(j); }
      if (g.length > 1 && g[0] === g[g.length - 1]) g.pop();
      if (g.length >= 3) f.push(g);
    }
    return { v, f };
  };

  // ------------------------------------------------------------------ operations (GoBuild mesh/operations)
  // Extrude: the selected faces move as one region along their averaged normals; each boundary edge a->b of the
  // region gets a side quad [a, b, b', a'] (GoBuild extrude_operation's winding).
  P.extrude = (m0, faces, dist) => {
    const m = clone(m0), sel = new Set(faces.filter((i) => i >= 0 && i < m.f.length));
    if (!sel.size) return m;
    const vn = new Map();
    for (const fi of sel) {
      const n = P.faceNormal(m, m.f[fi]);
      for (const i of m.f[fi]) vn.set(i, add(vn.get(i) || [0, 0, 0], n));
    }
    const edgeUse = new Map();
    for (const fi of sel) {
      const f = m.f[fi];
      for (let k = 0; k < f.length; k++) {
        const a = f[k], b = f[(k + 1) % f.length], key = Math.min(a, b) + "," + Math.max(a, b);
        const e = edgeUse.get(key) || { n: 0, a, b };
        e.n++; edgeUse.set(key, e);
      }
    }
    const top = new Map();
    for (const [i, n] of vn) { top.set(i, m.v.length); m.v.push(add(m.v[i], mul(norm(n), dist))); }
    for (const e of edgeUse.values()) if (e.n === 1) m.f.push([e.a, e.b, top.get(e.b), top.get(e.a)]);
    for (const fi of sel) m.f[fi] = m.f[fi].map((i) => top.get(i));
    return m;
  };
  // Inset (GoBuild inset_operation): each face gets a smaller copy pulled toward its centroid by amount (0..1),
  // joined to the old ring by quads.
  P.inset = (m0, faces, amount) => {
    const m = clone(m0), t = Math.min(0.95, Math.max(0.01, amount));
    for (const fi of new Set(faces)) {
      const f = m.f[fi];
      if (!f) continue;
      const c = P.centroid(m, f), ring = f.map((i) => { m.v.push(add(m.v[i], mul(sub(c, m.v[i]), t))); return m.v.length - 1; });
      for (let k = 0; k < f.length; k++) { const k2 = (k + 1) % f.length; m.f.push([f[k], f[k2], ring[k2], ring[k]]); }
      m.f[fi] = ring;
    }
    return m;
  };
  P.deleteFaces = (m0, faces) => {
    const drop = new Set(faces), m = { v: m0.v.map((p) => p.slice()), f: m0.f.filter((_, i) => !drop.has(i)).map((f) => f.slice()) };
    return P.compact(m);
  };
  P.flip = (m0, faces) => {
    const m = clone(m0), sel = faces && faces.length ? new Set(faces) : null;
    m.f = m.f.map((f, i) => (!sel || sel.has(i) ? f.slice().reverse() : f));
    return m;
  };
  P.compact = (m) => {
    const used = new Map(), v = [];
    const f = m.f.map((face) => face.map((i) => { if (!used.has(i)) { used.set(i, v.length); v.push(m.v[i]); } return used.get(i); }));
    return { v, f };
  };
  // Catmull-Clark: every n-gon becomes n quads; boundaries keep their shape (crease rule)
  P.smooth = (m) => {
    const fp = m.f.map((f) => P.centroid(m, f)), edges = new Map(), vf = m.v.map(() => []), ve = m.v.map(() => []);
    m.f.forEach((f, fi) => {
      for (let k = 0; k < f.length; k++) {
        const a = f[k], b = f[(k + 1) % f.length], key = Math.min(a, b) + "," + Math.max(a, b);
        let e = edges.get(key);
        if (!e) { e = { a, b, faces: [] }; edges.set(key, e); ve[a].push(e); ve[b].push(e); }
        e.faces.push(fi);
        vf[a].push(fi);
      }
    });
    const out = { v: [], f: [] };
    m.v.forEach((p, i) => {
      const bnd = ve[i].filter((e) => e.faces.length === 1);
      if (bnd.length) {
        if (bnd.length !== 2) { out.v.push(p.slice()); return; }
        const q = bnd.map((e) => m.v[e.a === i ? e.b : e.a]);
        out.v.push(add(mul(p, 0.75), mul(add(q[0], q[1]), 0.125)));
        return;
      }
      const n = vf[i].length;
      if (!n) { out.v.push(p.slice()); return; }
      const F = mul(vf[i].reduce((s, fi) => add(s, fp[fi]), [0, 0, 0]), 1 / n);
      const R = mul(ve[i].reduce((s, e) => add(s, mul(add(m.v[e.a], m.v[e.b]), 0.5)), [0, 0, 0]), 1 / ve[i].length);
      out.v.push(mul(add(add(F, mul(R, 2)), mul(p, n - 3)), 1 / n));
    });
    const fBase = out.v.length;
    fp.forEach((p) => out.v.push(p));
    for (const e of edges.values()) {
      e.id = out.v.length;
      const mid = mul(add(m.v[e.a], m.v[e.b]), 0.5);
      out.v.push(e.faces.length === 2 ? mul(add(add(m.v[e.a], m.v[e.b]), add(fp[e.faces[0]], fp[e.faces[1]])), 0.25) : mid);
    }
    m.f.forEach((f, fi) => {
      const eid = (a, b) => edges.get(Math.min(a, b) + "," + Math.max(a, b)).id;
      for (let k = 0; k < f.length; k++) {
        const prev = f[(k + f.length - 1) % f.length], cur = f[k], next = f[(k + 1) % f.length];
        out.f.push([cur, eid(cur, next), fBase + fi, eid(prev, cur)]);
      }
    });
    return out;
  };

  // ------------------------------------------------------------------ for the GPU / the sculpt mesh
  // Fan triangulation; tri2face[t] = the poly face triangle t came from (click a triangle -> select its face).
  P.triangulate = (m) => {
    const pos = new Float32Array(m.v.length * 3), idx = [], tri2face = [];
    m.v.forEach((p, i) => { pos[i * 3] = p[0]; pos[i * 3 + 1] = p[1]; pos[i * 3 + 2] = p[2]; });
    m.f.forEach((f, fi) => { for (let k = 1; k + 1 < f.length; k++) { idx.push(f[0], f[k], f[k + 1]); tri2face.push(fi); } });
    return { pos, idx: Uint32Array.from(idx), tri2face: Int32Array.from(tri2face) };
  };
  P.fromTriangles = (pos, idx) => {
    const v = [];
    for (let i = 0; i < pos.length; i += 3) v.push([pos[i], pos[i + 1], pos[i + 2]]);
    const f = [];
    for (let i = 0; i < idx.length; i += 3) f.push([idx[i], idx[i + 1], idx[i + 2]]);
    return P.compact(P.weld({ v, f }, 1e-6));
  };
  // signed volume: > 0 when the faces point outward (the tests use it to prove every winding is right)
  P.volume = (m) => {
    let s = 0;
    for (const f of m.f) for (let k = 1; k + 1 < f.length; k++) {
      const a = m.v[f[0]], b = m.v[f[k]], c = m.v[f[k + 1]];
      s += a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0]);
    }
    return s / 6;
  };

  // ------------------------------------------------------------------ DynaMesh: voxel remesh -> even quads
  // pos/idx: any triangle soup (the sculpt mesh). res: voxels along the longest side (ZBrush's DynaMesh
  // resolution). Returns a poly mesh of quads; smooth: Laplacian passes that take the voxel steps off.
  P.dynamesh = (pos, idx, res, smooth) => {
    res = Math.max(16, Math.min(256, Math.round(res || 96)));
    let lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < pos.length; i += 3) for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], pos[i + a]); hi[a] = Math.max(hi[a], pos[i + a]); }
    const size = Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) || 1, h = size / res, pad = 2;
    const N = [0, 1, 2].map((a) => Math.ceil((hi[a] - lo[a]) / h) + 1 + 2 * pad);
    const org = [0, 1, 2].map((a) => lo[a] - pad * h);
    const at = (i, j, k) => (k * N[1] + j) * N[0] + i, total = N[0] * N[1] * N[2];
    const votes = new Uint8Array(total), nt = idx.length / 3;
    // three passes: rays along axis z (columns over x,y), along x and along y; each votes "inside" by parity
    for (let ax = 0; ax < 3; ax++) {
      const u = (ax + 1) % 3, w = (ax + 2) % 3, bins = new Map();
      for (let t = 0; t < nt; t++) {
        let umin = Infinity, umax = -Infinity, wmin = Infinity, wmax = -Infinity;
        for (let c = 0; c < 3; c++) {
          const p = idx[t * 3 + c] * 3;
          umin = Math.min(umin, pos[p + u]); umax = Math.max(umax, pos[p + u]);
          wmin = Math.min(wmin, pos[p + w]); wmax = Math.max(wmax, pos[p + w]);
        }
        const i0 = Math.ceil((umin - org[u]) / h), i1 = Math.floor((umax - org[u]) / h);
        const j0 = Math.ceil((wmin - org[w]) / h), j1 = Math.floor((wmax - org[w]) / h);
        for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
          const key = j * N[u] + i;
          let b = bins.get(key); if (!b) { b = []; bins.set(key, b); } b.push(t);
        }
      }
      for (const [key, tris] of bins) {
        const i = key % N[u], j = Math.floor(key / N[u]), pu = org[u] + i * h + 1e-7 * h, pw = org[w] + j * h + 1.3e-7 * h, hits = [];
        for (const t of tris) {
          const a = idx[t * 3] * 3, b = idx[t * 3 + 1] * 3, c = idx[t * 3 + 2] * 3;
          const x0 = pos[a + u], y0 = pos[a + w], x1 = pos[b + u], y1 = pos[b + w], x2 = pos[c + u], y2 = pos[c + w];
          const d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2);
          if (Math.abs(d) < 1e-20) continue;
          const l0 = ((y1 - y2) * (pu - x2) + (x2 - x1) * (pw - y2)) / d, l1 = ((y2 - y0) * (pu - x2) + (x0 - x2) * (pw - y2)) / d, l2 = 1 - l0 - l1;
          if (l0 < 0 || l1 < 0 || l2 < 0) continue;
          hits.push(l0 * pos[a + ax] + l1 * pos[b + ax] + l2 * pos[c + ax]);
        }
        if (hits.length < 2) continue;
        hits.sort((p, q) => p - q);
        for (let q = 0; q + 1 < hits.length; q += 2) {
          const k0 = Math.ceil((hits[q] - org[ax]) / h), k1 = Math.floor((hits[q + 1] - org[ax]) / h);
          for (let k = Math.max(0, k0); k <= Math.min(N[ax] - 1, k1); k++) {
            const c = [0, 0, 0]; c[u] = i; c[w] = j; c[ax] = k;
            votes[at(c[0], c[1], c[2])]++;
          }
        }
      }
    }
    // field: -1 inside, +1 outside, softened once (3x3x3 box) so the surface sits between voxels, not on them
    const raw = new Float32Array(total);
    for (let q = 0; q < total; q++) raw[q] = votes[q] >= 2 ? -1 : 1;
    const fld = new Float32Array(total);
    for (let k = 0; k < N[2]; k++) for (let j = 0; j < N[1]; j++) for (let i = 0; i < N[0]; i++) {
      let s = 0, c = 0;
      for (let dk = -1; dk <= 1; dk++) for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
        const x = i + di, y = j + dj, z = k + dk;
        if (x < 0 || y < 0 || z < 0 || x >= N[0] || y >= N[1] || z >= N[2]) { s += 1; c++; continue; }
        s += raw[at(x, y, z)]; c++;
      }
      fld[at(i, j, k)] = s / c;
    }
    // naive Surface Nets: one vertex per cell the surface crosses, one quad per grid edge with a sign change
    const cellV = new Int32Array(total).fill(-1), v = [];
    const corner = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
    const cedges = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];
    for (let k = 0; k < N[2] - 1; k++) for (let j = 0; j < N[1] - 1; j++) for (let i = 0; i < N[0] - 1; i++) {
      const val = corner.map((c) => fld[at(i + c[0], j + c[1], k + c[2])]);
      let s = [0, 0, 0], n = 0;
      for (const [a, b] of cedges) {
        if ((val[a] < 0) === (val[b] < 0)) continue;
        const t = val[a] / (val[a] - val[b]);
        s = add(s, add(corner[a], mul(sub(corner[b], corner[a]), t))); n++;
      }
      if (!n) continue;
      s = mul(s, 1 / n);
      cellV[at(i, j, k)] = v.length;
      v.push([org[0] + (i + s[0]) * h, org[1] + (j + s[1]) * h, org[2] + (k + s[2]) * h]);
    }
    const f = [];
    for (let k = 1; k < N[2] - 1; k++) for (let j = 1; j < N[1] - 1; j++) for (let i = 1; i < N[0] - 1; i++) {
      const here = fld[at(i, j, k)] < 0;
      for (let ax = 0; ax < 3; ax++) {
        const d = [0, 0, 0]; d[ax] = 1;
        if (i + d[0] >= N[0] || j + d[1] >= N[1] || k + d[2] >= N[2]) continue;
        const there = fld[at(i + d[0], j + d[1], k + d[2])] < 0;
        if (here === there) continue;
        const u = (ax + 1) % 3, w = (ax + 2) % 3;
        const cell = (du, dw) => { const c = [i, j, k]; c[u] -= du; c[w] -= dw; return cellV[at(c[0], c[1], c[2])]; };
        const q = [cell(1, 1), cell(0, 1), cell(0, 0), cell(1, 0)];
        if (q.some((x) => x < 0)) continue;
        f.push(here ? q : q.slice().reverse());   // inside -> outside along +axis: the quad faces +axis
      }
    }
    let m = { v, f };
    for (let pass = 0; pass < (smooth == null ? 2 : smooth); pass++) {   // Laplacian on the quad net
      const acc = m.v.map(() => [0, 0, 0]), cnt = new Uint32Array(m.v.length);
      for (const face of m.f) for (let q = 0; q < face.length; q++) {
        const a = face[q], b = face[(q + 1) % face.length];
        acc[a] = add(acc[a], m.v[b]); acc[b] = add(acc[b], m.v[a]); cnt[a]++; cnt[b]++;
      }
      m.v = m.v.map((p, q) => (cnt[q] ? add(mul(p, 0.5), mul(acc[q], 0.5 / cnt[q])) : p));
    }
    m = P.compact(m);
    return m;
  };

  // ---------------------------------------------------------------- edges (GoBuildMesh edge table)
  // GoBuild's edge tools (bevel, loop cut, knife) address EDGES; LOKI's mesh is {v,f}, so this
  // rebuilds the edge table first: an edge is the sorted pair of its endpoints plus the faces that use
  // it. alignRing orients a new ring (a bevel strip, a cap) to face outward like its neighbours.
  const ekey = (a, b) => Math.min(a, b) + "," + Math.max(a, b);
  P.edges = (m) => {
    const map = new Map(), out = [];
    m.f.forEach((face, fi) => {
      for (let k = 0; k < face.length; k++) {
        const a = face[k], b = face[(k + 1) % face.length], key = ekey(a, b);
        let e = map.get(key);
        if (!e) { e = { a: Math.min(a, b), b: Math.max(a, b), faces: [] }; map.set(key, e); out.push(e); }
        e.faces.push(fi);
      }
    });
    return out;
  };
  P.alignRing = (m, ring, outward) => {   // make the ring face outward; true when it flipped
    let n = [0, 0, 0];
    for (let i = 0; i < ring.length; i++) {
      const a = m.v[ring[i]], b = m.v[ring[(i + 1) % ring.length]];
      n = add(n, [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])]);
    }
    if (n[0] * outward[0] + n[1] * outward[1] + n[2] * outward[2] < 0) { ring.reverse(); return true; }
    return false;
  };
  // ---------------------------------------------------------------- edit-mode selection (Blender's editmesh model)
  // A selection is three sets - vertex ids, edge ids (indices into topo.edges), face ids - kept consistent the way
  // Blender flushes them (editmesh_select.cc): a face is selected when all its vertices / edges are, an edge when
  // both its ends are. The walkers follow bmesh_walkers_impl.cc: an edge LOOP crosses a valence-4 vertex to the
  // edge that shares no face with the one it came from (and follows the border along an open edge); an edge RING
  // and a FACE loop step across a quad to its opposite edge. All pure, so tests/test_forge_poly.py runs them in node.
  // topology depends only on the faces and the vertex count: a move / tweak keeps both, so the last answer for the same
  // face list is reused (it took ~0.2 s of every edit on 70k faces). A checksum over every face's vertex ids guards
  // against a face list changed in place; callers treat the answer as read-only.
  const topoCache = new WeakMap();
  const faceSig = (m) => { let h = m.v.length | 0; for (const f of m.f) { h = (h * 31 + f.length) | 0; for (let k = 0; k < f.length; k++) h = (h * 31 + f[k]) | 0; } return h; };
  P.topology = (m) => {
    const hit = m && m.f && topoCache.get(m.f);
    if (hit && hit.nv === m.v.length && hit.nf === m.f.length) {
      const sig = faceSig(m);
      if (sig === hit.sig) return hit.T;
      topoCache.delete(m.f);
    }
    const T = P.topologyBuild(m);
    if (m && m.f) topoCache.set(m.f, { T, nv: m.v.length, nf: m.f.length, sig: faceSig(m) });
    return T;
  };
  P.topologyBuild = (m) => {
    const edges = [], index = new Map(), vertEdges = m.v.map(() => []), vertFaces = m.v.map(() => []), faceEdges = [];
    m.f.forEach((face, fi) => {
      const fe = [];
      for (let k = 0; k < face.length; k++) {
        const a = face[k], b = face[(k + 1) % face.length], key = ekey(a, b);
        let ei = index.get(key);
        if (ei === undefined) {
          ei = edges.length; index.set(key, ei);
          edges.push({ a: Math.min(a, b), b: Math.max(a, b), faces: [] });
          vertEdges[a].push(ei); vertEdges[b].push(ei);
        }
        edges[ei].faces.push(fi);
        fe.push(ei);
        vertFaces[a].push(fi);
      }
      faceEdges.push(fe);
    });
    return { edges, index, vertEdges, vertFaces, faceEdges, edge: (a, b) => index.get(ekey(a, b)) };
  };
  P.edgeKey = ekey;

  // flush: make the other two sets follow the one that was edited (mode = the select mode it was edited in)
  P.flushSelection = (m, T, sel, mode) => {
    const v = new Set(sel.v), e = new Set(sel.e), f = new Set(sel.f);
    if (mode === "vert") {
      e.clear(); f.clear();
      T.edges.forEach((ed, i) => { if (v.has(ed.a) && v.has(ed.b)) e.add(i); });
      m.f.forEach((face, i) => { if (face.every((x) => v.has(x))) f.add(i); });
    } else if (mode === "edge") {
      v.clear(); f.clear();
      for (const i of e) { const ed = T.edges[i]; if (ed) { v.add(ed.a); v.add(ed.b); } }
      T.faceEdges.forEach((fe, i) => { if (fe.every((x) => e.has(x))) f.add(i); });
    } else {
      v.clear(); e.clear();
      for (const i of f) { const face = m.f[i]; if (!face) continue; for (const x of face) v.add(x); for (const x of T.faceEdges[i]) e.add(x); }
    }
    return { v, e, f };
  };

  // the next edge of a loop, standing on vertex `at` having come along edge `ei` (or -1: the loop ends)
  function loopStep(m, T, ei, at) {
    const ed = T.edges[ei], around = T.vertEdges[at];
    if (ed.faces.length === 1) {                        // a border edge: follow the border
      const nxt = around.filter((x) => x !== ei && T.edges[x].faces.length === 1);
      return nxt.length === 1 ? nxt[0] : -1;
    }
    if (ed.faces.length !== 2 || around.length !== 4) return -1;   // a pole, a corner or non-manifold: stop
    const mine = new Set(ed.faces);
    const nxt = around.filter((x) => x !== ei && !T.edges[x].faces.some((f) => mine.has(f)));
    return nxt.length === 1 ? nxt[0] : -1;
  }
  P.edgeLoop = (m, T, ei) => {
    T = T || P.topology(m);
    if (!T.edges[ei]) return [];
    const out = new Set([ei]);
    for (const start of [T.edges[ei].a, T.edges[ei].b]) {
      let cur = ei, at = start === T.edges[ei].a ? T.edges[ei].b : T.edges[ei].a;
      // walk away from `start`: stand on the far end and step on
      for (let guard = 0; guard < T.edges.length; guard++) {
        const nxt = loopStep(m, T, cur, at);
        if (nxt < 0 || out.has(nxt)) break;
        out.add(nxt);
        const e2 = T.edges[nxt];
        at = e2.a === at ? e2.b : e2.a;
        cur = nxt;
      }
    }
    return [...out];
  };
  function oppositeEdge(m, T, fi, ei) {              // across a quad: the edge that shares no vertex
    const face = m.f[fi];
    if (!face || face.length !== 4) return -1;
    const k = T.faceEdges[fi].indexOf(ei);
    return k < 0 ? -1 : T.faceEdges[fi][(k + 2) % 4];
  }
  // edge ring + the faces it crosses (a face loop): returns { edges, faces }
  P.edgeRing = (m, T, ei) => {
    T = T || P.topology(m);
    if (!T.edges[ei]) return { edges: [], faces: [] };
    const edges = new Set([ei]), faces = new Set();
    for (const first of T.edges[ei].faces) {
      let cur = ei, fi = first;
      for (let guard = 0; guard < m.f.length + 1; guard++) {
        if (faces.has(fi) || m.f[fi].length !== 4) break;
        faces.add(fi);
        const opp = oppositeEdge(m, T, fi, cur);
        if (opp < 0) break;
        edges.add(opp);
        const next = T.edges[opp].faces.find((x) => x !== fi);
        if (next === undefined) break;
        cur = opp; fi = next;
      }
    }
    return { edges: [...edges], faces: [...faces] };
  };
  // Split the quad faces crossed by an edge ring. `t` is measured from the lower-index
  // endpoint of every edge, and is clamped away from degenerate zero-width faces.
  P.loopCut = (m0, ei, t) => {
    const m = clone(m0), T = P.topology(m), ring = P.edgeRing(m, T, ei);
    if (ring.faces.length === 0) return m;
    const amount = Math.max(0.01, Math.min(0.99, Number.isFinite(t) ? t : 0.5));
    const cuts = new Map();
    for (const edgeId of ring.edges) {
      const edge = T.edges[edgeId];
      const a = m.v[edge.a], b = m.v[edge.b];
      cuts.set(edgeId, m.v.push(add(mul(a, 1 - amount), mul(b, amount))) - 1);
    }
    const replacements = new Map();
    for (const faceId of ring.faces) {
      const face = m.f[faceId], edgeIds = T.faceEdges[faceId];
      if (face.length !== 4) continue;
      const cutSides = edgeIds.map((id, i) => cuts.has(id) ? i : -1).filter((i) => i >= 0);
      if (cutSides.length !== 2 || (cutSides[0] + 2) % 4 !== cutSides[1]) continue;
      const i = cutSides[0], j = cutSides[1];
      const cutA = cuts.get(edgeIds[i]), cutB = cuts.get(edgeIds[j]);
      const first = [cutA];
      for (let k = (i + 1) % 4; k !== (j + 1) % 4; k = (k + 1) % 4) first.push(face[k]);
      first.push(cutB);
      const second = [cutB];
      for (let k = (j + 1) % 4; k !== (i + 1) % 4; k = (k + 1) % 4) second.push(face[k]);
      second.push(cutA);
      replacements.set(faceId, [first, second]);
    }
    for (const [faceId, pieces] of [...replacements].sort((a, b) => b[0] - a[0])) m.f.splice(faceId, 1, ...pieces);
    return m;
  };
  // ---------------------------------------------------------------- Bevel / Poke / Chamfer (the pro modelling tools)
  // Bevel an edge: the two faces beside it pull their shared edge inward by `width`, the strip between them
  // becomes a face, and each end vertex gets a corner face that closes it (turn the corner the pro way). The
  // windings are fixed once at the end by a BFS over shared edges - that is the part the earlier port got wrong
  // at a vertex where three beveled edges meet (it left the mesh open).
  const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  function orientFaces(faces) {             // make neighbours traverse their shared edge in opposite directions
    const edges = new Map();
    faces.forEach((f, fi) => {
      for (let k = 0; k < f.length; k++) {
        const a = f[k], b = f[(k + 1) % f.length], key = a < b ? a + "|" + b : b + "|" + a;
        let list = edges.get(key); if (!list) { list = []; edges.set(key, list); }
        list.push({ fi, forward: a <= b });
      }
    });
    const state = new Int8Array(faces.length).fill(-1);
    for (let seed = 0; seed < faces.length; seed++) {
      if (state[seed] !== -1) continue;
      state[seed] = 0;
      const stack = [seed];
      while (stack.length) {
        const cur = stack.pop();
        const f = state[cur] === 1 ? faces[cur].slice().reverse() : faces[cur];
        for (let k = 0; k < f.length; k++) {
          const a = f[k], b = f[(k + 1) % f.length], key = a < b ? a + "|" + b : b + "|" + a;
          for (const e of edges.get(key)) {
            if (e.fi === cur || state[e.fi] !== -1) continue;
            state[e.fi] = ((a <= b) === e.forward) ? 1 : 0;
            stack.push(e.fi);
          }
        }
      }
    }
    return faces.map((f, i) => state[i] === 1 ? f.slice().reverse() : f);
  }
  // the vertices around `v`, in the order of the edges that meet there (walks the face cycle)
  function edgesAroundVertex(m, T, v) {
    const at = [...new Set(T.vertEdges[v])];
    const link = new Map(), faceAt = new Map();
    for (const ei of at) link.set(ei, []);
    for (const fi of new Set(T.vertFaces[v])) {
      const f = m.f[fi], arr = [];
      for (let k = 0; k < f.length; k++) { const a = f[k], b = f[(k + 1) % f.length]; if (a === v || b === v) arr.push(T.edge(a, b)); }
      if (arr.length !== 2) continue;
      link.get(arr[0]).push(arr[1]); link.get(arr[1]).push(arr[0]);
      faceAt.set(Math.min(arr[0], arr[1]) + "," + Math.max(arr[0], arr[1]), fi);
    }
    const order = [], seen = new Set(); let cur = at[0], prev = null;
    for (let g = 0; g < at.length + 2; g++) { if (cur == null || seen.has(cur)) break; order.push(cur); seen.add(cur); const nxt = link.get(cur).find((x) => x !== prev) ?? link.get(cur)[0]; prev = cur; cur = nxt; }
    return order.length === at.length ? { order, faceAt } : null;
  }
  // Bevel: selected EDGES get a flat strip of `width`; interior edges only (a border edge has no second face).
  P.bevel = (m0, edges, width) => {
    const m = clone(m0), T = P.topology(m), w = +width;
    const sel = new Set((edges || []).filter((i) => i >= 0 && i < T.edges.length && T.edges[i].faces.length === 2));
    if (!sel.size || !(w > 0)) return m;
    const fn = m.f.map((f) => P.faceNormal(m, f));
    const off = new Map(), okey = (ei, fi, vid) => ei + "|" + fi + "|" + vid;
    for (const ei of sel) {
      const e = T.edges[ei], a = m.v[e.a], b = m.v[e.b], dir = norm(sub(b, a));
      for (const fi of e.faces) {
        const f = m.f[fi], n = fn[fi], mid = mul(add(a, b), 0.5);
        let perp = norm(cross(dir, n));
        if (dot3(perp, sub(P.centroid(m, f), mid)) < 0) perp = mul(perp, -1);
        const wid = Math.min(w, 0.49 * len(sub(b, a)));
        off.set(okey(ei, fi, e.a), add(a, mul(perp, wid)));
        off.set(okey(ei, fi, e.b), add(b, mul(perp, wid)));
      }
    }
    const pos = new Map();
    const tok = (ei, fi, vid) => { if (sel.has(ei)) { const k = "p:" + ei + "|" + fi + "|" + vid; pos.set(k, off.get(okey(ei, fi, vid))); return k; } const k = "o:" + vid; pos.set(k, m.v[vid]); return k; };
    let faces = [];
    m.f.forEach((f, fi) => {                       // each face pulls its beveled edges inward
      const n = f.length, seq = [];
      for (let k = 0; k < n; k++) { const a = f[k], b = f[(k + 1) % n]; seq.push(tok(T.edge(a, b), fi, a), tok(T.edge(a, b), fi, b)); }
      const out = [];
      for (const t of seq) if (out.length === 0 || out[out.length - 1] !== t) out.push(t);
      if (out.length > 1 && out[0] === out[out.length - 1]) out.pop();
      if (out.length >= 3) faces.push(out);
    });
    for (const ei of sel) {                        // the strip itself
      const e = T.edges[ei], f1 = e.faces[0], f2 = e.faces[1];
      faces.push(["p:" + ei + "|" + f1 + "|" + e.a, "p:" + ei + "|" + f1 + "|" + e.b, "p:" + ei + "|" + f2 + "|" + e.b, "p:" + ei + "|" + f2 + "|" + e.a]);
    }
    const touched = new Set();
    for (const ei of sel) { touched.add(T.edges[ei].a); touched.add(T.edges[ei].b); }
    for (const v of touched) {                     // the corner face that closes each end vertex
      const ring = edgesAroundVertex(m, T, v); if (!ring) continue;
      const { order, faceAt } = ring, seq = [];
      for (let i = 0; i < order.length; i++) {
        const em = order[(i - 1 + order.length) % order.length], ep = order[i];
        const fi = faceAt.get(Math.min(em, ep) + "," + Math.max(em, ep));
        if (fi == null) continue;
        seq.push(sel.has(em) ? tok(em, fi, v) : "o:" + v, sel.has(ep) ? tok(ep, fi, v) : "o:" + v);
      }
      const out = [];
      for (const t of seq) if (out.length === 0 || out[out.length - 1] !== t) out.push(t);
      if (out.length > 1 && out[0] === out[out.length - 1]) out.pop();
      if (out.length >= 3) faces.push(out);
    }
    faces = orientFaces(faces);
    const v = [], f = [], idOf = new Map();
    for (const face of faces) {
      const ids = face.map((t) => { if (!idOf.has(t)) { idOf.set(t, v.length); v.push(pos.get(t).slice()); } return idOf.get(t); });
      if (ids.length >= 3) f.push(ids);
    }
    return { v, f };
  };
  // Poke Face: a centre vertex in every picked face, fanned to its corners (polyPoke)
  P.poke = (m0, faces) => {
    const m = clone(m0), sel = [...new Set(faces || [])].filter((i) => i >= 0 && i < m.f.length);
    const add2 = [];
    for (const fi of sel) {
      const face = m.f[fi], c = P.centroid(m, face), ci = m.v.push(c) - 1;
      for (let k = 0; k < face.length; k++) add2.push([face[k], face[(k + 1) % face.length], ci]);
    }
    for (const fi of sel.slice().sort((a, b) => b - a)) m.f.splice(fi, 1);
    m.f.push(...add2);
    return m;
  };
  // Chamfer Vertex: every picked vertex is cut off at `width` along each edge that meets it; the cuts close as a
  // face in the middle (polyChamfer for points in the pro tools)
  P.chamferVertex = (m0, verts, width) => {
    const m = clone(m0), T = P.topology(m), w = +width;
    const sel = new Set((verts || []).filter((i) => i >= 0 && i < m.v.length));
    if (!sel.size || !(w > 0)) return m;
    const vn = m.v.map(() => [0, 0, 0]);
    m.f.forEach((f) => { const n = P.faceNormal(m, f); for (const i of f) vn[i] = add(vn[i], n); });
    const pt = new Map(), pkey = (v, u) => v + "|" + u;
    for (const v of sel) for (const ei of T.vertEdges[v]) {
      const e = T.edges[ei], u = e.a === v ? e.b : e.a, d = sub(m.v[u], m.v[v]);
      pt.set(pkey(v, u), add(m.v[v], mul(norm(d), Math.min(w, 0.49 * len(d)))));
    }
    const v = [], idOf = new Map();
    const idP = (k) => { if (!idOf.has(k)) { idOf.set(k, v.length); v.push(pt.get(k).slice()); } return idOf.get(k); };
    const idO = (vid) => { const k = "o" + vid; if (!idOf.has(k)) { idOf.set(k, v.length); v.push(m.v[vid].slice()); } return idOf.get(k); };
    const f = [];
    for (const face of m.f) {
      const ids = [];
      for (let k = 0; k < face.length; k++) {
        const x = face[k];
        if (!sel.has(x)) { ids.push(idO(x)); continue; }
        ids.push(idP(pkey(x, face[(k - 1 + face.length) % face.length])), idP(pkey(x, face[(k + 1) % face.length])));
      }
      const ded = [];
      for (const x of ids) if (ded.length === 0 || ded[ded.length - 1] !== x) ded.push(x);
      if (ded.length > 2 && ded[0] === ded[ded.length - 1]) ded.pop();
      if (ded.length >= 3) f.push(ded);
    }
    for (const v0 of sel) {
      const ring = edgesAroundVertex(m, T, v0); if (!ring) continue;
      const ids = ring.order.map((ei) => { const e = T.edges[ei]; return idP(pkey(v0, e.a === v0 ? e.b : e.a)); });
      let N = [0, 0, 0];
      for (let i = 0; i < ids.length; i++) { const A = v[ids[i]], B = v[ids[(i + 1) % ids.length]]; N = add(N, [(A[1] - B[1]) * (A[2] + B[2]), (A[2] - B[2]) * (A[0] + B[0]), (A[0] - B[0]) * (A[1] + B[1])]); }
      if (dot3(N, vn[v0]) < 0) ids.reverse();
      if (ids.length >= 3) f.push(ids);
    }
    return { v, f };
  };

  // everything connected to the given vertices through faces (Blender's Select Linked)
  P.linked = (m, T, verts) => {
    T = T || P.topology(m);
    const seen = new Set(verts), stack = [...verts];
    while (stack.length) {
      const x = stack.pop();
      for (const fi of T.vertFaces[x] || []) for (const y of m.f[fi]) if (!seen.has(y)) { seen.add(y); stack.push(y); }
    }
    return seen;
  };
  // Select More / Less (Ctrl + / Ctrl -): one ring of faces around the selection out, or in
  P.grow = (m, T, verts) => {
    T = T || P.topology(m);
    const out = new Set(verts);
    for (const x of verts) for (const fi of T.vertFaces[x] || []) for (const y of m.f[fi]) out.add(y);
    return out;
  };
  P.shrink = (m, T, verts) => {
    T = T || P.topology(m);
    const vs = new Set(verts), out = new Set();
    for (const x of vs) {
      const fs = T.vertFaces[x] || [];
      if (fs.length && fs.every((fi) => m.f[fi].every((y) => vs.has(y)))) out.add(x);
    }
    return out;
  };
  // delete in vertex / edge mode (Blender): the faces that use any selected vertex / edge go
  P.deleteVerts = (m, verts) => {
    const s = new Set(verts);
    return P.deleteFaces(m, m.f.map((f, i) => (f.some((x) => s.has(x)) ? i : -1)).filter((i) => i >= 0));
  };
  P.deleteEdges = (m, T, edges) => {
    T = T || P.topology(m);
    const drop = new Set();
    for (const ei of edges) for (const fi of (T.edges[ei] || { faces: [] }).faces) drop.add(fi);
    return P.deleteFaces(m, [...drop]);
  };

  // ---------------------------------------------------------------- transform (the move / rotate / scale tools)
  // Proportional editing, as Blender's calculatePropRatio (transform_mode.cc): every unselected vertex within
  // `radius` of the nearest selected one moves by factor(d), d = (radius - dist) / radius.
  P.FALLOFF = {
    smooth: (d) => Math.min(1, 3 * d * d - 2 * d * d * d), sphere: (d) => Math.sqrt(Math.max(0, 2 * d - d * d)),
    root: (d) => Math.sqrt(d), sharp: (d) => d * d, linear: (d) => d, constant: () => 1, inverse: (d) => d * (2 - d),
  };
  P.weights = (m, verts, radius, falloff) => {
    const w = new Map(), sel = [...new Set(verts)];
    for (const i of sel) w.set(i, 1);
    if (!(radius > 0) || !sel.length) return w;
    const fn = P.FALLOFF[falloff] || P.FALLOFF.smooth, r2 = radius * radius;
    // a grid over the selected vertices (cells a quarter of the radius): a vertex outside the selection's box or
    // with no selected vertex in its coarse neighbourhood is skipped at once; the rest search outward shell by
    // shell and stop as soon as no nearer selected vertex can be left - fast even with thousands selected
    const S = 4, cell = radius / S, hash = (a, b, c) => ((a * 73856093) ^ (b * 19349663) ^ (c * 83492791)) | 0;
    const fine = new Map(), coarse = new Set(), lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (const i of sel) {
      const p = m.v[i], a = Math.floor(p[0] / cell), b = Math.floor(p[1] / cell), c = Math.floor(p[2] / cell), k = hash(a, b, c);
      if (!fine.has(k)) fine.set(k, []); fine.get(k).push(i);
      coarse.add(hash(Math.floor(a / S), Math.floor(b / S), Math.floor(c / S)));
      for (let d = 0; d < 3; d++) { lo[d] = Math.min(lo[d], p[d] - radius); hi[d] = Math.max(hi[d], p[d] + radius); }
    }
    m.v.forEach((p, i) => {
      if (w.has(i) || p[0] < lo[0] || p[1] < lo[1] || p[2] < lo[2] || p[0] > hi[0] || p[1] > hi[1] || p[2] > hi[2]) return;
      const c = [Math.floor(p[0] / cell), Math.floor(p[1] / cell), Math.floor(p[2] / cell)], C = c.map((x) => Math.floor(x / S));
      let near = false;
      for (let dx = -1; dx <= 1 && !near; dx++) for (let dy = -1; dy <= 1 && !near; dy++) for (let dz = -1; dz <= 1 && !near; dz++)
        if (coarse.has(hash(C[0] + dx, C[1] + dy, C[2] + dz))) near = true;
      if (!near) return;
      let best = Infinity;
      for (let sh = 0; sh <= S + 1; sh++) {
        if (best < Infinity && (sh - 1) * cell > Math.sqrt(best)) break;
        for (let dx = -sh; dx <= sh; dx++) for (let dy = -sh; dy <= sh; dy++) for (let dz = -sh; dz <= sh; dz++) {
          if (Math.max(Math.abs(dx), Math.abs(dy), Math.abs(dz)) !== sh) continue;   // this shell only
          for (const j of fine.get(hash(c[0] + dx, c[1] + dy, c[2] + dz)) || []) {
            const q = m.v[j], d2 = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2;
            if (d2 < best) best = d2;
          }
        }
      }
      if (best < r2) { const f = fn((radius - Math.sqrt(best)) / radius); if (f > 0) w.set(i, f); }
    });
    return w;
  };
  // Maya's soft selection Falloff Mode "Surface" (Blockbench proportional edit "connected", Wings' magnet over the
  // mesh): the distance is measured ALONG the mesh's edges from the picked vertices (multi-source Dijkstra), so the
  // lower lip moves without the upper one, a finger without the next finger. Same falloff curves as P.weights.
  P.weightsSurface = (m, verts, radius, falloff) => {
    const w = new Map(), sel = [...new Set(verts)].filter((i) => m.v[i]);
    for (const i of sel) w.set(i, 1);
    if (!(radius > 0) || !sel.length) return w;
    const fn = P.FALLOFF[falloff] || P.FALLOFF.smooth;
    const nb = m.v.map(() => []);
    for (const f of m.f) for (let k = 0; k < f.length; k++) {
      const a = f[k], b = f[(k + 1) % f.length];
      if (!nb[a].includes(b)) { nb[a].push(b); nb[b].push(a); }
    }
    const dist = new Float64Array(m.v.length).fill(Infinity);
    // a binary heap of [distance, vertex]
    const heap = [];
    const push = (d, i) => { heap.push([d, i]); let c = heap.length - 1; while (c) { const p = (c - 1) >> 1; if (heap[p][0] <= heap[c][0]) break; [heap[p], heap[c]] = [heap[c], heap[p]]; c = p; } };
    const pop = () => { const top = heap[0], last = heap.pop(); if (heap.length) { heap[0] = last; let c = 0; for (;;) { const l = 2 * c + 1, r = l + 1; let s = c; if (l < heap.length && heap[l][0] < heap[s][0]) s = l; if (r < heap.length && heap[r][0] < heap[s][0]) s = r; if (s === c) break; [heap[s], heap[c]] = [heap[c], heap[s]]; c = s; } } return top; };
    for (const i of sel) { dist[i] = 0; push(0, i); }
    while (heap.length) {
      const [d, i] = pop();
      if (d > dist[i] || d > radius) continue;
      const p = m.v[i];
      for (const j of nb[i]) {
        const q = m.v[j], nd = d + Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
        if (nd < dist[j] && nd < radius) { dist[j] = nd; push(nd, j); }
      }
    }
    dist.forEach((d, i) => { if (!w.has(i) && d < radius) { const f = fn((radius - d) / radius); if (f > 0) w.set(i, f); } });
    return w;
  };
  // p' = p + w (M p - p): M is a 4x4 column-major matrix (three.js' Matrix4.elements); weights from P.weights
  P.applyMatrix = (m0, weights, M, into) => {
    const m = into || clone(m0);
    for (const [i, w] of weights) {
      const p = m0.v[i], x = p[0], y = p[1], z = p[2];
      const nx = M[0] * x + M[4] * y + M[8] * z + M[12], ny = M[1] * x + M[5] * y + M[9] * z + M[13], nz = M[2] * x + M[6] * y + M[10] * z + M[14];
      m.v[i] = [x + (nx - x) * w, y + (ny - y) * w, z + (nz - z) * w];
    }
    return m;
  };
  P.median = (m, verts) => {
    let s = [0, 0, 0], n = 0;
    for (const i of verts) { s = add(s, m.v[i]); n++; }
    return n ? mul(s, 1 / n) : [0, 0, 0];
  };

  // ------------------------------------------------------------------ whole-mesh tools (Mesh > Combine / Separate / Mirror)
  // a 4x4 matrix in three.js' column-major `elements` order applied to every vertex
  P.transform = (m0, e) => {
    const m = clone(m0);
    m.v = m.v.map(([x, y, z]) => {
      const w = e[3] * x + e[7] * y + e[11] * z + e[15] || 1;
      return [(e[0] * x + e[4] * y + e[8] * z + e[12]) / w, (e[1] * x + e[5] * y + e[9] * z + e[13]) / w, (e[2] * x + e[6] * y + e[10] * z + e[14]) / w];
    });
    return m;
  };
  // Combine: several meshes as one (their vertices and faces side by side, nothing welded)
  P.combine = (list) => {
    const v = [], f = [];
    for (const m of list) {
      const base = v.length;
      for (const p of m.v) v.push(p.slice());
      for (const face of m.f) f.push(face.map((i) => i + base));
    }
    return { v, f };
  };
  // Separate: the pieces that share no vertex, each its own compact mesh (largest first)
  P.shells = (m) => {
    const parent = m.v.map((_, i) => i);
    const find = (i) => { while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i]; } return i; };
    for (const face of m.f) for (let k = 1; k < face.length; k++) { const a = find(face[0]), b = find(face[k]); if (a !== b) parent[a] = b; }
    const groups = new Map();
    m.f.forEach((face, fi) => { const r = find(face[0]); if (!groups.has(r)) groups.set(r, []); groups.get(r).push(fi); });
    return [...groups.values()].map((fs) => P.compact({ v: m.v, f: fs.map((fi) => m.f[fi]) })).sort((a, b) => b.f.length - a.f.length);
  };
  // Mirror across the plane through `point` with normal `normal`: the mirrored copy is added (winding reversed so
  // it faces out) and the vertices that land on each other on the plane are merged
  P.mirror = (m0, point, normal, eps) => {
    const n = normal.slice(), len = Math.hypot(n[0], n[1], n[2]) || 1;
    n[0] /= len; n[1] /= len; n[2] /= len;
    const refl = (p) => { const d = 2 * ((p[0] - point[0]) * n[0] + (p[1] - point[1]) * n[1] + (p[2] - point[2]) * n[2]); return [p[0] - d * n[0], p[1] - d * n[1], p[2] - d * n[2]]; };
    const copy = { v: m0.v.map(refl), f: m0.f.map((f) => f.slice().reverse()) };
    const tol = eps || 1e-4;
    // snap what is on the plane exactly onto it, so the weld finds the pairs
    const snap = (p) => { const d = (p[0] - point[0]) * n[0] + (p[1] - point[1]) * n[1] + (p[2] - point[2]) * n[2]; return Math.abs(d) < tol ? [p[0] - d * n[0], p[1] - d * n[1], p[2] - d * n[2]] : p; };
    const both = P.combine([{ v: m0.v.map(snap), f: m0.f }, { v: copy.v.map(snap), f: copy.f }]);
    // drop faces lying in the plane (they would be doubled, back to back)
    const flat = (face) => face.every((i) => Math.abs((both.v[i][0] - point[0]) * n[0] + (both.v[i][1] - point[1]) * n[1] + (both.v[i][2] - point[2]) * n[2]) < tol);
    const half = m0.f.length;
    both.f = both.f.filter((face, i) => !(i >= half && flat(face)));
    return P.compact(P.weld(both, tol / 4));
  };

  // Merge: the given vertices that lie within `dist` of each other become one (at their average); faces that
  // collapse go. Merge to Center: all the given vertices become one, at their middle.
  P.mergeVerts = (m0, verts, dist, toCenter) => {
    const m = clone(m0), list = [...new Set(verts)].filter((i) => i >= 0 && i < m.v.length);
    if (list.length < 2) return m;
    const map = m.v.map((_, i) => i);
    const groups = [];
    if (toCenter) groups.push(list);
    else {
      const left = new Set(list);
      for (const i of list) {
        if (!left.has(i)) continue;
        const g = [i]; left.delete(i);
        for (let k = 0; k < g.length; k++) for (const j of [...left]) {
          const a = m.v[g[k]], b = m.v[j];
          if (Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) <= dist) { g.push(j); left.delete(j); }
        }
        if (g.length > 1) groups.push(g);
      }
    }
    for (const g of groups) {
      const c = mul(g.reduce((s, i) => add(s, m.v[i]), [0, 0, 0]), 1 / g.length);
      m.v[g[0]] = c;
      for (const i of g.slice(1)) map[i] = g[0];
    }
    const f = [];
    for (const face of m.f) {
      const out = [];
      for (const i of face) { const j = map[i]; if (out[out.length - 1] !== j) out.push(j); }
      if (out.length > 1 && out[0] === out[out.length - 1]) out.pop();
      if (new Set(out).size >= 3 && out.length >= 3) f.push(out);
    }
    return P.compact({ v: m.v, f });
  };
  // Fill Hole: every open border (a loop of edges with one face) - or only the borders touching `verts` - gets a
  // face, wound to match its neighbours
  P.fillHoles = (m0, verts) => {
    const m = clone(m0), T = P.topology(m);
    const next = new Map();                           // border edge a->b, in the direction its face does NOT use
    for (const e of T.edges) {
      if (e.faces.length !== 1) continue;
      const face = m.f[e.faces[0]], k = face.indexOf(e.a);
      const forward = face[(k + 1) % face.length] === e.b;    // the face goes a->b, so the hole goes b->a
      if (forward) next.set(e.b, e.a); else next.set(e.a, e.b);
    }
    const want = verts && verts.length ? new Set(verts) : null, done = new Set();
    let added = 0;
    for (const start of next.keys()) {
      if (done.has(start)) continue;
      const loop = [];
      let x = start, guard = 0;
      while (x !== undefined && !done.has(x) && guard++ < 100000) { loop.push(x); done.add(x); x = next.get(x); }
      if (x !== start || loop.length < 3) continue;
      if (want && !loop.some((i) => want.has(i))) continue;
      m.f.push(loop); added++;
    }
    m.filled = added;
    return m;
  };

  root.ForgePoly = P;
  if (typeof module !== "undefined" && module.exports) module.exports = P;
})(typeof window !== "undefined" ? window : globalThis);
