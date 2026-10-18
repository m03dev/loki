// Forge > Materials: a node-based procedural material editor in the spirit of (and running the node definitions
// of) Material Maker by Rodolphe Suescun and contributors (MIT; github.com/RodZill4/material-maker). The node
// library is Material Maker's own .mmg files (app/ui/vendor/material_maker/nodes.json, tools/import_mm_nodes.py),
// compiled by forge_mm.js; this file is the editor: a graph you drag nodes and wires in, a parameter panel,
// live PBR maps (albedo, normal, roughness, metallic, AO, height) rendered with WebGL2 and applied to the Forge
// model as you edit, PNG export, .ptex save/load (Material Maker's project format) and "Open in Material Maker".
//
// window.ForgeMaterials = { open(host), bake(size) -> {albedo, normal, ...: canvas}, renderMap(graph, map, size) }
// Uses el(), api(), state from app.js and forgeBtn/forgeSay from forge.js. Plain DOM, CSP-safe.
"use strict";

(function () {
  const VERT = "#version 300 es\nin vec2 p; out vec2 vUv; void main() { vUv = p * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0); }";
  const M = { graph: null, sel: "", lib: null, gl: null, compiled: null, timer: 0, host: null, size: 512, onMaps: null, view: { x: 0, y: 0 } };

  // ------------------------------------------------------------------------------------------ WebGL2 renderer
  function glContext() {
    if (M.gl) return M.gl;
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2", { preserveDrawingBuffer: true, premultipliedAlpha: false });
    if (!gl) return null;
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    M.gl = { gl, canvas: c, programs: new Map() };
    return M.gl;
  }

  function program(G, frag) {
    if (G.programs.has(frag)) return G.programs.get(frag);
    const gl = G.gl;
    const sh = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || "shader error");
      return s;
    };
    const p = gl.createProgram();
    gl.attachShader(p, sh(gl.VERTEX_SHADER, VERT)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, frag));
    gl.bindAttribLocation(p, 0, "p"); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) || "link error");
    if (G.programs.size > 40) G.programs.clear();
    G.programs.set(frag, p);
    return p;
  }

  // render one fragment shader at size x size into a new 2D canvas (so it can be shown, saved, used as a texture)
  function draw(frag, uniforms, size) {
    const G = glContext();
    if (!G) throw new Error("WebGL2 is not available");
    const gl = G.gl;
    G.canvas.width = size; G.canvas.height = size;
    const p = program(G, frag);
    gl.viewport(0, 0, size, size);
    gl.useProgram(p);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.uniform1f(gl.getUniformLocation(p, "mm_size"), size);
    for (const [name, u] of Object.entries(uniforms)) {
      const loc = gl.getUniformLocation(p, name);
      if (!loc) continue;
      if (u.kind === "vec4") gl.uniform4f(loc, u.value.r, u.value.g, u.value.b, u.value.a === undefined ? 1 : u.value.a);
      else gl.uniform1f(loc, Number(u.value) || 0);
    }
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    const out = document.createElement("canvas");
    out.width = size; out.height = size;
    out.getContext("2d").drawImage(G.canvas, 0, 0);
    return out;
  }

  function compiled() {
    if (!M.compiled) M.compiled = window.ForgeMM.compile(M.graph);
    return M.compiled;
  }

  function renderMap(graph, map, size) {
    const c = window.ForgeMM.compile(graph);
    if (c.errors.length) throw new Error(c.errors.join("; "));
    return draw(c.maps[map], c.uniforms, size);
  }

  function bake(size) {
    const c = compiled(), out = {};
    for (const k of Object.keys(c.maps)) out[k] = draw(c.maps[k], c.uniforms, size || M.size);
    return out;
  }

  // ------------------------------------------------------------------------------------------ library
  async function library() {
    if (M.lib) return M.lib;
    const r = await fetch("/ui/vendor/material_maker/nodes.json");
    M.lib = window.ForgeMM.load(await r.json());
    return M.lib;
  }

  function uniqueName(type) {
    let i = 1;
    const names = new Set(M.graph.nodes.map((n) => n.name));
    while (names.has(type + "_" + i)) i++;
    return type + "_" + i;
  }

  function changed(structure) {
    if (structure) M.compiled = null;
    clearTimeout(M.timer);
    M.timer = setTimeout(refresh, 60);
    try { localStorage.setItem("loki-forge-material", JSON.stringify(window.ForgeMM.toPtex(M.graph))); } catch (_) { /* private mode */ }
  }

  // live: parameter edits only change uniforms - no recompile, just re-render
  function setParam(node, name, value) {
    node.parameters[name] = value;
    const c = M.compiled;
    if (c) {
      let found = false;
      for (const u of Object.values(c.uniforms)) if (u.node === node.name && u.param === name) { u.value = value; found = true; }
      if (!found) M.compiled = null;   // enums, booleans, gradients are compiled in
    }
    changed(false);
  }

  function refresh() {
    const say = (t, bad) => { const s = M.host && M.host.querySelector(".fm-status"); if (s) { s.textContent = t; s.classList.toggle("bad", !!bad); } };
    let c;
    try { c = compiled(); } catch (exc) { say("Could not build: " + exc.message, true); return; }
    if (c.errors.length) say(c.errors.slice(0, 2).join("; "), true); else say("");
    try {
      const maps = bake(Math.min(M.size, 512));
      for (const [k, cv] of Object.entries(maps)) {
        const slot = M.host && M.host.querySelector('[data-map="' + k + '"]');
        if (slot) { slot.replaceChildren(cv); cv.title = k; }
      }
      if (M.onMaps) M.onMaps(maps);
      drawThumbs();
    } catch (exc) {
      say("Shader: " + String(exc.message).split("\n").slice(0, 2).join(" "), true);
    }
  }

  function drawThumbs() {
    if (!M.host) return;
    const c = compiled();
    for (const box of M.host.querySelectorAll(".fm-node canvas.fm-thumb")) {
      try {
        const frag = c.preview(box.dataset.node, 0);
        if (!frag) continue;
        const cv = draw(frag, c.uniforms, 64);
        box.getContext("2d").clearRect(0, 0, 64, 64);
        box.getContext("2d").drawImage(cv, 0, 0);
      } catch (_) { /* a node without outputs */ }
    }
  }

  // ------------------------------------------------------------------------------------------ the editor
  function open(host, onMaps) {
    M.host = host; M.onMaps = onMaps;
    return library().then(() => {
      if (!M.graph) {
        let saved = null;
        try { saved = JSON.parse(localStorage.getItem("loki-forge-material") || "null"); } catch (_) { saved = null; }
        M.graph = saved ? window.ForgeMM.fromPtex(saved).graph : window.ForgeMM.newGraph();
      }
      build();
      M.compiled = null;
      refresh();
    });
  }

  function build() {
    const h = M.host;
    h.replaceChildren();
    const bar = el("div", "fm-bar");
    const add = el("select", "fm-add"); add.setAttribute("aria-label", "Add a node");
    add.append(new Option("+ Add node…", ""));
    const groups = {};
    for (const [name, def] of Object.entries(M.lib.nodes)) {
      if (name.startsWith("custom:")) continue;
      (groups[def.category || "Filters"] = groups[def.category || "Filters"] || []).push([name, def.shader_model.name || name]);
    }
    for (const [cat, items] of Object.entries(groups)) {
      const og = document.createElement("optgroup"); og.label = cat;
      for (const [name, label] of items.sort((a, b) => a[1].localeCompare(b[1]))) og.append(new Option(label, name));
      add.append(og);
    }
    add.addEventListener("change", () => {
      if (!add.value) return;
      const type = add.value; add.value = "";
      const n = { name: uniqueName(type), type, parameters: window.ForgeMM.defaults(type), seed_int: Math.floor(Math.random() * 65535),
        node_position: { x: 40 - M.view.x + M.graph.nodes.length * 14, y: 40 - M.view.y + M.graph.nodes.length * 14 } };
      M.graph.nodes.push(n); M.sel = n.name; build(); changed(true);
    });
    const size = el("select", "fm-size"); size.setAttribute("aria-label", "Texture size");
    for (const s of [256, 512, 1024, 2048, 4096]) { const o = new Option(s + " px", String(s)); if (s === M.size) o.selected = true; size.append(o); }
    size.addEventListener("change", () => { M.size = +size.value; });
    bar.append(add, size,
      forgeBtn("save", "Save maps", "Save the PBR maps as PNGs (albedo, normal, roughness, metallic, AO, height) into models/.", saveMaps),
      forgeBtn("file", "Save .ptex", "Save this material as a Material Maker project (.ptex) into models/.", savePtex),
      forgeBtn("upload", "Load .ptex", "Open a Material Maker project (.ptex).", loadPtex),
      forgeBtn("external", "Open in Material Maker", "Open this material in the Material Maker app (download link when it is not installed).", openInMM),
      forgeBtn("trash", "New", "Start a new material.", () => { M.graph = window.ForgeMM.newGraph(); M.sel = ""; build(); changed(true); }));
    const status = el("span", "fm-status"); status.setAttribute("role", "status");
    const main = el("div", "fm-main");
    const canvas = el("div", "fm-graph"); canvas.setAttribute("aria-label", "Material graph: drag nodes, drag from an output dot to an input dot");
    const wires = document.createElementNS("http://www.w3.org/2000/svg", "svg"); wires.classList.add("fm-wires");
    const layer = el("div", "fm-layer");
    canvas.append(wires, layer);
    const side = el("div", "fm-side");
    const params = el("div", "fm-params");
    const maps = el("div", "fm-maps");
    for (const k of Object.keys(window.ForgeMM.MAPS)) {
      const slot = el("figure", "fm-map"); const box = el("div", "fm-map-img"); box.dataset.map = k;
      slot.append(box, el("figcaption", "", k)); maps.append(slot);
    }
    side.append(params, maps);
    main.append(canvas, side);
    h.append(bar, status, main);
    for (const n of M.graph.nodes) layer.append(nodeBox(n));
    canvasPan(canvas, layer);
    layer.style.transform = "translate(" + M.view.x + "px," + M.view.y + "px)";
    requestAnimationFrame(drawWires);
    showParams();
  }

  function nodeBox(n) {
    const model = window.ForgeMM.modelOf(n) || { inputs: [], outputs: [] };
    const box = el("div", "fm-node" + (n.name === M.sel ? " on" : "") + (n.type === "material" ? " fm-material" : ""));
    box.dataset.node = n.name;
    const p = n.node_position || { x: 0, y: 0 };
    box.style.left = p.x + "px"; box.style.top = p.y + "px";
    const head = el("div", "fm-head", n.type === "material" ? "Material" : (model.name || (M.lib.nodes[n.type] || {}).shader_model?.name || n.type));
    box.append(head);
    const rows = el("div", "fm-rows");
    const ins = el("div", "fm-ins"), outs = el("div", "fm-outs");
    (model.inputs || []).forEach((inp, i) => {
      const r = el("div", "fm-port in"); const dot = el("span", "fm-dot t-" + inp.type); dot.dataset.port = i; dot.dataset.dir = "in";
      r.append(dot, el("span", "", inp.shortdesc || inp.label || inp.name)); ins.append(r);
    });
    (model.outputs || []).forEach((out, i) => {
      const r = el("div", "fm-port out"); const dot = el("span", "fm-dot t-" + (out.type || "rgba")); dot.dataset.port = i; dot.dataset.dir = "out";
      r.append(el("span", "", out.shortdesc || (out.type || "")), dot); outs.append(r);
    });
    rows.append(ins, outs);
    if (n.type !== "material") { const t = document.createElement("canvas"); t.width = 64; t.height = 64; t.className = "fm-thumb"; t.dataset.node = n.name; box.append(t); }
    box.append(rows);
    if (n.type !== "material") {
      const x = el("button", "fm-x", "×"); x.type = "button"; x.title = "Delete node"; x.setAttribute("aria-label", "Delete " + n.name);
      x.addEventListener("click", (e) => {
        e.stopPropagation();
        M.graph.nodes = M.graph.nodes.filter((m) => m !== n);
        M.graph.connections = M.graph.connections.filter((c) => c.from !== n.name && c.to !== n.name);
        if (M.sel === n.name) M.sel = "";
        build(); changed(true);
      });
      head.append(x);
    }
    // drag the node by its head; drag from an output dot to an input dot to connect
    head.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".fm-x")) return;
      M.sel = n.name;
      for (const b of M.host.querySelectorAll(".fm-node")) b.classList.toggle("on", b === box);
      showParams();
      const sx = e.clientX, sy = e.clientY, ox = p.x, oy = p.y;
      head.setPointerCapture(e.pointerId);
      const move = (ev) => { n.node_position = { x: ox + ev.clientX - sx, y: oy + ev.clientY - sy }; box.style.left = n.node_position.x + "px"; box.style.top = n.node_position.y + "px"; drawWires(); };
      const up = () => { head.removeEventListener("pointermove", move); head.removeEventListener("pointerup", up); changed(false); };
      head.addEventListener("pointermove", move); head.addEventListener("pointerup", up);
    });
    box.addEventListener("pointerdown", (e) => {
      const dot = e.target.closest(".fm-dot");
      if (!dot) return;
      e.stopPropagation(); e.preventDefault();
      if (dot.dataset.dir === "in") {   // pull an existing wire off an input
        const i = M.graph.connections.findIndex((c) => c.to === n.name && c.to_port === +dot.dataset.port);
        if (i >= 0) { M.graph.connections.splice(i, 1); drawWires(); changed(true); }
        return;
      }
      const temp = document.createElementNS("http://www.w3.org/2000/svg", "path"); temp.classList.add("fm-wire", "temp");
      M.host.querySelector(".fm-wires").append(temp);
      const from = center(dot);
      const move = (ev) => { const g = M.host.querySelector(".fm-graph").getBoundingClientRect(); temp.setAttribute("d", curve(from, { x: ev.clientX - g.left, y: ev.clientY - g.top })); };
      const up = (ev) => {
        document.removeEventListener("pointermove", move); document.removeEventListener("pointerup", up); temp.remove();
        const hit = document.elementFromPoint(ev.clientX, ev.clientY);
        const target = hit && hit.closest && hit.closest(".fm-dot[data-dir='in']");
        if (!target) return;
        const to = target.closest(".fm-node").dataset.node, port = +target.dataset.port;
        if (to === n.name) return;
        M.graph.connections = M.graph.connections.filter((c) => !(c.to === to && c.to_port === port));
        M.graph.connections.push({ from: n.name, from_port: +dot.dataset.port, to, to_port: port });
        drawWires(); changed(true);
      };
      document.addEventListener("pointermove", move); document.addEventListener("pointerup", up);
    });
    return box;
  }

  function canvasPan(canvas, layer) {
    canvas.addEventListener("pointerdown", (e) => {
      if (e.target !== canvas && !e.target.classList.contains("fm-wires") && e.target !== layer) return;
      const sx = e.clientX - M.view.x, sy = e.clientY - M.view.y;
      canvas.setPointerCapture(e.pointerId);
      const move = (ev) => { M.view = { x: ev.clientX - sx, y: ev.clientY - sy }; layer.style.transform = "translate(" + M.view.x + "px," + M.view.y + "px)"; drawWires(); };
      const up = () => { canvas.removeEventListener("pointermove", move); canvas.removeEventListener("pointerup", up); };
      canvas.addEventListener("pointermove", move); canvas.addEventListener("pointerup", up);
    });
  }

  function center(dot) {
    const g = M.host.querySelector(".fm-graph").getBoundingClientRect(), r = dot.getBoundingClientRect();
    return { x: r.left + r.width / 2 - g.left, y: r.top + r.height / 2 - g.top };
  }

  function curve(a, b) {
    const dx = Math.max(40, Math.abs(b.x - a.x) / 2);
    return "M" + a.x + "," + a.y + " C" + (a.x + dx) + "," + a.y + " " + (b.x - dx) + "," + b.y + " " + b.x + "," + b.y;
  }

  function drawWires() {
    if (!M.host) return;
    const svg = M.host.querySelector(".fm-wires");
    if (!svg) return;
    for (const p of [...svg.querySelectorAll(".fm-wire:not(.temp)")]) p.remove();
    for (const c of M.graph.connections) {
      const a = M.host.querySelector('.fm-node[data-node="' + CSS.escape(c.from) + '"] .fm-dot[data-dir="out"][data-port="' + c.from_port + '"]');
      const b = M.host.querySelector('.fm-node[data-node="' + CSS.escape(c.to) + '"] .fm-dot[data-dir="in"][data-port="' + c.to_port + '"]');
      if (!a || !b) continue;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.classList.add("fm-wire"); path.setAttribute("d", curve(center(a), center(b)));
      svg.append(path);
    }
  }

  // parameters of the selected node: sliders for floats, menus for enums, checkboxes, colours, gradient stops
  function showParams() {
    const box = M.host.querySelector(".fm-params");
    if (!box) return;
    box.replaceChildren();
    const n = M.graph.nodes.find((m) => m.name === M.sel) || M.graph.nodes.find((m) => m.type === "material");
    if (!n) return;
    const model = window.ForgeMM.modelOf(n);
    box.append(el("div", "forge-sub", n.type === "material" ? "Material" : n.name));
    const def = M.lib.nodes[n.type];
    if (def && def.shader_model.longdesc) box.append(el("p", "note fm-desc", def.shader_model.longdesc));
    for (const p of (model && model.parameters) || []) {
      const row = el("label", "fm-param");
      row.append(el("span", "fm-pname", p.shortdesc || p.label || p.name));
      const val = n.parameters[p.name] !== undefined ? n.parameters[p.name] : p.default;
      if (p.type === "float") {
        const r = document.createElement("input"); r.type = "range";
        r.min = String(p.min ?? 0); r.max = String(p.max ?? 1); r.step = String(p.step ?? 0.01); r.value = String(val);
        const num = el("span", "fm-num", Number(val).toFixed(2));
        r.addEventListener("input", () => { num.textContent = Number(r.value).toFixed(2); setParam(n, p.name, Number(r.value)); });
        row.append(r, num);
      } else if (p.type === "enum") {
        const s = document.createElement("select");
        (p.values || []).forEach((v, i) => { const o = new Option(v.name, String(i)); if (i === Number(val)) o.selected = true; s.append(o); });
        s.addEventListener("change", () => setParam(n, p.name, Number(s.value)));
        row.append(s);
      } else if (p.type === "boolean") {
        const c = document.createElement("input"); c.type = "checkbox"; c.checked = !!val;
        c.addEventListener("change", () => setParam(n, p.name, c.checked));
        row.append(c);
      } else if (p.type === "size") {
        const s = document.createElement("select");
        for (let i = p.first || 4; i <= (p.last || 12); i++) { const o = new Option(String(2 ** i), String(i)); if (i === Number(val)) o.selected = true; s.append(o); }
        s.addEventListener("change", () => setParam(n, p.name, Number(s.value)));
        row.append(s);
      } else if (p.type === "color") {
        const c = document.createElement("input"); c.type = "color"; c.value = toHex(val);
        c.addEventListener("input", () => setParam(n, p.name, { ...fromHex(c.value), a: 1 }));
        row.append(c);
      } else if (p.type === "gradient") {
        row.append(gradientEditor(n, p.name, val));
      }
      box.append(row);
    }
  }

  function gradientEditor(n, name, g) {
    const wrap = el("div", "fm-grad");
    const draw = () => {
      wrap.replaceChildren();
      const pts = (g.points || []).slice().sort((a, b) => a.pos - b.pos);
      const strip = el("div", "fm-grad-strip");
      strip.style.background = "linear-gradient(90deg," + pts.map((q) => toHex(q) + " " + Math.round(q.pos * 100) + "%").join(",") + ")";
      wrap.append(strip);
      pts.forEach((q) => {
        const row = el("div", "fm-grad-stop");
        const c = document.createElement("input"); c.type = "color"; c.value = toHex(q);
        const r = document.createElement("input"); r.type = "range"; r.min = "0"; r.max = "1"; r.step = "0.01"; r.value = String(q.pos);
        c.addEventListener("input", () => { Object.assign(q, fromHex(c.value)); M.compiled = null; setParam(n, name, g); draw(); });
        r.addEventListener("change", () => { q.pos = Number(r.value); M.compiled = null; setParam(n, name, g); draw(); });
        row.append(c, r);
        if (pts.length > 2) {
          const x = el("button", "fm-x", "×"); x.type = "button"; x.title = "Remove this colour";
          x.addEventListener("click", () => { g.points = g.points.filter((o) => o !== q); M.compiled = null; setParam(n, name, g); draw(); });
          row.append(x);
        }
        wrap.append(row);
      });
      const addStop = el("button", "quiet small", "+ colour"); addStop.type = "button";
      addStop.addEventListener("click", () => { g.points.push({ pos: 0.5, r: 0.5, g: 0.5, b: 0.5, a: 1 }); M.compiled = null; setParam(n, name, g); draw(); });
      wrap.append(addStop);
    };
    g = n.parameters[name] = JSON.parse(JSON.stringify(g || { points: [] }));
    draw();
    return wrap;
  }

  const toHex = (c) => "#" + [c.r, c.g, c.b].map((v) => Math.round(Math.min(1, Math.max(0, Number(v) || 0)) * 255).toString(16).padStart(2, "0")).join("");
  const fromHex = (h) => ({ r: parseInt(h.slice(1, 3), 16) / 255, g: parseInt(h.slice(3, 5), 16) / 255, b: parseInt(h.slice(5, 7), 16) / 255 });

  // ------------------------------------------------------------------------------------------ files
  async function upload(name, body) {
    const resp = await fetch("/forge/save?name=" + encodeURIComponent(name), {
      method: "POST", headers: { Authorization: "Bearer " + state.token, "Content-Type": "application/octet-stream" }, body,
    }).catch(() => null);
    return resp ? resp.json().catch(() => ({})) : {};
  }

  async function saveMaps() {
    const base = "material-" + new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
    const maps = bake(M.size);
    const saved = [];
    for (const [k, cv] of Object.entries(maps)) {
      const blob = await new Promise((res) => cv.toBlob(res, "image/png"));
      const r = await upload(base + "_" + k + ".png", blob);
      if (r.ok) saved.push(r.name);
    }
    forgeSay(saved.length ? "Saved " + saved.length + " maps in models/ (" + base + "_*.png)" : "Could not save the maps.", !saved.length);
  }

  async function savePtex() {
    const r = await upload("material.ptex", new TextEncoder().encode(JSON.stringify(window.ForgeMM.toPtex(M.graph), null, 1)));
    forgeSay(r.ok ? "Saved models/" + r.name + " (opens in Material Maker)" : r.error || "Could not save.", !r.ok);
    return r;
  }

  function loadPtex() {
    const input = document.createElement("input"); input.type = "file"; input.accept = ".ptex,application/json";
    input.addEventListener("change", () => {
      const f = input.files && input.files[0];
      if (!f) return;
      f.text().then((t) => {
        const { graph, skipped } = window.ForgeMM.fromPtex(JSON.parse(t));
        M.graph = graph; M.sel = ""; build(); changed(true);
        forgeSay(skipped.length ? "Loaded; not in Forge yet (open in Material Maker): " + skipped.slice(0, 4).join(", ") : "Loaded " + f.name);
      }).catch((e) => forgeSay("Not a .ptex: " + e.message, true));
    });
    input.click();
  }

  async function openInMM() {
    const st = await api("/forge/mm").catch(() => null);
    if (!st || !st.installed) {
      forgeSay("Material Maker is not installed here - get it (free, MIT) from " + ((st && st.download) || "github.com/RodZill4/material-maker/releases"), true);
      if (st && st.download) api("/open", { url: st.download }).catch(() => {});
      return;
    }
    const saved = await savePtex();
    if (!saved.ok) return;
    const r = await api("/forge/mm/open", { name: saved.name }).catch(() => null);
    forgeSay(r && r.ok ? "Opened " + saved.name + " in Material Maker" : (r && r.error) || "Could not open it.", !(r && r.ok));
  }

  window.ForgeMaterials = { open, bake, renderMap, refresh, state: M, draw };
})();
