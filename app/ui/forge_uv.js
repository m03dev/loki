// Forge's UV system (owner 2026-10-21: "camera based, then select edges, cut, select UV shell, unfold and layout ...
// make sure you have settings, everything should be modular, make a real system not just placeholders").
//
// The data model is the pro tool's "map UVs": a modelled cage {v, f} gains
//     uv:  [[u, v], ...]          the UV points
//     fuv: [[uvIndex, ...], ...]  per face, one UV index per corner (parallel to f)
// Two faces that meet at an edge but use different UV indices there have a SEAM (a UV border); a SHELL is a set of
// faces connected through shared UV indices. Everything here is plain functions on that data - every operation
// returns a NEW cage (copy) and leaves the old one untouched, so Forge's undo (which keeps cages) just works. The
// heavy maths (unfold = LSCM + an area-preserving optimisation, layout = shell packing) runs in LOKI's C++ engine
// in its own worker (window.ForgeGeom: uvUnfold / uvLayout); the rest is here.
//
// The GPU mesh of a cage is one vertex per face corner (forge.js showPoly), so cornerUVs() gives it seams for free.
"use strict";

window.ForgeUV = (() => {
  const EPS = 1e-9;
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const len = (a) => Math.hypot(a[0], a[1], a[2]);
  const norm = (a) => { const l = len(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
  const ekey = (a, b) => (a < b ? a + "," + b : b + "," + a);

  // ------------------------------------------------------------------ basics
  const has = (m) => !!(m && Array.isArray(m.uv) && Array.isArray(m.fuv) && m.fuv.length === m.f.length
    && m.fuv.every((c, i) => c && c.length === m.f[i].length && c.every((x) => x >= 0 && x < m.uv.length)));
  function clone(m) {
    const out = { v: m.v.map((p) => p.slice()), f: m.f.map((f) => f.slice()) };
    for (const k of Object.keys(m)) if (!(k in out) && k !== "uv" && k !== "fuv") out[k] = m[k];
    if (has(m)) { out.uv = m.uv.map((p) => p.slice()); out.fuv = m.fuv.map((c) => c.slice()); }
    return out;
  }
  function faceNormal(m, f) {                       // Newell's method: robust for n-gons
    let n = [0, 0, 0];
    for (let k = 0; k < f.length; k++) {
      const a = m.v[f[k]], b = m.v[f[(k + 1) % f.length]];
      n[0] += (a[1] - b[1]) * (a[2] + b[2]); n[1] += (a[2] - b[2]) * (a[0] + b[0]); n[2] += (a[0] - b[0]) * (a[1] + b[1]);
    }
    return norm(n);
  }
  function faceArea3(m, f) {
    let s = 0;
    for (let k = 1; k + 1 < f.length; k++) s += len(cross(sub(m.v[f[k]], m.v[f[0]]), sub(m.v[f[k + 1]], m.v[f[0]]))) / 2;
    return s;
  }
  function faceAreaUV(m, fi) {                      // signed: > 0 counter-clockwise (front-facing in UV space)
    const c = m.fuv[fi]; let s = 0;
    for (let k = 0; k < c.length; k++) { const a = m.uv[c[k]], b = m.uv[c[(k + 1) % c.length]]; s += a[0] * b[1] - b[0] * a[1]; }
    return s / 2;
  }
  // the corners' UVs in showPoly's corner order (face after face) - what the GPU mesh gets
  function cornerUVs(m) {
    if (!has(m)) return null;
    let n = 0; for (const f of m.f) n += f.length;
    const out = new Float32Array(n * 2); let c = 0;
    m.fuv.forEach((ix) => { for (const i of ix) { out[c++] = m.uv[i][0]; out[c++] = m.uv[i][1]; } });
    return out;
  }

  // ------------------------------------------------------------------ topology of the UVs
  // every geometric edge with the faces on it, and whether it is a UV seam (or an open border)
  function edges(m) {
    const map = new Map();
    m.f.forEach((f, fi) => {
      for (let k = 0; k < f.length; k++) {
        const a = f[k], b = f[(k + 1) % f.length], key = ekey(a, b);
        let e = map.get(key);
        if (!e) map.set(key, (e = { a: Math.min(a, b), b: Math.max(a, b), uses: [] }));
        e.uses.push({ fi, k });
      }
    });
    if (has(m)) for (const e of map.values()) {
      if (e.uses.length !== 2) { e.seam = true; continue; }
      const uvAt = (u, vert) => { const f = m.f[u.fi], c = m.fuv[u.fi]; const k = f[u.k] === vert ? u.k : (u.k + 1) % f.length; return c[k]; };
      e.seam = uvAt(e.uses[0], e.a) !== uvAt(e.uses[1], e.a) || uvAt(e.uses[0], e.b) !== uvAt(e.uses[1], e.b);
    }
    return map;
  }
  function seams(m) { const out = new Set(); for (const [k, e] of edges(m)) if (e.seam) out.add(k); return out; }

  // shells: faces connected through shared UV indices
  function shells(m) {
    if (!has(m)) return [];
    const parent = m.uv.map((_, i) => i);
    const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
    for (const c of m.fuv) for (let k = 1; k < c.length; k++) { const a = find(c[0]), b = find(c[k]); if (a !== b) parent[a] = b; }
    const by = new Map();
    m.fuv.forEach((c, fi) => { const r = find(c[0]); if (!by.has(r)) by.set(r, { faces: [], uvs: new Set() }); const s = by.get(r); s.faces.push(fi); for (const i of c) s.uvs.add(i); });
    return [...by.values()].map((s, id) => Object.assign(s, { id }));
  }
  function shellOfFace(m, fi) { return shells(m).find((s) => s.faces.includes(fi)) || null; }

  // Rebuild the UV indices from a set of seam edges ("a,b"): around every vertex, the face corners that are joined
  // through non-seam edges share one UV index; corners split by a seam get their own. A wedge keeps the UV value
  // its corners had (the first corner's when they differed - a sew), so a cut never moves anything.
  function rebuild(m, seamSet) {
    const out = clone(m);
    if (!has(m)) return out;
    const E = edges(m);
    // corner id = flat index; union corners of the same vertex across non-seam edges
    const start = []; let n = 0; for (const f of m.f) { start.push(n); n += f.length; }
    const parent = new Int32Array(n).map((_, i) => i);
    const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
    const join = (a, b) => { a = find(a); b = find(b); if (a !== b) parent[a] = b; };
    for (const [key, e] of E) {
      if (seamSet.has(key) || e.uses.length !== 2) continue;
      const [u0, u1] = e.uses;
      const cornerOf = (u, vert) => { const f = m.f[u.fi]; return start[u.fi] + (f[u.k] === vert ? u.k : (u.k + 1) % f.length); };
      join(cornerOf(u0, e.a), cornerOf(u1, e.a)); join(cornerOf(u0, e.b), cornerOf(u1, e.b));
    }
    const idOf = new Map(); out.uv = []; out.fuv = m.f.map((f) => new Array(f.length));
    m.f.forEach((f, fi) => {
      for (let k = 0; k < f.length; k++) {
        const r = find(start[fi] + k);
        let id = idOf.get(r);
        if (id === undefined) { id = out.uv.length; idOf.set(r, id); out.uv.push(m.uv[m.fuv[fi][k]].slice()); }
        out.fuv[fi][k] = id;
      }
    });
    return out;
  }
  // Cut UV edges: the edges become seams (pairs of vertex indices)
  function cut(m, pairs) { if (!has(m)) return clone(m); const s = seams(m); for (const [a, b] of pairs) s.add(ekey(a, b)); return rebuild(m, s); }
  // Sew UV edges: the edges stop being seams; the joined UV points meet in the middle
  function sew(m, pairs) {
    if (!has(m)) return clone(m);
    const s = seams(m), E = edges(m), mid = [];
    for (const [a, b] of pairs) {
      const key = ekey(a, b), e = E.get(key);
      if (!e || e.uses.length !== 2) continue;
      s.delete(key);
      for (const vert of [e.a, e.b]) {
        const ids = e.uses.map((u) => { const f = m.f[u.fi]; return m.fuv[u.fi][f[u.k] === vert ? u.k : (u.k + 1) % f.length]; });
        if (ids[0] !== ids[1]) mid.push(ids);
      }
    }
    const w = clone(m);
    for (const [i, j] of mid) { const p = [(w.uv[i][0] + w.uv[j][0]) / 2, (w.uv[i][1] + w.uv[j][1]) / 2]; w.uv[i] = p.slice(); w.uv[j] = p.slice(); }
    return rebuild(w, s);
  }
  // Move and Sew: sew, but move the smaller shell onto the bigger one first (no stretched middle)
  function moveAndSew(m, pairs) {
    if (!has(m) || !pairs.length) return sew(m, pairs);
    const E = edges(m), e = E.get(ekey(pairs[0][0], pairs[0][1]));
    if (!e || e.uses.length !== 2) return sew(m, pairs);
    const sh = shells(m), sa = sh.find((s) => s.faces.includes(e.uses[0].fi)), sb = sh.find((s) => s.faces.includes(e.uses[1].fi));
    if (!sa || !sb || sa === sb) return sew(m, pairs);
    const [big, small, ub, us] = sa.faces.length >= sb.faces.length ? [sa, sb, e.uses[0], e.uses[1]] : [sb, sa, e.uses[1], e.uses[0]];
    const at = (u, vert) => { const f = m.f[u.fi]; return m.fuv[u.fi][f[u.k] === vert ? u.k : (u.k + 1) % f.length]; };
    const A0 = m.uv[at(ub, e.a)], A1 = m.uv[at(ub, e.b)], B0 = m.uv[at(us, e.a)], B1 = m.uv[at(us, e.b)];
    // the similarity that takes the small shell's edge (B0 -> B1) onto the big one's (A0 -> A1)
    const ax = A1[0] - A0[0], ay = A1[1] - A0[1], bx = B1[0] - B0[0], by = B1[1] - B0[1];
    const bl = bx * bx + by * by || EPS;
    const c = (ax * bx + ay * by) / bl, s = (ay * bx - ax * by) / bl;
    const w = clone(m);
    for (const i of small.uvs) {
      const x = m.uv[i][0] - B0[0], y = m.uv[i][1] - B0[1];
      w.uv[i] = [A0[0] + c * x - s * y, A0[1] + s * x + c * y];
    }
    void big;
    return sew(w, pairs);
  }

  // ------------------------------------------------------------------ projections (each makes the faces one shell)
  // faces: the face indices to project (all when empty). The projected faces get fresh UV indices shared among
  // themselves, so they become one shell, cut off from the rest.
  function assign(m, faces, uvOfVert) {
    const out = has(m) ? clone(m) : Object.assign(clone(m), { uv: [], fuv: m.f.map(() => null) });
    const set = new Set(faces && faces.length ? faces : m.f.map((_, i) => i));
    const ids = new Map();
    for (const fi of set) {
      out.fuv[fi] = m.f[fi].map((vert) => {
        if (!ids.has(vert)) { ids.set(vert, out.uv.length); out.uv.push(uvOfVert(vert, fi)); }
        return ids.get(vert);
      });
    }
    // faces never given UVs yet (no UVs before this): a quick planar map so the cage is always valid
    out.fuv.forEach((c, fi) => { if (!c) out.fuv[fi] = m.f[fi].map((vert) => { out.uv.push(planarAuto(m, vert, faceNormal(m, m.f[fi]))); return out.uv.length - 1; }); });
    return compact(out);
  }
  const basisFor = (n) => {                       // two axes across a direction
    const up = Math.abs(n[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
    const u = norm(cross(up, n)), v = cross(n, u);
    return [u, v];
  };
  const planarAuto = (m, vert, n) => { const [u, v] = basisFor(n); const p = m.v[vert]; return [dot(p, u), dot(p, v)]; };
  function fitUnit(m, faces, pad) {               // scale + move the given faces' UVs into the 0-1 square, keeping proportions
    const ids = new Set(); for (const fi of faces) for (const i of m.fuv[fi]) ids.add(i);
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const i of ids) { const p = m.uv[i]; x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); }
    const s = (1 - 2 * (pad || 0)) / Math.max(x1 - x0, y1 - y0, EPS), ox = (1 - (x1 - x0) * s) / 2, oy = (1 - (y1 - y0) * s) / 2;
    for (const i of ids) m.uv[i] = [ox + (m.uv[i][0] - x0) * s, oy + (m.uv[i][1] - y0) * s];
    return m;
  }
  function facesOr(m, faces) { return faces && faces.length ? faces : m.f.map((_, i) => i); }

  // planar along an axis ("x" | "y" | "z") or the faces' average normal ("best")
  function planar(m, faces, axis) {
    faces = facesOr(m, faces);
    let n;
    if (axis === "x") n = [1, 0, 0]; else if (axis === "y") n = [0, 1, 0]; else if (axis === "z") n = [0, 0, 1];
    else { n = [0, 0, 0]; for (const fi of faces) { const fn = faceNormal(m, m.f[fi]), a = faceArea3(m, m.f[fi]); n = [n[0] + fn[0] * a, n[1] + fn[1] * a, n[2] + fn[2] * a]; } n = len(n) > EPS ? norm(n) : [0, 0, 1]; }
    const [u, v] = axis === "x" ? [[0, 0, -1], [0, 1, 0]] : axis === "y" ? [[1, 0, 0], [0, 0, -1]] : axis === "z" ? [[1, 0, 0], [0, 1, 0]] : basisFor(n);
    return fitUnit(assign(m, faces, (vert) => { const p = m.v[vert]; return [dot(p, u), dot(p, v)]; }), faces.map((fi) => fi), 0.02);
  }
  // camera-based: what the camera sees - each vertex projected to the screen. toScreen(p) -> [x, y] (any units,
  // y up); the result is fit into 0-1 keeping the screen's proportions
  function camera(m, faces, toScreen) {
    faces = facesOr(m, faces);
    return fitUnit(assign(m, faces, (vert) => toScreen(m.v[vert])), faces, 0.02);
  }
  function cylindrical(m, faces, axis) {
    faces = facesOr(m, faces);
    const ax = axis === "x" ? 0 : axis === "z" ? 2 : 1, a1 = (ax + 1) % 3, a2 = (ax + 2) % 3;
    const c = centroidOf(m, faces);
    const out = assign(m, faces, (vert) => { const p = m.v[vert]; return [0.5 + Math.atan2(p[a2] - c[a2], p[a1] - c[a1]) / (2 * Math.PI), p[ax]]; });
    unwrapSeam(out, faces, 0);
    return fitUnit(out, faces, 0.02);
  }
  function spherical(m, faces) {
    faces = facesOr(m, faces);
    const c = centroidOf(m, faces);
    const out = assign(m, faces, (vert) => { const d = norm(sub(m.v[vert], c)); return [0.5 + Math.atan2(d[2], d[0]) / (2 * Math.PI), 0.5 + Math.asin(Math.max(-1, Math.min(1, d[1]))) / Math.PI]; });
    unwrapSeam(out, faces, 0);
    return fitUnit(out, faces, 0.02);
  }
  // a face that straddles the wrap-around (u jumps by more than half) gets its own UVs on the far side
  function unwrapSeam(m, faces, comp) {
    for (const fi of faces) {
      const c = m.fuv[fi], us = c.map((i) => m.uv[i][comp]);
      if (Math.max(...us) - Math.min(...us) <= 0.5) continue;
      m.fuv[fi] = c.map((i) => { const p = m.uv[i].slice(); if (p[comp] < 0.5) p[comp] += 1; m.uv.push(p); return m.uv.length - 1; });
    }
  }
  function centroidOf(m, faces) {
    const c = [0, 0, 0]; let n = 0;
    for (const fi of faces) for (const vert of m.f[fi]) { c[0] += m.v[vert][0]; c[1] += m.v[vert][1]; c[2] += m.v[vert][2]; n++; }
    return n ? [c[0] / n, c[1] / n, c[2] / n] : c;
  }
  // automatic: faces grouped by the closest of `planes` directions (6 = the box), each group planar-projected into
  // its own shell; the caller lays them out after (Layout)
  function automatic(m, faces, planes) {
    faces = facesOr(m, faces);
    const dirs = planes === 3 ? [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
      : planes === 4 ? [[1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1]]
        : [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
    const groups = dirs.map(() => []);
    for (const fi of faces) {
      const n = faceNormal(m, m.f[fi]); let best = 0, bd = -Infinity;
      dirs.forEach((d, i) => { const s = planes === 3 ? Math.abs(dot(n, d)) : dot(n, d); if (s > bd) { bd = s; best = i; } });
      groups[best].push(fi);
    }
    let out = has(m) ? m : null;
    for (let g = 0; g < dirs.length; g++) {
      if (!groups[g].length) continue;
      const [u, v] = basisFor(dirs[g]);
      out = assign(out || m, groups[g], (vert) => { const p = m.v[vert]; return [dot(p, u), dot(p, v)]; });
      // each group: its own shells per connected patch (split where faces of the group do not touch)
      out = splitDisconnected(out, groups[g]);
    }
    return out || clone(m);
  }
  // faces of one projection that do not touch each other become separate shells
  function splitDisconnected(m, faces) {
    const set = new Set(faces), s = seams(m), E = edges(m);
    for (const [key, e] of E) if (e.uses.length === 2 && set.has(e.uses[0].fi) !== set.has(e.uses[1].fi)) s.add(key);
    return rebuild(m, s);
  }
  // drop UV points no face uses (after projections), renumbering
  function compact(m) {
    const used = new Map(), uv = [];
    m.fuv = m.fuv.map((c) => c.map((i) => { if (!used.has(i)) { used.set(i, uv.length); uv.push(m.uv[i]); } return used.get(i); }));
    m.uv = uv;
    return m;
  }

  // ------------------------------------------------------------------ UV points: split, merge (Maya's UV > Split UVs /
  // Merge UVs). ids: UV point ids.
  // Split: a UV point shared by several face corners becomes one point per corner (the faces come apart there in UV).
  function splitUVs(m, ids) {
    if (!has(m)) return clone(m);
    const out = clone(m), want = new Set(ids), seen = new Set();
    out.fuv.forEach((c, fi) => {
      for (let k = 0; k < c.length; k++) {
        const i = c[k];
        if (!want.has(i)) continue;
        if (!seen.has(i)) { seen.add(i); continue; }          // the first corner keeps the point
        out.uv.push(out.uv[i].slice()); c[k] = out.uv.length - 1;
      }
    });
    return out;
  }
  // Merge: picked UV points closer than dist (in UV space) become one, at their middle. Maya's default is 0.01.
  function mergeUVs(m, ids, dist) {
    if (!has(m)) return clone(m);
    const d = dist == null ? 0.01 : +dist, list = [...new Set(ids)].filter((i) => i >= 0 && i < m.uv.length);
    const parent = new Map(list.map((i) => [i, i]));
    const find = (x) => { while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); } return x; };
    // a grid in UV space so a big pick is not n^2
    const cell = Math.max(d, 1e-6), grid = new Map(), key = (a, b) => a + "," + b;
    for (const i of list) { const p = m.uv[i], k = key(Math.floor(p[0] / cell), Math.floor(p[1] / cell)); if (!grid.has(k)) grid.set(k, []); grid.get(k).push(i); }
    for (const i of list) {
      const p = m.uv[i], gx = Math.floor(p[0] / cell), gy = Math.floor(p[1] / cell);
      for (let x = gx - 1; x <= gx + 1; x++) for (let y = gy - 1; y <= gy + 1; y++) for (const j of grid.get(key(x, y)) || []) {
        if (j <= i) continue;
        const q = m.uv[j];
        if (Math.hypot(p[0] - q[0], p[1] - q[1]) <= d) { const a = find(i), b = find(j); if (a !== b) parent.set(a, b); }
      }
    }
    const groups = new Map();
    for (const i of list) { const r = find(i); if (!groups.has(r)) groups.set(r, []); groups.get(r).push(i); }
    const out = clone(m), to = new Map();
    for (const g of groups.values()) {
      if (g.length < 2) continue;
      const c = [0, 0]; for (const i of g) { c[0] += m.uv[i][0]; c[1] += m.uv[i][1]; }
      out.uv[g[0]] = [c[0] / g.length, c[1] / g.length];
      for (const i of g.slice(1)) to.set(i, g[0]);
    }
    if (!to.size) return out;
    out.fuv = out.fuv.map((c) => c.map((i) => (to.has(i) ? to.get(i) : i)));
    return compact(out);
  }
  // Delete UVs: the mesh without UVs (Forge keeps UVs for every face or none)
  function deleteUVs(m) { const out = clone(m); delete out.uv; delete out.fuv; delete out.uvPins; out.uvDropped = true; return out; }   // uvDropped: showPoly must not carry the old UVs back

  // ------------------------------------------------------------------ transforms in UV space  // ------------------------------------------------------------------ transforms in UV space
  function uvsOfFaces(m, faces) { const s = new Set(); for (const fi of faces) for (const i of m.fuv[fi]) s.add(i); return s; }
  function bbox(m, ids) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const i of ids) { const p = m.uv[i]; x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); }
    return { x0, y0, x1, y1, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 };
  }
  // move by (du, dv), rotate by deg about (px, py), scale by (sx, sy) about (px, py) - on the given UV indices
  function transform(m, ids, t) {
    const out = clone(m), list = [...ids];
    const b = bbox(m, list), px = t.pivot ? t.pivot[0] : b.cx, py = t.pivot ? t.pivot[1] : b.cy;
    const r = ((t.rotate || 0) * Math.PI) / 180, c = Math.cos(r), s = Math.sin(r), sx = t.scale ? t.scale[0] : 1, sy = t.scale ? t.scale[1] : 1;
    for (const i of list) {
      let x = (m.uv[i][0] - px) * sx, y = (m.uv[i][1] - py) * sy;
      [x, y] = [x * c - y * s, x * s + y * c];
      out.uv[i] = [x + px + (t.move ? t.move[0] : 0), y + py + (t.move ? t.move[1] : 0)];
    }
    return out;
  }
  function flip(m, ids, axis) { return transform(m, ids, { scale: axis === "v" ? [1, -1] : [-1, 1] }); }

  // ------------------------------------------------------------------ measures
  // texel density (pixels per 3D unit) of faces at a texture resolution
  function density(m, faces, res) {
    let a3 = 0, a2 = 0;
    for (const fi of facesOr(m, faces)) { a3 += faceArea3(m, m.f[fi]); a2 += Math.abs(faceAreaUV(m, fi)); }
    return a3 > EPS ? Math.sqrt(a2 / a3) * (res || 1024) : 0;
  }
  // set the texel density of each shell touched by the faces (each shell scaled about its own centre)
  function setDensity(m, faces, target, res) {
    let out = clone(m);
    const touched = new Set(facesOr(m, faces));
    for (const sh of shells(m)) {
      if (!sh.faces.some((fi) => touched.has(fi))) continue;
      const d = density(m, sh.faces, res);
      if (d <= EPS) continue;
      const k = target / d;
      out = transform(out, sh.uvs, { scale: [k, k] });
    }
    return out;
  }
  // per face: stretch (1 = none; area ratio against the mesh's average) and flipped (back-facing in UV)
  function distortion(m) {
    if (!has(m)) return null;
    let A3 = 0, A2 = 0; const a3 = [], a2 = [];
    m.f.forEach((f, fi) => { const x = faceArea3(m, f), y = faceAreaUV(m, fi); a3.push(x); a2.push(y); A3 += x; A2 += Math.abs(y); });
    const k = A3 > EPS ? A2 / A3 : 1;
    return m.f.map((_, fi) => ({ stretch: a3[fi] > EPS ? Math.abs(a2[fi]) / (a3[fi] * k || EPS) : 1, flipped: a2[fi] < 0 }));
  }
  function overlapCount(m) {                       // faces whose UV box overlaps another shell's (quick check)
    const sh = shells(m), boxes = sh.map((s) => bbox(m, s.uvs));
    let n = 0;
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.x0 < b.x1 - 1e-6 && b.x0 < a.x1 - 1e-6 && a.y0 < b.y1 - 1e-6 && b.y0 < a.y1 - 1e-6) n++;
    }
    return n;
  }

  // ------------------------------------------------------------------ keeping UVs through modelling
  // A modelling step makes a new cage without UVs. Faces that are still there (same vertices, by index - or by
  // position when the step renumbered them) keep theirs; new faces get a planar map of their own and are listed in
  // `uvNew` so the UV Editor can say so. Returns the new cage with UVs (or the cage itself when the old had none).
  function carry(old, next) {
    if (!has(old) || has(next) || !next || !next.f) return next;
    const keyIdx = (f) => f.slice().sort((a, b) => a - b).join(",");
    const r = (p) => p.map((x) => Math.round(x * 1e5)).join(":");
    const keyPos = (mm, f) => f.map((i) => r(mm.v[i])).sort().join("|");
    const byIdx = new Map(), byPos = new Map();
    old.f.forEach((f, fi) => { byIdx.set(keyIdx(f), fi); byPos.set(keyPos(old, f), fi); });
    const useIdx = next.v.length >= old.v.length;   // indices kept when the step only added vertices
    const uv = [], fuv = [], seen = new Map(), fresh = [];
    next.f.forEach((f, fi) => {
      let src = useIdx ? byIdx.get(keyIdx(f)) : undefined;
      if (src !== undefined && !f.every((vert) => old.f[src].includes(vert))) src = undefined;
      if (src === undefined) src = byPos.get(keyPos(next, f));
      if (src !== undefined) {
        const of = old.f[src];
        fuv.push(f.map((vert, k) => {
          let j = useIdx ? of.indexOf(vert) : -1;
          if (j < 0) j = of.findIndex((ov) => r(old.v[ov]) === r(next.v[vert]));
          const oi = old.fuv[src][j >= 0 ? j : k % of.length];
          const key = vert + "@" + oi;                    // the old UV point (per vertex): the seams stay exactly where they were
          if (!seen.has(key)) { seen.set(key, uv.length); uv.push(old.uv[oi].slice()); }
          return seen.get(key);
        }));
      } else {
        fresh.push(fi);
        const n = faceNormal(next, f);
        fuv.push(f.map((vert) => { uv.push(planarAuto(next, vert, n)); return uv.length - 1; }));
      }
    });
    // most faces new = a different object (Create, switching the edited object), not a modelling step: no UVs
    if (fresh.length > next.f.length * 0.5) return next;
    const out = Object.assign({}, next, { uv, fuv });
    if (fresh.length) { fitUnit(out, fresh, 0); for (const fi of fresh) for (const i of out.fuv[fi]) out.uv[i] = [out.uv[i][0] * 0.2 + 1.05, out.uv[i][1] * 0.2]; }
    out.uvNew = fresh;
    return out;
  }

  // ------------------------------------------------------------------ the C++ engine: unfold and layout
  function flat(m) {
    const pos = new Float32Array(m.v.length * 3); m.v.forEach((p, i) => pos.set(p, i * 3));
    let n = 0; for (const f of m.f) n += f.length;
    const sizes = new Int32Array(m.f.length), fv = new Int32Array(n), fuv = new Int32Array(n);
    let c = 0;
    m.f.forEach((f, fi) => { sizes[fi] = f.length; for (let k = 0; k < f.length; k++) { fv[c] = f[k]; fuv[c] = m.fuv[fi][k]; c++; } });
    const uv = new Float32Array(m.uv.length * 2); m.uv.forEach((p, i) => { uv[i * 2] = p[0]; uv[i * 2 + 1] = p[1]; });
    return { pos, sizes, fv, fuv, uv };
  }
  // the sub-cage of some faces (the engine works on what it is given; untouched UVs come back unchanged)
  function sub_(m, faces) {
    const fs = facesOr(m, faces);
    return { v: m.v, f: fs.map((fi) => m.f[fi]), fuv: fs.map((fi) => m.fuv[fi]), uv: m.uv };
  }
  function applyUV(m, arr) { const out = clone(m); for (let i = 0; i < out.uv.length; i++) out.uv[i] = [arr[i * 2], arr[i * 2 + 1]]; return out; }

  // Unfold the shells of `faces` (all when empty). opts: {iterations, pinned: Set of UV ids, scaleToDensity}
  async function unfold(m, faces, opts) {
    if (!has(m)) throw new Error("No UVs yet - project first (Create UVs > Camera-based, Planar ... or Automatic).");
    const G = window.ForgeGeom;
    if (!G || !G.uvUnfold) throw new Error("The C++ engine is not available here, so Unfold cannot run.");
    const sh = shells(m), want = new Set(facesOr(m, faces)), fs = [];
    for (const s of sh) if (s.faces.some((fi) => want.has(fi))) fs.push(...s.faces);
    const F = flat(sub_(m, fs));
    let pinned = null;
    if (opts && opts.pinned && opts.pinned.size) { pinned = new Uint8Array(m.uv.length); for (const i of opts.pinned) if (i < pinned.length) pinned[i] = 1; }
    const r = await G.uvUnfold(F, { pinned, iterations: opts && opts.iterations != null ? opts.iterations : 6, scaleToDensity: (opts && opts.scaleToDensity) || 1 });
    if (!r) throw new Error("The C++ engine could not unfold this" + (G.lastError ? ": " + G.lastError : "."));
    const out = applyUV(m, r.uv);
    out.uvInfo = { shells: r.shells, flips: r.flips, stretch: r.stretch, ms: r.ms };
    return out;
  }
  // A plain shelf packer in JS - what Layout does when the C++ engine is not there (an older build, WebAssembly
  // blocked): each shell's bounding box (optionally turned 90 degrees to lie flat), uniform texel density, sorted by
  // height, rows across a square, then scaled into 0-1. Not as tight as the engine's packer, but never overlapping.
  function layoutBasic(m, faces, opts) {
    const o = Object.assign({ paddingPx: 4, resolution: 1024, rotate: 1, scaleMode: 1, margin: 0.005 }, opts || {});
    const want = new Set(facesOr(m, faces));
    let out = clone(m);
    const list = shells(out).filter((sh) => sh.faces.some((fi) => want.has(fi)));
    if (!list.length) return out;
    if (o.scaleMode === 1) {                       // the same pixels per 3D unit on every shell
      const ref = density(out, list.flatMap((sh) => sh.faces), 1);
      for (const sh of list) { const d = density(out, sh.faces, 1); if (d > EPS) out = transform(out, sh.uvs, { scale: [ref / d, ref / d] }); }
    }
    const boxes = list.map((sh) => {
      let b = bbox(out, sh.uvs);
      if (o.rotate && b.y1 - b.y0 > b.x1 - b.x0) { out = transform(out, sh.uvs, { rotate: 90 }); b = bbox(out, sh.uvs); }
      return { sh, b, w: b.x1 - b.x0, h: b.y1 - b.y0 };
    });
    const area = boxes.reduce((a, x) => a + x.w * x.h, 0), side = Math.sqrt(area) * 1.15 || 1;
    const gap = (o.paddingPx / o.resolution) * side;
    boxes.sort((a, b) => b.h - a.h);
    let x = 0, y = 0, row = 0, W = 0;
    for (const bx of boxes) {
      if (x > 0 && x + bx.w > side) { x = 0; y += row + gap; row = 0; }
      out = transform(out, bx.sh.uvs, { move: [x - bx.b.x0, y - bx.b.y0] });
      x += bx.w + gap; row = Math.max(row, bx.h); W = Math.max(W, x);
    }
    const H = y + row, span = Math.max(W, H, EPS), k = (1 - 2 * o.margin) / span;
    const ids = new Set(); for (const bx of boxes) for (const i of bx.sh.uvs) ids.add(i);
    for (const i of ids) out.uv[i] = [o.margin + out.uv[i][0] * k, o.margin + out.uv[i][1] * k];
    out.uvInfo = { shells: boxes.length, basic: true };
    return out;
  }
  // Layout the shells of `faces` (all when empty) into 0-1. opts: {paddingPx, resolution, rotate, scaleMode, margin}
  async function layout(m, faces, opts) {
    if (!has(m)) throw new Error("No UVs yet - project first.");
    const G = window.ForgeGeom;
    if (!G || !G.uvLayout || (G.supports && G.state === "on" && !G.supports("uvLayout"))) return layoutBasic(m, faces, opts);
    const sh = shells(m), want = new Set(facesOr(m, faces)), fs = [];
    for (const s of sh) if (s.faces.some((fi) => want.has(fi))) fs.push(...s.faces);
    const r = await G.uvLayout(flat(sub_(m, fs)), opts || {});
    if (!r && G.supports && !G.supports("uvLayout")) return layoutBasic(m, faces, opts);   // an engine build without it
    if (!r) throw new Error("The C++ engine could not lay this out" + (G.lastError ? ": " + G.lastError : "."));
    const out = applyUV(m, r.uv);
    out.uvInfo = { shells: r.shells, ms: r.ms };
    return out;
  }

  // fully automatic UVs with xatlas (C++): new charts, seams, unfold and packing in one go
  async function autoAtlas(m, opts) {
    const G = window.ForgeGeom;
    if (!G || !G.uvAuto) throw new Error("The C++ engine is not available here.");
    const base = has(m) ? m : Object.assign(clone(m), { uv: [[0, 0]], fuv: m.f.map((f) => f.map(() => 0)) });
    const r = await G.uvAuto(flat(base), opts || {});
    if (!r) throw new Error("The C++ engine could not unwrap this" + (G.lastError ? ": " + G.lastError : "."));
    const out = clone(m); out.uv = []; for (let i = 0; i < r.uv.length; i += 2) out.uv.push([r.uv[i], r.uv[i + 1]]);
    let c = 0; out.fuv = m.f.map((f) => f.map(() => r.fuv[c++]));
    out.uvInfo = { charts: r.charts, ms: r.ms };
    return out;
  }
  // OptCuts (C++ -> WebAssembly, its own worker, app/ui/vendor/optcuts): seams and the unfold optimised together - the
  // shortest seams that keep the distortion under a bound, no overlaps. opts: {distortionBound (4.1 = little stretch,
  // up to ~5 = fewer seams), timeBudgetMs, seed, useBijectivity}; onProgress({iter, distortion, phase}).
  let ocWorker = null, ocSeq = 0;
  const ocWait = new Map();
  function ocStart() {
    if (ocWorker) return ocWorker;
    ocWorker = new Worker("/ui/vendor/optcuts/optcuts_worker.js");
    ocWorker.onmessage = (ev) => {
      const r = ev.data || {}, w = ocWait.get(r.seq);
      if (r.t === "fail" && r.seq == null) { for (const x of ocWait.values()) x.reject(new Error(r.error || "OptCuts did not load")); ocWait.clear(); return; }
      if (!w) return;
      if (r.t === "progress") { if (w.onProgress) w.onProgress(r); return; }
      ocWait.delete(r.seq);
      if (r.t === "optcuts") w.resolve(r); else w.reject(new Error(r.error || "OptCuts failed"));
    };
    ocWorker.onerror = (e) => { for (const x of ocWait.values()) x.reject(new Error("OptCuts worker: " + (e.message || "error"))); ocWait.clear(); ocWorker = null; };
    return ocWorker;
  }
  function optcutsCancel() { if (ocWorker) for (const seq of ocWait.keys()) ocWorker.postMessage({ t: "cancel", seq }); }
  async function optcuts(m, opts, onProgress) {
    if (typeof Worker === "undefined") throw new Error("OptCuts needs Web Workers.");
    const pos = new Float32Array(m.v.length * 3); m.v.forEach((p, i) => pos.set(p, i * 3));
    const tris = [], cornerOf = [];                    // tri corner -> [face, k]
    m.f.forEach((f, fi) => { for (let k = 1; k + 1 < f.length; k++) { tris.push(f[0], f[k], f[k + 1]); cornerOf.push([fi, 0], [fi, k], [fi, k + 1]); } });
    const w = ocStart(), seq = ++ocSeq;
    const r = await new Promise((resolve, reject) => {
      ocWait.set(seq, { resolve, reject, onProgress });
      w.postMessage({ t: "optcuts", seq, pos, tris: Int32Array.from(tris), opts: Object.assign({ distortionBound: 4.1, useBijectivity: 1, timeBudgetMs: 20000, seed: 1 }, opts || {}) });
    });
    if (!r.ok) throw new Error(r.error || "OptCuts found no map.");
    // OptCuts works on triangles and may cut along a quad's diagonal, which a polygon cage cannot hold: such a seam is
    // moved onto the polygon's border (below). The C++ unfold then flattens the shells.
    const polyEdges = new Set(); for (const f of m.f) for (let k = 0; k < f.length; k++) polyEdges.add(ekey(f[k], f[(k + 1) % f.length]));
    const pairs = []; let diag = 0;
    // a seam across a polygon (a diagonal a-c of a b c d) is moved onto the polygon's border: a-b-c or a-d-c, whichever
    // is shorter - the cut keeps its path (so a torus cut into a disk stays a disk), it just follows the edge flow
    const faceOf = new Map(); m.f.forEach((f, fi) => { for (let i = 0; i < f.length; i++) for (let j = i + 2; j < f.length; j++) if (!(i === 0 && j === f.length - 1)) faceOf.set(ekey(f[i], f[j]), fi); });
    const dist = (x, y) => Math.hypot(m.v[x][0] - m.v[y][0], m.v[x][1] - m.v[y][1], m.v[x][2] - m.v[y][2]);
    for (let i = 0; i < r.seams.length; i += 2) {
      const a2 = r.seams[i], c2 = r.seams[i + 1], k = ekey(a2, c2);
      if (polyEdges.has(k)) { pairs.push([a2, c2]); continue; }
      const fi = faceOf.get(k); if (fi == null) continue;
      diag++;
      const f = m.f[fi], ia = f.indexOf(a2), ic = f.indexOf(c2), n = f.length;
      const walk = (step) => { const out = []; for (let t = ia; t !== ic; t = (t + step + n) % n) out.push([f[t], f[(t + step + n) % n]]); return out; };
      const fw = walk(1), bw = walk(-1), len = (p) => p.reduce((acc, [x, y]) => acc + dist(x, y), 0);
      for (const e of (len(fw) <= len(bw) ? fw : bw)) pairs.push(e);
    }
    const base = has(m) ? m : planar(m, [], "best");
    const seamSet = new Set(pairs.map(([a2, b2]) => ekey(a2, b2)));
    let out = rebuild(base, seamSet);                 // exactly OptCuts' seams (the old ones dropped)
    out = await unfold(out, [], { iterations: (opts && opts.unfoldIterations) || 6 });
    out.uvInfo = Object.assign({}, out.uvInfo, { distortion: r.distortion, iterations: r.iterations, converged: r.converged, ms: r.ms, seams: pairs.length, diagonal: diag });
    return out;
  }
  return { optcuts, optcutsCancel, autoAtlas, has, clone, cornerUVs, edges, seams, shells, shellOfFace, rebuild, cut, sew, moveAndSew, planar, camera, cylindrical,
    spherical, automatic, transform, flip, density, setDensity, distortion, overlapCount, carry, unfold, layout, layoutBasic, uvsOfFaces,
    bbox, faceAreaUV, faceArea3, compact, ekey, splitUVs, mergeUVs, deleteUVs };
})();
