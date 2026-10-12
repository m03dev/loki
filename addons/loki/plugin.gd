@tool
extends EditorPlugin

const MCP_DIR: String = "res://addons/loki/godot_mcp/"
const MCP_DEFAULT_URL: String = "ws://127.0.0.1:9080"

# The Godot MCP bridge is vendored inside this addon (MIT, see
# godot_mcp/LICENSE.godot-mcp.txt) instead of installed as its own plugin, so a
# project only ever needs addons/loki - nothing else.
var _main_screen_panel: Control
var _mcp_bridge: Node
var _mcp_debugger: EditorDebuggerPlugin


func _enter_tree() -> void:
	# The Loki button in the viewport. The chat dock is where real work happens, so this
	# screen is a small welcome that can open the dock or its settings - not a dead end.
	# NOTE: this tab and the chat dock must not share a layout key; the dock sets its own
	# (see addons/loki/chat/plugin.gd), which is what keeps the two apart in the layout.
	_build_main_screen()
	_start_mcp_bridge()
	# Chat is provided by the independent addons/loki/chat dock plugin.


func _build_main_screen() -> void:
	_main_screen_panel = CenterContainer.new()
	_main_screen_panel.name = "LokiMainScreen"
	var box: VBoxContainer = VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	var title: Label = Label.new()
	title.text = "Loki"
	title.add_theme_font_size_override("font_size", 34)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	box.add_child(title)
	var sub: Label = Label.new()
	sub.text = "Your Godot agent. Ask, plan, then let it build."
	sub.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	sub.modulate = Color(0.75, 0.78, 0.82)
	box.add_child(sub)
	var row: HBoxContainer = HBoxContainer.new()
	row.alignment = BoxContainer.ALIGNMENT_CENTER
	var open: Button = Button.new()
	open.text = "Open chat"
	open.tooltip_text = "Show the Loki chat dock"
	open.pressed.connect(_open_chat_dock)
	row.add_child(open)
	var settings: Button = Button.new()
	settings.text = "Settings"
	settings.tooltip_text = "Models, memory, account and tools"
	settings.pressed.connect(_open_chat_settings)
	row.add_child(settings)
	box.add_child(row)
	_main_screen_panel.add_child(box)
	EditorInterface.get_editor_main_screen().add_child(_main_screen_panel)
	_make_visible(false)


func _open_chat_dock() -> void:
	# The dock lives in its own plugin; reach it through a group so the two stay
	# independent (either can be enabled without the other).
	for node: Node in get_tree().get_nodes_in_group("loki_chat_dock"):
		if node is EditorDock:
			(node as EditorDock).make_visible()
			return


func _open_chat_settings() -> void:
	_open_chat_dock()
	for node: Node in get_tree().get_nodes_in_group("loki_chat_panel"):
		if node.has_method("open_settings"):
			node.call("open_settings")
			return


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
	if _main_screen_panel != null:
		_main_screen_panel.queue_free()
		_main_screen_panel = null


func _has_main_screen() -> bool:
	return true


func _make_visible(visible: bool) -> void:
	if _main_screen_panel != null:
		_main_screen_panel.visible = visible


func _get_plugin_name() -> String:
	return "Loki"


func _get_plugin_icon() -> Texture2D:
	var theme: Theme = EditorInterface.get_editor_theme()
	if theme != null and theme.has_icon("Node", "EditorIcons"):
		return theme.get_icon("Node", "EditorIcons")
	return null
