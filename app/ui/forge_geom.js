// Forge's C++ geometry helper (owner 2026-10-21: "improve it with c++"). LOKI's native engine (native/sculpt,
// C++ built to WebAssembly) runs a second, mesh-less copy in its own Web Worker for the modelling side: today the
// Catmull-Clark smooth preview of a polygon cage (keys 2 / 3), the very same result as ForgePoly.smooth in JS
// (native/sculpt/wasm/test/test_cage.js proves it) at about 6x the speed, and off the window's thread so the
// viewport never stalls on a big cage. If the worker cannot start (WebAssembly blocked, an old build), every call
// answers null and Forge keeps the JS path.
"use strict";

window.ForgeGeom = (() => {
  const SRC = "/ui/vendor/sculpt/sculpt_worker.js";   // the worker page with its own CSP (engine/loki_bridge.py)
  let worker = null, state = "idle", seq = 0, lastError = "", ops = null;   // ops: what this engine build answers (null = an older build that does not say)
  const waiting = new Map();
  const ready = [];

  function start() {
    if (state !== "idle") return;
    if (typeof Worker === "undefined" || typeof WebAssembly === "undefined") { state = "off"; return; }
    state = "starting";
    try { worker = new Worker(SRC); } catch (_) { state = "off"; return; }
    worker.onmessage = (ev) => {
      const m = ev.data || {};
      if (m.t === "ready") { state = "on"; ops = Array.isArray(m.ops) ? new Set(m.ops) : null; ready.splice(0).forEach((f) => f(true)); return; }
      if (m.t === "fail" && state === "starting") { off(); return; }
      if (m.t === "cage") { const w = waiting.get(m.seq); if (w) { waiting.delete(m.seq); w({ pos: m.pos, idx: m.idx, ms: m.ms, faces: m.faces, steps: m.steps }); } return; }
      if (m.t === "cornerNormals") { const w = waiting.get(m.seq); if (w) { waiting.delete(m.seq); w({ nrm: m.nrm, ms: m.ms }); } return; }
      if (m.t === "fail" && m.during === "cornerNormals" && waiting.has(m.seq)) { const w = waiting.get(m.seq); waiting.delete(m.seq); w(null); return; }
      if (m.t === "uvUnfold" || m.t === "uvLayout" || m.t === "uvAuto") { const w = waiting.get(m.seq); if (w) { waiting.delete(m.seq); w(m); } return; }
      if (m.t === "fail" && (m.during === "uvUnfold" || m.during === "uvLayout" || m.during === "uvAuto") && waiting.has(m.seq)) {
        const w = waiting.get(m.seq); waiting.delete(m.seq); lastError = m.error || "engine error"; w(null); return; }
      if (m.t === "fail" && m.during === "cage") { for (const w of waiting.values()) w(null); waiting.clear(); }
    };
    worker.onerror = () => off();
  }
  function off() {
    state = "off";
    ready.splice(0).forEach((f) => f(false));
    for (const w of waiting.values()) w(null);
    waiting.clear();
    try { if (worker) worker.terminate(); } catch (_) { /* gone */ }
    worker = null;
  }
  const whenReady = () => (state === "on" ? Promise.resolve(true) : state === "off" ? Promise.resolve(false)
    : new Promise((res) => { ready.push(res); start(); }));

  // a ForgePoly cage {v: [[x,y,z]...], f: [[i...]...]} -> flat arrays for the engine
  function flat(poly) {
    const v = new Float32Array(poly.v.length * 3);
    for (let i = 0; i < poly.v.length; i++) { const p = poly.v[i]; v[i * 3] = p[0]; v[i * 3 + 1] = p[1]; v[i * 3 + 2] = p[2]; }
    let n = 0; for (const f of poly.f) n += f.length;
    const sizes = new Int32Array(poly.f.length), idx = new Int32Array(n);
    let k = 0;
    poly.f.forEach((f, i) => { sizes[i] = f.length; for (const x of f) idx[k++] = x; });
    return { v, sizes, idx };
  }

  // one request; null when the engine is off, this build lacks the call, it reports an error, or it does not answer
  // within `ms` (an older worker ignores calls it does not know)
  function ask(msg, transfer, ms) {
    return whenReady().then((ok) => {
      if (!ok || !worker) return null;
      if (!ops || !ops.has(msg.t)) { lastError = "this engine build has no " + msg.t + " (rebuild native/sculpt)"; return null; }
      const id = ++seq;
      return new Promise((res) => {
        const t = setTimeout(() => { if (waiting.has(id)) { waiting.delete(id); lastError = msg.t + " did not answer in " + Math.round((ms || 60000) / 1000) + " s"; res(null); } }, ms || 60000);
        waiting.set(id, (r) => { clearTimeout(t); res(r); });
        worker.postMessage(Object.assign({ seq: id }, msg), transfer || []);
      });
    });
  }

  return {
    get lastError() { return lastError; },
    // does this engine build answer `t` (e.g. "uvUnfold")? false until the worker is ready
    supports(t) { return !!(ops && ops.has(t)); },
    // UV unfold of a flat cage {pos, sizes, fv, fuv, uv} (forge_uv.js flat()): LSCM + optimisation in C++
    uvUnfold(F, o) {
      o = o || {};
      return ask({ t: "uvUnfold", pos: F.pos, sizes: F.sizes, fv: F.fv, fuv: F.fuv, uv: F.uv, pinned: o.pinned || null,
        iterations: o.iterations == null ? 6 : o.iterations, scaleToDensity: o.scaleToDensity || 1 });
    },
    // UV layout (shell packing into 0-1): o = {paddingPx, resolution, rotate (0 none / 1 90 deg / 2 free), scaleMode (0 keep /
    // 1 uniform texel density / 2 none), margin}
    uvLayout(F, o) {
      o = o || {};
      return ask({ t: "uvLayout", pos: F.pos, sizes: F.sizes, fv: F.fv, fuv: F.fuv, uv: F.uv, paddingPx: o.paddingPx == null ? 4 : o.paddingPx,
        resolution: o.resolution || 1024, rotate: o.rotate == null ? 1 : o.rotate, scaleMode: o.scaleMode == null ? 1 : o.scaleMode, margin: o.margin == null ? 0.005 : o.margin });
    },
    // fully automatic unwrap (xatlas in C++: charts + parameterization + packing); keepSeams: keep the cage's own shells
    uvAuto(F, o) {
      o = o || {};
      return ask({ t: "uvAuto", pos: F.pos, sizes: F.sizes, fv: F.fv, fuv: o.keepSeams ? F.fuv : null, uv: o.keepSeams ? F.uv : null,
        opts: Object.assign({ padding: 4, resolution: 1024 }, o.opts || {}) }, [], 120000);
    },
    // true while the engine can take work (starting counts: the first request waits for it)
    usable() { if (state === "idle") start(); return state === "on" || state === "starting"; },
    get state() { return state; },
    // soft / hard edges: one normal per face corner (C++, core of forge_normals.js), {nrm: Float32Array, ms} or null
    cornerNormals(poly) {
      return whenReady().then((ok) => {
        if (!ok || !worker || (ops && !ops.has("cornerNormals"))) return null;
        const F = flat(poly), id = ++seq;
        const hard = [];
        if (poly.hard instanceof Map) for (const k of poly.hard.keys()) { const [a, b] = k.split(","); hard.push(+a, +b); }
        const H = Int32Array.from(hard);
        return new Promise((res) => {
          waiting.set(id, res);
          worker.postMessage({ t: "cornerNormals", seq: id, v: F.v, sizes: F.sizes, idx: F.idx, hard: H }, [F.v.buffer, F.sizes.buffer, F.idx.buffer, H.buffer]);
        });
      });
    },
    // the smooth preview: {pos: Float32Array, idx: Uint32Array, ms} or null (engine unavailable / bad cage)
    smooth(poly, levels, maxFaces) {
      return whenReady().then((ok) => {
        if (!ok || !worker) return null;
        const F = flat(poly), id = ++seq;
        return new Promise((res) => {
          waiting.set(id, res);
          worker.postMessage({ t: "cage", seq: id, v: F.v, sizes: F.sizes, idx: F.idx, levels: levels || 2, max: maxFaces || 60000 },
            [F.v.buffer, F.sizes.buffer, F.idx.buffer]);
        });
      });
    },
  };
})();
