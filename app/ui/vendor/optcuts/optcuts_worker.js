/* OptCuts in a Web Worker (LOKI, AGPL-3.0): the WebAssembly OptCuts (optcuts.wasm via optcuts_engine.js) cuts and
 * unwraps a triangle mesh off the window's thread. The solve runs in slices so the worker can post progress and
 * take a cancel between them.
 *
 * Messages in:  {t: "optcuts", seq, pos (Float32Array xyz), tris (Int32Array/Uint32Array, 3 per triangle), opts}
 *                 opts: distortionBound (4.1), lambdaInit (0.999), useBijectivity (1), initialCutOption
 *                 (0 OptCuts' one-point cut, 1 start from opts.seams = vertex-id pairs, 2 farthest-point cut),
 *                 maxIterations (0 = none), timeBudgetMs (0 = none), seed (0), sliceMs (progress interval, 100)
 *               {t: "cancel", seq}  - stop that run; it answers with the best result so far (converged: false)
 * Messages out: {t: "ready"} | {t: "fail", error} (engine could not load)
 *               {t: "progress", seq, iter, distortion, topologyOps, phase}
 *               {t: "optcuts", seq, ok: true, uv, cornerUV, seams, distortion, iterations, topologyOps,
 *                  seamLength, flipped, converged, ms}   (typed arrays transferred)
 *               {t: "fail", seq, error}
 * CSP: this worker is served with script-src 'self' 'wasm-unsafe-eval' (engine/loki_bridge.py WORKER_PAGES) and
 * loads nothing but its own engine script and module. */
/* global OptCutsEngine, importScripts */
"use strict";
importScripts("/ui/vendor/optcuts/optcuts_engine.js");

let E = null, loadError = "";
const queue = [];
let running = null;   // {seq, cancel}

const ready = OptCutsEngine.create("/ui/vendor/optcuts/optcuts.wasm")
  .then((e) => { E = e; postMessage({ t: "ready" }); })
  .catch((err) => { loadError = String(err && err.message || err); postMessage({ t: "fail", error: loadError }); });

function finish(seq) {
  const r = E.result();
  postMessage(Object.assign({ t: "optcuts", seq }, r), [r.uv.buffer, r.cornerUV.buffer, r.seams.buffer]);
}

function runNext() {
  if (running || !queue.length) return;
  const m = queue.shift();
  if (!E) { postMessage({ t: "fail", seq: m.seq, error: loadError || "optcuts engine not loaded" }); return runNext(); }
  const opts = m.opts || {};
  const sliceMs = Math.max(10, +opts.sliceMs || 100);
  running = { seq: m.seq, cancel: false };
  try {
    E.begin(m.pos, m.tris, opts);
  } catch (err) {
    postMessage({ t: "fail", seq: m.seq, error: String(err && err.message || err) });
    running = null;
    return runNext();
  }
  const slice = () => {
    try {
      const done = running.cancel || E.step(1 << 20, sliceMs);
      if (!done) {
        const p = E.progress();
        postMessage({ t: "progress", seq: m.seq, iter: p.iter, distortion: p.distortion, topologyOps: p.topologyOps, phase: p.phase });
        setTimeout(slice, 0);   // let a cancel message in between slices
        return;
      }
      finish(m.seq);
    } catch (err) {
      postMessage({ t: "fail", seq: m.seq, error: String(err && err.message || err) });
    }
    running = null;
    runNext();
  };
  slice();
}

onmessage = (ev) => {
  const m = ev.data || {};
  if (m.t === "cancel") {
    if (running && (m.seq === undefined || m.seq === running.seq)) running.cancel = true;
    for (let i = queue.length - 1; i >= 0; i--) if (m.seq === undefined || queue[i].seq === m.seq) {
      postMessage({ t: "fail", seq: queue[i].seq, error: "cancelled" }); queue.splice(i, 1);
    }
    return;
  }
  if (m.t !== "optcuts") return;
  queue.push(m);
  ready.then(runNext);
};
