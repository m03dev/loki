class_name UnitFrames
extends Control
## Top left: your frame (portrait, name, level, health, energy), the target frame beside it,
## and the party frames below - the agents busy right now (working / waiting / blocked).

var hud: Node
const W := 250.0
const H := 64.0
var party_rects: Array = []      # [Rect2, NpcAgent] for clicks


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_PASS
	position = Vector2(12, 12)
	size = Vector2(W * 2 + 20, 360)


func _process(_d: float) -> void:
	queue_redraw()


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		for row in party_rects:
			if (row[0] as Rect2).has_point(event.position) and is_instance_valid(row[1]):
				hud.world.player.set_target(row[1])
				accept_event()
				return


func _has_point(p: Vector2) -> bool:
	for row in party_rects:
		if (row[0] as Rect2).has_point(p):
			return true
	return false


func _unit(r: Rect2, a: Actor, sub: String) -> void:
	UiKit.frame(self, r)
	var pr := Rect2(r.position + Vector2(6, 6), Vector2(r.size.y - 12, r.size.y - 12))
	draw_rect(pr, a.name_color.darkened(0.35))
	draw_rect(pr, Color(0, 0, 0), false, 2.0)
	UiKit.text(self, pr.position + Vector2(0, pr.size.y * 0.68), a.display_name.substr(0, 1).to_upper(), Color.WHITE, int(pr.size.y * 0.55), HORIZONTAL_ALIGNMENT_CENTER, pr.size.x)
	UiKit.text(self, Vector2(pr.position.x, pr.end.y + 0), str(a.level), UiKit.GOLD, 11)
	var x := pr.end.x + 8
	var bw := r.end.x - x - 8
	UiKit.text(self, Vector2(x, r.position.y + 18), a.display_name, a.name_color, 14)
	UiKit.text(self, Vector2(x, r.position.y + 18), sub, UiKit.DIM, 11, HORIZONTAL_ALIGNMENT_RIGHT, bw)
	UiKit.bar(self, Rect2(x, r.position.y + 24, bw, 14), a.hp / maxf(a.hp_max, 1.0), UiKit.HP if a.hostile else UiKit.HP_FRIEND,
			"%d / %d" % [roundi(a.hp), roundi(a.hp_max)])
	if a.en_max > 0:
		UiKit.bar(self, Rect2(x, r.position.y + 41, bw, 12), a.en / maxf(a.en_max, 1.0), UiKit.EN, "%d / %d" % [roundi(a.en), roundi(a.en_max)])


func _draw() -> void:
	if hud == null or hud.world == null or GameState.mode != "play":
		return
	var p: Player = hud.world.player
	_unit(Rect2(0, 0, W, H), p, "%s%s" % [p.cls, "  (demo)" if GameState.source == "offline" else ""])
	var t := p.target
	if t != null and is_instance_valid(t):
		var sub := t.title_line.substr(0, 26)
		_unit(Rect2(W + 12, 0, W, H), t, sub if not t.hostile else "Monster")
		if t is Monster:
			UiKit.text(self, Vector2(W + 12, H + 14), (t as Monster).data.get("error", "").substr(0, 60), Color(1, 0.6, 0.55), 11)
	party_rects.clear()
	var y := H + 30.0
	var shown := 0
	for n in hud.world.npcs.values():
		if not is_instance_valid(n) or not (n as NpcAgent).busy():
			continue
		if shown >= 5:
			break
		var r := Rect2(0, y, 190, 34)
		UiKit.frame(self, r, Color(0.07, 0.08, 0.11, 0.8))
		UiKit.text(self, Vector2(6, y + 14), "%d %s" % [n.level, n.display_name], n.name_color, 12)
		var st: String = (n as NpcAgent).npc_state
		UiKit.text(self, Vector2(6, y + 14), st, Color(1, 0.5, 0.4) if st == "blocked" else UiKit.DIM, 10, HORIZONTAL_ALIGNMENT_RIGHT, 178)
		UiKit.bar(self, Rect2(6, y + 18, 178, 6), n.hp / maxf(n.hp_max, 1.0), UiKit.HP_FRIEND)
		UiKit.bar(self, Rect2(6, y + 25, 178, 4), n.en / maxf(n.en_max, 1.0), UiKit.EN)
		party_rects.append([r, n])
		y += 38
		shown += 1
	if shown > 0:
		UiKit.text(self, Vector2(0, H + 24), "Party - your agents at work", UiKit.DIM, 11)
