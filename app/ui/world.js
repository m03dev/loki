// LOKI World: your agents as characters in a small 3D world, drawn with plain WebGL (no
// libraries, CSP-clean). The engine's GET /world says who is there, where they work and
// what they are doing - only real state, never invented (engine/events.py world()). This
// file just animates it: agents walk to their station, bob while they work, glow red when
// blocked, and show what they last said on the team board.
//
// Two views share one renderer: behind the home screen (dim, slowly orbiting, "the world
// happening in the background") and full size in Settings > LOKI World (drag to orbit,
// wheel to zoom). LOKI_WORLD (Settings > General) picks background | panel | off.
//
// The look: a 3D pixel-art, cel-shaded floating island. The scene is drawn into a small
// low-resolution framebuffer (1/3 - 1/4 of the canvas, an integer scale) and blown up with
// NEAREST filtering plus a light ordered dither, so it reads as chunky pixels. Lighting is
// quantized into bands (a sun or moon, a sky/ground hemisphere fill, a rim light and the
// station lamps as small point lights), and every solid gets a dark ink outline from an
// inflated back-face hull. Sky, island, trees, rocks, lamps and little station buildings are
// all built here from boxes, cylinders, cones and spheres - nothing is loaded.
"use strict";

const World = {
  mode: "background", views: {}, agents: {}, data: null, lastFetch: 0, fetching: false,
  reduced: window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  pixel: null,   // set a number (CSS px per world pixel) to override every view's pixel size
  hour: null,    // set 0-24 to pin the time of day (otherwise the local clock tints the sky)
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

// ---------------------------------------------------------------- shaders
// Solids. The normal goes through the inverse scale (IS = 1/s^2) so squashed shapes still
// light correctly.
const VS = "attribute vec3 p; attribute vec3 n; uniform mat4 M; uniform mat4 VP; uniform vec3 IS;" +
  "varying vec3 vn; varying vec3 wp;" +
  "void main(){ vec4 w = M * vec4(p,1.0); wp = w.xyz; vn = mat3(M) * (n * IS); gl_Position = VP * w; }";

// Cel shading: the sun term is quantized into BANDS hard steps between a cool shadow tone
// and the lit tone; the hemisphere fill, the station lamps, the rim and a toon highlight are
// stepped too, so every surface reads as flat painted colour.
const FS = "precision mediump float; varying vec3 vn; varying vec3 wp;" +
  "uniform vec3 C; uniform float A; uniform float E; uniform float G; uniform float S;" +
  "uniform vec3 eye; uniform vec3 sunDir; uniform vec3 sunCol; uniform vec3 skyAmb; uniform vec3 gndAmb;" +
  "uniform vec3 shadeTint; uniform vec3 rimCol; uniform vec3 fogc; uniform vec2 fogr;" +
  "uniform vec3 LP[10]; uniform vec4 LC[10];" +
  "const float BANDS = 3.0;" +
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
  " float rim = 1.0 - max(dot(N, V), 0.0); col += rimCol * step(0.72, rim) * (0.3 + 0.7 * b);" +
  " vec3 H = normalize(sunDir + V); col += sunCol * step(0.96, dot(N, H)) * S;" +
  " col += C * E;" +
  " float f = clamp((length(eye - wp) - fogr.x) / fogr.y, 0.0, 1.0); f = floor(f * 4.0) / 4.0;" +
  " gl_FragColor = vec4(mix(col, fogc, f * 0.6), A); }";

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

// Sky: a gradient by the view ray's height (zenith, a glowing horizon band, the deep below
// the floating island), a pixel sun/moon and stars that fade in at night.
const SKY_VS = "attribute vec3 p; uniform vec3 camF; uniform vec3 camR; uniform vec3 camU; uniform vec2 tanH;" +
  "varying vec3 ray; void main(){ ray = camF + camR * p.x * tanH.x + camU * p.y * tanH.y; gl_Position = vec4(p.xy, 0.9999, 1.0); }";
const SKY_FS = "#ifdef GL_FRAGMENT_PRECISION_HIGH\nprecision highp float;\n#else\nprecision mediump float;\n#endif\n" +
  "varying vec3 ray; uniform vec3 zenith; uniform vec3 horizon; uniform vec3 glow; uniform vec3 deep;" +
  "uniform vec3 skySun; uniform vec3 skySunCol; uniform float stars;" +
  "void main(){ vec3 d = normalize(ray); float e = d.y;" +
  " vec3 col = e > 0.0 ? mix(horizon, zenith, pow(clamp(e * 1.6, 0.0, 1.0), 0.7)) : mix(horizon, deep, pow(clamp(-e * 2.2, 0.0, 1.0), 0.6));" +
  " col += glow * exp(-abs(e) * 9.0);" +
  " float s = dot(d, skySun); col = mix(col, skySunCol, step(0.9985, s)); col += skySunCol * step(0.99, s) * 0.18;" +
  " vec3 q = floor(d * 140.0); float h = fract(sin(dot(q, vec3(12.9898, 78.233, 37.719))) * 43758.5453);" +
  " col += vec3(0.85, 0.95, 1.0) * step(0.993, h) * stars * smoothstep(-0.25, 0.15, e);" +
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
  const loc = { p: gl.getAttribLocation(prog, "p"), n: gl.getAttribLocation(prog, "n") };
  for (const u of uniforms) loc[u] = gl.getUniformLocation(prog, u);
  return { prog, loc };
}

function makeView(canvas, labels, opts) {
  let gl = null;
  try { gl = canvas.getContext("webgl", { antialias: false, alpha: false, premultipliedAlpha: false }); } catch (_) { gl = null; }
  if (!gl) return null;
  const solid = makeProgram(gl, VS, FS, ["M", "VP", "IS", "C", "A", "E", "G", "S", "eye", "sunDir", "sunCol", "skyAmb",
    "gndAmb", "shadeTint", "rimCol", "fogc", "fogr", "LP", "LC"]);
  if (!solid) return null;
  const outline = makeProgram(gl, OUTLINE_VS, OUTLINE_FS, ["M", "VP", "oeye", "OL", "OC", "ofog", "ofogr"]);
  const sky = makeProgram(gl, SKY_VS, SKY_FS, ["camF", "camR", "camU", "tanH", "zenith", "horizon", "glow", "deep", "skySun", "skySunCol", "stars"]);
  const sprite = makeProgram(gl, SPRITE_VS, SPRITE_FS, ["VP", "SC", "SS", "SB", "camR", "camU", "SK", "SA"]);
  const blit = makeProgram(gl, BLIT_VS, BLIT_FS, ["T", "R", "VPX", "Q"]);
  const upload = (mesh) => {
    const pb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, pb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(mesh.p), gl.STATIC_DRAW);
    const nb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, nb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(mesh.n), gl.STATIC_DRAW);
    return { pb, nb, count: mesh.p.length / 3 };
  };
  const meshes = { box: upload(boxMesh()), cyl: upload(cylinderMesh()), cyl6: upload(cylinderMesh(7)), cone: upload(coneMesh()),
    pyr: upload(coneMesh(4)), sph: upload(sphereMesh()), quad: upload(quadMesh()) };
  const view = { canvas, labels, gl, solid, outline, sky, sprite, blit, meshes, opts, yaw: 0.6, pitch: opts.pitch || 0.5,
    dist: opts.dist || 15, drag: null, labelNodes: {}, visible: false, raf: 0, last: 0, lastDraw: 0, fb: null, fbFailed: false };
  canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); view.lost = true; });
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

function bindMesh(gl, loc, m) {
  gl.bindBuffer(gl.ARRAY_BUFFER, m.pb); gl.vertexAttribPointer(loc.p, 3, gl.FLOAT, false, 0, 0); gl.enableVertexAttribArray(loc.p);
  if (loc.n >= 0) { gl.bindBuffer(gl.ARRAY_BUFFER, m.nb); gl.vertexAttribPointer(loc.n, 3, gl.FLOAT, false, 0, 0); gl.enableVertexAttribArray(loc.n); }
  for (let i = 0; i < 4; i++) if (i !== loc.p && i !== loc.n) gl.disableVertexAttribArray(i);
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

// The scenery that never changes: trees, rocks, lamp posts and clouds, scattered once with a
// fixed seed, kept off the paths, the plaza and the stations.
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
  const trees = [], rocks = [], lamps = [], clouds = [];
  for (let i = 0; i < 400 && trees.length < 16; i++) {
    const a = rnd() * Math.PI * 2, r = 4 + rnd() * (ISLAND - 4.8);
    const x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (!clear(x, z, 0.2) || trees.some((t) => Math.hypot(t.x - x, t.z - z) < 1.3)) continue;
    trees.push({ x, z, h: 0.8 + rnd() * 0.6, kind: rnd() < 0.6 ? 0 : 1, ry: rnd() * 6 });
  }
  for (let i = 0; i < 300 && rocks.length < 9; i++) {
    const a = rnd() * Math.PI * 2, r = 3.5 + rnd() * (ISLAND - 4);
    const x = Math.cos(a) * r, z = Math.sin(a) * r;
    if (!clear(x, z, 0) || trees.some((t) => Math.hypot(t.x - x, t.z - z) < 0.9)) continue;
    rocks.push({ x, z, s: 0.3 + rnd() * 0.45, ry: rnd() * 6 });
  }
  for (const name of ["library", "review desk", "terminal"]) {   // lamps halfway along three paths
    const [sx, sz] = STATION_LAYOUT[name].pos, len = Math.hypot(sx, sz);
    lamps.push({ x: sx * 0.5 + sz / len * 0.75, z: sz * 0.5 - sx / len * 0.75 });
  }
  for (let i = 0; i < 4; i++) clouds.push({ a: i * 1.6 + rnd(), r: 15 + rnd() * 4, y: 6.5 + rnd() * 2.5, s: 0.7 + rnd() * 0.5 });
  return { trees, rocks, lamps, clouds };
})();

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
    w.color = hexRgb(a.color, hexRgb(a.id === "loki" ? "#2ee6d6" : (STATION_LAYOUT[a.station] || {}).color, [0.6, 0.7, 0.85]));
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

// ---------------------------------------------------------------- building the scene
// Each frame collects what to draw (solids, see-through solids, shadows, glows, lights) and
// then draws it in passes: sky, ink outlines, cel-shaded solids, shadows, glows.
function sceneList(view, t, dt) {
  const L = { solids: [], clear: [], shadows: [], glows: [], lights: [] };
  const solid = (mesh, pos, ry, s, color, o) => (o && o.a < 1 ? L.clear : L.solids).push(Object.assign({ mesh, pos, ry, s, color }, o || {}));
  const shadow = (x, z, r, a) => L.shadows.push({ x, z, r, a: Math.min(1, (a == null ? 0.5 : a) * 1.3) });
  const glow = (pos, r, color, a) => L.glows.push({ pos, r, color, a: a == null ? 1 : a });
  const light = (pos, color, radius) => L.lights.push({ pos, color, radius });
  const ink = { line: false };

  // the island: grass top with a soft checker, a band of earth, a faceted rock cone below
  solid("cyl", [0, -0.2, 0], 0, [ISLAND * 2, 0.4, ISLAND * 2], [0.10, 0.60, 0.36], { g: 0.9 });
  solid("cyl6", [0, -0.75, 0], 0.3, [ISLAND * 2 - 0.2, 0.75, ISLAND * 2 - 0.2], [0.55, 0.34, 0.30]);
  solid("cone", [0, -3.6, 0], 0.5, [ISLAND * 1.9, 5.0, ISLAND * 1.9].map((v, i) => (i === 1 ? -v : v)), [0.36, 0.26, 0.42], { line: false });
  solid("cone", [0, -3.4, 0], 2.1, [ISLAND * 1.55, -4.6, ISLAND * 1.55], [0.30, 0.22, 0.40], { line: false });
  // the plaza and the paths
  solid("cyl", [0, 0.02, 0], 0, [7.2, 0.06, 7.2], [0.62, 0.62, 0.78], Object.assign({ g: 1.4 }, ink));
  solid("cyl", [0, 0.05, 0], 0, [3.2, 0.04, 3.2], [0.12, 0.22, 0.42], ink);

  for (const [name, st] of Object.entries(STATION_LAYOUT)) {
    const [x, z] = st.pos;
    const c = hexRgb(st.color, [0.5, 0.6, 0.7]);
    const busy = Object.values(World.agents).some((a) => a.data && a.data.station === name && a.data.state === "working");
    if (name === "hall") {
      // the conductor's spire: an L-shaped mark, LOKI's sign, with a beacon on top
      solid("box", [x - 0.25, 1.3, z], 0, [0.36, 2.6, 0.36], [0.18, 0.86, 0.82], { e: 0.12 });
      solid("box", [x + 0.2, 0.2, z], 0, [1.2, 0.36, 0.36], [0.18, 0.86, 0.82], { e: 0.12 });
      const by = 2.85 + Math.sin(t * 1.4) * 0.08;
      solid("sph", [x - 0.25, by, z], 0, [0.36, 0.36, 0.36], [0.6, 1, 0.95], { e: 1.1, line: false });
      glow([x - 0.25, by, z], 1.1, [0.3, 1, 0.9], 0.8);
      light([x - 0.25, 2.2, z], [0.1, 0.5, 0.48], 3.4);
      continue;
    }
    const len = Math.hypot(x, z), ux = x / len, uz = z / len, ang = Math.atan2(x, z);
    solid("box", [x / 2, 0.015, z / 2], ang, [0.9, 0.03, len], [0.70, 0.66, 0.80], ink);
    for (let k = 1; k < 5; k++) solid("box", [x * k / 5 + uz * 0.55, 0.035, z * k / 5 - ux * 0.55], ang + k, [0.22, 0.03, 0.22], [0.58, 0.55, 0.70], ink);
    solid("cyl", [x, 0.03, z], 0, [2.6, 0.06, 2.6], mix3(c, [0.6, 0.6, 0.75], 0.55), ink);
    // a little building behind the station: cream walls, a roof in the station colour, a lit window
    const bx = x + ux * 2.1, bz = z + uz * 2.1, rot = ang;
    solid("box", [bx, 0.55, bz], rot, [1.5, 1.1, 1.3], [0.93, 0.86, 0.74]);
    solid("pyr", [bx, 1.55, bz], rot + Math.PI / 4, [2.25, 0.9, 2.0], c);
    solid("box", [bx - ux * 0.66 + uz * 0.38, 0.62, bz - uz * 0.66 - ux * 0.38], rot, [0.42, 0.34, 0.04], [1.0, 0.82, 0.45], { e: 0.9, line: false });
    solid("box", [bx - ux * 0.66 - uz * 0.3, 0.33, bz - uz * 0.66 + ux * 0.3], rot, [0.34, 0.66, 0.06], [0.36, 0.22, 0.20], { line: false });
    shadow(bx + 0.25, bz - 0.2, 1.4, 0.45);
    // the desk the agent works at, and the station lamp
    solid("box", [x, 0.48, z], ang, [1.4, 0.12, 0.75], [0.62, 0.38, 0.26]);
    solid("box", [x - 0.55, 0.22, z], ang, [0.1, 0.44, 0.1], [0.40, 0.25, 0.18]);
    solid("box", [x + 0.55, 0.22, z], ang, [0.1, 0.44, 0.1], [0.40, 0.25, 0.18]);
    shadow(x, z, 0.95, 0.35);
    const lx = x - uz * 1.0 + ux * 0.6, lz = z + ux * 1.0 + uz * 0.6;
    solid("cyl6", [lx, 0.7, lz], 0, [0.09, 1.4, 0.09], [0.16, 0.18, 0.28]);
    const oy = 1.55 + Math.sin(t * 1.4 + x) * 0.05;
    solid("sph", [lx, oy, lz], 0, [0.32, 0.32, 0.32], mix3(c, [1, 1, 1], 0.25), { e: busy ? 1.1 : 0.55, line: false });
    glow([lx, oy, lz], busy ? 1.2 : 0.8, c, busy ? 0.9 : 0.55);
    light([lx, 1.2, lz], scale3(c, busy ? 0.95 : 0.55), busy ? 3.8 : 3.0);
    shadow(lx, lz, 0.3, 0.4);
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
    glow([lp.x, 1.55, lp.z], 0.85, [1.0, 0.7, 0.35], 0.75);
    light([lp.x, 1.3, lp.z], [0.7, 0.45, 0.2], 2.3);
    shadow(lp.x, lp.z, 0.3, 0.4);
  }
  for (const cl of SCENERY.clouds) {
    const a = cl.a + (World.reduced ? 0 : t * 0.01);
    const cx = Math.cos(a) * cl.r, cz = Math.sin(a) * cl.r, s = cl.s;
    solid("sph", [cx, cl.y, cz], a, [1.6 * s, 0.9 * s, 1.2 * s], [0.92, 0.95, 1.0], { e: 0.1 });
    solid("sph", [cx + 0.8 * s, cl.y - 0.15, cz + 0.2], a, [1.1 * s, 0.7 * s, 0.9 * s], [0.92, 0.95, 1.0], { e: 0.1 });
    solid("sph", [cx - 0.8 * s, cl.y - 0.2, cz - 0.1], a, [1.0 * s, 0.6 * s, 0.8 * s], [0.92, 0.95, 1.0], { e: 0.1 });
  }

  // agents
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
    const big = id === "loki" ? 1.6 : 1.3;
    a.big = big;
    shadow(a.x + 0.06, a.z - 0.05, 0.42 * big, 0.7);
    solid("cyl", [a.x, 0.42 * big + bob, a.z], a.ry, [0.42 * big, 0.62 * big, 0.42 * big], col, { s2: 0.25 });
    solid("sph", [a.x, 0.98 * big + bob, a.z], a.ry, [0.44 * big, 0.44 * big, 0.44 * big], col.map((v) => Math.min(1, v * 1.12 + 0.05)), { s2: 0.4 });
    const fx = Math.sin(a.ry) * 0.18 * big, fz = Math.cos(a.ry) * 0.18 * big;
    solid("box", [a.x + fx, 1.02 * big + bob, a.z + fz], a.ry, [0.28 * big, 0.09 * big, 0.08], [0.6, 0.98, 1.0], { e: 0.8, line: false });
    if (d.state === "working") {
      const wy = 1.6 * big + Math.sin(t * 3 + a.phase) * 0.05;
      solid("box", [a.x, wy, a.z], t * 2.4, [0.16, 0.16, 0.16], [0.56, 0.9, 1], { e: 0.9 });
      glow([a.x, wy, a.z], 0.45, [0.4, 0.85, 1.0], 0.7);
    }
    if (d.state === "blocked") {
      solid("cyl", [a.x, 0.07, a.z], 0, [1.1, 0.03, 1.1], [1, 0.3, 0.3], { a: 0.5 + 0.3 * Math.sin(t * 5), e: 0.8, line: false });
      light([a.x, 0.8, a.z], [0.9, 0.15, 0.15], 2.2);
    }
    if (d.state === "done") solid("sph", [a.x, 1.6 * big, a.z], 0, [0.18, 0.18, 0.18], [0.5, 1, 0.55], { e: 0.9 });
  }
  return L;
}

// ---------------------------------------------------------------- frame
function frame(view, now) {
  const { gl, canvas } = view;
  if (view.lost || gl.isContextLost()) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(canvas.clientWidth * dpr)), h = Math.max(1, Math.round(canvas.clientHeight * dpr));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  // one world pixel = `pixel` CSS px, rounded to a whole number of device pixels
  const scale = Math.max(1, Math.round((World.pixel || view.opts.pixel || 3) * dpr));
  const lw = Math.max(1, Math.ceil(w / scale)), lh = Math.max(1, Math.ceil(h / scale));
  const fb = ensureTarget(view, lw, lh);
  const rw = fb ? lw : w, rh = fb ? lh : h;

  const dt = Math.min(0.1, (now - (view.last || now)) / 1000);
  view.last = now;
  if (!view.drag && !World.reduced) view.yaw += dt * (view.opts.spin || 0.05);
  const t = now / 1000;

  // time of day -> palette (subtle; reduced motion keeps it but it only moves with the clock)
  const d = new Date(), hour = World.hour != null ? World.hour : d.getHours() + d.getMinutes() / 60;
  const day = smooth(5.5, 8.5, hour) * (1 - smooth(17.5, 20.5, hour)) * 0.85;
  const P = {};
  for (const k of Object.keys(NIGHT)) P[k] = Array.isArray(NIGHT[k]) ? mix3(NIGHT[k], DAY[k], day) : NIGHT[k] + (DAY[k] - NIGHT[k]) * day;
  const sunAz = 0.9 + (World.reduced ? 0 : t * 0.004);
  const sunDir = norm([Math.cos(sunAz) * 0.6, 0.62 + day * 0.25, Math.sin(sunAz) * 0.6]);

  // camera
  const fov = view.opts.fov || 0.8, target = [0, 0.7, 0];
  const eye = [Math.cos(view.yaw) * Math.cos(view.pitch) * view.dist, Math.sin(view.pitch) * view.dist + target[1],
    Math.sin(view.yaw) * Math.cos(view.pitch) * view.dist];
  const vp = M4.mul(M4.persp(fov, w / h, 0.1, 90), M4.lookAt(eye, target, [0, 1, 0]));
  const camF = norm(sub(target, eye)), camR = norm(cross(camF, [0, 1, 0])), camU = cross(camR, camF);
  const fogr = [view.dist + 2, 16];

  const L = sceneList(view, t, dt);

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
    gl.uniform1f(loc.stars, P.stars);
    bindMesh(gl, loc, quad);
    gl.drawArrays(gl.TRIANGLES, 0, quad.count);
  }
  gl.enable(gl.DEPTH_TEST);
  gl.enable(gl.CULL_FACE);

  // 2. ink outlines: inflated back faces (cull the front)
  if (view.outline) {
    const { prog, loc } = view.outline;
    gl.useProgram(prog);
    gl.cullFace(gl.FRONT);
    gl.uniformMatrix4fv(loc.VP, false, vp);
    gl.uniform3fv(loc.oeye, eye);
    gl.uniform1f(loc.OL, 1.15 * 2 * Math.tan(fov / 2) / rh);
    gl.uniform3fv(loc.ofog, P.fog); gl.uniform2fv(loc.ofogr, fogr);
    const inkc = [0.03, 0.03, 0.10];
    for (const o of L.solids) {
      if (o.line === false) continue;
      const m = view.meshes[o.mesh];
      bindMesh(gl, loc, m);
      gl.uniformMatrix4fv(loc.M, false, M4.trs(o.pos, o.ry, o.s));
      gl.uniform3fv(loc.OC, mix3(inkc, o.color, 0.22));
      gl.drawArrays(gl.TRIANGLES, 0, m.count);
    }
  }

  // 3. cel-shaded solids
  const { prog, loc } = view.solid;
  gl.useProgram(prog);
  gl.cullFace(gl.BACK);
  gl.uniformMatrix4fv(loc.VP, false, vp);
  gl.uniform3fv(loc.eye, eye);
  gl.uniform3fv(loc.sunDir, sunDir); gl.uniform3fv(loc.sunCol, P.sunCol);
  gl.uniform3fv(loc.skyAmb, P.skyAmb); gl.uniform3fv(loc.gndAmb, P.gndAmb); gl.uniform3fv(loc.shadeTint, P.shade);
  gl.uniform3fv(loc.rimCol, P.rim); gl.uniform3fv(loc.fogc, P.fog); gl.uniform2fv(loc.fogr, fogr);
  const lp = new Float32Array(30), lc = new Float32Array(40);
  L.lights.slice(0, 10).forEach((l, i) => {
    lp.set(l.pos, i * 3);
    lc.set([l.color[0] * P.lamps, l.color[1] * P.lamps, l.color[2] * P.lamps, l.radius], i * 4);
  });
  for (let i = L.lights.length; i < 10; i++) lc[i * 4 + 3] = 1;
  gl.uniform3fv(loc.LP, lp); gl.uniform4fv(loc.LC, lc);
  const drawSolid = (o) => {
    const m = view.meshes[o.mesh];
    bindMesh(gl, loc, m);
    gl.uniformMatrix4fv(loc.M, false, M4.trs(o.pos, o.ry, o.s));
    gl.uniform3f(loc.IS, 1 / (o.s[0] * o.s[0]), 1 / (o.s[1] * o.s[1]), 1 / (o.s[2] * o.s[2]));
    gl.uniform3fv(loc.C, o.color); gl.uniform1f(loc.A, o.a == null ? 1 : o.a); gl.uniform1f(loc.E, o.e || 0);
    gl.uniform1f(loc.G, o.g || 0); gl.uniform1f(loc.S, o.s2 || 0.3);
    gl.drawArrays(gl.TRIANGLES, 0, m.count);
  };
  for (const o of L.solids) {
    // squashed with a negative y (the rock cone points down): flip the winding for it
    gl.frontFace(o.s[0] * o.s[1] * o.s[2] < 0 ? gl.CW : gl.CCW);
    drawSolid(o);
  }
  gl.frontFace(gl.CCW);

  // 4. see-through solids, shadows, glows: blended, depth-tested, not depth-written
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  gl.depthMask(false);
  for (const o of L.clear) drawSolid(o);
  gl.disable(gl.CULL_FACE);
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
      gl.drawArrays(gl.TRIANGLES, 0, quad.count);
    }
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);   // glows add light
    gl.uniform1f(sp.loc.SB, 1);
    for (const g of L.glows) {
      gl.uniform3fv(sp.loc.SC, g.pos); gl.uniform2f(sp.loc.SS, g.r, g.r);
      gl.uniform3fv(sp.loc.SK, g.color); gl.uniform1f(sp.loc.SA, g.a * (0.55 + 0.45 * P.lamps));
      gl.drawArrays(gl.TRIANGLES, 0, quad.count);
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
    gl.uniform1f(bl.Q, view.opts.levels || 20);
    bindMesh(gl, bl, quad);
    gl.drawArrays(gl.TRIANGLES, 0, quad.count);
  }

  // the label above each head, and what it last said
  const proj = (p) => {
    const v = [vp[0] * p[0] + vp[4] * p[1] + vp[8] * p[2] + vp[12], vp[1] * p[0] + vp[5] * p[1] + vp[9] * p[2] + vp[13],
      vp[3] * p[0] + vp[7] * p[1] + vp[11] * p[2] + vp[15]];
    if (v[2] <= 0) return null;
    return [(v[0] / v[2] * 0.5 + 0.5) * canvas.clientWidth, (1 - (v[1] / v[2] * 0.5 + 0.5)) * canvas.clientHeight];
  };
  if (!view.labels) return;
  const seen = new Set();
  for (const [id, a] of Object.entries(World.agents)) {
    const d2 = a.data || {};
    seen.add(id);
    let node = view.labelNodes[id];
    if (!node) {
      node = view.labelNodes[id] = el("div", "wlabel");
      node.append(el("b"), el("span"), el("i"));
      view.labels.append(node);
    }
    const at = proj([a.x, 1.6 * (a.big || 1) + 0.35, a.z]);
    node.hidden = !at;
    if (at) {
      node.style.transform = "translate(" + Math.round(at[0]) + "px," + Math.round(at[1]) + "px) translate(-50%,-100%)";
      node.children[0].textContent = d2.name || id;
      node.children[1].textContent = view.opts.detail ? (d2.state + (d2.task ? " · " + d2.task.slice(0, 48) : "")) : "";
      const fresh = a.said && performance.now() - a.saidAt < 9000;
      node.children[2].textContent = fresh ? "“" + a.said.slice(0, 90) + "”" : "";
      node.classList.toggle("speaking", !!fresh);
    }
  }
  for (const id of Object.keys(view.labelNodes)) if (!seen.has(id)) { view.labelNodes[id].remove(); delete view.labelNodes[id]; }
}

// Runs while the view is visible and the window is not hidden. The background view is
// capped (opts.fps, 30) so it stays light behind the home screen.
function loop(view) {
  const tick = (now) => {
    if (!view.visible || document.hidden) { view.visible = false; view.raf = 0; return; }
    view.raf = requestAnimationFrame(tick);
    const fps = view.opts.fps || 0;
    if (fps && view.lastDraw && now - view.lastDraw < 1000 / fps - 2) return;
    view.lastDraw = now;
    if (now - World.lastFetch > 2500) fetchWorld();
    frame(view, now);
  };
  if (!view.raf) view.raf = requestAnimationFrame(tick);
}

function setVisible(view, on) {
  if (!view) return;
  view.visible = on && !document.hidden;
  if (view.visible) { view.last = 0; view.lastDraw = 0; loop(view); }
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
    World.views.panel = canvas && makeView(canvas, document.getElementById("world-panel-labels"),
      { dist: 17, pitch: 0.5, spin: 0.03, detail: true, pixel: 3, fps: 0 });
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
  if (canvas) World.views.bg = makeView(canvas, document.getElementById("world-bg-labels"),
    { dist: 19, pitch: 0.46, spin: 0.045, detail: false, pixel: 4, fps: 30 });
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
