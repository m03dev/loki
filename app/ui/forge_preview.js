// Forge - tool previews: while a modelling tool is armed, show what it will do *before* the click.
// The Insert Edge Loop tool draws the loop it would insert under the cursor (the same ring walk and position the
// op uses, computed on the mesh as it is, nothing committed); Offset Edge Loop draws its two loops. The tool
// state lives in forge_toolkit.js (`forgeToolkit.sel()`), the mesh in forge_edit.js (`view.poly`, `view.cutPointAt`).
// Re-implemented from the standard "preview the operation under the cursor" model.
const FORGE_PREVIEW_COLOR = 0xffc857;

function forgePreviewAttach() {
  let line = null, key = "", active = true, reason = "start";

  function view() { return typeof forge !== "undefined" && forge.view ? forge.view : null; }
  function host() { const v = view(); return v && v.holder ? v.holder : null; }

  function hide() {
    key = "";
    if (line) { if (line.parent) line.parent.remove(line); line.geometry.dispose(); line.material.dispose(); line = null; const v = view(); if (v) v.dirty = true; }
  }
  function show(segs, v) {
    const THREE = v.THREE, h = host();
    if (!h) return;
    if (!line) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(segs.length * 3), 3));
      line = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: FORGE_PREVIEW_COLOR, depthTest: false, transparent: true, opacity: 0.95 }));
      line.name = "forge-loop-preview"; line.renderOrder = 12; line.raycast = () => {};
      h.add(line);
    }
    const arr = line.geometry.attributes.position;
    if (arr.count !== segs.length) { line.geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(segs.length * 3), 3)); }
    const a = line.geometry.attributes.position;
    for (let i = 0; i < segs.length; i++) { a.setXYZ(i, segs[i][0], segs[i][1], segs[i][2]); }
    a.needsUpdate = true;
    line.geometry.computeBoundingSphere();
    v.dirty = true;
  }

  // the loop an Insert Edge Loop would make: the cut point on every edge of the ring, joined across each face
  function loopSegments(v, edge, t, n) {
    const P = window.ForgePoly; if (!P || !v.poly) return null;
    const m = v.poly, T = P.topology(m), THREE = v.THREE;
    const ei = T.edge(edge[0], edge[1]);
    if (ei == null) return null;
    const ring = P.edgeRing(m, T, ei);
    if (!ring || !ring.faces.length) return null;
    const ringF = new Set(ring.faces), start = new Map([[ei, T.edges[ei].a]]), queue = [ei];
    while (queue.length) {                       // the same side-propagation the op runs
      const e = queue.shift(), s = start.get(e);
      for (const fi of T.edges[e].faces) {
        if (!ringF.has(fi)) continue;
        const f = m.f[fi], fe = T.faceEdges[fi], k = fe.indexOf(e), opp = fe[(k + 2) % 4];
        if (start.has(opp) || opp == null) continue;
        start.set(opp, s === f[k] ? f[(k + 3) % 4] : f[(k + 2) % 4]);
        queue.push(opp);
      }
    }
    const at = (e, frac) => {                    // the point `frac` along e, from the ring's start side
      const ed = T.edges[e], s = start.has(e) ? start.get(e) : ed.a, oth = s === ed.a ? ed.b : ed.a;
      const A = m.v[s], B = m.v[oth];
      return [A[0] + (B[0] - A[0]) * frac, A[1] + (B[1] - A[1]) * frac, A[2] + (B[2] - A[2]) * frac];
    };
    const fracs = n > 1 ? Array.from({ length: n }, (_, i) => (i + 1) / (n + 1)) : [t];
    const out = [];
    for (const fr of fracs) for (const fi of ring.faces) {
      const fe = T.faceEdges[fi];
      for (const j of [0, 1]) {
        const a = fe[j], b = fe[j + 2];
        if (a == null || b == null || !ring.edges.includes(a) || !ring.edges.includes(b)) continue;
        out.push(at(a, fr), at(b, fr));          // the loop passes between the face's two opposite edges
      }
    }
    return out.length ? out : null;
  }

  function update(e) {
    const v = view();
    if (!active || !v || v.mode !== "poly" || !v.poly || !v.cutPointAt || !v.canvas) { reason = active ? "no-poly-view" : "inactive"; hide(); return; }
    const tk = window.forgeToolkit && window.forgeToolkit.sel ? window.forgeToolkit.sel() : null;
    if (!tk || (tk.kind !== "insertEdgeLoop" && tk.kind !== "offsetEdgeLoop")) { reason = "no-tool"; hide(); return; }
    const r = v.canvas.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) { reason = "outside"; hide(); return; }
    const hit = v.cutPointAt([e.clientX - r.left, e.clientY - r.top]);
    if (!hit || !hit.e) { reason = "no-hit"; hide(); return; }
    const k = tk.kind + ":" + hit.e[0] + "," + hit.e[1];
    if (k === key) { reason = "same-edge"; return; }
    const live = window.forgeToolkit && window.forgeToolkit.last ? window.forgeToolkit.last() : null;
    const opts = (live && live.rec && live.rec.op === "insertEdgeLoop" && live.rec.params) || {};
    const segs = tk.kind === "offsetEdgeLoop"
      ? (() => {                                    // two loops, one either side of the hovered one
        const d = typeof opts.distance === "number" ? opts.distance : 0.25;
        return loopSegments(v, hit.e, Math.max(0.02, d), 1) && loopSegments(v, hit.e, 1 - Math.max(0.02, d), 1);
      })()
      : loopSegments(v, hit.e, typeof opts.t === "number" ? opts.t : 0.5, Math.max(1, Math.round(opts.count || 1)));
    if (!segs) { reason = "no-segments"; hide(); return; }
    key = k;
    reason = "shown";
    show(segs, v);
  }

  document.addEventListener("pointermove", (e) => { try { update(e); } catch (err) { reason = "threw: " + (err && err.message); hide(); } }, true);
  window.forgePreviewState = () => ({ reason: reason, key: key, has: !!line });
  document.addEventListener("pointerdown", () => { hide(); }, true);
  // the toolkit's own pointerdown handler stops the event for a click (it commits the op), so also clear on the
  // release - the next move redraws the preview if the tool is still armed
  document.addEventListener("pointerup", () => { reason = "pointerup"; hide(); }, true);
  window.forgePreviewHide = hide;
  window.forgePreviewLoop = loopSegments;          // Multi-Cut's Ctrl loop preview uses the same walk (forge_multicut.js)
  window.forgePreviewSetActive = (on) => { active = on !== false; if (!active) hide(); };
  return { hide: hide, active: () => active };
}
window.forgePreviewAttach = forgePreviewAttach;
