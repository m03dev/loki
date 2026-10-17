extends Node
## GameState (autoload): the game as the client knows it, in the shape of the engine's
## GET /mmo/state (docs/MMO_API.md section 4), whatever its source:
##   "engine"  - the engine's own /mmo/state (when the engine has the MMO API)
##   "derived" - built here from the endpoints every LOKI has (/world, /jobs, /creations)
##   "offline" - LOKI is not running: a small made-up world so the game still plays
## The rule from docs/MMO_API.md holds for "engine" and "derived": nothing is invented -
## quests are jobs, monsters are failed jobs, loot is what LOKI made.

signal state_changed
signal chat_line(channel: String, from: String, text: String, color: Color)
signal notice(text: String, color: Color)
signal level_up(level: int)
signal loot_got(items: Array, title: String, offer_retry: Dictionary)
signal presence_changed(players: Array)
signal need_pair(reason: String)
signal mode_changed(mode: String)

const PROFILE_FILE := "user://loki_world_profile.json"
const MAX_LEVEL := 99

## The same tables as engine/mmo_state.py, so a derived/offline game reads like the engine's.
const CLASSES := {
	"Warrior": {"color": "#d9604f", "about": "Front line. Strikes hard, shrugs off hits.", "hp": 1.2, "power": 1.0, "hat": "helm", "gear": "sword"},
	"Mage": {"color": "#8b7bff", "about": "Bolts from afar; the arcane does the work.", "hp": 0.9, "power": 1.2, "hat": "wizard", "gear": "staff"},
	"Archer": {"color": "#55b85c", "about": "Quick and precise at range.", "hp": 1.0, "power": 1.1, "hat": "hood", "gear": "bow"},
	"Shaman": {"color": "#2ec4b6", "about": "Mends wounds; spirits answer.", "hp": 1.05, "power": 0.95, "hat": "feather", "gear": "totem"},
}
const NPC_CLASSES := [
	["^loki$|conductor", "Trickster", "#2ee6d6", "horns", "staff"],
	["research|hermes", "Sage", "#3fa9ff", "wizard", "book"],
	["architect", "Arcanist", "#b46cff", "wizard", "staff"],
	["browser", "Scout", "#4d7cff", "hood", "bow"],
	["test", "Alchemist", "#ffc23d", "goggles", "none"],
	["review", "Paladin", "#ff7a45", "helm", "sword"],
	["build|loki agent|claude|codex|opencode|openhands|agent", "Smith", "#36e07a", "cap", "hammer"],
]
const MONSTER_KINDS := [
	["time ?out|timed out|deadline", "Timeout Wraith", "wraith"],
	["rate.?limit|429|quota|too many requests", "Rate-Limit Slime", "slime"],
	["syntax|parse|json|decode|unexpected token", "Syntax Golem", "golem"],
	["permission|denied|policy|forbidden|approval|blocked", "Gatekeeper Goblin", "goblin"],
	["network|connect|unreachable|dns|refused|ssl|certificate", "Netwisp", "wisp"],
	["api key|provider|model|unauthori[sz]ed|401", "Model Mimic", "mimic"],
	["test|assert|fail", "Bug Beetle", "beetle"],
]
const RARITY := {"images": "rare", "videos": "epic", "media": "uncommon", "sketches": "common", "games": "legendary"}
const RARITY_COLORS := {"common": Color(0.85, 0.85, 0.85), "uncommon": Color(0.35, 0.9, 0.4), "rare": Color(0.3, 0.6, 1.0),
		"epic": Color(0.75, 0.4, 1.0), "legendary": Color(1.0, 0.6, 0.15)}
## The hotbar (engine/mmo_state.py SKILLS): combat skills are played here; "loki" skills start real jobs.
const SKILLS := [
	{"slot": 1, "id": "strike", "name": "Strike", "kind": "combat", "cd_s": 1.1, "energy": 0, "cast_s": 0.0, "range": 2.6, "dmg": [10, 16]},
	{"slot": 2, "id": "bolt", "name": "Bolt", "kind": "combat", "cd_s": 2.5, "energy": 18, "cast_s": 0.7, "range": 11.0, "dmg": [15, 24]},
	{"slot": 3, "id": "mend", "name": "Mend", "kind": "self", "cd_s": 10, "energy": 25, "cast_s": 1.0, "heal": [30, 40]},
	{"slot": 4, "id": "image", "name": "Make a picture", "kind": "loki", "cd_s": 8, "energy": 0, "cast_s": 1.5, "ask": "a picture of..."},
	{"slot": 5, "id": "research", "name": "Research", "kind": "loki", "cd_s": 8, "energy": 0, "cast_s": 1.5, "ask": "find out about..."},
	{"slot": 6, "id": "build", "name": "Build", "kind": "loki", "cd_s": 8, "energy": 0, "cast_s": 1.5, "ask": "build or change..."},
	{"slot": 7, "id": "video", "name": "Make a video", "kind": "loki", "cd_s": 8, "energy": 0, "cast_s": 1.5, "ask": "a video of..."},
	{"slot": 8, "id": "game", "name": "Make a game", "kind": "loki", "cd_s": 8, "energy": 0, "cast_s": 1.5, "ask": "a game where..."},
	{"slot": 9, "id": "hearth", "name": "Hearth", "kind": "travel", "cd_s": 30, "energy": 0, "cast_s": 2.5},
]
const EMOTES := ["wave", "dance", "sit", "cheer", "bow"]

var source := "offline"          # engine | derived | offline
var mode := "play"               # play | background (behind LOKI's home screen: no HUD, slow orbit)
var state: Dictionary = {}
var local: Dictionary = {}       # the saved profile for derived/offline play
var cooldowns: Dictionary = {}   # skill id -> seconds left
var presence_players: Array = []
var self_zone := "This computer"
var _known_quests: Dictionary = {}
var persist := true              # false with --no-save (tests): the saved profile is not touched
var _rng := RandomNumberGenerator.new()


func _ready() -> void:
	_rng.randomize()
	persist = not OS.get_cmdline_user_args().has("--no-save")
	_load_local()
	_setup_input()
	state = empty_state()


func _process(delta: float) -> void:
	for k in cooldowns.keys():
		cooldowns[k] = max(0.0, float(cooldowns[k]) - delta)


# ----------------------------------------------------------------- input map (built in code)

## Every action and its default keys. Built at start so the project file stays small and the
## tests can read the controls from one place.
const CONTROLS := {
	"move_forward": [KEY_W, KEY_UP], "move_back": [KEY_S, KEY_DOWN], "move_left": [KEY_A], "move_right": [KEY_D],
	"turn_left": [KEY_Q, KEY_LEFT], "turn_right": [KEY_E, KEY_RIGHT], "jump": [KEY_SPACE],
	"target_next": [KEY_TAB], "interact": [KEY_F], "chat": [KEY_ENTER, KEY_KP_ENTER], "chat_slash": [KEY_SLASH],
	"cancel": [KEY_ESCAPE], "toggle_quests": [KEY_L], "toggle_bags": [KEY_B, KEY_I], "toggle_character": [KEY_C],
	"toggle_map": [KEY_M], "toggle_help": [KEY_H, KEY_F1], "autorun": [KEY_R],
	"skill_1": [KEY_1], "skill_2": [KEY_2], "skill_3": [KEY_3], "skill_4": [KEY_4], "skill_5": [KEY_5],
	"skill_6": [KEY_6], "skill_7": [KEY_7], "skill_8": [KEY_8], "skill_9": [KEY_9],
}


func _setup_input() -> void:
	for action in CONTROLS:
		if not InputMap.has_action(action):
			InputMap.add_action(action)
		for key in CONTROLS[action]:
			var ev := InputEventKey.new()
			ev.physical_keycode = key
			InputMap.action_add_event(action, ev)


# ----------------------------------------------------------------- levels and numbers

static func xp_to_next(level: int) -> int:
	return int(round(80.0 * pow(float(level), 1.55)))


static func level_of(xp: float) -> Dictionary:
	var lvl := 1
	var left := maxi(0, int(xp))
	while lvl < MAX_LEVEL and left >= xp_to_next(lvl):
		left -= xp_to_next(lvl)
		lvl += 1
	return {"level": lvl, "xp_into": left, "xp_need": xp_to_next(lvl)}


static func class_info(cls: String) -> Dictionary:
	return CLASSES.get(cls, CLASSES["Mage"])


static func npc_class(role: String) -> Dictionary:
	var r := role.to_lower()
	for row in NPC_CLASSES:
		var re := RegEx.create_from_string(row[0])
		if re.search(r) != null:
			return {"name": row[1], "color": row[2], "hat": row[3], "gear": row[4]}
	return {"name": "Adventurer", "color": "#9aa0aa", "hat": "none", "gear": "none"}


static func monster_of(error: String) -> Array:
	var e := error.to_lower()
	for row in MONSTER_KINDS:
		var re := RegEx.create_from_string(row[0])
		if re.search(e) != null:
			return [row[1], row[2]]
	return ["Error Gremlin", "gremlin"]


static func hash_text(text: String) -> int:
	return absi(text.hash())


func profile() -> Dictionary:
	return state.get("profile", {})


func level() -> int:
	return int(profile().get("level", 1))


func hp_max() -> float:
	return float(profile().get("hp_max", 100))


func en_max() -> float:
	return float(profile().get("en_max", 100))


func power() -> float:
	return float(profile().get("power", 1.0))


func skills() -> Array:
	var s: Array = state.get("skills", [])
	return s if not s.is_empty() else SKILLS


func skill_in_slot(slot: int) -> Dictionary:
	for s in skills():
		if int(s.get("slot", 0)) == slot:
			return s
	return {}


## Damage of a combat skill: rand(dmg) + 2 * level, times power, 15 % crits x1.75 (docs/MMO_API.md).
func roll_damage(skill: Dictionary) -> Array:
	var d: Array = skill.get("dmg", [10, 16])
	var amount := (_rng.randi_range(int(d[0]), int(d[1])) + 2 * level()) * power()
	var crit := _rng.randf() < 0.15
	if crit:
		amount *= 1.75
	return [roundi(amount), crit]


func roll_heal(skill: Dictionary) -> int:
	var h: Array = skill.get("heal", [30, 40])
	return roundi((_rng.randi_range(int(h[0]), int(h[1])) + 2 * level()) * power())


func start_cooldown(skill: Dictionary) -> void:
	cooldowns[skill.get("id", "")] = float(skill.get("cd_s", 1.0))


func cooldown_left(skill: Dictionary) -> float:
	return float(cooldowns.get(skill.get("id", ""), 0.0))


func set_mode(new_mode: String) -> void:
	if new_mode != mode and new_mode in ["play", "background"]:
		mode = new_mode
		mode_changed.emit(mode)


# ----------------------------------------------------------------- applying a state

static func empty_state() -> Dictionary:
	var lv := level_of(0)
	return {
		"ok": true, "version": 1, "time": 0.0,
		"profile": {"name": "You", "cls": "Mage", "color": "#8b7bff", "xp": 0, "level": lv["level"], "xp_into": 0,
				"xp_need": lv["xp_need"], "hp_max": 102, "en_max": 100, "power": 1.2,
				"stats": {"quests": 0, "kills": 0, "deaths": 0, "casts": 0, "loot": 0, "retries": 0}, "machine": ""},
		"classes": CLASSES, "skills": SKILLS, "quests": [], "monsters": [], "npcs": [],
		"loot": {"items": [], "scrolls": []}, "zones": {"self": {"name": "This computer", "os": ""}, "machines": []},
		"presence": {"players": [], "chat": [], "cursor": 0},
	}


## Take a new state (any source). Fills defaults, notices finished quests and level-ups.
func apply_state(new_state: Dictionary, from_source: String) -> void:
	var before_level := level()
	var had_profile := state.has("profile") and not state.is_empty()
	source = from_source
	var s := empty_state()
	for k in new_state.keys():
		s[k] = new_state[k]
	_fill_profile(s)
	var zones: Dictionary = s.get("zones", {})
	var me: Dictionary = zones.get("self", {})
	self_zone = str(me.get("name", "This computer"))
	if self_zone == "":
		self_zone = "This computer"
	state = s
	for q in s.get("quests", []):
		var id := str(q.get("id", ""))
		var st := str(q.get("status", ""))
		var was := str(_known_quests.get(id, ""))
		if was != "" and was != st:
			if st == "complete":
				notice.emit("Quest complete: %s - bring it to LOKI" % q.get("title", ""), Color(1.0, 0.85, 0.3))
			elif st == "failed":
				notice.emit("A quest failed - something is out there: %s" % q.get("title", ""), Color(1.0, 0.4, 0.35))
		_known_quests[id] = st
	if had_profile and level() > before_level:
		level_up.emit(level())
	if s.has("welcome") and s["welcome"] is Dictionary and not local.get("welcomed", false):
		var w: Dictionary = s["welcome"]
		notice.emit("Welcome! Your past work became %d XP: level %d." % [int(w.get("xp", 0)), int(w.get("level", 1))], Color(0.5, 1.0, 0.9))
		local["welcomed"] = true
		save_local()
	state_changed.emit()


func _fill_profile(s: Dictionary) -> void:
	var p: Dictionary = s.get("profile", {})
	var cls := str(p.get("cls", "Mage"))
	if not CLASSES.has(cls):
		cls = "Mage"
	var lv := level_of(float(p.get("xp", 0)))
	if not p.has("level"):
		p["level"] = lv["level"]
		p["xp_into"] = lv["xp_into"]
		p["xp_need"] = lv["xp_need"]
	var info := class_info(cls)
	if not p.has("hp_max"):
		p["hp_max"] = roundi((90 + 12 * int(p["level"])) * float(info["hp"]))
	if not p.has("en_max"):
		p["en_max"] = 100
	if not p.has("power"):
		p["power"] = info["power"]
	if not p.has("color"):
		p["color"] = info["color"]
	p["cls"] = cls
	s["profile"] = p


# ----------------------------------------------------------------- local profile (derived / offline)

func _load_local() -> void:
	local = {"name": "You", "cls": "Mage", "xp": 0, "turned_in": {}, "beaten": {}, "seen": {},
			"stats": {"quests": 0, "kills": 0, "deaths": 0, "casts": 0, "loot": 0, "retries": 0}}
	if persist and FileAccess.file_exists(PROFILE_FILE):
		var f := FileAccess.open(PROFILE_FILE, FileAccess.READ)
		if f != null:
			var parsed = JSON.parse_string(f.get_as_text())
			if parsed is Dictionary:
				for k in parsed.keys():
					local[k] = parsed[k]


func save_local() -> void:
	if not persist:
		return
	var f := FileAccess.open(PROFILE_FILE, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(local))


func local_profile(machine: String) -> Dictionary:
	var lv := level_of(float(local.get("xp", 0)))
	var cls := str(local.get("cls", "Mage"))
	var info := class_info(cls)
	return {"name": str(local.get("name", "You")), "cls": cls, "color": info["color"], "xp": int(local.get("xp", 0)),
			"level": lv["level"], "xp_into": lv["xp_into"], "xp_need": lv["xp_need"],
			"hp_max": roundi((90 + 12 * int(lv["level"])) * float(info["hp"])), "en_max": 100, "power": info["power"],
			"stats": local.get("stats", {}), "machine": machine}


## Derived/offline: XP earned in this client (the engine keeps it itself when it has /mmo/*).
func add_local_xp(amount: int, why: String) -> void:
	var before: int = level_of(float(local.get("xp", 0)))["level"]
	local["xp"] = int(local.get("xp", 0)) + amount
	save_local()
	var lv := level_of(float(local["xp"]))
	var p := profile()
	p["xp"] = local["xp"]
	p["level"] = lv["level"]
	p["xp_into"] = lv["xp_into"]
	p["xp_need"] = lv["xp_need"]
	notice.emit("+%d XP  %s" % [amount, why], Color(0.75, 0.55, 1.0))
	if lv["level"] > before:
		var info := class_info(str(p.get("cls", "Mage")))
		p["hp_max"] = roundi((90 + 12 * int(lv["level"])) * float(info["hp"]))
		level_up.emit(lv["level"])
	state_changed.emit()


func bump_stat(stat: String) -> void:
	var st: Dictionary = local.get("stats", {})
	st[stat] = int(st.get(stat, 0)) + 1
	local["stats"] = st
	save_local()


## Engine answers like /mmo/quest/turnin carry total_xp/level: put them into the profile now.
func apply_reward(answer: Dictionary) -> void:
	var p := profile()
	var before := int(p.get("level", 1))
	for k in ["level", "xp_into", "xp_need"]:
		if answer.has(k):
			p[k] = answer[k]
	if answer.has("total_xp"):
		p["xp"] = answer["total_xp"]
	if answer.has("xp"):
		notice.emit("+%d XP" % int(answer["xp"]), Color(0.75, 0.55, 1.0))
	if int(p.get("level", 1)) > before or bool(answer.get("level_up", false)):
		level_up.emit(int(p.get("level", 1)))
	state_changed.emit()


## Turn a quest's error text into the name of what you fight.
func quest_by_id(id: String) -> Dictionary:
	for q in state.get("quests", []):
		if str(q.get("id", "")) == id:
			return q
	return {}


func monster_by_id(id: String) -> Dictionary:
	for m in state.get("monsters", []):
		if str(m.get("id", "")) == id:
			return m
	return {}


func loot_items() -> Array:
	var loot: Dictionary = state.get("loot", {})
	return loot.get("items", [])


func say(channel: String, from: String, text: String, color: Color = Color.WHITE) -> void:
	chat_line.emit(channel, from, text, color)


## A made-up painting for offline play (no LOKI, so nothing real to hang): sky, hills, a sun.
static func fake_painting(seed_value: int) -> ImageTexture:
	var rng := RandomNumberGenerator.new()
	rng.seed = seed_value
	var img := Image.create(32, 24, false, Image.FORMAT_RGB8)
	var sky := Color.from_hsv(rng.randf(), 0.35, 0.95)
	var hill := Color.from_hsv(rng.randf(), 0.5, 0.6)
	var sun := Color(1, 0.9, 0.5)
	var sx := rng.randi_range(5, 26)
	for y in 24:
		for x in 32:
			var c := sky.darkened(float(y) / 60.0)
			if y > 15 + int(3.0 * sin(float(x) * 0.3 + float(seed_value % 7))):
				c = hill.darkened(float(y - 15) / 30.0)
			if Vector2(x - sx, y - 6).length() < 3.2:
				c = sun
			img.set_pixel(x, y, c)
	return ImageTexture.create_from_image(img)
