class_name Monster
extends Actor
## A failed job, out in the world as a monster (GET /mmo/state monsters[]): named from its error
## (Timeout Wraith, Syntax Golem...). It wanders near its spawn, chases you inside aggro_radius,
## hits for dmg every attack_every_s, goes home and heals beyond leash (docs/MMO_API.md).
## Beating it gives XP and a lesson scroll and offers "retry with a stronger model".

var data: Dictionary = {}
var spawn := Vector3.ZERO
var aggro := 5.0
var leash := 10.0
var move_speed := 2.4
var attack_every := 2.0
var dmg: Array = [6, 10]
var player: Actor = null
var _attack_t := 0.0
var _wander_to := Vector3.ZERO
var _wander_wait := 0.0
var _returning := false
var _dead_t := 0.0


func setup(d: Dictionary, at: Vector3) -> void:
	setup_body(0.45, 1.4, LAYER_MONSTER)
	spawn = at
	_wander_to = at
	actor_id = str(d.get("id", ""))
	hostile = true
	friendly = false
	name_color = Color(1.0, 0.42, 0.36)
	set_model(CharacterModel.monster(str(d.get("kind", "gremlin")), 1.0 + 0.04 * float(d.get("level", 1))))
	apply(d)
	hp = hp_max


func apply(d: Dictionary) -> void:
	data = d
	display_name = str(d.get("name", "Monster"))
	title_line = str(d.get("title", "")).substr(0, 44)
	level = int(d.get("level", 1))
	hp_max = float(d.get("hp_max", 100))
	aggro = float(d.get("aggro_radius", 5.0))
	leash = float(d.get("leash", 10.0))
	move_speed = float(d.get("speed", 2.4))
	attack_every = float(d.get("attack_every_s", 2.0))
	dmg = d.get("dmg", [6, 10])
	en = 0.0
	en_max = 0.0
	interact_hint = "Attack"


func _physics_process(delta: float) -> void:
	_tick_bubble(delta)
	if not alive:
		_dead_t += delta
		if model != null:
			model.tick(delta, 0.0)
			model.position.y = -minf(_dead_t * 0.3, 1.2) if _dead_t > 2.0 else 0.0
		if _dead_t > 6.0:
			queue_free()
		return
	var wish := Vector3.ZERO
	var from_home := global_position - spawn
	from_home.y = 0.0
	var chase := false
	if player != null and player.alive and not _returning:
		var to_p := player.global_position - global_position
		to_p.y = 0.0
		if to_p.length() < aggro or (hp < hp_max and to_p.length() < leash):
			chase = true
			if to_p.length() > 1.5:
				wish = to_p.normalized()
			face_towards(to_p, delta, 8.0)
			_attack_t -= delta
			if to_p.length() <= 1.9 and _attack_t <= 0.0:
				_attack_t = attack_every
				var amount := randi_range(int(dmg[0]), int(dmg[1]))
				player.take_damage(amount, false, self)
				if model != null:
					model.start_emote("bow")
	if from_home.length() > leash:
		_returning = true
	if _returning:
		wish = -from_home.normalized()
		hp = min(hp_max, hp + hp_max * 0.2 * delta)
		if from_home.length() < 1.0:
			_returning = false
	elif not chase:
		var to := _wander_to - global_position
		to.y = 0.0
		if to.length() > 0.4:
			wish = to.normalized() * 0.5
		else:
			_wander_wait -= delta
			if _wander_wait <= 0.0:
				_wander_wait = randf_range(2.0, 6.0)
				_wander_to = spawn + Vector3(randf_range(-2.5, 2.5), 0, randf_range(-2.5, 2.5))
		if not chase and hp < hp_max:
			hp = min(hp_max, hp + hp_max * 0.05 * delta)
	var speed := _physics_move(delta, wish, move_speed)
	if wish != Vector3.ZERO and not chase:
		face_towards(wish, delta, 6.0)
	if model != null:
		model.tick(delta, speed, not is_on_floor())
