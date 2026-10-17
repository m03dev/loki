class_name Derive
## Builds the game state (the shape of GET /mmo/state, docs/MMO_API.md) from the endpoints every
## LOKI already has, for an engine without the MMO API: GET /world (agents, machines, self,
## presence), GET /jobs (quests and failure monsters) and GET /creations (loot).
## Only real things: a quest is a job, a monster is a failed job, loot is something LOKI made.

const MONSTER_DAYS := 7
const MONSTERS_MAX := 6
const QUESTS_MAX := 60
const QUEST_STATES := {"queued": "active", "starting": "active", "working": "active", "blocked": "active",
		"done": "complete", "failed": "failed", "cancelled": "cancelled"}


static func state(world: Dictionary, jobs: Array, creations: Array, local: Dictionary) -> Dictionary:
	var me: Dictionary = world.get("self", {})
	var machine := str(me.get("name", world.get("machine", "This computer")))
	if machine == "":
		machine = "This computer"
	var turned: Dictionary = local.get("turned_in", {})
	var beaten: Dictionary = local.get("beaten", {})
	var seen: Dictionary = local.get("seen", {})
	var now := Time.get_unix_time_from_system()
	var quests: Array = []
	var monsters: Array = []
	var done_by_role: Dictionary = {}
	var sorted_jobs := jobs.duplicate()
	sorted_jobs.sort_custom(func(a, b): return _stamp(a.get("created")) > _stamp(b.get("created")))
	for job in sorted_jobs:
		if not (job is Dictionary):
			continue
		var id := str(job.get("id", ""))
		var status := str(job.get("status", ""))
		var title := str(job.get("title", ""))
		var role := role_of(job)
		if status == "done":
			done_by_role[role.to_lower()] = int(done_by_role.get(role.to_lower(), 0)) + 1
		var qs: String = QUEST_STATES.get(status, "active")
		if qs == "complete" and turned.has(id):
			qs = "turned_in"
		if qs == "failed" and beaten.has(id):
			qs = "beaten"
		if quests.size() < QUESTS_MAX:
			var minutes := 0.0
			var started := _stamp(job.get("started"))
			var finished := _stamp(job.get("finished"))
			if started > 0.0 and finished > started:
				minutes = (finished - started) / 60.0
			quests.append({"id": id, "title": title, "kind": quest_kind(title), "status": qs, "job_status": status,
					"objective": objective(status, role), "role": role, "giver": "LOKI",
					"created": _stamp(job.get("created")), "started": started, "finished": finished,
					"xp": 100 + mini(200, int(20.0 * minutes)), "bonus_xp": mini(200, int(20.0 * minutes))})
		if status == "failed" and not beaten.has(id) and monsters.size() < MONSTERS_MAX:
			var finished_at := _stamp(job.get("finished"))
			if finished_at == 0.0 or now - finished_at < MONSTER_DAYS * 86400.0:
				monsters.append(monster_for(job, machine))
	var npcs: Array = []
	for a in world.get("agents", []):
		if not (a is Dictionary):
			continue
		var role := str(a.get("role", a.get("name", "")))
		var cls := GameState.npc_class(role if str(a.get("id", "")) != "loki" else "loki")
		var done := int(done_by_role.get(str(a.get("name", "")).to_lower(), 0))
		if str(a.get("id", "")) == "loki":
			done = 0
			for v in done_by_role.values():
				done += int(v)
		var st := str(a.get("state", "idle"))
		npcs.append({"id": str(a.get("id", "")), "name": str(a.get("name", "")), "class": cls,
				"level": GameState.level_of(float(done) * 120.0)["level"], "jobs_done": done,
				"state": st, "station": str(a.get("station", "workshop")), "task": str(a.get("task", "")),
				"quest_giver": str(a.get("id", "")) == "loki", "hp": 0.15 if st == "failed" else 1.0,
				"energy": {"working": 1.0, "waiting": 0.4, "blocked": 0.15}.get(st, 0.6),
				"last_message": str(a.get("last_message", "")), "machine": str(a.get("machine", machine)),
				"role": role, "team": str(a.get("team", ""))})
	var items: Array = []
	for c in creations:
		if not (c is Dictionary):
			continue
		var path := str(c.get("path", ""))
		var kind := str(c.get("kind", "images"))
		items.append({"id": path, "path": path, "title": str(c.get("title", path)), "kind": kind,
				"show": str(c.get("show", "file")), "rarity": GameState.RARITY.get(kind, "common"),
				"url": "/creations/" + path, "t": float(c.get("t", 0)), "new": not seen.has(path)})
	var p := GameState.local_profile(machine)
	var pres: Dictionary = world.get("presence", {"players": [], "chat": [], "cursor": 0})
	return {
		"ok": true, "version": 1, "time": now, "profile": p, "classes": GameState.CLASSES, "skills": GameState.SKILLS,
		"quests": quests, "monsters": monsters, "npcs": npcs,
		"loot": {"items": items, "scrolls": []},
		"zones": {"self": {"name": machine, "os": str(me.get("os", ""))}, "machines": world.get("machines", [])},
		"presence": pres, "stats": world.get("stats", {}),
	}


static func _stamp(v) -> float:
	if v == null:
		return 0.0
	if v is float or v is int:
		return float(v)
	var s := str(v)
	if s.is_valid_float():
		return s.to_float()
	if s.length() >= 19:   # "2026-10-17 10:00:00", local time (engine/workers.py _stamp)
		var utc := Time.get_unix_time_from_datetime_string(s.substr(0, 19).replace(" ", "T"))
		return float(utc) - float(Time.get_time_zone_from_system().get("bias", 0)) * 60.0
	return 0.0


static func role_of(job: Dictionary) -> String:
	var title := str(job.get("title", ""))
	if title.begins_with("Team ") and title.find("·") >= 0:
		return title.split("·", true, 1)[1].split(":", true, 1)[0].strip_edges()
	if str(job.get("agent_id", "")) != "" and title.find(":") >= 0:
		return title.split(":", true, 1)[0].strip_edges().substr(0, 40)
	var agent := str(job.get("agent", ""))
	return "Loki agent" if agent == "loki" or agent == "" else agent


static func quest_kind(title: String) -> String:
	for pair in [["Make an image", "image"], ["Make a short video", "video"], ["Make a small game", "game"],
			["Research:", "research"], ["Retry:", "retry"], ["Team ", "team"]]:
		if title.begins_with(pair[0]):
			return pair[1]
	return "task"


static func objective(status: String, role: String) -> String:
	match status:
		"queued", "starting":
			return "waiting for a free agent"
		"working":
			return "%s is on it" % role
		"blocked":
			return "blocked - answer LOKI in the app"
		"done":
			return "done - bring it to LOKI"
		"failed":
			return "failed - a monster is out there"
		"cancelled":
			return "cancelled"
	return status


## A failure monster for a failed job: its name from the error, a stable spot on this island.
static func monster_for(job: Dictionary, zone: String) -> Dictionary:
	var id := str(job.get("id", ""))
	var error := str(job.get("error", job.get("note", "")))
	var named := GameState.monster_of(error)
	var h := GameState.hash_text(id)
	var lvl := 2 + h % 8
	var angle := float(h % 360) * PI / 180.0
	var r := 0.45 + float((h / 360) % 40) / 100.0
	return {"id": id, "job_id": id, "name": named[0], "kind": named[1], "level": lvl,
			"hp_max": 60 + 18 * lvl, "dmg": [4 + lvl, 8 + lvl], "attack_every_s": 2.0, "aggro_radius": 5.0,
			"leash": 10.0, "speed": 2.4, "xp": 100, "error": error.substr(0, 300), "title": str(job.get("title", "")),
			"finished": _stamp(job.get("finished")), "spawn": {"zone": zone, "u": cos(angle) * r, "v": sin(angle) * r}}
