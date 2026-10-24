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
//   play        Play in Editor (possess the Player Start) and Simulate (scripts run, editor camera stays).
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
      what: "Where Play puts you. Walk with W A S D, look with the mouse, fly mode adds Q / E.",
      props: { speed: 5, eyeHeight: 1.7, mode: "walk" },
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
  };

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
      if (ACTORS[rec.type]) obj = createActor(T, rec.type, { props: rec.props });
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

    function makePlayer() {
      const start = actors(scene).find((o) => actorOf(o).actor === "playerStart");
      const props = start ? actorOf(start).props : clone(ACTORS.playerStart.props);
      player = new T.Group(); player.name = "Player";
      player.userData.loki = { actor: "player", props, scripts: [], tags: ["overlap"] };
      const sp = new T.Vector3(), sq = new T.Quaternion();
      if (start) { start.getWorldPosition(sp); start.getWorldQuaternion(sq); }
      player.position.copy(sp);
      yaw = new T.Euler().setFromQuaternion(sq, "YXZ").y; pitch = 0;
      playerCam = new T.PerspectiveCamera(70, opts.aspect || 16 / 9, 0.05, 2000);
      playerCam.position.y = props.eyeHeight;
      player.add(playerCam);
      scene.add(player); spawned.push(player);
    }

    function movePlayer(dt) {
      if (!player) return;
      const p = actorOf(player).props;
      player.rotation.set(0, yaw, 0); playerCam.rotation.set(pitch, 0, 0, "YXZ");
      fwd.set(-Math.sin(yaw), 0, -Math.cos(yaw)); right.set(Math.cos(yaw), 0, -Math.sin(yaw));
      const step = p.speed * dt * (input.down("shift") ? 2 : 1);
      if (input.down("w")) player.position.addScaledVector(fwd, step);
      if (input.down("s")) player.position.addScaledVector(fwd, -step);
      if (input.down("d")) player.position.addScaledVector(right, step);
      if (input.down("a")) player.position.addScaledVector(right, -step);
      if (p.mode === "fly") {
        if (input.down("e")) player.position.y += step;
        if (input.down("q")) player.position.y -= step;
      }
    }

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
      if (self.possess) makePlayer();
      for (const o of actors(scene)) bindScripts(o);
      running = true;
      dispatch("start");
    };

    self.tick = function (dt) {
      if (!running) return;
      dt = Math.min(Math.max(dt, 0), 0.1); // a stall (breakpoint, tab hidden) must not teleport anything
      time += dt;
      movePlayer(dt);
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
      spawned.length = 0; overlaps.clear(); keys.clear();
    };

    // input from the viewport (the UI forwards DOM events here while playing)
    self.keydown = function (e) { keys.add(String(e.key).toLowerCase()); dispatch("keydown", [e]); };
    self.keyup = function (e) { keys.delete(String(e.key).toLowerCase()); dispatch("keyup", [e]); };
    self.pointerdown = function (e) { dispatch("pointerdown", [e]); };
    self.look = function (dx, dy) {
      yaw -= dx * 0.0025;
      pitch = Math.max(-1.45, Math.min(1.45, pitch - dy * 0.0025));
    };
  }

  const api = { FORMAT, VERSION, EVENTS, ACTORS, TEMPLATE, actorOf, isActor, makeActor, createActor, adoptActor, visualOf, applyProps,
    actors, serialize, load, compileScript, checkScripts, Session };
  root.ForgeLevel = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
