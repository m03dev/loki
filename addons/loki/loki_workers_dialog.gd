@tool
extends AcceptDialog
## Background agents: see what each one is doing, start one, talk to it, stop it.
##
## Reads the bridge's /workers endpoints (see harness/workers.py). Everything shown is the
## real job state - status, the event log, the report - never a simulation. Polls only
## while the dialog is open, so a closed dialog costs nothing.

const ROLES: Array[String] = ["coder", "tester", "reviewer", "researcher"]
const STATUS_COLORS: Dictionary = {
	"queued": "#8b8b92", "working": "#6ba1ff", "done": "#a3be8c",
	"blocked": "#ebcb8b", "failed": "#bf616a", "cancelled": "#8b8b92",
}

var _base_url: String = ""
var _headers_fn: Callable
var _list: ItemList
var _detail: RichTextLabel
var _role: OptionButton
var _goal: LineEdit
var _message: LineEdit
var _summary: Label
var _list_http: HTTPRequest
var _detail_http: HTTPRequest
var _action_http: HTTPRequest
var _timer: Timer
var _jobs: Array = []
var _selected_id: String = ""


func setup(base_url: String, headers_fn: Callable) -> void:
	_base_url = base_url
	_headers_fn = headers_fn


func _init() -> void:
	title = "Background agents"
	ok_button_text = "Close"
	var box: VBoxContainer = VBoxContainer.new()
	box.custom_minimum_size = Vector2(620.0, 500.0)
	add_child(box)

	var start_row: HBoxContainer = HBoxContainer.new()
	box.add_child(start_row)
	_role = OptionButton.new()
	for role_name in ROLES:
		_role.add_item(role_name)
	_role.tooltip_text = "coder implements; tester runs and reports; reviewer and researcher only read"
	start_row.add_child(_role)
	_goal = LineEdit.new()
	_goal.placeholder_text = "Give a background agent a self-contained goal..."
	_goal.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_goal.text_submitted.connect(func(_t: String) -> void: _start_job())
	start_row.add_child(_goal)
	var start_button: Button = Button.new()
	start_button.text = "Start"
	start_button.pressed.connect(_start_job)
	start_row.add_child(start_button)

	_summary = Label.new()
	_summary.text = "Loading..."
	box.add_child(_summary)

	var split: HSplitContainer = HSplitContainer.new()
	split.size_flags_vertical = Control.SIZE_EXPAND_FILL
	box.add_child(split)
	_list = ItemList.new()
	_list.custom_minimum_size = Vector2(240.0, 0.0)
	_list.item_selected.connect(_on_selected)
	split.add_child(_list)
	_detail = RichTextLabel.new()
	_detail.bbcode_enabled = true
	_detail.scroll_following = true
	_detail.selection_enabled = true
	_detail.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	split.add_child(_detail)

	var talk_row: HBoxContainer = HBoxContainer.new()
	box.add_child(talk_row)
	_message = LineEdit.new()
	_message.placeholder_text = "Message the selected agent (it reads it before its next step)..."
	_message.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_message.text_submitted.connect(func(_t: String) -> void: _send_message())
	talk_row.add_child(_message)
	var send_button: Button = Button.new()
	send_button.text = "Send"
	send_button.pressed.connect(_send_message)
	talk_row.add_child(send_button)
	var cancel_button: Button = Button.new()
	cancel_button.text = "Stop agent"
	cancel_button.pressed.connect(_cancel_selected)
	talk_row.add_child(cancel_button)

	_list_http = _make_http(_on_list_response)
	_detail_http = _make_http(_on_detail_response)
	_action_http = _make_http(_on_action_response)
	_timer = Timer.new()
	_timer.wait_time = 2.0
	_timer.timeout.connect(_refresh)
	add_child(_timer)
	visibility_changed.connect(_on_visibility_changed)


func _make_http(handler: Callable) -> HTTPRequest:
	var node: HTTPRequest = HTTPRequest.new()
	node.timeout = 15.0
	node.request_completed.connect(handler)
	add_child(node)
	return node


func _on_visibility_changed() -> void:
	if visible:
		_refresh()
		_timer.start()
	else:
		_timer.stop()


func _headers() -> PackedStringArray:
	if _headers_fn.is_valid():
		return _headers_fn.call()
	return PackedStringArray(["Content-Type: application/json"])


func _api_get(node: HTTPRequest, path: String) -> void:
	if _base_url.is_empty() or node.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	node.request(_base_url + path, _headers())


func _api_post(path: String, payload: Dictionary) -> void:
	if _base_url.is_empty() or _action_http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		return
	_action_http.request(_base_url + path, _headers(), HTTPClient.METHOD_POST, JSON.stringify(payload))


func _refresh() -> void:
	_api_get(_list_http, "/workers")
	if not _selected_id.is_empty():
		_api_get(_detail_http, "/workers/" + _selected_id)


func _start_job() -> void:
	var goal_text: String = _goal.text.strip_edges()
	if goal_text.is_empty():
		return
	_api_post("/workers", {"goal": goal_text, "role": ROLES[_role.selected]})
	_goal.text = ""


func _send_message() -> void:
	var text: String = _message.text.strip_edges()
	if text.is_empty() or _selected_id.is_empty():
		return
	_api_post("/workers/%s/message" % _selected_id, {"text": text})
	_message.text = ""


func _cancel_selected() -> void:
	if not _selected_id.is_empty():
		_api_post("/workers/%s/cancel" % _selected_id, {})


func _on_selected(index: int) -> void:
	if index >= 0 and index < _jobs.size():
		_selected_id = str((_jobs[index] as Dictionary).get("id", ""))
		_detail.text = ""
		_api_get(_detail_http, "/workers/" + _selected_id)


func _parse(code: int, body: PackedByteArray) -> Dictionary:
	if code != 200:
		return {}
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	return parsed if parsed is Dictionary else {}


func _on_list_response(_result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	var data: Dictionary = _parse(code, body)
	if data.is_empty():
		_summary.text = "The bridge is not answering yet."
		return
	_jobs = data.get("jobs", [])
	_jobs.reverse()   # newest first
	_list.clear()
	var counts: Dictionary = {}
	for job_variant in _jobs:
		var job: Dictionary = job_variant
		var status: String = str(job.get("status", ""))
		counts[status] = int(counts.get(status, 0)) + 1
		var label: String = "%s  %s - %s" % [status, str(job.get("role", "")), str(job.get("goal", "")).left(60)]
		var row: int = _list.add_item(label)
		_list.set_item_custom_fg_color(row, Color(str(STATUS_COLORS.get(status, "#ececed"))))
		if str(job.get("id", "")) == _selected_id:
			_list.select(row)
	var parts: PackedStringArray = PackedStringArray()
	for key in counts.keys():
		parts.append("%s %d" % [str(key), int(counts[key])])
	_summary.text = ("No background agents yet." if _jobs.is_empty() else ", ".join(parts)) \
		+ "   (at most %d run at once)" % int(data.get("max_concurrent", 2))


func _on_detail_response(_result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	var data: Dictionary = _parse(code, body)
	if data.is_empty():
		return
	var lines: PackedStringArray = PackedStringArray()
	lines.append("[b]%s[/b]" % _escape(str(data.get("report", ""))))
	lines.append("")
	for event_variant in data.get("events", []):
		var item: Dictionary = event_variant
		var stamp: String = Time.get_time_string_from_unix_time(int(float(item.get("t", 0.0))))
		var who: String = str(item.get("who", ""))
		lines.append("[color=#8b8b92]%s %s%s[/color] %s" % [
			stamp, str(item.get("kind", "")), (" (" + who + ")") if not who.is_empty() else "",
			_escape(str(item.get("text", "")))])
	_detail.text = "\n".join(lines)


func _on_action_response(_result: int, _code: int, _h: PackedStringArray, _body: PackedByteArray) -> void:
	_refresh()


func _escape(value: String) -> String:
	return value.replace("[", "[lb]")
