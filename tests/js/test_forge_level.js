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

  console.log("\n" + pass + " passed, " + fail + " failed");
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
