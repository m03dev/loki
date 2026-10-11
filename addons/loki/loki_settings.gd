@tool
extends ConfirmationDialog

signal profile_saved
signal category_toggled(category: String, enabled: bool)
signal sign_in_requested
signal sign_out_requested

const PROFILE_PATH: String = "user://loki_profile.cfg"

var _name_edit: LineEdit
var _profile_edit: TextEdit
var _status: Label
var _tabs: TabContainer
var _category_box: VBoxContainer
var _account_label: Label
var _sign_in_button: Button
var _sign_out_button: Button


func _ready() -> void:
	title = "Loki Settings"
	ok_button_text = "Close"
	initial_position = Window.WINDOW_INITIAL_POSITION_CENTER_MAIN_WINDOW_SCREEN
	_build()
	_load_profile()
	confirmed.connect(_save_profile)


func _build() -> void:
	var root: VBoxContainer = VBoxContainer.new()
	root.custom_minimum_size = Vector2(460.0, 360.0)
	add_child(root)

	var heading: Label = Label.new()
	heading.text = "Settings"
	heading.add_theme_font_size_override("font_size", 18)
	root.add_child(heading)

	_tabs = TabContainer.new()
	_tabs.custom_minimum_size = Vector2(440.0, 300.0)
	_tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.add_child(_tabs)

	_build_agent_tab()
	_build_account_tab()
	_build_profile_tab()

	_status = Label.new()
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	root.add_child(_status)


func _build_agent_tab() -> void:
	var page: VBoxContainer = VBoxContainer.new()
	page.name = "Agent"
	_tabs.add_child(page)

	var hint: Label = Label.new()
	hint.text = "Turn tool categories on or off. Disabled categories are hidden from the agent."
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	page.add_child(hint)

	var scroll: ScrollContainer = ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	page.add_child(scroll)

	_category_box = VBoxContainer.new()
	_category_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(_category_box)


func _build_account_tab() -> void:
	var page: VBoxContainer = VBoxContainer.new()
	page.name = "Account"
	_tabs.add_child(page)

	var hint: Label = Label.new()
	hint.text = "Sign in with Google to run Loki on the cloud - no API keys needed."
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	page.add_child(hint)

	_account_label = Label.new()
	_account_label.text = "Not signed in."
	page.add_child(_account_label)

	_sign_in_button = Button.new()
	_sign_in_button.text = "Sign in with Google"
	_sign_in_button.pressed.connect(func() -> void: sign_in_requested.emit())
	page.add_child(_sign_in_button)

	_sign_out_button = Button.new()
	_sign_out_button.text = "Sign out"
	_sign_out_button.disabled = true
	_sign_out_button.pressed.connect(func() -> void: sign_out_requested.emit())
	page.add_child(_sign_out_button)


func _build_profile_tab() -> void:
	var page: VBoxContainer = VBoxContainer.new()
	page.name = "Profile"
	_tabs.add_child(page)

	var name_label: Label = Label.new()
	name_label.text = "Preferred name"
	page.add_child(name_label)

	_name_edit = LineEdit.new()
	_name_edit.placeholder_text = "What should Loki call you?"
	page.add_child(_name_edit)

	var notes_label: Label = Label.new()
	notes_label.text = "About you and response preferences"
	page.add_child(notes_label)

	_profile_edit = TextEdit.new()
	_profile_edit.custom_minimum_size = Vector2(420.0, 150.0)
	_profile_edit.placeholder_text = "Optional context and preferences. Avoid sensitive information."
	page.add_child(_profile_edit)

	var save: Button = Button.new()
	save.text = "Save profile"
	save.pressed.connect(_save_profile)
	page.add_child(save)


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
