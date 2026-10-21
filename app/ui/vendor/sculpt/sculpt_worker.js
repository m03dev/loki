/* Forge's sculpting engine, in a Web Worker: the WebAssembly engine (sculpt.wasm via sculpt_engine.js) owns the
 * sculpt mesh here, off the window's thread, so strokes never stall the viewport. The window sends cursor rays;
 * the worker sends back the vertices that moved (positions + normals, transferred, not copied) or, after a
 * topology change (dynamic detail, remesh, subdivision levels), the whole new mesh.
 *
 * Messages in:  cage {seq, v, sizes, idx, levels, max} (smooth preview of a polygon cage) | load {pos, idx} | brush {preset, strength, symmetry, dyn {on, detail, relative, constant}}
 *               press {ray, pressure, radius, mods, mode?, tube?, insert?} (mode "curve": the stroke draws a Tube on
 *               release; mode "insert": a primitive is added where it lands)
 *               drag {rays, pressure, pressures?, radius, angle} | release | hit {seq, ray} | setPositions {pos} | op {name, arg}
 *               UV unwrapping of a polygon cage with map UVs (no sculpt mesh needed, like cage; pos xyz, sizes corners
 *               per face, fv / fuv a vertex id / UV index per corner, uv u,v per UV index):
 *               uvUnfold {seq, pos, sizes, fv, fuv, uv, pinned?, iterations?, scaleToDensity?}
 *               uvLayout {seq, pos, sizes, fv, fuv, uv, paddingPx?, resolution?, rotate?, scaleMode?, margin?}
 *               uvAuto {seq, pos, sizes, fv, fuv?, uv?, opts?} (fuv given = keep those seams unless opts.keepSeams false)
 * Messages out: cage {seq, steps, faces, pos, idx, ms} | ready | fail | loaded | dirty {ids, pos, nrm, ms} | topology {pos, nrm, idx, polys, levels, level}
 *               hit {seq, point, normal} | released {kind} | done {name, ok, info}
 *               uvUnfold {seq, shells, uv, flips, stretch, ms} | uvLayout {seq, shells, uv, ms} | uvAuto {seq, uv, fuv, charts, ms}
 *               ready carries ops: the message types this worker understands; an unknown type or a failed UV call
 *               posts fail {seq, during, error} (Forge waits on replies by seq) */
/* global SculptEngine, importScripts */
"use strict";
importScripts("/ui/vendor/sculpt/sculpt_engine.js");

let E = null, adjStart = null, adj = null, topoSent = 0, lastTopoPost = 0;
// The engine's dirty list already holds every vertex whose position OR normal changed (the moved set plus its
// one-ring: brush.cpp applyDisplacements), so padding it with another ring here re-sent only ~4% more vertices
// for ~2.7 ms of JS per flush at 1M vertices (measured). Kept behind this switch (brush message padRing).
let padRing = false;
let curve = null, inserted = false, dragMs = 0;
const WORKER_OPS = ["load", "brush", "press", "drag", "release", "hit", "setPositions", "cage", "op", "uvUnfold", "uvLayout", "uvAuto"];   // Tube stroke in progress / Insert done at press / engine time

SculptEngine.create("/ui/vendor/sculpt/sculpt.wasm")
  .then((e) => { E = e; postMessage({ t: "ready", ops: WORKER_OPS }); })
  .catch((err) => postMessage({ t: "fail", error: String(err && err.message || err) }));

function buildAdjacency() {  // vertex one-rings: a moved vertex changes its neighbours' normals too
  const n = E.vertexCount, T = E.tris(), deg = new Int32Array(n + 1);
  for (let i = 0; i < T.length; i += 3) { if (T[i] < 0) continue; deg[T[i]] += 2; deg[T[i + 1]] += 2; deg[T[i + 2]] += 2; }
  adjStart = new Int32Array(n + 1);
  for (let v = 0; v < n; v++) adjStart[v + 1] = adjStart[v] + deg[v];
  adj = new Int32Array(adjStart[n]);
  const fill = adjStart.slice(0, n);
  for (let i = 0; i < T.length; i += 3) {
    const a = T[i], b = T[i + 1], c = T[i + 2];
    if (a < 0) continue;
    adj[fill[a]++] = b; adj[fill[a]++] = c; adj[fill[b]++] = a; adj[fill[b]++] = c; adj[fill[c]++] = a; adj[fill[c]++] = b;
  }
}

function sendTopology(extra) {
  const T = E.tris(), live = [];
  for (let i = 0; i < T.length; i += 3) if (T[i] >= 0) live.push(T[i], T[i + 1], T[i + 2]);
  const pos = E.positions().slice(), nrm = E.normals().slice(), idx = Uint32Array.from(live);
  topoSent = E.topologyVersion;
  lastTopoPost = performance.now();
  buildAdjacency();
  E.takeDirty();
  postMessage(Object.assign({ t: "topology", pos, nrm, idx, polys: E.polygons(), levels: E.levelCount, level: E.level }, extra || {}),
    [pos.buffer, nrm.buffer, idx.buffer]);
}

let mark = null, list = [];
function flush(midStroke) {
  if (E.topologyVersion !== topoSent) {  // dynamic detail re-tessellated: the window needs the new mesh
    if (!midStroke || performance.now() - lastTopoPost > 60) sendTopology();
    return;
  }
  const d = E.takeDirty();
  if (!d.length) return;
  let ids = d;
  if (padRing) {
    const n = E.vertexCount;
    if (!mark || mark.length < n) mark = new Uint8Array(n);
    list.length = 0;
    for (const v of d) {
      if (!mark[v]) { mark[v] = 1; list.push(v); }
      for (let k = adjStart[v]; k < adjStart[v + 1]; k++) { const u = adj[k]; if (!mark[u]) { mark[u] = 1; list.push(u); } }
    }
    for (const v of list) mark[v] = 0;
    ids = Int32Array.from(list);
  }
  const P = E.positions(), N = E.normals();
  const pos = new Float32Array(ids.length * 3), nrm = new Float32Array(ids.length * 3);
  for (let i = 0; i < ids.length; i++) {
    const v = ids[i] * 3;
    pos[i * 3] = P[v]; pos[i * 3 + 1] = P[v + 1]; pos[i * 3 + 2] = P[v + 2];
    nrm[i * 3] = N[v]; nrm[i * 3 + 1] = N[v + 1]; nrm[i * 3 + 2] = N[v + 2];
  }
  postMessage({ t: "dirty", ids, pos, nrm, ms: dragMs }, [ids.buffer, pos.buffer, nrm.buffer]);
  dragMs = 0;
}

const OPS = {
  voxelRemesh: (a) => E.voxelRemesh(a || 128),
  quadRemesh: (a) => E.quadRemesh(a || 4000) > 0,
  decimate: (a) => E.decimate(a && a.percent != null ? a.percent : (typeof a === "number" ? a : 50), !a || a.lockBorder !== false, (a && a.maxError) || 0) > 0,
  divide: () => E.divide() > 0,
  setLevel: (a) => E.setLevel(a),
  smoothAll: (a) => { E.smoothAll(a || 0.5, 2); return true; },
};

onmessage = (ev) => {
  const m = ev.data;
  if (!E) { postMessage({ t: "fail", error: "engine not loaded yet" }); return; }
  try {
    switch (m.t) {
      case "load": {
        const t0 = performance.now();
        E.load(m.pos, m.idx);
        topoSent = E.topologyVersion;
        buildAdjacency();
        E.takeDirty();
        postMessage({ t: "loaded", id: m.id, verts: E.vertexCount, ms: performance.now() - t0 });
        break;
      }
      case "brush":
        E.setBrush(m.preset);
        E.setStrength(m.strength);
        E.setSymmetry(m.symmetry);
        if (m.radial != null) E.setRadial(m.radial, m.radialAxis == null ? 1 : m.radialAxis);
        // detail relative to the brush (default), or a fixed edge length (the window turns "N pixels on screen"
        // into one at the press point: screen-relative detail)
        E.setDyntopo(!!(m.dyn && m.dyn.on), (m.dyn && m.dyn.detail) || 0.12, !(m.dyn && m.dyn.relative === false),
          (m.dyn && m.dyn.constant) || 0.02);
        if (typeof m.padRing === "boolean") padRing = m.padRing;
        break;
      case "press": {
        curve = null; inserted = false;
        if (m.mode === "curve" || m.mode === "insert") {   // Tube / Insert Mesh: add geometry, no sculpting
          const h = E.raycast(m.ray.origin, m.ray.dir);
          if (h && m.mode === "curve") curve = { pts: [h.point[0], h.point[1], h.point[2]], last: h.point, radius: m.radius, tube: m.tube || {} };
          if (h && m.mode === "insert") {
            const ins = m.insert || {};
            inserted = E.insert(ins.kind || 0, h.point, h.normal, m.radius, ins.depth == null ? 0.3 : ins.depth) > 0;
            if (inserted) sendTopology({ stroke: true });
          }
          postMessage({ t: "pressed", ok: !!h });
          break;
        }
        const ok = E.press(m.ray, m.pressure, m.radius, m.mods);
        if (ok) flush(true);
        postMessage({ t: "pressed", ok });
        break;
      }
      case "drag": {
        if (curve) {   // the Tube follows the surface under the cursor, one point per quarter radius
          for (const r of m.rays) {
            const h = E.raycast(r.origin, r.dir);
            if (!h) continue;
            const p = h.point, q = curve.last;
            if (Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]) < curve.radius * 0.25) continue;
            curve.pts.push(p[0], p[1], p[2]); curve.last = p;
          }
          break;
        }
        if (inserted) break;
        const t0 = performance.now();
        for (let i = 0; i < m.rays.length; i++) E.drag(m.rays[i], m.pressures ? m.pressures[i] : m.pressure, m.radius, m.angle);
        dragMs += performance.now() - t0;
        flush(true);
        break;
      }
      case "release": {
        if (curve || inserted) {
          let kind = inserted ? 2 : 0;
          if (curve && curve.pts.length >= 6) {
            const tb = curve.tube;
            if (E.tube(curve.pts, tb.radius || curve.radius * 0.35, tb.sides || 12, tb.taperStart || 0, tb.taperEnd || 0) > 0) {
              sendTopology({ stroke: true }); kind = 2;
            }
          }
          curve = null; inserted = false;
          postMessage({ t: "released", kind });
          break;
        }
        const kind = E.release();
        if (kind === 2 || E.topologyVersion !== topoSent) sendTopology({ stroke: true });
        else flush(false);
        postMessage({ t: "released", kind });
        break;
      }
      case "hit": {
        const h = E.raycast(m.ray.origin, m.ray.dir);
        postMessage({ t: "hit", seq: m.seq, point: h && h.point, normal: h && h.normal });
        break;
      }
      case "setPositions":
        E.setPositions(m.pos);
        break;
      case "cage": {   // the modelling cage's smooth preview (no sculpt mesh needed): {seq, v, sizes, idx, levels, max}
        const t0 = performance.now();
        const r = E.cageSubdivide(m.v, m.sizes, m.idx, m.levels || 2, m.max || 60000);
        postMessage({ t: "cage", seq: m.seq, steps: r.steps, faces: r.faces, pos: r.pos, idx: r.idx, ms: performance.now() - t0 }, [r.pos.buffer, r.idx.buffer]);
        break;
      }
      case "op": {
        const t0 = performance.now();
        const ok = !!OPS[m.name](m.arg);
        if (ok) sendTopology({ op: m.name });
        postMessage({ t: "done", name: m.name, ok, ms: performance.now() - t0, verts: E.vertexCount, levels: E.levelCount, level: E.level });
        break;
      }
      case "uvUnfold":   // map-UV unfold of a polygon cage (no sculpt mesh needed)
      case "uvLayout":
      case "uvAuto": {
        const t0 = performance.now();
        try {
          if (m.t === "uvUnfold") {
            const r = E.uvUnfold(m.pos, m.sizes, m.fv, m.fuv, m.uv, { pinned: m.pinned || null, iterations: m.iterations === undefined ? 6 : m.iterations, scaleToDensity: m.scaleToDensity || 1 });
            postMessage({ t: "uvUnfold", seq: m.seq, shells: r.shells, uv: r.uv, flips: r.flips, stretch: r.stretch, ms: performance.now() - t0 }, [r.uv.buffer]);
          } else if (m.t === "uvLayout") {
            const o = {};
            for (const k of ["paddingPx", "resolution", "rotate", "scaleMode", "margin"]) if (m[k] !== undefined) o[k] = m[k];
            if (m.settings) Object.assign(o, m.settings);
            const r = E.uvLayout(m.pos, m.sizes, m.fv, m.fuv, m.uv, o);
            postMessage({ t: "uvLayout", seq: m.seq, shells: r.shells, uv: r.uv, ms: performance.now() - t0 }, [r.uv.buffer]);
          } else {
            const o = Object.assign({}, m.opts || {});
            if (m.uv && o.uv === undefined) o.uv = m.uv;
            const r = E.uvAuto(m.pos, m.sizes, m.fv, m.fuv || null, o);
            postMessage({ t: "uvAuto", seq: m.seq, uv: r.uv, fuv: r.fuv, charts: r.charts, ms: performance.now() - t0 }, [r.uv.buffer, r.fuv.buffer]);
          }
        } catch (err) {
          postMessage({ t: "fail", seq: m.seq, during: m.t, error: String(err && err.message || err) });
        }
        break;
      }
      default:
        postMessage({ t: "fail", seq: m.seq, during: m.t, error: "unknown message " + m.t });
        break;
    }
  } catch (err) {
    postMessage({ t: "fail", error: String(err && err.message || err), during: m.t });
  }
};
