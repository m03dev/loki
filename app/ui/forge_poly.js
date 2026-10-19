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
  const clone = (m) => ({ v: m.v.map((p) => p.slice()), f: m.f.map((f) => f.slice()) });
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
    cube: { name: "Cube", what: "A box made of quads. Segments splits every side.", params: { segments: [1, 1, 8] } },
    plane: { name: "Plane", what: "A flat grid of quads, one sided.", params: { segments: [4, 1, 32] } },
    sphere: { name: "Sphere", what: "A UV sphere: rings and segments.", params: { segments: [24, 6, 64], rings: [12, 3, 48] } },
    quadsphere: { name: "Quad sphere", what: "A subdivided cube pushed round: even quads, best for sculpting.", params: { segments: [6, 1, 24] } },
    cylinder: { name: "Cylinder", what: "Sides and height segments, capped.", params: { sides: [16, 3, 64], segments: [1, 1, 16] } },
    cone: { name: "Cone", what: "A capped cone.", params: { sides: [16, 3, 64] } },
    torus: { name: "Torus", what: "A ring: ring segments and tube sides; thickness sets the tube.", params: { segments: [32, 3, 96], sides: [12, 3, 48], thickness: [0.3, 0.05, 0.45] } },
  };
  function opt(kind, o, k) {
    const d = P.PRIMITIVES[kind].params[k];
    const x = o && o[k] != null ? +o[k] : d[0];
    return Math.min(d[2], Math.max(d[1], k === "thickness" ? x : Math.round(x)));
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
  P.primitive = (kind, o) => {
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
  root.ForgePoly = P;
  if (typeof module !== "undefined" && module.exports) module.exports = P;
})(typeof window !== "undefined" ? window : globalThis);
