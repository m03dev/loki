extends SceneTree

func _initialize() -> void:
	var result: GDScript = ResourceLoader.load("res://scripts/autochess/arena_3d.gd", "GDScript", ResourceLoader.CACHE_MODE_IGNORE) as GDScript
	print("arena_script", result)
	quit()
