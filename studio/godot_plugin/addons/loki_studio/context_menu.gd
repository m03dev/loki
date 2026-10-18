@tool
extends EditorContextMenuPlugin
## Right-click entries (Godot 4.4+): "Add to LOKI Studio chat" in the script editor (the
## selected code), the scene tree (the selected nodes) and the FileSystem dock (@-mentions).

var dock: Control
var slot := 0


func _popup_menu(paths: PackedStringArray) -> void:
	add_context_menu_item("Add to LOKI Studio chat", _add)


func _add(args: Variant) -> void:
	if dock == null:
		return
	if slot == 4:            # CONTEXT_SLOT_SCRIPT_EDITOR_CODE
		dock.add_selection_to_chat()
	elif slot == 0:          # CONTEXT_SLOT_SCENE_TREE
		dock.add_text_to_chat("@selection ")
	else:                    # the FileSystem dock: the selected files
		var items: Array = Array(args) if typeof(args) == TYPE_ARRAY or typeof(args) == TYPE_PACKED_STRING_ARRAY else []
		for p in items:
			dock.add_text_to_chat("@%s " % str(p))
