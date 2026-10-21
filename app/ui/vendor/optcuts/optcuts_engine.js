/* OptCuts (WebAssembly) - JavaScript wrapper. Works in the browser (self.OptCutsEngine / window.OptCutsEngine)
 * and in node (module.exports). The module is OptCuts (Li et al., SIGGRAPH Asia 2018; MIT) built by
 * native/optcuts/build.sh; the calls are in native/optcuts/wasm/optcuts_api.cpp. Part of LOKI (AGPL-3.0).
 *
 *   const eng = await OptCutsEngine.create(urlOrBytes);
 *   const r = eng.unwrap(pos, tris, { distortionBound: 4.1, seed: 1 }, (p) => console.log(p.iter, p.distortion));
 *   // r: { ok, uv (Float32Array u,v), cornerUV (Int32Array, 3 per triangle), seams (Int32Array vertex pairs),
 *   //      distortion, iterations, topologyOps, seamLength, flipped, converged, ms }
 * or step by step (what the worker does): eng.begin(pos, tris, opts); while (!eng.step(1, 50)) {...}; eng.result().
 *
 * The input is triangles only (the caller triangulates polygons and keeps the map back to its faces). A failed
 * run inside OptCuts traps the module; the wrapper then makes a fresh instance before the next run, so an
 * engine object stays usable. */
(function (root) {
  "use strict";

  function wasi(getMem) {
    const dec = new TextDecoder();
    let line = "";
    const ok = 0, badf = 8, nosys = 52;
    return {
      environ_get: () => ok,
      environ_sizes_get: (pc, ps) => { const v = new DataView(getMem().buffer); v.setUint32(pc, 0, true); v.setUint32(ps, 0, true); return ok; },
      clock_time_get: (id, prec, out) => {
        const ns = BigInt(Math.round((typeof performance !== "undefined" ? performance.now() : Date.now()) * 1e6));
        new DataView(getMem().buffer).setBigUint64(out, ns, true); return ok;
      },
      fd_close: () => ok,
      fd_fdstat_get: () => badf,
      fd_fdstat_set_flags: () => badf,
      fd_prestat_get: () => badf,
      fd_prestat_dir_name: () => badf,
      fd_read: () => badf,
      fd_seek: () => ok,
      path_open: () => nosys,   // no file system: OptCuts' log files are never opened
      fd_write: (fd, iovs, n, nw) => {
        const v = new DataView(getMem().buffer); let total = 0;
        for (let i = 0; i < n; i++) {
          const p = v.getUint32(iovs + i * 8, true), l = v.getUint32(iovs + i * 8 + 4, true);
          if (fd === 2) line += dec.decode(new Uint8Array(getMem().buffer, p, l));
          total += l;
        }
        let k; while ((k = line.indexOf("\n")) >= 0) { if (line.slice(0, k).trim()) console.debug("[optcuts]", line.slice(0, k)); line = line.slice(k + 1); }
        v.setUint32(nw, total, true); return ok;
      },
      proc_exit: (c) => { throw new Error("optcuts stopped (" + c + ")"); },
    };
  }

  const DEFAULTS = { distortionBound: 4.1, lambdaInit: 0.999, useBijectivity: 1, initialCutOption: 0,
                     maxIterations: 0, timeBudgetMs: 0, seed: 0, seams: null };

  async function load(src) {
    if (typeof src !== "string") return src;
    const node = typeof process !== "undefined" && process.versions && process.versions.node && typeof window === "undefined" && typeof importScripts === "undefined";
    if (node) return require("fs").readFileSync(src);
    return await (await fetch(src)).arrayBuffer();
  }

  class OptCutsEngine {
    static async create(src) {
      const bytes = await load(src);
      const module = await WebAssembly.compile(bytes);
      const eng = new OptCutsEngine(module);
      await eng._fresh();
      return eng;
    }

    constructor(module) { this.module = module; this.x = null; this.broken = false; this.t0 = 0; }

    async _fresh() {
      let mem = null;
      const inst = await WebAssembly.instantiate(this.module, { wasi_snapshot_preview1: wasi(() => mem) });
      mem = inst.exports.memory;
      if (inst.exports._initialize) inst.exports._initialize();
      this.x = inst.exports; this.broken = false;
    }
    _freshSync() {
      let mem = null;
      const inst = new WebAssembly.Instance(this.module, { wasi_snapshot_preview1: wasi(() => mem) });
      mem = inst.exports.memory;
      if (inst.exports._initialize) inst.exports._initialize();
      this.x = inst.exports; this.broken = false;
    }
    get memory() { return this.x.memory.buffer; }  // re-read: it grows

    _cstr(p) { const u = new Uint8Array(this.memory, p); let e = 0; while (u[e]) e++; return new TextDecoder().decode(u.subarray(0, e)); }
    _put(arr, Type) {
      const a = arr instanceof Type ? arr : Type.from(arr);
      const p = this.x.oc_alloc(a.byteLength || 4);
      new Type(this.memory, p, a.length).set(a);
      return p;
    }
    /** Run fn against the module; a trap inside OptCuts becomes an Error with OptCuts' own message. */
    _guard(fn) {
      try { return fn(); } catch (e) {
        let msg = "";
        try { msg = this._cstr(this.x.oc_error()); } catch (_) { /* memory gone */ }
        this.broken = true;
        throw new Error("optcuts: " + (msg || (e && e.message) || String(e)));
      }
    }

    /** Validate and set up a run. pos: xyz floats; tris: vertex ids, 3 per triangle. Throws on bad input. */
    begin(pos, tris, opts) {
      const o = Object.assign({}, DEFAULTS, opts || {});
      if (this.broken) this._freshSync();
      if (!pos || !tris || pos.length < 9 || pos.length % 3 || tris.length < 3 || tris.length % 3)
        throw new Error("optcuts: need positions (xyz) and triangles (3 ids each)");
      const nv = pos.length / 3, nt = tris.length / 3;
      const pp = this._put(pos, Float32Array), tp = this._put(tris, Int32Array);
      const seams = o.seams && o.seams.length ? o.seams : null;
      const sp = seams ? this._put(seams, Int32Array) : 0;
      this.t0 = (typeof performance !== "undefined" ? performance : Date).now();
      const ok = this._guard(() => this.x.oc_init(pp, nv, tp, nt, sp, seams ? seams.length / 2 : 0,
        +o.distortionBound, +o.lambdaInit, o.useBijectivity ? 1 : 0, o.initialCutOption | 0,
        o.maxIterations | 0, +o.timeBudgetMs || 0, (o.seed >>> 0)));
      this.x.oc_free(pp); this.x.oc_free(tp); if (sp) this.x.oc_free(sp);
      if (!ok) throw new Error("optcuts: " + this._cstr(this.x.oc_error()));
    }
    /** Up to `units` units of work (a Newton step or a topology decision each), at most sliceMs. true = finished. */
    step(units = 1, sliceMs = 0) {
      const s = this._guard(() => this.x.oc_step(units | 0, +sliceMs || 0));
      if (s < 0) throw new Error("optcuts: " + (this._cstr(this.x.oc_error()) || "not started"));
      return s === 1;
    }
    progress() {
      return { iter: this.x.oc_iterations(), distortion: this.x.oc_distortion(), topologyOps: this.x.oc_topology_ops(),
               lambda: this.x.oc_lambda(), phase: this._cstr(this.x.oc_phase_name()) };
    }
    /** The result (copies). Also valid after a budget stop: then `converged` is false. */
    result() {
      this._guard(() => this.x.oc_finish());
      const x = this.x, m = this.memory;
      const nuv = x.oc_uv_count(), nc = x.oc_corner_count(), ns = x.oc_seam_count();
      const uv = new Float32Array(m, x.oc_uv(), nuv * 2).slice();
      const cornerUV = new Int32Array(m, x.oc_corner_uv(), nc).slice();
      const seams = ns ? new Int32Array(m, x.oc_seams(), ns * 2).slice() : new Int32Array(0);
      const now = (typeof performance !== "undefined" ? performance : Date).now();
      return { ok: true, uv, cornerUV, seams, distortion: x.oc_result_distortion(), iterations: x.oc_iterations(),
               topologyOps: x.oc_topology_ops(), seamLength: x.oc_seam_length(), flipped: x.oc_flipped(),
               converged: !!x.oc_converged(), ms: Math.round(now - this.t0) };
    }
    /** Whole run in one call; onProgress(progress) after every slice of `sliceMs`. */
    unwrap(pos, tris, opts, onProgress, sliceMs = 100) {
      this.begin(pos, tris, opts);
      while (!this.step(1 << 20, sliceMs)) if (onProgress) onProgress(this.progress());
      return this.result();
    }
  }

  if (typeof module !== "undefined" && module.exports) module.exports = OptCutsEngine;
  else root.OptCutsEngine = OptCutsEngine;
})(typeof self !== "undefined" ? self : (typeof window !== "undefined" ? window : globalThis));
