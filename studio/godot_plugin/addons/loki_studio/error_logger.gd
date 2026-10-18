extends Logger
## Catches Godot's errors and warnings (script errors, failed loads, push_error/push_warning)
## so LOKI Studio's agent sees what the Output and Debugger panels show. Loaded only when the
## Godot build has the Logger class (4.5+). Called from any thread: everything goes through a
## Mutex, and nothing here prints (that would call this logger again).

const TYPES := ["error", "warning", "script", "shader"]

var source := "editor"
var keep_messages := false
var _mutex := Mutex.new()
var _rows: Array = []
var _seq := 0                 # rows are numbered so several links (Studio, LOKI's engine) each read every error
var _lines: Array = []


func _log_error(function: String, file: String, line: int, code: String, rationale: String, editor_notify: bool,
		error_type: int, script_backtraces: Array[ScriptBacktrace]) -> void:
	var text := rationale if rationale != "" else code
	var row := {"source": source, "type": TYPES[clampi(error_type, 0, 3)], "text": text.substr(0, 600),
		"file": file, "line": line, "function": function}
	if not script_backtraces.is_empty():
		row["backtrace"] = str(script_backtraces[0]).substr(0, 800)
	_mutex.lock()
	_seq += 1
	row["n"] = _seq
	_rows.append(row)
	if _rows.size() > 500:
		_rows = _rows.slice(_rows.size() - 500)
	_mutex.unlock()


func _log_message(message: String, error: bool) -> void:
	if not keep_messages:
		return
	_mutex.lock()
	_lines.append(message.strip_edges().substr(0, 400))
	if _lines.size() > 400:
		_lines = _lines.slice(_lines.size() - 400)
	_mutex.unlock()


## The errors after `cursor` (a row's "n"); each link keeps its own cursor.
func errors_since(cursor: int) -> Array:
	_mutex.lock()
	var out: Array = []
	for row in _rows:
		if int(row.get("n", 0)) > cursor:
			out.append(row)
	_mutex.unlock()
	return out


func take_errors() -> Array:
	_mutex.lock()
	var out := _rows
	_rows = []
	_mutex.unlock()
	return out


func recent_lines(count: int = 120) -> Array:
	_mutex.lock()
	var out := _lines.slice(maxi(0, _lines.size() - count))
	_mutex.unlock()
	return out
