@tool
extends EditorPlugin

const MCP_DIR: String = "res://addons/loki/godot_mcp/"
const MCP_DEFAULT_URL: String = "ws://127.0.0.1:9080"

# The Godot MCP bridge is vendored inside this addon (MIT, see
# godot_mcp/LICENSE.godot-mcp.txt) instead of installed as its own plugin, so a
# project only ever needs addons/loki - nothing else.
var _mcp_bridge: Node
var _mcp_debugger: EditorDebuggerPlugin


func _enter_tree() -> void:
	# No main-screen tab. Loki's whole UI is the chat dock, and a second thing named
	# "Loki" here stole the dock's layout key, which is why a duplicate Loki tab and a
	# misplaced chat panel appeared. This plugin now only hosts the bundled MCP bridge.
	_start_mcp_bridge()
	# Chat is provided by the independent addons/loki/chat dock plugin.


func _start_mcp_bridge() -> void:
	# The Godot MCP bridge is vendored inside this addon (MIT, see
	# godot_mcp/LICENSE.godot-mcp.txt) rather than installed as its own plugin,
	# so a project only ever needs addons/loki - nothing else to enable.
	var bridge_script: Script = load(MCP_DIR + "mcp_bridge.gd") as Script
	var router_script: Script = load(MCP_DIR + "command_router.gd") as Script
	if bridge_script == null or router_script == null:
		push_warning("Loki: the bundled Godot MCP bridge is missing - live-editor tools are off.")
		return
	var router: Object = router_script.new()
	var debugger_script: Script = load(MCP_DIR + "mcp_debugger.gd") as Script
	if debugger_script != null:
		_mcp_debugger = debugger_script.new() as EditorDebuggerPlugin
		add_debugger_plugin(_mcp_debugger)
		if router.has_method("set_debugger"):
			router.set_debugger(_mcp_debugger)
	_mcp_bridge = bridge_script.new(router) as Node
	if _mcp_bridge == null:
		push_warning("Loki: could not create the MCP bridge node.")
		return
	add_child(_mcp_bridge)
	var url: String = OS.get_environment("GODOT_MCP_BRIDGE_URL")
	if url.is_empty():
		url = MCP_DEFAULT_URL
	_mcp_bridge.start(url)


func _stop_mcp_bridge() -> void:
	if _mcp_bridge != null:
		if _mcp_bridge.has_method("dispose"):
			_mcp_bridge.dispose()
		_mcp_bridge.queue_free()
		_mcp_bridge = null
	if _mcp_debugger != null:
		remove_debugger_plugin(_mcp_debugger)
		_mcp_debugger = null



func _exit_tree() -> void:
	_stop_mcp_bridge()


func _has_main_screen() -> bool:
	# Hidden: an extra "Loki" tab here clashed with the chat dock's layout key.
	return false
