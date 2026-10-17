class_name Player
extends Actor
## You. WASD to walk (relative to the camera), mouse drag to orbit the camera (right drag also
## turns you), wheel to zoom, Space to jump, Q/E to turn, click to target, Tab for the nearest
## enemy, 1-9 for the hotbar, F to interact. Combat numbers follow docs/MMO_API.md.

signal target_changed(target: Actor)
signal cast_started(skill_name: String, seconds: float)
signal cast_finished(ok: bool)
signal zone_entered(zone_name: String)
signal wants_prompt(skill: Dictionary)       # a LOKI action: the HUD asks "what?"
signal wants_talk(npc: Actor)

const WALK_SPEED := 5.4
const JUMP_SPEED := 8.6
const CAM_MIN := 3.0
const CAM_MAX := 22.0
const CLICK_MASK := 4 | 8 | 16 | 32

var cls := "Mage"
var target: Actor = null
var cam_yaw := 0.0              # 0: the camera is south of you, looking north at LOKI's hall
var cam_pitch := -0.42
var cam_dist := 9.0
var cam_rig: Node3D
var camera: Camera3D
var world: Node = null                # world.gd
var spawn_point := Vector3(0, 0.2, 5)
var casting: Dictionary = {}          # {skill, t, total, text}
var auto_attack := false
var autorun := false
var dead_t := 0.0
var combat_t := 99.0                  # seconds since the last hit given or taken
var emote := ""
var emote_at := 0
var _drag := {}                       # button -> {start, moved}
var _last_click_ms := 0
var _last_zone := ""
var _orbit_t := 0.0
var input_enabled := true


func _ready() -> void:
	setup_body(0.35, 1.7, LAYER_PLAYER)
	actor_id = "you"
	friendly = true
	name_color = Color(0.5, 1.0, 0.6)
	cam_rig = Node3D.new()
	cam_rig.top_level = true
	add_child(cam_rig)
	camera = Camera3D.new()
	camera.fov = 62.0
	camera.near = 0.1
	camera.far = 600.0
	cam_rig.add_child(camera)
	camera.current = true
	rebuild_model()
	damaged.connect(_on_damaged)


func rebuild_model() -> void:
	var p := GameState.profile()
	cls = str(p.get("cls", "Mage"))
	var info := GameState.class_info(cls)
	var color := Color.from_string(str(p.get("color", info["color"])), Color(0.55, 0.48, 1.0))
	set_model(CharacterModel.person(color, str(info.get("hat", "none")), str(info.get("gear", "none")), 0))


func sync_profile() -> void:
	var p := GameState.profile()
	display_name = str(p.get("name", "You"))
	level = int(p.get("level", 1))
	title_line = "<%s>" % str(p.get("cls", "Mage"))
	var new_max := float(p.get("hp_max", 100))
	if new_max != hp_max:
		hp = clampf(hp + (new_max - hp_max), 1.0, new_max) if alive else hp
		hp_max = new_max
	en_max = float(p.get("en_max", 100))
	if str(p.get("cls", "Mage")) != cls:
		rebuild_model()


# ----------------------------------------------------------------- input (from main.gd)

## Mouse events, forwarded from the root window (positions converted to the 3D view's pixels).
func handle_mouse(event: InputEvent, view_pos: Vector2) -> void:
	if not input_enabled:
		return
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.button_index == MOUSE_BUTTON_WHEEL_UP and mb.pressed:
			cam_dist = maxf(CAM_MIN, cam_dist * 0.9)
		elif mb.button_index == MOUSE_BUTTON_WHEEL_DOWN and mb.pressed:
			cam_dist = minf(CAM_MAX, cam_dist * 1.1)
		elif mb.button_index in [MOUSE_BUTTON_LEFT, MOUSE_BUTTON_RIGHT]:
			if mb.pressed:
				_drag[mb.button_index] = {"start": mb.position, "moved": false}
			else:
				var d: Dictionary = _drag.get(mb.button_index, {})
				_drag.erase(mb.button_index)
				if not d.is_empty() and not d["moved"]:
					_click(view_pos, mb.button_index == MOUSE_BUTTON_RIGHT)
	elif event is InputEventMouseMotion:
		var mm := event as InputEventMouseMotion
		for b in _drag.keys():
			var d: Dictionary = _drag[b]
			if (mm.position - d["start"]).length() > 4.0:
				d["moved"] = true
			if d["moved"]:
				cam_yaw -= mm.relative.x * 0.008
				cam_pitch = clampf(cam_pitch - mm.relative.y * 0.006, -1.35, 0.25)


func _click(view_pos: Vector2, right: bool) -> void:
	var hit := pick(view_pos)
	var now := Time.get_ticks_msec()
	var double := now - _last_click_ms < 350
	_last_click_ms = now
	if hit != null:
		set_target(hit)
		if right or double:
			interact()


## The actor under a point of the 3D view (or null).
func pick(view_pos: Vector2) -> Actor:
	if camera == null or not is_inside_tree():
		return null
	var from := camera.project_ray_origin(view_pos)
	var dir := camera.project_ray_normal(view_pos)
	var q := PhysicsRayQueryParameters3D.create(from, from + dir * 200.0, CLICK_MASK, [get_rid()])
	var hit := get_world_3d().direct_space_state.intersect_ray(q)
	if hit.is_empty():
		return null
	var c = hit.get("collider")
	return c if c is Actor else null


func set_target(a: Actor) -> void:
	if a == target:
		return
	target = a
	if a == null:
		auto_attack = false
	target_changed.emit(a)


## Tab: the nearest living enemy in front of the camera, cycling on each press.
func target_next() -> void:
	if world == null:
		return
	var best: Array = []
	for m in world.monsters_alive():
		var d: float = m.global_position.distance_to(global_position)
		if d < 30.0:
			best.append([d, m])
	if best.is_empty():
		return
	best.sort_custom(func(a, b): return a[0] < b[0])
	var idx := 0
	for i in best.size():
		if best[i][1] == target:
			idx = (i + 1) % best.size()
	set_target(best[idx][1])


func interact() -> void:
	if target == null or not is_instance_valid(target):
		return
	if target.hostile:
		auto_attack = true
		use_slot(1)
	elif target is NpcAgent or target is RemotePlayer:
		if target.global_position.distance_to(global_position) < 7.0 or target is RemotePlayer:
			wants_talk.emit(target)
		else:
			GameState.notice.emit("Too far away - walk closer to %s." % target.display_name, Color(1, 0.8, 0.5))
	elif target is Critter:
		target.say("<3", 2.0)
		GameState.say("emote", "", "You pet the %s." % target.display_name.to_lower(), Color(1.0, 0.75, 0.85))


func do_emote(name_: String) -> void:
	emote = name_
	emote_at = int(Time.get_unix_time_from_system() * 1000.0)
	if model != null:
		model.start_emote(name_)


# ----------------------------------------------------------------- skills

func use_slot(slot: int) -> void:
	if not alive or not input_enabled:
		return
	var skill := GameState.skill_in_slot(slot)
	if skill.is_empty():
		return
	if not casting.is_empty():
		return
	if GameState.cooldown_left(skill) > 0.0:
		GameState.notice.emit("%s is not ready yet." % skill.get("name", ""), Color(1, 0.6, 0.5))
		return
	var cost := float(skill.get("energy", 0))
	if en < cost:
		GameState.notice.emit("Not enough energy.", Color(0.5, 0.7, 1.0))
		return
	match str(skill.get("kind", "")):
		"combat":
			if target == null or not is_instance_valid(target) or not target.hostile or not target.alive:
				GameState.notice.emit("Pick an enemy first (click it or press Tab).", Color(1, 0.6, 0.5))
				return
			var dist := target.global_position.distance_to(global_position)
			if dist > float(skill.get("range", 3.0)):
				GameState.notice.emit("Out of range.", Color(1, 0.6, 0.5))
				return
			face_towards(target.global_position - global_position, 1.0, 1.0)
			_begin(skill, "")
		"self":
			_begin(skill, "")
		"loki":
			wants_prompt.emit(skill)
		"travel":
			_begin(skill, "")


## Called by the HUD after the player said what the LOKI action is about.
func cast_loki(skill: Dictionary, text: String) -> void:
	if text.strip_edges() == "":
		return
	_begin(skill, text.strip_edges())


func _begin(skill: Dictionary, text: String) -> void:
	var total := float(skill.get("cast_s", 0.0))
	if total <= 0.0:
		_finish(skill, text)
		return
	casting = {"skill": skill, "t": 0.0, "total": total, "text": text}
	if model != null:
		model.casting = true
	cast_started.emit(str(skill.get("name", "")), total)


func cancel_cast() -> void:
	if casting.is_empty():
		return
	casting = {}
	if model != null:
		model.casting = false
	cast_finished.emit(false)


func _finish(skill: Dictionary, text: String) -> void:
	en -= float(skill.get("energy", 0))
	GameState.start_cooldown(skill)
	combat_t = 0.0 if skill.get("kind", "") == "combat" else combat_t
	match str(skill.get("id", "")):
		"strike", "bolt":
			if target != null and is_instance_valid(target) and target.alive:
				var roll := GameState.roll_damage(skill)
				if skill.get("id", "") == "bolt" and world != null:
					world.spawn_bolt(self, target, roll[0], roll[1])
				else:
					target.take_damage(roll[0], roll[1], self)
		"mend":
			heal(GameState.roll_heal(skill))
		"hearth":
			global_position = spawn_point
			velocity = Vector3.ZERO
			GameState.notice.emit("Home again.", Color(0.6, 1.0, 0.8))
		_:
			if str(skill.get("kind", "")) == "loki":
				LokiApi.loki_action(str(skill.get("id", "")), text)
	cast_finished.emit(true)


## A hit puts you in combat (slower energy, no health regen). Casts are not interrupted by
## hits - only moving cancels them.
func _on_damaged(_a: Actor, _amount: int, _crit: bool, is_heal: bool) -> void:
	if not is_heal:
		combat_t = 0.0


func die() -> void:
	super.die()
	cancel_cast()
	dead_t = 4.0
	GameState.notice.emit("You were defeated. Back to LOKI's hall in a moment...", Color(1, 0.4, 0.35))
	LokiApi.note({"death": true})


# ----------------------------------------------------------------- per frame

func _physics_process(delta: float) -> void:
	_tick_bubble(delta)
	combat_t += delta
	if GameState.mode == "background":
		_background_camera(delta)
		return
	if not alive:
		dead_t -= delta
		if dead_t <= 0.0:
			alive = true
			hp = hp_max
			en = en_max
			global_position = spawn_point
			velocity = Vector3.ZERO
			if model != null:
				model.dead = false
		_update_camera(delta)
		if model != null:
			model.tick(delta, 0.0)
		return
	var typing := _typing()
	var input := Vector2.ZERO
	if input_enabled and not typing:
		input = Input.get_vector("move_left", "move_right", "move_forward", "move_back")
		if Input.is_action_pressed("turn_left"):
			cam_yaw += 2.2 * delta
		if Input.is_action_pressed("turn_right"):
			cam_yaw -= 2.2 * delta
	if autorun and input == Vector2.ZERO:
		input = Vector2(0, -1)
	if input != Vector2.ZERO and Input.is_action_pressed("move_back"):
		autorun = false
	# camera-relative: forward is where the camera looks, flattened
	var fwd := Vector3(-sin(cam_yaw), 0, -cos(cam_yaw))
	var right := Vector3(cos(cam_yaw), 0, -sin(cam_yaw))
	var wish := (right * input.x - fwd * input.y)
	if wish.length() > 1.0:
		wish = wish.normalized()
	if wish != Vector3.ZERO and not casting.is_empty():
		cancel_cast()
		GameState.notice.emit("Cast cancelled (you moved).", Color(1, 0.7, 0.5))
	if input_enabled and not typing and Input.is_action_just_pressed("jump") and is_on_floor():
		velocity.y = JUMP_SPEED
	var speed := _physics_move(delta, wish, WALK_SPEED)
	if _drag.has(MOUSE_BUTTON_RIGHT) and _drag[MOUSE_BUTTON_RIGHT]["moved"]:
		rotation.y = lerp_angle(rotation.y, cam_yaw + PI, clampf(delta * 14.0, 0.0, 1.0))
	elif wish != Vector3.ZERO:
		face_towards(wish, delta, 12.0)
	if wish != Vector3.ZERO:
		emote = ""
	# casting
	if not casting.is_empty():
		casting["t"] = float(casting["t"]) + delta
		if float(casting["t"]) >= float(casting["total"]):
			var c := casting
			casting = {}
			if model != null:
				model.casting = false
			_finish(c["skill"], str(c["text"]))
	# auto attack: keep striking the target while in range
	if auto_attack and casting.is_empty() and target != null and is_instance_valid(target) and target.alive and target.hostile:
		var strike := GameState.skill_in_slot(1)
		if GameState.cooldown_left(strike) <= 0.0 and target.global_position.distance_to(global_position) <= float(strike.get("range", 2.6)):
			face_towards(target.global_position - global_position, 1.0, 1.0)
			_finish(strike, "")
	if target != null and (not is_instance_valid(target) or (target.hostile and not target.alive)):
		set_target(null)
	# regeneration (docs/MMO_API.md): energy 6/s in combat, 14/s out; health 6 %/s after 5 s out of it
	en = minf(en_max, en + (6.0 if combat_t < 5.0 else 14.0) * delta)
	if combat_t > 5.0:
		hp = minf(hp_max, hp + hp_max * 0.06 * delta)
	if global_position.y < -40.0:
		global_position = spawn_point
		velocity = Vector3.ZERO
		GameState.notice.emit("You fell off the world - the wind carried you home.", Color(0.7, 0.85, 1.0))
	if world != null:
		var z: String = world.zone_at(global_position)
		if z != _last_zone and z != "":
			_last_zone = z
			zone = z
			zone_entered.emit(z)
	_update_camera(delta)
	if model != null:
		model.tick(delta, speed, not is_on_floor())


func _typing() -> bool:
	var vp := get_tree().root
	var f := vp.gui_get_focus_owner()
	return f is LineEdit or f is TextEdit


func _update_camera(_delta: float) -> void:
	var pivot := global_position + Vector3(0, 1.5, 0)
	var off := Vector3(sin(cam_yaw) * cos(cam_pitch), -sin(cam_pitch), cos(cam_yaw) * cos(cam_pitch)) * cam_dist
	cam_rig.global_position = pivot + off
	cam_rig.look_at(pivot, Vector3.UP)


## Behind LOKI's home screen: no player, a slow orbit round the home island.
func _background_camera(delta: float) -> void:
	_orbit_t += delta
	visible = false
	var c := Vector3(0, 1.0, 0)
	var yaw := _orbit_t * 0.05
	cam_rig.global_position = c + Vector3(sin(yaw) * 34.0, 14.0, cos(yaw) * 34.0)
	cam_rig.look_at(c, Vector3.UP)


## What other machines see (POST /world/presence player).
func presence() -> Dictionary:
	var uv: Vector2 = world.zone_uv(zone, global_position) if world != null else Vector2.ZERO
	var p := GameState.profile()
	return {"name": display_name, "cls": cls, "lvl": level, "zone": zone, "u": snappedf(uv.x, 0.001), "v": snappedf(uv.y, 0.001),
			"y": snappedf(maxf(0.0, global_position.y), 0.01), "ry": snappedf(wrapf(rotation.y, -PI, PI), 0.001),
			"hp": snappedf(hp / maxf(hp_max, 1.0), 0.01), "en": snappedf(en / maxf(en_max, 1.0), 0.01),
			"moving": Vector2(velocity.x, velocity.z).length() > 0.2, "emote": emote, "emote_at": emote_at,
			"ts": int(Time.get_unix_time_from_system() * 1000.0), "color": str(p.get("color", "")),
			"target": target.display_name if target != null and is_instance_valid(target) else ""}
