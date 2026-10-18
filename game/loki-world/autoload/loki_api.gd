extends Node
## LokiApi (autoload): the only place LOKI World talks to LOKI's engine (engine/loki_bridge.py).
##
## Connecting (docs/MMO_API.md section 1):
##   web build inside LOKI's window - same origin as the page; the token comes in the page URL
##     fragment (#token=...), exactly as app/ui gets it (or sessionStorage "loki-token").
##   desktop build - http://127.0.0.1:8767 (the app) then :8766 (a command-line engine); the token
##     is read from LOKI's state folder (<data>/app/engine.token, app/loki_app.py read_token()),
##     or given with --token / --token-file / LOKI_TOKEN, or pasted in the Pair window.
##   no engine - OFFLINE mode: a small made-up world (fake data) so the game always runs; it keeps
##     looking for LOKI every 10 s.
##
## Endpoints used today (every LOKI has them): GET /health, /world, /jobs, /creations,
## /creations/<kind>/<file>; POST /jobs, /creations/make, /chat.
## HOOKS for the engine's MMO API (docs/MMO_API.md - the engine answers them once that work is
## merged; until then the game derives the same state from the endpoints above): GET /mmo/state,
## POST /mmo/skill, /mmo/quest/turnin, /mmo/monster/defeat, /mmo/monster/retry, /mmo/note,
## /mmo/profile, GET+POST /world/presence, POST /world/retry. A 404 on a hook switches it off.

signal connected(base_url: String, source: String)
signal went_offline(reason: String)
## Forge's models changed (GET /forge/list): the world's Forge shelf shows the newest (owner 2026-10-18: everything
## LOKI makes should show up everywhere - a model made in Forge stands in LOKI World)
signal forge_models_changed(items: Array)

const PORTS := [8767, 8766]
const EP := {
	"health": "/health", "world": "/world", "jobs": "/jobs", "creations": "/creations",
	"creation_file": "/creations/",   # + <kind>/<file>
	"make": "/creations/make", "chat": "/chat", "models": "/models",
	"forge_list": "/forge/list", "forge_file": "/forge/file/",   # + <name>.glb
	# ---- hooks: the engine's MMO API (docs/MMO_API.md) ----
	"mmo_state": "/mmo/state", "mmo_skill": "/mmo/skill", "mmo_accept": "/mmo/quest/accept",
	"mmo_turnin": "/mmo/quest/turnin", "mmo_defeat": "/mmo/monster/defeat", "mmo_retry": "/mmo/monster/retry",
	"mmo_note": "/mmo/note", "mmo_profile": "/mmo/profile",
	"presence": "/world/presence", "retry": "/world/retry",
}
## The same words as engine/mmo_state.py action_prompt (Settings > Creations), for a LOKI action
## sent as a plain POST /jobs when the engine has no /mmo/skill yet.
const ACTION_PROMPTS := {
	"image": "Make an image of %s. Save it in images/ and say where it is.",
	"video": "Make a short video of: %s. Save it in videos/ and say where it is.",
	"game": "Make a small game with LOKI's Pixel Engine (read game_engine_guide first): %s. Save it as games/<short-name>/game.js so it shows in Play.",
	"research": "Research: %s. Find good sources, write what you learned to research/<short-name>.md with the links, and give me a short summary.",
	"build": "%s",
}
const STATE_EVERY := 3.0
const WORLD_EVERY := 3.0
const CREATIONS_EVERY := 15.0
const FORGE_EVERY := 15.0
const RETRY_EVERY := 10.0

var base_url := ""
var token := ""
var offline := true
var is_web := false
var has_mmo := true          # the /mmo/* hooks answer (switched off on the first 404)
var has_presence := true     # /world/presence answers
var presence_cursor := 0
var last_world: Dictionary = {}
var last_jobs: Array = []
var last_creations: Array = []
var fake: FakeWorld = null
var _timers := {"state": 0.0, "creations": 0.0, "retry": 0.0, "presence": 0.0, "forge": 0.0}
var forge_models: Array = []
var _forge_key := ""
var _model_cache := {}
var _busy := {}
var _texture_cache: Dictionary = {}
var _presence_pending := ""
var _started := false


func _ready() -> void:
	is_web = OS.has_feature("web")
	fake = FakeWorld.new()


## Called by main.gd once the scene is up.
func start() -> void:
	if _started:
		return
	_started = true
	await connect_engine()


# ----------------------------------------------------------------- connecting

var _connecting := false


func connect_engine() -> bool:
	if _connecting:          # the retry timer fired while a slow first check was still waiting: one at a time
		return not offline
	_connecting = true
	var ok := await _connect_engine()
	_connecting = false
	return ok


func _connect_engine() -> bool:
	var candidates := _base_candidates()
	if token == "":
		token = read_token()
	var engine_seen := false
	var page := _js_location("origin") if is_web else ""
	for base in candidates:
		# The page's own LOKI gets 12 s and a second try: right after the 39 MB engine starts, the page is busy and
		# a 3 s check timed out (HTTPRequest result 13), so the game showed the made-up demo world although LOKI was
		# right there (found 2026-10-18 with the first real web export).
		var wait := 12.0 if base == page else 3.0
		var r := await _request("GET", base + EP["health"], null, wait)
		if base == page and r["status"] == 0:
			r = await _request("GET", base + EP["health"], null, wait)
		# the bridge checks the token before the route: any answer but 401/403 means "you are in"
		if r["status"] != 0 and r["status"] != 401 and r["status"] != 403:
			base_url = base
			offline = false
			await refresh_state()
			connected.emit(base_url, GameState.source)
			GameState.say("system", "", "Connected to LOKI at %s." % base_url, Color(0.5, 1.0, 0.8))
			return true
		if r["status"] == 401:
			engine_seen = true
			var again := read_token()   # the token changes every time LOKI starts: read it again
			if again != "" and again != token:
				token = again
				var r2 := await _request("GET", base + EP["health"], null, 3.0)
				if r2["status"] != 0 and r2["status"] != 401 and r2["status"] != 403:
					base_url = base
					offline = false
					await refresh_state()
					connected.emit(base_url, GameState.source)
					return true
	go_offline("LOKI is running but this game has no valid token - pair it." if engine_seen else "LOKI is not running here.")
	if engine_seen:
		GameState.need_pair.emit("LOKI is running, but this game needs its token to join.")
	return false


func go_offline(reason: String) -> void:
	var was_offline := offline
	offline = true
	base_url = ""
	GameState.apply_state(fake.state(GameState.local), "offline")
	if not was_offline or not _timers.has("announced"):
		_timers["announced"] = 1.0
		GameState.say("system", "", "Offline: %s Playing a demo world until LOKI answers." % reason, Color(1.0, 0.75, 0.4))
	went_offline.emit(reason)


## Pair: use a token pasted by the player (or a path to engine.token).
func pair(value: String) -> void:
	var v := value.strip_edges()
	if v.ends_with("engine.token") or v.find("/") >= 0 or v.find("\\") >= 0:
		token = _read_file(v)
	else:
		token = v
	await connect_engine()


func _base_candidates() -> Array:
	var out: Array = []
	var arg_url := _arg("--loki-url")
	if arg_url != "":
		out.append(arg_url.trim_suffix("/"))
	if is_web:
		var origin := _js_location("origin")
		if origin.begins_with("http"):
			out.append(origin)
	for port in PORTS:
		out.append("http://127.0.0.1:%d" % port)
	return out


## The engine token: page fragment (web), command line, environment, then LOKI's state folder.
func read_token() -> String:
	if is_web:
		var hash_text := _js_location("hash")
		var re := RegEx.create_from_string("(?:^|[#&])token=([^&]+)")
		var m := re.search(hash_text)
		if m != null:
			return m.get_string(1).uri_decode()
		var stored := _js_session("loki-token")
		if stored != "":
			return stored
		return ""
	var t := _arg("--token")
	if t != "":
		return t
	var tf := _arg("--token-file")
	if tf != "":
		return _read_file(tf)
	if OS.get_environment("LOKI_TOKEN") != "":
		return OS.get_environment("LOKI_TOKEN")
	for path in token_paths():
		var got := _read_file(path)
		if got != "":
			return got
	return ""


## Where app/loki_app.py keeps engine.token: <LOKI_DATA>/app, a checkout's harness_data/app
## (this repo when run from game/loki-world, ~/Documents/loki on the owner's machines), or a
## packaged LOKI's per-user folder.
func token_paths() -> Array:
	var out: Array = []
	var data := OS.get_environment("LOKI_DATA")
	if data != "":
		out.append(data.path_join("app").path_join("engine.token"))
	var here := ProjectSettings.globalize_path("res://")
	if here != "" and not here.begins_with("res://"):
		out.append(here.path_join("../../harness_data/app/engine.token").simplify_path())
	var exe_dir := OS.get_executable_path().get_base_dir()
	out.append(exe_dir.path_join("../harness_data/app/engine.token").simplify_path())
	var home := OS.get_environment("USERPROFILE") if OS.get_name() == "Windows" else OS.get_environment("HOME")
	if home != "":
		out.append(home.path_join("Documents/loki/harness_data/app/engine.token"))
		out.append(home.path_join("Loki/harness_data/app/engine.token"))
	match OS.get_name():
		"Windows":
			var lad := OS.get_environment("LOCALAPPDATA")
			if lad != "":
				out.append(lad.path_join("Loki/app/engine.token"))
		"macOS":
			if home != "":
				out.append(home.path_join("Library/Application Support/Loki/app/engine.token"))
		_:
			if home != "":
				out.append(home.path_join(".local/share/loki/app/engine.token"))
	return out


func _read_file(path: String) -> String:
	if path == "" or not FileAccess.file_exists(path):
		return ""
	var f := FileAccess.open(path, FileAccess.READ)
	return f.get_as_text().strip_edges() if f != null else ""


func _arg(name: String) -> String:
	for a in OS.get_cmdline_user_args() + OS.get_cmdline_args():
		if a.begins_with(name + "="):
			return a.substr(name.length() + 1)
	return ""


func _js_location(field: String) -> String:
	if not is_web:
		return ""
	var win = JavaScriptBridge.get_interface("window")
	if win == null:
		return ""
	return str(win.location[field])


func _js_session(key: String) -> String:
	if not is_web:
		return ""
	var store = JavaScriptBridge.get_interface("sessionStorage")
	if store == null:
		return ""
	var v = store.getItem(key)
	return "" if v == null else str(v)


# ----------------------------------------------------------------- polling

func _process(delta: float) -> void:
	if not _started:
		return
	for k in _timers.keys():
		_timers[k] = float(_timers[k]) - delta
	if offline:
		fake.tick(delta)
		if _timers["state"] <= 0.0:
			_timers["state"] = STATE_EVERY
			GameState.apply_state(fake.state(GameState.local), "offline")
		if _timers["retry"] <= 0.0 and not _busy.get("connect", false):
			_timers["retry"] = RETRY_EVERY
			_busy["connect"] = true
			_retry_connect()
		return
	if _timers["state"] <= 0.0 and not _busy.get("state", false):
		_timers["state"] = STATE_EVERY
		refresh_state()
	if _timers["forge"] <= 0.0 and not _busy.get("forge", false):
		_timers["forge"] = FORGE_EVERY
		refresh_forge()


## Forge's models (newest first) -> forge_models_changed when the list is different.
func refresh_forge() -> void:
	_busy["forge"] = true
	var r := await _request("GET", base_url + EP["forge_list"])
	_busy["forge"] = false
	if r["status"] != 200 or not (r["data"] is Dictionary):
		return
	var items: Array = r["data"].get("items", [])
	var key := ""
	for it in items.slice(0, 6):
		key += "%s@%s;" % [str(it.get("name", "")), str(it.get("t", ""))]
	if key == _forge_key:
		return
	_forge_key = key
	forge_models = items
	forge_models_changed.emit(items)


## A .glb's bytes -> its scene (GLTFDocument, at runtime), or null.
static func scene_from_glb(bytes: PackedByteArray) -> Node3D:
	if bytes.is_empty():
		return null
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	if doc.append_from_buffer(bytes, "", st) != OK:
		return null
	return doc.generate_scene(st) as Node3D


## One Forge model as a scene, loaded at runtime from its .glb (GLTFDocument); null when it cannot be read.
func forge_model(name: String) -> Node3D:
	if _model_cache.has(name):
		var cached = _model_cache[name]
		return (cached as PackedScene).instantiate() if cached is PackedScene else null
	var r := await _request("GET", base_url + EP["forge_file"] + name.uri_encode(), null, 30.0, true)
	var bytes: PackedByteArray = r.get("bytes", PackedByteArray())
	var scene := scene_from_glb(bytes)
	if scene == null:
		_model_cache[name] = null
		return null
	var packed := PackedScene.new()
	for c in scene.find_children("*", "", true, false):
		c.owner = scene
	if packed.pack(scene) == OK:
		_model_cache[name] = packed
	return scene as Node3D


func _retry_connect() -> void:
	await connect_engine()
	_busy["connect"] = false


## One refresh: the engine's /mmo/state, or the derived state from /world + /jobs + /creations.
func refresh_state() -> void:
	_busy["state"] = true
	if has_mmo:
		var r := await _request("GET", base_url + EP["mmo_state"])
		if r["status"] == 200 and r["data"] is Dictionary:
			GameState.apply_state(r["data"], "engine")
			_busy["state"] = false
			_after_state(r["data"])
			return
		if r["status"] == 404:
			has_mmo = false
			GameState.say("system", "", "This LOKI has no MMO API yet: the game reads its jobs and creations directly.", Color(0.7, 0.8, 1.0))
		elif r["status"] == 0:
			_busy["state"] = false
			go_offline("LOKI stopped answering.")
			return
		elif r["status"] == 401:
			_busy["state"] = false
			token = read_token()
			return
	var w := await _request("GET", base_url + EP["world"])
	if w["status"] == 0:
		_busy["state"] = false
		go_offline("LOKI stopped answering.")
		return
	if w["status"] == 401:
		token = read_token()
		_busy["state"] = false
		return
	if w["data"] is Dictionary:
		last_world = w["data"]
	var j := await _request("GET", base_url + EP["jobs"])
	if j["data"] is Dictionary:
		last_jobs = j["data"].get("jobs", [])
	if _timers["creations"] <= 0.0:
		_timers["creations"] = CREATIONS_EVERY
		var c := await _request("GET", base_url + EP["creations"])
		if c["data"] is Dictionary:
			last_creations = c["data"].get("items", [])
	var derived := Derive.state(last_world, last_jobs, last_creations, GameState.local)
	GameState.apply_state(derived, "derived")
	_after_state(derived)
	_busy["state"] = false


func _after_state(s: Dictionary) -> void:
	var pres: Dictionary = s.get("presence", {})
	if not has_presence and pres.has("players"):
		_take_presence(pres)


# ----------------------------------------------------------------- presence (hook)

## The player's avatar out, the other machines' avatars and chat back (POST /world/presence).
## world.gd calls this every frame; it sends every 150 ms while moving, every 1 s standing.
func presence_tick(delta: float, player: Dictionary, moving: bool) -> void:
	_timers["presence"] = float(_timers.get("presence", 0.0))
	if _presence_pending == "" and _timers["presence"] > 0.0:
		return
	_timers["presence"] = 0.15 if moving else 1.0
	if offline:
		GameState.presence_players = fake.players()
		GameState.presence_changed.emit(GameState.presence_players)
		if _presence_pending != "":
			GameState.say("say", str(player.get("name", "You")), _presence_pending, Color.WHITE)
			_presence_pending = ""
		return
	if not has_presence or _busy.get("presence", false):
		return
	_busy["presence"] = true
	var body := {"player": player, "after": presence_cursor}
	var line := _presence_pending
	if line != "":
		body["chat"] = line
		_presence_pending = ""
	var r := await _request("POST", base_url + EP["presence"], body, 5.0)
	_busy["presence"] = false
	if r["status"] == 404:
		has_presence = false
		if line != "":
			GameState.say("say", str(player.get("name", "You")), line, Color.WHITE)
		return
	if r["status"] == 200 and r["data"] is Dictionary:
		_take_presence(r["data"])


func _take_presence(d: Dictionary) -> void:
	GameState.presence_players = d.get("players", [])
	GameState.presence_changed.emit(GameState.presence_players)
	for line in d.get("chat", []):
		var seq := int(line.get("seq", 0))
		if seq != 0 and seq <= presence_cursor:
			continue
		var who := "%s (%s)" % [str(line.get("from", "?")), str(line.get("machine", ""))]
		GameState.say("say", who, str(line.get("text", "")), Color(0.95, 0.95, 0.85))
	presence_cursor = maxi(presence_cursor, int(d.get("cursor", presence_cursor)))


## Say something in the world chat (other players see it through presence).
func say_to_players(text: String) -> void:
	_presence_pending = text.substr(0, 200)
	_timers["presence"] = 0.0


# ----------------------------------------------------------------- actions

## Talk to LOKI (POST /chat). Answers come back as chat lines in the LOKI channel.
func chat_with_loki(text: String) -> void:
	GameState.say("loki", "You", text, Color(0.75, 0.95, 1.0))
	if offline:
		await get_tree().create_timer(0.8).timeout
		GameState.say("loki", "LOKI", fake.loki_reply(text), Color(0.4, 1.0, 0.9))
		return
	var r := await _request("POST", base_url + EP["chat"], {"message": text}, 0.0)
	if r["status"] == 200 and r["data"] is Dictionary:
		var reply := str(r["data"].get("response", "")).strip_edges()
		GameState.say("loki", "LOKI", reply if reply != "" else "(no answer)", Color(0.4, 1.0, 0.9))
	else:
		GameState.say("loki", "LOKI", "(could not answer: %s)" % _error_of(r), Color(1.0, 0.5, 0.4))


## A hotbar LOKI action (make a picture, research, build, video, game): starts a REAL job.
func loki_action(skill_id: String, text: String) -> void:
	if offline:
		fake.start_quest(skill_id, text)
		GameState.notice.emit("Quest started (demo): %s" % text, Color(1.0, 0.85, 0.3))
		return
	var r: Dictionary
	if has_mmo:
		r = await _request("POST", base_url + EP["mmo_skill"], {"skill": skill_id, "text": text})
		if r["status"] == 404:
			has_mmo = false
	if not has_mmo:
		if skill_id == "image":
			r = await _request("POST", base_url + EP["make"], {"prompt": text})
		else:
			var prompt: String = ACTION_PROMPTS.get(skill_id, "%s") % text
			r = await _request("POST", base_url + EP["jobs"], {"prompt": prompt, "backend": "local", "agent": "loki", "title": prompt.substr(0, 80)})
	if r["status"] == 200:
		GameState.notice.emit("LOKI took the quest: %s" % text, Color(1.0, 0.85, 0.3))
		GameState.bump_stat("casts")
	else:
		GameState.notice.emit("LOKI said no: %s" % _error_of(r), Color(1.0, 0.45, 0.4))
	refresh_soon()


## Hand finished quests to LOKI for XP (and the loot made meanwhile).
func turn_in(quest_ids: Array) -> void:
	if quest_ids.is_empty():
		return
	if offline or not has_mmo:
		var xp := 0
		var turned: Dictionary = GameState.local.get("turned_in", {})
		for id in quest_ids:
			if not turned.has(id):
				turned[id] = Time.get_unix_time_from_system()
				xp += 100 + int(GameState.quest_by_id(str(id)).get("bonus_xp", 0))
				GameState.bump_stat("quests")
		GameState.local["turned_in"] = turned
		if offline:
			fake.turned_in(quest_ids)
		if xp > 0:
			GameState.add_local_xp(xp, "for %d quest%s" % [quest_ids.size(), "" if quest_ids.size() == 1 else "s"])
		refresh_soon()
		return
	var body := {"all": true} if quest_ids.size() > 1 else {"id": quest_ids[0]}
	var r := await _request("POST", base_url + EP["mmo_turnin"], body)
	if r["status"] == 200 and r["data"] is Dictionary:
		GameState.apply_reward(r["data"])
		var loot: Array = r["data"].get("loot", [])
		if not loot.is_empty():
			GameState.loot_got.emit(loot, "Quest reward", {})
	else:
		GameState.notice.emit(_error_of(r), Color(1.0, 0.45, 0.4))
	refresh_soon()


## A failure monster died: record it (XP + a lesson scroll) and offer the retry.
func monster_defeated(monster: Dictionary) -> void:
	var id := str(monster.get("id", ""))
	if offline or not has_mmo:
		var beaten: Dictionary = GameState.local.get("beaten", {})
		if not beaten.has(id):
			beaten[id] = Time.get_unix_time_from_system()
			GameState.local["beaten"] = beaten
			GameState.bump_stat("kills")
			GameState.add_local_xp(int(monster.get("xp", 100)), "for the %s" % monster.get("name", "monster"))
		if offline:
			fake.beaten(id)
		var scroll := {"id": "scroll:" + id, "title": "Lesson: " + str(monster.get("title", "")), "rarity": "uncommon",
				"text": str(monster.get("error", "")), "job_id": id, "kind": "scroll", "show": "scroll"}
		GameState.loot_got.emit([scroll], str(monster.get("name", "Monster")), monster)
		refresh_soon()
		return
	var r := await _request("POST", base_url + EP["mmo_defeat"], {"id": id})
	if r["status"] == 200 and r["data"] is Dictionary:
		GameState.apply_reward(r["data"])
		GameState.loot_got.emit(r["data"].get("loot", []), str(monster.get("name", "Monster")), monster)
	else:
		GameState.notice.emit(_error_of(r), Color(1.0, 0.45, 0.4))
	refresh_soon()


## "Retry with a stronger model": start the failed job again (POST /mmo/monster/retry, or
## /world/retry, or as a plain new job when the engine has neither).
func retry_failed(monster: Dictionary, model: String = "") -> void:
	var id := str(monster.get("job_id", monster.get("id", "")))
	if offline:
		fake.start_quest("retry", "Retry: " + str(monster.get("title", "")))
		GameState.notice.emit("Retrying (demo) on a stronger model.", Color(1.0, 0.85, 0.3))
		return
	var body := {"id": id}
	if model != "":
		body["model"] = model
	var r := {"status": 404}
	if has_mmo:
		r = await _request("POST", base_url + EP["mmo_retry"], body)
	if r["status"] == 404:
		r = await _request("POST", base_url + EP["retry"], body)
	if r["status"] == 404:
		var prompt := "Retry: %s. The last attempt failed with: %s" % [monster.get("title", ""), monster.get("error", "")]
		var spec := {"prompt": prompt, "backend": "local", "agent": "loki", "title": prompt.substr(0, 80)}
		if model != "":
			spec["model"] = model
		r = await _request("POST", base_url + EP["jobs"], spec)
	if r["status"] == 200:
		GameState.bump_stat("retries")
		GameState.notice.emit("Retrying on a stronger model.", Color(1.0, 0.85, 0.3))
	else:
		GameState.notice.emit("Could not retry: %s" % _error_of(r), Color(1.0, 0.45, 0.4))
	refresh_soon()


## The model names this LOKI can use (GET /models), for "retry on a stronger model".
func models() -> Array:
	if offline:
		return ["smart", "online"]
	var r := await _request("GET", base_url + EP["models"])
	if r["status"] == 200 and r["data"] is Dictionary:
		return r["data"].get("models", [])
	return []


func note(body: Dictionary) -> void:
	if offline or not has_mmo:
		if body.get("death", false):
			GameState.bump_stat("deaths")
		return
	await _request("POST", base_url + EP["mmo_note"], body)


func set_profile(name_: String, cls: String) -> void:
	GameState.local["name"] = name_.substr(0, 24)
	GameState.local["cls"] = cls
	GameState.save_local()
	if not offline and has_mmo:
		await _request("POST", base_url + EP["mmo_profile"], {"name": name_.substr(0, 24), "cls": cls})
	refresh_soon()


func refresh_soon() -> void:
	_timers["state"] = 0.2


## A creation's picture as a texture (GET /creations/<kind>/<file>; cached). Offline: a made-up one.
func creation_texture(item: Dictionary) -> Texture2D:
	var id := str(item.get("id", item.get("path", "")))
	if _texture_cache.has(id):
		return _texture_cache[id]
	if offline or str(item.get("show", "image")) != "image":
		var tex := GameState.fake_painting(GameState.hash_text(id))
		_texture_cache[id] = tex
		return tex
	var url := str(item.get("url", ""))
	if url == "":
		url = EP["creation_file"] + str(item.get("path", ""))
	var r := await _request("GET", base_url + url, null, 20.0, true)
	var img := Image.new()
	var bytes: PackedByteArray = r.get("bytes", PackedByteArray())
	var err := ERR_FILE_UNRECOGNIZED
	var lower := url.to_lower()
	if bytes.size() > 0:
		if lower.ends_with(".png"):
			err = img.load_png_from_buffer(bytes)
		elif lower.ends_with(".webp"):
			err = img.load_webp_from_buffer(bytes)
		elif lower.ends_with(".jpg") or lower.ends_with(".jpeg"):
			err = img.load_jpg_from_buffer(bytes)
	var tex2: Texture2D
	if err == OK:
		if img.get_width() > 256:
			img.resize(256, maxi(1, int(256.0 * img.get_height() / img.get_width())), Image.INTERPOLATE_BILINEAR)
		tex2 = ImageTexture.create_from_image(img)
	else:
		tex2 = GameState.fake_painting(GameState.hash_text(id))
	_texture_cache[id] = tex2
	return tex2


# ----------------------------------------------------------------- HTTP

## One request; answers {status, data, error, bytes?}. status 0 = nothing answered.
func _request(method: String, url: String, body = null, timeout_s: float = 8.0, raw: bool = false) -> Dictionary:
	var req := HTTPRequest.new()
	req.timeout = timeout_s
	req.use_threads = false
	add_child(req)
	var headers := PackedStringArray(["Accept: application/json"])
	if token != "":
		headers.append("Authorization: Bearer " + token)
	var payload := ""
	var m := HTTPClient.METHOD_GET
	if method == "POST":
		m = HTTPClient.METHOD_POST
		headers.append("Content-Type: application/json")
		payload = JSON.stringify(body if body != null else {})
	var err := req.request(url, headers, m, payload)
	if err != OK:
		req.queue_free()
		return {"status": 0, "data": {}, "error": "request failed (%d)" % err}
	var res: Array = await req.request_completed
	req.queue_free()
	var status: int = res[1]
	if int(res[0]) != HTTPRequest.RESULT_SUCCESS:
		status = 0
	var out := {"status": status, "data": {}, "error": "", "result": int(res[0])}
	var bytes: PackedByteArray = res[3]
	if raw:
		out["bytes"] = bytes if status == 200 else PackedByteArray()
		return out
	var parsed = JSON.parse_string(bytes.get_string_from_utf8()) if bytes.size() > 0 else null
	if parsed is Dictionary:
		out["data"] = parsed
		out["error"] = str(parsed.get("error", ""))
	return out


func _error_of(r: Dictionary) -> String:
	if r.get("error", "") != "":
		return str(r["error"])
	if int(r.get("status", 0)) == 0:
		return "LOKI did not answer"
	return "HTTP %d" % int(r.get("status", 0))
