@tool
extends VBoxContainer

const BRIDGE_URL: String = "http://127.0.0.1:8766"
const BRIDGE_LAUNCHER: String = "res://addons/loki/run_bridge.bat"
const DEFAULT_MODEL: String = "qwen3.5:9b"
const SETTINGS_DIALOG_SCRIPT: Script = preload("res://addons/loki/loki_settings.gd")

var _chat_log: RichTextLabel
var _input_edit: TextEdit
var _send_button: Button
var _status: Label
var _chat_http: HTTPRequest
var _approval_http: HTTPRequest
var _poll_timer: Timer
var _permission_dialog: ConfirmationDialog
var _token: String = ""
var _approval_id: String = ""
var _busy: bool = false
var _bridge_ready: bool = false
var _profile_apply_requested: bool = false
var _profile_request_pending: bool = false
var _settings_dialog: ConfirmationDialog
var _model_picker: OptionButton
var _models: Array = []
var _settings_http: HTTPRequest
var _auth_http: HTTPRequest
var _auth_timer: Timer
var _progress_http: HTTPRequest
var _progress_timer: Timer
var _progress_cursor: int = 0
var _active_chat_id: String = ""
var _task_mode: bool = false
var _relaunch_ticks: int = 0
var _stop_button: Button
var _elapsed_label: Label
var _started_ms: int = 0
var _cancel_http: HTTPRequest
var _last_op_id: int = 0

func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_build_ui()
	_chat_http = HTTPRequest.new()
	_chat_http.timeout = 0.0
	_chat_http.request_completed.connect(_on_chat_response)
	add_child(_chat_http)
	_approval_http = HTTPRequest.new()
	_approval_http.timeout = 3.0
	_approval_http.request_completed.connect(_on_approval_poll)
	add_child(_approval_http)
	_poll_timer = Timer.new()
	_poll_timer.wait_time = 0.5
	_poll_timer.timeout.connect(_poll_approval)
	_poll_timer.timeout.connect(_poll_editor_ops)
	add_child(_poll_timer)
	_profile_apply_requested = FileAccess.file_exists("user://loki_profile.cfg")
	_progress_http = HTTPRequest.new()
	_progress_http.timeout = 3.0
	_progress_http.request_completed.connect(_on_progress_response)
	add_child(_progress_http)
	_progress_timer = Timer.new()
	_progress_timer.wait_time = 0.4
	_progress_timer.timeout.connect(_poll_progress)
	add_child(_progress_timer)
	_cancel_http = HTTPRequest.new()
	_cancel_http.timeout = 5.0
	_cancel_http.request_completed.connect(_on_cancel_response)
	add_child(_cancel_http)
	_start_bridge()

func _build_ui() -> void:
	custom_minimum_size = Vector2(350.0, 300.0)
	var sidebar_content: VBoxContainer = self
	var header: HBoxContainer = HBoxContainer.new()
	sidebar_content.add_child(header)
	var heading: Label = Label.new()
	heading.text = "Loki"
	heading.add_theme_font_size_override("font_size", 15)
	heading.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(heading)
	_model_picker = OptionButton.new()
	_model_picker.tooltip_text = "Model / provider"
	_model_picker.item_selected.connect(_on_model_selected)
	header.add_child(_model_picker)
	var menu: MenuButton = MenuButton.new()
	menu.text = "⋮"
	menu.flat = true
	menu.tooltip_text = "More"
	var popup: PopupMenu = menu.get_popup()
	popup.add_item("Settings", 1)
	popup.add_item("New chat", 2)
	popup.add_item("Copy chat as Markdown", 3)
	popup.add_separator()
	popup.add_item("Inspect current scene", 10)
	popup.add_item("Validate project", 11)
	popup.add_item("Run task (no limit)", 12)
	popup.id_pressed.connect(_on_menu_pressed)
	header.add_child(menu)
	_settings_dialog = SETTINGS_DIALOG_SCRIPT.new() as ConfirmationDialog
	_settings_dialog.profile_saved.connect(_on_profile_saved)
	_settings_dialog.category_toggled.connect(_on_category_toggled)
	_settings_dialog.sign_in_requested.connect(_on_sign_in)
	_settings_dialog.sign_out_requested.connect(_on_sign_out)
	_settings_dialog.confirmed.connect(_on_settings_closed)
	_settings_dialog.canceled.connect(_on_settings_closed)
	add_child(_settings_dialog)
	_settings_http = HTTPRequest.new()
	_settings_http.timeout = 10.0
	_settings_http.request_completed.connect(_on_settings_response)
	add_child(_settings_http)
	_auth_http = HTTPRequest.new()
	_auth_http.timeout = 10.0
	_auth_http.request_completed.connect(_on_auth_response)
	add_child(_auth_http)
	_auth_timer = Timer.new()
	_auth_timer.wait_time = 2.0
	_auth_timer.timeout.connect(_refresh_account)
	add_child(_auth_timer)
	_chat_log = RichTextLabel.new()
	_chat_log.bbcode_enabled = true
	_chat_log.selection_enabled = true
	_chat_log.scroll_following = true
	_chat_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_chat_log.custom_minimum_size = Vector2(350.0, 180.0)
	sidebar_content.add_child(_chat_log)
	_append_log("[b]Loki Python harness[/b] — tool approval prompts are enabled.")
	_input_edit = TextEdit.new()
	_input_edit.custom_minimum_size = Vector2(350.0, 100.0)
	_input_edit.placeholder_text = "Describe a task; Loki works until done (Ctrl+Enter)"
	_input_edit.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	_input_edit.gui_input.connect(_on_input_gui)
	sidebar_content.add_child(_input_edit)
	var bottom: HBoxContainer = HBoxContainer.new()
	sidebar_content.add_child(bottom)
	_send_button = Button.new()
	_send_button.text = "Send"
	_send_button.pressed.connect(_on_send_pressed)
	bottom.add_child(_send_button)
	var clear: Button = Button.new()
	clear.text = "Clear"
	clear.pressed.connect(_on_clear_pressed)
	bottom.add_child(clear)
	_stop_button = Button.new()
	_stop_button.text = "Stop"
	_stop_button.disabled = true
	_stop_button.pressed.connect(_on_stop_pressed)
	bottom.add_child(_stop_button)
	_status = Label.new()
	_status.text = "Starting bridge..."
	_status.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	bottom.add_child(_status)
	_elapsed_label = Label.new()
	_elapsed_label.text = ""
	bottom.add_child(_elapsed_label)
	_permission_dialog = ConfirmationDialog.new()
	_permission_dialog.title = "Approve Loki tool call?"
	_permission_dialog.ok_button_text = "Approve"
	_permission_dialog.cancel_button_text = "Deny"
	_permission_dialog.confirmed.connect(_submit_approval.bind(true))
	_permission_dialog.canceled.connect(_submit_approval.bind(false))
	add_child(_permission_dialog)

func _project_dir() -> String:
	return ProjectSettings.globalize_path("res://").trim_suffix("/")

func _token_path() -> String:
	return _project_dir().path_join(".godot/loki_bridge.token")

func _load_token() -> void:
	if FileAccess.file_exists(_token_path()):
		_token = FileAccess.get_file_as_string(_token_path()).strip_edges()
	else:
		_token = ""

func _start_bridge() -> void:
	_load_token()
	if not _token.is_empty():
		_status.text = "Checking bridge..."
		_poll_timer.start()
		return
	_relaunch_ticks = 20
	var launcher: String = ProjectSettings.globalize_path(BRIDGE_LAUNCHER)
	var pid: int = OS.create_process("cmd.exe", PackedStringArray(["/c", "start", "\"Loki Bridge\"", "/min", launcher]), false)
	if pid <= 0:
		_status.text = "Bridge launch failed"
		_append_log("[color=#ff7777]Could not start the bridge. Run addons/loki/run_bridge.bat manually.[/color]")
		return
	_status.text = "Starting Loki bridge..."
	_poll_timer.start()

func _headers() -> PackedStringArray:
	return PackedStringArray(["Content-Type: application/json", "Authorization: Bearer " + _token])

func _on_input_gui(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.keycode == KEY_ENTER and event.ctrl_pressed:
		_on_send_pressed()
		_input_edit.accept_event()

func _on_send_pressed() -> void:
	if _busy:
		return
	_load_token()
	if _token.is_empty():
		_status.text = "Bridge unavailable"
		return
	var prompt: String = _input_edit.text.strip_edges()
	if prompt.is_empty():
		return
	_input_edit.clear()
	_append_log("[color=#88c0d0][b]You:[/b][/color] " + _escape(prompt))
	_busy = true
	_task_mode = true
	_active_chat_id = ""
	_progress_cursor = 0
	_send_button.disabled = true
	_stop_button.disabled = false
	_started_ms = Time.get_ticks_msec()
	_elapsed_label.text = ""
	_status.text = "Loki is thinking..."
	_append_log("[color=#b48ead]Working (autonomous, until done)[/color]")
	_progress_timer.start()
	var err: Error = _chat_http.request(BRIDGE_URL + "/task", _headers(), HTTPClient.METHOD_POST, JSON.stringify({"task": prompt, "steps": 0}))
	if err != OK:
		_busy = false
		_send_button.disabled = false
		_stop_button.disabled = true
		_elapsed_label.text = ""
		_status.text = "Request failed"
		_progress_timer.stop()
		_append_log("[color=#ff7777]Bridge request error: %s[/color]" % error_string(err))

func _on_chat_response(result: int, code: int, _received_headers: PackedStringArray, body: PackedByteArray) -> void:
	var was_task: bool = _task_mode
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
		_append_log("[color=#ff7777]Bridge returned HTTP %d with invalid JSON: %s[/color]" % [code, _escape(body.get_string_from_utf8())])
		return
	var response: Dictionary = parsed
	if was_task:
		if not bool(response.get("ok", false)):
			_status.text = "Task error"
			_append_log("[color=#ff7777]%s[/color]" % _escape(str(response.get("error", "Unknown task error"))))
		else:
			_status.text = "Task complete"
			_append_log("[color=#d8dee9][b]Task:[/b][/color] " + _escape(str(response.get("response", "Task complete."))))
		return
	if not bool(response.get("ok", false)):
		_status.text = "Loki error"
		_append_log("[color=#ff7777]%s[/color]" % _escape(str(response.get("error", "Unknown bridge error"))))
		return
	var _answer: String = str(response.get("response", "")).strip_edges()
	if _answer.is_empty():
		_answer = "(no message returned - see the progress log above)"
	_append_log("[color=#d8dee9][b]Loki:[/b][/color] " + _escape(_answer))
	_status.text = "Connected • " + DEFAULT_MODEL

func _poll_progress() -> void:
	if not _busy or _token.is_empty():
		return
	var secs: int = int((Time.get_ticks_msec() - _started_ms) / 1000.0)
	_elapsed_label.text = "%ds" % secs
	if _progress_http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	var err: Error = _progress_http.request(BRIDGE_URL + "/progress?after=" + str(_progress_cursor), _headers())
	if err != OK:
		_append_log("[color=#ff7777]Could not poll Loki progress: %s[/color]" % error_string(err))

func _on_progress_response(result: int, code: int, _headers_received: PackedStringArray, body: PackedByteArray) -> void:
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
			_append_log("[color=#b48ead]Thinking: [/color]" + text)
		elif kind == "tool":
			_status.text = "Using a tool..."
			_append_log("[color=#81a1c1]Using tool: [/color]" + text)
		elif kind == "tool_result":
			_append_log("[color=#a3be8c]Tool result: [/color]" + text)
		elif kind == "approval":
			_status.text = "Waiting for approval..."
			_append_log("[color=#ebcb8b]Permission: [/color]" + text)
		elif kind == "task":
			_status.text = "Running task..."
			_append_log("[color=#b48ead][b]Task:[/b][/color] " + text)
		elif kind == "assistant":
			_append_log("[color=#d8dee9][b]Loki:[/b][/color] " + text)
		elif kind == "done":
			_append_log("[color=#a3be8c]Done: [/color]" + text)
		elif kind == "error":
			_append_log("[color=#ff7777]Error: [/color]" + text)
	# Advance only through events actually consumed, otherwise a chat_id race can skip them.

func _poll_approval() -> void:
	_load_token()
	if _approval_http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	if _token.is_empty():
		if _relaunch_ticks > 0:
			_relaunch_ticks -= 1
		else:
			_start_bridge()
		return
	var route: String = "/approval" if _bridge_ready else "/health"
	var err: Error = _approval_http.request(BRIDGE_URL + route, _headers())
	if err != OK:
		_status.text = "Bridge unavailable"

func _on_approval_poll(result: int, code: int, _received_headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		_bridge_ready = false
		_status.text = "Waiting for bridge..."
		if code == 401:
			_token = ""
			_relaunch_ticks = 0
			DirAccess.remove_absolute(_token_path())
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		return
	_bridge_ready = true
	_status.text = "Connected • " + DEFAULT_MODEL
	if _profile_apply_requested:
		_apply_saved_profile()
	if not _approval_id.is_empty():
		return
	var ticket_value: Variant = parsed.get("approval")
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
	request.request_completed.connect(_on_approval_submitted.bind(request, approved))
	var payload: Dictionary = {"id": _approval_id, "approved": approved}
	var err: Error = request.request(BRIDGE_URL + "/approval", _headers(), HTTPClient.METHOD_POST, JSON.stringify(payload))
	if err != OK:
		request.queue_free()
	if not approved:
		_append_log("[color=#ebcb8b]Tool approval denied.[/color]")

func _on_approval_submitted(_result: int, _code: int, _received_headers: PackedStringArray, _body: PackedByteArray, request: HTTPRequest, approved: bool) -> void:
	request.queue_free()
	if approved:
		_append_log("[color=#a3be8c]Tool approval granted.[/color]")
	_approval_id = ""

func _refresh_models() -> void:
	_load_token()
	if _token.is_empty():
		return
	_settings_http.request(BRIDGE_URL + "/models", _headers())


func _on_model_selected(index: int) -> void:
	if index < 0 or index >= _models.size():
		return
	_load_token()
	if _token.is_empty():
		return
	_settings_http.request(BRIDGE_URL + "/model", _headers(), HTTPClient.METHOD_POST, JSON.stringify({"model": _models[index]}))


func _on_menu_pressed(id: int) -> void:
	match id:
		1:
			_on_settings_pressed()
		2:
			_on_new_chat()
		3:
			_copy_chat_markdown()
		10:
			_on_quick_action_selected(1)
		11:
			_on_quick_action_selected(2)
		12:
			_on_quick_action_selected(3)


func _copy_chat_markdown() -> void:
	DisplayServer.clipboard_set(_chat_log.get_parsed_text())
	_append_log("[color=#a3be8c]Chat copied to clipboard as text.[/color]")


func _on_settings_pressed() -> void:
	_refresh_settings()
	_refresh_models()
	_refresh_account()
	_auth_timer.start()
	_settings_dialog.popup_centered(Vector2i(520, 440))


func _on_settings_closed() -> void:
	_auth_timer.stop()


func _refresh_settings() -> void:
	_load_token()
	if _token.is_empty():
		return
	_settings_http.request(BRIDGE_URL + "/settings", _headers())


func _refresh_account() -> void:
	_load_token()
	if _token.is_empty():
		return
	if _auth_http.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED:
		_auth_http.request(BRIDGE_URL + "/auth/status", _headers())


func _on_settings_response(_result: int, code: int, _headers_in: PackedStringArray, body: PackedByteArray) -> void:
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
			for i in _models.size():
				_model_picker.add_item(str(_models[i]))
				if str(_models[i]) == current:
					_model_picker.select(i)
		return
	if _settings_dialog.has_method("set_categories"):
		_settings_dialog.set_categories(payload)


func _on_auth_response(result: int, code: int, _headers_in: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		return
	var payload: Dictionary = parsed
	if payload.has("signed_in") and _settings_dialog.has_method("set_account"):
		var user: Dictionary = payload.get("user", {})
		_settings_dialog.set_account(str(user.get("email", "")), str(user.get("name", "")), bool(payload.get("signed_in", false)))


func _on_category_toggled(category: String, enabled: bool) -> void:
	_load_token()
	if _token.is_empty():
		return
	_settings_http.request(BRIDGE_URL + "/settings", _headers(), HTTPClient.METHOD_POST, JSON.stringify({"category": category, "enabled": enabled}))


func _on_sign_in() -> void:
	_load_token()
	if _token.is_empty():
		return
	_settings_dialog.set_status("Opening your browser to sign in with Google...")
	_auth_http.request(BRIDGE_URL + "/auth/start", _headers(), HTTPClient.METHOD_POST, "{}")


func _on_sign_out() -> void:
	_load_token()
	if _token.is_empty():
		return
	_settings_dialog.set_status("Signing out...")
	_auth_http.request(BRIDGE_URL + "/auth/signout", _headers(), HTTPClient.METHOD_POST, "{}")

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
	request.timeout = 5.0
	add_child(request)
	request.request_completed.connect(_on_profile_updated.bind(request))
	var payload: Dictionary = {"profile_path": profile_path}
	var err: Error = request.request(BRIDGE_URL + "/profile", _headers(), HTTPClient.METHOD_POST, JSON.stringify(payload))
	if err != OK:
		_profile_request_pending = false
		request.queue_free()
		_profile_apply_requested = true
		_append_log("[color=#ff7777]Could not apply profile: %s[/color]" % error_string(err))

func _on_profile_updated(_result: int, code: int, _headers: PackedStringArray, body: PackedByteArray, request: HTTPRequest) -> void:
	_profile_request_pending = false
	request.queue_free()
	if code != 200:
		_profile_apply_requested = true
		_append_log("[color=#ff7777]Profile update failed (HTTP %d): %s[/color]" % [code, _escape(body.get_string_from_utf8())])
	else:
		_profile_apply_requested = false
		_append_log("[color=#a3be8c]Profile saved and applied to the next Loki turn.[/color]")

func _on_quick_action_selected(index: int) -> void:
	if index == 3:
		_submit_multistep_task()
		return
	if index == 1:
		_input_edit.text = "Inspect the currently open Godot scene and report its node tree and configuration warnings. Do not modify files."
	elif index == 2:
		_input_edit.text = "Validate this Godot project with a headless editor check and report warnings/errors. Do not modify files."
	else:
		return
	_on_send_pressed()

func _submit_multistep_task() -> void:
	if _busy:
		return
	_load_token()
	if _token.is_empty():
		_status.text = "Bridge unavailable"
		_append_log("[color=#ff7777]Cannot start task: bridge token is missing.[/color]")
		return
	var prompt: String = _input_edit.text.strip_edges()
	if prompt.is_empty():
		prompt = "Inspect the clean Godot project read-only. Use multiple short steps: first inspect the project tree, then inspect the active scene, then run a headless Godot validation and summarize results. Do not modify files."
	_input_edit.clear()
	_append_log("[color=#88c0d0][b]Multi-step task:[/b][/color] " + _escape(prompt))
	_busy = true
	_task_mode = true
	_active_chat_id = ""
	_progress_cursor = 0
	_send_button.disabled = true
	_stop_button.disabled = false
	_started_ms = Time.get_ticks_msec()
	_elapsed_label.text = ""
	_status.text = "Running multi-step task..."
	_progress_timer.start()
	var payload: Dictionary = {"task": prompt, "steps": 0}
	var err: Error = _chat_http.request(BRIDGE_URL + "/task", _headers(), HTTPClient.METHOD_POST, JSON.stringify(payload))
	if err != OK:
		_busy = false
		_send_button.disabled = false
		_progress_timer.stop()
		_status.text = "Task request failed"
		_append_log("[color=#ff7777]Task request error: %s[/color]" % error_string(err))

func _on_new_chat() -> void:
	_chat_log.clear()
	_append_log("[b]New Loki chat context requested.[/b]")
	_load_token()
	if _token.is_empty():
		return
	var request: HTTPRequest = HTTPRequest.new()
	request.timeout = 20.0
	add_child(request)
	request.request_completed.connect(_on_reset_response.bind(request))
	request.request(BRIDGE_URL + "/reset", _headers(), HTTPClient.METHOD_POST, "{}")

func _on_reset_response(_result: int, code: int, _received_headers: PackedStringArray, _body: PackedByteArray, request: HTTPRequest) -> void:
	if code != 200:
		_append_log("[color=#ff7777]Could not reset Loki context (HTTP %d).[/color]" % code)
	request.queue_free()

func _on_clear_pressed() -> void:
	_chat_log.clear()
	_append_log("[b]Display cleared. Context remains until New chat.[/b]")

func _append_log(text: String) -> void:
	_chat_log.append_text(text + "\n\n")
	_chat_log.scroll_to_line(_chat_log.get_line_count())

func _escape(value: String) -> String:
	return value.replace("[", "[lb]").replace("]", "[rb]")

func _on_stop_pressed() -> void:
	if not _busy or _token.is_empty():
		return
	_status.text = "Stopping..."
	_stop_button.disabled = true
	var err: Error = _cancel_http.request(BRIDGE_URL + "/cancel", _headers(), HTTPClient.METHOD_POST, "{}")
	if err != OK:
		_append_log("[color=#ff7777]Could not send stop request: %s[/color]" % error_string(err))

func _on_cancel_response(_result: int, _code: int, _headers: PackedStringArray, _body: PackedByteArray) -> void:
	_append_log("[color=#ffb86c]Stop requested - waiting for Loki to stop.[/color]")
	_status.text = "Stopping..."

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
	for line in text.split("
"):
		var trimmed: String = line.strip_edges()
		if trimmed.is_empty():
			continue
		var parsed: Variant = JSON.parse_string(trimmed)
		if not (parsed is Dictionary):
			continue
		var op_id: int = int(parsed.get("id", 0))
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
