// Forge's Level workspace engine (app/ui/forge_level_core.js) in node with the vendored three.js:
// actors, Play in Editor + Stop restores everything, scripts, overlaps, script errors never escape, level files.
//   node tests/js/test_forge_level.js   (< 5 s)
"use strict";
const path = require("path");
const { pathToFileURL } = require("url");

(async () => {
  const T = await import(pathToFileURL(path.join(__dirname, "../../app/ui/vendor/three/three.module.js")).href);
  const L = require(path.join(__dirname, "../../app/ui/forge_level_core.js"));
  let pass = 0, fail = 0;
  const check = (n, ok, d) => { if (ok) pass++; else fail++; console.log((ok ? "  PASS " : "  FAIL ") + n + (ok ? "" : "  <- " + JSON.stringify(d).slice(0, 300))); };
  const near = (a, b, e = 1e-4) => Math.abs(a - b) < e;

  // a small level: a modelled cube with a spin script, a player start, a trigger with a door script, lights
  function buildLevel() {
    const scene = new T.Scene();
    const cube = new T.Mesh(new T.BoxGeometry(1, 1, 1), new T.MeshStandardMaterial());
    cube.name = "Crate"; cube.position.set(3, 0.5, 0);
    L.makeActor(cube, "mesh").scripts.push({ name: "spin", source: L.TEMPLATE });
    const start = L.createActor(T, "playerStart", { position: [0, 0, 5] });
    const trig = L.createActor(T, "triggerBox", { name: "DoorTrigger", position: [0, 1, 0], props: { size: [2, 2, 2] } });
    const door = new T.Mesh(new T.BoxGeometry(1, 2, 0.1), new T.MeshStandardMaterial());
    door.name = "Door"; door.position.set(0, 1, -1.2);
    L.makeActor(door, "mesh");
    L.actorOf(trig).scripts.push({ name: "door", source:
      "function beginOverlap(o) { if (o === level.player) { level.find('Door').position.y = 3; level.log('open'); } }\n" +
      "function endOverlap(o) { if (o === level.player) level.find('Door').position.y = 1; }" });
    const sun = L.createActor(T, "dirLight", { position: [5, 10, 5], props: { intensity: 3 } });
    scene.add(cube, start, trig, door, sun);
    return { scene, cube, start, trig, door, sun };
  }

  // ---- 1. actors
  const lv = buildLevel();
  check("Place Actors: every type builds (a group, its visual named shape)", Object.keys(L.ACTORS).every((t) => { const a = L.createActor(T, t); return a.isGroup && (t === "empty" || L.visualOf(a)); }), Object.keys(L.ACTORS));
  // Forge's node layout: the outer group is the actor (transform), the visual goes in the node's inner group
  const grp = new T.Group(), inner = new T.Group(); grp.add(inner);
  L.adoptActor(T, "triggerBox", grp, inner, { props: { size: [4, 1, 1] } });
  check("adoptActor: data on the node group, gizmo inside inner", L.isActor(grp) && L.visualOf(grp).parent === inner && L.visualOf(grp).children[0].scale.x === 4 && !L.visualOf(grp).isMesh);
  check("actors() lists the 5 actors", L.actors(lv.scene).length === 5, L.actors(lv.scene).map((o) => o.name));
  check("props apply to the light", L.visualOf(lv.sun).intensity === 3);

  // ---- 2. Play: the player walks forward, the crate spins, the trigger opens the door
  const s = new L.Session(T, lv.scene, { possess: true });
  s.start();
  check("Play spawns the player at the Player Start", s.player && near(s.player.position.z, 5));
  check("editor gizmos (player start body, trigger box) are hidden in Play", !L.visualOf(lv.trig).visible);
  s.keydown({ key: "w" });
  for (let i = 0; i < 60; i++) s.tick(1 / 60);         // 1 s at 5 m/s -> z 5 -> 0, inside the trigger
  check("W walks the player forward 5 m in 1 s", near(s.player.position.z, 0, 0.05), s.player.position.z);
  check("the crate's update() ran (rotation.y = 1.5 rad after 1 s)", near(lv.cube.rotation.y, 1.5, 0.01), lv.cube.rotation.y);
  check("beginOverlap opened the door", near(lv.door.position.y, 3) && s.logs.includes("open"), s.logs);
  for (let i = 0; i < 60; i++) s.tick(1 / 60);         // walk on through and out the back
  check("endOverlap closed it again", near(lv.door.position.y, 1), lv.door.position.y);
  s.keyup({ key: "w" });
  const spawned = s.level.spawn("pointLight", { name: "Flare" });
  lv.scene.remove(lv.sun);
  s.stop();

  // ---- 3. Stop restores the level exactly
  check("Stop: the crate is back to its edit-time rotation", lv.cube.rotation.y === 0);
  check("Stop: the door is back", near(lv.door.position.y, 1));
  check("Stop: spawned actors are gone, destroyed ones are back",
    !spawned.parent && lv.sun.parent === lv.scene && !lv.scene.getObjectByName("Player"));
  check("Stop: gizmos visible again", L.visualOf(lv.trig).visible);
  check("Stop: script state (userData.spin) is not left behind", lv.cube.userData.spin === undefined);

  // ---- 4. bad scripts never escape the session
  const bad = buildLevel();
  L.actorOf(bad.cube).scripts = [
    { name: "syntax", source: "function update( {" },
    { name: "throws", source: "function update(dt) { undefinedThing.go(); }" },
  ];
  check("checkScripts finds the syntax error without playing", L.checkScripts(bad.scene).length === 1);
  const s2 = new L.Session(T, bad.scene, { possess: false });
  let threw = false;
  try { s2.start(); for (let i = 0; i < 10; i++) s2.tick(0.016); s2.stop(); } catch (e) { threw = e; }
  check("a broken script is reported, switched off, and Play keeps running", !threw &&
    s2.errors.length === 2 && s2.errors.some((e) => e.where === "compile") && s2.errors.filter((e) => e.where === "update").length === 1,
    { threw: String(threw), errors: s2.errors });
  check("Simulate (no possess) spawns no player", s2.player === null);

  // ---- 5. a frame stall can't teleport: dt is clamped
  const s3 = new L.Session(T, buildLevel().scene, {});
  s3.start(); s3.keydown({ key: "w" }); s3.tick(5.0);
  check("a 5 s stall moves the player at most one 0.1 s step", near(s3.player.position.z, 4.5, 0.01), s3.player.position.z);
  s3.stop();

  // ---- 6. level files round-trip
  const doc = L.serialize(lv.scene, { name: "test" });
  const json = JSON.parse(JSON.stringify(doc));
  const scene2 = new T.Scene();
  const loaded = await L.load(json, scene2, T, {
    loadAsset: async () => new T.Mesh(new T.BoxGeometry(1, 1, 1), new T.MeshStandardMaterial()),
  });
  check("serialize writes a loki-level v1 with every actor", doc.format === "loki-level" && doc.actors.length === 5);
  check("load rebuilds all 5 actors with names and transforms", loaded.length === 5 &&
    near(scene2.getObjectByName("Crate").position.x, 3) && scene2.getObjectByName("DoorTrigger"));
  check("scripts and props survive the round trip",
    L.actorOf(scene2.getObjectByName("DoorTrigger")).scripts[0].name === "door" &&
    L.visualOf(scene2.getObjectByName("Directional Light")).intensity === 3);
  let rejected = false;
  try { await L.load({ format: "something-else" }, new T.Scene(), T); } catch (e) { rejected = true; }
  check("load refuses files that are not LOKI levels", rejected);

  // ---- 7. the loaded level plays too
  const s4 = new L.Session(T, scene2, {});
  s4.start(); s4.keydown({ key: "w" }); for (let i = 0; i < 60; i++) s4.tick(1 / 60); s4.stop();
  check("a reloaded level plays (trigger fired)", s4.logs.includes("open"), s4.logs);

  // ---- 8. terrain: sculpt, paint, ground height, saved with the level
  const ws = new T.Scene();
  const ter = L.createActor(T, "terrain", { props: { size: 64, res: 32 } });
  ws.add(ter); ws.updateMatrixWorld(true);
  check("a new terrain is flat at its actor's height", L.heightAt(T, ws, 5, 5) === 0 && L.heightAt(T, ws, 500, 0) === null);
  for (let i = 0; i < 10; i++) L.sculpt(T, ter, new T.Vector3(0, 0, 0), { mode: "raise", radius: 8, strength: 0.5 });
  const peak = L.heightAt(T, ws, 0, 0), side = L.heightAt(T, ws, 6, 0);
  check("Raise builds a smooth hill (highest in the middle, falling off)", peak > 4 && side > 0.2 && side < peak && L.heightAt(T, ws, 20, 0) === 0, [peak, side]);
  for (let i = 0; i < 20; i++) L.sculpt(T, ter, new T.Vector3(0, 0, 0), { mode: "smooth", radius: 8, strength: 1 });
  check("Smooth lowers the peak", L.heightAt(T, ws, 0, 0) < peak, L.heightAt(T, ws, 0, 0));
  L.sculpt(T, ter, new T.Vector3(-20, 0, -20), { mode: "flatten", radius: 4, strength: 1, height: 2 });
  check("Flatten pulls the ground to a height", Math.abs(L.heightAt(T, ws, -20, -20) - 2) < 0.05, L.heightAt(T, ws, -20, -20));
  L.sculpt(T, ter, new T.Vector3(20, 0, 20), { mode: "paint", radius: 3, strength: 1, color: "snow" });
  const col = L.visualOf(ter).getObjectByName("terrain").geometry.attributes.color;
  let snowy = 0; for (let i = 0; i < col.count; i++) if (col.getX(i) > 0.9 && col.getZ(i) > 0.9) snowy++;
  check("Paint colours the ground (snow)", snowy > 0, snowy);
  ter.position.y = 10; ws.updateMatrixWorld(true);
  check("ground height follows the terrain actor's position", Math.abs(L.heightAt(T, ws, -20, -20) - 12) < 0.05);
  ter.position.y = 0; ws.updateMatrixWorld(true);
  const tdoc = JSON.parse(JSON.stringify(L.serialize(ws, {})));
  const ws2 = new T.Scene(); await L.load(tdoc, ws2, T); ws2.updateMatrixWorld(true);
  check("terrain heights and paint are saved in the level and come back", Math.abs(L.heightAt(T, ws2, -20, -20) - 2) < 0.05 &&
    Math.abs(L.heightAt(T, ws2, 0, 0) - L.heightAt(T, ws, 0, 0)) < 1e-4 && tdoc.actors[0].props.heights.length > 1000, tdoc.actors[0].props.heights.length);

  // ---- 9. third person on terrain: WoW controls, gravity, jump, camera behind and above the ground
  const start2 = L.createActor(T, "playerStart", { position: [0, 0, 20] });
  ws.add(start2); ws.updateMatrixWorld(true);
  const p3 = new L.Session(T, ws, {});
  p3.start();
  check("Play is third person by default: a body, the camera behind and above", p3.mode === "third" && p3.player.getObjectByName("body") &&
    p3.camera.position.z > p3.player.position.z && p3.camera.position.y > p3.player.position.y + 1, [p3.mode, p3.camera.position.toArray()]);
  p3.keydown({ key: "w" }); for (let i = 0; i < 180; i++) p3.tick(1 / 60); p3.keyup({ key: "w" });
  const onHill = L.heightAt(T, ws, p3.player.position.x, p3.player.position.z);
  check("walking onto the hill keeps the feet on the ground", p3.player.position.z < 6 && Math.abs(p3.player.position.y - onHill) < 0.05 && onHill > 0.3, [p3.player.position.toArray(), onHill]);
  const y0 = p3.player.position.y;
  p3.keydown({ key: " " }); p3.tick(1 / 60); p3.keyup({ key: " " });
  let top = y0; for (let i = 0; i < 20; i++) { p3.tick(1 / 60); top = Math.max(top, p3.player.position.y); }
  for (let i = 0; i < 90; i++) p3.tick(1 / 60);
  check("Space jumps and gravity brings you back down", top > y0 + 0.5 && Math.abs(p3.player.position.y - L.heightAt(T, ws, p3.player.position.x, p3.player.position.z)) < 0.05, [y0, top, p3.player.position.y]);
  const yaw0 = p3.player.rotation.y;
  p3.keydown({ key: "a" }); for (let i = 0; i < 30; i++) p3.tick(1 / 60); p3.keyup({ key: "a" });
  check("A turns the character (WoW keyboard turning)", p3.player.rotation.y > yaw0 + 1, [yaw0, p3.player.rotation.y]);
  const yaw1 = p3.player.rotation.y; p3.look(200, 0, "orbit");
  check("left-drag orbits only the camera", Math.abs(p3.player.rotation.y - yaw1) < 1e-9);
  p3.look(200, 0, "turn"); p3.tick(1 / 60);
  check("right-drag turns the character with the camera", Math.abs(p3.player.rotation.y - yaw1) > 0.5);
  const d0 = p3.camera.position.distanceTo(p3.player.position); p3.zoom(1); p3.zoom(1);
  check("the wheel zooms the camera out", p3.camera.position.distanceTo(p3.player.position) > d0 + 0.5);
  p3.stop();
  check("Stop removes the player's camera too", !ws.children.some((o) => o.isCamera));

  // ---- 10. creatures: wander inside the ring, hostile ones chase and leash home
  const ws3 = new T.Scene();
  ws3.add(L.createActor(T, "terrain", { props: { size: 200, res: 16 } }));
  const spawn = L.createActor(T, "npcSpawn", { position: [0, 0, 0], props: { count: 4, wander: 5, hostile: true, aggro: 8 } });
  ws3.add(spawn, L.createActor(T, "playerStart", { position: [0, 0, 60] }));
  const c4 = new L.Session(T, ws3, { seed: 42 });
  c4.start();
  check("a Creature Spawn makes its creatures in Play", c4.creatures.length === 4 && c4.creatures.every((c) => c.obj.parent === ws3));
  for (let i = 0; i < 600; i++) c4.tick(1 / 60);
  const inRing = c4.creatures.every((c) => Math.hypot(c.obj.position.x, c.obj.position.z) <= 5.3);
  const moved = c4.creatures.some((c) => c.state === "wander" || c.state === "idle");
  check("they wander inside the spawn's ring", inRing && moved, c4.creatures.map((c) => c.obj.position.toArray().map((v) => +v.toFixed(1))));
  c4.player.position.set(0, 0, 9);                                         // walk up to them
  for (let i = 0; i < 60; i++) c4.tick(1 / 60);
  check("hostile creatures notice the player and attack", c4.creatures.some((c) => c.state === "chase") && c4.logs.some((m) => /attacks/.test(m)), c4.creatures.map((c) => c.state));
  c4.player.position.set(0, 0, 90);                                        // run away
  for (let i = 0; i < 600; i++) c4.tick(1 / 60);
  check("they give up (leash) and go home", c4.creatures.every((c) => c.state !== "chase" && Math.hypot(c.obj.position.x, c.obj.position.z) < 8),
    c4.creatures.map((c) => [c.state, +Math.hypot(c.obj.position.x, c.obj.position.z).toFixed(1)]));
  c4.stop();
  check("Stop removes the creatures", !ws3.children.some((o) => L.actorOf(o) && L.actorOf(o).actor === "creature"));

  console.log("\n" + pass + " passed, " + fail + " failed");
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
