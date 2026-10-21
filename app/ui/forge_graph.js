// Forge - the Graph Editor: the keyframe curves of the selected object on a canvas, one line per channel
// (X red, Y green, Z blue; translate solid, rotate dashed, scale dotted), a square per key, the playhead, and
// dragging a key to change its frame or value. The keys live on the scene nodes (forge_scene.js tree.api.setKey /
// setFrame / evalKeys); this is the curve view. Re-implemented from the standard curve-editor model.
function forgeGraphAttach(view) {
  const T = view && view.tree;
  if (!T || !T.api) return null;
  const api = T.api;
  const stage = (document.getElementById("forge-view") || {}).parentElement;
  if (!stage || document.getElementById("forge-graph")) return null;

  const panel = document.createElement("div");
  panel.className = "forge-float forge-graph"; panel.id = "forge-graph"; panel.hidden = true;
  const head = document.createElement("div"); head.className = "fx-head";
  const title = document.createElement("b"); title.id = "forge-graph-title"; title.textContent = "Graph Editor";
  const fit = document.createElement("button"); fit.type = "button"; fit.className = "mini forge-btn"; fit.textContent = "Frame All";
  const close = document.createElement("button"); close.type = "button"; close.className = "mini forge-btn"; close.textContent = "\u00d7";
  close.title = "Close the Graph Editor.";
  head.append(title, fit, close);
  const cv = document.createElement("canvas"); cv.id = "forge-graph-canvas"; cv.width = 380; cv.height = 210;
  const hint = document.createElement("div"); hint.className = "fx-info"; hint.textContent = "Drag a key to change its frame and value.";
  panel.append(head, cv, hint);
  stage.append(panel);

  const P = 12;                                  // padding inside the canvas
  const COL = { 0: "#e07263", 1: "#7fc27f", 2: "#7f9fe0" };     // X / Y / Z
  const STYLE = { translate: [], rotate: [6, 4], scale: [2, 3] };
  let drag = null;

  function node() { return api.active(); }
  function data() {
    const n = node();
    const out = { name: n ? n.name : "", channels: [], frames: [], values: [] };
    if (!n || !n.keys) return out;
    for (const k of Object.keys(n.keys).sort()) {
      const ks = n.keys[k] || [];
      if (!ks.length) continue;
      out.channels.push({ k: k, part: k.slice(0, -1), axis: Number(k.slice(-1)), keys: ks.map((x) => [x.f, x.v]) });
      for (const x of ks) { out.frames.push(x.f); out.values.push(x.v); }
    }
    return out;
  }
  view.graphData = data;                          // tests / scripts read the curve straight off this
  view.graphXY = (f, v) => [X(f), Y(v)];          // ...and the canvas pixel of a (frame, value)

  function bounds(d) {
    let f0 = T.time.start, f1 = T.time.end, v0 = -1, v1 = 1;
    if (d.frames.length) { f0 = Math.min(f0, ...d.frames); f1 = Math.max(f1, ...d.frames); v0 = Math.min(...d.values); v1 = Math.max(...d.values); }
    if (f1 - f0 < 1) f1 = f0 + 1;
    if (v1 - v0 < 1e-6) { v0 -= 0.5; v1 += 0.5; } else { const m = (v1 - v0) * 0.15; v0 -= m; v1 += m; }
    return { f0: f0, f1: f1, v0: v0, v1: v1 };
  }
  let B = { f0: 1, f1: 24, v0: -1, v1: 1 };
  const X = (f) => P + ((f - B.f0) / (B.f1 - B.f0)) * (cv.width - 2 * P);
  const Y = (v) => cv.height - P - ((v - B.v0) / (B.v1 - B.v0)) * (cv.height - 2 * P);
  const invX = (x) => B.f0 + ((x - P) / (cv.width - 2 * P)) * (B.f1 - B.f0);
  const invY = (y) => B.v0 + ((cv.height - P - y) / (cv.height - 2 * P)) * (B.v1 - B.v0);

  function draw() {
    const g = cv.getContext("2d");
    const d = data();
    B = bounds(d);
    g.clearRect(0, 0, cv.width, cv.height);
    g.fillStyle = "#1e2024"; g.fillRect(0, 0, cv.width, cv.height);
    g.strokeStyle = "#2c3036"; g.lineWidth = 1;
    for (let i = 0; i <= 4; i++) { const y = P + (i / 4) * (cv.height - 2 * P); g.beginPath(); g.moveTo(P, y); g.lineTo(cv.width - P, y); g.stroke(); }
    if (B.v0 < 0 && B.v1 > 0) { g.strokeStyle = "#3d434b"; g.beginPath(); g.moveTo(P, Y(0)); g.lineTo(cv.width - P, Y(0)); g.stroke(); }
    // the playhead
    const px = X(T.time.frame);
    g.strokeStyle = "#8b93a0"; g.beginPath(); g.moveTo(px, P); g.lineTo(px, cv.height - P); g.stroke();
    for (const ch of d.channels) {
      g.strokeStyle = COL[ch.axis] || "#c3cad6";
      g.setLineDash(STYLE[ch.part] || []);
      g.beginPath();
      for (let x = P; x <= cv.width - P; x++) { const v = keyValueOf(ch.keys, invX(x)); const y = Y(v); if (x === P) g.moveTo(x, y); else g.lineTo(x, y); }
      g.stroke();
      g.setLineDash([]);
      for (const [f, v] of ch.keys) {
        const sel = drag && drag.k === ch.k && drag.f === f;
        g.fillStyle = sel ? "#ffffff" : COL[ch.axis];
        g.fillRect(X(f) - 2.5, Y(v) - 2.5, 5, 5);
      }
    }
    title.textContent = d.name ? "Graph Editor - " + d.name : "Graph Editor";
  }
  function keyValueOf(keys, f) {                  // the same interpolation forge_scene.js uses for playback
    if (!keys.length) return 0;
    if (f <= keys[0][0]) return keys[0][1];
    const last = keys[keys.length - 1];
    if (f >= last[0]) return last[1];
    for (let i = 0; i < keys.length - 1; i++) {
      const a = keys[i], b = keys[i + 1];
      if (f >= a[0] && f <= b[0]) { const t = (f - a[0]) / Math.max(1e-9, b[0] - a[0]); return a[1] + (b[1] - a[1]) * t; }
    }
    return last[1];
  }

  function pick(ev) {
    const r = cv.getBoundingClientRect();
    const x = (ev.clientX - r.left) * (cv.width / r.width), y = (ev.clientY - r.top) * (cv.height / r.height);
    const d = data();
    let best = null, bd = 8 * 8;
    for (const ch of d.channels) for (const [f, v] of ch.keys) {
      const dd = (X(f) - x) ** 2 + (Y(v) - y) ** 2;
      if (dd < bd) { bd = dd; best = { k: ch.k, f: f, x: x, y: y }; }
    }
    return best;
  }
  cv.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    const hit = pick(ev);
    if (!hit) { const r = cv.getBoundingClientRect(); api.setFrame(invX((ev.clientX - r.left) * (cv.width / r.width))); draw(); return; }
    const n = node(), arr = n && n.keys && n.keys[hit.k];
    const at = arr ? arr.find((x) => x.f === hit.f) : null;
    if (!at) return;
    drag = { k: hit.k, f: hit.f, key: at, before: { f: at.f, v: at.v } };
    api.undoChunk("move key", () => { });        // a placeholder so the first move is not its own step
    view.undoOpen("move key");
    cv.setPointerCapture(ev.pointerId);
    draw();
  });
  cv.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const r = cv.getBoundingClientRect();
    const x = (ev.clientX - r.left) * (cv.width / r.width), y = (ev.clientY - r.top) * (cv.height / r.height);
    drag.key.f = Math.round(invX(x)); drag.key.v = Math.round(invY(y) * 1000) / 1000;
    const arr = node().keys[drag.k];
    if (arr) { arr.sort((a, b) => a.f - b.f); }
    api.setFrame(T.time.frame);                  // re-evaluate the pose from the edited keys
    if (T.syncChannel) T.syncChannel();
    draw();
  });
  const end = () => { if (!drag) return; drag = null; view.undoClose(); if (T.syncKeys) T.syncKeys(); draw(); };
  cv.addEventListener("pointerup", end);
  cv.addEventListener("pointercancel", end);

  fit.addEventListener("click", () => { draw(); });
  close.addEventListener("click", () => { panel.hidden = true; });
  T.syncGraph = () => { if (!panel.hidden) draw(); };
  api.graphOpen = (on) => { panel.hidden = on == null ? !panel.hidden : !on; if (!panel.hidden) draw(); return !panel.hidden; };
  api.graphShown = () => !panel.hidden;
  return panel;
}
window.forgeGraphAttach = forgeGraphAttach;
