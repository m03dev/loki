@tool
extends EditorDebuggerPlugin
## The editor's end of the line to the RUNNING game: messages "loki:*" go to and come from
## game_bridge.gd (the autoload in the game) over Godot's own debugger connection - no
## network port of our own, and only while the game runs from this editor.

var bridge: Node


func _has_capture(prefix: String) -> bool:
	return prefix == "loki"


func _capture(message: String, data: Array, session_id: int) -> bool:
	if bridge != null:
		bridge.on_game_message(message.trim_prefix("loki:"), data)
	return true


func send(message: String, data: Array) -> bool:
	for session in get_sessions():
		if session != null and session.is_active():
			session.send_message("loki:" + message, data)
			return true
	return false


func game_running() -> bool:
	for session in get_sessions():
		if session != null and session.is_active():
			return true
	return false
