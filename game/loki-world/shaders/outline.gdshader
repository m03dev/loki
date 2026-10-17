// LOKI World ink outlines: an inverted hull (front faces culled, pushed out, drawn flat ink).
// Used as next_pass on actors' toon materials. Merged island meshes bake their own hull instead.
// mode 0: push along the normal (smooth meshes)
// mode 1: push along sign(VERTEX) (boxes, prisms, cylinders centred on their origin: a true grown box)
shader_type spatial;
// depth_draw_never puts it in the alpha queue, so the grown hull never casts a shadow onto its own mesh
render_mode unshaded, cull_front, shadows_disabled, fog_disabled, depth_draw_never;

uniform vec4 ink : source_color = vec4(0.03, 0.03, 0.06, 1.0);
uniform float width = 0.03;
uniform int mode = 1;

void vertex() {
	// keep the line about the same on screen: grow it a little with distance
	float dist = length((MODELVIEW_MATRIX * vec4(VERTEX, 1.0)).xyz);
	float w = width * clamp(dist / 10.0, 1.0, 4.0);
	if (mode == 1) {
		VERTEX += sign(VERTEX) * w;
	} else {
		VERTEX += NORMAL * w;
	}
}

void fragment() {
	ALBEDO = ink.rgb;
}
