class_name QuestTracker
extends Control
## Right side under the minimap: the quests in flight (= LOKI's jobs) - active ones with what is
## happening, finished ones to bring to LOKI (gold), failed ones (a monster is out there).

var hud: Node


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)


func _process(_d: float) -> void:
	queue_redraw()


func _draw() -> void:
	if hud == null or GameState.mode != "play":
		return
	var x := size.x - 300.0
	var y := 230.0
	var shown := 0
	var quests: Array = GameState.state.get("quests", [])
	var order := {"complete": 0, "active": 1, "failed": 2}
	var list: Array = []
	for q in quests:
		if order.has(str(q.get("status", ""))):
			list.append(q)
	list.sort_custom(func(a, b): return order[str(a["status"])] < order[str(b["status"])])
	if list.is_empty():
		return
	UiKit.text(self, Vector2(x, y), "Quests  (L)", UiKit.GOLD, 14)
	y += 18
	for q in list:
		if shown >= 6:
			UiKit.text(self, Vector2(x, y), "... %d more in the quest log" % (list.size() - shown), UiKit.DIM, 11)
			break
		var st := str(q.get("status", ""))
		var col := UiKit.TEXT
		if st == "complete":
			col = UiKit.GOLD
		elif st == "failed":
			col = Color(1.0, 0.5, 0.42)
		UiKit.text(self, Vector2(x, y), str(q.get("title", "")).substr(0, 44), col, 12)
		UiKit.text(self, Vector2(x + 10, y + 14), "- " + str(q.get("objective", st)).substr(0, 48), UiKit.DIM, 11)
		y += 32
		shown += 1
