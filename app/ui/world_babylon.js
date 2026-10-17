// LOKI World - the Babylon.js renderer (Babylon.js, Apache-2.0, built from source into
// ui/vendor/babylon/babylon.loki.js with only the parts LOKI uses).
//
// world.js keeps the simulation (who is where, walking, working, teams, critters, islands,
// labels, picking) and every frame hands over one description of the scene: the island baked
// once, plus everything that moves. This module draws it with a real engine, in LOKI World's
// own look - the owner's pixel cel-shaded style, made richer rather than replaced:
//
//   * pixel art: the scene renders at low resolution (one world pixel = several screen pixels)
//     and is blown up with NEAREST filtering, then posterized with a 4x4 Bayer dither;
//   * cel shading: Babylon's toon material (hard light bands) on per-vertex/per-instance colour,
//     lit by a sun/moon with real (hard, pixel-friendly) shadow maps, a sky/ground fill and the
//     station lamps as point lights;
//   * ink outlines: every solid gets a dark hull pushed out from its centre by about one world
//     pixel, front faces culled - the same ink the classic renderer drew;
//   * things that glow (lamp bulbs, crystals, visors, beacons) are unlit and get soft halos;
//   * the stylised water (shore foam, caustics, ripples, the waterfall) and a stepped sky dome
//     with stars;
//   * everything that moves is thin-instanced: one draw per shape however many agents.
//
// Quality: "high" (2048 shadows), "medium" (1024), "low" (no shadows). world.js lowers it when
// frames run late. If WebGL is missing, create() returns null and world.js keeps the classic one.
"use strict";

(function () {
  const SHAPES = ["box", "cyl", "cyl6", "cone", "pyr", "sph", "sph4"];
  const CAP = { box: 1400, cyl: 200, cyl6: 260, cone: 120, pyr: 220, sph: 240, sph4: 200 };
  const LIGHTS = 8;
  const EMISSIVE = 0.3;           // e at or above this: drawn unlit (it glows)

  const INK_VS = "precision highp float; attribute vec3 position;\n" +
    "#include<instancesDeclaration>\n" +
    "uniform mat4 viewProjection; uniform vec3 eye; uniform float OL;\n" +
    "#ifndef THIN\nattribute vec3 center;\n#endif\n" +
    "void main(){\n#include<instancesVertex>\n" +
    " vec4 w = finalWorld * vec4(position, 1.0);\n" +
    "#ifdef THIN\n vec3 c = finalWorld[3].xyz;\n#else\n vec3 c = center;\n#endif\n" +
    " vec3 d = w.xyz - c; float l = length(d); w.xyz += (l > 0.0001 ? d / l : vec3(0.0, 1.0, 0.0)) * OL * length(eye - w.xyz);" +
    " gl_Position = viewProjection * w; }";
  const INK_FS = "precision highp float; uniform vec3 ink; void main(){ gl_FragColor = vec4(ink, 1.0); }";

  const GLOW_VS = "precision highp float; attribute vec3 position; attribute vec4 gpos; attribute vec4 gcol;" +
    "uniform mat4 viewProjection; uniform vec3 camR; uniform vec3 camU; varying vec2 q; varying vec4 col;" +
    "void main(){ q = position.xy; col = gcol; vec3 w = gpos.xyz + (camR * position.x + camU * position.y) * gpos.w;" +
    " gl_Position = viewProjection * vec4(w, 1.0); }";
  const GLOW_FS = "precision highp float; varying vec2 q; varying vec4 col;" +
    "void main(){ float a = clamp(1.0 - length(q), 0.0, 1.0); a = floor(a * 4.0 + 0.5) / 4.0; if (a <= 0.0) discard;" +
    " gl_FragColor = vec4(col.rgb * a * col.a, a * col.a); }";

  // blob shadows on the ground (the classic look): a soft disc in 3 hard steps
  const SHADOW_VS = "precision highp float; attribute vec3 position; attribute vec3 sh;\n" +
    "#ifdef DYN\nattribute vec4 spos;\n#endif\n" +
    "uniform mat4 viewProjection; varying vec3 q;" +
    "void main(){\n#ifdef DYN\n q = vec3(position.xy, spos.w); vec3 w = vec3(spos.x + position.x * spos.z, 0.078, spos.y + position.y * spos.z);\n" +
    "#else\n q = sh; vec3 w = position;\n#endif\n gl_Position = viewProjection * vec4(w, 1.0); }";
  const SHADOW_FS = "precision highp float; varying vec3 q; uniform vec3 SK;" +
    "void main(){ float a = clamp(1.0 - length(q.xy), 0.0, 1.0); a = floor(a * 3.0 + 0.6) / 3.0; if (a <= 0.0) discard;" +
    " gl_FragColor = vec4(SK, a * q.z * 0.75); }";

  const SKY_VS = "precision highp float; attribute vec3 position; uniform mat4 world; uniform mat4 viewProjection; varying vec3 vDir;" +
    "void main(){ vDir = position; vec4 p = viewProjection * (world * vec4(position, 1.0)); gl_Position = p.xyww; }";
  const SKY_FS = "precision highp float; varying vec3 vDir; uniform vec3 zenith; uniform vec3 horizon; uniform vec3 glow; uniform vec3 deep;" +
    " uniform vec3 sunDir; uniform vec3 sunCol; uniform float stars; uniform float T;" +
    " void main(){ vec3 d = normalize(vDir); float e = d.y;" +
    " vec3 col = e > 0.0 ? mix(horizon, zenith, pow(clamp(e * 1.5, 0.0, 1.0), 0.7)) : mix(horizon, deep, pow(clamp(-e * 2.0, 0.0, 1.0), 0.6));" +
    " col += glow * exp(-abs(e) * 8.0);" +
    " float s = max(dot(d, sunDir), 0.0); col += sunCol * (step(0.9992, s) * 1.4 + step(0.995, s) * 0.25);" +
    " vec3 q = floor(d * 160.0); float h = fract(sin(dot(q, vec3(12.9898, 78.233, 37.719))) * 43758.5453);" +
    " float tw = 0.6 + 0.4 * sin(T * 2.0 + h * 40.0);" +
    " col += vec3(0.9, 0.95, 1.0) * step(0.996, h) * stars * tw * smoothstep(-0.1, 0.25, e) * 1.4;" +
    " float band = sin(d.x * 3.0 + d.z * 2.0 + T * 0.05) * 0.5 + 0.5;" +
    " col += vec3(0.08, 0.55, 0.45) * stars * 0.35 * step(0.7, band) * smoothstep(0.2, 0.55, e) * (1.0 - smoothstep(0.6, 0.95, e));" +
    " gl_FragColor = vec4(floor(col * 24.0) / 24.0, 1.0); }";   // stepped: the sky stays pixel art

  // the pixel pass: posterize with a 4x4 Bayer dither in world pixels, a soft vignette
  const PIXEL_FS = "precision highp float; varying vec2 vUV; uniform sampler2D textureSampler; uniform vec2 R; uniform float Q;" +
    "float bayer2(vec2 a){ a = floor(a); return fract(a.x / 2.0 + a.y * a.y * 0.75); }" +
    "float bayer4(vec2 a){ return bayer2(0.5 * a) * 0.25 + bayer2(a); }" +
    "void main(){ vec3 c = texture2D(textureSampler, vUV).rgb; float b = bayer4(floor(vUV * R)) - 0.5;" +
    " c = floor(c * Q + 0.5 + b) / Q; vec2 v = vUV - 0.5; c *= 1.0 - dot(v, v) * 0.35; gl_FragColor = vec4(c, 1.0); }";

  function waterShaders(noise) {
    const vs = "precision highp float; attribute vec3 position; uniform mat4 world; uniform mat4 viewProjection; uniform float T; uniform vec4 shape;" +
      " varying vec3 wp; varying vec2 lp;" +
      " void main(){ vec4 w = world * vec4(position, 1.0); lp = shape.w > 1.5 ? position.xy : position.xz;" +
      " if (shape.w < 1.5) w.y += (sin(w.x * 2.3 + T * 1.6) + sin(w.z * 2.9 - T * 1.3)) * 0.006;" +
      " wp = w.xyz; gl_Position = viewProjection * w; }";
    const fs = "precision highp float; varying vec3 wp; varying vec2 lp;" +
      "uniform float T; uniform vec4 shape; uniform vec4 rect; uniform vec4 obs0; uniform vec4 obs1; uniform vec2 flow; uniform float beer;" +
      "uniform vec3 eyePos; uniform vec3 sunDir; uniform vec3 sunCol; uniform vec3 zenith; uniform vec3 horizon; uniform float dayK;" +
      "uniform vec3 shallow; uniform vec3 deep; uniform vec3 foamCol; uniform vec4 rip[4];\n" + noise + "\n" +
      "float boxd(vec2 p, vec4 b){ vec2 d = abs(p - b.xy) - b.zw; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }" +
      "float shore(vec2 p){ float d; if (shape.w < 0.5) d = shape.z - length(p - shape.xy);" +
      " else { vec2 l = p - shape.xy; d = rect.z - abs(dot(l, vec2(-rect.y, rect.x))); }" +
      " if (obs0.z > 0.0) d = min(d, boxd(p, obs0)); if (obs1.z > 0.0) d = min(d, boxd(p, obs1)); return d; }" +
      "float hgt(vec2 p){ return snoise(p * 0.9 - flow * T + vec2(T * 0.08, T * 0.05)) * 0.6 + snoise(p * 1.9 - flow * T * 1.4 + vec2(-T * 0.09, T * 0.12)) * 0.28; }" +
      "void main(){" +
      " if (shape.w > 1.5) {" +
      "  float n1 = snoise(vec2(lp.x * 9.0, wp.y * 0.9 + T * 2.6)); float n2 = snoise(vec2(lp.x * 17.0 + 3.0, wp.y * 1.7 + T * 4.1));" +
      "  vec3 c = mix(deep, shallow, 0.6 + 0.2 * n1); c = mix(c, foamCol, step(0.42, n1 * 0.6 + n2 * 0.4)); c = mix(c, foamCol, step(0.43, lp.y));" +
      "  float a = (1.0 - step(0.9, abs(lp.x) * 2.0 + n2 * 0.06)) * 0.9 * step(-0.37, lp.y);" +
      "  if (a <= 0.0) discard; gl_FragColor = vec4(c * (1.0 + 0.3 * dayK), a); return; }" +
      " vec2 q = wp.xz; float s = shore(q); if (s < -0.02) discard;" +
      " float h0 = hgt(q); float e = 0.07; vec2 g = vec2(hgt(q + vec2(e, 0.0)) - h0, hgt(q + vec2(0.0, e)) - h0) / e;" +
      " float ring = 0.0;" +
      " for (int i = 0; i < 4; i++) { if (rip[i].w > 0.0) { vec2 dv = q - rip[i].xy; float d = length(dv); float r = rip[i].z * 0.85;" +
      "  float k = exp(-abs(d - r) * 16.0) * rip[i].w * max(0.0, 1.0 - rip[i].z / 2.2); g += dv / max(d, 0.001) * k * 2.2; ring += k; } }" +
      " vec3 N = normalize(vec3(-g.x * 0.2, 1.0, -g.y * 0.2));" +
      " float depth = 1.0 - exp(-max(s, 0.0) * beer); depth = floor(depth * 4.0) / 4.0; vec3 col = mix(shallow, deep, depth);" +
      " vec2 F = cellular(q * 1.35 + g * 0.15 + vec2(T * 0.04, -T * 0.03));" +
      " col += vec3(0.5, 0.9, 1.0) * step(F.y - F.x, 0.08) * (1.0 - depth * 0.85) * (0.12 + 0.2 * dayK);" +
      " vec3 V = normalize(eyePos - wp); vec3 Rr = reflect(-V, N);" +
      " float fr = 0.04 + 0.96 * pow(1.0 - max(dot(N, V), 0.0), 5.0);" +
      " col = mix(col, mix(horizon, zenith, clamp(Rr.y * 1.4, 0.0, 1.0)), clamp(fr, 0.0, 0.6));" +
      " float sp = max(dot(Rr, sunDir), 0.0); col += sunCol * step(0.985, sp) * 0.8;" +
      " float wob = snoise(q * 3.1 + vec2(T * 0.3, -T * 0.25)) * 0.05 + snoise(q * 7.0 - vec2(T * 0.5)) * 0.025; float sd = s + wob;" +
      " float foam = step(sd, 0.1) + step(abs(sd - 0.24 - 0.035 * sin(T * 1.5)), 0.018) * 0.7 + step(0.4, ring) * 0.85;" +
      " foam = max(foam, step(0.62, h0) * 0.6 * step(0.05, length(flow))); foam = clamp(foam, 0.0, 1.0);" +
      " col = mix(col, foamCol, foam);" +
      " gl_FragColor = vec4(col, max(mix(0.62, 0.93, depth), foam)); }";
    return { vs, fs };
  }

  function create(canvas, ctx) {
    const B = window.BABYLON;
    if (!B) return null;
    let engine;
    try {
      engine = new B.Engine(canvas, false, { preserveDrawingBuffer: false, stencil: false, antialias: false,
        powerPreference: "high-performance", premultipliedAlpha: false }, false);
    } catch (_) { return null; }
    if (!engine || !engine._gl) return null;
    canvas.style.imageRendering = "pixelated";
    const scene = new B.Scene(engine);
    scene.useRightHandedSystem = true;             // world.js's maths are right-handed (OpenGL)
    scene.skipPointerMovePicking = true;
    scene.autoClear = true;
    scene.clearColor = new B.Color4(0.05, 0.06, 0.12, 1);
    scene.ambientColor = new B.Color3(1, 1, 1);
    scene.fogMode = B.Scene.FOGMODE_LINEAR;
    const camera = new B.FreeCamera("cam", new B.Vector3(0, 8, 14), scene);
    camera.minZ = 0.3; camera.maxZ = 400; camera.inputs.clear();

    // ---------------------------------------------------------------- lights
    const sun = new B.DirectionalLight("sun", new B.Vector3(-0.5, -1, -0.3), scene);
    sun.position = new B.Vector3(15, 30, 10);
    sun.shadowMinZ = 1; sun.shadowMaxZ = 80;
    const hemi = new B.HemisphericLight("hemi", new B.Vector3(0, 1, 0), scene);
    const points = [];
    for (let i = 0; i < LIGHTS; i++) {
      const p = new B.PointLight("lamp" + i, B.Vector3.Zero(), scene);
      p.intensity = 0; p.range = 4; points.push(p);
    }
    let shadows = null;
    function makeShadows(size) {
      if (shadows) shadows.dispose();
      shadows = size ? new B.ShadowGenerator(size, sun) : null;
      if (shadows) {
        shadows.bias = 0.0015; shadows.normalBias = 0.02;
        shadows.usePercentageCloserFiltering = false; shadows.useExponentialShadowMap = false;
        shadows.usePoissonSampling = false;          // hard edges: they read as pixel art
        shadows.darkness = 0.35;
        for (const m of casters) shadows.addShadowCaster(m, false);
      }
    }

    // ---------------------------------------------------------------- materials
    const celMat = (name) => {
      const m = new B.CellMaterial(name, scene);
      m.diffuseColor = new B.Color3(1, 1, 1);
      m.computeHighLevel = true; m.maxSimultaneousLights = LIGHTS + 2;
      return m;
    };
    const unlitMat = (name) => {
      const m = new B.StandardMaterial(name, scene);
      m.disableLighting = true; m.emissiveColor = new B.Color3(1, 1, 1); m.diffuseColor = new B.Color3(0, 0, 0);
      m.specularColor = new B.Color3(0, 0, 0);
      return m;
    };
    const lit = celMat("loki-cel");
    const glowing = unlitMat("loki-glow");
    const clearMat = celMat("loki-clear"); clearMat.alpha = 0.55;
    const inkMat = (thin) => {
      const m = new B.ShaderMaterial("loki-ink" + (thin ? "-t" : ""), scene, { vertexSource: INK_VS, fragmentSource: INK_FS },
        { attributes: thin ? ["position"] : ["position", "center"],
          uniforms: ["world", "viewProjection", "eye", "OL", "ink"], defines: thin ? ["#define THIN"] : [] });
      m.backFaceCulling = true;
      m.sideOrientation = B.Material.ClockWiseSideOrientation;   // flipped vs. the solids: draw the BACK faces (the hull)
      return m;
    };
    const ink = inkMat(false), inkThin = inkMat(true);
    const casters = [];

    // ---------------------------------------------------------------- the baked island
    function meshFromArrays(name, p, n, c, mat) {
      const m = new B.Mesh(name, scene);
      const vd = new B.VertexData();
      vd.positions = p; vd.normals = n;
      if (c) vd.colors = c;
      const idx = new Uint32Array(p.length / 3);
      for (let i = 0; i < idx.length; i++) idx[i] = i;
      vd.indices = idx;
      vd.applyToMesh(m, false);
      m.material = mat;
      if (c) m.useVertexColors = true;
      m.isPickable = false; m.alwaysSelectAsActiveMesh = true;
      return m;
    }
    // split the baked solids into lit and glowing parts (by emission), colour -> rgba
    function bake(solid, name) {
      const L = { p: [], n: [], c: [] }, G = { p: [], n: [], c: [] };
      const verts = solid.p.length / 3;
      for (let v = 0; v < verts; v += 3) {
        const e = solid.x[v * 4], dst = e >= EMISSIVE ? G : L, k = e >= EMISSIVE ? 0.55 + e * 0.6 : 1;
        for (let j = 0; j < 3; j++) {
          const i = v + j;
          dst.p.push(solid.p[i * 3], solid.p[i * 3 + 1], solid.p[i * 3 + 2]);
          dst.n.push(solid.n[i * 3], solid.n[i * 3 + 1], solid.n[i * 3 + 2]);
          dst.c.push(Math.min(1, solid.c[i * 3] * k), Math.min(1, solid.c[i * 3 + 1] * k), Math.min(1, solid.c[i * 3 + 2] * k), 1);
        }
      }
      const out = [];
      if (L.p.length) { const m = meshFromArrays(name, new Float32Array(L.p), new Float32Array(L.n), new Float32Array(L.c), lit); m.receiveShadows = true; out.push(m); }
      if (G.p.length) out.push(meshFromArrays(name + "-glow", new Float32Array(G.p), new Float32Array(G.n), new Float32Array(G.c), glowing));
      return out;
    }
    function inkMesh(inkBuf, name) {
      if (!inkBuf.p.length) return null;
      const m = meshFromArrays(name, inkBuf.p, inkBuf.p, null, ink);   // normals unused
      m.setVerticesData("center", inkBuf.n, false, 3);                     // world.js stores the object centre there
      return m;
    }
    const st = ctx.staticScene();
    const land = bake(st.land.solid, "land");
    land.forEach((m) => casters.push(m));
    const landInk = inkMesh(st.land.ink, "land-ink");
    const skyRoot = new B.TransformNode("sky-batch", scene);
    const skyParts = bake(st.sky.solid, "sky");
    skyParts.forEach((m) => { m.parent = skyRoot; });
    const skyInk = inkMesh(st.sky.ink, "sky-ink");
    if (skyInk) skyInk.parent = skyRoot;

    // ---------------------------------------------------------------- sky dome
    const skyMat = new B.ShaderMaterial("loki-sky", scene, { vertexSource: SKY_VS, fragmentSource: SKY_FS },
      { attributes: ["position"], uniforms: ["world", "viewProjection", "zenith", "horizon", "glow", "deep", "sunDir", "sunCol", "stars", "T"] });
    skyMat.backFaceCulling = false; skyMat.disableDepthWrite = true;
    const dome = B.MeshBuilder.CreateSphere("dome", { diameter: 300, segments: 16 }, scene);
    dome.material = skyMat; dome.infiniteDistance = true; dome.isPickable = false; dome.renderingGroupId = 0;
    dome.applyFog = false;

    // ---------------------------------------------------------------- water
    const waters = [];
    if (ctx.noise) {
      const sh = waterShaders(ctx.noise);
      for (const w of ctx.water) {
        const src = ctx.meshes[w.mesh];
        const mat = new B.ShaderMaterial("loki-water-" + w.id, scene, { vertexSource: sh.vs, fragmentSource: sh.fs },
          { attributes: ["position"], needAlphaBlending: true,
            uniforms: ["world", "viewProjection", "T", "shape", "rect", "obs0", "obs1", "flow", "beer", "eyePos", "sunDir", "sunCol",
              "zenith", "horizon", "dayK", "shallow", "deep", "foamCol", "rip"] });
        mat.backFaceCulling = false; mat.disableDepthWrite = true; mat.alphaMode = B.Engine.ALPHA_COMBINE;
        const mesh = meshFromArrays("water-" + w.id, new Float32Array(src.p), new Float32Array(src.n), null, mat);
        mesh.position.set(w.pos[0], w.pos[1], w.pos[2]); mesh.rotation.y = w.ry; mesh.scaling.set(w.s[0], w.s[1], w.s[2]);
        mesh.alwaysSelectAsActiveMesh = true;
        mat.setVector4("shape", new B.Vector4(...w.shape)); mat.setVector4("rect", new B.Vector4(...w.rect));
        mat.setVector4("obs0", new B.Vector4(...(w.obs[0] || [0, 0, 0, 0]))); mat.setVector4("obs1", new B.Vector4(...(w.obs[1] || [0, 0, 0, 0])));
        mat.setVector2("flow", new B.Vector2(w.flow[0], w.flow[1])); mat.setFloat("beer", w.beer);
        waters.push({ w, mesh, mat });
      }
    }

    // ---------------------------------------------------------------- blob shadows
    const shadowMat = (dyn) => {
      const m = new B.ShaderMaterial("loki-shadow" + (dyn ? "-d" : ""), scene, { vertexSource: SHADOW_VS, fragmentSource: SHADOW_FS },
        { attributes: dyn ? ["position", "spos"] : ["position", "sh"], uniforms: ["viewProjection", "SK"], needAlphaBlending: true,
          defines: dyn ? ["#define DYN"] : [] });
      m.backFaceCulling = false; m.disableDepthWrite = true; m.alphaMode = B.Engine.ALPHA_COMBINE;
      m.setVector3("SK", new B.Vector3(0.02, 0.03, 0.12));
      return m;
    };
    if (st.shadows && st.shadows.p.length) {
      const sm = meshFromArrays("shadows", st.shadows.p, st.shadows.p, null, shadowMat(false));
      sm.setVerticesData("sh", st.shadows.n, false, 3);
    }
    const SHADOWS = 160, spos = new Float32Array(SHADOWS * 4);
    const blob = B.MeshBuilder.CreatePlane("blob", { size: 2 }, scene);
    blob.material = shadowMat(true); blob.alwaysSelectAsActiveMesh = true; blob.isPickable = false;
    blob.thinInstanceSetBuffer("spos", spos, 4, false);
    blob.thinInstanceCount = 0;

    // ---------------------------------------------------------------- things that move (thin instances)
    function pool(shape, mat, cap, withInk) {
      const src = ctx.meshes[shape];
      const matrices = new Float32Array(cap * 16), colors = new Float32Array(cap * 4);
      const m = meshFromArrays("dyn-" + shape + "-" + mat.name, new Float32Array(src.p), new Float32Array(src.n), null, mat);
      m.thinInstanceSetBuffer("matrix", matrices, 16, false);   // Babylon keeps THIS array: write into it
      m.thinInstanceSetBuffer("color", colors, 4, false);
      m.thinInstanceCount = 0;
      m.receiveShadows = mat === lit;
      let inkM = null, inkMatrices = null;
      if (withInk) {
        inkMatrices = new Float32Array(cap * 16);
        inkM = meshFromArrays("ink-" + shape, new Float32Array(src.p), new Float32Array(src.n), null, inkThin);
        inkM.thinInstanceSetBuffer("matrix", inkMatrices, 16, false);
        inkM.thinInstanceCount = 0;
      }
      return { m, inkM, cap, mat: matrices, col: colors, inkMat: inkMatrices, n: 0, ni: 0 };
    }
    const pools = { lit: {}, glow: {}, clear: {} };
    for (const s of SHAPES) {
      pools.lit[s] = pool(s, lit, CAP[s], true);
      pools.glow[s] = pool(s, glowing, Math.ceil(CAP[s] / 3), false);
      pools.clear[s] = pool(s, clearMat, 40, false);
      casters.push(pools.lit[s].m);
    }

    // halos: one quad, thin-instanced, billboarded in the shader, additive
    const glowMat = new B.ShaderMaterial("loki-halo", scene, { vertexSource: GLOW_VS, fragmentSource: GLOW_FS },
      { attributes: ["position", "gpos", "gcol"], uniforms: ["viewProjection", "camR", "camU"], needAlphaBlending: true });
    glowMat.backFaceCulling = false; glowMat.disableDepthWrite = true; glowMat.alphaMode = B.Engine.ALPHA_ADD;
    const quad = B.MeshBuilder.CreatePlane("halo", { size: 2 }, scene);
    quad.material = glowMat; quad.alwaysSelectAsActiveMesh = true; quad.isPickable = false;
    const HALOS = 220, gpos = new Float32Array(HALOS * 4), gcol = new Float32Array(HALOS * 4);
    quad.thinInstanceSetBuffer("gpos", gpos, 4, false);
    quad.thinInstanceSetBuffer("gcol", gcol, 4, false);
    quad.thinInstanceCount = 0;

    // ---------------------------------------------------------------- the pixel pass
    let pixelLevels = 32, rw = 1, rh = 1;
    const pixelPass = new B.PostProcess("loki-pixel", "lokiPixel", ["R", "Q"], null, 1.0, camera, B.Texture.NEAREST_SAMPLINGMODE, engine);
    B.Effect.ShadersStore.lokiPixelFragmentShader = PIXEL_FS;
    pixelPass.onApply = (effect) => { effect.setFloat2("R", rw, rh); effect.setFloat("Q", pixelLevels); };

    let quality = "high";
    function setQuality(q) {
      // Real shadow maps are not used: blob shadows read better in pixel art and cost almost
      // nothing. Quality steps are taken by world.js as coarser world pixels instead.
      quality = q;
      makeShadows(0);
    }
    setQuality("high");

    // ---------------------------------------------------------------- per frame
    const c3 = (a) => new B.Color3(a[0], a[1], a[2]);
    const v3 = (a) => new B.Vector3(a[0], a[1], a[2]);
    function fill(p, o, e) {
      const isGlow = e >= EMISSIVE;
      if (p.n >= p.cap) return;
      // world.js's trs layout (column-major, translation in 12-14), the same as Babylon's
      const c = Math.cos(o.ry || 0), s = Math.sin(o.ry || 0), sx = o.s[0], sy = o.s[1], sz = o.s[2], k = p.n * 16;
      const m = p.mat;
      m[k] = c * sx; m[k + 1] = 0; m[k + 2] = -s * sx; m[k + 3] = 0;
      m[k + 4] = 0; m[k + 5] = sy; m[k + 6] = 0; m[k + 7] = 0;
      m[k + 8] = s * sz; m[k + 9] = 0; m[k + 10] = c * sz; m[k + 11] = 0;
      m[k + 12] = o.pos[0]; m[k + 13] = o.pos[1]; m[k + 14] = o.pos[2]; m[k + 15] = 1;
      const g = isGlow ? 0.55 + e * 0.6 : 1 + (e || 0) * 0.5;
      p.col[p.n * 4] = Math.min(1, o.color[0] * g); p.col[p.n * 4 + 1] = Math.min(1, o.color[1] * g);
      p.col[p.n * 4 + 2] = Math.min(1, o.color[2] * g); p.col[p.n * 4 + 3] = o.a == null ? 1 : o.a;
      if (p.inkM && o.line !== false && p.ni < p.cap) { p.inkMat.set(m.subarray(k, k + 16), p.ni * 16); p.ni++; }
      p.n++;
    }
    function flush(p) {
      p.m.thinInstanceCount = p.n;
      if (p.n) { p.m.thinInstanceBufferUpdated("matrix"); p.m.thinInstanceBufferUpdated("color"); }
      p.m.isVisible = p.n > 0;
      if (p.inkM) { p.inkM.thinInstanceCount = p.ni; if (p.ni) p.inkM.thinInstanceBufferUpdated("matrix"); p.inkM.isVisible = p.ni > 0; }
    }

    let size = [0, 0, 0];
    function render(f) {
      const { w, h } = f;
      const pixel = Math.max(1, f.pixel || 3), dpr = f.dpr || 1;
      if (size[0] !== w || size[1] !== h || size[2] !== pixel) {
        size = [w, h, pixel];
        engine.setHardwareScalingLevel(pixel / dpr);       // one world pixel = `pixel` device pixels
        engine.resize();
      }
      rw = engine.getRenderWidth(); rh = engine.getRenderHeight();
      pixelLevels = f.levels || 32;
      const P = f.P, day = P.dayK;

      camera.fov = f.fov;
      camera.position.set(f.eye[0], f.eye[1], f.eye[2]);
      camera.setTarget(v3(f.target));
      scene.fogColor = c3(P.fog); scene.fogStart = f.fogr ? f.fogr[0] : 18; scene.fogEnd = (f.fogr ? f.fogr[0] + f.fogr[1] : 34) + 30;

      // sky + lights, from the same palette as the classic renderer
      skyMat.setVector3("zenith", v3(P.zenith)); skyMat.setVector3("horizon", v3(P.horizon));
      skyMat.setVector3("glow", v3(P.glow)); skyMat.setVector3("deep", v3(P.deep));
      skyMat.setVector3("sunDir", v3(f.sunDir)); skyMat.setVector3("sunCol", v3(P.sunSky));
      skyMat.setFloat("stars", P.stars); skyMat.setFloat("T", f.t % 600);
      sun.direction = new B.Vector3(-f.sunDir[0], -f.sunDir[1], -f.sunDir[2]);
      sun.position = new B.Vector3(f.sunDir[0] * 35, f.sunDir[1] * 35, f.sunDir[2] * 35);
      sun.diffuse = c3(P.sunCol); sun.intensity = 0.85 + 0.6 * day; sun.specular = new B.Color3(0, 0, 0);
      hemi.diffuse = c3(P.skyAmb); hemi.groundColor = c3(P.gndAmb); hemi.intensity = 0.42 + 0.18 * day; hemi.specular = new B.Color3(0, 0, 0);
      const lamps = f.lights || [];
      for (let i = 0; i < LIGHTS; i++) {
        const l = lamps[i], p = points[i];
        if (!l) { p.intensity = 0; continue; }
        p.position.set(l.pos[0], l.pos[1], l.pos[2]); p.diffuse = c3(l.color); p.specular = new B.Color3(0, 0, 0);
        p.range = l.radius * 1.3; p.intensity = 1.6 * P.lamps;
      }
      skyRoot.rotation.y = f.skyRot || 0;

      // ink: about one world pixel thick at any distance
      const OL = 1.1 * 2 * Math.tan(f.fov / 2) / Math.max(1, rh);
      for (const m of [ink, inkThin]) {
        m.setVector3("eye", v3(f.eye)); m.setFloat("OL", OL);
        m.setColor3("ink", new B.Color3(0.04, 0.04, 0.11));
      }

      // water
      const nowS = performance.now() / 1000;
      for (const wb of waters) {
        const m = wb.mat;
        m.setFloat("T", f.t % 600); m.setVector3("eyePos", v3(f.eye)); m.setVector3("sunDir", v3(f.sunDir));
        m.setVector3("sunCol", v3(P.sunCol)); m.setVector3("zenith", v3(P.zenith)); m.setVector3("horizon", v3(P.horizon));
        m.setFloat("dayK", day);
        m.setVector3("shallow", v3(f.waterLook.shallow)); m.setVector3("deep", v3(f.waterLook.deep)); m.setVector3("foamCol", v3(f.waterLook.foam));
        const rip = new Array(16).fill(0);
        let k = 0;
        for (const r of f.ripples || []) if (r.body === wb.w.id && k < 4) { rip[k * 4] = r.x; rip[k * 4 + 1] = r.z; rip[k * 4 + 2] = nowS - r.t0; rip[k * 4 + 3] = r.k; k++; }
        m.setArray4("rip", rip);
      }

      // what moves
      for (const group of Object.values(pools)) for (const s of SHAPES) { group[s].n = 0; group[s].ni = 0; }
      for (const o of f.L.solids) {
        const e = o.e || 0, grp = e >= EMISSIVE ? pools.glow : pools.lit;
        if (grp[o.mesh]) fill(grp[o.mesh], o, e);
      }
      for (const o of f.L.clear) if (pools.clear[o.mesh]) fill(pools.clear[o.mesh], o, 0);
      for (const group of Object.values(pools)) for (const s of SHAPES) flush(group[s]);

      // blob shadows under what moves
      let ns = 0;
      for (const sh of f.L.shadows || []) {
        if (ns >= SHADOWS) break;
        spos.set([sh.x, sh.z, sh.r, Math.min(1, sh.a == null ? 0.5 : sh.a)], ns * 4); ns++;
      }
      blob.thinInstanceCount = ns;
      if (ns) blob.thinInstanceBufferUpdated("spos");

      // halos (glows + puffs)
      const list = f.L.glows.concat(f.L.static_glows || []);
      let n = 0;
      for (const g of list) {
        if (n >= HALOS) break;
        gpos.set([g.pos[0], g.pos[1], g.pos[2], g.r * 1.15], n * 4);
        gcol.set([g.color[0], g.color[1], g.color[2], Math.min(1, g.a == null ? 1 : g.a) * 0.45], n * 4);
        n++;
      }
      for (const g of f.L.puffs || []) {
        if (n >= HALOS) break;
        gpos.set([g.pos[0], g.pos[1], g.pos[2], g.r * 1.4], n * 4);
        gcol.set([g.color[0] * 0.5, g.color[1] * 0.5, g.color[2] * 0.5, Math.min(1, g.a == null ? 1 : g.a) * 0.4], n * 4);
        n++;
      }
      quad.thinInstanceCount = n;
      if (n) { quad.thinInstanceBufferUpdated("gpos"); quad.thinInstanceBufferUpdated("gcol"); }
      const view = camera.getViewMatrix();
      glowMat.setVector3("camR", new B.Vector3(view.m[0], view.m[4], view.m[8]));
      glowMat.setVector3("camU", new B.Vector3(view.m[1], view.m[5], view.m[9]));

      scene.render();
      return engine._drawCalls ? engine._drawCalls.current : 0;
    }

    canvas.addEventListener("webglcontextlost", (e) => e.preventDefault());
    return { render, setQuality, get quality() { return quality; }, renderer: { getContext: () => engine._gl }, kind: "babylon", engine, scene };
  }

  window.WorldBabylon = { create };
})();
