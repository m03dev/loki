@tool
extends VBoxContainer
## The LOKI Studio dock: the chat with Studio's agent about THIS project, inside the editor.
##
## Sessions of this project, a new one, fork; the mode (Default / Plan / Ask) and the model;
## the thread (your messages, the agent's answers, thinking, tool calls, results, diffs,
## checkpoints); approvals and the agent's questions as buttons; its todo list; Undo turn,
## Diff, Stop; the input with /commands and @-mentions (autocomplete), Enter to send. It talks
## only to LOKI Studio's loopback API (api.gd) - every path it uses is in Studio's server.

const MODES := ["default", "plan", "ask"]
const MODE_LABELS := ["Default", "Plan", "Ask"]
const POLL_S := 1.0

var api: Node
var bridge: Node
var session_id := ""
var after := 0
var working := false
var turn := 0
var _ticks := 0
var _busy := false
var _sessions: Array = []
var _models: Array = []
var _commands: Array = []
var _rows := {}                  # approval / question id -> its row
var _suggest_kind := ""
var _suggest_word := ""

var status_label: Label
var session_pick: OptionButton
var new_btn: Button
var fork_btn: Button
var studio_btn: Button
var mode_pick: OptionButton
var model_pick: OptionButton
var ask_edits: CheckBox
var thread: RichTextLabel
var pending_box: VBoxContainer
var todos_label: RichTextLabel
var undo_btn: Button
var diff_btn: Button
var stop_btn: Button
var queue_label: Label
var input: TextEdit
var send_btn: Button
var sel_btn: Button
var suggest: PopupMenu
var diff_dialog: AcceptDialog
var diff_view: TextEdit
var image_dialog: AcceptDialog
var image_rect: TextureRect
var timer: Timer


func _init() -> void:
	name = "LOKI Studio"
	custom_minimum_size = Vector2(260, 320)
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	_build()


func _button(text: String, tip: String, cb: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.tooltip_text = tip
	b.pressed.connect(cb)
	return b


func _build() -> void:
	var top := HBoxContainer.new()
	status_label = Label.new()
	status_label.text = "connecting..."
	status_label.tooltip_text = "Whether LOKI Studio answers. Start it with Loki Studio.cmd (Windows) or LOKI Studio.app (Mac)."
	top.add_child(status_label)
	session_pick = OptionButton.new()
	session_pick.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	session_pick.tooltip_text = "This project's sessions with LOKI Studio"
	session_pick.item_selected.connect(_on_session_picked)
	top.add_child(session_pick)
	new_btn = _button("New", "Start a new session (type the task below and press Enter)", _on_new)
	top.add_child(new_btn)
	fork_btn = _button("Fork", "Copy this conversation into a new session, to try another way", _on_fork)
	top.add_child(fork_btn)
	studio_btn = _button("Studio", "Open the LOKI Studio window (diagrams, every session, LOKI itself)", _on_open_studio)
	top.add_child(studio_btn)
	add_child(top)

	var modes := HBoxContainer.new()
	mode_pick = OptionButton.new()
	for i in MODES.size():
		mode_pick.add_item(MODE_LABELS[i], i)
	mode_pick.tooltip_text = "Default: may change the project (every turn can be undone). Plan: reads and plans, changes nothing. Ask: answers questions."
	mode_pick.item_selected.connect(_on_mode)
	modes.add_child(mode_pick)
	model_pick = OptionButton.new()
	model_pick.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	model_pick.add_item("Auto (DeepSeek V4.1 on NVIDIA)")
	model_pick.set_item_metadata(0, "auto")
	model_pick.tooltip_text = "The model this session runs on"
	model_pick.item_selected.connect(_on_model)
	modes.add_child(model_pick)
	ask_edits = CheckBox.new()
	ask_edits.text = "Ask first"
	ask_edits.tooltip_text = "Ask before every change to files or scenes"
	ask_edits.toggled.connect(_on_ask_edits)
	modes.add_child(ask_edits)
	add_child(modes)

	thread = RichTextLabel.new()
	thread.bbcode_enabled = true
	thread.scroll_following = true
	thread.selection_enabled = true
	thread.size_flags_vertical = Control.SIZE_EXPAND_FILL
	thread.custom_minimum_size = Vector2(0, 160)
	thread.meta_clicked.connect(_on_meta)
	add_child(thread)

	pending_box = VBoxContainer.new()
	add_child(pending_box)

	todos_label = RichTextLabel.new()
	todos_label.bbcode_enabled = true
	todos_label.fit_content = true
	todos_label.visible = false
	add_child(todos_label)

	var acts := HBoxContainer.new()
	undo_btn = _button("Undo turn", "Undo the agent's last turn: files back as they were, editor changes undone", _on_undo)
	acts.add_child(undo_btn)
	diff_btn = _button("Diff", "Every change this session made", _on_diff)
	acts.add_child(diff_btn)
	stop_btn = _button("Stop", "Stop the agent now", _on_stop)
	acts.add_child(stop_btn)
	queue_label = Label.new()
	queue_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	acts.add_child(queue_label)
	add_child(acts)

	input = TextEdit.new()
	input.custom_minimum_size = Vector2(0, 72)
	input.placeholder_text = "Ask or tell LOKI... Enter sends, Shift+Enter is a new line. /commands, @files, @scene, @selection, @errors"
	input.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	input.gui_input.connect(_on_input_key)
	input.text_changed.connect(_on_text_changed)
	add_child(input)

	var bottom := HBoxContainer.new()
	sel_btn = _button("+ Selection", "Add the code selected in the script editor to your message", add_selection_to_chat)
	bottom.add_child(sel_btn)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bottom.add_child(spacer)
	send_btn = _button("Send", "Send (Enter)", _on_send)
	bottom.add_child(send_btn)
	add_child(bottom)

	suggest = PopupMenu.new()
	suggest.id_pressed.connect(_on_suggest)
	add_child(suggest)
	diff_dialog = AcceptDialog.new()
	diff_dialog.title = "LOKI Studio - changes"
	diff_view = TextEdit.new()
	diff_view.editable = false
	diff_view.custom_minimum_size = Vector2(760, 480)
	diff_dialog.add_child(diff_view)
	add_child(diff_dialog)
	image_dialog = AcceptDialog.new()
	image_dialog.title = "LOKI Studio - screenshot"
	image_rect = TextureRect.new()
	image_rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	image_rect.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	image_rect.custom_minimum_size = Vector2(800, 450)
	image_dialog.add_child(image_rect)
	add_child(image_dialog)
	timer = Timer.new()
	timer.wait_time = POLL_S
	timer.timeout.connect(_tick)
	add_child(timer)
	_say("[color=gray]LOKI Studio: tell it what to build, fix or check in this project. It works live in this editor; every turn can be undone.[/color]")


func start() -> void:
	timer.start()
	_tick()


func _esc(t: Variant) -> String:
	return str(t).replace("[", "[lb]")


func _say(bb: String) -> void:
	thread.append_text(bb + "\n")


func project_key(p: String) -> String:
	var k := p.replace("\\", "/").rstrip("/")
	return k.to_lower() if OS.get_name() == "Windows" else k


func my_project() -> String:
	return ProjectSettings.globalize_path("res://").rstrip("/")


# ------------------------------------------------------------------ polling
func _tick() -> void:
	if _busy or api == null:
		return
	_busy = true
	_ticks += 1
	if _ticks % 5 == 1:
		await _refresh_state()
	if session_id != "":
		await _poll_session()
	_busy = false


func _refresh_state() -> void:
	var st: Dictionary = await api.get_json("/api/state", 10.0)
	if not st.get("ok", false):
		status_label.text = "offline"
		status_label.tooltip_text = str(st.get("error", "LOKI Studio is not running"))
		return
	var linked: bool = bridge != null and str(bridge.editor_id) != ""
	status_label.text = "linked" if linked else "online"
	status_label.tooltip_text = "LOKI Studio answers; the editor link is %s." % ("up" if linked else "connecting")
	var mine := project_key(my_project())
	for e in st.get("editors", []):
		if bridge != null and str(e.get("editor", "")) == bridge.editor_id:
			mine = project_key(str(e.get("project", mine)))
	_sessions = []
	for s in st.get("sessions", []):
		if str(s.get("kind", "")) == "godot" and project_key(str(s.get("root", ""))) == mine:
			_sessions.append(s)
	session_pick.clear()
	session_pick.add_item("(new session)")
	session_pick.set_item_metadata(0, "")
	var pick := 0
	for s in _sessions:
		session_pick.add_item("%s [%s]" % [str(s.get("title", s.get("id"))).substr(0, 48), s.get("status", "")])
		session_pick.set_item_metadata(session_pick.item_count - 1, str(s.get("id")))
		if str(s.get("id")) == session_id:
			pick = session_pick.item_count - 1
	session_pick.select(pick)
	if _models.is_empty():
		var m: Dictionary = await api.get_json("/api/models", 10.0)
		if m.get("ok", false):
			_models = m.get("models", [])
			model_pick.clear()
			for row in _models:
				model_pick.add_item(str(row.get("name", row.get("id"))).substr(0, 60))
				model_pick.set_item_metadata(model_pick.item_count - 1, str(row.get("id")))
	if _commands.is_empty():
		var c: Dictionary = await api.get_json("/api/commands" + ("?id=" + session_id if session_id != "" else ""), 10.0)
		if c.get("ok", false):
			_commands = c.get("commands", [])


func _poll_session() -> void:
	var data: Dictionary = await api.get_json("/api/session?id=%s&after=%d" % [session_id, after], 15.0)
	if not data.get("ok", false):
		return
	for e in data.get("events", []):
		_render(e)
		after = maxi(after, int(e.get("id", 0)))
	var s: Dictionary = data.get("session", {})
	working = bool(data.get("working", false))
	turn = int(s.get("turn", 0))
	stop_btn.disabled = not working
	undo_btn.disabled = working or turn < 1
	var q := int(s.get("queued", 0))
	queue_label.text = ("%s%s" % ["working..." if working else str(s.get("status", "")), (" - %d queued" % q) if q > 0 else ""])
	var mode := str(s.get("mode", "default"))
	if MODES.has(mode) and mode_pick.selected != MODES.find(mode):
		mode_pick.select(MODES.find(mode))
	ask_edits.set_pressed_no_signal(bool(s.get("approve_edits", false)))
	_show_todos(s.get("todos", []))


func _show_todos(todos: Array) -> void:
	todos_label.visible = not todos.is_empty()
	var lines: Array = ["[b]Todos[/b]"]
	for t in todos:
		var mark := "[color=green]done[/color]" if t.get("status") == "done" else ("[color=yellow]doing[/color]" if t.get("status") == "doing" else "todo")
		lines.append("%s  %s" % [mark, _esc(t.get("text", ""))])
	todos_label.text = "\n".join(lines)


# ------------------------------------------------------------------ the thread
func _render(e: Dictionary) -> void:
	var kind := str(e.get("type", ""))
	var text := str(e.get("text", ""))
	match kind:
		"user":
			_say("\n[b][color=#7fc8ff]You:[/color][/b] " + _esc(text) + ((" [color=gray](%s)[/color]" % ", ".join(e.get("attachments", []))) if e.has("attachments") else ""))
		"assistant":
			_say("[b]LOKI:[/b] " + _esc(_mermaid_note(text)))
		"thinking":
			_say("[color=gray][i]thinking: %s[/i][/color]" % _esc(text.substr(0, 300)))
		"tool":
			_say("[color=#e0c070]> %s[/color]" % _esc(text.substr(0, 300)))
		"result":
			var lines := text.split("\n")
			_say("[color=gray]%s%s[/color]" % [_esc("\n".join(lines.slice(0, 4))), " ..." if lines.size() > 4 else ""])
			for p in e.get("images", []):
				thread.push_meta("image:" + str(p))
				thread.append_text("[u][color=#7fc8ff]see the screenshot[/color][/u]")
				thread.pop()
				thread.append_text("\n")
		"diff":
			var out: Array = []
			for line in text.split("\n").slice(0, 40):
				if line.begins_with("+") and not line.begins_with("+++"):
					out.append("[color=#80d080]%s[/color]" % _esc(line))
				elif line.begins_with("-") and not line.begins_with("---"):
					out.append("[color=#e08080]%s[/color]" % _esc(line))
				else:
					out.append("[color=gray]%s[/color]" % _esc(line))
			_say("[code]%s[/code]" % "\n".join(out))
		"approval":
			_approval_row(e)
		"approved", "denied":
			_close_row(str(e.get("approval", "")), kind)
		"question":
			_question_row(e)
		"answered":
			_close_row(str(e.get("question_id", "")), "answered: " + text)
		"error":
			_say("[color=#ff7070]%s[/color]" % _esc(text + ("\n" + str(e.get("how")) if str(e.get("how", "")) != "" else "")))
		"command":
			_say("[color=#a0a0ff]%s[/color]" % _esc(_mermaid_note(text)))
		"checkpoint":
			_say("[color=gray][i]%s[/i][/color]" % _esc(text))
		"undo", "check", "ship", "mode":
			_say("[color=#a0d0a0]%s[/color]" % _esc(text))
		"todos":
			pass
		_:
			_say("[color=gray]%s[/color]" % _esc(text.substr(0, 400)))


func _mermaid_note(text: String) -> String:
	if text.find("```mermaid") >= 0:
		return text + "\n(diagram: press Studio to see it drawn)"
	return text


func _approval_row(e: Dictionary) -> void:
	var id := str(e.get("approval", ""))
	var row := HBoxContainer.new()
	var label := Label.new()
	label.text = str(e.get("text", ""))
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(label)
	row.add_child(_button("Approve", "Let the agent do this", func(): _approve(id, true)))
	row.add_child(_button("Deny", "Say no; the agent goes on without it", func(): _approve(id, false)))
	pending_box.add_child(row)
	_rows[id] = row


func _question_row(e: Dictionary) -> void:
	var id := str(e.get("question_id", ""))
	var box := VBoxContainer.new()
	var label := Label.new()
	label.text = "LOKI asks: " + str(e.get("text", ""))
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(label)
	var opts := HBoxContainer.new()
	for o in e.get("options", []):
		var choice := str(o)
		opts.add_child(_button(choice.substr(0, 40), choice, func(): _answer(id, choice)))
	var free := LineEdit.new()
	free.placeholder_text = "or type an answer"
	free.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	free.text_submitted.connect(func(t): _answer(id, t))
	opts.add_child(free)
	box.add_child(opts)
	pending_box.add_child(box)
	_rows[id] = box


func _close_row(id: String, note: String) -> void:
	if _rows.has(id):
		_rows[id].queue_free()
		_rows.erase(id)
	_say("[color=gray](%s)[/color]" % _esc(note))


func _approve(id: String, yes: bool) -> void:
	await api.post_json("/api/session/approve", {"id": session_id, "approval": id, "yes": yes})


func _answer(id: String, text: String) -> void:
	await api.post_json("/api/session/answer", {"id": session_id, "question": id, "answer": text})


func _on_meta(meta: Variant) -> void:
	var m := str(meta)
	if m.begins_with("image:"):
		var img := Image.load_from_file(m.substr(6))
		if img != null and not img.is_empty():
			image_rect.texture = ImageTexture.create_from_image(img)
			image_dialog.popup_centered()


# ------------------------------------------------------------------ actions
func _select(id: String) -> void:
	session_id = id
	after = 0
	_rows.clear()
	for c in pending_box.get_children():
		c.queue_free()
	thread.clear()
	_commands = []


func _on_session_picked(index: int) -> void:
	_select(str(session_pick.get_item_metadata(index)))


func _on_new() -> void:
	_select("")
	session_pick.select(0)
	_say("[color=gray]New session: type the task and press Enter.[/color]")
	input.grab_focus()


func _on_fork() -> void:
	if session_id == "":
		return
	var r: Dictionary = await api.post_json("/api/session/fork", {"id": session_id})
	if r.get("ok", false):
		_select(str(r["session"]["id"]))
		_ticks = 0


func _on_open_studio() -> void:
	var url: String = api.studio_url()
	if url != "":
		OS.shell_open(url)


func _on_mode(index: int) -> void:
	if session_id != "":
		await api.post_json("/api/session/mode", {"id": session_id, "mode": MODES[index]})


func _model_id() -> String:
	var m: Variant = model_pick.get_item_metadata(model_pick.selected) if model_pick.selected >= 0 else "auto"
	return str(m) if m != null else "auto"


func _on_model(_index: int) -> void:
	if session_id != "":
		await api.post_json("/api/session/model", {"id": session_id, "model": _model_id()})


func _on_ask_edits(on: bool) -> void:
	if session_id != "":
		await api.post_json("/api/session/approve_edits", {"id": session_id, "on": on})


func _on_undo() -> void:
	if session_id == "" or turn < 1:
		return
	var r: Dictionary = await api.post_json("/api/session/undo", {"id": session_id, "turn": turn})
	if not r.get("ok", false):
		_say("[color=#ff7070]%s[/color]" % _esc(r.get("error", r.get("text", "could not undo"))))


func _on_diff() -> void:
	if session_id == "":
		return
	var r: Dictionary = await api.get_json("/api/session/diff?id=" + session_id, 20.0)
	diff_view.text = str(r.get("diff", r.get("error", ""))) if r.get("ok", false) or r.has("error") else ""
	if diff_view.text == "":
		diff_view.text = "(no changes)"
	diff_dialog.popup_centered()


func _on_stop() -> void:
	if session_id != "":
		await api.post_json("/api/session/stop", {"id": session_id})


func _on_send() -> void:
	var text := input.text.strip_edges()
	if text == "":
		return
	input.text = ""
	suggest.hide()
	var r: Dictionary
	if session_id == "":
		r = await api.post_json("/api/session/new", {"text": text, "project": my_project(), "mode": MODES[maxi(0, mode_pick.selected)],
			"model": _model_id(), "approve_edits": ask_edits.button_pressed}, 30.0)
		if r.get("ok", false):
			_select(str(r["session"]["id"]))
			_ticks = 0
	else:
		r = await api.post_json("/api/session/send", {"id": session_id, "text": text}, 30.0)
	if not r.get("ok", false):
		_say("[color=#ff7070]%s[/color]" % _esc(r.get("error", "LOKI Studio did not take it")))
		input.text = text


func _on_input_key(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if (event.keycode == KEY_ENTER or event.keycode == KEY_KP_ENTER) and not event.shift_pressed:
			input.accept_event()
			if suggest.visible and suggest.item_count > 0:
				_on_suggest(0)
			else:
				_on_send()
		elif event.keycode == KEY_ESCAPE:
			suggest.hide()


func add_text_to_chat(t: String) -> void:
	input.text = (input.text + ("" if input.text == "" or input.text.ends_with(" ") else " ") + t)
	input.set_caret_column(input.get_line(input.get_line_count() - 1).length())
	input.set_caret_line(input.get_line_count() - 1)
	input.grab_focus()


func add_selection_to_chat() -> void:
	if bridge == null:
		return
	var sel: Dictionary = bridge._selected_code()
	if sel.is_empty() or str(sel.get("text", "")) == "":
		_say("[color=gray](select code in the script editor first)[/color]")
		return
	add_text_to_chat("\n%s lines %d-%d:\n```gdscript\n%s\n```\n" % [sel.get("file", ""), sel.get("from_line", 0), sel.get("to_line", 0), sel.get("text", "")])


# ------------------------------------------------------------------ /commands and @mentions
func _current_word() -> String:
	var line := input.get_line(input.get_caret_line()).substr(0, input.get_caret_column())
	var parts := line.split(" ")
	return parts[parts.size() - 1] if parts.size() > 0 else ""


func _on_text_changed() -> void:
	var word := _current_word()
	if input.text.begins_with("/") and input.text.find(" ") < 0 and input.get_line_count() == 1:
		_show_suggest("command", word, _command_items(word.substr(1)))
	elif word.begins_with("@") and word.length() >= 2:
		var q := word.substr(1)
		var url := "/api/mentions?q=%s&%s" % [q.uri_encode(), ("id=" + session_id) if session_id != "" else ("project=" + my_project().uri_encode())]
		var r: Dictionary = await api.get_json(url, 5.0)
		if _current_word() == word:
			_show_suggest("mention", word, r.get("items", []))
	else:
		suggest.hide()


func _command_items(prefix: String) -> Array:
	var out: Array = []
	for c in _commands:
		if str(c.get("name", "")).begins_with(prefix):
			out.append("/%s - %s" % [c["name"], str(c.get("description", "")).substr(0, 70)])
	return out.slice(0, 14)


func _show_suggest(kind: String, word: String, items: Array) -> void:
	suggest.clear()
	if items.is_empty():
		suggest.hide()
		return
	_suggest_kind = kind
	_suggest_word = word
	for i in items.size():
		suggest.add_item(str(items[i]), i)
	var pos := input.get_screen_position() + input.get_caret_draw_pos() + Vector2(0, 8)
	suggest.popup(Rect2i(Vector2i(pos), Vector2i(360, 0)))
	input.grab_focus()


func _on_suggest(id: int) -> void:
	var item := suggest.get_item_text(suggest.get_item_index(id))
	suggest.hide()
	if _suggest_kind == "command":
		input.text = item.split(" - ")[0] + " "
	else:
		var t := input.text
		var at := t.rfind(_suggest_word)
		if at >= 0:
			input.text = t.substr(0, at) + "@" + item + " " + t.substr(at + _suggest_word.length())
	input.set_caret_line(input.get_line_count() - 1)
	input.set_caret_column(input.get_line(input.get_line_count() - 1).length())
	input.grab_focus()
