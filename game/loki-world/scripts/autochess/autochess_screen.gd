class_name AutoChessScreen
extends Control
## Standalone local Auto Chess prototype overlay; deliberately isolated from MMO GameState.

const COLS := 8
const ROWS := 6
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
var _viewport_container: SubViewportContainer
var _arena_viewport: SubViewport
var _arena: Node3D
var _camera: Camera3D
var _avatar: Node3D
var _camera_yaw: float = 0.0
var _camera_pitch: float = -0.28
var _camera_distance: float = 22.0
var _dragging_camera: bool = false
var _unit_visuals: Array[Node3D] = []
var _last_view_size: Vector2 = Vector2.ZERO


func _ready() -> void:
	_rng.seed = 13579
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	_build_arena()
	_build_ui()
	_roll_shop()
	_sync_unit_visuals()
	queue_redraw()


func _build_arena() -> void:
	_viewport_container = SubViewportContainer.new()
	_viewport_container.name = "ArenaView"
	_viewport_container.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_viewport_container.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_viewport_container.stretch = true
	_viewport_container.z_index = -1
	add_child(_viewport_container)
	_arena_viewport = SubViewport.new()
	_arena_viewport.name = "Arena3D"
	_arena_viewport.own_world_3d = true
	_arena_viewport.handle_input_locally = false
	_arena_viewport.msaa_3d = Viewport.MSAA_DISABLED
	_viewport_container.add_child(_arena_viewport)
	_arena = Node3D.new()
	_arena.name = "AutoChessIsland"
	_arena_viewport.add_child(_arena)
	_build_island_environment()
	_build_island_geometry()
	_build_arena_camera()
	_build_avatar()


func _build_island_environment() -> void:
	var environment_node := WorldEnvironment.new()
	var environment := Environment.new()
	environment.background_mode = Environment.BG_SKY
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color(0.56, 0.7, 0.88)
	environment.ambient_light_energy = 0.72
	environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	var sky := Sky.new()
	var sky_material := ProceduralSkyMaterial.new()
	sky_material.sky_top_color = Color(0.08, 0.2, 0.39)
	sky_material.sky_horizon_color = Color(0.46, 0.7, 0.82)
	sky_material.ground_bottom_color = Color(0.025, 0.06, 0.1)
	sky_material.ground_horizon_color = Color(0.26, 0.42, 0.44)
	sky.sky_material = sky_material
	environment.sky = sky
	environment_node.environment = environment
	_arena.add_child(environment_node)
	var sun := DirectionalLight3D.new()
	sun.rotation = Vector3(deg_to_rad(-52.0), deg_to_rad(-28.0), 0.0)
	sun.light_color = Color(1.0, 0.84, 0.65)
	sun.light_energy = 1.5
	sun.shadow_enabled = true
	_arena.add_child(sun)


func _build_island_geometry() -> void:
	_add_primitive(_arena, "Ocean", BoxMesh.new(), Vector3(0.0, -15.0, 0.0), Vector3(180.0, 2.0, 180.0), Color(0.035, 0.19, 0.31))
	_add_primitive(_arena, "IslandRock", CylinderMesh.new(), Vector3(0.0, -1.7, 0.0), Vector3(1.0, 1.8, 1.0), Color(0.19, 0.23, 0.27), 25.0, 28.0)
	_add_primitive(_arena, "IslandGrass", CylinderMesh.new(), Vector3(0.0, -0.45, 0.0), Vector3(1.0, 0.58, 1.0), Color(0.19, 0.39, 0.29), 24.0, 24.0)
	_add_primitive(_arena, "ArenaPlatform", CylinderMesh.new(), Vector3(0.0, 0.0, 0.0), Vector3(1.0, 0.18, 1.0), Color(0.27, 0.34, 0.3), 18.0, 48.0)
	for x in 8:
		for z in 6:
			var side_color: Color = Color(0.14, 0.31, 0.27) if x < 4 else Color(0.34, 0.2, 0.21)
			var tile_color: Color = side_color.lightened(0.04) if (x + z) % 2 == 0 else side_color.darkened(0.05)
			_add_primitive(_arena, "Board_%d_%d" % [x, z], BoxMesh.new(), _board_world_position(Vector2i(x, z)), Vector3(2.45, 0.15, 2.45), tile_color)
	_add_primitive(_arena, "BoardBorder", BoxMesh.new(), Vector3(0.0, 0.16, 0.0), Vector3(20.4, 0.16, 15.7), Color(0.48, 0.37, 0.2))
	for index in 8:
		var angle: float = TAU * float(index) / 8.0
		var position := Vector3(cos(angle) * 16.5, -0.6, sin(angle) * 16.5)
		_add_primitive(_arena, "RuinPillar_%d" % index, CylinderMesh.new(), position, Vector3(0.8, 2.6, 0.8), Color(0.3, 0.37, 0.39), 0.6, 8.0)
		_add_primitive(_arena, "PillarCap_%d" % index, BoxMesh.new(), position + Vector3(0, 1.3, 0), Vector3(1.35, 0.3, 1.35), Color(0.63, 0.49, 0.28))
	for index in 10:
		var angle: float = TAU * float(index) / 10.0
		var position := Vector3(cos(angle) * 13.8, 0.15, sin(angle) * 13.8)
		_add_primitive(_arena, "Crystal_%d" % index, SphereMesh.new(), position, Vector3(0.35, 1.1, 0.35), Color(0.25, 0.76, 0.88))


func _build_arena_camera() -> void:
	var pivot := Node3D.new()
	pivot.name = "CameraPivot"
	pivot.position = Vector3(0.0, 1.4, 0.0)
	_arena.add_child(pivot)
	_camera = Camera3D.new()
	_camera.name = "ThirdPersonCamera"
	_camera.fov = 58.0
	_camera.current = true
	pivot.add_child(_camera)
	_update_camera_transform()


func _build_avatar() -> void:
	_avatar = Node3D.new()
	_avatar.name = "ThirdPersonAvatar"
	_avatar.position = Vector3(0.0, 0.0, 7.5)
	_arena.add_child(_avatar)
	_add_primitive(_avatar, "Body", CapsuleMesh.new(), Vector3(0.0, 1.0, 0.0), Vector3(0.72, 1.15, 0.72), Color(0.28, 0.67, 0.91))
	_add_primitive(_avatar, "Head", SphereMesh.new(), Vector3(0.0, 2.0, 0.0), Vector3(0.57, 0.57, 0.57), Color(0.91, 0.73, 0.55))
	_add_primitive(_avatar, "Shoulders", SphereMesh.new(), Vector3(0.0, 1.48, 0.0), Vector3(1.0, 0.42, 0.58), Color(0.76, 0.56, 0.23))


func _add_primitive(parent: Node3D, node_name: String, mesh: Mesh, position: Vector3, scale: Vector3, color: Color, top_radius: float = 0.5, bottom_radius: float = 0.5) -> MeshInstance3D:
	var instance := MeshInstance3D.new()
	instance.name = node_name
	if mesh is CylinderMesh:
		var cylinder := mesh as CylinderMesh
		cylinder.top_radius = top_radius
		cylinder.bottom_radius = bottom_radius
	instance.mesh = mesh
	instance.position = position
	instance.scale = scale
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = 0.84
	instance.material_override = material
	parent.add_child(instance)
	return instance


func _board_world_position(cell: Vector2i) -> Vector3:
	return Vector3((float(cell.x) - 3.5) * 2.5, 0.22, (float(cell.y) - 2.5) * 2.5)


func _update_camera_transform() -> void:
	if _camera == null:
		return
	var pivot := _camera.get_parent() as Node3D
	if pivot == null:
		return
	pivot.rotation = Vector3(_camera_pitch, _camera_yaw, 0.0)
	_camera.position = Vector3(0.0, 0.0, _camera_distance)
	_camera.look_at(pivot.global_position, Vector3.UP)


func _sync_unit_visuals() -> void:
	for visual in _unit_visuals:
		if is_instance_valid(visual):
			visual.queue_free()
	_unit_visuals.clear()
	if _arena == null:
		return
	for unit in units:
		var cell: Vector2i = unit["cell"]
		var root := Node3D.new()
		root.name = "Unit_%s" % str(unit["name"]).validate_node_name()
		root.position = _board_world_position(cell) + Vector3(0.0, 0.35, 0.0)
		_arena.add_child(root)
		var tint: Color = unit["color"]
		_add_primitive(root, "Body", CapsuleMesh.new(), Vector3(0.0, 0.9, 0.0), Vector3(0.55, 0.85, 0.55), tint)
		_add_primitive(root, "Head", SphereMesh.new(), Vector3(0.0, 1.85, 0.0), Vector3(0.43, 0.43, 0.43), Color(0.94, 0.77, 0.61))
		_add_primitive(root, "TeamCrest", SphereMesh.new(), Vector3(0.0, 2.45, 0.0), Vector3(0.28, 0.28, 0.28), Color(0.32, 0.92, 0.53) if not unit.get("enemy", false) else Color(0.98, 0.36, 0.3))
		_unit_visuals.append(root)


func _update_viewport_size() -> void:
	var current_size := get_viewport_rect().size
	if current_size != _last_view_size:
		_last_view_size = current_size
		_arena_viewport.size = Vector2i(maxi(1, int(current_size.x)), maxi(1, int(current_size.y)))


func _build_ui() -> void:
	var header := HBoxContainer.new()
	header.position = Vector2(24, 18)
	header.size = Vector2(1230, 44)
	add_child(header)
	var title := Label.new()
	title.text = "LOKI AUTO CHESS   •   TACTICAL ARENA"
	title.add_theme_font_size_override("font_size", 22)
	title.add_theme_color_override("font_color", Color(1.0, 0.83, 0.38))
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(title)
	_start_button = _button("START BATTLE", _start_battle)
	header.add_child(_start_button)
	header.add_child(_button("REFRESH  •  2G", _refresh_shop))
	header.add_child(_button("EXIT  ×", close_screen))
	_status = Label.new()
	_status.position = Vector2(24, 72)
	_status.size = Vector2(270, 170)
	_status.add_theme_font_size_override("font_size", 16)
	_status.add_theme_color_override("font_color", Color(0.88, 0.91, 1.0))
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	add_child(_status)
	var shop_title := Label.new()
	shop_title.text = "HERO SHOP     TAP A HERO, THEN A TILE"
	shop_title.position = Vector2(318, 512)
	shop_title.add_theme_color_override("font_color", Color(1.0, 0.83, 0.38))
	add_child(shop_title)
	_shop_row = HBoxContainer.new()
	_shop_row.position = Vector2(318, 542)
	_shop_row.size = Vector2(620, 108)
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


func _start_battle() -> void:
	if phase != "PREP":
		return
	if units.is_empty():
		battle_log = "Recruit at least one hero before starting the battle."
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
		enemy["cell"] = Vector2i(5 + (i % 3), i / 3)
		units.append(enemy)
	phase = "BATTLE"
	battle_log = "Round %d — your heroes are fighting automatically!" % round_number
	_start_button.text = "AUTO BATTLE"
	_start_button.disabled = true
	_refresh_shop_cards()
	_refresh_status()
	queue_redraw()


func _process(delta: float) -> void:
	_update_viewport_size()
	_update_avatar_movement(delta)
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
	var team_count: int = 0
	for unit in units:
		if not unit.get("enemy", false):
			team_count += 1
	_status.text = "ROUND %d     %s\nGOLD     %d\nTEAM     %d / 6\n\n%s" % [round_number, phase, gold, team_count, battle_log]


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		var local: Vector2 = event.position - BOARD_ORIGIN
		var cell := Vector2i(floori(local.x / CELL.x), floori(local.y / CELL.y))
		if local.x >= 0.0 and local.y >= 0.0 and cell.x < COLS and cell.y < ROWS:
			_place_or_remove(cell)
			accept_event()


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
	_refresh_shop_cards()
	_refresh_status()
	queue_redraw()


func _draw() -> void:
	var viewport_size: Vector2 = get_viewport_rect().size
	# This is a modal game screen: make the backdrop truly opaque so the MMO HUD
	# and world cannot bleed through beneath the board or shop.
	draw_rect(Rect2(Vector2.ZERO, viewport_size), Color(0.018, 0.025, 0.045, 1.0))
	draw_rect(Rect2(Vector2(14, 12), Vector2(viewport_size.x - 28, viewport_size.y - 24)), Color(0.035, 0.05, 0.082), false, 2.0)
	draw_rect(Rect2(Vector2(22, 70), Vector2(272, viewport_size.y - 96)), Color(0.055, 0.075, 0.115))
	draw_rect(Rect2(Vector2(22, 70), Vector2(272, viewport_size.y - 96)), Color(0.18, 0.25, 0.34), false, 1.0)
	draw_rect(Rect2(Vector2(306, 80), Vector2(648, 414)), Color(0.045, 0.065, 0.095))
	draw_rect(Rect2(Vector2(306, 80), Vector2(648, 414)), Color(0.18, 0.25, 0.34), false, 1.0)
	draw_string(ThemeDB.fallback_font, Vector2(318, 94), "RIVAL DEPLOYMENT", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color(1.0, 0.55, 0.45))
	draw_string(ThemeDB.fallback_font, Vector2(318, 490), "YOUR FORMATION", HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color(0.45, 0.78, 1.0))
	for y in ROWS:
		for x in COLS:
			var rect := Rect2(BOARD_ORIGIN + Vector2(x * CELL.x, y * CELL.y), CELL - Vector2(3, 3))
			var player_side: bool = x < COLS / 2
			var fill: Color = Color(0.12, 0.2, 0.27) if player_side else Color(0.24, 0.12, 0.16)
			if y >= 3:
				fill = fill.darkened(0.16)
			draw_rect(rect, fill)
			draw_rect(rect, Color(0.31, 0.52, 0.65) if player_side else Color(0.58, 0.32, 0.37), false, 1.0)
	# Central deployment boundary and subtle floor markers.
	var divider_x: float = BOARD_ORIGIN.x + COLS / 2.0 * CELL.x - 2.0
	draw_line(Vector2(divider_x, BOARD_ORIGIN.y + 3.0), Vector2(divider_x, BOARD_ORIGIN.y + ROWS * CELL.y - 3.0), Color(0.95, 0.69, 0.32, 0.75), 2.0)
	for unit in units:
		var cell: Vector2i = unit["cell"]
		var center := BOARD_ORIGIN + Vector2((cell.x + 0.5) * CELL.x, (cell.y + 0.5) * CELL.y)
		var tint: Color = unit["color"]
		draw_circle(center + Vector2(0, 3), 21.0, Color(0.015, 0.02, 0.03, 0.8))
		draw_circle(center, 19.0, tint.darkened(0.38))
		draw_circle(center, 15.0, tint)
		draw_string(ThemeDB.fallback_font, center + Vector2(-13, 4), str(unit["name"]).substr(0, 3).to_upper(), HORIZONTAL_ALIGNMENT_LEFT, 30, 11, Color.WHITE)
		var hp_ratio: float = clampf(float(unit["hp"]) / maxf(1.0, float(unit["max_hp"])), 0.0, 1.0)
		draw_rect(Rect2(center.x - 22, center.y + 23, 44, 4), Color(0.15, 0.04, 0.05))
		draw_rect(Rect2(center.x - 22, center.y + 23, 44 * hp_ratio, 4), Color(0.28, 0.9, 0.4) if not unit.get("enemy", false) else Color(0.95, 0.32, 0.3))


func close_screen() -> void:
	queue_free()
