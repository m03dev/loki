extends Node3D
## LOKI World: one shared sky; every device running LOKI is its own island (zone). The island
## you stand on is THIS machine; linked machines float out in the space around it, joined by
## bridges of light you can walk across. Builds the islands, keeps the actors in step with the
## game state (GameState), runs day/night from the local clock, and plays the effects.

signal float_text(world_pos: Vector3, text: String, color: Color)
signal actor_died(actor: Actor)

const HOME_RADIUS := 16.0
const OTHER_RADIUS := 10.0
const RING := 52.0
const SPAWN := Vector3(0, 0.3, 6.0)
const MACHINE_COLORS := {"mac": Color(0.8, 0.82, 0.86), "darwin": Color(0.8, 0.82, 0.86), "pc": Color(0.3, 0.52, 1.0), "windows": Color(0.3, 0.52, 1.0)}

var player: Player
var zones: Dictionary = {}          # name -> {center: Vector3, radius: float, node: Node3D, home: bool}
var npcs: Dictionary = {}           # id -> NpcAgent
var monsters: Dictionary = {}       # id -> Monster
var remotes: Dictionary = {}        # machine -> RemotePlayer
var critters: Array = []
var paintings: Array = []           # MeshInstance3D frames in the creations hall
var sun: DirectionalLight3D
var env: Environment
var sky_mat: ShaderMaterial
var hour_override := -1.0
var day_speed := 0.0                # > 0: hours per second (for screenshots/tests)
var _hour := 12.0
var _zone_key := ""
var _painting_key := ""
## The Forge shelf (beside the creations hall): the newest models made in Forge stand on these pedestals
const SHELF_SIZE := 3
var shelf_spots: Array = []        # world positions of the pedestal tops
var shelf_models: Array = []       # Node3D per spot (the loaded model, or null)
var _shelf_gen := 0
var _bolts: Array = []
var _islets: Array = []
var _beacons: Dictionary = {}


func _ready() -> void:
	_build_environment()
	player = Player.new()
	player.name = "Player"
	player.world = self
	player.spawn_point = SPAWN
	add_child(player)
	player.position = SPAWN
	player.rotation.y = PI     # facing LOKI's hall
	player.died.connect(func(a): actor_died.emit(a))
	player.damaged.connect(_on_damaged)
	_build_zones()
	player.zone = GameState.self_zone
	_spawn_critters()
	GameState.state_changed.connect(_on_state)
	GameState.presence_changed.connect(_on_presence)
	GameState.level_up.connect(func(_l): level_up_effect())
	LokiApi.forge_models_changed.connect(_on_forge_models)
	_on_state()


# ----------------------------------------------------------------- environment, day/night

func _build_environment() -> void:
	env = Environment.new()
	env.background_mode = Environment.BG_SKY
	var sky := Sky.new()
	sky_mat = ShaderMaterial.new()
	sky_mat.shader = preload("res://shaders/sky.gdshader")
	sky.sky_material = sky_mat
	sky.radiance_size = Sky.RADIANCE_SIZE_32
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.55, 0.6, 0.75)
	env.ambient_light_energy = 0.55
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	env.fog_enabled = true
	env.fog_light_color = Color(0.7, 0.8, 0.95)
	env.fog_density = 0.0035
	env.fog_sky_affect = 0.0
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)
	sun = DirectionalLight3D.new()
	sun.shadow_enabled = true
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_ORTHOGONAL
	sun.directional_shadow_max_distance = 60.0
	sun.shadow_bias = 0.08
	sun.light_energy = 1.25
	add_child(sun)


func is_night() -> bool:
	return _hour < 6.0 or _hour > 20.5


func _day_night(delta: float) -> void:
	if hour_override >= 0.0:
		_hour = hour_override
		if day_speed > 0.0:
			hour_override = fmod(hour_override + day_speed * delta, 24.0)
	else:
		var t := Time.get_time_dict_from_system()
		_hour = float(t["hour"]) + float(t["minute"]) / 60.0
	# sun angle: rises at 6, sets at 20; the moon (a dim blue sun) the rest of the time
	var day_k := clampf(sin((_hour - 6.0) / 14.0 * PI), 0.0, 1.0) if _hour >= 6.0 and _hour <= 20.0 else 0.0
	var dusk := clampf(1.0 - absf(_hour - 19.5) / 1.5, 0.0, 1.0) + clampf(1.0 - absf(_hour - 6.5) / 1.5, 0.0, 1.0)
	var elev := lerpf(0.35, 1.15, day_k) if day_k > 0.0 else 0.9
	var azim := (_hour / 24.0) * TAU
	sun.rotation = Vector3(-elev, azim, 0)
	var night := 1.0 - clampf(day_k * 3.0, 0.0, 1.0)
	sun.light_color = Color(1.0, 0.93, 0.8).lerp(Color(1.0, 0.65, 0.45), clampf(dusk, 0.0, 1.0)).lerp(Color(0.55, 0.65, 1.0), night)
	sun.light_energy = lerpf(0.35, 1.1, 1.0 - night)
	var zen := Color(0.27, 0.52, 0.86).lerp(Color(0.04, 0.06, 0.16), night)
	var hor := Color(0.8, 0.88, 0.96).lerp(Color(1.0, 0.62, 0.45), clampf(dusk, 0.0, 1.0) * 0.8).lerp(Color(0.12, 0.14, 0.3), night)
	sky_mat.set_shader_parameter("zenith", zen)
	sky_mat.set_shader_parameter("horizon", hor)
	sky_mat.set_shader_parameter("below", hor.darkened(0.35))
	sky_mat.set_shader_parameter("night", night)
	sky_mat.set_shader_parameter("sun_color", sun.light_color)
	env.ambient_light_color = Color(0.58, 0.62, 0.78).lerp(Color(0.25, 0.3, 0.55), night)
	env.ambient_light_energy = lerpf(0.5, 0.42, night)
	env.fog_light_color = hor


func hour() -> float:
	return _hour


# ----------------------------------------------------------------- zones (islands)

func _zone_names() -> Array:
	var z: Dictionary = GameState.state.get("zones", {})
	var out := [GameState.self_zone]
	for m in z.get("machines", []):
		var n := str(m.get("name", ""))
		if n != "" and not out.has(n):
			out.append(n)
	return out


func _build_zones() -> void:
	var names := _zone_names()
	var key := ",".join(PackedStringArray(names))
	if key == _zone_key:
		return
	_zone_key = key
	for z in zones.values():
		z["node"].queue_free()
	zones.clear()
	_beacons.clear()
	for n in names:
		var home: bool = n == names[0]
		var center := Vector3.ZERO
		if not home:
			# a stable slot from the name, so islands never jump or swap
			var a := float(GameState.hash_text(str(n)) % 3600) / 3600.0 * TAU
			center = Vector3(cos(a) * RING, 0, sin(a) * RING)
			for other in zones.values():
				if (other["center"] as Vector3).distance_to(center) < OTHER_RADIUS * 2.6:
					a += 0.9
					center = Vector3(cos(a) * RING, 0, sin(a) * RING)
		var node := Node3D.new()
		node.name = "Island_%s" % str(n).validate_node_name()
		node.position = center
		add_child(node)
		var radius := HOME_RADIUS if home else OTHER_RADIUS
		zones[n] = {"center": center, "radius": radius, "node": node, "home": home}
		if home:
			_build_home(node)
		else:
			_build_other(node, str(n))
			_build_bridge(Vector3.ZERO, HOME_RADIUS, center, OTHER_RADIUS)
	if _islets.is_empty():
		_build_scenery()


func has_zone(name_: String) -> bool:
	return zones.has(name_)


func zone_point(name_: String, u: float, v: float) -> Vector3:
	var z: Dictionary = zones.get(name_, {})
	if z.is_empty():
		return Vector3(0, -500, 0)
	var r: float = z["radius"]
	return (z["center"] as Vector3) + Vector3(u * r, 0.05, v * r)


func zone_uv(name_: String, pos: Vector3) -> Vector2:
	var z: Dictionary = zones.get(name_, {})
	if z.is_empty():
		return Vector2.ZERO
	var d := pos - (z["center"] as Vector3)
	var r: float = z["radius"]
	return Vector2(clampf(d.x / r, -1.5, 1.5), clampf(d.z / r, -1.5, 1.5))


## The island under (or nearest to) a point; "" over the open sky between islands.
func zone_at(pos: Vector3) -> String:
	for n in zones.keys():
		var z: Dictionary = zones[n]
		var d := Vector2(pos.x - z["center"].x, pos.z - z["center"].z).length()
		if d <= float(z["radius"]) * 1.05:
			return str(n)
	return ""


func zone_center(name_: String) -> Vector3:
	return zones.get(name_, {}).get("center", Vector3.ZERO)


func station_point(station: String) -> Vector3:
	var s: Array = IslandBuilder.STATIONS.get(station, IslandBuilder.STATIONS["workshop"])
	var a := deg_to_rad(float(s[0]))
	var r := float(s[1]) * HOME_RADIUS
	if station == "hall":
		return Vector3(0, 0, -HOME_RADIUS * 0.38 + 3.6)
	return Vector3(cos(a) * r, 0, sin(a) * r)


func _build_home(node: Node3D) -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 1776
	var body := StaticBody3D.new()
	body.name = "Ground"
	node.add_child(body)
	IslandBuilder.ground_collider(body, HOME_RADIUS)
	var m := MeshMerger.new()
	m.add(IslandBuilder.island_mesh(HOME_RADIUS, 77, 26), Transform3D(), Color.WHITE, true, 0.05)
	# LOKI's hall, north: the big house with horns over the door
	var hall := Vector3(0, 0, -HOME_RADIUS * 0.38)
	IslandBuilder.house(m, hall, 0.0, Vector3(6.0, 3.4, 4.6), Color(0.93, 0.88, 0.78), Color(0.15, 0.62, 0.6))
	m.add(Mats.cyl(0.0, 0.25, 1.0, 5), IslandBuilder.xf(hall + Vector3(-1.1, 6.4, 1.2), 0, Vector3.ONE, 0, 0.6), Color(0.95, 0.9, 0.75))
	m.add(Mats.cyl(0.0, 0.25, 1.0, 5), IslandBuilder.xf(hall + Vector3(1.1, 6.4, 1.2), 0, Vector3.ONE, 0, -0.6), Color(0.95, 0.9, 0.75))
	IslandBuilder.box_collider(body, hall + Vector3(0, 1.7, 0), Vector3(6.0, 3.4, 4.6))
	# the plaza and its paths
	m.add(Mats.cyl(4.2, 4.4, 0.08, 12), IslandBuilder.xf(Vector3(0, 0.04, 0)), IslandBuilder.PATH, false)
	m.add(Mats.cyl(0.9, 1.1, 0.5, 8), IslandBuilder.xf(Vector3(0, 0.25, 0)), Color(0.7, 0.68, 0.72))
	m.add(Mats.cyl(0.18, 0.18, 2.6, 6), IslandBuilder.xf(Vector3(0, 1.5, 0)), Color(0.75, 0.73, 0.8))
	IslandBuilder.post_collider(body, Vector3.ZERO, 1.0, 0.6)
	# the stations of LOKI's agents
	for st in IslandBuilder.STATIONS.keys():
		if st == "hall":
			continue
		var p := station_point(st)
		var face := atan2(-p.x, -p.z)
		IslandBuilder.station(m, body, st, p, face)
	# the creations hall (pink roof): the newest pictures LOKI made hang on its front wall
	var ch := Vector3(cos(deg_to_rad(125.0)), 0, sin(deg_to_rad(125.0))) * HOME_RADIUS * 0.66
	var ch_face := atan2(-ch.x, -ch.z)
	IslandBuilder.house(m, ch, ch_face, Vector3(5.6, 2.8, 2.6), Color(0.96, 0.92, 0.95), Color(0.95, 0.45, 0.65))
	IslandBuilder.box_collider(body, ch + Vector3(0, 1.4, 0), Vector3(5.6, 2.8, 2.6), ch_face)
	var basis := Basis.from_euler(Vector3(0, ch_face, 0))
	paintings.clear()
	for k in 5:
		var local := Vector3(-2.2 + 1.1 * k, 1.75, 1.36)
		if k == 2:
			local = Vector3(0, 2.15, 1.36)   # the door is in the middle: hang the newest above it
		var frame_pos := ch + basis * local
		m.add(Mats.box(Vector3(0.95, 0.75, 0.06)), Transform3D(basis, frame_pos), Color(0.75, 0.55, 0.25))
		var pic := MeshInstance3D.new()
		var quad := QuadMesh.new()
		quad.size = Vector2(0.8, 0.6)
		pic.mesh = quad
		pic.transform = Transform3D(basis, frame_pos + basis * Vector3(0, 0, 0.04))
		pic.material_override = Mats.picture(GameState.fake_painting(k))
		pic.visible = false
		node.add_child(pic)
		paintings.append(pic)
	# the Forge shelf: three pedestals in front of the creations hall
	shelf_spots.clear()
	for k in SHELF_SIZE:
		var spot := ch + basis * Vector3(-1.8 + 1.8 * k, 0, 3.0)
		m.add(Mats.cyl(0.45, 0.55, 0.7, 8), IslandBuilder.xf(spot + Vector3(0, 0.35, 0)), Color(0.82, 0.78, 0.86))
		m.add(Mats.cyl(0.52, 0.52, 0.08, 8), IslandBuilder.xf(spot + Vector3(0, 0.74, 0)), Color(0.95, 0.45, 0.65))
		IslandBuilder.box_collider(body, spot + Vector3(0, 0.35, 0), Vector3(0.9, 0.7, 0.9))
		shelf_spots.append(spot + Vector3(0, 0.78, 0))
	shelf_models.resize(SHELF_SIZE)
	# the pond and the waterfall off the east edge
	var pond_a := deg_to_rad(95.0)
	var pond := Vector3(cos(pond_a), 0, sin(pond_a)) * HOME_RADIUS * 0.8
	var water := MeshInstance3D.new()
	water.mesh = Mats.cyl(2.2, 2.2, 0.05, 10)
	water.position = pond + Vector3(0, 0.06, 0)
	water.material_override = Mats.water(false)
	node.add_child(water)
	m.add(Mats.cyl(2.5, 2.6, 0.1, 10), IslandBuilder.xf(pond + Vector3(0, 0.02, 0)), Color(0.55, 0.5, 0.48), false)
	for k in 8:
		var a := TAU * k / 8.0
		IslandBuilder.rock(m, pond + Vector3(cos(a) * 2.5, 0, sin(a) * 2.5), 0.7, rng)
	var fall := MeshInstance3D.new()
	var fq := QuadMesh.new()
	fq.size = Vector2(2.0, 30.0)
	fall.mesh = fq
	var out_dir := Vector3(cos(pond_a), 0, sin(pond_a))
	fall.position = out_dir * (HOME_RADIUS * 1.02) + Vector3(0, -15.0, 0)
	fall.rotation.y = atan2(out_dir.x, out_dir.z)
	fall.material_override = Mats.water(true)
	node.add_child(fall)
	m.add(Mats.box(Vector3(1.4, 0.12, HOME_RADIUS * 0.22)), Transform3D(Basis.from_euler(Vector3(0, atan2(out_dir.x, out_dir.z), 0)), out_dir * HOME_RADIUS * 0.93 + Vector3(0, 0.02, 0)), Color(0.35, 0.65, 0.9), false)
	# trees, rocks and flowers, kept off the paths and the stations
	var keep_out: Array = [Vector3.ZERO, hall, ch, pond, SPAWN]
	for st in IslandBuilder.STATIONS.keys():
		keep_out.append(station_point(st))
	var placed := 0
	var tries := 0
	while placed < 26 and tries < 400:
		tries += 1
		var a := rng.randf() * TAU
		var r := rng.randf_range(0.25, 0.9) * HOME_RADIUS
		var p := Vector3(cos(a) * r, 0, sin(a) * r)
		var ok := true
		for k in keep_out:
			if (k as Vector3).distance_to(p) < 3.6:
				ok = false
				break
		if not ok:
			continue
		keep_out.append(p)
		placed += 1
		if rng.randf() < 0.75:
			var size := rng.randf_range(0.9, 1.5)
			IslandBuilder.tree(m, p, size, rng)
			IslandBuilder.post_collider(body, p, 0.3 * size, 2.0)
		elif rng.randf() < 0.5:
			IslandBuilder.rock(m, p, rng.randf_range(0.8, 1.6), rng)
		else:
			IslandBuilder.flowers(m, p, rng)
	for k in 10:
		var a := rng.randf() * TAU
		var p := Vector3(cos(a), 0, sin(a)) * rng.randf_range(0.3, 0.9) * HOME_RADIUS
		IslandBuilder.flowers(m, p, rng)
	m.commit(node, "HomeIsland")
	var glow := MeshMerger.new()
	glow.ink_width = 0.04
	IslandBuilder.crystals(glow, HOME_RADIUS, rng, 22)
	glow.commit(node, "Crystals", Mats.toon(Color.WHITE, false, 1, Color(0.06, 0.35, 0.33)))
	_name_sign(node, Vector3(0, 3.4, 0), "%s - you are here" % GameState.self_zone, Color(0.6, 1.0, 0.9))


func _build_other(node: Node3D, machine: String) -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = GameState.hash_text(machine)
	var body := StaticBody3D.new()
	node.add_child(body)
	IslandBuilder.ground_collider(body, OTHER_RADIUS)
	var m := MeshMerger.new()
	m.add(IslandBuilder.island_mesh(OTHER_RADIUS, rng.randi(), 18), Transform3D(), Color.WHITE, true, 0.05)
	var info := _machine_info(machine)
	var os_name := str(info.get("os", "")).to_lower()
	var col: Color = MACHINE_COLORS.get(os_name, MACHINE_COLORS.get(machine.to_lower(), Color(0.85, 0.6, 0.35)))
	IslandBuilder.house(m, Vector3(0, 0, -3.0), 0.0, Vector3(4.4, 2.8, 3.4), Color(0.93, 0.92, 0.9), col)
	IslandBuilder.box_collider(body, Vector3(0, 1.4, -3.0), Vector3(4.4, 2.8, 3.4))
	m.add(Mats.cyl(2.6, 2.8, 0.08, 10), IslandBuilder.xf(Vector3(0, 0.04, 1.5)), IslandBuilder.PATH, false)
	for k in 9:
		var a := rng.randf() * TAU
		var p := Vector3(cos(a), 0, sin(a)) * rng.randf_range(0.45, 0.85) * OTHER_RADIUS
		if p.distance_to(Vector3(0, 0, -3)) < 3.5:
			continue
		var size := rng.randf_range(0.8, 1.3)
		IslandBuilder.tree(m, p, size, rng)
		IslandBuilder.post_collider(body, p, 0.3 * size, 2.0)
	m.commit(node, "Island")
	var glow := MeshMerger.new()
	glow.ink_width = 0.04
	IslandBuilder.crystals(glow, OTHER_RADIUS, rng, 12)
	glow.commit(node, "Crystals", Mats.toon(Color.WHITE, false, 1, Color(0.06, 0.35, 0.33)))
	# a beacon: lit while the machine answers
	var beacon := MeshInstance3D.new()
	beacon.mesh = Mats.cyl(0.25, 0.25, 9.0, 6)
	beacon.position = Vector3(3.2, 4.5, -3.0)
	beacon.material_override = Mats.glow(col.lightened(0.3), 0.6)
	node.add_child(beacon)
	_beacons[machine] = beacon
	_name_sign(node, Vector3(0, 6.2, -3.0), machine, Color(0.8, 0.9, 1.0))
	# a figure per job running there (from GET /world machines[].working)
	var working := mini(6, int(info.get("working", 0)))
	for k in working:
		var fig := CharacterModel.person(Color.from_hsv(rng.randf(), 0.5, 0.85), ["cap", "wizard", "goggles", "hood"][k % 4], "none", k % 3)
		fig.position = Vector3(-2.0 + 1.2 * k, 0, 1.5)
		fig.rotation.y = PI
		fig.casting = true
		node.add_child(fig)
		fig.set_meta("ambient", true)


func _machine_info(machine: String) -> Dictionary:
	for m in GameState.state.get("zones", {}).get("machines", []):
		if str(m.get("name", "")) == machine:
			return m
	return {}


func _build_bridge(a_center: Vector3, a_r: float, b_center: Vector3, b_r: float) -> void:
	var dir := (b_center - a_center)
	dir.y = 0.0
	var dist := dir.length()
	dir = dir.normalized()
	var start := a_center + dir * (a_r * 0.9)
	var end := b_center - dir * (b_r * 0.9)
	var length := start.distance_to(end)
	var mid := (start + end) * 0.5
	var yaw := atan2(dir.x, dir.z)
	var node := Node3D.new()
	node.name = "Bridge"
	node.position = mid
	node.rotation.y = yaw
	add_child(node)
	var deck := MeshInstance3D.new()
	deck.mesh = Mats.box(Vector3(2.2, 0.08, length))
	deck.position = Vector3(0, -0.04, 0)
	deck.material_override = Mats.glow(Color(0.35, 1.0, 0.95), 0.45, 1.0)
	node.add_child(deck)
	for side in [-1.0, 1.0]:
		var rail := MeshInstance3D.new()
		rail.mesh = Mats.box(Vector3(0.08, 0.08, length))
		rail.position = Vector3(side * 1.1, 0.9, 0)
		rail.material_override = Mats.glow(Color(0.6, 1.0, 1.0), 0.9)
		node.add_child(rail)
	var body := StaticBody3D.new()
	node.add_child(body)
	IslandBuilder.box_collider(body, Vector3(0, -0.15, 0), Vector3(2.2, 0.3, length + 2.0))
	IslandBuilder.box_collider(body, Vector3(-1.25, 0.6, 0), Vector3(0.2, 1.2, length))
	IslandBuilder.box_collider(body, Vector3(1.25, 0.6, 0), Vector3(0.2, 1.2, length))
	if dist <= 0.0:
		node.queue_free()


func _name_sign(node: Node3D, pos: Vector3, text: String, color: Color) -> void:
	var l := Label3D.new()
	l.text = text
	l.position = pos
	l.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	l.modulate = color
	l.outline_modulate = Color(0.02, 0.02, 0.05)
	l.outline_size = 10
	l.font_size = 40
	l.pixel_size = 0.004
	l.no_depth_test = false
	l.texture_filter = BaseMaterial3D.TEXTURE_FILTER_NEAREST
	node.add_child(l)


## Floating islets, clouds below: scenery only, slowly turning.
func _build_scenery() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 4242
	for k in 9:
		var a := rng.randf() * TAU
		var r := rng.randf_range(26.0, 90.0)
		var islet := Node3D.new()
		islet.position = Vector3(cos(a) * r, rng.randf_range(-14.0, 12.0), sin(a) * r)
		add_child(islet)
		var m := MeshMerger.new()
		var rad := rng.randf_range(1.6, 3.6)
		m.add(IslandBuilder.island_mesh(rad, rng.randi(), 10), Transform3D(), Color.WHITE, true, 0.06)
		if rng.randf() < 0.7:
			IslandBuilder.tree(m, Vector3(rng.randf_range(-0.5, 0.5), 0, rng.randf_range(-0.5, 0.5)), rng.randf_range(0.6, 1.0), rng)
		m.commit(islet, "Islet")
		var g := MeshMerger.new()
		IslandBuilder.crystals(g, rad, rng, 3)
		g.commit(islet, "Crystals", Mats.toon(Color.WHITE, false, 1, Color(0.06, 0.35, 0.33)))
		_islets.append({"node": islet, "base": islet.position.y, "phase": rng.randf() * TAU, "spin": rng.randf_range(-0.05, 0.05)})
	var clouds := Node3D.new()
	clouds.name = "Clouds"
	add_child(clouds)
	var cm := MeshMerger.new()
	cm.ink_width = 0.0
	for k in 26:
		var a := rng.randf() * TAU
		var r := rng.randf_range(20.0, 120.0)
		var c := Vector3(cos(a) * r, rng.randf_range(-34.0, -22.0), sin(a) * r)
		for j in 3:
			cm.add(Mats.box(Vector3(rng.randf_range(4, 9), rng.randf_range(1.0, 2.0), rng.randf_range(3, 6))),
					IslandBuilder.xf(c + Vector3(rng.randf_range(-3, 3), rng.randf_range(-0.5, 0.5), rng.randf_range(-2, 2)), rng.randf() * TAU),
					Color(0.96, 0.97, 1.0), false)
	cm.commit(clouds, "CloudBank")
	_islets.append({"node": clouds, "base": clouds.position.y, "phase": 0.0, "spin": 0.01})


## Fly to another island (the big map): an arc through the sky, then you land by its house.
func fly_to(name_: String) -> void:
	if not has_zone(name_) or not player.alive:
		return
	var z: Dictionary = zones[name_]
	var land: Vector3 = (z["center"] as Vector3) + Vector3(0, 0.4, 3.5 if not z["home"] else 6.0)
	var start := player.global_position
	player.input_enabled = false
	var tw := create_tween()
	tw.tween_method(func(k: float):
		var p := start.lerp(land, k)
		p.y += sin(k * PI) * 14.0
		player.global_position = p
		player.velocity = Vector3.ZERO, 0.0, 1.0, 2.6).set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN_OUT)
	tw.finished.connect(func(): player.input_enabled = GameState.mode == "play")
	GameState.notice.emit("Flying to %s..." % name_, Color(0.6, 0.9, 1.0))


# ----------------------------------------------------------------- critters

func _spawn_critters() -> void:
	var kinds := ["fox", "rabbit", "rabbit_grey"]
	for k in kinds.size():
		var c := Critter.new()
		var at := Vector3(4.0 + k * 1.5, 0.3, 3.0 - k)
		c.position = at
		add_child(c)
		c.setup(kinds[k], at, Vector3.ZERO, HOME_RADIUS)
		c.player = player
		c.world = self
		c.loki_spot = station_point("hall")
		critters.append(c)


# ----------------------------------------------------------------- state -> actors

func _on_state() -> void:
	_build_zones()
	player.sync_profile()
	_sync_npcs()
	_sync_monsters()
	_sync_paintings()
	for m in _beacons.keys():
		var info := _machine_info(m)
		(_beacons[m] as MeshInstance3D).visible = bool(info.get("ok", true))


func _sync_npcs() -> void:
	var seen := {}
	for d in GameState.state.get("npcs", []):
		var machine := str(d.get("machine", GameState.self_zone))
		if machine != GameState.self_zone and machine != "" and has_zone(machine):
			continue   # another machine's agents are shown as figures on its own island
		var id := str(d.get("id", ""))
		seen[id] = true
		if npcs.has(id) and is_instance_valid(npcs[id]):
			npcs[id].apply(d)
			continue
		var n := NpcAgent.new()
		var st := str(d.get("station", "workshop"))
		var desk := station_point(st)
		var start := desk + Vector3(randf_range(-1.0, 1.0), 0.3, randf_range(-1.0, 1.0))
		if id == "loki":
			start = desk + Vector3(0, 0.3, 1.5)
		n.position = start
		add_child(n)
		n.setup(d, desk, Vector3.ZERO, HOME_RADIUS)
		n.damaged.connect(_on_damaged)
		npcs[id] = n
	for id in npcs.keys():
		if not seen.has(id):
			if is_instance_valid(npcs[id]):
				npcs[id].queue_free()
			npcs.erase(id)


func _sync_monsters() -> void:
	var seen := {}
	for d in GameState.state.get("monsters", []):
		var id := str(d.get("id", ""))
		seen[id] = true
		if monsters.has(id) and is_instance_valid(monsters[id]):
			if monsters[id].alive:
				monsters[id].apply(d)
			continue
		var sp: Dictionary = d.get("spawn", {})
		var zone := str(sp.get("zone", GameState.self_zone))
		if not has_zone(zone):
			zone = GameState.self_zone
		var at := zone_point(zone, float(sp.get("u", 0.5)), float(sp.get("v", 0.5)))
		var mo := Monster.new()
		mo.position = at + Vector3(0, 0.4, 0)
		add_child(mo)
		mo.setup(d, at)
		mo.player = player
		mo.zone = zone
		mo.damaged.connect(_on_damaged)
		mo.died.connect(_on_monster_died)
		monsters[id] = mo
	for id in monsters.keys():
		if not seen.has(id):
			var mo: Monster = monsters[id]
			if is_instance_valid(mo) and mo.alive:
				mo.queue_free()
			monsters.erase(id)


func monsters_alive() -> Array:
	var out: Array = []
	for m in monsters.values():
		if is_instance_valid(m) and m.alive:
			out.append(m)
	return out


func _on_monster_died(a: Actor) -> void:
	var mo := a as Monster
	actor_died.emit(a)
	float_text.emit(a.nameplate_position(), "Defeated!", Color(1.0, 0.85, 0.3))
	_burst(a.global_position + Vector3(0, 0.8, 0), Color(1.0, 0.4, 0.3), 30)
	LokiApi.monster_defeated(mo.data)


func _sync_paintings() -> void:
	var images: Array = []
	for it in GameState.loot_items():
		if str(it.get("show", "")) == "image":
			images.append(it)
		if images.size() >= 5:
			break
	var key := ""
	for it in images:
		key += str(it.get("id", "")) + ";"
	if key == _painting_key:
		return
	_painting_key = key
	# the newest in the middle (above the door), then outwards
	var order := [2, 1, 3, 0, 4]
	for k in paintings.size():
		(paintings[k] as MeshInstance3D).visible = false
	for i in images.size():
		_hang(paintings[order[i]], images[i])


## Forge -> LOKI World: the newest models from Forge (GET /forge/list), loaded from their .glb at runtime, scaled to
## about a metre and turning slowly on the shelf's pedestals. A newer model pushes the oldest off the shelf.
func _on_forge_models(items: Array) -> void:
	_shelf_gen += 1
	var gen := _shelf_gen
	for k in shelf_models.size():
		if shelf_models[k] is Node3D and is_instance_valid(shelf_models[k]):
			(shelf_models[k] as Node3D).queue_free()
		shelf_models[k] = null
	for k in mini(items.size(), shelf_spots.size()):
		var it: Dictionary = items[k]
		var model: Node3D = await LokiApi.forge_model(str(it.get("name", "")))
		if gen != _shelf_gen or model == null:   # a newer list arrived while this one loaded
			if model != null:
				model.queue_free()
			continue
		place_on_shelf(model, k, str(it.get("prompt", it.get("name", ""))))


func place_on_shelf(model: Node3D, k: int, title: String) -> void:
	var holder := Node3D.new()
	holder.name = "ForgeShelf%d" % k
	add_child(holder)
	holder.add_child(model)
	var box := AABB()
	var first := true
	for mi in model.find_children("*", "MeshInstance3D", true, false):
		var b: AABB = (mi as MeshInstance3D).get_aabb()
		b = (mi as MeshInstance3D).transform * b
		box = b if first else box.merge(b)
		first = false
	var size := maxf(box.size.x, maxf(box.size.y, box.size.z))
	var fit := 1.1 / size if size > 0.0001 else 1.0
	model.scale = Vector3.ONE * fit
	model.position = -Vector3(box.get_center().x, box.position.y, box.get_center().z) * fit
	holder.position = shelf_spots[k]
	var label := Label3D.new()
	label.text = title.substr(0, 40)
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	label.font_size = 28
	label.outline_size = 6
	label.position = Vector3(0, box.size.y * fit + 0.35, 0)
	holder.add_child(label)
	shelf_models[k] = holder


func _hang(frame: MeshInstance3D, item: Dictionary) -> void:
	var tex: Texture2D = await LokiApi.creation_texture(item)
	if is_instance_valid(frame) and tex != null:
		frame.material_override = Mats.picture(tex)
		frame.visible = true
		frame.set_meta("item", item)


func _on_presence(players: Array) -> void:
	var seen := {}
	for p in players:
		var machine := str(p.get("machine", ""))
		if machine == "":
			continue
		seen[machine] = true
		if not remotes.has(machine) or not is_instance_valid(remotes[machine]):
			var r := RemotePlayer.new()
			add_child(r)
			r.setup(p, self)
			r.global_position = zone_point(str(p.get("zone", "")), float(p.get("u", 0)), float(p.get("v", 0)))
			remotes[machine] = r
			GameState.notice.emit("%s joined from %s." % [str(p.get("name", "Someone")), machine], Color(0.55, 0.85, 1.0))
		else:
			remotes[machine].apply(p)
	for m in remotes.keys():
		if not seen.has(m):
			if is_instance_valid(remotes[m]):
				remotes[m].queue_free()
			remotes.erase(m)


# ----------------------------------------------------------------- effects

func _on_damaged(a: Actor, amount: int, crit: bool, is_heal: bool) -> void:
	if amount <= 0 and not is_heal:
		return
	var col := Color(1.0, 0.95, 0.4) if crit else Color(1, 1, 1)
	if a == player:
		col = Color(1.0, 0.35, 0.3)
	if is_heal:
		col = Color(0.4, 1.0, 0.5)
	var text := ("+%d" % amount) if is_heal else (("%d!" % amount) if crit else str(amount))
	float_text.emit(a.nameplate_position() + Vector3(randf_range(-0.3, 0.3), 0, 0), text, col)


## Bolt: a glowing orb flies from you to the target; damage lands on arrival.
func spawn_bolt(from: Actor, to: Actor, amount: int, crit: bool) -> void:
	var orb := MeshInstance3D.new()
	orb.mesh = Mats.ball(0.18, 6, 4)
	orb.material_override = Mats.glow(Color(0.65, 0.55, 1.0), 1.2)
	add_child(orb)
	orb.global_position = from.global_position + Vector3(0, 1.3, 0)
	_bolts.append({"node": orb, "to": to, "amount": amount, "crit": crit, "from": from, "t": 0.0})


func level_up_effect() -> void:
	_burst(player.global_position + Vector3(0, 1.0, 0), Color(1.0, 0.85, 0.3), 70)
	if player.model != null:
		player.model.start_emote("cheer")


func _burst(at: Vector3, color: Color, amount: int) -> void:
	var p := CPUParticles3D.new()
	p.one_shot = true
	p.amount = amount
	p.lifetime = 1.2
	p.explosiveness = 0.95
	p.direction = Vector3.UP
	p.spread = 70.0
	p.initial_velocity_min = 2.5
	p.initial_velocity_max = 6.0
	p.gravity = Vector3(0, -6.0, 0)
	p.scale_amount_min = 0.6
	p.scale_amount_max = 1.2
	var cube := BoxMesh.new()
	cube.size = Vector3(0.12, 0.12, 0.12)
	p.mesh = cube
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = color
	p.material_override = mat
	add_child(p)
	p.global_position = at
	p.emitting = true
	get_tree().create_timer(2.0).timeout.connect(p.queue_free)


func _process(delta: float) -> void:
	_day_night(delta)
	var t := Time.get_ticks_msec() / 1000.0
	for h in shelf_models:
		if h is Node3D and is_instance_valid(h):
			(h as Node3D).rotation.y += 0.4 * delta
	for it in _islets:
		var n: Node3D = it["node"]
		n.position.y = float(it["base"]) + sin(t * 0.4 + float(it["phase"])) * 0.6
		n.rotation.y += float(it["spin"]) * delta
	for b in _bolts.duplicate():
		var orb: MeshInstance3D = b["node"]
		var to: Actor = b["to"]
		b["t"] = float(b["t"]) + delta
		if not is_instance_valid(to) or float(b["t"]) > 3.0:
			orb.queue_free()
			_bolts.erase(b)
			continue
		var aim := to.global_position + Vector3(0, 1.0, 0)
		var step := 22.0 * delta
		if orb.global_position.distance_to(aim) <= step:
			to.take_damage(int(b["amount"]), bool(b["crit"]), b["from"])
			_burst(aim, Color(0.7, 0.6, 1.0), 12)
			orb.queue_free()
			_bolts.erase(b)
		else:
			orb.global_position = orb.global_position.move_toward(aim, step)
	# presence: your avatar out to the other machines
	if GameState.mode == "play":
		var pr := player.presence()
		LokiApi.presence_tick(delta, pr, bool(pr["moving"]))
