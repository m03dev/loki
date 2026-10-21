class_name Lobby
extends Node3D
## Lobby scene for the reimagined Voxel Lobby project.
## Provides a starting point for players to connect and access 3D modeling/sculpting tools.
## Multiplayer setup: P2P ready structure (Godot @rpc would go here, currently single-player local).

const MAX_PLAYERS := 4
const LOBBY_NAME := "Voxel Lobby"

var local_player_name := "Player"
var selected_character := "Human"
var is_host := false

func _ready() -> void:
	# Setup lobby UI and wait for connections
	print("Voxel Lobby initialized")
	setup_environment()

func setup_environment() -> void:
	# Configure environment for modeling
	var env = Environment.new()
	env.background_mode = Environment.BG_SKY
	env.ambient_light_color = Color(0.5, 0.5, 0.5)
	env.ambient_light_energy = 0.8
	get_tree().root.environment = env

	# Create a floor plane for the modeling area
	var floor_mesh := PlaneMesh.new()
	floor_mesh.size = Vector3(50, 1, 50)
	floor_mesh.subdivide_width = 50
	floor_mesh.subdivide_height = 50
	
	var floor_material := StandardMaterial3D.new()
	floor_material.albedo_color = Color(0.2, 0.2, 0.2)
	floor_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	
	var floor_instance := MeshInstance3D.new()
	floor_instance.mesh = floor_mesh
	floor_instance.material_override = floor_material
	floor_instance.position = Vector3(0, -0.5, 0)
	add_child(floor_instance)

	# Add a sky
	var sky := Sky.new()
	sky.radiance_size = Sky.RADIANCE_SIZE_64
	env = Environment.new()
	env.sky = sky
	env.background_mode = Environment.BG_SKY
	get_tree().root.environment = env

func on_host_button_pressed() -> void:
	is_host = true
	print("Hosting lobby session...")
	# TODO: Initialize P2P host connection
	# @rpc multiplayer setup would go here

func on_join_button_pressed() -> void:
	print("Joining lobby session...")
	# TODO: Join P2P session
	# @rpc multiplayer setup would go here

func on_start_modeling_button_pressed() -> void:
	if is_host or not is_instance_valid(get_tree().get_first_node_by_classname("Player")):
		start_modeling_session()
	else:
		print("Please host or wait for a player to join.")

func start_modeling_session() -> void:
	# Transition to modeling mode
	print("Starting 3D modeling session...")
	# TODO: Load modeling tools (gator_model_studio)
	# TODO: Switch to modeling scene

func _physics_process(delta: float) -> void:
	# Lobby update logic
	pass