class_name Critter
extends Actor
## The fox and the rabbits (the owner loves the fox). The fox trots between flower patches, sits
## and looks around, visits LOKI now and then, and curls up asleep at night. Rabbits hop about
## and keep away from you.

var kind := "fox"
var center := Vector3.ZERO
var radius := 10.0
var loki_spot := Vector3.ZERO
var player: Actor = null
var world: Node = null
var _to := Vector3.ZERO
var _wait := 0.0
var _sitting := 0.0


func setup(kind_name: String, at: Vector3, island_center: Vector3, island_radius: float) -> void:
	kind = kind_name
	setup_body(0.22, 0.5, LAYER_CRITTER)
	center = island_center
	radius = island_radius
	_to = at
	friendly = true
	show_bars = false
	if kind == "fox":
		set_model(CharacterModel.fox())
		display_name = "Fox"
		title_line = "<the island's fox>"
		name_color = Color(1.0, 0.7, 0.4)
		interact_hint = "Pet"
	else:
		set_model(CharacterModel.rabbit(kind == "rabbit_grey"))
		display_name = "Rabbit"
		name_color = Color(0.9, 0.9, 0.9)
		interact_hint = "Pet"


func _physics_process(delta: float) -> void:
	var night: bool = world != null and world.is_night()
	if model != null:
		model.asleep = night and kind == "fox" and _to.distance_to(global_position) < 0.5
	var wish := Vector3.ZERO
	var to := _to - global_position
	to.y = 0.0
	if kind != "fox" and player != null and player.global_position.distance_to(global_position) < 2.5:
		var away := global_position - player.global_position
		away.y = 0.0
		_to = global_position + away.normalized() * 3.0
		_to = center + (_to - center).limit_length(radius * 0.85)
		_wait = 0.0
	if to.length() > 0.35:
		wish = to.normalized()
	else:
		_wait -= delta
		if _wait <= 0.0:
			_wait = randf_range(2.0, 7.0) * (3.0 if night else 1.0)
			if kind == "fox" and randf() < 0.25 and loki_spot != Vector3.ZERO:
				_to = loki_spot + Vector3(randf_range(-1.5, 1.5), 0, 1.8)
			else:
				var a := randf() * TAU
				var r := randf_range(0.2, 0.8) * radius
				_to = center + Vector3(cos(a) * r, 0, sin(a) * r)
	var speed := _physics_move(delta, wish, 2.6 if kind == "fox" else 2.0)
	if wish != Vector3.ZERO:
		face_towards(wish, delta, 8.0)
	if model != null:
		model.tick(delta, speed, not is_on_floor())
