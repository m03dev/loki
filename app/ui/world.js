// LOKI World: your agents as characters in a small 3D world, drawn with plain WebGL (no
// libraries, CSP-clean). The engine's GET /world says who is there, where they work and
// what they are doing - only real state, never invented (engine/events.py world()). This
// file just animates it: agents walk the paths to their station, act out the work there
// (reading, hammering, testing, typing), glow red when blocked, cheer when done, and show
// what they last said on the team board.
//
// It plays like a little life sim: idle agents wander the plaza, sit on benches and chat
// (a "···" bubble - never invented words), each team has a banner with its real stages,
// and in Settings > LOKI World you can click an agent to inspect it (state, task, team
// stage, time on task, last message) or follow it with the camera. Ambient life - wander,
// chat, fireflies, birds, the waterfall - is decoration only; every label is real state.
//
// Two views share one renderer: behind the home screen (dim, slowly orbiting, "the world
// happening in the background") and full size in Settings > LOKI World (drag to orbit,
// wheel or pinch to zoom, click to inspect, double-click to follow). LOKI_WORLD (Settings >
// General) picks background | panel | off.
//
// The look: a 3D pixel-art, cel-shaded floating island. The scene is drawn into a small
// low-resolution framebuffer (1/2 - 1/3 of the canvas, an integer scale; denser than the first
// 1/3 - 1/4, with 32 colour levels and 4 cel bands) and blown up with
// NEAREST filtering plus a light ordered dither, so it reads as chunky pixels. Lighting is
// quantized into bands (a sun or moon, a sky/ground hemisphere fill, a rim light and the
// station lamps as small point lights), and every solid gets a dark ink outline from an
// inflated back-face hull. Sky, island, trees, rocks, lamps and little station buildings are
// all built here from boxes, cylinders, cones and spheres - nothing is loaded.
//
// Staying smooth: everything that never moves is baked ONCE into a single vertex buffer
// (one draw for the solids, one for their outlines, one for their shadows), the clouds and
// islets are one more buffer turned by one matrix, and a frame-time watcher makes the world
// pixels coarser when a machine falls behind (and finer again when it catches up) - the
// pixel-art look hides it. A lost WebGL context (sleep, GPU switch) is rebuilt.
"use strict";

const World = {
  mode: "background", views: {}, agents: {}, data: null, lastFetch: 0, fetching: false,
  reduced: window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  pixel: null,   // set a number (CSS px per world pixel) to override every view's pixel size
  hour: null,    // set 0-24 to pin the time of day (otherwise the local clock tints the sky)
  adaptive: true,   // coarser world pixels when frames run late (World.adaptive = false to pin)
  engine: "babylon",   // Babylon.js in the pixel cel-shaded look (default); "classic" = the hand-written WebGL one; "three" = three.js
  selected: "", particles: [], seats: {}, ripples: [], fish: null, fishAt: 0,
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
function mix3(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]; }
function scale3(a, k) { return [a[0] * k, a[1] * k, a[2] * k]; }
function smooth(e0, e1, x) { const t = Math.max(0, Math.min(1, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); }
function lerp(a, b, t) { return a + (b - a) * t; }
function angLerp(a, b, t) { let d = b - a; while (d > Math.PI) d -= Math.PI * 2; while (d < -Math.PI) d += Math.PI * 2; return a + d * t; }
function hexRgb(hex, fallback) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return fallback;
  const n = parseInt(m[1], 16);
  return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
}
function seeded(seed) {   // a small deterministic random, so the island is the same every time
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}
function hashColor(text) {   // a stable, pleasant colour per team id
  let h = 2166136261;
  for (const ch of String(text || "")) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  const hue = (h % 360) / 360, k = (n) => (n + hue * 12) % 12;
  const f = (n) => 0.62 - 0.32 * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
  return [f(0), f(8), f(4)];
}
function ago(seconds) {
  if (!seconds || seconds < 0) return "";
  if (seconds < 60) return Math.round(seconds) + " s";
  if (seconds < 3600) return Math.round(seconds / 60) + " min";
  return (seconds / 3600).toFixed(seconds < 36000 ? 1 : 0) + " h";
}

// ---------------------------------------------------------------- meshes (all CCW = front)
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

function cylinderMesh(seg = 12) {
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

function coneMesh(seg = 7) {   // faceted (flat normals): low-poly trees, roofs, the island's rock
  const p = [], n = [];
  for (let i = 0; i < seg; i++) {
    const a0 = (i / seg) * Math.PI * 2, a1 = ((i + 1) / seg) * Math.PI * 2;
    const b0 = [Math.cos(a0) * 0.5, -0.5, Math.sin(a0) * 0.5], b1 = [Math.cos(a1) * 0.5, -0.5, Math.sin(a1) * 0.5], top = [0, 0.5, 0];
    const fn = norm(cross(sub(top, b0), sub(b1, b0)));
    p.push(...b0, ...top, ...b1); n.push(...fn, ...fn, ...fn);
    p.push(0, -0.5, 0, ...b0, ...b1); n.push(0, -1, 0, 0, -1, 0, 0, -1, 0);
  }
  return { p, n };
}

function sphereMesh(rings = 7, seg = 10) {
  const p = [], n = [];
  const at = (r, s) => {
    const th = (r / rings) * Math.PI, ph = (s / seg) * Math.PI * 2;
    return [Math.sin(th) * Math.cos(ph) * 0.5, Math.cos(th) * 0.5, Math.sin(th) * Math.sin(ph) * 0.5];
  };
  for (let r = 0; r < rings; r++) for (let s = 0; s < seg; s++) {
    const a = at(r, s), b = at(r + 1, s), c = at(r + 1, s + 1), d = at(r, s + 1);
    for (const v of [a, c, b, a, d, c]) { p.push(...v); n.push(...norm(v)); }
  }
  return { p, n };
}

function quadMesh() {   // corners in -1..1, for the sky, the blit, shadows and glows
  const p = [-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, -1, 0, 1, 1, 0, -1, 1, 0];
  return { p, n: p.map(() => 0) };
}

// Water surfaces are fine grids so the vertex waves have something to move: a polar disc
// (pool, pond), a flat strip (stream) and an upright sheet (waterfall), all in -0.5..0.5.
function discGrid(rings = 6, seg = 40) {
  const p = [], n = [];
  const at = (r, s) => { const a = (s / seg) * Math.PI * 2, k = (r / rings) * 0.5; return [Math.cos(a) * k, 0, Math.sin(a) * k]; };
  for (let r = 0; r < rings; r++) for (let k = 0; k < seg; k++) {
    const a = at(r, k), b = at(r + 1, k), c = at(r + 1, k + 1), d = at(r, k + 1);
    for (const v of [a, c, b, a, d, c]) { p.push(...v); n.push(0, 1, 0); }
  }
  return { p, n };
}
function planeGrid(nx, nz, upright) {
  const p = [], n = [];
  const at = (i, j) => { const u = i / nx - 0.5, v = j / nz - 0.5; return upright ? [u, v, 0] : [u, 0, v]; };
  const nn = upright ? [0, 0, 1] : [0, 1, 0];
  for (let i = 0; i < nx; i++) for (let j = 0; j < nz; j++) {
    const a = at(i, j), b = at(i + 1, j), c = at(i + 1, j + 1), d = at(i, j + 1);
    const tri = upright ? [a, b, c, a, c, d] : [a, c, b, a, d, c];
    for (const v of tri) { p.push(...v); n.push(...nn); }
  }
  return { p, n };
}

// The shapes, built once and shared by every view (and by the baker).
const MESH_SRC = { box: boxMesh(), cyl: cylinderMesh(), cyl6: cylinderMesh(7), cone: coneMesh(), pyr: coneMesh(4),
  sph: sphereMesh(), sph4: sphereMesh(4, 6), quad: quadMesh(),
  wdisc: discGrid(), wstrip: planeGrid(3, 24, false), wsheet: planeGrid(4, 40, true) };

// ---------------------------------------------------------------- shaders
// Solids. The normal goes through the inverse scale (IS = 1/s^2) so squashed shapes still
// light correctly.
const VS = "attribute vec3 p; attribute vec3 n; uniform mat4 M; uniform mat4 VP; uniform vec3 IS;" +
  "varying vec3 vn; varying vec3 wp;" +
  "void main(){ vec4 w = M * vec4(p,1.0); wp = w.xyz; vn = mat3(M) * (n * IS); gl_Position = VP * w; }";

// The baked static scene: positions and normals are already in world space (M only turns
// the cloud batch), and each vertex carries its colour (c) and its material (x = emission,
// checker, highlight, water).
const BAKED_VS = "attribute vec3 p; attribute vec3 n; attribute vec3 c; attribute vec4 x; uniform mat4 M; uniform mat4 VP;" +
  "varying vec3 vn; varying vec3 wp; varying vec3 C; varying vec4 X;" +
  "void main(){ vec4 w = M * vec4(p,1.0); wp = w.xyz; vn = mat3(M) * n; C = c; X = x; gl_Position = VP * w; }";

// Cel shading: the sun term is quantized into BANDS hard steps between a cool shadow tone
// and the lit tone; the hemisphere fill, the station lamps, the rim and a toon highlight are
// stepped too, so every surface reads as flat painted colour.
function fragmentShader(baked) {
  const head = baked
    ? "#define E X.x\n#define G X.y\n#define S X.z\nprecision mediump float; varying vec3 vn; varying vec3 wp; varying vec3 C; varying vec4 X; uniform float A;"
    : "precision mediump float; varying vec3 vn; varying vec3 wp; uniform vec3 C; uniform float A; uniform float E; uniform float G; uniform float S;";
  return head +
  "uniform vec3 eye; uniform vec3 sunDir; uniform vec3 sunCol; uniform vec3 skyAmb; uniform vec3 gndAmb; uniform float T;" +
  "uniform vec3 shadeTint; uniform vec3 rimCol; uniform vec3 fogc; uniform vec2 fogr;" +
  "uniform vec3 LP[10]; uniform vec4 LC[10];" +
  "const float BANDS = 4.0;" +
  "float cel(float x){ return min(floor(clamp(x,0.0,1.0) * BANDS) / (BANDS - 1.0), 1.0); }" +
  "void main(){ vec3 N = normalize(vn); vec3 V = normalize(eye - wp);" +
  " vec3 base = C;" +
  " if (G > 0.0) { float ch = mod(floor(wp.x * G) + floor(wp.z * G), 2.0); base *= 0.9 + 0.1 * ch; }" +
  " float b = cel(dot(N, sunDir) * 0.55 + 0.42);" +
  " vec3 amb = mix(gndAmb, skyAmb, step(0.0, N.y) * 0.5 + step(0.6, N.y) * 0.5);" +
  " vec3 col = mix(base * amb * shadeTint, base * (amb + sunCol), b);" +
  " for (int i = 0; i < 10; i++) { vec3 d = LP[i] - wp; float r = length(d);" +
  "  float at = clamp(1.0 - r / LC[i].w, 0.0, 1.0) * (0.35 + 0.65 * max(dot(N, d / max(r, 0.001)), 0.0));" +
  "  col += (base * 0.8 + 0.12) * LC[i].rgb * (step(0.15, at) * 0.5 + step(0.5, at) * 0.5); }" +
  " float rim = 1.0 - max(dot(N, V), 0.0); col += rimCol * step(0.72, rim) * (0.3 + 0.7 * b) * (1.0 - step(0.8, N.y));" +
  " vec3 H = normalize(sunDir + V); col += sunCol * step(0.96, dot(N, H)) * S;" +
  " col += base * E;" +
  " float f = clamp((length(eye - wp) - fogr.x) / fogr.y, 0.0, 1.0); f = floor(f * 4.0) / 4.0;" +
  " gl_FragColor = vec4(mix(col, fogc, f * 0.6), A); }";
}
const FS = fragmentShader(false);
const BAKED_FS = fragmentShader(true);
const LIGHT_UNIFORMS = ["VP", "eye", "sunDir", "sunCol", "skyAmb", "gndAmb", "shadeTint", "rimCol", "fogc", "fogr", "LP", "LC", "T", "A", "M"];

// Ink outlines: the same solid drawn again, back faces only, pushed out along its own
// direction from the centre by about one low-res pixel (OL grows with distance so the line
// stays one pixel wide), in a dark ink tinted by the object's colour.
const OUTLINE_VS = "attribute vec3 p; attribute vec3 n; uniform mat4 M; uniform mat4 VP; uniform vec3 oeye; uniform float OL;" +
  "varying float dist;" +
  "void main(){ vec4 w = M * vec4(p,1.0); vec3 dir = normalize(mat3(M) * p + vec3(0.0, 0.0001, 0.0));" +
  " dist = length(oeye - w.xyz); w.xyz += dir * OL * dist; gl_Position = VP * w; }";
const OUTLINE_FS = "precision mediump float; varying float dist; uniform vec3 OC; uniform vec3 ofog; uniform vec2 ofogr;" +
  "void main(){ float f = clamp((dist - ofogr.x) / ofogr.y, 0.0, 1.0); f = floor(f * 4.0) / 4.0;" +
  " gl_FragColor = vec4(mix(OC, ofog, f * 0.6), 1.0); }";
// ...and baked: n carries each solid's centre, c its ink colour.
const BAKED_OUTLINE_VS = "attribute vec3 p; attribute vec3 n; attribute vec3 c; uniform mat4 M; uniform mat4 VP; uniform vec3 oeye; uniform float OL;" +
  "varying float dist; varying vec3 ic;" +
  "void main(){ vec4 w = M * vec4(p,1.0); vec3 ctr = (M * vec4(n,1.0)).xyz; vec3 dir = normalize(w.xyz - ctr + vec3(0.0, 0.0001, 0.0));" +
  " dist = length(oeye - w.xyz); w.xyz += dir * OL * dist; ic = c; gl_Position = VP * w; }";
const BAKED_OUTLINE_FS = "precision mediump float; varying float dist; varying vec3 ic; uniform vec3 ofog; uniform vec2 ofogr;" +
  "void main(){ float f = clamp((dist - ofogr.x) / ofogr.y, 0.0, 1.0); f = floor(f * 4.0) / 4.0;" +
  " gl_FragColor = vec4(mix(ic, ofog, f * 0.6), 1.0); }";

// Water: its own program, drawn after the solids and before the see-through things.
// Every body of water knows its shape (a disc with up to two blocks standing in it, or a
// strip), so the distance to its shore is exact in the shader - no depth texture needed,
// which keeps it working on every WebGL 1 driver. From that distance:
//   - depth colour with a Beer-Lambert falloff, shallow teal at the edge to deep in the middle
//     (the depth fade of paddy-exe/Godot-3D-Stylized-Water, MIT, Patrick Exner);
//   - a shoreline foam band whose edge wobbles with noise, plus a second foam line breathing
//     in and out (that shader's noise-displaced foam edge, again);
//   - caustics on the shallow floor from cellular noise (F2 - F1 lines);
// and from a normal built from two scrolling simplex layers (stegu/webgl-noise, MIT): a
// Schlick fresnel mix with the sky colour, a stepped sun/moon glint, the station lamps
// reflected as streaks at night, flow-aligned whitecaps on the stream, and expanding ripple
// rings (a fish jumping, LOKI's beacon pinging the pool). The waterfall is the same program
// in sheet mode: streaks sliding down, a white lip at the top, fading into mist below.
// The result is quantized into bands, so it stays pixel-art like the rest.
const WATER_VS = "attribute vec3 p; uniform mat4 M; uniform mat4 VP; uniform float T; uniform vec4 shape;" +
  "varying vec3 wp; varying vec2 lp;" +
  "void main(){ vec4 w = M * vec4(p,1.0); lp = shape.w > 1.5 ? p.xy : p.xz;" +
  " if (shape.w < 1.5) w.y += (sin(w.x * 2.3 + T * 1.6) + sin(w.z * 2.9 - T * 1.3)) * 0.006;" +
  " wp = w.xyz; gl_Position = VP * w; }";
const WATER_FS = "#ifdef GL_FRAGMENT_PRECISION_HIGH\nprecision highp float;\n#else\nprecision mediump float;\n#endif\n" +
  "varying vec3 wp; varying vec2 lp;" +
  "uniform float T; uniform vec4 shape; uniform vec4 rect; uniform vec4 obs0; uniform vec4 obs1; uniform vec2 flow; uniform float beer;" +
  "uniform vec3 eye; uniform vec3 sunDir; uniform vec3 sunCol; uniform vec3 zenith; uniform vec3 horizon; uniform float dayK;" +
  "uniform vec3 fogc; uniform vec2 fogr; uniform vec3 LP[10]; uniform vec4 LC[10];" +
  "uniform vec3 shallow; uniform vec3 deep; uniform vec3 foamCol; uniform vec4 rip[4];" +
  "\n" + (typeof WORLD_NOISE_GLSL === "string" ? WORLD_NOISE_GLSL : "") + "\n" +
  "float boxd(vec2 p, vec4 b){ vec2 d = abs(p - b.xy) - b.zw; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }" +
  "float shore(vec2 p){ float d;" +
  " if (shape.w < 0.5) d = shape.z - length(p - shape.xy);" +
  " else { vec2 l = p - shape.xy; d = rect.z - abs(dot(l, vec2(-rect.y, rect.x))); }" +
  " if (obs0.z > 0.0) d = min(d, boxd(p, obs0));" +
  " if (obs1.z > 0.0) d = min(d, boxd(p, obs1));" +
  " return d; }" +
  "float hgt(vec2 p){ return snoise(p * 0.9 - flow * T + vec2(T * 0.08, T * 0.05)) * 0.6" +
  " + snoise(p * 1.9 - flow * T * 1.4 + vec2(-T * 0.09, T * 0.12)) * 0.28; }" +
  "vec3 quant(vec3 c){ return floor(c * 9.0 + 0.5) / 9.0; }" +
  "vec4 fogged(vec3 col, float a){ float f = clamp((length(eye - wp) - fogr.x) / fogr.y, 0.0, 1.0); f = floor(f * 4.0) / 4.0;" +
  " return vec4(mix(quant(col), fogc, f * 0.6), a); }" +
  "vec4 sheet(){" +
  " float n1 = snoise(vec2(lp.x * 9.0, wp.y * 0.9 + T * 2.6)); float n2 = snoise(vec2(lp.x * 17.0 + 3.0, wp.y * 1.7 + T * 4.1));" +
  " vec3 col = mix(deep, shallow, 0.6 + 0.2 * n1);" +
  " col = mix(col, foamCol, step(0.42, n1 * 0.6 + n2 * 0.4));" +
  " col = mix(col, foamCol, step(0.44, lp.y + n2 * 0.015));" +
  " col += sunCol * 0.12 * dayK;" +
  " float a = (1.0 - step(0.9, abs(lp.x) * 2.0 + n2 * 0.06)) * 0.88 * smoothstep(-0.5, -0.28, lp.y);" +
  " if (a <= 0.01) discard;" +
  " return fogged(col, a); }" +
  "void main(){" +
  " if (shape.w > 1.5) { gl_FragColor = sheet(); return; }" +
  " vec2 q = wp.xz; float s = shore(q);" +
  " if (s < -0.02) discard;" +
  " float h0 = hgt(q); float e = 0.07;" +
  " vec2 g = vec2(hgt(q + vec2(e, 0.0)) - h0, hgt(q + vec2(0.0, e)) - h0) / e;" +
  " float ring = 0.0;" +
  " for (int i = 0; i < 4; i++) { if (rip[i].w > 0.0) {" +
  "  vec2 dv = q - rip[i].xy; float d = length(dv); float r = rip[i].z * 0.85;" +
  "  float k = exp(-abs(d - r) * 16.0) * rip[i].w * max(0.0, 1.0 - rip[i].z / 2.2);" +
  "  g += dv / max(d, 0.001) * k * 2.2; ring += k; } }" +
  " vec3 N = normalize(vec3(-g.x * 0.2, 1.0, -g.y * 0.2));" +
  " float depth = 1.0 - exp(-max(s, 0.0) * beer);" +
  " vec3 col = mix(shallow, deep, depth);" +
  " vec2 F = cellular(q * 1.35 + g * 0.15 + vec2(T * 0.04, -T * 0.03));" +
  " col += vec3(0.55, 0.95, 1.0) * step(F.y - F.x, 0.11) * (1.0 - depth * 0.85) * (0.16 + 0.2 * dayK);" +
  " vec3 V = normalize(eye - wp); vec3 R = reflect(-V, N);" +
  " float fr = 0.06 + 0.94 * pow(1.0 - max(dot(N, V), 0.0), 5.0);" +
  " vec3 sky = mix(horizon, zenith, clamp(R.y * 1.4, 0.0, 1.0));" +
  " col = mix(col, sky, clamp(fr, 0.0, 0.7));" +
  " float sp = max(dot(R, sunDir), 0.0); col += sunCol * (step(0.988, sp) * 0.9 + step(0.95, sp) * 0.12);" +
  " for (int i = 0; i < 10; i++) { vec3 L = LP[i] - wp; float dl = length(L);" +
  "  float k = pow(max(dot(R, L / max(dl, 0.001)), 0.0), 14.0) * clamp(1.0 - dl / (LC[i].w * 2.4), 0.0, 1.0);" +
  "  col += LC[i].rgb * (step(0.25, k) * 0.7 + step(0.6, k) * 0.7); }" +
  " float wob = snoise(q * 3.1 + vec2(T * 0.3, -T * 0.25)) * 0.05 + snoise(q * 7.0 - vec2(T * 0.5)) * 0.025;" +
  " float sd = s + wob;" +
  " float foam = step(sd, 0.12) + step(abs(sd - 0.24 - 0.035 * sin(T * 1.5)), 0.02) * 0.75 + step(0.45, ring) * 0.85;" +
  " foam = max(foam, step(0.62, h0) * 0.65 * step(0.05, length(flow)));" +
  " foam = clamp(foam, 0.0, 1.0);" +
  " col = mix(col, foamCol, foam);" +
  " float a = max(mix(0.62, 0.94, depth), foam);" +
  " gl_FragColor = fogged(col, a); }";

// Sky: a gradient by the view ray's height (zenith, a glowing horizon band, the deep below
// the floating island), a pixel sun/moon and stars that fade in at night.
const SKY_VS = "attribute vec3 p; uniform vec3 camF; uniform vec3 camR; uniform vec3 camU; uniform vec2 tanH;" +
  "varying vec3 ray; void main(){ ray = camF + camR * p.x * tanH.x + camU * p.y * tanH.y; gl_Position = vec4(p.xy, 0.9999, 1.0); }";
const SKY_FS = "#ifdef GL_FRAGMENT_PRECISION_HIGH\nprecision highp float;\n#else\nprecision mediump float;\n#endif\n" +
  "varying vec3 ray; uniform vec3 zenith; uniform vec3 horizon; uniform vec3 glow; uniform vec3 deep;" +
  "uniform vec3 skySun; uniform vec3 skySunCol; uniform float stars; uniform float T;" +
  "void main(){ vec3 d = normalize(ray); float e = d.y;" +
  " vec3 col = e > 0.0 ? mix(horizon, zenith, pow(clamp(e * 1.6, 0.0, 1.0), 0.7)) : mix(horizon, deep, pow(clamp(-e * 2.2, 0.0, 1.0), 0.6));" +
  " col += glow * exp(-abs(e) * 9.0);" +
  " float s = dot(d, skySun); col = mix(col, skySunCol, step(0.9985, s)); col += skySunCol * step(0.99, s) * 0.18;" +
  " vec3 q = floor(d * 140.0); float h = fract(sin(dot(q, vec3(12.9898, 78.233, 37.719))) * 43758.5453);" +
  " float tw = 0.65 + 0.35 * step(0.5, fract(h * 91.0 + T * 0.6));" +
  " col += vec3(0.85, 0.95, 1.0) * step(0.993, h) * stars * tw * smoothstep(-0.25, 0.15, e);" +
  " float band = sin(d.x * 3.0 + d.z * 2.0 + T * 0.05) * 0.5 + 0.5;" +
  " col += vec3(0.10, 0.45, 0.42) * stars * 0.35 * step(0.72, band) * smoothstep(0.25, 0.6, e) * (1.0 - smoothstep(0.6, 0.95, e));" +
  " gl_FragColor = vec4(col, 1.0); }";

// Sprites: soft blob shadows lying on the ground and additive light glows facing the camera,
// both cut into a few hard rings so they stay pixel-art.
const SPRITE_VS = "attribute vec3 p; uniform mat4 VP; uniform vec3 SC; uniform vec2 SS; uniform float SB; uniform vec3 camR; uniform vec3 camU;" +
  "varying vec2 uv; void main(){ uv = p.xy;" +
  " vec3 w = SB > 0.5 ? SC + camR * p.x * SS.x + camU * p.y * SS.y : SC + vec3(p.x * SS.x, 0.0, p.y * SS.y);" +
  " gl_Position = VP * vec4(w, 1.0); }";
const SPRITE_FS = "precision mediump float; varying vec2 uv; uniform vec3 SK; uniform float SA;" +
  "void main(){ float a = clamp(1.0 - length(uv), 0.0, 1.0); a = floor(a * 3.0 + 0.6) / 3.0; if (a <= 0.0) discard;" +
  " gl_FragColor = vec4(SK * a, a * SA); }";
// ...and every static shadow in one buffer: p is the ground point, n = (u, v, alpha).
const SHADOW_VS = "attribute vec3 p; attribute vec3 n; uniform mat4 VP; varying vec3 q; void main(){ q = n; gl_Position = VP * vec4(p, 1.0); }";
const SHADOW_FS = "precision mediump float; varying vec3 q; uniform vec3 SK;" +
  "void main(){ float a = clamp(1.0 - length(q.xy), 0.0, 1.0); a = floor(a * 3.0 + 0.6) / 3.0; if (a <= 0.0) discard;" +
  " gl_FragColor = vec4(SK * a, a * q.z); }";

// Upscale: the low-res scene, NEAREST-sampled onto the canvas, posterized with a 4x4
// ordered (Bayer) dither in world pixels.
const BLIT_VS = "attribute vec3 p; void main(){ gl_Position = vec4(p.xy, 0.0, 1.0); }";
const BLIT_FS = "precision mediump float; uniform sampler2D T; uniform vec2 R; uniform vec2 VPX; uniform float Q;" +
  "float bayer2(vec2 a){ a = floor(a); return fract(a.x / 2.0 + a.y * a.y * 0.75); }" +
  "float bayer4(vec2 a){ return bayer2(0.5 * a) * 0.25 + bayer2(a); }" +
  "void main(){ vec2 uv = gl_FragCoord.xy / VPX; vec3 c = texture2D(T, uv).rgb;" +
  " float b = bayer4(floor(uv * R)) - 0.5; c = floor(c * Q + 0.5 + b) / Q;" +
  " vec2 v = uv - 0.5; c *= 1.0 - dot(v, v) * 0.35;" +
  " gl_FragColor = vec4(c, 1.0); }";

// ---------------------------------------------------------------- renderer
function makeProgram(gl, vs, fs, uniforms) {
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
  const prog = gl.createProgram();
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, vs));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
  const loc = { p: gl.getAttribLocation(prog, "p"), n: gl.getAttribLocation(prog, "n"),
    c: gl.getAttribLocation(prog, "c"), x: gl.getAttribLocation(prog, "x") };
  for (const u of uniforms) loc[u] = gl.getUniformLocation(prog, u);
  return { prog, loc };
}

function uploadMesh(gl, mesh) {
  const buf = (data) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data instanceof Float32Array ? data : new Float32Array(data), gl.STATIC_DRAW); return b; };
  const out = { pb: buf(mesh.p), nb: buf(mesh.n), count: mesh.p.length / 3 };
  if (mesh.c) out.cb = buf(mesh.c);
  if (mesh.x) out.xb = buf(mesh.x);
  return out;
}

// Build (or rebuild, after a lost context) everything a view keeps on the GPU.
function initGL(view) {
  const { gl } = view;
  const sceneU = ["IS", "C", "E", "G", "S"].concat(LIGHT_UNIFORMS);
  view.solid = makeProgram(gl, VS, FS, sceneU);
  if (!view.solid) return false;
  view.baked = makeProgram(gl, BAKED_VS, BAKED_FS, LIGHT_UNIFORMS);
  view.outline = makeProgram(gl, OUTLINE_VS, OUTLINE_FS, ["M", "VP", "oeye", "OL", "OC", "ofog", "ofogr"]);
  view.bakedOutline = makeProgram(gl, BAKED_OUTLINE_VS, BAKED_OUTLINE_FS, ["M", "VP", "oeye", "OL", "ofog", "ofogr"]);
  view.sky = makeProgram(gl, SKY_VS, SKY_FS, ["camF", "camR", "camU", "tanH", "zenith", "horizon", "glow", "deep", "skySun", "skySunCol", "stars", "T"]);
  view.sprite = makeProgram(gl, SPRITE_VS, SPRITE_FS, ["VP", "SC", "SS", "SB", "camR", "camU", "SK", "SA"]);
  view.shadowBatch = makeProgram(gl, SHADOW_VS, SHADOW_FS, ["VP", "SK"]);
  view.blit = makeProgram(gl, BLIT_VS, BLIT_FS, ["T", "R", "VPX", "Q"]);
  view.water = typeof WORLD_NOISE_GLSL === "string" ? makeProgram(gl, WATER_VS, WATER_FS, ["M", "VP", "T", "shape", "rect", "obs0",
    "obs1", "flow", "beer", "eye", "sunDir", "sunCol", "zenith", "horizon", "dayK", "fogc", "fogr", "LP", "LC", "shallow", "deep",
    "foamCol", "rip"]) : null;   // a driver that cannot compile it keeps the plain water floor
  view.meshes = {};
  for (const [k, m] of Object.entries(MESH_SRC)) view.meshes[k] = uploadMesh(gl, m);
  const st = staticScene();
  view.batches = {
    land: uploadMesh(gl, st.land.solid), landInk: uploadMesh(gl, st.land.ink),
    sky: uploadMesh(gl, st.sky.solid), skyInk: uploadMesh(gl, st.sky.ink),
    shadows: uploadMesh(gl, st.shadows),
  };
  view.fb = null; view.fbFailed = false; view.lost = false;
  return true;
}

function makeView(canvas, labels, opts) {
  // LOKI's own pixel cel-shaded renderer is the world's look. The three.js renderer
  // (world_three.js) is only used when asked for: LOKI_WORLD_ENGINE=three (Settings > General).
  const engineMod = World.engine === "babylon" ? window.WorldBabylon : World.engine === "three" ? window.WorldThree : null;
  if (engineMod) {
    let three = null;   // (the slot is called "three" for history: any engine that draws world.js's scene description)
    try {
      three = engineMod.create(canvas, { staticScene, meshes: MESH_SRC, water: WATER,
        noise: typeof WORLD_NOISE_GLSL === "string" ? WORLD_NOISE_GLSL : "" });
    } catch (err) { three = null; console.warn("LOKI World: the " + World.engine + " renderer failed, using the classic one", err); }
    if (three) {
      staticScene();
      const view = { canvas, labels, gl: three.renderer.getContext(), three, opts, yaw: 0.6, pitch: opts.pitch || 0.5,
        dist: opts.dist || 15, target: [0, 0.7, 0], drag: null, pointers: {}, labelNodes: {}, visible: false, raf: 0, last: 0,
        lastDraw: 0, perf: { ema: 0, boost: 0, slow: 0, fast: 0, draws: 0, ms: 0, engine: three.kind || "three" }, follow: "" };
      three.setQuality(opts.quality || "high");
      return view;
    }
  }
  let gl = null;
  try { gl = canvas.getContext("webgl", { antialias: false, alpha: false, premultipliedAlpha: false }); } catch (_) { gl = null; }
  if (!gl) return null;
  const view = { canvas, labels, gl, opts, yaw: 0.6, pitch: opts.pitch || 0.5,
    dist: opts.dist || 15, target: [0, 0.7, 0], drag: null, pointers: {}, labelNodes: {}, visible: false, raf: 0, last: 0,
    lastDraw: 0, fb: null, fbFailed: false, perf: { ema: 0, boost: 0, slow: 0, fast: 0, draws: 0, ms: 0 }, follow: "" };
  if (!initGL(view)) return null;
  canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); view.lost = true; });
  canvas.addEventListener("webglcontextrestored", () => {   // sleep / GPU switch: build it all again
    if (initGL(view) && view.visible) { view.raf = 0; loop(view); }
  });
  return view;
}

// The low-res target: a colour texture with NEAREST filtering and a depth buffer. If the
// driver will not make one, the view draws straight to the canvas instead (still cel-shaded).
function ensureTarget(view, lw, lh) {
  const { gl } = view;
  if (view.fbFailed || !view.blit) return null;
  if (view.fb && view.fb.w === lw && view.fb.h === lh) return view.fb;
  try {
    if (view.fb) { gl.deleteFramebuffer(view.fb.fbo); gl.deleteTexture(view.fb.tex); gl.deleteRenderbuffer(view.fb.depth); }
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, lw, lh, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const depth = gl.createRenderbuffer();
    gl.bindRenderbuffer(gl.RENDERBUFFER, depth);
    gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, lw, lh);
    const fbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, depth);
    const ok = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (!ok) throw new Error("incomplete framebuffer");
    view.fb = { fbo, tex, depth, w: lw, h: lh };
  } catch (_) {
    view.fb = null; view.fbFailed = true;   // fall back to drawing directly
  }
  return view.fb;
}

// Bind a mesh's buffers to whatever attributes this program has; leave every other array off.
function bindMesh(gl, loc, m) {
  const used = [];
  const on = (l, b, size) => {
    if (l < 0 || !b) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.vertexAttribPointer(l, size, gl.FLOAT, false, 0, 0); gl.enableVertexAttribArray(l); used.push(l);
  };
  on(loc.p, m.pb, 3); on(loc.n, m.nb, 3); on(loc.c, m.cb, 3); on(loc.x, m.xb, 4);
  for (let i = 0; i < 6; i++) if (!used.includes(i)) gl.disableVertexAttribArray(i);
}

// ---------------------------------------------------------------- the place
const STATION_LAYOUT = {
  "hall": { pos: [0, 0], color: "#2ee6d6", label: "Hall" },
  "library": { pos: [-5.2, -2.6], color: "#3fa9ff", label: "Library" },
  "drafting table": { pos: [-1.8, -5.6], color: "#b46cff", label: "Drafting" },
  "workshop": { pos: [3.0, -4.8], color: "#36e07a", label: "Workshop" },
  "test bench": { pos: [5.6, -0.4], color: "#ffc23d", label: "Test bench" },
  "review desk": { pos: [3.6, 3.8], color: "#ff7a45", label: "Review" },
  "terminal": { pos: [-2.4, 4.6], color: "#4d7cff", label: "Terminal" },
};
const STATE_COLOR = { working: "#8fb3d9", waiting: "#9aa0aa", blocked: "#ff7777", done: "#a3be8c", failed: "#bf616a", idle: "#9aa0aa" };
const ISLAND = 9.6;   // radius of the island's grass top
const PLAZA_R = 2.9;  // agents walk round the plaza on this ring (the pool is in the middle)

// Palettes for the night (LOKI's navy/teal) and the day (brighter teal), blended gently by
// the local clock - it shifts the tint, it never turns the world into a different place.
const NIGHT = {
  zenith: [0.03, 0.04, 0.16], horizon: [0.07, 0.30, 0.42], glow: [0.10, 0.45, 0.50], deep: [0.02, 0.03, 0.10],
  sunCol: [0.55, 0.66, 0.95], skyAmb: [0.30, 0.36, 0.62], gndAmb: [0.16, 0.14, 0.30], shade: [0.80, 0.85, 1.20],
  rim: [0.25, 0.85, 0.95], fog: [0.05, 0.16, 0.28], stars: 1, sunSky: [0.85, 0.92, 1.0], lamps: 1.0,
};
const DAY = {
  zenith: [0.10, 0.32, 0.78], horizon: [0.45, 0.85, 0.88], glow: [0.55, 0.40, 0.20], deep: [0.08, 0.16, 0.42],
  sunCol: [1.00, 0.88, 0.66], skyAmb: [0.42, 0.52, 0.68], gndAmb: [0.26, 0.20, 0.24], shade: [0.72, 0.78, 1.15],
  rim: [0.70, 1.00, 0.90], fog: [0.40, 0.70, 0.80], stars: 0, sunSky: [1.0, 0.95, 0.75], lamps: 0.45,
};

function stationPos(name) {
  const s = STATION_LAYOUT[name] || STATION_LAYOUT.workshop;
  return s.pos;
}
function stationFrame(name) {   // where a station is, which way is out (u) and along its desk (tg)
  const [x, z] = stationPos(name), len = Math.hypot(x, z) || 1;
  const u = [x / len, z / len];
  return { x, z, u, tg: [u[1], -u[0]], ang: Math.atan2(x, z), len };
}

// The scenery that never changes: trees, rocks, lamp posts, flowers, benches, the waterfall
// and clouds, scattered once with a fixed seed, kept off the paths, the plaza and the stations.
const SCENERY = (function () {
  const rnd = seeded(1729);
  const stations = Object.values(STATION_LAYOUT).map((s) => s.pos);
  const clear = (x, z, pad) => {
    if (Math.hypot(x, z) < 3.8 + pad) return false;
    for (const [sx, sz] of stations) {
      if (Math.hypot(x - sx, z - sz) < 3.0 + pad) return false;
      const len = Math.hypot(sx, sz) || 1, t = Math.max(0, Math.min(1, (x * sx + z * sz) / (len * len)));
      if (Math.hypot(x - sx * t, z - sz * t) < 0.9 + pad) return false;
    }
    return true;
  };
  const trees = [], rocks = [], lamps = [], clouds = [], flowers = [], tufts = [], islets = [], crystals = [];
  // the waterfall: a little pond near the edge in the first clear spot, a stream to the rim
  let fall = null;
  for (let i = 0; i < 64 && !fall; i++) {
    const a = 2.3 + i * 0.37, r = ISLAND - 1.4;
    const x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (clear(x, z, 0.5)) fall = { a, x, z };
  }
  // the creations hall: a little open gallery near the edge, where what LOKI made hangs
  let gallery = null;
  for (let i = 0; i < 192 && !gallery; i++) {
    const a = 0.9 + i * 0.41, r = ISLAND - 2.2 - (i % 3) * 0.6, x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (clear(x, z, 0.6) && !(fall && Math.hypot(fall.x - x, fall.z - z) < 3.2)) gallery = { a, x, z };
  }
  const nearGallery = (x, z, d) => gallery && Math.hypot(gallery.x - x, gallery.z - z) < d;
  for (let i = 0; i < 400 && trees.length < 16; i++) {
    const a = rnd() * Math.PI * 2, r = 4 + rnd() * (ISLAND - 4.8);
    const x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (!clear(x, z, 0.2) || trees.some((t) => Math.hypot(t.x - x, t.z - z) < 1.3)) continue;
    if (fall && Math.hypot(fall.x - x, fall.z - z) < 1.6) continue;
    if (nearGallery(x, z, 2.4)) continue;
    trees.push({ x, z, h: 0.8 + rnd() * 0.6, kind: rnd() < 0.6 ? 0 : 1, ry: rnd() * 6 });
  }
  for (let i = 0; i < 300 && rocks.length < 9; i++) {
    const a = rnd() * Math.PI * 2, r = 3.5 + rnd() * (ISLAND - 4);
    const x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (!clear(x, z, 0) || trees.some((t) => Math.hypot(t.x - x, t.z - z) < 0.9)) continue;
    if (fall && Math.hypot(fall.x - x, fall.z - z) < 1.6) continue;
    if (nearGallery(x, z, 2.2)) continue;
    rocks.push({ x, z, s: 0.3 + rnd() * 0.45, ry: rnd() * 6 });
  }
  for (const name of ["library", "review desk", "terminal"]) {   // lamps halfway along three paths
    const [sx, sz] = STATION_LAYOUT[name].pos, len = Math.hypot(sx, sz);
    lamps.push({ x: sx * 0.5 + sz / len * 0.75, z: sz * 0.5 - sx / len * 0.75 });
  }
  const busy = (x, z, d) => trees.some((t) => Math.hypot(t.x - x, t.z - z) < d) || rocks.some((t) => Math.hypot(t.x - x, t.z - z) < d) ||
    (fall && Math.hypot(fall.x - x, fall.z - z) < 1.3) || nearGallery(x, z, 1.9);
  const FLOWER = [[1.0, 0.55, 0.75], [1.0, 0.86, 0.35], [0.95, 0.95, 1.0], [0.70, 0.60, 1.0]];
  for (let i = 0; i < 900 && flowers.length < 34; i++) {
    const a = rnd() * Math.PI * 2, r = 3.9 + rnd() * (ISLAND - 4.5), x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (!clear(x, z, -0.2) || busy(x, z, 0.5)) continue;
    flowers.push({ x, z, c: FLOWER[Math.floor(rnd() * FLOWER.length)], h: 0.12 + rnd() * 0.1 });
  }
  for (let i = 0; i < 900 && tufts.length < 60; i++) {
    const a = rnd() * Math.PI * 2, r = 3.7 + rnd() * (ISLAND - 4.1), x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (!clear(x, z, -0.4) || busy(x, z, 0.35)) continue;
    tufts.push({ x, z, s: 0.16 + rnd() * 0.14, ry: rnd() * 6 });
  }
  for (let i = 0; i < 4; i++) clouds.push({ a: i * 1.6 + rnd(), r: 15 + rnd() * 4, y: 6.5 + rnd() * 2.5, s: 0.7 + rnd() * 0.5 });
  for (let i = 0; i < 3; i++) islets.push({ a: i * 2.1 + 0.7 + rnd(), r: 13 + rnd() * 3, y: -1.5 + rnd() * 3, s: 0.8 + rnd() * 0.5 });
  for (let i = 0; i < 7; i++) {
    const a = rnd() * Math.PI * 2, r = 2 + rnd() * 5.5;
    crystals.push({ x: Math.cos(a) * r, z: Math.sin(a) * r, y: -1.4 - rnd() * (2.6 - r * 0.25), h: 0.6 + rnd() * 0.8, ry: rnd() * 6 });
  }
  // plaza life: benches and team banner spots in the gaps between the paths
  const angs = Object.entries(STATION_LAYOUT).filter(([n]) => n !== "hall").map(([, s]) => Math.atan2(s.pos[1], s.pos[0])).sort((a, b) => a - b);
  const gaps = angs.map((a, i) => { const b = i + 1 < angs.length ? angs[i + 1] : angs[0] + Math.PI * 2; return (a + b) / 2; });
  const benches = gaps.filter((_, i) => i % 2 === 0).map((a) => ({ a, x: Math.cos(a) * 2.75, z: Math.sin(a) * 2.75 }));
  const banners = gaps.map((a, i) => ({ a: a + (i % 2 === 0 ? 0.32 : 0), x: Math.cos(a + (i % 2 === 0 ? 0.32 : 0)) * 3.35, z: Math.sin(a + (i % 2 === 0 ? 0.32 : 0)) * 3.35 }));
  const spots = gaps.map((a) => [Math.cos(a - 0.25) * 2.35, Math.sin(a - 0.25) * 2.35]);   // where wanderers stand
  return { trees, rocks, lamps, clouds, flowers, tufts, islets, crystals, fall, gallery, benches, banners, spots };
})();

// The water in the world: where each body is, its shape for the shore distance (disc with
// blocks standing in it, or a strip), how fast it flows and how quickly it gets deep.
const WATER = (function () {
  const out = [];
  out.push({ id: "pool", mesh: "wdisc", pos: [0, 0.088, 0], ry: 0, s: [3.24, 1, 3.24], shape: [0, 0, 1.62, 0], rect: [0, 0, 0, 0],
    obs: [[-0.25, 0, 0.2, 0.2], [0.2, 0, 0.62, 0.2]], flow: [0, 0], beer: 1.15 });
  const fl = SCENERY.fall;
  if (fl) {
    const ux = Math.cos(fl.a), uz = Math.sin(fl.a), ry = Math.atan2(ux, uz), run = ISLAND - Math.hypot(fl.x, fl.z);
    out.push({ id: "pond", mesh: "wdisc", pos: [fl.x, 0.078, fl.z], ry: 0, s: [1.56, 1, 1.56], shape: [fl.x, fl.z, 0.78, 0], rect: [0, 0, 0, 0],
      obs: [], flow: [ux * 0.04, uz * 0.04], beer: 2.6 });
    const len = run - 0.55, cx = fl.x + ux * (0.55 + len / 2), cz = fl.z + uz * (0.55 + len / 2);
    out.push({ id: "stream", mesh: "wstrip", pos: [cx, 0.06, cz], ry, s: [0.46, 1, len + 0.1], shape: [cx, cz, 0, 1], rect: [ux, uz, 0.23, len / 2],
      obs: [], flow: [ux * 0.55, uz * 0.55], beer: 6.0 });
    out.push({ id: "fall", mesh: "wsheet", pos: [ux * (ISLAND + 0.05), -2.72, uz * (ISLAND + 0.05)], ry, s: [0.46, 5.6, 1], shape: [0, 0, 0, 2],
      rect: [0, 0, 0, 0], obs: [], flow: [0, 0], beer: 1 });
  }
  return out;
})();
const WATER_LOOK = {   // shallow, deep and foam colours, blended night -> day like the rest
  night: { shallow: [0.16, 0.56, 0.66], deep: [0.06, 0.18, 0.40], foam: [0.78, 0.95, 1.0] },
  day: { shallow: [0.24, 0.78, 0.80], deep: [0.06, 0.30, 0.56], foam: [0.95, 1.0, 1.0] },
};

// Ripples: rings spreading on a body of water. Real events make some (LOKI's beacon pings
// the pool when a board message arrives); the pond's fish make the rest (ambience).
function addRipple(body, x, z, strength) {
  if (World.reduced) return;
  World.ripples.push({ body, x, z, t0: performance.now() / 1000, k: strength || 1 });
  if (World.ripples.length > 12) World.ripples.shift();
}

// ---------------------------------------------------------------- baking the static scene
// Static solids go through the same description as dynamic ones ({mesh, pos, ry, s, color,
// e, g, s2, w, line}); bake() transforms them into world space once.
function bake(list) {
  const P = [], N = [], C = [], X = [], OP = [], ON = [], OC = [];
  const inkc = [0.03, 0.03, 0.10];
  for (const o of list) {
    const src = MESH_SRC[o.mesh], M = M4.trs(o.pos, o.ry, o.s);
    const is = [1 / (o.s[0] * o.s[0]), 1 / (o.s[1] * o.s[1]), 1 / (o.s[2] * o.s[2])];
    const order = o.s[0] * o.s[1] * o.s[2] < 0 ? [0, 2, 1] : [0, 1, 2];   // mirrored: keep it front-facing
    const mat = [o.e || 0, o.g || 0, o.s2 == null ? 0.3 : o.s2, o.w || 0];
    const ink = mix3(inkc, o.color, 0.22), lined = o.line !== false;
    for (let t = 0; t < src.p.length; t += 9) for (const k of order) {
      const i = t + k * 3, px = src.p[i], py = src.p[i + 1], pz = src.p[i + 2];
      const wx = M[0] * px + M[4] * py + M[8] * pz + M[12], wy = M[1] * px + M[5] * py + M[9] * pz + M[13], wz = M[2] * px + M[6] * py + M[10] * pz + M[14];
      const nx = src.n[i] * is[0], ny = src.n[i + 1] * is[1], nz = src.n[i + 2] * is[2];
      const wn = norm([M[0] * nx + M[4] * ny + M[8] * nz, M[1] * nx + M[5] * ny + M[9] * nz, M[2] * nx + M[6] * ny + M[10] * nz]);
      P.push(wx, wy, wz); N.push(wn[0], wn[1], wn[2]); C.push(o.color[0], o.color[1], o.color[2]); X.push(mat[0], mat[1], mat[2], mat[3]);
      if (lined) { OP.push(wx, wy, wz); ON.push(o.pos[0], o.pos[1], o.pos[2]); OC.push(ink[0], ink[1], ink[2]); }
    }
  }
  return { solid: { p: new Float32Array(P), n: new Float32Array(N), c: new Float32Array(C), x: new Float32Array(X) },
    ink: { p: new Float32Array(OP), n: new Float32Array(ON), c: new Float32Array(OC) } };
}

let STATIC = null;
function staticScene() {
  if (STATIC) return STATIC;
  const land = [], sky = [], shadows = [], lights = [], glows = [];
  const solid = (mesh, pos, ry, s, color, o) => land.push(Object.assign({ mesh, pos, ry, s, color }, o || {}));
  const shadow = (x, z, r, a) => shadows.push({ x, z, r, a: Math.min(1, (a == null ? 0.5 : a) * 1.3) });
  const ink = { line: false };
  const curb = (cx, cz, r, n, size, color) => {   // a ring of stone blocks round a pool
    for (let k = 0; k < n; k++) {
      const a = (k / n) * Math.PI * 2, j = (k % 3) * 0.012;
      solid("box", [cx + Math.cos(a) * r, 0.075 + j, cz + Math.sin(a) * r], -a - Math.PI / 2, [size[0], size[1] + j, size[2]],
        mix3(color, [0.5, 0.5, 0.62], (k % 2) * 0.18));
    }
  };

  // the island: grass top with a soft checker, a band of earth, a faceted rock cone below
  solid("cyl", [0, -0.2, 0], 0, [ISLAND * 2, 0.4, ISLAND * 2], [0.10, 0.60, 0.36], { g: 0.9 });
  solid("cyl6", [0, -0.75, 0], 0.3, [ISLAND * 2 - 0.2, 0.75, ISLAND * 2 - 0.2], [0.55, 0.34, 0.30]);
  solid("cone", [0, -3.6, 0], 0.5, [ISLAND * 1.9, 5.0, ISLAND * 1.9].map((v, i) => (i === 1 ? -v : v)), [0.36, 0.26, 0.42], { line: false });
  solid("cone", [0, -3.4, 0], 2.1, [ISLAND * 1.55, -4.6, ISLAND * 1.55], [0.30, 0.22, 0.40], { line: false });
  for (const c of SCENERY.crystals) {   // LOKI-teal crystals hanging under the island
    solid("pyr", [c.x, c.y, c.z], c.ry, [0.45 * c.h, -1.3 * c.h, 0.45 * c.h], [0.25, 0.95, 0.88], { e: 0.75, line: false });
    glows.push({ pos: [c.x, c.y - 0.4 * c.h, c.z], r: 0.7 * c.h, color: [0.2, 0.9, 0.85], a: 0.45 });
  }
  // the plaza, with a reflecting pool round the conductor's spire
  solid("cyl", [0, 0.02, 0], 0, [7.2, 0.06, 7.2], [0.62, 0.62, 0.78], Object.assign({ g: 1.4 }, ink));
  solid("cyl", [0, 0.045, 0], 0, [3.5, 0.03, 3.5], [0.75, 0.74, 0.86], ink);
  solid("cyl", [0, 0.062, 0], 0, [3.22, 0.012, 3.22], [0.16, 0.30, 0.42], Object.assign({ g: 2.6 }, ink));   // tiled floor under the water
  curb(0, 0, 1.7, 22, [0.5, 0.1, 0.2], [0.74, 0.74, 0.86]);
  // the conductor's spire: an L-shaped mark, LOKI's sign (its beacon is dynamic)
  solid("box", [-0.25, 1.3, 0], 0, [0.36, 2.6, 0.36], [0.18, 0.86, 0.82], { e: 0.12 });
  solid("box", [0.2, 0.2, 0], 0, [1.2, 0.36, 0.36], [0.18, 0.86, 0.82], { e: 0.12 });

  for (const [name, st] of Object.entries(STATION_LAYOUT)) {
    if (name === "hall") continue;
    const f = stationFrame(name), { x, z, ang, len } = f, [ux, uz] = f.u, [tx, tz] = f.tg;
    const c = hexRgb(st.color, [0.5, 0.6, 0.7]);
    solid("box", [x / 2, 0.015, z / 2], ang, [0.9, 0.03, len], [0.70, 0.66, 0.80], ink);
    for (let k = 1; k < 5; k++) solid("box", [x * k / 5 + uz * 0.55, 0.035, z * k / 5 - ux * 0.55], ang + k, [0.22, 0.03, 0.22], [0.58, 0.55, 0.70], ink);
    solid("cyl", [x, 0.03, z], 0, [2.6, 0.06, 2.6], mix3(c, [0.6, 0.6, 0.75], 0.55), ink);
    // a little building behind the station: cream walls, a roof in the station colour, a lit window
    const bx = x + ux * 2.1, bz = z + uz * 2.1, rot = ang;
    solid("box", [bx, 0.55, bz], rot, [1.5, 1.1, 1.3], [0.93, 0.86, 0.74]);
    solid("pyr", [bx, 1.55, bz], rot + Math.PI / 4, [2.25, 0.9, 2.0], c);
    solid("box", [bx - ux * 0.66 + uz * 0.38, 0.62, bz - uz * 0.66 - ux * 0.38], rot, [0.42, 0.34, 0.04], [1.0, 0.82, 0.45], { e: 0.9, line: false });
    solid("box", [bx - ux * 0.66 - uz * 0.3, 0.45, bz - uz * 0.66 + ux * 0.3], rot, [0.4, 0.9, 0.06], [0.36, 0.22, 0.20], { line: false });
    shadow(bx + 0.25, bz - 0.2, 1.4, 0.45);
    // the desk the agent works at
    solid("box", [x, 0.48, z], ang, [1.4, 0.12, 0.75], [0.62, 0.38, 0.26]);
    solid("box", [x - tx * 0.55, 0.22, z - tz * 0.55], ang, [0.1, 0.44, 0.1], [0.40, 0.25, 0.18]);
    solid("box", [x + tx * 0.55, 0.22, z + tz * 0.55], ang, [0.1, 0.44, 0.1], [0.40, 0.25, 0.18]);
    shadow(x, z, 0.95, 0.35);
    // the station lamp post (its orb is dynamic: it brightens when someone works here)
    const lx = x - uz * 1.0 + ux * 0.6, lz = z + ux * 1.0 + uz * 0.6;
    solid("cyl6", [lx, 0.7, lz], 0, [0.09, 1.4, 0.09], [0.16, 0.18, 0.28]);
    shadow(lx, lz, 0.3, 0.4);
    // what each station works with
    const top = 0.56, at = (along, out, y) => [x + tx * along + ux * out, y, z + tz * along + uz * out];
    if (name === "library") {
      const sx = x + tx * 1.35 + ux * 0.4, sz = z + tz * 1.35 + uz * 0.4;
      solid("box", [sx, 0.6, sz], ang, [0.35, 1.2, 0.9], [0.45, 0.28, 0.20]);
      const books = [[0.85, 0.3, 0.3], [0.3, 0.55, 0.9], [0.95, 0.8, 0.3], [0.4, 0.8, 0.5]];
      for (let r = 0; r < 3; r++) for (let b = 0; b < 4; b++) {
        // the shelf is deep along the desk (local x) and wide outward (local z): books stand in a
        // row along its width with their spines showing on the side that faces the desk
        solid("box", [sx - tx * 0.08 + ux * (b - 1.5) * 0.19, 0.28 + r * 0.33, sz - tz * 0.08 + uz * (b - 1.5) * 0.19], ang,
          [0.22, 0.24, 0.14], books[(b + r) % 4], { line: false });
      }
      shadow(sx, sz, 0.6, 0.35);
      solid("box", at(0.35, 0.05, top + 0.04), ang + 0.3, [0.32, 0.06, 0.24], [0.9, 0.86, 0.75]);
    } else if (name === "drafting table") {
      solid("box", at(0, 0.05, top + 0.02), ang, [1.1, 0.03, 0.55], [0.55, 0.75, 1.0], { e: 0.25, line: false });
      solid("box", at(0.15, 0.0, top + 0.04), ang + 0.4, [0.5, 0.01, 0.04], [1, 1, 1], { e: 0.6, line: false });
      solid("box", at(-0.25, 0.1, top + 0.04), ang - 0.2, [0.04, 0.01, 0.4], [1, 1, 1], { e: 0.6, line: false });
    } else if (name === "workshop") {
      const ax = x + tx * 1.25, az = z + tz * 1.25;
      solid("box", [ax, 0.18, az], ang, [0.34, 0.36, 0.3], [0.30, 0.30, 0.38]);
      solid("box", [ax, 0.42, az], ang, [0.6, 0.14, 0.3], [0.38, 0.40, 0.50]);
      solid("box", [x - tx * 1.3 + ux * 0.3, 0.25, z - tz * 1.3 + uz * 0.3], ang + 0.4, [0.5, 0.5, 0.5], [0.70, 0.52, 0.30]);
      shadow(ax, az, 0.45, 0.35);
      solid("box", [bx + tx * 0.35 + ux * 0.2, 1.8, bz + tz * 0.35 + uz * 0.2], rot, [0.22, 0.6, 0.22], [0.55, 0.40, 0.36]);   // chimney
    } else if (name === "test bench") {
      for (let k = 0; k < 4; k++) {
        solid("cyl6", at(-0.45 + k * 0.3, 0.05, top + 0.12), 0, [0.12, 0.22, 0.12], [[0.4, 1, 0.8], [1, 0.8, 0.3], [0.5, 0.7, 1], [1, 0.5, 0.7]][k], { e: 0.5, line: false });
      }
    } else if (name === "review desk") {
      solid("box", at(-0.35, 0.05, top + 0.08), ang, [0.36, 0.16, 0.26], [0.95, 0.93, 0.85]);
      solid("box", at(0.3, 0.05, top + 0.05), ang + 0.2, [0.34, 0.06, 0.26], [0.95, 0.93, 0.85]);
    } else if (name === "terminal") {
      solid("box", at(0, 0.18, top + 0.3), ang, [0.8, 0.5, 0.08], [0.15, 0.17, 0.25]);
      solid("box", at(0, 0.13, top + 0.3), ang, [0.68, 0.38, 0.02], [0.3, 0.6, 1.0], { e: 0.9, line: false });
      solid("box", at(0, -0.1, top + 0.02), ang, [0.55, 0.03, 0.2], [0.25, 0.27, 0.36]);
    }
  }

  for (const tr of SCENERY.trees) {
    const h = tr.h;
    solid("cyl6", [tr.x, 0.3 * h, tr.z], 0, [0.22, 0.6 * h, 0.22], [0.48, 0.30, 0.22]);
    const leaf = tr.kind ? [0.12, 0.66, 0.52] : [0.24, 0.78, 0.34];
    if (tr.kind === 0) {
      solid("cone", [tr.x, 0.95 * h, tr.z], tr.ry, [1.2 * h, 1.0 * h, 1.2 * h], leaf);
      solid("cone", [tr.x, 1.55 * h, tr.z], tr.ry + 1, [0.85 * h, 0.85 * h, 0.85 * h], mix3(leaf, [0.6, 1, 0.6], 0.15));
    } else {
      solid("sph", [tr.x, 1.05 * h, tr.z], tr.ry, [1.15 * h, 1.0 * h, 1.15 * h], leaf);
    }
    shadow(tr.x + 0.2, tr.z - 0.15, 0.75 * h, 0.5);
  }
  for (const r of SCENERY.rocks) {
    solid("box", [r.x, r.s * 0.3, r.z], r.ry, [r.s, r.s * 0.75, r.s * 0.85], [0.55, 0.58, 0.74]);
    shadow(r.x + 0.1, r.z - 0.08, r.s * 0.85, 0.4);
  }
  for (const lp of SCENERY.lamps) {
    solid("cyl6", [lp.x, 0.75, lp.z], 0, [0.1, 1.5, 0.1], [0.16, 0.18, 0.28]);
    solid("box", [lp.x, 1.55, lp.z], 0, [0.26, 0.26, 0.26], [1.0, 0.78, 0.40], { e: 1.0 });
    solid("pyr", [lp.x, 1.78, lp.z], Math.PI / 4, [0.42, 0.2, 0.42], [0.16, 0.18, 0.28]);
    glows.push({ pos: [lp.x, 1.55, lp.z], r: 0.85, color: [1.0, 0.7, 0.35], a: 0.75 });
    lights.push({ pos: [lp.x, 1.3, lp.z], color: [0.7, 0.45, 0.2], radius: 2.3, pri: 0 });
    shadow(lp.x, lp.z, 0.3, 0.4);
  }
  for (const f of SCENERY.flowers) {
    solid("cyl6", [f.x, f.h / 2, f.z], 0, [0.03, f.h, 0.03], [0.2, 0.55, 0.3], ink);
    solid("sph4", [f.x, f.h + 0.04, f.z], 0, [0.12, 0.09, 0.12], f.c, { e: 0.15, line: false });
  }
  for (const t of SCENERY.tufts) solid("pyr", [t.x, t.s * 0.4, t.z], t.ry, [t.s, t.s * 0.9, t.s], [0.14, 0.50, 0.32], ink);
  for (const b of SCENERY.benches) {
    // A park bench along the plaza ring, facing the pool: its length runs along the ring (local x
    // = the tangent), its back is on the outer side (local z = outward), legs at both ends.
    const f = benchFrame(b), [ox, oz] = f.out, [tx, tz] = f.tan, wood = [0.62, 0.42, 0.28], dark = [0.50, 0.33, 0.22];
    for (const k of [-1, 0, 1]) solid("box", [b.x + ox * k * 0.1, 0.32, b.z + oz * k * 0.1], f.ry, [0.96, 0.05, 0.09], wood);   // seat slats
    for (const yb of [0.5, 0.64]) solid("box", [b.x + ox * 0.17, yb, b.z + oz * 0.17], f.ry, [0.96, 0.08, 0.04], dark);   // back rails
    for (const s2 of [-0.4, 0.4]) {
      solid("box", [b.x + tx * s2, 0.15, b.z + tz * s2], f.ry, [0.06, 0.3, 0.3], [0.26, 0.24, 0.30], ink);                    // legs
      solid("box", [b.x + tx * s2 + ox * 0.17, 0.45, b.z + tz * s2 + oz * 0.17], f.ry, [0.06, 0.34, 0.05], [0.26, 0.24, 0.30], ink);   // back posts
      solid("box", [b.x + tx * s2 * 1.05, 0.42, b.z + tz * s2 * 1.05], f.ry, [0.05, 0.04, 0.3], [0.26, 0.24, 0.30], ink);   // arm rests
    }
    shadow(b.x, b.z, 0.6, 0.35);
  }
  const fl = SCENERY.fall;
  if (fl) {   // pond, stream to the rim, and the falling sheet over the edge
    const ux = Math.cos(fl.a), uz = Math.sin(fl.a), ry = Math.atan2(ux, uz);
    solid("cyl6", [fl.x, 0.01, fl.z], 0.2, [1.75, 0.04, 1.75], [0.58, 0.58, 0.72]);
    solid("cyl", [fl.x, 0.035, fl.z], 0, [1.52, 0.02, 1.52], [0.14, 0.26, 0.30], ink);   // the pond bed
    const run = ISLAND - Math.hypot(fl.x, fl.z);
    solid("box", [fl.x + ux * (run + 0.75) / 2, 0.02, fl.z + uz * (run + 0.75) / 2], ry, [0.5, 0.04, run - 0.75], [0.30, 0.26, 0.30], ink);
    curb(fl.x, fl.z, 0.86, 12, [0.46, 0.1, 0.17], [0.66, 0.66, 0.78]);
    for (const [k, rr, sz] of [[0.6, 0.38, 0.26], [2.4, 0.42, 0.2], [4.1, 0.3, 0.17]]) {   // lily pads
      const lx = fl.x + Math.cos(k) * rr, lz = fl.z + Math.sin(k) * rr;
      solid("cyl6", [lx, 0.088, lz], k, [sz, 0.015, sz], [0.20, 0.62, 0.36], ink);
      if (k > 2) solid("sph4", [lx, 0.11, lz], 0, [0.08, 0.06, 0.08], [1.0, 0.62, 0.80], { e: 0.3, line: false });
    }
    for (let k = 0; k < 5; k++) {   // wet rocks at the lip of the fall
      const side = (k - 2) * 0.17, rx = ux * (ISLAND - 0.1) + uz * side * 1.9, rz = uz * (ISLAND - 0.1) - ux * side * 1.9;
      if (Math.abs(side) > 0.12) solid("box", [rx, 0.06, rz], k, [0.2, 0.12, 0.18], [0.42, 0.44, 0.56]);
    }
    glows.push({ pos: [ux * (ISLAND + 0.1), -5.6, uz * (ISLAND + 0.1)], r: 0.9, color: [0.6, 0.85, 1.0], a: 0.4 });
  }

  // the sky batch (turned slowly as one): clouds and little floating islets
  const ssolid = (mesh, pos, ry, s, color, o) => sky.push(Object.assign({ mesh, pos, ry, s, color }, o || {}));
  for (const cl of SCENERY.clouds) {
    const a = cl.a, cx = Math.cos(a) * cl.r, cz = Math.sin(a) * cl.r, s = cl.s;
    ssolid("sph", [cx, cl.y, cz], a, [1.6 * s, 0.9 * s, 1.2 * s], [0.92, 0.95, 1.0], { e: 0.1 });
    ssolid("sph", [cx + 0.8 * s, cl.y - 0.15, cz + 0.2], a, [1.1 * s, 0.7 * s, 0.9 * s], [0.92, 0.95, 1.0], { e: 0.1 });
    ssolid("sph", [cx - 0.8 * s, cl.y - 0.2, cz - 0.1], a, [1.0 * s, 0.6 * s, 0.8 * s], [0.92, 0.95, 1.0], { e: 0.1 });
  }
  for (const is of SCENERY.islets) {
    const x = Math.cos(is.a) * is.r, z = Math.sin(is.a) * is.r, s = is.s;
    ssolid("cyl6", [x, is.y, z], is.a, [1.6 * s, 0.25 * s, 1.6 * s], [0.12, 0.58, 0.36]);
    ssolid("cone", [x, is.y - 0.75 * s, z], is.a, [1.5 * s, -1.3 * s, 1.5 * s], [0.36, 0.26, 0.42], { line: false });
    ssolid("cone", [x + 0.2 * s, is.y + 0.45 * s, z], is.a, [0.6 * s, 0.7 * s, 0.6 * s], [0.24, 0.78, 0.34]);
  }

  // every static shadow in one buffer of ground quads
  const sp = [], sn = [];
  const Q = MESH_SRC.quad.p;
  for (const s of shadows) for (let i = 0; i < Q.length; i += 3) {
    sp.push(s.x + Q[i] * s.r, 0.075, s.z + Q[i + 1] * s.r); sn.push(Q[i], Q[i + 1], s.a);
  }
  STATIC = { land: bake(land), sky: bake(sky), shadows: { p: new Float32Array(sp), n: new Float32Array(sn) }, lights, glows,
    count: land.length + sky.length };
  return STATIC;
}

// ---------------------------------------------------------------- agents: data -> life
function seatFor(id) {
  for (const [k, who] of Object.entries(World.seats)) if (who === id) return Number(k);
  for (let i = 0; i < SCENERY.benches.length * 2; i++) if (!World.seats[i]) { World.seats[i] = id; return i; }
  return -1;
}
// A bench's frame: ry turns a box so its local x runs along the plaza ring and local z points
// outward (M4.trs maps local x -> (cos ry, -sin ry), local z -> (sin ry, cos ry) in x/z).
function benchFrame(b) {
  const len = Math.hypot(b.x, b.z) || 1, out = [b.x / len, b.z / len];
  return { ry: Math.atan2(out[0], out[1]), out, tan: [out[1], -out[0]] };
}
function seatPos(i) {
  const b = SCENERY.benches[Math.floor(i / 2)], f = benchFrame(b), s = i % 2 ? 0.22 : -0.22;
  // sit on the seat (slightly forward of the back), facing the pool (agents face local +z)
  return { x: b.x + f.tan[0] * s - f.out[0] * 0.02, z: b.z + f.tan[1] * s - f.out[1] * 0.02, face: f.ry + Math.PI };
}
function freeSeat(id) { for (const k of Object.keys(World.seats)) if (World.seats[k] === id) delete World.seats[k]; }

// Walk round the plaza ring instead of through the pool: from where you are to the ring,
// along it, then out along the target's path.
function routeTo(a, tx, tz) {
  const pts = [];
  const ra = Math.hypot(a.x, a.z), rb = Math.hypot(tx, tz);
  let aa = Math.atan2(a.z, a.x);
  const ab = Math.atan2(tz, tx);
  if (ra > PLAZA_R + 0.3 || ra < PLAZA_R - 0.6) pts.push([Math.cos(aa) * PLAZA_R, Math.sin(aa) * PLAZA_R]);
  let d = ab - aa;
  while (d > Math.PI) d -= Math.PI * 2;
  while (d < -Math.PI) d += Math.PI * 2;
  const steps = Math.floor(Math.abs(d) / 0.55);
  for (let i = 1; i <= steps; i++) { aa += d / (steps + 1); pts.push([Math.cos(aa) * PLAZA_R, Math.sin(aa) * PLAZA_R]); }
  if (rb > PLAZA_R + 0.3) pts.push([Math.cos(ab) * PLAZA_R, Math.sin(ab) * PLAZA_R]);
  pts.push([tx, tz]);
  a.route = pts;
  a.goal = [tx, tz];
}

function syncAgents(list) {
  const seen = new Set();
  const counts = {};
  const now = performance.now();
  for (const a of list || []) {
    seen.add(a.id);
    let w = World.agents[a.id];
    if (!w) {
      const hall = stationPos("hall"), r = Math.random() * 6;
      w = World.agents[a.id] = { x: hall[0] + Math.cos(r) * 2.4, z: hall[1] + Math.sin(r) * 2.4, ry: 0, phase: Math.random() * 6,
        said: "", saidAt: 0, route: [], goal: null, wanderAt: 0, stateAt: now, prevState: "" };
    }
    if (w.data && w.data.state !== a.state) {
      w.stateAt = now;
      if (a.state === "done") w.cheerAt = now;
    }
    w.data = a;
    w.color = hexRgb(a.color, hexRgb(a.id === "loki" ? "#2ee6d6" : (STATION_LAYOUT[a.station] || {}).color, [0.6, 0.7, 0.85]));
    if (a.last_message && a.last_message !== w.said) { w.said = a.last_message; w.saidAt = now; }
    // where to be: at the station's desk while the work is live; done or idle agents drift off
    // to the plaza (after a moment), sit on a bench, or wander - that part is only ambience.
    const i = counts[a.station] = (counts[a.station] || 0) + 1;
    const f = stationFrame(a.station);
    let tx, tz;
    const atDesk = a.id === "loki" ? a.state === "working" : ["working", "waiting", "blocked"].includes(a.state) ||
      (a.state !== "idle" && now - w.stateAt < 8000);
    const mode = atDesk ? "desk" : "free";
    if (w.mode !== mode && mode === "free") w.wanderAt = 0;   // just finished: head off now
    w.mode = mode;
    if (a.id === "loki" && atDesk) {
      tx = 0.9; tz = 1.75;
    } else if (atDesk) {
      const side = i === 1 ? 0 : (i % 2 ? 1 : -1) * Math.ceil((i - 1) / 2) * 0.85;
      const row = i > 5 ? 0.9 : 0;
      tx = f.x - f.u[0] * (1.05 + row) + f.tg[0] * side; tz = f.z - f.u[1] * (1.05 + row) + f.tg[1] * side;
    }
    if (atDesk) {
      freeSeat(a.id);
      w.seat = -1;
      if (!w.goal || Math.hypot(w.goal[0] - tx, w.goal[1] - tz) > 0.05) routeTo(w, tx, tz);
    }
  }
  for (const id of Object.keys(World.agents)) if (!seen.has(id)) { delete World.agents[id]; freeSeat(id); }
  if (World.selected && !World.agents[World.selected]) World.selected = "";
}

// Free agents: sit if there is a seat for "done" (they finished; a breather), otherwise drift
// between plaza spots now and then. Called per frame; decisions only every few seconds.
function wander(a, now, rnd) {
  if (a.mode !== "free" || World.reduced) return;
  const d = a.data || {};
  if (now < a.wanderAt) return;
  a.wanderAt = now + 7000 + rnd() * 9000;
  if ((d.state === "done" || d.state === "failed") && rnd() < 0.7) {
    const s = seatFor(a.data.id);
    if (s >= 0) { const p = seatPos(s); a.seat = s; routeTo(a, p.x, p.z); return; }
  }
  freeSeat(a.data.id); a.seat = -1;
  const spot = SCENERY.spots[Math.floor(rnd() * SCENERY.spots.length)];
  const j = (rnd() - 0.5) * 0.9;
  routeTo(a, spot[0] + j, spot[1] - j);
}

async function fetchWorld() {
  if (World.fetching || typeof state === "undefined" || !state.token) return;
  World.fetching = true;
  try {
    const data = await api("/world");
    if (data && data.ok) {
      World.data = data; syncAgents(data.agents); renderLegend();
      if (window.MMO) window.MMO.onWorld(data);
    }
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
    row.dataset.agent = a.id;
    if (a.id === World.selected) row.classList.add("selected");
    const dot = el("span", "agent-dot");
    dot.style.background = a.color || STATE_COLOR[a.state] || "#8fb3d9";
    row.append(dot, el("b", "", a.name), el("span", "pill " + (a.state === "working" ? "working" : a.state === "blocked" ? "blocked" : a.state === "done" ? "done" : ""), a.state),
               el("span", "muted", (a.station || "") + (a.task ? " · " + a.task : "")));
    row.addEventListener("click", () => selectAgent(a.id, World.views.panel));
    box.append(row);
  }
}

// ---------------------------------------------------------------- particles (ambience)
function emit(kind, pos, n) {
  if (World.reduced || World.particles.length > 160) return;
  for (let i = 0; i < (n || 1); i++) {
    const r = Math.random, p = { kind, x: pos[0], y: pos[1], z: pos[2], vx: 0, vy: 0, vz: 0, life: 1, age: 0 };
    if (kind === "spark") { p.vx = (r() - 0.5) * 2.2; p.vy = 1.2 + r() * 1.5; p.vz = (r() - 0.5) * 2.2; p.life = 0.45 + r() * 0.3; p.c = [1, 0.62 + r() * 0.3, 0.25]; }
    if (kind === "bubble") { p.vx = (r() - 0.5) * 0.15; p.vy = 0.45 + r() * 0.3; p.vz = (r() - 0.5) * 0.15; p.life = 1.2 + r(); p.c = [0.45, 1, 0.85]; }
    if (kind === "smoke") { p.vx = 0.15 + r() * 0.1; p.vy = 0.5 + r() * 0.2; p.vz = (r() - 0.5) * 0.1; p.life = 2.5 + r(); p.c = [0.62, 0.64, 0.72]; }
    if (kind === "page") { p.vx = (r() - 0.5) * 0.5; p.vy = 0.6 + r() * 0.3; p.vz = (r() - 0.5) * 0.5; p.life = 1.0; p.c = [1, 0.97, 0.88]; }
    if (kind === "confetti") { p.vx = (r() - 0.5) * 3; p.vy = 2.2 + r() * 2; p.vz = (r() - 0.5) * 3; p.life = 1.4 + r() * 0.6; p.c = [[1, 0.4, 0.6], [1, 0.85, 0.3], [0.4, 0.9, 1], [0.6, 1, 0.5]][Math.floor(r() * 4)]; p.ry = r() * 6; }
    if (kind === "mist") { p.vx = (r() - 0.5) * 0.4; p.vy = -0.1 + r() * 0.3; p.vz = (r() - 0.5) * 0.4; p.life = 1.6 + r(); p.c = [0.75, 0.88, 1]; }
    World.particles.push(p);
  }
}
function stepParticles(dt) {
  const P = World.particles;
  for (let i = P.length - 1; i >= 0; i--) {
    const p = P[i];
    p.age += dt;
    if (p.age >= p.life) { P.splice(i, 1); continue; }
    if (p.kind === "spark" || p.kind === "confetti") p.vy -= 6 * dt;
    if (p.kind === "confetti") { p.vx *= 0.98; p.vz *= 0.98; p.ry += dt * 8; if (p.y < 0.08) { p.y = 0.08; p.vy = 0; p.vx *= 0.8; p.vz *= 0.8; } }
    p.x += p.vx * dt; p.y += p.vy * dt; p.z += p.vz * dt;
  }
}

// ---------------------------------------------------------------- other machines' islands
// Where a linked machine's island floats: a stable spot from its name (so it never jumps when
// another machine joins), spread round your island at different heights.
function machineIsland(name, slot) {
  let h = 2166136261;
  for (const ch of String(name)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  const ang = MACHINE_SLOTS[slot] + (((h >>> 8) % 100) / 100 - 0.5) * 0.18;
  const r = 21 + (h >>> 12) % 4, y = -1.5 + ((h >>> 20) % 40) / 12.5;
  return { cx: Math.cos(ang) * r, cz: Math.sin(ang) * r, y, ang, R: 3.4, seed: h % 100000 };
}
// the far side of your island from where the camera starts (yaw 0.6), fanned out so islands
// never overlap; a machine keeps its slot (picked from its name) unless another already has it
const MACHINE_SLOTS = [3.74, 3.14, 4.34, 2.54, 4.94, 1.94];
function machineSlots(names) {
  const used = new Set(), out = {};
  for (const n of names.slice().sort()) {
    let h = 2166136261;
    for (const ch of String(n)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
    let k = h % MACHINE_SLOTS.length;
    while (used.has(k)) k = (k + 1) % MACHINE_SLOTS.length;
    used.add(k); out[n] = k;
  }
  return out;
}

// ---------------------------------------------------------------- critters
// Island life the owner asked for more of: a fox (LOKI's favourite) trots between the flower
// patches, sits to watch the agents, follows LOKI now and then and curls up asleep at night;
// two rabbits hop about. Pure ambience - built from the same boxes, cel shading and ink lines.
function critterSpots() {
  if (World.spots) return World.spots;
  World.spots = SCENERY.flowers.map((f) => [f.x, f.z]).concat(SCENERY.tufts.filter((_, i) => i % 3 === 0).map((f) => [f.x, f.z]));
  return World.spots;
}
function critters(solid, shadow, t, dt, night) {
  const spots = critterSpots();
  if (!spots.length) return;
  if (!World.critters) {
    World.critters = [
      { kind: "fox", x: spots[0][0], z: spots[0][1], ry: 0, speed: 0.75, phase: 0, mode: "rest", until: 0, tx: 0, tz: 0 },
      { kind: "rabbit", x: spots[3 % spots.length][0], z: spots[3 % spots.length][1], ry: 1, speed: 0.6, phase: 0, mode: "rest", until: 0, tx: 0, tz: 0 },
      { kind: "rabbit", x: spots[9 % spots.length][0], z: spots[9 % spots.length][1], ry: 2, speed: 0.6, phase: 1, mode: "rest", until: 0, tx: 0, tz: 0 },
    ];
  }
  const loki = World.agents.loki;
  for (const c of World.critters) {
    const asleep = c.kind === "fox" && night > 0.75;
    if (c.mode === "rest" && t > c.until && !asleep) {
      // pick somewhere near (no long trips across the plaza); the fox sometimes goes to see LOKI
      let tx, tz;
      if (c.kind === "fox" && loki && Math.random() < 0.25 && Math.hypot(loki.x, loki.z) > 3.6) {
        tx = loki.x + 0.9; tz = loki.z + 0.9;
      } else {
        const near = spots.filter((p) => { const d = Math.hypot(p[0] - c.x, p[1] - c.z); return d > 0.8 && d < 4.5; });
        const p = (near.length ? near : spots)[Math.floor(Math.random() * (near.length || spots.length))];
        tx = p[0]; tz = p[1];
      }
      if (Math.hypot(tx, tz) < 3.9) { const k = 3.9 / (Math.hypot(tx, tz) || 1); tx *= k; tz *= k; }   // never into the plaza/pool
      c.tx = tx; c.tz = tz; c.mode = "walk";
    }
    if (c.mode === "walk") {
      const dx = c.tx - c.x, dz = c.tz - c.z, d = Math.hypot(dx, dz);
      if (d < 0.08) { c.mode = "rest"; c.until = t + (c.kind === "fox" ? 3 + Math.random() * 7 : 1 + Math.random() * 4); }
      else {
        const step = Math.min(d, dt * c.speed * (c.kind === "rabbit" ? (Math.sin(c.phase) > 0 ? 1.6 : 0.2) : 1));
        c.x += dx / d * step; c.z += dz / d * step;
        c.ry = angLerp(c.ry, Math.atan2(dx, dz), Math.min(1, dt * 8));
        c.phase += dt * (c.kind === "rabbit" ? 9 : 11);
      }
    }
    const f = [Math.sin(c.ry), Math.cos(c.ry)], sd = [Math.cos(c.ry), -Math.sin(c.ry)], walking = c.mode === "walk";
    const at = (fw, sw, y) => [c.x + f[0] * fw + sd[0] * sw, y, c.z + f[1] * fw + sd[1] * sw];
    if (c.kind === "fox") {
      const orange = [0.93, 0.47, 0.17], cream = [0.98, 0.93, 0.84], dark = [0.22, 0.14, 0.12];
      const lift = asleep ? -0.1 : 0, bob = walking ? Math.abs(Math.sin(c.phase)) * 0.025 : 0;
      solid("box", at(0, 0, 0.27 + lift + bob), c.ry, [0.22, 0.19, 0.46], orange);                          // body
      solid("box", at(0.17, 0, 0.23 + lift + bob), c.ry, [0.17, 0.12, 0.13], cream, { line: false });       // chest
      const hy = asleep ? 0.2 : 0.42 + bob, hf = asleep ? 0.2 : 0.3, look = asleep ? 0 : Math.sin(t * 0.7 + c.x) * 0.35 * (walking ? 0.2 : 1);
      solid("box", at(hf, 0, hy), c.ry + look, [0.2, 0.18, 0.19], orange);                                  // head
      solid("box", at(hf + 0.14, 0, hy - 0.04), c.ry + look, [0.09, 0.08, 0.12], cream);                    // snout
      solid("box", at(hf + 0.21, 0, hy - 0.02), c.ry + look, [0.04, 0.04, 0.03], dark, { line: false });    // nose
      for (const s2 of [-1, 1]) {
        solid("pyr", at(hf - 0.01, s2 * 0.065, hy + 0.15), c.ry + look, [0.08, 0.13, 0.05], orange);       // ears
        if (!asleep) solid("box", at(hf + 0.09, s2 * 0.05, hy + 0.03), c.ry + look, [0.03, 0.03, 0.02], dark, { line: false });   // eyes
      }
      const wag = walking ? Math.sin(c.phase * 0.5) * 0.25 : Math.sin(t * 1.5) * 0.12;
      const tailSide = asleep ? 0.2 : 0;
      solid("box", at(-0.34, tailSide + wag * 0.3, 0.3 + lift), c.ry + wag + (asleep ? 1.2 : 0), [0.12, 0.12, 0.3], orange);   // tail
      solid("box", at(-0.52, tailSide + wag * 0.5, 0.3 + lift), c.ry + wag + (asleep ? 1.2 : 0), [0.11, 0.11, 0.1], cream);    // white tip
      if (!asleep) for (const [fw, s2] of [[0.15, 1], [0.15, -1], [-0.15, 1], [-0.15, -1]]) {
        const swing = walking ? Math.sin(c.phase + (fw > 0 ? 0 : Math.PI) + (s2 > 0 ? 0 : Math.PI)) * 0.06 : 0;
        solid("box", at(fw + swing, s2 * 0.07, 0.09), c.ry, [0.05, 0.18, 0.05], dark, { line: false });   // legs
      }
      shadow(c.x, c.z, 0.38, 0.45);
      if (asleep && Math.random() < dt * 0.6) emit("bubble", [c.x, 0.5, c.z]);   // little z's
    } else {
      const fur = [0.62, 0.55, 0.50], hop = walking ? Math.max(0, Math.sin(c.phase)) * 0.12 : 0;
      solid("box", at(0, 0, 0.1 + hop), c.ry, [0.15, 0.14, 0.21], fur);
      solid("box", at(0.12, 0, 0.19 + hop), c.ry, [0.12, 0.12, 0.12], fur);
      for (const s2 of [-1, 1]) solid("box", at(0.1, s2 * 0.035, 0.31 + hop), c.ry, [0.03, 0.14, 0.04], mix3(fur, [1, 0.8, 0.8], 0.25));
      solid("sph4", at(-0.12, 0, 0.13 + hop), 0, [0.07, 0.07, 0.07], [0.97, 0.96, 0.94], { line: false });
      shadow(c.x, c.z, 0.22, 0.4);
    }
  }
}

// ---------------------------------------------------------------- building the dynamic scene
// Each frame collects what moves (agents, lamp orbs, banners, particles, lights) and then
// draws it in passes: sky, ink outlines, cel-shaded solids, shadows, glows.
function sceneList(view, t, dt, P) {
  const L = { solids: [], clear: [], shadows: [], glows: [], puffs: [], lights: STATIC.lights.slice() };
  const solid = (mesh, pos, ry, s, color, o) => (o && o.a < 1 ? L.clear : L.solids).push(Object.assign({ mesh, pos, ry, s, color }, o || {}));
  const shadow = (x, z, r, a) => L.shadows.push({ x, z, r, a: Math.min(1, (a == null ? 0.5 : a) * 1.3) });
  const glow = (pos, r, color, a) => L.glows.push({ pos, r, color, a: a == null ? 1 : a });
  const light = (pos, color, radius, pri) => L.lights.push({ pos, color, radius, pri: pri || 1 });
  const ring = (x, z, r, color, spin, e) => {   // a dashed ring on the ground: opaque, so it reads at any light
    for (let k = 0; k < 10; k++) {
      const an = spin + k * Math.PI / 5;
      solid("box", [x + Math.cos(an) * r, 0.1, z + Math.sin(an) * r], -an, [0.2, 0.05, 0.08], color, { e, line: false });
    }
  };
  const now = performance.now();
  const night = 1 - P.dayK;
  for (const g of STATIC.glows) L.glows.push(g);

  // the conductor's beacon: it pulses when a board message just arrived
  const fresh = Object.values(World.agents).some((a) => a.said && now - a.saidAt < 1500);
  for (const a of Object.values(World.agents)) {   // a new board line: the beacon pings the pool
    if (a.said && a.saidAt !== a.rippled && now - a.saidAt < 1500) {
      a.rippled = a.saidAt;
      const ang = Math.random() * Math.PI * 2;
      addRipple("pool", Math.cos(ang) * 0.85, Math.sin(ang) * 0.85, 1);
    }
  }
  const fl = SCENERY.fall;
  if (fl && !World.reduced) {   // now and then a fish jumps in the pond
    if (!World.fish && now > World.fishAt) {
      const a0 = Math.random() * 6.28, r0 = 0.15 + Math.random() * 0.3;
      World.fish = { x: fl.x + Math.cos(a0) * r0, z: fl.z + Math.sin(a0) * r0, dir: a0 + 1.6 + Math.random(), t0: t };
      addRipple("pond", World.fish.x, World.fish.z, 0.8);
    }
    if (World.fish) {
      const f = World.fish, k = (t - f.t0) / 0.7;
      if (k >= 1) {
        addRipple("pond", f.x + Math.cos(f.dir) * 0.32, f.z + Math.sin(f.dir) * 0.32, 0.9);
        World.fish = null; World.fishAt = now + 5000 + Math.random() * 7000;
      } else {
        const fx = f.x + Math.cos(f.dir) * 0.32 * k, fz = f.z + Math.sin(f.dir) * 0.32 * k, fy = 0.09 + Math.sin(k * Math.PI) * 0.3;
        const ry = Math.atan2(Math.cos(f.dir), Math.sin(f.dir));
        solid("sph4", [fx, fy, fz], ry, [0.07, 0.07 + 0.03 * Math.cos(k * Math.PI), 0.16], [1.0, 0.55, 0.25], { e: 0.2, line: false });
      }
    }
  }
  const by = 2.85 + Math.sin(t * 1.4) * 0.08;
  solid("sph", [-0.25, by, 0], 0, [0.36, 0.36, 0.36], [0.6, 1, 0.95], { e: fresh ? 1.6 : 1.1, line: false });
  glow([-0.25, by, 0], fresh ? 1.5 : 1.1, [0.3, 1, 0.9], 0.8);
  light([-0.25, 2.2, 0], [0.1, 0.5, 0.48], 3.4, 2);

  for (const [name, st] of Object.entries(STATION_LAYOUT)) {
    if (name === "hall") continue;
    const f = stationFrame(name), { x, z } = f, [ux, uz] = f.u;
    const c = hexRgb(st.color, [0.5, 0.6, 0.7]);
    const workers = Object.values(World.agents).filter((a) => a.data && a.data.station === name && a.data.state === "working" && a.mode === "desk");
    const busy = workers.length > 0;
    const lx = x - uz * 1.0 + ux * 0.6, lz = z + ux * 1.0 + uz * 0.6;
    const oy = 1.55 + Math.sin(t * 1.4 + x) * 0.05;
    solid("sph", [lx, oy, lz], 0, [0.32, 0.32, 0.32], mix3(c, [1, 1, 1], 0.25), { e: busy ? 1.1 : 0.55, line: false });
    glow([lx, oy, lz], busy ? 1.2 : 0.8, c, busy ? 0.9 : 0.55);
    light([lx, 1.2, lz], scale3(c, busy ? 0.95 : 0.55), busy ? 3.8 : 3.0, busy ? 2 : 1);
    if (busy && !World.reduced) {   // the work shows: sparks, bubbles, smoke, pages, a lit screen
      const top = [x, 0.62, z];
      if (name === "workshop") {
        const bx = x + ux * 2.1 + f.tg[0] * 0.35 + ux * 0.2, bz = z + uz * 2.1 + f.tg[1] * 0.35 + uz * 0.2;
        if (Math.random() < dt * 2.2) emit("smoke", [bx, 2.15, bz]);
      }
      if (name === "test bench" && Math.random() < dt * 4) emit("bubble", [x + f.tg[0] * (Math.random() - 0.5) * 0.9, 0.85, z + f.tg[1] * (Math.random() - 0.5) * 0.9]);
      if (name === "library" && Math.random() < dt * 0.6) emit("page", top);
      if (name === "terminal") glow([x - ux * 0.13, 0.86, z - uz * 0.13], 0.75 + Math.sin(t * 13) * 0.08, [0.3, 0.6, 1.0], 0.6);
      if (name === "drafting table") glow([x, 0.7, z], 0.8, [0.55, 0.75, 1.0], 0.35 + 0.15 * Math.sin(t * 3));
    }
  }

  // team banners in the plaza, one per live team: the flag in the team's colour, a pip per
  // real stage (lit = done, pulsing = now)
  const teams = ((World.data && World.data.teams) || []).filter((tm) => tm.status !== "done" && tm.status !== "failed").slice(0, SCENERY.banners.length);
  view.teamSpots = [];
  teams.forEach((tm, i) => {
    const b = SCENERY.banners[i], col = hashColor(tm.id), out = [Math.cos(b.a), Math.sin(b.a)];
    // the flag hangs from the pole along the plaza ring (local x = the tangent), so it reads
    // face-on from the plaza and from the camera's usual orbit
    const ry = Math.atan2(out[0], out[1]), tan = [out[1], -out[0]];
    solid("cyl6", [b.x, 0.85, b.z], 0, [0.07, 1.7, 0.07], [0.20, 0.22, 0.32]);
    solid("sph4", [b.x, 1.73, b.z], 0, [0.12, 0.12, 0.12], [1, 0.9, 0.5], { e: 0.6, line: false });
    solid("box", [b.x + tan[0] * 0.3, 1.66, b.z + tan[1] * 0.3], ry, [0.62, 0.03, 0.03], [0.20, 0.22, 0.32]);   // crossbar
    const wave = World.reduced ? 0 : Math.sin(t * 3 + i) * 0.06;
    solid("box", [b.x + tan[0] * 0.32, 1.42, b.z + tan[1] * 0.32], ry + wave, [0.56, 0.44, 0.03], col);
    solid("box", [b.x + tan[0] * 0.32, 1.17, b.z + tan[1] * 0.32], ry + wave, [0.56, 0.06, 0.035], mix3(col, [0, 0, 0], 0.3), { line: false });   // hem
    const stages = tm.stages && tm.stages.length ? tm.stages : ["plan", "build", "check"];
    const cur = stages.indexOf(tm.stage);
    stages.forEach((sname, k) => {
      const along = 0.32 + (k - (stages.length - 1) / 2) * 0.14;
      const pos = [b.x + tan[0] * along - out[0] * 0.03, 1.42, b.z + tan[1] * along - out[1] * 0.03];   // pips sewn on the flag
      const lit = cur > k || tm.status === "done", now2 = k === cur;
      solid("box", pos, ry, [0.09, 0.09, 0.03], lit ? [0.45, 1, 0.55] : now2 ? [1, 1, 1] : [0.3, 0.32, 0.42],
        { e: lit ? 0.7 : now2 ? 0.4 + 0.4 * Math.abs(Math.sin(t * 3)) : 0, line: false });
    });
    shadow(b.x, b.z, 0.25, 0.4);
    view.teamSpots.push({ id: tm.id, pos: [b.x, 2.05, b.z], goal: tm.goal || "", stage: tm.stage || "" });
  });

  // Every device that runs LOKI has its own island in the same sky. The island you stand on is
  // THIS machine (its name floats over the spire: "you are here"); each linked machine is a
  // whole island of its own out in the space around it - its own houses in its colours (a Mac
  // is silver, a PC blue), its own trees, a beacon that is lit while it answers, a little
  // figure for each job running there - joined to yours by a bridge of light (the peer link,
  // LAN or relay) with packets travelling both ways. Click a machine's name to fly there.
  view.machineSpots = [];
  const self = (World.data && World.data.self) || {};
  const selfName = self.name || "this computer";
  view.machineSpots.push({ key: "machine:self", pos: [-0.25, 3.4, 0], name: selfName, sub: "you are here", home: true });
  const machines = ((World.data && World.data.machines) || []).filter((m) => m.name !== self.name).slice(0, 6);
  const slots = machineSlots(machines.map((m) => m.name));
  machines.forEach((m, i) => {
    const isl = machineIsland(m.name, slots[m.name]);
    const { cx, cz, y: y0, ang, R } = isl, ok = m.ok;
    const mac = /darwin|mac/i.test(m.os || "") || /mac/i.test(m.name);
    const roof = mac ? [0.80, 0.82, 0.90] : /windows|win/i.test(m.os || "") || /pc|win/i.test(m.name) ? [0.30, 0.55, 0.95] : [0.55, 0.85, 0.55];
    const tone = ok ? [0.25, 0.95, 0.85] : [0.55, 0.55, 0.62];
    const bob = World.reduced ? 0 : Math.sin(t * 0.5 + i) * 0.15, y = y0 + bob;
    const rnd = seeded(isl.seed);
    // the island itself: grass, a band of earth, a rock cone with crystals underneath
    solid("cyl6", [cx, y - 0.2, cz], isl.seed % 7, [R * 2, 0.4, R * 2], ok ? [0.12, 0.6, 0.38] : [0.28, 0.42, 0.36], { g: 0.9 });
    solid("cyl6", [cx, y - 0.65, cz], isl.seed % 5, [R * 2 - 0.2, 0.6, R * 2 - 0.2], [0.55, 0.34, 0.30]);
    solid("cone", [cx, y - 2.6, cz], isl.seed % 3, [R * 1.9, -3.6, R * 1.9], [0.36, 0.26, 0.42], { line: false });
    solid("pyr", [cx + R * 0.3, y - 3.3, cz - R * 0.2], 0.4, [0.5, -1.2, 0.5], tone, { e: ok ? 0.7 : 0.1, line: false });
    // its house (in the machine's colours), a path, a lamp
    const hx = cx + Math.cos(ang + 0.6) * R * 0.35, hz = cz + Math.sin(ang + 0.6) * R * 0.35, hr = Math.atan2(cx - hx, cz - hz);
    solid("box", [hx, y + 0.55, hz], hr, [1.5, 1.1, 1.3], [0.93, 0.86, 0.74]);
    solid("pyr", [hx, y + 1.55, hz], hr + Math.PI / 4, [2.25, 0.9, 2.0], roof);
    solid("box", [hx + Math.sin(hr) * 0.66, y + 0.6, hz + Math.cos(hr) * 0.66], hr, [0.42, 0.34, 0.04], [1.0, 0.82, 0.45], { e: ok ? 0.9 : 0.1, line: false });
    shadow(hx + 0.2, hz - 0.2, 1.3, 0.45);
    for (let k = 0; k < 4; k++) {   // trees, from the machine's own seed
      const a2 = rnd() * Math.PI * 2, r2 = R * (0.55 + rnd() * 0.3), tx = cx + Math.cos(a2) * r2, tz = cz + Math.sin(a2) * r2, h = 0.8 + rnd() * 0.5;
      if (Math.hypot(tx - hx, tz - hz) < 1.3) continue;
      solid("cyl6", [tx, y + 0.3 * h, tz], 0, [0.22, 0.6 * h, 0.22], [0.48, 0.30, 0.22]);
      solid("cone", [tx, y + 0.95 * h, tz], k, [1.1 * h, 1.0 * h, 1.1 * h], k % 2 ? [0.24, 0.78, 0.34] : [0.12, 0.66, 0.52]);
      shadow(tx + 0.15, tz - 0.1, 0.65 * h, 0.45);
    }
    // the beacon tower: lit while this machine answers
    const bx = cx - Math.cos(ang + 0.6) * R * 0.3, bz = cz - Math.sin(ang + 0.6) * R * 0.3;
    solid("cyl6", [bx, y + 1.3, bz], 0, [0.24, 2.6, 0.24], [0.18, 0.2, 0.3]);
    const beacon = [bx, y + 2.85 + (ok && !World.reduced ? Math.sin(t * 2 + i) * 0.06 : 0), bz];
    solid("sph", beacon, 0, [0.45, 0.45, 0.45], tone, { e: ok ? 1.3 : 0.15, line: false });
    if (ok) { glow(beacon, 1.4, tone, 0.8); light([beacon[0], beacon[1] - 0.4, beacon[2]], scale3(tone, 0.7), 4.5, 1); }
    // a figure for each job running there (blue: working, red: needs you)
    const people = Math.min(5, (m.working || 0) + (m.blocked || 0));
    for (let k = 0; k < people; k++) {
      const a2 = (World.reduced ? 0 : t * 0.35) + k * (Math.PI * 2 / Math.max(1, people)), fx = bx + Math.cos(a2) * 1.3, fz = bz + Math.sin(a2) * 1.3;
      const col = k < (m.working || 0) ? [0.55, 0.75, 1.0] : [1.0, 0.45, 0.45];
      solid("cyl", [fx, y + 0.35, fz], a2, [0.3, 0.45, 0.3], col);
      solid("sph", [fx, y + 0.72, fz], a2, [0.3, 0.3, 0.3], col.map((v) => Math.min(1, v * 1.1)));
      shadow(fx, fz, 0.3, 0.5);
    }
    // the bridge of light from your island's edge to theirs
    const dir = norm([cx, 0, cz]);
    const a0 = [dir[0] * (ISLAND - 0.3), 0.3, dir[2] * (ISLAND - 0.3)];
    const a1 = [cx - dir[0] * (R - 0.3), y + 0.2, cz - dir[2] * (R - 0.3)];
    const N = 22, lift = 1.6 + Math.abs(y0) * 0.3;
    for (let k = 0; k <= N; k++) {
      const u = k / N, p = mix3(a0, a1, u);
      p[1] += Math.sin(u * Math.PI) * lift;
      solid("box", p, Math.atan2(dir[0], dir[2]), [0.12, 0.05, 0.12], tone, { e: ok ? 0.9 : 0.05, line: false });
    }
    if (ok && !World.reduced) for (let k = 0; k < 3; k++) {   // packets travelling both ways
      const u = ((t * 0.3 + k / 3) % 1), d2 = k % 2 ? u : 1 - u, p = mix3(a0, a1, d2);
      p[1] += Math.sin(d2 * Math.PI) * lift + 0.12;
      glow(p, 0.35, k % 2 ? [0.4, 1, 0.9] : [1, 0.85, 0.4], 0.95);
    }
    view.machineSpots.push({ key: "machine:" + m.name, pos: [bx, y + 3.7, bz], focus: [cx, y + 0.6, cz], name: m.name,
      sub: ok ? (m.relay ? "via relay · " : "") + (m.ms != null ? m.ms + " ms" : "") + (m.working ? " · " + m.working + " working" : "") +
        (m.blocked ? " · " + m.blocked + " need you" : "") : "offline" + (m.error ? " · " + m.error.slice(0, 60) : "") });
  });

  // the creations hall: what LOKI made hangs here - one lit frame per newest piece (a picture's
  // frame in its own colour, a video's with a play mark), and its name opens Settings > Creations
  const gal = SCENERY.gallery, made = (World.data && World.data.creations) || { count: 0, latest: [] };
  if (gal) {
    const face = Math.atan2(-gal.x, -gal.z);   // the open side looks at the plaza
    const fx = Math.sin(face), fz = Math.cos(face), sx = Math.cos(face), sz = -Math.sin(face);
    const at = (u, v, h) => [gal.x + sx * u + fx * v, h, gal.z + sz * u + fz * v];
    solid("box", at(0, 0, 0.08), face, [3.4, 0.16, 2.0], [0.82, 0.78, 0.72]);            // floor
    solid("box", at(0, -0.85, 1.05), face, [3.4, 1.9, 0.18], [0.95, 0.92, 0.86]);         // back wall
    for (const u of [-1.6, 1.6]) solid("box", at(u, 0.2, 1.05), face, [0.16, 1.9, 0.16], [0.66, 0.5, 0.38]);
    solid("box", at(0, -0.1, 2.08), face, [3.8, 0.16, 2.3], [0.62, 0.36, 0.42]);         // roof slab
    solid("pyr", at(0, -0.1, 2.5), face + Math.PI / 4, [3.2, 0.7, 3.2], [0.85, 0.45, 0.5]);
    shadow(gal.x, gal.z, 2.2, 0.5);
    const hung = (made.latest || []).slice(0, 5);
    hung.forEach((c, k) => {
      const u = (k - (hung.length - 1) / 2) * 0.62, y = 1.15 + (k % 2) * 0.12;
      let h = 0;
      for (const ch of c.title || "") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
      const hue = (h % 360) / 360, col = [0.5 + 0.45 * Math.cos(6.283 * hue), 0.5 + 0.45 * Math.cos(6.283 * (hue - 0.33)),
        0.5 + 0.45 * Math.cos(6.283 * (hue - 0.67))];
      solid("box", at(u, -0.74, y), face, [0.52, 0.52, 0.05], [0.25, 0.18, 0.12]);        // the frame
      solid("box", at(u, -0.71, y), face, [0.42, 0.42, 0.04], col, { e: 0.6, line: false }); // the piece
      if (c.show === "video") solid("pyr", at(u, -0.68, y), face, [0.14, 0.02, 0.14], [1, 1, 1], { e: 1, line: false });
    });
    if (hung.length) light(at(0, 0.3, 1.6), [1.0, 0.85, 0.6], 3.2, 0);
    view.machineSpots.push({ key: "creations", pos: at(0, 0, 3.2), name: "Creations",
      sub: made.count ? made.count + " made · newest: " + ((made.latest[0] || {}).title || "").slice(0, 34) : "ask LOKI to make something",
      gallery: true });
  }

  // agents
  const list = Object.entries(World.agents);
  const rnd = Math.random;
  for (const [, a] of list) wander(a, now, rnd);
  for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) {   // don't stand inside each other
    const A = list[i][1], B = list[j][1];
    if (A.seat >= 0 && A.mode === "free" || B.seat >= 0 && B.mode === "free") continue;
    const dx = B.x - A.x, dz = B.z - A.z, d = Math.hypot(dx, dz);
    if (d > 0.001 && d < 0.62) { const k = (0.62 - d) * 0.5 * Math.min(1, dt * 8) / d; A.x -= dx * k; A.z -= dz * k; B.x += dx * k; B.z += dz * k; }
  }
  for (const [id, a] of list) {
    const d = a.data || {};
    let walking = false;
    if (a.route && a.route.length) {
      const [px, pz] = a.route[0], dx = px - a.x, dz = pz - a.z, dist = Math.hypot(dx, dz);
      const speed = d.state === "blocked" ? 2.6 : a.mode === "free" ? 1.3 : 2.2;
      if (dist < 0.06) a.route.shift();
      else { const step = Math.min(dist, dt * speed); a.x += dx / dist * step; a.z += dz / dist * step; a.ry = angLerp(a.ry, Math.atan2(dx, dz), Math.min(1, dt * 10)); walking = true; }
    }
    const seated = !walking && a.mode === "free" && a.seat >= 0 && a.route.length === 0;
    if (!walking) {
      if (seated) a.ry = angLerp(a.ry, seatPos(a.seat).face, Math.min(1, dt * 6));
      else if (a.mode === "desk" && d.station) { const s = id === "loki" ? [-0.25, 0] : stationPos(d.station); a.ry = angLerp(a.ry, Math.atan2(s[0] - a.x, s[1] - a.z), Math.min(1, dt * 6)); }
    }
    // chit-chat: two free agents standing near each other turn to face and "talk" (no words)
    a.chatting = false;
    if (!walking && a.mode === "free" && !World.reduced) {
      for (const [oid, o] of list) {
        if (oid === id || o.mode !== "free" || (o.route && o.route.length)) continue;
        if (Math.hypot(o.x - a.x, o.z - a.z) < 1.5) { a.chatting = true; if (!seated) a.ry = angLerp(a.ry, Math.atan2(o.x - a.x, o.z - a.z), Math.min(1, dt * 4)); break; }
      }
    }
    a.phase += dt * (walking ? 9 : d.state === "working" ? 7 : 2);
    let bob = walking ? Math.abs(Math.sin(a.phase)) * 0.12 : d.state === "working" ? Math.abs(Math.sin(a.phase)) * 0.06 : Math.sin(a.phase) * 0.02;
    const cheer = a.cheerAt && now - a.cheerAt < 2400 && !World.reduced;
    if (cheer) {
      bob = Math.abs(Math.sin((now - a.cheerAt) / 160)) * 0.45;
      if (!a.cheered) { a.cheered = true; emit("confetti", [a.x, 1.6, a.z], 26); }
    } else a.cheered = false;
    const slump = d.state === "failed" ? 0.85 : 1;
    const col = d.state === "failed" ? [0.75, 0.38, 0.42] : a.color;
    // People-sized next to the benches, desks and doors (about 1 unit tall; LOKI a head taller).
    const big = (id === "loki" ? 1.15 : 0.95);
    a.big = big;
    const sit = seated ? 0.345 - 0.11 * big : 0;    // the body's base rests on the bench seat (0.345)
    const y0 = bob + sit;
    const fwd = [Math.sin(a.ry), Math.cos(a.ry)], side = [Math.cos(a.ry), -Math.sin(a.ry)];
    shadow(a.x + 0.06, a.z - 0.05, 0.42 * big, 0.7);
    // body, head, visor
    solid("cyl", [a.x, 0.42 * big * slump + y0, a.z], a.ry, [0.42 * big, 0.62 * big * slump, 0.42 * big], col, { s2: 0.25 });
    const hy = (0.98 * slump) * big + y0;
    solid("sph", [a.x, hy, a.z], a.ry, [0.44 * big, 0.44 * big, 0.44 * big], col.map((v) => Math.min(1, v * 1.12 + 0.05)), { s2: 0.4 });
    solid("box", [a.x + fwd[0] * 0.18 * big, hy + 0.04 * big, a.z + fwd[1] * 0.18 * big], a.ry, [0.28 * big, 0.09 * big, 0.08], [0.6, 0.98, 1.0], { e: 0.45, line: false });
    // feet that step while walking, tucked when sitting
    for (const s of [-1, 1]) {
      const stride = walking ? Math.sin(a.phase) * s * 0.11 * big : 0;
      const fy = 0.05;                                // feet stay on the ground, also when seated
      const out = seated ? 0.3 * big : 0;
      solid("box", [a.x + side[0] * s * 0.11 * big + fwd[0] * (stride + out), fy + Math.max(0, -stride) * 0.4, a.z + side[1] * s * 0.11 * big + fwd[1] * (stride + out)],
        a.ry, [0.11 * big, 0.08 * big, 0.17 * big], mix3(col, [0.05, 0.05, 0.1], 0.5), { line: false });
    }
    // arms: swinging when walking, acting out the work at the desk
    const st = d.station;
    const working = d.state === "working" && a.mode === "desk" && !walking;
    for (const s of [-1, 1]) {
      let fo = walking ? -Math.sin(a.phase) * s * 0.09 * big : 0, ay = 0.55 * big * slump + y0, so = 0.27 * big;
      if (working) {
        if (st === "workshop" && s === 1) { const k = Math.abs(Math.sin(t * 5 + a.phase)); fo = 0.12 * big; ay += k * 0.22 * big; if (k > 0.97 && !a.hit) { a.hit = true; emit("spark", [a.x + fwd[0] * 0.55, 0.62, a.z + fwd[1] * 0.55], 5); } else if (k < 0.5) a.hit = false; }
        else if (st === "terminal" || st === "test bench") { fo = 0.14 * big; ay += Math.abs(Math.sin(t * 14 + s)) * 0.04 * big; so = 0.2 * big; }
        else if (st === "library") { fo = 0.16 * big; ay += 0.08 * big; so = 0.18 * big; }
        else if (st === "drafting table" && s === 1) { fo = 0.15 * big; so = (0.2 + Math.sin(t * 2.2) * 0.1) * big; }
        else if (st === "review desk" && s === 1) { fo = 0.14 * big; ay += Math.abs(Math.sin(t * 3.4)) * 0.14 * big; }
        else fo = 0.06 * big;
      }
      if (d.state === "blocked" && !walking && s === 1) ay += 0.25 * big;   // a hand up: needs you
      if (cheer) ay += 0.3 * big;
      const ap = [a.x + side[0] * s * so + fwd[0] * fo, ay, a.z + side[1] * s * so + fwd[1] * fo];
      solid("box", ap, a.ry, [0.1 * big, 0.3 * big, 0.1 * big], col.map((v) => v * 0.85), { line: false });
      if (working && st === "workshop" && s === 1) solid("box", [ap[0] + fwd[0] * 0.08, ap[1] + 0.16 * big, ap[2] + fwd[1] * 0.08], a.ry, [0.22 * big, 0.08 * big, 0.08 * big], [0.55, 0.58, 0.68], { line: false });
      if (working && st === "library" && s === 1) solid("box", [a.x + fwd[0] * 0.3 * big, ay + 0.05, a.z + fwd[1] * 0.3 * big], a.ry, [0.3 * big, 0.2 * big, 0.06], [0.85, 0.3, 0.3], { line: false });
    }
    // a hat per role, so you can tell them apart at a glance
    const role = (d.role || d.name || "").toLowerCase(), hat = hy + 0.22 * big;
    if (id === "loki") { for (const s of [-1, 1]) solid("cone", [a.x + side[0] * s * 0.16 * big, hat + 0.02, a.z + side[1] * s * 0.16 * big], a.ry, [0.1 * big, 0.26 * big, 0.1 * big], [0.25, 0.95, 0.85], { e: 0.5 }); }
    else if (role.includes("builder")) solid("sph4", [a.x, hat - 0.06 * big, a.z], a.ry, [0.48 * big, 0.2 * big, 0.48 * big], [1, 0.8, 0.2]);
    else if (role.includes("architect")) solid("cyl", [a.x, hat - 0.04 * big, a.z], a.ry, [0.36 * big, 0.07 * big, 0.36 * big], [0.55, 0.3, 0.8]);
    else if (role.includes("research")) solid("box", [a.x + fwd[0] * 0.21 * big, hy + 0.04 * big, a.z + fwd[1] * 0.21 * big], a.ry, [0.32 * big, 0.04 * big, 0.04], [0.1, 0.1, 0.15], { line: false });
    else if (role.includes("test")) solid("cyl6", [a.x, hat, a.z], a.ry, [0.12 * big, 0.12 * big, 0.12 * big], [1, 0.5, 0.3], { e: 0.3 });
    else if (role.includes("review")) solid("pyr", [a.x, hat + 0.02, a.z], a.ry + Math.PI / 4, [0.34 * big, 0.2 * big, 0.34 * big], [0.95, 0.5, 0.3]);
    // above the head: what state it is in (the same colours as the legend)
    const top = hy + 0.46 * big;
    a.labelY = ["working", "blocked", "waiting", "done", "failed"].includes(d.state) ? top + 0.3 : hy + 0.45 * big;
    if (d.state === "working") {
      const wy = top + Math.sin(t * 3 + a.phase) * 0.05;
      solid("box", [a.x, wy, a.z], t * 2.4, [0.16, 0.16, 0.16], [0.56, 0.9, 1], { e: 0.9 });
      glow([a.x, wy, a.z], 0.45, [0.4, 0.85, 1.0], 0.7);
    }
    if (d.state === "blocked") {
      const by2 = top + 0.1 + Math.abs(Math.sin(t * 4)) * 0.08;
      solid("box", [a.x, by2 + 0.12, a.z], 0, [0.09, 0.26, 0.09], [1, 0.3, 0.3], { e: 0.9 });
      solid("box", [a.x, by2 - 0.08, a.z], 0, [0.09, 0.09, 0.09], [1, 0.3, 0.3], { e: 0.9 });
      glow([a.x, by2, a.z], 0.55, [1, 0.25, 0.25], 0.6);
      ring(a.x, a.z, 0.62, [1, 0.28, 0.28], World.reduced ? 0 : -t * 0.8, 0.6 + 0.4 * Math.abs(Math.sin(t * 5)));
      light([a.x, 0.8, a.z], [0.9, 0.15, 0.15], 2.2, 3);
    }
    if (d.state === "waiting") {   // an hourglass: queued, it will start
      const wy = top + 0.05, r = World.reduced ? 0 : t * 1.2;
      solid("pyr", [a.x, wy + 0.08, a.z], r, [0.16, -0.16, 0.16], [0.85, 0.85, 0.95], { e: 0.4, line: false });
      solid("pyr", [a.x, wy - 0.08, a.z], r, [0.16, 0.16, 0.16], [0.85, 0.85, 0.95], { e: 0.4, line: false });
    }
    if (d.state === "done") solid("sph", [a.x, top, a.z], 0, [0.18, 0.18, 0.18], [0.5, 1, 0.55], { e: 0.9 });
    if (d.state === "failed") {   // a little grey cloud: it did not work out
      solid("sph4", [a.x, top + 0.1, a.z], 0, [0.4, 0.2, 0.3], [0.45, 0.47, 0.55], { line: false });
      if (!World.reduced && Math.random() < dt * 3) emit("bubble", [a.x + (Math.random() - 0.5) * 0.3, top, a.z]);
    }
    if (id === World.selected) {
      ring(a.x, a.z, 0.78, [0.3, 1, 0.9], World.reduced ? 0 : t * 0.6, 0.9);
      light([a.x, 1.2, a.z], [0.15, 0.5, 0.45], 2.0, 3);
    }
  }

  // ambience: fireflies at night, birds by day, mist at the foot of the waterfall
  if (!World.reduced) {
    if (night > 0.2) for (let i = 0; i < 18; i++) {
      const a0 = i * 2.4, r = 4 + (i % 5) * 1.0;
      const fx = Math.cos(a0 + t * 0.07 * (i % 3 + 1)) * r + Math.sin(t * 0.9 + i) * 0.4, fz = Math.sin(a0 + t * 0.07 * (i % 3 + 1)) * r + Math.cos(t * 0.7 + i) * 0.4;
      const fy = 0.6 + Math.sin(t * 1.3 + i * 1.7) * 0.4 + (i % 4) * 0.2;
      const blink = Math.max(0, Math.sin(t * 2.1 + i * 3.3));
      if (blink > 0.1) glow([fx, fy, fz], 0.22, [0.75, 1, 0.45], blink * night);
    }
    if (P.dayK > 0.25) for (let i = 0; i < 3; i++) {
      const a0 = t * (0.16 + i * 0.03) + i * 2.1, r = 7 + i * 1.6, bx = Math.cos(a0) * r, bz = Math.sin(a0) * r, byy = 5 + i * 0.6 + Math.sin(t + i) * 0.3;
      const ry = Math.atan2(-Math.sin(a0), Math.cos(a0)), flap = Math.sin(t * 9 + i * 2) * 0.09, sd = [Math.cos(ry), -Math.sin(ry)];
      solid("box", [bx, byy, bz], ry, [0.08, 0.07, 0.22], [0.15, 0.17, 0.25], { line: false });
      for (const s of [-1, 1]) solid("box", [bx + sd[0] * s * 0.17, byy + flap, bz + sd[1] * s * 0.17], ry, [0.26, 0.03, 0.12], [0.2, 0.22, 0.3], { line: false });
    }
    critters(solid, shadow, t, dt, night);
    const fl = SCENERY.fall;
    if (fl && Math.random() < dt * 5) emit("mist", [Math.cos(fl.a) * (ISLAND + 0.1), -5.4, Math.sin(fl.a) * (ISLAND + 0.1)]);
  }

  // the MMO: you, the other machines' avatars, failure monsters, spell effects (pooled, no garbage)
  if (view.mmo && view.mmo.active) view.mmo.scene(L, t, dt, P, now);

  // particles
  for (const p of World.particles) {
    const k = 1 - p.age / p.life;
    if (p.kind === "confetti") solid("box", [p.x, p.y, p.z], p.ry, [0.09, 0.02, 0.06], p.c, { e: 0.4, line: false });
    else if (p.kind === "smoke" || p.kind === "mist") L.puffs.push({ pos: [p.x, p.y, p.z], r: (p.kind === "smoke" ? 0.18 : 0.35) + (1 - k) * 0.35, color: p.c, a: k * 0.7 });
    else glow([p.x, p.y, p.z], p.kind === "page" ? 0.12 : 0.1, p.c, k);
  }
  return L;
}

// ---------------------------------------------------------------- frame
function setLighting(gl, loc, F) {
  gl.uniformMatrix4fv(loc.VP, false, F.vp);
  gl.uniform3fv(loc.eye, F.eye);
  gl.uniform3fv(loc.sunDir, F.sunDir); gl.uniform3fv(loc.sunCol, F.P.sunCol);
  gl.uniform3fv(loc.skyAmb, F.P.skyAmb); gl.uniform3fv(loc.gndAmb, F.P.gndAmb); gl.uniform3fv(loc.shadeTint, F.P.shade);
  gl.uniform3fv(loc.rimCol, F.P.rim); gl.uniform3fv(loc.fogc, F.P.fog); gl.uniform2fv(loc.fogr, F.fogr);
  gl.uniform3fv(loc.LP, F.lp); gl.uniform4fv(loc.LC, F.lc);
  gl.uniform1f(loc.T, F.t); gl.uniform1f(loc.A, 1);
}

function frame(view, now) {
  const { gl, canvas } = view;
  if (view.lost || gl.isContextLost()) return;
  const t0 = performance.now();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(canvas.clientWidth * dpr)), h = Math.max(1, Math.round(canvas.clientHeight * dpr));
  if (!view.three && (canvas.width !== w || canvas.height !== h)) { canvas.width = w; canvas.height = h; }
  // one world pixel = `pixel` CSS px, rounded to a whole number of device pixels (plus the
  // frame-time watcher's boost when this machine is falling behind)
  const scale = Math.max(1, Math.round((World.pixel || view.opts.pixel || 3) * dpr)) + (World.pixel ? 0 : view.perf.boost);
  const lw = Math.max(1, Math.ceil(w / scale)), lh = Math.max(1, Math.ceil(h / scale));
  const fb = view.three ? null : ensureTarget(view, lw, lh);
  const rw = fb ? lw : w, rh = fb ? lh : h;

  const dt = Math.min(0.1, (now - (view.last || now)) / 1000);
  view.last = now;
  // the MMO (app/ui/mmo/): you walk your own character; the camera follows you, not the orbit
  const mmo = view.mmo && view.mmo.active ? view.mmo : null;
  if (!view.drag && !World.reduced && !view.follow && !mmo) view.yaw += dt * (view.opts.spin || 0.05);
  const t = now / 1000;
  stepParticles(dt);
  if (mmo) mmo.tick(view, dt, now);

  // time of day -> palette (subtle; reduced motion keeps it but it only moves with the clock)
  const d = new Date(), hour = World.hour != null ? World.hour : d.getHours() + d.getMinutes() / 60;
  const day = smooth(5.5, 8.5, hour) * (1 - smooth(17.5, 20.5, hour)) * 0.85;
  const P = { dayK: day };
  for (const k of Object.keys(NIGHT)) P[k] = Array.isArray(NIGHT[k]) ? mix3(NIGHT[k], DAY[k], day) : NIGHT[k] + (DAY[k] - NIGHT[k]) * day;
  const sunAz = 0.9 + (World.reduced ? 0 : t * 0.004);
  const sunDir = norm([Math.cos(sunAz) * 0.6, 0.62 + day * 0.25, Math.sin(sunAz) * 0.6]);

  // camera: orbit round a target that eases onto a followed agent
  const fol = view.follow && World.agents[view.follow];
  if (view.follow && !fol) view.follow = "";
  const want = mmo ? mmo.camTarget : fol ? [fol.x, 0.9, fol.z] : view.focus || [0, 0.7, 0];   // view.focus: look at a place
  const ease = mmo ? 1 : Math.min(1, dt * 3);   // the MMO smooths its own camera
  view.target = [lerp(view.target[0], want[0], ease), lerp(view.target[1], want[1], ease), lerp(view.target[2], want[2], ease)];
  if (fol && !view.drag && !mmo) view.dist = lerp(view.dist, Math.min(view.dist, 9.5), ease * 0.5);
  const fov = view.opts.fov || 0.8, target = view.target;
  const eye = [target[0] + Math.cos(view.yaw) * Math.cos(view.pitch) * view.dist, Math.sin(view.pitch) * view.dist + target[1],
    target[2] + Math.sin(view.yaw) * Math.cos(view.pitch) * view.dist];
  const vp = M4.mul(M4.persp(fov, w / h, 0.5, 90), M4.lookAt(eye, target, [0, 1, 0]));
  view.lastVP = vp;
  const camF = norm(sub(target, eye)), camR = norm(cross(camF, [0, 1, 0])), camU = cross(camR, camF);
  // the fog reaches further when other machines' islands float out in the space around you
  const far = ((World.data && World.data.machines) || []).some((m) => !World.data.self || m.name !== World.data.self.name);
  const fogr = [view.dist + 2, far ? 34 : 16];

  const L = sceneList(view, t, dt, P);

  // the 10 lights the shader takes: the ones that say something first (blocked, busy), then
  // the plain lamps - a blocked agent's red light must never be the one that is dropped
  const lights = L.lights.slice().sort((a, b) => (b.pri || 0) - (a.pri || 0)).slice(0, 10);
  const lp = view.lpBuf || (view.lpBuf = new Float32Array(30)), lc = view.lcBuf || (view.lcBuf = new Float32Array(40));
  lp.fill(0); lc.fill(0);
  lights.forEach((l, i) => {
    lp.set(l.pos, i * 3);
    lc.set([l.color[0] * P.lamps, l.color[1] * P.lamps, l.color[2] * P.lamps, l.radius], i * 4);
  });
  for (let i = lights.length; i < 10; i++) lc[i * 4 + 3] = 1;
  const F = { vp, eye, sunDir, P, fogr, lp, lc, t };
  if (view.three) {   // the three.js renderer draws the same scene description
    const nowS = performance.now() / 1000;
    World.ripples = World.ripples.filter((r) => nowS - r.t0 < 2.4);
    const scaleDown = [1, 0.85, 0.7][view.perf.boost] || 1;
    view.perf.draws = view.three.render({ L, lights, eye, target, fov, P, sunDir, t, w: canvas.clientWidth || 1,
      h: canvas.clientHeight || 1, dpr: view.three.kind === "babylon" ? dpr : dpr * scaleDown, pixel: scale, levels: view.opts.levels || 32, fogr, skyRot: World.reduced ? 0 : -t * 0.01, ripples: World.ripples,
      waterLook: { shallow: mix3(WATER_LOOK.night.shallow, WATER_LOOK.day.shallow, P.dayK),
        deep: mix3(WATER_LOOK.night.deep, WATER_LOOK.day.deep, P.dayK), foam: mix3(WATER_LOOK.night.foam, WATER_LOOK.day.foam, P.dayK) } });
    view.perf.ms = performance.now() - t0;
    view.perf.quality = view.three.quality;
    drawLabels(view, vp, now);
    if (view.opts.detail) updateHud(view, now, hour);
    return;
  }
  const skyM = M4.trs([0, 0, 0], World.reduced ? 0 : -t * 0.01, [1, 1, 1]);
  const ident = M4.ident();
  let draws = 0;

  gl.bindFramebuffer(gl.FRAMEBUFFER, fb ? fb.fbo : null);
  gl.viewport(0, 0, rw, rh);
  gl.disable(gl.BLEND);
  gl.depthMask(true);
  gl.clearColor(P.deep[0], P.deep[1], P.deep[2], 1);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  const quad = view.meshes.quad;

  // 1. sky
  if (view.sky) {
    const { prog, loc } = view.sky;
    gl.useProgram(prog);
    gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE);
    const th = Math.tan(fov / 2);
    gl.uniform3fv(loc.camF, camF); gl.uniform3fv(loc.camR, camR); gl.uniform3fv(loc.camU, camU);
    gl.uniform2f(loc.tanH, th * w / h, th);
    gl.uniform3fv(loc.zenith, P.zenith); gl.uniform3fv(loc.horizon, P.horizon); gl.uniform3fv(loc.glow, P.glow);
    gl.uniform3fv(loc.deep, P.deep); gl.uniform3fv(loc.skySun, sunDir); gl.uniform3fv(loc.skySunCol, P.sunSky);
    gl.uniform1f(loc.stars, P.stars); gl.uniform1f(loc.T, t);
    bindMesh(gl, loc, quad);
    gl.drawArrays(gl.TRIANGLES, 0, quad.count); draws++;
  }
  gl.enable(gl.DEPTH_TEST);
  gl.enable(gl.CULL_FACE);

  // 2. ink outlines: inflated back faces (cull the front) - the baked scene in two draws
  const OL = 1.15 * 2 * Math.tan(fov / 2) / rh;
  gl.cullFace(gl.FRONT);
  if (view.bakedOutline) {
    const { prog, loc } = view.bakedOutline;
    gl.useProgram(prog);
    gl.uniformMatrix4fv(loc.VP, false, vp); gl.uniform3fv(loc.oeye, eye); gl.uniform1f(loc.OL, OL);
    gl.uniform3fv(loc.ofog, P.fog); gl.uniform2fv(loc.ofogr, fogr);
    for (const [batch, M] of [[view.batches.landInk, ident], [view.batches.skyInk, skyM]]) {
      if (!batch.count) continue;
      gl.uniformMatrix4fv(loc.M, false, M);
      bindMesh(gl, loc, batch);
      gl.drawArrays(gl.TRIANGLES, 0, batch.count); draws++;
    }
  }
  if (view.outline) {
    const { prog, loc } = view.outline;
    gl.useProgram(prog);
    gl.uniformMatrix4fv(loc.VP, false, vp);
    gl.uniform3fv(loc.oeye, eye);
    gl.uniform1f(loc.OL, OL);
    gl.uniform3fv(loc.ofog, P.fog); gl.uniform2fv(loc.ofogr, fogr);
    const inkc = [0.03, 0.03, 0.10];
    let bound = null;
    for (const o of L.solids) {
      if (o.line === false) continue;
      const m = view.meshes[o.mesh];
      if (bound !== m) { bindMesh(gl, loc, m); bound = m; }
      gl.uniformMatrix4fv(loc.M, false, M4.trs(o.pos, o.ry, o.s));
      gl.uniform3fv(loc.OC, mix3(inkc, o.color, 0.22));
      gl.drawArrays(gl.TRIANGLES, 0, m.count); draws++;
    }
  }

  // 3. cel-shaded solids: the baked scene (land, then the turning sky batch), then what moves
  gl.cullFace(gl.BACK);
  if (view.baked) {
    const { prog, loc } = view.baked;
    gl.useProgram(prog);
    setLighting(gl, loc, F);
    for (const [batch, M] of [[view.batches.land, ident], [view.batches.sky, skyM]]) {
      gl.uniformMatrix4fv(loc.M, false, M);
      bindMesh(gl, loc, batch);
      gl.drawArrays(gl.TRIANGLES, 0, batch.count); draws++;
    }
  }
  const { prog, loc } = view.solid;
  gl.useProgram(prog);
  setLighting(gl, loc, F);
  let bound = null;
  const drawSolid = (o) => {
    const m = view.meshes[o.mesh];
    if (bound !== m) { bindMesh(gl, loc, m); bound = m; }
    gl.uniformMatrix4fv(loc.M, false, M4.trs(o.pos, o.ry, o.s));
    gl.uniform3f(loc.IS, 1 / (o.s[0] * o.s[0]), 1 / (o.s[1] * o.s[1]), 1 / (o.s[2] * o.s[2]));
    gl.uniform3fv(loc.C, o.color); gl.uniform1f(loc.A, o.a == null ? 1 : o.a); gl.uniform1f(loc.E, o.e || 0);
    gl.uniform1f(loc.G, o.g || 0); gl.uniform1f(loc.S, o.s2 || 0.3);
    gl.drawArrays(gl.TRIANGLES, 0, m.count); draws++;
  };
  for (const o of L.solids) {
    // squashed with a negative y (an hourglass half points down): flip the winding for it
    gl.frontFace(o.s[0] * o.s[1] * o.s[2] < 0 ? gl.CW : gl.CCW);
    drawSolid(o);
  }
  gl.frontFace(gl.CCW);

  // 4. see-through: water first (its own shader), then glass, shadows, glows - blended,
  // depth-tested, not depth-written
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  gl.depthMask(false);
  if (view.water) draws += drawWater(view, F, P, t);
  for (const o of L.clear) drawSolid(o);
  gl.disable(gl.CULL_FACE);
  if (view.shadowBatch && view.batches.shadows.count) {
    const { prog: sp, loc: sl } = view.shadowBatch;
    gl.useProgram(sp);
    gl.uniformMatrix4fv(sl.VP, false, vp); gl.uniform3fv(sl.SK, [0.02, 0.03, 0.12]);
    bindMesh(gl, sl, view.batches.shadows);
    gl.drawArrays(gl.TRIANGLES, 0, view.batches.shadows.count); draws++;
  }
  if (view.sprite) {
    const sp = view.sprite;
    gl.useProgram(sp.prog);
    gl.uniformMatrix4fv(sp.loc.VP, false, vp);
    gl.uniform3fv(sp.loc.camR, camR); gl.uniform3fv(sp.loc.camU, camU);
    bindMesh(gl, sp.loc, quad);
    gl.uniform1f(sp.loc.SB, 0);
    gl.uniform3fv(sp.loc.SK, [0.02, 0.03, 0.12]);
    for (const s of L.shadows) {
      gl.uniform3f(sp.loc.SC, s.x, 0.075, s.z); gl.uniform2f(sp.loc.SS, s.r, s.r);
      gl.uniform1f(sp.loc.SA, s.a);
      gl.drawArrays(gl.TRIANGLES, 0, quad.count); draws++;
    }
    gl.uniform1f(sp.loc.SB, 1);
    for (const g of L.puffs) {   // smoke and mist: soft, not glowing
      gl.uniform3fv(sp.loc.SC, g.pos); gl.uniform2f(sp.loc.SS, g.r, g.r);
      gl.uniform3fv(sp.loc.SK, scale3(g.color, 0.55 + 0.45 * P.dayK + 0.3)); gl.uniform1f(sp.loc.SA, g.a);
      gl.drawArrays(gl.TRIANGLES, 0, quad.count); draws++;
    }
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);   // glows add light
    for (const g of L.glows) {
      gl.uniform3fv(sp.loc.SC, g.pos); gl.uniform2f(sp.loc.SS, g.r, g.r);
      gl.uniform3fv(sp.loc.SK, g.color); gl.uniform1f(sp.loc.SA, g.a * (0.55 + 0.45 * P.lamps));
      gl.drawArrays(gl.TRIANGLES, 0, quad.count); draws++;
    }
  }
  gl.depthMask(true);
  gl.disable(gl.BLEND);

  // 5. blow the low-res picture up to the canvas: NEAREST, whole-number scale, dithered
  if (fb) {
    const { prog: bp, loc: bl } = view.blit;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, lw * scale, lh * scale);
    gl.disable(gl.DEPTH_TEST);
    gl.useProgram(bp);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, fb.tex);
    gl.uniform1i(bl.T, 0);
    gl.uniform2f(bl.R, lw, lh); gl.uniform2f(bl.VPX, lw * scale, lh * scale);
    gl.uniform1f(bl.Q, view.opts.levels || 32);   // colour levels per channel: more bits than the first 20
    bindMesh(gl, bl, quad);
    gl.drawArrays(gl.TRIANGLES, 0, quad.count); draws++;
  }
  view.perf.draws = draws;
  view.perf.ms = performance.now() - t0;
  view.perf.scale = scale;
  drawLabels(view, vp, now);
  if (view.opts.detail) updateHud(view, now, hour);
}

function drawWater(view, F, P, t) {
  const { gl } = view, { prog, loc } = view.water;
  gl.useProgram(prog);
  gl.disable(gl.CULL_FACE);
  const T = t % 600;   // keep the noise inputs small (float precision); a jump every 10 min
  gl.uniformMatrix4fv(loc.VP, false, F.vp); gl.uniform3fv(loc.eye, F.eye); gl.uniform1f(loc.T, T);
  gl.uniform3fv(loc.sunDir, F.sunDir); gl.uniform3fv(loc.sunCol, P.sunCol); gl.uniform1f(loc.dayK, P.dayK);
  gl.uniform3fv(loc.zenith, P.zenith); gl.uniform3fv(loc.horizon, P.horizon);
  gl.uniform3fv(loc.fogc, P.fog); gl.uniform2fv(loc.fogr, F.fogr);
  gl.uniform3fv(loc.LP, F.lp); gl.uniform4fv(loc.LC, F.lc);
  gl.uniform3fv(loc.shallow, mix3(WATER_LOOK.night.shallow, WATER_LOOK.day.shallow, P.dayK));
  gl.uniform3fv(loc.deep, mix3(WATER_LOOK.night.deep, WATER_LOOK.day.deep, P.dayK));
  gl.uniform3fv(loc.foamCol, mix3(WATER_LOOK.night.foam, WATER_LOOK.day.foam, P.dayK));
  const nowS = performance.now() / 1000;
  World.ripples = World.ripples.filter((r) => nowS - r.t0 < 2.4);
  const rip = view.ripBuf || (view.ripBuf = new Float32Array(16));
  let draws = 0;
  for (const w of WATER) {
    rip.fill(0);
    let k = 0;
    for (const r of World.ripples) if (r.body === w.id && k < 4) { rip.set([r.x, r.z, nowS - r.t0, r.k], k * 4); k++; }
    gl.uniform4fv(loc.rip, rip);
    gl.uniform4fv(loc.shape, w.shape); gl.uniform4fv(loc.rect, w.rect);
    gl.uniform4fv(loc.obs0, w.obs[0] || [0, 0, 0, 0]); gl.uniform4fv(loc.obs1, w.obs[1] || [0, 0, 0, 0]);
    gl.uniform2fv(loc.flow, w.flow); gl.uniform1f(loc.beer, w.beer);
    gl.uniformMatrix4fv(loc.M, false, M4.trs(w.pos, w.ry, w.s));
    const m = view.meshes[w.mesh];
    bindMesh(gl, loc, m);
    gl.drawArrays(gl.TRIANGLES, 0, m.count);
    draws++;
  }
  gl.enable(gl.CULL_FACE);
  return draws;
}

// ---------------------------------------------------------------- labels, card, HUD
function project(view, p) {
  const vp = view.lastVP, canvas = view.canvas;
  if (!vp) return null;
  const v = [vp[0] * p[0] + vp[4] * p[1] + vp[8] * p[2] + vp[12], vp[1] * p[0] + vp[5] * p[1] + vp[9] * p[2] + vp[13],
    vp[3] * p[0] + vp[7] * p[1] + vp[11] * p[2] + vp[15]];
  if (v[2] <= 0) return null;
  return [(v[0] / v[2] * 0.5 + 0.5) * canvas.clientWidth, (1 - (v[1] / v[2] * 0.5 + 0.5)) * canvas.clientHeight, v[2]];
}

// The label above each head, and what it last said. Labels never pile up: the nearest is
// placed first and any that would overlap it are lifted above.
function drawLabels(view, vp, now) {
  if (!view.labels) return;
  const seen = new Set(), items = [];
  const nodeFor = (key, cls) => {
    let node = view.labelNodes[key];
    if (!node) {
      node = view.labelNodes[key] = el("div", cls);
      node.append(el("b"), el("span"), el("i"), el("em"));
      view.labels.append(node);
    }
    return node;
  };
  const setText = (node, k, text) => { if (node.children[k].textContent !== text) { node.children[k].textContent = text; node.dirty = true; } };
  const mmo = view.mmo && view.mmo.active ? view.mmo : null;
  for (const [id, a] of Object.entries(World.agents)) {
    const d2 = a.data || {};
    seen.add(id);
    const node = nodeFor(id, "wlabel");
    const at = project(view, [a.x, a.labelY || 1.6 * (a.big || 1) + 0.35, a.z]);
    node.hidden = !at;
    if (!at) continue;
    setText(node, 0, d2.name || id);
    setText(node, 1, view.opts.detail ? (d2.state + (d2.task ? " · " + d2.task.slice(0, 48) : "")) : "");
    const fresh = a.said && now - a.saidAt < 9000;
    setText(node, 2, fresh ? "“" + a.said.slice(0, 90) + "”" : "");
    setText(node, 3, !fresh && a.chatting && Math.floor(now / 900 + a.phase) % 3 !== 0 ? "···" : "");
    node.classList.toggle("speaking", !!fresh);
    node.classList.toggle("selected", id === World.selected);
    if (mmo) mmo.decorate(node, id, a, now);   // nameplate: level, class, bars
    items.push({ node, x: at[0], y: at[1], depth: at[2] });
  }
  if (mmo) mmo.labels(view, now, nodeFor, setText, items, seen);   // you, other players, monsters
  if (view.opts.detail) for (const tm of view.teamSpots || []) {
    const key = "team:" + tm.id;
    seen.add(key);
    const node = nodeFor(key, "wlabel team");
    const at = project(view, tm.pos);
    node.hidden = !at;
    if (!at) continue;
    setText(node, 0, tm.goal.slice(0, 40) || "team");
    setText(node, 1, tm.stage);
    items.push({ node, x: at[0], y: at[1], depth: at[2] + 0.5 });
  }
  // agents first (nearest first), then team banners; a label is lifted at most twice and
  // never more than ~40px from its head - a banner label that still collides just hides
  for (const ms of view.machineSpots || []) {
    seen.add(ms.key);
    const node = nodeFor(ms.key, "wlabel machine" + (ms.home ? " home" : "") + (ms.gallery ? " gallery" : ""));
    if (!node.flyTo) {   // click a machine's name: fly there; click your own island's name: come home
      node.flyTo = true;
      node.title = ms.gallery ? "Open what LOKI made" : ms.home ? "This computer - click to come home" : "Click to fly to " + ms.name;
      node.addEventListener("click", (e) => {
        e.stopPropagation();
        if (ms.gallery) {   // the creations hall opens Settings > Creations
          const sheet = document.getElementById("settings");
          if (sheet && typeof showTab === "function") { sheet.hidden = false; showTab("creations"); }
          return;
        }
        const spot = (view.machineSpots || []).find((x) => x.key === ms.key);
        view.follow = "";
        view.focus = spot && spot.focus ? spot.focus : null;
        view.dist = spot && spot.focus ? 13 : Math.max(view.dist, 16);
      });
    }
    const at = project(view, ms.pos);
    node.hidden = !at;
    if (!at) continue;
    setText(node, 0, ms.name);
    setText(node, 1, ms.sub);
    items.push({ node, x: at[0], y: at[1], depth: at[2] });
  }
  // away visiting another machine's island: a button to come home
  if (!view.homeBtn && view.labels) {
    view.homeBtn = el("button", "world-home");
    view.homeBtn.addEventListener("click", (e) => { e.stopPropagation(); view.focus = null; view.dist = Math.max(view.dist, 16); });
    view.labels.append(view.homeBtn);
  }
  if (view.homeBtn) {
    const away = !!(view.focus && Math.hypot(view.focus[0], view.focus[2]) > 12);
    view.homeBtn.hidden = !away;
    const txt = "\u2302 back to " + (((World.data && World.data.self) || {}).name || "this computer");
    if (view.homeBtn.textContent !== txt) view.homeBtn.textContent = txt;
  }
  items.sort((p, q) => (p.node.classList.contains("team") - q.node.classList.contains("team")) || p.depth - q.depth);
  const placed = [];
  for (const it of items) {
    if (it.node.dirty || !it.node.wh) { it.node.wh = [it.node.offsetWidth || 80, it.node.offsetHeight || 18]; it.node.dirty = false; }
    const [bw, bh] = it.node.wh;
    const team = it.node.classList.contains("team");
    let y = it.y, hit = null;
    for (let k = 0; k < 3; k++) {
      hit = placed.find((r) => Math.abs(r.x - it.x) < (r.w + bw) / 2 - 4 && y > r.y - r.h + 4 && y - bh < r.y - 4);
      if (!hit || k === 2 || team) break;
      const ny = hit.y - hit.h - 2;
      if (it.y - ny > 44) break;
      y = ny;
    }
    it.node.classList.toggle("crowded", !!hit);
    if (team && hit) { it.node.hidden = true; continue; }
    placed.push({ x: it.x, y, w: bw, h: bh });
    it.node.style.transform = "translate(" + Math.round(it.x) + "px," + Math.round(y) + "px) translate(-50%,-100%)";
  }
  for (const id of Object.keys(view.labelNodes)) if (!seen.has(id)) { view.labelNodes[id].remove(); delete view.labelNodes[id]; }
}

function selectAgent(id, view) {
  World.selected = World.selected === id && !view ? "" : id;
  if (view && !id) view.follow = "";
  renderLegend();
  if (view) updateCard(view, true);
}

// The inspector: everything here is from GET /world - nothing is made up.
function updateCard(view, force) {
  const frameBox = view.canvas.parentElement;
  if (!frameBox) return;
  let card = view.card;
  const a = World.selected && World.agents[World.selected];
  if (!a) { if (card) card.hidden = true; return; }
  if (!card) {
    card = view.card = el("div", "world-card");
    const head = el("div", "wc-head");
    head.append(el("span", "agent-dot"), el("b"), el("span", "pill"));
    const close = el("button", "wc-close", "×");
    close.type = "button"; close.title = "Close";
    close.addEventListener("click", () => { World.selected = ""; view.follow = ""; renderLegend(); updateCard(view, true); });
    head.append(close);
    const rows = el("dl", "wc-rows");
    const actions = el("div", "wc-actions");
    const follow = el("button", "wc-follow", "Follow");
    follow.type = "button";
    follow.addEventListener("click", () => { view.follow = view.follow === World.selected ? "" : World.selected; updateCard(view, true); });
    actions.append(follow);
    card.append(head, rows, el("p", "wc-said"), actions);
    frameBox.append(card);
  }
  if (!force && view.cardAt && performance.now() - view.cardAt < 400) return;
  view.cardAt = performance.now();
  card.hidden = false;
  const d = a.data || {}, nowS = (World.data && World.data.time) || Date.now() / 1000;
  const [dot, name, pill] = card.firstChild.children;
  dot.style.background = d.color || STATE_COLOR[d.state] || "#8fb3d9";
  name.textContent = d.name || d.id;
  pill.textContent = d.state || "";
  pill.className = "pill " + (d.state === "working" ? "working" : d.state === "blocked" ? "blocked" : d.state === "done" ? "done" : "");
  const rows = card.children[1];
  rows.replaceChildren();
  const team = ((World.data && World.data.teams) || []).find((tm) => tm.id === d.team);
  const add = (k, v) => { if (!v) return; rows.append(el("dt", "", k), el("dd", "", v)); };
  add("Role", d.role);
  add("Doing", d.task);
  add("Where", (d.station || "") + (d.machine ? " · " + d.machine : ""));
  if (d.since) add(d.state === "done" || d.state === "failed" ? "Took" : "On it for", ago((d.finished || nowS) - d.since));
  if (team) {
    const stages = team.stages && team.stages.length ? team.stages : ["plan", "build", "check"];
    const cur = stages.indexOf(team.stage);
    add("Team", (team.goal || team.id).slice(0, 60));
    add("Stage", stages.map((s, i) => (i < cur ? "✓ " : i === cur ? "▸ " : "· ") + s).join("   "));
  }
  card.children[2].textContent = a.said ? "“" + a.said.slice(0, 220) + "”" : "";
  card.children[3].firstChild.textContent = view.follow === World.selected ? "Stop following" : "Follow";
}

function updateHud(view, now, hour) {
  const frameBox = view.canvas.parentElement;
  if (!frameBox) return;
  if (!view.hud) { view.hud = el("div", "world-hud"); frameBox.append(view.hud); }
  if (view.hudAt && now - view.hudAt < 500) return;
  view.hudAt = now;
  const agents = (World.data && World.data.agents) || [];
  const s = (World.data && World.data.stats) || {};
  const count = (k) => agents.filter((a) => a.state === k).length;
  const hh = Math.floor(hour), mm = Math.floor((hour - hh) * 60);
  const parts = [(hour >= 6.5 && hour < 19 ? "☀ " : "☾ ") + String(hh).padStart(2, "0") + ":" + String(mm).padStart(2, "0"),
    (s.working != null ? s.working : count("working")) + " working", (s.waiting != null ? s.waiting : count("waiting")) + " waiting"];
  const blocked = s.blocked != null ? s.blocked : count("blocked");
  if (blocked) parts.push(blocked + " need you");
  if (s.done_today != null) parts.push(s.done_today + " done today");
  const model = (World.data && World.data.model) || {};
  if (model.model) parts.push("◆ " + model.model + (model.local ? " (local)" : ""));
  const usage = (World.data && World.data.usage) || {};
  if (usage.calls) parts.push(usage.calls + " calls" + (usage.cost ? " · $" + Number(usage.cost).toFixed(2) : ""));
  const machinesUp = ((World.data && World.data.machines) || []).filter((m) => m.ok).length;
  if ((World.data && World.data.machines || []).length) parts.push(machinesUp + "/" + World.data.machines.length + " machines linked");
  if (s.failed_today) parts.push(s.failed_today + " failed");
  const text = parts.join("  ·  ");
  if (view.hud.textContent !== text) view.hud.textContent = text;
  view.hud.classList.toggle("alert", blocked > 0);
  if (World.selected) updateCard(view);
}

// ---------------------------------------------------------------- loop
// Runs while the view is visible and the window is not hidden. The background view is
// capped (opts.fps, 30) so it stays light behind the home screen. The frame-time watcher:
// if frames keep arriving late, draw coarser world pixels (up to +3); when they are on time
// again for a while, step back. Only between whole pixel sizes, so the look holds.
function loop(view) {
  const tick = (now) => {
    if (!view.visible || document.hidden) { view.visible = false; view.raf = 0; return; }
    view.raf = requestAnimationFrame(tick);
    const fps = view.opts.fps || 0;
    if (fps && view.lastDraw && now - view.lastDraw < 1000 / fps - 2) return;
    const gap = view.lastDraw ? now - view.lastDraw : 0;
    view.lastDraw = now;
    if (now - World.lastFetch > 2500) fetchWorld();
    frame(view, now);
    watchFrames(view, gap, fps);
  };
  if (!view.raf) view.raf = requestAnimationFrame(tick);
}

function watchFrames(view, gap, fps) {
  const pf = view.perf;
  if (!gap || gap > 250) return;   // first frame, or the window was asleep: not a measurement
  pf.ema = pf.ema ? pf.ema * 0.92 + gap * 0.08 : gap;
  if (!World.adaptive || World.pixel) return;
  const budget = 1000 / (fps || 60);
  if (pf.trial) {   // a coarser step only stays if it actually made frames faster
    if (++pf.trial.frames < 60) return;
    if (pf.ema > pf.trial.before * 0.88) { pf.boost--; pf.noGain = performance.now(); }
    pf.trial = null; pf.slow = 0; pf.fast = 0;
    return;
  }
  if (pf.ema > budget * 1.35) { pf.slow++; pf.fast = 0; } else if (pf.ema < budget * 1.1) { pf.fast++; pf.slow = 0; } else { pf.slow = 0; pf.fast = 0; }
  const cooling = pf.noGain && performance.now() - pf.noGain < 60000;   // pixels are not the bottleneck here
  const most = view.three ? 2 : 3;
  if (pf.slow > 40 && pf.boost < most && !cooling) { pf.trial = { before: pf.ema, frames: 0 }; pf.boost++; pf.slow = 0; }
  if (pf.fast > 300 && pf.boost > 0) { pf.boost--; pf.fast = 0; }
  if (view.three) {   // three.js: coarser rendering = fewer shadows/bloom first, then fewer pixels
    const want = ["high", "medium", "low"][pf.boost] || "high";
    if (view.three.quality !== want) view.three.setQuality(want);
  }
}

function setVisible(view, on) {
  if (!view) return;
  view.visible = on && !document.hidden;
  if (view.visible) { view.last = 0; view.lastDraw = 0; loop(view); }
}

function pickAgent(view, cx, cy) {
  let best = "", bestD = 30;
  for (const [id, a] of Object.entries(World.agents)) {
    for (const y of [0.5, 1.0, 1.5]) {
      const at = project(view, [a.x, y * (a.big || 1.3), a.z]);
      if (!at) continue;
      const dd = Math.hypot(at[0] - cx, at[1] - cy);
      if (dd < bestD) { bestD = dd; best = id; }
    }
  }
  return best;
}

function attachControls(view) {
  const c = view.canvas;
  c.tabIndex = 0;
  const end = (e) => {
    const p = view.pointers[e.pointerId];
    delete view.pointers[e.pointerId];
    if (p && !p.moved && e.type === "pointerup" && Object.keys(view.pointers).length === 0) {   // a click: inspect
      const r = c.getBoundingClientRect();
      if (view.mmo && view.mmo.active && view.mmo.click(view, e.clientX - r.left, e.clientY - r.top)) {
        view.drag = null; view.pinch = null; return;   // the MMO took it: a target, a monster, another player
      }
      const id = pickAgent(view, e.clientX - r.left, e.clientY - r.top);
      World.selected = id;
      if (!id) view.follow = "";
      renderLegend(); updateCard(view, true);
    }
    view.drag = Object.keys(view.pointers).length ? view.drag : null;
    view.pinch = null;
  };
  c.addEventListener("pointerdown", (e) => {
    view.pointers[e.pointerId] = { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, moved: false };
    view.drag = { x: e.clientX, y: e.clientY };
    try { c.setPointerCapture(e.pointerId); } catch (_) { /* not capturable */ }
  });
  c.addEventListener("pointermove", (e) => {
    const p = view.pointers[e.pointerId];
    if (!p) return;
    if (Math.hypot(e.clientX - p.sx, e.clientY - p.sy) > 5) p.moved = true;
    const ids = Object.keys(view.pointers);
    if (ids.length === 2) {   // pinch to zoom
      const [a, b] = ids.map((k) => view.pointers[k]);
      p.x = e.clientX; p.y = e.clientY;
      const dd = Math.hypot(a.x - b.x, a.y - b.y);
      if (view.pinch) view.dist = Math.max(6, Math.min(28, view.dist * view.pinch / Math.max(1, dd)));
      view.pinch = dd;
      return;
    }
    if (!view.drag || !p.moved) { p.x = e.clientX; p.y = e.clientY; return; }
    view.yaw += (e.clientX - view.drag.x) * 0.008;
    view.pitch = Math.max(0.2, Math.min(1.35, view.pitch + (e.clientY - view.drag.y) * 0.006));
    view.drag = { x: e.clientX, y: e.clientY };
    p.x = e.clientX; p.y = e.clientY;
  });
  c.addEventListener("pointerup", end);
  c.addEventListener("pointercancel", end);
  c.addEventListener("lostpointercapture", (e) => { if (view.pointers[e.pointerId]) end(e); });
  c.addEventListener("dblclick", (e) => {
    const r = c.getBoundingClientRect();
    if (view.mmo && view.mmo.active) { view.mmo.interact(); return; }   // talk to / attack what you clicked
    const id = pickAgent(view, e.clientX - r.left, e.clientY - r.top);
    World.selected = id; view.follow = id;
    renderLegend(); updateCard(view, true);
  });
  c.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { World.selected = ""; view.follow = ""; renderLegend(); updateCard(view, true); }
    if (e.key === "ArrowLeft") view.yaw -= 0.15;
    if (e.key === "ArrowRight") view.yaw += 0.15;
    if (e.key === "+" || e.key === "=") view.dist = Math.max(6, view.dist - 1);
    if (e.key === "-") view.dist = Math.min(28, view.dist + 1);
  });
  c.addEventListener("wheel", (e) => {
    e.preventDefault();
    const close = view.mmo && view.mmo.active ? 3 : 6;   // third person: you can zoom in close
    view.dist = Math.max(close, Math.min(28, view.dist + e.deltaY * 0.01));
  }, { passive: false });
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
  try { if (localStorage.getItem("loki.safeMode") === "1") localStorage.removeItem("loki.safeMode"); } catch (_) { /* ignore */ }
  if (World.engine === "godot" && window.WorldGodot) { fetchWorld(); window.WorldGodot.panel(true); return; }
  if (!World.views.panel) {
    const canvas = document.getElementById("world-panel-canvas");
    World.views.panel = canvas && makeView(canvas, document.getElementById("world-panel-labels"),
      { dist: 17, pitch: 0.5, spin: 0.03, detail: true, pixel: 2, fps: 0 });
    if (World.views.panel) {
      attachControls(World.views.panel);
      if (window.MMO) window.MMO.attach(World.views.panel);   // LOKI World as an MMO (app/ui/mmo/)
    } else if (canvas) canvas.replaceWith(el("p", "note", "This window cannot draw 3D (no WebGL). The list below shows the same agents."));
  }
  fetchWorld();
  setVisible(World.views.panel, true);
  refreshBackground();
}

function hideWorldPanel() {
  if (World.engine === "godot" && window.WorldGodot) { window.WorldGodot.panel(false); return; }
  setVisible(World.views.panel, false);
  setTimeout(refreshBackground, 0);
}

function setWorldMode(mode) {
  World.mode = mode || "background";
  refreshBackground();
}

// The optional three.js renderer is a module loaded on demand (LOKI_WORLD_ENGINE=three), so the
// default pixel engine never pays for parsing it. Resolves either way; makeView falls back.
function loadThree() {
  if (window.WorldThree) return Promise.resolve(true);
  return new Promise((resolve) => {
    const s = document.createElement("script");
    s.type = "module"; s.src = "/ui/world_three.js";
    s.onload = () => setTimeout(() => resolve(!!window.WorldThree), 0);
    s.onerror = () => resolve(false);
    document.head.append(s);
  });
}

// Babylon.js (2.9 MB, LOKI's own slim build) and its renderer, loaded when the world starts.
function loadScript(src) {
  return new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = src; s.onload = () => resolve(true); s.onerror = () => resolve(false);
    document.head.append(s);
  });
}
async function loadBabylon() {
  if (window.WorldBabylon && window.BABYLON) return true;
  return (await loadScript("/ui/vendor/babylon/babylon.loki.js")) && (await loadScript("/ui/world_babylon.js")) && !!window.WorldBabylon;
}

// The Godot MMO's host (app/ui/world_godot/host.js): resolves true once the web build is starting.
async function loadGodotWorld() {
  if (!window.WorldGodot && !(await loadScript("/ui/world_godot/host.js"))) return false;
  return !!window.WorldGodot && (await window.WorldGodot.start(state.token, backgroundWanted));
}

async function startWorld() {
  // "Reload without the 3D world" (boot.js rescue screen): skip the world until it is opened again in
  // Settings > LOKI World, so a renderer that breaks this machine's window cannot keep it blank.
  let safe = false;
  try { safe = localStorage.getItem("loki.safeMode") === "1"; } catch (_) { /* no storage */ }
  if (safe) return;
  try {
    const data = await api("/settings/general");
    if (data && data.ok) {
      World.mode = data.values.LOKI_WORLD || "background";
      const want = (data.values.LOKI_WORLD_ENGINE || "babylon").toLowerCase();
      World.engine = ["babylon", "godot", "three", "classic"].includes(want) ? want : "babylon";
    }
  } catch (_) { /* default */ }
  // LOKI World as the Godot MMO (game/loki-world, web build in /ui/world_godot/): its own page in a
  // frame, which needs no view here. Not exported yet / cannot run -> Babylon as before.
  if (World.engine === "godot") {
    if (await loadGodotWorld()) return;
    World.engine = "babylon";
  }
  if (World.engine === "three") await loadThree();   // only then is the 2 MB three.js parsed at all
  if (World.engine === "babylon" && !(await loadBabylon())) World.engine = "classic";
  const canvas = document.getElementById("world-bg-canvas");
  if (canvas) World.views.bg = makeView(canvas, document.getElementById("world-bg-labels"),
    { dist: 19, pitch: 0.46, spin: 0.045, detail: false, pixel: 3, fps: 30, quality: "medium" });
  const main = document.getElementById("main");
  if (main) new MutationObserver(refreshBackground).observe(main, { attributes: true, attributeFilter: ["class"] });
  const settings = document.getElementById("settings");
  if (settings) new MutationObserver(refreshBackground).observe(settings, { attributes: true, attributeFilter: ["hidden"] });
  document.addEventListener("visibilitychange", () => {
    refreshBackground();
    const panel = document.querySelector('[data-panel="world"]');
    if (World.views.panel && settings && !settings.hidden && panel && !panel.hidden) setVisible(World.views.panel, true);
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
