class_name HudWindows
extends Control
## The MMO windows: quest log (L), bags (B), character sheet (C), loot, talking to an agent,
## "what should LOKI make?" for the LOKI-action skills, help (H) and pairing with LOKI.
## Each is a small draggable panel built fresh when it opens, from GameState.

var hud: Node
var open: Dictionary = {}      # name -> PanelContainer
var _drag_win: Control = null
var _drag_off := Vector2.ZERO


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	GameState.loot_got.connect(show_loot)
	GameState.need_pair.connect(func(reason): show_pair(reason))
	GameState.state_changed.connect(_refresh_open)


func is_open(name_: String) -> bool:
	return open.has(name_) and is_instance_valid(open[name_])


func any_open() -> bool:
	for k in open.keys():
		if is_instance_valid(open[k]):
			return true
	return false


func close(name_: String) -> void:
	if is_open(name_):
		open[name_].queue_free()
	open.erase(name_)


func close_all() -> bool:
	var had := any_open()
	for k in open.keys():
		close(k)
	return had


func toggle(name_: String) -> void:
	if is_open(name_):
		close(name_)
		return
	match name_:
		"quests":
			show_quests()
		"bags":
			show_bags()
		"character":
			show_character()
		"help":
			show_help()


func _refresh_open() -> void:
	for k in ["quests", "bags", "character"]:
		if is_open(k) and not open[k].get_meta("busy", false):
			var pos: Vector2 = open[k].position
			close(k)
			toggle(k)
			if is_open(k):
				open[k].position = pos


## A window: title bar (drag it), close button, a VBox body to fill.
func _window(name_: String, title: String, w: float, at: Vector2 = Vector2(-1, -1)) -> VBoxContainer:
	close(name_)
	var p := PanelContainer.new()
	p.mouse_filter = Control.MOUSE_FILTER_STOP
	p.custom_minimum_size = Vector2(w, 0)
	add_child(p)
	var v := VBoxContainer.new()
	v.add_theme_constant_override("separation", 6)
	p.add_child(v)
	var bar := HBoxContainer.new()
	v.add_child(bar)
	var t := UiKit.label(title, 15, UiKit.GOLD)
	t.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	t.mouse_filter = Control.MOUSE_FILTER_STOP
	t.gui_input.connect(func(ev): _drag(ev, p))
	bar.add_child(t)
	bar.add_child(UiKit.button("x", func(): close(name_)))
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 4)
	v.add_child(body)
	open[name_] = p
	p.position = at if at.x >= 0 else Vector2((size.x - w) * 0.5, size.y * 0.16)
	return body


func _drag(ev: InputEvent, win: Control) -> void:
	if ev is InputEventMouseButton and ev.button_index == MOUSE_BUTTON_LEFT:
		_drag_win = win if ev.pressed else null
		_drag_off = win.get_global_mouse_position() - win.position
	elif ev is InputEventMouseMotion and _drag_win == win:
		win.position = win.get_global_mouse_position() - _drag_off


func _scroll(body: VBoxContainer, height: float) -> VBoxContainer:
	var sc := ScrollContainer.new()
	sc.custom_minimum_size = Vector2(0, height)
	sc.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	body.add_child(sc)
	var inner := VBoxContainer.new()
	inner.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	sc.add_child(inner)
	return inner


func _near_loki() -> bool:
	var loki = hud.world.npcs.get("loki")
	return loki != null and is_instance_valid(loki) and loki.global_position.distance_to(hud.world.player.global_position) < 8.0


# ----------------------------------------------------------------- quest log

func show_quests() -> void:
	var body := _window("quests", "Quest log - LOKI's jobs", 520, Vector2(size.x - 560, 120))
	var quests: Array = GameState.state.get("quests", [])
	var done: Array = []
	for q in quests:
		if str(q.get("status", "")) == "complete":
			done.append(str(q.get("id", "")))
	if not done.is_empty():
		var h := HBoxContainer.new()
		body.add_child(h)
		h.add_child(UiKit.label("%d finished - bring them to LOKI in the hall." % done.size(), 13, UiKit.GOLD))
		var b := UiKit.button("Turn in all", func(): LokiApi.turn_in(done))
		b.disabled = not _near_loki()
		b.tooltip_text = "Stand next to LOKI (the horned one in the hall) to turn in."
		h.add_child(b)
	var inner := _scroll(body, 360)
	if quests.is_empty():
		inner.add_child(UiKit.label("No quests yet. Use 4-8 on the hotbar, or talk to LOKI, to give LOKI work.", 13, UiKit.DIM))
	for q in quests:
		var st := str(q.get("status", ""))
		var col: Color = {"complete": UiKit.GOLD, "failed": Color(1, 0.5, 0.42), "active": UiKit.TEXT}.get(st, UiKit.DIM)
		var row := VBoxContainer.new()
		inner.add_child(row)
		row.add_child(UiKit.label("%s   [%s]" % [str(q.get("title", "")), st], 13, col))
		row.add_child(UiKit.label("   %s  -  %s, %d XP" % [str(q.get("objective", "")), str(q.get("kind", "task")), int(q.get("xp", 100))], 11, UiKit.DIM))


# ----------------------------------------------------------------- bags

func show_bags() -> void:
	var body := _window("bags", "Bags - what LOKI made", 470, Vector2(size.x - 510, size.y - 520))
	var items: Array = GameState.loot_items()
	var grid := GridContainer.new()
	grid.columns = 6
	var inner := _scroll(body, 330)
	inner.add_child(grid)
	if items.is_empty():
		inner.add_child(UiKit.label("Empty. Pictures, videos and games LOKI makes land here.", 13, UiKit.DIM))
	var seen: Array = []
	for it in items.slice(0, 48):
		var slot := Button.new()
		slot.custom_minimum_size = Vector2(68, 68)
		slot.focus_mode = Control.FOCUS_NONE
		slot.tooltip_text = "%s\n%s %s" % [str(it.get("title", "")), str(it.get("rarity", "")), str(it.get("kind", ""))]
		var rc: Color = GameState.RARITY_COLORS.get(str(it.get("rarity", "common")), Color.WHITE)
		var sb := UiKit.panel_style()
		sb.border_color = rc
		sb.bg_color = Color(0.1, 0.11, 0.15)
		slot.add_theme_stylebox_override("normal", sb)
		slot.expand_icon = true
		slot.icon_alignment = HORIZONTAL_ALIGNMENT_CENTER
		if str(it.get("show", "")) == "image":
			_load_icon(slot, it)
		else:
			slot.text = str(it.get("kind", "?")).substr(0, 5)
		if it.get("new", false):
			slot.text = "new" if slot.text == "" else slot.text
		slot.pressed.connect(func(): show_item(it))
		grid.add_child(slot)
		if it.get("new", false):
			seen.append(str(it.get("id", "")))
	var scrolls: Array = GameState.state.get("loot", {}).get("scrolls", [])
	if not scrolls.is_empty():
		body.add_child(UiKit.label("Lesson scrolls (what went wrong, from beaten monsters):", 12, UiKit.DIM))
		for s in scrolls.slice(0, 6):
			body.add_child(UiKit.label("%s - %s" % [str(s.get("title", "")), str(s.get("text", "")).substr(0, 90)], 11, Color(0.5, 0.95, 0.55)))
	if not seen.is_empty():
		var local_seen: Dictionary = GameState.local.get("seen", {})
		for id in seen:
			local_seen[id] = true
		GameState.local["seen"] = local_seen
		GameState.save_local()
		LokiApi.note({"seen": seen})


func _load_icon(slot: Button, it: Dictionary) -> void:
	var tex: Texture2D = await LokiApi.creation_texture(it)
	if is_instance_valid(slot):
		slot.icon = tex


func show_item(it: Dictionary) -> void:
	var body := _window("item", str(it.get("title", "")), 420)
	var rc: Color = GameState.RARITY_COLORS.get(str(it.get("rarity", "common")), Color.WHITE)
	body.add_child(UiKit.label("%s %s" % [str(it.get("rarity", "")).capitalize(), str(it.get("kind", ""))], 13, rc))
	if str(it.get("show", "")) == "image":
		var tr := TextureRect.new()
		tr.custom_minimum_size = Vector2(400, 300)
		tr.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		tr.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
		body.add_child(tr)
		var tex: Texture2D = await LokiApi.creation_texture(it)
		if is_instance_valid(tr):
			tr.texture = tex
	else:
		body.add_child(UiKit.label("Open it in LOKI: Settings > Creations.", 12, UiKit.DIM))


# ----------------------------------------------------------------- character

func show_character() -> void:
	var body := _window("character", "Character", 380, Vector2(40, 140))
	var p := GameState.profile()
	body.add_child(UiKit.label("%s - level %d %s" % [str(p.get("name", "You")), int(p.get("level", 1)), str(p.get("cls", ""))], 16, UiKit.GOLD))
	body.add_child(UiKit.label("XP %d (%d / %d to the next level)" % [int(p.get("xp", 0)), int(p.get("xp_into", 0)), int(p.get("xp_need", 1))], 12))
	body.add_child(UiKit.label("Health %d   Energy %d   Power %.2f" % [int(p.get("hp_max", 0)), int(p.get("en_max", 0)), float(p.get("power", 1))], 12))
	var st: Dictionary = p.get("stats", {})
	body.add_child(UiKit.label("Quests %d   Kills %d   Deaths %d   Casts %d   Loot %d   Retries %d" % [int(st.get("quests", 0)),
			int(st.get("kills", 0)), int(st.get("deaths", 0)), int(st.get("casts", 0)), int(st.get("loot", 0)), int(st.get("retries", 0))], 12, UiKit.DIM))
	body.add_child(UiKit.label("Name", 12, UiKit.DIM))
	var name_edit := LineEdit.new()
	name_edit.text = str(p.get("name", "You"))
	name_edit.max_length = 24
	body.add_child(name_edit)
	body.add_child(UiKit.label("Class", 12, UiKit.DIM))
	var row := HBoxContainer.new()
	body.add_child(row)
	for cls in GameState.CLASSES.keys():
		var b := UiKit.button(cls, func(): LokiApi.set_profile(name_edit.text, cls); close("character"))
		b.tooltip_text = str(GameState.CLASSES[cls]["about"])
		row.add_child(b)
	body.add_child(UiKit.button("Save name", func(): LokiApi.set_profile(name_edit.text, str(p.get("cls", "Mage")))))
	open["character"].set_meta("busy", true)
	body.add_child(UiKit.label("Source: %s" % {"engine": "LOKI's MMO API", "derived": "LOKI's jobs and creations", "offline": "demo world (LOKI not running)"}.get(GameState.source, GameState.source), 11, UiKit.DIM))


# ----------------------------------------------------------------- loot

func show_loot(items: Array, title: String, offer_retry: Dictionary) -> void:
	var body := _window("loot", "Loot - " + title, 380, Vector2(size.x * 0.5 + 60, size.y * 0.35))
	if items.is_empty():
		body.add_child(UiKit.label("Nothing dropped.", 12, UiKit.DIM))
	for it in items:
		var rc: Color = GameState.RARITY_COLORS.get(str(it.get("rarity", "common")), Color.WHITE)
		body.add_child(UiKit.label(str(it.get("title", "")), 13, rc))
		if str(it.get("text", "")) != "":
			body.add_child(UiKit.label(str(it.get("text", "")).substr(0, 240), 11, UiKit.DIM))
	if not offer_retry.is_empty():
		body.add_child(UiKit.label("This monster was a failed job. Try it again on a stronger model?", 12, UiKit.GOLD))
		var h := HBoxContainer.new()
		body.add_child(h)
		var pick := OptionButton.new()
		pick.add_item("LOKI chooses")
		h.add_child(pick)
		_fill_models(pick)
		h.add_child(UiKit.button("Retry with a stronger model", func():
			var model := "" if pick.selected <= 0 else pick.get_item_text(pick.selected)
			LokiApi.retry_failed(offer_retry, model)
			close("loot")))
	body.add_child(UiKit.button("Take all", func(): close("loot")))


func _fill_models(pick: OptionButton) -> void:
	var names: Array = await LokiApi.models()
	if is_instance_valid(pick):
		for n in names:
			pick.add_item(str(n))


# ----------------------------------------------------------------- talk / quests from LOKI

func show_talk(a: Actor) -> void:
	var body := _window("talk", a.display_name, 440)
	if a is RemotePlayer:
		body.add_child(UiKit.label("%s, playing on %s." % [a.display_name, (a as RemotePlayer).machine], 13))
		body.add_child(UiKit.button("Wave", func(): hud.world.player.do_emote("wave"); close("talk")))
		return
	var n := a as NpcAgent
	var d: Dictionary = n.data
	body.add_child(UiKit.label("%s - level %d" % [n.title_line, n.level], 12, n.name_color))
	var line := str(d.get("last_message", ""))
	if line == "":
		line = "Working on: " + str(d.get("task", "")) if n.busy() else "Nothing on my desk right now."
	body.add_child(UiKit.label("\"%s\"" % line.substr(0, 300), 13))
	if not n.quest_giver:
		return
	var done: Array = []
	for q in GameState.state.get("quests", []):
		if str(q.get("status", "")) == "complete":
			done.append(str(q.get("id", "")))
	if not done.is_empty():
		body.add_child(UiKit.button("Turn in %d finished quest%s" % [done.size(), "" if done.size() == 1 else "s"], func(): LokiApi.turn_in(done); close("talk")))
	body.add_child(UiKit.label("Give LOKI a quest (it starts a real job):", 12, UiKit.GOLD))
	var row := HBoxContainer.new()
	body.add_child(row)
	for s in GameState.skills():
		if str(s.get("kind", "")) == "loki":
			row.add_child(UiKit.button(str(s.get("name", "")), func(): close("talk"); show_prompt(s)))
	body.add_child(UiKit.button("Chat with LOKI", func(): close("talk"); hud.chat.focus_input("/l ")))


func show_prompt(skill: Dictionary) -> void:
	var body := _window("prompt", str(skill.get("name", "")), 420)
	body.add_child(UiKit.label("What should LOKI do? (%s)" % str(skill.get("ask", "")), 13))
	var e := LineEdit.new()
	e.placeholder_text = str(skill.get("ask", ""))
	e.max_length = 2000
	body.add_child(e)
	var go := func(_t = ""):
		var text := e.text.strip_edges()
		if text != "":
			hud.world.player.cast_loki(skill, text)
		close("prompt")
	e.text_submitted.connect(go)
	body.add_child(UiKit.button("Cast", func(): go.call()))
	body.add_child(UiKit.label("It becomes a real background job; finish it to complete the quest.", 11, UiKit.DIM))
	e.call_deferred("grab_focus")


# ----------------------------------------------------------------- help / pair

func show_help() -> void:
	var body := _window("help", "LOKI World - controls", 470)
	for line in [
		"W A S D - walk (relative to the camera)    Space - jump    R - autorun",
		"Mouse drag - look around (right drag also turns you)    Wheel - zoom    Q / E - turn",
		"Click - target    Double/right click or F - talk / attack    Tab - nearest enemy    Esc - clear / close",
		"1 Strike  2 Bolt  3 Mend  4 Picture  5 Research  6 Build  7 Video  8 Game  9 Hearth",
		"(4-8 are LOKI actions: each starts a real job = a quest)",
		"Enter - chat    /l <text> talk to LOKI    /wave /dance /sit /cheer /bow",
		"L quests   B bags   C character   M map (click an island to fly)   H this help",
		"Failed jobs are monsters: beat one for XP and a lesson, then retry it on a stronger model.",
	]:
		body.add_child(UiKit.label(line, 12))


func show_pair(reason: String) -> void:
	var body := _window("pair", "Join LOKI", 460)
	body.add_child(UiKit.label(reason, 13))
	body.add_child(UiKit.label("Paste LOKI's engine token (harness_data/app/engine.token in the LOKI folder) or the path to that file:", 12, UiKit.DIM))
	var e := LineEdit.new()
	e.secret = true
	body.add_child(e)
	var go := func(_t = ""):
		LokiApi.pair(e.text)
		close("pair")
	e.text_submitted.connect(go)
	body.add_child(UiKit.button("Pair", func(): go.call()))
	body.add_child(UiKit.button("Play offline (demo)", func(): close("pair")))
