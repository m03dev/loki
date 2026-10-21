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
