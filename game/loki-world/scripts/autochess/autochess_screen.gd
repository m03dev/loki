class_name AutoChessScreen
extends Control
## Standalone local Auto Chess prototype overlay; deliberately isolated from MMO GameState.

const COLS := 8
const ROWS := 6
const WORLD_CELL_SIZE := 2.5
const CELL := Vector2(78.0, 62.0)
const HEROES := [
	{"name": "Vanguard", "role": "Guardian", "hp": 130, "atk": 16, "range": 1, "color": Color(0.9, 0.37, 0.27)},
	{"name": "Stormcaller", "role": "Mage", "hp": 78, "atk": 27, "range": 3, "color": Color(0.48, 0.58, 1.0)},
	{"name": "Ranger", "role": "Marksman", "hp": 88, "atk": 22, "range": 3, "color": Color(0.33, 0.82, 0.53)},
	{"name": "Medic", "role": "Support", "hp": 96, "atk": 12, "range": 2, "color": Color(0.28, 0.8, 0.75)},
	{"name": "Duelist", "role": "Assassin", "hp": 91, "atk": 24, "range": 1, "color": Color(0.9, 0.68, 0.24)},
]
const BOARD_ORIGIN := Vector2(318.0, 108.0)

var round_number: int = 1
var gold: int = 10
var phase: String = "PREP"
var units: Array[Dictionary] = []
var shop: Array[Dictionary] = []
var selected_shop: int = -1
var battle_clock: float = 0.0
var battle_log: String = "Choose a hero, then place them on your half of the board."
var _shop_row: HBoxContainer
var _status: Label
var _start_button: Button
var _rng := RandomNumberGenerator.new()
const ARENA_SCRIPT = preload("res://scripts/autochess/arena_3d.gd")
var _arena_node: Node3D
var _arena_viewport: SubViewport
var _arena_backdrop: TextureRect
var _camera: Camera3D
var _avatar: Node3D
var _arena: Node3D
var _camera_yaw: float = 0.0
var _camera_pitch: float = -0.28
var _camera_distance: float = 30.0
var _dragging_camera: bool = false
var _last_view_size: Vector2 = Vector2.ZERO
var _health_refresh_clock: float = 0.0


func _ready() -> void:
	_rng.seed = 13579
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	_build_arena()
	_build_ui()
	_roll_shop()
	_sync_unit_visuals()
	queue_redraw()
	await get_tree().process_frame
	_camera = _arena_node.camera
	_avatar = _arena_node.avatar
	_update_camera_transform()
	_apply_arena_size()


func _apply_arena_size() -> void:
	if _arena_viewport == null or _arena_backdrop == null:
		return
	var view_size := get_viewport_rect().size
	_arena_viewport.size = Vector2i(maxi(1, int(view_size.x)), maxi(1, int(view_size.y)))
	_arena_backdrop.size = view_size
	_last_view_size = view_size


func _build_arena() -> void:
	_arena_viewport = SubViewport.new()
	_arena_viewport.name = "Arena3D"
	_arena_viewport.own_world_3d = true
	_arena_viewport.size = Vector2i(1280, 720)
	_arena_viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	_arena_viewport.msaa_3d = Viewport.MSAA_DISABLED
	add_child(_arena_viewport)
	_arena_node = ARENA_SCRIPT.new()
	_arena_node.name = "AutoChessIsland"
	_arena_viewport.add_child(_arena_node)
	_arena_node.camera_yaw = _camera_yaw
	_arena_node.camera_pitch = _camera_pitch
	_arena_node.camera_distance = _camera_distance
	_arena_backdrop = TextureRect.new()
	_arena_backdrop.name = "ArenaBackdrop"
	_arena_backdrop.texture = _arena_viewport.get_texture()
	_arena_backdrop.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_arena_backdrop.stretch_mode = TextureRect.STRETCH_SCALE
	_arena_backdrop.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_arena_backdrop.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_arena_backdrop)
	_arena_backdrop.move_to_front()
	_arena_node.camera_yaw = _camera_yaw
	_arena_node.camera_pitch = _camera_pitch
	_arena_node.camera_distance = _camera_distance
	_arena = _arena_node
	_camera = _arena_node.camera
	_avatar = _arena_node.avatar


func _sync_unit_visuals() -> void:
	if _arena_node != null:
		_arena_node.set_units(units)


func _sync_unit_health_visuals() -> void:
	if _arena_node != null:
		_arena_node.update_unit_health(units)


func _update_viewport_size() -> void:
	var current_size := get_viewport_rect().size
	if current_size != _last_view_size:
		_apply_arena_size()
		var shop_title := get_node_or_null("ShopTitle") as Label
		if shop_title != null:
			shop_title.position.y = current_size.y - 144.0
		if _shop_row != null:
			_shop_row.position.y = current_size.y - 112.0


func _update_camera_transform() -> void:
	if _arena_node == null:
		return
	_arena_node.camera_yaw = _camera_yaw
	_arena_node.camera_pitch = _camera_pitch
	_arena_node.camera_distance = _camera_distance
	_arena_node.update_camera()


func _build_ui() -> void:
	var header := HBoxContainer.new()
	header.position = Vector2(24, 18)
	header.size = Vector2(1230, 44)
	header.add_theme_constant_override("separation", 8)
	add_child(header)
	var title := Label.new()
	title.text = "LOKI AUTO CHESS   •   TACTICAL ARENA"
	title.custom_minimum_size.x = 520.0
	title.add_theme_font_size_override("font_size", 22)
	title.add_theme_color_override("font_color", Color(1.0, 0.83, 0.38))
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(title)
	_start_button = _button("START BATTLE", _start_battle)
	_start_button.custom_minimum_size = Vector2(164, 40)
	header.add_child(_start_button)
	header.add_child(_button("REFRESH  •  2G", _refresh_shop))
	header.add_child(_button("EXIT  ×", close_screen))
	_status = Label.new()
	_status.position = Vector2(24, 72)
	_status.size = Vector2(260, 245)
	_status.add_theme_font_size_override("font_size", 16)
	_status.add_theme_color_override("font_color", Color(0.88, 0.91, 1.0))
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(_status)
	var shop_title := Label.new()
	shop_title.name = "ShopTitle"
	shop_title.text = "RECRUIT HEROES  •  CLICK A SHOP CARD, THEN A BLUE TILE"
	shop_title.position = Vector2(32, get_viewport_rect().size.y - 144)
	shop_title.add_theme_color_override("font_color", Color(1.0, 0.83, 0.38))
	add_child(shop_title)
	_shop_row = HBoxContainer.new()
	_shop_row.position = Vector2(32, get_viewport_rect().size.y - 112)
	_shop_row.size = Vector2(620, 96)
	_shop_row.mouse_filter = Control.MOUSE_FILTER_STOP
	_shop_row.add_theme_constant_override("separation", 10)
	add_child(_shop_row)
	_refresh_status()


func _button(text_: String, callback: Callable) -> Button:
	var button := Button.new()
	button.text = text_
	button.custom_minimum_size = Vector2(132, 40)
	button.focus_mode = Control.FOCUS_NONE
	button.pressed.connect(callback)
	return button


func _roll_shop() -> void:
	selected_shop = -1
	shop.clear()
	for i in 4:
		shop.append(HEROES[_rng.randi_range(0, HEROES.size() - 1)].duplicate(true))
	_refresh_shop_cards()


func _refresh_shop_cards() -> void:
	if _shop_row == null:
		return
	for child in _shop_row.get_children():
		child.queue_free()
	for i in shop.size():
		var hero: Dictionary = shop[i]
		var card := _button("%s\n%s\n%dG  •  %d ATK" % [hero["name"], hero["role"], 3, hero["atk"]], func(): _select_shop(i))
		card.custom_minimum_size = Vector2(145, 88)
		card.add_theme_color_override("font_color", hero["color"])
		card.disabled = phase != "PREP" or gold < 3
		_shop_row.add_child(card)


func _select_shop(index: int) -> void:
	if phase != "PREP" or index < 0 or index >= shop.size():
		return
	selected_shop = index
	battle_log = "%s selected — choose an empty tile on your side." % shop[index]["name"]
	_refresh_status()
	queue_redraw()


func _refresh_shop() -> void:
	if phase != "PREP" or gold < 2:
		return
	gold -= 2
	_roll_shop()
	_refresh_status()


func _update_start_button() -> void:
	if _start_button == null:
		return
	var ally_count: int = 0
	for unit in units:
		if not unit.get("enemy", false):
			ally_count += 1
	_start_button.disabled = phase != "PREP" or ally_count == 0
	_start_button.text = "AUTO BATTLE" if phase == "BATTLE" else "START ROUND %d" % round_number


func _start_battle() -> void:
	if phase != "PREP":
		return
	if units.is_empty():
		battle_log = "Recruit a hero on a BLUE tile to begin."
		_refresh_status()
		return
	phase = "BATTLE"
	selected_shop = -1
	battle_clock = 0.0
	for unit in units:
		unit["hp"] = unit["max_hp"]
	for i in mini(3 + round_number, 6):
		var template: Dictionary = HEROES[_rng.randi_range(0, HEROES.size() - 1)]
		var enemy: Dictionary = template.duplicate(true)
		enemy["name"] = "Rival " + str(template["name"])
		enemy["hp"] = int(template["hp"]) + round_number * 10
		enemy["max_hp"] = enemy["hp"]
		enemy["atk"] = int(template["atk"]) + round_number * 2
		enemy["enemy"] = true
		enemy["cell"] = Vector2i(5 + (i % 3), floori(float(i) / 3.0))
		units.append(enemy)
	phase = "BATTLE"
	battle_log = "Round %d — your heroes are fighting automatically!" % round_number
	_start_button.text = "AUTO BATTLE"
	_start_button.disabled = true
	_sync_unit_visuals()
	_update_start_button()
	_refresh_shop_cards()
	_refresh_status()
	queue_redraw()


func _process(delta: float) -> void:
	_update_viewport_size()
	_update_avatar_movement(delta)
	_health_refresh_clock += delta
	if _health_refresh_clock >= 0.16:
		_health_refresh_clock = 0.0
		_sync_unit_health_visuals()
	if phase != "BATTLE":
		return
	battle_clock += delta
	if battle_clock < 0.82:
		return
	battle_clock = 0.0
	var allies: Array[Dictionary] = []
	var enemies: Array[Dictionary] = []
	for unit in units:
		if float(unit["hp"]) <= 0.0:
			continue
		if unit.get("enemy", false):
			enemies.append(unit)
		else:
			allies.append(unit)
	if allies.is_empty() or enemies.is_empty():
		_finish_battle(not allies.is_empty())
		return
	var acting_side: Array[Dictionary] = allies if _rng.randf() < 0.5 else enemies
	var opposing_side: Array[Dictionary] = enemies if acting_side == allies else allies
	var attacker: Dictionary = acting_side[_rng.randi_range(0, acting_side.size() - 1)]
	var targets: Array[Dictionary] = opposing_side
	var target: Dictionary = targets[_rng.randi_range(0, targets.size() - 1)]
	target["hp"] = maxf(0.0, float(target["hp"]) - float(attacker["atk"]))
	battle_log = "%s strikes %s for %d!" % [attacker["name"], target["name"], int(attacker["atk"])]
	_refresh_status()
	queue_redraw()


func _finish_battle(won: bool) -> void:
	phase = "PREP"
	units = units.filter(func(unit: Dictionary) -> bool: return not unit.get("enemy", false))
	_sync_unit_visuals()
	if won:
		gold += 5
		battle_log = "Victory! +5 gold. Set up your formation for the next round."
	else:
		gold += 2
		battle_log = "Defeat — consolation +2 gold. Reposition and try again."
	round_number += 1
	_start_button.text = "START ROUND %d" % round_number
	_start_button.disabled = false
	_refresh_shop_cards()
	_refresh_status()
	queue_redraw()


func _refresh_status() -> void:
	if _status == null:
		return
	_update_start_button()
	var team_count: int = 0
	for unit in units:
		if not unit.get("enemy", false):
			team_count += 1
	_status.text = "ROUND %d     %s\nGOLD     %d\nTEAM     %d / 6\n\n%s" % [round_number, phase, gold, team_count, battle_log]


func _update_avatar_movement(delta: float) -> void:
	if _avatar == null:
		return
	var direction := Vector3.ZERO
	if Input.is_key_pressed(KEY_W) or Input.is_key_pressed(KEY_UP):
		direction.z -= 1.0
	if Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN):
		direction.z += 1.0
	if Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT):
		direction.x -= 1.0
	if Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT):
		direction.x += 1.0
	if direction.length_squared() <= 0.0:
		return
	direction = direction.normalized().rotated(Vector3.UP, _camera_yaw)
	_avatar.position += direction * 5.0 * delta
	var center_limit: float = 10.0
	_avatar.position.x = clampf(_avatar.position.x, -center_limit, center_limit)
	_avatar.position.z = clampf(_avatar.position.z, -center_limit, center_limit)
	_avatar.rotation.y = atan2(direction.x, direction.z)
	_update_camera_transform()


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		var button_event := event as InputEventMouseButton
		if button_event.button_index == MOUSE_BUTTON_RIGHT:
			_dragging_camera = button_event.pressed
			accept_event()
			return
		if button_event.pressed and button_event.button_index == MOUSE_BUTTON_WHEEL_UP:
			_camera_distance = maxf(18.0, _camera_distance - 1.5)
			_update_camera_transform()
			accept_event()
			return
		if button_event.pressed and button_event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			_camera_distance = minf(36.0, _camera_distance + 1.5)
			_update_camera_transform()
			accept_event()
			return
		if button_event.button_index != MOUSE_BUTTON_LEFT or not button_event.pressed:
			return
		var click_position: Vector2 = button_event.position
		if click_position.y >= get_viewport_rect().size.y - 160.0:
			return
		if click_position.y < 64.0 or click_position.x < 310.0:
			return
		var cell := _screen_position_to_cell(click_position)
		if cell.x >= 0:
			_place_or_remove(cell)
			accept_event()
	elif event is InputEventMouseMotion and _dragging_camera:
		var motion := event as InputEventMouseMotion
		_camera_yaw -= motion.relative.x * 0.006
		_camera_pitch = clampf(_camera_pitch - motion.relative.y * 0.004, -0.75, 0.08)
		_update_camera_transform()
		accept_event()


func _screen_position_to_cell(screen_position: Vector2) -> Vector2i:
	if _camera == null or _arena_viewport == null:
		return Vector2i(-1, -1)
	var ray_origin: Vector3 = _camera.project_ray_origin(screen_position)
	var ray_direction: Vector3 = _camera.project_ray_normal(screen_position)
	var plane := Plane(Vector3.UP, 0.25)
	var hit_point: Variant = plane.intersects_ray(ray_origin, ray_direction)
	if hit_point == null:
		return Vector2i(-1, -1)
	var board_hit: Vector3 = hit_point
	var cell_x: int = floori(board_hit.x / WORLD_CELL_SIZE + 4.0)
	var cell_y: int = floori(board_hit.z / WORLD_CELL_SIZE + 3.0)
	if cell_x < 0 or cell_y < 0 or cell_x >= COLS or cell_y >= ROWS:
		return Vector2i(-1, -1)
	return Vector2i(cell_x, cell_y)


func _place_or_remove(cell: Vector2i) -> void:
	if phase != "PREP" or cell.x >= COLS / 2:
		return
	var existing_index: int = -1
	for i in units.size():
		if not units[i].get("enemy", false) and units[i]["cell"] == cell:
			existing_index = i
			break
	var allied_count: int = 0
	for unit in units:
		if not unit.get("enemy", false):
			allied_count += 1
	if selected_shop >= 0 and existing_index < 0 and allied_count < 6 and gold >= 3 and selected_shop < shop.size():
		var unit: Dictionary = shop[selected_shop].duplicate(true)
		unit["max_hp"] = unit["hp"]
		unit["cell"] = cell
		unit["enemy"] = false
		units.append(unit)
		gold -= 3
		shop.remove_at(selected_shop)
		selected_shop = -1
		battle_log = "%s joins your formation." % unit["name"]
	elif existing_index >= 0:
		var sold: Dictionary = units[existing_index]
		gold += 2
		battle_log = "%s sold for 2 gold." % sold["name"]
		units.remove_at(existing_index)
	_sync_unit_visuals()
	_refresh_shop_cards()
	_refresh_status()
	queue_redraw()


func _draw() -> void:
	var viewport_size: Vector2 = get_viewport_rect().size
	# Keep the 3D island visible. Only HUD plates are drawn here; no full-screen
	# fill hides the SubViewport behind this Control.
	draw_rect(Rect2(Vector2(14, 12), Vector2(viewport_size.x - 28, 54)), Color(0.025, 0.04, 0.07, 0.88))
	draw_rect(Rect2(Vector2(18, 70), Vector2(288, viewport_size.y - 92)), Color(0.035, 0.055, 0.085, 0.78))
	draw_rect(Rect2(Vector2(18, 70), Vector2(288, viewport_size.y - 92)), Color(0.48, 0.65, 0.73, 0.6), false, 1.0)
	draw_rect(Rect2(Vector2(18, viewport_size.y - 152), Vector2(916, 126)), Color(0.025, 0.04, 0.07, 0.9))
	draw_string(ThemeDB.fallback_font, Vector2(32, viewport_size.y - 30), "WASD MOVE   •   RIGHT-DRAG ORBIT   •   WHEEL ZOOM", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color(0.73, 0.83, 0.9))


func close_screen() -> void:
	queue_free()
