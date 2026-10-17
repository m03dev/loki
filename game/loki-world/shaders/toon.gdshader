// LOKI World toon shading: flat low-poly faces, 4 hard light bands, no specular.
// Colour = albedo x vertex colour (merged island meshes carry their colours per vertex).
// Ambient light comes from the world's Environment (day/night sets its colour and energy).
shader_type spatial;
render_mode specular_disabled;

uniform vec4 albedo : source_color = vec4(1.0);
uniform vec4 emission : source_color = vec4(0.0, 0.0, 0.0, 1.0);
uniform float bands = 4.0;
uniform float shade_floor = 0.38;   // the darkest lit band is never black: soft and readable
uniform float flat_shading = 1.0;

void fragment() {
	if (flat_shading > 0.5) {
		// faceted look: one normal per triangle, from screen-space derivatives (works on GL Compatibility)
		vec3 n = normalize(cross(dFdx(VERTEX), dFdy(VERTEX)));
		if (dot(n, -VERTEX) < 0.0) {
			n = -n;
		}
		NORMAL = n;
	}
	ALBEDO = albedo.rgb * COLOR.rgb;
	EMISSION = emission.rgb;
}

void light() {
	float nl = clamp(dot(NORMAL, LIGHT), 0.0, 1.0) * ATTENUATION;
	// hard bands: with 4 bands the steps are 0, 1/3, 2/3, 1, lifted above the shade floor
	float q = floor(nl * (bands - 1.0) + 0.5) / (bands - 1.0);
	// the renderer multiplies DIFFUSE_LIGHT by ALBEDO afterwards
	DIFFUSE_LIGHT += LIGHT_COLOR / PI * mix(shade_floor * step(0.001, nl), 1.0, q);
}
