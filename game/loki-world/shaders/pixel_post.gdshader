// LOKI World's pixel look, as a post-process on the low-resolution 3D view:
// the world is rendered small (SubViewportContainer.stretch_shrink) and shown with nearest
// filtering; this shader posterizes each colour channel with a 4x4 Bayer dither.
shader_type canvas_item;

uniform float levels = 28.0;     // colour steps per channel
uniform float dither = 0.85;     // 0 = plain posterize
uniform float saturation = 1.08;
uniform float vignette = 0.18;

const float BAYER[16] = float[16](0.0, 8.0, 2.0, 10.0, 12.0, 4.0, 14.0, 6.0,
		3.0, 11.0, 1.0, 9.0, 15.0, 7.0, 13.0, 5.0);

void fragment() {
	vec4 c = texture(TEXTURE, UV);
	vec2 px = floor(UV / TEXTURE_PIXEL_SIZE);
	int i = int(mod(px.x, 4.0)) + int(mod(px.y, 4.0)) * 4;
	float t = (BAYER[i] + 0.5) / 16.0 - 0.5;
	vec3 col = c.rgb;
	float grey = dot(col, vec3(0.299, 0.587, 0.114));
	col = mix(vec3(grey), col, saturation);
	vec2 d = UV - vec2(0.5);
	col *= 1.0 - vignette * dot(d, d) * 2.0;
	col = floor(col * levels + 0.5 + t * dither) / levels;
	COLOR = vec4(clamp(col, 0.0, 1.0), 1.0);
}
