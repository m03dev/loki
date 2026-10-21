/* Forge's sculpting engine, in a Web Worker: the WebAssembly engine (sculpt.wasm via sculpt_engine.js) owns the
 * sculpt mesh here, off the window's thread, so strokes never stall the viewport. The window sends cursor rays;
 * the worker sends back the vertices that moved (positions + normals, transferred, not copied) or, after a
 * topology change (dynamic detail, remesh, subdivision levels), the whole new mesh.
 *
 * Messages in:  load {pos, idx} | brush {preset, strength, symmetry, dyn} | press {ray, pressure, radius, mods}
 *               drag {rays, pressure, radius, angle} | release | hit {seq, ray} | setPositions {pos} | op {name, arg}
 * Messages out: ready | fail | loaded | dirty {ids, pos, nrm} | topology {pos, nrm, idx, polys, levels, level}
 *               hit {seq, point, normal} | released {kind} | done {name, ok, info} */
/* global SculptEngine, importScripts */
"use strict";
importScripts("/ui/vendor/sculpt/sculpt_engine.js");

let E = null, adjStart = null, adj = null, topoSent = 0, lastTopoPost = 0;

SculptEngine.create("/ui/vendor/sculpt/sculpt.wasm")
  .then((e) => { E = e; postMessage({ t: "ready" }); })
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
  const n = E.vertexCount;
  if (!mark || mark.length < n) mark = new Uint8Array(n);
  list.length = 0;
  for (const v of d) {
    if (!mark[v]) { mark[v] = 1; list.push(v); }
    for (let k = adjStart[v]; k < adjStart[v + 1]; k++) { const u = adj[k]; if (!mark[u]) { mark[u] = 1; list.push(u); } }
  }
  const P = E.positions(), N = E.normals(), ids = Int32Array.from(list);
  const pos = new Float32Array(ids.length * 3), nrm = new Float32Array(ids.length * 3);
  for (let i = 0; i < ids.length; i++) {
    const v = ids[i] * 3; mark[ids[i]] = 0;
    pos[i * 3] = P[v]; pos[i * 3 + 1] = P[v + 1]; pos[i * 3 + 2] = P[v + 2];
    nrm[i * 3] = N[v]; nrm[i * 3 + 1] = N[v + 1]; nrm[i * 3 + 2] = N[v + 2];
  }
  postMessage({ t: "dirty", ids, pos, nrm }, [ids.buffer, pos.buffer, nrm.buffer]);
}

const OPS = {
  voxelRemesh: (a) => E.voxelRemesh(a || 128),
  quadRemesh: (a) => E.quadRemesh(a || 4000) > 0,
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
        E.setDyntopo(!!(m.dyn && m.dyn.on), (m.dyn && m.dyn.detail) || 0.12);
        break;
      case "press": {
        const ok = E.press(m.ray, m.pressure, m.radius, m.mods);
        if (ok) flush(true);
        postMessage({ t: "pressed", ok });
        break;
      }
      case "drag":
        for (const r of m.rays) E.drag(r, m.pressure, m.radius, m.angle);
        flush(true);
        break;
      case "release": {
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
      case "op": {
        const t0 = performance.now();
        const ok = !!OPS[m.name](m.arg);
        if (ok) sendTopology({ op: m.name });
        postMessage({ t: "done", name: m.name, ok, ms: performance.now() - t0, verts: E.vertexCount, levels: E.levelCount, level: E.level });
        break;
      }
      default:
        break;
    }
  } catch (err) {
    postMessage({ t: "fail", error: String(err && err.message || err), during: m.t });
  }
};
