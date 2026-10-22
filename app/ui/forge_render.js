// Forge's Render (owner 2026-10-21: LOKI becomes "a game engine, render studio, AI farm hive"). A real path-traced
// render of every visible mesh in Forge's scene, in LOKI's window, with three-gpu-pathtracer + three-mesh-bvh
// (MIT, vendored in app/ui/vendor/pathtracer/ and app/ui/vendor/three-mesh-bvh/ - docs/FORGE_RENDER.md):
//
//   Renderer > Path Traced Preview   the viewport itself converges progressively while the camera is still and
//                                    goes back to the raster view the moment anything changes (orbit, edit, select)
//   Renderer > Render...             the Render window: resolution, samples, bounces, a procedural environment
//                                    (studio / sky / gradient / neutral, made in code - no image downloads), background,
//                                    floor, denoise, exposure + tone mapping, depth of field, progress, Stop, Save PNG
//   window.ForgeRender               the same renderer for scripts and the Render Studio tab: render(opts) -> a job,
//                                    renderSequence(opts) for the Time Slider's frames, isAvailable()
//
// The render works on copies: every visible mesh is put into a scene of its own with its material translated for
// the path tracer (standard / physical as they are, matcap -> clay, unlit / image planes -> emissive), so nothing in
// Forge's scene changes. Final renders draw in an offscreen canvas at the chosen size, a few tiles per animation
// frame, so the window never freezes.
"use strict";

const FORGE_RENDER_STORE = "loki-forge-render";
const FORGE_RENDER_DEFAULTS = {
  res: "viewport", width: 1280, height: 720, camera: "current", samples: 128, bounces: 5,
  environment: "studio", envIntensity: 1, envRotation: 0, background: "environment", backgroundColor: "#3a3d42",
  floor: "none", denoise: true, exposure: 1, toneMapping: "agx", dof: false, focus: "selection", fStop: 2.8, previewScale: 0.5,
  mis: true, denoiseStrength: 0.5,     // multiple importance sampling: cleaner light from the environment; off = a much smaller shader (faster first compile)
};
const FORGE_RENDER_RES = [["viewport", "Viewport size"], ["1280x720", "1280 x 720 (HD)"], ["1920x1080", "1920 x 1080 (Full HD)"],
  ["3840x2160", "3840 x 2160 (4K)"], ["custom", "Custom"]];
const FORGE_RENDER_ENVS = [["studio", "Studio (soft boxes)"], ["sky", "Sky with sun"], ["gradient", "Studio gradient"], ["neutral", "Neutral grey"]];
const FORGE_RENDER_TONES = [["agx", "AgX"], ["aces", "ACES Filmic"], ["neutral", "Neutral"], ["reinhard", "Reinhard"], ["linear", "Linear"], ["none", "None"]];
const FORGE_RENDER_CAMS = [["current", "Current view"], ["persp", "persp"], ["top", "top"], ["front", "front"], ["side", "side"]];

const ForgeRender = (() => {
  let lib = null, loading = null, avail = null;
  const ctxs = new Map();          // "preview" / "final" -> { pt, quads, targets } on Forge's WebGL context
  let chain = Promise.resolve();   // final renders run one after another
  const envCache = {};

  // ---------------------------------------------------------------- settings (remembered per machine)
  function saved() {
    let s = {}; try { s = JSON.parse(localStorage.getItem(FORGE_RENDER_STORE) || "{}") || {}; } catch (_) { s = {}; }
    return Object.assign({}, FORGE_RENDER_DEFAULTS, s);
  }
  function save(s) { try { localStorage.setItem(FORGE_RENDER_STORE, JSON.stringify(s)); } catch (_) { /* private window */ } }
  // the options a caller gives (the dialog, Render Studio, a script) -> one flat settings object
  function norm(o) {
    const s = Object.assign({}, saved(), o || {});
    if (o && o.environment && typeof o.environment === "object") {
      const e = o.environment;
      s.environment = e.type || e.name || FORGE_RENDER_DEFAULTS.environment;
      if (e.intensity != null) s.envIntensity = +e.intensity;
      if (e.rotation != null) s.envRotation = +e.rotation;
    }
    if (o && typeof o.background === "string" && o.background.startsWith("#")) { s.backgroundColor = o.background; s.background = "color"; }
    if (o && o.background && typeof o.background === "object") { s.background = o.background.type || "color"; if (o.background.color) s.backgroundColor = o.background.color; }
    if (o && o.dof && typeof o.dof === "object") { s.dof = o.dof.enabled !== false; if (o.dof.fStop != null) s.fStop = +o.dof.fStop; if (o.dof.focus) s.focus = o.dof.focus; }
    s.dof = !!s.dof;
    const tm = String(s.toneMapping || "agx").toLowerCase();
    s.toneMapping = FORGE_RENDER_TONES.some(([k]) => k === tm) ? tm : (tm.includes("aces") ? "aces" : tm.includes("agx") ? "agx" : "agx");
    s.samples = Math.max(1, Math.min(100000, Math.round(+s.samples || 1)));
    s.bounces = Math.max(1, Math.min(32, Math.round(+s.bounces || 1)));
    s.exposure = Math.max(0.01, +s.exposure || 1);
    s.envIntensity = Math.max(0, Number.isFinite(+s.envIntensity) ? +s.envIntensity : 1);
    s.envRotation = Number.isFinite(+s.envRotation) ? +s.envRotation : 0;
    s.fStop = Math.max(0.5, +s.fStop || 2.8);
    s.previewScale = Math.max(0.1, Math.min(1, +s.previewScale || 0.5));
    s.denoiseStrength = Math.max(0, Math.min(1, Number.isFinite(+s.denoiseStrength) ? +s.denoiseStrength : 0.5));
    s.mis = s.mis !== false && s.mis !== "false" && s.mis !== 0;
    return s;
  }
  function sizeOf(s) {
    if (s.res && /^\d+x\d+$/.test(s.res)) return s.res.split("x").map((x) => x | 0);
    if (s.res === "custom") return [Math.max(1, s.width | 0), Math.max(1, s.height | 0)];
    const v = view(), c = v && v.canvas;
    return [Math.max(16, (c && c.width) || 960), Math.max(16, (c && c.height) || 540)];
  }

  // ---------------------------------------------------------------- loading and the WebGL2 check
  function view() { return typeof forge !== "undefined" && forge ? forge.view : null; }
  function say(t, bad) { if (typeof forgeSay === "function") forgeSay(t, bad); }
  function isAvailable() {
    if (avail != null) return avail;
    try {
      const c = document.createElement("canvas"), gl = c.getContext("webgl2");
      avail = !!(gl && gl.getExtension("EXT_color_buffer_float"));
      const lose = gl && gl.getExtension("WEBGL_lose_context"); if (lose) lose.loseContext();
    } catch (_) { avail = false; }
    return avail;
  }
  function load() {
    if (lib) return Promise.resolve(lib);
    if (!loading) {
      loading = Promise.all([
        import("/ui/vendor/three/three.module.js"),
        import("/ui/vendor/pathtracer/index.js"),
        import("/ui/vendor/pathtracer/materials/fullscreen/ClampedInterpolationMaterial.js"),
        import("/ui/vendor/three/addons/postprocessing/Pass.js"),
      ]).then(([THREE, PT, CI, PS]) => { lib = { THREE, PT, Clamped: CI.ClampedInterpolationMaterial, FullScreenQuad: PS.FullScreenQuad }; return lib; })
        .catch((exc) => { loading = null; throw exc; });
    }
    return loading;
  }

  // Everything runs on Forge's own WebGL context (view.renderer) with ONE path tracer: its shader is very large and
  // compiling it is the slow part (seconds on a GPU, ~25 s on a software one), so a second context or a second path
  // tracer would pay that again. The preview (draws into the viewport) and the final renders (their own size, read back
  // into a 2D canvas) take turns with it: c.owner says who set it up last, and the other one rebuilds before drawing.
  function ctxFor(key) {
    let c = ctxs.get("pt");
    const v = view(), renderer = v && v.renderer;
    if (!renderer) throw new Error("Open Forge first.");
    if (c && c.renderer === renderer) { if (c.owner !== key) { c.owner = key; c.dirty = true; } return c; }
    const { THREE, PT, FullScreenQuad } = lib;
    const pt = new PT.WebGLPathTracer(renderer);
    Object.assign(pt, { renderToCanvas: false, rasterizeScene: false, minSamples: 0, renderDelay: 0, fadeDuration: 0, dynamicLowRes: false });
    pt.synchronizeRenderSize = false;                        // sizes are set by hand: the viewport's, or the render's
    pt.filterGlossyFactor = 0.5;
    const dm = new PT.DenoiseMaterial({ map: null, blending: THREE.NoBlending, transparent: false, premultipliedAlpha: false });
    dm.uniforms.sigma.value = 4; dm.uniforms.threshold.value = 0.04;
    c = { owner: key, dirty: true, renderer, pt, dquad: new FullScreenQuad(dm), oquad: new FullScreenQuad(outputMaterial()), dtarget: null, otarget: null };
    ctxs.set("pt", c);
    return c;
  }
  let DENOISE_T0 = 0.02, DENOISE_T1 = 0.3;
  const TONE_FN = { agx: "AgXToneMapping", aces: "ACESFilmicToneMapping", neutral: "NeutralToneMapping", reinhard: "ReinhardToneMapping",
    linear: "LinearToneMapping", none: "FrNoToneMapping" };
  // exposure + tone mapping + sRGB in one small pass of our own, so the result is the same on the canvas and in a
  // render target (three.js applies its tone mapping only when drawing to the canvas). The tone curves are three's
  // own (ShaderChunk.tonemapping_pars_fragment), with the exposure uniform renamed.
  function outputMaterial() {
    const { THREE } = lib;
    const curves = THREE.ShaderChunk.tonemapping_pars_fragment.replace(/toneMappingExposure/g, "uExposure");
    return new THREE.ShaderMaterial({
      name: "ForgeRenderOutput", toneMapped: false, depthTest: false, depthWrite: false, blending: THREE.NoBlending, transparent: false,
      defines: { TM_FN: "AgXToneMapping" },
      uniforms: { map: { value: null }, uExposure: { value: 1 }, flipY: { value: 0 }, premul: { value: 0 } },
      vertexShader: "varying vec2 vUv;\nvoid main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }",
      fragmentShader: [
        "uniform sampler2D map; uniform float flipY; uniform float premul; varying vec2 vUv;",
        curves,
        "vec3 FrNoToneMapping(vec3 c) { return saturate(c * uExposure); }",
        "vec3 frSRGB(vec3 c) { c = saturate(c); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c)); }",
        "void main() {",
        "  vec2 uv = vec2(vUv.x, flipY > 0.5 ? 1.0 - vUv.y : vUv.y);",
        "  vec4 t = texture2D(map, uv);",
        "  vec3 c = frSRGB(TM_FN(max(t.rgb, vec3(0.0))));",
        "  float a = saturate(t.a);",
        "  gl_FragColor = vec4(premul > 0.5 ? c * a : c, a);",
        "}"].join("\n"),
    });
  }
  // the accumulated picture -> the canvas (target null) or the output target, denoised first if asked
  function blit(c, s, target, flip) {
    const { THREE } = lib, r = c.renderer, pt = c.pt;
    const was = [r.getRenderTarget(), r.autoClear, r.getScissorTest()];
    r.autoClear = false; r.setScissorTest(false);
    let tex = pt.target.texture;
    if (s.denoise) {
      const w = pt.target.width, h = pt.target.height;
      if (!c.dtarget) c.dtarget = new THREE.WebGLRenderTarget(w, h, { type: THREE.FloatType, format: THREE.RGBAFormat, depthBuffer: false });
      if (c.dtarget.width !== w || c.dtarget.height !== h) c.dtarget.setSize(w, h);
      c.dquad.material.map = tex; c.dquad.material.opacity = 1;
      c.dquad.material.threshold = DENOISE_T0 + DENOISE_T1 * s.denoiseStrength;   // the edge threshold: higher smooths more
      r.setRenderTarget(c.dtarget); c.dquad.render(r);
      tex = c.dtarget.texture;
    }
    const m = c.oquad.material, fn = TONE_FN[s.toneMapping] || TONE_FN.agx;
    if (m.defines.TM_FN !== fn) { m.defines.TM_FN = fn; m.needsUpdate = true; }
    m.uniforms.map.value = tex; m.uniforms.uExposure.value = s.exposure;
    m.uniforms.flipY.value = flip ? 1 : 0;
    m.uniforms.premul.value = target ? 0 : (r.getContextAttributes().premultipliedAlpha ? 1 : 0);
    r.setRenderTarget(target || null);
    c.oquad.render(r);
    r.setRenderTarget(was[0]); r.autoClear = was[1]; r.setScissorTest(was[2]);
  }
  // a final render's picture -> a 2D canvas (read back from the GPU; the output pass draws it upside down so the rows
  // come back top first)
  function readOut(c, s, canvas) {
    const { THREE } = lib, w = canvas.width, h = canvas.height;
    if (!c.otarget) c.otarget = new THREE.WebGLRenderTarget(w, h, { type: THREE.UnsignedByteType, format: THREE.RGBAFormat, depthBuffer: false });
    if (c.otarget.width !== w || c.otarget.height !== h) c.otarget.setSize(w, h);
    blit(c, s, c.otarget, true);
    const px = new Uint8ClampedArray(w * h * 4);
    c.renderer.readRenderTargetPixels(c.otarget, 0, 0, w, h, px);
    canvas.getContext("2d").putImageData(new ImageData(px, w, h), 0, 0);
  }

  // ---------------------------------------------------------------- the environment, made in code
  function smooth(a, b, x) { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); }
  function envTexture(type) {
    if (envCache[type]) return envCache[type];
    const { THREE, PT } = lib, dir = new THREE.Vector3();
    const tex = new PT.ProceduralEquirectTexture(256, 128);
    const sun = new THREE.Vector3(0.45, 0.62, 0.35).normalize();
    tex.generationCallback = (polar, uv, coord, col) => {
      dir.setFromSpherical(polar); const y = dir.y;
      if (type === "sky") {
        if (y >= 0) {
          const t = Math.pow(y, 0.45);
          col.setRGB(0.78 + (0.16 - 0.78) * t, 0.86 + (0.36 - 0.86) * t, 1.0 + (0.82 - 1.0) * t);
          const d = dir.dot(sun);
          const glow = Math.pow(Math.max(0, d), 64) * 2.0, disc = d > 0.9993 ? 60 : 0;
          col.r += glow + disc; col.g += glow * 0.9 + disc * 0.95; col.b += glow * 0.75 + disc * 0.85;
        } else {
          const t = smooth(-0.15, 0, y);
          col.setRGB(0.20 + 0.5 * t, 0.18 + 0.6 * t, 0.16 + 0.75 * t);
        }
      } else if (type === "gradient") {
        const t = smooth(-0.4, 0.9, y);
        col.setRGB(0.05 + 0.85 * t, 0.055 + 0.85 * t, 0.06 + 0.88 * t);
      } else if (type === "neutral") {
        col.setRGB(0.6, 0.6, 0.6);
      } else {   // studio: a dark floor, grey walls, a big soft box overhead and a key strip to one side, a rim behind
        const base = 0.06 + 0.24 * smooth(-0.25, 0.25, y);
        let v = base + 3.2 * smooth(0.78, 0.9, y);
        if (dir.x > 0.72 && Math.abs(y - 0.15) < 0.38) v += 2.2 * smooth(0.72, 0.82, dir.x);
        if (dir.z < -0.8 && y > 0.1 && y < 0.6) v += 1.2;
        col.setRGB(v, v, v * 1.02);
      }
    };
    tex.update();
    envCache[type] = tex;
    return tex;
  }

  // ---------------------------------------------------------------- what is drawn: copies of Forge's visible meshes
  function meshesOf(v) {
    const out = [], seen = new Set();
    const shown = (o) => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
    const ok = (o) => {
      if (!o.isMesh || !o.geometry || !o.geometry.isBufferGeometry || !o.geometry.attributes.position || !o.geometry.attributes.position.count) return false;
      if (/^forge-(sel|cage|grid)/.test(o.name || "") || o.isInstancedMesh || o.isSkinnedMesh) return false;
      if (o.renderOrder >= 10 || (o.material && o.material.depthTest === false)) return false;   // overlays (the brush ring, handles)
      const ms = Array.isArray(o.material) ? o.material : [o.material];
      return ms.some((m) => m && m.visible !== false && !m.wireframe && (m.opacity == null || m.opacity > 0.02));
    };
    const api = v.tree && v.tree.api;
    if (api && api.sceneNodes) {
      const nodes = api.sceneNodes(), grps = new Set(nodes.map((n) => n.grp).filter(Boolean));
      for (const n of nodes) {
        if (!n.grp || !n.visible || !shown(n.grp)) continue;
        if (api.layersTemplate && api.layersTemplate(n.id)) continue;           // a template draws as a guide wire, not a surface
        if (api.layerNorm && !api.layerNorm(n)) continue;
        const walk = (o) => {
          if (o !== n.grp && grps.has(o)) return;                               // another node: it adds its own meshes
          if (!o.visible) return;
          if (ok(o) && !seen.has(o)) { seen.add(o); out.push(o); }
          for (const k of o.children) walk(k);
        };
        walk(n.grp);
      }
    }
    if (!out.length && v.meshObj) { const m = v.meshObj(); if (m && ok(m) && shown(m)) out.push(m); }
    return out;
  }
  // Forge's look -> materials the path tracer understands (it reads MeshStandard / MeshPhysical)
  function mapMaterial(m) {
    const { THREE } = lib;
    if (!m) return new THREE.MeshStandardMaterial({ color: 0x9a9a9a, roughness: 0.8 });
    if (m.isMeshStandardMaterial) {                                // standard and physical work as they are
      const c = m.clone(); c.wireframe = false; c.polygonOffset = false; return c;
    }
    const common = { side: m.side, transparent: !!m.transparent, opacity: m.opacity == null ? 1 : m.opacity, alphaTest: m.alphaTest || 0,
      vertexColors: !!m.vertexColors };
    const col = m.color ? m.color.clone() : new THREE.Color(0x9a9a9a);
    if (m.isMeshMatcapMaterial) {                                  // a lit-sphere look has no real surface: render it as clay
      return new THREE.MeshStandardMaterial(Object.assign(common, { color: col.multiply(new THREE.Color(0xc9b8a8)), roughness: 0.55, metalness: 0 }));
    }
    if (m.isMeshBasicMaterial) {                                   // unlit (an image plane): shows its own colours, as light
      if (m.map) return new THREE.MeshStandardMaterial(Object.assign(common, { color: 0x000000, map: m.map, emissive: 0xffffff, emissiveMap: m.map, emissiveIntensity: 1, roughness: 1, metalness: 0 }));
      return new THREE.MeshStandardMaterial(Object.assign(common, { color: col, roughness: 0.9, metalness: 0 }));
    }
    const rough = m.isMeshPhongMaterial ? Math.sqrt(2 / ((m.shininess || 30) + 2)) : m.isMeshToonMaterial ? 0.8 : 1;
    return new THREE.MeshStandardMaterial(Object.assign(common, { color: col, map: m.map || null, normalMap: m.normalMap || null,
      emissive: m.emissive ? m.emissive.clone() : 0x000000, roughness: rough, metalness: 0 }));
  }
  function sceneKey(meshes, s) {
    return meshes.map((o) => {
      const p = o.geometry.attributes.position, ms = Array.isArray(o.material) ? o.material : [o.material];
      return o.uuid + ":" + o.geometry.uuid + ":" + p.version + ":" + p.count + ":" + o.matrixWorld.elements.map((x) => x.toFixed(5)).join(",")
        + ":" + ms.map((m) => m && m.uuid + "." + m.version).join(",");
    }).join("|") + "#" + [s.environment, s.envIntensity, s.envRotation, s.background, s.backgroundColor, s.floor].join(",");
  }
  function buildScene(v, s) {
    const { THREE } = lib;
    v.scene && v.scene.updateMatrixWorld(true);
    const meshes = meshesOf(v), scene = new THREE.Scene(), box = new THREE.Box3(), mats = [];
    for (const o of meshes) {
      const mat = Array.isArray(o.material) ? o.material.map(mapMaterial) : mapMaterial(o.material);
      (Array.isArray(mat) ? mat : [mat]).forEach((m) => mats.push(m));
      const c = new THREE.Mesh(o.geometry, mat);                   // the geometry is shared, read only
      c.matrixAutoUpdate = false; c.matrix.copy(o.matrixWorld); c.matrixWorld.copy(o.matrixWorld);
      scene.add(c);
      if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
      box.union(o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld));
    }
    if (box.isEmpty()) box.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(1, 1, 1));
    let floor = null;
    if (s.floor === "grey" || s.floor === "catcher") {
      const size = box.getSize(new THREE.Vector3()), span = Math.max(size.x, size.y, size.z, 1) * 40;
      const fm = new THREE.MeshStandardMaterial({ color: 0x7c7c7c, roughness: 0.85, metalness: 0 });
      if (s.floor === "catcher") fm.matte = true;                  // the path tracer's matte: shows the background, keeps the shadows
      floor = new THREE.Mesh(new THREE.PlaneGeometry(span, span), fm);
      floor.rotation.x = -Math.PI / 2; floor.position.set(box.getCenter(new THREE.Vector3()).x, box.min.y - 1e-4, box.getCenter(new THREE.Vector3()).z);
      floor.updateMatrixWorld(true);
      scene.add(floor); mats.push(fm);
    }
    const env = envTexture(s.environment);
    const rot = s.envRotation * Math.PI / 180;
    scene.environment = env; scene.environmentIntensity = s.envIntensity; scene.environmentRotation.set(0, rot, 0);
    scene.backgroundRotation.set(0, rot, 0); scene.backgroundIntensity = s.envIntensity;
    scene.background = s.background === "transparent" ? null : s.background === "color" ? new THREE.Color(s.backgroundColor || "#3a3d42") : env;
    return { scene, box, meshes, key: sceneKey(meshes, s), dispose() { mats.forEach((m) => m.dispose()); if (floor) floor.geometry.dispose(); } };
  }

  // ---------------------------------------------------------------- the camera (the view, or one of the named ones)
  function focusPoint(v, built, s) {
    const { THREE } = lib, api = v.tree && v.tree.api;
    if (s.focus === "selection" && v.tree && v.tree.sel && v.tree.sel.length && api) {
      const b = new THREE.Box3();
      const inSel = (o) => { for (let p = o; p; p = p.parent) if (v.tree.sel.some((id) => { const n = api.node(id); return n && n.grp === p; })) return true; return false; };
      for (const o of built.meshes) if (inSel(o)) { if (!o.geometry.boundingBox) o.geometry.computeBoundingBox(); b.union(o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld)); }
      if (!b.isEmpty()) return b.getCenter(new THREE.Vector3());
    }
    if (s.focus === "selection" || s.focus === "scene") return built.box.getCenter(new THREE.Vector3());
    return v.controls && v.controls.target ? v.controls.target.clone() : built.box.getCenter(new THREE.Vector3());
  }
  function buildCamera(v, built, s, w, h) {
    const { THREE, PT } = lib, aspect = w / h, name = s.camera || "current";
    const sphere = built.box.getBoundingSphere(new THREE.Sphere()), r = Math.max(sphere.radius, 1e-3);
    let cam;
    if (name === "top" || name === "front" || name === "side") {
      const dir = { top: [0, 1, 0], front: [0, 0, 1], side: [1, 0, 0] }[name], hh = r * 1.15, hw = hh * aspect;
      cam = new THREE.OrthographicCamera(-hw, hw, hh, -hh, 0.001, r * 20 + 10);
      if (name === "top") cam.up.set(0, 0, -1);
      cam.position.copy(sphere.center).addScaledVector(new THREE.Vector3(dir[0], dir[1], dir[2]), r * 6 + 1);
      cam.lookAt(sphere.center); cam.updateProjectionMatrix(); cam.updateMatrixWorld(true);
      return cam;
    }
    cam = new PT.PhysicalCamera(35, aspect, 0.01, 100);
    if (name === "persp" || !v.camera) {
      const d = r / Math.sin((cam.fov * Math.PI) / 360) * 1.15;
      cam.position.copy(sphere.center).addScaledVector(new THREE.Vector3(28, 21, 28).normalize(), d);
      cam.near = d / 100; cam.far = d * 100 + r * 4; cam.lookAt(sphere.center);
    } else {
      const src = v.camera; src.updateMatrixWorld(true);
      cam.fov = src.fov || 35; cam.near = src.near; cam.far = src.far; cam.zoom = src.zoom || 1;
      if (src.filmGauge) cam.filmGauge = src.filmGauge;
      src.matrixWorld.decompose(cam.position, cam.quaternion, cam.scale);
    }
    cam.aspect = aspect; cam.updateProjectionMatrix(); cam.updateMatrixWorld(true);
    if (s.dof) {
      cam.fStop = s.fStop;
      const p = focusPoint(v, built, s), fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(cam.quaternion);
      cam.focusDistance = Math.max(cam.near * 2, p.clone().sub(cam.position).dot(fwd));
    } else {
      cam.fStop = Infinity;                                      // bokeh 0: everything sharp
    }
    return cam;
  }

  // ---------------------------------------------------------------- final renders: a job in the offscreen canvas
  const nextFrame = () => new Promise((res) => requestAnimationFrame(() => res(performance.now())));
  function render(opts) {
    opts = opts || {};
    const job = { progress: 0, samples: 0, target: 0, ms: 0, running: true, stopped: false, width: 0, height: 0, canvas: null,
      stop() { job.stopped = true; }, done: null };
    const given = Object.assign({}, opts);
    job.done = (chain = chain.catch(() => {}).then(() => run(job, given)));
    job.done.catch(() => { job.running = false; });
    return job;
  }
  let finals = 0;                  // final renders running (the preview waits for them)
  async function run(job, given) {
    finals++;
    try { return await runFinal(job, given); } finally { finals--; }
  }
  async function runFinal(job, given) {
    if (!isAvailable()) throw new Error("Render needs WebGL2 with float render targets (EXT_color_buffer_float), and this browser has none.");
    await load();
    const v = view();
    if (!v) throw new Error("Open Forge first.");
    const s = norm(given);
    let w, h;
    if (given.width && given.height) { w = given.width | 0; h = given.height | 0; } else [w, h] = sizeOf(s);
    w = Math.max(1, Math.min(8192, w)); h = Math.max(1, Math.min(8192, h));
    Object.assign(job, { width: w, height: h, target: s.samples });
    const c = ctxFor("final"), pt = c.pt;
    c.dirty = true;
    job.canvas = document.createElement("canvas"); job.canvas.width = w; job.canvas.height = h;
    pt._pathTracer.setSize(w, h);                                // WebGLPathTracer has no public setSize (see docs/FORGE_RENDER.md)
    const built = buildScene(v, s), cam = buildCamera(v, built, s, w, h);
    pt.tiles.set(Math.max(1, Math.ceil(w / 256)), Math.max(1, Math.ceil(h / 256)));
    pt.bounces = s.bounces; pt.transmissiveBounces = Math.max(4, s.bounces);
    pt.multipleImportanceSampling = s.mis;
    pt.setScene(built.scene, cam);
    pt.reset();
    const t0 = performance.now();
    let per = 1, shown = 0, last = await nextFrame();
    try {
      while (!job.stopped && pt.samples < s.samples) {
        for (let i = 0; i < per && pt.samples < s.samples; i++) pt.renderSample();
        // the picture shown while it renders: read back a few times a second, not every frame (a read-back stalls the GPU)
        if (performance.now() - shown > 250) { readOut(c, s, job.canvas); shown = performance.now(); }
        job.samples = Math.floor(pt.samples); job.progress = Math.min(1, pt.samples / s.samples); job.ms = performance.now() - t0;
        if (typeof given.onProgress === "function") { try { given.onProgress(job); } catch (_) { /* the caller's problem */ } }
        const now = await nextFrame(), dt = now - last; last = now;
        if (dt < 24 && per < 64) per++; else if (dt > 45 && per > 1) per = Math.max(1, per >> 1);   // keep the window at frame rate
      }
      readOut(c, s, job.canvas);
    } finally { built.dispose(); }
    job.samples = Math.floor(pt.samples); job.progress = job.stopped ? Math.min(1, pt.samples / s.samples) : 1; job.ms = performance.now() - t0;
    const out = job.canvas;
    const dataURL = out.toDataURL("image/png");
    const blob = await new Promise((res) => (out.toBlob ? out.toBlob(res, "image/png") : res(null)));
    job.running = false; job.result = out;
    return { canvas: out, dataURL, blob, samples: job.samples, ms: Math.round(job.ms), width: w, height: h, stopped: job.stopped };
  }

  // an animation: each frame of the Time Slider in turn, the scene put back exactly as it was afterwards
  function renderSequence(opts) {
    opts = opts || {};
    const seq = { progress: 0, frame: null, frames: [], running: true, stopped: false, current: null,
      stop() { seq.stopped = true; if (seq.current) seq.current.stop(); }, done: null };
    seq.done = (async () => {
      const v = view(), T = v && v.tree, api = T && T.api;
      if (!api || !T.time) throw new Error("Open Forge first.");
      const t = T.time, keep = { frame: t.frame, start: t.start, end: t.end, playing: t.playing };
      const xf = T.nodes ? T.nodes.map((n) => n.grp && [n, n.grp.position.clone(), n.grp.quaternion.clone(), n.grp.scale.clone()]).filter(Boolean) : [];
      const start = Math.round(opts.start != null ? +opts.start : t.start), end = Math.round(opts.end != null ? +opts.end : t.end);
      const step = Math.max(1, Math.round(+opts.step || 1)), list = [];
      for (let f = start; f <= end; f += step) list.push(f);
      const t0 = performance.now();
      t.playing = false;
      try {
        for (let i = 0; i < list.length && !seq.stopped; i++) {
          seq.frame = list[i];
          t.start = Math.min(keep.start, start); t.end = Math.max(keep.end, end);   // a frame outside the range is not clamped
          api.setFrame(list[i]);
          const sub = Object.assign({}, opts, { onProgress: (j) => { seq.progress = (i + j.progress) / list.length; if (opts.onProgress) opts.onProgress(seq, j); } });
          delete sub.start; delete sub.end; delete sub.step;
          seq.current = render(sub);
          const res = await seq.current.done;
          res.frame = list[i];
          seq.frames.push(res);
          seq.progress = (i + 1) / list.length;
          if (typeof opts.onFrame === "function") { try { opts.onFrame(res, seq); } catch (_) { /* the caller's */ } }
        }
      } finally {
        Object.assign(t, keep);
        for (const [n, p, q, sc] of xf) { n.grp.position.copy(p); n.grp.quaternion.copy(q); n.grp.scale.copy(sc); }
        v.dirty = true;
        if (T.syncChannel) T.syncChannel();
        if (T.syncKeys) T.syncKeys();
        seq.running = false; seq.current = null;
      }
      return { frames: seq.frames, ms: Math.round(performance.now() - t0), stopped: seq.stopped };
    })();
    seq.done.catch(() => { seq.running = false; });
    return seq;
  }

  // ---------------------------------------------------------------- the path-traced preview, in the viewport itself
  const P = { on: false, c: null, built: null, cam: null, key: "", last: 0, tracing: false, hooked: false, per: 1, lastT: 0, s: null };
  function previewOn() { return P.on; }
  async function setPreview(on) {
    on = !!on;
    if (on === P.on) return P.on;
    if (on) {
      if (!isAvailable()) { say("Path Traced Preview needs WebGL2 with float render targets, which this browser does not have.", true); return false; }
      const v = view();
      if (!v || !v.renderer) { say("Open Forge first.", true); return false; }
      try { await load(); } catch (exc) { say("The path tracer could not load: " + exc.message, true); return false; }
      P.c = ctxFor("preview"); P.c.pt.tiles.set(2, 2);
      if (!P.hooked && Array.isArray(v.frameHooks)) { v.frameHooks.push(() => { P.last = performance.now(); P.tracing = false; }); P.hooked = true; }
      P.on = true; P.tracing = false; P.last = 0; P.key = "";
      requestAnimationFrame(previewLoop);
      say("Path Traced Preview: hold the camera still and the view refines; any change shows the raster view again.");
    } else {
      P.on = false; P.tracing = false;
      if (P.built) { P.built.dispose(); P.built = null; } P.key = "";
      const v = view(); if (v) v.dirty = true;
      say("Path Traced Preview off.");
    }
    syncDialog();
    return P.on;
  }
  function previewLoop() {
    if (!P.on) return;
    requestAnimationFrame(previewLoop);
    const v = view(), now = performance.now();
    if (!v || v.quad || !v.renderer || v.renderer !== P.c.renderer) return;
    if (finals > 0) { P.tracing = false; return; }                               // a final render has the path tracer
    if (v.dirty) { P.last = now; P.tracing = false; return; }                     // something changed: the raster frame shows it
    if (now - P.last < 200) return;                                              // wait for the camera to be still
    const s = P.s || norm({});
    const pt = P.c.pt;
    if (!P.tracing) {
      const cnv = v.canvas, w = Math.max(1, cnv.width), h = Math.max(1, cnv.height);
      const meshes = meshesOf(v), key = sceneKey(meshes, s);
      P.c = ctxFor("preview");
      if (P.c.dirty) { P.key = ""; P.c.dirty = false; }
      const sc = Math.max(0.1, Math.min(1, +s.previewScale || 1));      // a fraction of the viewport's pixels: faster on a slow GPU
      pt._pathTracer.setSize(Math.max(1, Math.round(w * sc)), Math.max(1, Math.round(h * sc)));
      if (key !== P.key || !P.built) {
        if (P.built) P.built.dispose();
        P.built = buildScene(v, s); P.key = key;
        P.cam = buildCamera(v, P.built, Object.assign({}, s, { camera: "current" }), w, h);
        pt.bounces = s.bounces; pt.transmissiveBounces = Math.max(4, s.bounces);
        pt.multipleImportanceSampling = s.mis;
        pt.setScene(P.built.scene, P.cam);
      } else {
        P.cam = buildCamera(v, P.built, Object.assign({}, s, { camera: "current" }), w, h);
        pt.bounces = s.bounces;
        pt.setCamera(P.cam);
      }
      pt.reset(); P.tracing = true; P.per = 1; P.lastT = now;
    }
    const cap = Math.max(s.samples, 16);
    P.s = s;
    if (pt.samples >= cap) return;
    const dt = now - P.lastT; P.lastT = now;
    if (dt < 24 && P.per < 16) P.per++; else if (dt > 45 && P.per > 1) P.per = Math.max(1, P.per >> 1);
    for (let i = 0; i < P.per && pt.samples < cap; i++) pt.renderSample();
    blit(P.c, s);
    P.samples = Math.floor(pt.samples);
  }

  // ---------------------------------------------------------------- the Render window
  let dlg = null, dlgJob = null, dlgResult = null, dlgTimer = 0;
  function css() {
    if (document.getElementById("forge-render-css")) return;
    const st = document.createElement("style"); st.id = "forge-render-css";
    st.textContent = `
.forge-rw { position: fixed; z-index: 1000; right: 40px; top: 70px; width: min(720px, calc(100vw - 32px)); max-height: calc(100vh - 90px);
  display: flex; flex-direction: column; background: #3c3d40; color: #dcdcdc; border: 1px solid #222; border-radius: 4px;
  box-shadow: 0 14px 40px rgba(0,0,0,.5); font-size: 12px; }
.forge-rw[hidden] { display: none; }
.forge-rw-title { display: flex; align-items: center; height: 26px; padding: 0 6px 0 10px; background: #2f3033; cursor: move; user-select: none; font-weight: 600; }
.forge-rw-title span { flex: 1; }
.forge-rw-x { border: 0; background: transparent; color: #ccc; font-size: 16px; width: 22px; height: 22px; border-radius: 3px; cursor: pointer; }
.forge-rw-x:hover { background: rgba(255,255,255,.12); }
.forge-rw-body { display: flex; gap: 10px; padding: 8px 10px; min-height: 0; overflow: auto; scrollbar-width: none; }
.forge-rw-set { flex: 0 0 250px; display: flex; flex-direction: column; gap: 3px; }
.forge-rw-sec { margin-top: 6px; font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em; color: #a9b0bb; }
.forge-rw-row { display: flex; align-items: center; gap: 6px; min-height: 22px; }
.forge-rw-row > span:first-child { flex: 0 0 92px; color: #c4c8ce; }
.forge-rw select, .forge-rw input[type=number], .forge-rw input[type=color] { background: #2b2b2b; color: #e6e6e6; border: 1px solid #222; border-radius: 2px; padding: 2px 5px; font: inherit; min-width: 0; }
.forge-rw select { flex: 1; } .forge-rw input[type=number] { width: 64px; } .forge-rw input[type=range] { flex: 1; min-width: 0; }
.forge-rw input[type=color] { width: 40px; height: 20px; padding: 0 2px; }
.forge-rw-view { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.forge-rw-stage { flex: 1; min-height: 180px; display: flex; align-items: center; justify-content: center; border: 1px solid #222; border-radius: 2px;
  background: repeating-conic-gradient(#2c2d30 0% 25%, #343538 0% 50%) 50% / 16px 16px; }
.forge-rw-stage canvas { max-width: 100%; max-height: 360px; image-rendering: auto; }
.forge-rw-bar { height: 4px; background: #2b2b2b; border-radius: 2px; overflow: hidden; } .forge-rw-bar > i { display: block; height: 100%; width: 0; background: #5285a6; }
.forge-rw-foot { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.forge-rw-foot button { background: #5d5d5d; color: #eee; border: 0; border-radius: 2px; padding: 4px 12px; font: inherit; cursor: pointer; }
.forge-rw-foot button.primary { background: #5285a6; } .forge-rw-foot button:hover:not(:disabled) { filter: brightness(1.12); }
.forge-rw-foot button:disabled { opacity: .45; cursor: default; }
.forge-rw-info { flex: 1; color: #b9c0c8; font-variant-numeric: tabular-nums; } .forge-rw-info.bad { color: #f0a070; }
@media (max-width: 640px) { .forge-rw-body { flex-direction: column; } .forge-rw-set { flex-basis: auto; } }`;
    document.head.append(st);
  }
  function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function openDialog(show) {
    if (dlg && show === false) { dlg.hidden = true; return dlg; }
    if (!dlg) buildDialog();
    dlg.hidden = false;
    fill(saved());
    syncDialog();
    return dlg;
  }
  function buildDialog() {
    css();
    dlg = el("div", "forge-rw"); dlg.id = "forge-render"; dlg.hidden = true;
    dlg.setAttribute("role", "dialog"); dlg.setAttribute("aria-label", "Render");
    const title = el("div", "forge-rw-title"); const x = el("button", "forge-rw-x", "×");
    x.type = "button"; x.title = "Close (Esc)"; title.append(el("span", "", "Render"), x);
    const set = el("div", "forge-rw-set");
    const row = (label, ...kids) => { const r = el("label", "forge-rw-row"); r.append(el("span", "", label), ...kids); return r; };
    const sel = (id, opts, tip) => { const s = el("select"); s.id = id; s.title = tip || ""; for (const [v, t] of opts) { const o = el("option", "", t); o.value = v; s.append(o); } return s; };
    const num = (id, min, max, step, tip) => { const i = el("input"); i.type = "number"; i.id = id; i.min = min; i.max = max; i.step = step; i.title = tip || ""; return i; };
    const rng = (id, min, max, step, tip) => { const i = el("input"); i.type = "range"; i.id = id; i.min = min; i.max = max; i.step = step; i.title = tip || ""; return i; };
    const chk = (id, tip) => { const i = el("input"); i.type = "checkbox"; i.id = id; i.title = tip || ""; return i; };
    const wIn = num("fr-w", 16, 8192, 1, "Width in pixels"), hIn = num("fr-h", 16, 8192, 1, "Height in pixels");
    const col = el("input"); col.type = "color"; col.id = "fr-bgcol"; col.title = "Background colour";
    set.append(
      el("div", "forge-rw-sec", "Output"),
      row("Resolution", sel("fr-res", FORGE_RENDER_RES, "The size of the picture")),
      row("Custom", wIn, el("span", "", "x"), hIn),
      row("Camera", sel("fr-cam", FORGE_RENDER_CAMS, "Which camera to render through")),
      el("div", "forge-rw-sec", "Quality"),
      row("Samples", num("fr-samples", 1, 100000, 1, "Paths per pixel: more is cleaner and slower")),
      row("Bounces", num("fr-bounces", 1, 32, 1, "How many times light may bounce")),
      row("Denoise", chk("fr-denoise", "Smooth the remaining noise (an edge-aware filter)")),
      row("Strength", rng("fr-dnstr", 0, 1, 0.05, "How strongly the denoiser smooths (edges are kept)")),
      row("Light sampling", chk("fr-mis", "Multiple importance sampling: cleaner light from the environment. Off: a simpler shader that starts much sooner on a slow GPU")),
      el("div", "forge-rw-sec", "Light"),
      row("Environment", sel("fr-env", FORGE_RENDER_ENVS, "The light around the scene, made in code")),
      row("Intensity", rng("fr-envint", 0, 4, 0.05, "How bright the environment is")),
      row("Rotation", rng("fr-envrot", 0, 360, 1, "Turn the environment around the up axis")),
      row("Background", sel("fr-bg", [["environment", "Environment"], ["color", "Colour"], ["transparent", "Transparent"]], "What is behind the objects"), col),
      row("Floor", sel("fr-floor", [["none", "None"], ["grey", "Grey floor"], ["catcher", "Shadow catcher"]], "A floor under the objects")),
      el("div", "forge-rw-sec", "Camera"),
      row("Exposure", rng("fr-exposure", 0.1, 4, 0.05, "Brighter or darker, like a camera's exposure")),
      row("Tone mapping", sel("fr-tone", FORGE_RENDER_TONES, "How bright light is fitted to the screen")),
      row("Depth of field", chk("fr-dof", "Blur what is not in focus")),
      row("Focus", sel("fr-focus", [["selection", "The selection"], ["target", "The view's centre"], ["scene", "The scene's centre"]], "What is sharp")),
      row("f-stop", num("fr-fstop", 0.5, 64, 0.1, "Lower is a shallower focus (more blur)")),
      el("div", "forge-rw-sec", "Viewport preview"),
      row("Resolution", sel("fr-pscale", [["0.25", "1/4"], ["0.5", "1/2"], ["0.75", "3/4"], ["1", "Full"]], "How many of the viewport's pixels the preview traces (fewer is faster)")));
    const viewBox = el("div", "forge-rw-view"), stage = el("div", "forge-rw-stage"), cv = el("canvas"); cv.id = "fr-canvas"; cv.width = 320; cv.height = 180;
    stage.append(cv);
    const bar = el("div", "forge-rw-bar"); bar.append(el("i")); bar.id = "fr-bar";
    const foot = el("div", "forge-rw-foot"), info = el("span", "forge-rw-info", "Ready."); info.id = "fr-info";
    const bR = el("button", "primary", "Render"), bS = el("button", "", "Stop"), bP = el("button", "", "Save PNG"), bV = el("button", "", "Preview in viewport");
    bR.id = "fr-render"; bS.id = "fr-stop"; bP.id = "fr-save"; bV.id = "fr-preview";
    for (const b of [bR, bS, bP, bV]) b.type = "button";
    bR.title = "Render the scene at the chosen size"; bS.title = "Stop: keep what has been rendered so far"; bP.title = "Download the picture as a PNG";
    bV.title = "Path Traced Preview: the viewport refines itself while the camera is still";
    foot.append(bR, bS, bP, bV, info);
    viewBox.append(stage, bar, foot);
    const body = el("div", "forge-rw-body"); body.append(set, viewBox);
    dlg.append(title, body);
    document.body.append(dlg);

    x.addEventListener("click", () => { dlg.hidden = true; });
    dlg.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Escape") dlg.hidden = true; });
    dlg.addEventListener("keyup", (e) => e.stopPropagation());
    set.addEventListener("input", () => { const s = read(); save(s); P.s = norm(s); P.key = ""; P.tracing = false; P.last = performance.now(); syncDialog(); });
    bR.addEventListener("click", () => startDialogRender());
    bS.addEventListener("click", () => { if (dlgJob) dlgJob.stop(); });
    bP.addEventListener("click", () => savePNG());
    bV.addEventListener("click", () => setPreview(!P.on));
    title.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button")) return;
      const r = dlg.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      title.setPointerCapture(e.pointerId);
      const mv = (ev) => { dlg.style.left = Math.max(0, ev.clientX - dx) + "px"; dlg.style.top = Math.max(0, ev.clientY - dy) + "px"; dlg.style.right = "auto"; };
      const up = () => { title.removeEventListener("pointermove", mv); title.removeEventListener("pointerup", up); };
      title.addEventListener("pointermove", mv); title.addEventListener("pointerup", up);
    });
  }
  const $ = (id) => document.getElementById(id);
  function fill(s) {
    $("fr-res").value = s.res; $("fr-w").value = s.width; $("fr-h").value = s.height; $("fr-cam").value = s.camera;
    $("fr-samples").value = s.samples; $("fr-bounces").value = s.bounces; $("fr-denoise").checked = !!s.denoise; $("fr-mis").checked = s.mis !== false; $("fr-dnstr").value = s.denoiseStrength;
    $("fr-env").value = s.environment; $("fr-envint").value = s.envIntensity; $("fr-envrot").value = s.envRotation;
    $("fr-bg").value = s.background; $("fr-bgcol").value = s.backgroundColor; $("fr-floor").value = s.floor;
    $("fr-exposure").value = s.exposure; $("fr-tone").value = s.toneMapping; $("fr-dof").checked = !!s.dof;
    $("fr-focus").value = s.focus; $("fr-fstop").value = s.fStop;
    $("fr-pscale").value = String([0.25, 0.5, 0.75, 1].reduce((a, b) => (Math.abs(b - s.previewScale) < Math.abs(a - s.previewScale) ? b : a)));
  }
  function read() {
    return { res: $("fr-res").value, width: +$("fr-w").value || 1280, height: +$("fr-h").value || 720, camera: $("fr-cam").value,
      samples: +$("fr-samples").value || 1, bounces: +$("fr-bounces").value || 1, denoise: $("fr-denoise").checked, mis: $("fr-mis").checked, denoiseStrength: +$("fr-dnstr").value,
      environment: $("fr-env").value, envIntensity: +$("fr-envint").value, envRotation: +$("fr-envrot").value,
      background: $("fr-bg").value, backgroundColor: $("fr-bgcol").value, floor: $("fr-floor").value,
      exposure: +$("fr-exposure").value || 1, toneMapping: $("fr-tone").value, dof: $("fr-dof").checked,
      focus: $("fr-focus").value, fStop: +$("fr-fstop").value || 2.8, previewScale: +$("fr-pscale").value || 0.5 };
  }
  function syncDialog() {
    if (!dlg) return;
    const custom = $("fr-res").value === "custom";
    $("fr-w").disabled = $("fr-h").disabled = !custom;
    $("fr-bgcol").disabled = $("fr-bg").value !== "color";
    $("fr-focus").disabled = $("fr-fstop").disabled = !$("fr-dof").checked;
    const running = !!(dlgJob && dlgJob.running);
    $("fr-render").disabled = running; $("fr-stop").disabled = !running; $("fr-save").disabled = !dlgResult && !running;
    $("fr-preview").textContent = P.on ? "Preview in viewport: on" : "Preview in viewport";
    $("fr-preview").classList.toggle("primary", P.on);
  }
  function info(text, bad) { const i = $("fr-info"); if (i) { i.textContent = text; i.classList.toggle("bad", !!bad); } }
  function show(src) {
    const cv = $("fr-canvas"); if (!cv || !src) return;
    if (cv.width !== src.width || cv.height !== src.height) { cv.width = src.width; cv.height = src.height; }
    const g = cv.getContext("2d"); g.clearRect(0, 0, cv.width, cv.height); g.drawImage(src, 0, 0);
  }
  function startDialogRender() {
    if (dlgJob && dlgJob.running) return dlgJob;
    const s = read(); save(s);
    if (!isAvailable()) { info("Render needs WebGL2 with float render targets; this browser has none.", true); return null; }
    const job = render(Object.assign({}, s, s.res === "custom" ? { width: s.width, height: s.height } : { width: 0, height: 0 }));
    dlgJob = job; dlgResult = null;
    info("Preparing the scene...");
    const tick = () => {
      if (job.canvas) show(job.canvas);
      const bar = $("fr-bar"); if (bar) bar.firstChild.style.width = (job.progress * 100).toFixed(1) + "%";
      if (job.target) info(job.samples + " / " + job.target + " samples · " + (job.ms / 1000).toFixed(1) + " s · " + job.width + " x " + job.height);
      if (job.running) dlgTimer = requestAnimationFrame(tick);
    };
    dlgTimer = requestAnimationFrame(tick);
    syncDialog();
    job.done.then((res) => {
      cancelAnimationFrame(dlgTimer); dlgResult = res; show(res.canvas);
      const bar = $("fr-bar"); if (bar) bar.firstChild.style.width = (res.stopped ? job.progress * 100 : 100) + "%";
      info((res.stopped ? "Stopped at " : "Done: ") + res.samples + " samples in " + (res.ms / 1000).toFixed(1) + " s · " + res.width + " x " + res.height);
      syncDialog();
    }, (exc) => { cancelAnimationFrame(dlgTimer); info("Render failed: " + exc.message, true); syncDialog(); });
    return job;
  }
  function savePNG() {
    let url = dlgResult && dlgResult.dataURL;
    if (!url && dlgJob && dlgJob.canvas) {                       // still rendering: what is there so far
      const c = document.createElement("canvas"); c.width = dlgJob.canvas.width; c.height = dlgJob.canvas.height;
      c.getContext("2d").drawImage(dlgJob.canvas, 0, 0); url = c.toDataURL("image/png");
    }
    if (!url) { info("Render something first.", true); return null; }
    const a = document.createElement("a");
    const d = new Date(), pad = (n) => String(n).padStart(2, "0");
    a.href = url; a.download = "forge-render-" + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + "-" + pad(d.getHours()) + pad(d.getMinutes()) + pad(d.getSeconds()) + ".png";
    a.hidden = true; document.body.append(a); a.click(); a.remove();
    api.lastSave = url;
    info("Saved " + a.download + ".");
    return url;
  }

  const api = {
    isAvailable, load, render, renderSequence, setPreview, previewOn, togglePreview: () => setPreview(!P.on),
    openDialog, startDialogRender, savePNG, settings: () => norm({}), defaults: () => Object.assign({}, FORGE_RENDER_DEFAULTS),
    dialogJob: () => dlgJob, dialogResult: () => dlgResult, previewSamples: () => (P.on && P.c && P.tracing ? Math.floor(P.c.pt.samples) : 0),
    meshes: () => (view() ? meshesOf(view()) : []), lastSave: null,
  };
  return api;
})();
window.ForgeRender = ForgeRender;

// the commands (the Renderer menu, the hotbox, the Hotkey Editor all read FORGE_PRO_CMDS)
if (typeof FORGE_PRO_CMDS !== "undefined") {
  if (!FORGE_PRO_CMDS.renderPreview) FORGE_PRO_CMDS.renderPreview = ["Path Traced Preview", () => ForgeRender.togglePreview().then((on) => (on ? "Path Traced Preview on." : ""))];
  if (!FORGE_PRO_CMDS.renderStudio) FORGE_PRO_CMDS.renderStudio = ["Send to Render Studio", () => {
    if (!window.LokiModeBar) return "Render Studio is not in this window.";
    window.LokiModeBar.go("render", { fromForge: true });
    return "Render Studio opened with Forge's camera and Time Slider range.";
  }];
  if (!FORGE_PRO_CMDS.renderDialog) FORGE_PRO_CMDS.renderDialog = ["Render...", () => { ForgeRender.openDialog(true); return "Render: pick a size and press Render."; }];
}
if (typeof FORGE_PRO_TOGGLES !== "undefined" && !FORGE_PRO_TOGGLES.renderPreview) FORGE_PRO_TOGGLES.renderPreview = () => ForgeRender.previewOn();
