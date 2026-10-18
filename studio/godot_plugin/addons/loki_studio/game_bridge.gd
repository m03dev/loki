extends Node
## LOKI Studio's hands in the RUNNING game (an autoload the plugin registers as LokiStudioGame).
##
## It only does anything when the game was started from the editor (the debugger connection is
## active) or with --loki-selftest: in an exported game it stays idle. Messages come from the
## editor over Godot's debugger link ("loki:input", "loki:screenshot", "loki:tree",
## "loki:monitors", "loki:get") and every answer goes back as "loki:reply" [id, result].
## Errors in the game (script errors, push_error) are caught by a Logger and sent as "loki:errors".
##
## Inputs are held for at least two PHYSICS frames, so per-frame pollers
## (Input.is_action_pressed in _physics_process) really see them.

const MIN_HOLD_PHYSICS := 2
const SHOT_MAX_W := 1280

var _logger: Object = null
var _active := false
var _physics_frames := 0


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	if Engine.is_editor_hint():
		return
	if ClassDB.class_exists("Logger"):
		var logger_script: Script = load("res://addons/loki_studio/error_logger.gd")
		if logger_script != null:
			_logger = logger_script.new()
			_logger.source = "game"
			OS.call("add_logger", _logger)
	if EngineDebugger.is_active():
		EngineDebugger.register_message_capture("loki", _on_message)
		_active = true
	for arg in OS.get_cmdline_user_args():
		if str(arg).begins_with("--loki-selftest="):
			_active = true
			_selftest.call_deferred(str(arg).substr("--loki-selftest=".length()))


func _exit_tree() -> void:
	if _logger != null:
		OS.call("remove_logger", _logger)
	if EngineDebugger.is_active() and EngineDebugger.has_capture("loki"):
		EngineDebugger.unregister_message_capture("loki")


func _physics_process(_delta: float) -> void:
	_physics_frames += 1


func _process(_delta: float) -> void:
	if _logger == null or not EngineDebugger.is_active():
		return
	var rows: Array = _logger.take_errors()
	if not rows.is_empty():
		EngineDebugger.send_message("loki:errors", [rows])


func _on_message(message: String, data: Array) -> bool:
	var kind := message.trim_prefix("loki:")
	if data.size() < 2:
		return false
	_answer(kind, int(data[0]), data[1] if typeof(data[1]) == TYPE_DICTIONARY else {})
	return true


func _answer(kind: String, id: int, args: Dictionary) -> void:
	var r: Dictionary = await handle(kind, args)
	EngineDebugger.send_message("loki:reply", [id, r])


func handle(kind: String, args: Dictionary) -> Dictionary:
	match kind:
		"input":
			return await _input_events(args.get("events", []), int(args.get("wait_ms", 300)))
		"screenshot":
			return await _screenshot()
		"tree":
			return {"ok": true, "result": _tree(int(args.get("depth", 6)))}
		"monitors":
			return await _monitors(float(args.get("seconds", 4.0)))
		"get":
			return _get_value(str(args.get("node", "")), str(args.get("property", "")))
		"errors":
			return {"ok": true, "result": _logger.take_errors() if _logger != null else []}
	return {"ok": false, "error": "unknown game command %s" % kind}


# ------------------------------------------------------------------ input
func _hold(ms: int) -> void:
	var start := _physics_frames
	var end := Time.get_ticks_msec() + maxi(ms, 0)
	while Time.get_ticks_msec() < end or _physics_frames - start < MIN_HOLD_PHYSICS:
		await get_tree().physics_frame


func _key_event(code: int, pressed: bool, unicode: int = 0) -> InputEventKey:
	var ev := InputEventKey.new()
	ev.keycode = code
	ev.physical_keycode = code
	ev.unicode = unicode
	ev.pressed = pressed
	return ev


func _input_events(events: Array, wait_ms: int) -> Dictionary:
	var log: Array = []
	for e in events:
		if typeof(e) != TYPE_DICTIONARY:
			continue
		var hold := int(e.get("hold_ms", 120))
		if e.has("action"):
			var action := str(e["action"])
			if not InputMap.has_action(action):
				log.append("no input action %s (actions: %s)" % [action, ", ".join(_actions())])
				continue
			var down := InputEventAction.new()
			down.action = action
			down.pressed = true
			down.strength = 1.0
			Input.parse_input_event(down)
			await _hold(hold)
			var up := InputEventAction.new()
			up.action = action
			up.pressed = false
			Input.parse_input_event(up)
			log.append("action %s %d ms" % [action, hold])
		elif e.has("key"):
			var code := OS.find_keycode_from_string(str(e["key"]))
			if code == KEY_NONE:
				log.append("unknown key %s" % e["key"])
				continue
			Input.parse_input_event(_key_event(code, true))
			await _hold(hold)
			Input.parse_input_event(_key_event(code, false))
			log.append("key %s %d ms" % [e["key"], hold])
		elif e.has("mouse"):
			var pos := Vector2(float(e.get("x", 0)), float(e.get("y", 0)))
			var button: int = {"left": MOUSE_BUTTON_LEFT, "right": MOUSE_BUTTON_RIGHT, "middle": MOUSE_BUTTON_MIDDLE}.get(str(e["mouse"]), MOUSE_BUTTON_LEFT)
			var move := InputEventMouseMotion.new()
			move.position = pos
			move.global_position = pos
			Input.parse_input_event(move)
			for pressed in [true, false]:
				var click := InputEventMouseButton.new()
				click.button_index = button
				click.position = pos
				click.global_position = pos
				click.pressed = pressed
				Input.parse_input_event(click)
				if pressed:
					await _hold(hold)
			log.append("mouse %s at %s" % [e["mouse"], pos])
		elif e.has("text"):
			for ch in str(e["text"]):
				var code := OS.find_keycode_from_string(ch.to_upper())
				Input.parse_input_event(_key_event(code, true, ch.unicode_at(0)))
				Input.parse_input_event(_key_event(code, false, ch.unicode_at(0)))
				await get_tree().process_frame
			log.append("typed %d characters" % str(e["text"]).length())
		if e.has("wait_ms"):
			await get_tree().create_timer(float(e["wait_ms"]) / 1000.0).timeout
	if wait_ms > 0:
		await get_tree().create_timer(float(wait_ms) / 1000.0).timeout
	return {"ok": true, "result": {"sent": log, "scene": _scene_path()}}


func _actions() -> Array:
	var out: Array = []
	for a in InputMap.get_actions():
		if not str(a).begins_with("ui_"):
			out.append(str(a))
	return out


# ------------------------------------------------------------------ looking at the game
func _scene_path() -> String:
	var cs := get_tree().current_scene
	return cs.scene_file_path if cs != null else ""


func _screenshot() -> Dictionary:
	if DisplayServer.get_name() == "headless":
		return {"ok": false, "error": "the game runs headless: there is no picture to take"}
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	if img == null or img.is_empty():
		return {"ok": false, "error": "the game has no picture (headless run?)"}
	if img.get_width() > SHOT_MAX_W:
		img.resize(SHOT_MAX_W, int(img.get_height() * float(SHOT_MAX_W) / img.get_width()))
	return {"ok": true, "result": {"width": img.get_width(), "height": img.get_height(),
		"png_base64": Marshalls.raw_to_base64(img.save_png_to_buffer())}}


func _tree(depth: int) -> Dictionary:
	var rows: Array = []
	_walk(get_tree().root, rows, depth, 0)
	return {"scene": _scene_path(), "nodes": rows, "count": rows.size()}


func _walk(n: Node, rows: Array, depth: int, level: int) -> void:
	if rows.size() >= 500 or n == self:
		return
	var row := {"path": str(n.get_path()), "type": n.get_class()}
	var s: Script = n.get_script()
	if s != null:
		row["script"] = s.resource_path
	if n is Node2D or n is Node3D:
		row["position"] = var_to_str(n.position)
	if n is CanvasItem or n is Node3D:
		row["visible"] = n.visible
	rows.append(row)
	if level < depth:
		for c in n.get_children():
			_walk(c, rows, depth, level + 1)


func _get_value(path: String, prop: String) -> Dictionary:
	var n: Node = null
	if path.begins_with("/root"):
		n = get_tree().root.get_node_or_null(NodePath(path))
	elif get_tree().current_scene != null:
		n = get_tree().current_scene if path in ["", "."] else get_tree().current_scene.get_node_or_null(NodePath(path))
	if n == null:
		return {"ok": false, "error": "no node %s in the running game" % path}
	if not (prop in n):
		return {"ok": false, "error": "%s has no property %s" % [path, prop]}
	var v: Variant = n.get(prop)
	return {"ok": true, "result": {"node": str(n.get_path()), "property": prop, "value": var_to_str(v)}}


func _monitors(seconds: float) -> Dictionary:
	var samples := {"fps": [], "process_ms": [], "physics_ms": [], "draw_calls": []}
	var end := Time.get_ticks_msec() + int(clampf(seconds, 0.5, 20.0) * 1000)
	var last := Time.get_ticks_usec()
	var worst_frame_ms := 0.0
	while Time.get_ticks_msec() < end:
		await get_tree().process_frame
		var now := Time.get_ticks_usec()
		worst_frame_ms = maxf(worst_frame_ms, (now - last) / 1000.0)
		last = now
		samples["fps"].append(Performance.get_monitor(Performance.TIME_FPS))
		samples["process_ms"].append(Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0)
		samples["physics_ms"].append(Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0)
		samples["draw_calls"].append(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME))
	var types := {}
	var busy := {}
	for n in get_tree().root.find_children("*", "", true, false):
		if n == self:
			continue
		types[n.get_class()] = int(types.get(n.get_class(), 0)) + 1
		if n.is_processing() or n.is_physics_processing():
			var s: Script = n.get_script()
			var key: String = s.resource_path if s != null else n.get_class()
			busy[key] = int(busy.get(key, 0)) + 1
	return {"ok": true, "result": {
		"seconds": seconds, "frames": samples["fps"].size(), "worst_frame_ms": snappedf(worst_frame_ms, 0.01),
		"fps": snappedf(_avg(samples["fps"]), 0.1), "fps_min": snappedf(_min(samples["fps"]), 0.1),
		"process_ms_avg": snappedf(_avg(samples["process_ms"]), 0.01), "process_ms_max": snappedf(_max(samples["process_ms"]), 0.01),
		"physics_ms_avg": snappedf(_avg(samples["physics_ms"]), 0.01), "physics_ms_max": snappedf(_max(samples["physics_ms"]), 0.01),
		"draw_calls_max": int(_max(samples["draw_calls"])),
		"objects": int(Performance.get_monitor(Performance.OBJECT_COUNT)),
		"nodes": int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT)),
		"orphan_nodes": int(Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT)),
		"static_mem_mb": snappedf(Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0, 0.1),
		"video_mem_mb": snappedf(Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED) / 1048576.0, 0.1),
		"node_types": _top(types, 10), "processing": _top(busy, 10),
	}}


func _avg(a: Array) -> float:
	if a.is_empty():
		return 0.0
	var t := 0.0
	for x in a:
		t += float(x)
	return t / a.size()


func _min(a: Array) -> float:
	return float(a.min()) if not a.is_empty() else 0.0


func _max(a: Array) -> float:
	return float(a.max()) if not a.is_empty() else 0.0


func _top(d: Dictionary, n: int) -> Array:
	var rows: Array = []
	for k in d:
		rows.append([k, d[k]])
	rows.sort_custom(func(a, b): return a[1] > b[1])
	return rows.slice(0, n)


# ------------------------------------------------------------------ the offline self-test (tests/test_studio_godot.py)
func _selftest(spec_path: String) -> void:
	var f := FileAccess.open(spec_path, FileAccess.READ)
	if f == null:
		get_tree().quit(2)
		return
	var spec: Variant = JSON.parse_string(f.get_as_text())
	f.close()
	var results: Array = []
	for step in (spec.get("steps", []) if typeof(spec) == TYPE_DICTIONARY else []):
		if str(step.get("kind", "")) == "push_error":
			push_error(str(step.get("text", "selftest error")))
			await get_tree().process_frame
			results.append({"ok": true})
			continue
		var r: Dictionary = await handle(str(step.get("kind", "")), step.get("args", {}))
		if typeof(r.get("result")) == TYPE_DICTIONARY and r["result"].has("png_base64"):
			r["result"]["png_base64"] = str(r["result"]["png_base64"]).length()
		results.append(r)
	var out := FileAccess.open(str(spec.get("out", "user://loki_selftest.json")), FileAccess.WRITE)
	if out != null:
		out.store_string(JSON.stringify({"results": results, "logger": _logger != null}))
		out.close()
	get_tree().quit()
