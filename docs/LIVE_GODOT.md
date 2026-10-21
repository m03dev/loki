# Your Godot projects, live with LOKI's agents

Owner, 2026-10-18: *"the agents should be able to roam around in a live project state, change everything and make it
so ... the web godot is of no help to us, we want the godot and the assetstore and all the plugins."*

The owner's game projects live in `~/LOKI Projects/<name>` (`LOKI_PROJECTS_DIR`). The Godot tab picks one and opens it
in the real Godot editor - the computer's own Godot when it has one, else **LOKI's own standard Godot 4.7.2**
(engine/godot_editor.py: downloaded once into `<data>/addons/godot-export/editor`, SHA-512 checked).
`LOKI_GODOT_EDITOR=system` never uses LOKI's copy. The home screen lists every project as a card that opens it here.

## How it works

```
 the owner's Godot editor (Asset Library, every plugin)            LOKI's engine (engine/loki_bridge.py)
 ┌─────────────────────────────────────────────┐   link 1       ┌────────────────────────────────────┐
 │ ~/LOKI Projects/<name> + addons/loki_studio  │ ─────────────▶ │ engine/godot_live.py  (GodotHub)   │
 │   bridge.gd  (EditorInterface, UndoRedo)     │ ~/.loki/       │   /api/godot/hello|poll|result|... │
 │   game_bridge.gd in the running game         │ engine_connect │   godot_editor tool → every agent  │
 │   live sync: scene + script changes          │ .json          │   ACTIVITY → the Godot tab, /world │
 └─────────────────────────────────────────────┘                └────────────────────────────────────┘
                     │ link 2: LOKI Studio's own hub (~/.loki/studio_connect.json)
```

- **Open in Godot** (`/godot-editor/native`, engine/godot_web.py): `godot_live.ensure_plugin` copies the LOKI plugin in
  (only when it changed) and installs every plugin in the project's `plugins.json`, then the editor starts.
- **Two links, one editor.** The plugin talks to LOKI Studio (its own app, works when LOKI is down) and to LOKI's
  engine. Each link has its own reply ids and its own read position in the error log.
- **Every agent works in the editor.** `godot_editor(action, args)`: editor_state, scene_tree, node_info,
  set_property, add_node, remove_node, connect_signal, attach_script, new_scene, open_scene, save_scene,
  open_script, select_nodes, rescan, run_game, stop_game, screenshot, game_input, game_tree, game_monitors, game_get,
  undo_turn, plugins, install_plugin. Scene changes go through the editor's UndoRedo (Ctrl+Z). Plan mode only reads.
  A background job calls the engine over loopback with the engine token; the engine calls the hub directly.
- **Who is working.** Each editor action is remembered for 90 s: the Godot tab lists it, and the live view
  (`/world`, engine/events.py) shows that agent at the **Godot editor** with what it did.
- **Live.** The plugin turns on Debug > Synchronize Scene Changes and Synchronize Script Changes, so the game running
  from the editor changes while the agents work.
- **Plugins.** `install_plugin {asset_id}` (or the Godot tab's "Add plugin"): the Asset Library's pinned archive (exact
  commit, its hash when the library has one), only its `addons/<name>/` copied, recorded in `plugins.json`. Another
  machine installs the same set when the project opens there. The Godot editor's own AssetLib tab works as always; what
  is installed there but not in `plugins.json` stays on that machine (the Godot tab says so).

## Next

1. The plugin dock shows LOKI's agents (who is in the editor now, what they changed) next to Studio's chat.
2. An agent's edits highlighted in the editor (select the node it changed, a toast with its name).
3. A curated starter set in `plugins.json` (terrain, dialogue, camera) once the owner picks them.
