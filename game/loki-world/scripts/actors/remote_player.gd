class_name RemotePlayer
extends Actor
## Another machine's player (the owner on his other computer), from presence
## (POST /world/presence players[]). Positions are buffered by the sender's clock and drawn about
## 450 ms in the past, between the two samples around that moment (docs/MMO_API.md section 6),
## so movement over the relay stays smooth.

const DELAY_MS := 450.0
const MAX_EXTRAPOLATE_MS := 250.0

var machine := ""
var samples: Array = []            # [{ts, pos: Vector3, ry, y}]
var clock_offset := INF           # local ms - sender ms (smallest seen)
var cls := "Warrior"
var _last_emote_at := 0
var world: Node = null            # world.gd: zone -> position


func setup(p: Dictionary, world_node: Node) -> void:
	setup_body(0.35, 1.7, LAYER_REMOTE)
	collision_mask = 0
	world = world_node
	machine = str(p.get("machine", ""))
	actor_id = "player:" + machine
	cls = str(p.get("cls", "Warrior"))
	var info := GameState.class_info(cls)
	var color := Color.from_string(str(p.get("color", "")), Color.from_string(str(info["color"]), Color(0.8, 0.4, 0.3)))
	set_model(CharacterModel.person(color, str(info.get("hat", "none")), str(info.get("gear", "none")), 1))
	name_color = Color(0.55, 0.85, 1.0)
	apply(p)


func apply(p: Dictionary) -> void:
	display_name = str(p.get("name", "Player"))
	title_line = "<%s> on %s" % [str(p.get("cls", "")), machine]
	level = int(p.get("lvl", 1))
	hp_max = 100.0
	en_max = 100.0
	hp = 100.0 * float(p.get("hp", 1.0))
	en = 100.0 * float(p.get("en", 1.0))
	zone = str(p.get("zone", ""))
	var ts := float(p.get("ts", 0))
	var now := Time.get_ticks_msec() + 0.0
	if ts > 0.0:
		clock_offset = minf(clock_offset, now - ts)
	var pos: Vector3 = world.zone_point(zone, float(p.get("u", 0.0)), float(p.get("v", 0.0))) if world != null else Vector3.ZERO
	pos.y += float(p.get("y", 0.0))
	if samples.is_empty() or float(samples[-1]["ts"]) < ts:
		samples.append({"ts": ts, "pos": pos, "ry": float(p.get("ry", 0.0))})
		if samples.size() > 20:
			samples.pop_front()
	var emote := str(p.get("emote", ""))
	var at := int(p.get("emote_at", 0))
	if emote != "" and at != _last_emote_at and model != null:
		_last_emote_at = at
		model.start_emote(emote)
	visible = world == null or world.has_zone(zone)


func _physics_process(delta: float) -> void:
	_tick_bubble(delta)
	if samples.is_empty():
		return
	var render_ts := Time.get_ticks_msec() - (0.0 if clock_offset == INF else clock_offset) - DELAY_MS
	var a: Dictionary = samples[0]
	var b: Dictionary = samples[-1]
	for i in range(samples.size() - 1):
		if float(samples[i]["ts"]) <= render_ts and float(samples[i + 1]["ts"]) >= render_ts:
			a = samples[i]
			b = samples[i + 1]
			break
	var target: Vector3
	var ry: float
	var span := float(b["ts"]) - float(a["ts"])
	if span > 0.0:
		var k := clampf((render_ts - float(a["ts"])) / span, 0.0, 1.0 + MAX_EXTRAPOLATE_MS / span)
		target = (a["pos"] as Vector3).lerp(b["pos"], k)
		ry = lerp_angle(float(a["ry"]), float(b["ry"]), clampf(k, 0.0, 1.0))
	else:
		target = b["pos"]
		ry = float(b["ry"])
	var before := global_position
	global_position = global_position.lerp(target, clampf(delta * 12.0, 0.0, 1.0)) if before.distance_to(target) < 8.0 else target
	rotation.y = lerp_angle(rotation.y, ry, clampf(delta * 10.0, 0.0, 1.0))
	var speed := Vector2(global_position.x - before.x, global_position.z - before.z).length() / maxf(delta, 0.001)
	if model != null:
		model.tick(delta, speed, false)
