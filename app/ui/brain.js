// Settings > Brain: LOKI's brain map, Obsidian-style (engine/brain.py, GET /brain).
// Everything LOKI knows as one graph - LOKI and its specialist roles, the capabilities behind
// them, memory, skills, recent jobs, the project's docs and your Obsidian vault (read-only),
// linked by [[wikilinks]] and #tags. Drag to pan, wheel to zoom, click a node to read it,
// type to find. The layout settles and then stops, so it costs nothing while you read.
"use strict";

const Brain = (function () {
  const COLORS = { loki: "#8ccfc4", role: "#a596c4", capability: "#7fb2e6", memory: "#f2b880",
    skill: "#9fd59a", job: "#e88a8a", doc: "#d8d2b8", vault: "#c4b5e8", tag: "#8a8a96" };
  let graph = null, nodes = [], edges = [], byId = {}, canvas = null, ctx = null, raf = 0;
  let view = { x: 0, y: 0, k: 1 }, drag = null, hover = null, selected = null, query = "", heat = 1;

  function layoutInit() {
    const groups = Object.keys(graph.groups || {});
    nodes = graph.nodes.map((n, i) => {
      const g = Math.max(0, groups.indexOf(n.group)), a = (g / Math.max(1, groups.length)) * Math.PI * 2 + i * 0.01;
      const r = n.group === "loki" ? 0 : 120 + (i % 7) * 18;
      return { ...n, x: Math.cos(a) * r + (Math.random() - 0.5) * 40, y: Math.sin(a) * r + (Math.random() - 0.5) * 40,
        vx: 0, vy: 0, r: 3 + Math.min(10, Math.sqrt(n.degree || 0) * 1.6) };
    });
    byId = {};
    for (const n of nodes) byId[n.id] = n;
    edges = graph.edges.map(([a, b]) => [byId[a], byId[b]]).filter(([a, b]) => a && b);
    heat = 1;
  }

  // one step of a force layout: springs on edges, repulsion between nearby nodes (a grid keeps
  // it fast for a big vault), a soft pull to the middle. Cools down and stops by itself.
  function step() {
    const cell = 60, grid = new Map();
    for (const n of nodes) {
      const key = Math.floor(n.x / cell) + "," + Math.floor(n.y / cell);
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(n);
    }
    for (const n of nodes) {
      const gx = Math.floor(n.x / cell), gy = Math.floor(n.y / cell);
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
        for (const m of grid.get((gx + dx) + "," + (gy + dy)) || []) {
          if (m === n) continue;
          let ex = n.x - m.x, ey = n.y - m.y, d2 = ex * ex + ey * ey + 0.01;
          if (d2 > cell * cell) continue;
          const f = 900 / d2;
          n.vx += ex * f * 0.02; n.vy += ey * f * 0.02;
        }
      }
      n.vx -= n.x * 0.0009; n.vy -= n.y * 0.0009;
    }
    for (const [a, b] of edges) {
      const ex = b.x - a.x, ey = b.y - a.y, d = Math.hypot(ex, ey) || 1, f = (d - 46) * 0.004;
      a.vx += ex / d * f * d * 0.08; a.vy += ey / d * f * d * 0.08;
      b.vx -= ex / d * f * d * 0.08; b.vy -= ey / d * f * d * 0.08;
    }
    let moved = 0;
    for (const n of nodes) {
      if (n === drag?.node) { n.vx = n.vy = 0; continue; }
      n.vx *= 0.6; n.vy *= 0.6;
      n.x += n.vx * heat; n.y += n.vy * heat;
      moved += Math.abs(n.vx) + Math.abs(n.vy);
    }
    heat = Math.max(0.02, heat * 0.985);
    return moved / Math.max(1, nodes.length) > 0.02 && heat > 0.03;
  }

  function match(n) { return !query || n.label.toLowerCase().includes(query); }

  function draw() {
    const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.translate(w / 2 + view.x, h / 2 + view.y);
    ctx.scale(view.k, view.k);
    const focus = selected || hover;
    const near = new Set();
    if (focus) for (const [a, b] of edges) { if (a === focus) near.add(b); if (b === focus) near.add(a); }
    ctx.lineWidth = 1 / view.k;
    for (const [a, b] of edges) {
      const lit = focus && (a === focus || b === focus);
      ctx.strokeStyle = lit ? "rgba(140,207,196,.75)" : "rgba(160,160,175,.14)";
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    for (const n of nodes) {
      const dim = (query && !match(n)) || (focus && n !== focus && !near.has(n));
      ctx.globalAlpha = dim ? 0.22 : 1;
      ctx.fillStyle = COLORS[n.group] || "#bbb";
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill();
      if (n === selected) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2 / view.k; ctx.stroke(); ctx.lineWidth = 1 / view.k; }
      if (!dim && (view.k > 1.3 || n.r > 7 || n === focus || near.has(n) || (query && match(n)))) {
        ctx.fillStyle = "rgba(228,228,231,.9)";
        ctx.font = (11 / view.k) + "px system-ui, sans-serif";
        ctx.fillText(n.label, n.x + n.r + 3 / view.k, n.y + 4 / view.k);
      }
    }
    ctx.globalAlpha = 1;
  }

  function loop() {
    raf = 0;
    const busy = step();
    draw();
    if (busy || drag) raf = requestAnimationFrame(loop);
  }
  function kick(h) { heat = Math.max(heat, h || 0.3); if (!raf) raf = requestAnimationFrame(loop); }
  function redraw() { if (!raf) requestAnimationFrame(draw); }

  function toWorld(ev) {
    const r = canvas.getBoundingClientRect();
    return [(ev.clientX - r.left - r.width / 2 - view.x) / view.k, (ev.clientY - r.top - r.height / 2 - view.y) / view.k];
  }
  function pick(ev) {
    const [x, y] = toWorld(ev);
    let best = null, bd = 12 / view.k;
    for (const n of nodes) { const d = Math.hypot(n.x - x, n.y - y) - n.r; if (d < bd) { bd = d; best = n; } }
    return best;
  }

  async function openNote(n, pane) {
    selected = n; redraw();
    pane.replaceChildren(el("h4", "", n.label), el("span", "brain-group", (graph.groups || {})[n.group] || n.group));
    if (n.detail) pane.append(el("p", "note", n.detail));
    if (n.group === "memory" && !n.note && n.id !== "hub:memory") pane.append(factTools(n, pane));
    const links = edges.filter(([a, b]) => a === n || b === n).map(([a, b]) => (a === n ? b : a));
    if (n.note) {
      const data = await api("/brain/note?id=" + encodeURIComponent(n.id)).catch(() => null);
      const body = el("div", "brain-text");
      body.innerHTML = renderMarkdown(String((data && data.text) || "").slice(0, 40000));
      pane.append(body);
    }
    if (links.length) {
      const list = el("div", "brain-links");
      list.append(el("b", "", "Linked (" + links.length + ")"));
      for (const m of links.slice(0, 60)) {
        const b = el("button", "quiet", m.label);
        b.type = "button";
        b.addEventListener("click", () => { center(m); openNote(m, pane); });
        list.append(b);
      }
      pane.append(list);
    }
  }
  // A remembered fact can be corrected or forgotten right here (memory.md, GET/POST /memory):
  // the map is for fixing what LOKI knows, not only for looking at it.
  function factTools(n, pane) {
    const row = el("div", "brain-fact");
    const edit = el("textarea");
    edit.value = n.detail; edit.rows = 3; edit.setAttribute("aria-label", "Edit this memory");
    const save = el("button", "", "Save change"), forget = el("button", "quiet", "Forget it");
    save.type = forget.type = "button";
    const apply = async (replacement) => {
      const cur = await api("/memory").catch(() => null);
      const lines = String((cur && cur.memory) || "").split("\n");
      const i = lines.findIndex((l) => l.replace(/^[-*\s]+/, "").trim() === n.detail.trim());
      if (i < 0) { addNotice("That fact changed since the map was drawn; reopen the Brain tab.", true); return; }
      if (replacement === null) lines.splice(i, 1); else lines[i] = "- " + replacement.trim();
      const r = await api("/memory", { text: lines.join("\n") }).catch(() => null);
      if (!r || !r.ok) { addNotice((r && r.error) || "Could not change LOKI's memory.", true); return; }
      addNotice(replacement === null ? "Forgotten." : "Memory updated.");
      load();
    };
    save.addEventListener("click", () => { if (edit.value.trim()) apply(edit.value); });
    forget.addEventListener("click", () => apply(null));
    row.append(edit, save, forget);
    return row;
  }

  function center(n) { view.x = -n.x * view.k; view.y = -n.y * view.k; redraw(); }

  async function load() {
    const box = document.getElementById("brain-panel");
    if (!box) return;
    box.replaceChildren(el("p", "note", "Drawing LOKI's brain…"));
    const data = await api("/brain").catch(() => null);
    if (!data || !data.ok) { box.replaceChildren(el("p", "note", (data && data.error) || "The brain map is not available.")); return; }
    graph = data;
    layoutInit();
    const bar = el("div", "brain-bar");
    const find = el("input");
    find.type = "search"; find.placeholder = "Find in the brain…"; find.setAttribute("aria-label", "Find a node");
    find.addEventListener("input", () => {
      query = find.value.trim().toLowerCase(); redraw();
      const hit = query && nodes.find(match);
      if (hit) center(hit);
    });
    const legend = el("div", "brain-legend");
    for (const [g, label] of Object.entries(graph.groups || {})) {
      const chip = el("span", "brain-chip", label);
      chip.style.setProperty("--c", COLORS[g] || "#bbb");
      legend.append(chip);
    }
    const vault = el("form", "brain-vault");
    const vin = el("input");
    vin.placeholder = "Your Obsidian vault folder (optional)"; vin.value = graph.vault || ""; vin.setAttribute("aria-label", "Obsidian vault folder");
    const vbtn = el("button", "", graph.vault ? "Change" : "Add vault");
    vbtn.type = "submit";
    vault.append(vin, vbtn);
    vault.addEventListener("submit", async (e) => {
      e.preventDefault();
      const r = await api("/brain/vault", { path: vin.value }).catch(() => null);
      if (!r || !r.ok) addNotice((r && r.error) || "Could not use that folder.", true); else load();
    });
    bar.append(find, el("span", "note", nodes.length + " notes · " + edges.length + " links"), vault);
    const wrap = el("div", "brain-wrap");
    canvas = el("canvas", "brain-canvas");
    canvas.setAttribute("aria-label", "Brain map");
    const pane = el("div", "brain-pane");
    pane.append(el("p", "note", "Click a node to read it. Drag to move around, wheel to zoom."));
    wrap.append(canvas, pane);
    box.replaceChildren(bar, legend, wrap);
    ctx = canvas.getContext("2d");
    view = { x: 0, y: 0, k: 1 };
    canvas.addEventListener("pointerdown", (ev) => {
      const n = pick(ev);
      drag = { node: n, x: ev.clientX, y: ev.clientY, vx: view.x, vy: view.y, moved: false };
      canvas.setPointerCapture(ev.pointerId);
    });
    canvas.addEventListener("pointermove", (ev) => {
      if (!drag) { const h = pick(ev); if (h !== hover) { hover = h; canvas.style.cursor = h ? "pointer" : "grab"; redraw(); } return; }
      const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      if (drag.node) { const [x, y] = toWorld(ev); drag.node.x = x; drag.node.y = y; kick(0.15); }
      else { view.x = drag.vx + dx; view.y = drag.vy + dy; redraw(); }
    });
    canvas.addEventListener("pointerup", () => {
      if (drag && !drag.moved && drag.node) openNote(drag.node, pane);
      drag = null;
    });
    canvas.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const k = Math.max(0.15, Math.min(5, view.k * Math.exp(-ev.deltaY * 0.0015)));
      view.x *= k / view.k; view.y *= k / view.k; view.k = k; redraw();
    }, { passive: false });
    for (let i = 0; i < 120; i++) step();        // most of the settling happens before the first frame
    const cx = nodes.reduce((a, n) => a + n.x, 0) / Math.max(1, nodes.length), cy = nodes.reduce((a, n) => a + n.y, 0) / Math.max(1, nodes.length);
    for (const n of nodes) { n.x -= cx; n.y -= cy; }   // start centred
    kick(0.5);
  }

  function stop() { if (raf) cancelAnimationFrame(raf); raf = 0; }
  return { load, stop };
})();
window.Brain = Brain;
