class_name Mats
## Shared materials for LOKI World's look: toon (cel bands) + ink outline, glow, water.
## One material per colour, cached, so a hundred red boxes share one material.

const TOON := preload("res://shaders/toon.gdshader")
const OUTLINE := preload("res://shaders/outline.gdshader")
const INK := preload("res://shaders/ink.gdshader")
const GLOW := preload("res://shaders/glow.gdshader")
const WATER := preload("res://shaders/water.gdshader")

const INK_COLOR := Color(0.03, 0.03, 0.06)

static var _toon: Dictionary = {}
static var _outline: Dictionary = {}
static var _glow: Dictionary = {}
static var _ink: ShaderMaterial = null
static var _vertex_toon: ShaderMaterial = null


## A cel-shaded material in `color`, with an ink outline pass (mode 1 = grown box, 0 = along normals).
static func toon(color: Color, outline: bool = true, outline_mode: int = 1, emission: Color = Color.BLACK) -> ShaderMaterial:
	var key := "%s|%s|%d|%s" % [color.to_html(), outline, outline_mode, emission.to_html()]
	if _toon.has(key):
		return _toon[key]
	var m := ShaderMaterial.new()
	m.shader = TOON
	m.set_shader_parameter("albedo", color)
	m.set_shader_parameter("emission", emission)
	if outline:
		m.next_pass = outline_pass(outline_mode)
	_toon[key] = m
	return m


static func outline_pass(mode: int = 1, width: float = 0.028) -> ShaderMaterial:
	var key := "%d|%.3f" % [mode, width]
	if _outline.has(key):
		return _outline[key]
	var m := ShaderMaterial.new()
	m.shader = OUTLINE
	m.set_shader_parameter("ink", INK_COLOR)
	m.set_shader_parameter("width", width)
	m.set_shader_parameter("mode", mode)
	_outline[key] = m
	return m


## The material of merged meshes: white albedo x the mesh's vertex colours.
static func vertex_toon() -> ShaderMaterial:
	if _vertex_toon == null:
		_vertex_toon = ShaderMaterial.new()
		_vertex_toon.shader = TOON
		_vertex_toon.set_shader_parameter("albedo", Color.WHITE)
	return _vertex_toon


static func ink() -> ShaderMaterial:
	if _ink == null:
		_ink = ShaderMaterial.new()
		_ink.shader = INK
		_ink.set_shader_parameter("ink", INK_COLOR)
	return _ink


static func glow(color: Color, strength: float = 0.7, stripes: float = 0.0) -> ShaderMaterial:
	var key := "%s|%.2f|%.2f" % [color.to_html(), strength, stripes]
	if _glow.has(key):
		return _glow[key]
	var m := ShaderMaterial.new()
	m.shader = GLOW
	m.set_shader_parameter("color", color)
	m.set_shader_parameter("strength", strength)
	m.set_shader_parameter("stripes", stripes)
	_glow[key] = m
	return m


static func water(falling: bool) -> ShaderMaterial:
	var m := ShaderMaterial.new()
	m.shader = WATER
	m.set_shader_parameter("falling", 1.0 if falling else 0.0)
	return m


## A flat picture (a creation LOKI made) on a quad: unshaded so the colours stay true.
static func picture(tex: Texture2D) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.albedo_texture = tex
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_NEAREST
	return m


## A mesh part: `mesh` placed at `pos` under `parent`, cel-shaded in `color` with an ink outline.
static func part(parent: Node3D, mesh: Mesh, color: Color, pos: Vector3, rot: Vector3 = Vector3.ZERO,
		outline: bool = true) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.position = pos
	mi.rotation = rot
	mi.material_override = toon(color, outline)
	parent.add_child(mi)
	return mi


static func box(size: Vector3) -> BoxMesh:
	var b := BoxMesh.new()
	b.size = size
	return b


static func cyl(top: float, bottom: float, height: float, sides: int = 6) -> CylinderMesh:
	var c := CylinderMesh.new()
	c.top_radius = top
	c.bottom_radius = bottom
	c.height = height
	c.radial_segments = sides
	c.rings = 1
	return c


static func ball(radius: float, segments: int = 8, rings: int = 5) -> SphereMesh:
	var s := SphereMesh.new()
	s.radius = radius
	s.height = radius * 2.0
	s.radial_segments = segments
	s.rings = rings
	return s


static func prism(size: Vector3) -> PrismMesh:
	var p := PrismMesh.new()
	p.size = size
	return p
