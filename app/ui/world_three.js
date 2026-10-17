// LOKI World - the three.js renderer (three.js r186, MIT, vendored in ui/vendor/three).
//
// world.js keeps the simulation: who is where, walking, working, teams, labels, picking.
// Every frame it builds one description of the scene (static island baked once, plus the
// list of things that move) and hands it here. This module turns it into a real 3D scene:
//
//   * physically based materials (MeshStandardMaterial) with per-vertex colour, emission and
//     the plaza's checker, injected into three's own shader so it keeps all of three's lighting;
//   * a sun/moon directional light with soft shadow maps, a sky/ground hemisphere fill, and the
//     station lamps as real point lights (the important ones first);
//   * everything that moves drawn with InstancedMesh - one draw per shape, however many agents;
//   * the stylised water (shore foam, caustics, fresnel, ripples, the waterfall) as a ShaderMaterial
//     using the same MIT webgl-noise as before;
//   * a gradient sky dome with stars and a soft aurora at night;
//   * post-processing: HDR render, Unreal bloom on lamps/beacons/crystals, ACES tone mapping,
//     sRGB output, MSAA.
//
// Quality: "high" (2048 shadows, bloom), "medium" (1024 shadows, bloom), "low" (no shadows, no
// bloom). world.js lowers it when frames run late and raises it again when they are on time.
// If WebGL 2 is missing, create() returns null and world.js keeps its classic renderer.
import * as THREE from "./vendor/three/three.module.js";
import { EffectComposer } from "./vendor/three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "./vendor/three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "./vendor/three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "./vendor/three/addons/postprocessing/OutputPass.js";

const SHAPES = ["box", "cyl", "cyl6", "cone", "pyr", "sph", "sph4"];
const CAP = { box: 900, cyl: 120, cyl6: 160, cone: 60, pyr: 120, sph: 160, sph4: 120 };
const LIGHTS = 8;
const lin = (c) => new THREE.Color().setRGB(c[0], c[1], c[2], THREE.SRGBColorSpace);

function geometryFor(src) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(src.p, 3));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(src.n, 3));
  return g;
}

// MeshStandardMaterial plus LOKI's extras: x = (emission, checker, highlight, alpha), from a
// vertex attribute (baked scene) or an instanced attribute (things that move).
function lokiMaterial(opts) {
  const m = new THREE.MeshStandardMaterial(Object.assign({ roughness: 0.78, metalness: 0.0, vertexColors: !opts.instanced }, opts.base || {}));
  m.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nattribute vec4 lokiX;\nvarying vec4 vLokiX;\nvarying vec3 vLokiW;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvLokiX = lokiX;")
      .replace("#include <worldpos_vertex>", "#include <worldpos_vertex>\nvec4 lokiWp = vec4(transformed, 1.0);\n" +
        "#ifdef USE_INSTANCING\nlokiWp = instanceMatrix * lokiWp;\n#endif\nvLokiW = (modelMatrix * lokiWp).xyz;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying vec4 vLokiX;\nvarying vec3 vLokiW;")
      .replace("#include <color_fragment>", "#include <color_fragment>\n" +
        "if (vLokiX.y > 0.0) { float ch = mod(floor(vLokiW.x * vLokiX.y) + floor(vLokiW.z * vLokiX.y), 2.0); diffuseColor.rgb *= 0.92 + 0.08 * ch; }\n" +
        (opts.transparent ? "diffuseColor.a *= vLokiX.w;\n" : ""))
      .replace("#include <emissivemap_fragment>", "#include <emissivemap_fragment>\ntotalEmissiveRadiance += diffuseColor.rgb * vLokiX.x * 2.2;")
      .replace("#include <roughnessmap_fragment>", "#include <roughnessmap_fragment>\nroughnessFactor = clamp(roughnessFactor - vLokiX.z * 0.9, 0.08, 1.0);");
  };
  m.customProgramCacheKey = () => "loki-" + (opts.instanced ? "i" : "v") + (opts.transparent ? "t" : "o");
  if (opts.transparent) { m.transparent = true; m.depthWrite = false; }
  return m;
}

function bakedMesh(baked, castShadow) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(baked.p, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(baked.n, 3));
  const c = new Float32Array(baked.c.length);
  const tmp = new THREE.Color();
  for (let i = 0; i < c.length; i += 3) { tmp.setRGB(baked.c[i], baked.c[i + 1], baked.c[i + 2], THREE.SRGBColorSpace); c[i] = tmp.r; c[i + 1] = tmp.g; c[i + 2] = tmp.b; }
  g.setAttribute("color", new THREE.BufferAttribute(c, 3));
  const x = new Float32Array(baked.x.length);
  for (let i = 0; i < x.length; i += 4) { x[i] = baked.x[i]; x[i + 1] = baked.x[i + 1]; x[i + 2] = baked.x[i + 2]; x[i + 3] = 1; }
  g.setAttribute("lokiX", new THREE.BufferAttribute(x, 4));
  const mesh = new THREE.Mesh(g, lokiMaterial({}));
  mesh.castShadow = castShadow; mesh.receiveShadow = true;
  mesh.matrixAutoUpdate = false;
  return mesh;
}

function instancedPool(shape, src, transparent) {
  const g = geometryFor(src);
  const cap = transparent ? 40 : CAP[shape];
  g.setAttribute("lokiX", new THREE.InstancedBufferAttribute(new Float32Array(cap * 4), 4));
  const mesh = new THREE.InstancedMesh(g, lokiMaterial({ instanced: true, transparent, base: { side: THREE.DoubleSide } }), cap);
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(cap * 3), 3);
  mesh.castShadow = !transparent; mesh.receiveShadow = true;
  mesh.frustumCulled = false;
  mesh.count = 0;
  return mesh;
}

function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.25, "rgba(255,255,255,0.55)");
  r.addColorStop(0.6, "rgba(255,255,255,0.12)"); r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r; g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function spritePool(n, additive, tex) {
  const group = new THREE.Group();
  const list = [];
  for (let i = 0; i < n; i++) {
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false,
      blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending, toneMapped: !additive });
    const s = new THREE.Sprite(mat);
    s.visible = false;
    group.add(s); list.push(s);
  }
  return { group, list };
}

const SKY_VS = "varying vec3 vDir; void main(){ vDir = normalize((modelMatrix * vec4(position, 0.0)).xyz);" +
  " vec4 p = projectionMatrix * viewMatrix * vec4((modelMatrix * vec4(position, 1.0)).xyz, 1.0); gl_Position = p.xyww; }";
const SKY_FS = "varying vec3 vDir; uniform vec3 zenith; uniform vec3 horizon; uniform vec3 glow; uniform vec3 deep;" +
  " uniform vec3 sunDir; uniform vec3 sunCol; uniform float stars; uniform float T;" +
  " void main(){ vec3 d = normalize(vDir); float e = d.y;" +
  " vec3 col = e > 0.0 ? mix(horizon, zenith, pow(clamp(e * 1.5, 0.0, 1.0), 0.7)) : mix(horizon, deep, pow(clamp(-e * 2.0, 0.0, 1.0), 0.6));" +
  " col += glow * exp(-abs(e) * 8.0);" +
  " float s = max(dot(d, sunDir), 0.0); col += sunCol * (pow(s, 900.0) * 6.0 + pow(s, 60.0) * 0.35 + pow(s, 8.0) * 0.06);" +
  " vec3 q = floor(d * 220.0); float h = fract(sin(dot(q, vec3(12.9898, 78.233, 37.719))) * 43758.5453);" +
  " float tw = 0.6 + 0.4 * sin(T * 2.0 + h * 40.0);" +
  " col += vec3(0.9, 0.95, 1.0) * step(0.9965, h) * stars * tw * smoothstep(-0.1, 0.25, e) * 1.6;" +
  " float band = sin(d.x * 3.0 + d.z * 2.0 + T * 0.05) * 0.5 + 0.5;" +
  " col += vec3(0.08, 0.55, 0.45) * stars * 0.45 * smoothstep(0.55, 0.95, band) * smoothstep(0.2, 0.55, e) * (1.0 - smoothstep(0.6, 0.95, e));" +
  " gl_FragColor = vec4(col, 1.0); }";

// The water: the same maths as world.js's WATER_FS (shore distance, Beer-Lambert depth, foam,
// caustics, fresnel, ripples, the falling sheet), on three's matrices, output in linear light.
function waterMaterial(noise) {
  const fs = "varying vec3 wp; varying vec2 lp;" +
    "uniform float T; uniform vec4 shape; uniform vec4 rect; uniform vec4 obs0; uniform vec4 obs1; uniform vec2 flow; uniform float beer;" +
    "uniform vec3 eyePos; uniform vec3 sunDir; uniform vec3 sunCol; uniform vec3 zenith; uniform vec3 horizon; uniform float dayK;" +
    "uniform vec3 LP[8]; uniform vec4 LC[8]; uniform vec3 shallow; uniform vec3 deep; uniform vec3 foamCol; uniform vec4 rip[4];\n" +
    noise + "\n" +
    "float boxd(vec2 p, vec4 b){ vec2 d = abs(p - b.xy) - b.zw; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }" +
    "float shore(vec2 p){ float d; if (shape.w < 0.5) d = shape.z - length(p - shape.xy);" +
    " else { vec2 l = p - shape.xy; d = rect.z - abs(dot(l, vec2(-rect.y, rect.x))); }" +
    " if (obs0.z > 0.0) d = min(d, boxd(p, obs0)); if (obs1.z > 0.0) d = min(d, boxd(p, obs1)); return d; }" +
    "float hgt(vec2 p){ return snoise(p * 0.9 - flow * T + vec2(T * 0.08, T * 0.05)) * 0.6 + snoise(p * 1.9 - flow * T * 1.4 + vec2(-T * 0.09, T * 0.12)) * 0.28; }" +
    "void main(){" +
    " if (shape.w > 1.5) {" +
    "  float n1 = snoise(vec2(lp.x * 9.0, wp.y * 0.9 + T * 2.6)); float n2 = snoise(vec2(lp.x * 17.0 + 3.0, wp.y * 1.7 + T * 4.1));" +
    "  vec3 c = mix(deep, shallow, 0.6 + 0.2 * n1); c = mix(c, foamCol, smoothstep(0.35, 0.5, n1 * 0.6 + n2 * 0.4)); c = mix(c, foamCol, smoothstep(0.4, 0.46, lp.y));" +
    "  float a = (1.0 - smoothstep(0.85, 0.95, abs(lp.x) * 2.0 + n2 * 0.06)) * 0.9 * smoothstep(-0.5, -0.25, lp.y);" +
    "  gl_FragColor = vec4(c * (1.0 + 0.4 * dayK), a); return; }" +
    " vec2 q = wp.xz; float s = shore(q); if (s < -0.02) discard;" +
    " float h0 = hgt(q); float e = 0.07; vec2 g = vec2(hgt(q + vec2(e, 0.0)) - h0, hgt(q + vec2(0.0, e)) - h0) / e;" +
    " float ring = 0.0;" +
    " for (int i = 0; i < 4; i++) { if (rip[i].w > 0.0) { vec2 dv = q - rip[i].xy; float d = length(dv); float r = rip[i].z * 0.85;" +
    "  float k = exp(-abs(d - r) * 16.0) * rip[i].w * max(0.0, 1.0 - rip[i].z / 2.2); g += dv / max(d, 0.001) * k * 2.2; ring += k; } }" +
    " vec3 N = normalize(vec3(-g.x * 0.2, 1.0, -g.y * 0.2));" +
    " float depth = 1.0 - exp(-max(s, 0.0) * beer); vec3 col = mix(shallow, deep, depth);" +
    " vec2 F = cellular(q * 1.35 + g * 0.15 + vec2(T * 0.04, -T * 0.03));" +
    " col += vec3(0.5, 0.9, 1.0) * smoothstep(0.12, 0.05, F.y - F.x) * (1.0 - depth * 0.85) * (0.12 + 0.2 * dayK);" +
    " vec3 V = normalize(eyePos - wp); vec3 R = reflect(-V, N);" +
    " float fr = 0.04 + 0.96 * pow(1.0 - max(dot(N, V), 0.0), 5.0);" +
    " col = mix(col, mix(horizon, zenith, clamp(R.y * 1.4, 0.0, 1.0)), clamp(fr, 0.0, 0.75));" +
    " float sp = max(dot(R, sunDir), 0.0); col += sunCol * (pow(sp, 400.0) * 3.0 + pow(sp, 40.0) * 0.15);" +
    " for (int i = 0; i < 8; i++) { vec3 L = LP[i] - wp; float dl = length(L);" +
    "  col += LC[i].rgb * pow(max(dot(R, L / max(dl, 0.001)), 0.0), 18.0) * clamp(1.0 - dl / (LC[i].w * 2.4), 0.0, 1.0) * 1.6; }" +
    " float wob = snoise(q * 3.1 + vec2(T * 0.3, -T * 0.25)) * 0.05 + snoise(q * 7.0 - vec2(T * 0.5)) * 0.025; float sd = s + wob;" +
    " float foam = smoothstep(0.13, 0.09, sd) + smoothstep(0.025, 0.0, abs(sd - 0.24 - 0.035 * sin(T * 1.5))) * 0.7 + smoothstep(0.3, 0.6, ring) * 0.85;" +
    " foam = max(foam, smoothstep(0.58, 0.68, h0) * 0.6 * step(0.05, length(flow))); foam = clamp(foam, 0.0, 1.0);" +
    " col = mix(col, foamCol, foam);" +
    " gl_FragColor = vec4(col, max(mix(0.6, 0.93, depth), foam)); }";
  const vs = "uniform float T; uniform vec4 shape; varying vec3 wp; varying vec2 lp;" +
    "void main(){ vec4 w = modelMatrix * vec4(position, 1.0); lp = shape.w > 1.5 ? position.xy : position.xz;" +
    " if (shape.w < 1.5) w.y += (sin(w.x * 2.3 + T * 1.6) + sin(w.z * 2.9 - T * 1.3)) * 0.006;" +
    " wp = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }";
  const v3 = () => new THREE.Vector3(), v4 = () => new THREE.Vector4();
  return new THREE.ShaderMaterial({
    vertexShader: vs, fragmentShader: fs, transparent: true, depthWrite: false, side: THREE.DoubleSide,
    uniforms: {
      T: { value: 0 }, shape: { value: v4() }, rect: { value: v4() }, obs0: { value: v4() }, obs1: { value: v4() },
      flow: { value: new THREE.Vector2() }, beer: { value: 1 }, eyePos: { value: v3() }, sunDir: { value: v3() }, sunCol: { value: v3() },
      zenith: { value: v3() }, horizon: { value: v3() }, dayK: { value: 0 },
      LP: { value: Array.from({ length: 8 }, v3) }, LC: { value: Array.from({ length: 8 }, v4) },
      shallow: { value: v3() }, deep: { value: v3() }, foamCol: { value: v3() }, rip: { value: Array.from({ length: 4 }, v4) },
    },
  });
}

function create(canvas, ctx) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, powerPreference: "high-performance" });
  } catch (_) { return null; }
  if (!renderer.capabilities.isWebGL2) { renderer.dispose(); return null; }
  renderer.toneMapping = THREE.NoToneMapping;       // the OutputPass does ACES + sRGB
  renderer.shadowMap.enabled = true;
  renderer.info.autoReset = false;
  renderer.shadowMap.type = THREE.PCFShadowMap;   // soft via shadow.radius

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.5, 120);

  // sky dome
  const skyMat = new THREE.ShaderMaterial({ vertexShader: SKY_VS, fragmentShader: SKY_FS, side: THREE.BackSide, depthWrite: false,
    uniforms: { zenith: { value: new THREE.Vector3() }, horizon: { value: new THREE.Vector3() }, glow: { value: new THREE.Vector3() },
      deep: { value: new THREE.Vector3() }, sunDir: { value: new THREE.Vector3() }, sunCol: { value: new THREE.Vector3() },
      stars: { value: 0 }, T: { value: 0 } } });
  const sky = new THREE.Mesh(new THREE.SphereGeometry(100, 32, 16), skyMat);
  sky.renderOrder = -10; sky.frustumCulled = false;
  scene.add(sky);

  // lights
  const sun = new THREE.DirectionalLight(0xffffff, 2.0);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -13, right: 13, top: 13, bottom: -13, near: 1, far: 60 });
  sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.03; sun.shadow.radius = 4;
  scene.add(sun, sun.target);
  const hemi = new THREE.HemisphereLight(0x8899cc, 0x332833, 0.9);
  scene.add(hemi);
  const points = [];
  for (let i = 0; i < LIGHTS; i++) { const l = new THREE.PointLight(0xffffff, 0, 4, 1.6); scene.add(l); points.push(l); }

  // the baked island and the turning sky batch
  const st = ctx.staticScene();
  const land = bakedMesh(st.land.solid, true);
  const skyBatch = bakedMesh(st.sky.solid, false);
  skyBatch.matrixAutoUpdate = true;
  scene.add(land, skyBatch);

  // water bodies
  const noise = ctx.noise || "";
  const waters = noise ? ctx.water.map((w) => {
    const mat = waterMaterial(noise);
    const mesh = new THREE.Mesh(geometryFor(ctx.meshes[w.mesh]), mat);
    mesh.position.set(w.pos[0], w.pos[1], w.pos[2]); mesh.rotation.y = w.ry; mesh.scale.set(w.s[0], w.s[1], w.s[2]);
    mesh.renderOrder = 2;
    mat.uniforms.shape.value.fromArray(w.shape); mat.uniforms.rect.value.fromArray(w.rect);
    mat.uniforms.obs0.value.fromArray(w.obs[0] || [0, 0, 0, 0]); mat.uniforms.obs1.value.fromArray(w.obs[1] || [0, 0, 0, 0]);
    mat.uniforms.flow.value.fromArray(w.flow); mat.uniforms.beer.value = w.beer;
    scene.add(mesh);
    return { w, mesh, mat };
  }) : [];

  // things that move
  const pools = {}, clearPools = {};
  for (const s of SHAPES) {
    pools[s] = instancedPool(s, ctx.meshes[s], false); scene.add(pools[s]);
    clearPools[s] = instancedPool(s, ctx.meshes[s], true); scene.add(clearPools[s]);
  }
  const glowTex = glowTexture();
  const glows = spritePool(140, true, glowTex), puffs = spritePool(80, false, glowTex);
  scene.add(glows.group, puffs.group);

  // post-processing
  const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 }));
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.55, 0.45, 0.82);
  composer.addPass(bloom);
  const output = new OutputPass();
  composer.addPass(output);
  renderer.toneMappingExposure = 1.0;
  output.toneMapping = THREE.ACESFilmicToneMapping;

  const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), V = new THREE.Vector3(), S = new THREE.Vector3(), C = new THREE.Color();
  const UP = new THREE.Vector3(0, 1, 0);
  let quality = "high", size = [0, 0, 0];

  function setQuality(q) {
    quality = q;
    const shadows = q !== "low";
    renderer.shadowMap.enabled = shadows;
    sun.castShadow = shadows;
    const res = q === "high" ? 2048 : 1024;
    if (sun.shadow.mapSize.x !== res) { sun.shadow.mapSize.set(res, res); if (sun.shadow.map) { sun.shadow.map.dispose(); sun.shadow.map = null; } }
    bloom.enabled = q !== "low";
    size = [0, 0, 0];
  }

  function fill(pool, list) {
    const counts = {};
    for (const s of SHAPES) counts[s] = 0;
    for (const o of list) {
      const mesh = pool[o.mesh];
      if (!mesh) continue;
      const i = counts[o.mesh];
      if (i >= mesh.instanceMatrix.count) continue;
      counts[o.mesh] = i + 1;
      Q.setFromAxisAngle(UP, o.ry || 0);
      M.compose(V.set(o.pos[0], o.pos[1], o.pos[2]), Q, S.set(o.s[0], o.s[1], o.s[2]));
      mesh.setMatrixAt(i, M);
      C.setRGB(o.color[0], o.color[1], o.color[2], THREE.SRGBColorSpace);
      mesh.setColorAt(i, C);
      const x = mesh.geometry.attributes.lokiX;
      x.setXYZW(i, o.e || 0, o.g || 0, o.s2 == null ? 0.3 : o.s2, o.a == null ? 1 : o.a);
    }
    for (const s of SHAPES) {
      const mesh = pool[s];
      mesh.count = counts[s];
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      mesh.geometry.attributes.lokiX.needsUpdate = true;
    }
  }

  function sprites(pool, list, puff) {
    for (let i = 0; i < pool.list.length; i++) {
      const s = pool.list[i], g = list[i];
      if (!g) { s.visible = false; continue; }
      s.visible = true;
      s.position.set(g.pos[0], g.pos[1], g.pos[2]);
      const r = g.r * (puff ? 2.0 : 2.4);
      s.scale.set(r, r, 1);
      s.material.color.setRGB(g.color[0], g.color[1], g.color[2], THREE.SRGBColorSpace);
      s.material.opacity = Math.min(1, g.a == null ? 1 : g.a) * (puff ? 0.6 : 0.9);
    }
  }

  function render(f) {
    const { w, h, dpr } = f;
    if (size[0] !== w || size[1] !== h || size[2] !== dpr) {
      size = [w, h, dpr];
      renderer.setPixelRatio(dpr);
      renderer.setSize(w, h, false);
      composer.setPixelRatio(dpr);
      composer.setSize(w, h);
      bloom.resolution.set(w * dpr / 2, h * dpr / 2);
    }
    camera.fov = f.fov * 180 / Math.PI; camera.aspect = w / h; camera.updateProjectionMatrix();
    camera.position.set(f.eye[0], f.eye[1], f.eye[2]);
    camera.lookAt(f.target[0], f.target[1], f.target[2]);
    const P = f.P, day = P.dayK;

    // sky + lights from the same palette as the classic renderer
    const u = skyMat.uniforms;
    u.zenith.value.set(...lin(P.zenith).toArray()); u.horizon.value.set(...lin(P.horizon).toArray());
    u.glow.value.set(...lin(P.glow).toArray()); u.deep.value.set(...lin(P.deep).toArray());
    u.sunDir.value.set(f.sunDir[0], f.sunDir[1], f.sunDir[2]); u.sunCol.value.set(...lin(P.sunSky).toArray());
    u.stars.value = P.stars; u.T.value = f.t % 600;
    sky.position.copy(camera.position);
    sun.position.set(f.sunDir[0] * 30, f.sunDir[1] * 30, f.sunDir[2] * 30);
    sun.color.copy(lin(P.sunCol)); sun.intensity = 1.1 + 2.0 * day;
    hemi.color.copy(lin(P.skyAmb)); hemi.groundColor.copy(lin(P.gndAmb)); hemi.intensity = 1.6 + 0.4 * day;
    renderer.toneMappingExposure = 1.15 - 0.1 * day;
    scene.fog = null;
    f.lights.forEach((l, i) => {
      if (i >= LIGHTS) return;
      const p = points[i];
      p.position.set(l.pos[0], l.pos[1], l.pos[2]);
      p.color.copy(lin(l.color)); p.distance = l.radius * 1.4; p.intensity = 3.2 * P.lamps;
    });
    for (let i = f.lights.length; i < LIGHTS; i++) points[i].intensity = 0;
    skyBatch.rotation.y = f.skyRot;

    // water
    const nowS = performance.now() / 1000;
    for (const wb of waters) {
      const un = wb.mat.uniforms;
      un.T.value = f.t % 600; un.eyePos.value.set(f.eye[0], f.eye[1], f.eye[2]);
      un.sunDir.value.set(f.sunDir[0], f.sunDir[1], f.sunDir[2]); un.sunCol.value.set(...lin(P.sunCol).toArray());
      un.zenith.value.set(...lin(P.zenith).toArray()); un.horizon.value.set(...lin(P.horizon).toArray()); un.dayK.value = day;
      un.shallow.value.set(...lin(f.waterLook.shallow).toArray()); un.deep.value.set(...lin(f.waterLook.deep).toArray());
      un.foamCol.value.set(...lin(f.waterLook.foam).toArray());
      for (let i = 0; i < 8; i++) {
        const l = f.lights[i];
        if (l) { un.LP.value[i].set(l.pos[0], l.pos[1], l.pos[2]); const c = lin(l.color); un.LC.value[i].set(c.r * P.lamps, c.g * P.lamps, c.b * P.lamps, l.radius); }
        else { un.LC.value[i].set(0, 0, 0, 1); }
      }
      let k = 0;
      for (const r of f.ripples) if (r.body === wb.w.id && k < 4) { un.rip.value[k].set(r.x, r.z, nowS - r.t0, r.k); k++; }
      for (; k < 4; k++) un.rip.value[k].set(0, 0, 0, 0);
    }

    fill(pools, f.L.solids);
    fill(clearPools, f.L.clear);
    sprites(glows, f.L.glows.concat(f.L.static_glows || []), false);
    sprites(puffs, f.L.puffs, true);
    renderer.info.reset();
    composer.render();
    return renderer.info.render.calls;
  }

  canvas.addEventListener("webglcontextlost", (e) => e.preventDefault());
  return { render, setQuality, get quality() { return quality; }, renderer, kind: "three" };
}

window.WorldThree = { create, version: THREE.REVISION };
window.dispatchEvent(new Event("worldthree-ready"));
