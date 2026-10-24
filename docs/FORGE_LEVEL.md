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
| Play in Editor (Alt+P) | possesses the Player Start: W A S D, mouse look (click the view), Shift runs, fly mode adds Q / E; Esc stops |
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
- Physics and collision (the player walks through walls), prefabs, a node graph for logic (Forge's node graph
  could drive it), and export of a level to Godot or the Carbon MMO server (`native/carbon_mmo`).
