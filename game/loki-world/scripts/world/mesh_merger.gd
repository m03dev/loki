class_name MeshMerger
extends RefCounted
## Bakes many small static parts (island, trees, houses, crystals) into ONE mesh with vertex
## colours, plus ONE ink hull mesh (each part grown about its own centre, drawn back faces only).
## A whole island is then 2 draw calls instead of hundreds - the same trick as app/ui/world.js.

var ink_width := 0.06
var _verts := PackedVector3Array()
var _norms := PackedVector3Array()
var _cols := PackedColorArray()
var _ink := PackedVector3Array()


## Add `mesh` (any Mesh; surface 0) placed by `xform`, tinted `color` (times its own vertex
## colours if it has them). `ink` = give it an outline. `shade` > 0 darkens faces randomly a
## little so big flat surfaces are not one colour.
func add(mesh: Mesh, xform: Transform3D, color: Color, ink: bool = true, shade: float = 0.0) -> void:
	if mesh == null or mesh.get_surface_count() == 0:
		return
	var arrays := mesh.surface_get_arrays(0)
	var v: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var n: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL] if arrays[Mesh.ARRAY_NORMAL] != null else PackedVector3Array()
	var c: PackedColorArray = arrays[Mesh.ARRAY_COLOR] if arrays[Mesh.ARRAY_COLOR] != null else PackedColorArray()
	var idx: PackedInt32Array = arrays[Mesh.ARRAY_INDEX] if arrays[Mesh.ARRAY_INDEX] != null else PackedInt32Array()
	var order := idx
	if order.is_empty():
		order.resize(v.size())
		for i in v.size():
			order[i] = i
	var basis := xform.basis
	var nb := basis.inverse().transposed()
	# the ink hull: the part scaled about its own bounding-box centre so it is `ink_width` bigger
	# on every side, in world units (divide by the part's own scale)
	var aabb := mesh.get_aabb()
	var centre := aabb.get_center()
	var sc := basis.get_scale()
	var grow := Vector3.ONE
	for axis in 3:
		var size: float = max(aabb.size[axis], 0.001)
		var local_w: float = ink_width / max(abs(sc[axis]), 0.001)
		grow[axis] = (size + 2.0 * local_w) / size
	var tri_shade := 1.0
	var tri := 0
	for k in order.size():
		var i: int = order[k]
		if k % 3 == 0:
			tri += 1
			tri_shade = 1.0 - shade * _noise(tri, v[i])
		var p: Vector3 = v[i]
		_verts.append(xform * p)
		_norms.append((nb * n[i]).normalized() if i < n.size() else Vector3.UP)
		var col := color * (c[i] if i < c.size() else Color.WHITE)
		col.r *= tri_shade
		col.g *= tri_shade
		col.b *= tri_shade
		col.a = 1.0
		_cols.append(col)
		if ink:
			_ink.append(xform * (centre + (p - centre) * grow))


func is_empty() -> bool:
	return _verts.is_empty()


## The merged solid mesh (cel-shaded with vertex colours).
func build_solid() -> ArrayMesh:
	var am := ArrayMesh.new()
	if _verts.is_empty():
		return am
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = _verts
	arrays[Mesh.ARRAY_NORMAL] = _norms
	arrays[Mesh.ARRAY_COLOR] = _cols
	am.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	am.surface_set_material(0, Mats.vertex_toon())
	return am


## The merged ink hull (null when nothing asked for an outline).
func build_ink() -> ArrayMesh:
	if _ink.is_empty():
		return null
	var am := ArrayMesh.new()
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = _ink
	am.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	am.surface_set_material(0, Mats.ink())
	return am


## Put both under `parent` as two MeshInstance3Ds; returns the solid one.
func commit(parent: Node3D, name_prefix: String = "Baked", material: Material = null) -> MeshInstance3D:
	var solid := MeshInstance3D.new()
	solid.name = name_prefix
	solid.mesh = build_solid()
	if material != null:
		solid.material_override = material
	parent.add_child(solid)
	var ink_mesh := build_ink()
	if ink_mesh != null:
		var hull := MeshInstance3D.new()
		hull.name = name_prefix + "Ink"
		hull.mesh = ink_mesh
		hull.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		parent.add_child(hull)
	return solid


static func _noise(i: int, p: Vector3) -> float:
	var h := sin(float(i) * 12.9898 + p.x * 78.233 + p.z * 37.719) * 43758.5453
	return h - floor(h)
