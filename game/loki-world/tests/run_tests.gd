extends Node
## LOKI World's own headless tests (autoloads are up, unlike a bare --script run):
##   godot --headless --path game/loki-world res://tests/run_tests.tscn
## Prints "N passed, M failed" and exits 1 on any failure. tests/test_godot_world.py runs it
## when a Godot 4 binary is on PATH (or LOKI_GODOT points at one).

var passed := 0
var failed := 0


func check(name_: String, ok: bool, detail: Variant = "") -> void:
	if ok:
		passed += 1
	else:
		failed += 1
		print("FAIL ", name_, "  ", detail)


func _ready() -> void:
	await get_tree().process_frame
	# never the player's saved profile (beaten monsters, XP), however the suite is started - with or without
	# --no-save - so a played game can never make a test fail, and the tests never change the player's save
	GameState.persist = false
	LokiApi.allow_connect = false   # deterministic: run offline, never join a LOKI that happens to be running here
	GameState._load_local()
	_scripts_compile()
	_levels()
	_derive()
	_fake()
	_net_layer()
	await _world()
	print("%d passed, %d failed" % [passed, failed])
	get_tree().quit(1 if failed > 0 else 0)


func _scripts_compile() -> void:
	for dir in ["res://autoload", "res://scripts", "res://scripts/world", "res://scripts/actors", "res://scripts/hud", "res://scripts/net", "res://shaders"]:
		for f in DirAccess.get_files_at(dir):
			if f.ends_with(".gd") or f.ends_with(".gdshader"):
				var res = load(dir.path_join(f))
				var ok: bool = res != null
				if ok and res is GDScript:
					ok = (res as GDScript).can_instantiate()
				check("compiles: " + f, ok)


func _levels() -> void:
	# the same curve as engine/mmo_state.py: round(80 * L^1.55)
	check("xp to level 2 is 80", GameState.xp_to_next(1) == 80, GameState.xp_to_next(1))
	check("xp to level 8", GameState.xp_to_next(7) == int(round(80.0 * pow(7.0, 1.55))))
	check("level_of(0) is 1", GameState.level_of(0)["level"] == 1)
	check("level_of(80) is 2", GameState.level_of(80)["level"] == 2)
	check("level cap 99", GameState.level_of(1e12)["level"] == 99)
	check("npc classes like the engine", GameState.npc_class("researcher")["name"] == "Sage"
			and GameState.npc_class("conductor")["name"] == "Trickster" and GameState.npc_class("builder")["name"] == "Smith")
	check("monster names from errors", GameState.monster_of("timed out after 1800 s")[0] == "Timeout Wraith"
			and GameState.monster_of("HTTP 429 rate limit")[1] == "slime" and GameState.monster_of("???")[0] == "Error Gremlin")
	check("9 hotbar slots", GameState.SKILLS.size() == 9 and GameState.skill_in_slot(9)["id"] == "hearth")
	var roll := GameState.roll_damage(GameState.SKILLS[0])
	check("damage roll is positive", int(roll[0]) > 0)


func _derive() -> void:
	var world := {"self": {"name": "Mac mini", "os": "Darwin"}, "machines": [{"name": "pc", "ok": true, "os": "Windows"}],
		"agents": [{"id": "loki", "name": "LOKI", "role": "conductor", "state": "idle", "station": "hall"},
			{"id": "job-a1", "name": "Researcher", "role": "researcher", "state": "working", "station": "library", "task": "Research: foxes"}],
		"presence": {"players": [], "chat": [], "cursor": 0}}
	var jobs := [
		{"id": "a1", "title": "Research: foxes", "status": "working", "agent": "loki", "created": "2026-10-17 10:00:00"},
		{"id": "b2", "title": "Make an image of a fox", "status": "done", "agent": "loki", "created": "2026-10-17 09:00:00",
			"started": "2026-10-17 09:00:00", "finished": "2026-10-17 09:05:00"},
		{"id": "c3", "title": "Build the page", "status": "failed", "agent": "loki", "error": "timed out after 1800 s",
			"created": "2026-10-17 08:00:00", "finished": Time.get_datetime_string_from_system(false, true)},
	]
	var creations := [{"kind": "images", "show": "image", "path": "images/fox.jpg", "title": "Fox", "t": 1.0}]
	var s := Derive.state(world, jobs, creations, {"turned_in": {}, "beaten": {}, "seen": {}})
	for key in ["profile", "skills", "quests", "monsters", "npcs", "loot", "zones", "presence"]:
		check("derived state has " + key, s.has(key))
	check("3 quests from 3 jobs", s["quests"].size() == 3)
	var by_id := {}
	for q in s["quests"]:
		by_id[q["id"]] = q
	check("working job = active quest", by_id["a1"]["status"] == "active" and by_id["a1"]["kind"] == "research")
	check("done job = complete quest", by_id["b2"]["status"] == "complete" and by_id["b2"]["kind"] == "image")
	check("5 minutes of work = 200 XP", int(by_id["b2"]["xp"]) == 200, by_id["b2"]["xp"])
	check("failed job = a monster", s["monsters"].size() == 1 and s["monsters"][0]["name"] == "Timeout Wraith")
	check("monster spawns on this island", s["monsters"][0]["spawn"]["zone"] == "Mac mini")
	check("loot is the creation, served from /creations/", s["loot"]["items"][0]["url"] == "/creations/images/fox.jpg"
			and s["loot"]["items"][0]["rarity"] == "rare")
	check("npcs keep their stations", s["npcs"].size() == 2 and s["npcs"][1]["station"] == "library")
	check("LOKI gives quests", s["npcs"][0]["quest_giver"] == true)
	var s2 := Derive.state(world, jobs, creations, {"turned_in": {"b2": 1}, "beaten": {"c3": 1}, "seen": {"images/fox.jpg": true}})
	var by2 := {}
	for q in s2["quests"]:
		by2[q["id"]] = q
	check("turned-in quest stays turned in", by2["b2"]["status"] == "turned_in")
	check("beaten monster is gone", s2["monsters"].is_empty() and by2["c3"]["status"] == "beaten")
	check("seen loot is not new", s2["loot"]["items"][0]["new"] == false)


func _fake() -> void:
	var f := FakeWorld.new()
	var s := f.state(GameState.local)
	check("offline state is marked demo", s.get("demo", false) == true)
	check("offline has monsters and quests", s["monsters"].size() >= 1 and s["quests"].size() >= 1)
	check("offline has another machine", s["zones"]["machines"].size() == 1)
	check("offline other player walks there", f.players()[0]["zone"] == s["zones"]["machines"][0]["name"])


func _net_layer() -> void:
	var ep: Dictionary = LokiApi.EP
	for path in ["/health", "/world", "/jobs", "/creations", "/creations/make", "/chat", "/mmo/state", "/mmo/skill",
			"/mmo/quest/turnin", "/mmo/monster/defeat", "/mmo/monster/retry", "/world/presence", "/world/retry"]:
		check("net layer knows " + path, ep.values().has(path))
	check("ports 8767 then 8766", LokiApi.PORTS == [8767, 8766])
	var paths: Array = LokiApi.token_paths()
	var has_checkout := false
	for p in paths:
		if str(p).ends_with("harness_data/app/engine.token"):
			has_checkout = true
	check("token looked for in a checkout's harness_data/app", has_checkout, paths)


func _world() -> void:
	var main: Node = load("res://scenes/main.tscn").instantiate()
	get_tree().root.add_child(main)
	for i in 30:
		await get_tree().physics_frame
	var w = main.world
	check("home island is this machine", w.zones.has(GameState.self_zone) and w.zones[GameState.self_zone]["home"])
	check("another machine has its own island", w.zones.size() >= 2)
	check("agents are NPCs", w.npcs.has("loki") and w.npcs.size() >= 2)
	check("failed jobs are monsters", w.monsters_alive().size() >= 1)
	check("the fox and the rabbits", w.critters.size() == 3 and w.critters[0].kind == "fox")
	# LOKI World is an editable scene (2026-10-18): main.tscn holds the World and the baked home island
	var main_text := FileAccess.get_file_as_string("res://scenes/main.tscn")
	check("main.tscn holds the World and the home island (the editor shows LOKI World)",
		main_text.find('name="World"') >= 0 and main_text.find("res://scenes/home_island.tscn") >= 0)
	check("the island in the game is the scene's (named pieces you can edit)", w.home_island != null
		and w.home_island.get_node_or_null("Hall") != null and w.home_island.get_node_or_null("CreationsHall") != null)
	check("the creations hall's 5 frames and the shelf's 3 spots come from the scene", w.paintings.size() == 5 and w.shelf_spots.size() == 3,
		[w.paintings.size(), w.shelf_spots.size()])
	var lib: Node3D = w.home_island.get_node("Station_library")
	var before: Vector3 = w.station_point("library")
	lib.position += Vector3(2, 0, 0)
	check("move a station in the editor and the agents go to the new place", w.station_point("library").distance_to(before + Vector3(2, 0, 0)) < 0.01,
		[before, w.station_point("library")])
	lib.position -= Vector3(2, 0, 0)
	# Forge -> LOKI World: a .glb (made here with GLTFDocument, as Forge's are) loads at runtime and stands on the shelf
	check("the Forge shelf has its pedestals", w.shelf_spots.size() == w.SHELF_SIZE)
	var src := Node3D.new()
	var mesh := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = Vector3(4, 2, 1)
	mesh.mesh = bm
	src.add_child(mesh)
	mesh.owner = src
	var gdoc := GLTFDocument.new()
	var gst := GLTFState.new()
	gdoc.append_from_scene(src, gst)
	var glb: PackedByteArray = gdoc.generate_buffer(gst)
	src.free()
	var model: Node3D = LokiApi.scene_from_glb(glb)
	check("a Forge .glb loads at runtime", model != null and model.find_children("*", "MeshInstance3D", true, false).size() >= 1)
	check("a broken .glb is refused, not a crash", LokiApi.scene_from_glb(PackedByteArray([1, 2, 3])) == null)
	w.place_on_shelf(model, 0, "a test box")
	var holder: Node3D = w.shelf_models[0]
	check("it stands on the first pedestal", holder != null and holder.position.distance_to(w.shelf_spots[0]) < 0.01)
	check("scaled to about a metre (4 m box -> 1.1 m)", absf(model.scale.x - 1.1 / 4.0) < 0.01, model.scale)
	check("with its name over it", holder.find_children("*", "Label3D", true, false).size() == 1)
	var other := ""
	for z in w.zones.keys():
		if not w.zones[z]["home"]:
			other = z
	var p: Vector3 = w.zone_point(other, 0.5, -0.25)
	var uv: Vector2 = w.zone_uv(other, p)
	check("zone u/v round trip", absf(uv.x - 0.5) < 0.01 and absf(uv.y + 0.25) < 0.01, uv)
	check("zone_at finds the island", w.zone_at(p) == other)
	var pr: Dictionary = w.player.presence()
	for k in ["name", "cls", "lvl", "zone", "u", "v", "y", "ry", "hp", "en", "moving", "emote", "emote_at", "ts"]:
		check("presence has " + k, pr.has(k))
	check("the player stands on the home island", w.zone_at(w.player.global_position) == GameState.self_zone)
	# fight: Bolt the nearest monster until it dies -> XP and loot
	var xp_before := int(GameState.local.get("xp", 0))
	var got_loot := [false]
	GameState.loot_got.connect(func(_items, _t, _r): got_loot[0] = true)
	var mo = w.monsters_alive()[0]
	w.player.global_position = mo.global_position + Vector3(0, 0.5, 3)
	w.player.set_target(mo)
	for i in 600:
		if not mo.alive:
			break
		mo.take_damage(25, false, w.player)
		await get_tree().physics_frame
	for i in 10:
		await get_tree().process_frame
	check("a beaten monster dies", not mo.alive)
	check("beating it gives XP", int(GameState.local.get("xp", 0)) > xp_before)
	check("and loot with the retry offer", got_loot[0])
	# skills: Mend heals, cooldowns run
	w.player.hp = 10.0
	GameState.cooldowns.clear()
	w.player.use_slot(3)
	for i in 90:
		await get_tree().physics_frame
	check("Mend heals", w.player.hp > 10.0)
	check("Mend is on cooldown", GameState.cooldown_left(GameState.skill_in_slot(3)) > 0.0)
	main.queue_free()
