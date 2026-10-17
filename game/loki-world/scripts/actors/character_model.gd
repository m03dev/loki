class_name CharacterModel
extends Node3D
## A low-poly, cel-shaded, ink-outlined body built from boxes, cones and spheres: people (you,
## other players, LOKI's agents), the fox, rabbits and the failure monsters. Faces +z.
## tick() plays it: walk swing, idle breathing, casting, emotes, death, sleep.

const SKINS := [Color(1.0, 0.84, 0.7), Color(0.92, 0.72, 0.56), Color(0.72, 0.52, 0.38), Color(0.5, 0.35, 0.25)]

var kind := "person"
var body: Node3D
var head: Node3D
var arm_l: Node3D
var arm_r: Node3D
var leg_l: Node3D
var leg_r: Node3D
var extra: Node3D          # tail, lid, crown... animated by kind
var height := 1.75
var t := 0.0
var emote := ""
var emote_t := 0.0
var casting := false
var dead := false
var asleep := false
var floating := false
var hit_flash := 0.0


## A person. `hat`: horns, helm, wizard, hood, feather, cap, goggles, crown, none.
## `gear`: sword, staff, bow, totem, hammer, book, none.
static func person(color: Color, hat: String = "none", gear: String = "none", skin_index: int = 0, scale_k: float = 1.0) -> CharacterModel:
	var m := CharacterModel.new()
	m.kind = "person"
	var skin: Color = SKINS[clampi(skin_index, 0, SKINS.size() - 1)]
	var dark := color.darkened(0.35)
	m.body = Node3D.new()
	m.add_child(m.body)
	m.leg_l = m._pivot(m.body, Vector3(-0.13, 0.62, 0))
	m.leg_r = m._pivot(m.body, Vector3(0.13, 0.62, 0))
	Mats.part(m.leg_l, Mats.box(Vector3(0.2, 0.6, 0.22)), dark, Vector3(0, -0.3, 0))
	Mats.part(m.leg_r, Mats.box(Vector3(0.2, 0.6, 0.22)), dark, Vector3(0, -0.3, 0))
	Mats.part(m.body, Mats.box(Vector3(0.56, 0.62, 0.34)), color, Vector3(0, 0.93, 0))
	Mats.part(m.body, Mats.box(Vector3(0.6, 0.1, 0.38)), dark, Vector3(0, 0.66, 0))   # belt
	m.arm_l = m._pivot(m.body, Vector3(-0.37, 1.18, 0))
	m.arm_r = m._pivot(m.body, Vector3(0.37, 1.18, 0))
	Mats.part(m.arm_l, Mats.box(Vector3(0.17, 0.56, 0.18)), color.lightened(0.08), Vector3(0, -0.26, 0))
	Mats.part(m.arm_r, Mats.box(Vector3(0.17, 0.56, 0.18)), color.lightened(0.08), Vector3(0, -0.26, 0))
	Mats.part(m.arm_l, Mats.box(Vector3(0.15, 0.13, 0.16)), skin, Vector3(0, -0.6, 0))
	Mats.part(m.arm_r, Mats.box(Vector3(0.15, 0.13, 0.16)), skin, Vector3(0, -0.6, 0))
	m.head = m._pivot(m.body, Vector3(0, 1.25, 0))
	Mats.part(m.head, Mats.box(Vector3(0.44, 0.42, 0.42)), skin, Vector3(0, 0.23, 0))
	Mats.part(m.head, Mats.box(Vector3(0.07, 0.09, 0.03)), Color(0.08, 0.08, 0.12), Vector3(-0.1, 0.25, 0.215), Vector3.ZERO, false)
	Mats.part(m.head, Mats.box(Vector3(0.07, 0.09, 0.03)), Color(0.08, 0.08, 0.12), Vector3(0.1, 0.25, 0.215), Vector3.ZERO, false)
	m._hat(hat, color)
	m._gear(gear, color)
	m.scale = Vector3.ONE * scale_k
	m.height = 1.9 * scale_k
	return m


static func fox() -> CharacterModel:
	var m := CharacterModel.new()
	m.kind = "fox"
	var orange := Color(0.95, 0.5, 0.18)
	var white := Color(0.98, 0.95, 0.9)
	m.body = Node3D.new()
	m.add_child(m.body)
	Mats.part(m.body, Mats.box(Vector3(0.34, 0.3, 0.7)), orange, Vector3(0, 0.38, 0))
	Mats.part(m.body, Mats.box(Vector3(0.26, 0.12, 0.5)), white, Vector3(0, 0.24, 0.04))
	m.head = m._pivot(m.body, Vector3(0, 0.55, 0.36))
	Mats.part(m.head, Mats.box(Vector3(0.32, 0.28, 0.28)), orange, Vector3(0, 0.02, 0.06))
	Mats.part(m.head, Mats.box(Vector3(0.14, 0.12, 0.16)), white, Vector3(0, -0.04, 0.26))
	Mats.part(m.head, Mats.box(Vector3(0.06, 0.06, 0.04)), Color(0.08, 0.08, 0.1), Vector3(0, 0.0, 0.35), Vector3.ZERO, false)
	Mats.part(m.head, Mats.cyl(0.0, 0.09, 0.2, 4), orange, Vector3(-0.1, 0.24, 0.02))
	Mats.part(m.head, Mats.cyl(0.0, 0.09, 0.2, 4), orange, Vector3(0.1, 0.24, 0.02))
	Mats.part(m.head, Mats.box(Vector3(0.05, 0.05, 0.02)), Color(0.08, 0.08, 0.1), Vector3(-0.08, 0.07, 0.2), Vector3.ZERO, false)
	Mats.part(m.head, Mats.box(Vector3(0.05, 0.05, 0.02)), Color(0.08, 0.08, 0.1), Vector3(0.08, 0.07, 0.2), Vector3.ZERO, false)
	m.extra = m._pivot(m.body, Vector3(0, 0.45, -0.34))
	Mats.part(m.extra, Mats.box(Vector3(0.18, 0.18, 0.5)), orange, Vector3(0, 0.05, -0.25), Vector3(0.5, 0, 0))
	Mats.part(m.extra, Mats.box(Vector3(0.16, 0.16, 0.14)), white, Vector3(0, 0.16, -0.48), Vector3(0.5, 0, 0))
	m.leg_l = m._pivot(m.body, Vector3(-0.1, 0.25, 0.22))
	m.leg_r = m._pivot(m.body, Vector3(0.1, 0.25, -0.22))
	m.arm_l = m._pivot(m.body, Vector3(0.1, 0.25, 0.22))
	m.arm_r = m._pivot(m.body, Vector3(-0.1, 0.25, -0.22))
	for leg in [m.leg_l, m.leg_r, m.arm_l, m.arm_r]:
		Mats.part(leg, Mats.box(Vector3(0.08, 0.26, 0.08)), Color(0.25, 0.15, 0.1), Vector3(0, -0.12, 0))
	m.height = 0.85
	return m


static func rabbit(grey: bool = false) -> CharacterModel:
	var m := CharacterModel.new()
	m.kind = "rabbit"
	var fur := Color(0.72, 0.7, 0.68) if grey else Color(0.97, 0.96, 0.94)
	m.body = Node3D.new()
	m.add_child(m.body)
	Mats.part(m.body, Mats.box(Vector3(0.24, 0.22, 0.32)), fur, Vector3(0, 0.15, 0))
	m.head = m._pivot(m.body, Vector3(0, 0.3, 0.14))
	Mats.part(m.head, Mats.box(Vector3(0.18, 0.16, 0.16)), fur, Vector3(0, 0, 0.04))
	Mats.part(m.head, Mats.box(Vector3(0.05, 0.22, 0.04)), fur, Vector3(-0.05, 0.17, 0))
	Mats.part(m.head, Mats.box(Vector3(0.05, 0.22, 0.04)), fur, Vector3(0.05, 0.17, 0))
	Mats.part(m.head, Mats.box(Vector3(0.03, 0.03, 0.02)), Color(0.1, 0.05, 0.08), Vector3(-0.05, 0.02, 0.12), Vector3.ZERO, false)
	Mats.part(m.head, Mats.box(Vector3(0.03, 0.03, 0.02)), Color(0.1, 0.05, 0.08), Vector3(0.05, 0.02, 0.12), Vector3.ZERO, false)
	Mats.part(m.body, Mats.box(Vector3(0.1, 0.1, 0.08)), Color.WHITE, Vector3(0, 0.2, -0.18))
	m.height = 0.55
	return m


## A failure monster; `kind` from GET /mmo/state monsters[].kind.
static func monster(kind_name: String, scale_k: float = 1.0) -> CharacterModel:
	var m := CharacterModel.new()
	m.kind = kind_name
	m.body = Node3D.new()
	m.add_child(m.body)
	var eye := Color(1.0, 0.15, 0.1)
	var glow_eye := Mats.toon(eye, false, 1, Color(0.9, 0.1, 0.05))
	match kind_name:
		"slime":
			var s := Mats.part(m.body, Mats.ball(0.55, 10, 6), Color(0.4, 0.85, 0.35), Vector3(0, 0.38, 0))
			s.material_override = Mats.toon(Color(0.4, 0.85, 0.35), true, 0)
			s.scale = Vector3(1.0, 0.72, 1.0)
			m.head = s
			m.height = 0.9
		"golem":
			Mats.part(m.body, Mats.box(Vector3(1.0, 0.9, 0.7)), Color(0.55, 0.52, 0.5), Vector3(0, 1.2, 0))
			Mats.part(m.body, Mats.box(Vector3(0.3, 0.75, 0.35)), Color(0.45, 0.42, 0.42), Vector3(-0.26, 0.38, 0))
			Mats.part(m.body, Mats.box(Vector3(0.3, 0.75, 0.35)), Color(0.45, 0.42, 0.42), Vector3(0.26, 0.38, 0))
			m.arm_l = m._pivot(m.body, Vector3(-0.68, 1.5, 0))
			m.arm_r = m._pivot(m.body, Vector3(0.68, 1.5, 0))
			Mats.part(m.arm_l, Mats.box(Vector3(0.34, 0.9, 0.34)), Color(0.5, 0.47, 0.46), Vector3(0, -0.42, 0))
			Mats.part(m.arm_r, Mats.box(Vector3(0.34, 0.9, 0.34)), Color(0.5, 0.47, 0.46), Vector3(0, -0.42, 0))
			m.head = m._pivot(m.body, Vector3(0, 1.65, 0.05))
			Mats.part(m.head, Mats.box(Vector3(0.5, 0.4, 0.45)), Color(0.6, 0.57, 0.55), Vector3(0, 0.2, 0))
			m.height = 2.2
		"wisp":
			var w := Mats.part(m.body, Mats.ball(0.38, 4, 2), Color(0.45, 0.75, 1.0), Vector3(0, 1.2, 0))
			w.material_override = Mats.toon(Color(0.45, 0.75, 1.0), true, 0, Color(0.15, 0.35, 0.6))
			m.head = w
			m.floating = true
			m.height = 1.7
		"mimic":
			Mats.part(m.body, Mats.box(Vector3(0.9, 0.55, 0.65)), Color(0.55, 0.35, 0.18), Vector3(0, 0.3, 0))
			Mats.part(m.body, Mats.box(Vector3(0.94, 0.08, 0.69)), Color(0.85, 0.7, 0.25), Vector3(0, 0.52, 0))
			m.extra = m._pivot(m.body, Vector3(0, 0.58, -0.32))
			Mats.part(m.extra, Mats.box(Vector3(0.9, 0.22, 0.65)), Color(0.6, 0.38, 0.2), Vector3(0, 0.1, 0.32))
			for k in 4:
				Mats.part(m.body, Mats.cyl(0.0, 0.05, 0.12, 4), Color.WHITE, Vector3(-0.3 + 0.2 * k, 0.62, 0.3))
			m.head = m.extra
			m.height = 1.1
		"beetle":
			var shell := Mats.part(m.body, Mats.ball(0.5, 8, 4), Color(0.2, 0.45, 0.3), Vector3(0, 0.35, 0))
			shell.material_override = Mats.toon(Color(0.2, 0.45, 0.3), true, 0)
			shell.scale = Vector3(1.0, 0.6, 1.3)
			m.head = m._pivot(m.body, Vector3(0, 0.35, 0.6))
			Mats.part(m.head, Mats.box(Vector3(0.3, 0.22, 0.2)), Color(0.15, 0.2, 0.18), Vector3.ZERO)
			for side in [-1.0, 1.0]:
				for k in 3:
					Mats.part(m.body, Mats.box(Vector3(0.4, 0.05, 0.05)), Color(0.1, 0.12, 0.1), Vector3(side * 0.5, 0.15, -0.3 + 0.3 * k), Vector3(0, 0, side * 0.5))
			m.height = 0.9
		_:
			# wraith, goblin, gremlin: a hunched figure
			var col := Color(0.42, 0.3, 0.6) if kind_name == "wraith" else (Color(0.4, 0.62, 0.3) if kind_name == "goblin" else Color(0.85, 0.3, 0.25))
			if kind_name == "wraith":
				Mats.part(m.body, Mats.cyl(0.2, 0.6, 1.3, 7), col, Vector3(0, 0.95, 0))
				m.floating = true
			else:
				Mats.part(m.body, Mats.box(Vector3(0.5, 0.5, 0.35)), col, Vector3(0, 0.6, 0))
				m.leg_l = m._pivot(m.body, Vector3(-0.12, 0.38, 0))
				m.leg_r = m._pivot(m.body, Vector3(0.12, 0.38, 0))
				Mats.part(m.leg_l, Mats.box(Vector3(0.16, 0.38, 0.18)), col.darkened(0.3), Vector3(0, -0.19, 0))
				Mats.part(m.leg_r, Mats.box(Vector3(0.16, 0.38, 0.18)), col.darkened(0.3), Vector3(0, -0.19, 0))
			m.arm_l = m._pivot(m.body, Vector3(-0.32, 0.8 if kind_name != "wraith" else 1.35, 0))
			m.arm_r = m._pivot(m.body, Vector3(0.32, 0.8 if kind_name != "wraith" else 1.35, 0))
			Mats.part(m.arm_l, Mats.box(Vector3(0.13, 0.5, 0.13)), col.lightened(0.1), Vector3(0, -0.22, 0))
			Mats.part(m.arm_r, Mats.box(Vector3(0.13, 0.5, 0.13)), col.lightened(0.1), Vector3(0, -0.22, 0))
			m.head = m._pivot(m.body, Vector3(0, 0.88 if kind_name != "wraith" else 1.6, 0.04))
			Mats.part(m.head, Mats.box(Vector3(0.42, 0.36, 0.38)), col.lightened(0.05), Vector3(0, 0.15, 0))
			if kind_name != "wraith":
				Mats.part(m.head, Mats.cyl(0.0, 0.07, 0.22, 4), col.darkened(0.2), Vector3(-0.17, 0.4, 0), Vector3(0, 0, 0.5))
				Mats.part(m.head, Mats.cyl(0.0, 0.07, 0.22, 4), col.darkened(0.2), Vector3(0.17, 0.4, 0), Vector3(0, 0, -0.5))
			m.height = 1.3 if kind_name != "wraith" else 2.0
	# red eyes on every monster
	var eye_parent: Node3D = m.head if m.head != null else m.body
	var eye_y := 0.18 if m.head != null and m.head != m.body else 0.6
	for side in [-1.0, 1.0]:
		var e := MeshInstance3D.new()
		e.mesh = Mats.box(Vector3(0.08, 0.08, 0.04))
		e.material_override = glow_eye
		e.position = Vector3(side * 0.1, eye_y, 0.23)
		if kind_name == "slime":
			e.position = Vector3(side * 0.16, 0.15, 0.5)
		elif kind_name == "mimic":
			e.position = Vector3(side * 0.2, 0.15, 0.66)
		elif kind_name == "wisp":
			e.position = Vector3(side * 0.12, 0.05, 0.36)
		elif kind_name == "beetle":
			e.position = Vector3(side * 0.08, 0.04, 0.11)
		eye_parent.add_child(e)
	m.scale = Vector3.ONE * scale_k
	m.height *= scale_k
	return m


func _pivot(parent: Node3D, pos: Vector3) -> Node3D:
	var p := Node3D.new()
	p.position = pos
	parent.add_child(p)
	return p


func _hat(hat: String, color: Color) -> void:
	match hat:
		"horns":
			Mats.part(head, Mats.cyl(0.0, 0.07, 0.34, 5), Color(0.95, 0.9, 0.75), Vector3(-0.18, 0.55, 0), Vector3(0, 0, 0.45))
			Mats.part(head, Mats.cyl(0.0, 0.07, 0.34, 5), Color(0.95, 0.9, 0.75), Vector3(0.18, 0.55, 0), Vector3(0, 0, -0.45))
			Mats.part(body, Mats.box(Vector3(0.6, 0.85, 0.06)), Color(0.15, 0.75, 0.7), Vector3(0, 0.82, -0.2), Vector3(0.12, 0, 0))
		"helm":
			Mats.part(head, Mats.box(Vector3(0.5, 0.22, 0.48)), Color(0.7, 0.72, 0.78), Vector3(0, 0.42, 0))
			Mats.part(head, Mats.box(Vector3(0.08, 0.16, 0.4)), color, Vector3(0, 0.6, 0))
			Mats.part(body, Mats.box(Vector3(0.6, 0.85, 0.06)), color.darkened(0.2), Vector3(0, 0.82, -0.2), Vector3(0.12, 0, 0))
		"wizard":
			Mats.part(head, Mats.cyl(0.32, 0.32, 0.05, 8), color.darkened(0.25), Vector3(0, 0.45, 0))
			Mats.part(head, Mats.cyl(0.0, 0.24, 0.6, 7), color.darkened(0.15), Vector3(0, 0.75, -0.03), Vector3(-0.15, 0, 0))
		"hood":
			Mats.part(head, Mats.box(Vector3(0.5, 0.48, 0.46)), color.darkened(0.2), Vector3(0, 0.27, -0.03))
		"feather":
			Mats.part(head, Mats.box(Vector3(0.46, 0.08, 0.46)), color.darkened(0.2), Vector3(0, 0.4, 0))
			Mats.part(head, Mats.box(Vector3(0.05, 0.35, 0.1)), Color(1.0, 0.95, 0.85), Vector3(0.18, 0.58, -0.1), Vector3(0, 0, -0.3))
		"cap":
			Mats.part(head, Mats.box(Vector3(0.48, 0.12, 0.48)), color, Vector3(0, 0.44, 0))
			Mats.part(head, Mats.box(Vector3(0.4, 0.04, 0.2)), color.darkened(0.2), Vector3(0, 0.39, 0.28))
		"goggles":
			Mats.part(head, Mats.box(Vector3(0.46, 0.08, 0.46)), Color(0.3, 0.25, 0.2), Vector3(0, 0.33, 0))
			Mats.part(head, Mats.box(Vector3(0.12, 0.1, 0.04)), Color(1.0, 0.85, 0.3), Vector3(-0.1, 0.33, 0.23))
			Mats.part(head, Mats.box(Vector3(0.12, 0.1, 0.04)), Color(1.0, 0.85, 0.3), Vector3(0.1, 0.33, 0.23))
		"crown":
			Mats.part(head, Mats.box(Vector3(0.46, 0.12, 0.46)), Color(1.0, 0.82, 0.25), Vector3(0, 0.48, 0))
		_:
			pass


func _gear(gear: String, color: Color) -> void:
	match gear:
		"sword":
			Mats.part(arm_r, Mats.box(Vector3(0.06, 0.8, 0.12)), Color(0.85, 0.88, 0.95), Vector3(0, -0.75, 0.3), Vector3(1.4, 0, 0))
			Mats.part(arm_r, Mats.box(Vector3(0.24, 0.05, 0.08)), Color(0.75, 0.6, 0.2), Vector3(0, -0.66, 0.06))
		"staff":
			Mats.part(arm_r, Mats.cyl(0.035, 0.035, 1.5, 5), Color(0.5, 0.33, 0.2), Vector3(0, -0.45, 0.1))
			var orb := Mats.part(arm_r, Mats.ball(0.11, 6, 4), color.lightened(0.4), Vector3(0, 0.33, 0.1))
			orb.material_override = Mats.toon(color.lightened(0.4), true, 0, color * 0.6)
		"bow":
			Mats.part(arm_l, Mats.box(Vector3(0.04, 0.9, 0.05)), Color(0.55, 0.38, 0.2), Vector3(0, -0.55, 0.12))
		"totem":
			Mats.part(arm_r, Mats.box(Vector3(0.1, 0.5, 0.1)), Color(0.5, 0.35, 0.25), Vector3(0, -0.7, 0.1))
			Mats.part(arm_r, Mats.box(Vector3(0.2, 0.2, 0.2)), color, Vector3(0, -0.42, 0.1))
		"hammer":
			Mats.part(arm_r, Mats.box(Vector3(0.05, 0.55, 0.05)), Color(0.5, 0.35, 0.25), Vector3(0, -0.7, 0.1))
			Mats.part(arm_r, Mats.box(Vector3(0.24, 0.14, 0.14)), Color(0.55, 0.57, 0.6), Vector3(0, -0.98, 0.1))
		"book":
			Mats.part(arm_l, Mats.box(Vector3(0.24, 0.3, 0.07)), color.darkened(0.2), Vector3(0, -0.62, 0.12))
		_:
			pass


func start_emote(name_: String) -> void:
	emote = name_
	emote_t = 0.0


## Play one frame. `speed` = horizontal speed (m/s), `air` = in the air.
func tick(delta: float, speed: float, air: bool = false) -> void:
	t += delta
	if hit_flash > 0.0:
		hit_flash = max(0.0, hit_flash - delta)
	var moving := speed > 0.3
	if moving and emote != "":
		emote = ""
	var swing := sin(t * clampf(speed * 2.4, 4.0, 12.0)) * clampf(speed / 4.0, 0.0, 1.0) * 0.9
	var bob := 0.0
	if body == null:
		return
	body.rotation = Vector3.ZERO
	body.position = Vector3.ZERO
	if dead:
		body.rotation.x = -PI * 0.5
		body.position.y = 0.2
		return
	if asleep:
		body.position.y = -0.12
		if head != null:
			head.rotation.x = 0.35
		if extra != null:
			extra.rotation.y = 1.2
		return
	if floating:
		body.position.y = 0.25 + sin(t * 2.0) * 0.12
	match kind:
		"person", "goblin", "gremlin", "wraith", "golem":
			if leg_l != null:
				leg_l.rotation.x = swing
				leg_r.rotation.x = -swing
			if arm_l != null:
				arm_l.rotation = Vector3(-swing * 0.8, 0, 0)
				arm_r.rotation = Vector3(swing * 0.8, 0, 0)
			if not moving:
				bob = sin(t * 2.2) * 0.012
			if casting and arm_l != null:
				arm_l.rotation = Vector3(-1.3 + sin(t * 10.0) * 0.1, 0, -0.2)
				arm_r.rotation = Vector3(-1.3 - sin(t * 10.0) * 0.1, 0, 0.2)
			if air and leg_l != null:
				leg_l.rotation.x = -0.6
				leg_r.rotation.x = 0.3
		"fox", "rabbit":
			if leg_l != null:
				leg_l.rotation.x = swing
				leg_r.rotation.x = swing
				arm_l.rotation.x = -swing
				arm_r.rotation.x = -swing
			if extra != null:
				extra.rotation.y = sin(t * 3.0) * 0.4
			if kind == "rabbit" and moving:
				bob = abs(sin(t * 9.0)) * 0.12
		"slime":
			var sq := 1.0 + sin(t * (8.0 if moving else 3.0)) * 0.12
			if head != null:
				head.scale = Vector3(1.0 / sqrt(sq), 0.72 * sq, 1.0 / sqrt(sq))
		"mimic":
			if extra != null:
				extra.rotation.x = -absf(sin(t * (6.0 if moving else 1.5))) * 0.6
		"wisp":
			body.rotation.y = t * 1.5
		"beetle":
			bob = absf(sin(t * 14.0)) * 0.03 if moving else 0.0
	body.position.y += bob
	_emote(delta)


func _emote(delta: float) -> void:
	if emote == "":
		return
	emote_t += delta
	match emote:
		"wave":
			if arm_r != null:
				arm_r.rotation = Vector3(0, 0, 2.6 + sin(emote_t * 10.0) * 0.35)
			if emote_t > 2.5:
				emote = ""
		"cheer":
			if arm_l != null:
				arm_l.rotation = Vector3(0, 0, -2.7)
				arm_r.rotation = Vector3(0, 0, 2.7)
			body.position.y += absf(sin(emote_t * 7.0)) * 0.25
			if emote_t > 2.5:
				emote = ""
		"dance":
			body.rotation.y = sin(emote_t * 4.0) * 0.6
			body.position.y += absf(sin(emote_t * 8.0)) * 0.12
			if arm_l != null:
				arm_l.rotation = Vector3(0, 0, -1.2 - sin(emote_t * 8.0) * 0.8)
				arm_r.rotation = Vector3(0, 0, 1.2 + cos(emote_t * 8.0) * 0.8)
		"sit":
			body.position.y -= 0.45
			if leg_l != null:
				leg_l.rotation.x = -1.5
				leg_r.rotation.x = -1.5
		"bow":
			body.rotation.x = 0.6 * clampf(emote_t * 3.0, 0.0, 1.0)
			if emote_t > 2.0:
				emote = ""
