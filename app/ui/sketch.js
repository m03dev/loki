// Sketch - draw something for LOKI (a layout, a diagram, a game level, an arrow on a screenshot).
//
// The ✎ button in the message box opens a drawing pad: pen (pressure-sensitive on a tablet or
// Apple Pencil via pointer events), marker, eraser, colours, undo/redo, clear. "Attach" saves
// the drawing as a PNG in the workspace (POST /sketch -> sketches/sketch-<time>.png) and the next
// message carries it: LOKI is told where it is and looks at it with its view_image tool.
// LOKI can draw back (the canvas <-> agent loop PenEcho is built on): its sketch_reply tool saves
// shapes to sketches/loki-<time>.json and the pad shows the newest one under your own strokes
// (GET /sketch/reply; "LOKI's drawing" hides it). For a full AI canvas there is the optional
// PenEcho add-on (Settings > Add-ons).
"use strict";

const Sketch = (function () {
  const COLORS = ["#e4e4e7", "#8ccfc4", "#f2b880", "#e88a8a", "#a596c4", "#7fb2e6", "#111114"];
  let pending = [];                 // [{path, url}] attached to the next message
  let modal = null, canvas = null, ctx = null, strokes = [], redo = [], current = null;
  let tool = "pen", color = COLORS[0];
  let reply = null, showReply = true;   // LOKI's newest drawing on the pad (sketch_reply)

  function node(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  // ---------------------------------------------------------------- drawing
  function width(s, p) {      // pen width follows pen pressure; mouse/trackpad get the middle
    const base = s.tool === "marker" ? 14 : s.tool === "eraser" ? 26 : 3.2;
    return base * (s.tool === "pen" ? 0.45 + (p == null ? 0.5 : p) * 1.1 : 1);
  }

  function redraw() {
    const r = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#1c1c20";
    ctx.fillRect(0, 0, r.width, r.height);
    if (reply && showReply) drawReply(r.width, r.height);
    for (const s of strokes) drawStroke(s);
  }

  // LOKI's shapes use 0..1000 across and down the pad.
  function drawReply(w, h) {
    const X = (v) => (Number(v) || 0) * w / 1000, Y = (v) => (Number(v) || 0) * h / 1000;
    ctx.save();
    ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.lineWidth = 2.5;
    ctx.font = "15px system-ui, sans-serif";
    for (const s of reply.shapes || []) {
      ctx.strokeStyle = ctx.fillStyle = s.color || "#8ccfc4";
      ctx.beginPath();
      if (s.type === "line" || s.type === "arrow") {
        const x1 = X(s.x1), y1 = Y(s.y1), x2 = X(s.x2), y2 = Y(s.y2);
        ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
        if (s.type === "arrow") {
          const a = Math.atan2(y2 - y1, x2 - x1), k = 12;
          ctx.beginPath(); ctx.moveTo(x2, y2);
          ctx.lineTo(x2 - k * Math.cos(a - 0.45), y2 - k * Math.sin(a - 0.45));
          ctx.lineTo(x2 - k * Math.cos(a + 0.45), y2 - k * Math.sin(a + 0.45));
          ctx.closePath(); ctx.fill();
        }
      } else if (s.type === "rect") {
        ctx.strokeRect(X(s.x), Y(s.y), X(s.w), Y(s.h));
      } else if (s.type === "circle") {
        ctx.arc(X(s.cx), Y(s.cy), Math.max(1, X(s.r)), 0, Math.PI * 2); ctx.stroke();
      } else if (s.type === "text") {
        ctx.fillText(String(s.text || ""), X(s.x), Y(s.y));
      } else if (s.type === "path" && (s.points || []).length > 1) {
        ctx.moveTo(X(s.points[0][0]), Y(s.points[0][1]));
        for (const p of s.points.slice(1)) ctx.lineTo(X(p[0]), Y(p[1]));
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  async function loadReply(button) {
    const data = await api("/sketch/reply").catch(() => null);
    reply = data && data.ok && (data.shapes || []).length ? data : null;
    if (button) { button.hidden = !reply; button.title = reply ? (reply.note || reply.name || "") : ""; }
    if (canvas) redraw();
  }

  function drawStroke(s) {
    ctx.save();
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.strokeStyle = s.tool === "eraser" ? "#1c1c20" : s.color;
    ctx.globalAlpha = s.tool === "marker" ? 0.45 : 1;
    const pts = s.pts;
    if (pts.length === 1) {
      ctx.fillStyle = ctx.strokeStyle;
      ctx.beginPath(); ctx.arc(pts[0][0], pts[0][1], width(s, pts[0][2]) / 2, 0, Math.PI * 2); ctx.fill();
    }
    for (let i = 1; i < pts.length; i++) {      // smooth: midpoint quadratic segments
      const a = pts[i - 1], b = pts[i], m = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      ctx.lineWidth = width(s, b[2]);
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.quadraticCurveTo(a[0], a[1], m[0], m[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
    }
    ctx.restore();
  }

  function pos(e) {
    const r = canvas.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top, e.pointerType === "pen" ? e.pressure : null];
  }

  function down(e) {
    e.preventDefault();
    try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* keep drawing without capture */ }
    current = { tool, color, pts: [pos(e)] };
    strokes.push(current); redo = [];
    drawStroke(current);
  }
  function move(e) {
    if (!current) return;
    const co = e.getCoalescedEvents ? e.getCoalescedEvents() : [];
    const evs = co.length ? co : [e];      // finer strokes on a pen; synthetic events have none
    for (const ev of evs) current.pts.push(pos(ev));
    redraw();
  }
  function up() { current = null; }

  function size() {
    const r = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(r.width * dpr); canvas.height = Math.round(r.height * dpr);
    redraw();
  }

  // ---------------------------------------------------------------- the pad
  function open() {
    if (modal) { modal.hidden = false; size(); loadReply(modal.querySelector(".sketch-reply")); return; }
    modal = node("div", "sketch-modal");
    const panel = node("div", "sketch-panel");
    const bar = node("div", "sketch-bar");
    const tools = node("div", "sketch-tools");
    for (const [id, label] of [["pen", "Pen"], ["marker", "Marker"], ["eraser", "Eraser"]]) {
      const b = node("button", "sketch-tool" + (id === tool ? " on" : ""), label);
      b.type = "button";
      b.addEventListener("click", () => { tool = id; tools.querySelectorAll(".sketch-tool").forEach((x) => x.classList.toggle("on", x === b)); });
      tools.append(b);
    }
    const swatches = node("div", "sketch-colors");
    for (const c of COLORS) {
      const b = node("button", "sketch-color" + (c === color ? " on" : ""));
      b.type = "button"; b.style.background = c; b.setAttribute("aria-label", "colour " + c);
      b.addEventListener("click", () => { color = c; if (tool === "eraser") tool = "pen"; swatches.querySelectorAll(".sketch-color").forEach((x) => x.classList.toggle("on", x === b)); });
      swatches.append(b);
    }
    const act = (label, fn, cls) => { const b = node("button", cls || "quiet", label); b.type = "button"; b.addEventListener("click", fn); return b; };
    const actions = node("div", "sketch-actions");
    const replyBtn = act("LOKI's drawing", () => { showReply = !showReply; replyBtn.classList.toggle("on", showReply); redraw(); }, "quiet sketch-tool sketch-reply on");
    replyBtn.hidden = true;
    actions.append(
      replyBtn,
      act("Undo", () => { if (strokes.length) { redo.push(strokes.pop()); redraw(); } }),
      act("Redo", () => { if (redo.length) { strokes.push(redo.pop()); redraw(); } }),
      act("Clear", () => { strokes = []; redo = []; redraw(); }),
      act("Cancel", close),
      act("Attach to message", attach, "send"));
    bar.append(tools, swatches, actions);
    canvas = node("canvas", "sketch-canvas");
    canvas.setAttribute("aria-label", "Drawing pad");
    panel.append(bar, canvas, node("div", "sketch-hint", "Draw with the mouse, a trackpad or a pen. Ctrl/Cmd+Z undoes. LOKI looks at the drawing with your next message."));
    modal.append(panel);
    document.body.append(modal);
    ctx = canvas.getContext("2d");
    canvas.addEventListener("pointerdown", down);
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", up);
    modal.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) { if (redo.length) strokes.push(redo.pop()); } else if (strokes.length) redo.push(strokes.pop()); redraw(); }
      if (e.key === "Escape") close();
    });
    modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
    window.addEventListener("resize", () => { if (modal && !modal.hidden) size(); });
    modal.tabIndex = -1;
    requestAnimationFrame(() => { size(); modal.focus(); });
    loadReply(replyBtn);
  }

  function close() { if (modal) modal.hidden = true; }

  async function attach() {
    if (!strokes.length) { close(); return; }
    const url = canvas.toDataURL("image/png");
    const data = await api("/sketch", { png: url }).catch((e) => ({ ok: false, error: String(e) }));
    if (!data.ok) { addNotice(data.error || "Could not save the drawing.", true); return; }
    pending.push({ path: data.path, url });
    strokes = []; redo = [];
    close();
    renderChips();
    const p = document.getElementById("prompt");
    if (p) p.focus();
  }

  function renderChips() {
    const box = document.querySelector(".composer-box");
    if (!box) return;
    let row = box.querySelector(".sketch-chips");
    if (!pending.length) { if (row) row.remove(); return; }
    if (!row) { row = node("div", "sketch-chips"); box.prepend(row); }
    row.replaceChildren();
    pending.forEach((s, i) => {
      const chip = node("span", "sketch-chip");
      const img = node("img"); img.src = s.url; img.alt = "your drawing";
      const x = node("button", "quiet", "×"); x.type = "button"; x.setAttribute("aria-label", "remove the drawing");
      x.addEventListener("click", () => { pending.splice(i, 1); renderChips(); });
      chip.append(img, node("span", "", s.path), x);
      row.append(chip);
    });
  }

  // called by app.js just before a message goes to the engine
  function take(text) {
    if (!pending.length) return { text, thumbs: [] };
    const list = pending.map((s) => s.path).join(", ");
    const out = { text: text + "\n\n[The user drew " + (pending.length === 1 ? "a sketch" : "sketches") + " for this message: " + list +
      ". Look at " + (pending.length === 1 ? "it" : "them") + " with view_image first; you can answer on the pad itself with sketch_reply.]", thumbs: pending.map((s) => s.url) };
    pending = [];
    renderChips();
    return out;
  }

  function wire() {
    const row = document.querySelector(".composer-row");
    if (!row) return;
    const b = node("button", "quiet sketch-open", "✎ Draw");
    b.type = "button"; b.title = "Draw something for LOKI";
    b.addEventListener("click", open);
    row.insertBefore(b, row.querySelector(".bg-toggle"));
  }

  document.addEventListener("DOMContentLoaded", wire);
  return { open, take, pendingCount: () => pending.length };
})();
window.Sketch = Sketch;
