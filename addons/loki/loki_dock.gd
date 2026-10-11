@tool
extends VBoxContainer

## Loki dock - a Ziva-style chat with conversation tabs, saved history and memory.

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

var _chat_log: RichTextLabel
var _recent_log: Array[String] = []
var _input_edit: TextEdit
var _send_button: Button
var _stop_button: Button
var _clear_button: Button
var _status: Label
var _elapsed_label: Label
var _model_picker: OptionButton
var _smart_button: Button
var _menu: MenuButton
var _tabs: TabBar
var _add_tab_button: Button

var _chat_http: HTTPRequest
var _approval_http: HTTPRequest
var _settings_http: HTTPRequest
var _auth_http: HTTPRequest
var _progress_http: HTTPRequest
var _cancel_http: HTTPRequest
var _conv_http: HTTPRequest
var _memory_http: HTTPRequest
var _ecc_http: HTTPRequest

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
	_chat_http = HTTPRequest.new()
	_chat_http.timeout = 0.0
	_chat_http.request_completed.connect(_on_chat_response)
	add_child(_chat_http)
	_approval_http = _new_http(3.0, _on_approval_poll)
	_settings_http = _new_http(10.0, _on_settings_response)
	_auth_http = _new_http(12.0, _on_auth_response)
	_progress_http = _new_http(3.0, _on_progress_response)
	_cancel_http = _new_http(5.0, _on_cancel_response)
	_conv_http = _new_http(12.0, _on_conv_response)
	_memory_http = _new_http(10.0, _on_memory_response)
	_ecc_http = _new_http(30.0, _on_ecc_response)
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
	custom_minimum_size = Vector2(360.0, 320.0)
	var header: HBoxContainer = HBoxContainer.new()
	add_child(header)
	var heading: Label = Label.new()
	heading.text = "Loki"
	heading.add_theme_font_size_override("font_size", 15)
	heading.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(heading)
	_menu = MenuButton.new()
	_menu.text = "⋮"
	_menu.flat = true
	_menu.tooltip_text = "More"
	var popup: PopupMenu = _menu.get_popup()
	popup.add_icon_item(_editor_icon("Tools"), "Settings", 1)
	popup.add_icon_item(_editor_icon("Add"), "New chat", 2)
	popup.add_icon_item(_editor_icon("Edit"), "Rename chat", 4)
	popup.add_icon_item(_editor_icon("History"), "Memory...", 5)
	popup.add_icon_item(_editor_icon("Node"), "Agents and skills (ECC)", 6)
	popup.add_icon_item(_editor_icon("Reload"), "Sync ECC library from GitHub", 7)
	popup.add_icon_item(_editor_icon("Copy"), "Copy chat as Markdown", 3)
	popup.add_separator()
	popup.add_icon_item(_editor_icon("AnimationPlayer"), "Inspect current scene", 10)
	popup.add_icon_item(_editor_icon("Search"), "Validate project", 11)
	popup.add_icon_item(_editor_icon("Play"), "Run task (no limit)", 12)
	popup.id_pressed.connect(_on_menu_pressed)
	header.add_child(_menu)

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

	_chat_log = RichTextLabel.new()
	_chat_log.bbcode_enabled = true
	_chat_log.selection_enabled = true
	_chat_log.scroll_following = true
	_chat_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_chat_log.custom_minimum_size = Vector2(360.0, 170.0)
	add_child(_chat_log)
	_append_log("[color=#6e7681]Loki - your Godot agent.[/color]")

	_input_edit = TextEdit.new()
	_input_edit.custom_minimum_size = Vector2(360.0, 96.0)
	_input_edit.placeholder_text = "Describe a task; Loki works until done (Ctrl+Enter)"
	_input_edit.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	_input_edit.gui_input.connect(_on_input_gui)
	add_child(_input_edit)

	var bottom: HBoxContainer = HBoxContainer.new()
	add_child(bottom)
	_model_picker = OptionButton.new()
	_model_picker.tooltip_text = "Model / provider"
	_model_picker.fit_to_longest_item = false
	_model_picker.clip_text = true
	_model_picker.flat = true
	_model_picker.custom_minimum_size = Vector2(112.0, 0.0)
	_model_picker.item_selected.connect(_on_model_selected)
	bottom.add_child(_model_picker)
	_smart_button = Button.new()
	_smart_button.text = "Smart"
	_smart_button.flat = true
	_smart_button.tooltip_text = "Use the best available free provider, chosen automatically"
	_smart_button.pressed.connect(_on_smart_pressed)
	bottom.add_child(_smart_button)
	var bottom_spacer: Control = Control.new()
	bottom_spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bottom.add_child(bottom_spacer)
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

	_rename_dialog = ConfirmationDialog.new()
	_rename_dialog.title = "Rename chat"
	_rename_edit = LineEdit.new()
	_rename_edit.custom_minimum_size = Vector2(320.0, 0.0)
	_rename_dialog.add_child(_rename_edit)
	_rename_dialog.confirmed.connect(_on_rename_confirmed)
	add_child(_rename_dialog)

func _editor_icon(name: String) -> Texture2D:
	# Godot's built-in editor icons - the same set Ziva's panel draws from.
	# Returns null outside a real editor session so headless runs never fail.
	if not Engine.is_editor_hint() or EditorInterface == null:
		return null
	var theme: Theme = EditorInterface.get_editor_theme()
	if theme != null and theme.has_icon(name, "EditorIcons"):
		return theme.get_icon(name, "EditorIcons")
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
	var bundled: PackedStringArray = PackedStringArray([
		project.path_join("harness_data/.venv/Scripts/pythonw.exe"),
		project.path_join("harness_data/.venv/Scripts/python.exe"),
		project.path_join(".venv/Scripts/pythonw.exe"),
		project.path_join(".venv/Scripts/python.exe"),
	])
	for interpreter in bundled:
		if FileAccess.file_exists(interpreter):
			var bundled_pid: int = OS.create_process(interpreter, args, false)
			if bundled_pid > 0:
				return bundled_pid
	for name in PackedStringArray(["pythonw", "python", "py"]):
		var path_pid: int = OS.create_process(name, args, false)
		if path_pid > 0:
			return path_pid
	return -1

func _on_input_gui(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.keycode == KEY_ENTER and event.ctrl_pressed:
		_on_send_pressed()
		_input_edit.accept_event()

func _on_send_pressed() -> void:
	_submit(false)

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
	_input_edit.clear()
	_append_log("[right][color=#7f9db0][b]You[/b][/color][/right]
[right][color=#dfe6ee]" + _escape(prompt) + "[/color][/right]")
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
	var err: Error = _chat_http.request(BRIDGE_URL + "/task", _headers(), HTTPClient.METHOD_POST, JSON.stringify({"task": prompt, "steps": 0}))
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
		var text: String = str(response.get("response", "")).strip_edges()
		if not text.is_empty():
			_append_log("[color=#5c6670]▏[/color] [color=#dfe6ee]" + _escape(text) + "[/color]")
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
			_append_log("[color=#81a1c1]Tool: [/color]" + text)
		elif kind == "tool_result":
			_append_log("[color=#a3be8c]Result: [/color]" + text)
		elif kind == "approval":
			_status.text = "Waiting for approval..."
			_append_log("[color=#ebcb8b]Permission: [/color]" + text)
		elif kind == "task":
			_status.text = "Running task..."
			_append_log("[color=#b48ead][b]Task:[/b][/color] " + text)
		elif kind == "assistant":
			_append_log("[color=#5c6670]▏[/color] [color=#dfe6ee]" + text + "[/color]")
		elif kind == "done":
			_append_log("[color=#a3be8c]Done: [/color]" + text)
		elif kind == "error":
			_append_log("[color=#ff7777]Error: [/color]" + text)

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
	_chat_log.clear()
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
			_append_log("[right][color=#7f9db0][b]You[/b][/color][/right]
[right][color=#dfe6ee]" + _escape(content) + "[/color][/right]")
		elif role == "assistant":
			_append_log("[color=#5c6670]▏[/color] [color=#dfe6ee]" + _escape(content) + "[/color]")

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

func _on_settings_pressed() -> void:
	_refresh_settings()
	_refresh_models()
	_refresh_account()
	_refresh_memory()
	_auth_timer.start()
	_settings_dialog.popup_centered(Vector2i(620, 610))

func _on_settings_closed() -> void:
	_auth_timer.stop()

func _refresh_settings() -> void:
	_api_get(_settings_http, "/settings")

func _refresh_models() -> void:
	_api_get(_settings_http, "/models")

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

func _on_smart_pressed() -> void:
	_api_post(_settings_http, "/model", {"model": "smart"})
	_current_model = "smart"
	_status.text = "Smart - choosing the best free provider"
	for i in _models.size():
		if str(_models[i]) == "smart":
			_model_picker.select(i)
	_refresh_models()


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
			_rename_dialog.popup_centered(Vector2i(380, 150))
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

func _copy_chat_markdown() -> void:
	DisplayServer.clipboard_set(_chat_log.get_parsed_text())
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
	_chat_log.clear()
	_append_log("[b]Display cleared.[/b] Use the + tab to start a new chat.")

func _append_log(text: String) -> void:
	if _is_internal(text):
		return
	var plain: String = text.strip_edges()
	if plain in _recent_log:
		return
	_recent_log.append(plain)
	if _recent_log.size() > 80:
		_recent_log.remove_at(0)
	_chat_log.append_text(text + "\n\n")
	_chat_log.scroll_to_line(_chat_log.get_line_count())


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
	_permission_dialog.dialog_text = "%s\n\n%s\n\nApprove only if you understand this action." % [str(ticket.get("tool", "tool")), str(ticket.get("details", ""))]
	_permission_dialog.popup_centered(Vector2i(560, 380))

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
	_ecc_dialog.popup_centered(Vector2i(580, 540))
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
