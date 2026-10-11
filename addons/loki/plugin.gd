@tool
extends EditorPlugin

var _main_screen_panel: Control


func _enter_tree() -> void:
	_main_screen_panel = CenterContainer.new()
	_main_screen_panel.name = "LokiMainScreen"
	var hint: Label = Label.new()
	hint.text = "Your Loki chat is available in the left dock beside Scene."
	_main_screen_panel.add_child(hint)
	EditorInterface.get_editor_main_screen().add_child(_main_screen_panel)
	_make_visible(false)
	# Chat is provided by the independent addons/loki/chat dock plugin.


func _exit_tree() -> void:
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
	return EditorInterface.get_editor_theme().get_icon("Node", "EditorIcons")
