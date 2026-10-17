extends Node
## LOKI World's root. The 3D world is rendered small in a SubViewport and shown with nearest
## filtering plus the posterize/dither shader (the pixel look); the HUD sits on top at full
## resolution. Starts LokiApi (connect to LOKI or play offline).
##
## Options (command line after `--`, or the page fragment in the web build):
##   --mode=play|background   background = behind LOKI's home screen: no HUD, slow orbit, 30 fps
##   --pixel=N                 world pixel size (default 3)
##   --hour=H                  fix the time of day (0-24)      --day-speed=X  hours per second
##   --screenshot=PATH         save a screenshot after --frames=N frames (default 90), then quit
##   --quit-after=N            quit after N frames (smoke test)   --run-seconds=S  quit after S seconds
##   --say=TEXT                say one line in the world chat once connected (tests)
##   --cam=yaw,pitch,dist  --at=x,z   camera and start spot (screenshots)
##   --fight=1                 target the nearest monster and attack (screenshots, tests)
##   --open=quests|bags|character|help|map   open a window at start (screenshots)
##   --loki-url=URL --token=T --token-file=PATH   (see autoload/loki_api.gd)

const POST := preload("res://shaders/pixel_post.gdshader")

var container: SubViewportContainer
var view: SubViewport
var world: Node3D
var hud: CanvasLayer
var pixel := 3
var _frames := 0
var _shot_path := ""
var _shot_frame := 90
var _quit_after := -1
var _js_cb = null
var _fight := false
var _run_seconds := -1.0
var _say := ""
var _t := 0.0


func _ready() -> void:
	var opts := _options()
	pixel = clampi(int(opts.get("pixel", "3")), 1, 8)
	GameState.set_mode(str(opts.get("mode", "play")))
	container = SubViewportContainer.new()
	container.name = "WorldView"
	container.stretch = true
	container.stretch_shrink = pixel
	container.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	container.mouse_filter = Control.MOUSE_FILTER_IGNORE
	container.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	var mat := ShaderMaterial.new()
	mat.shader = POST
	container.material = mat
	add_child(container)
	view = SubViewport.new()
	view.name = "World3D"
	view.msaa_3d = Viewport.MSAA_DISABLED
	view.positional_shadow_atlas_size = 0
	view.handle_input_locally = false
	container.add_child(view)
	world = preload("res://scripts/world/world.gd").new()
	world.name = "World"
	view.add_child(world)
	if opts.has("hour"):
		world.hour_override = clampf(float(opts["hour"]), 0.0, 24.0)
	if opts.has("day-speed"):
		world.day_speed = float(opts["day-speed"])
		if world.hour_override < 0.0:
			world.hour_override = 12.0
	if opts.has("cam"):   # yaw,pitch,distance - for screenshots
		var c := str(opts["cam"]).split(",")
		if c.size() == 3:
			world.player.cam_yaw = c[0].to_float()
			world.player.cam_pitch = c[1].to_float()
			world.player.cam_dist = c[2].to_float()
	if opts.has("at"):    # x,z - start somewhere else (screenshots, tests)
		var a := str(opts["at"]).split(",")
		if a.size() == 2:
			world.player.position = Vector3(a[0].to_float(), 0.4, a[1].to_float())
	hud = preload("res://scripts/hud/hud.gd").new()
	hud.name = "HUD"
	add_child(hud)
	hud.setup(world, pixel)
	GameState.mode_changed.connect(_on_mode)
	_on_mode(GameState.mode)
	_shot_path = str(opts.get("screenshot", ""))
	_shot_frame = int(opts.get("frames", "90"))
	_quit_after = int(opts.get("quit-after", "-1"))
	_run_seconds = float(opts.get("run-seconds", "-1"))
	_say = str(opts.get("say", ""))   # tests: say one line in the world chat once connected
	_fight = opts.has("fight")   # screenshots/tests: target the nearest monster and attack it
	if opts.has("open"):
		var w := str(opts["open"])
		if w == "map":
			hud.minimap.big = true
		else:
			hud.windows.call_deferred("toggle", w)
	_listen_to_page()
	LokiApi.start()


func _options() -> Dictionary:
	var out := {}
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--") and a.find("=") > 0:
			var kv := a.substr(2).split("=", true, 1)
			out[kv[0]] = kv[1]
	if OS.has_feature("web"):
		var win = JavaScriptBridge.get_interface("window")
		if win != null:
			var h := str(win.location.hash).trim_prefix("#")
			for part in h.split("&"):
				var kv := part.split("=", true, 1)
				if kv.size() == 2 and kv[0] in ["mode", "pixel", "hour"]:
					out[kv[0]] = kv[1].uri_decode()
	return out


func _on_mode(m: String) -> void:
	Engine.max_fps = 30 if m == "background" else 0
	if world != null and world.player != null:
		world.player.visible = m == "play"
		world.player.input_enabled = m == "play"


## Web build inside LOKI's window: the page (app/ui/world_godot/boot.js) tells us when LOKI
## World moves between the home-screen background and the Settings panel.
func _listen_to_page() -> void:
	if not OS.has_feature("web"):
		return
	var win = JavaScriptBridge.get_interface("window")
	if win == null:
		return
	_js_cb = JavaScriptBridge.create_callback(_on_page_message)
	win.addEventListener("message", _js_cb)


func _on_page_message(args: Array) -> void:
	if args.is_empty():
		return
	var ev = args[0]
	var win = JavaScriptBridge.get_interface("window")
	if ev == null or win == null or str(ev.origin) != str(win.location.origin):
		return
	var data = ev.data
	if not (data is JavaScriptObject):
		return
	if str(data.lokiWorld) == "mode":
		GameState.set_mode(str(data.mode))


func _unhandled_input(event: InputEvent) -> void:
	if GameState.mode != "play" or world == null:
		return
	if event is InputEventMouse:
		var pos: Vector2 = (event as InputEventMouse).position / float(pixel)
		world.player.handle_mouse(event, pos)
		return
	if event is InputEventKey and event.pressed and not event.echo:
		if hud.handle_key(event):
			get_viewport().set_input_as_handled()


func _input(event: InputEvent) -> void:
	# a mouse release must reach the player even over a HUD panel, or a drag would never end
	if event is InputEventMouseButton and not event.pressed and world != null:
		world.player.handle_mouse(event, (event as InputEventMouse).position / float(pixel))


func _process(delta: float) -> void:
	_frames += 1
	_t += delta
	if _say != "" and not LokiApi.offline and _t > 1.0:
		LokiApi.say_to_players(_say)
		_say = ""
	if _fight and _frames == 20:
		world.player.target_next()
		world.player.interact()
		world.player.use_slot(2)
	if _shot_path != "" and _frames == _shot_frame:
		var img := get_viewport().get_texture().get_image()
		img.save_png(_shot_path)
		print("LOKI World: screenshot saved to ", _shot_path)
		get_tree().quit()
	if (_quit_after > 0 and _frames >= _quit_after) or (_run_seconds > 0.0 and _t >= _run_seconds):
		print("LOKI World: ran %d frames, source=%s, zones=%d, npcs=%d, monsters=%d, quests=%d, remotes=%d, loot=%d" % [_frames,
				GameState.source, world.zones.size(), world.npcs.size(), world.monsters.size(),
				GameState.state.get("quests", []).size(), world.remotes.size(), GameState.loot_items().size()])
		get_tree().quit()
