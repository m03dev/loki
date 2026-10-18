@tool
extends Node
## LOKI Studio's loopback API, from the editor: JSON over HTTP with Studio's bearer token.
##
## Studio writes its address and token to the connect file when it starts
## (~/.loki/studio_connect.json; LOKI_STUDIO_CONNECT or the editor setting
## loki_studio/connect_file override it). A refused connection or a 401 means Studio
## restarted (new port or token): the file is read again on the next request.

signal connection_changed(ok: bool)

var base_url := ""
var token := ""
var connected := false
var last_error := ""
## which hub this link talks to: "studio" (LOKI Studio, its own app) or "engine" (LOKI's engine - every LOKI agent,
## engine/godot_live.py). Both use the same routes; only the connect file differs.
var target := "studio"


func my_connect_file() -> String:
	if target == "engine":
		var env := OS.get_environment("LOKI_ENGINE_CONNECT")
		if env != "":
			return env
		var home := OS.get_environment("USERPROFILE") if OS.get_name() == "Windows" else OS.get_environment("HOME")
		return home.path_join(".loki").path_join("engine_connect.json")
	return connect_file_path()


static func connect_file_path() -> String:
	var env := OS.get_environment("LOKI_STUDIO_CONNECT")
	if env != "":
		return env
	if Engine.is_editor_hint():
		var es := EditorInterface.get_editor_settings()
		if es != null and es.has_setting("loki_studio/connect_file"):
			var custom := str(es.get_setting("loki_studio/connect_file"))
			if custom != "":
				return custom
	var home := OS.get_environment("USERPROFILE") if OS.get_name() == "Windows" else OS.get_environment("HOME")
	return home.path_join(".loki").path_join("studio_connect.json")


func load_connection() -> bool:
	var path := my_connect_file()
	if not FileAccess.file_exists(path):
		last_error = ("LOKI is not running (no %s). Start LOKI." % path) if target == "engine" else \
			("LOKI Studio is not running (no %s). Start LOKI Studio (Loki Studio.cmd / LOKI Studio.app)." % path)
		_set_connected(false)
		return false
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		last_error = "cannot read %s" % path
		return false
	var data: Variant = JSON.parse_string(f.get_as_text())
	f.close()
	if typeof(data) != TYPE_DICTIONARY:
		last_error = "%s is not valid" % path
		return false
	base_url = str(data.get("url", "")).rstrip("/")
	token = str(data.get("token", ""))
	return base_url != "" and token != ""


func studio_url() -> String:
	if base_url == "":
		load_connection()
	return "%s/#token=%s" % [base_url, token] if base_url != "" else ""


func _set_connected(ok: bool) -> void:
	if ok != connected:
		connected = ok
		connection_changed.emit(ok)


## {"ok": ..., ...} from Studio; {"ok": false, "error", "offline": true} when it cannot be reached.
func request(method: int, path: String, body: Variant = null, timeout: float = 30.0) -> Dictionary:
	if base_url == "" and not load_connection():
		return {"ok": false, "error": last_error, "offline": true}
	var http := HTTPRequest.new()
	http.timeout = timeout
	add_child(http)
	var headers := PackedStringArray(["Authorization: Bearer " + token, "Content-Type: application/json"])
	var payload := "" if body == null else JSON.stringify(body)
	var err := http.request(base_url + path, headers, method, payload)
	if err != OK:
		http.queue_free()
		base_url = ""
		_set_connected(false)
		return {"ok": false, "error": "could not send the request (%s)" % error_string(err), "offline": true}
	var res: Array = await http.request_completed
	http.queue_free()
	var result: int = res[0]
	var code: int = res[1]
	var raw: PackedByteArray = res[3]
	if result != HTTPRequest.RESULT_SUCCESS:
		base_url = ""
		_set_connected(false)
		last_error = "LOKI Studio does not answer (start it: Loki Studio.cmd / LOKI Studio.app)"
		return {"ok": false, "error": last_error, "offline": true}
	var parsed: Variant = JSON.parse_string(raw.get_string_from_utf8())
	var out: Dictionary = parsed if typeof(parsed) == TYPE_DICTIONARY else {"ok": false, "error": "HTTP %d" % code}
	out["http_code"] = code
	if code == 401:
		base_url = ""
		_set_connected(false)
		return out
	_set_connected(true)
	return out


func get_json(path: String, timeout: float = 30.0) -> Dictionary:
	return await request(HTTPClient.METHOD_GET, path, null, timeout)


func post_json(path: String, body: Dictionary, timeout: float = 30.0) -> Dictionary:
	return await request(HTTPClient.METHOD_POST, path, body, timeout)
