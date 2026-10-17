class_name FakeWorld
extends RefCounted
## OFFLINE mode: LOKI is not running, so the game plays a small made-up world - clearly marked
## "demo" in the HUD - with the same shape as GET /mmo/state. Nothing here ever reaches LOKI.

var t := 0.0
var quests: Array = []
var monsters: Array = []
var _beaten: Dictionary = {}
var _n := 0
var me := "This computer"
var other := "pc"


func _init() -> void:
	var host := OS.get_environment("COMPUTERNAME")
	if host == "":
		host = OS.get_environment("HOSTNAME")
	if host != "":
		me = host.to_lower()
	other = "mac-mini" if OS.get_name() == "Windows" else "pc"
	quests = [
		{"id": "demo-1", "title": "Make an image of a red fox in studio light", "kind": "image", "status": "complete",
				"job_status": "done", "objective": "done - bring it to LOKI", "role": "Loki agent", "giver": "LOKI", "xp": 140},
		{"id": "demo-2", "title": "Research: the best free image models", "kind": "research", "status": "active",
				"job_status": "working", "objective": "Researcher is on it", "role": "Researcher", "giver": "LOKI", "xp": 100},
		{"id": "demo-3", "title": "Team 9f8e - Builder: build a landing page", "kind": "team", "status": "failed",
				"job_status": "failed", "objective": "failed - a monster is out there", "role": "Builder", "giver": "LOKI", "xp": 100},
		{"id": "demo-4", "title": "Make a small game where the fox dodges acorns", "kind": "game", "status": "failed",
				"job_status": "failed", "objective": "failed - a monster is out there", "role": "Loki agent", "giver": "LOKI", "xp": 100},
	]
	monsters = [
		_monster("demo-3", "Syntax Golem", "golem", 4, "SyntaxError: unexpected token '}' in order.js", "Team 9f8e - Builder: build a landing page", 0.55, -0.35),
		_monster("demo-4", "Timeout Wraith", "wraith", 3, "timed out after 1800 s", "Make a small game where the fox dodges acorns", -0.6, 0.45),
	]


func _monster(id: String, name_: String, kind: String, lvl: int, error: String, title: String, u: float, v: float) -> Dictionary:
	return {"id": id, "job_id": id, "name": name_, "kind": kind, "level": lvl, "hp_max": 60 + 18 * lvl,
			"dmg": [4 + lvl, 8 + lvl], "attack_every_s": 2.0, "aggro_radius": 5.0, "leash": 10.0, "speed": 2.4, "xp": 100,
			"error": error, "title": title, "finished": 0, "spawn": {"zone": me, "u": u, "v": v}}


func tick(delta: float) -> void:
	t += delta
	for q in quests:
		if q["status"] == "active" and q.has("done_at") and t >= float(q["done_at"]):
			q["status"] = "complete"
			q["job_status"] = "done"
			q["objective"] = "done - bring it to LOKI"


func state(local: Dictionary) -> Dictionary:
	var live: Array = []
	for m in monsters:
		if not _beaten.has(m["id"]) and not local.get("beaten", {}).has(m["id"]):
			live.append(m)
	var shown: Array = []
	for q in quests:
		var c: Dictionary = q.duplicate()
		if c["status"] == "complete" and local.get("turned_in", {}).has(c["id"]):
			c["status"] = "turned_in"
		if c["status"] == "failed" and (_beaten.has(c["id"]) or local.get("beaten", {}).has(c["id"])):
			c["status"] = "beaten"
		shown.append(c)
	var working := 0
	for q in shown:
		if q["status"] == "active":
			working += 1
	var npcs := [
		_npc("loki", "LOKI", "loki", "working" if working > 0 else "idle", "hall", 9, "Ask me anything - or bring me finished quests."),
		_npc("job-demo-2", "Researcher", "researcher", "working", "library", 4, "reading three papers about image models"),
		_npc("job-demo-5", "Builder", "builder", "idle", "workshop", 6, ""),
		_npc("job-demo-6", "Tester", "tester", "waiting", "test bench", 3, "waiting for the build"),
		_npc("job-demo-7", "Reviewer", "reviewer", "idle", "review desk", 5, ""),
	]
	var items: Array = []
	for k in 5:
		var titles := ["Red fox in studio light", "A fox asleep in the snow", "Floating islands at dawn", "Crystal cave", "LOKI's hall"]
		items.append({"id": "demo/%d" % k, "title": titles[k], "kind": "images", "show": "image",
				"rarity": ["rare", "rare", "epic", "uncommon", "legendary"][k], "url": "", "t": 0, "new": k == 0})
	return {
		"ok": true, "version": 1, "time": Time.get_unix_time_from_system(),
		"profile": GameState.local_profile(me), "classes": GameState.CLASSES, "skills": GameState.SKILLS,
		"quests": shown, "monsters": live, "npcs": npcs,
		"loot": {"items": items, "scrolls": []},
		"zones": {"self": {"name": me, "os": OS.get_name()}, "machines": [{"name": other, "ok": true, "os": "Windows" if other == "pc" else "Darwin", "working": 2}]},
		"presence": {"players": players(), "chat": [], "cursor": 0},
		"demo": true,
	}


func _npc(id: String, name_: String, role: String, st: String, station: String, lvl: int, task: String) -> Dictionary:
	return {"id": id, "name": name_, "class": GameState.npc_class(role), "level": lvl, "jobs_done": lvl * 3,
			"state": st, "station": station, "task": task, "quest_giver": id == "loki",
			"hp": 1.0, "energy": {"working": 1.0, "waiting": 0.4}.get(st, 0.6), "last_message": task,
			"machine": me, "role": role}


## The owner on the other machine, walking a slow circle on its island (demo only).
func players() -> Array:
	var a := t * 0.25
	return [{"machine": other, "age": 0.2, "name": "Mohamed", "cls": "Warrior", "lvl": 5, "zone": other,
			"u": cos(a) * 0.45, "v": sin(a) * 0.45, "y": 0.0, "ry": atan2(-sin(a), cos(a)), "hp": 1.0, "en": 1.0,
			"moving": true, "emote": "", "emote_at": 0, "ts": int(Time.get_unix_time_from_system() * 1000.0), "color": "", "target": ""}]


func start_quest(kind: String, text: String) -> void:
	_n += 1
	quests.push_front({"id": "demo-new-%d" % _n, "title": text, "kind": kind, "status": "active", "job_status": "working",
			"objective": "Loki agent is on it", "role": "Loki agent", "giver": "LOKI", "xp": 100, "done_at": t + 20.0})


func turned_in(_ids: Array) -> void:
	pass


func beaten(id: String) -> void:
	_beaten[id] = true


func loki_reply(text: String) -> String:
	return "I'm not running right now (this is the demo world). Start LOKI and ask me again: \"%s\"" % text.substr(0, 80)
