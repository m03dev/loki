# LOKI World, live in Godot

Owner, 2026-10-18: *"i want the loki world to be an editable project in godot - godot and loki world should be the
same thing, same with loki: the agents should be able to roam around in a live project state, change everything and
make it so ... the web godot is of no help to us, we want the godot and the assetstore and all the plugins."*

## How it works

```
 the owner's Godot editor (Asset Library, every plugin)            LOKI's engine (engine/loki_bridge.py)
 ┌─────────────────────────────────────────────┐   link 1       ┌────────────────────────────────────┐
 │ game/loki-world  +  addons/loki_studio       │ ─────────────▶ │ engine/godot_live.py  (GodotHub)   │
 │   bridge.gd  (EditorInterface, UndoRedo)     │ ~/.loki/       │   /api/godot/hello|poll|result|... │
 │   game_bridge.gd in the running game         │ engine_connect │   godot_editor tool → every agent  │
 │   live sync: scene + script changes          │ .json          │   ACTIVITY → /world: Godot forge   │
 └─────────────────────────────────────────────┘                └────────────────────────────────────┘
                     │ link 2 (as before): LOKI Studio's own hub (~/.loki/studio_connect.json)
```

- **One project.** LOKI World is `game/loki-world`. LOKI's Godot tab opens it in the Godot app on this computer
  (`/godot-editor/native`), after `godot_live.ensure_world`: the LOKI plugin copied in (only when it changed) and every
  plugin in `plugins.json` installed. `project.godot` enables the plugin and its game helper (committed).
- **Two links, one editor.** The plugin talks to LOKI Studio (its own app, works when LOKI is down) and to LOKI's
  engine. Each link has its own reply ids and its own read position in the error log.
- **Every agent works in the editor.** `godot_editor(action, args)`: editor_state, scene_tree, node_info,
  set_property, add_node, remove_node, connect_signal, attach_script, new_scene, open_scene, save_scene,
  open_script, select_nodes, rescan, run_game, stop_game, screenshot, game_input, game_tree, game_monitors, game_get,
  undo_turn, plugins, install_plugin. Scene changes go through the editor's UndoRedo (Ctrl+Z). Plan mode only reads.
  A background job calls the engine over loopback with the engine token; the engine calls the hub directly.
- **Agents roam.** Each editor action is remembered for 90 s; `/world` puts that agent at the **Godot forge** station
  (LOKI World, 160°) with what it did as its words - in the Godot game run from the editor and in the World tab.
- **Live.** The plugin turns on Debug > Synchronize Scene Changes and Synchronize Script Changes, so the game running
  from the editor changes while the agents work.
- **Plugins.** `install_plugin {asset_id}` (or the Godot tab's "Add plugin"): the Asset Library's pinned archive (exact
  commit, its hash when the library has one), only its `addons/<name>/` copied, recorded in `plugins.json`. Another
  machine installs the same set when LOKI starts. The Godot editor's own AssetLib tab works as always; what is installed
  there but not in `plugins.json` stays on that machine (the Godot tab says so).
- **The World tab** still shows a web copy of LOKI World (`engine/world_build.py`, "Rebuild the World tab"); the Godot
  app is where it is made.

## Next

1. The plugin dock shows LOKI's agents (who is in the editor now, what they changed) next to Studio's chat.
2. An agent's edits highlighted in the editor (select the node it changed, a toast with its name).
3. Agents as players in the game run from the editor: walk to the node they are editing, a beam to it.
4. A curated starter set in `plugins.json` (terrain, dialogue, camera) once the owner picks them.
