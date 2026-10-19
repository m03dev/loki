class_name AutoChessArena
extends Node3D
## Self-contained 3D arena scene builder used by the Auto Chess mode.

const COLUMNS: int = 8
const ROWS: int = 6
const CELL_SIZE: float = 2.5

var avatar: Node3D
var camera: Camera3D
var camera_pivot: Node3D
var unit_roots: Array[Node3D] = []
var camera_yaw: float = 0.0
var camera_pitch: float = -0.28
var camera_distance: float = 30.0


func _ready() -> void:
	_build_environment()
	_build_island()
	_build_avatar()
	_build_camera()


func _build_environment() -> void:
	var world_environment := WorldEnvironment.new()
	var environment := Environment.new()
	environment.background_mode = Environment.BG_SKY
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color(0.56, 0.7, 0.88)
	environment.ambient_light_energy = 0.72
	environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	var sky := Sky.new()
	var sky_material := ProceduralSkyMaterial.new()
	sky_material.sky_top_color = Color(0.08, 0.2, 0.39)
	sky_material.sky_horizon_color = Color(0.46, 0.7, 0.82)
	sky_material.ground_bottom_color = Color(0.025, 0.06, 0.1)
	sky_material.ground_horizon_color = Color(0.26, 0.42, 0.44)
	sky.sky_material = sky_material
	environment.sky = sky
	world_environment.environment = environment
	add_child(world_environment)
	var sun := DirectionalLight3D.new()
	sun.rotation = Vector3(deg_to_rad(-52.0), deg_to_rad(-28.0), 0.0)
	sun.light_color = Color(1.0, 0.84, 0.65)
	sun.light_energy = 1.5
	sun.shadow_enabled = true
	add_child(sun)


func _build_island() -> void:
	_add_primitive("Ocean", BoxMesh.new(), Vector3(0, -5, 0), Vector3(180, 2, 180), Color(0.035, 0.19, 0.31))
	_add_primitive("IslandRock", _cylinder_mesh(25, 28), Vector3(0, -1.7, 0), Vector3(1, 1.8, 1), Color(0.19, 0.23, 0.27))
	_add_primitive("IslandGrass", _cylinder_mesh(24, 24), Vector3(0, -0.45, 0), Vector3(1, 0.58, 1), Color(0.19, 0.39, 0.29))
	_add_primitive("ArenaPlatform", _cylinder_mesh(18, 48), Vector3(0, 0, 0), Vector3(1, 0.18, 1), Color(0.27, 0.34, 0.3))
	for x in COLUMNS:
		for z in ROWS:
			var base_color: Color = Color(0.14, 0.31, 0.27) if x < 4 else Color(0.34, 0.2, 0.21)
			var tile_color: Color = base_color.lightened(0.04) if (x + z) % 2 == 0 else base_color.darkened(0.05)
			_add_primitive("Board_%d_%d" % [x, z], BoxMesh.new(), board_position(Vector2i(x, z)), Vector3(2.45, 0.15, 2.45), tile_color)
	_add_primitive("BoardBorder", BoxMesh.new(), Vector3(0, 0.16, 0), Vector3(20.4, 0.16, 15.7), Color(0.48, 0.37, 0.2))
	for index in 8:
		var angle: float = TAU * float(index) / 8.0
		var pillar_position := Vector3(cos(angle) * 16.5, -0.6, sin(angle) * 16.5)
		_add_primitive("RuinPillar_%d" % index, _cylinder_mesh(0.6, 8), pillar_position, Vector3(0.8, 2.6, 0.8), Color(0.3, 0.37, 0.39))
		_add_primitive("PillarCap_%d" % index, BoxMesh.new(), pillar_position + Vector3(0, 1.3, 0), Vector3(1.35, 0.3, 1.35), Color(0.63, 0.49, 0.28))
	for index in 10:
		var angle: float = TAU * float(index) / 10.0
		_add_primitive("Crystal_%d" % index, SphereMesh.new(), Vector3(cos(angle) * 13.8, 0.15, sin(angle) * 13.8), Vector3(0.35, 1.1, 0.35), Color(0.25, 0.76, 0.88))


func _build_avatar() -> void:
	avatar = Node3D.new()
	avatar.name = "ThirdPersonAvatar"
	avatar.position = Vector3(0, 0, 7.5)
	add_child(avatar)
	_add_child_primitive(avatar, "Body", CapsuleMesh.new(), Vector3(0, 1, 0), Vector3(0.72, 1.15, 0.72), Color(0.28, 0.67, 0.91))
	_add_child_primitive(avatar, "Head", SphereMesh.new(), Vector3(0, 2, 0), Vector3(0.57, 0.57, 0.57), Color(0.91, 0.73, 0.55))
	_add_child_primitive(avatar, "Shoulders", SphereMesh.new(), Vector3(0, 1.48, 0), Vector3(1, 0.42, 0.58), Color(0.76, 0.56, 0.23))


func _build_camera() -> void:
	camera_pivot = Node3D.new()
	camera_pivot.name = "CameraPivot"
	add_child(camera_pivot)
	camera = Camera3D.new()
	camera.name = "ThirdPersonCamera"
	camera.fov = 58.0
	camera.current = true
	camera_pivot.add_child(camera)
	update_camera()


func update_camera() -> void:
	if camera == null or camera_pivot == null:
		return
	if avatar != null:
		camera_pivot.position = avatar.position + Vector3(0, 4, 0)
	camera_pivot.rotation = Vector3(camera_pitch, camera_yaw, 0)
	camera.position = Vector3(0, 0, camera_distance)
	camera.look_at(camera_pivot.global_position, Vector3.UP)


func move_avatar(direction: Vector3, delta: float) -> void:
	if avatar == null or direction.length_squared() <= 0.0:
		return
	var world_direction: Vector3 = direction.normalized().rotated(Vector3.UP, camera_yaw)
	avatar.position += world_direction * 5.0 * delta
	avatar.position.x = clampf(avatar.position.x, -10.0, 10.0)
	avatar.position.z = clampf(avatar.position.z, -10.0, 10.0)
	avatar.rotation.y = atan2(world_direction.x, world_direction.z)
	update_camera()


func set_units(units: Array[Dictionary]) -> void:
	for unit_root in unit_roots:
		if is_instance_valid(unit_root):
			unit_root.queue_free()
	unit_roots.clear()
	for unit in units:
		var unit_root := Node3D.new()
		unit_root.name = "Unit_%d" % unit_roots.size()
		unit_root.position = board_position(unit["cell"]) + Vector3(0, 0.35, 0)
		add_child(unit_root)
		var tint: Color = unit["color"]
		_add_child_primitive(unit_root, "Body", CapsuleMesh.new(), Vector3(0, 0.9, 0), Vector3(0.55, 0.85, 0.55), tint)
		_add_child_primitive(unit_root, "Head", SphereMesh.new(), Vector3(0, 1.85, 0), Vector3(0.43, 0.43, 0.43), Color(0.94, 0.77, 0.61))
		var crest_color: Color = Color(0.32, 0.92, 0.53) if not unit.get("enemy", false) else Color(0.98, 0.36, 0.3)
		_add_child_primitive(unit_root, "TeamCrest", SphereMesh.new(), Vector3(0, 2.45, 0), Vector3(0.28, 0.28, 0.28), crest_color)
		unit_roots.append(unit_root)


func update_unit_health(units: Array[Dictionary]) -> void:
	if unit_roots.size() != units.size():
		return
	for index in units.size():
		var unit: Dictionary = units[index]
		var unit_root: Node3D = unit_roots[index]
		var body := unit_root.get_node_or_null("Body") as MeshInstance3D
		if body != null:
			var body_material := body.material_override as StandardMaterial3D
			if body_material != null:
				var ratio: float = clampf(float(unit["hp"]) / maxf(1.0, float(unit["max_hp"])), 0.0, 1.0)
				var unit_color: Color = unit["color"]
				body_material.albedo_color = unit_color.lerp(Color(0.12, 0.12, 0.15), 1.0 - ratio)
		unit_root.visible = float(unit["hp"]) > 0.0


func board_position(cell: Vector2i) -> Vector3:
	return Vector3((float(cell.x) - 3.5) * CELL_SIZE, 0.22, (float(cell.y) - 2.5) * CELL_SIZE)


func _cylinder_mesh(top_radius: float, bottom_radius: float) -> CylinderMesh:
	var mesh := CylinderMesh.new()
	mesh.top_radius = top_radius
	mesh.bottom_radius = bottom_radius
	return mesh


func _add_primitive(node_name: String, mesh: Mesh, position: Vector3, scale: Vector3, color: Color) -> MeshInstance3D:
	return _add_child_primitive(self, node_name, mesh, position, scale, color)


func _add_child_primitive(parent: Node3D, node_name: String, mesh: Mesh, position: Vector3, scale: Vector3, color: Color) -> MeshInstance3D:
	var instance := MeshInstance3D.new()
	instance.name = node_name
	instance.mesh = mesh
	instance.position = position
	instance.scale = scale
	var surface_material := StandardMaterial3D.new()
	surface_material.albedo_color = color
	surface_material.roughness = 0.84
	instance.material_override = surface_material
	parent.add_child(instance)
	return instance
