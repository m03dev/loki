@tool
extends EditorDebuggerPlugin
## The editor's end of the line to the RUNNING game: messages "loki:*" go to and come from
## game_bridge.gd (the autoload in the game) over Godot's own debugger connection - no
## network port of our own, and only while the game runs from this editor.

var bridge: Node
var bridges: Array = []     # every link (Studio, LOKI's engine): each takes the replies to its own requests


func _has_capture(prefix: String) -> bool:
	return prefix == "loki"


func _capture(message: String, data: Array, session_id: int) -> bool:
	var all := bridges if not bridges.is_empty() else ([bridge] if bridge != null else [])
	for b in all:
		if b != null and is_instance_valid(b):
			b.on_game_message(message.trim_prefix("loki:"), data)
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
