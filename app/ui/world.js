// LOKI World: your agents as characters in a small 3D world, drawn with plain WebGL (no
// libraries, CSP-clean). The engine's GET /world says who is there, where they work and
// what they are doing - only real state, never invented (engine/events.py world()). This
// file just animates it: agents walk to their station, bob while they work, glow red when
// blocked, and show what they last said on the team board.
//
// Two views share one renderer: behind the home screen (dim, slowly orbiting, "the world
// happening in the background") and full size in Settings > LOKI World (drag to orbit,
// wheel to zoom). LOKI_WORLD (Settings > General) picks background | panel | off.
"use strict";

const World = {
  mode: "background", views: {}, agents: {}, data: null, lastFetch: 0, fetching: false,
  reduced: window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
};

// ---------------------------------------------------------------- math (column-major 4x4)
const M4 = {
  ident() { return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]; },
  mul(a, b) {
    const o = new Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
    return o;
  },
  persp(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
  },
  lookAt(eye, at, up) {
    const z = norm(sub(eye, at)), x = norm(cross(up, z)), y = cross(z, x);
    return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0,
      -dot(x, eye), -dot(y, eye), -dot(z, eye), 1];
  },
  trs(t, ry, s) {
    const c = Math.cos(ry), n = Math.sin(ry);
    return [c * s[0], 0, -n * s[0], 0, 0, s[1], 0, 0, n * s[2], 0, c * s[2], 0, t[0], t[1], t[2], 1];
  },
};
function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function norm(a) { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; }
function hexRgb(hex, fallback) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return fallback;
  const n = parseInt(m[1], 16);
  return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
}

// ---------------------------------------------------------------- meshes
function boxMesh() {
  const p = [], n = [];
  const faces = [[[1, 0, 0], [0, 1, 0], [0, 0, 1]], [[-1, 0, 0], [0, 1, 0], [0, 0, -1]], [[0, 1, 0], [0, 0, 1], [1, 0, 0]],
    [[0, -1, 0], [0, 0, -1], [1, 0, 0]], [[0, 0, 1], [1, 0, 0], [0, 1, 0]], [[0, 0, -1], [-1, 0, 0], [0, 1, 0]]];
  for (const [nn, u, v] of faces) {
    const c = nn.map((x) => x * 0.5);
    const corner = (a, b) => [c[0] + (u[0] * a + v[0] * b) * 0.5, c[1] + (u[1] * a + v[1] * b) * 0.5, c[2] + (u[2] * a + v[2] * b) * 0.5];
    const q = [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, -1), corner(1, 1), corner(-1, 1)];
    for (const v3 of q) { p.push(...v3); n.push(...nn); }
  }
  return { p, n };
}

function cylinderMesh(seg = 18) {
  const p = [], n = [];
  for (let i = 0; i < seg; i++) {
    const a0 = (i / seg) * Math.PI * 2, a1 = ((i + 1) / seg) * Math.PI * 2;
    const x0 = Math.cos(a0) * 0.5, z0 = Math.sin(a0) * 0.5, x1 = Math.cos(a1) * 0.5, z1 = Math.sin(a1) * 0.5;
    const n0 = [Math.cos(a0), 0, Math.sin(a0)], n1 = [Math.cos(a1), 0, Math.sin(a1)];
    p.push(x0, -0.5, z0, x1, 0.5, z1, x1, -0.5, z1, x0, -0.5, z0, x0, 0.5, z0, x1, 0.5, z1);
    n.push(...n0, ...n1, ...n1, ...n0, ...n0, ...n1);
    p.push(0, 0.5, 0, x1, 0.5, z1, x0, 0.5, z0); n.push(0, 1, 0, 0, 1, 0, 0, 1, 0);
    p.push(0, -0.5, 0, x0, -0.5, z0, x1, -0.5, z1); n.push(0, -1, 0, 0, -1, 0, 0, -1, 0);
  }
  return { p, n };
}

function sphereMesh(rings = 9, seg = 14) {
  const p = [], n = [];
  const at = (r, s) => {
    const th = (r / rings) * Math.PI, ph = (s / seg) * Math.PI * 2;
    return [Math.sin(th) * Math.cos(ph) * 0.5, Math.cos(th) * 0.5, Math.sin(th) * Math.sin(ph) * 0.5];
  };
  for (let r = 0; r < rings; r++) for (let s = 0; s < seg; s++) {
    const a = at(r, s), b = at(r + 1, s), c = at(r + 1, s + 1), d = at(r, s + 1);
    for (const v of [a, b, c, a, c, d]) { p.push(...v); n.push(...norm(v)); }
  }
  return { p, n };
}

// ---------------------------------------------------------------- renderer
const VS = "attribute vec3 p; attribute vec3 n; uniform mat4 M; uniform mat4 VP; varying vec3 vn; varying vec3 wp;" +
  "void main(){ vec4 w = M * vec4(p,1.0); wp = w.xyz; vn = mat3(M) * n; gl_Position = VP * w; }";
const FS = "precision mediump float; varying vec3 vn; varying vec3 wp; uniform vec3 C; uniform float A; uniform float E;" +
  "uniform vec3 eye; uniform vec3 fogc; void main(){ vec3 N = normalize(vn); vec3 L = normalize(vec3(0.45,0.85,0.35));" +
  "float d = max(dot(N,L),0.0); float h = 0.5 + 0.5*N.y; vec3 col = C*(0.28 + 0.62*d) + C*0.22*h + C*E;" +
  "float rim = pow(1.0 - max(dot(N, normalize(eye-wp)),0.0), 3.0); col += vec3(0.25,0.55,0.75)*rim*0.35;" +
  "float f = clamp((length(eye-wp)-9.0)/22.0, 0.0, 1.0); gl_FragColor = vec4(mix(col, fogc, f), A); }";

function makeView(canvas, labels, opts) {
  let gl = null;
  try { gl = canvas.getContext("webgl", { antialias: true, alpha: true, premultipliedAlpha: false }); } catch (_) { gl = null; }
  if (!gl) return null;
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
  const prog = gl.createProgram();
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
  const loc = { p: gl.getAttribLocation(prog, "p"), n: gl.getAttribLocation(prog, "n") };
  for (const u of ["M", "VP", "C", "A", "E", "eye", "fogc"]) loc[u] = gl.getUniformLocation(prog, u);
  const upload = (mesh) => {
    const pb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, pb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(mesh.p), gl.STATIC_DRAW);
    const nb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, nb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(mesh.n), gl.STATIC_DRAW);
    return { pb, nb, count: mesh.p.length / 3 };
  };
  const meshes = { box: upload(boxMesh()), cyl: upload(cylinderMesh()), sph: upload(sphereMesh()) };
  return { canvas, labels, gl, prog, loc, meshes, opts, yaw: 0.6, pitch: 0.62, dist: opts.dist || 15, drag: null,
           labelNodes: {}, visible: false, raf: 0, last: 0 };
}

function draw(view, mesh, matrix, color, alpha = 1, emit = 0) {
  const { gl, loc } = view;
  const m = view.meshes[mesh];
  gl.bindBuffer(gl.ARRAY_BUFFER, m.pb); gl.vertexAttribPointer(loc.p, 3, gl.FLOAT, false, 0, 0); gl.enableVertexAttribArray(loc.p);
  gl.bindBuffer(gl.ARRAY_BUFFER, m.nb); gl.vertexAttribPointer(loc.n, 3, gl.FLOAT, false, 0, 0); gl.enableVertexAttribArray(loc.n);
  gl.uniformMatrix4fv(loc.M, false, new Float32Array(matrix));
  gl.uniform3fv(loc.C, color); gl.uniform1f(loc.A, alpha); gl.uniform1f(loc.E, emit);
  gl.drawArrays(gl.TRIANGLES, 0, m.count);
}

// ---------------------------------------------------------------- the place
const STATION_LAYOUT = {
  "hall": { pos: [0, 0], color: "#8fb3d9", label: "Hall" },
  "library": { pos: [-5.2, -2.6], color: "#88c0d0", label: "Library" },
  "drafting table": { pos: [-1.8, -5.6], color: "#b48ead", label: "Drafting" },
  "workshop": { pos: [3.0, -4.8], color: "#a3be8c", label: "Workshop" },
  "test bench": { pos: [5.6, -0.4], color: "#ebcb8b", label: "Test bench" },
  "review desk": { pos: [3.6, 3.8], color: "#d08770", label: "Review" },
  "terminal": { pos: [-2.4, 4.6], color: "#5e81ac", label: "Terminal" },
};
const STATE_COLOR = { working: "#8fb3d9", waiting: "#9aa0aa", blocked: "#ff7777", done: "#a3be8c", failed: "#bf616a", idle: "#9aa0aa" };

function stationPos(name) {
  const s = STATION_LAYOUT[name] || STATION_LAYOUT.workshop;
  return s.pos;
}

function syncAgents(list) {
  const seen = new Set();
  const counts = {};
  for (const a of list || []) {
    seen.add(a.id);
    const base = stationPos(a.station);
    const i = counts[a.station] = (counts[a.station] || 0) + 1;
    const offset = i === 1 ? [0, 1.25] : [Math.cos(i * 2.1) * 1.3, Math.sin(i * 2.1) * 1.3];
    const target = [base[0] + offset[0], base[1] + offset[1]];
    let w = World.agents[a.id];
    if (!w) {
      const hall = stationPos("hall");
      w = World.agents[a.id] = { x: hall[0] + (Math.random() - 0.5), z: hall[1] + (Math.random() - 0.5), ry: 0, phase: Math.random() * 6, said: "", saidAt: 0 };
    }
    w.data = a;
    w.tx = target[0]; w.tz = target[1];
    w.color = hexRgb(a.color, hexRgb(a.id === "loki" ? "#a3be8c" : (STATION_LAYOUT[a.station] || {}).color, [0.6, 0.7, 0.85]));
    if (a.last_message && a.last_message !== w.said) { w.said = a.last_message; w.saidAt = performance.now(); }
  }
  for (const id of Object.keys(World.agents)) if (!seen.has(id)) delete World.agents[id];
}

async function fetchWorld() {
  if (World.fetching || typeof state === "undefined" || !state.token) return;
  World.fetching = true;
  try {
    const data = await api("/world");
    if (data && data.ok) { World.data = data; syncAgents(data.agents); renderLegend(); }
  } catch (_) { /* engine restarting */ }
  World.fetching = false;
  World.lastFetch = performance.now();
}

function renderLegend() {
  const box = document.getElementById("world-legend");
  if (!box || !World.data) return;
  box.replaceChildren();
  for (const a of World.data.agents) {
    const row = el("div", "legend-row");
    const dot = el("span", "agent-dot");
    dot.style.background = a.color || STATE_COLOR[a.state] || "#8fb3d9";
    row.append(dot, el("b", "", a.name), el("span", "pill " + (a.state === "working" ? "working" : a.state === "blocked" ? "blocked" : a.state === "done" ? "done" : ""), a.state),
               el("span", "muted", (a.station || "") + (a.task ? " · " + a.task : "")));
    box.append(row);
  }
}

// ---------------------------------------------------------------- frame
function frame(view, now) {
  const { gl, canvas } = view;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(canvas.clientWidth * dpr)), h = Math.max(1, Math.round(canvas.clientHeight * dpr));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const dt = Math.min(0.1, (now - (view.last || now)) / 1000);
  view.last = now;
  if (!view.drag && !World.reduced) view.yaw += dt * (view.opts.spin || 0.05);
  gl.viewport(0, 0, w, h);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.enable(gl.DEPTH_TEST);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  gl.useProgram(view.prog);
  const eye = [Math.cos(view.yaw) * Math.cos(view.pitch) * view.dist, Math.sin(view.pitch) * view.dist, Math.sin(view.yaw) * Math.cos(view.pitch) * view.dist];
  const vp = M4.mul(M4.persp(0.8, w / h, 0.1, 80), M4.lookAt(eye, [0, 0.6, 0], [0, 1, 0]));
  gl.uniformMatrix4fv(view.loc.VP, false, new Float32Array(vp));
  gl.uniform3fv(view.loc.eye, eye);
  gl.uniform3fv(view.loc.fogc, [0.12, 0.12, 0.15]);
  const t = now / 1000;

  // ground: a wide disk, an inner ring, paths to every station
  draw(view, "cyl", M4.trs([0, -0.15, 0], 0, [17, 0.3, 17]), [0.17, 0.18, 0.22]);
  draw(view, "cyl", M4.trs([0, 0.01, 0], 0, [3.4, 0.04, 3.4]), [0.22, 0.24, 0.3]);
  for (const [name, s] of Object.entries(STATION_LAYOUT)) {
    const [x, z] = s.pos;
    const c = hexRgb(s.color, [0.5, 0.6, 0.7]);
    if (name !== "hall") {
      const len = Math.hypot(x, z), ang = Math.atan2(x, z);
      draw(view, "box", M4.trs([x / 2, 0.005, z / 2], ang, [0.5, 0.02, len]), [0.21, 0.22, 0.27]);
    }
    draw(view, "cyl", M4.trs([x, 0.03, z], 0, [2.4, 0.06, 2.4]), c.map((v) => v * 0.35));
    if (name === "hall") {
      // the conductor's spire: an L-shaped mark, LOKI's sign
      draw(view, "box", M4.trs([x - 0.25, 1.1, z], 0, [0.3, 2.2, 0.3]), [0.3, 0.75, 0.7], 1, 0.15);
      draw(view, "box", M4.trs([x + 0.15, 0.15, z], 0, [1.1, 0.3, 0.3]), [0.3, 0.75, 0.7], 1, 0.15);
    } else {
      draw(view, "box", M4.trs([x, 0.45, z], Math.atan2(x, z), [1.5, 0.12, 0.8]), [0.36, 0.32, 0.3]);
      draw(view, "box", M4.trs([x - 0.6, 0.2, z], 0, [0.08, 0.4, 0.08]), [0.3, 0.27, 0.25]);
      draw(view, "box", M4.trs([x + 0.6, 0.2, z], 0, [0.08, 0.4, 0.08]), [0.3, 0.27, 0.25]);
      const busy = Object.values(World.agents).some((a) => a.data && a.data.station === name && a.data.state === "working");
      draw(view, "sph", M4.trs([x, 1.35 + Math.sin(t * 1.4 + x) * 0.06, z], 0, [0.34, 0.34, 0.34]), c, 1, busy ? 0.7 : 0.15);
    }
  }

  // agents
  const proj = (p) => {
    const v = [vp[0] * p[0] + vp[4] * p[1] + vp[8] * p[2] + vp[12], vp[1] * p[0] + vp[5] * p[1] + vp[9] * p[2] + vp[13],
      vp[3] * p[0] + vp[7] * p[1] + vp[11] * p[2] + vp[15]];
    if (v[2] <= 0) return null;
    return [(v[0] / v[2] * 0.5 + 0.5) * canvas.clientWidth, (1 - (v[1] / v[2] * 0.5 + 0.5)) * canvas.clientHeight];
  };
  const seen = new Set();
  for (const [id, a] of Object.entries(World.agents)) {
    const d = a.data || {};
    const dx = a.tx - a.x, dz = a.tz - a.z, dist = Math.hypot(dx, dz);
    const walking = dist > 0.05;
    if (walking) {
      const step = Math.min(dist, dt * 2.2);
      a.x += dx / dist * step; a.z += dz / dist * step;
      a.ry = Math.atan2(dx, dz);
    } else if (d.station) {
      const s = stationPos(d.station);
      a.ry = Math.atan2(s[0] - a.x, s[1] - a.z);
    }
    a.phase += dt * (walking ? 9 : d.state === "working" ? 7 : 2);
    const bob = walking ? Math.abs(Math.sin(a.phase)) * 0.12 : d.state === "working" ? Math.abs(Math.sin(a.phase)) * 0.06 : Math.sin(a.phase) * 0.02;
    const col = d.state === "failed" ? [0.75, 0.38, 0.42] : a.color;
    const big = id === "loki" ? 1.25 : 1;
    draw(view, "cyl", M4.trs([a.x, 0.04, a.z], 0, [0.75 * big, 0.02, 0.75 * big]), [0, 0, 0], 0.35);
    draw(view, "cyl", M4.trs([a.x, 0.42 * big + bob, a.z], a.ry, [0.42 * big, 0.62 * big, 0.42 * big]), col);
    draw(view, "sph", M4.trs([a.x, 0.98 * big + bob, a.z], a.ry, [0.42 * big, 0.42 * big, 0.42 * big]), col.map((v) => Math.min(1, v * 1.12 + 0.05)));
    const fx = Math.sin(a.ry) * 0.17 * big, fz = Math.cos(a.ry) * 0.17 * big;
    draw(view, "box", M4.trs([a.x + fx, 1.02 * big + bob, a.z + fz], a.ry, [0.26 * big, 0.08 * big, 0.06]), [0.08, 0.1, 0.14], 1, 0.0);
    if (d.state === "working") {
      draw(view, "box", M4.trs([a.x, 1.6 * big + Math.sin(t * 3 + a.phase) * 0.05, a.z], t * 2.4, [0.14, 0.14, 0.14]), [0.56, 0.8, 1], 1, 0.9);
    }
    if (d.state === "blocked") draw(view, "cyl", M4.trs([a.x, 0.06, a.z], 0, [1.1, 0.03, 1.1]), [1, 0.47, 0.47], 0.5 + 0.3 * Math.sin(t * 5), 0.8);
    if (d.state === "done") draw(view, "sph", M4.trs([a.x, 1.6 * big, a.z], 0, [0.16, 0.16, 0.16]), [0.64, 0.75, 0.55], 1, 0.9);

    // the label above the head, and what it last said
    if (view.labels) {
      seen.add(id);
      let node = view.labelNodes[id];
      if (!node) {
        node = view.labelNodes[id] = el("div", "wlabel");
        node.append(el("b"), el("span"), el("i"));
        view.labels.append(node);
      }
      const at = proj([a.x, 1.6 * big + 0.35, a.z]);
      node.hidden = !at;
      if (at) {
        node.style.transform = "translate(" + Math.round(at[0]) + "px," + Math.round(at[1]) + "px) translate(-50%,-100%)";
        node.children[0].textContent = d.name || id;
        node.children[1].textContent = view.opts.detail ? (d.state + (d.task ? " · " + d.task.slice(0, 48) : "")) : "";
        const fresh = a.said && performance.now() - a.saidAt < 9000;
        node.children[2].textContent = fresh ? "“" + a.said.slice(0, 90) + "”" : "";
        node.classList.toggle("speaking", !!fresh);
      }
    }
  }
  if (view.labels) for (const id of Object.keys(view.labelNodes)) if (!seen.has(id)) { view.labelNodes[id].remove(); delete view.labelNodes[id]; }
}

function loop(view) {
  const tick = (now) => {
    if (!view.visible) { view.raf = 0; return; }
    if (now - World.lastFetch > 2500) fetchWorld();
    frame(view, now);
    view.raf = requestAnimationFrame(tick);
  };
  if (!view.raf) view.raf = requestAnimationFrame(tick);
}

function setVisible(view, on) {
  if (!view) return;
  view.visible = on && !document.hidden;
  if (view.visible) { view.last = 0; loop(view); }
}

function attachControls(view) {
  const c = view.canvas;
  c.addEventListener("pointerdown", (e) => { view.drag = { x: e.clientX, y: e.clientY }; c.setPointerCapture(e.pointerId); });
  c.addEventListener("pointermove", (e) => {
    if (!view.drag) return;
    view.yaw += (e.clientX - view.drag.x) * 0.008;
    view.pitch = Math.max(0.2, Math.min(1.35, view.pitch + (e.clientY - view.drag.y) * 0.006));
    view.drag = { x: e.clientX, y: e.clientY };
  });
  c.addEventListener("pointerup", () => { view.drag = null; });
  c.addEventListener("wheel", (e) => { e.preventDefault(); view.dist = Math.max(7, Math.min(28, view.dist + e.deltaY * 0.01)); }, { passive: false });
}

// ---------------------------------------------------------------- the two views
function backgroundWanted() {
  const main = document.getElementById("main");
  return World.mode === "background" && main && main.classList.contains("home") && document.getElementById("settings").hidden;
}

function refreshBackground() {
  const view = World.views.bg;
  const box = document.querySelector(".world-bg");
  if (!box) return;
  const on = !!view && backgroundWanted();
  box.classList.toggle("on", on);
  setVisible(view, on);
}

function showWorldPanel() {
  if (!World.views.panel) {
    const canvas = document.getElementById("world-panel-canvas");
    World.views.panel = canvas && makeView(canvas, document.getElementById("world-panel-labels"), { dist: 16, spin: 0.03, detail: true });
    if (World.views.panel) attachControls(World.views.panel);
    else if (canvas) canvas.replaceWith(el("p", "note", "This window cannot draw 3D (no WebGL). The list below shows the same agents."));
  }
  fetchWorld();
  setVisible(World.views.panel, true);
  refreshBackground();
}

function hideWorldPanel() {
  setVisible(World.views.panel, false);
  setTimeout(refreshBackground, 0);
}

function setWorldMode(mode) {
  World.mode = mode || "background";
  refreshBackground();
}

async function startWorld() {
  const canvas = document.getElementById("world-bg-canvas");
  if (canvas) World.views.bg = makeView(canvas, document.getElementById("world-bg-labels"), { dist: 17, spin: 0.045, detail: false });
  try {
    const data = await api("/settings/general");
    if (data && data.ok) World.mode = data.values.LOKI_WORLD || "background";
  } catch (_) { /* default */ }
  const main = document.getElementById("main");
  if (main) new MutationObserver(refreshBackground).observe(main, { attributes: true, attributeFilter: ["class"] });
  const settings = document.getElementById("settings");
  if (settings) new MutationObserver(refreshBackground).observe(settings, { attributes: true, attributeFilter: ["hidden"] });
  document.addEventListener("visibilitychange", () => {
    refreshBackground();
    if (World.views.panel && !document.getElementById("settings").hidden &&
        !document.querySelector('[data-panel="world"]').hidden) setVisible(World.views.panel, true);
  });
  refreshBackground();
}

// app.js calls afterStart() once the engine answers; chain onto it.
(function () {
  const previous = window.afterStart;
  window.afterStart = function () {
    if (typeof previous === "function") previous();
    startWorld();
  };
})();
