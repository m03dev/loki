// Loki brain map: an Obsidian-style force-directed graph of what Loki knows.
// Data comes from GET /brain; note bodies from GET /brain/note?id= (only ids the map listed).
// Plain canvas, no libraries (the app's CSP only allows its own scripts).
"use strict";

(function () {
  const PALETTE = {
    loki: "--ok", role: "--task", capability: "--tool", memory: "--warn",
    skill: "--accent", job: "--err", doc: "--text", vault: "--accent", tag: "--muted",
  };
  const view = {
    api: null, canvas: null, ctx: null, nodes: [], edges: [], byId: new Map(), adj: new Map(),
    scale: 1, ox: 0, oy: 0, dpr: 1, w: 0, h: 0, alpha: 0, raf: 0, hover: null, selected: null,
    drag: null, pan: null, hidden: new Set(), query: "", matches: new Set(), colors: {},
  };

  const $ = (s) => document.querySelector(s);
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function readColors() {
    const css = getComputedStyle(document.documentElement);
    for (const [g, v] of Object.entries(PALETTE)) view.colors[g] = css.getPropertyValue(v).trim() || "#8fb3d9";
    view.colors.line = css.getPropertyValue("--line").trim() || "#34343c";
    view.colors.text = css.getPropertyValue("--text").trim() || "#e6e9ee";
    view.colors.bg = css.getPropertyValue("--bg").trim() || "#1f1f24";
  }

  // ------------------------------------------------------------ data
  function load(data) {
    const groups = Object.keys(data.groups || {});
    view.nodes = data.nodes.map((n, i) => {
      const gi = Math.max(0, groups.indexOf(n.group));
      const a = (gi / Math.max(1, groups.length)) * Math.PI * 2 + (i % 17) * 0.05;
      const r = n.id === "loki" ? 0 : 120 + (i % 23) * 9;
      return Object.assign({}, n, { x: Math.cos(a) * r, y: Math.sin(a) * r, vx: 0, vy: 0, fixed: n.id === "loki" });
    });
    view.byId = new Map(view.nodes.map((n) => [n.id, n]));
    view.edges = data.edges.map(([a, b]) => [view.byId.get(a), view.byId.get(b)]).filter((e) => e[0] && e[1]);
    view.adj = new Map(view.nodes.map((n) => [n.id, new Set()]));
    for (const [a, b] of view.edges) { view.adj.get(a.id).add(b.id); view.adj.get(b.id).add(a.id); }
    renderLegend(data.groups || {});
    $("#brain-count").textContent = view.nodes.length + " notes · " + view.edges.length + " links";
    view.alpha = 1;
    kick();
  }

  // ------------------------------------------------------------ physics
  function step() {
    const nodes = view.nodes.filter((n) => !view.hidden.has(n.group));
    const cell = 70, grid = new Map();
    for (const n of nodes) {
      const k = Math.floor(n.x / cell) + "," + Math.floor(n.y / cell);
      if (!grid.has(k)) grid.set(k, []);
      grid.get(k).push(n);
    }
    const a = view.alpha;
    for (const n of nodes) {
      const cx = Math.floor(n.x / cell), cy = Math.floor(n.y / cell);
      for (let dx = -2; dx <= 2; dx++) for (let dy = -2; dy <= 2; dy++) {
        const bucket = grid.get((cx + dx) + "," + (cy + dy));
        if (!bucket) continue;
        for (const m of bucket) {
          if (m === n) continue;
          let x = n.x - m.x, y = n.y - m.y, d2 = x * x + y * y;
          if (d2 < 0.01) { x = Math.random() - 0.5; y = Math.random() - 0.5; d2 = 0.5; }
          if (d2 > cell * cell * 4) continue;
          const f = (900 / d2) * a;
          n.vx += x * f * 0.02; n.vy += y * f * 0.02;
        }
      }
      n.vx -= n.x * 0.0009 * a; n.vy -= n.y * 0.0009 * a;   // gentle pull to the centre
    }
    for (const [s, t] of view.edges) {
      if (view.hidden.has(s.group) || view.hidden.has(t.group)) continue;
      const x = t.x - s.x, y = t.y - s.y, d = Math.sqrt(x * x + y * y) || 1;
      const want = 38 + Math.min(60, Math.sqrt(s.degree + t.degree) * 6);
      const f = ((d - want) / d) * 0.04 * a;
      if (!s.fixed) { s.vx += x * f; s.vy += y * f; }
      if (!t.fixed) { t.vx -= x * f; t.vy -= y * f; }
    }
    for (const n of nodes) {
      if (n.fixed || n === view.drag) { n.vx = n.vy = 0; continue; }
      n.vx *= 0.82; n.vy *= 0.82;
      n.x += Math.max(-30, Math.min(30, n.vx)); n.y += Math.max(-30, Math.min(30, n.vy));
    }
    view.alpha *= 0.985;
  }

  function kick() {
    if (view.raf) return;
    const loop = () => {
      if (view.alpha > 0.02) step();
      draw();
      view.raf = (view.alpha > 0.02 || view.drag) ? requestAnimationFrame(loop) : 0;
    };
    view.raf = requestAnimationFrame(loop);
  }

  // ------------------------------------------------------------ drawing
  const radius = (n) => (n.id === "loki" ? 11 : 2.6 + Math.sqrt(n.degree) * 1.4);
  const toScreen = (n) => [n.x * view.scale + view.ox, n.y * view.scale + view.oy];

  function draw() {
    const c = view.ctx;
    if (!c) return;
    c.setTransform(view.dpr, 0, 0, view.dpr, 0, 0);
    c.fillStyle = view.colors.bg;
    c.fillRect(0, 0, view.w, view.h);
    const focus = view.hover || view.selected;
    const near = focus ? view.adj.get(focus.id) : null;
    const searching = view.query.length > 0;
    c.lineWidth = 1;
    for (const [s, t] of view.edges) {
      if (view.hidden.has(s.group) || view.hidden.has(t.group)) continue;
      const lit = focus && (s === focus || t === focus);
      c.strokeStyle = lit ? view.colors[focus.group] : view.colors.line;
      c.globalAlpha = lit ? 0.9 : (focus || searching ? 0.15 : 0.55);
      const [x1, y1] = toScreen(s), [x2, y2] = toScreen(t);
      c.beginPath(); c.moveTo(x1, y1); c.lineTo(x2, y2); c.stroke();
    }
    for (const n of view.nodes) {
      if (view.hidden.has(n.group)) continue;
      const [x, y] = toScreen(n);
      if (x < -20 || y < -20 || x > view.w + 20 || y > view.h + 20) continue;
      const on = !focus || n === focus || (near && near.has(n.id));
      const hit = !searching || view.matches.has(n.id);
      c.globalAlpha = on && hit ? 1 : 0.18;
      c.fillStyle = view.colors[n.group] || view.colors.text;
      c.beginPath(); c.arc(x, y, radius(n) * Math.max(0.7, Math.sqrt(view.scale)), 0, Math.PI * 2); c.fill();
      if (n === view.selected) { c.strokeStyle = view.colors.text; c.lineWidth = 2; c.stroke(); c.lineWidth = 1; }
      const showLabel = n === focus || (near && near.has(n.id)) || (searching && view.matches.has(n.id))
        || view.scale > 1.6 || n.degree > 12 || n.id === "loki";
      if (showLabel && on && hit) {
        c.fillStyle = view.colors.text;
        c.font = (n.id === "loki" ? "600 13px " : "11px ") + "-apple-system, system-ui, sans-serif";
        c.fillText(n.label, x + radius(n) + 4, y + 4);
      }
    }
    c.globalAlpha = 1;
  }

  function resize() {
    const box = view.canvas.parentElement.getBoundingClientRect();
    view.dpr = window.devicePixelRatio || 1;
    const first = !view.w;
    view.w = box.width; view.h = box.height;
    view.canvas.width = Math.round(view.w * view.dpr); view.canvas.height = Math.round(view.h * view.dpr);
    view.canvas.style.width = view.w + "px"; view.canvas.style.height = view.h + "px";
    if (first) { view.ox = view.w / 2; view.oy = view.h / 2; }
    draw();
  }

  // ------------------------------------------------------------ interaction
  function nodeAt(px, py) {
    let best = null, bestD = 14 * 14;
    for (const n of view.nodes) {
      if (view.hidden.has(n.group)) continue;
      const [x, y] = toScreen(n), d = (x - px) ** 2 + (y - py) ** 2;
      if (d < bestD) { best = n; bestD = d; }
    }
    return best;
  }

  function point(e) {
    const r = view.canvas.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }

  function wireCanvas() {
    const cv = view.canvas;
    cv.addEventListener("pointerdown", (e) => {
      const [x, y] = point(e), n = nodeAt(x, y);
      cv.setPointerCapture(e.pointerId);
      if (n) { view.drag = n; view.dragMoved = false; } else view.pan = [x, y, view.ox, view.oy];
    });
    cv.addEventListener("pointermove", (e) => {
      const [x, y] = point(e);
      if (view.drag) {
        view.drag.x = (x - view.ox) / view.scale; view.drag.y = (y - view.oy) / view.scale;
        view.dragMoved = true; view.alpha = Math.max(view.alpha, 0.3); kick();
      } else if (view.pan) {
        view.ox = view.pan[2] + x - view.pan[0]; view.oy = view.pan[3] + y - view.pan[1]; draw();
      } else {
        const n = nodeAt(x, y);
        if (n !== view.hover) { view.hover = n; cv.style.cursor = n ? "pointer" : "grab"; draw(); }
      }
    });
    const end = () => {
      if (view.drag && !view.dragMoved) select(view.drag);
      view.drag = null; view.pan = null;
    };
    cv.addEventListener("pointerup", end);
    cv.addEventListener("pointercancel", end);
    cv.addEventListener("pointerleave", () => { view.hover = null; draw(); });
    cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      const [x, y] = point(e), k = Math.exp(-e.deltaY * 0.0015);
      const next = Math.max(0.15, Math.min(6, view.scale * k));
      view.ox = x - ((x - view.ox) * next) / view.scale;
      view.oy = y - ((y - view.oy) * next) / view.scale;
      view.scale = next; draw();
    }, { passive: false });
  }

  function centerOn(n) {
    view.ox = view.w / 2 - n.x * view.scale; view.oy = view.h / 2 - n.y * view.scale; draw();
  }

  async function select(n) {
    view.selected = n; draw();
    const box = $("#brain-detail");
    box.replaceChildren();
    if (!n) { box.hidden = true; return; }
    box.hidden = false;
    box.append(el("h3", "", n.label), el("div", "brain-group", (window.__brainGroups || {})[n.group] || n.group));
    if (n.detail) box.append(el("p", "brain-text", n.detail));
    const links = [...(view.adj.get(n.id) || [])].map((id) => view.byId.get(id)).filter(Boolean);
    if (links.length) {
      box.append(el("div", "brain-sub", "Linked (" + links.length + ")"));
      const list = el("div", "brain-links");
      for (const m of links.slice(0, 60)) {
        const b = el("button", "quiet", m.label);
        b.type = "button";
        b.addEventListener("click", () => { centerOn(m); select(m); });
        list.append(b);
      }
      box.append(list);
    }
    if (n.note) {
      const pre = el("pre", "brain-note", "Loading…");
      box.append(pre);
      const data = await view.api("/brain/note?id=" + encodeURIComponent(n.id)).catch(() => null);
      pre.textContent = data && data.ok ? data.text : "Could not open this note.";
    }
  }

  function renderLegend(groups) {
    window.__brainGroups = groups;
    const box = $("#brain-legend");
    box.replaceChildren();
    for (const [g, label] of Object.entries(groups)) {
      const item = el("label", "brain-key");
      const cb = el("input");
      cb.type = "checkbox"; cb.checked = !view.hidden.has(g);
      cb.addEventListener("change", () => { cb.checked ? view.hidden.delete(g) : view.hidden.add(g); view.alpha = 0.5; kick(); });
      const dot = el("span", "brain-dot");
      dot.style.background = view.colors[g] || view.colors.text;
      item.append(cb, dot, document.createTextNode(label));
      box.append(item);
    }
  }

  function search(text) {
    view.query = text.trim().toLowerCase();
    view.matches = new Set(view.query ? view.nodes.filter((n) =>
      n.label.toLowerCase().includes(view.query) || (n.detail || "").toLowerCase().includes(view.query)).map((n) => n.id) : []);
    draw();
    return view.nodes.find((n) => view.matches.has(n.id));
  }

  // ------------------------------------------------------------ public
  async function refresh() {
    $("#brain-count").textContent = "Mapping…";
    const data = await view.api("/brain").catch((e) => ({ ok: false, error: String(e) }));
    if (!data.ok) { $("#brain-count").textContent = data.error || "Could not build the map."; return; }
    $("#brain-vault").value = data.vault || "";
    load(data);
  }

  function init(api) {
    view.api = api;
    view.canvas = $("#brain-canvas");
    view.ctx = view.canvas.getContext("2d");
    readColors();
    wireCanvas();
    window.addEventListener("resize", () => { if (!$("#brain").hidden) resize(); });
    $("#brain-search").addEventListener("input", (e) => search(e.target.value));
    $("#brain-search").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { const n = search(e.target.value); if (n) { centerOn(n); select(n); } }
    });
    $("#brain-refresh").addEventListener("click", refresh);
    $("#brain-fit").addEventListener("click", () => { view.scale = 1; view.ox = view.w / 2; view.oy = view.h / 2; draw(); });
    $("#brain-vault-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = await api("/brain/vault", { path: $("#brain-vault").value });
      $("#brain-count").textContent = data.ok ? (data.vault ? "Vault linked" : "Vault removed") : (data.error || "Could not use that folder.");
      if (data.ok) refresh();
    });
  }

  function open() {
    $("#brain").hidden = false;
    readColors();
    requestAnimationFrame(() => { resize(); if (!view.nodes.length) refresh(); else draw(); });
  }

  function close() { $("#brain").hidden = true; select(null); }

  window.LokiBrain = { init, open, close, _view: view, _search: search };
})();
