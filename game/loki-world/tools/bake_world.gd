extends SceneTree
## Save LOKI World's home island as an editable scene: res://scenes/home_island.tscn (HomeBuilder's pieces).
##
##   godot --headless --path game/loki-world -s res://tools/bake_world.gd            write it if it is missing
##   godot --headless --path game/loki-world -s res://tools/bake_world.gd -- --force overwrite (loses edits!)
##
## After that the scene is yours: open it in Godot and change anything. The game loads it instead of building.

const OUT := "res://scenes/home_island.tscn"


func _init() -> void:
	var force := OS.get_cmdline_user_args().has("--force")
	if ResourceLoader.exists(OUT) and not force:
		print("bake_world: %s exists - keeping your edits (use -- --force to rebuild it from code)" % OUT)
		quit(0)
		return
	var holder := Node3D.new()
	var island: Node3D = HomeBuilder.build(holder)
	holder.remove_child(island)
	HomeBuilder.own(island, island)
	var packed := PackedScene.new()
	var err := packed.pack(island)
	if err == OK:
		err = ResourceSaver.save(packed, OUT)
	print("bake_world: %s -> %s (%d nodes)" % [OUT, error_string(err), island.find_children("*", "", true, false).size() + 1])
	island.free()
	holder.free()
	quit(0 if err == OK else 1)
