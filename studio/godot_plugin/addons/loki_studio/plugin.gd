@tool
extends EditorPlugin
## LOKI Studio inside the Godot editor (docs/STUDIO.md, "The Godot plugin").
##
## A second front end for LOKI Studio, which keeps running as its own app: this plugin adds
## the LOKI Studio dock (the chat), the editor bridge (Studio's agent sees and changes the live
## editor through it), a debugger plugin + a game autoload (the agent plays the running game,
## takes screenshots, reads its errors and performance) and right-click "Add to LOKI Studio
## chat" entries. It works in ANY Godot 4 project: copy addons/loki_studio into it
## (python studio/install_godot_plugin.py <project>) and enable it in Project Settings > Plugins.

const ApiScript := preload("res://addons/loki_studio/api.gd")
const BridgeScript := preload("res://addons/loki_studio/bridge.gd")
const DockScript := preload("res://addons/loki_studio/dock.gd")
const DebuggerScript := preload("res://addons/loki_studio/debugger.gd")
const GAME_AUTOLOAD := "LokiStudioGame"
const GAME_SCRIPT := "res://addons/loki_studio/game_bridge.gd"

var api: Node
var bridge: Node
var engine_api: Node          # the second link: LOKI's engine (every LOKI agent; engine/godot_live.py)
var engine_bridge: Node
var dock: Control
var dock_holder: Control
var debugger: EditorDebuggerPlugin
var logger: Object
var context_menus: Array = []


func _enter_tree() -> void:
	api = ApiScript.new()
	api.name = "LokiStudioApi"
	add_child(api)
	bridge = BridgeScript.new()
	bridge.name = "LokiStudioBridge"
	bridge.plugin = self
	bridge.api = api
	add_child(bridge)
	engine_api = ApiScript.new()
	engine_api.name = "LokiEngineApi"
	engine_api.target = "engine"
	add_child(engine_api)
	engine_bridge = BridgeScript.new()
	engine_bridge.name = "LokiEngineBridge"
	engine_bridge.plugin = self
	engine_bridge.api = engine_api
	add_child(engine_bridge)
	debugger = DebuggerScript.new()
	debugger.bridge = bridge
	debugger.bridges = [bridge, engine_bridge]
	add_debugger_plugin(debugger)
	bridge.debugger = debugger
	engine_bridge.debugger = debugger
	if ClassDB.class_exists("Logger"):
		var logger_script: Script = load("res://addons/loki_studio/error_logger.gd")
		if logger_script != null:
			logger = logger_script.new()
			logger.source = "editor"
			logger.keep_messages = true
			OS.call("add_logger", logger)
			bridge.logger = logger
			engine_bridge.logger = logger
	dock = DockScript.new()
	dock.api = api
	dock.bridge = bridge
	dock.engine_bridge = engine_bridge
	_add_dock()
	_add_context_menus()
	if not ProjectSettings.has_setting("autoload/" + GAME_AUTOLOAD):
		add_autoload_singleton(GAME_AUTOLOAD, GAME_SCRIPT)
	bridge.start()
	engine_bridge.start()
	dock.start()
	print("LOKI Studio plugin %s ready (Godot %s)" % [bridge.VERSION, Engine.get_version_info().string])


func _exit_tree() -> void:
	for b in [bridge, engine_bridge]:
		if b != null:
			b.stop()
	for item in context_menus:
		call("remove_context_menu_plugin", item)
	context_menus.clear()
	if dock_holder != null:
		call("remove_dock", dock_holder)
		dock_holder.queue_free()
	elif dock != null:
		remove_control_from_docks(dock)
		dock.queue_free()
	if debugger != null:
		remove_debugger_plugin(debugger)
	if logger != null:
		OS.call("remove_logger", logger)
	for n in [bridge, api, engine_bridge, engine_api]:
		if n != null:
			n.queue_free()


func _enable_plugin() -> void:
	if not ProjectSettings.has_setting("autoload/" + GAME_AUTOLOAD):
		add_autoload_singleton(GAME_AUTOLOAD, GAME_SCRIPT)


func _disable_plugin() -> void:
	if ProjectSettings.has_setting("autoload/" + GAME_AUTOLOAD):
		remove_autoload_singleton(GAME_AUTOLOAD)


func _add_dock() -> void:
	# Godot 4.6+ has EditorDock + add_dock; older 4.x has add_control_to_dock.
	if ClassDB.class_exists("EditorDock") and has_method("add_dock"):
		dock_holder = ClassDB.instantiate("EditorDock")
		dock_holder.set("title", "LOKI Studio")
		dock_holder.set("default_slot", 4)          # DOCK_SLOT_RIGHT_UL
		dock_holder.set("layout_key", "loki_studio")
		dock_holder.add_child(dock)
		call("add_dock", dock_holder)
	else:
		add_control_to_dock(DOCK_SLOT_RIGHT_UL, dock)


func _add_context_menus() -> void:
	if not ClassDB.class_exists("EditorContextMenuPlugin") or not has_method("add_context_menu_plugin"):
		return
	var script: Script = load("res://addons/loki_studio/context_menu.gd")
	if script == null:
		return
	for slot in [4, 0, 1]:      # the script editor's code, the scene tree, the FileSystem dock
		var item: Object = script.new()
		item.dock = dock
		item.slot = slot
		call("add_context_menu_plugin", slot, item)
		context_menus.append(item)
