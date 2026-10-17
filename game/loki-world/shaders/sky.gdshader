// LOKI World sky: a three-colour gradient that the day/night cycle drives, a square pixel sun,
// and blocky stars that fade in at night.
shader_type sky;

uniform vec4 zenith : source_color = vec4(0.27, 0.52, 0.86, 1.0);
uniform vec4 horizon : source_color = vec4(0.78, 0.88, 0.96, 1.0);
uniform vec4 below : source_color = vec4(0.36, 0.45, 0.62, 1.0);
uniform vec4 sun_color : source_color = vec4(1.0, 0.93, 0.7, 1.0);
uniform float night = 0.0;

float hash3(vec3 p) {
	return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453);
}

void sky() {
	float y = EYEDIR.y;
	vec3 c = mix(horizon.rgb, zenith.rgb, clamp(y * 1.7, 0.0, 1.0));
	if (y < 0.0) {
		c = mix(horizon.rgb, below.rgb, clamp(-y * 2.2, 0.0, 1.0));
	}
	if (LIGHT0_ENABLED) {
		float s = dot(EYEDIR, LIGHT0_DIRECTION);
		if (s > 0.9975) {
			c = mix(c, sun_color.rgb, 0.95);
		} else if (s > 0.990) {
			c = mix(c, sun_color.rgb, 0.25);
		}
	}
	vec3 cell = floor(EYEDIR * 90.0);
	float h = hash3(cell);
	if (h > 0.9965 && y > -0.05) {
		c += vec3(0.9, 0.92, 1.0) * night * (0.5 + 0.5 * sin(TIME * 2.0 + h * 50.0));
	}
	COLOR = c;
}
