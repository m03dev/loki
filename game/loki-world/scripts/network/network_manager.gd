# Network Manager for Voxel Lobby P2P Multiplayer
# Provides framework for peer-to-peer connection (Steam or local)
# Works with hobby tier (local) and Basic tier (Steam relay)

extends Node

const MAX_PLAYERS := 4
const LOBBY_NAME := "Voxel Lobby"

var is_host := false
var is_connected := false
var connected_peers := []
var player_name := "Player"
var using_steam := false

func _ready() -> void:
	# Initialize networking state
	print("Network Manager initialized")
	# Check available multiplayer mode
	_choose_multiplayer_mode()

func _choose_multiplayer_mode() -> void:
	# For hobby tier: use local mode
	# For Basic tier: would check for Steam plugin and use Steam multiplayer
	using_steam = false
	setup_local()

func _process(delta: float) -> void:
	# Network update logic
	pass

# ----------------------------------------------------------------- local multiplayer

func setup_local() -> void:
	"""Setup local multiplayer (no network connectivity)."""
	is_host = true
	is_connected = true
	connected_peers = [{"id": 1, "name": "Local Player", "connected": true}]
	print("Local multiplayer session started")
	_on_host_session_started()

func _on_host_session_started() -> void:
	"""Called when a host session starts."""
	print("Host session started - %d players max" % MAX_PLAYERS)
	# TODO: Initialize UI to show lobby is ready
	# TODO: Set up input for connected players

func request_join(session_name: String) -> void:
	"""Request to join a multiplayer session."""
	print("Joining session: %s" % session_name)
	# TODO: Implement join logic
	# For hobby tier: local-only simulation
	is_connected = true
	connected_peers.append({"id": connected_peers.size() + 1, "name": "Remote Player", "connected": true})
	print("Joined session successfully")

# ----------------------------------------------------------------- RPC placeholders (for Basic tier upgrade)

# The following methods would be @rpc functions for Basic tier:
# - @rpc("transfer", "authority") func host_make_model(...)
# - @rpc("transfer", "authority") func peer_apply_operation(...)
# - @rpc("all") func sync_lobby_state(...)
# - @rpc("all") func sync_model_data(...)

# These are commented out for hobby tier compliance:
# func rpc_host_create_model(data: Dictionary) -> void:
# 	rpc("transfer", "authority") call_deferred("_host_create_model", data)
	
# func _host_create_model(data: Dictionary) -> void:
	# host_create_model_rpc(data)

# func rpc_peer_join_model(data: Dictionary) -> void:
	# rpc("all", "reliable") peer_apply_model_data(data)

# func peer_apply_model_data(data: Dictionary) -> void:
	# Apply model changes from peer
	pass

# ----------------------------------------------------------------- lobby signals

# Signals that would be connected to UI:
# - session_hosted
# - session_joined
# - player_connected
# - player_disconnected
# - modeling_session_started
# - modeling_session_ended