class_name HomeBuilder
extends RefCounted
## The home island as EDITABLE pieces (owner, 2026-10-18: "loki world [is] an editable project in godot").
##
## Before, world.gd built the whole island into one merged mesh while the game ran, so the Godot editor showed an empty
## scene. Now every object is its own node - Hall, Plaza, Station_<name>, CreationsHall, ForgeShelf, Pond, Waterfall,
## Tree_<n>, Rock_<n>, Flowers_<n>, Crystals, Sign - each with its meshes, ink outline and colliders under it.
## tools/bake_world.gd runs this once and saves scenes/home_island.tscn; you open LOKI World in Godot and move, delete,
## duplicate or edit anything, and the game uses YOUR scene (world.gd builds it from code only when it is missing).
##
## A piece is a Node3D at its pivot (move/rotate it in the editor) with a child "Geo" at -pivot that holds the mesh and
## the StaticBody in island coordinates - the builders below stay exactly as they were.
##
## What the game reads from the scene, so you can move these too:
##   group "loki_station" + meta "station" = where an agent of that station stands (the piece's position)
##   group "loki_painting" + meta "index" = the creations hall's picture frames (0..4)
##   group "loki_shelf_spot" + meta "index" = the tops of the Forge shelf's pedestals (0..2)

const HOME_RADIUS := 16.0
const SPAWN := Vector3(0, 0.3, 6.0)


static func station_point(station: String) -> Vector3:
	var s: Array = IslandBuilder.STATIONS.get(station, IslandBuilder.STATIONS["workshop"])
	var a := deg_to_rad(float(s[0]))
	var r := float(s[1]) * HOME_RADIUS
	if station == "hall":
		return Vector3(0, 0, -HOME_RADIUS * 0.38 + 3.6)
	return Vector3(cos(a) * r, 0, sin(a) * r)


class Piece:
	var node: Node3D
	var geo: Node3D
	var m: MeshMerger
	var body: StaticBody3D
	var name: String

	func _init(parent: Node3D, name_: String, pivot: Vector3) -> void:
		name = name_
		node = Node3D.new()
		node.name = name_
		node.position = pivot
		parent.add_child(node)
		geo = Node3D.new()
		geo.name = "Geo"
		geo.position = -pivot
		node.add_child(geo)
		m = MeshMerger.new()

	func collider() -> StaticBody3D:
		if body == null:
			body = StaticBody3D.new()
			body.name = "Collision"
			geo.add_child(body)
		return body

	func commit(material: Material = null) -> void:
		if not m.is_empty():
			m.commit(geo, "Mesh", material)


static func build(root: Node3D) -> Node3D:
	var island := Node3D.new()
	island.name = "HomeIsland"
	root.add_child(island)
	var rng := RandomNumberGenerator.new()
	rng.seed = 1776
	var pieces: Array = []
	var keep_out: Array = []

	# the ground: the island itself
	var ground := Piece.new(island, "Ground", Vector3.ZERO)
	ground.m.add(IslandBuilder.island_mesh(HOME_RADIUS, 77, 26), Transform3D(), Color.WHITE, true, 0.05)
	IslandBuilder.ground_collider(ground.collider(), HOME_RADIUS)
	pieces.append(ground)

	# LOKI's hall, north: the big house with horns over the door
	var hall_p := Vector3(0, 0, -HOME_RADIUS * 0.38)
	var hall := Piece.new(island, "Hall", hall_p)
	IslandBuilder.house(hall.m, hall_p, 0.0, Vector3(6.0, 3.4, 4.6), Color(0.93, 0.88, 0.78), Color(0.15, 0.62, 0.6))
	hall.m.add(Mats.cyl(0.0, 0.25, 1.0, 5), IslandBuilder.xf(hall_p + Vector3(-1.1, 6.4, 1.2), 0, Vector3.ONE, 0, 0.6), Color(0.95, 0.9, 0.75))
	hall.m.add(Mats.cyl(0.0, 0.25, 1.0, 5), IslandBuilder.xf(hall_p + Vector3(1.1, 6.4, 1.2), 0, Vector3.ONE, 0, -0.6), Color(0.95, 0.9, 0.75))
	IslandBuilder.box_collider(hall.collider(), hall_p + Vector3(0, 1.7, 0), Vector3(6.0, 3.4, 4.6))
	_mark_station(hall.node, "hall", station_point("hall") - hall_p)
	pieces.append(hall)
	keep_out.append(hall_p)

	# the plaza and its fountain
	var plaza := Piece.new(island, "Plaza", Vector3.ZERO)
	plaza.m.add(Mats.cyl(4.2, 4.4, 0.08, 12), IslandBuilder.xf(Vector3(0, 0.04, 0)), IslandBuilder.PATH, false)
	plaza.m.add(Mats.cyl(0.9, 1.1, 0.5, 8), IslandBuilder.xf(Vector3(0, 0.25, 0)), Color(0.7, 0.68, 0.72))
	plaza.m.add(Mats.cyl(0.18, 0.18, 2.6, 6), IslandBuilder.xf(Vector3(0, 1.5, 0)), Color(0.75, 0.73, 0.8))
	IslandBuilder.post_collider(plaza.collider(), Vector3.ZERO, 1.0, 0.6)
	pieces.append(plaza)
	keep_out.append(Vector3.ZERO)
	keep_out.append(SPAWN)

	# the stations of LOKI's agents
	for st in IslandBuilder.STATIONS.keys():
		if st == "hall":
			continue
		var p := station_point(st)
		var face := atan2(-p.x, -p.z)
		var piece := Piece.new(island, "Station_" + str(st).replace(" ", "_"), p)
		IslandBuilder.station(piece.m, piece.collider(), st, p, face)
		_mark_station(piece.node, st, Vector3.ZERO)
		pieces.append(piece)
		keep_out.append(p)

	# the creations hall (pink roof): the newest pictures LOKI made hang on its front wall
	var ch := Vector3(cos(deg_to_rad(125.0)), 0, sin(deg_to_rad(125.0))) * HOME_RADIUS * 0.66
	var ch_face := atan2(-ch.x, -ch.z)
	var chp := Piece.new(island, "CreationsHall", ch)
	IslandBuilder.house(chp.m, ch, ch_face, Vector3(5.6, 2.8, 2.6), Color(0.96, 0.92, 0.95), Color(0.95, 0.45, 0.65))
	IslandBuilder.box_collider(chp.collider(), ch + Vector3(0, 1.4, 0), Vector3(5.6, 2.8, 2.6), ch_face)
	var basis := Basis.from_euler(Vector3(0, ch_face, 0))
	for k in 5:
		var local := Vector3(-2.2 + 1.1 * k, 1.75, 1.36)
		if k == 2:
			local = Vector3(0, 2.15, 1.36)   # the door is in the middle: hang the newest above it
		var frame_pos := ch + basis * local
		chp.m.add(Mats.box(Vector3(0.95, 0.75, 0.06)), Transform3D(basis, frame_pos), Color(0.75, 0.55, 0.25))
		var pic := MeshInstance3D.new()
		pic.name = "Painting_%d" % k
		var quad := QuadMesh.new()
		quad.size = Vector2(0.8, 0.6)
		pic.mesh = quad
		pic.transform = Transform3D(basis, frame_pos + basis * Vector3(0, 0, 0.04))
		pic.visible = false
		pic.set_meta("index", k)
		pic.add_to_group("loki_painting", true)
		chp.geo.add_child(pic)
	pieces.append(chp)
	keep_out.append(ch)

	# the Forge shelf: three pedestals in front of the creations hall
	var shelf_c := ch + basis * Vector3(0, 0, 3.0)
	var shelf := Piece.new(island, "ForgeShelf", shelf_c)
	for k in 3:
		var spot := ch + basis * Vector3(-1.8 + 1.8 * k, 0, 3.0)
		shelf.m.add(Mats.cyl(0.45, 0.55, 0.7, 8), IslandBuilder.xf(spot + Vector3(0, 0.35, 0)), Color(0.82, 0.78, 0.86))
		shelf.m.add(Mats.cyl(0.52, 0.52, 0.08, 8), IslandBuilder.xf(spot + Vector3(0, 0.74, 0)), Color(0.95, 0.45, 0.65))
		IslandBuilder.box_collider(shelf.collider(), spot + Vector3(0, 0.35, 0), Vector3(0.9, 0.7, 0.9))
		var mark := Marker3D.new()
		mark.name = "Spot_%d" % k
		mark.position = spot + Vector3(0, 0.78, 0)
		mark.set_meta("index", k)
		mark.add_to_group("loki_shelf_spot", true)
		shelf.geo.add_child(mark)
	pieces.append(shelf)

	# the pond and the waterfall off the east edge
	var pond_a := deg_to_rad(95.0)
	var pond_c := Vector3(cos(pond_a), 0, sin(pond_a)) * HOME_RADIUS * 0.8
	var pond := Piece.new(island, "Pond", pond_c)
	var water := MeshInstance3D.new()
	water.name = "Water"
	water.mesh = Mats.cyl(2.2, 2.2, 0.05, 10)
	water.position = pond_c + Vector3(0, 0.06, 0)
	water.material_override = Mats.water(false)
	pond.geo.add_child(water)
	pond.m.add(Mats.cyl(2.5, 2.6, 0.1, 10), IslandBuilder.xf(pond_c + Vector3(0, 0.02, 0)), Color(0.55, 0.5, 0.48), false)
	for k in 8:
		var a := TAU * k / 8.0
		IslandBuilder.rock(pond.m, pond_c + Vector3(cos(a) * 2.5, 0, sin(a) * 2.5), 0.7, rng)
	pieces.append(pond)
	keep_out.append(pond_c)
	var out_dir := Vector3(cos(pond_a), 0, sin(pond_a))
	var fall_p := out_dir * (HOME_RADIUS * 0.93)
	var fall := Piece.new(island, "Waterfall", fall_p)
	var sheet := MeshInstance3D.new()
	sheet.name = "Sheet"
	var fq := QuadMesh.new()
	fq.size = Vector2(2.0, 30.0)
	sheet.mesh = fq
	sheet.position = out_dir * (HOME_RADIUS * 1.02) + Vector3(0, -15.0, 0)
	sheet.rotation.y = atan2(out_dir.x, out_dir.z)
	sheet.material_override = Mats.water(true)
	fall.geo.add_child(sheet)
	fall.m.add(Mats.box(Vector3(1.4, 0.12, HOME_RADIUS * 0.22)), Transform3D(Basis.from_euler(Vector3(0, atan2(out_dir.x, out_dir.z), 0)), out_dir * HOME_RADIUS * 0.93 + Vector3(0, 0.02, 0)), Color(0.35, 0.65, 0.9), false)
	pieces.append(fall)

	# trees, rocks and flowers, kept off the paths and the stations - each its own piece
	var nature := Node3D.new()
	nature.name = "Nature"
	island.add_child(nature)
	var placed := 0
	var tries := 0
	while placed < 26 and tries < 400:
		tries += 1
		var a := rng.randf() * TAU
		var r := rng.randf_range(0.25, 0.9) * HOME_RADIUS
		var p := Vector3(cos(a) * r, 0, sin(a) * r)
		var ok := true
		for k in keep_out:
			if (k as Vector3).distance_to(p) < 3.6:
				ok = false
				break
		if not ok:
			continue
		keep_out.append(p)
		placed += 1
		if rng.randf() < 0.75:
			var size := rng.randf_range(0.9, 1.5)
			var tree := Piece.new(nature, "Tree_%d" % placed, p)
			IslandBuilder.tree(tree.m, p, size, rng)
			IslandBuilder.post_collider(tree.collider(), p, 0.3 * size, 2.0)
			pieces.append(tree)
		elif rng.randf() < 0.5:
			var rock := Piece.new(nature, "Rock_%d" % placed, p)
			IslandBuilder.rock(rock.m, p, rng.randf_range(0.8, 1.6), rng)
			pieces.append(rock)
		else:
			var fl := Piece.new(nature, "Flowers_%d" % placed, p)
			IslandBuilder.flowers(fl.m, p, rng)
			pieces.append(fl)
	for k in 10:
		var a := rng.randf() * TAU
		var p := Vector3(cos(a), 0, sin(a)) * rng.randf_range(0.3, 0.9) * HOME_RADIUS
		var fl := Piece.new(nature, "Flowers_extra_%d" % k, p)
		IslandBuilder.flowers(fl.m, p, rng)
		pieces.append(fl)
	for piece in pieces:
		(piece as Piece).commit()
	var glow := Piece.new(island, "Crystals", Vector3.ZERO)
	glow.m.ink_width = 0.04
	IslandBuilder.crystals(glow.m, HOME_RADIUS, rng, 22)
	glow.commit(Mats.toon(Color.WHITE, false, 1, Color(0.06, 0.35, 0.33)))
	var sign := Label3D.new()
	sign.name = "Sign"
	sign.text = "you are here"
	sign.position = Vector3(0, 3.4, 0)
	sign.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	sign.modulate = Color(0.6, 1.0, 0.9)
	sign.outline_modulate = Color(0.02, 0.02, 0.05)
	sign.outline_size = 10
	sign.font_size = 40
	sign.pixel_size = 0.004
	sign.texture_filter = BaseMaterial3D.TEXTURE_FILTER_NEAREST
	island.add_child(sign)
	return island


static func _mark_station(piece: Node3D, station: String, stand: Vector3) -> void:
	piece.add_to_group("loki_station", true)
	piece.set_meta("station", station)
	piece.set_meta("stand", stand)       # where the agent stands, relative to the piece


## Every node under `node` belongs to `owner` (so PackedScene.pack saves it).
static func own(node: Node, owner: Node) -> void:
	for c in node.get_children():
		c.owner = owner
		own(c, owner)
