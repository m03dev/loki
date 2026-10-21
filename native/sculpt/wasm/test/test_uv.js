// The UV unwrapping core (core/src/uv_unwrap.cpp via ks_uv_unfold / ks_uv_layout / ks_uv_auto): a cube cut like a
// box net, an open cylinder, a hemisphere, user pins, two shells in one call, layout of 20 random shells (inside
// 0-1, no overlap, gap, rotation, texel density), automatic unwraps (xatlas) of a cube / torus / sphere, keeping
// existing seams, bad input; then speed.
//   node native/sculpt/wasm/test/test_uv.js [path/to/sculpt.wasm]      (~3 s)
"use strict";
const path = require("path");
const ROOT = path.resolve(__dirname, "../../../..");
const SculptEngine = require(path.join(__dirname, "../sculpt_engine.js"));
const wasm = process.argv[2] || path.join(ROOT, "app/ui/vendor/sculpt/sculpt.wasm");
let pass = 0, fail = 0;
const check = (name, ok, detail) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + name + (ok ? "" : "  <- " + detail)); };

// ---- meshes: {v: [[x,y,z]], f: [[vertex ids]], fu: [[uv ids]] (same shape), nuv}
function flat(m, uv) {
  const pos = new Float32Array(m.v.length * 3); m.v.forEach((p, i) => pos.set(p, i * 3));
  return { pos, sizes: Int32Array.from(m.f.map((f) => f.length)), fv: Int32Array.from(m.f.flat()), fuv: Int32Array.from(m.fu.flat()),
    uv: uv || new Float32Array(m.nuv * 2) };
}
const area3 = (m) => { let a = 0; for (const f of m.f) for (let k = 1; k + 1 < f.length; k++) a += triA3(m.v[f[0]], m.v[f[k]], m.v[f[k + 1]]); return a; };
function triA3(a, b, c) {
  const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  const x = u[1] * v[2] - u[2] * v[1], y = u[2] * v[0] - u[0] * v[2], z = u[0] * v[1] - u[1] * v[0];
  return 0.5 * Math.hypot(x, y, z);
}
function area2(sizes, fuv, uv, faces) {   // unsigned 2D area of the faces (fan)
  let a = 0, s = 0; const st = [];
  for (let f = 0; f < sizes.length; f++) { st.push(s); s += sizes[f]; }
  for (const f of faces || [...sizes.keys()]) {
    const o = st[f];
    for (let k = 1; k + 1 < sizes[f]; k++) {
      const i = fuv[o], j = fuv[o + k], l = fuv[o + k + 1];
      a += Math.abs(0.5 * ((uv[2 * j] - uv[2 * i]) * (uv[2 * l + 1] - uv[2 * i + 1]) - (uv[2 * l] - uv[2 * i]) * (uv[2 * j + 1] - uv[2 * i + 1])));
    }
  }
  return a;
}

// Cube cut as a cross net: the 6 faces share UVs along the net's interior edges, every other edge is a seam.
function cubeNet() {
  const v = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]];
  // faces with outward winding
  const F = { bottom: [0, 3, 2, 1], top: [4, 5, 6, 7], front: [0, 1, 5, 4], back: [2, 3, 7, 6], right: [1, 2, 6, 5], left: [3, 0, 4, 7] };
  // net layout (grid coords of each face's corners in the same order as F): cross with front in the middle
  //        back(-y up)
  // left  top  right
  //        front
  //        bottom
  // Rather than hand-placing, build UV ids: corner (face, vertex) -> UV key; faces glued in the net share keys.
  const glue = [["top", "front"], ["top", "back"], ["top", "left"], ["top", "right"], ["front", "bottom"]];
  const key = new Map(); let n = 0; const id = {};
  const parent = {};
  const names = Object.keys(F);
  for (const nm of names) for (const vv of F[nm]) parent[nm + ":" + vv] = nm + ":" + vv;
  const find = (x) => (parent[x] === x ? x : (parent[x] = find(parent[x])));
  for (const [a, b] of glue) for (const vv of F[a]) if (F[b].includes(vv)) parent[find(a + ":" + vv)] = find(b + ":" + vv);
  const f = [], fu = [];
  for (const nm of names) {
    f.push(F[nm]);
    fu.push(F[nm].map((vv) => { const r = find(nm + ":" + vv); if (!key.has(r)) key.set(r, n++); return key.get(r); }));
  }
  void id;
  return { v, f, fu, nuv: n };
}
// Cylinder side: n segments around, h rings, one vertical seam (the seam column has its own UV ids)
function cylinder(n, h) {
  const v = [], f = [], fu = [];
  for (let j = 0; j <= h; j++) for (let i = 0; i < n; i++) { const a = (i / n) * Math.PI * 2; v.push([Math.cos(a), (j / h) * 3, Math.sin(a)]); }
  const uvId = (i, j) => j * (n + 1) + i;   // i in 0..n (n = the seam's duplicate)
  for (let j = 0; j < h; j++) for (let i = 0; i < n; i++) {
    const i1 = (i + 1) % n;
    f.push([j * n + i, (j + 1) * n + i, (j + 1) * n + i1, j * n + i1]);
    fu.push([uvId(i, j), uvId(i, j + 1), uvId(i + 1, j + 1), uvId(i + 1, j)]);
  }
  return { v, f, fu, nuv: (n + 1) * (h + 1) };
}
// Hemisphere as a grid disc: polar grid, centre fan of triangles, UV ids = vertex ids (no seam)
function hemisphere(seg, rings) {
  const v = [[0, 1, 0]], f = [];
  for (let r = 1; r <= rings; r++) {
    const th = (r / rings) * Math.PI / 2;
    for (let i = 0; i < seg; i++) { const a = (i / seg) * Math.PI * 2; v.push([Math.sin(th) * Math.cos(a), Math.cos(th), Math.sin(th) * Math.sin(a)]); }
  }
  const id = (r, i) => 1 + (r - 1) * seg + (i % seg);
  for (let i = 0; i < seg; i++) f.push([0, id(1, i + 1), id(1, i)]);
  for (let r = 1; r < rings; r++) for (let i = 0; i < seg; i++) f.push([id(r, i), id(r, i + 1), id(r + 1, i + 1), id(r + 1, i)]);
  return { v, f, fu: f.map((x) => x.slice()), nuv: v.length };
}
function grid(n, m, sx = 1, sy = 1, z = (x, y) => 0) {   // open grid, UV ids = vertex ids
  const v = [], f = [];
  for (let j = 0; j <= m; j++) for (let i = 0; i <= n; i++) v.push([(i / n) * sx, (j / m) * sy, z(i / n, j / m)]);
  for (let j = 0; j < m; j++) for (let i = 0; i < n; i++) { const a = j * (n + 1) + i; f.push([a, a + 1, a + n + 2, a + n + 1]); }
  return { v, f, fu: f.map((x) => x.slice()), nuv: v.length };
}
function concat(a, b) {   // two meshes, second one's ids offset
  const nv = a.v.length, nu = a.nuv;
  return { v: a.v.concat(b.v), f: a.f.concat(b.f.map((x) => x.map((i) => i + nv))), fu: a.fu.concat(b.fu.map((x) => x.map((i) => i + nu))), nuv: a.nuv + b.nuv };
}
function torus(n, m, R = 1, r = 0.35) {   // closed, UV ids = vertex ids (no seams: auto must cut it)
  const v = [], f = [];
  for (let j = 0; j < m; j++) for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2, b = (j / m) * Math.PI * 2;
    v.push([(R + r * Math.cos(b)) * Math.cos(a), r * Math.sin(b), (R + r * Math.cos(b)) * Math.sin(a)]);
  }
  for (let j = 0; j < m; j++) for (let i = 0; i < n; i++) { const i1 = (i + 1) % n, j1 = (j + 1) % m; f.push([j * n + i, j * n + i1, j1 * n + i1, j1 * n + i]); }
  return { v, f, fu: f.map((x) => x.slice()), nuv: v.length };
}
function sphere(seg, rings) {   // UV sphere: triangle caps + quads, no seams
  const v = [[0, 1, 0]], f = [];
  for (let r = 1; r < rings; r++) { const th = (r / rings) * Math.PI; for (let i = 0; i < seg; i++) { const a = (i / seg) * Math.PI * 2; v.push([Math.sin(th) * Math.cos(a), Math.cos(th), Math.sin(th) * Math.sin(a)]); } }
  v.push([0, -1, 0]);
  const id = (r, i) => 1 + (r - 1) * seg + (i % seg), S = v.length - 1;
  for (let i = 0; i < seg; i++) f.push([0, id(1, i + 1), id(1, i)]);
  for (let r = 1; r < rings - 1; r++) for (let i = 0; i < seg; i++) f.push([id(r, i), id(r, i + 1), id(r + 1, i + 1), id(r + 1, i)]);
  for (let i = 0; i < seg; i++) f.push([id(rings - 1, i), id(rings - 1, i + 1), S]);
  return { v, f, fu: f.map((x) => x.slice()), nuv: v.length };
}

// shells by UV connectivity (JS twin, for the checks)
function shellsOf(sizes, fuv, nuv) {
  const p = Int32Array.from({ length: nuv }, (_, i) => i);
  const find = (a) => { while (p[a] !== a) a = p[a] = p[p[a]]; return a; };
  let s = 0; const faceShell = [];
  for (let f = 0; f < sizes.length; f++) { for (let k = 1; k < sizes[f]; k++) { const a = find(fuv[s]), b = find(fuv[s + k]); if (a !== b) p[b] = a; } s += sizes[f]; }
  s = 0; for (let f = 0; f < sizes.length; f++) { faceShell.push(find(fuv[s])); s += sizes[f]; }
  return faceShell;
}
function shellBoxes(sizes, fuv, uv) {
  const fs = shellsOf(sizes, fuv, uv.length / 2), box = new Map(); let s = 0;
  for (let f = 0; f < sizes.length; f++) {
    const b = box.get(fs[f]) || [1e9, 1e9, -1e9, -1e9];
    for (let k = 0; k < sizes[f]; k++) { const g = fuv[s + k]; b[0] = Math.min(b[0], uv[2 * g]); b[1] = Math.min(b[1], uv[2 * g + 1]); b[2] = Math.max(b[2], uv[2 * g]); b[3] = Math.max(b[3], uv[2 * g + 1]); }
    box.set(fs[f], b); s += sizes[f];
  }
  return [...box.values()];
}
function minGap(boxes) {   // smallest separation between two boxes (negative = overlap)
  let g = Infinity;
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    const dx = Math.max(b[0] - a[2], a[0] - b[2]), dy = Math.max(b[1] - a[3], a[1] - b[3]);
    g = Math.min(g, Math.max(dx, dy));
  }
  return g;
}
// triangles of the result overlapping between different charts (exact SAT test on a grid of buckets)
function chartOverlaps(sizes, fuv, uv) {
  const fs = shellsOf(sizes, fuv, uv.length / 2), tris = []; let s = 0;
  for (let f = 0; f < sizes.length; f++) { for (let k = 1; k + 1 < sizes[f]; k++) tris.push([fuv[s], fuv[s + k], fuv[s + k + 1], fs[f]]); s += sizes[f]; }
  const G = 64, cells = new Map();
  const P = (g) => [uv[2 * g], uv[2 * g + 1]];
  tris.forEach((t, i) => {
    const ps = [P(t[0]), P(t[1]), P(t[2])];
    const x0 = Math.floor(Math.min(...ps.map((p) => p[0])) * G), x1 = Math.floor(Math.max(...ps.map((p) => p[0])) * G);
    const y0 = Math.floor(Math.min(...ps.map((p) => p[1])) * G), y1 = Math.floor(Math.max(...ps.map((p) => p[1])) * G);
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) { const k = x * 4096 + y; if (!cells.has(k)) cells.set(k, []); cells.get(k).push(i); }
  });
  const sep = (A, B) => {
    for (const T of [A, B]) for (let e = 0; e < 3; e++) {
      const p = T[e], q = T[(e + 1) % 3], nx = q[1] - p[1], ny = p[0] - q[0];
      let a0 = Infinity, a1 = -Infinity, b0 = Infinity, b1 = -Infinity;
      for (const r of A) { const d = r[0] * nx + r[1] * ny; a0 = Math.min(a0, d); a1 = Math.max(a1, d); }
      for (const r of B) { const d = r[0] * nx + r[1] * ny; b0 = Math.min(b0, d); b1 = Math.max(b1, d); }
      const eps = 1e-9 * (Math.abs(nx) + Math.abs(ny));
      if (a1 <= b0 + eps || b1 <= a0 + eps) return true;
    }
    return false;
  };
  let n = 0; const seen = new Set();
  for (const list of cells.values()) for (let a = 0; a < list.length; a++) for (let b = a + 1; b < list.length; b++) {
    const i = list[a], j = list[b], ti = tris[i], tj = tris[j];
    if (ti[3] === tj[3]) continue;
    const key = i < j ? i * 1e7 + j : j * 1e7 + i; if (seen.has(key)) continue; seen.add(key);
    if (!sep([P(ti[0]), P(ti[1]), P(ti[2])], [P(tj[0]), P(tj[1]), P(tj[2])])) n++;
  }
  return n;
}
const rng = (() => { let s = 12345; return () => ((s = (s * 1103515245 + 12345) >>> 0) / 4294967296); })();

SculptEngine.create(wasm).then((E) => {
  // (a) cube net
  {
    const m = cubeNet(), F = flat(m), r = E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, F.uv, { iterations: 6 });
    const a2 = area2(F.sizes, F.fuv, r.uv);
    check("cube cut as a cross: one shell, 0 flips, stretch " + r.stretch.toFixed(3) + " < 1.2, 2D area " + a2.toFixed(3) + " ~ 6",
      r.shells === 1 && r.flips === 0 && r.stretch < 1.2 && Math.abs(a2 - 6) < 0.06, JSON.stringify({ shells: r.shells, flips: r.flips, stretch: r.stretch, a2 }));
    const l = E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, F.uv, { iterations: 0 });
    check("pure LSCM (iterations 0) on the net: 0 flips", l.flips === 0 && l.shells === 1, JSON.stringify(l.flips));
  }
  // (b) cylinder side
  {
    const m = cylinder(32, 8), F = flat(m), r = E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, F.uv);
    let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
    for (let i = 0; i < m.nuv; i++) { x0 = Math.min(x0, r.uv[2 * i]); x1 = Math.max(x1, r.uv[2 * i]); y0 = Math.min(y0, r.uv[2 * i + 1]); y1 = Math.max(y1, r.uv[2 * i + 1]); }
    const fill = area2(F.sizes, F.fuv, r.uv) / ((x1 - x0) * (y1 - y0));
    check("open cylinder, one seam: a rectangle (fills " + (fill * 100).toFixed(1) + "% of its box), stretch " + r.stretch.toFixed(4) + " < 1.1, 0 flips",
      r.flips === 0 && r.stretch < 1.1 && fill > 0.97, JSON.stringify({ flips: r.flips, stretch: r.stretch, fill }));
  }
  // (c) hemisphere
  {
    const m = hemisphere(24, 10), F = flat(m), r = E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, F.uv);
    const a2 = area2(F.sizes, F.fuv, r.uv), a3 = area3(m);
    check("hemisphere (polar grid, tri fan + quads): 0 flips, stretch " + r.stretch.toFixed(3) + ", area " + (a2 / a3).toFixed(3) + " x 3D",
      r.flips === 0 && r.shells === 1 && Math.abs(a2 / a3 - 1) < 0.01 && r.stretch < 1.5, JSON.stringify({ flips: r.flips, stretch: r.stretch, a2, a3 }));
    // the shell stays where the input was: bbox centre
    const uvIn = new Float32Array(m.nuv * 2); for (let i = 0; i < m.nuv; i++) { uvIn[2 * i] = 5 + m.v[i][0] * 0.1; uvIn[2 * i + 1] = -3 + m.v[i][2] * 0.1; }
    const q = E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, uvIn);
    let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
    for (let i = 0; i < m.nuv; i++) { x0 = Math.min(x0, q.uv[2 * i]); x1 = Math.max(x1, q.uv[2 * i]); y0 = Math.min(y0, q.uv[2 * i + 1]); y1 = Math.max(y1, q.uv[2 * i + 1]); }
    check("the unfolded shell's box centre stays where the input's was (5, -3)", Math.abs((x0 + x1) / 2 - 5) < 1e-4 && Math.abs((y0 + y1) / 2 + 3) < 1e-4, [(x0 + x1) / 2, (y0 + y1) / 2].join());
    const d = E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, F.uv, { scaleToDensity: 4 });
    check("scaleToDensity 4: 2D area = 4 x 3D area", Math.abs(area2(F.sizes, F.fuv, d.uv) / a3 - 4) < 0.04, area2(F.sizes, F.fuv, d.uv) / a3);
  }
  // (d) user pins
  {
    const m = grid(12, 6, 2, 1, (x, y) => 0.3 * Math.sin(x * 3) * Math.cos(y * 2)), F = flat(m);
    const uvIn = new Float32Array(m.nuv * 2); for (let i = 0; i < m.nuv; i++) { uvIn[2 * i] = m.v[i][0]; uvIn[2 * i + 1] = m.v[i][1]; }
    const pinned = new Uint8Array(m.nuv); const pins = [0, 12, 13 * 7 - 1, 13 * 6];
    uvIn[0] = 0.1234567; uvIn[1] = -0.7654321; uvIn[24] = 2.5; uvIn[25] = 0.25; uvIn[2 * (13 * 7 - 1)] = 2.75; uvIn[2 * (13 * 7 - 1) + 1] = 1.5; uvIn[2 * 78] = 0.0; uvIn[2 * 78 + 1] = 1.1;
    for (const p of pins) pinned[p] = 1;
    const r = E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, uvIn, { pinned });
    check("user pins stay exactly where given (4 corners)", pins.every((p) => r.uv[2 * p] === uvIn[2 * p] && r.uv[2 * p + 1] === uvIn[2 * p + 1]) && r.flips === 0,
      JSON.stringify(pins.map((p) => [r.uv[2 * p], r.uv[2 * p + 1]])) + " flips " + r.flips);
    const one = new Uint8Array(m.nuv); one[13 * 3 + 6] = 1;
    const r1 = E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, uvIn, { pinned: one });
    check("one user pin: kept, the rest unfolds without flips", r1.uv[2 * 45] === uvIn[90] && r1.uv[91] === uvIn[91] && r1.flips === 0, r1.flips);
  }
  // (e) two shells + untouched UV ids
  {
    const m = concat(cylinder(16, 4), hemisphere(12, 5)); m.nuv += 3;   // 3 UV ids no face uses
    const F = flat(m); for (let i = 0; i < F.uv.length; i++) F.uv[i] = i * 0.001;
    const r = E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, F.uv);
    const tail = [m.nuv - 3, m.nuv - 2, m.nuv - 1].every((i) => r.uv[2 * i] === F.uv[2 * i] && r.uv[2 * i + 1] === F.uv[2 * i + 1]);
    const fs = shellsOf(F.sizes, F.fuv, m.nuv), ids = [...new Set(fs)];
    const okA = ids.every((id) => { const faces = fs.map((s, i) => (s === id ? i : -1)).filter((i) => i >= 0); const sub = { v: m.v, f: faces.map((i) => m.f[i]) }; return Math.abs(area2(F.sizes, F.fuv, r.uv, faces) / area3(sub) - 1) < 0.01; });
    check("two shells in one call: both unfold (world scale each), 0 flips; unused UV ids copied unchanged", r.shells === 2 && r.flips === 0 && tail && okA,
      JSON.stringify({ shells: r.shells, flips: r.flips, tail, okA }));
  }
  // (f) layout
  {
    let m = null;
    for (let s = 0; s < 20; s++) {
      const w = 1 + Math.floor(rng() * 6), h = 1 + Math.floor(rng() * 4), sx = 0.2 + rng() * 2, sy = 0.2 + rng() * 1.5;
      const g = grid(w, h, sx, sy, (x, y) => 0.1 * x * y);
      g.v = g.v.map((p) => [p[0] + s * 3, p[1], p[2]]);
      m = m ? concat(m, g) : g;
    }
    const F = flat(m); for (let i = 0; i < m.nuv; i++) { F.uv[2 * i] = m.v[i][0] * (1 + (i % 7) * 0.01); F.uv[2 * i + 1] = m.v[i][1]; }
    // give the shells very different UV scales so scaleMode 1 has something to fix
    const fs0 = shellsOf(F.sizes, F.fuv, m.nuv); { let s = 0; const k = new Map(); for (let f = 0; f < F.sizes.length; f++) { if (!k.has(fs0[f])) k.set(fs0[f], 0.2 + rng() * 3); for (let c = 0; c < F.sizes[f]; c++) { const g = F.fuv[s + c]; F.uv[2 * g] *= k.get(fs0[f]); F.uv[2 * g + 1] *= k.get(fs0[f]); } s += F.sizes[f]; } }
    const pad = 4, res = 1024;
    for (const rot of [0, 1, 2]) {
      const r = E.uvLayout(F.pos, F.sizes, F.fv, F.fuv, F.uv, { paddingPx: pad, resolution: res, rotate: rot, scaleMode: 1, margin: 0.005 });
      let inside = true; for (let i = 0; i < r.uv.length; i++) if (!(r.uv[i] >= 0 && r.uv[i] <= 1)) inside = false;
      const boxes = shellBoxes(F.sizes, F.fuv, r.uv), gap = minGap(boxes);
      let bx = 0; for (const b of boxes) bx = Math.max(bx, b[2], b[3]);
      check("layout rotate=" + rot + ": 20 shells in [0,1], no box overlap, gap " + (gap * res).toFixed(2) + " px >= " + pad + ", fills to " + bx.toFixed(3),
        r.shells === 20 && inside && gap >= pad / res - 1e-6 && bx > 0.98, JSON.stringify({ shells: r.shells, inside, gap: gap * res, bx }));
      if (rot === 1) {
        // texel density: 2D/3D per shell within 2 %
        const fs = shellsOf(F.sizes, F.fuv, m.nuv), ids = [...new Set(fs)], ratios = ids.map((id) => {
          const faces = fs.map((s, i) => (s === id ? i : -1)).filter((i) => i >= 0);
          return area2(F.sizes, F.fuv, r.uv, faces) / area3({ v: m.v, f: faces.map((i) => m.f[i]) });
        });
        const mn = Math.min(...ratios), mx = Math.max(...ratios);
        check("scaleMode 1: equal texel density (2D/3D area ratios within 2%: " + ((mx / mn - 1) * 100).toFixed(3) + "%)", mx / mn < 1.02, JSON.stringify(ratios));
      }
    }
    const k = E.uvLayout(F.pos, F.sizes, F.fv, F.fuv, F.uv, { scaleMode: 2, rotate: 0, margin: 0 });
    const a0 = area2(F.sizes, F.fuv, F.uv), a1 = area2(F.sizes, F.fuv, k.uv);
    check("scaleMode 2: shells only moved (total area unchanged)", Math.abs(a1 / a0 - 1) < 1e-4 && minGap(shellBoxes(F.sizes, F.fuv, k.uv)) > 0, a1 / a0);
    // free rotation: a long thin strip on the diagonal
    const strip = grid(20, 1, 4, 0.2); const cs = Math.SQRT1_2;
    const S = flat(strip); for (let i = 0; i < strip.nuv; i++) { const x = strip.v[i][0], y = strip.v[i][1]; S.uv[2 * i] = x * cs - y * cs; S.uv[2 * i + 1] = x * cs + y * cs; }
    const totalBox = (uv) => { let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9; for (let i = 0; i < uv.length; i += 2) { x0 = Math.min(x0, uv[i]); x1 = Math.max(x1, uv[i]); y0 = Math.min(y0, uv[i + 1]); y1 = Math.max(y1, uv[i + 1]); } return (x1 - x0) * (y1 - y0); };
    const r0 = E.uvLayout(S.pos, S.sizes, S.fv, S.fuv, S.uv, { rotate: 0, scaleMode: 2, margin: 0 }), r2 = E.uvLayout(S.pos, S.sizes, S.fv, S.fuv, S.uv, { rotate: 2, scaleMode: 2, margin: 0 });
    const b0 = totalBox(r0.uv), b2 = totalBox(r2.uv);
    check("rotate=2 straightens a diagonal strip: box area " + b2.toFixed(3) + " vs " + b0.toFixed(3) + " with rotate=0", b2 <= b0 + 1e-9 && b2 < b0 * 0.5, b0 + " " + b2);
  }
  // automatic (xatlas)
  {
    const t0 = performance.now();
    const capped = (() => { const c = cylinder(12, 3); const n = 12, top = 3 * n; c.f.push([...Array(n).keys()].reverse(), [...Array(n).keys()].map((i) => top + i)); c.fu = c.f.map((x) => x.slice()); c.nuv = c.v.length; return c; })();
    for (const [name, m] of [["cube", cubeNet()], ["torus 24x12", torus(24, 12)], ["sphere 24x12", sphere(24, 12)], ["cylinder with 12-gon caps", capped]]) {
      const F = flat(m), r = E.uvAuto(F.pos, F.sizes, F.fv, null, { padding: 2, resolution: 512 });
      let inside = r.fuv.length === F.fv.length; for (const g of r.fuv) if (!(g >= 0 && 2 * g + 1 < r.uv.length && r.uv[2 * g] >= 0 && r.uv[2 * g] <= 1 && r.uv[2 * g + 1] >= 0 && r.uv[2 * g + 1] <= 1)) inside = false;
      const ov = chartOverlaps(F.sizes, r.fuv, r.uv);
      check("auto unwrap " + name + ": " + r.charts + " charts, every corner's UV inside 0-1, no chart overlap (" + r.ms.toFixed(0) + " ms)",
        r.charts > 0 && inside && ov === 0, JSON.stringify({ charts: r.charts, inside, ov }));
    }
    // a mixed-size polygon mesh: the corner mapping (xatlas polygon input) is right: each corner's UV belongs to a
    // UV id whose 3D vertex is that corner's vertex - check through the chart's 2D/3D edge-length ratio consistency
    const m = sphere(9, 5), F = flat(m), r = E.uvAuto(F.pos, F.sizes, F.fv, null, {});
    let worst = 0, s = 0; const ratios = [];
    for (let f = 0; f < F.sizes.length; f++) {
      for (let k = 0; k < F.sizes[f]; k++) {
        const a = s + k, b = s + (k + 1) % F.sizes[f];
        const l3 = Math.hypot(...[0, 1, 2].map((d) => F.pos[3 * F.fv[a] + d] - F.pos[3 * F.fv[b] + d]));
        const l2 = Math.hypot(r.uv[2 * r.fuv[a]] - r.uv[2 * r.fuv[b]], r.uv[2 * r.fuv[a] + 1] - r.uv[2 * r.fuv[b] + 1]);
        ratios.push(l2 / l3);
      }
      s += F.sizes[f];
    }
    ratios.sort((x, y) => x - y); worst = ratios[ratios.length - 1] / ratios[Math.floor(ratios.length / 2)];
    check("auto unwrap of tris + quads: corners map to their own vertices (edge 2D/3D ratio max/median " + worst.toFixed(2) + " < 3)", worst < 3 && ratios[0] > 0, worst);
    // keep seams: the cube net stays one shell; a 2-shell input stays 2 shells, with the same seams
    const c = cubeNet(), C = flat(c), k = E.uvAuto(C.pos, C.sizes, C.fv, C.fuv, { padding: 2 });
    const same = (() => { const m1 = new Map(); for (let i = 0; i < C.fuv.length; i++) { const a = C.fuv[i], b = k.fuv[i]; if (m1.has(a) && m1.get(a) !== b) return false; m1.set(a, b); } return new Set(m1.values()).size === m1.size; })();
    let inside = true; for (const g of k.fuv) if (!(k.uv[2 * g] >= 0 && k.uv[2 * g] <= 1 && k.uv[2 * g + 1] >= 0 && k.uv[2 * g + 1] <= 1)) inside = false;
    check("auto with existing seams: the cube net stays 1 chart, the UV ids map one to one, inside 0-1", k.charts === 1 && same && inside, JSON.stringify({ charts: k.charts, same, inside }));
    const two = concat(cylinder(16, 4), cubeNet()), T = flat(two), k2 = E.uvAuto(T.pos, T.sizes, T.fv, T.fuv, {});
    const ov2 = chartOverlaps(T.sizes, k2.fuv, k2.uv);
    check("auto with existing seams: 2 shells stay 2 charts, no overlap", k2.charts === 2 && ov2 === 0, JSON.stringify({ charts: k2.charts, ov2 }));
    console.log("  auto unwraps: " + (performance.now() - t0).toFixed(0) + " ms in all");
  }
  // (g) bad input
  {
    const m = cubeNet(), F = flat(m);
    const bad = (fn) => { try { fn(); return false; } catch (_) { return true; } };
    const fuvBad = F.fuv.slice(); fuvBad[3] = m.nuv;
    const fvBad = F.fv.slice(); fvBad[0] = -1;
    check("bad input refused: UV index out of range, vertex index out of range, sizes / corners mismatch, no UVs, pin count",
      bad(() => E.uvUnfold(F.pos, F.sizes, F.fv, fuvBad, F.uv)) && bad(() => E.uvLayout(F.pos, F.sizes, fvBad, F.fuv, F.uv)) &&
      bad(() => E.uvUnfold(F.pos, Int32Array.of(4, 4, 4, 4, 4, 5), F.fv, F.fuv, F.uv)) && bad(() => E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, new Float32Array(0))) &&
      bad(() => E.uvAuto(F.pos, F.sizes, fvBad, null)) && bad(() => E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, F.uv, { pinned: new Uint8Array(2) })), "accepted");
  }
  // (h) speed
  {
    const m = grid(200, 100, 2, 1, (x, y) => 0.4 * Math.sin(x * 6) * Math.cos(y * 5)), F = flat(m);
    let t = performance.now(); const r = E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, F.uv, { iterations: 6 }); const tu = performance.now() - t;
    t = performance.now(); E.uvUnfold(F.pos, F.sizes, F.fv, F.fuv, F.uv, { iterations: 0 }); const tl = performance.now() - t;
    t = performance.now(); E.uvLayout(F.pos, F.sizes, F.fv, F.fuv, r.uv); const tlay = performance.now() - t;
    // xatlas's chart growing is much slower than the unfold (about 14 s for this 20 000-face shell, one thread), so
    // its speed is measured on a 5 000-face one
    const g5 = flat(grid(100, 50, 2, 1, (x, y) => 0.4 * Math.sin(x * 6) * Math.cos(y * 5)));
    t = performance.now(); const a = E.uvAuto(g5.pos, g5.sizes, g5.fv, null, {}); const ta = performance.now() - t;
    t = performance.now(); const ak = E.uvAuto(F.pos, F.sizes, F.fv, F.fuv, { unfoldIterations: 6 }); const tak = performance.now() - t;
    console.log("  speed: 20 000-face shell: unfold (LSCM + 6 ARAP) " + tu.toFixed(0) + " ms, LSCM only " + tl.toFixed(0) + " ms, layout " + tlay.toFixed(0) +
      " ms, auto keeping its seams " + tak.toFixed(0) + " ms (" + ak.charts + " chart); flips " + r.flips + ", stretch " + r.stretch.toFixed(3) +
      "; auto (xatlas cuts) on 5 000 faces " + ta.toFixed(0) + " ms, " + a.charts + " charts");
    check("unfold of a 20 000-face shell (6 ARAP rounds) under 2 s", tu < 2000 && r.flips === 0, tu + " ms, flips " + r.flips);
  }
  console.log("\n" + pass + " passed, " + fail + " failed");
  process.exit(fail ? 1 : 0);
});
