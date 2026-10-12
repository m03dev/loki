@tool
extends EditorPlugin

const DOCK_SCRIPT: Script = preload("res://addons/loki/loki_dock.gd")

var _dock: EditorDock
var _chat_panel: Control


func _enter_tree() -> void:
	_chat_panel = DOCK_SCRIPT.new() as Control
	if _chat_panel == null:
		push_error("Loki chat panel did not instantiate a Control.")
		return
	_chat_panel.name = "LokiChatPanel"
	_chat_panel.custom_minimum_size = Vector2(350.0, 300.0)
	_dock = EditorDock.new()
	_dock.title = "Loki"
	_dock.icon_name = "Node"
	_dock.default_slot = EditorDock.DOCK_SLOT_LEFT_UL
	_dock.available_layouts = EditorDock.DOCK_LAYOUT_VERTICAL | EditorDock.DOCK_LAYOUT_FLOATING
	# transient = a loaded editor layout may MOVE this dock but never closes it, so the
	# panel is always there instead of silently vanishing when a layout is restored.
	_dock.transient = true
	_dock.add_child(_chat_panel)
	add_dock(_dock)
	_dock.open()
	_dock.make_visible()


func _exit_tree() -> void:
	if _dock != null:
		remove_dock(_dock)
		_dock.queue_free()
		_dock = null
		_chat_panel = null
