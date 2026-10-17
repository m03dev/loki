extends CanvasLayer
## The MMO HUD at full resolution over the pixelated 3D view: unit frames (you, target, party),
## minimap + clock, quest tracker, hotbar with cooldowns + cast bar + XP bar, chat, nameplates
## and combat numbers, banners (zone, level up, notices) and the windows.

var world: Node            # world.gd
var shrink := 3            # the 3D view's pixel size (SubViewportContainer.stretch_shrink)
var root: Control
var overlay: HudOverlay
var frames: UnitFrames
var hotbar: Hotbar
var minimap: Minimap
var tracker: QuestTracker
var chat: ChatBox
var windows: HudWindows
var banner: Label
var notices: VBoxContainer
var status_line: Label
var _banner_t := 0.0


func setup(world_node: Node, pixel: int) -> void:
	world = world_node
	shrink = pixel
	root = Control.new()
	root.theme = UiKit.theme()
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(root)
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	overlay = HudOverlay.new()
	overlay.hud = self
	root.add_child(overlay)
	tracker = QuestTracker.new()
	tracker.hud = self
	root.add_child(tracker)
	minimap = Minimap.new()
	minimap.hud = self
	root.add_child(minimap)
	hotbar = Hotbar.new()
	hotbar.hud = self
	root.add_child(hotbar)
	frames = UnitFrames.new()
	frames.hud = self
	root.add_child(frames)
	chat = ChatBox.new()
	chat.hud = self
	root.add_child(chat)
	chat.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	chat.position = Vector2(12, 0)
	banner = UiKit.label("", 30, UiKit.GOLD)
	banner.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	banner.set_anchors_preset(Control.PRESET_CENTER_TOP)
	banner.add_theme_constant_override("outline_size", 8)
	banner.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(banner)
	notices = VBoxContainer.new()
	notices.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(notices)
	status_line = UiKit.label("", 11, UiKit.DIM)
	status_line.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(status_line)
	windows = HudWindows.new()
	windows.hud = self
	root.add_child(windows)
	var p: Player = world.player
	p.zone_entered.connect(func(z): show_banner(z + (" - you are here" if z == GameState.self_zone else ""), Color(0.6, 1.0, 0.9)))
	p.wants_prompt.connect(windows.show_prompt)
	p.wants_talk.connect(windows.show_talk)
	world.float_text.connect(overlay.add_float)
	GameState.notice.connect(add_notice)
	GameState.level_up.connect(func(l): show_banner("LEVEL %d!" % l, UiKit.GOLD))
	GameState.mode_changed.connect(_on_mode)
	_on_mode(GameState.mode)


func camera() -> Camera3D:
	return world.player.camera if world != null and world.player != null else null


func _on_mode(m: String) -> void:
	root.visible = m == "play"


func show_banner(text_: String, color: Color) -> void:
	banner.text = text_
	banner.add_theme_color_override("font_color", color)
	_banner_t = 3.0


func add_notice(text_: String, color: Color) -> void:
	var l := UiKit.label(text_, 14, color)
	l.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	l.custom_minimum_size = Vector2(620, 0)
	l.set_meta("t", 4.0)
	notices.add_child(l)
	while notices.get_child_count() > 4:
		notices.get_child(0).free()


func _process(delta: float) -> void:
	var vs := root.get_viewport_rect().size
	chat.position = Vector2(12, vs.y - chat.size.y - 14)
	banner.position = Vector2(vs.x * 0.5 - banner.size.x * 0.5, vs.y * 0.18)
	notices.position = Vector2(vs.x * 0.5 - 310, vs.y * 0.25)
	status_line.position = Vector2(vs.x - 330, vs.y - 18)
	status_line.size = Vector2(320, 16)
	status_line.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	status_line.text = "%s   %d fps" % [{"engine": "LOKI (MMO API)", "derived": "LOKI", "offline": "offline demo"}.get(GameState.source, ""), Engine.get_frames_per_second()]
	if _banner_t > 0.0:
		_banner_t -= delta
		banner.modulate.a = clampf(_banner_t, 0.0, 1.0)
	for c in notices.get_children():
		var t := float(c.get_meta("t", 0.0)) - delta
		c.set_meta("t", t)
		c.modulate.a = clampf(t, 0.0, 1.0)
		if t <= 0.0:
			c.queue_free()


## Keys that open and close things (movement and skills are read by the player itself).
func handle_key(event: InputEvent) -> bool:
	var focus := root.get_viewport().gui_get_focus_owner()
	if focus is LineEdit:
		if event.is_action_pressed("cancel"):
			focus.release_focus()
			return true
		return false
	if event.is_action_pressed("chat"):
		chat.focus_input()
		return true
	if event.is_action_pressed("chat_slash"):
		chat.focus_input("/")
		return true
	if event.is_action_pressed("cancel"):
		if minimap.big:
			minimap.big = false
		elif not windows.close_all():
			world.player.cancel_cast()
			world.player.set_target(null)
		return true
	for pair in [["toggle_quests", "quests"], ["toggle_bags", "bags"], ["toggle_character", "character"], ["toggle_help", "help"]]:
		if event.is_action_pressed(pair[0]):
			windows.toggle(pair[1])
			return true
	if event.is_action_pressed("toggle_map"):
		minimap.big = not minimap.big
		return true
	if event.is_action_pressed("target_next"):
		world.player.target_next()
		return true
	if event.is_action_pressed("interact"):
		world.player.interact()
		return true
	if event.is_action_pressed("autorun"):
		world.player.autorun = not world.player.autorun
		return true
	for i in 9:
		if event.is_action_pressed("skill_%d" % (i + 1)):
			world.player.use_slot(i + 1)
			return true
	return false
