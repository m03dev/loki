class_name ChatBox
extends PanelContainer
## Bottom left: the chat. Two channels - "Say" (the other players, through presence) and "LOKI"
## (POST /chat: LOKI answers here). Enter to type, Enter to send, Esc to stop typing.
## Commands: /l or /loki <text>, /s <text>, /wave /dance /sit /cheer /bow, /help, /hour <0-24>.
## Text is added as plain text (never parsed as markup): lines from other machines are data.

var hud: Node
var log_view: RichTextLabel
var input: LineEdit
var channel_btn: Button
var channel := "say"


func _ready() -> void:
	custom_minimum_size = Vector2(380, 210)
	var v := VBoxContainer.new()
	add_child(v)
	log_view = RichTextLabel.new()
	log_view.bbcode_enabled = false
	log_view.scroll_following = true
	log_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	log_view.add_theme_font_size_override("normal_font_size", 12)
	log_view.selection_enabled = true
	log_view.focus_mode = Control.FOCUS_NONE
	v.add_child(log_view)
	var h := HBoxContainer.new()
	v.add_child(h)
	channel_btn = UiKit.button("Say", _toggle_channel)
	channel_btn.custom_minimum_size = Vector2(56, 0)
	h.add_child(channel_btn)
	input = LineEdit.new()
	input.placeholder_text = "Enter to chat - /l talks to LOKI - /help"
	input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	input.max_length = 600
	input.text_submitted.connect(_submit)
	h.add_child(input)
	GameState.chat_line.connect(add_line)
	add_line("system", "", "Welcome to LOKI World. WASD walk, mouse drag look, Space jump, 1-9 skills, H for help.", Color(0.7, 0.85, 1.0))


func _toggle_channel() -> void:
	channel = "loki" if channel == "say" else "say"
	channel_btn.text = "LOKI" if channel == "loki" else "Say"


func focus_input(prefix: String = "") -> void:
	input.grab_focus()
	if prefix != "":
		input.text = prefix
		input.caret_column = prefix.length()


func add_line(ch: String, from: String, text_: String, color: Color) -> void:
	if log_view == null:
		return
	var tag: String = {"say": "", "loki": "[LOKI] ", "system": "", "emote": ""}.get(ch, "")
	log_view.push_color(color)
	log_view.add_text(tag + (from + ": " if from != "" else "") + text_)
	log_view.pop()
	log_view.newline()
	if log_view.get_paragraph_count() > 200:
		log_view.remove_paragraph(0)


func _submit(text_: String) -> void:
	var t := text_.strip_edges()
	input.text = ""
	input.release_focus()
	if t == "":
		return
	if t.begins_with("/"):
		var parts := t.split(" ", true, 1)
		var cmd := parts[0].to_lower().substr(1)
		var rest := parts[1] if parts.size() > 1 else ""
		match cmd:
			"l", "loki":
				if rest != "":
					LokiApi.chat_with_loki(rest)
				return
			"s", "say":
				if rest != "":
					LokiApi.say_to_players(rest)
				return
			"help":
				hud.windows.toggle("help")
				return
			"hour":
				hud.world.hour_override = clampf(rest.to_float(), 0.0, 24.0) if rest != "" else -1.0
				return
			_:
				if cmd in GameState.EMOTES:
					hud.world.player.do_emote(cmd)
					add_line("emote", "", "You %s." % cmd, Color(1.0, 0.75, 0.85))
					return
		add_line("system", "", "Unknown command: /%s (try /help)" % cmd, Color(1, 0.6, 0.5))
		return
	if channel == "loki":
		LokiApi.chat_with_loki(t)
	else:
		LokiApi.say_to_players(t)
