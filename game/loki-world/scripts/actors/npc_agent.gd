class_name NpcAgent
extends Actor
## One of LOKI's agents as an NPC at its station (GET /mmo/state npcs[], or /world agents):
## a class from its role, a level from the jobs that role finished. It walks to its desk while
## its job is working/waiting/blocked, acts out the work there, and wanders when idle.
## LOKI itself is the quest giver in the hall.

var data: Dictionary = {}
var home := Vector3.ZERO        # where it stands to work (in front of its desk)
var desk := Vector3.ZERO        # the station's desk
var wander_to := Vector3.ZERO
var wander_wait := 0.0
var quest_giver := false
var npc_state := "idle"
var island_center := Vector3.ZERO
var island_radius := 10.0
var _last_line := ""


func setup(d: Dictionary, station_pos: Vector3, center: Vector3, radius: float) -> void:
	setup_body(0.35, 1.7, LAYER_NPC)
	island_center = center
	island_radius = radius
	desk = station_pos
	var inward := (center - station_pos)
	inward.y = 0.0
	home = station_pos + (inward.normalized() * 1.1 if inward.length() > 0.5 else Vector3(0, 0, 1.6))
	wander_to = home
	actor_id = str(d.get("id", ""))
	var cls: Dictionary = d.get("class", {})
	var color := Color.from_string(str(cls.get("color", "#9aa0aa")), Color(0.6, 0.6, 0.65))
	var hat := str(cls.get("hat", ""))
	var gear := str(cls.get("gear", ""))
	if hat == "" or gear == "":
		var guess := GameState.npc_class(str(d.get("role", d.get("name", ""))))
		hat = guess["hat"] if hat == "" else hat
		gear = guess["gear"] if gear == "" else gear
	var is_loki := actor_id == "loki"
	set_model(CharacterModel.person(color, "horns" if is_loki else hat, gear, GameState.hash_text(actor_id) % 3, 1.12 if is_loki else 1.0))
	apply(d)


func apply(d: Dictionary) -> void:
	data = d
	display_name = str(d.get("name", "Agent"))
	var cls: Dictionary = d.get("class", {})
	level = int(d.get("level", 1))
	quest_giver = bool(d.get("quest_giver", false))
	npc_state = str(d.get("state", "idle"))
	name_color = Color.from_string(str(cls.get("color", "#9aa0aa")), Color(0.8, 0.8, 0.8))
	title_line = "<%s>" % str(cls.get("name", "Adventurer"))
	var task := str(d.get("task", ""))
	if npc_state in ["working", "waiting", "blocked"] and task != "":
		title_line += "  " + task.substr(0, 40)
	hp_max = 100.0
	hp = 100.0 * float(d.get("hp", 1.0))
	en_max = 100.0
	en = 100.0 * float(d.get("energy", 0.6))
	interact_hint = "Talk" if not quest_giver else "Quests"
	var line := str(d.get("last_message", ""))
	if line != "" and line != _last_line:
		_last_line = line
		say(line, 6.0)
	if npc_state == "blocked":
		bubble = "!"
		bubble_t = 2.0
	if npc_state == "done" and model != null and model.emote == "":
		model.start_emote("cheer")


func busy() -> bool:
	return npc_state in ["working", "waiting", "blocked"]


func _physics_process(delta: float) -> void:
	_tick_bubble(delta)
	var target := home if busy() or quest_giver else wander_to
	var to := target - global_position
	to.y = 0.0
	var wish := Vector3.ZERO
	if to.length() > 0.45:
		wish = to.normalized()
	elif not busy() and not quest_giver:
		wander_wait -= delta
		if wander_wait <= 0.0:
			wander_wait = randf_range(3.0, 9.0)
			var a := randf() * TAU
			var r := randf_range(0.25, 0.75) * island_radius
			wander_to = island_center + Vector3(cos(a) * r, 0, sin(a) * r)
	var speed := _physics_move(delta, wish, 2.2)
	if wish != Vector3.ZERO:
		face_towards(wish, delta, 6.0)
	elif busy():
		# at the desk: face it and work with both hands
		face_towards(desk - global_position, delta, 4.0)
	elif quest_giver:
		face_towards(island_center - global_position, delta, 3.0)
	if model != null:
		model.casting = busy() and wish == Vector3.ZERO and npc_state == "working"
		model.tick(delta, speed, not is_on_floor())
