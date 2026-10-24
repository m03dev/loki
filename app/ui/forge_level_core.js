// Forge's Level workspace, the engine side (owner 2026-10-24: "forge as an editor ... close to unreal engine").
// No DOM in this file, so it runs the same in LOKI's window and in node (tests/js/test_forge_level.js).
//
//   actors      Unreal's "Place Actors": Empty, Point/Directional/Spot Light, Camera, Player Start, Trigger Box.
//               Any Forge object becomes an actor once it gets scripts. Actor data lives in
//               object.userData.loki, so it survives Forge's own .glb save (glTF "extras").
//   levels      save / open a level as JSON ("loki-level" v1): actors, transforms, props, scripts, asset paths.
//   scripts     the three.js editor's model (MIT, mrdoob/three.js editor/js/libs/app.js): each script defines
//               start / update(dt) / stop / keydown / keyup / pointerdown / beginOverlap / endOverlap with
//               `this` = the actor. A script that throws is switched off and reported - Play never crashes the editor.
//   world       (owner 2026-10-24: "its gonna be an rpg like world of warcraft") Terrain you sculpt and paint
//               (heights + colours stored in the level), Creature Spawns that wander and, when hostile, chase.
//   play        Play in Editor (possess the Player Start) and Simulate (scripts run, editor camera stays).
//               Third person by default, WoW controls: right-drag turns, left-drag orbits the camera, wheel
//               zooms, W/S move, A/D turn (strafe while right-dragging), Q/E strafe, Space jumps, feet on the ground.
//               Stop puts every object back exactly as it was: transforms, visibility, props, spawned and
//               destroyed actors.
"use strict";

(function (root) {
  const FORMAT = "loki-level";
  const VERSION = 1;
  const EVENTS = ["start", "update", "stop", "keydown", "keyup", "pointerdown", "beginOverlap", "endOverlap"];

  // ---------------------------------------------------------------------- actor types
  // make(THREE, props) -> Object3D. editorOnly children are hidden while playing.
  const ACTORS = {
    empty: {
      label: "Empty Actor", icon: "empty", group: "Basic",
      what: "An empty transform: a parent, a spawn point or a holder for scripts.",
      props: {},
      make: () => null,
    },
    pointLight: {
      label: "Point Light", icon: "bulb", group: "Lights",
      what: "Light from one point in every direction, fading with distance.",
      props: { color: "#ffffff", intensity: 20, distance: 0 },
      make: (T, p) => new T.PointLight(p.color, p.intensity, p.distance),
      apply: (o, p) => { o.color.set(p.color); o.intensity = p.intensity; o.distance = p.distance; },
    },
    dirLight: {
      label: "Directional Light", icon: "sun", group: "Lights",
      what: "Sunlight: parallel rays from one direction, no falloff.",
      props: { color: "#ffffff", intensity: 2 },
      make: (T, p) => new T.DirectionalLight(p.color, p.intensity),
      apply: (o, p) => { o.color.set(p.color); o.intensity = p.intensity; },
    },
    spotLight: {
      label: "Spot Light", icon: "spot", group: "Lights",
      what: "A cone of light, like a torch or a stage light.",
      props: { color: "#ffffff", intensity: 30, angle: 35, distance: 0 },
      make: (T, p) => new T.SpotLight(p.color, p.intensity, p.distance, (p.angle * Math.PI) / 180),
      apply: (o, p) => { o.color.set(p.color); o.intensity = p.intensity; o.distance = p.distance; o.angle = (p.angle * Math.PI) / 180; },
    },
    camera: {
      label: "Camera Actor", icon: "camera", group: "Basic",
      what: "A camera scripts can switch to (level.viewFrom(actor)).",
      props: { fov: 50 },
      make: (T, p) => new T.PerspectiveCamera(p.fov, 16 / 9, 0.05, 2000),
      apply: (o, p) => { o.fov = p.fov; o.updateProjectionMatrix && o.updateProjectionMatrix(); },
    },
    playerStart: {
      label: "Player Start", icon: "person", group: "Basic",
      what: "Where Play puts you. Third person (WoW controls), first-person walk, or fly.",
      props: { speed: 5, eyeHeight: 1.7, mode: "third", jump: 6, camDist: 7 },
      make: (T) => {
        const g = new T.Group();
        g.userData.lokiEditorOnly = true; // the whole marker is a gizmo
        const body = new T.Mesh(new T.CylinderGeometry(0.35, 0.35, 1.8, 16),
          new T.MeshBasicMaterial({ color: 0x4fa3ff, wireframe: true }));
        body.position.y = 0.9;
        const nose = new T.Mesh(new T.ConeGeometry(0.15, 0.4, 12), new T.MeshBasicMaterial({ color: 0x4fa3ff }));
        nose.rotation.x = -Math.PI / 2; nose.position.set(0, 1.5, -0.5);
        g.add(body, nose);
        return g;
      },
    },
    triggerBox: {
      label: "Trigger Box", icon: "trigger", group: "Volumes",
      what: "An invisible box that tells scripts when the player (or an actor tagged overlap) enters and leaves.",
      props: { size: [2, 2, 2] },
      make: (T, p) => {
        // a Group around the wire box: Forge's modelling tools only edit a node's MESH named "shape", never a gizmo
        const g = new T.Group();
        const m = new T.Mesh(new T.BoxGeometry(1, 1, 1),
          new T.MeshBasicMaterial({ color: 0x3ddc84, wireframe: true, transparent: true, opacity: 0.6 }));
        m.scale.set(p.size[0], p.size[1], p.size[2]);
        g.userData.lokiEditorOnly = true; // the box itself is a gizmo; the actor is the volume
        g.add(m);
        return g;
      },
      apply: (o, p) => o.children[0] && o.children[0].scale.set(p.size[0], p.size[1], p.size[2]),
    },
    terrain: {
      label: "Terrain", icon: "level", group: "World",
      what: "Ground you sculpt (raise, lower, smooth, flatten) and paint (grass, dirt, rock, snow). Play walks on it.",
      props: { size: 128, res: 64, heights: "", colors: "" },
      make: (T, p) => {
        const g = new T.Group();
        const m = new T.Mesh(new T.BufferGeometry(), new T.MeshStandardMaterial({ vertexColors: true, roughness: 0.95, metalness: 0 }));
        m.name = "terrain"; m.receiveShadow = true;
        g.add(m);
        buildTerrain(T, g, p);
        return g;
      },
      apply: (o, p) => { const T = o.userData.__T; if (T) buildTerrain(T, o, p); },
    },
    npcSpawn: {
      label: "Creature Spawn", icon: "person", group: "World",
      what: "Creatures appear here in Play and wander inside the ring; hostile ones chase you when you come close.",
      props: { creature: "Wolf", level: 1, hostile: true, count: 3, wander: 6, speed: 2.5, aggro: 9, color: "#b5452f" },
      make: (T, p) => {
        const g = new T.Group();
        g.userData.lokiEditorOnly = true;
        const ring = new T.Mesh(new T.RingGeometry(0.97, 1, 48), new T.MeshBasicMaterial({ color: p.color, side: T.DoubleSide, transparent: true, opacity: 0.8 }));
        ring.rotation.x = -Math.PI / 2; ring.position.y = 0.05; ring.scale.setScalar(p.wander);
        const pin = new T.Mesh(new T.ConeGeometry(0.3, 0.8, 10), new T.MeshBasicMaterial({ color: p.color }));
        pin.rotation.x = Math.PI; pin.position.y = 1.2;
        g.add(ring, pin);
        return g;
      },
      apply: (o, p) => { const [ring, pin] = o.children; if (ring) { ring.scale.setScalar(p.wander); ring.material.color.set(p.color); } if (pin) pin.material.color.set(p.color); },
    },
  };

  // ---------------------------------------------------------------------- terrain
  // A height grid of (res+1)^2 vertices over size x size metres, centred on the actor. Heights (float32) and colours
  // (rgb bytes) live in props as base64 so the level file carries them; the decoded arrays sit on the visual.
  const PAINT = { grass: "#4f7a32", dirt: "#7a5a3a", rock: "#7d7d7a", snow: "#eef2f5", sand: "#c9b27c" };
  const b64 = {
    enc(bytes) {
      if (typeof Buffer !== "undefined") return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString("base64");
      let s = ""; for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      return btoa(s);
    },
    dec(str) {
      if (typeof Buffer !== "undefined") { const b = Buffer.from(str, "base64"); return new Uint8Array(b.buffer, b.byteOffset, b.byteLength); }
      const s = atob(str), out = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i); return out;
    },
  };

  function terrainArrays(p) {
    const n = (p.res + 1) * (p.res + 1);
    let h = null, c = null;
    try { if (p.heights) { const raw = b64.dec(p.heights); if (raw.length === n * 4) h = new Float32Array(raw.slice().buffer); } } catch (_) { h = null; }
    try { if (p.colors) { const raw = b64.dec(p.colors); if (raw.length === n * 3) c = raw.slice(); } } catch (_) { c = null; }
    if (!h) h = new Float32Array(n);
    if (!c) { c = new Uint8Array(n * 3); const g = hexRgb(PAINT.grass); for (let i = 0; i < n; i++) c.set(g, i * 3); }
    return { h, c };
  }
  function hexRgb(hex) { const v = parseInt(String(hex).replace("#", ""), 16); return [(v >> 16) & 255, (v >> 8) & 255, v & 255]; }

  function buildTerrain(T, vis, p) {
    vis.userData.__T = T;
    const res = Math.max(4, Math.min(256, p.res | 0)), size = +p.size || 128;
    p.res = res;
    const { h, c } = vis.userData.__terrain && vis.userData.__terrain.res === res && !p.__reload ? vis.userData.__terrain : terrainArrays(p);
    delete p.__reload;
    const mesh = vis.getObjectByName("terrain");
    const geo = new T.PlaneGeometry(size, size, res, res);
    geo.rotateX(-Math.PI / 2);
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) pos.setY(i, h[i]);
    const col = new Float32Array(pos.count * 3);
    for (let i = 0; i < col.length; i++) col[i] = c[i] / 255;
    geo.setAttribute("color", new T.BufferAttribute(col, 3));
    geo.computeVertexNormals();
    if (mesh.geometry) mesh.geometry.dispose();
    mesh.geometry = geo;
    vis.userData.__terrain = { res, size, h, c };
  }

  // the terrain actors' data: [{ obj, vis, t }]
  function terrains(scene) {
    const out = [];
    for (const o of actors(scene)) {
      if (actorOf(o).actor !== "terrain") continue;
      const vis = visualOf(o);
      if (vis && vis.userData.__terrain && o.parent) out.push({ obj: o, vis, t: vis.userData.__terrain });
    }
    return out;
  }

  // world point -> terrain grid coordinates (fractional), or null when outside
  function gridOf(T, item, x, z) {
    item.vis.updateWorldMatrix(true, false);
    const local = new T.Vector3(x, 0, z).applyMatrix4(new T.Matrix4().copy(item.vis.matrixWorld).invert());
    const { res, size } = item.t;
    const gx = (local.x / size + 0.5) * res, gz = (local.z / size + 0.5) * res;
    if (gx < 0 || gz < 0 || gx > res || gz > res) return null;
    return { gx, gz, local };
  }

  // The ground height under (x, z): the highest terrain there, or null when no terrain covers it.
  function heightAt(T, scene, x, z, list) {
    let best = null;
    for (const item of list || terrains(scene)) {
      const g = gridOf(T, item, x, z); if (!g) continue;
      const { res, h } = item.t, n = res + 1;
      const x0 = Math.min(res - 1, Math.floor(g.gx)), z0 = Math.min(res - 1, Math.floor(g.gz));
      const fx = g.gx - x0, fz = g.gz - z0;
      const at = (i, j) => h[j * n + i];
      const hy = (at(x0, z0) * (1 - fx) + at(x0 + 1, z0) * fx) * (1 - fz) + (at(x0, z0 + 1) * (1 - fx) + at(x0 + 1, z0 + 1) * fx) * fz;
      const wy = new T.Vector3(g.local.x, hy, g.local.z).applyMatrix4(item.vis.matrixWorld).y;
      if (best === null || wy > best) best = wy;
    }
    return best;
  }

  // One brush dab at a world point. mode: raise | lower | smooth | flatten | paint. Returns vertices changed.
  function sculpt(T, terrainObj, point, brush) {
    const vis = visualOf(terrainObj); if (!vis || !vis.userData.__terrain) return 0;
    const item = { obj: terrainObj, vis, t: vis.userData.__terrain };
    const g = gridOf(T, item, point.x, point.z);
    const { res, size, h, c } = item.t, n = res + 1, cell = size / res;
    const lx = g ? g.local.x : new T.Vector3(point.x, 0, point.z).applyMatrix4(new T.Matrix4().copy(vis.matrixWorld).invert()).x;
    const lz = g ? g.local.z : new T.Vector3(point.x, 0, point.z).applyMatrix4(new T.Matrix4().copy(vis.matrixWorld).invert()).z;
    const r = Math.max(cell * 0.5, +brush.radius || 4), str = +brush.strength || 0.5;
    const i0 = Math.max(0, Math.floor(((lx - r) / size + 0.5) * res)), i1 = Math.min(res, Math.ceil(((lx + r) / size + 0.5) * res));
    const j0 = Math.max(0, Math.floor(((lz - r) / size + 0.5) * res)), j1 = Math.min(res, Math.ceil(((lz + r) / size + 0.5) * res));
    const rgb = brush.mode === "paint" ? hexRgb(PAINT[brush.color] || brush.color || PAINT.grass) : null;
    const target = brush.mode === "flatten" ? (brush.height != null ? brush.height : heightAt(T, null, point.x, point.z, [item]) || 0) : 0;
    const old = brush.mode === "smooth" ? h.slice() : null;
    let changed = 0;
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
      const vx = (i / res - 0.5) * size, vz = (j / res - 0.5) * size;
      const d = Math.hypot(vx - lx, vz - lz); if (d > r) continue;
      const f = 0.5 + 0.5 * Math.cos(Math.PI * d / r);           // smooth falloff 1 -> 0
      const k = j * n + i;
      if (brush.mode === "raise") h[k] += str * f;
      else if (brush.mode === "lower") h[k] -= str * f;
      else if (brush.mode === "flatten") h[k] += (target - h[k]) * Math.min(1, str * f);
      else if (brush.mode === "smooth") {
        let s = 0, m = 0;
        for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
          const ii = i + di, jj = j + dj; if (ii < 0 || jj < 0 || ii > res || jj > res) continue;
          s += old[jj * n + ii]; m++;
        }
        h[k] += (s / m - h[k]) * Math.min(1, str * f);
      } else if (rgb) {
        const w = Math.min(1, str * f);
        for (let q = 0; q < 3; q++) c[k * 3 + q] = Math.round(c[k * 3 + q] + (rgb[q] - c[k * 3 + q]) * w);
      } else continue;
      changed++;
    }
    if (changed) {
      const mesh = vis.getObjectByName("terrain"), pos = mesh.geometry.attributes.position, col = mesh.geometry.attributes.color;
      for (let k = 0; k < pos.count; k++) { pos.setY(k, h[k]); col.setXYZ(k, c[k * 3] / 255, c[k * 3 + 1] / 255, c[k * 3 + 2] / 255); }
      pos.needsUpdate = true; col.needsUpdate = true;
      if (brush.mode !== "paint") { mesh.geometry.computeVertexNormals(); mesh.geometry.computeBoundingSphere(); mesh.geometry.computeBoundingBox(); }
    }
    return changed;
  }

  // Write a terrain's live arrays back into its props (before saving the level).
  function commitTerrain(terrainObj) {
    const a = actorOf(terrainObj), vis = visualOf(terrainObj);
    if (!a || !vis || !vis.userData.__terrain) return;
    const { h, c } = vis.userData.__terrain;
    a.props.heights = b64.enc(new Uint8Array(h.buffer, h.byteOffset, h.byteLength));
    a.props.colors = b64.enc(c);
  }

  // A seeded random (creature wandering is the same every Play with the same seed - tests rely on it)
  function rng(seed) { let s = (seed >>> 0) || 1; return () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }

  const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));

  function actorOf(obj) {
    return (obj && obj.userData && obj.userData.loki) || null;
  }

  function isActor(obj) {
    return !!actorOf(obj);
  }

  // Ensure `obj` carries actor data (any Forge mesh can become a "mesh" actor).
  function makeActor(obj, type) {
    obj.userData = obj.userData || {};
    if (!obj.userData.loki) {
      const def = ACTORS[type];
      obj.userData.loki = { actor: type || "mesh", props: clone(def ? def.props : {}) || {}, scripts: [], tags: [] };
    }
    return obj.userData.loki;
  }

  // An actor is a Group carrying userData.loki (its transform is the actor's), with its visual - the light, the
  // camera, the gizmo - as a child named "shape" (Forge's own node layout: node.grp > node.inner > "shape").
  function createActor(T, type, opts) {
    const def = ACTORS[type];
    if (!def) throw new Error("unknown actor type " + type);
    opts = opts || {};
    const props = Object.assign(clone(def.props), opts.props || {});
    const obj = new T.Group();
    const vis = def.make(T, props);
    if (vis) { vis.name = "shape"; obj.add(vis); }
    obj.name = opts.name || def.label;
    if (opts.position) obj.position.set(opts.position[0], opts.position[1], opts.position[2]);
    obj.userData.loki = { actor: type, props, scripts: clone(opts.scripts) || [], tags: clone(opts.tags) || [] };
    if (opts.asset) obj.userData.loki.asset = opts.asset;
    return obj;
  }

  // the visual of an actor (a light, a camera, a gizmo, a mesh) - the first descendant named "shape"
  function visualOf(obj) {
    return (obj && obj.getObjectByName && obj.getObjectByName("shape")) || null;
  }

  // Forge wraps a visual its own way: give `holder` (the node's group) the actor data and put the visual in `into`.
  function adoptActor(T, type, holder, into, opts) {
    const a = createActor(T, type, opts);
    const vis = visualOf(a);
    if (vis) (into || holder).add(vis);
    holder.userData.loki = a.userData.loki;
    return holder;
  }

  function applyProps(obj) {
    const a = actorOf(obj);
    const def = a && ACTORS[a.actor];
    const vis = visualOf(obj);
    if (def && def.apply && vis) def.apply(vis, a.props);
  }

  function actors(scene) {
    const out = [];
    scene.traverse((o) => { if (o !== scene && isActor(o)) out.push(o); });
    return out;
  }

  // ---------------------------------------------------------------------- level files
  function serialize(scene, meta) {
    const list = actors(scene);
    for (const o of list) if (actorOf(o).actor === "terrain") commitTerrain(o);
    const ids = new Map(list.map((o, i) => [o, i + 1]));
    const parentId = (o) => {
      for (let p = o.parent; p && p !== scene; p = p.parent) if (ids.has(p)) return ids.get(p);
      return 0;
    };
    return {
      format: FORMAT, version: VERSION, meta: Object.assign({ saved: new Date().toISOString() }, meta || {}),
      actors: list.map((o) => {
        const a = actorOf(o);
        return {
          id: ids.get(o), parent: parentId(o), name: o.name, type: a.actor,
          position: o.position.toArray(), quaternion: o.quaternion.toArray(), scale: o.scale.toArray(),
          visible: o.visible, props: clone(a.props) || {}, scripts: clone(a.scripts) || [], tags: clone(a.tags) || [],
          asset: a.asset || null,
        };
      }),
    };
  }

  // load(json, scene, T, { loadAsset(path) -> Promise<Object3D> }) -> Promise<Object3D[]>
  // Mesh actors come back through loadAsset (Forge's own loader); without one they become a placeholder Empty.
  async function load(doc, scene, T, opts) {
    if (!doc || doc.format !== FORMAT) throw new Error("not a LOKI level file");
    if (doc.version > VERSION) throw new Error("level was saved by a newer LOKI (v" + doc.version + ")");
    opts = opts || {};
    const byId = new Map(), made = [];
    for (const rec of doc.actors) {
      let obj;
      if (ACTORS[rec.type]) obj = createActor(T, rec.type, { props: clone(rec.props) });
      else {
        obj = new T.Group();
        const vis = rec.asset && opts.loadAsset ? await opts.loadAsset(rec.asset) : null;
        if (vis) { vis.name = "shape"; obj.add(vis); }
      }
      obj.name = rec.name;
      obj.position.fromArray(rec.position); obj.quaternion.fromArray(rec.quaternion); obj.scale.fromArray(rec.scale);
      obj.visible = rec.visible !== false;
      obj.userData.loki = { actor: rec.type, props: clone(rec.props) || {}, scripts: clone(rec.scripts) || [], tags: clone(rec.tags) || [] };
      if (rec.asset) obj.userData.loki.asset = rec.asset;
      applyProps(obj);
      byId.set(rec.id, obj);
      made.push([rec, obj]);
    }
    for (const [rec, obj] of made) (byId.get(rec.parent) || scene).add(obj);
    return made.map((m) => m[1]);
  }

  // ---------------------------------------------------------------------- scripts
  const TEMPLATE = [
    "// `this` is the actor. Use only the events you need.",
    "function start() {",
    "  this.userData.spin = 1.5;",
    "}",
    "function update(dt) {",
    "  this.rotation.y += this.userData.spin * dt;",
    "}",
    "function beginOverlap(other) {",
    "  level.log(other.name + ' entered ' + this.name);",
    "}",
  ].join("\n");

  const PARAMS = ["THREE", "scene", "level", "input", "camera"];

  function compileScript(source) {
    try {
      const body = source + "\nreturn {" + EVENTS.map((e) => e + ": typeof " + e + " === 'function' ? " + e + " : undefined").join(", ") + "};";
      return { factory: new Function(...PARAMS, body), error: null };
    } catch (e) {
      return { factory: null, error: e.message };
    }
  }

  // Checks every script on every actor without running Play. -> [{actor, script, error}]
  function checkScripts(scene) {
    const problems = [];
    for (const o of actors(scene)) {
      for (const s of actorOf(o).scripts || []) {
        const r = compileScript(s.source || "");
        if (r.error) problems.push({ actor: o.name, script: s.name, error: r.error });
      }
    }
    return problems;
  }

  // ---------------------------------------------------------------------- play
  // new Session(T, scene, { possess, editorCamera, aspect, onLog, onError })
  function Session(T, scene, opts) {
    opts = opts || {};
    const self = this;
    const handlers = {}; EVENTS.forEach((e) => (handlers[e] = []));
    const keys = new Set();
    const spawned = [];
    let snapshot = null, running = false, time = 0;
    let player = null, playerCam = null, yaw = 0, pitch = 0, viewCam = null;
    const overlaps = new Map(); // trigger -> Set(actor)
    const box = new T.Box3(), pt = new T.Vector3(), fwd = new T.Vector3(), right = new T.Vector3();

    self.errors = []; self.logs = [];
    self.possess = opts.possess !== false;
    Object.defineProperties(self, {
      running: { get: () => running },
      time: { get: () => time },
      camera: { get: () => viewCam || playerCam || opts.editorCamera || null },
      player: { get: () => player },
    });

    const log = (msg) => { self.logs.push(String(msg)); if (opts.onLog) opts.onLog(String(msg)); };
    const report = (actor, script, where, err) => {
      const e = { actor: actor.name, script, where, error: (err && err.message) || String(err) };
      self.errors.push(e);
      if (opts.onError) opts.onError(e);
    };

    const input = {
      down: (k) => keys.has(String(k).toLowerCase()),
      get keys() { return Array.from(keys); },
    };

    const level = {
      log,
      get time() { return time; },
      get player() { return player; },
      find: (name) => scene.getObjectByName(name) || null,
      findTagged: (tag) => actors(scene).filter((o) => (actorOf(o).tags || []).includes(tag)),
      spawn: (type, o) => {
        const obj = createActor(T, type, o || {});
        scene.add(obj); spawned.push(obj); bindScripts(obj); fire(obj, "start");
        return obj;
      },
      destroy: (obj) => { if (obj && obj.parent) { fire(obj, "stop"); obj.parent.remove(obj); } },
      viewFrom: (cam) => { const c = cam && (cam.isCamera ? cam : visualOf(cam)); viewCam = c && c.isCamera ? c : null; },
      stop: () => self.stop(),
    };
    self.level = level;

    function bindScripts(obj) {
      const a = actorOf(obj);
      obj.userData.__lokiFns = [];
      for (const s of (a && a.scripts) || []) {
        if (s.enabled === false) continue;
        const c = compileScript(s.source || "");
        if (c.error) { report(obj, s.name, "compile", c.error); continue; }
        let fns;
        try { fns = c.factory.call(obj, T, scene, level, input, self.camera); }
        catch (e) { report(obj, s.name, "load", e); continue; }
        for (const ev of EVENTS) {
          if (!fns[ev]) continue;
          const entry = { obj, script: s.name, ev, fn: fns[ev], dead: false };
          handlers[ev].push(entry); obj.userData.__lokiFns.push(entry);
        }
      }
    }

    function call(entry, args) {
      if (entry.dead || !entry.obj.parent) return;
      try { entry.fn.apply(entry.obj, args); }
      catch (e) { entry.dead = true; report(entry.obj, entry.script, entry.ev, e); }
    }

    function fire(obj, ev, args) {
      for (const h of handlers[ev]) if (h.obj === obj) call(h, args || []);
    }

    function dispatch(ev, args) {
      for (const h of handlers[ev].slice()) call(h, args || []);
    }

    function takeSnapshot() {
      const items = [];
      scene.traverse((o) => {
        if (o === scene) return;
        items.push({
          o, parent: o.parent, index: o.parent ? o.parent.children.indexOf(o) : 0,
          p: o.position.clone(), q: o.quaternion.clone(), s: o.scale.clone(), v: o.visible,
          ud: Object.assign({}, o.userData, { loki: clone(o.userData.loki) }),
        });
      });
      return items;
    }

    function restore(items) {
      for (const obj of spawned) if (obj.parent) obj.parent.remove(obj);
      for (const it of items) {
        if (it.o.parent !== it.parent) { if (it.o.parent) it.o.parent.remove(it.o); it.parent.add(it.o); }
      }
      for (const it of items) {
        const kids = it.parent.children, at = kids.indexOf(it.o);
        if (at !== it.index && at >= 0 && it.index < kids.length) { kids.splice(at, 1); kids.splice(it.index, 0, it.o); }
        it.o.position.copy(it.p); it.o.quaternion.copy(it.q); it.o.scale.copy(it.s); it.o.visible = it.v;
        it.o.userData = it.ud;
        applyProps(it.o);
      }
    }

    // ---- the player: third person (WoW) by default, or first-person walk / fly
    let mode = "third", camYaw = 0, camPitch = -0.35, camDist = 7, vy = 0, onGround = true, rmb = false;
    let world = [];             // the terrains, looked up once per Play
    const camTarget = new T.Vector3(), camPos = new T.Vector3();
    function groundAt(x, z, fallback) { const h = heightAt(T, scene, x, z, world); return h === null ? fallback : h; }

    function makePlayer() {
      const start = actors(scene).find((o) => actorOf(o).actor === "playerStart");
      const props = Object.assign(clone(ACTORS.playerStart.props), start ? actorOf(start).props : {});
      player = new T.Group(); player.name = "Player";
      player.userData.loki = { actor: "player", props, scripts: [], tags: ["overlap"] };
      const sp = new T.Vector3(), sq = new T.Quaternion();
      if (start) { start.getWorldPosition(sp); start.getWorldQuaternion(sq); }
      player.userData.baseY = sp.y;
      const g = groundAt(sp.x, sp.z, null); if (g !== null && g > sp.y) sp.y = g;
      player.position.copy(sp);
      yaw = new T.Euler().setFromQuaternion(sq, "YXZ").y; pitch = 0;
      mode = props.mode === "walk" || props.mode === "fly" ? props.mode : "third";
      camYaw = yaw; camPitch = -0.35; camDist = +props.camDist || 7; vy = 0; onGround = true;
      playerCam = new T.PerspectiveCamera(70, opts.aspect || 16 / 9, 0.05, 4000);
      if (mode === "third") {
        const body = new T.Mesh(new T.CapsuleGeometry(0.35, 1.1, 6, 14), new T.MeshStandardMaterial({ color: 0x3b6fd6, roughness: 0.6 }));
        body.position.y = 0.9; body.name = "body";
        const nose = new T.Mesh(new T.ConeGeometry(0.12, 0.35, 10), new T.MeshStandardMaterial({ color: 0xf2c14e }));
        nose.rotation.x = -Math.PI / 2; nose.position.set(0, 1.45, -0.38);
        player.add(body, nose);
        scene.add(playerCam); spawned.push(playerCam);
      } else {
        playerCam.position.y = props.eyeHeight;
        player.add(playerCam);
      }
      scene.add(player); spawned.push(player);
      placeCamera();
    }

    function placeCamera() {
      if (!player || mode !== "third") return;
      const p = actorOf(player).props;
      camTarget.copy(player.position); camTarget.y += 1.6;
      const cp = Math.cos(camPitch);
      camPos.set(Math.sin(camYaw) * cp, -Math.sin(camPitch), Math.cos(camYaw) * cp).multiplyScalar(camDist).add(camTarget);
      const gy = groundAt(camPos.x, camPos.z, -Infinity);
      if (camPos.y < gy + 0.4) camPos.y = gy + 0.4;            // never under the ground
      playerCam.position.copy(camPos);
      playerCam.lookAt(camTarget);
      void p;
    }

    function movePlayer(dt) {
      if (!player) return;
      const p = actorOf(player).props;
      const run = p.speed * (input.down("shift") ? 2 : 1);
      if (mode === "third") {
        // WoW: A / D turn (strafe while the right button is held), Q / E strafe, W / S forward / back (back is slower)
        if (!rmb) { if (input.down("a")) { yaw += 2.6 * dt; camYaw += 2.6 * dt; } if (input.down("d")) { yaw -= 2.6 * dt; camYaw -= 2.6 * dt; } }
        fwd.set(-Math.sin(yaw), 0, -Math.cos(yaw)); right.set(Math.cos(yaw), 0, -Math.sin(yaw));
        const mv = new T.Vector3();
        if (input.down("w") || (rmb && input.down("lmb"))) mv.add(fwd);
        if (input.down("s")) mv.addScaledVector(fwd, -0.65);
        if (input.down("e") || (rmb && input.down("d"))) mv.add(right);
        if (input.down("q") || (rmb && input.down("a"))) mv.sub(right);
        if (mv.lengthSq() > 1) mv.normalize();
        player.position.addScaledVector(mv, run * dt);
        player.rotation.set(0, yaw, 0);
      } else {
        player.rotation.set(0, yaw, 0); playerCam.rotation.set(pitch, 0, 0, "YXZ");
        fwd.set(-Math.sin(yaw), 0, -Math.cos(yaw)); right.set(Math.cos(yaw), 0, -Math.sin(yaw));
        const step = run * dt;
        if (input.down("w")) player.position.addScaledVector(fwd, step);
        if (input.down("s")) player.position.addScaledVector(fwd, -step);
        if (input.down("d")) player.position.addScaledVector(right, step);
        if (input.down("a")) player.position.addScaledVector(right, -step);
        if (mode === "fly") {
          if (input.down("e")) player.position.y += step;
          if (input.down("q")) player.position.y -= step;
          return;
        }
      }
      // gravity, jumping, feet on the terrain (or on the Player Start's height where there is no terrain)
      const ground = groundAt(player.position.x, player.position.z, player.userData.baseY);
      if (input.down(" ") && onGround) { vy = +p.jump || 6; onGround = false; }
      vy -= 20 * dt;
      player.position.y += vy * dt;
      if (player.position.y <= ground) { player.position.y = ground; vy = 0; onGround = true; }
      placeCamera();
    }

    // ---- creatures (Creature Spawn actors)
    const creatures = [];
    const random = rng(opts.seed || 1234567);
    function spawnCreatures() {
      for (const sp of actors(scene).filter((o) => actorOf(o).actor === "npcSpawn" && o.parent)) {
        const p = Object.assign(clone(ACTORS.npcSpawn.props), actorOf(sp).props);
        const home = sp.getWorldPosition(new T.Vector3());
        for (let i = 0; i < Math.max(0, Math.min(50, p.count | 0)); i++) {
          const c = new T.Group(); c.name = p.creature + (p.count > 1 ? " " + (i + 1) : "");
          const body = new T.Mesh(new T.CapsuleGeometry(0.35, 0.7, 5, 10), new T.MeshStandardMaterial({ color: p.color, roughness: 0.7 }));
          body.rotation.z = Math.PI / 2; body.position.y = 0.55;
          const head = new T.Mesh(new T.SphereGeometry(0.28, 10, 8), new T.MeshStandardMaterial({ color: p.color, roughness: 0.7 }));
          head.position.set(0, 0.8, -0.65);
          c.add(body, head);
          const a = random() * Math.PI * 2, r = Math.sqrt(random()) * p.wander;
          c.position.set(home.x + Math.cos(a) * r, 0, home.z + Math.sin(a) * r);
          c.position.y = groundAt(c.position.x, c.position.z, home.y);
          c.userData.loki = { actor: "creature", props: { creature: p.creature, level: p.level, hostile: !!p.hostile }, scripts: [], tags: ["overlap", "creature"] };
          scene.add(c); spawned.push(c);
          creatures.push({ obj: c, p, home, target: null, wait: random() * 2, state: "idle" });
        }
      }
    }
    function moveCreatures(dt) {
      for (const cr of creatures) {
        const o = cr.obj; if (!o.parent) continue;
        const toPlayer = player ? player.position.distanceTo(o.position) : Infinity;
        const fromHome = o.position.distanceTo(cr.home);
        if (cr.p.hostile && player && (cr.state === "chase" ? toPlayer < cr.p.aggro * 2.5 && fromHome < cr.p.wander + 30 : toPlayer < cr.p.aggro)) {
          if (cr.state !== "chase") { cr.state = "chase"; log(o.name + " attacks!"); }
          cr.target = toPlayer > 1.6 ? player.position.clone() : null;
        } else if (cr.state === "chase") {
          cr.state = "return"; cr.target = cr.home.clone();                   // leashed: back home (WoW evade)
        } else if (!cr.target) {
          cr.wait -= dt;
          if (cr.wait <= 0) {
            const a = random() * Math.PI * 2, r = Math.sqrt(random()) * cr.p.wander;
            cr.target = new T.Vector3(cr.home.x + Math.cos(a) * r, 0, cr.home.z + Math.sin(a) * r);
            cr.wait = 2 + random() * 3; cr.state = "wander";
          }
        }
        if (cr.target) {
          const d = new T.Vector3(cr.target.x - o.position.x, 0, cr.target.z - o.position.z);
          const len = d.length(), speed = cr.p.speed * (cr.state === "chase" ? 2.2 : cr.state === "return" ? 3 : 1);
          if (len < 0.15) { cr.target = null; if (cr.state === "return") cr.state = "idle"; }
          else {
            d.multiplyScalar(Math.min(len, speed * dt) / len);
            o.position.add(d);
            o.rotation.y = Math.atan2(-d.x, -d.z);
          }
        }
        o.position.y = groundAt(o.position.x, o.position.z, cr.home.y);
      }
    }
    self.creatures = creatures;

    function overlapTests() {
      const triggers = actors(scene).filter((o) => actorOf(o).actor === "triggerBox" && o.parent);
      if (!triggers.length) return;
      const movers = actors(scene).filter((o) => o.parent && (actorOf(o).tags || []).includes("overlap"));
      for (const t of triggers) {
        t.updateWorldMatrix(true, false);
        const sz = actorOf(t).props.size || [1, 1, 1];
        box.set(new T.Vector3(-sz[0] / 2, -sz[1] / 2, -sz[2] / 2), new T.Vector3(sz[0] / 2, sz[1] / 2, sz[2] / 2)).applyMatrix4(t.matrixWorld);
        const inside = overlaps.get(t) || new Set();
        for (const m of movers) {
          if (m === t) continue;
          m.getWorldPosition(pt);
          if (m === player) pt.y += 0.9; // the middle of the body, not the feet
          const now = box.containsPoint(pt), was = inside.has(m);
          if (now && !was) { inside.add(m); fire(t, "beginOverlap", [m]); fire(m, "beginOverlap", [t]); }
          else if (!now && was) { inside.delete(m); fire(t, "endOverlap", [m]); fire(m, "endOverlap", [t]); }
        }
        overlaps.set(t, inside);
      }
    }

    self.start = function () {
      if (running) return;
      snapshot = takeSnapshot();
      time = 0; self.errors = []; self.logs = [];
      scene.traverse((o) => { if (o.userData && o.userData.lokiEditorOnly) o.visible = false; });
      world = terrains(scene);
      if (self.possess) makePlayer();
      spawnCreatures();
      for (const o of actors(scene)) bindScripts(o);
      running = true;
      dispatch("start");
    };

    self.tick = function (dt) {
      if (!running) return;
      dt = Math.min(Math.max(dt, 0), 0.1); // a stall (breakpoint, tab hidden) must not teleport anything
      time += dt;
      movePlayer(dt);
      moveCreatures(dt);
      dispatch("update", [dt]);
      if (running) overlapTests();
    };

    self.stop = function () {
      if (!running) return;
      running = false;
      dispatch("stop");
      for (const ev of EVENTS) handlers[ev].length = 0;
      restore(snapshot);
      snapshot = null; player = null; playerCam = null; viewCam = null;
      spawned.length = 0; overlaps.clear(); keys.clear(); creatures.length = 0; world = []; rmb = false;
    };

    // input from the viewport (the UI forwards DOM events here while playing)
    self.keydown = function (e) { keys.add(String(e.key).toLowerCase()); dispatch("keydown", [e]); };
    self.keyup = function (e) { keys.delete(String(e.key).toLowerCase()); dispatch("keyup", [e]); };
    self.pointerdown = function (e) { dispatch("pointerdown", [e]); };
    // mouse: first person looks; third person (WoW) - "turn" (right button) turns you and the camera, "orbit" (left
    // button) swings only the camera round you
    self.look = function (dx, dy, how) {
      if (mode === "third") {
        camYaw -= dx * 0.005;
        camPitch = Math.max(-1.35, Math.min(0.6, camPitch - dy * 0.005));
        if (how !== "orbit") yaw = camYaw;
        placeCamera();
        return;
      }
      yaw -= dx * 0.0025;
      pitch = Math.max(-1.45, Math.min(1.45, pitch - dy * 0.0025));
    };
    self.zoom = function (d) { camDist = Math.max(1.5, Math.min(40, camDist * (d > 0 ? 1.12 : 1 / 1.12))); placeCamera(); };
    self.setTurning = function (on) { rmb = !!on; if (on && mode === "third") { yaw = camYaw; } };
    Object.defineProperty(self, "mode", { get: () => mode });
  }

  const api = { FORMAT, VERSION, EVENTS, ACTORS, TEMPLATE, PAINT, actorOf, isActor, makeActor, createActor, adoptActor, visualOf, applyProps,
    actors, serialize, load, compileScript, checkScripts, Session, terrains, heightAt, sculpt, commitTerrain };
  root.ForgeLevel = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
