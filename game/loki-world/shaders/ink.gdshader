// The baked ink hull of a merged island mesh: the hull geometry is already grown at build time
// (scripts/world/mesh_merger.gd), so this only draws it flat, back faces only.
shader_type spatial;
// depth_draw_never: alpha queue, so the hull casts no shadow onto the island it wraps
render_mode unshaded, cull_front, shadows_disabled, depth_draw_never;

uniform vec4 ink : source_color = vec4(0.03, 0.03, 0.06, 1.0);

void fragment() {
	ALBEDO = ink.rgb;
}
