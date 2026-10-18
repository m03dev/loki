class_name IslandBuilder
## Builds LOKI World's floating islands from Godot primitives and one generated ArrayMesh:
## a low-poly grass top, a dirt band, a rocky underside with glowing crystals, trees, rocks,
## flowers, houses, the stations of LOKI's agents, a pond with a waterfall off the edge.
## Everything static is baked by MeshMerger (2 draw calls per island).

const GRASS := Color(0.42, 0.74, 0.36)
const GRASS_DARK := Color(0.33, 0.62, 0.31)
const DIRT := Color(0.55, 0.38, 0.25)
const ROCK := Color(0.47, 0.43, 0.52)
const ROCK_DEEP := Color(0.33, 0.3, 0.42)
const TRUNK := Color(0.45, 0.3, 0.2)
const LEAF := Color(0.27, 0.6, 0.33)
const LEAF_LIGHT := Color(0.42, 0.72, 0.36)
const CRYSTAL := Color(0.25, 0.95, 0.88)
const PATH := Color(0.86, 0.78, 0.6)

## Where each LOKI agent works on the home island (angle in degrees, distance as a fraction of
## the radius). docs/WORLD.md: hall (LOKI), library (Researcher), drafting table (Architect),
## workshop (Builder), test bench (Tester), review desk (Reviewer), terminal (Browser tester).
const STATIONS := {
	"hall": [270.0, 0.0],
	"library": [200.0, 0.56],
	"drafting table": [235.0, 0.6],
	"workshop": [305.0, 0.6],
	"test bench": [340.0, 0.56],
	"review desk": [20.0, 0.56],
	"terminal": [55.0, 0.6],
	# where an agent stands while it works in the live Godot editor (engine/godot_live.py, 2026-10-18)
	"godot forge": [160.0, 0.58],
}
const STATION_COLORS := {
	"library": Color(0.25, 0.55, 0.95), "drafting table": Color(0.65, 0.4, 0.95),
	"workshop": Color(0.25, 0.8, 0.45), "test bench": Color(1.0, 0.75, 0.25),
	"review desk": Color(1.0, 0.5, 0.3), "terminal": Color(0.3, 0.45, 1.0),
	"godot forge": Color(0.28, 0.55, 0.75),
}


## The island's own mesh: top, dirt band and underside, with vertex colours, clockwise front faces.
static func island_mesh(radius: float, seed_value: int, segments: int = 22) -> ArrayMesh:
	var rng := RandomNumberGenerator.new()
	rng.seed = seed_value
	var rim: Array[Vector3] = []
	var mid: Array[Vector3] = []
	var band: Array[Vector3] = []
	var under1: Array[Vector3] = []
	var under2: Array[Vector3] = []
	for i in segments:
		var a := TAU * float(i) / float(segments)
		var d := Vector3(cos(a), 0.0, sin(a))
		var wob := rng.randf_range(0.93, 1.05)
		rim.append(d * radius * wob)
		mid.append(d * radius * 0.55 * rng.randf_range(0.9, 1.1) + Vector3(0, rng.randf_range(-0.05, 0.05), 0))
		band.append(d * radius * wob * 0.97 + Vector3(0, -0.8 - rng.randf_range(0.0, 0.3), 0))
		under1.append(d * radius * rng.randf_range(0.6, 0.7) + Vector3(0, -radius * rng.randf_range(0.3, 0.38), 0))
		under2.append(d * radius * rng.randf_range(0.22, 0.3) + Vector3(0, -radius * rng.randf_range(0.62, 0.72), 0))
	var tip := Vector3(rng.randf_range(-0.5, 0.5), -radius * 0.95, rng.randf_range(-0.5, 0.5))
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var centre := Vector3.ZERO
	for i in segments:
		var j := (i + 1) % segments
		var g := GRASS if (i % 3) != 0 else GRASS_DARK
		# top: centre fan to the mid ring, then the mid ring to the rim
		_tri(st, centre, mid[i], mid[j], g)
		_tri(st, mid[i], rim[i], rim[j], GRASS)
		_tri(st, mid[i], rim[j], mid[j], GRASS_DARK if (i % 2) == 0 else GRASS)
		# sides, outward: (B_up, A_up, A_lo), (B_up, A_lo, B_lo)
		_quad(st, rim[i], rim[j], band[i], band[j], DIRT)
		_quad(st, band[i], band[j], under1[i], under1[j], ROCK)
		_quad(st, under1[i], under1[j], under2[i], under2[j], ROCK_DEEP)
		_tri(st, under2[j], under2[i], tip, ROCK_DEEP)
	var mesh := st.commit()
	return mesh


static func _tri(st: SurfaceTool, a: Vector3, b: Vector3, c: Vector3, col: Color) -> void:
	st.set_color(col)
	st.add_vertex(a)
	st.set_color(col)
	st.add_vertex(b)
	st.set_color(col)
	st.add_vertex(c)


## An outward-facing quad between an upper pair (a_up at angle a, b_up at a + da) and a lower pair.
static func _quad(st: SurfaceTool, a_up: Vector3, b_up: Vector3, a_lo: Vector3, b_lo: Vector3, col: Color) -> void:
	_tri(st, b_up, a_up, a_lo, col)
	_tri(st, b_up, a_lo, b_lo, col)


## The island's ground: a cylinder collider whose top is y = 0.
static func ground_collider(body: StaticBody3D, radius: float) -> void:
	var shape := CylinderShape3D.new()
	shape.radius = radius * 0.94
	shape.height = 2.0
	var cs := CollisionShape3D.new()
	cs.shape = shape
	cs.position = Vector3(0, -1.0, 0)
	body.add_child(cs)


static func box_collider(body: StaticBody3D, pos: Vector3, size: Vector3, rot_y: float = 0.0) -> void:
	var shape := BoxShape3D.new()
	shape.size = size
	var cs := CollisionShape3D.new()
	cs.shape = shape
	cs.position = pos
	cs.rotation = Vector3(0, rot_y, 0)
	body.add_child(cs)


static func post_collider(body: StaticBody3D, pos: Vector3, radius: float, height: float) -> void:
	var shape := CylinderShape3D.new()
	shape.radius = radius
	shape.height = height
	var cs := CollisionShape3D.new()
	cs.shape = shape
	cs.position = pos + Vector3(0, height * 0.5, 0)
	body.add_child(cs)


static func xf(pos: Vector3, rot_y: float = 0.0, scale: Vector3 = Vector3.ONE, rot_x: float = 0.0, rot_z: float = 0.0) -> Transform3D:
	var b := Basis.from_euler(Vector3(rot_x, rot_y, rot_z)).scaled(scale)
	return Transform3D(b, pos)


## A low-poly tree: trunk and two or three stacked cones (or a round crown).
static func tree(m: MeshMerger, pos: Vector3, size: float, rng: RandomNumberGenerator) -> void:
	m.add(Mats.cyl(0.12 * size, 0.17 * size, 1.1 * size, 5), xf(pos + Vector3(0, 0.55 * size, 0)), TRUNK)
	var leaf := LEAF if rng.randf() < 0.6 else LEAF_LIGHT
	if rng.randf() < 0.7:
		var y := 1.0 * size
		for k in 3:
			var w := (1.0 - 0.25 * k) * size
			m.add(Mats.cyl(0.0, 0.85 * w, 1.1 * size, 6), xf(pos + Vector3(0, y + 0.55 * size, 0), rng.randf() * TAU), leaf.darkened(0.06 * k), true, 0.08)
			y += 0.6 * size
	else:
		m.add(Mats.ball(0.85 * size, 7, 4), xf(pos + Vector3(0, 1.6 * size, 0), rng.randf() * TAU), leaf, true, 0.1)


static func rock(m: MeshMerger, pos: Vector3, size: float, rng: RandomNumberGenerator) -> void:
	m.add(Mats.ball(0.5 * size, 6, 3), xf(pos + Vector3(0, 0.15 * size, 0), rng.randf() * TAU, Vector3(1.2, 0.7, 1.0)), ROCK.lightened(0.15), true, 0.12)


static func flowers(m: MeshMerger, pos: Vector3, rng: RandomNumberGenerator) -> void:
	var colors := [Color(1, 0.45, 0.55), Color(1, 0.85, 0.3), Color(0.7, 0.55, 1), Color(1, 1, 1)]
	for k in 5:
		var p := pos + Vector3(rng.randf_range(-0.7, 0.7), 0.0, rng.randf_range(-0.7, 0.7))
		m.add(Mats.box(Vector3(0.05, 0.3, 0.05)), xf(p + Vector3(0, 0.15, 0)), LEAF, false)
		m.add(Mats.box(Vector3(0.16, 0.12, 0.16)), xf(p + Vector3(0, 0.32, 0), rng.randf()), colors[rng.randi() % colors.size()], false)


## A house: walls, a prism roof, door and lit windows. Returns its footprint size for a collider.
static func house(m: MeshMerger, pos: Vector3, rot_y: float, size: Vector3, wall: Color, roof: Color) -> void:
	var basis := Basis.from_euler(Vector3(0, rot_y, 0))
	var t := Transform3D(basis, pos)
	m.add(Mats.box(size), t * Transform3D(Basis(), Vector3(0, size.y * 0.5, 0)), wall, true, 0.04)
	m.add(Mats.prism(Vector3(size.x + 0.5, size.y * 0.7, size.z + 0.5)), t * Transform3D(Basis(), Vector3(0, size.y + size.y * 0.35, 0)), roof, true, 0.05)
	m.add(Mats.box(Vector3(size.x * 0.22, size.y * 0.55, 0.1)), t * Transform3D(Basis(), Vector3(0, size.y * 0.275, size.z * 0.5 + 0.03)), Color(0.32, 0.2, 0.13), true)
	for side in [-1.0, 1.0]:
		m.add(Mats.box(Vector3(size.x * 0.16, size.y * 0.22, 0.08)), t * Transform3D(Basis(), Vector3(side * size.x * 0.3, size.y * 0.62, size.z * 0.5 + 0.03)), Color(1.0, 0.86, 0.45), false)


## Teal crystals hanging under an island (baked into a separate glowing mesh).
static func crystals(m: MeshMerger, radius: float, rng: RandomNumberGenerator, count: int) -> void:
	for k in count:
		var a := rng.randf() * TAU
		var r := rng.randf_range(0.15, 0.6) * radius
		var depth := -radius * (0.3 + 0.5 * (1.0 - r / radius)) * rng.randf_range(0.7, 1.0)
		var h := rng.randf_range(0.8, 2.2) * (radius / 10.0 + 0.5)
		var tilt := rng.randf_range(-0.35, 0.35)
		m.add(Mats.cyl(0.0, 0.32 * h, h, 5), xf(Vector3(cos(a) * r, depth - h * 0.4, sin(a) * r), rng.randf() * TAU, Vector3.ONE, PI + tilt, tilt),
				CRYSTAL.lerp(Color(0.6, 0.5, 1.0), rng.randf() * 0.4), true)


## A station desk with the prop of its trade, in the station's colour.
static func station(m: MeshMerger, body: StaticBody3D, name: String, pos: Vector3, face_y: float) -> void:
	var col: Color = STATION_COLORS.get(name, Color(0.6, 0.6, 0.6))
	var t := Transform3D(Basis.from_euler(Vector3(0, face_y, 0)), pos)
	# a small paved plot
	m.add(Mats.cyl(1.9, 2.0, 0.08, 8), t * Transform3D(Basis(), Vector3(0, 0.04, 0)), PATH, false)
	m.add(Mats.box(Vector3(1.6, 0.12, 0.8)), t * Transform3D(Basis(), Vector3(0, 0.9, 0)), Color(0.58, 0.4, 0.26))
	for sx in [-0.7, 0.7]:
		for sz in [-0.32, 0.32]:
			m.add(Mats.box(Vector3(0.1, 0.85, 0.1)), t * Transform3D(Basis(), Vector3(sx, 0.42, sz)), Color(0.45, 0.3, 0.2))
	match name:
		"library":
			for k in 3:
				m.add(Mats.box(Vector3(0.22, 0.3, 0.3)), t * Transform3D(Basis(), Vector3(-0.5 + 0.25 * k, 1.11, 0)), [col, Color(0.9, 0.3, 0.3), Color(0.95, 0.85, 0.4)][k])
			m.add(Mats.box(Vector3(1.6, 2.2, 0.4)), t * Transform3D(Basis(), Vector3(0, 1.1, -1.2)), Color(0.5, 0.33, 0.22))
		"drafting table":
			m.add(Mats.box(Vector3(1.3, 0.04, 0.7)), t * Transform3D(Basis.from_euler(Vector3(-0.35, 0, 0)), Vector3(0, 1.1, 0)), Color(0.85, 0.9, 1.0))
		"workshop":
			m.add(Mats.box(Vector3(0.8, 0.5, 0.6)), t * Transform3D(Basis(), Vector3(0, 1.21, 0)), Color(0.35, 0.36, 0.4))
			m.add(Mats.cyl(0.25, 0.35, 0.7, 6), t * Transform3D(Basis(), Vector3(1.4, 0.35, 0.6)), Color(0.85, 0.4, 0.2))
		"test bench":
			for k in 3:
				m.add(Mats.cyl(0.07, 0.12, 0.35, 6), t * Transform3D(Basis(), Vector3(-0.4 + 0.4 * k, 1.13, 0)), [Color(0.4, 1, 0.5), Color(1, 0.8, 0.3), Color(0.5, 0.7, 1)][k])
		"review desk":
			m.add(Mats.box(Vector3(0.6, 0.06, 0.4)), t * Transform3D(Basis(), Vector3(0.2, 0.99, 0)), Color(0.98, 0.96, 0.9))
			m.add(Mats.cyl(0.08, 0.08, 0.2, 6), t * Transform3D(Basis(), Vector3(-0.45, 1.06, 0)), Color(0.85, 0.2, 0.2))
		"godot forge":
			# an anvil and a big screen showing the editor: agents shape LOKI World itself here
			m.add(Mats.box(Vector3(0.7, 0.3, 0.35)), t * Transform3D(Basis(), Vector3(0.9, 0.55, 0.8)), Color(0.3, 0.32, 0.36))
			m.add(Mats.box(Vector3(0.3, 0.4, 0.25)), t * Transform3D(Basis(), Vector3(0.9, 0.2, 0.8)), Color(0.25, 0.26, 0.3))
			m.add(Mats.box(Vector3(1.3, 0.85, 0.08)), t * Transform3D(Basis(), Vector3(0, 1.45, -0.2)), Color(0.14, 0.16, 0.22))
			m.add(Mats.box(Vector3(1.18, 0.73, 0.02)), t * Transform3D(Basis(), Vector3(0, 1.45, -0.15)), Color(0.28, 0.55, 0.75), false)
			m.add(Mats.box(Vector3(0.5, 0.05, 0.03)), t * Transform3D(Basis(), Vector3(-0.2, 1.6, -0.13)), Color(0.95, 0.95, 1.0), false)
			m.add(Mats.box(Vector3(0.7, 0.05, 0.03)), t * Transform3D(Basis(), Vector3(-0.1, 1.45, -0.13)), Color(0.95, 0.8, 0.4), false)
		"terminal":
			m.add(Mats.box(Vector3(0.9, 0.6, 0.08)), t * Transform3D(Basis(), Vector3(0, 1.3, -0.2)), Color(0.12, 0.14, 0.2))
			m.add(Mats.box(Vector3(0.8, 0.5, 0.02)), t * Transform3D(Basis(), Vector3(0, 1.3, -0.15)), Color(0.3, 0.9, 1.0), false)
	# a banner pole in the station's colour
	m.add(Mats.cyl(0.05, 0.05, 2.6, 5), t * Transform3D(Basis(), Vector3(-1.2, 1.3, -0.6)), Color(0.5, 0.4, 0.3))
	m.add(Mats.box(Vector3(0.6, 0.8, 0.04)), t * Transform3D(Basis(), Vector3(-0.88, 2.2, -0.6)), col)
	box_collider(body, t * Vector3(0, 0.5, 0), Vector3(1.7, 1.0, 0.9), face_y)
