@tool
extends VBoxContainer

## Loki dock - the chat panel: conversation tabs, saved history, modes and memory.

const BRIDGE_URL: String = "http://127.0.0.1:8766"
const BRIDGE_BOOTSTRAP: String = "res://addons/loki/bootstrap.py"
const BRIDGE_HARNESS: String = "res://addons/loki/harness"
const SETTINGS_DIALOG_SCRIPT: Script = preload("res://addons/loki/loki_settings.gd")
const BRIDGE_MAX_LAUNCHES: int = 3
const BRIDGE_GRACE_POLLS: int = 240
const BRIDGE_MISS_TOLERANCE: int = 4

## Two dock instances can exist (this plugin is re-entered on a filesystem
## rescan), and each would spawn its own bridge. The bridge refuses to double-bind,
## which leaves a stray bootstrap behind, so a short shared cooldown makes the
## later dock yield to the one that just launched.
static var _last_bridge_spawn_msec: int = 0

# Internal agent-steering turns; these are not conversation and must be hidden.
const INTERNAL_MARKERS: Array[String] = [
	"You ended your turn",
	"is premature",
	"NO file was created",
	"(no output)",
	"the model stopped responding",
	"returned empty replies",
	"You have not used any tools",
]

const BUBBLE_COLOR := Color("3a3a44")

var _chat_clip: Control
var _chat_scroll: ScrollContainer
var _chat_box: VBoxContainer
var _recent_log: Array[String] = []
var _input_edit: TextEdit
var _send_button: Button
var _stop_button: Button
var _clear_button: Button
var _status: Label
var _elapsed_label: Label
var _model_picker: OptionButton
var _menu: MenuButton
var _tabs: TabBar
var _add_tab_button: Button
var _attach_button: Button
var _attachment_status: Label
var _attachment_dialog: FileDialog
var _pending_attachments: Array[Dictionary] = []

const MAX_ATTACHMENT_FILES: int = 8
const MAX_ATTACHMENT_FILE_BYTES: int = 96_000
const MAX_ATTACHMENT_TOTAL_BYTES: int = 384_000
const TEXT_ATTACHMENT_EXTENSIONS: Array[String] = [
	"gd", "cs", "tscn", "tres", "gdshader", "shader", "json", "txt", "md", "cfg", "ini", "csv", "xml", "yaml", "yml", "toml", "py", "js", "ts", "html", "css", "sql", "log"
]

var _chat_http: HTTPRequest
var _approval_http: HTTPRequest
var _settings_http: HTTPRequest
var _auth_http: HTTPRequest
var _progress_http: HTTPRequest
var _cancel_http: HTTPRequest
var _conv_http: HTTPRequest
var _memory_http: HTTPRequest
var _ecc_http: HTTPRequest
var _connections_http: HTTPRequest
var _connect_http: HTTPRequest
var _mode_http: HTTPRequest
var _mode_button: MenuButton
var _settings_button: Button

var _poll_timer: Timer
var _progress_timer: Timer
var _auth_timer: Timer

var _permission_dialog: ConfirmationDialog
var _settings_dialog: ConfirmationDialog
var _rename_dialog: ConfirmationDialog
var _rename_edit: LineEdit
var _ecc_dialog: AcceptDialog
var _ecc_search: LineEdit
var _ecc_agents_list: ItemList
var _ecc_skills_list: ItemList

var _token: String = ""
var _approval_id: String = ""
var _busy: bool = false
var _bridge_ready: bool = false
var _task_mode: bool = false
var _signed_in: bool = false
var _progress_cursor: int = 0
var _active_chat_id: String = ""
var _started_ms: int = 0
var _relaunch_ticks: int = 0
var _bridge_misses: int = 0
var _bridge_grace: int = 0
var _bridge_launches: int = 0
var _launch_warned: bool = false
var _profile_apply_requested: bool = false
var _profile_request_pending: bool = false
var _last_op_id: int = 0
var _models: Array = []
var _current_model: String = ""
var _conversations: Array = []
var _ecc_agents: Array = []
var _ecc_skills: Array = []
var _active_conversation: String = ""
var _shown_conversation: String = ""
var _tab_suppressed: bool = false

func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_build_ui()
	_build_ecc_dialog()
	# A restored dock can come back with stale geometry; re-sorting once the layout
	# settles re-fits every row so the input can never be pushed off the panel.
	resized.connect(_refit_rows)
	get_tree().create_timer(1.0).timeout.connect(_refit_rows)
	_chat_http = HTTPRequest.new()
	_chat_http.timeout = 0.0
	_chat_http.request_completed.connect(_on_chat_response)
	add_child(_chat_http)
	_approval_http = _new_http(3.0, _on_approval_poll)
	_settings_http = _new_http(10.0, _on_settings_response)
	_connect_http = _new_http(15.0, _on_connect_response)
	_mode_http = _new_http(10.0, _on_mode_response)
	_refresh_mode()
	_auth_http = _new_http(12.0, _on_auth_response)
	_progress_http = _new_http(3.0, _on_progress_response)
	_cancel_http = _new_http(5.0, _on_cancel_response)
	_conv_http = _new_http(12.0, _on_conv_response)
	_memory_http = _new_http(10.0, _on_memory_response)
	_ecc_http = _new_http(30.0, _on_ecc_response)
	_connections_http = _new_http(10.0, _on_connections_response)
	_poll_timer = Timer.new()
	_poll_timer.wait_time = 0.5
	_poll_timer.timeout.connect(_poll_approval)
	_poll_timer.timeout.connect(_poll_editor_ops)
	add_child(_poll_timer)
	_progress_timer = Timer.new()
	_progress_timer.wait_time = 0.4
	_progress_timer.timeout.connect(_poll_progress)
	add_child(_progress_timer)
	_auth_timer = Timer.new()
	_auth_timer.wait_time = 2.0
	_auth_timer.timeout.connect(_refresh_account)
	add_child(_auth_timer)
	_profile_apply_requested = FileAccess.file_exists("user://loki_profile.cfg")
	_start_bridge()

func _new_http(timeout: float, handler: Callable) -> HTTPRequest:
	var node: HTTPRequest = HTTPRequest.new()
	node.timeout = timeout
	node.request_completed.connect(handler)
	add_child(node)
	return node

func _build_ui() -> void:
	# Honest minimum: the rows below need ~497px across (the toolbar is the widest
	# row) and ~286px down. Declaring less lets the editor shrink the dock below
	# what its content needs, which clips the input row and the right-hand buttons.
	# A small honest minimum: the user has to be able to drag the dock narrow. Nothing
	# below needs more than this - the toolbar clips and the transcript scrolls.
	custom_minimum_size = Vector2(300.0, 240.0)
	# No title row: the dock's own tab already reads "Loki", so repeating the name
	# inside the panel is just clutter. The header controls live on the tab row.
	_menu = MenuButton.new()
	_menu.text = "⋮"
	_menu.flat = true
	_menu.tooltip_text = "More"
	var popup: PopupMenu = _menu.get_popup()
	popup.add_icon_item(_editor_icon("Add"), "New chat", 2)
	popup.add_icon_item(_editor_icon("Edit"), "Rename chat", 4)
	popup.add_icon_item(_editor_icon("Copy"), "Copy chat as Markdown", 3)
	popup.add_icon_item(_editor_icon("History"), "Memory...", 5)
	popup.add_separator()
	popup.add_icon_item(_editor_icon("Tools"), "Settings", 1)
	popup.add_icon_item(_editor_icon("Node"), "Agents and skills (ECC)", 6)
	popup.add_icon_item(_editor_icon("Reload"), "Sync ECC library from GitHub", 7)
	popup.add_separator()
	popup.add_icon_item(_editor_icon("AnimationPlayer"), "Inspect current scene", 10)
	popup.add_icon_item(_editor_icon("Search"), "Validate project", 11)
	popup.add_icon_item(_editor_icon("Play"), "Run task (no limit)", 12)
	popup.add_icon_item(_editor_icon("Clear"), "Clear pending attachments", 13)
	_cap_popup(popup, 320)
	popup.id_pressed.connect(_on_menu_pressed)

	var tab_row: HBoxContainer = HBoxContainer.new()
	add_child(tab_row)
	_tabs = TabBar.new()
	_tabs.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_tabs.clip_tabs = true
	_tabs.tab_close_display_policy = TabBar.CLOSE_BUTTON_SHOW_ALWAYS
	_tabs.tab_changed.connect(_on_tab_changed)
	_tabs.tab_close_pressed.connect(_on_tab_close)
	tab_row.add_child(_tabs)
	_add_tab_button = Button.new()
	_add_tab_button.text = "+"
	var add_icon: Texture2D = _editor_icon("Add")
	if add_icon != null:
		_add_tab_button.icon = add_icon
		_add_tab_button.text = ""
	_add_tab_button.tooltip_text = "New chat"
	_add_tab_button.pressed.connect(_on_new_chat)
	tab_row.add_child(_add_tab_button)
	_settings_button = _icon_button("Tools", "Loki settings")
	_settings_button.pressed.connect(_on_settings_pressed)
	tab_row.add_child(_settings_button)
	tab_row.add_child(_menu)

	# The transcript is a real message list, so each message can be a ROUNDED bubble like
	# Ziva's. A plain ScrollContainer would defeat that: its minimum height follows its
	# child's, so a long transcript inflates it and shoves the input row off the bottom of
	# the dock. The scroll therefore lives inside a bare Control that CLIPS it - a plain
	# Control does not aggregate its children's minimum size, so the panel keeps its own.
	_chat_clip = Control.new()
	_chat_clip.name = "ChatClip"
	_chat_clip.clip_contents = true
	_chat_clip.custom_minimum_size = Vector2(200.0, 80.0)
	_chat_clip.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_chat_clip.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	add_child(_chat_clip)

	_chat_scroll = ScrollContainer.new()
	_chat_scroll.name = "ChatScroll"
	_chat_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_chat_scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_chat_clip.add_child(_chat_scroll)

	_chat_box = VBoxContainer.new()
	_chat_box.name = "ChatBox"
	_chat_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_chat_box.add_theme_constant_override("separation", 6)
	_chat_scroll.add_child(_chat_box)

	# The composer is one block: the box and its icon row travel together.
	var composer: VBoxContainer = VBoxContainer.new()
	composer.add_theme_constant_override("separation", 3)
	add_child(composer)
	_input_edit = TextEdit.new()
	_input_edit.custom_minimum_size = Vector2(200.0, 56.0)
	_input_edit.placeholder_text = "Message Loki  -  Enter to send, Shift+Enter for a new line"
	_input_edit.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	_input_edit.gui_input.connect(_on_input_gui)
	composer.add_child(_input_edit)

	# A flow container WRAPS its children instead of forcing their total width as the
	# minimum (measured: HBox 446px vs HFlow 71px). That is what makes the dock
	# resizable - with an HBox the panel could never be dragged narrower than its row.
	var bottom: HFlowContainer = HFlowContainer.new()
	bottom.add_theme_constant_override("h_separation", 4)
	bottom.add_theme_constant_override("v_separation", 2)
	composer.add_child(bottom)
	_attach_button = _icon_button("Attach", "Attach text, code, scenes, or images")
	_attach_button.text = "+"
	_attach_button.pressed.connect(_on_attach_pressed)
	bottom.add_child(_attach_button)
	_attachment_status = Label.new()
	_attachment_status.text = ""
	_attachment_status.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_attachment_status.clip_text = true
	_attachment_status.tooltip_text = "Pending attachments"
	bottom.add_child(_attachment_status)
	_model_picker = OptionButton.new()
	_model_picker.tooltip_text = "Model / provider"
	_model_picker.fit_to_longest_item = false
	_model_picker.clip_text = true
	_model_picker.flat = true
	_model_picker.custom_minimum_size = Vector2(112.0, 0.0)
	_cap_popup(_model_picker.get_popup(), 320)
	_model_picker.item_selected.connect(_on_model_selected)
	bottom.add_child(_model_picker)
	_mode_button = MenuButton.new()
	_mode_button.tooltip_text = "Ask (questions) -> Plan (clear the fog) -> Build (do it)"
	_mode_button.flat = true
	_mode_button.text = "Build"
	_cap_popup(_mode_button.get_popup(), 200)
	_mode_button.get_popup().id_pressed.connect(_on_mode_selected)
	_populate_modes()
	bottom.add_child(_mode_button)
	_send_button = _icon_button("Play", "Send  (Ctrl+Enter)")
	_send_button.pressed.connect(_on_send_pressed)
	bottom.add_child(_send_button)
	_clear_button = _icon_button("Clear", "Clear the display")
	_clear_button.pressed.connect(_on_clear_pressed)
	bottom.add_child(_clear_button)
	_stop_button = _icon_button("Stop", "Stop Loki")
	_stop_button.disabled = true
	_stop_button.pressed.connect(_on_stop_pressed)
	bottom.add_child(_stop_button)
	_status = Label.new()
	_status.text = "Starting bridge..."
	_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	bottom.add_child(_status)
	_elapsed_label = Label.new()
	_elapsed_label.text = ""
	bottom.add_child(_elapsed_label)


	_settings_dialog = SETTINGS_DIALOG_SCRIPT.new() as ConfirmationDialog
	_settings_dialog.profile_saved.connect(_on_profile_saved)
	_settings_dialog.connections_refresh_requested.connect(_refresh_connections)
	_settings_dialog.connect_requested.connect(_connect_provider)
	_settings_dialog.category_toggled.connect(_on_category_toggled)
	_settings_dialog.sign_in_requested.connect(_on_sign_in)
	_settings_dialog.sign_out_requested.connect(_on_sign_out)
	_settings_dialog.memory_save_requested.connect(_on_memory_save)
	_settings_dialog.confirmed.connect(_on_settings_closed)
	_settings_dialog.canceled.connect(_on_settings_closed)
	add_child(_settings_dialog)

	_permission_dialog = ConfirmationDialog.new()
	_permission_dialog.title = "Approve Loki tool call?"
	_permission_dialog.ok_button_text = "Approve"
	_permission_dialog.cancel_button_text = "Deny"
	_permission_dialog.confirmed.connect(_submit_approval.bind(true))
	_permission_dialog.canceled.connect(_submit_approval.bind(false))
	add_child(_permission_dialog)

	_attachment_dialog = FileDialog.new()
	_attachment_dialog.title = "Attach files to Loki"
	_attachment_dialog.file_mode = FileDialog.FILE_MODE_OPEN_FILES
	_attachment_dialog.access = FileDialog.ACCESS_FILESYSTEM
	_attachment_dialog.filters = PackedStringArray([
		"*.gd, *.cs, *.tscn, *.tres, *.gdshader, *.shader, *.json, *.txt, *.md, *.cfg, *.ini, *.csv, *.xml, *.yaml, *.yml, *.toml, *.py, *.js, *.ts, *.html, *.css, *.sql, *.log ; Text, code and Godot resources",
		"*.png, *.jpg, *.jpeg, *.webp ; Images (sent as file references)"
	])
	_attachment_dialog.files_selected.connect(_on_attachment_files_selected)
	add_child(_attachment_dialog)

	_rename_dialog = ConfirmationDialog.new()
	_rename_dialog.title = "Rename chat"
	_rename_edit = LineEdit.new()
	_rename_edit.custom_minimum_size = Vector2(320.0, 0.0)
	_rename_dialog.add_child(_rename_edit)
	_rename_dialog.confirmed.connect(_on_rename_confirmed)
	add_child(_rename_dialog)
	_apply_rounding()

# --- Ziva-style rounding ----------------------------------------------------
# The editor's own colours are KEPT: each control's CURRENT stylebox is copied and
# only its corners and padding change. That is what makes the panel read as rounded
# and beveled WITHOUT turning it into a different, darker theme.


func _rounded_copy(control: Variant, item: String, type: String, radius: int,
		pad_h: int = 0, pad_v: int = 0) -> StyleBox:
	var base: StyleBox = control.get_theme_stylebox(item, type)
	if base == null:
		return null
	var box: StyleBox = base.duplicate()
	if box is StyleBoxFlat:
		var flat: StyleBoxFlat = box
		flat.set_corner_radius_all(radius)
		if pad_h > 0:
			flat.content_margin_left = float(pad_h)
			flat.content_margin_right = float(pad_h)
		if pad_v > 0:
			flat.content_margin_top = float(pad_v)
			flat.content_margin_bottom = float(pad_v)
	return box


func _round(control: Variant, type: String, items: PackedStringArray, radius: int,
		pad_h: int = 0, pad_v: int = 0) -> void:
	if control == null:
		return
	for item: String in items:
		var box: StyleBox = _rounded_copy(control, item, type, radius, pad_h, pad_v)
		if box != null:
			control.add_theme_stylebox_override(item, box)


func _apply_rounding() -> void:
	# The typing box IS the bubble: a rounded field with real padding.
	_round(_input_edit, "TextEdit", PackedStringArray(["normal", "focus", "read_only"]), 12, 12, 9)
	# Every button and picker in the composer row, plus the header controls.
	for button: Button in [_attach_button, _model_picker, _mode_button, _send_button,
			_clear_button, _stop_button, _add_tab_button, _settings_button, _menu]:
		_round(button, "Button", PackedStringArray(
			["normal", "hover", "pressed", "focus", "disabled"]), 6)
	# The chat tabs.
	_round(_tabs, "TabBar", PackedStringArray(["tab_selected", "tab_unselected", "tab_hovered"]), 6, 6, 3)
	# The dropdown panels.
	_round(_menu.get_popup(), "PopupMenu", PackedStringArray(["panel"]), 8, 6, 6)
	_round(_model_picker.get_popup(), "PopupMenu", PackedStringArray(["panel"]), 8, 6, 6)
	_round(_mode_button.get_popup(), "PopupMenu", PackedStringArray(["panel"]), 8, 6, 6)


func _cap_popup(popup: PopupMenu, max_height: int = 300) -> void:
	# The model picker lists every provider and the menu lists every action, so the
	# dropdown opened taller than the editor window. Capping the height makes it scroll.
	if popup != null:
		popup.max_size = Vector2i(520, max_height)


func _popup_fit(dialog: Window, wanted: Vector2) -> void:
	# A Godot Window GROWS to its content's minimum size, so a tall dialog used to run
	# off the bottom of the editor and take its own Close button with it. Cap the usable
	# size to the host window, wrap the controls so their minimums cannot force it open
	# again, and only then center it.
	var host: Window = get_window()
	var limit: Vector2 = Vector2(1000.0, 700.0)
	if host != null:
		limit = Vector2(maxf(420.0, host.size.x - 60.0), maxf(300.0, host.size.y - 100.0))
	var fit: Vector2 = Vector2(minf(wanted.x, limit.x), minf(wanted.y, limit.y))
	dialog.wrap_controls = true
	dialog.max_size = Vector2i(int(limit.x), int(limit.y))
	dialog.size = Vector2i(int(fit.x), int(fit.y))
	dialog.popup_centered(Vector2i(int(fit.x), int(fit.y)))


func _editor_icon(name: String) -> Texture2D:
	# Godot's built-in editor icons.
	# Returns null outside a real editor session so headless runs never fail.
	if not Engine.is_editor_hint() or EditorInterface == null:
		return null
	var theme: Theme = EditorInterface.get_editor_theme()
	if theme != null and theme.has_icon(name, "EditorIcons"):
		return theme.get_icon(name, "EditorIcons")
	return null



func _scroll_chat_to_bottom() -> void:
	if _chat_scroll != null:
		var bar: VScrollBar = _chat_scroll.get_v_scroll_bar()
		if bar != null:
			_chat_scroll.scroll_vertical = int(bar.max_value)


func _refit_rows() -> void:
	# Only Containers have queue_sort; calling it on a RichTextLabel/TextEdit is an
	# invalid call that aborts the whole refit and leaves the rows unsorted.
	queue_sort()
	for child in get_children():
		if child is Container:
			(child as Container).queue_sort()


func _first_icon(names: PackedStringArray) -> Texture2D:
	# Several candidate names per meaning, because not every Godot version ships
	# every editor icon. The first that exists is used; none means no icon.
	for name in names:
		var texture: Texture2D = _editor_icon(name)
		if texture != null:
			return texture
	return null


func _project_dir() -> String:
	return ProjectSettings.globalize_path("res://").trim_suffix("/")

func _token_path() -> String:
	return _project_dir().path_join(".godot/loki_bridge.token")

func _load_token() -> void:
	if FileAccess.file_exists(_token_path()):
		_token = FileAccess.get_file_as_string(_token_path()).strip_edges()
	else:
		_token = ""

func _headers() -> PackedStringArray:
	return PackedStringArray(["Content-Type: application/json", "Authorization: Bearer " + _token])

func _api_get(node: HTTPRequest, path: String) -> void:
	_load_token()
	if _token.is_empty():
		return
	if node.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	node.request(BRIDGE_URL + path, _headers())

func _api_post(node: HTTPRequest, path: String, payload: Dictionary) -> void:
	_load_token()
	if _token.is_empty():
		return
	if node.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	node.request(BRIDGE_URL + path, _headers(), HTTPClient.METHOD_POST, JSON.stringify(payload))

func _start_bridge(force: bool = false) -> void:
	# force = the token file exists but nothing answers on the port (stale token),
	# so drop it and relaunch instead of polling a dead bridge forever.
	_load_token()
	if not force and not _token.is_empty() and _bridge_ready:
		_status.text = "Checking bridge..."
		_poll_timer.start()
		return
	if not force and not _token.is_empty() and _bridge_grace == 0 and _bridge_launches == 0:
		# first look after the editor opened: a token may be live from a bridge
		# started outside the editor, so give it a moment before relaunching.
		_bridge_grace = 4
		_status.text = "Checking bridge..."
		_poll_timer.start()
		return
	if _bridge_launches >= BRIDGE_MAX_LAUNCHES:
		_status.text = "Bridge not running"
		if not _launch_warned:
			_launch_warned = true
			_append_log("[color=#ff7777]Loki could not start its local engine. Check .godot/loki_bridge.log[/color]")
		_poll_timer.start()
		return
	# Yield to a bridge another dock instance just launched (see the note above).
	var now_msec: int = Time.get_ticks_msec()
	if not force and now_msec - _last_bridge_spawn_msec < 5000:
		_bridge_grace = BRIDGE_GRACE_POLLS
		_bridge_misses = 0
		_status.text = "Starting Loki bridge..."
		_poll_timer.start()
		return
	_last_bridge_spawn_msec = now_msec
	_bridge_launches += 1
	if force:
		DirAccess.remove_absolute(_token_path())
		_token = ""
	_bridge_grace = BRIDGE_GRACE_POLLS
	_bridge_misses = 0
	var pid: int = _spawn_bridge()
	if pid <= 0:
		_status.text = "Bridge launch failed"
		_append_log("[color=#ff7777]Could not start Loki: no Python 3 interpreter was found.[/color]")
		return
	_status.text = "Starting Loki bridge..."
	_poll_timer.start()


func _spawn_bridge() -> int:
	# Launch the bridge ourselves. A shell chain such as
	# "cmd /c start \"title\" /min app.bat" is mangled by cmd on Windows
	# ("cannot find the file Bridge\.") and never starts anything.
	# Create the process directly, preferring an interpreter that ships with
	# the project so the plugin needs no setup from the user.
	var project: String = _project_dir()
	var args: PackedStringArray = PackedStringArray([
		ProjectSettings.globalize_path(BRIDGE_BOOTSTRAP),
		"--loki-root", ProjectSettings.globalize_path(BRIDGE_HARNESS),
		"--project-dir", project,
		"--godot-exe", OS.get_executable_path(),
		"--secret-file", _token_path(),
	])
	for interpreter in _bridge_interpreters(project):
		if FileAccess.file_exists(interpreter):
			var bundled_pid: int = OS.create_process(interpreter, args, false)
			if bundled_pid > 0:
				return bundled_pid
	# Bare names only on Windows. On macOS/Linux create_process forks first, so it
	# returns a pid even when the name does not exist and the bridge silently never
	# starts; and a stock Mac has no `python`, `pythonw` or `py` at all.
	if OS.get_name() == "Windows":
		for name in PackedStringArray(["pythonw", "python", "py"]):
			var path_pid: int = OS.create_process(name, args, false)
			if path_pid > 0:
				return path_pid
	return -1


func _bridge_interpreters(project: String) -> PackedStringArray:
	# Absolute interpreter paths to try, best first: the project's own venv
	# (setup.bat / setup.sh make it), then a system Python 3 that bootstrap.py can
	# build that venv from.
	if OS.get_name() == "Windows":
		return PackedStringArray([
			project.path_join("harness_data/.venv/Scripts/pythonw.exe"),
			project.path_join("harness_data/.venv/Scripts/python.exe"),
			project.path_join(".venv/Scripts/pythonw.exe"),
			project.path_join(".venv/Scripts/python.exe"),
		])
	# macOS / Linux. A Godot started from Finder gets a minimal PATH, so name the
	# usual Homebrew, python.org and system locations explicitly.
	return PackedStringArray([
		project.path_join("harness_data/.venv/bin/python3"),
		project.path_join("harness_data/.venv/bin/python"),
		project.path_join(".venv/bin/python3"),
		project.path_join(".venv/bin/python"),
		"/opt/homebrew/bin/python3",
		"/usr/local/bin/python3",
		"/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
		"/usr/bin/python3",
	])

func _on_input_gui(event: InputEvent) -> void:
	# Enter sends and Shift+Enter adds a line, the way Ziva's composer works, so the habit
	# carries over. Enter only counts while there is something to send.
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_ENTER or event.keycode == KEY_KP_ENTER:
			if event.shift_pressed:
				return
			_input_edit.accept_event()
			if not _input_edit.text.strip_edges().is_empty():
				_on_send_pressed()

func _on_send_pressed() -> void:
	_submit(false)

func _on_attach_pressed() -> void:
	_popup_fit(_attachment_dialog, Vector2(900.0, 600.0))

func _on_attachment_files_selected(paths: PackedStringArray) -> void:
	var added: int = 0
	var total_bytes: int = 0
	for attachment: Dictionary in _pending_attachments:
		total_bytes += int(attachment.get("size", 0))
	for path: String in paths:
		if _pending_attachments.size() >= MAX_ATTACHMENT_FILES:
			break
		if _find_attachment(path) >= 0:
			continue
		var extension: String = path.get_extension().to_lower()
		var is_image: bool = extension in ["png", "jpg", "jpeg", "webp"]
		if not is_image and not extension in TEXT_ATTACHMENT_EXTENSIONS:
			_append_log("[color=#ebcb8b]Skipped unsupported attachment: %s[/color]" % _escape(path.get_file()))
			continue
		var file: FileAccess = FileAccess.open(path, FileAccess.READ)
		if file == null:
			_append_log("[color=#ff7777]Could not read attachment: %s[/color]" % _escape(path.get_file()))
			continue
		var file_size: int = file.get_length()
		file.close()
		var size_limit: int = 6_000_000 if is_image else MAX_ATTACHMENT_FILE_BYTES
		if file_size <= 0 or file_size > size_limit:
			_append_log("[color=#ebcb8b]Skipped %s: file must be 1 byte to %s.[/color]" % [_escape(path.get_file()), "6 MB" if is_image else "96 KB"])
			continue
		if total_bytes + file_size > MAX_ATTACHMENT_TOTAL_BYTES and not is_image:
			_append_log("[color=#ebcb8b]Attachment text limit reached (384 KB total).[/color]")
			continue
		_pending_attachments.append({"path": path, "name": path.get_file(), "size": file_size, "image": is_image})
		total_bytes += file_size
		added += 1
	_update_attachment_status()
	if added > 0:
		_append_log("[color=#a3be8c]Added %d attachment(s).[/color]" % added)

func _find_attachment(path: String) -> int:
	for index: int in _pending_attachments.size():
		if str(_pending_attachments[index].get("path", "")) == path:
			return index
	return -1

func _update_attachment_status() -> void:
	if _attachment_status == null:
		return
	var names: PackedStringArray = PackedStringArray()
	for attachment: Dictionary in _pending_attachments:
		names.append(str(attachment.get("name", "file")))
	_attachment_status.text = ("%d file(s) attached" % _pending_attachments.size()) if not names.is_empty() else ""
	_attachment_status.tooltip_text = "\n".join(names) if not names.is_empty() else "No pending attachments"

func _clear_attachments() -> void:
	_pending_attachments.clear()
	_update_attachment_status()

func _build_prompt_with_attachments(prompt: String) -> String:
	if _pending_attachments.is_empty():
		return prompt
	var context: String = prompt + "\n\n--- Attached files ---\n"
	for attachment: Dictionary in _pending_attachments:
		var path: String = str(attachment.get("path", ""))
		var name: String = str(attachment.get("name", path.get_file()))
		if bool(attachment.get("image", false)):
			var project_path: String = ""
			var global_project: String = _project_dir().replace("\\", "/")
			var global_image: String = path.replace("\\", "/")
			if global_image.begins_with(global_project + "/"):
				project_path = "res://" + global_image.trim_prefix(global_project + "/")
			context += "\nImage attachment: %s\n" % name
			if not project_path.is_empty():
				context += "Ask Loki to inspect this image with view_image using project path %s.\n" % project_path
			else:
				context += "Image path (external to this Godot project): %s\n" % path
			continue
		var file: FileAccess = FileAccess.open(path, FileAccess.READ)
		if file == null:
			context += "\n[Could not read %s; file may have moved.]\n" % name
			continue
		var content: String = file.get_as_text()
		file.close()
		context += "\nFile: %s (%d chars)\n```%s\n%s\n```\n" % [name, content.length(), path.get_extension().to_lower(), content]
	return context

func _submit(no_limit: bool) -> void:
	if _busy:
		return
	_load_token()
	if _token.is_empty():
		_status.text = "Bridge unavailable"
		return
	var prompt: String = _input_edit.text.strip_edges()
	if prompt.is_empty():
		if not no_limit:
			return
		prompt = "Inspect this Godot project read-only in short steps: the project tree, the current scene, then a headless validation. Do not modify files."
	prompt = _build_prompt_with_attachments(prompt)
	_clear_attachments()
	_input_edit.clear()
	_append_log(_escape(prompt), PackedStringArray(), true)
	_busy = true
	_task_mode = true
	_active_chat_id = ""
	_progress_cursor = 0
	_send_button.disabled = true
	_stop_button.disabled = false
	_started_ms = Time.get_ticks_msec()
	_elapsed_label.text = ""
	_status.text = "Loki is working..."
	_progress_timer.start()
	# A normal message is ONE turn: /chat answers it and stops. The unbounded goal loop
	# is only for the explicit "Run task (no limit)" menu item. Sending every message
	# through /task is what let a simple question run dozens of turns, drift out of
	# English and stall until the dock's request gave up.
	var route: String = "/task" if no_limit else "/chat"
	var payload: Dictionary = {"task": prompt, "steps": 0} if no_limit else {"message": prompt}
	var err: Error = _chat_http.request(BRIDGE_URL + route, _headers(), HTTPClient.METHOD_POST, JSON.stringify(payload))
	if err != OK:
		_busy = false
		_send_button.disabled = false
		_stop_button.disabled = true
		_progress_timer.stop()
		_status.text = "Request failed"
		_append_log("[color=#ff7777]Bridge request error: %s[/color]" % error_string(err))

func _on_chat_response(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	_busy = false
	_task_mode = false
	_progress_timer.stop()
	_send_button.disabled = false
	_stop_button.disabled = true
	_elapsed_label.text = ""
	if result != HTTPRequest.RESULT_SUCCESS:
		_status.text = "Bridge error"
		_append_log("[color=#ff7777]Bridge transport error %d[/color]" % result)
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		_status.text = "Invalid response"
		return
	var response: Dictionary = parsed
	if not bool(response.get("ok", false)):
		_status.text = "Task error"
		_append_log("[color=#ff7777]%s[/color]" % _escape(str(response.get("error", "Unknown error"))))
	else:
		_status.text = "Connected"
		_refresh_mode()
		var text: String = str(response.get("response", "")).strip_edges()
		if not text.is_empty():
			_append_log("[color=#dfe6ee]" + _escape(text) + "[/color]", PackedStringArray(["Script", "Node"]))
	_refresh_conversations()

func _poll_progress() -> void:
	if not _busy or _token.is_empty():
		return
	_elapsed_label.text = "%ds" % int((Time.get_ticks_msec() - _started_ms) / 1000.0)
	if _progress_http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	var err: Error = _progress_http.request(BRIDGE_URL + "/progress?after=" + str(_progress_cursor), _headers())
	if err != OK:
		_append_log("[color=#ff7777]Could not poll Loki progress: %s[/color]" % error_string(err))

func _on_progress_response(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		return
	var payload: Dictionary = parsed
	var chat_id: String = str(payload.get("chat_id", ""))
	if chat_id.is_empty():
		return
	if _active_chat_id.is_empty():
		_active_chat_id = chat_id
	elif _active_chat_id != chat_id:
		return
	var events_value: Variant = payload.get("progress", [])
	if not events_value is Array:
		return
	if _progress_cursor == 0 and events_value.size() > 0:
		var first_event: Variant = events_value[0]
		if first_event is Dictionary:
			_progress_cursor = int(first_event.get("id", 1)) - 1
	for event_value: Variant in events_value:
		if not event_value is Dictionary:
			continue
		var event: Dictionary = event_value
		_progress_cursor = maxi(_progress_cursor, int(event.get("id", 0)))
		var kind: String = str(event.get("event", "progress"))
		var text: String = _escape(str(event.get("text", "")))
		if kind == "thinking":
			_status.text = "Thinking..."
		elif kind == "tool":
			_status.text = "Using a tool..."
			_append_log("[color=#81a1c1]Tool: [/color]" + text, PackedStringArray(["Tools", "Wrench", "Node"]))
		elif kind == "tool_result":
			_append_log("[color=#a3be8c]Result: [/color]" + text, PackedStringArray(["StatusSuccess", "CheckBox", "Output", "Node"]))
		elif kind == "approval":
			_status.text = "Waiting for approval..."
			_append_log("[color=#ebcb8b]Permission: [/color]" + text, PackedStringArray(["Lock", "GuiLocked", "Security", "Node"]))
		elif kind == "task":
			_status.text = "Running task..."
			_append_log("[color=#b48ead][b]Task:[/b][/color] " + text, PackedStringArray(["AnimationPlayer", "Time", "Node"]))
		elif kind == "assistant":
			_append_log("[color=#dfe6ee]" + text + "[/color]", PackedStringArray(["Script", "Node"]))
		elif kind == "done":
			_append_log("[color=#a3be8c]Done: [/color]" + text, PackedStringArray(["StatusSuccess", "CheckBox", "Node"]))
		elif kind == "error":
			_append_log("[color=#ff7777]Error: [/color]" + text, PackedStringArray(["StatusError", "Error", "Warning", "Node"]))

func _populate_modes() -> void:
	var popup: PopupMenu = _mode_button.get_popup()
	popup.clear()
	popup.add_item("Ask - answer my questions only", 0)
	popup.add_item("Plan - clear the fog, then a plan", 1)
	popup.add_item("Build - implement it", 2)
	popup.add_separator()
	popup.add_item("Working this way: Ask first, then Plan, then Build.", 3)
	popup.set_item_disabled(3, true)


func _on_mode_selected(id: int) -> void:
	var wanted: String = ["ask", "plan", "build"][id] if id < 3 else ""
	if wanted.is_empty():
		return
	_load_token()
	if _token.is_empty() or _mode_http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_mode_http.request(BRIDGE_URL + "/mode", _headers(), HTTPClient.METHOD_POST,
		JSON.stringify({"mode": wanted}))


func _on_mode_response(result: int, _code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if parsed is Dictionary:
		_set_mode_label(str((parsed as Dictionary).get("label", "")))


func _set_mode_label(label: String) -> void:
	if _mode_button != null and not label.is_empty():
		_mode_button.text = label


func _refresh_mode() -> void:
	_load_token()
	if _token.is_empty() or _mode_http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_mode_http.request(BRIDGE_URL + "/mode", _headers())


func _connect_provider(provider: String, key: String) -> void:
	if key.strip_edges().is_empty():
		_settings_dialog.set_connect_result(false, "Enter a key first.")
		return
	_load_token()
	if _token.is_empty():
		_settings_dialog.set_connect_result(false, "Loki's local engine is not running yet.")
		return
	if _connect_http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_settings_dialog.set_connect_result(true, "Checking the key...")
	var err: Error = _connect_http.request(BRIDGE_URL + "/connect", _headers(),
		HTTPClient.METHOD_POST, JSON.stringify({"provider": provider, "key": key}))
	if err != OK:
		_settings_dialog.set_connect_result(false, "Could not reach Loki's local engine.")


func _on_connect_response(result: int, _code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or not parsed is Dictionary:
		_settings_dialog.set_connect_result(false, "Connection check failed.")
		return
	var payload: Dictionary = parsed
	var ok: bool = bool(payload.get("ok", false))
	var message: String = str(payload.get("message", payload.get("error", "No response.")))
	_settings_dialog.set_connect_result(ok, message)
	if ok:
		_refresh_connections()


func _on_stop_pressed() -> void:
	if not _busy or _token.is_empty():
		return
	_status.text = "Stopping..."
	_stop_button.disabled = true
	var err: Error = _cancel_http.request(BRIDGE_URL + "/cancel", _headers(), HTTPClient.METHOD_POST, "{}")
	if err != OK:
		_append_log("[color=#ff7777]Could not send stop request: %s[/color]" % error_string(err))

func _on_cancel_response(_result: int, _code: int, _h: PackedStringArray, _body: PackedByteArray) -> void:
	_append_log("[color=#ffb86c]Stop requested - waiting for Loki to stop.[/color]")
	_status.text = "Stopping..."

func _refresh_conversations() -> void:
	_api_get(_conv_http, "/conversations")

func _on_conv_response(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if parsed is Dictionary:
		_apply_conversations(parsed)

func _apply_conversations(payload: Dictionary) -> void:
	if payload.has("conversations"):
		_conversations = payload.get("conversations", [])
	if payload.has("active"):
		_active_conversation = str(payload.get("active", ""))
	_rebuild_tabs()
	if payload.has("messages"):
		_shown_conversation = _active_conversation
		_render_messages(payload.get("messages", []))
	elif not _active_conversation.is_empty() and _active_conversation != _shown_conversation:
		_api_get(_conv_http, "/conversations/messages?id=" + _active_conversation)

func _rebuild_tabs() -> void:
	_tab_suppressed = true
	while _tabs.get_tab_count() > 0:
		_tabs.remove_tab(0)
	var select_index: int = -1
	for i in _conversations.size():
		var convo: Dictionary = _conversations[i]
		_tabs.add_tab(str(convo.get("title", "chat")))
		if str(convo.get("id", "")) == _active_conversation:
			select_index = i
	if select_index >= 0:
		_tabs.current_tab = select_index
	elif _tabs.get_tab_count() > 0:
		_tabs.current_tab = 0
	_tab_suppressed = false

func _on_tab_changed(index: int) -> void:
	if _tab_suppressed or index < 0 or index >= _conversations.size():
		return
	var cid: String = str((_conversations[index] as Dictionary).get("id", ""))
	if cid.is_empty() or cid == _active_conversation:
		return
	_active_conversation = cid
	_api_post(_conv_http, "/conversations/switch", {"id": cid})

func _on_tab_close(index: int) -> void:
	if index < 0 or index >= _conversations.size():
		return
	var cid: String = str((_conversations[index] as Dictionary).get("id", ""))
	if cid.is_empty():
		return
	_api_post(_conv_http, "/conversations/delete", {"id": cid})

func _on_new_chat() -> void:
	_api_post(_conv_http, "/conversations", {"title": ""})

func _on_rename_confirmed() -> void:
	if _active_conversation.is_empty():
		return
	_api_post(_conv_http, "/conversations/rename", {"id": _active_conversation, "title": _rename_edit.text.strip_edges()})

func _current_title() -> String:
	for convo: Variant in _conversations:
		if convo is Dictionary and str((convo as Dictionary).get("id", "")) == _active_conversation:
			return str((convo as Dictionary).get("title", ""))
	return ""

func _render_messages(messages: Array) -> void:
	_clear_chat()
	if messages.is_empty():
		_append_log("[i]New chat. Ask Loki for a change.[/i]")
		return
	for entry: Variant in messages:
		if not entry is Dictionary:
			continue
		var message: Dictionary = entry
		var role: String = str(message.get("role", ""))
		var content: String = str(message.get("content", "")).strip_edges()
		if content.is_empty():
			continue
		if role == "user":
			# Your message gets a right-aligned bubble like Ziva's; Loki's stays plain text.
			_append_log(_escape(content), PackedStringArray(), true)
		elif role == "assistant":
			_append_log("[color=#e6e9ee]" + _escape(content) + "[/color]", PackedStringArray(["Script", "Node"]))

func _refresh_memory() -> void:
	_api_get(_memory_http, "/memory")

func _on_memory_response(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if parsed is Dictionary and _settings_dialog.has_method("set_memory"):
		_settings_dialog.set_memory(str((parsed as Dictionary).get("memory", "")))

func _on_memory_save(text: String) -> void:
	_api_post(_memory_http, "/memory", {"text": text})
	_append_log("[color=#a3be8c]Memory updated.[/color]")

func open_settings() -> void:
	# Called from the Loki viewport screen.
	_on_settings_pressed()


func _on_settings_pressed() -> void:
	_refresh_settings()
	_refresh_models()
	_refresh_account()
	_refresh_memory()
	_refresh_connections()
	_auth_timer.start()
	_popup_fit(_settings_dialog, Vector2(620.0, 620.0))

func _on_settings_closed() -> void:
	_auth_timer.stop()

func _refresh_settings() -> void:
	_api_get(_settings_http, "/settings")

func _refresh_models() -> void:
	_api_get(_settings_http, "/models")

func _refresh_connections() -> void:
	_api_get(_connections_http, "/connections")

func _on_connections_response(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if parsed is Dictionary and _settings_dialog.has_method("set_connections"):
		_settings_dialog.set_connections(parsed)

func _refresh_account() -> void:
	if _auth_http.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED:
		_api_get(_auth_http, "/auth/status")

func _on_settings_response(_result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	if code != 200:
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		return
	var payload: Dictionary = parsed
	if payload.has("models"):
		_models = payload.get("models", [])
		if _model_picker != null:
			_model_picker.clear()
			var current: String = str(payload.get("current", ""))
			_current_model = current
			for i in _models.size():
				_model_picker.add_item(str(_models[i]))
				if str(_models[i]) == current:
					_model_picker.select(i)
			_status.text = "Connected - " + (_current_model if not _current_model.is_empty() else "model")
		return
	if _settings_dialog.has_method("set_categories"):
		_settings_dialog.set_categories(payload)

func _on_model_selected(index: int) -> void:
	if index < 0 or index >= _models.size():
		return
	_api_post(_settings_http, "/model", {"model": _models[index]})
	_current_model = str(_models[index])
	_status.text = "Connected - " + _current_model

func _on_auth_response(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		return
	var payload: Dictionary = parsed
	if payload.has("signed_in") and _settings_dialog.has_method("set_account"):
		var user: Dictionary = payload.get("user", {})
		var is_signed_in: bool = bool(payload.get("signed_in", false))
		if is_signed_in and not _signed_in:
			_append_log("[color=#a3be8c]Signed in to Loki Cloud.[/color]")
		elif _signed_in and not is_signed_in:
			_append_log("[color=#ebcb8b]Signed out of Loki Cloud.[/color]")
		_signed_in = is_signed_in
		_settings_dialog.set_account(str(user.get("email", "")), str(user.get("name", "")), is_signed_in)

func _on_category_toggled(category: String, enabled: bool) -> void:
	_api_post(_settings_http, "/settings", {"category": category, "enabled": enabled})

func _on_sign_in() -> void:
	_settings_dialog.set_status("Opening your browser to sign in with Google...")
	_append_log("[color=#b48ead]Opening your browser for Google sign-in...[/color]")
	_api_post(_auth_http, "/auth/start", {})

func _on_sign_out() -> void:
	_settings_dialog.set_status("Signing out...")
	_api_post(_auth_http, "/auth/signout", {})

func _on_profile_saved() -> void:
	_load_token()
	if _token.is_empty():
		_append_log("[color=#ff7777]Profile saved locally; bridge unavailable to apply it yet.[/color]")
		return
	_profile_apply_requested = true
	_apply_saved_profile()

func _apply_saved_profile() -> void:
	if not FileAccess.file_exists("user://loki_profile.cfg"):
		return
	if not _bridge_ready or _profile_request_pending:
		_profile_apply_requested = true
		return
	_profile_request_pending = true
	var profile_path: String = ProjectSettings.globalize_path("user://loki_profile.cfg")
	var request: HTTPRequest = HTTPRequest.new()
	request.timeout = 6.0
	add_child(request)
	request.request_completed.connect(func(_r: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
		_profile_request_pending = false
		request.queue_free()
		if code != 200:
			_profile_apply_requested = true
			_append_log("[color=#ff7777]Profile update failed (HTTP %d)[/color]" % code)
		else:
			_profile_apply_requested = false
			_append_log("[color=#a3be8c]Profile applied to the next Loki turn.[/color]"))
	var err: Error = request.request(BRIDGE_URL + "/profile", _headers(), HTTPClient.METHOD_POST, JSON.stringify({"profile_path": profile_path}))
	if err != OK:
		_profile_request_pending = false
		request.queue_free()
		_profile_apply_requested = true
		_append_log("[color=#ff7777]Could not apply profile: %s[/color]" % error_string(err))

func _on_menu_pressed(id: int) -> void:
	match id:
		1:
			_on_settings_pressed()
		2:
			_on_new_chat()
		3:
			_copy_chat_markdown()
		4:
			_rename_edit.text = _current_title()
			_popup_fit(_rename_dialog, Vector2(380.0, 180.0))
		5:
			_on_settings_pressed()
			_settings_dialog.open_memory_tab()
		6:
			_open_ecc()
		7:
			_sync_ecc()
		10:
			_on_quick_action_selected(1)
		11:
			_on_quick_action_selected(2)
		12:
			_on_quick_action_selected(3)
		13:
			_clear_attachments()

func _copy_chat_markdown() -> void:
	DisplayServer.clipboard_set(_chat_as_text())
	_append_log("[color=#a3be8c]Chat copied to clipboard as text.[/color]")

func _on_quick_action_selected(index: int) -> void:
	if index == 3:
		_submit(true)
		return
	if index == 1:
		_input_edit.text = "Inspect the currently open Godot scene and report its node tree and configuration warnings. Do not modify files."
	elif index == 2:
		_input_edit.text = "Validate this Godot project with a headless editor check and report warnings/errors. Do not modify files."
	else:
		return
	_submit(false)

func _on_clear_pressed() -> void:
	_clear_chat()
	_append_log("[b]Display cleared.[/b] Use the + tab to start a new chat.")

func _chat_label(text: String) -> RichTextLabel:
	# A label that GROWS to its text (fit_content) and wraps, so a bubble is as tall as
	# its message and never reports a large minimum width.
	var label: RichTextLabel = RichTextLabel.new()
	label.bbcode_enabled = true
	label.fit_content = true
	label.scroll_active = false
	label.selection_enabled = true
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.custom_minimum_size = Vector2.ZERO
	label.text = text
	return label


func _append_bubble(text: String) -> void:
	# Ziva's rounded bubble: the user's turn gets a rounded, padded panel.
	var panel: PanelContainer = PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _bubble_style())
	panel.add_child(_chat_label(text))
	_chat_box.add_child(panel)
	call_deferred("_scroll_chat_to_bottom")


func _bubble_style() -> StyleBoxFlat:
	var box: StyleBoxFlat = StyleBoxFlat.new()
	box.bg_color = BUBBLE_COLOR
	box.set_corner_radius_all(10)
	box.content_margin_left = 10.0
	box.content_margin_right = 10.0
	box.content_margin_top = 7.0
	box.content_margin_bottom = 7.0
	return box


func _clear_chat() -> void:
	if _chat_box == null:
		return
	for child in _chat_box.get_children():
		_chat_box.remove_child(child)
		child.queue_free()


func _collect_text(node: Node) -> String:
	if node is RichTextLabel:
		return (node as RichTextLabel).get_parsed_text()
	var out: String = ""
	for child in node.get_children():
		var part: String = _collect_text(child)
		if not part.strip_edges().is_empty():
			out += part + "\n"
	return out


func _chat_as_text() -> String:
	var parts: PackedStringArray = PackedStringArray()
	if _chat_box != null:
		for child in _chat_box.get_children():
			parts.append(_collect_text(child))
	return "".join(parts)


func _append_log(text: String, icons: PackedStringArray = PackedStringArray(),
		bubble: bool = false) -> void:
	if _is_internal(text):
		return
	var plain: String = text.strip_edges()
	if plain in _recent_log:
		return
	_recent_log.append(plain)
	if _recent_log.size() > 80:
		_recent_log.remove_at(0)
	if bubble:
		_append_bubble(text)
		return
	# Everything else is a plain row: an optional editor icon, then the message.
	var row: HBoxContainer = HBoxContainer.new()
	row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_theme_constant_override("separation", 6)
	if icons.size() > 0:
		var texture: Texture2D = _first_icon(icons)
		if texture != null:
			var image: TextureRect = TextureRect.new()
			image.texture = texture
			image.custom_minimum_size = Vector2(15.0, 15.0)
			image.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
			row.add_child(image)
	row.add_child(_chat_label(text))
	_chat_box.add_child(row)
	call_deferred("_scroll_chat_to_bottom")


func _is_internal(text: String) -> bool:
	var plain: String = text.strip_edges()
	for marker: String in INTERNAL_MARKERS:
		if plain.contains(marker):
			return true
	return false

func _icon_button(icon_name: String, tip: String) -> Button:
	var button: Button = Button.new()
	var icon: Texture2D = _editor_icon(icon_name)
	if icon != null:
		button.icon = icon
	else:
		button.text = tip.split(" ")[0]
	button.tooltip_text = tip
	button.flat = true
	return button


func _escape(value: String) -> String:
	# Already-escaped text escaped again used to render the markers literally
	# ("[lb]0,5,-10[rb]"), so normalise first, then escape exactly once using
	# sentinels that cannot themselves be re-escaped.
	var v: String = value.replace("[lb]", "[").replace("[rb]", "]")
	v = v.replace("[", "@@LB@@").replace("]", "@@RB@@")
	return v.replace("@@LB@@", "[lb]").replace("@@RB@@", "[rb]")

func _poll_approval() -> void:
	_load_token()
	if _approval_http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	if _token.is_empty():
		if _bridge_grace > 0:
			_bridge_grace -= 1
		else:
			_start_bridge()
		return
	var route: String = "/approval" if _bridge_ready else "/health"
	var err: Error = _approval_http.request(BRIDGE_URL + route, _headers())
	if err != OK:
		_status.text = "Bridge unavailable"

func _on_approval_poll(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		_bridge_ready = false
		if code == 401:
			_token = ""
			_bridge_grace = 0
			DirAccess.remove_absolute(_token_path())
			return
		if _token.is_empty():
			_status.text = "Waiting for bridge..."
			return
		if _bridge_grace > 0:
			_bridge_grace -= 1
			_status.text = "Starting Loki bridge..."
			return
		_bridge_misses += 1
		if _bridge_misses < BRIDGE_MISS_TOLERANCE:
			_status.text = "Waiting for bridge..."
			return
		_status.text = "Bridge not running - restarting..."
		_start_bridge(true)
		return
	_bridge_misses = 0
	_bridge_grace = 0
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		return
	if not _bridge_ready:
		_bridge_ready = true
		_refresh_models()
		_refresh_conversations()
		if _profile_apply_requested:
			_apply_saved_profile()
	_status.text = "Connected - " + (_current_model if not _current_model.is_empty() else "model")
	if not _approval_id.is_empty():
		return
	var ticket_value: Variant = (parsed as Dictionary).get("approval")
	if not ticket_value is Dictionary:
		return
	var ticket: Dictionary = ticket_value
	var ticket_id: String = str(ticket.get("id", ""))
	if ticket_id.is_empty() or ticket_id == _approval_id:
		return
	_approval_id = ticket_id
	_permission_dialog.dialog_text = "%s

%s

Approve only if you understand this action." % [str(ticket.get("tool", "tool")), str(ticket.get("details", ""))]
	_popup_fit(_permission_dialog, Vector2(560.0, 400.0))

func _submit_approval(approved: bool) -> void:
	if _approval_id.is_empty() or _token.is_empty():
		return
	var request: HTTPRequest = HTTPRequest.new()
	request.timeout = 5.0
	add_child(request)
	request.request_completed.connect(func(_r: int, _c: int, _h: PackedStringArray, _b: PackedByteArray) -> void:
		request.queue_free())
	var err: Error = request.request(BRIDGE_URL + "/approval", _headers(), HTTPClient.METHOD_POST, JSON.stringify({"id": _approval_id, "approved": approved}))
	if err != OK:
		request.queue_free()
	_append_log("[color=#a3be8c]Tool approval granted.[/color]" if approved else "[color=#ebcb8b]Tool approval denied.[/color]")
	_approval_id = ""

func _dock_log(text: String) -> void:
	var file: FileAccess = FileAccess.open(_project_dir() + "/.godot/loki_dock.log", FileAccess.READ_WRITE)
	if file == null:
		file = FileAccess.open(_project_dir() + "/.godot/loki_dock.log", FileAccess.WRITE)
	if file == null:
		return
	file.seek_end()
	file.store_line(Time.get_datetime_string_from_system() + "  " + text)
	file.close()

func _poll_editor_ops() -> void:
	var path: String = _project_dir() + "/.godot/loki_editor_ops.jsonl"
	if not FileAccess.file_exists(path):
		return
	var text: String = FileAccess.get_file_as_string(path)
	for line in text.split("\n"):
		var trimmed: String = line.strip_edges()
		if trimmed.is_empty():
			continue
		var parsed: Variant = JSON.parse_string(trimmed)
		if not (parsed is Dictionary):
			continue
		var op_id: int = int((parsed as Dictionary).get("id", 0))
		if op_id <= _last_op_id:
			continue
		_last_op_id = op_id
		_apply_editor_op(parsed)

func _apply_editor_op(op: Dictionary) -> void:
	var kind: String = str(op.get("op", ""))
	var path: String = str(op.get("path", ""))
	if kind != "open_scene" or path.is_empty():
		return
	_dock_log("op open_scene id=%d path=%s exists=%s" % [int(op.get("id", 0)), path, str(FileAccess.file_exists(path))])
	if DisplayServer.get_name() == "headless":
		_dock_log("skipping open_scene_from_path (headless)")
		return
	EditorInterface.open_scene_from_path(path)
	_dock_log("opened %s" % path)
	_append_log("[color=#a3be8c]Opened in the editor: [/color]" + _escape(path))
	if bool(op.get("run", false)):
		EditorInterface.play_custom_scene(path)


func _build_ecc_dialog() -> void:
	_ecc_dialog = AcceptDialog.new()
	_ecc_dialog.title = "ECC agents and skills"
	_ecc_dialog.ok_button_text = "Close"
	var box: VBoxContainer = VBoxContainer.new()
	box.custom_minimum_size = Vector2(540.0, 470.0)
	_ecc_dialog.add_child(box)
	var hint: Label = Label.new()
	hint.text = "Pick one to ask Loki to adopt it. The agent loads it with the load_ecc_agent / load_ecc_skill tool."
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(hint)
	_ecc_search = LineEdit.new()
	_ecc_search.placeholder_text = "Search agents and skills..."
	_ecc_search.text_changed.connect(func(_text: String) -> void: _filter_ecc())
	box.add_child(_ecc_search)
	var tabs: TabContainer = TabContainer.new()
	tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
	box.add_child(tabs)
	_ecc_agents_list = ItemList.new()
	_ecc_agents_list.name = "Agents"
	_ecc_agents_list.item_activated.connect(_on_ecc_chosen.bind(true))
	tabs.add_child(_ecc_agents_list)
	_ecc_skills_list = ItemList.new()
	_ecc_skills_list.name = "Skills"
	_ecc_skills_list.item_activated.connect(_on_ecc_chosen.bind(false))
	tabs.add_child(_ecc_skills_list)
	add_child(_ecc_dialog)

func _open_ecc() -> void:
	if not _bridge_ready:
		_append_log("[color=#ebcb8b]The bridge is still starting; try again in a moment.[/color]")
		return
	_popup_fit(_ecc_dialog, Vector2(580.0, 540.0))
	_api_get(_ecc_http, "/ecc")

func _on_ecc_response(_result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	if code != 200:
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		return
	_ecc_agents = (parsed as Dictionary).get("agents", [])
	_ecc_skills = (parsed as Dictionary).get("skills", [])
	_filter_ecc()

func _filter_ecc() -> void:
	if _ecc_agents_list == null or _ecc_skills_list == null:
		return
	var needle: String = _ecc_search.text.strip_edges().to_lower()
	_ecc_agents_list.clear()
	for name in _ecc_agents:
		if needle.is_empty() or needle in str(name).to_lower():
			_ecc_agents_list.add_item(str(name))
	_ecc_skills_list.clear()
	for name in _ecc_skills:
		if needle.is_empty() or needle in str(name).to_lower():
			_ecc_skills_list.add_item(str(name))

func _on_ecc_chosen(index: int, is_agent: bool) -> void:
	var list: ItemList = _ecc_agents_list if is_agent else _ecc_skills_list
	if list == null or index < 0 or index >= list.item_count:
		return
	var name: String = list.get_item_text(index)
	if is_agent:
		_input_edit.text = "Adopt the ECC agent '" + name + "' (call load_ecc_agent first) and continue with my request."
	else:
		_input_edit.text = "Apply the ECC skill '" + name + "' (call load_ecc_skill first) to this task."
	_ecc_dialog.hide()
	_input_edit.grab_focus()

func _sync_ecc() -> void:
	_load_token()
	if _token.is_empty():
		_append_log("[color=#ff7777]The bridge is not running, so ECC cannot be synced yet.[/color]")
		return
	_append_log("[color=#b48ead]Fetching the ECC library from GitHub...[/color]")
	var request: HTTPRequest = HTTPRequest.new()
	request.timeout = 300.0
	add_child(request)
	request.request_completed.connect(func(_r: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
		request.queue_free()
		if code != 200:
			_append_log("[color=#ff7777]ECC sync failed (HTTP %d).[/color]" % code)
			return
		var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
		if not parsed is Dictionary:
			return
		var payload: Dictionary = parsed
		_ecc_agents = payload.get("agents", [])
		_ecc_skills = payload.get("skills", [])
		_append_log("[color=#a3be8c]ECC library ready: %d agents, %d skills.[/color]" % [_ecc_agents.size(), _ecc_skills.size()]))
	request.request(BRIDGE_URL + "/ecc/sync", _headers(), HTTPClient.METHOD_POST, JSON.stringify({"force": true}))
