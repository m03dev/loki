// Forge's Multi-Cut, the pro tool's rules (owner 2026-10-21 12:46: "we need knife preview, different functions when
// multi cutting like showing you where it'll snap and if you press m3 it snaps to 50% just like maya ... shift cmd and
// control option should all do different things and show you different options with the tool").
//
// While the tool is on, the mouse shows what a click will do, before the click:
//   * a dot where the point will go (on a vertex, or on the edge under the mouse) and a readout beside the mouse
//     with the % along the edge;
//   * the knife: a line from the last point you placed to where the next one would go;
//   * Shift held: the point snaps to the Snap Step % (25 % by default: 25 / 50 / 75), the steps show as small dots
//     on the edge;
//   * middle-click on an edge: a point at exactly 50 %;
//   * Ctrl (Cmd on a Mac) held, before the first point: the edge loop a click would insert, across the ring of quads;
//     Ctrl+click inserts it there, Ctrl+Shift+click at the snap steps, Ctrl+middle-click in the exact middle;
//   * a click on a face (away from its edges) takes the face's nearest edge point;
//   * Backspace takes the last point back, Enter / right-click finishes, Esc cancels; Alt / Option stays the camera.
// Points are cut with ForgePoly.multiCut (forge_polyops.js) as one undo + INPUTS step, loops with insertEdgeLoop.
// Settings: Tool Settings > Snap Step % (remembered, forgeTkPref("multiCut", "snapStep")).
"use strict";

window.forgeMultiCut = (() => {
  const S = { line: null, dot: null, ticks: null, loop: null, tag: null, hover: null, last: null };
  const C = { knife: 0xffa630, dot: 0x6dff8a, vert: 0xffe066, tick: 0x111111, loop: 0xffc857, placed: 0xff3d3d };
  const view = () => (typeof forge !== "undefined" ? forge.view : null);
  const step = () => Math.max(1, Math.min(50, +(typeof forgeTkPref === "function" ? forgeTkPref("multiCut", "snapStep", 25) : 25) || 25));
  const ctrlOf = (e) => !!(e.ctrlKey || e.metaKey);

  function drop(k) {
    const o = S[k];
    if (!o) return;
    if (o.parent) o.parent.remove(o);
    if (o.geometry) o.geometry.dispose();
    if (o.material) o.material.dispose();
    S[k] = null;
  }
  function clear() {
    for (const k of ["line", "dot", "ticks", "loop"]) drop(k);
    if (S.tag) S.tag.hidden = true;
    S.hover = null;
    const v = view(); if (v) v.dirty = true;
  }
  function lines(v, key, pts, color, dashed) {
    const THREE = v.THREE;
    drop(key);
    if (!pts || pts.length < 2) return;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pts.flat()), 3));
    const m = dashed ? new THREE.LineDashedMaterial({ color, depthTest: false, transparent: true, dashSize: (v.size || 1) * 0.02, gapSize: (v.size || 1) * 0.012 })
      : new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true });
    const o = new THREE.LineSegments(g, m);
    if (dashed) o.computeLineDistances();
    o.renderOrder = 14; o.raycast = () => {}; o.name = "forge-mc-" + key;
    v.holder.add(o); S[key] = o;
  }
  function points(v, key, pts, color, size) {
    const THREE = v.THREE;
    drop(key);
    if (!pts || !pts.length) return;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pts.flat()), 3));
    const o = new THREE.Points(g, new THREE.PointsMaterial({ color, size, sizeAttenuation: false, depthTest: false, transparent: true }));
    o.renderOrder = 15; o.raycast = () => {}; o.name = "forge-mc-" + key;
    v.holder.add(o); S[key] = o;
  }
  function tag(text, x, y) {
    if (!S.tag) {
      S.tag = document.createElement("div");
      S.tag.className = "forge-mc-tag"; S.tag.id = "forge-mc-tag";
      document.body.append(S.tag);
    }
    S.tag.textContent = text;
    S.tag.style.left = Math.round(x + 16) + "px"; S.tag.style.top = Math.round(y + 14) + "px";
    S.tag.hidden = false;
  }
  const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

  // where a click with these keys would land: { kind: "point" | "loop", hit, t, why }
  function resolve(v, e, t) {
    const r = v.canvas.getBoundingClientRect(), pt = [e.clientX - r.left, e.clientY - r.top];
    let hit = v.cutPointAt ? v.cutPointAt(pt) : null;
    if (!hit) return null;
    if (hit.face != null) hit = nearestEdgeOfFace(v, hit.face, pt) || hit;
    if (hit.face != null) return { kind: "none", why: "Move onto an edge or a vertex." };
    const mid = e.button === 1 || (e.buttons & 4) !== 0;
    const snap = e.shiftKey, ctrl = ctrlOf(e);
    if (hit.e) {
      let tt = hit.t, how = Math.round(tt * 100) + "%";
      if (mid) { tt = 0.5; how = "50% (middle)"; }
      else if (snap) { const s = step() / 100; tt = Math.max(s, Math.min(1 - s, Math.round(tt / s) * s)); how = Math.round(tt * 100) + "% (snap " + step() + "%)"; }
      const pa = v.poly.v[hit.e[0]], pb = v.poly.v[hit.e[1]];
      hit = { e: hit.e, t: tt, at: lerp(pa, pb, tt) };
      if (ctrl && !t.pts.length) return { kind: "loop", hit, t: tt, why: "Edge loop " + how };
      return { kind: "point", hit, t: tt, why: "Edge " + how };
    }
    if (ctrl && !t.pts.length) return { kind: "none", why: "Edge loop: move onto an edge." };
    return { kind: "point", hit, why: "Vertex" };
  }
  // a face point: the nearest point on that face's edges, on screen
  function nearestEdgeOfFace(v, fi, pt) {
    const f = v.poly.f[fi]; if (!f || !v.camera) return null;
    const THREE = v.THREE, r = v.canvas.getBoundingClientRect(), mw = v.holder.matrixWorld;
    const proj = (p) => { const q = new THREE.Vector3(p[0], p[1], p[2]).applyMatrix4(mw).project(v.camera); return [(q.x + 1) / 2 * r.width, (1 - q.y) / 2 * r.height]; };
    let best = null, bd = Infinity;
    for (let k = 0; k < f.length; k++) {
      const a = f[k], b = f[(k + 1) % f.length], A = proj(v.poly.v[a]), B = proj(v.poly.v[b]);
      const dx = B[0] - A[0], dy = B[1] - A[1], l2 = dx * dx + dy * dy || 1;
      const t = Math.max(0.02, Math.min(0.98, ((pt[0] - A[0]) * dx + (pt[1] - A[1]) * dy) / l2));
      const d = Math.hypot(A[0] + dx * t - pt[0], A[1] + dy * t - pt[1]);
      if (d < bd) { bd = d; best = { e: [a, b], t }; }
    }
    if (!best) return null;
    best.at = lerp(v.poly.v[best.e[0]], v.poly.v[best.e[1]], best.t);
    return best;
  }
  function tickPoints(v, e) {
    const s = step() / 100, out = [], pa = v.poly.v[e[0]], pb = v.poly.v[e[1]];
    for (let x = s; x < 1 - 1e-6; x += s) out.push(lerp(pa, pb, x));
    return out;
  }

  // the preview under the mouse (pointermove, and when a modifier key goes down / up)
  function preview(e) {
    const tk = typeof forgeTk !== "undefined" ? forgeTk.tool : null, v = view();
    if (!tk || tk.kind !== "multiCut" || !v || v.mode !== "poly" || !v.poly || !v.canvas || e.altKey) { clear(); return; }
    const r = v.canvas.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) { clear(); return; }
    S.last = { clientX: e.clientX, clientY: e.clientY, shiftKey: e.shiftKey, ctrlKey: e.ctrlKey, metaKey: e.metaKey, altKey: e.altKey, buttons: e.buttons || 0, button: -1 };
    const res = resolve(v, S.last, tk);
    S.hover = res;
    if (!res || res.kind === "none") { for (const k of ["line", "dot", "ticks", "loop"]) drop(k); tag(res ? res.why : "Move onto an edge or a vertex.", e.clientX, e.clientY); v.dirty = true; return; }
    if (res.kind === "loop") {
      drop("line");
      const segs = window.forgePreviewLoop ? window.forgePreviewLoop(v, res.hit.e, res.t, 1) : null;
      lines(v, "loop", segs, C.loop);
      points(v, "dot", [res.hit.at], C.dot, 9);
      if (e.shiftKey) points(v, "ticks", tickPoints(v, res.hit.e), C.tick, 6); else drop("ticks");
      tag(segs ? res.why + " - click inserts it" : "No edge loop here (it runs across quads).", e.clientX, e.clientY);
      v.dirty = true;
      return;
    }
    drop("loop");
    const last = tk.pts[tk.pts.length - 1];
    if (last) lines(v, "line", [last.at, res.hit.at], C.knife, false); else drop("line");
    points(v, "dot", [res.hit.at], res.hit.v != null ? C.vert : C.dot, 10);
    if (res.hit.e && e.shiftKey) points(v, "ticks", tickPoints(v, res.hit.e), C.tick, 6); else drop("ticks");
    tag(res.why + (tk.pts.length ? "  ·  " + tk.pts.length + " placed" : "") + (ctrlOf(e) && tk.pts.length ? "  (Ctrl loops only before the first point)" : ""), e.clientX, e.clientY);
    v.dirty = true;
  }

  // a press while the tool is on (called by forge_toolkit.js forgeTkPointer, before selection sees it)
  function pointer(e, t) {
    const v = view();
    if (e.button === 2) { e.preventDefault(); e.stopImmediatePropagation(); clear(); forgeTkToolEnd(true); return; }
    if (e.button !== 0 && e.button !== 1) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const res = resolve(v, e, t);
    if (!res || res.kind === "none") { forgeTkSay(res ? "Multi-Cut: " + res.why : "Multi-Cut: click on an edge or a vertex.", true); return; }
    if (res.kind === "loop") {
      clear();
      const ok = forgeTkApplyOp("insertEdgeLoop", res.hit.e, { t: res.t }, "Insert Edge Loop");
      if (ok) forgeTkSay("Edge loop at " + Math.round(res.t * 100) + "% - Multi-Cut is still on.");
      return;
    }
    const last = t.pts[t.pts.length - 1];
    if (last && ((last.v != null && last.v === res.hit.v) || (last.e && res.hit.e && last.e[0] === res.hit.e[0] && last.e[1] === res.hit.e[1] && Math.abs(last.t - res.hit.t) < 1e-3))) {
      forgeTkSay("Multi-Cut: that point is already placed."); return;
    }
    t.pts.push(res.hit);
    t.marks.push(forgeTkMark(v, res.hit.at));
    forgeTkSay("Multi-Cut: " + t.pts.length + " point" + (t.pts.length === 1 ? "" : "s") + " (" + res.why + ") - Enter finishes, Backspace takes one back.");
    preview(e);
  }
  function key(e, t) {
    if (e.key === "Shift" || e.key === "Control" || e.key === "Meta") { if (S.last) setTimeout(() => preview(Object.assign({}, S.last, { shiftKey: e.shiftKey, ctrlKey: e.ctrlKey, metaKey: e.metaKey })), 0); return false; }
    if (e.key === "Backspace" && t.pts.length) {
      e.preventDefault(); e.stopImmediatePropagation();
      t.pts.pop(); const mk = t.marks.pop(); if (mk && mk.parent) mk.parent.remove(mk);
      if (S.last) preview(S.last);
      forgeTkSay("Multi-Cut: " + t.pts.length + " point" + (t.pts.length === 1 ? "" : "s") + ".");
      return true;
    }
    return false;
  }
  document.addEventListener("pointermove", (e) => { try { preview(e); } catch (_) { clear(); } }, true);
  document.addEventListener("keyup", (e) => { if ((e.key === "Shift" || e.key === "Control" || e.key === "Meta") && S.last && typeof forgeTk !== "undefined" && forgeTk.tool) preview(Object.assign({}, S.last, { shiftKey: e.shiftKey, ctrlKey: e.ctrlKey, metaKey: e.metaKey })); }, true);
  // a middle press must not start the camera / manipulator drag while cutting
  document.addEventListener("auxclick", (e) => { if (typeof forgeTk !== "undefined" && forgeTk.tool && forgeTk.tool.kind === "multiCut" && e.target && e.target.id === "forge-view") e.preventDefault(); }, true);
  return { pointer, key, clear, preview, state: S, step };
})();

// Tool Settings: Multi-Cut's Snap Step %
if (typeof FORGE_PRO_CMDS !== "undefined" && !FORGE_PRO_CMDS.multiCutStep) {
  FORGE_PRO_CMDS.multiCutStep = ["Multi-Cut Snap Step %...", () => {
    const now = forgeMultiCut.step();
    const opts = [5, 10, 20, 25, 33, 50];
    const next = opts[(opts.indexOf(now) + 1) % opts.length] || 25;
    if (typeof forgeTkPref === "function") forgeTkPref("multiCut", "snapStep", next, true);
    return "Multi-Cut Snap Step: " + next + "% (Shift while cutting).";
  }];
}
