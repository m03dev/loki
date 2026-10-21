/* Forge - the native sculpting engine (C++ built to WebAssembly, app/ui/vendor/sculpt/, source in native/sculpt/).
 *
 * The engine runs in a Web Worker (vendor/sculpt/sculpt_worker.js) and owns a copy of the sculpt mesh: a BVH for
 * picking, 40 brush kernels with the 212-preset library, dynamic detail (edges split/collapsed under the brush,
 * detail by brush size or by screen size), voxel remesh, field-aligned quad remesh, subdivision levels, Tube and
 * Insert Mesh. Forge's own mesh (view.sm, forge.js) stays the one that is drawn, saved and undone: the worker sends
 * back only the vertices a stroke moved, which go straight into the GPU buffers as runs of changed vertices, or the
 * whole new mesh after a topology change. When the worker is not available the brushes in forge.js do the work as
 * before.
 *
 * Also here: the stroke (ForgeStroke: stabiliser, even dab spacing, coalesced pointer samples, pen pressure), the
 * matcap gallery (lit-sphere looks for judging the form) and the sculpt bar's new controls. */
"use strict";

const FORGE_SCULPT_BASE = "/ui/vendor/sculpt/";
// Forge's brush buttons -> engine presets (the library has many more: the "Brushes" list)
// Tuned so the basic brushes stay smooth on dense meshes: Clay and Inflate auto-smooth a little after every dab
// (Clay alone leaves per-vertex ripples on a 100k+ mesh; 0.15 halves them, measured in test_engine.js), Smooth keeps
// volume (half Laplacian, half the HC step: a sphere no longer shrinks under it), Move follows the back faces too.
const FORGE_SCULPT_MAP = {
  draw: { kernel: "Clay", strength: 0.5, autoSmooth: 0.15 },
  inflate: { kernel: "Inflate", strength: 0.4, autoSmooth: 0.1 },
  smooth: { kernel: "Smooth", strength: 0.5, smoothVolume: 0.5 },
  flatten: { kernel: "Flatten", strength: 0.5, autoSmooth: 0.05 },
  grab: { kernel: "Move", strength: 1, frontFacesOnly: false },
  pinch: { kernel: "Pinch", strength: 0.5 },
  crease: { kernel: "Crease", strength: 0.5 },
};
const FORGE_SCULPT_FALLOFFS = ["Smooth", "Sphere", "Root", "Sharp", "Linear", "Constant"];

/* The stroke between the pointer and the dabs (pure: no DOM, tests drive it directly).
 *  - lazy mouse / stabiliser: the brush hangs on a string `lazy` pixels long behind the cursor and only moves when
 *    the string is taut, so hand jitter never reaches the surface (ZBrush's LazyMouse, Blender's Stabilize Stroke);
 *  - dabs at a fixed arc length (`step` px, the preset's spacing x the radius on screen) along the brush's path, the
 *    remainder carried to the next event, so the dab density never depends on how fast the pointer moves;
 *  - pen pressure low-passed (one-pole, `pressureSmooth`) and interpolated per dab. */
const ForgeStroke = {
  start(x, y, pressure, opts) {
    const o = opts || {};
    return { bx: x, by: y, cx: x, cy: y, p: pressure, lazy: Math.max(0, o.lazy || 0), ps: Math.min(0.95, Math.max(0, o.pressureSmooth == null ? 0.5 : o.pressureSmooth)), carry: 0 };
  },
  /** Feed one pointer sample; returns the dabs [{x, y, p}] it produced. */
  feed(st, x, y, pressure, step) {
    st.cx = x; st.cy = y;
    let tx = x, ty = y;
    const dx = x - st.bx, dy = y - st.by, d = Math.hypot(dx, dy);
    if (st.lazy > 0) {
      if (d <= st.lazy) return [];
      tx = st.bx + dx * (1 - st.lazy / d); ty = st.by + dy * (1 - st.lazy / d);
    }
    const p1 = st.p + (pressure - st.p) * (1 - st.ps), out = [];
    const sx = st.bx, sy = st.by, len = Math.hypot(tx - sx, ty - sy);
    step = Math.max(0.5, step);
    let t = step - st.carry;
    if (len > 0) {
      for (let k = 0; t <= len && k < 256; t += step, k++) {
        const f = t / len;
        out.push({ x: sx + (tx - sx) * f, y: sy + (ty - sy) * f, p: st.p + (p1 - st.p) * f });
      }
      // distance walked since the last dab (the press is a dab: it starts at 0)
      st.carry = out.length ? len - (t - step) : st.carry + len;
    }
    st.bx = tx; st.by = ty; st.p = p1;
    return out;
  },
};
window.ForgeStroke = ForgeStroke;

// Update ranges for a set of changed raw vertex ids: sorted, runs merged across small gaps, so a dab uploads its own
// vertices, not everything between the lowest and the highest id (on a 1M sphere a r=0.3 dab moved ~14k vertices
// whose ids spanned 183k: 4.4 MB per dab as one span, 0.33 MB as ~90 runs).
function forgeSculptRuns(ids, count, gap, maxRuns) {
  const s = ids.subarray(0, count).sort();
  const runs = [];
  if (!count) return runs;
  let g = gap;
  for (;;) {
    runs.length = 0;
    let a = s[0], b = s[0];
    for (let i = 1; i < count; i++) { const v = s[i]; if (v - b <= g) { b = v; continue; } runs.push(a, b); a = b = v; }
    runs.push(a, b);
    if (runs.length / 2 <= maxRuns) return runs;
    g *= 4;   // too many ranges (each one is a bufferSubData call): merge across bigger gaps
  }
}
// six looks, one job each (icons/matcaps in vendor/sculpt/matcaps, drawn procedurally by native/sculpt/tools/gen_matcaps.py)
const FORGE_MATCAPS = [
  ["clay_gray", "Clay Gray", "Neutral clay: read the big forms."],
  ["red_wax", "Red Wax", "Soft warm wax: the classic sculpting look."],
  ["skin", "Skin", "Warm skin with a little glow: faces and creatures."],
  ["toy_plastic", "Toy Plastic", "Glossy: the highlight shows every ripple in the surface."],
  ["chrome", "Chrome", "Reflections expose bumps and dents."],
  ["high_contrast", "High Contrast", "Strong light and rim: silhouette and depth."],
];

const ForgeSculpt = {
  worker: null, ok: false, failed: "", loadedSm: null, shadow: null, w2r: null,
  library: [], libraryByName: {}, dyn: { on: false, detail: 0.12, mode: "brush", px: 8 }, busy: false,
  pressed: false, last: null, pressAt: null, hover: undefined, hoverSeq: 0,
  stats: { loads: 0, dabs: 0, updates: 0, uploadBytes: 0, uploadRanges: 0, engineMs: 0, flushes: 0 },
  // stroke feel: stabiliser string (px), pen-pressure smoothing; per-brush overrides (0 / "" = the brush's own)
  strokeOpts: { lazy: 10, pressureSmooth: 0.5 }, over: { autoSmooth: 0, falloff: "" }, spacing: 0.1, stroke: null, rawBuf: null,

  start() {
    if (this.worker || this.failed) return;
    if (typeof Worker !== "function" || typeof WebAssembly !== "object") { this.failed = "no Worker / WebAssembly"; return; }
    try {
      this.worker = new Worker(FORGE_SCULPT_BASE + "sculpt_worker.js");
    } catch (exc) { this.failed = String(exc); return; }
    this.worker.onmessage = (ev) => this.onMessage(ev.data);
    this.worker.onerror = (ev) => { this.failed = ev.message || "worker error"; this.ok = false; console.warn("forge sculpt:", this.failed); };
    fetch(FORGE_SCULPT_BASE + "brushes.json").then((r) => r.json()).then((lib) => {
      this.library = (lib.brushes || []).filter((b) => b.kernel !== "Mask" && b.kernel !== "Paint" && b.kernel !== "HistoryRecall" && b.kernel !== "Morph");
      for (const b of this.library) this.libraryByName[b.name] = b;
      this.categories = (lib.categories || []).filter((c) => this.library.some((b) => b.category === c));
      forgeSculptFillLibrary();
    }).catch(() => {});
  },

  /** The engine takes strokes for this view (loaded, not switched off). */
  ready(view) {
    if (!this.worker && !this.failed) this.start();
    return this.ok && !!view && !!view.sm && view.brush.engine !== false && !!view.internals;
  },

  onMessage(m) {
    const view = forge.view;
    switch (m.t) {
      case "ready": this.ok = true; break;
      case "fail": console.warn("forge sculpt:", m.error, m.during || ""); if (!m.during) { this.failed = m.error; this.ok = false; } break;
      case "loaded": this.stats.loads++; this.stats.loadMs = Math.round(m.ms); break;
      case "dirty": if (view && view.sm === this.loadedSm) this.applyDirty(view, m); break;
      case "topology": if (view) this.applyTopology(view, m); break;
      case "hit": if (m.seq === this.hoverSeq) this.hover = m.point ? m : null; break;
      case "released": {
        this.openStrokes = Math.max(0, (this.openStrokes || 1) - 1);
        if (view && view.internals) { const g = view.internals.mesh && view.internals.mesh.geometry; if (g) { g.computeBoundingSphere(); g.computeBoundingBox(); } }
        if (view && m.kind === 1 && view.sculptStrokeEnd && !this.pressed) view.sculptStrokeEnd();
        if (view && view.onChange) view.onChange();
        break;
      }
      case "done": {
        this.busy = false;
        forgeSculptLevels(m.levels, m.level);
        if (typeof forgeSay === "function") forgeSay(m.ok ? forgeSculptOpName(m.name) + ": " + (m.verts || 0).toLocaleString() + " vertices (" + Math.round(m.ms) + " ms)" : forgeSculptOpName(m.name) + " did not work on this mesh.", !m.ok);
        break;
      }
      default: break;
    }
  },

  // ---- keeping the engine's mesh and Forge's view.sm the same
  sync(view) {
    const sm = view.sm;
    if (sm !== this.loadedSm) {
      const idx = new Int32Array(sm.idx.length);
      for (let i = 0; i < idx.length; i++) idx[i] = sm.wid[sm.idx[i]];
      const pos = sm.wpos.slice();
      this.worker.postMessage({ t: "load", pos, idx }, [pos.buffer, idx.buffer]);
      this.loadedSm = sm; this.shadow = sm.wpos.slice(); this.w2r = forgeSculptReverse(sm);
      this.hover = undefined;
      return;
    }
    // Forge's undo / transform tools move vertices in place: send the engine the positions it does not know
    const a = sm.wpos, b = this.shadow;
    let same = a.length === b.length;
    for (let i = 0; same && i < a.length; i++) if (a[i] !== b[i]) same = false;
    if (!same) { this.shadow = a.slice(); const pos = a.slice(); this.worker.postMessage({ t: "setPositions", pos }, [pos.buffer]); }
  },

  preset(view) {
    const b = view.brush;
    if (b.lib && this.libraryByName[b.lib] && b.tool === "lib") return this.libraryByName[b.lib];
    return FORGE_SCULPT_MAP[b.tool] || FORGE_SCULPT_MAP.draw;
  },
  /** The preset the engine gets: the brush's own, with the panel's Auto smooth / Falloff overrides on top. */
  effectivePreset(view) {
    const p = Object.assign({}, this.preset(view));
    if (this.over.autoSmooth > 0) p.autoSmooth = this.over.autoSmooth;
    if (this.over.falloff) { p.falloff = this.over.falloff; delete p.falloffPoints; }
    return p;
  },
  /** Dynamic detail for the engine. "screen": the detail is N pixels on screen at the press point (zoom in = finer),
   *  turned into an edge length in the model's units; "brush": a fraction of the brush radius (as before). */
  dynFor(view, atLocal) {
    const d = this.dyn;
    if (d.mode !== "screen" || !view.internals) return { on: d.on, detail: d.detail };
    const unitsPerPx = this.radius(view) / Math.max(1e-6, this.radiusPx(view, atLocal));
    return { on: d.on, detail: d.detail, relative: false, constant: Math.max(1e-5, (d.px || 8) * unitsPerPx) };
  },

  // ---- rays in the model's own space (the engine works on untransformed vertices)
  ray(view, x, y) {
    const I = view.internals, THREE = I.THREE, r = I.canvas.getBoundingClientRect();
    I.raycaster.setFromCamera(new THREE.Vector2(((x - r.left) / r.width) * 2 - 1, -((y - r.top) / r.height) * 2 + 1), I.camera);
    I.holder.updateMatrixWorld();
    const inv = I.holder.matrixWorld.clone().invert();
    const o = I.raycaster.ray.origin.clone().applyMatrix4(inv);
    const d = I.raycaster.ray.direction.clone().transformDirection(inv);
    return { origin: [o.x, o.y, o.z], dir: [d.x, d.y, d.z] };
  },
  radius(view) { return view.brush.radius * view.size; },
  radiusPx(view, atLocal) {   // the brush radius on screen, at the last hit
    const I = view.internals, THREE = I.THREE;
    const p = atLocal ? I.holder.localToWorld(new THREE.Vector3(atLocal[0], atLocal[1], atLocal[2])) : I.holder.getWorldPosition(new THREE.Vector3());
    const dist = Math.max(1e-6, I.camera.position.distanceTo(p));
    const R = this.radius(view) * I.holder.getWorldScale(new THREE.Vector3()).x;
    return R / (2 * dist * Math.tan(I.camera.fov * Math.PI / 360)) * (I.canvas.clientHeight || 600);
  },

  /** pointerdown on the model in Sculpt mode: true when the engine took the stroke. */
  press(view, e) {
    if (!this.ready(view)) return false;
    this.sync(view);
    const preset = this.effectivePreset(view);
    const at = this.hover && this.hover.point;
    this.worker.postMessage({ t: "brush", preset, strength: view.brush.strength, symmetry: view.brush.symBits | 0,
      radial: view.brush.radial | 0, radialAxis: view.brush.radialAxis | 0, dyn: this.dynFor(view, at) });
    // the sticky Invert / Smooth toggles of the sculpt UI (forge_sculpt_ui.js) act as if Ctrl / Shift were held
    const st = (window.forgeSculptUI && forgeSculptUI.sticky) || {};
    const sh = e.shiftKey || !!st.smooth, ct = e.ctrlKey || e.metaKey || !!st.invert;
    const mods = sh && ct ? 3 : sh ? 2 : ct ? 1 : 0;
    const pressure = e.pointerType === "pen" && e.pressure > 0 ? e.pressure : 1;
    // Tube (curve) and Insert Mesh presets add geometry instead of sculpting (Shift / Ctrl still sculpt)
    this.mode = mods === 0 && (preset.mode === "curve" || preset.mode === "insert") ? preset.mode : "";
    this.grab = /^(Move|MoveElastic|MoveInfiniteDepth|MoveTopological|SnakeHook|Nudge|Rotate|ElasticTwist|ElasticScale|Pose|Thumb|Cloth)$/.test(preset.kernel || "") && mods !== 2 && !this.mode;
    // dabs a fixed fraction of the radius apart: the preset's spacing, the same number the engine scales each dab's
    // height by (brush.cpp), so a stroke builds the same height whatever the spacing (was a fixed 0.12 here)
    this.spacing = preset.spacing > 0 ? Math.min(1, preset.spacing) : 0.1;
    this.last = { x: e.clientX, y: e.clientY };
    this.pressAt = { x: e.clientX, y: e.clientY, a0: null };
    this.stroke = ForgeStroke.start(e.clientX, e.clientY, pressure, { lazy: this.grab || this.mode ? 0 : this.strokeOpts.lazy, pressureSmooth: this.strokeOpts.pressureSmooth });
    this.pressed = true;
    // the history step (forge_scene.js) is recorded when the worker has sent the stroke's last vertices, not on the
    // pointer's release (they arrive a moment later)
    view.stroked = false;
    const radius = this.radius(view), msg = { t: "press", ray: this.ray(view, e.clientX, e.clientY), pressure, radius, mods };
    if (this.mode === "curve") {
      const tb = preset.tube || {};
      msg.mode = "curve";
      msg.tube = { radius: radius * (tb.scale || 0.35), sides: tb.sides || 12, taperStart: tb.taperStart || 0, taperEnd: tb.taperEnd || 0 };
    } else if (this.mode === "insert") {
      msg.mode = "insert";
      msg.insert = { kind: preset.insertKind === "cube" || preset.insertKind === 1 ? 1 : 0, depth: preset.insertDepth == null ? 0.3 : preset.insertDepth };
    }
    this.worker.postMessage(msg);
    this.stats.dabs++;
    return true;
  },

  drag(view, e) {
    if (!this.pressed) return;
    const radius = this.radius(view), pressure = e.pointerType === "pen" && e.pressure > 0 ? e.pressure : 1;
    if (this.grab) {
      let angle = 0;   // Rotate: the sweep around the press point, from the first direction past a small dead zone
      const dx = e.clientX - this.pressAt.x, dy = e.clientY - this.pressAt.y;
      if (Math.hypot(dx, dy) > 6) { const a = Math.atan2(dy, dx); if (this.pressAt.a0 == null) this.pressAt.a0 = a; angle = a - this.pressAt.a0; }
      this.worker.postMessage({ t: "drag", rays: [this.ray(view, e.clientX, e.clientY)], pressure, radius, angle });
      return;
    }
    if (this.mode === "insert") return;   // placed at the press
    // dabs spaced along the brush's path (spacing x radius on screen), each with its own ray and pressure. Every
    // pointer sample the browser coalesced into this event is used (a fast stroke at 60 fps otherwise gives the
    // stroke straight segments between frames), through the stabiliser.
    const step = Math.max(1, this.spacing * this.radiusPx(view, this.hover && this.hover.point));
    const evs = typeof e.getCoalescedEvents === "function" ? e.getCoalescedEvents() : null;
    const samples = evs && evs.length ? evs : [e], rays = [], pressures = [];
    for (const s of samples) {
      const p = s.pointerType === "pen" && s.pressure > 0 ? s.pressure : pressure;
      for (const d of ForgeStroke.feed(this.stroke, s.clientX, s.clientY, p, step)) {
        if (rays.length >= 128) break;
        rays.push(this.ray(view, d.x, d.y)); pressures.push(d.p);
      }
    }
    this.last = { x: this.stroke.bx, y: this.stroke.by };
    if (rays.length) {
      this.worker.postMessage({ t: "drag", rays, pressure: pressures[pressures.length - 1], pressures, radius, angle: 0 });
      this.stats.dabs += rays.length;
    }
    this.askHover(view, e);
  },

  release() { if (this.pressed && this.worker) { this.pressed = false; this.openStrokes = (this.openStrokes || 0) + 1; this.worker.postMessage({ t: "release" }); } },

  /** Hover picking through the engine's BVH (forge.js hitAt): the answer of the previous request, a new one sent. */
  hit(view, e) {
    if (e.type !== "pointermove" || view.sm !== this.loadedSm || !this.ready(view)) return undefined;
    this.askHover(view, e);
    if (this.hover === undefined) return undefined;
    if (!this.hover) return null;
    const THREE = view.internals.THREE, p = this.hover.point;
    return { point: new THREE.Vector3(p[0], p[1], p[2]), tri: -1, normal: this.hover.normal };
  },
  askHover(view, e) { this.worker.postMessage({ t: "hit", seq: ++this.hoverSeq, ray: this.ray(view, e.clientX, e.clientY) }); },

  // ---- engine -> Forge's buffers
  applyDirty(view, m) {
    const sm = view.sm, { ids, pos, nrm } = m, w2r = this.w2r;
    let lo = Infinity, hi = -1, nRaw = 0;
    if (!this.rawBuf || this.rawBuf.length < sm.n) this.rawBuf = new Int32Array(sm.n);
    const raw = this.rawBuf;
    for (let i = 0; i < ids.length; i++) {
      const w = ids[i], j = i * 3, k = w * 3;
      sm.wpos[k] = pos[j]; sm.wpos[k + 1] = pos[j + 1]; sm.wpos[k + 2] = pos[j + 2];
      this.shadow[k] = pos[j]; this.shadow[k + 1] = pos[j + 1]; this.shadow[k + 2] = pos[j + 2];
      sm.wnrm[k] = nrm[j]; sm.wnrm[k + 1] = nrm[j + 1]; sm.wnrm[k + 2] = nrm[j + 2];
      for (let q = w2r.start[w]; q < w2r.start[w + 1]; q++) {
        const r = w2r.raw[q], rr = r * 3;
        sm.pos[rr] = pos[j]; sm.pos[rr + 1] = pos[j + 1]; sm.pos[rr + 2] = pos[j + 2];
        sm.nrm[rr] = nrm[j]; sm.nrm[rr + 1] = nrm[j + 1]; sm.nrm[rr + 2] = nrm[j + 2];
        if (r < lo) lo = r; if (r > hi) hi = r;
        if (nRaw < raw.length) raw[nRaw++] = r;
      }
    }
    const mesh = view.internals.mesh;
    if (mesh && hi >= 0) {
      // only the runs of vertices that changed go to the GPU (forgeSculptRuns); ranges from earlier messages that
      // have not been drawn yet are kept: three.js clears them itself once uploaded (clearing them here, as before,
      // dropped a dab's vertices whenever two replies arrived between frames)
      const runs = forgeSculptRuns(raw, nRaw, 64, 256);
      let verts = 0;
      for (let i = 0; i < runs.length; i += 2) verts += runs[i + 1] - runs[i] + 1;
      for (const name of ["position", "normal"]) {
        const a = mesh.geometry.attributes[name];
        if (a.addUpdateRange) {
          if (a.updateRanges && a.updateRanges.length > 4096 && a.clearUpdateRanges) a.clearUpdateRanges();   // long unrendered: upload it all
          else for (let i = 0; i < runs.length; i += 2) a.addUpdateRange(runs[i] * 3, (runs[i + 1] - runs[i] + 1) * 3);
        }
        a.needsUpdate = true;
      }
      this.stats.uploadBytes += verts * 24; this.stats.uploadRanges += runs.length / 2;
      this.stats.spanBytes = (this.stats.spanBytes || 0) + (hi - lo + 1) * 24;   // what one lo..hi range would have sent
      view.dirty = true;
    }
    if (m.ms != null) { this.stats.engineMs += m.ms; this.stats.flushes++; }
    this.stats.updates++;
  },

  applyTopology(view, m) {
    const n = m.pos.length / 3, given = new Int32Array(n);
    for (let i = 0; i < n; i++) given[i] = i;
    const sm = forgeMeshFrom(m.pos, null, null, m.idx, given);   // engine vertices are already welded
    sm.nrm.set(m.nrm); sm.wnrm.set(m.nrm);
    if (!m.stroke || !this.pressed) { if (view.poly) { view.poly = null; view.tri2face = null; if (view.select) view.select([]); } }
    if (m.op && view.internals.snapshot) view.internals.snapshot();   // a remesh / level change is one undo step
    view.internals.useMesh(sm, true);
    this.loadedSm = sm; this.shadow = sm.wpos.slice(); this.w2r = forgeSculptReverse(sm);
    if (m.levels != null) forgeSculptLevels(m.levels, m.level);
    if (view.onChange) view.onChange();
  },

  op(name, arg) {
    const view = forge.view;
    if (!this.ready(view)) { if (typeof forgeSay === "function") forgeSay(this.failed ? "The sculpting engine is not available here (" + this.failed + ")." : "The sculpting engine is still loading.", true); return; }
    if (this.busy) return;
    this.sync(view);
    this.busy = true;
    if (typeof forgeSay === "function") forgeSay(forgeSculptOpName(name) + "...");
    this.worker.postMessage({ t: "op", name, arg });
  },
};
window.ForgeSculpt = ForgeSculpt;

function forgeSculptOpName(name) {
  return { voxelRemesh: "Remesh", quadRemesh: "Quad remesh", decimate: "Reduce", divide: "Divide", setLevel: "Level", smoothAll: "Relax" }[name] || name;
}

// welded vertex -> every raw (GPU) vertex that shows it (UV seams split one welded vertex into several)
function forgeSculptReverse(sm) {
  const start = new Int32Array(sm.wn + 1);
  for (let i = 0; i < sm.n; i++) start[sm.wid[i] + 1]++;
  for (let w = 0; w < sm.wn; w++) start[w + 1] += start[w];
  const fill = start.slice(0, sm.wn), raw = new Int32Array(sm.n);
  for (let i = 0; i < sm.n; i++) raw[fill[sm.wid[i]]++] = i;
  return { start, raw };
}

// ------------------------------------------------------------------------------------------ matcaps
function forgeSetMatcap(id) {
  const view = forge.view;
  try { localStorage.setItem("loki-forge-matcap", id || ""); } catch (exc) { /* private window */ }
  for (const b of document.querySelectorAll("#forge [data-matcap]")) b.classList.toggle("on", b.dataset.matcap === (id || ""));
  if (!view || !view.internals) return;
  const THREE = view.internals.THREE;
  if (!id) { view.matcapMat = null; view.internals.applyLook(); return; }
  new THREE.TextureLoader().load(FORGE_SCULPT_BASE + "matcaps/" + id + ".png", (tex) => {
    tex.colorSpace = THREE.SRGBColorSpace;
    if (view.matcapMat) { view.matcapMat.matcap.dispose(); view.matcapMat.matcap = tex; view.matcapMat.needsUpdate = true; }
    else view.matcapMat = new THREE.MeshMatcapMaterial({ matcap: tex });
    view.internals.applyLook();
  });
}
function forgeCycleMatcap(step) {
  let cur = "";
  try { cur = localStorage.getItem("loki-forge-matcap") || ""; } catch (exc) { /* ignore */ }
  const ids = [""].concat(FORGE_MATCAPS.map((m) => m[0]));
  const next = ids[(ids.indexOf(cur) + step + ids.length) % ids.length];
  forgeSetMatcap(next);
  if (typeof forgeSay === "function") forgeSay("Look: " + (next ? FORGE_MATCAPS.find((m) => m[0] === next)[1] : "lit (no matcap)"));
}

// ------------------------------------------------------------------------------------------ the sculpt bar
function forgeSculptFillLibrary() {
  const sel = document.getElementById("forge-sculpt-lib");
  if (!sel || sel.dataset.filled || !ForgeSculpt.library.length) return;
  sel.dataset.filled = "1";
  for (const cat of ForgeSculpt.categories) {
    const g = document.createElement("optgroup"); g.label = cat;
    for (const b of ForgeSculpt.library.filter((x) => x.category === cat)) {
      const o = document.createElement("option"); o.value = b.name; o.textContent = b.name; g.append(o);
    }
    sel.append(g);
  }
}

function forgeSculptLevels(count, level) {
  const t = document.getElementById("forge-sculpt-level");
  if (t) t.textContent = count > 1 ? "Level " + level + " / " + (count - 1) : "";
}

// the stroke settings are the artist's, not the model's: kept between sessions
function forgeSculptLoadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem("loki-forge-stroke") || "null");
    if (!p) return;
    if (typeof p.lazy === "number") ForgeSculpt.strokeOpts.lazy = Math.max(0, Math.min(40, p.lazy));
    if (typeof p.autoSmooth === "number") ForgeSculpt.over.autoSmooth = Math.max(0, Math.min(0.6, p.autoSmooth));
    if (typeof p.falloff === "string" && (!p.falloff || FORGE_SCULPT_FALLOFFS.includes(p.falloff))) ForgeSculpt.over.falloff = p.falloff;
    if (p.dynMode === "screen" || p.dynMode === "brush") ForgeSculpt.dyn.mode = p.dynMode;
  } catch (exc) { /* private window / bad value: defaults */ }
}
function forgeSculptSavePrefs() {
  try {
    localStorage.setItem("loki-forge-stroke", JSON.stringify({ lazy: ForgeSculpt.strokeOpts.lazy, autoSmooth: ForgeSculpt.over.autoSmooth,
      falloff: ForgeSculpt.over.falloff, dynMode: ForgeSculpt.dyn.mode }));
  } catch (exc) { /* private window */ }
}

function forgeSculptDecorate() {
  const bar = document.getElementById("forge-sculpt");
  if (!bar || bar.dataset.engine) return;
  bar.dataset.engine = "1";
  forgeSculptLoadPrefs();
  ForgeSculpt.start();
  // its own floating panel beside the brush column, shown whenever the sculpt bar is
  const row = el("div", "forge-float forge-enginebar"); row.id = "forge-sculpt-engine";
  row.hidden = bar.hidden;
  new MutationObserver(() => { row.hidden = bar.hidden; }).observe(bar, { attributes: true, attributeFilter: ["hidden"] });
  // every brush of the library (one list, grouped); picking one overrides the seven buttons until one is clicked
  const lib = document.createElement("select");
  lib.id = "forge-sculpt-lib"; lib.className = "forge-sculpt-lib";
  lib.setAttribute("aria-label", "Brushes"); lib.dataset.tipName = "Brushes"; lib.dataset.tipWhat = "Every brush of the sculpting engine: clay, hard surface, detail, move, smooth, cloth ...";
  const first = document.createElement("option"); first.value = ""; first.textContent = "More brushes..."; lib.append(first);
  lib.addEventListener("change", () => {
    if (!forge.view || !lib.value) return;
    forge.view.brush.tool = "lib"; forge.view.brush.lib = lib.value;
    for (const b of document.querySelectorAll("#forge [data-brush]")) b.classList.remove("on");
    if (typeof forgeSay === "function") forgeSay("Brush: " + lib.value);
  });
  const dyn = forgeBtn("sparkle", "Dynamic detail", "Dynamic detail: the brush adds triangles where it works and removes them where it smooths, so detail goes exactly where you sculpt.", (e) => {
    ForgeSculpt.dyn.on = !ForgeSculpt.dyn.on; e.currentTarget.classList.toggle("on", ForgeSculpt.dyn.on);
    if (typeof forgeSay === "function") forgeSay(ForgeSculpt.dyn.on ? "Dynamic detail on (smaller brush = finer triangles)." : "Dynamic detail off.");
  });
  dyn.id = "forge-sculpt-dyn";
  const detail = forgeSlider("Detail", "forge-sculpt-detail", 0.04, 0.4, 0.12, (v) => {
    ForgeSculpt.dyn.detail = 0.44 - v;
    ForgeSculpt.dyn.px = Math.round(20 - (v - 0.04) / 0.36 * 18);   // screen detail: 20 px (left) .. 2 px (right)
  });
  detail.dataset.tipName = "Detail"; detail.dataset.tipWhat = "How fine dynamic detail makes the triangles (right = finer).";
  const screenDetail = forgeBtn("frame", "Screen detail", "Detail by screen size: triangles are a few pixels on screen wherever you sculpt, so zooming in adds finer detail (off: a fraction of the brush size).", (e) => {
    ForgeSculpt.dyn.mode = ForgeSculpt.dyn.mode === "screen" ? "brush" : "screen";
    e.currentTarget.classList.toggle("on", ForgeSculpt.dyn.mode === "screen");
    forgeSculptSavePrefs();
    if (typeof forgeSay === "function") forgeSay(ForgeSculpt.dyn.mode === "screen" ? "Detail by screen size: zoom in for finer triangles." : "Detail by brush size.");
  });
  screenDetail.id = "forge-sculpt-screendetail";
  // the stroke: stabiliser, auto-smooth and falloff overrides for every brush
  const lazy = forgeSlider("Stabilize", "forge-sculpt-lazy", 0, 1, ForgeSculpt.strokeOpts.lazy / 40, (v) => { ForgeSculpt.strokeOpts.lazy = Math.round(v * 40); forgeSculptSavePrefs(); });
  lazy.dataset.tipName = "Stabilize"; lazy.dataset.tipWhat = "Lazy mouse: the brush trails the cursor on a short string, so shaky hands draw smooth lines (0 = off).";
  const autoS = forgeSlider("Auto smooth", "forge-sculpt-autosmooth", 0, 0.6, ForgeSculpt.over.autoSmooth, (v) => { ForgeSculpt.over.autoSmooth = v; forgeSculptSavePrefs(); });
  autoS.dataset.tipName = "Auto smooth"; autoS.dataset.tipWhat = "Smooth a little after every dab, inside the brush's falloff (0 = the brush's own setting).";
  const fall = document.createElement("select");
  fall.id = "forge-sculpt-falloff"; fall.className = "forge-sculpt-lib";
  fall.setAttribute("aria-label", "Falloff"); fall.dataset.tipName = "Falloff"; fall.dataset.tipWhat = "The brush's profile from centre to edge: Smooth (soft edge), Sphere (round, full), Root (pointy), Sharp, Linear, Constant (flat).";
  for (const f of [""].concat(FORGE_SCULPT_FALLOFFS)) { const o = document.createElement("option"); o.value = f; o.textContent = f ? "Falloff: " + f : "Falloff: the brush's own"; fall.append(o); }
  fall.value = ForgeSculpt.over.falloff || "";
  fall.addEventListener("change", () => { ForgeSculpt.over.falloff = fall.value; forgeSculptSavePrefs(); });
  const remesh = forgeBtn("cube", "Remesh", "Remesh: rebuild the model as one even, closed surface (voxels) - merges overlapping parts and evens out stretched areas.", () => {
    const res = +(document.getElementById("forge-sculpt-res") || { value: 128 }).value || 128;
    ForgeSculpt.op("voxelRemesh", res);
  });
  const res = forgeSlider("Resolution", "forge-sculpt-res", 32, 400, 128, () => {});
  res.querySelector("input").step = "8";
  res.dataset.tipName = "Resolution"; res.dataset.tipWhat = "Remesh resolution: voxels across the model (more = more detail kept).";
  const quad = forgeBtn("grid", "Quad remesh", "Quad remesh: clean, flowing quads that follow the shape - for animation, subdivision levels and export.", () => ForgeSculpt.op("quadRemesh", 4000));
  // Reduce (C++ decimation, meshoptimizer's quadric simplifier in the engine): fewer triangles, same shape - for
  // export, games and a lighter scene; colour kept, masked areas never move, open edges stay
  const reduce = forgeBtn("compress", "Reduce", "Reduce (decimate): keep the shape with far fewer triangles - for export, games and a lighter scene. Painted colour stays, masked areas are left alone, open edges stay put.", () => {
    const pct = +(document.getElementById("forge-sculpt-reduce") || { value: 50 }).value || 50;
    ForgeSculpt.op("decimate", { percent: pct, lockBorder: true });
  });
  reduce.id = "forge-sculpt-reduce-btn";
  const reducePct = forgeSlider("Keep %", "forge-sculpt-reduce", 2, 95, 50, () => {});
  reducePct.dataset.tipName = "Keep %"; reducePct.dataset.tipWhat = "Reduce keeps about this many percent of the triangles.";
  const divide = forgeBtn("subdivide", "Divide", "Add a subdivision level (4x the faces); the lower levels keep the big forms and detail rides along.", () => ForgeSculpt.op("divide"));
  const lower = forgeBtn("chevron", "Lower level", "Step down a subdivision level to move big forms (detail comes back when you go up).", () => {
    const t = (document.getElementById("forge-sculpt-level") || {}).textContent || "";
    const m = /Level (\d+)/.exec(t); if (m && +m[1] > 0) ForgeSculpt.op("setLevel", +m[1] - 1);
  });
  lower.classList.add("forge-flip");
  const higher = forgeBtn("chevron", "Higher level", "Step up a subdivision level (the detail you sculpted there comes back).", () => {
    const t = (document.getElementById("forge-sculpt-level") || {}).textContent || "";
    const m = /Level (\d+) \/ (\d+)/.exec(t); if (m && +m[1] < +m[2]) ForgeSculpt.op("setLevel", +m[1] + 1);
  });
  const level = el("span", "forge-sculpt-level", ""); level.id = "forge-sculpt-level";
  // matcap gallery
  const caps = el("div", "forge-matcaps");
  const off = el("button", "mini forge-matcap", "Lit"); off.type = "button"; off.dataset.matcap = "";
  off.dataset.tipName = "Lit"; off.dataset.tipWhat = "The normal lit look (no matcap)."; off.addEventListener("click", () => forgeSetMatcap(""));
  caps.append(off);
  for (const [id, name, what] of FORGE_MATCAPS) {
    const b = el("button", "mini forge-matcap", ""); b.type = "button"; b.dataset.matcap = id;
    b.dataset.tipName = name; b.dataset.tipWhat = what; b.setAttribute("aria-label", name);
    const img = document.createElement("img"); img.src = FORGE_SCULPT_BASE + "matcaps/" + id + "_thumb.png"; img.alt = "";
    b.append(img); b.addEventListener("click", () => forgeSetMatcap(id)); caps.append(b);
  }
  const topo = el("div", "forge-engine-row"), levels = el("div", "forge-engine-row");
  topo.append(dyn, screenDetail, remesh, quad, reduce); levels.append(divide, lower, higher, level);
  screenDetail.classList.toggle("on", ForgeSculpt.dyn.mode === "screen");
  row.append(el("span", "forge-engine-title", "Sculpting"), lib, topo, detail, res, reducePct, levels,
    el("span", "forge-engine-title", "Stroke"), lazy, autoS, fall, el("span", "forge-engine-title", "Look"), caps);
  bar.parentNode.append(row);
  // always below the view bar (it wraps onto more rows on a small screen) and beside the brush column
  const stage = bar.parentNode, place = () => {
    const vb = stage.querySelector(".forge-viewbar"), st = stage.getBoundingClientRect();
    const vr = vb && vb.offsetParent ? vb.getBoundingClientRect() : null;
    const top = Math.max(56, vr ? Math.round(vr.bottom - st.top + 6) : 56);
    const br = !bar.hidden ? bar.getBoundingClientRect() : null;
    const left = Math.max(64, br && br.width ? Math.round(br.right - st.left + 6) : 64);
    row.style.top = top + "px"; row.style.left = left + "px"; row.style.maxHeight = "calc(100% - " + (top + 60) + "px)";
  };
  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(place);
    ro.observe(stage);
    const vb = stage.querySelector(".forge-viewbar");   // the view bar wraps onto a 2nd row on a small window: follow it
    if (vb) ro.observe(vb);
  }
  new MutationObserver(place).observe(bar, { attributes: true, attributeFilter: ["hidden"] });
  place();
  forgeSculptFillLibrary();
  let saved = "";
  try { saved = localStorage.getItem("loki-forge-matcap") || ""; } catch (exc) { /* ignore */ }
  for (const b of caps.querySelectorAll("[data-matcap]")) b.classList.toggle("on", b.dataset.matcap === saved);
  if (saved) setTimeout(() => forgeSetMatcap(saved), 0);
}

document.addEventListener("DOMContentLoaded", () => {
  // the sculpt bar is built when Forge opens: decorate it the moment it exists
  const watch = new MutationObserver(() => { if (document.getElementById("forge-sculpt")) forgeSculptDecorate(); });
  watch.observe(document.body, { childList: true, subtree: true });
  forgeSculptDecorate();
});
