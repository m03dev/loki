class_name Minimap
extends Control
## Top right: the minimap (turns with the camera; islands, bridges, you, agents, monsters, other
## players), the zone name and the local time. M opens the big map: click an island to fly there.

var hud: Node
var big := false
const R := 84.0
const SCALE := 2.4          # minimap pixels per metre
var _click_zones: Array = []   # [Rect2, zone] on the big map


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_PASS
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)


func _has_point(p: Vector2) -> bool:
	if big:
		return true
	return (p - _centre()).length() < R + 4


func _centre() -> Vector2:
	return Vector2(size.x - R - 16, R + 30)


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		if big:
			for row in _click_zones:
				if (row[0] as Rect2).has_point(event.position):
					hud.world.fly_to(str(row[1]))
					big = false
					accept_event()
					return
			big = false
		else:
			big = true
		accept_event()


func _process(_d: float) -> void:
	queue_redraw()


func _draw() -> void:
	if hud == null or hud.world == null or GameState.mode != "play":
		return
	var w = hud.world
	var p: Player = w.player
	var c := _centre()
	var yaw: float = p.cam_yaw
	var to_map := func(pos: Vector3) -> Vector2:
		var d := Vector2(pos.x - p.global_position.x, pos.z - p.global_position.z) * SCALE
		return d.rotated(yaw)   # camera forward -> map up
	draw_circle(c, R + 3, Color(0.32, 0.35, 0.45))
	draw_circle(c, R, Color(0.1, 0.17, 0.3))
	for n in w.zones.keys():
		var z: Dictionary = w.zones[n]
		var mp: Vector2 = c + to_map.call(z["center"])
		var rr: float = float(z["radius"]) * SCALE
		if (mp - c).length() - rr < R:
			draw_circle(mp, rr, Color(0.3, 0.55, 0.3) if z["home"] else Color(0.35, 0.45, 0.6))
	for m in w.monsters_alive():
		_dot(c, to_map.call(m.global_position), Color(1, 0.3, 0.25), 3.5)
	for n in w.npcs.values():
		if is_instance_valid(n):
			_dot(c, to_map.call(n.global_position), UiKit.GOLD if n.quest_giver else Color(1, 0.95, 0.6), 3.0 if not n.quest_giver else 4.5)
	for r in w.remotes.values():
		if is_instance_valid(r):
			_dot(c, to_map.call(r.global_position), Color(0.4, 0.75, 1.0), 4.0)
	# you: an arrow pointing where you face (map up = camera forward)
	var f := Vector2(sin(p.rotation.y), cos(p.rotation.y)).rotated(yaw)
	var side := Vector2(-f.y, f.x)
	draw_colored_polygon(PackedVector2Array([c + f * 9.0, c - f * 5.0 + side * 5.0, c - f * 5.0 - side * 5.0]), Color.WHITE)
	draw_arc(c, R, 0, TAU, 48, Color(0, 0, 0), 2.0)
	var zone_name: String = p.zone if p.zone != "" else "Open sky"
	UiKit.text(self, Vector2(c.x - R - 30, 18), zone_name, UiKit.GOLD, 13, HORIZONTAL_ALIGNMENT_CENTER, R * 2 + 60)
	var hr: float = w.hour()
	UiKit.text(self, Vector2(c.x - R, c.y + R + 18), "%02d:%02d  %s" % [int(hr), int(fmod(hr, 1.0) * 60.0), "night" if w.is_night() else "day"], UiKit.DIM, 11, HORIZONTAL_ALIGNMENT_CENTER, R * 2)
	if big:
		_draw_big()


func _dot(c: Vector2, d: Vector2, col: Color, rad: float) -> void:
	if d.length() < R - 3:
		draw_circle(c + d, rad, Color(0, 0, 0))
		draw_circle(c + d, rad - 1.0, col)


func _draw_big() -> void:
	var w = hud.world
	var rect := Rect2(size * 0.15, size * 0.7)
	UiKit.frame(self, rect, Color(0.05, 0.08, 0.14, 0.96))
	UiKit.text(self, rect.position + Vector2(12, 22), "LOKI World - one island per machine. Click an island to fly there.", UiKit.GOLD, 14)
	var extent := 10.0
	for z in w.zones.values():
		extent = maxf(extent, (z["center"] as Vector3).length() + float(z["radius"]))
	var sc := minf(rect.size.x, rect.size.y) * 0.42 / extent
	var mid := rect.get_center()
	_click_zones.clear()
	for n in w.zones.keys():
		var z: Dictionary = w.zones[n]
		var mp: Vector2 = mid + Vector2(z["center"].x, z["center"].z) * sc
		if not z["home"]:
			draw_line(mid, mp, Color(0.4, 1.0, 0.95, 0.6), 3.0)
	for n in w.zones.keys():
		var z: Dictionary = w.zones[n]
		var mp: Vector2 = mid + Vector2(z["center"].x, z["center"].z) * sc
		var rr := float(z["radius"]) * sc
		draw_circle(mp, rr, Color(0.3, 0.55, 0.3) if z["home"] else Color(0.35, 0.45, 0.6))
		draw_arc(mp, rr, 0, TAU, 32, Color(0, 0, 0), 2.0)
		var label := str(n) + ("  (you are here)" if z["home"] else "")
		UiKit.text(self, mp + Vector2(-120, -rr - 6), label, Color.WHITE, 14, HORIZONTAL_ALIGNMENT_CENTER, 240)
		_click_zones.append([Rect2(mp - Vector2(rr, rr), Vector2(rr, rr) * 2.0), n])
	var pp := mid + Vector2(w.player.global_position.x, w.player.global_position.z) * sc
	draw_circle(pp, 5, Color.WHITE)
	for r in w.remotes.values():
		if is_instance_valid(r):
			var rp := mid + Vector2(r.global_position.x, r.global_position.z) * sc
			draw_circle(rp, 5, Color(0.4, 0.75, 1.0))
			UiKit.text(self, rp + Vector2(8, 4), r.display_name, Color(0.6, 0.85, 1.0), 12)
