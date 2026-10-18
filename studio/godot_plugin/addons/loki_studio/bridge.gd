@tool
extends Node
## The editor bridge: LOKI Studio's agent sees and changes the LIVE editor through this.
##
## It says hello to Studio (project, Godot version), then long-polls Studio for commands and
## answers each one. Every action name here is one of studio_godot.ACTIONS (Studio's side); the
## tests check both lists match. Scene changes go through the editor's EditorUndoRedoManager, so
## the owner can Ctrl+Z them, and Studio can undo a whole turn (undo_turn). Errors caught by the
## logger and the running game's messages are pushed to Studio as events.

signal hello_done(editor_id: String)

const VERSION := "1.2"
const MAX_NODES := 400
const SHOT_MAX_W := 1280

var plugin: EditorPlugin
var api: Node
var debugger: EditorDebuggerPlugin
var logger: Object
var editor_id := ""
var running := false
var turn_actions: Array = []        # [{turn, history, name}] - what Studio did, for undo_turn
var _game_replies := {}
var _game_seq := 0                 # the engine link counts from 1000000, so two links never share a reply id
var _game_waiting := {}
var _err_cursor := 0
var _game_errors: Array = []
var _last_flush := 0


func start() -> void:
	if running:
		return
	running = true
	if api != null and str(api.get("target")) == "engine":
		_game_seq = 1000000
	enable_live_sync()
	_loop()


## Edits show in the running game without restarting it: Debug > Synchronize Scene Changes + Synchronize Script Changes
## (Godot keeps them per project in the editor's project metadata, "debug_options").
static func enable_live_sync() -> void:
	if not Engine.is_editor_hint():
		return
	var es := EditorInterface.get_editor_settings()
	if es == null:
		return
	es.set_project_metadata("debug_options", "run_live_debug", true)
	es.set_project_metadata("debug_options", "run_reload_scripts", true)


func stop() -> void:
	running = false


func project_path() -> String:
	return ProjectSettings.globalize_path("res://").rstrip("/")


func _wait(seconds: float) -> void:
	if is_inside_tree():
		await get_tree().create_timer(seconds).timeout


func _loop() -> void:
	while running and is_inside_tree():
		if editor_id == "":
			if not await _hello():
				await _wait(3.0)
				continue
		var res: Dictionary = await api.get_json("/api/godot/poll?editor=%s&wait=20" % editor_id, 35.0)
		if not running or not is_inside_tree():
			break
		if int(res.get("http_code", 0)) == 404:
			editor_id = ""
			continue
		if not res.get("ok", false):
			await _wait(3.0)
			continue
		for cmd in res.get("commands", []):
			if typeof(cmd) == TYPE_DICTIONARY:
				await _run_command(cmd)
		await _flush()


func _hello() -> bool:
	var info := Engine.get_version_info()
	var res: Dictionary = await api.post_json("/api/godot/hello", {
		"project_path": project_path(),
		"project_name": str(ProjectSettings.get_setting("application/config/name", "")),
		"godot_version": "%d.%d.%d" % [info.major, info.minor, info.patch],
		"plugin_version": VERSION,
	}, 10.0)
	if res.get("ok", false) and str(res.get("editor", "")) != "":
		editor_id = str(res["editor"])
		hello_done.emit(editor_id)
		return true
	return false


## Errors (editor + game) and the editor's state go to Studio between polls.
func _flush() -> void:
	if editor_id == "":
		return
	var rows: Array = []
	if logger != null:
		var fresh: Array = logger.errors_since(_err_cursor)
		for r in fresh:
			_err_cursor = maxi(_err_cursor, int(r.get("n", 0)))
		rows.append_array(fresh)
	rows.append_array(_game_errors)
	_game_errors = []
	if not rows.is_empty():
		await api.post_json("/api/godot/event", {"editor": editor_id, "kind": "errors", "data": rows}, 10.0)
	var now := Time.get_ticks_msec()
	if now - _last_flush > 5000:
		_last_flush = now
		await api.post_json("/api/godot/event", {"editor": editor_id, "kind": "state", "data": {
			"playing": EditorInterface.is_playing_scene(), "edited_scene": _edited_path()}}, 10.0)


func _run_command(cmd: Dictionary) -> void:
	var action := str(cmd.get("action", ""))
	var args: Dictionary = cmd.get("args", {}) if typeof(cmd.get("args")) == TYPE_DICTIONARY else {}
	var out: Dictionary
	if action != "" and has_method("_do_" + action):
		var r: Variant = await call("_do_" + action, args)
		if typeof(r) == TYPE_DICTIONARY and r.has("ok"):
			out = r
		else:
			out = {"ok": true, "result": r}
	else:
		out = {"ok": false, "error": "this plugin version (%s) has no action %s" % [VERSION, action]}
	out["editor"] = editor_id
	out["id"] = str(cmd.get("id", ""))
	out["result"] = _j(out.get("result"))
	await api.post_json("/api/godot/result", out, 30.0)


# ------------------------------------------------------------------ helpers
static func _j(v: Variant) -> Variant:
	## Godot values -> JSON-safe values (Vector3 etc. become their Godot text).
	match typeof(v):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING:
			return v
		TYPE_STRING_NAME, TYPE_NODE_PATH:
			return str(v)
		TYPE_DICTIONARY:
			var d := {}
			for k in v:
				d[str(k)] = _j(v[k])
			return d
		TYPE_ARRAY, TYPE_PACKED_STRING_ARRAY:
			var a: Array = []
			for x in v:
				a.append(_j(x))
			return a
		TYPE_OBJECT:
			if v == null:
				return null
			if v is Resource and v.resource_path != "":
				return v.resource_path
			if v is Node:
				return "%s (%s)" % [v.name, v.get_class()]
			return "<%s>" % v.get_class()
	return var_to_str(v)


func _err(text: String) -> Dictionary:
	return {"ok": false, "error": text}


func _root() -> Node:
	return EditorInterface.get_edited_scene_root()


func _edited_path() -> String:
	var r := _root()
	return r.scene_file_path if r != null else ""


func _node(path: String) -> Node:
	var root := _root()
	if root == null:
		return null
	var p := str(path).strip_edges()
	if p == "" or p == "." or p == str(root.name):
		return root
	if p.begins_with(str(root.name) + "/"):
		p = p.substr(str(root.name).length() + 1)
	return root.get_node_or_null(NodePath(p))


func _path(n: Node) -> String:
	var root := _root()
	if root == null or n == null:
		return ""
	return "." if n == root else str(root.get_path_to(n))


func _parse_value(text: Variant, current: Variant = null) -> Variant:
	if typeof(text) != TYPE_STRING:
		return text
	var s := str(text).strip_edges()
	if s.begins_with("res://"):
		return load(s)
	if typeof(current) == TYPE_STRING and not s.begins_with("\""):
		return s
	var v: Variant = str_to_var(s)
	if v == null and s != "null":
		return s
	if typeof(current) == TYPE_FLOAT and typeof(v) == TYPE_INT:
		return float(v)
	return v


func _undo() -> EditorUndoRedoManager:
	return plugin.get_undo_redo()


func _record(args: Dictionary, obj: Object, name: String) -> void:
	turn_actions.append({"turn": int(args.get("turn", 0)), "history": _undo().get_object_history_id(obj), "name": name})


func _need_scene() -> Dictionary:
	if _root() == null:
		return _err("no scene is open in the editor (open_scene first)")
	return {}


# ------------------------------------------------------------------ reading the editor
func _do_editor_state(_args: Dictionary) -> Dictionary:
	var sel: Array = []
	for n in EditorInterface.get_selection().get_selected_nodes():
		sel.append(_path(n))
	var scripts: Array = []
	var se := EditorInterface.get_script_editor()
	for s in se.get_open_scripts():
		scripts.append(s.resource_path)
	var cur: Script = se.get_current_script()
	var info := Engine.get_version_info()
	return {"ok": true, "result": {
		"project": project_path(),
		"project_name": str(ProjectSettings.get_setting("application/config/name", "")),
		"godot": "%d.%d.%d" % [info.major, info.minor, info.patch],
		"main_scene": str(ProjectSettings.get_setting("application/run/main_scene", "")),
		"open_scenes": Array(EditorInterface.get_open_scenes()),
		"edited_scene": _edited_path(),
		"selected_nodes": sel,
		"open_scripts": scripts,
		"current_script": cur.resource_path if cur != null else "",
		"selected_code": _selected_code(),
		"playing": EditorInterface.is_playing_scene(),
		"playing_scene": EditorInterface.get_playing_scene(),
		"selected_files": Array(EditorInterface.get_selected_paths()),
	}}


func _scene_root_for(path: String) -> Node:
	if path == "" or path == _edited_path():
		return _root()
	for r in EditorInterface.get_open_scene_roots():
		if r.scene_file_path == path:
			return r
	return null


func _do_scene_tree(args: Dictionary) -> Dictionary:
	var root := _scene_root_for(str(args.get("scene", "")))
	if root == null:
		return _err("that scene is not open (open_scene first)" if str(args.get("scene", "")) != "" else "no scene is open in the editor")
	var rows: Array = []
	_walk(root, root, rows, int(args.get("depth", 32)), 0)
	return {"ok": true, "result": {"scene": root.scene_file_path, "nodes": rows, "count": rows.size()}}


func _walk(root: Node, n: Node, rows: Array, depth: int, level: int) -> void:
	if rows.size() >= MAX_NODES:
		return
	var row := {"path": "." if n == root else str(root.get_path_to(n)), "type": n.get_class()}
	var s: Script = n.get_script()
	if s != null:
		row["script"] = s.resource_path
	if n != root and n.scene_file_path != "":
		row["instance"] = n.scene_file_path
	if n is Node2D or n is Node3D or n is Control:
		row["visible"] = n.visible
	if n is Node2D:
		row["position"] = var_to_str(n.position)
	elif n is Node3D:
		row["position"] = var_to_str(n.position)
	rows.append(row)
	if level >= depth:
		return
	for c in n.get_children():
		if c.owner == root:     # the scene's own nodes (an instanced scene shows as one node with "instance")
			_walk(root, c, rows, depth, level + 1)


func _do_node_info(args: Dictionary) -> Dictionary:
	var n := _node(str(args.get("node", ".")))
	if n == null:
		return _err("no node %s in the edited scene" % args.get("node", ""))
	var props: Array = []
	for p in n.get_property_list():
		if int(p.get("usage", 0)) & PROPERTY_USAGE_EDITOR and props.size() < 220:
			props.append({"name": p["name"], "type": type_string(int(p["type"])), "value": _j(n.get(p["name"]))})
	var sigs: Array = []
	for s in n.get_signal_list():
		sigs.append(s["name"])
	var links: Array = []
	for c in n.get_incoming_connections():
		links.append("%s <- %s" % [str(c["signal"].get_name()), str(c["callable"])])
	return {"ok": true, "result": {"path": _path(n), "type": n.get_class(), "properties": props, "signals": sigs,
		"groups": Array(n.get_groups()), "incoming": links}}


func _selected_code() -> Dictionary:
	var ed: ScriptEditorBase = EditorInterface.get_script_editor().get_current_editor()
	if ed == null:
		return {}
	var code: Control = ed.get_base_editor()
	if not (code is TextEdit):
		return {}
	var te: TextEdit = code
	var cur: Script = EditorInterface.get_script_editor().get_current_script()
	var file := cur.resource_path if cur != null else ""
	if te.has_selection():
		return {"file": file, "from_line": te.get_selection_from_line() + 1, "to_line": te.get_selection_to_line() + 1,
			"text": te.get_selected_text()}
	var line := te.get_caret_line()
	return {"file": file, "from_line": line + 1, "to_line": line + 1, "text": te.get_line(line), "caret_only": true}


func _do_selected_code(_args: Dictionary) -> Dictionary:
	var sel := _selected_code()
	if sel.is_empty():
		return _err("no script is open in the script editor")
	return {"ok": true, "result": sel}


func _do_errors(args: Dictionary) -> Dictionary:
	return {"ok": true, "result": "errors are pushed to Studio as they happen; use Studio's editor_errors"}


func _do_output(args: Dictionary) -> Dictionary:
	if logger == null:
		return _err("this Godot has no Logger class (4.5+), so the Output cannot be read")
	return {"ok": true, "result": logger.recent_lines(int(args.get("lines", 120)))}


# ------------------------------------------------------------------ changing the scene (undoable)
func _do_set_property(args: Dictionary) -> Dictionary:
	var need := _need_scene()
	if not need.is_empty():
		return need
	var n := _node(str(args.get("node", "")))
	if n == null:
		return _err("no node %s in the edited scene" % args.get("node", ""))
	var prop := str(args.get("property", ""))
	if not (prop in n):
		return _err("%s (%s) has no property %s" % [_path(n), n.get_class(), prop])
	var old: Variant = n.get(prop)
	var value: Variant = _parse_value(args.get("value"), old)
	var name := "LOKI: %s.%s" % [_path(n), prop]
	var ur := _undo()
	ur.create_action(name, UndoRedo.MERGE_DISABLE, _root())
	ur.add_do_property(n, prop, value)
	ur.add_undo_property(n, prop, old)
	ur.commit_action()
	_record(args, n, name)
	return {"ok": true, "result": "%s.%s = %s (was %s)" % [_path(n), prop, var_to_str(n.get(prop)), var_to_str(old)]}


func _do_add_node(args: Dictionary) -> Dictionary:
	var need := _need_scene()
	if not need.is_empty():
		return need
	var root := _root()
	var parent := _node(str(args.get("parent", ".")))
	if parent == null:
		return _err("no parent %s in the edited scene" % args.get("parent", ""))
	var n: Node
	var scene := str(args.get("scene", ""))
	var type := str(args.get("type", ""))
	if scene != "":
		var ps := load(scene) as PackedScene
		if ps == null:
			return _err("cannot load the scene %s" % scene)
		n = ps.instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
	elif type != "" and ClassDB.class_exists(type) and ClassDB.can_instantiate(type) and ClassDB.is_parent_class(type, "Node"):
		n = ClassDB.instantiate(type)
	else:
		return _err("give type (a Node class like Sprite2D) or scene (a res:// .tscn); %s is not a node class" % type)
	if str(args.get("name", "")) != "":
		n.name = str(args["name"])
	var props: Variant = args.get("properties", {})
	if typeof(props) == TYPE_DICTIONARY:
		for k in props:
			if str(k) in n:
				n.set(str(k), _parse_value(props[k], n.get(str(k))))
	var name := "LOKI: add %s" % n.name
	var ur := _undo()
	ur.create_action(name, UndoRedo.MERGE_DISABLE, root)
	ur.add_do_method(parent, "add_child", n, true)
	ur.add_do_method(n, "set_owner", root)
	ur.add_do_reference(n)
	ur.add_undo_method(parent, "remove_child", n)
	ur.commit_action()
	_record(args, n, name)
	return {"ok": true, "result": "added %s (%s) under %s" % [_path(n), n.get_class(), _path(parent)]}


func _do_remove_node(args: Dictionary) -> Dictionary:
	var need := _need_scene()
	if not need.is_empty():
		return need
	var root := _root()
	var n := _node(str(args.get("node", "")))
	if n == null or n == root:
		return _err("no removable node %s (the root cannot be removed)" % args.get("node", ""))
	var parent := n.get_parent()
	var owned: Array = []
	for d in n.find_children("*", "", true, false):
		if d.owner == root:
			owned.append(d)
	var name := "LOKI: remove %s" % n.name
	var ur := _undo()
	ur.create_action(name, UndoRedo.MERGE_DISABLE, root)
	ur.add_do_method(parent, "remove_child", n)
	ur.add_undo_method(parent, "add_child", n, true)
	ur.add_undo_method(parent, "move_child", n, n.get_index())
	ur.add_undo_method(n, "set_owner", root)
	for d in owned:
		ur.add_undo_method(d, "set_owner", root)
	ur.add_undo_reference(n)
	ur.commit_action()
	_record(args, parent, name)
	return {"ok": true, "result": "removed %s" % str(args.get("node", ""))}


func _do_connect_signal(args: Dictionary) -> Dictionary:
	var need := _need_scene()
	if not need.is_empty():
		return need
	var a := _node(str(args.get("from", "")))
	var b := _node(str(args.get("to", "")))
	var sig := str(args.get("signal", ""))
	var method := str(args.get("method", ""))
	if a == null or b == null:
		return _err("from and to must be nodes of the edited scene")
	if not a.has_signal(sig):
		return _err("%s (%s) has no signal %s" % [_path(a), a.get_class(), sig])
	var c := Callable(b, method)
	if a.is_connected(sig, c):
		return {"ok": true, "result": "already connected"}
	var name := "LOKI: connect %s.%s" % [_path(a), sig]
	var ur := _undo()
	ur.create_action(name, UndoRedo.MERGE_DISABLE, _root())
	ur.add_do_method(a, "connect", sig, c, CONNECT_PERSIST)
	ur.add_undo_method(a, "disconnect", sig, c)
	ur.commit_action()
	_record(args, a, name)
	var note := "" if b.has_method(method) else " (note: %s has no method %s yet - write it)" % [_path(b), method]
	return {"ok": true, "result": "connected %s.%s -> %s.%s%s" % [_path(a), sig, _path(b), method, note]}


func _do_attach_script(args: Dictionary) -> Dictionary:
	var need := _need_scene()
	if not need.is_empty():
		return need
	var n := _node(str(args.get("node", "")))
	if n == null:
		return _err("no node %s" % args.get("node", ""))
	var s := load(str(args.get("script", ""))) as Script
	if s == null or not s.can_instantiate():
		return _err("the script %s does not load (missing, or it has errors - see editor_errors)" % args.get("script", ""))
	var name := "LOKI: script on %s" % n.name
	var ur := _undo()
	ur.create_action(name, UndoRedo.MERGE_DISABLE, _root())
	ur.add_do_property(n, "script", s)
	ur.add_undo_property(n, "script", n.get_script())
	ur.commit_action()
	_record(args, n, name)
	return {"ok": true, "result": "attached %s to %s" % [s.resource_path, _path(n)]}


func _do_new_scene(args: Dictionary) -> Dictionary:
	var path := str(args.get("path", ""))
	if not path.begins_with("res://") or not path.ends_with(".tscn"):
		return _err("path must be res://...tscn")
	if FileAccess.file_exists(path):
		return _err("%s exists already (open_scene it)" % path)
	var type := str(args.get("root_type", "Node2D"))
	if not (ClassDB.class_exists(type) and ClassDB.is_parent_class(type, "Node")):
		return _err("%s is not a node class" % type)
	var n: Node = ClassDB.instantiate(type)
	n.name = str(args.get("root_name", "")) if str(args.get("root_name", "")) != "" else path.get_file().get_basename().to_pascal_case()
	var ps := PackedScene.new()
	ps.pack(n)
	n.free()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(path.get_base_dir()))
	var err := ResourceSaver.save(ps, path)
	if err != OK:
		return _err("could not save %s (%s)" % [path, error_string(err)])
	EditorInterface.get_resource_filesystem().update_file(path)
	EditorInterface.open_scene_from_path(path)
	return {"ok": true, "result": "created and opened %s (root %s)" % [path, type]}


func _do_open_scene(args: Dictionary) -> Dictionary:
	var path := str(args.get("path", ""))
	if not FileAccess.file_exists(path):
		return _err("no scene %s" % path)
	EditorInterface.open_scene_from_path(path)
	return {"ok": true, "result": "opened %s" % path}


func _do_save_scene(args: Dictionary) -> Dictionary:
	if bool(args.get("all", false)):
		EditorInterface.save_all_scenes()
		return {"ok": true, "result": "saved all open scenes"}
	if _root() == null:
		return _err("no scene is open")
	var err := EditorInterface.save_scene()
	return {"ok": err == OK, "result": "saved %s" % _edited_path(), "error": error_string(err)}


func _do_open_script(args: Dictionary) -> Dictionary:
	var s := load(str(args.get("path", ""))) as Script
	if s == null:
		return _err("cannot load %s" % args.get("path", ""))
	EditorInterface.edit_script(s, int(args.get("line", 1)))
	return {"ok": true, "result": "showing %s" % s.resource_path}


func _do_select_nodes(args: Dictionary) -> Dictionary:
	var sel := EditorInterface.get_selection()
	sel.clear()
	var found: Array = []
	for p in args.get("nodes", []):
		var n := _node(str(p))
		if n != null:
			sel.add_node(n)
			found.append(_path(n))
	return {"ok": true, "result": "selected %s" % ", ".join(found)}


func _do_rescan(_args: Dictionary) -> Dictionary:
	EditorInterface.get_resource_filesystem().scan()
	EditorInterface.get_script_editor().reload_open_files()
	return {"ok": true, "result": "rescanned"}


func _do_undo_turn(args: Dictionary) -> Dictionary:
	var turn := int(args.get("turn", 0))
	var ur := _undo()
	var undone := 0
	var blocked := ""
	var i := turn_actions.size() - 1
	while i >= 0:
		var a: Dictionary = turn_actions[i]
		if int(a["turn"]) >= turn:
			var hist: UndoRedo = ur.get_history_undo_redo(int(a["history"]))
			if hist != null and hist.has_undo() and hist.get_current_action_name() == a["name"]:
				hist.undo()
				undone += 1
			elif blocked == "":
				blocked = a["name"]
			turn_actions.remove_at(i)
		i -= 1
	var text := "undid %d editor action(s)" % undone
	if blocked != "":
		text += "; '%s' was not the newest action any more (you changed the scene after it) - undo it by hand with Ctrl+Z" % blocked
	return {"ok": true, "result": {"undone": undone, "text": text}}


func _do_quit(_args: Dictionary) -> Dictionary:
	if OS.get_environment("LOKI_STUDIO_TEST") != "1":
		return _err("quit is for tests only")
	get_tree().create_timer(0.3).timeout.connect(func(): get_tree().quit())
	return {"ok": true, "result": "bye"}


# ------------------------------------------------------------------ the game
func _do_run_game(args: Dictionary) -> Dictionary:
	var scene := str(args.get("scene", "main"))
	if scene == "" or scene == "main":
		if str(ProjectSettings.get_setting("application/run/main_scene", "")) == "":
			return _err("the project has no main scene; give scene=current or a res:// path")
		EditorInterface.play_main_scene()
	elif scene == "current":
		EditorInterface.play_current_scene()
	else:
		EditorInterface.play_custom_scene(scene)
	for i in 40:
		await _wait(0.25)
		if debugger != null and debugger.game_running():
			await _wait(0.5)
			return {"ok": true, "result": "the game runs (%s)" % scene}
	return {"ok": true, "result": "asked Godot to play %s; the game has not connected yet (check editor_errors)" % scene}


func _do_stop_game(_args: Dictionary) -> Dictionary:
	EditorInterface.stop_playing_scene()
	return {"ok": true, "result": "stopped"}


func _image_result(img: Image, target: String) -> Dictionary:
	if img == null or img.is_empty():
		return _err("no picture of the %s (is there a window? the headless editor has none)" % target)
	if img.get_width() > SHOT_MAX_W:
		img.resize(SHOT_MAX_W, int(img.get_height() * float(SHOT_MAX_W) / img.get_width()))
	return {"ok": true, "result": {"target": target, "width": img.get_width(), "height": img.get_height(),
		"png_base64": Marshalls.raw_to_base64(img.save_png_to_buffer())}}


func _do_screenshot(args: Dictionary) -> Dictionary:
	var target := str(args.get("target", "game"))
	if target == "game":
		var r: Dictionary = await _game("screenshot", {}, 15.0)
		if not r.get("ok", false):
			return r
		var data: Dictionary = r.get("result", {})
		data["target"] = "game"
		return {"ok": true, "result": data}
	var vp: Viewport
	if target == "2d":
		vp = EditorInterface.get_editor_viewport_2d()
	elif target == "3d":
		vp = EditorInterface.get_editor_viewport_3d(0)
	else:
		vp = EditorInterface.get_base_control().get_viewport()
	if DisplayServer.get_name() == "headless":
		return _err("the editor runs headless: there is no picture of the %s" % target)
	await RenderingServer.frame_post_draw
	return _image_result(vp.get_texture().get_image() if vp != null else null, target)


func _do_game_input(args: Dictionary) -> Dictionary:
	return await _game("input", {"events": args.get("events", []), "wait_ms": int(args.get("wait_ms", 300))}, 60.0)


func _do_game_tree(args: Dictionary) -> Dictionary:
	return await _game("tree", {"depth": int(args.get("depth", 6))}, 15.0)


func _do_game_monitors(args: Dictionary) -> Dictionary:
	var secs := clampf(float(args.get("seconds", 4.0)), 1.0, 20.0)
	return await _game("monitors", {"seconds": secs}, secs + 15.0)


func _do_game_get(args: Dictionary) -> Dictionary:
	return await _game("get", {"node": str(args.get("node", "")), "property": str(args.get("property", ""))}, 10.0)


func _game(kind: String, args: Dictionary, timeout: float) -> Dictionary:
	if debugger == null or not debugger.game_running():
		return _err("the game is not running from this editor (run_game first)")
	_game_seq += 1
	var id := _game_seq
	_game_waiting[id] = true
	debugger.send(kind, [id, args])
	var end := Time.get_ticks_msec() + int(timeout * 1000)
	while Time.get_ticks_msec() < end:
		if _game_replies.has(id):
			var r: Variant = _game_replies[id]
			_game_replies.erase(id)
			_game_waiting.erase(id)
			return r if typeof(r) == TYPE_DICTIONARY else {"ok": true, "result": r}
		await _wait(0.05)
	_game_waiting.erase(id)
	return _err("the game did not answer %s within %.0f s" % [kind, timeout])


func on_game_message(message: String, data: Array) -> void:
	if message == "reply" and data.size() >= 2:
		if _game_waiting.has(int(data[0])):          # only the replies to this link's own requests
			_game_replies[int(data[0])] = data[1]
	elif message == "errors" and data.size() >= 1 and typeof(data[0]) == TYPE_ARRAY:
		for row in data[0]:
			if typeof(row) == TYPE_DICTIONARY:
				row["source"] = "game"
				_game_errors.append(row)
