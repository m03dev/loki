class_name HudOverlay
extends Control
## Drawn over the 3D view, in full-resolution pixels: nameplates (level, name, class/task,
## health and energy bars), speech bubbles, the target marker and floating combat numbers.

var hud: Node
var floats: Array = []        # {pos: Vector3, text, color, t}
const MAX_DIST := 48.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)


func add_float(pos: Vector3, text_: String, color: Color) -> void:
	floats.append({"pos": pos, "text": text_, "color": color, "t": 0.0})
	if floats.size() > 40:
		floats.pop_front()


func _process(delta: float) -> void:
	for f in floats:
		f["t"] = float(f["t"]) + delta
	floats = floats.filter(func(f): return float(f["t"]) < 1.4)
	queue_redraw()


func _screen(p: Vector3) -> Variant:
	var cam: Camera3D = hud.camera()
	if cam == null or cam.is_position_behind(p):
		return null
	return cam.unproject_position(p) * float(hud.shrink)


func _draw() -> void:
	if hud == null or hud.world == null or GameState.mode != "play":
		return
	var cam: Camera3D = hud.camera()
	if cam == null:
		return
	var w = hud.world
	var actors: Array = [w.player]
	actors.append_array(w.npcs.values())
	actors.append_array(w.monsters.values())
	actors.append_array(w.remotes.values())
	actors.append_array(w.critters)
	var target: Actor = w.player.target
	var eye := cam.global_position
	var drawn := []
	for a in actors:
		if not is_instance_valid(a) or not a.visible:
			continue
		var p: Vector3 = a.nameplate_position()
		var d := eye.distance_to(p)
		if d > MAX_DIST and a != target:
			continue
		var sp = _screen(p)
		if sp == null:
			continue
		drawn.append([d, a, sp])
	drawn.sort_custom(func(x, y): return x[0] > y[0])   # far first, near on top
	for row in drawn:
		_plate(row[1], row[2], row[1] == target, row[0])
	for f in floats:
		var sp = _screen(f["pos"] + Vector3(0, float(f["t"]) * 1.3, 0))
		if sp == null:
			continue
		var k := 1.0 - float(f["t"]) / 1.4
		var col: Color = f["color"]
		col.a = clampf(k * 1.6, 0.0, 1.0)
		var size := 22 if str(f["text"]).ends_with("!") else 17
		UiKit.text(self, sp + Vector2(-40, 0), str(f["text"]), col, size, HORIZONTAL_ALIGNMENT_CENTER, 80)


func _plate(a: Actor, sp: Vector2, is_target: bool, dist: float) -> void:
	var fade := clampf(1.4 - dist / MAX_DIST, 0.35, 1.0)
	var col := a.name_color
	col.a = fade
	var name_line := a.display_name
	if a.level > 0 and not (a is Critter):
		name_line = "%d  %s" % [a.level, a.display_name]
	var y := sp.y
	if a.show_bars and a.alive:
		var bw := 64.0
		UiKit.bar(self, Rect2(sp.x - bw * 0.5, y - 6, bw, 6), a.hp / maxf(a.hp_max, 1.0), UiKit.HP if a.hostile else UiKit.HP_FRIEND)
		if a.en_max > 0.0:
			UiKit.bar(self, Rect2(sp.x - bw * 0.5, y, bw, 4), a.en / maxf(a.en_max, 1.0), UiKit.EN)
		y -= 9
	UiKit.text(self, Vector2(sp.x - 110, y - 2), name_line, col, 14 if is_target else 13, HORIZONTAL_ALIGNMENT_CENTER, 220)
	if a.title_line != "" and dist < 22.0:
		var tcol := UiKit.DIM
		tcol.a = fade
		UiKit.text(self, Vector2(sp.x - 130, y - 17), a.title_line, tcol, 11, HORIZONTAL_ALIGNMENT_CENTER, 260)
		y -= 13
	if a is NpcAgent and (a as NpcAgent).quest_giver:
		var has_done := false
		for q in GameState.state.get("quests", []):
			if str(q.get("status", "")) == "complete":
				has_done = true
				break
		UiKit.text(self, Vector2(sp.x - 20, y - 22), "?" if has_done else "!", UiKit.GOLD, 24, HORIZONTAL_ALIGNMENT_CENTER, 40)
		y -= 22
	if is_target:
		var r := Rect2(sp.x - 46, y - 18, 92, 40 + (sp.y - y))
		draw_rect(r, Color(1.0, 0.85, 0.3, 0.9), false, 2.0)
	if a.bubble != "" and dist < 30.0:
		var f := UiKit.font()
		var tw := minf(260.0, f.get_string_size(a.bubble, HORIZONTAL_ALIGNMENT_LEFT, -1, 12).x + 14)
		var lines := ceili(f.get_string_size(a.bubble, HORIZONTAL_ALIGNMENT_LEFT, -1, 12).x / 246.0)
		var bh := 8.0 + 15.0 * lines
		var br := Rect2(sp.x - tw * 0.5, y - 24 - bh, tw, bh)
		var red := a.bubble == "!"
		draw_rect(br, Color(1, 0.95, 0.9, 0.95) if not red else Color(0.9, 0.15, 0.1, 0.95))
		draw_rect(br, Color(0, 0, 0, 0.9), false, 2.0)
		draw_multiline_string(f, br.position + Vector2(7, 14), a.bubble, HORIZONTAL_ALIGNMENT_LEFT, tw - 14, 12, -1, Color(0.08, 0.08, 0.12) if not red else Color.WHITE)
