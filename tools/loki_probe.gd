extends SceneTree

var _dock: Control
var _t: float = 0.0
var _phase: int = 0

func _initialize() -> void:
	var script: Script = load("res://addons/loki/loki_dock.gd")
	_dock = script.new() as Control
	root.add_child(_dock)

func _process(delta: float) -> bool:
	_t += delta
	if _phase == 0 and _t > 1.5:
		var sb: Button = _dock.get("_stop_button") as Button
		var el: Label = _dock.get("_elapsed_label") as Label
		var ch: HTTPRequest = _dock.get("_cancel_http") as HTTPRequest
		print("CONTROLS stop=", sb != null, " stop_text=", (sb.text if sb else ""),
			" elapsed=", el != null, " cancel=", ch != null,
			" timeout=", (_dock.get("_chat_http") as HTTPRequest).timeout)
		_phase = 1; quit()
	return false
