// Forge's automatic seams and island intelligence (owner 2026-10-21: "https://github.com/danielboxer/UVgami use that code").
//
// Portions ported from UVgami (c) Daniel Boxer, GPL-3.0 (https://github.com/danielboxer/UVgami, src/seams/*,
// src/similar.py, src/ops/island.py). UVgami is free software under the GNU General Public License v3; so is this
// port, which is part of LOKI (AGPL-3.0, GPL-3.0 compatible). The licence text is app/ui/licenses/UVgami-LICENSE.txt;
// docs/THIRD_PARTY.md has the row.
// The flatten engines the original add-on drives (OptCuts, xatlas, a GPU one) are NOT here: where the original
// called its engine, this file takes a hook - opts.flatten(cage) -> Promise<cage> - that Forge wires to LOKI's C++
// engine (window.ForgeGeom). A small rigid unfold (flattenRigid) is the fallback: exact for islands made of flat
// panels and developable strips (boxes, prisms, cylinder walls), not a general solver. See docs/FORGE_UVGAMI.md.
//
// Works on Forge's UV cage (app/ui/forge_uv.js): {v:[[x,y,z]], f:[[vert...]], uv:[[u,v]], fuv:[[uv...]]}. A seam set
// is a Set of "a,b" vertex-index keys (a < b), the same keys ForgeUV.ekey makes, so ForgeUV.rebuild(cage, seams)
// turns one into UV shells. No function here mutates its input: functions return a seam Set, plain data, or a new
// cage. Plain functions, no DOM, no eval; runs in node and the browser.
"use strict";

(function (root) {
  // ================================================================== small helpers
  const EMPTY = Object.freeze([]);
  const pair = (a, b) => (a < b ? a + "," + b : b + "," + a);
  const ab = (k) => { const i = k.indexOf(","); return [+k.slice(0, i), +k.slice(i + 1)]; };
  const otherEnd = (k, v) => { const [a, b] = ab(k); return a === v ? b : a; };
  const g = (m, k) => m.get(k) || 0;
  const addTo = (m, k, x) => { m.set(k, (m.get(k) || 0) + x); };
  const getSet = (m, k) => { let s = m.get(k); if (!s) m.set(k, (s = new Set())); return s; };
  const getArr = (m, k) => { let s = m.get(k); if (!s) m.set(k, (s = [])); return s; };
  const first = (it) => it.values().next().value;
  const cmpT = (x, y) => {
    for (let i = 0; i < x.length; i++) { if (x[i] < y[i]) return -1; if (x[i] > y[i]) return 1; }
    return 0;
  };
  const keyCmp = (x, y) => { const p = ab(x), q = ab(y); return p[0] - q[0] || p[1] - q[1]; };
  const mod = (a, n) => ((a % n) + n) % n;
  function findA(parent, x) { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; }
  function findM(parent, x) {
    while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); }
    return x;
  }
  const cross = (u, v) => [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const vnorm = (v) => Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
  const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const sub3 = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const dist3 = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  const dist2 = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const rad = (d) => (d * Math.PI) / 180;
  const unionSets = (...xs) => { const s = new Set(); for (const x of xs) if (x) for (const k of x) s.add(k); return s; };
  function argBest(items, score, better) {
    let best, bs;
    for (const it of items) { const s = score(it); if (best === undefined || better(s, bs)) { best = it; bs = s; } }
    return best;
  }
  const argMin = (items, score) => argBest(items, score, (a, b) => a < b);
  const mostCommon = (counter) => argBest(counter.keys(), (k) => counter.get(k), (a, b) => a > b);

  // a binary min-heap of tuples (arrays compared element by element, like Python's heapq)
  class Heap {
    constructor() { this.a = []; }
    get size() { return this.a.length; }
    push(x) {
      const a = this.a; a.push(x); let i = a.length - 1;
      while (i > 0) { const p = (i - 1) >> 1; if (cmpT(a[i], a[p]) >= 0) break; [a[i], a[p]] = [a[p], a[i]]; i = p; }
    }
    pop() {
      const a = this.a, top = a[0], last = a.pop();
      if (a.length) {
        a[0] = last; let i = 0;
        for (;;) {
          const l = 2 * i + 1, r = l + 1; let m = i;
          if (l < a.length && cmpT(a[l], a[m]) < 0) m = l;
          if (r < a.length && cmpT(a[r], a[m]) < 0) m = r;
          if (m === i) break;
          [a[i], a[m]] = [a[m], a[i]]; i = m;
        }
      }
      return top;
    }
  }
  // weights (seam restrictions, 0..1 per vertex): a Map, a plain object or an array
  function weightMap(w) {
    if (!w) return null;
    if (w instanceof Map) return w.size ? w : null;
    const m = new Map();
    if (Array.isArray(w)) w.forEach((x, i) => { if (x) m.set(i, +x); });
    else for (const k of Object.keys(w)) if (w[k]) m.set(+k, +w[k]);
    return m.size ? m : null;
  }

  // ================================================================== seams/mesh.py
  // low on purpose: a bevel splits one crease into several small turns
  const LOW_ANGLE = 10;
  const COLLAPSED_UV_AREA = 1e-8;

  function diagonal(verts) {
    if (!verts.length) return 0;
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (const v of verts) for (let i = 0; i < 3; i++) { if (v[i] < lo[i]) lo[i] = v[i]; if (v[i] > hi[i]) hi[i] = v[i]; }
    return vnorm(sub3(hi, lo));
  }
  // a face's edges as sorted vertex index pairs
  const faceKeys = (face) => face.map((v, i) => pair(v, face[(i + 1) % face.length]));
  // edge -> owning faces, keyed by sorted vertex index pair
  function faceEdges(faces) {
    const edges = new Map();
    faces.forEach((face, fi) => { for (const key of faceKeys(face)) getArr(edges, key).push(fi); });
    return edges;
  }
  // degrees the surface turns across an edge
  function turnAngle(weighted, owners) {
    const A = weighted[owners[0]], B = weighted[owners[1]];
    // two roots, not one over the product: folding them flips the odd seam
    const scale = Math.sqrt(A[0] * A[0] + A[1] * A[1] + A[2] * A[2]) * Math.sqrt(B[0] * B[0] + B[1] * B[1] + B[2] * B[2]);
    if (!scale) return 0;
    const d = (A[0] * B[0] + A[1] * B[1] + A[2] * B[2]) / scale;
    return (Math.acos(Math.max(-1, Math.min(1, d))) * 180) / Math.PI;
  }
  // scaled by twice the area of the first three corners
  const weightedNormals = (verts, faces) => faces.map((f) => { const a = verts[f[0]], b = verts[f[1]], c = verts[f[2]]; return cross(sub3(b, a), sub3(c, a)); });
  // per-face weighted normals and areas, plus edge -> owning faces
  function build(verts, faces) {
    const weighted = weightedNormals(verts, faces);
    return [weighted, weighted.map((n) => vnorm(n) / 2), faceEdges(faces)];
  }
  function signedArea(pts) {
    let t = 0;
    for (let i = 0; i < pts.length; i++) { const a = pts[i], b = pts[(i + 1) % pts.length]; t += a[0] * b[1] - b[0] * a[1]; }
    return t / 2;
  }
  // a uv map crushed to points, a failed flatten's signature
  const uvsCollapsed = (polygons) => polygons.reduce((s, p) => s + Math.abs(signedArea(p)), 0) < COLLAPSED_UV_AREA;
  // joined by interior edges not on a seam
  function islandGroups(faces, seams, edges) {
    const parent = new Int32Array(faces.length).map((_, i) => i);
    for (const [key, owners] of edges) {
      if (owners.length === 2 && !seams.has(key)) { const a = findA(parent, owners[0]), b = findA(parent, owners[1]); if (a !== b) parent[a] = b; }
    }
    const members = new Map();
    for (let fi = 0; fi < faces.length; fi++) getArr(members, findA(parent, fi)).push(fi);
    return [...members.values()];
  }
  // joined by any shared vertex: the loose parts
  function vertexComponents(faces) {
    const parent = new Map();
    for (const face of faces) {
      for (const v of face) if (!parent.has(v)) parent.set(v, v);
      for (const v of face.slice(1)) { const ra = findM(parent, face[0]), rb = findM(parent, v); if (ra !== rb) parent.set(ra, rb); }
    }
    const members = new Map();
    faces.forEach((face, fi) => getArr(members, findM(parent, face[0])).push(fi));
    return [...members.values()];
  }
  // boxes [x0, y0, x1, y1] can touch without the boundaries crossing
  function islandsOverlap(boxes) {
    const order = boxes.map((_, i) => i).sort((i, j) => boxes[i][0] - boxes[j][0]);
    for (let k = 0; k < order.length; k++) {
      const i = order[k];
      for (const j of order.slice(k + 1)) {
        if (boxes[j][0] >= boxes[i][2]) break;
        if (boxes[j][1] < boxes[i][3] && boxes[i][1] < boxes[j][3]) return true;
      }
    }
    return false;
  }
  // applied as u -> flip - u when flip is not null, then add (du, dv)
  function islandLayout(boxes, areas) {
    const gap = 0.05 * Math.max(...boxes.map((b) => b[2] - b[0]));
    let cursor = 0;
    return boxes.map((b, i) => {
      const t = [areas[i] < 0 ? b[0] + b[2] : null, cursor - b[0], -b[1]];
      cursor += b[2] - b[0] + gap;
      return t;
    });
  }

  // ================================================================== seams/regions.py
  const SPLIT_ASPECT = 6.0, WIDTH_CAP = 0.05, WIDTH_QUANTILE = 0.9, WIDTH_FACTOR = 2.0;
  const FLAT_ANGLE = 30, CREASE_ANGLE = 30, PANEL_SHARE = 0.95, HINGE_LINE_COS = 0.996;

  // forced wins when an edge is both forced and smooth
  function partition(faces, weighted, edges, angle, forced, smooth) {
    const parent = new Int32Array(faces.length).map((_, i) => i);
    for (const [key, owners] of edges) {
      if (owners.length !== 2) continue;
      if (forced && forced.has(key)) continue;
      if (turnAngle(weighted, owners) > angle && !(smooth && smooth.has(key))) continue;
      const ra = findA(parent, owners[0]), rb = findA(parent, owners[1]);
      if (ra !== rb) parent[ra] = rb;
    }
    return (i) => findA(parent, i);
  }
  const labelsOf = (n, rootFn) => Array.from({ length: n }, (_, i) => rootFn(i));
  // kept as a sum so merges can add boundaries together
  function boundaryTurns(verts, weighted, edges, label) {
    const total = new Map();
    for (const [key, owners] of edges) {
      if (owners.length !== 2) continue;
      const ra = label[owners[0]], rb = label[owners[1]];
      if (ra === rb) continue;
      const [v0, v1] = ab(key);
      addTo(total, pair(ra, rb), dist3(verts[v0], verts[v1]) * turnAngle(weighted, owners));
    }
    return total;
  }
  // EC is 1 for a disk, 0 once a region has a hole
  function regionTopology(edges, label) {
    const faceCount = new Map(); for (const r of label) addTo(faceCount, r, 1);
    const rverts = new Map(), edgeCount = new Map(), shared = new Map();
    for (const [key, owners] of edges) {
      const [v0, v1] = ab(key);
      const regions = new Set(owners.map((o) => label[o]));
      for (const r of regions) { const s = getSet(rverts, r); s.add(v0); s.add(v1); addTo(edgeCount, r, 1); }
      if (regions.size === 2) { const [ra, rb] = [...regions]; addTo(shared, pair(ra, rb), 1); }
    }
    const ec = new Map();
    for (const r of faceCount.keys()) ec.set(r, (rverts.has(r) ? rverts.get(r).size : 0) - g(edgeCount, r) + faceCount.get(r));
    return [ec, rverts, shared];
  }
  // 2 when they meet twice, so the union has a hole, 0 for a closed loop
  function jointCount(rverts, shared, a, b) {
    const A = rverts.get(a) || new Set(), B = rverts.get(b) || new Set();
    const [s, l] = A.size < B.size ? [A, B] : [B, A];
    let n = 0; for (const v of s) if (l.has(v)) n++;
    return n - g(shared, pair(a, b));
  }
  // meeting twice would open a hole, swallowing a region closes the surface
  function keepsTopology(ec, rverts, shared, a, b) {
    const merged = ec.get(a) + ec.get(b) - jointCount(rverts, shared, a, b);
    return Math.min(ec.get(a), ec.get(b)) <= merged && merged <= 1;
  }
  // no merge may take one, so a hand-marked edge survives as a region boundary
  function lockedPairs(edges, label, forced) {
    const locked = new Set();
    if (!forced) return locked;
    for (const [key, owners] of edges) {
      if (owners.length === 2 && forced.has(key)) { const ra = label[owners[0]], rb = label[owners[1]]; if (ra !== rb) locked.add(pair(ra, rb)); }
    }
    return locked;
  }
  function regionStats(verts, areas, edges, label) {
    const area = new Map(), shared = new Map(), perimeter = new Map();
    areas.forEach((a, i) => addTo(area, label[i], a));
    for (const [key, owners] of edges) {
      const [v0, v1] = ab(key), length = dist3(verts[v0], verts[v1]);
      const regions = new Set(owners.map((o) => label[o]));
      if (regions.size === 2) { const [ra, rb] = [...regions]; addTo(shared, pair(ra, rb), length); addTo(perimeter, ra, length); addTo(perimeter, rb, length); }
      else if (owners.length === 1) addTo(perimeter, label[owners[0]], length);
    }
    return [area, shared, perimeter];
  }
  function detectWidth(verts, faces, areas, edges, rootFn, scale) {
    const label = labelsOf(faces.length, rootFn);
    const [area, , perimeter] = regionStats(verts, areas, edges, label);
    const ws = [];
    for (const [r, a] of area) { const p = g(perimeter, r); if (p > 0) ws.push((2 * a) / p); }
    ws.sort((x, y) => x - y);
    if (!ws.length) return 0;
    const q = ws[Math.min(ws.length - 1, Math.floor(WIDTH_QUANTILE * ws.length))];
    return Math.min(WIDTH_FACTOR * q, WIDTH_CAP * scale);
  }
  // a dissolved band moves its turn and width onto the boundaries it leaves
  function absorb(verts, faces, weighted, areas, edges, rootFn, minWidth, forced, lockedIn) {
    const label = labelsOf(faces.length, rootFn);
    const [area, shared, perimeter] = regionStats(verts, areas, edges, label);
    const turns = boundaryTurns(verts, weighted, edges, label);
    const steps = new Map(turns), spread = new Map();
    const [ec, rverts, sharedEdges] = regionTopology(edges, label);
    const locked = unionSets(lockedPairs(edges, label, forced), lockedIn);
    const neighbors = new Map();
    for (const k of shared.keys()) { const [ra, rb] = ab(k); getSet(neighbors, ra).add(rb); getSet(neighbors, rb).add(ra); }
    const alive = new Set(area.keys()), parent = new Map();
    for (const r of area.keys()) parent.set(r, r);
    const width = (r) => (g(perimeter, r) > 0 ? (2 * g(area, r)) / g(perimeter, r) : Infinity);
    const heap = new Heap();
    for (const r of alive) if (width(r) < minWidth) heap.push([width(r), r]);
    const desc = (arr) => arr.slice().sort((x, y) => cmpT(y, x));
    while (heap.size) {
      const [w, region] = heap.pop();
      if (!alive.has(region) || width(region) !== w) continue;
      const partners = [...(neighbors.get(region) || EMPTY)].filter((n) => alive.has(n)).map((n) => [g(shared, pair(region, n)), n]);
      if (!partners.length) continue;
      // a bevel should dissolve into its surface, not accrete into a wider strip
      const wide = partners.filter((p) => width(p[1]) >= minWidth), rest = partners.filter((p) => width(p[1]) < minWidth);
      let best = null;
      for (const [, n] of desc(wide).concat(desc(rest))) {
        if (!locked.has(pair(region, n)) && keepsTopology(ec, rverts, sharedEdges, region, n)) { best = n; break; }
      }
      // nothing can take this strip without opening a hole
      if (best === null) continue;
      const contact = g(shared, pair(region, best));
      // the far side can tell a crease from spread out curvature
      const crossed = contact > 0 ? g(turns, pair(region, best)) / contact : 0;
      const crossedWidth = width(region) + (contact > 0 ? g(spread, pair(region, best)) / contact : 0);
      addTo(area, best, g(area, region));
      perimeter.set(best, g(perimeter, best) + g(perimeter, region) - 2 * contact);
      ec.set(best, ec.get(best) + ec.get(region) - jointCount(rverts, sharedEdges, region, best));
      for (const v of rverts.get(region) || EMPTY) getSet(rverts, best).add(v);
      for (const n of [...(neighbors.get(region) || EMPTY)]) {
        const rn = pair(region, n);
        if (n !== best && alive.has(n)) {
          const bn = pair(best, n);
          turns.set(bn, g(turns, bn) + g(turns, rn) + g(shared, rn) * crossed);
          spread.set(bn, g(spread, bn) + g(spread, rn) + g(shared, rn) * crossedWidth);
          steps.set(bn, g(steps, bn) + g(steps, rn));
          shared.set(bn, g(shared, bn) + g(shared, rn));
          sharedEdges.set(bn, g(sharedEdges, bn) + g(sharedEdges, rn));
          if (locked.has(rn)) locked.add(bn);
          getSet(neighbors, n).add(best); getSet(neighbors, best).add(n);
        }
        shared.delete(rn); turns.delete(rn); steps.delete(rn); spread.delete(rn); sharedEdges.delete(rn); locked.delete(rn);
        getSet(neighbors, n).delete(region);
      }
      getSet(neighbors, best).delete(best);
      neighbors.delete(region); alive.delete(region); parent.set(region, best);
      const nw = width(best);
      if (nw < minWidth) heap.push([nw, best]);
    }
    return [label.map((r) => findM(parent, r)), { turns, steps, spread, length: shared }];
  }
  // a boundary on a cylinder wall turns one segment angle however much has merged
  function mergeSmooth(edges, label, bounds, minWidth, angle = CREASE_ANGLE, forced = null) {
    const { turns, steps, spread, length: shared } = bounds;
    const neighbors = new Map();
    for (const k of shared.keys()) { const [ra, rb] = ab(k); getSet(neighbors, ra).add(rb); getSet(neighbors, rb).add(ra); }
    const [ec, rverts, sharedEdges] = regionTopology(edges, label);
    const locked = lockedPairs(edges, label, forced);
    const alive = new Set(label), parent = new Map();
    for (const r of alive) parent.set(r, r);
    // a dissolved band's edges count only while it is still band width
    const crease = (a, b) => {
      const key = pair(a, b), length = g(shared, key);
      if (length <= 0) return Infinity;
      const step = g(steps, key) / length;
      if (g(spread, key) / length > minWidth) return step;
      return Math.max(step, g(turns, key) / length);
    };
    const heap = new Heap();
    for (const [a, ns] of neighbors) for (const b of ns) if (a < b) { const c = crease(a, b); if (c < angle) heap.push([c, a, b]); }
    while (heap.size) {
      const [value, a, b] = heap.pop();
      if (!alive.has(a) || !alive.has(b) || crease(a, b) !== value || locked.has(pair(a, b)) || !keepsTopology(ec, rverts, sharedEdges, a, b)) continue;
      ec.set(a, ec.get(a) + ec.get(b) - jointCount(rverts, sharedEdges, a, b));
      for (const v of rverts.get(b) || EMPTY) getSet(rverts, a).add(v);
      for (const n of [...(neighbors.get(b) || EMPTY)]) {
        const bn = pair(b, n);
        if (n !== a) {
          // both sides of this boundary stay put, so no turn is crossed
          const an = pair(a, n);
          turns.set(an, g(turns, an) + g(turns, bn)); steps.set(an, g(steps, an) + g(steps, bn));
          spread.set(an, g(spread, an) + g(spread, bn)); shared.set(an, g(shared, an) + g(shared, bn));
          sharedEdges.set(an, g(sharedEdges, an) + g(sharedEdges, bn));
          if (locked.has(bn)) locked.add(an);
          getSet(neighbors, n).add(a); getSet(neighbors, a).add(n);
        }
        turns.delete(bn); steps.delete(bn); spread.delete(bn); shared.delete(bn); sharedEdges.delete(bn); locked.delete(bn);
        getSet(neighbors, n).delete(b);
      }
      getSet(neighbors, a).delete(a);
      neighbors.delete(b); alive.delete(b); parent.set(b, a);
      for (const n of neighbors.get(a) || EMPTY) { const v = crease(a, n); if (v < angle) heap.push(a < n ? [v, a, n] : [v, n, a]); }
    }
    return label.map((r) => findM(parent, r));
  }
  // flattest pair first, with the same lazy heap as absorb
  function mergeFlat(weighted, areas, edges, label, angle = FLAT_ANGLE, forced = null) {
    const total = new Map(), mass = new Map();
    label.forEach((r, i) => {
      if (!total.has(r)) total.set(r, [0, 0, 0]);
      const t = total.get(r); for (let k = 0; k < 3; k++) t[k] += weighted[i][k];
      addTo(mass, r, 2 * areas[i]);
    });
    const neighbors = new Map();
    for (const owners of edges.values()) {
      if (owners.length === 2) { const ra = label[owners[0]], rb = label[owners[1]]; if (ra !== rb) { getSet(neighbors, ra).add(rb); getSet(neighbors, rb).add(ra); } }
    }
    const ratio = (a, b) => {
      const m = g(mass, a) + g(mass, b), A = total.get(a), B = total.get(b);
      return m > 0 ? vnorm([A[0] + B[0], A[1] + B[1], A[2] + B[2]]) / m : 1;
    };
    const bound = (1 + Math.cos(rad(angle))) / 2;
    const [ec, rverts, sharedEdges] = regionTopology(edges, label);
    const locked = lockedPairs(edges, label, forced);
    const alive = new Set(total.keys()), parent = new Map();
    for (const r of total.keys()) parent.set(r, r);
    const heap = new Heap();
    for (const [a, ns] of neighbors) for (const b of ns) if (a < b && ratio(a, b) >= bound) heap.push([-ratio(a, b), a, b]);
    while (heap.size) {
      const [negr, a, b] = heap.pop();
      if (!alive.has(a) || !alive.has(b) || ratio(a, b) !== -negr || locked.has(pair(a, b)) || !keepsTopology(ec, rverts, sharedEdges, a, b)) continue;
      const A = total.get(a), B = total.get(b); for (let k = 0; k < 3; k++) A[k] += B[k];
      addTo(mass, a, g(mass, b));
      ec.set(a, ec.get(a) + ec.get(b) - jointCount(rverts, sharedEdges, a, b));
      for (const v of rverts.get(b) || EMPTY) getSet(rverts, a).add(v);
      for (const n of [...(neighbors.get(b) || EMPTY)]) {
        const bn = pair(b, n);
        if (n !== a) {
          const an = pair(a, n);
          sharedEdges.set(an, g(sharedEdges, an) + g(sharedEdges, bn));
          if (locked.has(bn)) locked.add(an);
          getSet(neighbors, n).add(a); getSet(neighbors, a).add(n);
        }
        sharedEdges.delete(bn); locked.delete(bn); getSet(neighbors, n).delete(b);
      }
      getSet(neighbors, a).delete(a);
      neighbors.delete(b); alive.delete(b); parent.set(b, a);
      for (const n of neighbors.get(a) || EMPTY) { const r = ratio(a, n); if (r >= bound) heap.push(a < n ? [-r, a, n] : [-r, n, a]); }
    }
    return label.map((r) => findM(parent, r));
  }
  // closing the ring is safe when the cut-open wall unrolls into a compact strip
  function closeRings(verts, weighted, areas, edges, label, angle = CREASE_ANGLE, forced = null) {
    const [area, shared, perimeter] = regionStats(verts, areas, edges, label);
    const turns = boundaryTurns(verts, weighted, edges, label);
    const [ec, rverts, sharedEdges] = regionTopology(edges, label);
    const locked = lockedPairs(edges, label, forced);
    const candidates = [];
    for (const [key, length] of shared) {
      const [a, b] = ab(key);
      if (ec.get(a) !== 1 || ec.get(b) !== 1) continue;
      if (locked.has(key)) continue;
      if (jointCount(rverts, sharedEdges, a, b) !== 2) continue;
      if (length <= 0 || g(turns, key) / length >= angle) continue;
      const strip = (g(perimeter, a) + g(perimeter, b)) / 2 - length, size = g(area, a) + g(area, b);
      if (size <= 0 || (strip * strip) / size > SPLIT_ASPECT) continue;
      candidates.push([(strip * strip) / size, a, b]);
    }
    const taken = new Set(), closed = new Map();
    for (const [, a, b] of candidates.sort(cmpT)) {
      if (taken.has(a) || taken.has(b)) continue;
      taken.add(a); taken.add(b); closed.set(b, a);
    }
    if (!closed.size) return label;
    return label.map((r) => (closed.has(r) ? closed.get(r) : r));
  }
  // 1 when every group is planar, lower the more each one curls
  function panelShare(weighted, groups) {
    let flat = 0, mass = 0;
    for (const group of groups) {
      const res = [0, 0, 0];
      for (const i of group) { for (let k = 0; k < 3; k++) res[k] += weighted[i][k]; mass += vnorm(weighted[i]); }
      flat += vnorm(res);
    }
    return mass > 0 ? flat / mass : 0;
  }
  // the sides swing about a single fold axis, a bent contact cannot open flat
  function straightPath(verts, keys) {
    let reference = null;
    const ends = new Map(), parent = new Map();
    for (const key of keys) {
      const [v0, v1] = ab(key), step = sub3(verts[v1], verts[v0]), length = vnorm(step);
      if (length <= 0) return false;
      const s = step.map((x) => x / length);
      if (reference === null) reference = s;
      else if (Math.abs(dot3(reference, s)) < HINGE_LINE_COS) return false;
      addTo(ends, v0, 1); addTo(ends, v1, 1);
      if (!parent.has(v0)) parent.set(v0, v0);
      if (!parent.has(v1)) parent.set(v1, v1);
      const ra = findM(parent, v0), rb = findM(parent, v1);
      if (ra !== rb) parent.set(ra, rb);
    }
    for (const c of ends.values()) if (c > 2) return false;
    return new Set([...parent.keys()].map((v) => findM(parent, v))).size === 1;
  }
  function pathEnds(keys) {
    const counts = new Map();
    for (const key of keys) for (const v of ab(key)) addTo(counts, v, 1);
    const ends = [...counts].filter(([, c]) => c === 1).map(([v]) => v);
    return ends.length === 2 ? ends : null;
  }
  // origin and in-plane axes projecting a flat panel to 2D
  function panelBasis(verts, faces, weighted, members) {
    let normal = [0, 0, 0];
    for (const i of members) for (let k = 0; k < 3; k++) normal[k] += weighted[i][k];
    const scale = vnorm(normal);
    if (scale <= 0) return null;
    normal = normal.map((x) => x / scale);
    const face = faces[members[0]], origin = verts[face[0]];
    for (const other of face.slice(1)) {
      const d = sub3(verts[other], origin), lift = dot3(d, normal);
      let u = d.map((x, k) => x - lift * normal[k]);
      const l = vnorm(u);
      if (l > 0) { u = u.map((x) => x / l); return [origin, u, cross(normal, u)]; }
    }
    return null;
  }
  const project = (basis, vert) => { const d = sub3(vert, basis[0]); return [dot3(d, basis[1]), dot3(d, basis[2])]; };
  const IDENTITY = [1, 0, 0, 0];
  const applyTransform = (t, p) => [t[0] * p[0] - t[1] * p[1] + t[2], t[1] * p[0] + t[0] * p[1] + t[3]];
  const composeTransforms = (o, i) => [o[0] * i[0] - o[1] * i[1], o[1] * i[0] + o[0] * i[1], o[0] * i[2] - o[1] * i[3] + o[2], o[1] * i[2] + o[0] * i[3] + o[3]];
  // rotation only, both panels project with their normal up
  function glueTransform(a0, a1, b0, b1) {
    let dax = a1[0] - a0[0], day = a1[1] - a0[1], dbx = b1[0] - b0[0], dby = b1[1] - b0[1];
    const la = Math.hypot(dax, day), lb = Math.hypot(dbx, dby);
    if (la <= 0 || lb <= 0) return null;
    dax /= la; day /= la; dbx /= lb; dby /= lb;
    const c = dbx * dax + dby * day, s = dbx * day - dby * dax;
    return [c, s, a0[0] - (c * b0[0] - s * b0[1]), a0[1] - (s * b0[0] + c * b0[1])];
  }
  // touching at an endpoint or running collinear is not a crossing
  function segmentsCross(a, b, c, d) {
    const orient = (p, q, r) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
    const o1 = orient(a, b, c), o2 = orient(a, b, d);
    if (o1 === 0 || o2 === 0 || (o1 > 0) === (o2 > 0)) return false;
    const o3 = orient(c, d, a), o4 = orient(c, d, b);
    return o3 !== 0 && o4 !== 0 && (o3 > 0) !== (o4 > 0);
  }
  // half-open so a vertex on the ray counts once
  function pointInPolygon(point, segments) {
    const [px, py] = point; let hits = 0;
    for (const [[x0, y0], [x1, y1]] of segments) if ((y0 > py) !== (y1 > py) && x0 + ((py - y0) * (x1 - x0)) / (y1 - y0) > px) hits++;
    return hits % 2 === 1;
  }
  const boxesMeet = (a, b) => !(a[2] <= b[0] || b[2] <= a[0] || a[3] <= b[1] || b[3] <= a[1]);
  const spanOf = (boxes) => [Math.min(...boxes.map((b) => b[0])), Math.min(...boxes.map((b) => b[1])), Math.max(...boxes.map((b) => b[2])), Math.max(...boxes.map((b) => b[3]))];
  function panelsOverlap(pa, pb) {
    for (const sa of pa[1]) for (const sb of pb[1]) if (segmentsCross(sa[0], sa[1], sb[0], sb[1])) return true;
    return pointInPolygon(pa[3], pb[1]) || pointInPolygon(pb[3], pa[1]);
  }
  // a hinge is the contact between two flat panels along one straight path
  function unfoldHinges(verts, faces, weighted, edges, label, forced = null) {
    // forced cuts here too, or a panel spans two regions
    const rootFn = partition(faces, weighted, edges, LOW_ANGLE, forced);
    const contacts = new Map(), outline = new Map(), poisoned = new Set();
    for (const [key, owners] of edges) {
      const panels = [...new Set(owners.map((o) => rootFn(o)))].sort((x, y) => x - y);
      if (owners.length === 2 && panels.length === 1) continue;
      for (const p of panels) getArr(outline, p).push(key);
      if (owners.length === 2) { const pp = pair(panels[0], panels[1]); getArr(contacts, pp).push(key); if (forced && forced.has(key)) poisoned.add(pp); }
    }
    const members = new Map();
    for (let i = 0; i < faces.length; i++) getArr(members, rootFn(i)).push(i);
    const flat = new Map();
    for (const pp of contacts.keys()) for (const p of ab(pp)) if (!flat.has(p)) flat.set(p, panelShare(weighted, [members.get(p)]) >= PANEL_SHARE);
    const [ec] = regionTopology(edges, label);
    const region = new Map(); for (const p of flat.keys()) region.set(p, label[members.get(p)[0]]);
    const basis = new Map(); for (const [p, isFlat] of flat) if (isFlat) basis.set(p, panelBasis(verts, faces, weighted, members.get(p)));
    const length = (keys) => keys.reduce((s, k) => { const [v0, v1] = ab(k); return s + dist3(verts[v1], verts[v0]); }, 0);
    const candidates = [];
    for (const [pp, keys] of contacts) {
      const [pa, pb] = ab(pp);
      if (region.get(pa) !== region.get(pb) && !poisoned.has(pp) && flat.get(pa) && flat.get(pb)
        && ec.get(region.get(pa)) === 1 && ec.get(region.get(pb)) === 1 && straightPath(verts, keys)) candidates.push([length(keys), pa, pb]);
    }
    candidates.sort((x, y) => cmpT(y, x));
    const localCache = new Map();
    const placedPanel = (move, p) => {
      if (!localCache.has(p)) {
        const face = faces[members.get(p)[0]];
        const centroid = [0, 1, 2].map((k) => face.reduce((s, v) => s + verts[v][k], 0) / face.length);
        localCache.set(p, [outline.get(p).map((k) => { const [v0, v1] = ab(k); return [project(basis.get(p), verts[v0]), project(basis.get(p), verts[v1])]; }), project(basis.get(p), centroid)]);
      }
      const [segments, inner] = localCache.get(p);
      const moved = segments.map(([a, b]) => [applyTransform(move, a), applyTransform(move, b)]);
      const xs = moved.flatMap((s) => [s[0][0], s[1][0]]), ys = moved.flatMap((s) => [s[0][1], s[1][1]]);
      return [move, moved, [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)], applyTransform(move, inner)];
    };
    // those folds are never cut
    const cluster = new Map(), placement = new Map(), glue = new Map();
    for (const [pp, keys] of contacts) {
      const [pa, pb] = ab(pp);
      if (region.has(pa) && region.get(pa) === region.get(pb) && !poisoned.has(pp) && flat.get(pa) && flat.get(pb)
        && basis.get(pa) && basis.get(pb) && straightPath(verts, keys) && pathEnds(keys)) {
        getArr(glue, pa).push([pb, keys]); getArr(glue, pb).push([pa, keys]);
      }
    }
    for (const [p, b] of basis) {
      if (!b || placement.has(p)) continue;
      cluster.set(p, p); placement.set(p, IDENTITY);
      const stack = [p];
      while (stack.length) {
        const current = stack.pop();
        for (const [neighbor, keys] of glue.get(current) || EMPTY) {
          if (placement.has(neighbor)) continue;
          const [e0, e1] = pathEnds(keys);
          const move = glueTransform(applyTransform(placement.get(current), project(basis.get(current), verts[e0])),
            applyTransform(placement.get(current), project(basis.get(current), verts[e1])),
            project(basis.get(neighbor), verts[e0]), project(basis.get(neighbor), verts[e1]));
          if (move === null) continue;
          cluster.set(neighbor, p); placement.set(neighbor, move); stack.push(neighbor);
        }
      }
    }
    // only panels inside a group can be overlap-tested
    const groupParent = new Map(), layouts = new Map();
    const groupLayout = (p) => {
      const seed = cluster.get(p);
      if (!groupParent.has(seed)) groupParent.set(seed, seed);
      const top = findM(groupParent, seed);
      if (!layouts.has(top)) {
        const m = new Map();
        for (const [q, s] of cluster) if (s === seed) m.set(q, placedPanel(placement.get(q), q));
        layouts.set(top, m);
      }
      return top;
    };
    const parent = new Map(); for (const r of new Set(label)) parent.set(r, r);
    const hinges = new Set();
    for (const [, pa, pb] of candidates) {
      const ra = findM(parent, region.get(pa)), rb = findM(parent, region.get(pb));
      if (ra === rb) continue;
      const keys = contacts.get(pair(pa, pb)), ends = pathEnds(keys);
      if (ends && basis.get(pa) && basis.get(pb)) {
        const ga = groupLayout(pa), gb = groupLayout(pb);
        if (ga !== gb) {
          const sideA = layouts.get(ga).get(pa), sideB = layouts.get(gb).get(pb), [e0, e1] = ends;
          const move = glueTransform(applyTransform(sideA[0], project(basis.get(pa), verts[e0])), applyTransform(sideA[0], project(basis.get(pa), verts[e1])),
            applyTransform(sideB[0], project(basis.get(pb), verts[e0])), applyTransform(sideB[0], project(basis.get(pb), verts[e1])));
          if (move !== null) {
            const arriving = new Map();
            for (const [q, placed] of layouts.get(gb)) arriving.set(q, placedPanel(composeTransforms(move, placed[0]), q));
            // one box for the arrivals drops a panel clear of them all
            const span = spanOf([...arriving.values()].map((x) => x[2]));
            let clash = false;
            outer: for (const placed of layouts.get(ga).values()) {
              if (!boxesMeet(placed[2], span)) continue;
              for (const arrival of arriving.values()) if (boxesMeet(placed[2], arrival[2]) && panelsOverlap(placed, arrival)) { clash = true; break outer; }
            }
            if (clash) continue;
            for (const [q, x] of arriving) layouts.get(ga).set(q, x);
            layouts.delete(gb); groupParent.set(gb, ga);
          }
        }
      }
      parent.set(ra, rb);
      for (const k of keys) hinges.add(k);
    }
    return hinges;
  }

  // ================================================================== seams/cuts.py
  const RESTRICT_COST = 9.0, CONCAVE_RELIEF = 0.5, CONVEX_RELIEF = 0.3, RELIEF_FULL_ANGLE = 45, CREASED_RELIEF = 0.9, TURN_COST = 1.0;

  // two loops meeting at a vertex count as one component, the cut would be a point
  function boundaryComponents(edges, label, forced) {
    const parent = new Map(), nodes = new Map();
    const node = (r, v) => { const k = r + "|" + v; if (!parent.has(k)) { parent.set(k, k); nodes.set(k, [r, v]); } return k; };
    for (const [key, owners] of edges) {
      const [v0, v1] = ab(key), regions = new Set(owners.map((o) => label[o]));
      if (owners.length === 2 && regions.size === 1 && (!forced || !forced.has(key))) continue;
      for (const r of regions) { const ra = findM(parent, node(r, v0)), rb = findM(parent, node(r, v1)); if (ra !== rb) parent.set(ra, rb); }
    }
    const grouped = new Map();
    for (const [k, [r, v]] of nodes) { if (!grouped.has(r)) grouped.set(r, new Map()); getSet(grouped.get(r), findM(parent, k)).add(v); }
    const out = new Map();
    for (const [r, comps] of grouped) out.set(r, [...comps.values()]);
    return out;
  }
  // the sign comes from the neighbour's centroid against the face plane
  function creaseRelief(verts, faces, weighted, edges) {
    const centroids = faces.map((face) => [0, 1, 2].map((k) => face.reduce((s, v) => s + verts[v][k], 0) / face.length));
    const relief = new Map();
    for (const [key, owners] of edges) {
      if (owners.length !== 2) continue;
      const angle = turnAngle(weighted, owners);
      if (angle <= LOW_ANGLE) continue;
      const na = weighted[owners[0]], base = verts[ab(key)[0]];
      const lift = dot3(na, sub3(centroids[owners[1]], base));
      const depth = Math.min((angle - LOW_ANGLE) / (RELIEF_FULL_ANGLE - LOW_ANGLE), 1);
      relief.set(key, 1 - (lift > 0 ? CONCAVE_RELIEF : CONVEX_RELIEF) * depth);
    }
    return relief;
  }
  const rel = (relief, k) => { const r = relief.get(k); return r === undefined ? 1 : r; };
  // longer where a painted restriction repels cuts, shorter along a crease
  function edgeCost(verts, weights, a, b, relief) {
    let length = dist3(verts[a], verts[b]);
    if (relief) length *= rel(relief, pair(a, b));
    if (!weights) return length;
    const paint = ((weights.get(a) || 0) + (weights.get(b) || 0)) / 2;
    return length * (1 + RESTRICT_COST * paint);
  }
  // zero along a crease or a straight continuation, up to TURN_COST on a reversal
  function turnCost(verts, u, v, w, relief) {
    if (rel(relief, pair(u, v)) < CREASED_RELIEF && rel(relief, pair(v, w)) < CREASED_RELIEF) return 0;
    const a = sub3(verts[v], verts[u]), b = sub3(verts[w], verts[v]), na = vnorm(a), nb = vnorm(b);
    if (!na || !nb) return 0;
    return (TURN_COST * (1 - dot3(a, b) / (na * nb))) / 2;
  }
  // turn penalties included, so a comparison matches what cutPath searches for
  function pathCost(verts, seq, weights = null, relief = null) {
    let total = 0;
    for (let i = 1; i < seq.length; i++) {
      let step = edgeCost(verts, weights, seq[i - 1], seq[i], relief);
      if (relief && i >= 2) step *= 1 + turnCost(verts, seq[i - 2], seq[i - 1], seq[i], relief);
      total += step;
    }
    return total;
  }
  // with relief the state carries the incoming direction. targets: a Set or a Map (keys are the targets)
  function cutPath(verts, adjacent, sources, targets, weights = null, relief = null) {
    const adj = (v) => adjacent.get(v) || EMPTY;
    if (!relief) {
      // without relief an edge costs at least its length
      const goal = targets.size === 1 ? verts[first(targets.keys())] : null;
      const remaining = (v) => (goal ? dist3(verts[v], goal) : 0);
      const dist = new Map(), prev = new Map(), heap = new Heap();
      for (const v of sources) { dist.set(v, 0); heap.push([remaining(v), 0, v]); }
      while (heap.size) {
        const [, d, v] = heap.pop();
        if (d !== dist.get(v)) continue;
        if (targets.has(v)) { const path = [v]; while (prev.has(path[path.length - 1])) path.push(prev.get(path[path.length - 1])); return path; }
        for (const w of adj(v)) {
          const step = d + edgeCost(verts, weights, v, w, null);
          if (step < (dist.has(w) ? dist.get(w) : Infinity)) { dist.set(w, step); prev.set(w, v); heap.push([step + remaining(w), step, w]); }
        }
      }
      return [];
    }
    // state is (vertex, arrived-from), -1 for a start with no direction yet
    const dist = new Map(), prev = new Map(), heap = new Heap();
    for (const v of sources) { dist.set(v + "|-1", 0); heap.push([0, v, -1]); }
    while (heap.size) {
      const [d, v, u] = heap.pop();
      if (d !== dist.get(v + "|" + u)) continue;
      if (targets.has(v)) {
        const path = [v]; let node = [v, u];
        while (prev.has(node[0] + "|" + node[1])) { node = prev.get(node[0] + "|" + node[1]); path.push(node[0]); }
        return path;
      }
      for (const w of adj(v)) {
        let step = edgeCost(verts, weights, v, w, relief);
        if (u >= 0) step *= 1 + turnCost(verts, u, v, w, relief);
        step += d;
        const k = w + "|" + v;
        if (step < (dist.has(k) ? dist.get(k) : Infinity)) { dist.set(k, step); prev.set(k, [v, u]); heap.push([step, w, v]); }
      }
    }
    return [];
  }
  function partLabels(adjacent) {
    const label = new Map();
    for (const start of adjacent.keys()) {
      if (label.has(start)) continue;
      label.set(start, start);
      const stack = [start];
      while (stack.length) { const v = stack.pop(); for (const w of adjacent.get(v) || EMPTY) if (!label.has(w)) { label.set(w, start); stack.push(w); } }
    }
    return label;
  }
  // every vertex maps to one vertex here, so segments that met still meet (cuts read off a coarse copy -> the dense mesh)
  function snapPaths(verts, adjacent, mapped, cuts) {
    const part = partLabels(adjacent), paths = new Set();
    for (const key of cuts) {
      const [a, b] = typeof key === "string" ? ab(key) : key;
      const va = mapped[a], vb = mapped[b];
      if (va === vb || part.get(va) !== part.get(vb)) continue;
      const path = cutPath(verts, adjacent, new Set([va]), new Set([vb]));
      for (let i = 0; i + 1 < path.length; i++) paths.add(pair(path[i], path[i + 1]));
    }
    return paths;
  }
  // one path per extra loop, each the shortest available at the time
  function connectLoops(verts, adjacent, comps, weights = null, relief = null) {
    const cuts = new Set(), sources = new Set(comps[0]), targets = new Map();
    comps.slice(1).forEach((comp, i) => { for (const v of comp) targets.set(v, i + 1); });
    while (targets.size) {
      const path = cutPath(verts, adjacent, sources, targets, weights, relief);
      if (!path.length) break;   // disconnected, leave the rest to the engine
      for (let i = 0; i + 1 < path.length; i++) cuts.add(pair(path[i], path[i + 1]));
      const reached = comps[targets.get(path[0])];
      for (const v of path) sources.add(v);
      for (const v of reached) { sources.add(v); targets.delete(v); }
    }
    return cuts;
  }
  // a path joining two boundary loops opens the region without splitting it
  function diskCuts(verts, edges, label, weights = null, relief = null, forced = null) {
    const needs = new Map();
    for (const [r, c] of boundaryComponents(edges, label, forced)) if (c.length > 1) needs.set(r, c);
    if (!needs.size) return new Set();
    const adjacent = new Map(); for (const r of needs.keys()) adjacent.set(r, new Map());
    for (const [key, owners] of edges) {
      const [v0, v1] = ab(key);
      for (const r of new Set(owners.map((o) => label[o]))) if (needs.has(r)) { getSet(adjacent.get(r), v0).add(v1); getSet(adjacent.get(r), v1).add(v0); }
    }
    const cuts = new Set();
    for (const [region, comps] of needs) for (const k of connectLoops(verts, adjacent.get(region), comps, weights, relief)) cuts.add(k);
    return cuts;
  }

  // ================================================================== seams/boundaries.py
  const REROUTE_RINGS = 2, LOOP_SHARE = 0.5;

  // a tooth is a face with every edge but one on the boundary to the same neighbour
  function flattenTeeth(weighted, faces, edges, label, angle = CREASE_ANGLE, forced = null) {
    const turns = new Map();
    const sharp = (key) => {
      const owners = edges.get(key);
      if (owners.length !== 2) return true;   // a mesh rim hides a seam as well as a crease
      if (!turns.has(key)) turns.set(key, turnAngle(weighted, owners));
      return turns.get(key) >= angle;
    };
    const lab = label.slice(), queue = lab.map((_, i) => i), queued = new Set(queue);
    let head = 0;
    while (head < queue.length) {
      const f = queue[head++]; queued.delete(f);
      if (head > 4096 && head * 2 > queue.length) { queue.splice(0, head); head = 0; }
      const keys = faceKeys(faces[f]), lost = new Map();
      for (const key of keys) {
        const owners = edges.get(key);
        if (owners.length === 2) { const o = owners[0] === f ? owners[1] : owners[0]; if (lab[o] !== lab[f]) getArr(lost, lab[o]).push(key); }
      }
      if (!lost.size) continue;
      let target, gone;
      for (const [t, ks] of lost) if (!gone || ks.length > gone.length) { target = t; gone = ks; }
      if (gone.length !== keys.length - 1) continue;
      const kept = keys.find((k) => !gone.includes(k));
      if (forced && gone.some((k) => forced.has(k))) continue;
      if (!sharp(kept) && gone.some(sharp)) continue;
      lab[f] = target;
      for (const key of keys) for (const o of edges.get(key)) if (o !== f && !queued.has(o)) { queued.add(o); queue.push(o); }
    }
    return lab;
  }
  // the merges settle face by face and leave boundaries staircased
  function rerouteBoundaries(verts, faces, areas, edges, label, relief, forced = null) {
    const lab = label.slice();
    // a reroute reads its two regions instead of every face in the mesh
    const regionFaces = new Map();
    lab.forEach((r, f) => getSet(regionFaces, r).add(f));
    const vertFaces = new Map();
    faces.forEach((face, fi) => { for (const v of face) getArr(vertFaces, v).push(fi); });
    // no path may pass through an anchored vertex, its own run's excepted
    const pairKeys = new Map(), anchored = new Set(), vertPairs = new Map();
    for (const [key, owners] of edges) {
      if (owners.length !== 2) { for (const v of ab(key)) anchored.add(v); continue; }
      const ra = lab[owners[0]], rb = lab[owners[1]];
      if (ra === rb) continue;
      const p = pair(ra, rb);
      getArr(pairKeys, p).push(key);
      const [a, b] = ab(key); getSet(vertPairs, a).add(p); getSet(vertPairs, b).add(p);
    }
    const blocked = unionSets(anchored, vertPairs.keys());
    function loopArcs(loop, cycle) {
      const n = loop.length;
      const creased = loop.filter((k) => rel(relief, k) < CREASED_RELIEF).length;
      if (creased < LOOP_SHARE * n) return [];
      // a vertex is as sharp as the duller of its two loop edges
      const sharp = loop.map((_, i) => 1 - Math.max(rel(relief, loop[mod(i - 1, n)]), rel(relief, loop[i])));
      const anchors = [], gap = Math.max(1, Math.floor(n / 4));
      const order = loop.map((_, i) => i).sort((i, j) => sharp[j] - sharp[i]);
      for (const i of order) {
        if (anchors.every((a) => Math.min(mod(i - a, n), mod(a - i, n)) >= gap)) anchors.push(i);
        if (anchors.length === 3) break;
      }
      if (anchors.length < 2) return [];
      anchors.sort((x, y) => x - y);
      return anchors.map((a, k) => {
        const b = anchors[(k + 1) % anchors.length];
        return [a < b ? loop.slice(a, b) : loop.slice(a).concat(loop.slice(0, b)), cycle[a], cycle[b]];
      });
    }
    function chains(keys) {
      const deg = new Map(), incident = new Map();
      for (const key of keys) for (const v of ab(key)) { addTo(deg, v, 1); getArr(incident, v).push(key); }
      const junctions = new Set();
      for (const [v, d] of deg) if (d !== 2 || anchored.has(v) || (vertPairs.has(v) && vertPairs.get(v).size > 1)) junctions.add(v);
      const seen = new Set(), out = [];
      for (const j of junctions) {
        for (const start of incident.get(j)) {
          if (seen.has(start)) continue;
          seen.add(start);
          const run = [start]; let v = otherEnd(start, j);
          while (!junctions.has(v)) {
            const key = incident.get(v).find((k) => k !== run[run.length - 1]);
            seen.add(key); run.push(key); v = otherEnd(key, v);
          }
          if (v !== j) out.push([run, j, v]);
        }
      }
      const left = new Set(keys.filter((k) => !seen.has(k)));
      while (left.size) {
        const start = first(left); left.delete(start);
        const loop = [start], cycle = ab(start);
        let v = cycle[1];
        for (;;) {
          const key = (incident.get(v) || EMPTY).find((k) => left.has(k));
          if (key === undefined) break;
          left.delete(key); loop.push(key); v = otherEnd(key, v); cycle.push(v);
        }
        // anything under three arcs of a few edges each is too small to move
        if (cycle[cycle.length - 1] !== cycle[0] || loop.length < 9) continue;
        cycle.pop();
        out.push(...loopArcs(loop, cycle));
      }
      return out;
    }
    const ec = (group) => {
      const ks = new Set(); for (const f of group) for (const k of faceKeys(faces[f])) ks.add(k);
      const vs = new Set(); for (const k of ks) for (const v of ab(k)) vs.add(v);
      return vs.size - ks.size + group.length;
    };
    // relief squared, a mild discount loses to a dull shortcut
    const pull = new Map(); for (const [k, r] of relief) pull.set(k, r * r);
    const runSeq = (run, j0) => { const seq = [j0]; for (const key of run) seq.push(otherEnd(key, seq[seq.length - 1])); return seq; };
    const creasedShare = (keys) => {
      let total = 0, creased = 0;
      for (const k of keys) { const [a, b] = ab(k), l = dist3(verts[a], verts[b]); total += l; if (rel(relief, k) < CREASED_RELIEF) creased += l; }
      return total ? creased / total : 0;
    };
    function reroute(p, run, j0, j1) {
      const [ra, rb] = ab(p);
      for (const key of run) {
        const owners = edges.get(key), s = new Set([lab[owners[0]], lab[owners[1]]]);
        if (s.size !== 2 || !s.has(ra) || !s.has(rb)) return;   // an earlier reroute moved this stretch
      }
      if (forced && run.some((k) => forced.has(k))) return;
      const runSet = new Set(run), runVerts = new Set(); for (const k of run) for (const v of ab(k)) runVerts.add(v);
      const corridor = new Set(); let ring = runVerts;
      for (let r = 0; r < REROUTE_RINGS; r++) {
        const grown = new Set();
        for (const v of ring) for (const f of vertFaces.get(v) || EMPTY) if ((lab[f] === ra || lab[f] === rb) && !corridor.has(f)) grown.add(f);
        for (const f of grown) corridor.add(f);
        ring = new Set(); for (const f of grown) for (const v of faces[f]) ring.add(v);
      }
      const allowed = new Set(runVerts);
      for (const f of corridor) for (const v of faces[f]) if (!blocked.has(v)) allowed.add(v);
      const adjacent = new Map();
      for (const f of corridor) {
        for (const key of faceKeys(faces[f])) {
          const [a, b] = ab(key);
          if (!allowed.has(a) || !allowed.has(b)) continue;
          const owners = edges.get(key);
          if (owners.length === 2 && owners.every((o) => lab[o] === ra || lab[o] === rb)) { getSet(adjacent, a).add(b); getSet(adjacent, b).add(a); }
        }
      }
      const path = cutPath(verts, adjacent, new Set([j0]), new Set([j1]), null, pull);
      if (!path.length) return;
      const nw = new Set(); for (let i = 0; i + 1 < path.length; i++) nw.add(pair(path[i], path[i + 1]));
      const same = nw.size === runSet.size && [...nw].every((k) => runSet.has(k));
      if (same || pathCost(verts, path, null, pull) >= pathCost(verts, runSeq(run, j0), null, pull)) return;
      // a reroute never trades crease for shortcut
      if (creasedShare(nw) < creasedShare(runSet)) return;
      // split the union along the new path, the old run no longer divides
      const union = unionSets(regionFaces.get(ra), regionFaces.get(rb));
      const parent = new Map(); for (const f of union) parent.set(f, f);
      for (const f of union) {
        for (const key of faceKeys(faces[f])) {
          if (nw.has(key)) continue;
          const owners = edges.get(key);
          if (owners.length !== 2) continue;
          const o = owners[0] === f ? owners[1] : owners[0];
          if (!parent.has(o)) continue;
          if (lab[f] !== lab[o] && !runSet.has(key)) continue;
          const fa = findM(parent, f), fb = findM(parent, o);
          if (fa !== fb) parent.set(fa, fb);
        }
      }
      const comps = new Map(); for (const f of union) getArr(comps, findM(parent, f)).push(f);
      if (comps.size !== 2) return;
      let [one, two] = [...comps.values()];
      const lean = (group) => group.reduce((s, f) => s + (lab[f] === ra ? areas[f] : -areas[f]), 0);
      if (lean(one) === lean(two)) return;
      if (lean(two) > lean(one)) [one, two] = [two, one];
      const floor = Math.min(ec([...union].filter((f) => lab[f] === ra)), ec([...union].filter((f) => lab[f] === rb)));
      if (Math.max(ec(one), ec(two)) > 1 || Math.min(ec(one), ec(two)) < floor) return;
      for (const f of one) lab[f] = ra;
      for (const f of two) lab[f] = rb;
      regionFaces.set(ra, new Set(one)); regionFaces.set(rb, new Set(two));
      for (const v of path) blocked.add(v);
    }
    for (const [p, keys] of pairKeys) for (const [run, j0, j1] of chains(keys)) reroute(p, run, j0, j1);
    return lab;
  }
  // edges between two regions
  function boundaryEdges(edges, label) {
    const out = new Set();
    for (const [key, owners] of edges) if (new Set(owners.map((o) => label[o])).size > 1) out.add(key);
    return out;
  }

  // ================================================================== seams/sweeps.py
  const SWEEP_BAND = 0.1, SWEEP_CAP_MIN = 0.02, SWEEP_MIN_SHARE = 0.01, SWEEP_MIN_FACES = 8, WALL_ROUND = 0.7;
  const SHARED_AXIS_COS = 0.95, PROFILE_BINS = 60, PROFILE_PEAK = 3.0, PROFILE_FLAT = 2.0, PROFILE_CORNER = 0.02, PROFILE_TURN = 45;
  const GENUS_TRIM_LEVELS = 24, CAP_SPLIT = 0.5, BAND_LO = 0.25, BAND_HI = 0.75, SWEEP_FIT_ROUNDS = 10;
  const RUN_SEED_FACES = 512, RUN_SLENDER = 0.2, VALLEY_SNAP_LAYERS = 6;

  function sym3(xx, yy, zz, xy, xz, yz) {
    const p1 = xy * xy + xz * xz + yz * yz, q = (xx + yy + zz) / 3;
    const p2 = (xx - q) ** 2 + (yy - q) ** 2 + (zz - q) ** 2 + 2 * p1, p = Math.sqrt(p2 / 6);
    const bxx = (xx - q) / p, byy = (yy - q) / p, bzz = (zz - q) / p, bxy = xy / p, bxz = xz / p, byz = yz / p;
    const det = bxx * (byy * bzz - byz * byz) - bxy * (bxy * bzz - byz * bxz) + bxz * (bxy * byz - byy * bxz);
    const phi = Math.acos(Math.max(-1, Math.min(1, det / 2))) / 3;
    return [q, p, phi];
  }
  // the cross of the two most independent rows of the shifted matrix
  function minEigenvector(xx, yy, zz, xy, xz, yz) {
    let lam;
    if (xy * xy + xz * xz + yz * yz === 0) lam = Math.min(xx, yy, zz);
    else { const [q, p, phi] = sym3(xx, yy, zz, xy, xz, yz); lam = q + 2 * p * Math.cos(phi + (2 * Math.PI) / 3); }
    const rows = [[xx - lam, xy, xz], [xy, yy - lam, yz], [xz, yz, zz - lam]];
    let best = null, bn = 0;
    for (let i = 0; i < 3; i++) for (let j = i + 1; j < 3; j++) { const c = cross(rows[i], rows[j]), n = vnorm(c); if (n > bn) { best = c; bn = n; } }
    if (best === null) return [1, 0, 0];   // degenerate: any direction is an eigenvector
    return best.map((x) => x / bn);
  }
  // largest first
  function eigenvalues3(xx, yy, zz, xy, xz, yz) {
    if (xy * xy + xz * xz + yz * yz === 0) return [xx, yy, zz].sort((a, b) => b - a);
    const [q, p, phi] = sym3(xx, yy, zz, xy, xz, yz);
    const high = q + 2 * p * Math.cos(phi), low = q + 2 * p * Math.cos(phi + (2 * Math.PI) / 3);
    return [high, 3 * q - high - low, low];
  }
  function moments(entries) {   // [[w, n]] -> the six sums
    const m = [0, 0, 0, 0, 0, 0];
    for (const [w, n] of entries) { m[0] += w * n[0] * n[0]; m[1] += w * n[1] * n[1]; m[2] += w * n[2] * n[2]; m[3] += w * n[0] * n[1]; m[4] += w * n[0] * n[2]; m[5] += w * n[1] * n[2]; }
    return m;
  }
  // refitting with cap normals repelled pulls the axis perpendicular to the walls
  function sweepAxis(normals) {
    const fit = (entries) => minEigenvector(...moments(entries));
    let axis = fit(normals);
    for (let r = 0; r < SWEEP_FIT_ROUNDS; r++) {
      const signed = normals.map(([w, n]) => [dot3(n, axis) ** 2 < CAP_SPLIT ? w : -w, n]);
      const refit = fit(signed);
      const done = Math.abs(Math.abs(dot3(axis, refit)) - 1) < 1e-12;
      axis = refit;
      if (done) break;
    }
    return axis;
  }
  // membership is read with findM
  function classComponents(group, isCap, edges, areas) {
    const inGroup = new Set(group), parent = new Map(), contact = new Map();
    for (const i of group) parent.set(i, i);
    for (const owners of edges.values()) {
      if (owners.length !== 2) continue;
      const [a, b] = owners;
      if (!inGroup.has(a) || !inGroup.has(b)) continue;
      if (isCap.get(a) === isCap.get(b)) { const ra = findM(parent, a), rb = findM(parent, b); if (ra !== rb) parent.set(ra, rb); }
      else addTo(contact, a + "," + b, 1);
    }
    const compArea = new Map();
    for (const i of group) addTo(compArea, findM(parent, i), areas[i]);
    return [parent, contact, compArea];
  }
  function touching(parent, contact, piece) {
    const touch = new Map();
    for (const [k, count] of contact) {
      const [a, b] = ab(k), ra = findM(parent, a), rb = findM(parent, b);
      if (ra !== rb && (piece === ra || piece === rb)) addTo(touch, ra === piece ? rb : ra, count);
    }
    return touch;
  }
  // a sliver's two boundary seams run a single face apart with no crease
  function mergeSlivers(wall, parent, contact, compArea, edges) {
    const inWall = new Set(wall);
    while (compArea.size > 1) {
      const exposed = new Set();
      for (const owners of edges.values()) {
        if (owners.length !== 2) continue;
        const [a, b] = owners, ai = inWall.has(a), bi = inWall.has(b);
        if (ai !== bi) exposed.add(ai ? a : b);
        else if (ai && findM(parent, a) !== findM(parent, b)) { exposed.add(a); exposed.add(b); }
      }
      const interior = new Map();
      for (const i of wall) if (!exposed.has(i)) addTo(interior, findM(parent, i), 1);
      const slivers = [...compArea.keys()].filter((c) => !g(interior, c));
      if (!slivers.length) return;
      const sliver = argMin(slivers, (c) => compArea.get(c));
      const touch = touching(parent, contact, sliver);
      if (!touch.size) return;
      const into = mostCommon(touch);
      parent.set(sliver, into); addTo(compArea, into, compArea.get(sliver)); compArea.delete(sliver);
    }
  }
  // a rim seam is not worth a speck
  function mergeSpecks(parent, contact, compArea, floor) {
    for (;;) {
      const speck = argMin(compArea.keys(), (c) => compArea.get(c));
      if (compArea.get(speck) >= floor || compArea.size < 2) break;
      const touch = touching(parent, contact, speck);
      if (!touch.size) break;
      const into = mostCommon(touch);
      parent.set(speck, into); addTo(compArea, into, compArea.get(speck)); compArea.delete(speck);
    }
  }
  // entries: Map face -> [area, unit normal]
  function normalFit(entries) {
    return (run) => {
      const picked = run.filter((i) => entries.has(i)).map((i) => entries.get(i));
      if (picked.length < SWEEP_MIN_FACES) return null;
      const axis = minEigenvector(...moments(picked));
      let total = 0, band = 0, wallMass = 0; const wallSum = [0, 0, 0];
      for (const [w, n] of picked) {
        const axial = dot3(n, axis) ** 2;
        total += w;
        if (BAND_LO < axial && axial < BAND_HI) band += w;
        if (axial < CAP_SPLIT) { wallMass += w; for (let k = 0; k < 3; k++) wallSum[k] += w * n[k]; }
      }
      // an end run carries the tube tip, but a run may not be mostly cap
      if (band > SWEEP_BAND * total || total - wallMass > total / 2) return null;
      if (!wallMass || vnorm(wallSum) / wallMass > WALL_ROUND) return null;
      return axis;
    };
  }
  const faceCentroid = (verts, face) => [0, 1, 2].map((k) => face.reduce((s, v) => s + verts[v][k], 0) / face.length);
  // a corrugated hose reads straight where the normal test sees a bend at each rib
  function slenderFit(verts, faces, areas, entries) {
    const centers = new Map();
    const center = (i) => { if (!centers.has(i)) centers.set(i, faceCentroid(verts, faces[i])); return centers.get(i); };
    return (run) => {
      if (run.length < SWEEP_MIN_FACES) return null;
      let total = 0; const mean = [0, 0, 0], resultant = [0, 0, 0];
      for (const i of run) {
        const w = areas[i], c = center(i); total += w;
        for (let k = 0; k < 3; k++) mean[k] += w * c[k];
        if (entries.has(i)) { const n = entries.get(i)[1]; for (let k = 0; k < 3; k++) resultant[k] += w * n[k]; }
      }
      if (!total) return null;
      if (vnorm(resultant) / total > WALL_ROUND) return null;
      for (let k = 0; k < 3; k++) mean[k] /= total;
      const m = [0, 0, 0, 0, 0, 0];
      for (const i of run) {
        const w = areas[i], c = center(i), d0 = c[0] - mean[0], d1 = c[1] - mean[1], d2 = c[2] - mean[2];
        m[0] += w * d0 * d0; m[1] += w * d1 * d1; m[2] += w * d2 * d2; m[3] += w * d0 * d1; m[4] += w * d0 * d2; m[5] += w * d1 * d2;
      }
      const [high, middle, low] = eigenvalues3(...m);
      if (high <= 0 || (middle + low) / high > RUN_SLENDER) return null;
      return minEigenvector(...m.map((x) => -x));
    };
  }
  // moves the cut to the deepest valley, the groove between ribs on a hose
  function valleySnap(verts, faces, edges, entries) {
    const score = (layer, nextLayer) => {
      const ahead = new Set(nextLayer); let total = 0;
      for (const f of layer) {
        if (!entries.has(f)) continue;
        const normal = entries.get(f)[1], base = faceCentroid(verts, faces[f]);
        for (const key of faceKeys(faces[f])) {
          const owners = edges.get(key);
          if (owners.length !== 2) continue;
          const other = owners[0] === f ? owners[1] : owners[0];
          if (!ahead.has(other) || !entries.has(other)) continue;
          const [v0, v1] = ab(key), length = dist3(verts[v1], verts[v0]);
          const turn = Math.acos(Math.max(-1, Math.min(1, dot3(normal, entries.get(other)[1]))));
          const toward = dot3(normal, sub3(faceCentroid(verts, faces[other]), base));
          total += length * turn * (toward > 0 ? 1 : -1);
        }
      }
      return total;
    };
    return (flat, ends, cut) => {
      let best = cut, bestScore = 0;
      for (let c = Math.max(2, cut - VALLEY_SNAP_LAYERS); c <= cut; c++) {
        const valley = score(flat.slice(ends[c - 2], ends[c - 1]), flat.slice(ends[c - 1], ends[c]));
        if (valley > bestScore) { best = c; bestScore = valley; }
      }
      return best;
    };
  }
  // the walk runs after absorb and nothing width-checks its leftovers
  function mergeShed(group, relabel, label, verts, faces, edges, areas, minWidth) {
    if (!minWidth) return;
    const inGroup = new Set(group);
    const shed = group.filter((i) => !relabel.has(i));
    for (const comp of componentFaces(shed, edges)) {
      const inComp = new Set(comp); let area = 0, perimeter = 0; const touch = new Map();
      for (const i of comp) {
        area += areas[i];
        for (const key of faceKeys(faces[i])) {
          const owners = edges.get(key);
          const other = owners.length === 2 ? (owners[0] === i ? owners[1] : owners[0]) : null;
          if (other !== null && inComp.has(other)) continue;
          const [v0, v1] = ab(key), length = dist3(verts[v1], verts[v0]);
          perimeter += length;
          if (other === null) continue;
          if (inGroup.has(other)) { if (relabel.has(other)) addTo(touch, relabel.get(other), length); }
          else addTo(touch, relabel.has(other) ? relabel.get(other) : label[other], length);
        }
      }
      if (perimeter <= 0 || (2 * area) / perimeter >= minWidth || !touch.size) continue;
      const into = mostCommon(touch);
      for (const i of comp) relabel.set(i, into);
    }
  }
  function unitNormals(weighted, areas, group) {
    const out = [];
    for (const i of group) { const n = weighted[i], l = vnorm(n); if (l) out.push([i, areas[i], n.map((x) => x / l)]); }
    return out;
  }
  // end caps kept give a polar map no distortion measure catches
  function splitSweeps(verts, faces, weighted, areas, edges, label, minWidth = 0, modelArea = null, faceIds = null) {
    const members = new Map();
    label.forEach((r, i) => getArr(members, r).push(i));
    if (modelArea == null) modelArea = areas.reduce((s, a) => s + a, 0);
    const relabel = new Map();
    for (const group of members.values()) {
      const axial = new Map(), normals = unitNormals(weighted, areas, group);
      const total = normals.reduce((s, x) => s + x[1], 0);
      if (normals.length < SWEEP_MIN_FACES || total < SWEEP_MIN_SHARE * modelArea) continue;
      const axis = sweepAxis(normals.map(([, w, n]) => [w, n]));
      let band = 0, cap = 0;
      for (const [i, w, n] of normals) {
        const a = dot3(n, axis) ** 2; axial.set(i, a);
        if (BAND_LO < a && a < BAND_HI) band += w;
        if (a >= CAP_SPLIT) cap += w;
      }
      if (band > SWEEP_BAND * total) {
        // normals catch a fat smooth tube, positions catch a corrugated hose
        const entries = new Map(normals.map(([i, w, n]) => [i, [w, n]]));
        const byNormals = normalFit(entries), byPositions = slenderFit(verts, faces, areas, entries);
        const either = (run) => byNormals(run) || byPositions(run);
        const snap = valleySnap(verts, faces, edges, entries);
        for (const [run] of straightRuns(group, entries, edges, either, snap, faceIds)) for (const i of run) relabel.set(i, run[0]);
        mergeShed(group, relabel, label, verts, faces, edges, areas, minWidth);
        continue;
      }
      if (!(SWEEP_CAP_MIN * total <= cap && cap <= total / 2)) continue;
      const wallSum = [0, 0, 0];
      for (const [i, w, n] of normals) if (axial.get(i) < CAP_SPLIT) for (let k = 0; k < 3; k++) wallSum[k] += w * n[k];
      if (vnorm(wallSum) / (total - cap) > WALL_ROUND) continue;
      const isCap = new Map(group.map((i) => [i, (axial.get(i) || 0) >= CAP_SPLIT]));
      const [parent, contact, compArea] = classComponents(group, isCap, edges, areas);
      mergeSpecks(parent, contact, compArea, SWEEP_CAP_MIN * total);
      if (compArea.size < 2) continue;
      for (const i of group) relabel.set(i, findM(parent, i));
    }
    if (!relabel.size) return label;
    return label.map((r, i) => (relabel.has(i) ? relabel.get(i) : r));
  }
  function componentFaces(subset, edges) {
    const inSet = new Set(subset), parent = new Map();
    for (const i of subset) parent.set(i, i);
    for (const owners of edges.values()) {
      if (owners.length === 2 && inSet.has(owners[0]) && inSet.has(owners[1])) { const ra = findM(parent, owners[0]), rb = findM(parent, owners[1]); if (ra !== rb) parent.set(ra, rb); }
    }
    const groups = new Map();
    for (const i of subset) getArr(groups, findM(parent, i)).push(i);
    return [...groups.values()];
  }
  // above 0 a handle runs through the surface and no cut diskCuts places opens it
  function surfaceGenus(subset, faces, edges) {
    const inSet = new Set(subset), used = new Set(), keys = new Set();
    for (const i of subset) { for (const v of faces[i]) used.add(v); for (const k of faceKeys(faces[i])) keys.add(k); }
    const euler = used.size - keys.size + subset.length;
    const parent = new Map();
    for (const key of keys) {
      if (edges.get(key).filter((o) => inSet.has(o)).length !== 1) continue;
      const [v0, v1] = ab(key);
      if (!parent.has(v0)) parent.set(v0, v0);
      if (!parent.has(v1)) parent.set(v1, v1);
      const ra = findM(parent, v0), rb = findM(parent, v1);
      if (ra !== rb) parent.set(ra, rb);
    }
    const loops = new Set([...parent.keys()].map((v) => findM(parent, v))).size;
    return Math.floor((2 - loops - euler) / 2);
  }
  // a handle through a wall makes a surface no flatten can open
  function trimGenus(wall, verts, faces, edges, areas, axis) {
    const kept = new Set();
    for (const comp of componentFaces([...wall], edges)) {
      if (surfaceGenus(comp, faces, edges) <= 0) { for (const i of comp) kept.add(i); continue; }
      const position = new Map(comp.map((i) => [i, dot3(faceCentroid(verts, faces[i]), axis)]));
      const ordered = comp.slice().sort((a, b) => position.get(a) - position.get(b));
      let best = null;
      for (const direction of [ordered, ordered.slice().reverse()]) {
        for (let level = 1; level < GENUS_TRIM_LEVELS; level++) {
          const cut = Math.floor((comp.length * level) / GENUS_TRIM_LEVELS), rest = direction.slice(cut);
          if (!rest.length) break;
          if (componentFaces(rest, edges).every((p) => surfaceGenus(p, faces, edges) <= 0)) {
            const loss = direction.slice(0, cut).reduce((s, i) => s + areas[i], 0);
            if (best === null || loss < best[0]) best = [loss, rest];
            break;
          }
        }
      }
      if (best !== null && best[0] <= comp.reduce((s, i) => s + areas[i], 0) / 2) for (const i of best[1]) kept.add(i);
    }
    return kept;
  }
  // a hoop unrolls into a strip past the slicer bound and rims would shred it
  function wallHoops(wall, axis, verts, faces, edges) {
    let boundary = 0;
    for (const i of wall) for (const key of faceKeys(faces[i])) {
      const owners = edges.get(key);
      if (owners.length === 2 && wall.has(owners[0]) !== wall.has(owners[1])) { const [v0, v1] = ab(key); boundary += dist3(verts[v1], verts[v0]); }
    }
    const along = []; for (const i of wall) for (const v of faces[i]) along.push(dot3(verts[v], axis));
    const extent = along.length ? Math.max(...along) - Math.min(...along) : 0;
    return boundary > 0 && (extent <= 0 || boundary / 2 > SPLIT_ASPECT * extent);
  }
  // the group's wall faces after the cap split, the genus trim and the hoop check
  function claimWall(group, axial, axis, total, verts, faces, edges, areas) {
    const isCap = new Map(group.map((i) => [i, (axial.get(i) || 0) >= CAP_SPLIT]));
    const [parent, contact, compArea] = classComponents(group, isCap, edges, areas);
    const cls = new Map(); for (const i of group) cls.set(findM(parent, i), isCap.get(i));
    mergeSpecks(parent, contact, compArea, SWEEP_CAP_MIN * total);
    let wall = new Set(group.filter((i) => !cls.get(findM(parent, i))));
    wall = trimGenus(wall, verts, faces, edges, areas, axis);
    if (!wall.size) return new Set();
    if (wallHoops(wall, axis, verts, faces, edges)) return new Set();
    return wall;
  }
  // reachable faces grouped by steps taken from the seed
  function spreadRings(adjacency, seed, allowed) {
    const layers = [[seed]], seen = new Set([seed]);
    for (;;) {
      const grown = [];
      for (const face of layers[layers.length - 1]) for (const other of adjacency.get(face) || EMPTY) if (allowed.has(other) && !seen.has(other)) { seen.add(other); grown.push(other); }
      if (!grown.length) return layers;
      layers.push(grown);
    }
  }
  const bisectLeft = (arr, x) => { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] < x) lo = m + 1; else hi = m; } return lo; };
  const bisectRight = (arr, x) => { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; if (x < arr[m]) hi = m; else lo = m + 1; } return lo; };
  // narrow panels are what let rectify straighten a bowed shell
  function profilePanels(wall, axis, entries, edges, areas) {
    let u = null;
    for (const cand of [[1, 0, 0], [0, 1, 0]]) { const c = cross(axis, cand), l = vnorm(c); if (l > 0.1) { u = c.map((x) => x / l); break; } }
    const v = cross(axis, u), theta = new Map(), mass = new Array(PROFILE_BINS).fill(0);
    for (const i of wall) {
      if (!entries.has(i)) continue;
      const [w, n] = entries.get(i), axialN = dot3(n, axis), perp = n.map((x, k) => x - axialN * axis[k]);
      if (vnorm(perp) <= 0) continue;
      const angle = Math.atan2(dot3(perp, v), dot3(perp, u));
      theta.set(i, angle);
      const b = Math.floor(((angle + Math.PI) / (2 * Math.PI)) * PROFILE_BINS);
      mass[Math.min(b, PROFILE_BINS - 1)] += w;
    }
    const total = mass.reduce((s, x) => s + x, 0), uniform = total / PROFILE_BINS;
    if (uniform <= 0 || Math.max(...mass) < PROFILE_PEAK * uniform) return null;
    const flat = mass.map((m) => m > PROFILE_FLAT * uniform);
    const starts = []; for (let b = 0; b < PROFILE_BINS; b++) if (flat[b] && !flat[mod(b - 1, PROFILE_BINS)]) starts.push(b);
    if (starts.length < 2) return null;
    const runs = starts.map((start) => { let length = 1; while (flat[(start + length) % PROFILE_BINS]) length++; return [start, length]; });
    const cuts = [];
    runs.forEach(([start, length], k) => {
      const [following, nextLength] = runs[(k + 1) % runs.length];
      const gap = []; for (let j = 0; j < mod(following - start - length, PROFILE_BINS); j++) gap.push((start + length + j) % PROFILE_BINS);
      if (!gap.length || gap.reduce((s, x) => s + mass[x], 0) < PROFILE_CORNER * total) return;
      const mid = start + (length - 1) / 2, nextMid = following + (nextLength - 1) / 2;
      const turn = (mod(nextMid - mid, PROFILE_BINS) * 360) / PROFILE_BINS;
      if (turn < PROFILE_TURN) return;
      const centre = (gap.length - 1) / 2;
      let low = 0;
      for (let j = 1; j < gap.length; j++) if (cmpT([mass[gap[j]], Math.abs(j - centre)], [mass[gap[low]], Math.abs(low - centre)]) < 0) low = j;
      cuts.push(-Math.PI + ((gap[low] + 0.5) * 2 * Math.PI) / PROFILE_BINS);
    });
    if (cuts.length < 2) return null;
    cuts.sort((a, b) => a - b);
    const panel = new Map(); for (const i of wall) panel.set(i, -1);
    for (const [i, angle] of theta) panel.set(i, bisectLeft(cuts, angle) % cuts.length);
    const wallList = [...wall], wallArea = wallList.reduce((s, i) => s + areas[i], 0);
    const [parent, contact, compArea] = classComponents(wallList, panel, edges, areas);
    mergeSpecks(parent, contact, compArea, SWEEP_CAP_MIN * wallArea);
    mergeSlivers(wallList, parent, contact, compArea, edges);
    if (compArea.size < 2) return null;
    return new Map(wallList.map((i) => [i, findM(parent, i)]));
  }
  const idsOf = (fs, faceIds) => (faceIds == null ? fs : fs.map((i) => faceIds[i]));
  // a coiled cable fails the whole-cluster test though every short piece is a tube
  function straightRuns(group, entries, edges, fitOf = null, snap = null, faceIds = null) {
    const inGroup = new Set(group), adjacency = new Map();
    for (const owners of edges.values()) if (owners.length === 2 && inGroup.has(owners[0]) && inGroup.has(owners[1])) { getArr(adjacency, owners[0]).push(owners[1]); getArr(adjacency, owners[1]).push(owners[0]); }
    if (!fitOf) fitOf = normalFit(entries);
    const remaining = new Set(group), ids = idsOf(group, faceIds), picks = new Set(ids);
    const local = new Map(ids.map((id, k) => [id, group[k]]));
    const runs = []; let seed = null;
    while (remaining.size) {
      if (seed === null || !remaining.has(seed)) { const rings = spreadRings(adjacency, local.get(first(picks)), remaining); seed = rings[rings.length - 1][0]; }
      const layers = spreadRings(adjacency, seed, remaining), flat = [], ends = [];
      for (const layer of layers) { flat.push(...layer); ends.push(flat.length); }
      const count = layers.length;
      let span = count;
      for (let d = 1; d <= ends.length; d++) if (ends[d - 1] >= RUN_SEED_FACES) { span = d; break; }
      let low = 0, axis = null, probe = 1;
      while (probe < span) { const fit = fitOf(flat.slice(0, ends[probe - 1])); if (fit) { low = probe; axis = fit; break; } probe *= 2; }
      if (axis === null) {
        const fit = fitOf(flat.slice(0, ends[span - 1]));
        if (fit) { low = span; axis = fit; }
        else {
          // nothing straight near this seed
          const dropped = flat.slice(0, ends[span - 1]);
          for (const f of dropped) remaining.delete(f);
          for (const id of idsOf(dropped, faceIds)) picks.delete(id);
          seed = span < count ? layers[span][0] : null;
          continue;
        }
      }
      let high = null;
      while (high === null && low < count) { const pr = Math.min(low * 2, count), fit = fitOf(flat.slice(0, ends[pr - 1])); if (fit) { low = pr; axis = fit; } else high = pr; }
      while (high !== null && high - low > 1) { const mid = (low + high) >> 1, fit = fitOf(flat.slice(0, ends[mid - 1])); if (fit) { low = mid; axis = fit; } else high = mid; }
      if (snap && 1 < low && low < count) low = snap(flat, ends, low);
      const run = flat.slice(0, ends[low - 1]);
      runs.push([run, axis]);
      for (const f of run) remaining.delete(f);
      for (const id of idsOf(run, faceIds)) picks.delete(id);
      seed = low < count ? layers[low][0] : null;
    }
    return runs;
  }
  // absorb never checks how far a boundary turns, so this reads before any merge
  function sweepRims(verts, faces, modelArea = null, faceIds = null, built = null) {
    const [weighted, areas, edges] = built || build(verts, faces);
    const rootFn = partition(faces, weighted, edges, CREASE_ANGLE);
    const groups = new Map();
    for (let i = 0; i < faces.length; i++) getArr(groups, rootFn(i)).push(i);
    if (modelArea == null) modelArea = areas.reduce((s, a) => s + a, 0);
    const walls = new Set(), wallAxis = new Map(), wallRun = new Map(), wallCluster = new Map(), wallPanel = new Map();
    let runCount = 0;
    const claim = (run, axis, clusterId, axial, total, entries) => {
      const wall = claimWall(run, axial, axis, total, verts, faces, edges, areas);
      if (!wall.size) return;
      runCount++;
      for (const i of wall) walls.add(i);
      const panels = profilePanels(wall, axis, entries, edges, areas);
      for (const i of wall) { wallAxis.set(i, axis); wallRun.set(i, runCount); wallCluster.set(i, clusterId); if (panels) wallPanel.set(i, panels.get(i)); }
    };
    for (const group of groups.values()) {
      const normals = unitNormals(weighted, areas, group);
      const total = normals.reduce((s, x) => s + x[1], 0);
      if (normals.length < SWEEP_MIN_FACES || total < SWEEP_MIN_SHARE * modelArea) continue;
      const axis = minEigenvector(...moments(normals.map(([, w, n]) => [w, n])));
      const axial = new Map(); let band = 0, offWall = 0; const resultant = [0, 0, 0];
      for (const [i, w, n] of normals) {
        const a = dot3(n, axis) ** 2; axial.set(i, a);
        if (a > BAND_LO) offWall += w;
        if (BAND_LO < a && a < BAND_HI) band += w;
        for (let k = 0; k < 3; k++) resultant[k] += w * n[k];
      }
      const entries = new Map(normals.map(([i, w, n]) => [i, [w, n]]));
      // of those only a bent tube fills the middle band
      if (offWall > SWEEP_BAND * total || vnorm(resultant) / total > WALL_ROUND) {
        if (band > SWEEP_BAND * total) {
          for (const [run, runAxis] of straightRuns(group, entries, edges, null, null, faceIds)) {
            const runAxial = new Map(); let runTotal = 0;
            for (const i of run) if (entries.has(i)) { const [w, n] = entries.get(i); runTotal += w; runAxial.set(i, dot3(n, runAxis) ** 2); }
            claim(run, runAxis, group[0], runAxial, runTotal, entries);
          }
        }
        continue;
      }
      claim(group, axis, group[0], axial, total, entries);
    }
    if (!walls.size) return [new Set(), walls];
    const rims = new Set();
    for (const [key, owners] of edges) {
      if (owners.length !== 2) continue;
      const [a, b] = owners, inA = walls.has(a), inB = walls.has(b);
      if (inA !== inB) rims.add(key);
      else if (inA && wallRun.get(a) !== wallRun.get(b)) {
        // runs of one bent tube always part, that cut is what made them straight
        if (wallCluster.get(a) === wallCluster.get(b)) rims.add(key);
        else if (Math.abs(dot3(wallAxis.get(a), wallAxis.get(b))) < SHARED_AXIS_COS) rims.add(key);
      } else if (inA && wallPanel.get(a) !== wallPanel.get(b)) rims.add(key);
    }
    return [rims, walls];
  }

  // ================================================================== seams/pipeline.py
  // the forced edges with the sweep rims added, and the wall faces
  function rimCuts(verts, faces, rims, forced = null, whole = null, built = null) {
    if (!rims) return [forced, null];
    const [modelArea, faceIds] = whole == null ? [null, null] : [whole.modelArea, whole.faceIds];
    const [rimEdges, walls] = sweepRims(verts, faces, modelArea, faceIds, built);
    if (rimEdges.size) return [unionSets(rimEdges, forced), walls];
    return [forced, walls];
  }
  // walls partition as one region however sharply the coarse wall turns
  function lowPartition(verts, faces, forced = null, walls = null, built = null) {
    const [weighted, areas, edges] = built || build(verts, faces);
    let smooth = null;
    if (walls && walls.size) {
      smooth = new Set();
      for (const [key, owners] of edges) if (owners.length === 2 && walls.has(owners[0]) && walls.has(owners[1])) smooth.add(key);
    }
    return [weighted, areas, edges, partition(faces, weighted, edges, LOW_ANGLE, forced, smooth)];
  }
  // a run over one loose part gets the seams the whole run would
  function wholeMeshInputs(verts, faces, rims = true, forced = null) {
    const built = build(verts, faces);
    const [cutFromStart, walls] = rimCuts(verts, faces, rims, forced, null, built);
    const [, areas, edges, rootFn] = lowPartition(verts, faces, cutFromStart, walls, built);
    const usedVerts = verts;
    return [detectWidth(usedVerts, faces, areas, edges, rootFn, diagonal(verts)), areas.reduce((s, a) => s + a, 0)];
  }
  // what survives the merges is the feature structure the seams will trace
  function featureLabels(verts, faces, angle = CREASE_ANGLE, rims = true, forced = null, scale = null, walls = null, whole = null, built = null) {
    const [weighted, areas, edges, rootFn] = lowPartition(verts, faces, forced, walls, built);
    let minWidth, modelArea = null, faceIds = null;
    if (whole == null) { if (scale == null) scale = diagonal(verts); minWidth = detectWidth(verts, faces, areas, edges, rootFn, scale); }
    else ({ minWidth, modelArea, faceIds } = whole);
    let [label, bounds] = absorb(verts, faces, weighted, areas, edges, rootFn, minWidth, forced);
    label = mergeSmooth(edges, label, bounds, minWidth, angle, forced);
    label = mergeFlat(weighted, areas, edges, label, angle, forced);
    label = closeRings(verts, weighted, areas, edges, label, angle, forced);
    const presplit = label;
    if (rims) label = splitSweeps(verts, faces, weighted, areas, edges, label, minWidth, modelArea, faceIds);
    const locked = new Set();
    for (const [key, owners] of edges) {
      if (owners.length !== 2) continue;
      const [a, b] = owners;
      if (label[a] === label[b]) continue;
      if ((forced && forced.has(key)) || presplit[a] === presplit[b]) locked.add(pair(label[a], label[b]));
    }
    return [weighted, areas, edges, label, minWidth, locked];
  }
  // one region covering the part means no structure, a smooth blob
  const ORGANIC_SHARE = 0.9, FRAGMENT_FACES = 8, SPREAD_ANGLE = 25, SPREAD_SHARE = 0.21, BOUNDARY_ANGLE = 20;
  const BOUNDARY_CREASED = 0.6, BOUNDARY_CREASED_ALONE = 0.8, ASSEMBLY_PIECE_SHARE = 0.5, COPLANAR_ANGLE = 0.01, COPLANAR_SHARE = 0.4;
  // ties fall organic, seams on sculpt ridges cost more than a slow unwrap
  function isHardSurface(verts, faces0, modelArea = null) {
    // a planar quad's diagonal is coplanar too
    const polygonEdges = new Set(); for (const f of faces0) for (const k of faceKeys(f)) polygonEdges.add(k);
    // the thresholds were tuned on triangles, quad diagonals change every share
    const faces = [];
    for (const f of faces0) for (let i = 1; i + 1 < f.length; i++) faces.push([f[0], f[i], f[i + 1]]);
    const used = new Set(); for (const f of faces) for (const v of f) used.add(v);
    const partScale = diagonal([...used].map((v) => verts[v]));
    const built = build(verts, faces);
    const [rims, walls] = sweepRims(verts, faces, null, null, built);
    const [weighted, areas, edges, presweep] = featureLabels(verts, faces, CREASE_ANGLE, false, rims.size ? rims : null, partScale, walls, null, built);
    const label = splitSweeps(verts, faces, weighted, areas, edges, presweep);
    const total = areas.reduce((s, a) => s + a, 0);
    if (total <= 0) return false;
    const region = new Map(); label.forEach((r, i) => addTo(region, r, areas[i]));
    // a smooth cylinder's wall is one big region, so the organic guard skips it
    const wallRegions = new Set([...walls].map((i) => label[i]));
    const top = argBest(region.keys(), (r) => region.get(r), (a, b) => a > b);
    if (region.get(top) / total >= ORGANIC_SHARE && !wallRegions.has(top)) return false;
    if (faces.length / region.size < FRAGMENT_FACES) {
      // a low poly box trips FRAGMENT_FACES too, only curled regions are noise
      const rootFn = partition(faces, weighted, edges, LOW_ANGLE), panels = new Map();
      for (let i = 0; i < faces.length; i++) getArr(panels, rootFn(i)).push(i);
      if (panelShare(weighted, panels.values()) < PANEL_SHARE) return false;
    }
    let near = new Set();
    for (const owners of edges.values()) if (owners.length === 2 && label[owners[0]] !== label[owners[1]]) { near.add(owners[0]); near.add(owners[1]); }
    // two rings, so a dissolved bevel band beside a seam stays out
    for (let r = 0; r < 2; r++) {
      const grown = new Set(near);
      for (const owners of edges.values()) if (owners.length === 2 && owners.some((o) => near.has(o))) { grown.add(owners[0]); grown.add(owners[1]); }
      near = grown;
    }
    let spread = 0, interior = 0, boundary = 0, boundaryCreased = 0, modeled = 0, coplanar = 0;
    for (const [key, owners] of edges) {
      if (owners.length !== 2) continue;
      const [a, b] = ab(key), length = dist3(verts[a], verts[b]), turn = turnAngle(weighted, owners);
      if (polygonEdges.has(key)) { modeled += length; if (turn < COPLANAR_ANGLE) coplanar += length; }
      if (label[owners[0]] !== label[owners[1]]) {
        boundary += length;
        if (turn >= BOUNDARY_ANGLE || presweep[owners[0]] === presweep[owners[1]]) boundaryCreased += length;
      } else if (!near.has(owners[0]) && !near.has(owners[1])) {
        // wall curvature is explained by the sweep, not sculpt detail
        if (walls.has(owners[0]) && walls.has(owners[1])) continue;
        interior += length;
        if (LOW_ANGLE < turn && turn < SPREAD_ANGLE) spread += length;
      }
    }
    if (modeled && coplanar / modeled >= COPLANAR_SHARE) return true;
    if (!boundary) return false;
    const creased = boundaryCreased / boundary;
    const piece = modelArea != null && total / modelArea < ASSEMBLY_PIECE_SHARE;
    if (piece && creased >= BOUNDARY_CREASED_ALONE) return true;
    return (!interior || spread / interior < SPREAD_SHARE) && creased >= BOUNDARY_CREASED;
  }
  // a caller joining parts decides the rerun for all of them
  function seamsAtAngle(verts, faces, angle, rims, weights, forced, whole, built = null) {
    if (!built) built = build(verts, faces);
    const [cutFromStart, walls] = rimCuts(verts, faces, rims, forced, whole, built);
    let [weighted, areas, edges, label, minWidth, locked] = featureLabels(verts, faces, angle, rims, cutFromStart, null, walls, whole, built);
    label = flattenTeeth(weighted, faces, edges, label, angle, forced);
    const relief = creaseRelief(verts, faces, weighted, edges);
    label = rerouteBoundaries(verts, faces, areas, edges, label, relief, forced);
    // everything since absorb can leave a region under its width floor
    [label] = absorb(verts, faces, weighted, areas, edges, (i) => label[i], minWidth, forced, locked);
    const hinges = rims ? unfoldHinges(verts, faces, weighted, edges, label, cutFromStart) : new Set();
    // diskCuts counts in-region forced edges as slits, so it gets only user marks
    const seams = boundaryEdges(edges, label);
    for (const h of hinges) seams.delete(h);
    for (const k of diskCuts(verts, edges, label, weights, relief, forced)) seams.add(k);
    if (forced) for (const k of forced) seams.add(k);
    let closed = true; for (const owners of edges.values()) if (owners.length === 1) { closed = false; break; }
    return [seams, closed];
  }
  // a closed mesh with every feature under the angle reruns at the CREASE_ANGLE floor
  function seamEdgesRaw(verts, faces, angle = CREASE_ANGLE, rims = true, weights = null, forced = null, whole = null) {
    const built = build(verts, faces);
    let [seams, closed] = seamsAtAngle(verts, faces, angle, rims, weights, forced, whole, built);
    if (!seams.size && angle > CREASE_ANGLE && closed) [seams] = seamsAtAngle(verts, faces, CREASE_ANGLE, rims, weights, forced, whole, built);
    return seams;
  }
  // seams/parallel.py without the worker processes: each loose part runs on its own with the whole mesh's inputs
  function seamEdgesParts(verts, faces, angle, rims, weights, forced, whole) {
    const parts = vertexComponents(faces);
    if (parts.length < 2) return seamEdgesRaw(verts, faces, angle, rims, weights, forced, whole);
    let minWidth, modelArea;
    if (whole == null) [minWidth, modelArea] = wholeMeshInputs(verts, faces, rims, forced);
    else ({ minWidth, modelArea } = whole);
    const run = (ang) => {
      const seams = new Set(); let closed = true;
      for (const part of parts) {
        const ids = whole && whole.faceIds ? part.map((i) => whole.faceIds[i]) : part;
        const [s, c] = seamsAtAngle(verts, part.map((i) => faces[i]), ang, rims, weights, forced, { minWidth, modelArea, faceIds: ids });
        for (const k of s) seams.add(k);
        closed = closed && c;
      }
      return [seams, closed];
    };
    let [seams, closed] = run(angle);
    if (!seams.size && angle > CREASE_ANGLE && closed) [seams] = run(CREASE_ANGLE);
    return seams;
  }
  // preseed.py: a marked part is hard however its geometry reads
  function hardFacesRaw(verts, faces, marks, marked = "NONE") {
    const markedVerts = new Set();
    if (marked !== "NONE" && marks) for (const k of marks) for (const v of ab(k)) markedVerts.add(v);
    const modelArea = faces.reduce((s, f) => s + polygonArea(verts, f), 0);
    const hard = new Set();
    for (const comp of vertexComponents(faces)) {
      const touches = markedVerts.size && comp.some((fi) => faces[fi].some((v) => markedVerts.has(v)));
      if (touches || (marked !== "ONLY" && isHardSurface(verts, comp.map((fi) => faces[fi]), modelArea))) for (const fi of comp) hard.add(fi);
    }
    return hard;
  }
  // preseed.py: a closed part no seam touches folds onto itself in the flatten
  function flattenable(subset, edges, seams) {
    const parent = new Map(); for (const f of subset) parent.set(f, f);
    const keeps = new Set();
    for (const [key, owners] of edges) {
      const inside = owners.filter((f) => parent.has(f));
      if (!inside.length) continue;
      const r = findM(parent, inside[0]);
      for (const f of inside.slice(1)) parent.set(findM(parent, f), r);
      if (inside.length === 1 || seams.has(key)) keeps.add(inside[0]);
    }
    const keptRoots = new Set([...keeps].map((f) => findM(parent, f)));
    return subset.filter((f) => keptRoots.has(findM(parent, f)));
  }

  // ================================================================== seams/islands.py
  const SPLIT_TARGET = 0.5, SPLIT_NECK = 0.5, SPLIT_DISTORTION = 8.0, SPLIT_STEP = 2.5, STRAIGHTEN_SWEEPS = 4;
  const SPLIT_ARC_BAND = 0.65, SPLIT_ARC_ANNULUS = 0.3, FRAGMENT_SHARE = 0.002, SPLIT_GAP = 0.98;

  // by fan, the same fan the flatten solves
  function polygonArea(verts, face) {
    const p0 = verts[face[0]]; let total = 0;
    for (let i = 1; i + 1 < face.length; i++) total += vnorm(cross(sub3(verts[face[i]], p0), sub3(verts[face[i + 1]], p0))) / 2;
    return total;
  }
  // corners glue across interior non-seam edges, so a cut-open tube is a disk. -> [euler, loops (Sets of mesh verts)]
  function uvTopology(group, faces, edges, seams) {
    const nodeOf = new Map(), vertOf = [];
    for (const f of group) for (const v of faces[f]) { const k = f + "|" + v; if (!nodeOf.has(k)) { nodeOf.set(k, vertOf.length); vertOf.push(v); } }
    const parent = new Int32Array(vertOf.length).map((_, i) => i);
    const union = (a, b) => { const ra = findA(parent, a), rb = findA(parent, b); if (ra !== rb) parent[ra] = rb; };
    const inGroup = new Set(group);
    for (const f of group) {
      const face = faces[f], n = face.length;
      for (let i = 0; i < n; i++) {
        const u = face[i], v = face[(i + 1) % n], key = pair(u, v), owners = edges.get(key);
        if (owners.length === 2 && !seams.has(key)) {
          const o = owners[0] === f ? owners[1] : owners[0];
          if (o !== f && f < o && inGroup.has(o)) { union(nodeOf.get(f + "|" + u), nodeOf.get(o + "|" + u)); union(nodeOf.get(f + "|" + v), nodeOf.get(o + "|" + v)); }
        }
      }
    }
    const edgeCount = new Map();
    for (const f of group) {
      const face = faces[f], n = face.length, roots = face.map((v) => findA(parent, nodeOf.get(f + "|" + v)));
      for (let i = 0; i < n; i++) addTo(edgeCount, pair(roots[i], roots[(i + 1) % n]), 1);
    }
    const classes = new Set(); for (let i = 0; i < parent.length; i++) classes.add(findA(parent, i));
    const ec = classes.size - edgeCount.size + group.length;
    const compParent = new Map(), boundary = [...edgeCount].filter(([, c]) => c === 1).map(([k]) => ab(k));
    for (const [a, b] of boundary) {
      if (!compParent.has(a)) compParent.set(a, a);
      if (!compParent.has(b)) compParent.set(b, b);
      const ra = findM(compParent, a), rb = findM(compParent, b);
      if (ra !== rb) compParent.set(ra, rb);
    }
    const loops = new Map();
    for (const [a, b] of boundary) { const s = getSet(loops, findM(compParent, a)); s.add(vertOf[a]); s.add(vertOf[b]); }
    return [ec, [...loops.values()]];
  }
  // segments sharing an endpoint always read as crossing, skip those pairs
  function crosses(a, b, c, d) {
    const a1 = signedArea([a, b, d]), a2 = signedArea([a, b, c]);
    if (a1 * a2 > 0) return false;
    const a3 = signedArea([c, d, a]), a4 = a3 + a2 - a1;
    if (a3 * a4 > 0) return false;
    if (a1 === 0 && a2 === 0) {
      const abx = b[0] - a[0], aby = b[1] - a[1], sq = abx * abx + aby * aby;
      if (sq === 0) return false;
      const cc = ((c[0] - a[0]) * abx + (c[1] - a[1]) * aby) / sq, cd = ((d[0] - a[0]) * abx + (d[1] - a[1]) * aby) / sq;
      const lo = Math.min(cc, cd), hi = Math.max(cc, cd);
      return !(lo > 1 || hi < 0);
    }
    return true;
  }
  const same2 = (p, q) => p[0] === q[0] && p[1] === q[1];
  // what makes the engine throw the island's layout away and re-cut it. uvs: per face, its corners' [u, v]
  function islandRuined(group, faces, uvs, edges, seams, uvAreas = null, euler = null) {
    const signed = group.map((f) => (uvAreas ? uvAreas[f] : signedArea(uvs[f])));
    const total = signed.reduce((s, x) => s + x, 0);
    if (total === 0 || signed.some((s) => s * total <= 0)) return true;
    if (euler == null) [euler] = uvTopology(group, faces, edges, seams);
    if (euler !== 1) return true;
    const segs = [];
    for (const f of group) {
      const face = faces[f], n = face.length;
      for (let i = 0; i < n; i++) { const key = pair(face[i], face[(i + 1) % n]); if (seams.has(key) || edges.get(key).length !== 2) segs.push([uvs[f][i], uvs[f][(i + 1) % n]]); }
    }
    if (!segs.length) return true;   // an island with no boundary cannot be flat
    const cell = segs.reduce((s, [a, b]) => s + dist2(a, b), 0) / segs.length;
    if (cell === 0) return true;
    const grid = new Map();
    segs.forEach(([a, b], idx) => {
      const x0 = Math.min(a[0], b[0]), x1 = Math.max(a[0], b[0]), y0 = Math.min(a[1], b[1]), y1 = Math.max(a[1], b[1]);
      for (let cx = Math.floor(x0 / cell); cx <= Math.floor(x1 / cell); cx++) for (let cy = Math.floor(y0 / cell); cy <= Math.floor(y1 / cell); cy++) getArr(grid, cx + "," + cy).push(idx);
    });
    const seen = new Set();
    for (const members of grid.values()) {
      for (let i = 0; i < members.length; i++) for (let j = i + 1; j < members.length; j++) {
        const ei = members[i], ej = members[j], key = ei < ej ? ei + "," + ej : ej + "," + ei;
        if (seen.has(key)) continue;
        seen.add(key);
        const [a, b] = segs[ei], [c, d] = segs[ej];
        // touching means a shared uv corner, not a mesh vertex
        if (same2(a, c) || same2(a, d) || same2(b, c) || same2(b, d)) continue;
        if (crosses(a, b, c, d)) return true;
      }
    }
    return false;
  }
  // only interior edges link, the same relation islandGroups used
  function faceAdjacency(group, faces, edges, seams) {
    const adjacent = new Map(), inGroup = new Set(group);
    for (const f of group) {
      const face = faces[f], n = face.length;
      for (let i = 0; i < n; i++) {
        const key = pair(face[i], face[(i + 1) % n]), owners = edges.get(key);
        if (seams.has(key) || owners.length !== 2) continue;
        const o = owners[0] === f ? owners[1] : owners[0];
        if (o !== f && inGroup.has(o)) getArr(adjacent, f).push([o, key]);
      }
    }
    return adjacent;
  }
  // without the separation check a path runs lengthwise along a tube
  function straightenCut(verts, group, faces, edges, adjacent, binOf, weights = null, relief = null) {
    const lengths = new Map(), interior = new Map(), neighbors = new Map();
    for (const f of group) {
      for (const [o, key] of adjacent.get(f) || EMPTY) {
        if (!lengths.has(key)) { const [a, b] = ab(key); lengths.set(key, edgeCost(verts, weights, a, b, relief)); getSet(interior, a).add(b); getSet(interior, b).add(a); }
        getArr(neighbors, f).push([o, lengths.get(key)]);
      }
    }
    const nfaces = [...neighbors.keys()].sort((x, y) => x - y);
    for (let s = 0; s < STRAIGHTEN_SWEEPS; s++) {
      let moved = false;
      for (const f of nfaces) {
        const here = binOf.get(f), costs = new Map();
        for (const [o, l] of neighbors.get(f)) addTo(costs, binOf.get(o), l);
        // a bin costs this face its edges to every neighbour outside that bin
        let total = 0; for (const c of costs.values()) total += c;
        let best = null;
        for (const [b, c] of costs) { const t = [total - c, b]; if (best === null || cmpT(t, best) < 0) best = t; }
        const [move, target] = best;
        if (target !== here && move < total - g(costs, here)) { binOf.set(f, target); moved = true; }
      }
      if (!moved) break;
    }
    const cuts = new Map();
    for (const key of lengths.keys()) { const [a, b] = edges.get(key); if (binOf.get(a) !== binOf.get(b)) getSet(cuts, pair(binOf.get(a), binOf.get(b))).add(key); }
    const separated = (source, target, cutSet) => {
      const seen = new Set([source]), stack = [source];
      while (stack.length) {
        const f = stack.pop();
        for (const [o, key] of adjacent.get(f) || EMPTY) {
          if (cutSet.has(key) || seen.has(o)) continue;
          if (o === target) return false;
          seen.add(o); stack.push(o);
        }
      }
      return true;
    };
    let blocked = new Set(); for (const ce of cuts.values()) for (const k of ce) blocked.add(k);
    const extra = new Set();
    for (const cutEdges of cuts.values()) {
      const byVert = new Map();
      for (const key of cutEdges) for (const v of ab(key)) getArr(byVert, v).push(key);
      const seen = new Set();
      for (const start of [...cutEdges].sort(keyCmp)) {
        if (seen.has(start)) continue;
        const run = [], stack = [start]; seen.add(start);
        while (stack.length) {
          const key = stack.pop(); run.push(key);
          for (const v of ab(key)) for (const near of byVert.get(v)) if (!seen.has(near)) { seen.add(near); stack.push(near); }
        }
        const degree = new Map(); for (const key of run) for (const v of ab(key)) addTo(degree, v, 1);
        const ends = [...degree].filter(([, d]) => d % 2).map(([v]) => v);
        if (ends.length !== 2) { for (const k of run) extra.add(k); continue; }
        const path = cutPath(verts, interior, new Set([ends[0]]), new Set([ends[1]]), weights, relief);
        const straight = []; for (let i = 0; i + 1 < path.length; i++) straight.push(pair(path[i], path[i + 1]));
        let better;
        if ([...degree.values()].every((d) => d <= 2)) {
          // a simple chain walks in order, so both sides price their turns
          const runKeys = new Set(run), seq = [ends[0]], walked = new Set();
          while (walked.size < run.length) {
            const key = byVert.get(seq[seq.length - 1]).find((k) => runKeys.has(k) && !walked.has(k));
            walked.add(key); seq.push(otherEnd(key, seq[seq.length - 1]));
          }
          better = straight.length > 0 && pathCost(verts, path, weights, relief) < pathCost(verts, seq, weights, relief);
        } else {
          better = straight.length > 0 && straight.reduce((s, k) => s + g(lengths, k), 0) < run.reduce((s, k) => s + g(lengths, k), 0);
        }
        if (better) {
          const candidate = new Set([...blocked].filter((k) => !run.includes(k)));
          for (const k of straight) candidate.add(k);
          // or the swap cut the island somewhere else and left the bins joined
          const [a, b] = edges.get(run[0]);
          if (separated(a, b, candidate)) blocked = candidate; else better = false;
        }
        for (const k of better ? straight : run) extra.add(k);
      }
    }
    return extra;
  }
  // a cone unrolls into an annulus sector, where a cut at one axis position is a chord
  function arcParameter(group, centroids, areas, size, cx, cy, xx, xy, yy) {
    const det = xx * yy - xy * xy;
    if (det <= 0) return null;
    let szx = 0, szy = 0;
    for (const f of group) { const dx = centroids.get(f)[0] - cx, dy = centroids.get(f)[1] - cy, sq = dx * dx + dy * dy; szx += areas.get(f) * sq * dx; szy += areas.get(f) * sq * dy; }
    const a = (szx * yy - szy * xy) / (2 * det), b = (szy * xx - szx * xy) / (2 * det);
    const radiusSq = (xx + yy) / size + a * a + b * b;
    if (radiusSq <= 0) return null;
    const radius = Math.sqrt(radiusSq);
    let band = 0; const dists = new Map(), angles = new Map();
    for (const f of group) {
      const dx = centroids.get(f)[0] - cx - a, dy = centroids.get(f)[1] - cy - b;
      dists.set(f, Math.hypot(dx, dy)); band += areas.get(f) * (dists.get(f) - radius) ** 2; angles.set(f, Math.atan2(dy, dx));
    }
    const across = (xx + yy) / 2 - Math.hypot((xx - yy) / 2, xy);
    if (across <= 0 || band > SPLIT_ARC_BAND ** 2 * across) return null;
    const ordered = [...angles.values()].sort((p, q) => p - q);
    const gaps = []; for (let i = 0; i + 1 < ordered.length; i++) gaps.push(ordered[i + 1] - ordered[i]);
    gaps.push(ordered[0] + 2 * Math.PI - ordered[ordered.length - 1]);
    let widest = 0; for (let i = 1; i < gaps.length; i++) if (gaps[i] > gaps[widest]) widest = i;
    const span = 2 * Math.PI - gaps[widest];
    const ds = [...dists.values()], rLo = Math.min(...ds), rHi = Math.max(...ds);
    if (rHi - rLo >= span * radius) return [dists, rLo, rHi - rLo];
    // a disk covers every distance down to its center
    if (rLo < SPLIT_ARC_ANNULUS * rHi) return null;
    const start = ordered[(widest + 1) % ordered.length];
    const ts = new Map(); for (const [f, t] of angles) ts.set(f, mod(t - start, 2 * Math.PI) * radius);
    return [ts, 0, span * radius];
  }
  function splitPieces(group, links, cuts) {
    const unvisited = new Set(group), pieces = [];
    while (unvisited.size) {
      const seed = first(unvisited); unvisited.delete(seed);
      const piece = [seed], stack = [seed];
      while (stack.length) {
        const f = stack.pop();
        for (const [o, key] of links.get(f) || EMPTY) if (unvisited.has(o) && !cuts.has(key)) { unvisited.delete(o); piece.push(o); stack.push(o); }
      }
      pieces.push(piece);
    }
    return pieces;
  }
  // a tiny piece among only tiny pieces keeps its cut, that split was on purpose (mutates cuts like the original)
  function absorbFragments(pieces, links, cuts, area, floor) {
    const pieceArea = (p) => p.reduce((s, f) => s + area(f), 0);
    let changed = true;
    while (changed && pieces.length > 1) {
      changed = false;
      for (let i = 0; i < pieces.length; i++) {
        const piece = pieces[i];
        if (pieceArea(piece) >= floor) continue;
        const owner = new Map(); pieces.forEach((p, j) => { for (const f of p) owner.set(f, j); });
        const shared = new Map();
        for (const f of piece) for (const [o, key] of links.get(f) || EMPTY) {
          const j = owner.get(o);
          if (cuts.has(key) && j !== i && pieceArea(pieces[j]) >= floor) getSet(shared, j).add(key);
        }
        if (!shared.size) continue;
        const best = argBest(shared.keys(), (j) => shared.get(j).size, (a, b) => a > b);
        for (const k of shared.get(best)) cuts.delete(k);
        pieces[best].push(...piece);
        pieces.splice(i, 1);
        changed = true;
        break;
      }
    }
    return pieces;
  }
  // only the strongest neck is returned, the caller re-scans each piece
  function stripCuts(group, ts, lo, length, cap, areas) {
    const slabs = 24, slab = new Array(slabs).fill(0);
    for (const f of group) slab[Math.min(slabs - 1, Math.floor(((ts.get(f) - lo) / length) * slabs))] += areas.get(f);
    const width = slab.map((a) => (a * slabs) / length);
    const smooth = width.map((_, i) => (width[Math.max(0, i - 1)] + width[i] + width[Math.min(slabs - 1, i + 1)]) / 3);
    const median = (xs) => { const s = xs.slice().sort((a, b) => a - b); return s[s.length >> 1]; };
    let best = null;
    // the profile needs a few faces per slab to mean anything
    if (group.length >= 2 * slabs) {
      for (let j = 3; j < slabs - 2; j++) {
        // windows local to j, a global median cannot place the step
        const left = median(smooth.slice(Math.max(0, j - 3), j)), right = median(smooth.slice(j, Math.min(slabs, j + 3)));
        if (Math.min(left, right) <= 0) continue;
        const ratio = Math.max(left, right) / Math.min(left, right);
        if (ratio > SPLIT_STEP && (best === null || ratio > best[0])) best = [ratio, j];
      }
    }
    if (best !== null) return [lo + (best[1] / slabs) * length];
    const size = slab.reduce((s, x) => s + x, 0);
    if (size > 0 && length > cap && (length * length) / size > SPLIT_ASPECT) {
      const n = Math.ceil(length / cap), out = [];
      for (let k = 1; k < n; k++) out.push(lo + (length * k) / n);
      return out;
    }
    return [];
  }
  // the uv-space measure is useless once a flatten has collapsed the map
  function spatialParameter(verts, faces, group) {
    const centroids = new Map(), areaOf = new Map();
    for (const f of group) { centroids.set(f, faceCentroid(verts, faces[f])); areaOf.set(f, polygonArea(verts, faces[f])); }
    let total = 0; for (const a of areaOf.values()) total += a;
    if (total <= 0) return null;
    const mean = [0, 1, 2].map((i) => group.reduce((s, f) => s + areaOf.get(f) * centroids.get(f)[i], 0) / total);
    const cov = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    for (const f of group) { const d = sub3(centroids.get(f), mean); for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) cov[i][j] += areaOf.get(f) * d[i] * d[j]; }
    let axis = [1, 1, 1];
    for (let it = 0; it < 30; it++) { axis = [0, 1, 2].map((i) => dot3(cov[i], axis)); const s = vnorm(axis) || 1; axis = axis.map((c) => c / s); }
    const ts = new Map(group.map((f) => [f, dot3(centroids.get(f), axis)]));
    const vals = [...ts.values()], lo = Math.min(...vals), hi = Math.max(...vals);
    return [ts, lo, hi - lo];
  }
  // a caller scanning many pieces computes them once
  function faceMeasures(verts, faces, uvs) {
    return [faces.map((face) => polygonArea(verts, face)), uvs.map((pts) => signedArea(pts)),
      uvs.map((pts) => [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length])];
  }
  // measures the unwrap itself, the 3d shape does not predict it. -> Set of extra seam keys
  function splitIslandsRaw(verts, faces, seams, uvs, weights = null, groups = null, edges = null, reliefCache = null, fragmentFloor = null, groupsClean = false, measures = null) {
    if (!edges) edges = faceEdges(faces);
    if (!groups) groups = islandGroups(faces, seams, edges);
    if (!reliefCache) reliefCache = [];
    if (!measures) measures = faceMeasures(verts, faces, uvs);
    const [areas3d, uvAreas, uvCentroids] = measures;
    const cutRelief = () => {
      // a caller scanning many pieces of one mesh shares the cache
      if (!reliefCache.length) reliefCache.push(creaseRelief(verts, faces, weightedNormals(verts, faces), edges));
      return reliefCache[0];
    };
    const extra = new Set();
    // scaled so every length compares at even texel density
    const measure = (group) => {
      const areas = new Map(group.map((f) => [f, Math.abs(uvAreas[f])])), centroids = new Map(group.map((f) => [f, uvCentroids[f]]));
      let size = 0; for (const a of areas.values()) size += a;
      const area3d = group.reduce((s, f) => s + areas3d[f], 0);
      if (group.length < 2 || size <= 0 || area3d <= 0) return null;
      const cx = group.reduce((s, f) => s + areas.get(f) * centroids.get(f)[0], 0) / size;
      const cy = group.reduce((s, f) => s + areas.get(f) * centroids.get(f)[1], 0) / size;
      let xx = 0, xy = 0, yy = 0;
      for (const f of group) { const dx = centroids.get(f)[0] - cx, dy = centroids.get(f)[1] - cy; xx += areas.get(f) * dx * dx; xy += areas.get(f) * dx * dy; yy += areas.get(f) * dy * dy; }
      const arc = arcParameter(group, centroids, areas, size, cx, cy, xx, xy, yy);
      let ts, lo, length;
      if (arc !== null) [ts, lo, length] = arc;
      else {
        const angle = 0.5 * Math.atan2(2 * xy, xx - yy), axis = [Math.cos(angle), Math.sin(angle)];
        ts = new Map(group.map((f) => [f, centroids.get(f)[0] * axis[0] + centroids.get(f)[1] * axis[1]]));
        const vals = [...ts.values()]; lo = Math.min(...vals); length = Math.max(...vals) - lo;
      }
      return [ts, lo, length, size, areas, Math.sqrt(area3d / size)];
    };
    // an island too small to cut still takes up the atlas
    let total = 0; for (const gr of groups) for (const f of gr) total += areas3d[f];
    if (total <= 0) return extra;
    const cap = Math.sqrt(total / SPLIT_TARGET);
    if (fragmentFloor == null) fragmentFloor = FRAGMENT_SHARE * areas3d.reduce((s, a) => s + a, 0);
    // an island is what the unwrap made one: faces joined by unseamed edges
    const queue = groups.map((gr) => [gr, groupsClean]);
    while (queue.length) {
      const [group, knownClean] = queue.shift();
      const m = measure(group);
      if (m === null) continue;
      let [ts, lo, length, size, areas, density] = m;
      // the cap in this island's own uv units
      const localCap = cap / density;
      const ruined = !knownClean && islandRuined(group, faces, uvs, edges, seams, uvAreas);
      // a ruined island's uv bins still place a good cut, a crushed one's do not
      const crushed = !ruined && flattenDistortionRaw(verts, faces, uvs, group, uvAreas) > SPLIT_DISTORTION;
      const clean = !ruined && !crushed;
      let cutsAt, loops;
      if (clean) {
        if (length <= 0 || length <= localCap * SPLIT_NECK) continue;
        cutsAt = stripCuts(group, ts, lo, length, localCap, areas);
        if (!cutsAt.length) continue;
      } else if ((loops = uvTopology(group, faces, edges, seams)[1]).length > 1) {
        // open a non-disk with a path joining two boundary loops
        const adjacent = new Map();
        for (const f of group) {
          const face = faces[f], n = face.length;
          for (let i = 0; i < n; i++) { const key = pair(face[i], face[(i + 1) % n]); if (edges.get(key).length === 2 && !seams.has(key)) { const [a, b] = ab(key); getSet(adjacent, a).add(b); getSet(adjacent, b).add(a); } }
        }
        for (const k of connectLoops(verts, adjacent, loops, weights, cutRelief())) extra.add(k);
        continue;
      } else if (crushed) {
        const spatial = spatialParameter(verts, faces, group);
        if (spatial === null) continue;
        [ts, lo, length] = spatial;
        if (length <= 0) continue;
        cutsAt = [lo + length / 2];
      } else {
        // every centroid projects to one point (doubled faces), no cut
        if (length <= 0) continue;
        // a ruined strip past the cap slices even, anything else halves
        const strip = (length * length) / size > SPLIT_ASPECT && length > localCap;
        const bins = strip ? Math.ceil(length / localCap) : 2;
        cutsAt = []; for (let k = 1; k < bins; k++) cutsAt.push(lo + (length * k) / bins);
      }
      const links = faceAdjacency(group, faces, edges, seams);
      const binOf = new Map(group.map((f) => [f, bisectRight(cutsAt, ts.get(f))]));
      const nw = straightenCut(verts, group, faces, edges, links, binOf, weights, cutRelief());
      if (!nw.size) continue;
      const pieces = absorbFragments(splitPieces(group, links, nw), links, nw, (f) => areas3d[f], fragmentFloor);
      if (!nw.size) continue;
      for (const k of nw) extra.add(k);
      // a bent island hides its next neck until each piece gets its own axis
      if (clean && pieces.length > 1) for (const p of pieces) queue.push([p, false]);
    }
    return extra;
  }
  // the pieces are never re-unwrapped, each only shrinks towards its own centre. -> [moves [[face, corner, u, v]], seams, pieces]
  function splitMovesRaw(verts, faces, uvs, seams, edges = null) {
    if (!edges) edges = faceEdges(faces);
    const groups = islandGroups(faces, seams, edges), measures = faceMeasures(verts, faces, uvs);
    const clean = groups.filter((gr) => !islandRuined(gr, faces, uvs, edges, seams, measures[1]));
    const extra = splitIslandsRaw(verts, faces, seams, uvs, null, clean, edges, null, null, true, measures);
    if (!extra.size) return [[], seams, groups];
    const touched = new Set(); for (const e of extra) for (const f of edges.get(e)) touched.add(f);
    const target = new Set(); for (const gr of clean) if (gr.some((f) => touched.has(f))) for (const f of gr) target.add(f);
    const moves = [], all = unionSets(seams, extra), pieces = islandGroups(faces, all, edges);
    for (const piece of pieces) {
      if (!target.has(piece[0])) continue;
      const pts = piece.flatMap((f) => uvs[f]);
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length, cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
      for (const f of piece) uvs[f].forEach(([u, v], corner) => moves.push([f, corner, cx + (u - cx) * SPLIT_GAP, cy + (v - cy) * SPLIT_GAP]));
    }
    return [moves, all, pieces];
  }

  // ================================================================== seams/rectify.py (+ ops/island.py rectify_islands)
  const RECTANGLE_SHARE = 0.8, STRIP_ELONGATION = 3.0, CORNER_WINDOW = 0.02, CORNER_TURN = 45, CORNER_SIDE_RATIO = 2.0;
  const CORNER_FIT_AREA = 1.6, CORNER_CANDIDATES = 12, SPINE_SAMPLES = 64, RELAX_RING = 2, RELAX_ROUNDS = 200, FLIP_NOISE = 1e-6;
  const RECTIFY_COLLAPSE = 0.5, RECTIFY_DISTORTION = 1.0;

  // scale-free symmetric Dirichlet, 4.0 at isometry. uvs: per face, its corners' [u, v]
  function flattenDistortionRaw(verts, faces, uvs, group, uvAreas = null) {
    const signedTotal = group.reduce((s, fi) => s + (uvAreas ? uvAreas[fi] : signedArea(uvs[fi])), 0);
    const orientation = signedTotal >= 0 ? 1 : -1, floor = FLIP_NOISE * Math.abs(signedTotal);
    let grow = 0, shrink = 0, total = 0;
    for (const fi of group) {
      const face = faces[fi], fuv = uvs[fi], p0 = verts[face[0]], u0 = fuv[0];
      for (let i = 1; i + 1 < face.length; i++) {
        const e1 = sub3(verts[face[i]], p0), e2 = sub3(verts[face[i + 1]], p0);
        const length = vnorm(e1), area = vnorm(cross(e1, e2)) / 2, u1 = fuv[i], u2 = fuv[i + 1];
        const uvArea = (((u0[0] * u1[1] - u1[0] * u0[1]) + (u1[0] * u2[1] - u2[0] * u1[1]) + (u2[0] * u0[1] - u0[0] * u2[1])) / 2) * orientation;
        if (length <= 0 || area <= 0 || Math.abs(uvArea) <= floor) continue;
        if (uvArea < 0) return Infinity;
        const x2 = dot3(e1, e2) / length, y2 = (2 * area) / length;
        const a = ((u1[0] - u0[0]) * orientation) / length, b = ((u2[0] - u0[0]) * orientation - x2 * a) / y2;
        const c = (u1[1] - u0[1]) / length, d = (u2[1] - u0[1] - x2 * c) / y2;
        const det = a * d - b * c;
        if (det <= 0) return Infinity;
        const frob2 = a * a + b * b + c * c + d * d;
        grow += area * frob2; shrink += (area * frob2) / (det * det); total += area;
      }
    }
    if (total <= 0) return Infinity;
    return (2 * Math.sqrt(grow * shrink)) / total;
  }
  // uv points (indices), not mesh vertices: a cut vertex carries two uvs
  function boundaryLoop(group, fuv) {
    const counts = new Map();
    for (const fi of group) { const c = fuv[fi]; for (let i = 0; i < c.length; i++) addTo(counts, pair(c[i], c[(i + 1) % c.length]), 1); }
    const boundary = [...counts].filter(([, n]) => n === 1).map(([k]) => ab(k));
    if (boundary.length < 4) return null;
    const neighbors = new Map();
    for (const [a, b] of boundary) { getArr(neighbors, a).push(b); getArr(neighbors, b).push(a); }
    for (const around of neighbors.values()) if (around.length !== 2) return null;
    const start = boundary[0][0], loop = [start];
    let previous = null, current = start;
    for (;;) {
      const [a, b] = neighbors.get(current), following = a === previous ? b : a;
      if (following === start) break;
      loop.push(following); previous = current; current = following;
      if (loop.length > neighbors.size) return null;
    }
    if (loop.length !== neighbors.size) return null;
    return loop;
  }
  // cyclic, one entry per point of the segment including both ends
  function arcLengths(points, start, stop) {
    const lengths = [0]; let i = start;
    while (i !== stop) { const after = (i + 1) % points.length; lengths.push(lengths[lengths.length - 1] + dist2(points[i], points[after])); i = after; }
    return lengths;
  }
  function* combinations4(arr) {
    const n = arr.length;
    for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) for (let c = b + 1; c < n; c++) for (let d = c + 1; d < n; d++) yield [arr[a], arr[b], arr[c], arr[d]];
  }
  // a curled strip's outer bulge sits closer to the box corner than its real end
  function turningCorners(points, area) {
    const n = points.length;
    if (n < 4) return null;
    const positions = []; let total = 0;
    for (let i = 0; i < n; i++) { positions.push(total); total += dist2(points[i], points[(i + 1) % n]); }
    if (total <= 0) return null;
    const turns = points.map((here, i) => {
      const before = points[mod(i - 1, n)], after = points[(i + 1) % n];
      const v0 = [here[0] - before[0], here[1] - before[1]], v1 = [after[0] - here[0], after[1] - here[1]];
      return Math.atan2(v0[0] * v1[1] - v0[1] * v1[0], v0[0] * v1[0] + v0[1] * v1[1]);
    });
    const win = total * CORNER_WINDOW, doubled = positions.concat(positions.map((p) => p + total)), prefix = [0];
    for (let i = 0; i < 2 * n; i++) prefix.push(prefix[prefix.length - 1] + turns[i % n]);
    const windowTurn = (i) => { const c = positions[i] + total; return prefix[bisectRight(doubled, c + win / 2)] - prefix[bisectLeft(doubled, c - win / 2)]; };
    const floor = rad(CORNER_TURN), candidates = [];
    const scored = points.map((_, i) => [windowTurn(i), i]).sort((x, y) => cmpT(y, x));
    for (const [score, i] of scored) {
      if (score < floor || candidates.length === CORNER_CANDIDATES) break;
      if (candidates.every((j) => Math.min(mod(positions[i] - positions[j], total), mod(positions[j] - positions[i], total)) >= win)) candidates.push(i);
    }
    if (candidates.length < 4) return null;
    // picking the sharpest four lets a jagged seam edge outscore a real corner
    let best = null, bestFit = Infinity;
    for (const combo of combinations4(candidates.slice().sort((x, y) => x - y))) {
      const arcs = [0, 1, 2, 3].map((s) => mod(positions[combo[(s + 1) % 4]] - positions[combo[s]], total));
      if (arcs.some((a) => a <= 0)) continue;
      const rect = (((arcs[0] + arcs[2]) / 2) * (arcs[1] + arcs[3])) / 2;
      const across = Math.max(arcs[0], arcs[2]) / Math.min(arcs[0], arcs[2]), along = Math.max(arcs[1], arcs[3]) / Math.min(arcs[1], arcs[3]);
      if (!(area / CORNER_FIT_AREA <= rect && rect <= area * CORNER_FIT_AREA) || across > CORNER_SIDE_RATIO || along > CORNER_SIDE_RATIO) continue;
      const fit = Math.abs(Math.log(rect / area)) + Math.log(across) + Math.log(along);
      if (fit < bestFit) { best = combo.slice(); bestFit = fit; }
    }
    return best;
  }
  // the strip unbends but keeps its own width profile
  function spineTargets(rotated, picks, sides, width, queries) {
    const n = rotated.length;
    const along = (side, lengths, fraction) => {
      const distance = fraction * lengths[lengths.length - 1], k = bisectRight(lengths, distance) - 1;
      if (k >= lengths.length - 1) return rotated[side[side.length - 1]];
      const a = rotated[side[k]], b = rotated[side[k + 1]], span = lengths[k + 1] - lengths[k], t = span > 0 ? (distance - lengths[k]) / span : 0;
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    };
    const walk = (a, b) => { const out = [a]; let i = a; while (i !== b) { i = (i + 1) % n; out.push(i); } return out; };
    const side0 = walk(picks[0], picks[1]), side2 = walk(picks[2], picks[3]), spine = [];
    for (let k = 0; k <= SPINE_SAMPLES; k++) {
      const fraction = k / SPINE_SAMPLES, p0 = along(side0, sides[0], fraction);
      // the far side walks the loop backward relative to the near one
      const p2 = along(side2, sides[2], 1 - fraction);
      spine.push([(p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2]);
    }
    return queries.map((q) => {
      let best = Infinity, bestK = 0;
      spine.forEach((s, k) => { const d = (q[0] - s[0]) ** 2 + (q[1] - s[1]) ** 2; if (d < best) { best = d; bestK = k; } });
      // project onto the straighter of the two segments at the sample
      let fraction = bestK / SPINE_SAMPLES, offset = 0, hit = false;
      for (const k of [bestK - 1, bestK]) {
        if (!(k >= 0 && k < SPINE_SAMPLES)) continue;
        const a = spine[k], b = spine[k + 1], dx = b[0] - a[0], dy = b[1] - a[1], span2 = dx * dx + dy * dy;
        if (span2 <= 0) continue;
        const t = ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / span2;
        if (t >= 0 && t <= 1) { fraction = (k + t) / SPINE_SAMPLES; offset = ((q[0] - a[0]) * dy - (q[1] - a[1]) * dx) / Math.sqrt(span2); hit = true; break; }
      }
      if (!hit) {
        const a = spine[Math.max(bestK - 1, 0)], b = spine[Math.min(bestK + 1, SPINE_SAMPLES)], dx = b[0] - a[0], dy = b[1] - a[1], span = Math.hypot(dx, dy);
        if (span > 0) offset = ((q[0] - a[0]) * dy - (q[1] - a[1]) * dx) / span;
      }
      return [-width / 2 + fraction * width, -offset];
    });
  }
  // -> [targets Map uvId -> [u, v], inner Map uvId -> [u, v] | null] or null. axisAlign keeps the rectangle on the UV axes;
  // spine (the original's way for a strip with four real corners) unbends it keeping its width profile, else the
  // boundary goes exactly onto the rectangle
  function rectangleTargets(loopIds, coord, area, interior, axisAlign, spine) {
    let ids = loopIds, points = ids.map(coord);
    if (signedArea(points) < 0) { ids = ids.slice().reverse(); points = points.slice().reverse(); }
    let perimeter = 0; for (let i = 0; i < points.length; i++) perimeter += dist2(points[i], points[(i + 1) % points.length]);
    const elongation = perimeter ** 2 / (4 * Math.PI * area);
    const meanX = points.reduce((s, p) => s + p[0], 0) / points.length, meanY = points.reduce((s, p) => s + p[1], 0) / points.length;
    const centred = points.map(([x, y]) => [x - meanX, y - meanY]);
    let xx = 0, xy = 0, yy = 0; for (const [x, y] of centred) { xx += x * x; xy += x * y; yy += y * y; }
    const boxAt = (angle) => {
      const c = Math.cos(angle), s = Math.sin(angle), rot = centred.map(([x, y]) => [x * c + y * s, y * c - x * s]);
      const xs = rot.map((p) => p[0]), ys = rot.map((p) => p[1]);
      const w = Math.max(...xs) - Math.min(...xs), h = Math.max(...ys) - Math.min(...ys);
      return { angle, rot, xs, ys, w, h, share: w > 0 && h > 0 ? area / (w * h) : 0 };
    };
    let box = boxAt(0.5 * Math.atan2(2 * xy, xx - yy));
    if (box.share < RECTANGLE_SHARE && elongation < STRIP_ELONGATION) {
      // Forge: a square-ish island has no principal axis (the fit lands anywhere), so try the boundary's own edge
      // directions - the minimum-area box lies along one of them - before giving up
      const tried = new Set();
      for (let i = 0; i < points.length && tried.size < 256; i++) {
        const p = points[i], q = points[(i + 1) % points.length], a = mod(Math.atan2(q[1] - p[1], q[0] - p[0]), Math.PI / 2), k = Math.round(a * 1e6);
        if (tried.has(k)) continue;
        tried.add(k);
        const b = boxAt(a);
        if (b.share > box.share) box = b;
      }
    }
    const angle = box.angle, cosA = Math.cos(angle), sinA = Math.sin(angle), rotated = box.rot, xs = box.xs, ys = box.ys, boxW = box.w, boxH = box.h;
    if (boxW <= 0 || boxH <= 0) return null;
    if (box.share < RECTANGLE_SHARE && elongation < STRIP_ELONGATION) return null;
    const sidesFor = (picks) => {
      if (!picks || new Set(picks).size !== 4) return null;
      const offsets = picks.map((k) => mod(k - picks[0], points.length));
      if (!(offsets[1] < offsets[2] && offsets[2] < offsets[3])) return null;
      const sides = [0, 1, 2, 3].map((s) => arcLengths(rotated, picks[s], picks[(s + 1) % 4]));
      if (sides.some((sd) => sd[sd.length - 1] === 0)) return null;
      return sides;
    };
    const last = (a) => a[a.length - 1];
    let picks = turningCorners(points, area), sides = sidesFor(picks);
    if (sides !== null && last(sides[0]) + last(sides[2]) < last(sides[1]) + last(sides[3])) {
      // the longer side pair maps onto the rectangle's width along the fitted axis
      picks = picks.slice(1).concat(picks.slice(0, 1)); sides = sides.slice(1).concat(sides.slice(0, 1));
    }
    const turned = sides !== null;
    if (sides === null) {
      const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
      picks = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(([cx, cy]) => argMin(rotated.keys(), (i) => ((rotated[i][0] - cx) / boxW) ** 2 + ((rotated[i][1] - cy) / boxH) ** 2));
      sides = sidesFor(picks);
      if (sides === null) return null;
    }
    // a strip that still curls unrolls to its real length, which the box undershoots
    const width = (last(sides[0]) + last(sides[2])) / 2, height = (last(sides[1]) + last(sides[3])) / 2;
    const rect = [[-width / 2, -height / 2], [width / 2, -height / 2], [width / 2, height / 2], [-width / 2, height / 2]];
    const rc = axisAlign ? 1 : cosA, rs = axisAlign ? 0 : sinA;
    const restore = (x, y) => [x * rc - y * rs + meanX, x * rs + y * rc + meanY];
    if (turned && interior && interior.length && spine) {
      // arc length would force a constant width, stretching a tapered strip
      const ri = interior.map((id) => { const q = coord(id); return [(q[0] - meanX) * cosA + (q[1] - meanY) * sinA, (q[1] - meanY) * cosA - (q[0] - meanX) * sinA]; });
      const placed = spineTargets(rotated, picks, sides, width, rotated.concat(ri));
      const targets = new Map(ids.map((id, k) => [id, restore(...placed[k])]));
      const inner = new Map(interior.map((id, k) => [id, restore(...placed[ids.length + k])]));
      return [targets, inner];
    }
    const targets = new Map();
    for (let s = 0; s < 4; s++) {
      const [ax, ay] = rect[s], [bx, by] = rect[(s + 1) % 4], lengths = sides[s];
      for (let step = 0; step < lengths.length - 1; step++) {
        const t = lengths[step] / last(lengths);
        targets.set(ids[(picks[s] + step) % ids.length], restore(ax + (bx - ax) * t, ay + (by - ay) * t));
      }
    }
    return [targets, null];
  }
  // the spine projection can jump between samples where the strip wiggles
  function relaxFlips(group, fuv, coord, targets, inner) {
    const position = new Map([...targets, ...inner]);
    const neighbors = new Map(), facesAt = new Map();
    for (const fi of group) { const c = fuv[fi], n = c.length; for (let i = 0; i < n; i++) { const a = c[i], b = c[(i + 1) % n]; getSet(neighbors, a).add(b); getSet(neighbors, b).add(a); getSet(facesAt, a).add(fi); } }
    const at = (id) => position.get(id) || coord(id);
    const placed = (fi) => fuv[fi].map(at);
    const total = group.reduce((s, fi) => s + signedArea(placed(fi)), 0);
    const orientation = total >= 0 ? 1 : -1, floor = FLIP_NOISE * Math.abs(total);
    const flippedFace = (fi) => { const p = placed(fi); for (let i = 1; i + 1 < p.length; i++) if (signedArea([p[0], p[i], p[i + 1]]) * orientation < -floor) return true; return false; };
    // only a face touching a moved uv can change
    let candidates = new Set(group);
    for (let r = 0; r < RELAX_ROUNDS; r++) {
      const flipped = group.filter((fi) => candidates.has(fi) && flippedFace(fi));
      if (!flipped.length) break;
      let free = new Set(); for (const fi of flipped) for (const id of fuv[fi]) free.add(id);
      for (let k = 0; k < RELAX_RING; k++) { const grown = new Set(free); for (const id of free) for (const o of neighbors.get(id)) grown.add(o); free = grown; }
      for (const id of free) {
        const around = [...neighbors.get(id)];
        position.set(id, [around.reduce((s, o) => s + at(o)[0], 0) / around.length, around.reduce((s, o) => s + at(o)[1], 0) / around.length]);
      }
      candidates = new Set(); for (const id of free) for (const fi of facesAt.get(id)) candidates.add(fi);
    }
    for (const [id, p] of position) { if (inner.has(id)) inner.set(id, p); else targets.set(id, p); }
  }
  // without four turning corners the interior is null, for the pinned unwrap
  function rectifyTargetsRaw(fuv, coord, groups, axisAlign = false, spine = true) {
    const plans = [];
    for (const group of groups) {
      const loop = boundaryLoop(group, fuv);
      if (loop === null) continue;
      const area = Math.abs(group.reduce((s, fi) => s + signedArea(fuv[fi].map(coord)), 0));
      if (area <= 0) continue;
      const inLoop = new Set(loop), interior = [];
      const seen = new Set(); for (const fi of group) for (const id of fuv[fi]) if (!inLoop.has(id) && !seen.has(id)) { seen.add(id); interior.push(id); }
      const result = rectangleTargets(loop, coord, area, interior, axisAlign, spine);
      if (result !== null) {
        const [targets, inner] = result;
        if (inner !== null) relaxFlips(group, fuv, coord, targets, inner);
        plans.push([group, targets, inner]);
      }
    }
    return plans;
  }

  // ================================================================== seams/symmetry.py + the mirror maps of similar.py
  const SEAM_MATCH_CELL = 1e-3, MATCH_CELL = 1e-4, MATCH_TOLERANCE = 1e-4, SPREAD_TOLERANCE = 1e-3, DEGENERATE_GAP = 1e-2, STACK_DECIMALS = 9;
  const NEIGHBOR_CELLS = [];
  for (const dx of [0, -1, 1]) for (const dy of [0, -1, 1]) for (const dz of [0, -1, 1]) if (dx || dy || dz) NEIGHBOR_CELLS.push([dx, dy, dz]);
  const cellKey = (x, y, z) => x + "," + y + "," + z;
  function gridOf(points, cell) {
    const lookup = new Map();
    points.forEach((p, i) => getArr(lookup, cellKey(Math.round(p[0] / cell), Math.round(p[1] / cell), Math.round(p[2] / cell))).push(i));
    return lookup;
  }
  // -1 where no vertex is close enough (partial = true) / null when any vertex has no match (partial = false)
  function matchPoints(positions, grid, query, cell, partial) {
    const perm = new Int32Array(query.length).fill(-1), used = new Uint8Array(positions.length);
    for (let index = 0; index < query.length; index++) {
      const q = query[index], x = Math.round(q[0] / cell), y = Math.round(q[1] / cell), z = Math.round(q[2] / cell);
      let options = (grid.get(cellKey(x, y, z)) || EMPTY).filter((i) => !used[i]);
      if (!options.length) for (const [dx, dy, dz] of NEIGHBOR_CELLS) options = options.concat((grid.get(cellKey(x + dx, y + dy, z + dz)) || EMPTY).filter((i) => !used[i]));
      if (!options.length) { if (partial) continue; return null; }
      let nearest = options[0], nd = Infinity;
      for (const i of options) { const d = dist3(positions[i], q); if (d < nd) { nd = d; nearest = i; } }
      if (nd > cell) { if (partial) continue; return null; }
      perm[index] = nearest; used[nearest] = 1;
    }
    return perm;
  }
  // a vertex with no counterpart is absent from its map. axes: ["x", "y", "z"]; -> [Map v -> mirror v] per axis, or null
  function mirrorMatches(verts, center, axes) {
    if (!verts.length) return null;
    const diag = diagonal(verts);
    if (diag <= 0) return null;
    const cell = SEAM_MATCH_CELL * diag, grid = gridOf(verts, cell), maps = [];
    for (const axis of axes) {
      const k = "xyz".indexOf(String(axis).toLowerCase());
      const reflected = verts.map((p) => { const q = p.slice(); q[k] = 2 * center[k] - q[k]; return q; });
      const matched = matchPoints(verts, grid, reflected, cell, true), m = new Map();
      matched.forEach((j, v) => { if (j >= 0) m.set(v, j); });
      maps.push(m);
    }
    if (!maps.some((m) => m.size)) return null;
    return maps;
  }
  const canonicalCycle = (cycle) => {
    let best = null;
    for (const dir of [cycle, cycle.slice().reverse()]) for (let s = 0; s < dir.length; s++) { const c = dir.slice(s).concat(dir.slice(0, s)); if (best === null || cmpT(c, best) < 0) best = c; }
    return best.join(",");
  };
  // a part with any vertex or face lacking a mirror image drops out (strict, for stacking mirrored islands)
  function mirrorPermutations(verts, faces, center, axes) {
    if (!verts.length) return null;
    const diag = diagonal(verts);
    if (diag <= 0) return null;
    const parent = new Int32Array(verts.length).map((_, i) => i);
    for (const face of faces) for (const v of face.slice(1)) { const ra = findA(parent, face[0]), rb = findA(parent, v); if (ra !== rb) parent[ra] = rb; }
    const partOf = verts.map((_, v) => findA(parent, v)), faceKeySet = new Set(faces.map(canonicalCycle));
    const cell = MATCH_CELL * diag, grid = gridOf(verts, cell), perAxis = [];
    let covered = null;
    for (const axis of axes) {
      const k = "xyz".indexOf(String(axis).toLowerCase());
      const reflected = verts.map((p) => { const q = p.slice(); q[k] = 2 * center[k] - q[k]; return q; });
      const perm = matchPoints(verts, grid, reflected, cell, true);
      const bad = new Set(); perm.forEach((j, v) => { if (j < 0) bad.add(partOf[v]); });
      for (const face of faces) { if (bad.has(partOf[face[0]])) continue; if (!faceKeySet.has(canonicalCycle(face.map((v) => perm[v])))) bad.add(partOf[face[0]]); }
      perAxis.push(perm);
      const axisCovered = new Set(partOf.filter((p) => !bad.has(p)));
      covered = covered === null ? axisCovered : new Set([...covered].filter((p) => axisCovered.has(p)));
    }
    // mirrored seams would land on a part that will not mirror back
    let changed = true;
    while (changed && covered.size) {
      changed = false;
      for (const perm of perAxis) for (let v = 0; v < verts.length; v++) {
        if (!covered.has(partOf[v])) continue;
        if (perm[v] < 0 || !covered.has(partOf[perm[v]])) { covered.delete(partOf[v]); changed = true; }
      }
    }
    if (!covered.size) return null;
    return perAxis.map((perm) => { const m = new Map(); for (let v = 0; v < verts.length; v++) if (covered.has(partOf[v])) m.set(v, perm[v]); return m; });
  }
  // a dropped face with no route to a kept one could never mirror its seams back
  function halfFaces(verts, faces, axes, mirrors) {
    const byVerts = new Map(faces.map((face, fi) => [face.slice().sort((a, b) => a - b).join(","), fi]));
    const image = (face, m) => { if (face.some((v) => !m.has(v))) return null; const k = byVerts.get(face.map((v) => m.get(v)).sort((a, b) => a - b).join(",")); return k === undefined ? null : k; };
    const images = faces.map((face) => mirrors.map((m) => image(face, m)));
    const dropped = new Set();
    axes.forEach((axis, mi) => {
      faces.forEach((face, fi) => {
        const gi = images[fi][mi];
        if (gi === null || gi === fi) return;
        const mine = face.reduce((s, v) => s + verts[v][axis], 0) / face.length, theirs = faces[gi].reduce((s, v) => s + verts[v][axis], 0) / faces[gi].length;
        if (cmpT([mine, fi], [theirs, gi]) < 0) dropped.add(fi);
      });
    });
    const reached = new Set(); for (let fi = 0; fi < faces.length; fi++) if (!dropped.has(fi)) reached.add(fi);
    const queue = [...reached];
    while (queue.length) { const fi = queue.shift(); for (const gi of images[fi]) if (gi !== null && !reached.has(gi)) { reached.add(gi); queue.push(gi); } }
    return new Set([...dropped].filter((f) => reached.has(f)));
  }
  // where the halves glue back together on the whole mesh
  function interfaceEdges(faces, dropped, edges) {
    const out = new Set();
    for (const [key, owners] of edges) if (owners.length === 2 && dropped.has(owners[0]) !== dropped.has(owners[1])) out.add(key);
    return out;
  }
  // glued along more than one interface arc the merge is a ring, not a disk
  function openMerged(verts, faces, edges, seams, iface) {
    const result = new Set(seams), queue = islandGroups(faces, result, edges);
    let guard = 0;
    while (queue.length && guard++ < 10000) {
      const group = queue.shift();
      if (group.length < 2) continue;
      const [ec, loops] = uvTopology(group, faces, edges, result);
      if (ec === 1) continue;
      const inside = new Set(group), keys = [];
      for (const [key, owners] of edges) if (iface.has(key) && !result.has(key) && owners.every((o) => inside.has(o))) keys.push(key);
      const parent = new Map();
      for (const key of keys) { const [a, b] = ab(key); if (!parent.has(a)) parent.set(a, a); if (!parent.has(b)) parent.set(b, b); const ra = findM(parent, a), rb = findM(parent, b); if (ra !== rb) parent.set(ra, rb); }
      const arcs = new Map(); for (const key of keys) getSet(arcs, findM(parent, ab(key)[0])).add(key);
      if (arcs.size) {
        const arcLen = (arc) => [...arc].reduce((s, k) => { const [a, b] = ab(k); return s + dist3(verts[a], verts[b]); }, 0);
        for (const k of argMin(arcs.values(), arcLen)) result.add(k);
      } else if (loops.length > 1) {
        const adjacent = new Map();
        for (const f of group) for (const key of faceKeys(faces[f])) if (edges.get(key).length === 2 && !result.has(key)) { const [a, b] = ab(key); getSet(adjacent, a).add(b); getSet(adjacent, b).add(a); }
        const cuts = connectLoops(verts, adjacent, loops);
        if (!cuts.size) continue;
        for (const k of cuts) result.add(k);
      } else continue;
      queue.push(...islandGroups(group.map((f) => faces[f]), new Set(result), faceEdges(group.map((f) => faces[f]))).map((p) => p.map((i) => group[i])));
    }
    return result;
  }
  // the maps may be partial, a seam outside their coverage stays as it is
  function mirrorSeamsRaw(seams, mirrors, edges) {
    const result = new Set(seams), queue = [...result];
    while (queue.length) {
      const [a, b] = ab(queue.pop());
      for (const m of mirrors) {
        if (!m.has(a) || !m.has(b)) continue;
        const key = pair(m.get(a), m.get(b));
        if (edges.has(key) && !result.has(key)) { result.add(key); queue.push(key); }
      }
    }
    return result;
  }
  // an island a map sends onto itself straddles the plane and stays put. uvGroups: the UV islands (face lists)
  // -> [[targetFace, corner, sourceFace, sourceCorner]]
  function stackMirroredRaw(faces, groups, mirrors) {
    const groupOf = new Map(); groups.forEach((gr, gi) => { for (const fi of gr) groupOf.set(fi, gi); });
    const byVerts = new Map(); faces.forEach((face, fi) => getArr(byVerts, face.slice().sort((a, b) => a - b).join(",")).push(fi));
    // the one island m sends this island onto whole, or null
    const image = (gi, m) => {
      const targets = new Set();
      for (const fi of groups[gi]) {
        const cands = byVerts.get(faces[fi].map((v) => (m.has(v) ? m.get(v) : -1)).sort((a, b) => a - b).join(","));
        if (!cands) return null;
        for (const c of cands) targets.add(groupOf.get(c));
      }
      if (targets.size === 1) { const t = first(targets); if (groups[t].length === groups[gi].length) return t; }
      return null;
    };
    const links = new Map();
    groups.forEach((_, gi) => { for (const m of mirrors) { const hi = image(gi, m); if (hi !== null && hi !== gi) getArr(links, gi).push([hi, m]); } });
    const assignments = [], seen = new Set();
    for (let gi = 0; gi < groups.length; gi++) {
      if (seen.has(gi)) continue;
      const component = new Set([gi]), queue = [gi];
      while (queue.length) for (const [hi] of links.get(queue.pop()) || EMPTY) if (!component.has(hi)) { component.add(hi); queue.push(hi); }
      for (const c of component) seen.add(c);
      if (component.size === 1) continue;
      const rep = argMin(component, (gg) => Math.min(...groups[gg]));
      // composed[g] maps each rep-island vertex to its counterpart in g
      const composed = new Map(), base = new Map();
      for (const fi of groups[rep]) for (const v of faces[fi]) base.set(v, v);
      composed.set(rep, base);
      const q = [rep];
      while (q.length) {
        const current = q.pop();
        for (const [hi, m] of links.get(current) || EMPTY) {
          if (composed.has(hi)) continue;
          const nm = new Map(); for (const [v, w] of composed.get(current)) nm.set(v, m.get(w));
          composed.set(hi, nm); q.push(hi);
        }
      }
      for (const [twin, vmap] of composed) {
        if (twin === rep) continue;
        for (const fi of groups[rep]) {
          const key = faces[fi].map((v) => vmap.get(v)).sort((a, b) => a - b).join(",");
          const target = (byVerts.get(key) || EMPTY).find((c) => groupOf.get(c) === twin);
          if (target === undefined) continue;
          faces[fi].forEach((v, corner) => assignments.push([target, faces[target].indexOf(vmap.get(v)), fi, corner]));
        }
      }
    }
    return assignments;
  }

  // ================================================================== similar.py: duplicated pieces (twins)
  // Jacobi eigen decomposition of a small symmetric matrix: values ascending, vectors as columns
  function eigh(A) {
    const n = A.length, a = A.map((r) => r.slice()), V = A.map((_, i) => A.map((__, j) => (i === j ? 1 : 0)));
    for (let sweep = 0; sweep < 64; sweep++) {
      let off = 0; for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) off += a[i][j] * a[i][j];
      if (off < 1e-30) break;
      for (let p = 0; p < n; p++) for (let q = p + 1; q < n; q++) {
        if (Math.abs(a[p][q]) < 1e-300) continue;
        const theta = (a[q][q] - a[p][p]) / (2 * a[p][q]);
        const t = (theta >= 0 ? 1 : -1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1)), c = 1 / Math.sqrt(t * t + 1), s = t * c;
        for (let k = 0; k < n; k++) { const kp = a[k][p], kq = a[k][q]; a[k][p] = c * kp - s * kq; a[k][q] = s * kp + c * kq; }
        for (let k = 0; k < n; k++) { const pk = a[p][k], qk = a[q][k]; a[p][k] = c * pk - s * qk; a[q][k] = s * pk + c * qk; }
        for (let k = 0; k < n; k++) { const kp = V[k][p], kq = V[k][q]; V[k][p] = c * kp - s * kq; V[k][q] = s * kp + c * kq; }
      }
    }
    const order = a.map((_, i) => i).sort((i, j) => a[i][i] - a[j][j]);
    return { values: order.map((i) => a[i][i]), vectors: V.map((row) => order.map((i) => row[i])) };
  }
  const apply4 = (M, p) => [0, 1, 2].map((r) => M[r][0] * p[0] + M[r][1] * p[1] + M[r][2] * p[2] + M[r][3]);
  // rotation or reflection, then translation (Horn's quaternion fit, tried on the source and its mirror image)
  function rigidFit(source, target) {
    const n = source.length, mean = (pts) => [0, 1, 2].map((k) => pts.reduce((s, p) => s + p[k], 0) / n);
    const sc = mean(source), tc = mean(target);
    const fitProper = (src) => {
      const sm = mean(src), S = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
      for (let i = 0; i < n; i++) { const p = sub3(src[i], sm), q = sub3(target[i], tc); for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) S[a][b] += p[a] * q[b]; }
      const [[xx, xy, xz], [yx, yy, yz], [zx, zy, zz]] = S;
      const N = [[xx + yy + zz, yz - zy, zx - xz, xy - yx], [yz - zy, xx - yy - zz, xy + yx, zx + xz], [zx - xz, xy + yx, -xx + yy - zz, yz + zy], [xy - yx, zx + xz, yz + zy, -xx - yy + zz]];
      const { vectors } = eigh(N), [w, x, y, z] = vectors.map((r) => r[3]);
      return [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]];
    };
    let best = null;
    for (const mirror of [false, true]) {
      const src = mirror ? source.map((p) => [-p[0], p[1], p[2]]) : source;
      let R = fitProper(src);
      if (mirror) R = R.map((row) => [-row[0], row[1], row[2]]);
      const t = sub3(tc, [0, 1, 2].map((r) => dot3(R[r], sc)));
      const M = [[...R[0], t[0]], [...R[1], t[1]], [...R[2], t[2]], [0, 0, 0, 1]];
      let e = 0; for (let i = 0; i < n; i++) { const d = sub3(apply4(M, source[i]), target[i]); e += dot3(d, d); }
      const error = Math.sqrt(e / n);
      if (!best || error < best[1] - 1e-15) best = [M, error, mirror];
    }
    return best;
  }
  // one piece: its own vertex list (first appearance in its faces), its faces in local indices, its PCA frame
  function makePiece(verts, faces, faceIdx) {
    const local = new Map(), positions = [], totals = [], corners = [];
    for (const fi of faceIdx) { totals.push(faces[fi].length); for (const v of faces[fi]) { if (!local.has(v)) { local.set(v, positions.length); positions.push(verts[v]); } corners.push(local.get(v)); } }
    const p = { faces: faceIdx, vertsOf: [...local.keys()], local, positions, totals, corners, signature: positions.length + "/" + corners.length + "/" + totals.length };
    p.diagonal = diagonal(positions);
    const mean = [0, 1, 2].map((k) => positions.reduce((s, q) => s + q[k], 0) / positions.length), centred = positions.map((q) => sub3(q, mean));
    const C = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    for (const q of centred) for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) C[a][b] += q[a] * q[b];
    const { values, vectors } = eigh(C);
    p.spread = values;
    p.pca = centred.map((q) => [0, 1, 2].map((c) => q[0] * vectors[0][c] + q[1] * vectors[1][c] + q[2] * vectors[2][c]));
    p.grid = null;
    return p;
  }
  function* planeAlignments(rep, piece, plane, unique, cell) {
    const repRadius = rep.pca.map((q) => Math.hypot(q[plane[0]], q[plane[1]]));
    let anchor = 0; repRadius.forEach((r, i) => { if (r > repRadius[anchor]) anchor = i; });
    const anchorAngle = Math.atan2(rep.pca[anchor][plane[1]], rep.pca[anchor][plane[0]]), anchorHeight = rep.pca[anchor][unique];
    const candRadius = piece.pca.map((q) => Math.hypot(q[plane[0]], q[plane[1]]));
    for (const axisSign of [1, -1]) {
      const heights = piece.pca.map((q) => q[unique] * axisSign);
      const anchors = []; piece.pca.forEach((_, i) => { if (Math.abs(candRadius[i] - repRadius[anchor]) <= cell && Math.abs(heights[i] - anchorHeight) <= cell) anchors.push(i); });
      for (const mirror of [1, -1]) for (const vertex of anchors) {
        const turn = anchorAngle - Math.atan2(piece.pca[vertex][plane[1]] * mirror, piece.pca[vertex][plane[0]]), c = Math.cos(turn), s = Math.sin(turn);
        yield piece.pca.map((q, i) => { const out = q.slice(), f = q[plane[0]], sc = q[plane[1]] * mirror; out[unique] = heights[i]; out[plane[0]] = f * c - sc * s; out[plane[1]] = f * s + sc * c; return out; });
      }
    }
  }
  const SIGNS = []; for (const a of [1, -1]) for (const b of [1, -1]) for (const c of [1, -1]) SIGNS.push([a, b, c]);
  const PERMS = [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]];
  // covers a box but not a freely rotated ball-like shape
  function* alignments(rep, piece, cell) {
    const scale = rep.spread[2] || 1, lowGap = (rep.spread[1] - rep.spread[0]) / scale, highGap = (rep.spread[2] - rep.spread[1]) / scale;
    if (lowGap >= DEGENERATE_GAP && highGap >= DEGENERATE_GAP) { for (const s of SIGNS) yield piece.pca.map((q) => [q[0] * s[0], q[1] * s[1], q[2] * s[2]]); }
    else if (lowGap >= DEGENERATE_GAP || highGap >= DEGENERATE_GAP) {
      const plane = highGap < DEGENERATE_GAP ? [1, 2] : [0, 1], unique = highGap < DEGENERATE_GAP ? 0 : 2;
      yield* planeAlignments(rep, piece, plane, unique, cell);
    } else for (const o of PERMS) for (const s of SIGNS) yield piece.pca.map((q) => [q[o[0]] * s[0], q[o[1]] * s[1], q[o[2]] * s[2]]);
  }
  function faceKeysOf(totals, corners) {
    const keys = []; let start = 0;
    for (const t of totals) { keys.push(canonicalCycle(corners.slice(start, start + t))); start += t; }
    return keys.sort().join("|");
  }
  // the cheap index-for-index fit first, then PCA alignment for a reordered copy. -> {matrix, exact, perm, mirrored} | null
  function twinMatrix(rep, piece) {
    const tolerance = MATCH_TOLERANCE * piece.diagonal;
    const sameOrder = rep.totals.join() === piece.totals.join() && rep.corners.join() === piece.corners.join();
    if (sameOrder) {
      const [matrix, error, mirrored] = rigidFit(rep.positions, piece.positions);
      if (error <= tolerance) return { matrix, exact: true, perm: piece.positions.map((_, i) => i), mirrored };
    }
    const spreadGap = Math.max(...rep.spread.map((s, i) => Math.abs(s - piece.spread[i])));
    if (spreadGap > SPREAD_TOLERANCE * Math.max(...piece.spread)) return null;
    if (rep.totals.slice().sort().join() !== piece.totals.slice().sort().join()) return null;
    const cell = MATCH_CELL * rep.diagonal;
    if (!rep.grid) rep.grid = gridOf(rep.pca, cell);
    const keys = faceKeysOf(piece.totals, piece.corners);
    let tries = 0;
    for (const aligned of alignments(rep, piece, cell)) {
      if (++tries > 512) break;
      const perm = matchPoints(rep.pca, rep.grid, aligned, cell, false);
      if (perm === null) continue;
      const inverse = new Int32Array(perm.length); perm.forEach((r, i) => { inverse[r] = i; });
      if (faceKeysOf(rep.totals, rep.corners.map((c) => inverse[c])) !== keys) continue;
      const [matrix, error, mirrored] = rigidFit([...perm].map((r) => rep.positions[r]), piece.positions);
      if (error <= tolerance) return { matrix, exact: false, perm: [...perm], mirrored };
    }
    return null;
  }

  // ================================================================== the cage side (Forge's UV model)
  const ForgeUV = () => root.ForgeUV || null;
  const hasUV = (m) => !!(m && Array.isArray(m.uv) && Array.isArray(m.fuv) && m.fuv.length === m.f.length
    && m.fuv.every((c, i) => c && c.length === m.f[i].length && c.every((x) => x >= 0 && x < m.uv.length)));
  function cloneCage(m) {
    const U = ForgeUV();
    if (U && U.clone) return U.clone(m);
    const out = { v: m.v.map((p) => p.slice()), f: m.f.map((f) => f.slice()) };
    for (const k of Object.keys(m)) if (!(k in out) && k !== "uv" && k !== "fuv") out[k] = m[k];
    if (hasUV(m)) { out.uv = m.uv.map((p) => p.slice()); out.fuv = m.fuv.map((c) => c.slice()); }
    return out;
  }
  // per face, its corners' [u, v] (the original add-on's face uv lists)
  const faceUVs = (m) => m.fuv.map((c) => c.map((i) => m.uv[i]));
  // the seams of a cage with UVs: edges whose faces use different UV indices, plus open borders
  function uvSeams(m) {
    const U = ForgeUV();
    if (U && U.seams) return U.seams(m);
    const out = new Set();
    if (!hasUV(m)) return out;
    const edges = faceEdges(m.f);
    for (const [key, owners] of edges) {
      if (owners.length !== 2) { out.add(key); continue; }
      const [a, b] = ab(key), at = (fi, v) => m.fuv[fi][m.f[fi].indexOf(v)];
      if (at(owners[0], a) !== at(owners[1], a) || at(owners[0], b) !== at(owners[1], b)) out.add(key);
    }
    return out;
  }
  // interior seams only (what the original add-on marks): open borders are not seams there
  function markedSeams(m) {
    const edges = faceEdges(m.f), out = new Set();
    for (const k of uvSeams(m)) { const o = edges.get(k); if (o && o.length === 2) out.add(k); }
    return out;
  }
  // a seam Set -> a new cage whose UV indices split exactly along it (ForgeUV.rebuild when loaded)
  function applySeams(m, seams) {
    const base = hasUV(m) ? m : Object.assign(cloneCage(m), { uv: [[0, 0]], fuv: m.f.map((f) => f.map(() => 0)) });
    const U = ForgeUV();
    if (U && U.rebuild) return U.rebuild(base, seams);
    const out = cloneCage(base), E = faceEdges(m.f), start = []; let n = 0;
    for (const f of m.f) { start.push(n); n += f.length; }
    const parent = new Int32Array(n).map((_, i) => i);
    for (const [key, owners] of E) {
      if (seams.has(key) || owners.length !== 2) continue;
      const [a, b] = ab(key), c = (fi, v) => start[fi] + m.f[fi].indexOf(v);
      for (const v of [a, b]) { const ra = findA(parent, c(owners[0], v)), rb = findA(parent, c(owners[1], v)); if (ra !== rb) parent[ra] = rb; }
    }
    const idOf = new Map(); out.uv = []; out.fuv = m.f.map((f) => new Array(f.length));
    m.f.forEach((f, fi) => f.forEach((_, k) => {
      const r = findA(parent, start[fi] + k);
      if (!idOf.has(r)) { idOf.set(r, out.uv.length); out.uv.push(base.uv[base.fuv[fi][k]].slice()); }
      out.fuv[fi][k] = idOf.get(r);
    }));
    return out;
  }
  // shells: faces connected through shared UV indices (ForgeUV.shells when loaded) -> [{faces, uvs:Set}]
  function shellsOf(m) {
    const U = ForgeUV();
    if (U && U.shells) return U.shells(m);
    if (!hasUV(m)) return [];
    const parent = new Int32Array(m.uv.length).map((_, i) => i);
    for (const c of m.fuv) for (let k = 1; k < c.length; k++) { const a = findA(parent, c[0]), b = findA(parent, c[k]); if (a !== b) parent[a] = b; }
    const by = new Map();
    m.fuv.forEach((c, fi) => { const r = findA(parent, c[0]); if (!by.has(r)) by.set(r, { faces: [], uvs: new Set() }); const s = by.get(r); s.faces.push(fi); for (const i of c) s.uvs.add(i); });
    return [...by.values()].map((s, id) => Object.assign(s, { id }));
  }
  const toSeamSet = (s) => {
    if (!s) return null;
    const out = new Set();
    for (const k of s) out.add(typeof k === "string" ? (() => { const [a, b] = ab(k); return pair(a, b); })() : pair(k[0], k[1]));
    return out;
  };
  const bboxCenter = (verts) => {
    const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (const v of verts) for (let i = 0; i < 3; i++) { lo[i] = Math.min(lo[i], v[i]); hi[i] = Math.max(hi[i], v[i]); }
    return [0, 1, 2].map((i) => (lo[i] + hi[i]) / 2);
  };
  const axisIndex = (a) => "xyz".indexOf(String(a).toLowerCase());

  // The settings, with the original add-on's defaults (src/ui/props.py, engines/optcuts) - see docs/FORGE_UVGAMI.md
  const DEFAULTS = Object.freeze({
    surfaceMode: "organic",      // "organic" | "hard" | "auto": seams on sharp features before the flatten (hard), per loose part (auto)
    hardAngle: 66,               // HARD_SURFACE_ANGLE: degrees, what counts as a sharp feature in hard-surface mode
    angle: CREASE_ANGLE,         // seamEdges' own default feature angle (30)
    rims: true,                  // cut sweep rims (cylinder caps off their walls, bent tubes into straight runs)
    marked: "NONE",              // "NONE" | "ADD" | "ONLY": what the cage's existing interior seams do (ignored / kept / the only seams)
    priority: "BALANCED",        // "LESS_STRETCH" | "BALANCED" | "FEWER_SEAMS": passed to the flatten hook (the engine's distortion bound)
    useWeights: false, weightMode: "SEAMS", weightValue: 3,   // painted seam restrictions (opts.weights: vertex -> 0..1)
    useSymmetry: false, symAxes: ["x"], symMerge: true,       // symmetric seams; merge = overlap the mirrored UVs
    stackSimilar: false,         // unwrap one of each set of identical pieces, copy it onto the others
    areaExpand: 1,               // grow a face selection by this many rings before an area unwrap
    margin: 0.001, fixScale: true, packAfterUnwrap: true,      // passed to the pack hook
    useProxy: false, proxyFaces: 20000,                        // not ported (docs/FORGE_UVGAMI.md); kept so settings round-trip
    splitPasses: 1,              // split_islands passes after the flatten (3 when symmetric, like the original's rebuild)
    rectify: true,               // straighten quad-ish strips into rectangles after the flatten
    axisAlign: true,             // Forge: rectified islands land on the UV axes (the original keeps the island's own angle)
    rectifyMode: "rectangle",    // "rectangle": the border goes exactly onto the rectangle, the inside follows (Forge);
                                 // "spine": the original's - a strip unbends along its spine keeping its width profile
  });
  const PRIORITY_BOUND = Object.freeze({ LESS_STRETCH: 4.05, BALANCED: 4.2, FEWER_SEAMS: 5.0 });
  const optsOf = (o) => Object.assign({}, DEFAULTS, o || {});
  function forcedOf(m, o) {
    const forced = toSeamSet(o.forced) || new Set();
    if (o.marked === "ADD" || o.marked === "ONLY") for (const k of markedSeams(m)) forced.add(k);
    return forced.size ? forced : null;
  }

  // ------------------------------------------------------------------ public: seams
  // The seams pipeline (seams/pipeline.py seam_edges): feature regions -> merges -> sweeps -> teeth -> reroute ->
  // hinges -> disk cuts. opts: {angle (30), rims (true), weights, forced (Set of keys), marked, faces (subset)}
  function seamEdges(cage, opts) {
    const o = optsOf(opts), forced = forcedOf(cage, o), weights = o.useWeights || o.weights ? weightMap(o.weights) : null;
    if (o.marked === "ONLY") return forced || new Set();
    const subset = Array.isArray(o.faces) && o.faces.length ? o.faces.slice().sort((a, b) => a - b) : null;
    if (!subset) return seamEdgesParts(cage.v, cage.f, o.angle, o.rims, weights, forced, null);
    // region widths and tie breaks come off the whole model, skipped parts included
    const [minWidth, modelArea] = wholeMeshInputs(cage.v, cage.f, o.rims, forced);
    return seamEdgesParts(cage.v, subset.map((i) => cage.f[i]), o.angle, o.rims, weights, forced, { minWidth, modelArea, faceIds: subset });
  }
  // hard-surface mode: seams on sharp features (66 degrees). surfaceMode "auto" only seams the loose parts that read
  // hard (isHardSurface); "organic" returns only forced / marked seams (the engine places the rest)
  function hardSurfaceSeams(cage, opts) {
    const o = optsOf(Object.assign({ surfaceMode: "hard" }, opts));
    const forced = forcedOf(cage, o);
    if (o.surfaceMode === "organic" || o.marked === "ONLY") return forced || new Set();
    let faces = Array.isArray(o.faces) && o.faces.length ? o.faces : null;
    if (o.surfaceMode === "auto") {
      const hard = hardFacesRaw(cage.v, cage.f, forced, o.marked);
      if (!hard.size) return forced || new Set();
      const sel = faces ? faces.filter((f) => hard.has(f)) : [...hard];
      faces = sel.length === cage.f.length ? null : sel;
      if (faces && !faces.length) return forced || new Set();
    }
    let seams = seamEdges(cage, Object.assign({}, o, { angle: o.hardAngle, faces, marked: "NONE", forced }));
    if (o.useSymmetry) seams = symmetrySeams(cage, seams, o);
    return seams;
  }
  const isHardSurfaceCage = (cage) => isHardSurface(cage.v, cage.f);
  // the faces of the loose parts that read hard-surface (the original add-on's Auto mode)
  const hardFaces = (cage, opts) => { const o = optsOf(opts); return hardFacesRaw(cage.v, cage.f, forcedOf(cage, o), o.marked); };
  // islands (face lists) a seam set makes
  const islands = (cage, seams) => islandGroups(cage.f, seams, faceEdges(cage.f));
  // [euler, boundary loops] of some faces under a seam set: a topological disk is [1, 1 loop]
  function topology(cage, faces, seams) { const [ec, loops] = uvTopology(faces, cage.f, faceEdges(cage.f), seams); return { euler: ec, loops: loops.length, disk: ec === 1 && loops.length === 1 }; }

  // ------------------------------------------------------------------ public: symmetry
  // mirror maps across planes through opts.center (default: the bounding box centre). -> [Map v -> v] | null
  const mirrorMaps = (cage, opts) => { const o = optsOf(opts); return mirrorMatches(cage.v, o.center || bboxCenter(cage.v), o.symAxes); };
  // seams mirrored across the symmetry planes, then any island the mirroring closed into a ring opened again
  function symmetrySeams(cage, seams, opts) {
    const o = optsOf(opts), maps = mirrorMaps(cage, o);
    if (!maps) return new Set(seams);
    const edges = faceEdges(cage.f);
    let out = mirrorSeamsRaw(toSeamSet(seams), maps, edges);
    const dropped = halfFaces(cage.v, cage.f, o.symAxes.map(axisIndex), maps);
    out = openMerged(cage.v, cage.f, edges, out, interfaceEdges(cage.f, dropped, edges));
    return mirrorSeamsRaw(out, maps, edges);
  }
  // the mirrored islands stacked onto their originals (sym_merge): a new cage
  function stackMirrored(cage, opts) {
    const o = optsOf(opts);
    if (!hasUV(cage)) return cloneCage(cage);
    const maps = mirrorPermutations(cage.v, cage.f, o.center || bboxCenter(cage.v), o.symAxes);
    if (!maps) return cloneCage(cage);
    const groups = shellsOf(cage).map((s) => s.faces), out = cloneCage(cage);
    for (const [target, corner, source, sc] of stackMirroredRaw(cage.f, groups, maps)) if (corner >= 0) out.uv[out.fuv[target][corner]] = cage.uv[cage.fuv[source][sc]].slice();
    return out;
  }

  // ------------------------------------------------------------------ public: reroute
  // move existing seams onto creases / shorter paths (boundaries.py reroute_boundaries + teeth), keeping islands disks.
  // seams default: the cage's own interior seams. -> a new seam Set
  function rerouteSeams(cage, seams, opts) {
    const o = optsOf(opts), forced = toSeamSet(o.forced);
    const s = toSeamSet(seams) || markedSeams(cage);
    const [weighted, areas, edges] = build(cage.v, cage.f);
    const groups = islandGroups(cage.f, s, edges), label = new Array(cage.f.length);
    groups.forEach((gr, gi) => { for (const f of gr) label[f] = gi; });
    let lab = o.teeth === false ? label : flattenTeeth(weighted, cage.f, edges, label, o.angle, forced);
    lab = rerouteBoundaries(cage.v, cage.f, areas, edges, lab, creaseRelief(cage.v, cage.f, weighted, edges), forced);
    const out = boundaryEdges(edges, lab);
    // slits inside an island (a seam with the same island on both sides) stay where they were
    for (const k of s) { const ow = edges.get(k); if (ow && ow.length === 2 && label[ow[0]] === label[ow[1]]) out.add(k); }
    for (const k of [...out]) { const ow = edges.get(k); if (!ow || ow.length !== 2) out.delete(k); }
    return out;
  }

  // ------------------------------------------------------------------ public: after a flatten
  // the flattened map's long / folded islands cut at their necks (islands.py split_islands). -> extra seam Set
  function splitIslands(cage, opts) {
    const o = optsOf(opts);
    if (!hasUV(cage)) return new Set();
    return splitIslandsRaw(cage.v, cage.f, uvSeams(cage), faceUVs(cage), weightMap(o.weights));
  }
  // split_moves + finish_preseed: cut the clean islands at their necks and shrink each new piece a little (98%)
  // toward its own centre so the pieces read apart without a re-flatten. -> new cage (uvInfo.split = cut count)
  function finishSplit(cage) {
    if (!hasUV(cage)) return cloneCage(cage);
    const uvs = faceUVs(cage), [moves, seams] = splitMovesRaw(cage.v, cage.f, uvs, uvSeams(cage));
    if (!moves.length) return cloneCage(cage);
    const out = applySeams(cage, seams);
    for (const [f, corner, u, v] of moves) out.uv[out.fuv[f][corner]] = [u, v];
    out.uvInfo = Object.assign({}, cage.uvInfo || {}, { split: seams.size });
    return out;
  }
  // symmetric Dirichlet distortion of some faces' UVs (4 = no distortion, Infinity = a flip)
  const flattenDistortion = (cage, faces) => flattenDistortionRaw(cage.v, cage.f, faceUVs(cage), faces || cage.f.map((_, i) => i));
  // would the engine throw this island's layout away? (a flip, not a disk, or crossing borders)
  const islandIsRuined = (cage, faces) => islandRuined(faces, cage.f, faceUVs(cage), faceEdges(cage.f), uvSeams(cage));

  // ------------------------------------------------------------------ public: rectify
  // the Tutte (uniform harmonic) solve that stands in for the original's pinned unwrap: the boundary is pinned on a
  // rectangle (convex), so the interior can not flip
  function harmonic(ids, fixed, neighbors, start) {
    const pos = new Map(start), free = ids.filter((i) => !fixed.has(i));
    for (const [i, p] of fixed) pos.set(i, p.slice());
    for (let it = 0; it < 2000; it++) {
      let move = 0;
      for (const i of free) {
        const ns = neighbors.get(i); let x = 0, y = 0;
        for (const n of ns) { const p = pos.get(n); x += p[0]; y += p[1]; }
        x /= ns.size; y /= ns.size;
        const p = pos.get(i); move = Math.max(move, Math.abs(p[0] - x) + Math.abs(p[1] - y));
        pos.set(i, [x, y]);
      }
      if (move < 1e-12) break;
    }
    return pos;
  }
  // straighten quad-ish islands (strips, panels) into rectangles. opts: {faces (only the shells they touch), axisAlign (true),
  // rectifyMode ("rectangle" | "spine")}
  // -> new cage; uvInfo.rectified = how many islands changed
  function rectify(cage, opts) {
    const o = optsOf(opts);
    if (!hasUV(cage)) return cloneCage(cage);
    let groups = shellsOf(cage).map((s) => s.faces);
    if (Array.isArray(o.faces) && o.faces.length) { const want = new Set(o.faces); groups = groups.filter((gr) => gr.some((f) => want.has(f))); }
    const coord = (id) => cage.uv[id];
    const plans = rectifyTargetsRaw(cage.fuv, coord, groups, o.axisAlign, o.rectifyMode === "spine");
    const out = cloneCage(cage), uvsBefore = faceUVs(cage);
    let changed = 0;
    for (const [group, targets, inner] of plans) {
      const before = flattenDistortionRaw(cage.v, cage.f, uvsBefore, group);
      const ids = [...new Set(group.flatMap((fi) => cage.fuv[fi]))];
      let pos;
      if (inner) pos = new Map([...targets, ...inner]);
      else {
        const neighbors = new Map();
        for (const fi of group) { const c = cage.fuv[fi]; for (let i = 0; i < c.length; i++) { getSet(neighbors, c[i]).add(c[(i + 1) % c.length]); getSet(neighbors, c[(i + 1) % c.length]).add(c[i]); } }
        pos = harmonic(ids, targets, neighbors, ids.map((i) => [i, cage.uv[i].slice()]));
      }
      const solved = cage.fuv.map((c) => c.map((i) => (pos.has(i) ? pos.get(i) : cage.uv[i])));
      const total = group.reduce((s, fi) => s + signedArea(uvsBefore[fi]), 0), orientation = total >= 0 ? 1 : -1;
      const areaBefore = Math.abs(total), floor = FLIP_NOISE * areaBefore;
      let areaAfter = 0, crushed = false;
      for (const fi of group) {
        const pts = solved[fi], face = cage.f[fi];
        for (let i = 1; i + 1 < pts.length; i++) {
          const a = signedArea([pts[0], pts[i], pts[i + 1]]) * orientation; areaAfter += a;
          if (a <= floor && vnorm(cross(sub3(cage.v[face[i]], cage.v[face[0]]), sub3(cage.v[face[i + 1]], cage.v[face[0]]))) > 0) crushed = true;
        }
      }
      const after = flattenDistortionRaw(cage.v, cage.f, solved, group);
      const bad = crushed || !(RECTIFY_COLLAPSE * areaBefore <= areaAfter && areaAfter <= areaBefore / RECTIFY_COLLAPSE) || after > before + RECTIFY_DISTORTION;
      if (bad) continue;
      for (const i of ids) if (pos.has(i)) out.uv[i] = pos.get(i).slice();
      changed++;
    }
    out.uvInfo = Object.assign({}, cage.uvInfo || {}, { rectified: changed });
    return out;
  }

  // ------------------------------------------------------------------ public: similar islands
  // Pieces that are rigid copies of each other (rotation or reflection + move). opts.by: "shells" (default when the
  // cage has UVs) or "parts" (loose parts). -> [{rep: {faces}, twins: [{faces, matrix (4x4), exact, mirrored, vertexMap}]}]
  function similarIslands(cage, opts) {
    const o = opts || {}, by = o.by || (hasUV(cage) ? "shells" : "parts");
    const groups = by === "shells" ? shellsOf(cage).map((s) => s.faces) : vertexComponents(cage.f);
    const pieces = groups.map((fs) => makePiece(cage.v, cage.f, fs)), reps = new Map(), out = new Map();
    for (const piece of pieces) {
      const cands = getArr(reps, piece.signature);
      let matched = false;
      for (const rep of cands) {
        const m = twinMatrix(rep, piece);
        if (!m) continue;
        // the twin's vertex -> the rep's vertex (mesh indices)
        const vertexMap = new Map(piece.vertsOf.map((v, i) => [v, rep.vertsOf[m.perm[i]]]));
        if (!out.has(rep)) out.set(rep, []);
        out.get(rep).push({ faces: piece.faces, matrix: m.matrix, exact: m.exact, mirrored: m.mirrored, vertexMap });
        matched = true; break;
      }
      if (!matched) cands.push(piece);
    }
    return [...out].map(([rep, twins]) => ({ rep: { faces: rep.faces }, twins }));
  }
  // stack_similar: each twin takes its rep's UVs, so only one of each set needs unwrapping. -> new cage
  function stackSimilar(cage, opts) {
    if (!hasUV(cage)) return cloneCage(cage);
    const out = cloneCage(cage);
    for (const { rep, twins } of similarIslands(cage, opts)) {
      const uvAt = new Map();
      for (const fi of rep.faces) cage.f[fi].forEach((v, k) => { if (!uvAt.has(v)) uvAt.set(v, cage.uv[cage.fuv[fi][k]]); });
      for (const t of twins) for (const fi of t.faces) cage.f[fi].forEach((v, k) => { const src = uvAt.get(t.vertexMap.get(v)); if (src) out.uv[out.fuv[fi][k]] = src.slice(); });
    }
    return out;
  }
  // find_stacks: islands whose UVs are already identical (to 9 decimals) - the packer keeps one, the rest follow it
  function findStacks(cage) {
    if (!hasUV(cage)) return [];
    const r = (x) => Math.round(x * 10 ** STACK_DECIMALS) / 10 ** STACK_DECIMALS, by = new Map();
    for (const s of shellsOf(cage)) {
      const key = s.faces.flatMap((fi) => cage.fuv[fi].map((i) => [r(cage.uv[i][0]), r(cage.uv[i][1])])).sort(cmpT).join(";");
      getArr(by, key).push(s.faces);
    }
    return [...by.values()].filter((m) => m.length > 1).map((m) => ({ kept: m[0], duplicates: m.slice(1) }));
  }

  // ------------------------------------------------------------------ public: the fallback flatten + layout
  // Unfold each shell face by face, gluing every face rigidly onto the edge it shares with an already placed one.
  // Exact for islands of flat faces that are developable (boxes, prisms, cylinder walls, the islands hard-surface mode
  // makes); curved islands come out distorted / overlapped - that is what opts.flatten (the C++ engine) is for.
  function flattenRigidSync(cage) {
    const m = hasUV(cage) ? cage : applySeams(cage, new Set());
    const out = cloneCage(m), placed = new Array(m.uv.length).fill(null);
    const edges = faceEdges(m.f);
    const faceBasis = (face) => {
      const n = [0, 0, 0];
      for (let k = 0; k < face.length; k++) { const a = m.v[face[k]], b = m.v[face[(k + 1) % face.length]]; n[0] += (a[1] - b[1]) * (a[2] + b[2]); n[1] += (a[2] - b[2]) * (a[0] + b[0]); n[2] += (a[0] - b[0]) * (a[1] + b[1]); }
      const l = vnorm(n) || 1, nn = n.map((x) => x / l), o = m.v[face[0]];
      let u = sub3(m.v[face[1]], o); const lift = dot3(u, nn); u = u.map((x, k) => x - lift * nn[k]); const ul = vnorm(u) || 1; u = u.map((x) => x / ul);
      return [o, u, cross(nn, u)];
    };
    const shells = shellsOf(m), boxes = [], areas = [];
    for (const sh of shells) {
      const inShell = new Set(sh.faces), done = new Set();
      const local = (fi) => { const b = faceBasis(m.f[fi]); return m.f[fi].map((v) => project(b, m.v[v])); };
      const queue = [sh.faces[0]];
      local(sh.faces[0]).forEach((p, k) => { placed[m.fuv[sh.faces[0]][k]] = p; });
      done.add(sh.faces[0]);
      while (queue.length) {
        const fi = queue.shift(), face = m.f[fi];
        for (let k = 0; k < face.length; k++) {
          const a = face[k], b = face[(k + 1) % face.length], owners = edges.get(pair(a, b));
          if (owners.length !== 2) continue;
          const gi = owners[0] === fi ? owners[1] : owners[0];
          if (!inShell.has(gi) || done.has(gi)) continue;
          const gf = m.f[gi], ia = gf.indexOf(a), ib = gf.indexOf(b);
          const ua = m.fuv[gi][ia], ub = m.fuv[gi][ib];
          if (ua !== m.fuv[fi][k] || ub !== m.fuv[fi][(k + 1) % face.length]) continue;   // a slit: not glued here
          const lp = local(gi), t = glueTransform(placed[ua], placed[ub], lp[ia], lp[ib]);
          if (!t) continue;
          lp.forEach((p, j) => { const id = m.fuv[gi][j]; if (!placed[id]) placed[id] = applyTransform(t, p); });
          done.add(gi); queue.push(gi);
        }
      }
      for (const fi of sh.faces) if (!done.has(fi)) local(fi).forEach((p, k) => { const id = m.fuv[fi][k]; if (!placed[id]) placed[id] = p; });
      const pts = [...sh.uvs].map((i) => placed[i]);
      boxes.push([Math.min(...pts.map((p) => p[0])), Math.min(...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[1]))]);
      areas.push(sh.faces.reduce((s, fi) => s + signedArea(m.fuv[fi].map((i) => placed[i])), 0));
    }
    // islands laid side by side (mesh.py island_layout), then the whole map fit into 0-1
    const layout = boxes.length ? islandLayout(boxes, areas) : [];
    shells.forEach((sh, si) => {
      const [flip, du, dv] = layout[si];
      for (const i of sh.uvs) { const p = placed[i]; out.uv[i] = [(flip !== null ? flip - p[0] : p[0]) + du, p[1] + dv]; }
    });
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const p of out.uv) { x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); }
    const s = 1 / Math.max(x1 - x0, y1 - y0, 1e-12);
    out.uv = out.uv.map((p) => [(p[0] - x0) * s, (p[1] - y0) * s]);
    out.uvInfo = Object.assign({}, cage.uvInfo || {}, { flatten: "rigid", shells: shells.length });
    return out;
  }
  const flattenRigid = async (cage) => flattenRigidSync(cage);
  // the faces of a selection grown by rings of neighbours (area_expand)
  function growFaces(cage, faces, rings) {
    const sel = new Set(faces), vf = new Map();
    cage.f.forEach((f, fi) => { for (const v of f) getArr(vf, v).push(fi); });
    for (let r = 0; r < (rings == null ? DEFAULTS.areaExpand : rings); r++) {
      const add = [];
      for (const fi of sel) for (const v of cage.f[fi]) for (const o of vf.get(v)) if (!sel.has(o)) add.push(o);
      for (const o of add) sel.add(o);
    }
    return [...sel].sort((a, b) => a - b);
  }

  // ------------------------------------------------------------------ public: the whole unwrap
  // The original add-on's unwrap flow, engine-agnostic:
  //   seams (hardSurfaceSeams / marks) -> symmetric seams -> cut -> opts.flatten (THE ENGINE HOOK) -> split necks
  //   (re-flatten when symmetric) -> rectify -> stack mirrored -> stack similar -> opts.pack (the packer hook)
  // opts.flatten(cage, {priority, bound, weights}) -> Promise<cage>: same faces, new UVs; Forge wires it to the C++
  // engine. Default: flattenRigid. opts.pack(cage, {margin, fixScale}) -> Promise<cage> (default: none).
  async function unwrap(cage, opts) {
    const o = optsOf(opts), t0 = Date.now();
    const flatten = typeof o.flatten === "function" ? o.flatten : flattenRigid;
    const hookOpts = { priority: o.priority, bound: PRIORITY_BOUND[o.priority] || PRIORITY_BOUND.BALANCED, weights: o.useWeights ? weightMap(o.weights) : null };
    let seams = hardSurfaceSeams(cage, Object.assign({}, o, { useSymmetry: false }));
    if (o.useSymmetry) seams = symmetrySeams(cage, seams, o);
    const edges = faceEdges(cage.f);
    const subset = flattenable(cage.f.map((_, i) => i), edges, seams);
    let m = applySeams(cage, seams);
    m = await flatten(m, hookOpts);
    if (!hasUV(m) || m.f.length !== cage.f.length) throw new Error("The flatten step returned no usable UVs.");
    const passes = o.useSymmetry ? Math.max(3, o.splitPasses) : o.splitPasses;
    let split = 0;
    if (o.useSymmetry) {
      // a second pass in uv space would land differently on each side: cut, mirror the cut, re-flatten
      const maps = mirrorMaps(cage, o);
      for (let p = 0; p < passes; p++) {
        const extra = splitIslands(m, o);
        if (!extra.size) break;
        const s = maps ? mirrorSeamsRaw(unionSets(uvSeams(m), extra), maps, edges) : unionSets(uvSeams(m), extra);
        split += extra.size;
        m = await flatten(applySeams(m, s), hookOpts);
      }
    } else for (let p = 0; p < passes; p++) { const before = uvSeams(m).size; m = finishSplit(m); const added = uvSeams(m).size - before; if (added <= 0) break; split += added; }
    if (o.rectify) m = rectify(m, o);
    if (o.useSymmetry && o.symMerge) m = stackMirrored(m, o);
    if (o.stackSimilar) m = stackSimilar(m, o);
    if (o.packAfterUnwrap && typeof o.pack === "function") m = await o.pack(m, { margin: o.margin, fixScale: o.fixScale });
    m.uvInfo = Object.assign({}, m.uvInfo || {}, { seams: uvSeams(m).size, split, flattened: subset.length, ms: Date.now() - t0 });
    return m;
  }

  root.ForgeUVgami = {
    DEFAULTS, PRIORITY_BOUND,
    // seams
    seamEdges, hardSurfaceSeams, hardFaces, isHardSurface: isHardSurfaceCage, islands, topology, applySeams, markedSeams,
    // symmetry
    mirrorMaps, symmetrySeams, stackMirrored,
    // reroute
    rerouteSeams,
    // after a flatten
    splitIslands, finishSplit, flattenDistortion, islandIsRuined,
    // rectify
    rectify,
    // similar
    similarIslands, stackSimilar, findStacks,
    // flatten fallback, selection, the whole flow
    flattenRigid, flattenRigidSync, growFaces, unwrap,
    // the ported internals, for tests and for anyone wiring a different flow (raw mesh lists, not cages)
    core: {
      LOW_ANGLE, CREASE_ANGLE, FLAT_ANGLE, pair, build, faceEdges, turnAngle, partition, absorb, mergeSmooth, mergeFlat, closeRings,
      detectWidth, regionTopology, unfoldHinges, flattenTeeth, rerouteBoundaries, boundaryEdges, creaseRelief, cutPath, pathCost,
      connectLoops, diskCuts, snapPaths, sweepRims, splitSweeps, isHardSurface, seamEdges: seamEdgesRaw, islandGroups, vertexComponents,
      uvTopology, islandRuined, crosses, splitIslands: splitIslandsRaw, splitMoves: splitMovesRaw, flattenDistortion: flattenDistortionRaw,
      rectifyTargets: rectifyTargetsRaw, mirrorMatches, mirrorPermutations, mirrorSeams: mirrorSeamsRaw, halfFaces, interfaceEdges,
      openMerged, stackMirrored: stackMirroredRaw, rigidFit, eigh, islandsOverlap, islandLayout, signedArea, uvsCollapsed,
    },
  };
  if (typeof module !== "undefined" && module.exports) module.exports = root.ForgeUVgami;
})(typeof window !== "undefined" ? window : globalThis);
