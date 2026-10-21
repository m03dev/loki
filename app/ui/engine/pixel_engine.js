// LOKI Pixel Engine - LOKI's own small game engine, in a pixel cel-shaded look.
//
// The same pixel cel-shaded style as the world: the scene is drawn into a low-resolution
// framebuffer and blown up with NEAREST filtering, posterized with an ordered (Bayer) dither,
// lit in hard cel bands, and every solid gets a dark ink outline (an inflated back-face hull).
// Plain WebGL 1, no libraries, so it runs in LOKI's window on the Mac and the PC.
//
// Games are one JavaScript file that LOKI (or you) writes. They run in the Play panel, in a
// sandboxed frame (no access to LOKI's token, files or engine). A game looks like:
//
//   const G = PixelEngine.create(document.getElementById("game"), { pixel: 3 });
//   const fox = G.add(PixelEngine.models.fox(), { pos: [0, 0, 0] });
//   G.on("update", (dt, t) => { if (G.key("ArrowLeft")) fox.pos[0] -= dt * 3; });
//   G.start();
//
// API (all of it):
//   PixelEngine.create(canvas, {pixel, levels, bands, sky:[top,horizon], sun:[x,y,z]}) -> G
//   G.add(partsOrPart, {pos, ry, scale}) -> entity {pos, ry, scale, parts, visible, data}
//       a part: {mesh: "box"|"sph"|"cyl"|"cone"|"pyr", pos, ry, s:[x,y,z], color:[r,g,b], e, line}
//   G.remove(entity)            G.clear()
//   G.camera = {target:[x,y,z], yaw, pitch, dist, fov}
//   G.on("update", fn(dt, t))   G.start()   G.stop()
//   G.key(name)  (KeyboardEvent.key or .code: "ArrowLeft", "a", "Space", ...)   G.pointer {x, y, down}
//   G.hud(text) / G.hud(text, "big")    G.sound(freq, seconds, type, volume)
//   G.hit(a, b, r)  true when two entities are closer than r (default 0.6) on the ground plane
//   G.rand(seed) -> a seeded random function
//   PixelEngine.models.{fox, rabbit, tree, rock, coin, person(color)} -> parts
"use strict";

(function () {
  // ------------------------------------------------------------------ math (column-major 4x4)
  const M4 = {
    perspective(fov, aspect, near, far) {
      const f = 1 / Math.tan(fov / 2), nf = 1 / (near - far);
      return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
    },
    lookAt(e, c, up) {
      let z = [e[0] - c[0], e[1] - c[1], e[2] - c[2]]; z = norm(z);
      let x = norm(cross(up, z)); const y = cross(z, x);
      return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0,
        -dot(x, e), -dot(y, e), -dot(z, e), 1];
    },
    mul(a, b) {
      const o = new Array(16);
      for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
        o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
      }
      return o;
    },
    // translate * rotateY * scale; local x -> (cos, -sin) and local z -> (sin, cos) on the ground
    trs(t, ry, s) {
      const c = Math.cos(ry), n = Math.sin(ry);
      return [c * s[0], 0, -n * s[0], 0, 0, s[1], 0, 0, n * s[2], 0, c * s[2], 0, t[0], t[1], t[2], 1];
    },
  };
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function norm(a) { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; }

  // ------------------------------------------------------------------ meshes (flat normals, unit size)
  function pushTri(P, N, a, b, c) {
    const n = norm(cross([b[0] - a[0], b[1] - a[1], b[2] - a[2]], [c[0] - a[0], c[1] - a[1], c[2] - a[2]]));
    P.push(...a, ...b, ...c); N.push(...n, ...n, ...n);
  }
  function boxMesh() {
    const P = [], N = [], h = 0.5;
    const v = (x, y, z) => [x * h, y * h, z * h];
    const quad = (a, b, c, d) => { pushTri(P, N, a, b, c); pushTri(P, N, a, c, d); };
    quad(v(-1, -1, 1), v(1, -1, 1), v(1, 1, 1), v(-1, 1, 1));
    quad(v(1, -1, -1), v(-1, -1, -1), v(-1, 1, -1), v(1, 1, -1));
    quad(v(1, -1, 1), v(1, -1, -1), v(1, 1, -1), v(1, 1, 1));
    quad(v(-1, -1, -1), v(-1, -1, 1), v(-1, 1, 1), v(-1, 1, -1));
    quad(v(-1, 1, 1), v(1, 1, 1), v(1, 1, -1), v(-1, 1, -1));
    quad(v(-1, -1, -1), v(1, -1, -1), v(1, -1, 1), v(-1, -1, 1));
    return { p: P, n: N };
  }
  function cylMesh(seg, topR) {
    const P = [], N = [];
    for (let i = 0; i < seg; i++) {
      const a0 = i / seg * Math.PI * 2, a1 = (i + 1) / seg * Math.PI * 2;
      const b0 = [Math.cos(a0) * 0.5, -0.5, Math.sin(a0) * 0.5], b1 = [Math.cos(a1) * 0.5, -0.5, Math.sin(a1) * 0.5];
      const t0 = [Math.cos(a0) * 0.5 * topR, 0.5, Math.sin(a0) * 0.5 * topR], t1 = [Math.cos(a1) * 0.5 * topR, 0.5, Math.sin(a1) * 0.5 * topR];
      pushTri(P, N, b0, t1, b1);
      if (topR > 0) { pushTri(P, N, b0, t0, t1); pushTri(P, N, [0, 0.5, 0], t1, t0); }
      pushTri(P, N, [0, -0.5, 0], b0, b1);
    }
    return { p: P, n: N };
  }
  function sphMesh(rings, segs) {
    const P = [], N = [];
    const pt = (r, s) => {
      const th = r / rings * Math.PI, ph = s / segs * Math.PI * 2;
      return [Math.sin(th) * Math.cos(ph) * 0.5, Math.cos(th) * 0.5, Math.sin(th) * Math.sin(ph) * 0.5];
    };
    for (let r = 0; r < rings; r++) for (let s = 0; s < segs; s++) {
      const a = pt(r, s), b = pt(r + 1, s), c = pt(r + 1, s + 1), d = pt(r, s + 1);
      if (r > 0) pushTri(P, N, a, d, c);
      if (r < rings - 1) pushTri(P, N, a, c, b);
    }
    return { p: P, n: N };
  }
  const MESHES = { box: boxMesh(), cyl: cylMesh(8, 1), cone: cylMesh(7, 0), pyr: cylMesh(4, 0), sph: sphMesh(5, 8) };

  // ------------------------------------------------------------------ shaders
  const VS = "attribute vec3 p; attribute vec3 n; uniform mat4 VP; uniform mat4 M; uniform vec3 IS;" +
    "varying vec3 vn; varying vec3 wp;" +
    "void main(){ vec4 w = M * vec4(p,1.0); wp = w.xyz; vn = mat3(M) * (n * IS); gl_Position = VP * w; }";
  const FS = "precision mediump float; varying vec3 vn; varying vec3 wp; uniform vec3 C; uniform float E; uniform float BANDS;" +
    "uniform vec3 eye; uniform vec3 sunDir; uniform vec3 sunCol; uniform vec3 skyAmb; uniform vec3 gndAmb; uniform vec3 rimCol;" +
    "float cel(float x){ return min(floor(clamp(x,0.0,1.0) * BANDS) / (BANDS - 1.0), 1.0); }" +
    "void main(){ vec3 N = normalize(vn); vec3 V = normalize(eye - wp);" +
    " float b = cel(dot(N, sunDir) * 0.55 + 0.42);" +
    " vec3 amb = mix(gndAmb, skyAmb, step(0.0, N.y) * 0.5 + step(0.6, N.y) * 0.5);" +
    " vec3 col = mix(C * amb * vec3(0.72,0.74,0.95), C * (amb + sunCol), b);" +
    " float rim = 1.0 - max(dot(N, V), 0.0); col += rimCol * step(0.72, rim) * (0.3 + 0.7 * b) * (1.0 - step(0.8, N.y));" +   // no rim on flat ground
    " vec3 H = normalize(sunDir + V); col += sunCol * step(0.96, dot(N, H)) * 0.3;" +
    " gl_FragColor = vec4(col + C * E, 1.0); }";
  // ink: the solid again, back faces only, pushed out along its normal by about one low-res pixel
  const OVS = "attribute vec3 p; attribute vec3 n; uniform mat4 VP; uniform mat4 M; uniform vec3 IS; uniform vec3 eye; uniform float OL;" +
    "void main(){ vec4 w = M * vec4(p,1.0); vec3 wn = normalize(mat3(M) * (n * IS));" +
    " w.xyz += wn * OL * length(eye - w.xyz); gl_Position = VP * w; }";
  const OFS = "precision mediump float; uniform vec3 OC; void main(){ gl_FragColor = vec4(OC, 1.0); }";
  const SKY_VS = "attribute vec3 p; varying float vy; void main(){ vy = p.y; gl_Position = vec4(p.xy, 0.999, 1.0); }";
  const SKY_FS = "precision mediump float; varying float vy; uniform vec3 top; uniform vec3 hor;" +
    "void main(){ float k = floor(clamp(vy * 0.5 + 0.5, 0.0, 1.0) * 6.0) / 6.0; gl_FragColor = vec4(mix(hor, top, k), 1.0); }";
  const BLIT_VS = "attribute vec3 p; void main(){ gl_Position = vec4(p.xy, 0.0, 1.0); }";
  const BLIT_FS = "precision mediump float; uniform sampler2D T; uniform vec2 R; uniform vec2 VPX; uniform float Q;" +
    "float bayer2(vec2 a){ a = floor(a); return fract(a.x / 2.0 + a.y * a.y * 0.75); }" +
    "float bayer4(vec2 a){ return bayer2(0.5 * a) * 0.25 + bayer2(a); }" +
    "void main(){ vec2 uv = gl_FragCoord.xy / VPX; vec3 c = texture2D(T, uv).rgb;" +
    " float b = bayer4(floor(uv * R)) - 0.5; c = floor(c * Q + 0.5 + b) / Q;" +
    " vec2 v = uv - 0.5; c *= 1.0 - dot(v, v) * 0.35; gl_FragColor = vec4(c, 1.0); }";

  function program(gl, vs, fs, uniforms) {
    const sh = (type, src) => {
      const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    const prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(prog);
    const loc = { p: gl.getAttribLocation(prog, "p"), n: gl.getAttribLocation(prog, "n") };
    for (const u of uniforms) loc[u] = gl.getUniformLocation(prog, u);
    return { prog, loc };
  }

  // ------------------------------------------------------------------ the engine
  function create(canvas, opts) {
    opts = opts || {};
    const gl = canvas.getContext("webgl", { antialias: false, alpha: false });
    if (!gl) throw new Error("this window cannot draw 3D (no WebGL)");
    const solid = program(gl, VS, FS, ["VP", "M", "IS", "C", "E", "BANDS", "eye", "sunDir", "sunCol", "skyAmb", "gndAmb", "rimCol"]);
    const ink = program(gl, OVS, OFS, ["VP", "M", "IS", "eye", "OL", "OC"]);
    const sky = program(gl, SKY_VS, SKY_FS, ["top", "hor"]);
    const blit = program(gl, BLIT_VS, BLIT_FS, ["T", "R", "VPX", "Q"]);
    const buffers = {};
    for (const [name, m] of Object.entries(MESHES)) {
      const pb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, pb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(m.p), gl.STATIC_DRAW);
      const nb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, nb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(m.n), gl.STATIC_DRAW);
      buffers[name] = { pb, nb, count: m.p.length / 3 };
    }
    const quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, -1, 0, 1, 1, 0, -1, 1, 0]), gl.STATIC_DRAW);
    let fb = null, tex = null, rb = null, fbSize = [0, 0];

    const G = {
      entities: [], camera: { target: [0, 0.5, 0], yaw: 0.8, pitch: 0.55, dist: 12, fov: 0.75 },
      pixel: opts.pixel || 3, levels: opts.levels || 32, bands: opts.bands || 4,
      skyTop: (opts.sky && opts.sky[0]) || [0.32, 0.58, 0.92], skyHorizon: (opts.sky && opts.sky[1]) || [0.78, 0.90, 1.0],
      sun: norm(opts.sun || [0.5, 0.8, 0.35]), pointer: { x: 0, y: 0, down: false },
      _handlers: { update: [] }, _keys: new Set(), _raf: 0, _last: 0, _t: 0, _audio: null,
    };

    G.add = (parts, o) => {
      o = o || {};
      const e = { parts: Array.isArray(parts) ? parts : [parts], pos: (o.pos || [0, 0, 0]).slice(), ry: o.ry || 0,
        scale: o.scale || 1, visible: true, data: o.data || {} };
      G.entities.push(e);
      return e;
    };
    G.remove = (e) => { const i = G.entities.indexOf(e); if (i >= 0) G.entities.splice(i, 1); };
    G.clear = () => { G.entities.length = 0; };
    G.on = (name, fn) => { (G._handlers[name] = G._handlers[name] || []).push(fn); };
    G.key = (name) => G._keys.has(name) || G._keys.has(String(name).toLowerCase());
    G.hit = (a, b, r) => Math.hypot(a.pos[0] - b.pos[0], a.pos[2] - b.pos[2]) < (r || 0.6);
    G.rand = (seed) => { let s = (seed >>> 0) || 1; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); };
    G.hud = (text, kind) => {
      let box = canvas.parentNode && canvas.parentNode.querySelector(".pe-hud" + (kind === "big" ? ".big" : ":not(.big)"));
      if (!box && canvas.parentNode) {
        box = document.createElement("div");
        box.className = "pe-hud" + (kind === "big" ? " big" : "");
        canvas.parentNode.append(box);
      }
      if (box) { box.textContent = text || ""; box.hidden = !text; }
    };
    G.sound = (freq, seconds, type, volume) => {
      try {
        G._audio = G._audio || new (window.AudioContext || window.webkitAudioContext)();
        const a = G._audio, o = a.createOscillator(), g = a.createGain();
        o.type = type || "square"; o.frequency.value = freq || 440;
        g.gain.setValueAtTime(volume == null ? 0.08 : volume, a.currentTime);
        g.gain.exponentialRampToValueAtTime(0.0001, a.currentTime + (seconds || 0.12));
        o.connect(g); g.connect(a.destination); o.start(); o.stop(a.currentTime + (seconds || 0.12));
      } catch (_) { /* no sound here */ }
    };

    window.addEventListener("keydown", (ev) => {
      G._keys.add(ev.key); G._keys.add(ev.code); G._keys.add(String(ev.key).toLowerCase());
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(ev.key)) ev.preventDefault();
    });
    window.addEventListener("keyup", (ev) => { G._keys.delete(ev.key); G._keys.delete(ev.code); G._keys.delete(String(ev.key).toLowerCase()); });
    window.addEventListener("blur", () => G._keys.clear());
    canvas.addEventListener("pointerdown", (ev) => { G.pointer.down = true; canvas.focus && canvas.focus(); });
    window.addEventListener("pointerup", () => { G.pointer.down = false; });
    canvas.addEventListener("pointermove", (ev) => { const r = canvas.getBoundingClientRect(); G.pointer.x = (ev.clientX - r.left) / r.width; G.pointer.y = (ev.clientY - r.top) / r.height; });

    function target(w, h) {
      if (fb && fbSize[0] === w && fbSize[1] === h) return;
      if (fb) { gl.deleteFramebuffer(fb); gl.deleteTexture(tex); gl.deleteRenderbuffer(rb); }
      tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.NEAREST], [gl.TEXTURE_MAG_FILTER, gl.NEAREST], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
      rb = gl.createRenderbuffer(); gl.bindRenderbuffer(gl.RENDERBUFFER, rb); gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, w, h);
      fb = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, rb);
      fbSize = [w, h];
    }

    function bind(loc, m) {
      gl.bindBuffer(gl.ARRAY_BUFFER, m.pb); gl.enableVertexAttribArray(loc.p); gl.vertexAttribPointer(loc.p, 3, gl.FLOAT, false, 0, 0);
      if (loc.n >= 0) { gl.bindBuffer(gl.ARRAY_BUFFER, m.nb); gl.enableVertexAttribArray(loc.n); gl.vertexAttribPointer(loc.n, 3, gl.FLOAT, false, 0, 0); }
    }

    // every part of every visible entity, in world space
    function parts() {
      const out = [];
      for (const e of G.entities) {
        if (!e.visible) continue;
        const c = Math.cos(e.ry), n = Math.sin(e.ry), k = e.scale;
        for (const p of e.parts) {
          const lp = p.pos || [0, 0, 0];
          out.push({ mesh: p.mesh || "box", color: p.color || [0.8, 0.8, 0.8], e: p.e || 0, line: p.line !== false,
            pos: [e.pos[0] + (lp[0] * c + lp[2] * n) * k, e.pos[1] + lp[1] * k, e.pos[2] + (-lp[0] * n + lp[2] * c) * k],
            ry: e.ry + (p.ry || 0), s: (p.s || [1, 1, 1]).map((v) => v * k) });
        }
      }
      return out;
    }

    function draw() {
      const dpr = window.devicePixelRatio || 1;
      const W = Math.max(1, Math.round(canvas.clientWidth * dpr)), H = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
      const px = Math.max(1, Math.round(G.pixel * dpr));
      const w = Math.max(1, Math.floor(W / px)), h = Math.max(1, Math.floor(H / px));
      target(w, h);
      const cam = G.camera, t = cam.target;
      const eye = [t[0] + Math.cos(cam.yaw) * Math.cos(cam.pitch) * cam.dist, t[1] + Math.sin(cam.pitch) * cam.dist,
        t[2] + Math.sin(cam.yaw) * Math.cos(cam.pitch) * cam.dist];
      const VP = M4.mul(M4.perspective(cam.fov || 0.75, w / h, 0.1, 200), M4.lookAt(eye, t, [0, 1, 0]));
      const list = parts();

      gl.bindFramebuffer(gl.FRAMEBUFFER, fb); gl.viewport(0, 0, w, h);
      gl.clearColor(0, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      // sky: a stepped vertical gradient
      gl.disable(gl.DEPTH_TEST);
      gl.useProgram(sky.prog); gl.uniform3fv(sky.loc.top, G.skyTop); gl.uniform3fv(sky.loc.hor, G.skyHorizon);
      gl.bindBuffer(gl.ARRAY_BUFFER, quad); gl.enableVertexAttribArray(sky.loc.p); gl.vertexAttribPointer(sky.loc.p, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE);

      // ink outlines: back faces of an inflated hull
      gl.cullFace(gl.FRONT); gl.useProgram(ink.prog);
      gl.uniformMatrix4fv(ink.loc.VP, false, VP); gl.uniform3fv(ink.loc.eye, eye);
      gl.uniform1f(ink.loc.OL, 1.15 * 2 * Math.tan((cam.fov || 0.75) / 2) / h);
      for (const o of list) {
        if (!o.line) continue;
        gl.frontFace(o.s[0] * o.s[1] * o.s[2] < 0 ? gl.CW : gl.CCW);   // a mirrored part keeps its outside out
        bind(ink.loc, buffers[o.mesh]);
        gl.uniformMatrix4fv(ink.loc.M, false, M4.trs(o.pos, o.ry, o.s));
        gl.uniform3f(ink.loc.IS, 1 / (o.s[0] * o.s[0]), 1 / (o.s[1] * o.s[1]), 1 / (o.s[2] * o.s[2]));
        gl.uniform3f(ink.loc.OC, 0.03 + o.color[0] * 0.2, 0.03 + o.color[1] * 0.2, 0.10 + o.color[2] * 0.2);
        gl.drawArrays(gl.TRIANGLES, 0, buffers[o.mesh].count);
      }
      // cel-shaded solids
      gl.cullFace(gl.BACK); gl.useProgram(solid.prog);
      const L = solid.loc;
      gl.uniformMatrix4fv(L.VP, false, VP); gl.uniform3fv(L.eye, eye); gl.uniform1f(L.BANDS, G.bands);
      gl.uniform3fv(L.sunDir, G.sun); gl.uniform3f(L.sunCol, 0.95, 0.88, 0.72); gl.uniform3f(L.skyAmb, 0.55, 0.62, 0.80);
      gl.uniform3f(L.gndAmb, 0.30, 0.32, 0.42); gl.uniform3f(L.rimCol, 0.35, 0.40, 0.55);
      for (const o of list) {
        gl.frontFace(o.s[0] * o.s[1] * o.s[2] < 0 ? gl.CW : gl.CCW);
        bind(L, buffers[o.mesh]);
        gl.uniformMatrix4fv(L.M, false, M4.trs(o.pos, o.ry, o.s));
        gl.uniform3f(L.IS, 1 / (o.s[0] * o.s[0]), 1 / (o.s[1] * o.s[1]), 1 / (o.s[2] * o.s[2]));
        gl.uniform3fv(L.C, o.color); gl.uniform1f(L.E, o.e);
        gl.drawArrays(gl.TRIANGLES, 0, buffers[o.mesh].count);
      }
      gl.frontFace(gl.CCW); gl.disable(gl.CULL_FACE); gl.disable(gl.DEPTH_TEST);

      // up to the canvas: NEAREST, posterized with a Bayer dither in world pixels
      gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, W, H);
      gl.useProgram(blit.prog);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex); gl.uniform1i(blit.loc.T, 0);
      gl.uniform2f(blit.loc.R, w, h); gl.uniform2f(blit.loc.VPX, W, H); gl.uniform1f(blit.loc.Q, G.levels);
      gl.bindBuffer(gl.ARRAY_BUFFER, quad); gl.enableVertexAttribArray(blit.loc.p); gl.vertexAttribPointer(blit.loc.p, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    }

    function frame(now) {
      G._raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, G._last ? (now - G._last) / 1000 : 0.016);
      G._last = now; G._t += dt;
      for (const fn of G._handlers.update) {
        try { fn(dt, G._t); } catch (err) { G.hud("Game error: " + err.message, "big"); G.stop(); console.error(err); return; }
      }
      draw();
    }
    G.start = () => { if (!G._raf) { G._last = 0; G._raf = requestAnimationFrame(frame); } };
    G.stop = () => { cancelAnimationFrame(G._raf); G._raf = 0; };
    G.drawOnce = draw;
    return G;
  }

  // ------------------------------------------------------------------ models (critters and props)
  const models = {
    fox() {
      const orange = [0.93, 0.47, 0.17], cream = [0.98, 0.93, 0.84], dark = [0.22, 0.14, 0.12];
      return [
        { mesh: "box", pos: [0, 0.27, 0], s: [0.22, 0.19, 0.46], color: orange },
        { mesh: "box", pos: [0, 0.23, 0.17], s: [0.17, 0.12, 0.13], color: cream, line: false },
        { mesh: "box", pos: [0, 0.42, 0.3], s: [0.2, 0.18, 0.19], color: orange },
        { mesh: "box", pos: [0, 0.38, 0.44], s: [0.09, 0.08, 0.12], color: cream },
        { mesh: "box", pos: [0, 0.4, 0.51], s: [0.04, 0.04, 0.03], color: dark, line: false },
        { mesh: "pyr", pos: [-0.065, 0.57, 0.29], s: [0.08, 0.13, 0.05], color: orange },
        { mesh: "pyr", pos: [0.065, 0.57, 0.29], s: [0.08, 0.13, 0.05], color: orange },
        { mesh: "box", pos: [-0.05, 0.45, 0.39], s: [0.03, 0.03, 0.02], color: dark, line: false },
        { mesh: "box", pos: [0.05, 0.45, 0.39], s: [0.03, 0.03, 0.02], color: dark, line: false },
        { mesh: "box", pos: [0, 0.3, -0.34], s: [0.12, 0.12, 0.3], color: orange },
        { mesh: "box", pos: [0, 0.3, -0.52], s: [0.11, 0.11, 0.1], color: cream },
        { mesh: "box", pos: [-0.07, 0.09, 0.15], s: [0.05, 0.18, 0.05], color: dark, line: false },
        { mesh: "box", pos: [0.07, 0.09, 0.15], s: [0.05, 0.18, 0.05], color: dark, line: false },
        { mesh: "box", pos: [-0.07, 0.09, -0.15], s: [0.05, 0.18, 0.05], color: dark, line: false },
        { mesh: "box", pos: [0.07, 0.09, -0.15], s: [0.05, 0.18, 0.05], color: dark, line: false },
      ];
    },
    rabbit() {
      const fur = [0.62, 0.55, 0.5];
      return [
        { mesh: "box", pos: [0, 0.1, 0], s: [0.15, 0.14, 0.21], color: fur },
        { mesh: "box", pos: [0, 0.19, 0.12], s: [0.12, 0.12, 0.12], color: fur },
        { mesh: "box", pos: [-0.035, 0.31, 0.1], s: [0.03, 0.14, 0.04], color: [0.8, 0.66, 0.64] },
        { mesh: "box", pos: [0.035, 0.31, 0.1], s: [0.03, 0.14, 0.04], color: [0.8, 0.66, 0.64] },
        { mesh: "sph", pos: [0, 0.13, -0.12], s: [0.07, 0.07, 0.07], color: [0.97, 0.96, 0.94], line: false },
      ];
    },
    tree(h) {
      h = h || 1;
      return [
        { mesh: "cyl", pos: [0, 0.3 * h, 0], s: [0.22, 0.6 * h, 0.22], color: [0.48, 0.3, 0.22] },
        { mesh: "cone", pos: [0, 0.95 * h, 0], s: [1.2 * h, 1.0 * h, 1.2 * h], color: [0.24, 0.78, 0.34] },
        { mesh: "cone", pos: [0, 1.55 * h, 0], s: [0.85 * h, 0.85 * h, 0.85 * h], color: [0.33, 0.84, 0.4] },
      ];
    },
    rock(s) { s = s || 0.5; return [{ mesh: "box", pos: [0, s * 0.3, 0], ry: 0.4, s: [s, s * 0.75, s * 0.85], color: [0.55, 0.58, 0.74] }]; },
    coin() { return [{ mesh: "cyl", pos: [0, 0.5, 0], s: [0.3, 0.06, 0.3], color: [1, 0.82, 0.3], e: 0.35 }]; },
    berry() { return [{ mesh: "sph", pos: [0, 0.25, 0], s: [0.22, 0.22, 0.22], color: [0.85, 0.2, 0.35], e: 0.25 },
      { mesh: "box", pos: [0, 0.39, 0], s: [0.04, 0.08, 0.04], color: [0.2, 0.55, 0.3], line: false }]; },
    person(color) {
      const c = color || [0.4, 0.6, 0.9];
      return [
        { mesh: "cyl", pos: [0, 0.35, 0], s: [0.34, 0.5, 0.34], color: c },
        { mesh: "sph", pos: [0, 0.8, 0], s: [0.36, 0.36, 0.36], color: c.map((v) => Math.min(1, v * 1.12 + 0.05)) },
        { mesh: "box", pos: [0, 0.83, 0.15], s: [0.23, 0.07, 0.07], color: [0.6, 0.98, 1], e: 0.45, line: false },
      ];
    },
    island(r) {
      r = r || 8;
      return [
        { mesh: "cyl", pos: [0, -0.2, 0], s: [r * 2, 0.4, r * 2], color: [0.1, 0.6, 0.36] },
        { mesh: "cyl", pos: [0, -0.75, 0], s: [r * 2 - 0.2, 0.75, r * 2 - 0.2], color: [0.55, 0.34, 0.3] },
        { mesh: "cone", pos: [0, -3.4, 0], ry: 0.5, s: [r * 1.9, -4.6, r * 1.9], color: [0.36, 0.26, 0.42], line: false },
      ];
    },
  };

  window.PixelEngine = { create, models, M4, MESHES };
})();
