@tool
extends ConfirmationDialog

signal profile_saved
signal category_toggled(category: String, enabled: bool)
signal sign_in_requested
signal sign_out_requested
signal memory_save_requested(text: String)

const PROFILE_PATH: String = "user://loki_profile.cfg"

var _name_edit: LineEdit
var _profile_edit: TextEdit
var _status: Label
var _tabs: TabContainer
var _category_box: VBoxContainer
var _account_label: Label
var _sign_in_button: Button
var _sign_out_button: Button
var _memory_edit: TextEdit
var _connections_list: VBoxContainer
var _connections_status: Label
var _connect_key: LineEdit
var _connect_status: Label

signal connections_refresh_requested
signal connect_requested(provider: String, key: String)


func _ready() -> void:
	title = "Loki Settings"
	ok_button_text = "Close"
	initial_position = Window.WINDOW_INITIAL_POSITION_CENTER_MAIN_WINDOW_SCREEN
	_build()
	_load_profile()
	confirmed.connect(_save_profile)


func _build() -> void:
	# The dialog's own minimum stays small and its controls wrap. A tab whose content is
	# tall must SCROLL - it must never inflate the window past the editor's height, which
	# is what put the Close button off the bottom of the screen.
	min_size = Vector2i(440, 300)
	wrap_controls = true
	var root: VBoxContainer = VBoxContainer.new()
	root.custom_minimum_size = Vector2(440.0, 300.0)
	root.add_theme_constant_override("separation", 6)
	add_child(root)

	_tabs = TabContainer.new()
	_tabs.custom_minimum_size = Vector2(440.0, 260.0)
	_tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_tabs.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	root.add_child(_tabs)

	_build_agent_tab()
	_build_account_tab()
	_build_memory_tab()
	_build_profile_tab()
	_build_connections_tab()

	_status = Label.new()
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_status.modulate = Color(0.75, 0.78, 0.82)
	root.add_child(_status)


func _page(title: String) -> VBoxContainer:
	# Every tab is scrollable, so no tab can force the dialog taller than the window.
	var scroll: ScrollContainer = ScrollContainer.new()
	scroll.name = title
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_tabs.add_child(scroll)
	var page: VBoxContainer = VBoxContainer.new()
	page.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page.add_theme_constant_override("separation", 6)
	scroll.add_child(page)
	return page


func _hint(text: String) -> Label:
	var label: Label = Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.modulate = Color(0.72, 0.75, 0.8)
	return label


func _section(text: String) -> Label:
	var label: Label = Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", 12)
	return label


func _build_agent_tab() -> void:
	var page: VBoxContainer = _page("Agent")
	page.add_child(_hint("Turn tool categories on and off. A disabled category is hidden from the agent completely."))
	_category_box = VBoxContainer.new()
	_category_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page.add_child(_category_box)


func _build_account_tab() -> void:
	var page: VBoxContainer = _page("Account")
	page.add_child(_hint("Sign in with Google to use Loki Cloud - no API keys needed. Loki starts the cloud service for you."))
	_account_label = Label.new()
	_account_label.text = "Not signed in."
	page.add_child(_account_label)
	var actions: HBoxContainer = HBoxContainer.new()
	_sign_in_button = Button.new()
	_sign_in_button.text = "Sign in with Google"
	_sign_in_button.pressed.connect(func() -> void: sign_in_requested.emit())
	actions.add_child(_sign_in_button)
	_sign_out_button = Button.new()
	_sign_out_button.text = "Sign out"
	_sign_out_button.disabled = true
	_sign_out_button.pressed.connect(func() -> void: sign_out_requested.emit())
	actions.add_child(_sign_out_button)
	page.add_child(actions)


func _build_memory_tab() -> void:
	var page: VBoxContainer = _page("Memory")
	page.add_child(_hint("Lasting facts Loki remembers about you and this project - one bullet per line."))
	_memory_edit = TextEdit.new()
	_memory_edit.custom_minimum_size = Vector2(0.0, 150.0)
	_memory_edit.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_memory_edit.placeholder_text = "- prefers concise answers" + String.chr(10) + "- building a 2D platformer in Godot 4"
	_memory_edit.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	page.add_child(_memory_edit)
	var save: Button = Button.new()
	save.text = "Save memory"
	save.pressed.connect(func() -> void: memory_save_requested.emit(_memory_edit.text))
	page.add_child(save)


func _build_profile_tab() -> void:
	var page: VBoxContainer = _page("Profile")
	page.add_child(_section("Preferred name"))
	_name_edit = LineEdit.new()
	_name_edit.placeholder_text = "What should Loki call you?"
	page.add_child(_name_edit)
	page.add_child(_section("About you and your response preferences"))
	_profile_edit = TextEdit.new()
	_profile_edit.custom_minimum_size = Vector2(0.0, 110.0)
	_profile_edit.placeholder_text = "Optional context and preferences. Avoid sensitive information."
	_profile_edit.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	page.add_child(_profile_edit)
	var save: Button = Button.new()
	save.text = "Save profile"
	save.pressed.connect(_save_profile)
	page.add_child(save)


func _build_connections_tab() -> void:
	var page: VBoxContainer = _page("Connections")
	page.add_child(_hint("What Loki can reach right now. Secrets are never shown here, and signing in or paying for a provider stays yours to do."))
	var refresh: Button = Button.new()
	refresh.text = "Refresh status"
	refresh.pressed.connect(func() -> void: connections_refresh_requested.emit())
	page.add_child(refresh)
	var connect_row: HBoxContainer = HBoxContainer.new()
	var connect_label: Label = Label.new()
	connect_label.text = "OpenRouter key"
	connect_row.add_child(connect_label)
	_connect_key = LineEdit.new()
	_connect_key.secret = true
	_connect_key.placeholder_text = "sk-or-..."
	_connect_key.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	connect_row.add_child(_connect_key)
	var connect_button: Button = Button.new()
	connect_button.text = "Connect"
	connect_button.tooltip_text = "Check the key against the provider, then save it."
	connect_button.pressed.connect(func() -> void: connect_requested.emit("openrouter", _connect_key.text))
	connect_row.add_child(connect_button)
	page.add_child(connect_row)
	_connect_status = Label.new()
	_connect_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	page.add_child(_connect_status)
	_connections_status = Label.new()
	_connections_status.text = "Waiting for the local Loki bridge..."
	_connections_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	page.add_child(_connections_status)
	_connections_list = VBoxContainer.new()
	_connections_list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	page.add_child(_connections_list)


func set_connect_result(ok: bool, message: String) -> void:
	# Shows what happened to the key - never the key itself.
	if _connect_status == null:
		return
	_connect_status.text = message
	_connect_status.modulate = Color(0.55, 0.85, 0.6) if ok else Color(1.0, 0.5, 0.5)
	if ok and _connect_key != null:
		_connect_key.text = ""


func set_connections(payload: Dictionary) -> void:
	if _connections_list == null:
		return
	for child: Node in _connections_list.get_children():
		child.queue_free()
	_connections_status.text = "Status checked locally. Secrets and tokens are not returned."
	var accounts: Array = payload.get("providers", [])
	for value: Variant in accounts:
		if not value is Dictionary:
			continue
		var entry: Dictionary = value
		var row: HBoxContainer = HBoxContainer.new()
		var label: Label = Label.new()
		label.text = str(entry.get("label", entry.get("id", "Provider")))
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(label)
		var status: Label = Label.new()
		status.text = str(entry.get("status", "Unknown"))
		row.add_child(status)
		_connections_list.add_child(row)
	var tools: Array = payload.get("tools", [])
	for value: Variant in tools:
		if not value is Dictionary:
			continue
		var entry: Dictionary = value
		var row: HBoxContainer = HBoxContainer.new()
		var label: Label = Label.new()
		label.text = str(entry.get("label", entry.get("id", "Tool")))
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(label)
		var status: Label = Label.new()
		status.text = str(entry.get("status", "Not detected"))
		row.add_child(status)
		_connections_list.add_child(row)


func set_memory(text: String) -> void:
	if _memory_edit != null:
		_memory_edit.text = text


func open_memory_tab() -> void:
	if _tabs == null:
		return
	for i in _tabs.get_tab_count():
		if _tabs.get_tab_title(i) == "Memory":
			_tabs.current_tab = i
			return


func set_categories(state: Dictionary) -> void:
	for child in _category_box.get_children():
		child.queue_free()
	var categories: Dictionary = state.get("categories", {})
	var labels: Dictionary = state.get("labels", {})
	for name in categories.keys():
		var row: HBoxContainer = HBoxContainer.new()
		var label: Label = Label.new()
		label.text = str(labels.get(name, name))
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		row.add_child(label)
		var toggle: CheckButton = CheckButton.new()
		toggle.button_pressed = bool(categories[name])
		toggle.toggled.connect(func(pressed: bool) -> void: category_toggled.emit(str(name), pressed))
		row.add_child(toggle)
		_category_box.add_child(row)


func set_account(email: String, name: String, signed_in: bool) -> void:
	if _account_label == null:
		return
	if signed_in:
		_account_label.text = "Signed in as %s" % (email if not email.is_empty() else name)
	else:
		_account_label.text = "Not signed in."
	if _sign_in_button != null:
		_sign_in_button.disabled = signed_in
	if _sign_out_button != null:
		_sign_out_button.disabled = not signed_in


func set_status(text: String) -> void:
	if _status != null:
		_status.text = text


func _load_profile() -> void:
	var config: ConfigFile = ConfigFile.new()
	if config.load(PROFILE_PATH) == OK:
		_name_edit.text = str(config.get_value("profile", "name", ""))
		_profile_edit.text = str(config.get_value("profile", "notes", ""))


func _save_profile() -> void:
	var config: ConfigFile = ConfigFile.new()
	config.set_value("profile", "name", _name_edit.text.strip_edges())
	config.set_value("profile", "notes", _profile_edit.text.strip_edges())
	var result: Error = config.save(PROFILE_PATH)
	_status.text = "Saved locally; applying profile to Loki..." if result == OK else "Could not save profile: %s" % error_string(result)
	if result == OK:
		profile_saved.emit()
