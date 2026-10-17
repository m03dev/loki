class_name Actor
extends CharacterBody3D
## Anything with a nameplate: you, other players, LOKI's agents, monsters, critters.
## Holds health/energy, level and class, and the body (CharacterModel).

signal damaged(actor: Actor, amount: int, crit: bool, heal: bool)
signal died(actor: Actor)

const LAYER_WORLD := 1
const LAYER_PLAYER := 2
const LAYER_NPC := 4
const LAYER_MONSTER := 8
const LAYER_REMOTE := 16
const LAYER_CRITTER := 32

var display_name := ""
var title_line := ""          # under the name: <class> or what it is doing
var level := 1
var hp := 100.0
var hp_max := 100.0
var en := 100.0
var en_max := 100.0
var hostile := false
var friendly := true
var name_color := Color(1, 1, 1)
var model: CharacterModel
var alive := true
var zone := ""
var bubble := ""
var bubble_t := 0.0
var gravity := 24.0
var show_bars := true
var interact_hint := ""        # e.g. "Talk", "Turn in"
var actor_id := ""


func setup_body(radius: float, height: float, layer: int) -> void:
	var shape := CapsuleShape3D.new()
	shape.radius = radius
	shape.height = max(height, radius * 2.0)
	var cs := CollisionShape3D.new()
	cs.shape = shape
	cs.position = Vector3(0, shape.height * 0.5, 0)
	add_child(cs)
	collision_layer = layer
	collision_mask = LAYER_WORLD


func set_model(m: CharacterModel) -> void:
	if model != null:
		model.queue_free()
	model = m
	add_child(m)


func nameplate_position() -> Vector3:
	var h := model.height if model != null else 1.8
	return global_position + Vector3(0, h + 0.35, 0)


func take_damage(amount: int, crit: bool = false, _source: Actor = null) -> void:
	if not alive:
		return
	hp = max(0.0, hp - amount)
	if model != null:
		model.hit_flash = 0.2
	damaged.emit(self, amount, crit, false)
	if hp <= 0.0:
		die()


func heal(amount: int) -> void:
	if not alive:
		return
	var before := hp
	hp = min(hp_max, hp + amount)
	damaged.emit(self, int(hp - before), false, true)


func die() -> void:
	alive = false
	if model != null:
		model.dead = true
	died.emit(self)


func say(text: String, seconds: float = 5.0) -> void:
	bubble = text.substr(0, 140)
	bubble_t = seconds


func _tick_bubble(delta: float) -> void:
	if bubble_t > 0.0:
		bubble_t -= delta
		if bubble_t <= 0.0:
			bubble = ""


## Fall with gravity and slide; returns horizontal speed (for the walk animation).
func _physics_move(delta: float, wish: Vector3, speed: float) -> float:
	if not is_on_floor():
		velocity.y -= gravity * delta
	velocity.x = wish.x * speed
	velocity.z = wish.z * speed
	move_and_slide()
	return Vector2(velocity.x, velocity.z).length()


func face_towards(dir: Vector3, delta: float, rate: float = 10.0) -> void:
	if dir.length_squared() < 0.0001:
		return
	var want := atan2(dir.x, dir.z)
	rotation.y = lerp_angle(rotation.y, want, clampf(rate * delta, 0.0, 1.0))
