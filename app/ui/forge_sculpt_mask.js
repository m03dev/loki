// Forge sculpt masking + hiding (owner 2026-10-21 22:13: "add those sculpting features" - masking, hide / isolate).
// The C++ engine keeps a mask per vertex (0 free .. 1 frozen; masked vertices never move under a brush). Ctrl+Shift+drag
// paints it (the engine's mode 3; with the Mask toggle on a plain drag paints and Ctrl+drag paints it away - mode 4), the Mask buttons / keys clear, invert or fill it. This file draws it: a dark overlay on
// the sculpt mesh, sharing its vertex buffers (no copy), so it follows every stroke. Hide masked takes the fully masked
// triangles off the screen (they are frozen too, so nothing can change them unseen); Show all brings them back.
"use strict";

const ForgeMask = {
  w: null,          // the mask per engine (welded) vertex
  overlay: null,
  hidden: false,
  any: false,

  // the raw (GPU) vertices of welded vertex w: ForgeSculpt.w2r
  _raw(cb) {
    const S = window.ForgeSculpt, view = typeof forge !== "undefined" ? forge.view : null;
    const mesh = view && view.internals && view.internals.mesh;
    if (!S || !S.w2r || !mesh || !mesh.geometry || !this.w) return null;
    const g = mesh.geometry, n = g.attributes.position.count;
    let a = g.attributes.mask;
    if (!a || a.count !== n) { a = new view.internals.THREE.BufferAttribute(new Float32Array(n), 1); g.setAttribute("mask", a); }
    cb(a.array, S.w2r);
    a.needsUpdate = true;
    this.ensure(view, mesh);
    view.dirty = true;
    return a;
  },
  // a whole new mask (a new mesh, or Clear / Invert / Fill)
  setAll(view, msk) {
    this.w = msk ? Float32Array.from(msk) : null;
    this.any = !!(this.w && this.w.some((x) => x > 0.01));
    this._raw((arr, w2r) => {
      for (let w = 0; w + 1 < w2r.start.length; w++) for (let q = w2r.start[w]; q < w2r.start[w + 1]; q++) arr[w2r.raw[q]] = this.w[w] || 0;
    });
    if (this.hidden) this.hide(true);
    this.sync();
  },
  // some vertices changed (a stroke)
  setSome(view, ids, msk) {
    if (!msk) return;
    if (!this.w) {                                   // the first mask stroke on a mesh: start from nothing masked (it
      const S = window.ForgeSculpt;                  // was dropped before, so the first stroke never showed)
      const n = S && S.w2r && S.w2r.start ? S.w2r.start.length - 1 : 0;
      if (n <= 0) return;
      this.w = new Float32Array(n);
    }
    let touched = false;
    for (let i = 0; i < ids.length; i++) { if (this.w[ids[i]] !== msk[i]) { touched = true; this.w[ids[i]] = msk[i]; } }
    if (!touched) return;
    this.any = this.any || msk.some((x) => x > 0.01);
    this._raw((arr, w2r) => {
      for (let i = 0; i < ids.length; i++) { const w = ids[i]; for (let q = w2r.start[w]; q < w2r.start[w + 1]; q++) arr[w2r.raw[q]] = msk[i]; }
    });
    this.sync();
  },
  // the overlay mesh: same position / index buffers, its own material
  ensure(view, mesh) {
    const THREE = view.internals.THREE;
    if (this.overlay && this.overlay.parent === mesh && this.overlay.geometry.attributes.position === mesh.geometry.attributes.position) {
      if (this.overlay.geometry.index !== mesh.geometry.index) this.overlay.geometry.setIndex(mesh.geometry.index);
      return;
    }
    if (this.overlay) { if (this.overlay.parent) this.overlay.parent.remove(this.overlay); this.overlay.geometry.dispose(); }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", mesh.geometry.attributes.position);
    g.setAttribute("mask", mesh.geometry.attributes.mask);
    g.setIndex(mesh.geometry.index);
    if (!this.mat) {
      this.mat = new THREE.ShaderMaterial({
        vertexShader: "attribute float mask; varying float vM; void main() { vM = mask; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
        fragmentShader: "varying float vM; void main() { if (vM < 0.02) discard; gl_FragColor = vec4(0.03, 0.04, 0.08, 0.66 * clamp(vM, 0.0, 1.0)); }",
        transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -2,
      });
    }
    this.overlay = new THREE.Mesh(g, this.mat);
    this.overlay.name = "forge-mask"; this.overlay.raycast = () => {}; this.overlay.renderOrder = 4;
    this.overlay.frustumCulled = false;
    mesh.add(this.overlay);
  },
  // Hide masked: draw only the triangles that are not fully masked
  hide(on) {
    const view = typeof forge !== "undefined" ? forge.view : null;
    const mesh = view && view.internals && view.internals.mesh;
    if (!mesh || !mesh.geometry || !mesh.geometry.index) return "Nothing to hide.";
    const g = mesh.geometry, m = g.attributes.mask;
    const full = g.userData.fullIndex || g.index;
    if (!on || !m) {
      if (g.userData.fullIndex) { g.setIndex(g.userData.fullIndex); delete g.userData.fullIndex; }
      this.hidden = false;
      if (this.overlay) this.overlay.geometry.setIndex(g.index);
      view.dirty = true;
      return "Everything shows again.";
    }
    const src = full.array, out = [];
    for (let i = 0; i < src.length; i += 3) {
      const a = m.array[src[i]], b = m.array[src[i + 1]], c = m.array[src[i + 2]];
      if (!(a > 0.5 && b > 0.5 && c > 0.5)) out.push(src[i], src[i + 1], src[i + 2]);
    }
    g.userData.fullIndex = full;
    g.setIndex(new view.internals.THREE.BufferAttribute(Uint32Array.from(out), 1));
    if (this.overlay) this.overlay.geometry.setIndex(g.index);
    this.hidden = true;
    view.dirty = true;
    return "Masked parts hidden (" + ((src.length - out.length) / 3).toLocaleString() + " triangles) - Show all brings them back.";
  },
  op(name) {
    const S = window.ForgeSculpt;
    if (!S) return "";
    if (name === "maskHide") return this.hide(true);
    if (name === "maskShow") return this.hide(false);
    if (name === "maskHideToggle") return this.hide(!this.hidden);
    S.op(name);
    return { maskClear: "Mask cleared.", maskInvert: "Mask inverted.", maskFill: "Everything masked." }[name] || "";
  },
  sync() { const b = document.querySelectorAll("#forge [data-mask-state]"); for (const e of b) e.classList.toggle("on", e.dataset.maskState === "hidden" ? this.hidden : this.any); },
};
window.ForgeMask = ForgeMask;

// the engine's messages: hook into ForgeSculpt without changing its own code paths
(function forgeMaskHook() {
  const S = window.ForgeSculpt;
  if (!S || S.maskHooked) return;
  S.maskHooked = true;
  const onMessage = S.onMessage.bind(S), applyDirty = S.applyDirty.bind(S), applyTopology = S.applyTopology.bind(S);
  S.onMessage = function (m) {
    if (m && m.t === "mask") { const view = forge.view; if (view) ForgeMask.setAll(view, m.msk); return; }
    if (m && m.t === "loaded") {                         // a fresh mesh in the engine: nothing masked or hidden yet
      const sm = S.loadedSm;
      ForgeMask.hidden = false; ForgeMask.any = false;
      ForgeMask.w = sm && sm.wpos ? new Float32Array(sm.wpos.length / 3) : (S.w2r && S.w2r.start ? new Float32Array(S.w2r.start.length - 1) : null);
      ForgeMask.sync();
    }
    return onMessage(m);
  };
  S.applyDirty = function (view, m) { applyDirty(view, m); if (m.msk) ForgeMask.setSome(view, m.ids, m.msk); };
  S.applyTopology = function (view, m) { const wasHidden = ForgeMask.hidden; ForgeMask.hidden = false; applyTopology(view, m); if (m.msk) { ForgeMask.hidden = wasHidden; ForgeMask.setAll(view, m.msk); } };
  if (S.op) {
    const op = S.op.bind(S);
    S.op = function (name, arg) {
      if (/^mask(Clear|Invert|Fill)$/.test(name)) {        // a mask edit is not a busy remesh: no "..." and no lock
        const view = forge.view;
        if (!S.ready(view)) return;
        S.sync(view);
        S.worker.postMessage({ t: "op", name, arg });
        return;
      }
      return op(name, arg);
    };
  }
})();

if (typeof FORGE_PRO_CMDS !== "undefined") {
  const C = FORGE_PRO_CMDS;
  C.maskClear = ["Clear Mask", () => ForgeMask.op("maskClear")];
  C.maskInvert = ["Invert Mask", () => ForgeMask.op("maskInvert")];
  C.maskFill = ["Mask All", () => ForgeMask.op("maskFill")];
  C.maskHide = ["Hide Masked", () => ForgeMask.op("maskHide")];
  C.maskShow = ["Show All", () => ForgeMask.op("maskShow")];
  C.maskHideToggle = ["Hide Masked / Show All", () => { const say = ForgeMask.op("maskHideToggle"); if (window.forgeSculptUI && typeof fscSync === "function") fscSync(); return say; }];
}
