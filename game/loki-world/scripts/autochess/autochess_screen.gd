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


func _ready() -> void:
	_rng.seed = 13579
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	_build_ui()
	_roll_shop()
	queue_redraw()


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
	draw_rect(Rect2(Vector2.ZERO, viewport_size), Color(0.025, 0.035, 0.065, 0.98))
	draw_rect(Rect2(Vector2(14, 12), Vector2(viewport_size.x - 28, viewport_size.y - 24)), Color(0.06, 0.08, 0.13), false, 2.0)
	draw_string(ThemeDB.fallback_font, Vector2(318, 94), "RIVAL DEPLOYMENT", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color(1.0, 0.55, 0.45))
	for y in ROWS:
		for x in COLS:
			var rect := Rect2(BOARD_ORIGIN + Vector2(x * CELL.x, y * CELL.y), CELL - Vector2(3, 3))
			var player_side: bool = x < COLS / 2
			var fill: Color = Color(0.14, 0.2, 0.26) if player_side else Color(0.25, 0.13, 0.16)
			if y >= 3:
				fill = fill.darkened(0.17)
			draw_rect(rect, fill)
			draw_rect(rect, Color(0.34, 0.48, 0.55) if player_side else Color(0.54, 0.32, 0.35), false, 1.0)
	for unit in units:
		var cell: Vector2i = unit["cell"]
		var center := BOARD_ORIGIN + Vector2((cell.x + 0.5) * CELL.x, (cell.y + 0.5) * CELL.y)
		var tint: Color = unit["color"]
		draw_circle(center, 19.0, tint.darkened(0.3))
		draw_circle(center, 15.0, tint)
		draw_string(ThemeDB.fallback_font, center + Vector2(-13, 4), str(unit["name"]).substr(0, 3).to_upper(), HORIZONTAL_ALIGNMENT_LEFT, 30, 11, Color.WHITE)
		var hp_ratio: float = clampf(float(unit["hp"]) / maxf(1.0, float(unit["max_hp"])), 0.0, 1.0)
		draw_rect(Rect2(center.x - 22, center.y + 23, 44, 4), Color(0.15, 0.04, 0.05))
		draw_rect(Rect2(center.x - 22, center.y + 23, 44 * hp_ratio, 4), Color(0.28, 0.9, 0.4) if not unit.get("enemy", false) else Color(0.95, 0.32, 0.3))
	draw_string(ThemeDB.fallback_font, Vector2(318, 498), battle_log.substr(0, 80), HORIZONTAL_ALIGNMENT_LEFT, 620, 12, Color(0.77, 0.83, 0.91))


func close_screen() -> void:
	queue_free()
