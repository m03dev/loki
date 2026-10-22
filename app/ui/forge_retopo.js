// Forge's Retopology workspace (owner 2026-10-21: Alpaca3D's Retopo lab, "those all go into forge ... a tab within
// forge like a workspace ... make a real system"). Workspace: Retopology. The selected object (or the one being
// edited - a sculpt, a scan, any mesh) becomes the LIVE surface; you draw a new, clean low-poly on top of it with
// Quad Draw, the pro tool's way:
//   click on the surface ........ a dot (a new vertex), stuck to the surface; drag a dot to slide it along the surface
//   Shift + click ................. a quad from the 4 dots nearest the mouse (3 = a triangle)
//   Tab + drag from a border edge . extrude a new quad strip from that edge
//   Shift + drag .................. relax: smooth the dots under the brush, kept on the surface
//   Ctrl + click .................. delete the dot under the mouse;  Ctrl + Shift + click: delete the face under it
//   Ctrl+Z / Ctrl+Shift+Z ......... undo / redo inside the tool;  Alt + mouse: the camera, as everywhere
// Symmetry X mirrors every dot and face across X (dots near the middle snap onto it). "Make Object" turns the
// result into an ordinary Forge object (retopo1) - a cage like any other, so UV Editing and Baking take it next.
// The surface gets its own BVH (built once, in JS) so placing and relaxing stay instant on millions of triangles.
"use strict";

const FORGE_RETOPO_STORE = "loki-forge-retopo";
const FORGE_RETOPO_DEFAULTS = { snapPx: 12, quadPx: 160, relaxPx: 60, relaxStrength: 0.5, symmetry: false, offset: 0.002 };

// ------------------------------------------------------------------ a ray BVH over a triangle soup (plain JS)
function forgeRetopoBVH(pos, idx, matrix) {
  const nt = (idx ? idx.length : pos.length / 3) / 3;
  const P = new Float32Array(nt * 9);                   // world-space triangle corners
  const e = matrix ? matrix.elements : null;
  const put = (t, k, vi) => {
    let x = pos[vi * 3], y = pos[vi * 3 + 1], z = pos[vi * 3 + 2];
    if (e) { const X = e[0] * x + e[4] * y + e[8] * z + e[12], Y = e[1] * x + e[5] * y + e[9] * z + e[13], Z = e[2] * x + e[6] * y + e[10] * z + e[14]; x = X; y = Y; z = Z; }
    P[t * 9 + k * 3] = x; P[t * 9 + k * 3 + 1] = y; P[t * 9 + k * 3 + 2] = z;
  };
  for (let t = 0; t < nt; t++) for (let k = 0; k < 3; k++) put(t, k, idx ? idx[t * 3 + k] : t * 3 + k);
  const order = new Uint32Array(nt).map((_, i) => i), cen = new Float32Array(nt * 3);
  for (let t = 0; t < nt; t++) for (let a = 0; a < 3; a++) cen[t * 3 + a] = (P[t * 9 + a] + P[t * 9 + 3 + a] + P[t * 9 + 6 + a]) / 3;
  const nodes = [];                                     // {min, max, l, r, s, n}
  const LEAF = 6;
  function build(s, n) {
    const mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
    for (let i = s; i < s + n; i++) { const t = order[i]; for (let k = 0; k < 3; k++) for (let a = 0; a < 3; a++) { const v = P[t * 9 + k * 3 + a]; if (v < mn[a]) mn[a] = v; if (v > mx[a]) mx[a] = v; } }
    const id = nodes.length; nodes.push({ mn, mx, l: -1, r: -1, s, n });
    if (n <= LEAF) return id;
    const ax = [0, 1, 2].reduce((b, a) => (mx[a] - mn[a] > mx[b] - mn[b] ? a : b), 0);
    // median split on the centroids (quickselect-free: sort the range by the axis)
    const sub = Array.from(order.subarray(s, s + n)).sort((p, q) => cen[p * 3 + ax] - cen[q * 3 + ax]);
    order.set(sub, s);
    const h = n >> 1;
    nodes[id].l = build(s, h); nodes[id].r = build(s + h, n - h);
    return id;
  }
  if (nt) build(0, nt);
  function hitBox(nd, o, inv, tmax) {
    let t0 = 0, t1 = tmax;
    for (let a = 0; a < 3; a++) {
      let ta = (nd.mn[a] - o[a]) * inv[a], tb = (nd.mx[a] - o[a]) * inv[a];
      if (ta > tb) { const x = ta; ta = tb; tb = x; }
      if (ta > t0) t0 = ta; if (tb < t1) t1 = tb;
      if (t0 > t1) return false;
    }
    return true;
  }
  // nearest hit along the ray (o + t d), both faces: {t, p, n} or null
  function ray(o, d, tmax) {
    if (!nodes.length) return null;
    const inv = [1 / (d[0] || 1e-30), 1 / (d[1] || 1e-30), 1 / (d[2] || 1e-30)];
    let best = tmax || Infinity, bt = -1, bu = 0, bv = 0;
    const stack = [0];
    while (stack.length) {
      const nd = nodes[stack.pop()];
      if (!hitBox(nd, o, inv, best)) continue;
      if (nd.l < 0) {
        for (let i = nd.s; i < nd.s + nd.n; i++) {
          const t = order[i], b = t * 9;
          const e1x = P[b + 3] - P[b], e1y = P[b + 4] - P[b + 1], e1z = P[b + 5] - P[b + 2];
          const e2x = P[b + 6] - P[b], e2y = P[b + 7] - P[b + 1], e2z = P[b + 8] - P[b + 2];
          const px = d[1] * e2z - d[2] * e2y, py = d[2] * e2x - d[0] * e2z, pz = d[0] * e2y - d[1] * e2x;
          const det = e1x * px + e1y * py + e1z * pz;
          if (Math.abs(det) < 1e-12) continue;
          const id = 1 / det, tx = o[0] - P[b], ty = o[1] - P[b + 1], tz = o[2] - P[b + 2];
          const u = (tx * px + ty * py + tz * pz) * id; if (u < 0 || u > 1) continue;
          const qx = ty * e1z - tz * e1y, qy = tz * e1x - tx * e1z, qz = tx * e1y - ty * e1x;
          const v = (d[0] * qx + d[1] * qy + d[2] * qz) * id; if (v < 0 || u + v > 1) continue;
          const tt = (e2x * qx + e2y * qy + e2z * qz) * id;
          if (tt > 1e-7 && tt < best) { best = tt; bt = t; bu = u; bv = v; }
        }
      } else { stack.push(nd.l, nd.r); }
    }
    if (bt < 0) return null;
    const b = bt * 9;
    const e1 = [P[b + 3] - P[b], P[b + 4] - P[b + 1], P[b + 5] - P[b + 2]], e2 = [P[b + 6] - P[b], P[b + 7] - P[b + 1], P[b + 8] - P[b + 2]];
    let n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
    const l = Math.hypot(n[0], n[1], n[2]) || 1; n = [n[0] / l, n[1] / l, n[2] / l];
    if (n[0] * d[0] + n[1] * d[1] + n[2] * d[2] > 0) n = [-n[0], -n[1], -n[2]];   // towards the ray's origin
    return { t: best, p: [o[0] + d[0] * best, o[1] + d[1] * best, o[2] + d[2] * best], n, tri: bt, u: bu, v: bv };   // (u, v): barycentrics on corners 1, 2
  }
  // the triangle's original corner vertex ids (to interpolate vertex attributes at a hit)
  const corners = (t) => (idx ? [idx[t * 3], idx[t * 3 + 1], idx[t * 3 + 2]] : [t * 3, t * 3 + 1, t * 3 + 2]);
  return { ray, triangles: nt, nodes: nodes.length, corners };
}

// ------------------------------------------------------------------ the retopology cage (pure data + rules)
// {v: [[x,y,z]], f: [[i...]]} with the tool's edits; every edit returns a NEW cage (the tool's own undo keeps them)
const ForgeRetopoCage = {
  empty: () => ({ v: [], f: [] }),
  copy: (c) => ({ v: c.v.map((p) => p.slice()), f: c.f.map((f) => f.slice()) }),
  addVert(c, p) { const o = ForgeRetopoCage.copy(c); o.v.push(p.slice()); return { cage: o, id: o.v.length - 1 }; },
  addFace(c, ids) {
    if (new Set(ids).size !== ids.length || ids.length < 3) return null;
    const key = ids.slice().sort((a, b) => a - b).join(",");
    if (c.f.some((f) => f.slice().sort((a, b) => a - b).join(",") === key)) return null;     // already there
    const o = ForgeRetopoCage.copy(c); o.f.push(ids.slice()); return o;
  },
  deleteFace(c, fi) { const o = ForgeRetopoCage.copy(c); o.f.splice(fi, 1); return o; },
  deleteVert(c, vi) {                                  // the dot and every face on it; indices after it shift down
    const o = { v: c.v.filter((_, i) => i !== vi).map((p) => p.slice()), f: [] };
    for (const f of c.f) if (!f.includes(vi)) o.f.push(f.map((i) => (i > vi ? i - 1 : i)));
    return o;
  },
  // edges used by exactly one face, as [a, b] in that face's winding
  borderEdges(c) {
    const count = new Map(), dir = new Map();
    for (const f of c.f) for (let k = 0; k < f.length; k++) {
      const a = f[k], b = f[(k + 1) % f.length], key = a < b ? a + "," + b : b + "," + a;
      count.set(key, (count.get(key) || 0) + 1); dir.set(key, [a, b]);
    }
    return [...count].filter(([, n]) => n === 1).map(([k]) => dir.get(k));
  },
  neighbours(c) {
    const nb = c.v.map(() => new Set());
    for (const f of c.f) for (let k = 0; k < f.length; k++) { const a = f[k], b = f[(k + 1) % f.length]; nb[a].add(b); nb[b].add(a); }
    return nb;
  },
  // the vertex on the other side of x = 0 (within eps), or -1
  mirrorOf(c, vi, eps) {
    const p = c.v[vi]; let best = -1, bd = eps * eps;
    c.v.forEach((q, i) => { const d = (q[0] + p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2; if (d < bd) { bd = d; best = i; } });
    return best;
  },
};

const ForgeRetopo = (() => {
  const R = { on: false, view: null, surface: null, bvh: null, cage: ForgeRetopoCage.empty(), undo: [], redo: [], group: null, drag: null,
    tabHeld: false, panel: null, hoverFace: -1, hoverVert: -1, mouse: null };
  const st = () => { let s = {}; try { s = JSON.parse(localStorage.getItem(FORGE_RETOPO_STORE) || "{}") || {}; } catch (_) { s = {}; } return Object.assign({}, FORGE_RETOPO_DEFAULTS, s); };
  const save = (s) => { try { localStorage.setItem(FORGE_RETOPO_STORE, JSON.stringify(s)); } catch (_) { /* private window */ } };
  const say = (t, bad) => { if (typeof forgeSay === "function") forgeSay(t, bad); const s = R.panel && R.panel.querySelector(".frt-status"); if (s) { s.textContent = t; s.classList.toggle("bad", !!bad); } };
  const size = () => (R.view && R.view.size) || 1;

  // ---------------------------------------------------------------- the live surface
  function pickSurface() {
    const v = R.view, t = v.tree && v.tree.api;
    let mesh = null;
    if (t) {
      const sel = t.selected ? t.selected() : v.tree.sel;
      const n = sel && sel.length ? t.node(sel[sel.length - 1]) : null;
      if (n) n.inner.traverse((o) => { if (!mesh && o.isMesh && o.geometry && o.name !== "forge-sel" && o.name !== "forge-smooth") mesh = o; });
    }
    if (!mesh && v.meshObj) mesh = v.meshObj();
    if (!mesh || !mesh.geometry || !mesh.geometry.attributes.position || !mesh.geometry.attributes.position.count) return false;
    mesh.updateMatrixWorld(true);
    const g = mesh.geometry, t0 = performance.now();
    R.surface = mesh;
    R.bvh = forgeRetopoBVH(g.attributes.position.array, g.index ? g.index.array : null, mesh.matrixWorld);
    R.bvhMs = performance.now() - t0;
    return true;
  }
  function rayFrom(x, y) {
    const v = R.view, THREE = v.THREE, r = v.canvas.getBoundingClientRect();
    const rc = new THREE.Raycaster();
    v.camera.updateMatrixWorld();
    rc.setFromCamera(new THREE.Vector2(((x - r.left) / r.width) * 2 - 1, -((y - r.top) / r.height) * 2 + 1), v.camera);
    return [rc.ray.origin.toArray(), rc.ray.direction.toArray()];
  }
  function hitAt(x, y) { if (!R.bvh) return null; const [o, d] = rayFrom(x, y); return R.bvh.ray(o, d); }
  function toScreen(p) {
    const v = R.view, THREE = v.THREE, r = v.canvas.getBoundingClientRect();
    const q = new THREE.Vector3(p[0], p[1], p[2]).project(v.camera);
    return [r.left + (q.x + 1) / 2 * r.width, r.top + (1 - q.y) / 2 * r.height, q.z];
  }
  // put a point back on the surface: along a normal when one is known (both ways, the nearer hit), else along the
  // view ray through its screen position (fine for what you see; a normal is needed on the far side - mirrors)
  function reproject(p, n) {
    if (n && R.bvh) {
      const reach = size() * 0.25, l = Math.hypot(n[0], n[1], n[2]) || 1, d = [n[0] / l, n[1] / l, n[2] / l];
      const o1 = [p[0] + d[0] * reach, p[1] + d[1] * reach, p[2] + d[2] * reach];
      const a = R.bvh.ray(o1, [-d[0], -d[1], -d[2]], reach * 2), b = R.bvh.ray(p, [-d[0], -d[1], -d[2]], reach);
      const pick = [a, b].filter(Boolean).sort((x, y) => Math.hypot(x.p[0] - p[0], x.p[1] - p[1], x.p[2] - p[2]) - Math.hypot(y.p[0] - p[0], y.p[1] - p[1], y.p[2] - p[2]))[0];
      if (pick) return pick.p;
    }
    const s = toScreen(p); const h = hitAt(s[0], s[1]); return h ? h.p : p;
  }
  function vertNormal(c, i) {
    const n = [0, 0, 0];
    for (const f of c.f) {
      if (!f.includes(i)) continue;
      const a = c.v[f[0]], b = c.v[f[1]], d = c.v[f[2]];
      const e1 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], e2 = [d[0] - a[0], d[1] - a[1], d[2] - a[2]];
      n[0] += e1[1] * e2[2] - e1[2] * e2[1]; n[1] += e1[2] * e2[0] - e1[0] * e2[2]; n[2] += e1[0] * e2[1] - e1[1] * e2[0];
    }
    return Math.hypot(n[0], n[1], n[2]) > 1e-12 ? n : null;
  }

  // ---------------------------------------------------------------- edits (each one undoable)
  function set(cage, label) { R.undo.push(R.cage); if (R.undo.length > 200) R.undo.shift(); R.redo = []; R.cage = cage; draw(); if (label) say(label); }
  function undo() { if (!R.undo.length) return say("Nothing to undo in Quad Draw."); R.redo.push(R.cage); R.cage = R.undo.pop(); draw(); say("Undo."); }
  function redoIt() { if (!R.redo.length) return say("Nothing to redo."); R.undo.push(R.cage); R.cage = R.redo.pop(); draw(); say("Redo."); }
  function snapMid(p) { const s = st(); if (s.symmetry && Math.abs(p[0]) < size() * 0.01) return [0, p[1], p[2]]; return p; }
  function addDot(p, n) {
    const s = st();
    p = snapMid(p);
    let { cage, id } = ForgeRetopoCage.addVert(R.cage, p);
    if (s.symmetry && Math.abs(p[0]) > 1e-9) cage = ForgeRetopoCage.addVert(cage, reproject([-p[0], p[1], p[2]], n ? [-n[0], n[1], n[2]] : null)).cage;
    set(cage, "Dot " + (id + 1) + (s.symmetry ? " (+ its mirror)" : "") + ". Shift-click between four dots for a quad.");
    return id;
  }
  function nearestVerts(x, y, maxPx, n) {
    return R.cage.v.map((p, i) => { const s = toScreen(p); return { i, d: Math.hypot(s[0] - x, s[1] - y), s }; })
      .filter((q) => q.d <= maxPx).sort((a, b) => a.d - b.d).slice(0, n);
  }
  function orderedFace(ids) {                          // counter-clockwise on screen = facing the camera
    const pts = ids.map((i) => toScreen(R.cage.v[i]));
    const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length, cy = pts.reduce((a, p) => a + p[1], 0) / pts.length;
    const ord = ids.map((i, k) => ({ i, a: Math.atan2(-(pts[k][1] - cy), pts[k][0] - cx) })).sort((p, q) => p.a - q.a).map((q) => q.i);
    return ord;
  }
  function makeFace(x, y) {
    const s = st(), near = nearestVerts(x, y, s.quadPx, 4);
    if (near.length < 3) { say("A quad needs four dots near the mouse (three for a triangle) - place more dots first.", true); return; }
    const ids = orderedFace(near.map((q) => q.i));
    let cage = ForgeRetopoCage.addFace(R.cage, ids);
    if (!cage) { say("That face is already there.", true); return; }
    if (s.symmetry) {                                  // the mirrored face, on the mirrored dots (made if missing)
      const eps = size() * 0.01;
      const mid = ids.map((i) => {
        const p = cage.v[i];
        if (Math.abs(p[0]) < 1e-9) return i;
        let m = ForgeRetopoCage.mirrorOf(cage, i, eps);
        if (m < 0) { const vn = vertNormal(cage, i); const r = ForgeRetopoCage.addVert(cage, reproject([-p[0], p[1], p[2]], vn ? [-vn[0], vn[1], vn[2]] : null)); cage = r.cage; m = r.id; }
        return m;
      });
      if (mid.some((m, k) => m !== ids[k])) { const c2 = ForgeRetopoCage.addFace(cage, mid.slice().reverse()); if (c2) cage = c2; }
    }
    set(cage, (ids.length === 4 ? "Quad" : "Triangle") + " made (" + cage.f.length + " faces).");
  }
  function faceAt(x, y) {
    for (let fi = R.cage.f.length - 1; fi >= 0; fi--) {
      const pts = R.cage.f[fi].map((i) => toScreen(R.cage.v[i]));
      let ins = false;
      for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
        const [xi, yi] = pts[i], [xj, yj] = pts[j];
        if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi || 1e-12) + xi) ins = !ins;
      }
      if (ins) return fi;
    }
    return -1;
  }
  function nearestBorder(x, y) {
    let best = null, bd = 40;
    for (const [a, b] of ForgeRetopoCage.borderEdges(R.cage)) {
      const p = toScreen(R.cage.v[a]), q = toScreen(R.cage.v[b]);
      const dx = q[0] - p[0], dy = q[1] - p[1], L = dx * dx + dy * dy || 1;
      const t = Math.max(0, Math.min(1, ((x - p[0]) * dx + (y - p[1]) * dy) / L));
      const d = Math.hypot(p[0] + dx * t - x, p[1] + dy * t - y);
      if (d < bd) { bd = d; best = [a, b]; }
    }
    return best;
  }
  function relaxAt(x, y, base) {
    const s = st(), nb = ForgeRetopoCage.neighbours(base), out = ForgeRetopoCage.copy(base);
    let moved = 0;
    base.v.forEach((p, i) => {
      const sc = toScreen(p), d = Math.hypot(sc[0] - x, sc[1] - y);
      if (d > s.relaxPx || !nb[i].size) return;
      const w = s.relaxStrength * (1 - d / s.relaxPx);
      const avg = [0, 0, 0]; for (const j of nb[i]) { avg[0] += base.v[j][0]; avg[1] += base.v[j][1]; avg[2] += base.v[j][2]; }
      const k = nb[i].size, q = [p[0] + (avg[0] / k - p[0]) * w, p[1] + (avg[1] / k - p[1]) * w, p[2] + (avg[2] / k - p[2]) * w];
      out.v[i] = snapMid(reproject(q, vertNormal(base, i))); moved++;
    });
    return { cage: out, moved };
  }

  // ---------------------------------------------------------------- the mouse in the viewport
  function onDown(e) {
    if (!R.on || e.button !== 0 || forgeCamMod(e)) return;    // Alt or Cmd: the camera
    e.preventDefault(); e.stopImmediatePropagation();
    const x = e.clientX, y = e.clientY, s = st();
    try { R.view.canvas.setPointerCapture(e.pointerId); } catch (_) { /* gone */ }
    if ((e.ctrlKey || e.metaKey) && e.shiftKey) { const fi = faceAt(x, y); if (fi >= 0) set(ForgeRetopoCage.deleteFace(R.cage, fi), "Face deleted."); return; }
    if (e.ctrlKey || e.metaKey) { const n = nearestVerts(x, y, s.snapPx, 1)[0]; if (n) set(ForgeRetopoCage.deleteVert(R.cage, n.i), "Dot deleted."); return; }
    if (R.tabHeld) {
      const edge = nearestBorder(x, y);
      if (!edge) { say("Tab + drag starts on a border edge (an edge with a face on one side only).", true); return; }
      R.drag = { kind: "extrude", edge, x, y, base: R.cage }; return;
    }
    if (e.shiftKey) { R.drag = { kind: "shift", x, y, base: R.cage, moved: false }; return; }
    const n = nearestVerts(x, y, s.snapPx, 1)[0];
    if (n) { R.drag = { kind: "move", vi: n.i, base: R.cage, moved: false }; return; }
    const h = hitAt(x, y);
    if (!h) { say("Click on the live surface to place a dot.", true); return; }
    addDot(h.p, h.n);
  }
  function onMove(e) {
    if (!R.on) return;
    R.mouse = [e.clientX, e.clientY];
    const d = R.drag;
    if (!d) { const f = e.shiftKey ? faceAt(e.clientX, e.clientY) : -1; if (f !== R.hoverFace) { R.hoverFace = f; } return; }
    e.stopImmediatePropagation();
    if (d.kind === "move") {
      const h = hitAt(e.clientX, e.clientY); if (!h) return;
      const c = ForgeRetopoCage.copy(d.base); c.v[d.vi] = snapMid(h.p);
      if (st().symmetry) { const m = ForgeRetopoCage.mirrorOf(d.base, d.vi, size() * 0.01); if (m >= 0 && m !== d.vi) c.v[m] = reproject([-c.v[d.vi][0], c.v[d.vi][1], c.v[d.vi][2]], [-h.n[0], h.n[1], h.n[2]]); }
      R.cage = c; d.moved = true; draw(); return;
    }
    if (d.kind === "shift") {
      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 5 && !d.moved) return;
      d.moved = true;
      const r = relaxAt(e.clientX, e.clientY, R.cage); R.cage = r.cage; draw(); return;
    }
    if (d.kind === "extrude") {
      const [a, b] = d.edge, base = d.base;
      const h = hitAt(e.clientX, e.clientY), h0 = hitAt(d.x, d.y);
      if (!h || !h0) return;
      const off = [h.p[0] - h0.p[0], h.p[1] - h0.p[1], h.p[2] - h0.p[2]];
      let c = ForgeRetopoCage.copy(base);
      const na = c.v.length, nb2 = na + 1;
      c.v.push(reproject([base.v[a][0] + off[0], base.v[a][1] + off[1], base.v[a][2] + off[2]]), reproject([base.v[b][0] + off[0], base.v[b][1] + off[1], base.v[b][2] + off[2]]));
      c = ForgeRetopoCage.addFace(c, [b, a, na, nb2]) || c;
      R.cage = c; d.made = true; draw();
    }
  }
  function onUp(e) {
    if (!R.on) return;
    const d = R.drag; R.drag = null;
    if (!d) return;
    e.stopImmediatePropagation();
    if (d.kind === "shift" && !d.moved) { makeFace(e.clientX, e.clientY); return; }
    if ((d.kind === "move" && d.moved) || (d.kind === "shift" && d.moved) || (d.kind === "extrude" && d.made)) {
      R.undo.push(d.base); R.redo = []; draw();
      say(d.kind === "move" ? "Dot moved." : d.kind === "shift" ? "Relaxed." : "Extruded a quad from the border edge.");
    }
  }

  // ---------------------------------------------------------------- drawing the cage over the surface
  function draw() {
    const v = R.view; if (!v) return;
    const THREE = v.THREE;
    let scene = v.holder; while (scene.parent) scene = scene.parent;
    if (!R.group) { R.group = new THREE.Group(); R.group.name = "forge-retopo"; R.group.renderOrder = 5; }
    if (R.group.parent !== scene) scene.add(R.group);
    for (const o of [...R.group.children]) { R.group.remove(o); o.geometry.dispose(); o.material.dispose(); }
    R.group.visible = R.on;
    const c = R.cage, s = st(), off = s.offset * size();
    // faces: pushed off the surface a little, see-through blue
    const tri = [];
    for (const f of c.f) for (let k = 1; k + 1 < f.length; k++) tri.push(f[0], f[k], f[k + 1]);
    const nrm = c.v.map(() => [0, 0, 0]);
    for (const f of c.f) {
      const a = c.v[f[0]], b = c.v[f[1]], d = c.v[f[2]];
      const e1 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], e2 = [d[0] - a[0], d[1] - a[1], d[2] - a[2]];
      const n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
      for (const i of f) { nrm[i][0] += n[0]; nrm[i][1] += n[1]; nrm[i][2] += n[2]; }
    }
    const pos = new Float32Array(c.v.length * 3);
    c.v.forEach((p, i) => { const n = nrm[i], l = Math.hypot(n[0], n[1], n[2]) || 1; pos.set([p[0] + n[0] / l * off, p[1] + n[1] / l * off, p[2] + n[2] / l * off], i * 3); });
    if (tri.length) {
      const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setIndex(tri);
      // drawn over the surface (a flat quad between four dots on a curved surface dips under it - the pro tool shows it anyway)
      const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: 0x3d8bff, transparent: true, opacity: 0.32, side: THREE.DoubleSide, depthWrite: false, depthTest: false }));
      m.renderOrder = 998; m.raycast = () => {}; R.group.add(m);
      const lp = [];
      for (const f of c.f) for (let k = 0; k < f.length; k++) { const a = f[k], b = f[(k + 1) % f.length]; lp.push(...pos.slice(a * 3, a * 3 + 3), ...pos.slice(b * 3, b * 3 + 3)); }
      const lg = new THREE.BufferGeometry(); lg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(lp), 3));
      const l = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0xa8d0ff, depthTest: false, transparent: true, opacity: 0.95 }));
      l.renderOrder = 999; l.raycast = () => {}; R.group.add(l);
    }
    if (c.v.length) {
      const pg = new THREE.BufferGeometry(); pg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      const pts = new THREE.Points(pg, new THREE.PointsMaterial({ color: 0xffd52e, size: 7, sizeAttenuation: false, depthTest: false }));
      pts.renderOrder = 1000; pts.raycast = () => {}; R.group.add(pts);
    }
    v.dirty = true;
    const info = R.panel && R.panel.querySelector(".frt-info");
    if (info) info.textContent = c.v.length + " dots · " + c.f.length + " faces · " + ForgeRetopoCage.borderEdges(c).length + " border edges"
      + (R.bvh ? " · surface " + R.bvh.triangles.toLocaleString() + " tris" : "");
  }

  // ---------------------------------------------------------------- start / finish
  function start() {
    const v = R.view; if (!v) return "";
    if (!pickSurface()) { say("Select the object to retopologise (a sculpt, a scan, any mesh) first.", true); return ""; }
    R.on = true; build(); R.panel.hidden = false; draw();
    return "Retopology: the live surface has " + R.bvh.triangles.toLocaleString() + " triangles (BVH in " + Math.round(R.bvhMs) + " ms). Click to place dots, Shift-click for quads.";
  }
  function stop() { R.on = false; if (R.panel) R.panel.hidden = true; draw(); return "Quad Draw off (your dots are kept until you Clear)."; }
  async function finish() {
    const v = R.view, c = R.cage;
    if (!c.f.length) { say("Draw some faces first (Shift-click between four dots).", true); return null; }
    const used = new Set(); for (const f of c.f) for (const i of f) used.add(i);
    const map = new Map(), out = { v: [], f: [] };
    c.v.forEach((p, i) => { if (used.has(i)) { map.set(i, out.v.length); out.v.push(p.slice()); } });
    out.f = c.f.map((f) => f.map((i) => map.get(i)));
    const t = v.tree && v.tree.api;
    if (t && t.newObject) t.newObject("retopo");
    if (v.mode !== "poly" && typeof forgeModelMode === "function") await forgeModelMode(true);
    if (typeof forgeModel !== "undefined") { forgeModel.prim = null; forgeModel.last = null; }
    v.showPoly(out, true);
    if (typeof forgeHistReset === "function") forgeHistReset();
    if (t && t.build) t.build(); else if (v.tree && v.tree.build) v.tree.build();
    set(ForgeRetopoCage.empty());
    say("Made a new object from " + out.f.length + " faces - UV Editing and Baking can take it from here.");
    return out;
  }

  // ---------------------------------------------------------------- the tool bar (in the viewport)
  function build() {
    if (R.panel) return R.panel;
    const stage = document.getElementById("forge-stage"); if (!stage) return null;
    const p = document.createElement("div"); p.className = "forge-retopo-bar"; p.id = "forge-retopo-bar"; p.hidden = true;
    const btn = (label, tip, fn, id) => { const b = document.createElement("button"); b.type = "button"; b.className = "fuv-btn"; b.textContent = label; b.title = tip; if (id) b.dataset.rt = id; b.addEventListener("click", (e) => { e.stopPropagation(); fn(b); }); return b; };
    const s = st();
    const sym = btn("Sym X", "Symmetry across X: every dot and face is mirrored (dots near the middle snap onto it).", (b) => { const t = st(); t.symmetry = !t.symmetry; save(t); b.classList.toggle("on", t.symmetry); say(t.symmetry ? "Symmetry X on." : "Symmetry off."); }, "sym");
    sym.classList.toggle("on", !!s.symmetry);
    const title = document.createElement("span"); title.className = "fuv-title"; title.textContent = "Quad Draw";
    title.title = "Click: dot · Shift-click: quad · Shift-drag: relax · Tab-drag a border edge: extrude · Ctrl-click: delete dot · Ctrl+Shift-click: delete face · Alt: camera";
    const num = (label, key, min, max, step) => {
      const w = document.createElement("label"); w.className = "frt-num"; w.textContent = label;
      const i = document.createElement("input"); i.type = "number"; i.min = min; i.max = max; i.step = step; i.value = String(st()[key]); i.dataset.key = key;
      i.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter" || e.key === "Escape") i.blur(); });
      i.addEventListener("change", () => { const t = st(); t[key] = isFinite(+i.value) ? +i.value : FORGE_RETOPO_DEFAULTS[key]; save(t); draw(); });
      w.append(i); return w;
    };
    const info = document.createElement("span"); info.className = "frt-info";
    const status = document.createElement("span"); status.className = "frt-status";
    p.append(title, sym, btn("Undo", "Undo the last Quad Draw step (Ctrl+Z).", undo), btn("Redo", "Redo (Ctrl+Shift+Z).", redoIt),
      btn("Surface", "Use the selected object as the live surface.", () => { if (pickSurface()) { draw(); say("New live surface: " + R.bvh.triangles.toLocaleString() + " triangles."); } else say("Select an object first.", true); }),
      btn("Clear", "Remove every dot and face.", () => set(ForgeRetopoCage.empty(), "Cleared.")),
      btn("Make Object", "Turn the faces into a new Forge object (retopo1): then UVs and baking.", () => finish(), "finish"),
      num("Relax px", "relaxPx", 10, 400, 5), num("Strength", "relaxStrength", 0.05, 1, 0.05), num("Quad reach px", "quadPx", 40, 600, 10),
      info, status);
    stage.append(p); R.panel = p;
    return p;
  }

  // ---------------------------------------------------------------- attach
  function attach(v) {
    if (R.view === v) return;
    R.view = v;
    const c = v.canvas;
    c.addEventListener("pointerdown", onDown, { capture: true });
    c.addEventListener("pointermove", onMove, { capture: true });
    c.addEventListener("pointerup", onUp, { capture: true });
    window.addEventListener("keydown", (e) => {               // window capture: before Forge's own hotkeys
      if (!R.on) return;
      if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
      if (e.key === "Tab") { R.tabHeld = true; e.preventDefault(); e.stopImmediatePropagation(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); e.stopImmediatePropagation(); if (e.shiftKey) redoIt(); else undo(); }
    }, true);
    window.addEventListener("keyup", (e) => { if (e.key === "Tab") R.tabHeld = false; }, true);
    window.addEventListener("blur", () => { R.tabHeld = false; });
  }
  setInterval(() => { const v = typeof forge !== "undefined" && forge.view; if (v && v !== R.view && v.canvas) attach(v); }, 400);

  return { start, stop, finish, undo, redo: redoIt, state: R, attach, draw, makeFace, addDot, relaxAt, hitAt, toScreen };
})();

if (typeof FORGE_PRO_CMDS !== "undefined") {
  if (!FORGE_PRO_CMDS.quadDraw) FORGE_PRO_CMDS.quadDraw = ["Quad Draw (Retopology)", () => (ForgeRetopo.state.on ? ForgeRetopo.stop() : ForgeRetopo.start())];
  if (!FORGE_PRO_CMDS.retopoFinish) FORGE_PRO_CMDS.retopoFinish = ["Make Object from Quad Draw", () => ForgeRetopo.finish()];
}
