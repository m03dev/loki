# Forge - the Level workspace

Owner, 2026-10-24: "i want forge as an editor or something close to unreal engine". Workspace > **Level**
(or the Level menu set, or Windows > Workspaces > Level). Modeling, Sculpting and the rest stay as they are;
the Level workspace adds Unreal-style level editing on top of the same scene and Outliner.

| Unreal | Forge |
| --- | --- |
| Place Actors | Empty Actor, Player Start, Trigger Box, Camera Actor, Point / Directional / Spot Light - each an Outliner node |
| Content Browser | the workspace's `models/` (.glb) placed as mesh actors; saved `.level` files to open |
| Details | the selected node's settings, tags and scripts; any Forge object gets a script with Add Script |
| Blueprints (code side) | scripts per actor: `start`, `update(dt)`, `stop`, `keydown`, `keyup`, `pointerdown`, `beginOverlap(other)`, `endOverlap(other)`; `this` is the actor; `level.find / findTagged / spawn / destroy / log / viewFrom / stop`, `input.down(key)`, `THREE`, `scene` |
| Landscape mode | **Terrain** actor + the Terrain brush: Raise, Lower, Smooth, Flatten, Paint (grass, dirt, rock, snow, sand), radius and strength; heights and paint are saved in the level |
| Spawners | **Creature Spawn**: creatures wander inside its ring; hostile ones attack when you come close and leash back home when you run (WoW evade) |
| Play in Editor (Alt+P) | possesses the Player Start. Third person by default with WoW controls: W / S move, A / D turn, Q / E strafe, right-drag turns you, left-drag orbits the camera, wheel zooms, Space jumps, Shift runs, feet stay on the terrain. Player Start's `mode` can also be `walk` (first person, click to look) or `fly`. Esc stops |
| Simulate | scripts run, the editor camera stays |
| Stop | every object back exactly as it was: transforms, visibility, settings, spawned and destroyed actors |
| Save Current Level | `models/<name>.level` (JSON "loki-level" v1, never overwrites) |

A script that fails to compile or throws is switched off and listed under Output; Play keeps running and the
editor never crashes. Check Scripts compiles everything without playing.

## Code

- `app/ui/forge_level_core.js` - the engine, no DOM: actor types, `Session` (Play / Simulate / Stop), scripts,
  overlaps, level files. Node suite: `node tests/js/test_forge_level.js`.
- `app/ui/forge_level.js` - the panel and its commands (`levelPlay`, `levelSimulate`, `levelStop`, `levelSave`,
  `levelCheckScripts`, `place*`), registered like the Baking workspace.
- `engine/forge_api.py` - `.level` in `POST /forge/save` and `GET /forge/file/`, `GET /forge/levels`.
- Forge hooks it uses: `tree.api.addActor` / `nodeOf` (forge_scene.js), `view.playing` (the render loop draws
  through Play's camera), `view.controls`.
- Suite: `python tests/test_forge_level_ui.py` (engine, routes, and the workspace in headless Chromium).

The script model follows the three.js editor's player (mrdoob/three.js `editor/js/libs/app.js`, MIT) - same
engine as Forge - written fresh, no code copied.

## Not yet

- A modeled Forge object with a script but no model file is skipped when a level is opened: export it to
  `models/` first (Save Level says so).
- Collision with placed meshes (the player walks through walls; terrain is solid), combat, health and loot, nameplates,
  terrain undo (Forge's Ctrl+Z doesn't undo brush strokes yet), prefabs, a node graph for logic (Forge's node graph
  could drive it), and export of a level to Godot or the Carbon MMO server (`native/carbon_mmo`).
