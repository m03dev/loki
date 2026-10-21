// Forge's control passes for Render Studio's AI Renderer (docs/AI_RENDERER.md "Forge's passes"). From one of Forge's
// cameras, over the Time Slider's frames (start / end / step), at any size, as PNG frames:
//
//   depth     white = near, black = far, normalised between the nearest and farthest point of the visible meshes
//             (the polarity of VACE's own depth annotator - ali-vilab/VACE vace/annotators/depth.py: MiDaS inverse depth,
//             min-max to 0..255); the background is black (as far as it gets)
//   lineart   white lines on black (the polarity of ComfyUI's core Canny node and of VACE's scribble annotator): the
//             silhouette and creases, found by edge detection on the depth and the normals - not a wireframe
//   normal    view-space normals as RGB (optional)
//   beauty    the viewport's own shaded look without the grid, manipulator or selection (optional; the preprocess graph
//             can turn it into line art with Canny)
//
// Nothing in the scene changes: the passes use their own camera (a copy), their own render target and an override
// material; what is hidden for the render (grid, helpers, manipulator) and the Time Slider's frame / range / playing
// and every node's transform are put back in a finally block, also when a frame fails or the caller stops it.
"use strict";

const ForgePasses = (() => {
  const VIEW_DIRS = { top: [0, 1, 0.0001], front: [0, 0, 1], side: [1, 0, 0] };   // forge.js setView's VIEWS
  const view = () => (typeof forge !== "undefined" && forge ? forge.view : null);

  // the visible scene meshes, as forge_render.js picks them (the path tracer and the passes see the same things)
  function meshesOf(v) {
    if (window.ForgeRender && typeof window.ForgeRender.meshes === "function") {
      try { const m = window.ForgeRender.meshes(); if (m && m.length) return m; } catch (_) { /* fall through */ }
    }
    const out = [], seen = new Set();
    const shown = (o) => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
    const ok = (o) => o.isMesh && o.geometry && o.geometry.attributes.position && o.geometry.attributes.position.count &&
      o.name !== "forge-sel" && !(Array.isArray(o.material) ? o.material : [o.material]).every((m) => !m || m.wireframe || m.visible === false);
    const api = v.tree && v.tree.api;
    if (api && api.sceneNodes) {
      for (const n of api.sceneNodes()) {
        if (!n.grp || !n.visible || !shown(n.grp)) continue;
        if (api.layersTemplate && api.layersTemplate(n.id)) continue;
        n.grp.traverse((o) => { if (o.visible && ok(o) && !seen.has(o) && shown(o)) { seen.add(o); out.push(o); } });
      }
    }
    if (!out.length && v.meshObj) { const m = v.meshObj(); if (m && ok(m) && shown(m)) out.push(m); }
    return out;
  }

  // a camera of our own for the chosen Forge camera; the viewport's camera is never moved
  function passCamera(v, which, aspect) {
    const THREE = v.THREE, cur = v.camera;
    const cam = new THREE.PerspectiveCamera(cur.fov, aspect, cur.near, cur.far);
    const target = v.controls ? v.controls.target.clone() : new THREE.Vector3();
    const name = which === "current" || !which ? v.cam || "persp" : which;
    if (name === (v.cam || "persp")) {
      cam.position.copy(cur.position); cam.quaternion.copy(cur.quaternion); cam.fov = cur.fov; cam.near = cur.near; cam.far = cur.far;
    } else if (VIEW_DIRS[name]) {
      // the same framing forge.js setView uses for an orthographic view (a 1.5 degree lens from far away)
      const span = Math.max(v.size || 1, 0.2) * 1.4;
      cam.fov = 1.5;
      const d = span / Math.tan((cam.fov * Math.PI) / 360) / 2;
      cam.position.copy(target).addScaledVector(new THREE.Vector3(...VIEW_DIRS[name]).normalize(), d);
      cam.near = d / 50; cam.far = d * 50;
      cam.up.set(0, 1, 0); cam.lookAt(target);
    } else {
      // persp asked while the viewport looks through an orthographic view: Forge's default 3/4 persp direction
      const d = Math.max(v.size || 1, 0.5) * 2.3;
      cam.fov = 35;
      cam.position.copy(target).addScaledVector(new THREE.Vector3(28, 21, 28).normalize(), d);
      cam.near = d / 100; cam.far = d * 100; cam.lookAt(target);
    }
    cam.aspect = aspect; cam.updateProjectionMatrix(); cam.updateMatrixWorld(true);
    return { cam, name };
  }

  function depthRange(THREE, cam, meshes) {
    let near = Infinity, far = -Infinity;
    const inv = cam.matrixWorldInverse, p = new THREE.Vector3(), box = new THREE.Box3();
    for (const m of meshes) {
      m.updateMatrixWorld(true);
      if (!m.geometry.boundingBox) m.geometry.computeBoundingBox();
      box.copy(m.geometry.boundingBox);
      for (let i = 0; i < 8; i++) {
        p.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z)
          .applyMatrix4(m.matrixWorld).applyMatrix4(inv);
        near = Math.min(near, -p.z); far = Math.max(far, -p.z);
      }
    }
    if (!isFinite(near)) { near = cam.near; far = cam.far; }
    near = Math.max(cam.near, near); far = Math.max(near + 1e-4, far);
    return [near, far];
  }

  function materials(THREE) {
    const depth = new THREE.ShaderMaterial({
      uniforms: { uNear: { value: 0.1 }, uFar: { value: 10 } },
      vertexShader: "varying float vZ; void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); vZ = -mv.z; gl_Position = projectionMatrix * mv; }",
      fragmentShader: "uniform float uNear; uniform float uFar; varying float vZ; void main() { float t = clamp((vZ - uNear) / (uFar - uNear), 0.0, 1.0); gl_FragColor = vec4(vec3(1.0 - t), 1.0); }",
      side: THREE.DoubleSide,
    });
    const normal = new THREE.MeshNormalMaterial({ side: THREE.DoubleSide });
    return { depth, normal };
  }

  // edges where depth jumps (silhouettes, overlaps) or the normal turns (creases): white on black
  function lineArt(depthPx, normalPx, w, h, opts) {
    const out = new Uint8ClampedArray(w * h * 4);
    const dT = opts.depthEdge == null ? 0.04 : opts.depthEdge, nT = opts.normalEdge == null ? 0.35 : opts.normalEdge;
    const thick = Math.max(0, Math.min(3, Math.round(opts.lineWidth == null ? 1 : opts.lineWidth) - 1));
    const D = (x, y) => depthPx[(y * w + x) * 4] / 255;
    const N = (x, y, c) => normalPx[(y * w + x) * 4 + c] / 127.5 - 1;
    const hit = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const d = D(x, y);
      let edge = false;
      for (const [dx, dy] of [[1, 0], [0, 1]]) {
        const X = Math.min(w - 1, x + dx), Y = Math.min(h - 1, y + dy);
        const e = D(X, Y);
        if ((d > 0) !== (e > 0)) { edge = true; break; }             // object against background
        if (d > 0 && Math.abs(d - e) > dT) { edge = true; break; }  // one surface in front of another
        if (d > 0 && e > 0) {
          const dot = N(x, y, 0) * N(X, Y, 0) + N(x, y, 1) * N(X, Y, 1) + N(x, y, 2) * N(X, Y, 2);
          if (1 - dot > nT) { edge = true; break; }                  // a crease
        }
      }
      if (edge) hit[y * w + x] = 1;
    }
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      let on = hit[y * w + x];
      for (let k = 1; !on && k <= thick; k++) on = (x >= k && hit[y * w + x - k]) || (y >= k && hit[(y - k) * w + x]) || (x + k < w && hit[y * w + x + k]) || (y + k < h && hit[(y + k) * w + x]);
      const v = (on ? 255 : 0) ^ (opts.invertLine ? 255 : 0);
      const i = (y * w + x) * 4; out[i] = out[i + 1] = out[i + 2] = v; out[i + 3] = 255;
    }
    return out;
  }

  function toCanvas(px, w, h, flip) {
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const g = c.getContext("2d"), img = g.createImageData(w, h);
    if (flip) {
      for (let y = 0; y < h; y++) img.data.set(px.subarray((h - 1 - y) * w * 4, (h - y) * w * 4), y * w * 4);
    } else img.data.set(px);
    for (let i = 3; i < img.data.length; i += 4) img.data[i] = 255;
    g.putImageData(img, 0, 0);
    return c;
  }
  const flipRows = (px, w, h) => {
    const o = new Uint8Array(px.length);
    for (let y = 0; y < h; y++) o.set(px.subarray((h - 1 - y) * w * 4, (h - y) * w * 4), y * w * 4);
    return o;
  };

  // render the passes; resolves {frames: [{frame, depth, lineart, normal?, beauty?}] (canvases), width, height, camera, range, near, far}
  async function render(opts) {
    opts = Object.assign({ camera: "current", passes: ["depth", "lineart"], width: 832, height: 480, step: 1 }, opts || {});
    const v = view();
    if (!v || !v.renderer || !v.scene) throw new Error("Open Forge first: the passes are rendered from its scene.");
    const THREE = v.THREE, T = v.tree, api = T && T.api;
    const W = Math.max(16, Math.min(4096, Math.round(+opts.width || 832))), H = Math.max(16, Math.min(4096, Math.round(+opts.height || 480)));
    const want = new Set(opts.passes || []);
    if (want.has("lineart")) { want.add("depth"); }
    const t = T && T.time ? T.time : null;
    const start = Math.round(opts.start != null ? +opts.start : t ? t.start : 1);
    const end = Math.round(opts.end != null ? +opts.end : t ? t.end : start);
    const step = Math.max(1, Math.round(+opts.step || 1));
    const list = [];
    for (let f = start; f <= end && list.length < 2000; f += step) list.push(f);
    const r = v.renderer, scene = v.scene;
    // everything we touch, to put back
    const keep = {
      time: t ? { frame: t.frame, start: t.start, end: t.end, playing: t.playing } : null,
      xf: T && T.nodes ? T.nodes.map((n) => n.grp && [n, n.grp.position.clone(), n.grp.quaternion.clone(), n.grp.scale.clone()]).filter(Boolean) : [],
      override: scene.overrideMaterial, background: scene.background, target: r.getRenderTarget(),
      clear: r.getClearColor(new THREE.Color()), alpha: r.getClearAlpha(), vis: [],
    };
    const mats = materials(THREE);
    const rt = new THREE.WebGLRenderTarget(W, H, { type: THREE.UnsignedByteType });
    const rtBeauty = new THREE.WebGLRenderTarget(W, H, { type: THREE.UnsignedByteType, samples: 4 });
    const result = { frames: [], width: W, height: H, camera: null, range: { start, end, step }, near: 0, far: 0, passes: [...want] };
    let lastCam = null;
    try {
      if (t) t.playing = false;
      for (let i = 0; i < list.length; i++) {
        if (opts.signal && opts.signal.stopped) break;
        if (api && api.setFrame) { if (t) { t.start = Math.min(keep.time.start, start); t.end = Math.max(keep.time.end, end); } api.setFrame(list[i]); }
        scene.updateMatrixWorld(true);
        const meshes = meshesOf(v);
        const show = new Set();
        for (const m of meshes) for (let p = m; p; p = p.parent) show.add(p);
        // hide everything that is not a scene mesh (grid, manipulator, helpers, lights stay - they draw nothing here)
        keep.vis = [];
        scene.traverse((o) => { if (o !== scene && !show.has(o) && (o.isMesh || o.isLine || o.isLineSegments || o.isPoints || o.isSprite)) { keep.vis.push([o, o.visible]); o.visible = false; } });
        try {
          const { cam, name } = passCamera(v, opts.camera, W / H);
          result.camera = name; lastCam = cam;
          const [near, far] = depthRange(THREE, cam, meshes);
          result.near = near; result.far = far;
          scene.background = null;
          r.setClearColor(0x000000, 1);
          const read = (target) => { const px = new Uint8Array(W * H * 4); r.readRenderTargetPixels(target, 0, 0, W, H, px); return px; };
          const out = { frame: list[i] };
          let dpx = null, npx = null;
          if (want.has("depth")) {
            mats.depth.uniforms.uNear.value = near; mats.depth.uniforms.uFar.value = far;
            scene.overrideMaterial = mats.depth; r.setRenderTarget(rt); r.clear(); r.render(scene, cam);
            dpx = flipRows(read(rt), W, H); out.depth = toCanvas(dpx, W, H, false);
          }
          if (want.has("normal") || want.has("lineart")) {
            scene.overrideMaterial = mats.normal; r.setRenderTarget(rt); r.clear(); r.render(scene, cam);
            npx = flipRows(read(rt), W, H);
            if (want.has("normal")) out.normal = toCanvas(npx, W, H, false);
          }
          if (want.has("lineart")) out.lineart = toCanvas(lineArt(dpx, npx, W, H, opts), W, H, false);
          if (want.has("beauty")) {
            scene.overrideMaterial = keep.override; scene.background = keep.background;
            r.setClearColor(0x3a3d42, 1); r.setRenderTarget(rtBeauty); r.clear(); r.render(scene, cam);
            out.beauty = toCanvas(flipRows(read(rtBeauty), W, H), W, H, false);
          }
          result.frames.push(out);
        } finally {
          for (const [o, vis] of keep.vis) o.visible = vis;
          scene.overrideMaterial = keep.override; scene.background = keep.background;
          r.setRenderTarget(keep.target); r.setClearColor(keep.clear, keep.alpha);
        }
        if (typeof opts.onProgress === "function") { try { opts.onProgress((i + 1) / list.length, list[i]); } catch (_) { /* the caller's */ } }
        await new Promise((res) => setTimeout(res, 0));   // keep the window responsive
      }
    } finally {
      if (keep.time) Object.assign(t, keep.time);
      for (const [n, p, q, s] of keep.xf) { n.grp.position.copy(p); n.grp.quaternion.copy(q); n.grp.scale.copy(s); }
      if (api && api.setFrame && keep.time) api.setFrame(keep.time.frame);
      for (const [n, p, q, s] of keep.xf) { n.grp.position.copy(p); n.grp.quaternion.copy(q); n.grp.scale.copy(s); }
      if (keep.time) Object.assign(t, keep.time);
      if (T && T.syncKeys) T.syncKeys();
      rt.dispose(); rtBeauty.dispose(); mats.depth.dispose(); mats.normal.dispose();
      v.dirty = true;
    }
    result.cameraInfo = lastCam ? { fov: lastCam.fov, position: lastCam.position.toArray(), near: lastCam.near, far: lastCam.far } : null;
    return result;
  }

  const toBlob = (c) => new Promise((res) => c.toBlob((b) => res(b), "image/png"));

  // send a result's frames to a Render Studio job (POST /render/upload-pass, raw PNG bodies)
  async function upload(job, result, onProgress) {
    const tok = typeof state !== "undefined" && state ? state.token : "";
    const passes = result.passes.filter((p) => result.frames.length && result.frames[0][p]);
    const total = passes.length * result.frames.length;
    let done = 0;
    for (const p of passes) {
      for (let i = 0; i < result.frames.length; i++) {
        const blob = await toBlob(result.frames[i][p]);
        const r = await fetch("/render/upload-pass?job=" + encodeURIComponent(job) + "&pass=" + p + "&index=" + i,
          { method: "POST", headers: { Authorization: "Bearer " + tok, "Content-Type": "image/png" }, body: blob });
        const j = await r.json().catch(() => ({ ok: false, error: "bad answer" }));
        if (!j.ok) throw new Error(j.error || "upload failed");
        done++;
        if (onProgress) onProgress(done / total);
      }
    }
    return done;
  }

  // the start image from Forge's current view (what the viewport shows, without grid and manipulator)
  async function snapshot(width, height) {
    const res = await render({ camera: "current", passes: ["beauty"], width, height, start: undefined, end: undefined, step: 1, frameOnly: true,
      ...(view() && view().tree && view().tree.time ? { start: Math.round(view().tree.time.frame), end: Math.round(view().tree.time.frame) } : {}) });
    return res.frames[0] && res.frames[0].beauty;
  }

  return { render, upload, snapshot, lineArt, meshes: () => (view() ? meshesOf(view()) : []) };
})();
window.ForgePasses = ForgePasses;
