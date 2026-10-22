/* Sculpting engine (WebAssembly) - JavaScript wrapper. Works in the browser
 * (window.SculptEngine) and in node (module.exports). The module is the C++
 * sculpting core built by wasm/build.sh; see wasm/sculpt_api.cpp for the calls.
 *
 *   const eng = await SculptEngine.create(urlOrBytes);
 *   eng.load(positions, indices);              // Float32Array xyz, Int32/Uint32 tris
 *   eng.setBrush({kernel: "Clay", strength: 0.5});
 *   if (eng.press(ray, 1, radius)) { eng.drag(ray2, 1, radius); eng.release(); }
 *   eng.takeDirty()  -> vertex ids to re-upload; eng.topologyVersion changes -> re-upload all
 */
(function (root) {
  "use strict";

  function wasi(getMem) {
    const dec = new TextDecoder();
    let line = "";
    const ok = 0, badf = 8;
    return {
      environ_get: () => ok,
      environ_sizes_get: (pc, ps) => { const v = new DataView(getMem().buffer); v.setUint32(pc, 0, true); v.setUint32(ps, 0, true); return ok; },
      clock_time_get: (id, prec, out) => {
        const ns = BigInt(Math.round((typeof performance !== "undefined" ? performance.now() : Date.now()) * 1e6));
        new DataView(getMem().buffer).setBigUint64(out, ns, true); return ok;
      },
      fd_close: () => ok,
      fd_prestat_get: () => badf,
      fd_prestat_dir_name: () => badf,
      fd_seek: () => ok,
      fd_write: (fd, iovs, n, nw) => {  // engine log lines -> console
        const v = new DataView(getMem().buffer); let total = 0;
        for (let i = 0; i < n; i++) {
          const p = v.getUint32(iovs + i * 8, true), l = v.getUint32(iovs + i * 8 + 4, true);
          line += dec.decode(new Uint8Array(getMem().buffer, p, l)); total += l;
        }
        let k; while ((k = line.indexOf("\n")) >= 0) { if (line.slice(0, k).trim()) console.debug("[sculpt]", line.slice(0, k)); line = line.slice(k + 1); }
        v.setUint32(nw, total, true); return ok;
      },
      proc_exit: (c) => { throw new Error("sculpt engine stopped (" + c + ")"); },
    };
  }

  class SculptEngine {
    static async create(src) {
      let bytes = src;
      if (typeof src === "string") {
        const node = typeof process !== "undefined" && process.versions && process.versions.node;
        if (!node) bytes = await (await fetch(src)).arrayBuffer();
        else bytes = require("fs").readFileSync(src);
      }
      let mem = null;
      const { instance } = await WebAssembly.instantiate(bytes, { wasi_snapshot_preview1: wasi(() => mem) });
      mem = instance.exports.memory;
      if (instance.exports._initialize) instance.exports._initialize();
      return new SculptEngine(instance.exports);
    }

    constructor(x) { this.x = x; this.version = 1; }
    get memory() { return this.x.memory.buffer; }  // re-read: it grows

    _put(arr, Type) {  // copy a typed array into module memory -> pointer
      const a = arr instanceof Type ? arr : Type.from(arr);
      const p = this.x.ks_alloc(a.byteLength || 4);
      new Type(this.memory, p, a.length).set(a);
      return p;
    }
    _f32(ptr, n) { return ptr ? new Float32Array(this.memory, ptr, n) : new Float32Array(0); }
    _i32(ptr, n) { return ptr ? new Int32Array(this.memory, ptr, n) : new Int32Array(0); }

    /** positions: xyz floats; indices: triangle (or polygon, with counts) vertex ids. */
    load(positions, indices, counts) {
      const pp = this._put(positions, Float32Array), ip = this._put(indices, Int32Array);
      const cp = counts ? this._put(counts, Int32Array) : 0;
      const ok = this.x.ks_load(pp, positions.length / 3, ip, indices.length, cp, counts ? counts.length : 0);
      this.x.ks_free(pp); this.x.ks_free(ip); if (cp) this.x.ks_free(cp);
      if (!ok) throw new Error("sculpt engine: bad mesh");
    }

    /** Positions changed outside the engine (host undo): copy them all in. */
    setPositions(positions) {
      const pp = this._put(positions, Float32Array);
      const ok = this.x.ks_set_positions(pp, positions.length / 3); this.x.ks_free(pp); return !!ok;
    }
    get vertexCount() { return this.x.ks_vertex_count(); }
    get triCount() { return this.x.ks_tri_count(); }
    get topologyVersion() { return this.x.ks_topology_version(); }
    /** Live views into engine memory (valid until the next engine call that may allocate). */
    positions() { return this._f32(this.x.ks_positions(), this.vertexCount * 3); }
    normals() { return this._f32(this.x.ks_normals(), this.vertexCount * 3); }
    colors() { return this._f32(this.x.ks_colors(), this.vertexCount * 3); }
    mask() { return this._f32(this.x.ks_mask(), this.vertexCount); }
    tris() { return this._i32(this.x.ks_tris(), this.triCount * 3); }
    /** Quads/n-gons when the mesh has them (after remesh / subdivision levels). */
    polygons() {
      const n = this.x.ks_poly_count(); if (!n) return null;
      return { counts: this._i32(this.x.ks_poly_counts(), n).slice(), indices: this._i32(this.x.ks_poly_indices(), this.x.ks_poly_index_count()).slice() };
    }
    /** Catmull-Clark of a polygon cage (Forge's smooth preview), independent of the sculpt mesh.
     *  verts: xyz floats; sizes: corners per face; idx: the faces' vertex ids. Up to `levels` steps while
     *  faces * 4 <= maxFaces. Returns {steps, pos (Float32Array), idx (Uint32Array, fan triangles), faces} - copies. */
    cageSubdivide(verts, sizes, idx, levels = 2, maxFaces = 60000) {
      const vp = this._put(verts, Float32Array), sp = this._put(sizes, Int32Array), ip = this._put(idx, Int32Array);
      const steps = this.x.ks_cage_subdiv(vp, verts.length / 3, sp, sizes.length, ip, idx.length, levels, maxFaces);
      this.x.ks_free(vp); this.x.ks_free(sp); this.x.ks_free(ip);
      if (steps < 0) throw new Error("sculpt engine: bad cage");
      const pos = this._f32(this.x.ks_cage_pos(), this.x.ks_cage_nverts() * 3).slice();
      const tri = new Uint32Array(this._i32(this.x.ks_cage_tris(), this.x.ks_cage_ntris() * 3));
      return { steps, pos, idx: tri, faces: this.x.ks_cage_nfaces() };
    }

    /** Soft / hard edges: one unit normal per face corner (3 floats each, the faces' corner order). Corners meeting
     *  over a soft edge share their faces' area-weighted normal; `hard` is a flat list of vertex pairs. */
    cornerNormals(verts, sizes, idx, hard) {
      const vp = this._put(verts, Float32Array), sp = this._put(sizes, Int32Array), ip = this._put(idx, Int32Array);
      const h = hard && hard.length ? hard : new Int32Array(2);
      const hp = this._put(h, Int32Array);
      const n = this.x.ks_corner_normals(vp, verts.length / 3, sp, sizes.length, ip, idx.length, hp, hard && hard.length ? hard.length / 2 : 0);
      this.x.ks_free(vp); this.x.ks_free(sp); this.x.ks_free(ip); this.x.ks_free(hp);
      if (n < 0) throw new Error("sculpt engine: bad cage");
      return this._f32(this.x.ks_corner_nrm(), n * 3).slice();
    }

    // ---- UV unwrapping of a polygon cage with map UVs (independent of the sculpt mesh; core/src/uv_unwrap.cpp).
    // pos: xyz floats; sizes: corners per face; fv: a vertex id per corner; fuv: a UV index per corner; uv: u,v
    // floats per UV index. A shell = faces sharing UV indices.
    _uvCall(pos, sizes, fv, fuv, uv, fn) {
      const ptrs = [], put = (a, T) => { const p = this._put(a, T); ptrs.push(p); return p; };
      try {
        const nuv = uv ? uv.length / 2 : 0;
        return fn(put(pos, Float32Array), pos.length / 3, put(sizes, Int32Array), sizes.length, put(fv, Int32Array),
          fuv ? put(fuv, Int32Array) : 0, fv.length, nuv, uv ? put(uv, Float32Array) : 0, put);
      } finally { for (const p of ptrs) this.x.ks_free(p); }
    }
    /** Unfold every shell: LSCM with pins, then `iterations` ARAP rounds; shells without user pins get
     *  2D area = 3D area * scaleToDensity and keep their place. pinned: nuv flags (0/1) or null.
     *  Returns {shells, uv (Float32Array copy, 2 per UV index), flips, stretch}. */
    uvUnfold(pos, sizes, fv, fuv, uv, { pinned = null, iterations = 6, scaleToDensity = 1 } = {}) {
      const r = this._uvCall(pos, sizes, fv, fuv, uv, (pp, nv, sp, nf, fp, up, nc, nuv, ip, put) => {
        const pin = pinned ? put(Uint8Array.from(pinned, (x) => (x ? 1 : 0)), Uint8Array) : 0;
        if (pinned && pinned.length !== nuv) return -1;
        return this.x.ks_uv_unfold(pp, nv, sp, nf, fp, up, nc, nuv, ip, pin, iterations | 0, scaleToDensity);
      });
      if (r < 0) throw new Error("sculpt engine: bad UV input");
      return { shells: r, uv: this._f32(this.x.ks_uv_out(), this.x.ks_uv_nuv() * 2).slice(), flips: this.x.ks_uv_flips(), stretch: this.x.ks_uv_stretch() };
    }
    /** Pack the shells into 0-1. rotate 0 none / 1 90-degree steps / 2 free; scaleMode 0 keep relative size /
     *  1 uniform texel density / 2 translate only. Returns {shells, uv}. */
    uvLayout(pos, sizes, fv, fuv, uv, { paddingPx = 4, resolution = 1024, rotate = 1, scaleMode = 1, margin = 0.005 } = {}) {
      const r = this._uvCall(pos, sizes, fv, fuv, uv, (pp, nv, sp, nf, fp, up, nc, nuv, ip) =>
        this.x.ks_uv_layout(pp, nv, sp, nf, fp, up, nc, nuv, ip, paddingPx, resolution, rotate | 0, scaleMode | 0, margin));
      if (r < 0) throw new Error("sculpt engine: bad UV input");
      return { shells: r, uv: this._f32(this.x.ks_uv_out(), this.x.ks_uv_nuv() * 2).slice() };
    }
    /** Fully automatic UVs (xatlas cuts, parameterizes and packs). With fuv (the existing seams; opts.uv
     *  optional, opts.keepSeams !== false) the existing shells are unfolded and only packed. Returns a NEW UV set: {uv, fuv (a UV index per corner,
     *  Int32Array), charts, ms}. opts: xatlas ChartOptions (maxChartArea, maxBoundaryLength, normalDeviationWeight,
     *  roundnessWeight, straightnessWeight, normalSeamWeight, textureSeamWeight, maxCost, maxIterations) and
     *  PackOptions (padding px, resolution, bilinear, blockAlign, bruteForce, rotateCharts, rotateChartsToAxis,
     *  texelsPerUnit), plus unfoldIterations (ARAP rounds for keepSeams). */
    uvAuto(pos, sizes, fv, fuv = null, opts = {}) {
      const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
      const keep = !!fuv && opts.keepSeams !== false;
      const D = { maxChartArea: 0, maxBoundaryLength: 0, normalDeviationWeight: 2, roundnessWeight: 0.01, straightnessWeight: 6,
        normalSeamWeight: 4, textureSeamWeight: 0.5, maxCost: 2, maxIterations: 1, padding: 4, resolution: 1024, bilinear: true,
        blockAlign: false, bruteForce: false, rotateCharts: true, rotateChartsToAxis: true, texelsPerUnit: 0, unfoldIterations: 6 };
      const o = Float32Array.from(Object.keys(D), (k) => { const v = opts[k] === undefined ? D[k] : opts[k]; return typeof v === "boolean" ? (v ? 1 : 0) : +v; });
      let uv = opts.uv || null;
      if (keep && !uv) { let m = -1; for (const i of fuv) if (i > m) m = i; uv = new Float32Array(2 * (m + 1)); }
      const r = this._uvCall(pos, sizes, fv, keep ? fuv : null, keep ? uv : null, (pp, nv, sp, nf, fp, up, nc, nuv, ip, put) =>
        this.x.ks_uv_auto(pp, nv, sp, nf, fp, nc, keep ? 1 : 0, up, nuv, ip, put(o, Float32Array), o.length));
      if (r < 0) throw new Error("sculpt engine: bad UV input");
      const out = this._f32(this.x.ks_uv_out(), this.x.ks_uv_auto_nuv() * 2).slice();
      const f = this._i32(this.x.ks_uv_auto_fuv(), fv.length).slice();
      return { uv: out, fuv: f, charts: r, ms: (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0 };
    }

    /** Vertex ids changed since the last call (a copy). */
    takeDirty() { const n = this.x.ks_take_dirty(); return n ? this._i32(this.x.ks_dirty(), n).slice() : new Int32Array(0); }

    _str(s, fn) {
      const b = new TextEncoder().encode(s), p = this.x.ks_alloc(b.length + 1);
      new Uint8Array(this.memory, p, b.length).set(b);
      const r = fn(p, b.length); this.x.ks_free(p); return r;
    }
    lastText() {
      const p = this.x.ks_text(); const u = new Uint8Array(this.memory, p); let e = 0; while (u[e]) e++;
      return new TextDecoder().decode(u.subarray(0, e));
    }
    /** Brush preset in the library format: {kernel, strength, falloff, spacing, ...}. */
    setBrush(preset) {
      if (!this._str(JSON.stringify(preset), (p, n) => this.x.ks_brush_json(p, n))) throw new Error("brush: " + this.lastText());
    }
    setStrength(v) { this.x.ks_brush_strength(v); }
    setInvert(on) { this.x.ks_brush_invert(on ? 1 : 0); }
    setSymmetry(bits) { this.x.ks_brush_symmetry(bits | 0); }  // 1 X, 2 Y, 4 Z
    setRadial(count, axis) { this.x.ks_brush_radial(count | 0, axis | 0); }  // `count` copies about axis 0 X, 1 Y, 2 Z
    setColor(r, g, b) { this.x.ks_brush_color(r, g, b); }
    get spacing() { return this.x.ks_brush_spacing(); }
    get isGrab() { return !!this.x.ks_brush_is_grab(); }
    /** Dynamic topology: detail = edge length as a fraction of the brush radius. */
    setDyntopo(on, detail = 0.12, relative = true, constant = 0.02) { this.x.ks_dyntopo(on ? 1 : 0, detail, relative ? 1 : 0, constant); }

    raycast(o, d) {
      if (!this.x.ks_raycast(o[0], o[1], o[2], d[0], d[1], d[2])) return null;
      const h = this._f32(this.x.ks_hit(), 8);
      return { point: [h[0], h[1], h[2]], normal: [h[3], h[4], h[5]], t: h[6] };
    }
    /** mods: 0 none, 1 invert, 2 smooth, 3 mask. Returns false when the ray misses. */
    press(ray, pressure, radius, mods = 0) {
      const o = ray.origin, d = ray.dir;
      return !!this.x.ks_press(o[0], o[1], o[2], d[0], d[1], d[2], pressure, radius, mods);
    }
    drag(ray, pressure, radius, angle = 0) {
      const o = ray.origin, d = ray.dir;
      return !!this.x.ks_drag(o[0], o[1], o[2], d[0], d[1], d[2], pressure, radius, angle);
    }
    /** 1 = positions changed, 2 = topology changed (dyntopo). */
    release() { return this.x.ks_release(); }
    undo() { return this.x.ks_undo(); }
    redo() { return this.x.ks_redo(); }
    maskOp(op) { this.x.ks_mask_op({ clear: 0, invert: 1, fill: 2 }[op] ?? op); }
    smoothAll(strength = 0.5, iterations = 2) { this.x.ks_smooth_all(strength, iterations); }
    /** Voxel remesh: an even, closed surface at `resolution` voxels across. */
    voxelRemesh(resolution = 128, relax = 2, sharp = true) { return !!this.x.ks_voxel_remesh(resolution, relax, sharp ? 1 : 0); }
    /** Field-aligned quad remesh to about `targetFaces` quads; returns the quad count. */
    quadRemesh(targetFaces = 5000) { return this.x.ks_quad_remesh(targetFaces); }
    /** Reduce (decimation): quadric edge collapse to about `percent` % of the triangles; colour kept, masked
     *  vertices locked, `lockBorder` keeps open edges. One undo step. Returns the triangle count after (0 = no change). */
    decimate(percent = 50, lockBorder = true, maxError = 0) { return this.x.ks_decimate(percent, lockBorder ? 1 : 0, maxError); }
    /** Tube (Curve Tube): sweep a circle of `radius` along points (xyz floats) and add it as a new shell
     *  (one undo step). Returns the vertex count added (0 = nothing). */
    tube(points, radius, sides = 12, taperStart = 0, taperEnd = 0) {
      const a = points instanceof Float32Array ? points : Float32Array.from(points);
      if (a.length < 6) return 0;
      const p = this._put(a, Float32Array);
      const k = this.x.ks_tube(p, a.length / 3, radius, sides, taperStart, taperEnd); this.x.ks_free(p); return k;
    }
    /** Insert Mesh: a sphere (kind 0) or cube (1) of `radius` at a surface point, along its normal, sunk by depth x radius. */
    insert(kind, point, normal, radius, depth = 0.3) {
      return this.x.ks_insert(kind | 0, point[0], point[1], point[2], normal[0], normal[1], normal[2], radius, depth);
    }
    /** Subdivision levels (Catmull-Clark, details kept per level). */
    divide() { return this.x.ks_divide(); }
    setLevel(k) { return !!this.x.ks_set_level(k); }
    get levelCount() { return this.x.ks_level_count(); }
    get level() { return this.x.ks_level(); }
  }

  if (typeof module !== "undefined" && module.exports) module.exports = SculptEngine;
  else root.SculptEngine = SculptEngine;
})(typeof window !== "undefined" ? window : globalThis);
