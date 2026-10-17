class_name Hotbar
extends Control
## Bottom centre: the 9-slot hotbar (keys 1-9; combat skills, Mend, LOKI actions that start real
## jobs, Hearth), cooldown sweeps, the cast bar above it and the XP bar along the bottom.

var hud: Node
const SLOT := 48.0
const GAP := 5.0
var hover := -1
var cast_name := ""
var cast_total := 0.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_PASS
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)


func _bar_rect() -> Rect2:
	var w := 9.0 * SLOT + 8.0 * GAP
	return Rect2((size.x - w) * 0.5, size.y - SLOT - 26.0, w, SLOT)


func _slot_rect(i: int) -> Rect2:
	var b := _bar_rect()
	return Rect2(b.position.x + i * (SLOT + GAP), b.position.y, SLOT, SLOT)


func _has_point(p: Vector2) -> bool:
	return _bar_rect().grow(4).has_point(p)


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion:
		hover = -1
		for i in 9:
			if _slot_rect(i).has_point(event.position):
				hover = i
	elif event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		for i in 9:
			if _slot_rect(i).has_point(event.position):
				hud.world.player.use_slot(i + 1)
				accept_event()


func _process(_d: float) -> void:
	queue_redraw()


func _draw() -> void:
	if hud == null or hud.world == null or GameState.mode != "play":
		return
	var p: Player = hud.world.player
	var b := _bar_rect()
	UiKit.frame(self, b.grow(5), Color(0.05, 0.06, 0.08, 0.85))
	for i in 9:
		var r := _slot_rect(i)
		var s := GameState.skill_in_slot(i + 1)
		draw_rect(r, Color(0.13, 0.14, 0.19))
		var kind := str(s.get("kind", ""))
		var tint: Color = {"combat": Color(0.9, 0.4, 0.35), "self": Color(0.4, 0.9, 0.5), "loki": Color(0.3, 0.9, 0.85), "travel": Color(0.9, 0.85, 0.5)}.get(kind, Color.WHITE)
		draw_rect(Rect2(r.position, Vector2(r.size.x, 3)), tint)
		UiKit.icon(self, str(s.get("id", "")), r.grow(-8), tint)
		var cd := GameState.cooldown_left(s)
		var total := float(s.get("cd_s", 1.0))
		if cd > 0.0:
			var k := cd / maxf(total, 0.01)
			var pts := PackedVector2Array([r.get_center()])
			var steps := 20
			for j in steps + 1:
				var ang := -PI * 0.5 + TAU * k * float(j) / float(steps)
				pts.append(r.get_center() + Vector2(cos(ang), sin(ang)) * SLOT * 0.75)
			draw_colored_polygon(pts, Color(0, 0, 0, 0.62))
			UiKit.text(self, r.position + Vector2(0, SLOT * 0.62), "%d" % ceili(cd) if cd >= 1.0 else "%.1f" % cd, Color.WHITE, 15, HORIZONTAL_ALIGNMENT_CENTER, SLOT)
		if p.en < float(s.get("energy", 0)):
			draw_rect(r, Color(0.1, 0.2, 0.6, 0.45))
		draw_rect(r, UiKit.GOLD if i == hover else Color(0.35, 0.38, 0.48), false, 2.0)
		UiKit.text(self, r.position + Vector2(3, 12), str(i + 1), UiKit.TEXT, 11)
	# cast bar
	if not p.casting.is_empty():
		var cr := Rect2(size.x * 0.5 - 140, b.position.y - 46, 280, 18)
		var k := float(p.casting["t"]) / maxf(float(p.casting["total"]), 0.01)
		UiKit.bar(self, cr, k, UiKit.GOLD.darkened(0.15), "%s  %.1fs" % [str(p.casting["skill"].get("name", "")), maxf(0.0, float(p.casting["total"]) - float(p.casting["t"]))])
	# XP bar
	var prof := GameState.profile()
	var xr := Rect2(b.position.x, size.y - 16, b.size.x, 10)
	var into := float(prof.get("xp_into", 0))
	var need := maxf(1.0, float(prof.get("xp_need", 1)))
	UiKit.bar(self, xr, into / need, UiKit.XP)
	UiKit.text(self, Vector2(xr.position.x, xr.position.y - 2), "Level %d   %d / %d XP" % [int(prof.get("level", 1)), int(into), int(need)], UiKit.TEXT, 11, HORIZONTAL_ALIGNMENT_CENTER, xr.size.x)
	# tooltip
	if hover >= 0:
		var s := GameState.skill_in_slot(hover + 1)
		var tip := "%s  [%d]" % [s.get("name", ""), hover + 1]
		var lines := [tip]
		match str(s.get("kind", "")):
			"combat":
				lines.append("Damage %s, range %s m" % [str(s.get("dmg", [])), str(s.get("range", ""))])
			"self":
				lines.append("Heals you")
			"loki":
				lines.append("A real LOKI job: you say what (%s)" % s.get("ask", ""))
			"travel":
				lines.append("Back to LOKI's hall on your island")
		lines.append("Cooldown %ss  Energy %s  Cast %ss" % [str(s.get("cd_s", 0)), str(s.get("energy", 0)), str(s.get("cast_s", 0))])
		var tr := Rect2(_slot_rect(hover).position + Vector2(-60, -18 - 18 * lines.size()), Vector2(270, 10 + 18 * lines.size()))
		UiKit.frame(self, tr)
		for j in lines.size():
			UiKit.text(self, tr.position + Vector2(8, 18 + 18 * j), str(lines[j]), UiKit.GOLD if j == 0 else UiKit.TEXT, 12)
