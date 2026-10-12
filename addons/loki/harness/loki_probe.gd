extends SceneTree

## Loki's injected-input probe.
##
## Runs a scene in a REAL window, feeds it a timed sequence of inputs, records what the
## game ACTUALLY received, then screenshots and quits. Everything is driven by a sidecar
## JSON written by the Python tool (never substituted into this file), so the tool and this
## script share one tested implementation and this ships as a normal addon asset.
##
## Why probe at all: reading a scene tells you what the file says, but only running it
## tells you whether the controller moves, the button reacts, or the shot lands. A press
## released in the same frame it was issued is invisible to a per-frame poller, so every
## press is held for at least MIN_HOLD_PHYSICS physics frames and any clamp is reported.

const SIDECAR := "res://.godot/loki_probe.json"

## A tap shorter than this is invisible to Input.is_action_pressed pollers, which sample
## once per PHYSICS tick. Physics frames, not render frames: render runs as fast as the
## machine draws, so a two-render-frame tap can span zero ticks and vanish.
const MIN_HOLD_PHYSICS := 2

## Process frames between the last input and the read, so autoload CanvasLayer HUDs and
## layout are in the captured frame.
const SETTLE_FRAMES_DEFAULT := 5

var _scene := ""
var _inputs: Array = []
var _settle_frames := SETTLE_FRAMES_DEFAULT
var _duration_ms := 3000
var _results_path := "user://loki_probe_results.json"
var _shot_path := "user://loki_probe.png"

var _start_ms := 0
var _index := 0
var _active := -1
var _release_at_ms := 0
var _press_phys := 0
var _settle_left := -1
var _events: Array = []
var _finished := false


func _initialize() -> void:
	var f := FileAccess.open(SIDECAR, FileAccess.READ)
	if f == null:
		print("LOKI_PROBE_ERROR: no sidecar at " + SIDECAR)
		quit(1)
		return
	# GDScript "or" yields a bool, not the operand, so parse and check explicitly.
	var parsed: Variant = JSON.parse_string(f.get_as_text())
	var params: Dictionary = parsed if typeof(parsed) == TYPE_DICTIONARY else {}
	f.close()
	_scene = str(params.get("scene", ""))
	_inputs = params.get("inputs", [])
	_settle_frames = int(params.get("settle_frames", SETTLE_FRAMES_DEFAULT))
	_duration_ms = int(params.get("duration_ms", 3000))
	_results_path = str(params.get("results_path", _results_path))
	_shot_path = str(params.get("shot_path", _shot_path))
	if _scene.is_empty():
		print("LOKI_PROBE_ERROR: no scene given")
		quit(1)
		return
	var packed: PackedScene = load(_scene)
	if packed == null:
		print("LOKI_PROBE_ERROR: cannot load " + _scene)
		quit(1)
		return
	root.add_child(packed.instantiate())
	_start_ms = Time.get_ticks_msec()


func _now_ms() -> int:
	return Time.get_ticks_msec() - _start_ms


func _send(spec: Dictionary, pressed: bool) -> bool:
	var kind := str(spec.get("type", "action"))
	if kind == "action":
		if pressed:
			Input.action_press(str(spec.get("action", "")))
		else:
			Input.action_release(str(spec.get("action", "")))
		return true
	if kind == "key":
		var code := OS.find_keycode_from_string(str(spec.get("key", "")))
		var ev := InputEventKey.new()
		ev.keycode = code
		ev.physical_keycode = code
		ev.pressed = pressed
		Input.parse_input_event(ev)
		return true
	if kind == "mouse":
		var me := InputEventMouseButton.new()
		me.position = Vector2(float(spec.get("x", 0)), float(spec.get("y", 0)))
		me.button_index = MOUSE_BUTTON_LEFT if str(spec.get("button", "left")) == "left" else MOUSE_BUTTON_RIGHT
		me.pressed = pressed
		Input.parse_input_event(me)
		return true
	if kind == "motion":
		if not pressed:
			return true
		var mm := InputEventMouseMotion.new()
		mm.relative = Vector2(float(spec.get("dx", 0)), float(spec.get("dy", 0)))
		Input.parse_input_event(mm)
		return true
	return false


func _hold_physics_frames(spec: Dictionary) -> int:
	var rate := float(Engine.physics_ticks_per_second)
	if rate <= 0.0:
		rate = 60.0
	return maxi(MIN_HOLD_PHYSICS, int(round(float(spec.get("hold_ms", 0)) * rate / 1000.0)))


func _start_next() -> void:
	var spec: Dictionary = _inputs[_index]
	if not _send(spec, true):
		_events.append({"index": _index, "type": str(spec.get("type", "?")),
			"delivered": false, "reason": "unknown input type"})
		_index += 1
		return
	_press_phys = Engine.get_physics_frames()
	_active = _index
	_release_at_ms = _now_ms() + int(spec.get("hold_ms", 0))
	_events.append({"index": _index, "type": str(spec.get("type", "?")),
		"at_ms": int(spec.get("at_ms", 0)), "delivered_at_ms": _now_ms(),
		"delivered": true, "press_frame": _press_phys,
		"requested_physics": _hold_physics_frames(spec)})
	_index += 1


func _release_active() -> void:
	var spec: Dictionary = _inputs[_active]
	_send(spec, false)
	var phys := Engine.get_physics_frames() - _press_phys
	var last: Dictionary = _events[_events.size() - 1]
	last["release_frame"] = Engine.get_physics_frames()
	last["physics_frames"] = phys
	# The clamp only counts as applied when the requested hold was shorter than the floor.
	last["clamp_applied"] = float(spec.get("hold_ms", 0)) < float(MIN_HOLD_PHYSICS)
	_active = -1


func _finish(code: int) -> void:
	_finished = true
	var image: Image = root.get_texture().get_image()
	image.save_png(_shot_path)
	var out := {
		"scene": _scene,
		"requested": _inputs.size(),
		"delivered": _events,
		"physics_ticks_per_second": Engine.physics_ticks_per_second,
		"screenshot": ProjectSettings.globalize_path(_shot_path),
	}
	var f := FileAccess.open(_results_path, FileAccess.WRITE)
	f.store_string(JSON.stringify(out))
	f.close()
	print("LOKI_PROBE_RESULTS: " + ProjectSettings.globalize_path(_results_path))
	print("LOKI_PROBE_SHOT: " + ProjectSettings.globalize_path(_shot_path))
	quit(code)


func _process(_delta: float) -> bool:
	if _finished:
		return true
	var now := _now_ms()
	if _active >= 0:
		var phys := Engine.get_physics_frames() - _press_phys
		if now >= _release_at_ms and phys >= MIN_HOLD_PHYSICS:
			_release_active()
	if _active < 0 and _index < _inputs.size() and now >= int(_inputs[_index].get("at_ms", 0)):
		_start_next()
	if _active < 0 and _index >= _inputs.size():
		if _settle_left < 0:
			_settle_left = _settle_frames
		_settle_left -= 1
		if _settle_left <= 0:
			_finish(0)
			return true
	if now > _duration_ms + 3000:
		_finish(0)
		return true
	return false
