// A real 3D preview of a model in Home (owner 2026-10-26: "i want to preview them in loki as 3d assets once they are
// made i should be able to open inside forge"). Home's big preview shows a Forge model turning slowly; drag to orbit,
// scroll to zoom, double-click to open it in Forge. three.js (vendored, MIT) + its GLTFLoader + OrbitControls, the
// file from GET /forge/file/<name> with the bearer token. Falls back to the picture if WebGL or the file fails.
// One global: window.LokiModelPreview.mount(host, name, {onOpen}) -> {dispose()}.
"use strict";

const LokiModelPreview = (() => {
  let libP = null;
  function lib() {
    libP = libP || Promise.all([import("/ui/vendor/three/three.module.js"),
      import("/ui/vendor/three/addons/loaders/GLTFLoader.js"),
      import("/ui/vendor/three/addons/controls/OrbitControls.js")])
      .then(([THREE, gl, oc]) => ({ THREE, GLTFLoader: gl.GLTFLoader, OrbitControls: oc.OrbitControls }));
    return libP;
  }
  const token = () => (typeof state !== "undefined" && state && state.token) || "";

  /** Frame an object: centre it, camera distance from its bounding sphere. Pure (tests/js/test_model_preview.js). */
  function frame(box, fovDeg) {
    const c = [(box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, (box.min[2] + box.max[2]) / 2];
    const d = [box.max[0] - box.min[0], box.max[1] - box.min[1], box.max[2] - box.min[2]];
    const r = Math.max(1e-4, Math.hypot(d[0], d[1], d[2]) / 2);
    const dist = r / Math.sin((fovDeg * Math.PI) / 360) * 1.08;
    return { center: c, radius: r, distance: dist };
  }

  function mount(host, name, opts) {
    opts = opts || {};
    let alive = true, raf = 0, renderer = null, controls = null, ro = null;
    const api = { dispose() {
      alive = false; cancelAnimationFrame(raf);
      if (ro) ro.disconnect();
      if (controls) controls.dispose();
      if (renderer) { renderer.dispose(); renderer.forceContextLoss && renderer.forceContextLoss(); renderer.domElement.remove(); }
    } };
    (async () => {
      let L;
      try { L = await lib(); } catch (_) { return; }
      const resp = await fetch("/forge/file/" + encodeURIComponent(name), { headers: { Authorization: "Bearer " + token() } }).catch(() => null);
      if (!alive || !resp || !resp.ok) return;
      const buf = await resp.arrayBuffer();
      if (!alive) return;
      const { THREE } = L;
      let gltf;
      try { gltf = await new L.GLTFLoader().parseAsync(buf, ""); } catch (_) { return; }
      if (!alive) return;
      try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); } catch (_) { return; }
      renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.NeutralToneMapping || THREE.ACESFilmicToneMapping;
      const scene = new THREE.Scene();
      scene.add(new THREE.HemisphereLight(0xffffff, 0x30343c, 1.6));
      const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(3, 5, 4); scene.add(key);
      const rim = new THREE.DirectionalLight(0xbfd4ff, 1.0); rim.position.set(-4, 3, -3); scene.add(rim);
      const model = gltf.scene;
      scene.add(model);
      const box = new THREE.Box3().setFromObject(model);
      const f = frame({ min: box.min.toArray(), max: box.max.toArray() }, 35);
      model.position.sub(new THREE.Vector3(...f.center));
      const cam = new THREE.PerspectiveCamera(35, 1, f.radius / 100, f.distance * 20);
      cam.position.set(f.distance * 0.75, f.distance * 0.35, f.distance * 0.75);
      controls = new L.OrbitControls(cam, renderer.domElement);
      controls.enableDamping = true; controls.autoRotate = true; controls.autoRotateSpeed = 1.2;
      controls.minDistance = f.radius * 0.4; controls.maxDistance = f.distance * 6;
      controls.addEventListener("start", () => { controls.autoRotate = false; });
      const mixer = gltf.animations && gltf.animations.length ? new THREE.AnimationMixer(model) : null;
      if (mixer) mixer.clipAction(gltf.animations[0]).play();
      const clock = new THREE.Clock();
      const cv = renderer.domElement; cv.className = "mp-canvas";
      cv.title = "Drag to turn it, scroll to zoom - double-click opens it in Forge";
      cv.addEventListener("dblclick", () => { if (opts.onOpen) opts.onOpen(); });
      host.querySelectorAll("img, svg").forEach((x) => { x.style.visibility = "hidden"; });
      host.append(cv);
      host.classList.add("mp-live");
      const size = () => {
        const w = Math.max(1, host.clientWidth), h = Math.max(1, host.clientHeight);
        renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix();
      };
      size();
      ro = new ResizeObserver(size); ro.observe(host);
      const tick = () => {
        if (!alive) return;
        if (!host.isConnected) { api.dispose(); return; }
        const dt = clock.getDelta();
        if (mixer) mixer.update(dt);
        controls.update();
        renderer.render(scene, cam);
        raf = requestAnimationFrame(tick);
      };
      tick();
      host.dataset.mpReady = "1";
      if (opts.onReady) opts.onReady({ triangles: countTris(model) });
    })();
    return api;
  }

  function countTris(root) {
    let n = 0;
    root.traverse((o) => { if (o.isMesh && o.geometry) n += (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count) / 3; });
    return Math.round(n);
  }

  const out = { mount, frame };
  if (typeof window !== "undefined") window.LokiModelPreview = out;
  return out;
})();
if (typeof module !== "undefined") module.exports = LokiModelPreview;
