// Bridges of light, beacons and spell effects: unshaded, softly pulsing, see-through.
shader_type spatial;
render_mode unshaded, blend_add, cull_disabled, shadows_disabled, depth_draw_never;

uniform vec4 color : source_color = vec4(0.3, 1.0, 0.95, 1.0);
uniform float strength = 0.7;
uniform float pulse = 1.0;
uniform float stripes = 0.0;   // > 0: packets running along the local z axis

varying vec3 local_pos;

void vertex() {
	local_pos = VERTEX;
}

void fragment() {
	float p = 0.75 + 0.25 * sin(TIME * 2.4 * pulse);
	float s = 1.0;
	if (stripes > 0.0) {
		s = 0.55 + 0.45 * step(0.82, fract(local_pos.z * stripes * 0.1 - TIME * 0.6));
	}
	ALBEDO = color.rgb * strength * p * s;
}
