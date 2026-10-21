// Forge's C++ geometry helper (owner 2026-10-21: "improve it with c++"). LOKI's native engine (native/sculpt,
// C++ built to WebAssembly) runs a second, mesh-less copy in its own Web Worker for the modelling side: today the
// Catmull-Clark smooth preview of a polygon cage (keys 2 / 3), the very same result as ForgePoly.smooth in JS
// (native/sculpt/wasm/test/test_cage.js proves it) at about 6x the speed, and off the window's thread so the
// viewport never stalls on a big cage. If the worker cannot start (WebAssembly blocked, an old build), every call
// answers null and Forge keeps the JS path.
"use strict";

window.ForgeGeom = (() => {
  const SRC = "/ui/vendor/sculpt/sculpt_worker.js";   // the worker page with its own CSP (engine/loki_bridge.py)
  let worker = null, state = "idle", seq = 0;
  const waiting = new Map();
  const ready = [];

  function start() {
    if (state !== "idle") return;
    if (typeof Worker === "undefined" || typeof WebAssembly === "undefined") { state = "off"; return; }
    state = "starting";
    try { worker = new Worker(SRC); } catch (_) { state = "off"; return; }
    worker.onmessage = (ev) => {
      const m = ev.data || {};
      if (m.t === "ready") { state = "on"; ready.splice(0).forEach((f) => f(true)); return; }
      if (m.t === "fail" && state === "starting") { off(); return; }
      if (m.t === "cage") { const w = waiting.get(m.seq); if (w) { waiting.delete(m.seq); w({ pos: m.pos, idx: m.idx, ms: m.ms, faces: m.faces, steps: m.steps }); } return; }
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

  return {
    // true while the engine can take work (starting counts: the first request waits for it)
    usable() { if (state === "idle") start(); return state === "on" || state === "starting"; },
    get state() { return state; },
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
