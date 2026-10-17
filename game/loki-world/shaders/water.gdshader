// Water: the pond (flat, slow shimmer bands) and the waterfall (vertical, fast falling stripes).
shader_type spatial;
render_mode unshaded, cull_disabled, shadows_disabled;

uniform vec4 deep : source_color = vec4(0.16, 0.45, 0.72, 1.0);
uniform vec4 light : source_color = vec4(0.62, 0.9, 1.0, 1.0);
uniform float falling = 0.0;   // 1 = waterfall
uniform float speed = 1.0;

void fragment() {
	vec2 uv = UV;
	float band;
	if (falling > 0.5) {
		float f = fract(uv.y * 6.0 - TIME * 1.6 * speed + sin(uv.x * 9.0) * 0.15);
		band = step(0.78, f) + step(0.93, fract(uv.x * 5.0 + uv.y * 0.3)) * 0.4;
		ALPHA = 0.88 - uv.y * 0.35;
	} else {
		float w = sin(uv.x * 23.0 + TIME * 0.9 * speed) * sin(uv.y * 19.0 - TIME * 0.7 * speed);
		band = step(0.72, w);
		ALPHA = 0.9;
	}
	ALBEDO = mix(deep.rgb, light.rgb, clamp(band, 0.0, 1.0) * 0.8);
}
