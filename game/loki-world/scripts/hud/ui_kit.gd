class_name UiKit
## The HUD's look: dark pixel panels with a light rim (hordes.io-like), bars, outlined text,
## and the hotbar icons drawn from lines and shapes (no image assets).

const PANEL := Color(0.07, 0.08, 0.11, 0.9)
const RIM := Color(0.32, 0.35, 0.45)
const TEXT := Color(0.93, 0.94, 0.97)
const DIM := Color(0.62, 0.65, 0.72)
const GOLD := Color(1.0, 0.85, 0.3)
const HP := Color(0.85, 0.22, 0.2)
const HP_FRIEND := Color(0.3, 0.8, 0.35)
const EN := Color(0.25, 0.55, 1.0)
const XP := Color(0.6, 0.35, 0.95)

static var _theme: Theme = null


static func font() -> Font:
	return ThemeDB.fallback_font


static func theme() -> Theme:
	if _theme != null:
		return _theme
	var t := Theme.new()
	t.default_font_size = 13
	t.set_stylebox("panel", "PanelContainer", panel_style())
	t.set_stylebox("panel", "Panel", panel_style())
	for state in ["normal", "hover", "pressed", "disabled", "focus"]:
		var sb := panel_style()
		sb.bg_color = {"normal": Color(0.16, 0.18, 0.24), "hover": Color(0.24, 0.27, 0.36), "pressed": Color(0.1, 0.11, 0.15),
				"disabled": Color(0.12, 0.12, 0.14), "focus": Color(0.16, 0.18, 0.24)}[state]
		if state == "focus":
			sb.draw_center = false
			sb.border_color = GOLD
		sb.content_margin_left = 8
		sb.content_margin_right = 8
		sb.content_margin_top = 3
		sb.content_margin_bottom = 3
		t.set_stylebox(state, "Button", sb)
	var le := panel_style()
	le.bg_color = Color(0.03, 0.04, 0.06, 0.9)
	le.content_margin_left = 6
	t.set_stylebox("normal", "LineEdit", le)
	t.set_stylebox("focus", "LineEdit", le)
	t.set_color("font_color", "Label", TEXT)
	t.set_color("font_color", "Button", TEXT)
	t.set_color("font_disabled_color", "Button", DIM)
	t.set_color("default_color", "RichTextLabel", TEXT)
	t.set_constant("outline_size", "Label", 4)
	t.set_color("font_outline_color", "Label", Color(0, 0, 0, 0.9))
	_theme = t
	return t


static func panel_style() -> StyleBoxFlat:
	var sb := StyleBoxFlat.new()
	sb.bg_color = PANEL
	sb.border_color = RIM
	sb.set_border_width_all(2)
	sb.set_corner_radius_all(2)
	sb.content_margin_left = 8
	sb.content_margin_right = 8
	sb.content_margin_top = 6
	sb.content_margin_bottom = 6
	return sb


static func text(ci: CanvasItem, pos: Vector2, s: String, color: Color = TEXT, size: int = 13, align: int = HORIZONTAL_ALIGNMENT_LEFT, width: float = -1.0) -> void:
	var f := font()
	ci.draw_string_outline(f, pos, s, align, width, size, 4, Color(0, 0, 0, 0.85))
	ci.draw_string(f, pos, s, align, width, size, color)


static func bar(ci: CanvasItem, r: Rect2, frac: float, color: Color, label: String = "") -> void:
	ci.draw_rect(r, Color(0.02, 0.02, 0.03, 0.9))
	var inner := Rect2(r.position + Vector2(1, 1), Vector2(maxf(0.0, (r.size.x - 2) * clampf(frac, 0.0, 1.0)), r.size.y - 2))
	ci.draw_rect(inner, color)
	ci.draw_rect(Rect2(inner.position, Vector2(inner.size.x, maxf(1.0, inner.size.y * 0.35))), color.lightened(0.25))
	ci.draw_rect(r, Color(0, 0, 0, 0.9), false, 1.0)
	if label != "" and r.size.y >= 10:
		text(ci, Vector2(r.position.x, r.position.y + r.size.y - 2), label, TEXT, int(clampf(r.size.y - 2, 9, 13)), HORIZONTAL_ALIGNMENT_CENTER, r.size.x)


static func frame(ci: CanvasItem, r: Rect2, bg: Color = PANEL, rim: Color = RIM) -> void:
	ci.draw_rect(r, bg)
	ci.draw_rect(r, rim, false, 2.0)


## A hotbar icon for a skill id, drawn in rect `r`.
static func icon(ci: CanvasItem, id: String, r: Rect2, col: Color) -> void:
	var c := r.get_center()
	var s := r.size.x * 0.5
	var w := maxf(2.0, s * 0.14)
	match id:
		"strike":
			ci.draw_line(c + Vector2(-s * 0.55, s * 0.55), c + Vector2(s * 0.55, -s * 0.55), Color(0.9, 0.92, 1.0), w * 1.4)
			ci.draw_line(c + Vector2(-s * 0.35, s * 0.05), c + Vector2(-s * 0.05, s * 0.35), GOLD, w * 1.2)
		"bolt":
			ci.draw_polyline(PackedVector2Array([c + Vector2(s * 0.1, -s * 0.7), c + Vector2(-s * 0.3, s * 0.05), c + Vector2(s * 0.2, -s * 0.05), c + Vector2(-s * 0.15, s * 0.7)]), Color(0.75, 0.65, 1.0), w * 1.3)
		"mend":
			ci.draw_rect(Rect2(c - Vector2(s * 0.15, s * 0.55), Vector2(s * 0.3, s * 1.1)), Color(0.4, 1.0, 0.5))
			ci.draw_rect(Rect2(c - Vector2(s * 0.55, s * 0.15), Vector2(s * 1.1, s * 0.3)), Color(0.4, 1.0, 0.5))
		"image":
			ci.draw_rect(Rect2(c - Vector2(s * 0.6, s * 0.45), Vector2(s * 1.2, s * 0.9)), Color(0.75, 0.55, 0.25), false, w)
			ci.draw_colored_polygon(PackedVector2Array([c + Vector2(-s * 0.45, s * 0.3), c + Vector2(-s * 0.05, -s * 0.15), c + Vector2(s * 0.45, s * 0.3)]), Color(0.4, 0.75, 0.4))
			ci.draw_circle(c + Vector2(s * 0.25, -s * 0.2), s * 0.12, GOLD)
		"research":
			ci.draw_arc(c + Vector2(-s * 0.1, -s * 0.1), s * 0.35, 0, TAU, 12, Color(0.6, 0.85, 1.0), w)
			ci.draw_line(c + Vector2(s * 0.15, s * 0.15), c + Vector2(s * 0.55, s * 0.55), Color(0.6, 0.85, 1.0), w * 1.4)
		"build":
			ci.draw_line(c + Vector2(-s * 0.45, s * 0.5), c + Vector2(s * 0.2, -s * 0.15), Color(0.7, 0.5, 0.3), w * 1.4)
			ci.draw_rect(Rect2(c + Vector2(-s * 0.05, -s * 0.6), Vector2(s * 0.6, s * 0.35)), Color(0.75, 0.77, 0.82))
		"video":
			ci.draw_rect(Rect2(c - Vector2(s * 0.6, s * 0.4), Vector2(s * 1.2, s * 0.8)), Color(0.85, 0.4, 0.6), false, w)
			ci.draw_colored_polygon(PackedVector2Array([c + Vector2(-s * 0.15, -s * 0.25), c + Vector2(s * 0.3, 0), c + Vector2(-s * 0.15, s * 0.25)]), TEXT)
		"game":
			ci.draw_rect(Rect2(c - Vector2(s * 0.65, s * 0.3), Vector2(s * 1.3, s * 0.6)), Color(0.5, 0.5, 0.6))
			ci.draw_rect(Rect2(c + Vector2(-s * 0.48, -s * 0.05), Vector2(s * 0.3, s * 0.1)), TEXT)
			ci.draw_rect(Rect2(c + Vector2(-s * 0.38, -s * 0.15), Vector2(s * 0.1, s * 0.3)), TEXT)
			ci.draw_circle(c + Vector2(s * 0.3, -s * 0.05), s * 0.08, Color(1, 0.4, 0.4))
			ci.draw_circle(c + Vector2(s * 0.45, s * 0.08), s * 0.08, Color(0.4, 0.8, 1))
		"hearth":
			ci.draw_rect(Rect2(c + Vector2(-s * 0.4, -s * 0.05), Vector2(s * 0.8, s * 0.55)), Color(0.9, 0.85, 0.75))
			ci.draw_colored_polygon(PackedVector2Array([c + Vector2(-s * 0.55, -s * 0.05), c + Vector2(0, -s * 0.55), c + Vector2(s * 0.55, -s * 0.05)]), Color(0.2, 0.7, 0.65))
		_:
			ci.draw_circle(c, s * 0.4, col)


static func button(text_: String, cb: Callable) -> Button:
	var b := Button.new()
	b.text = text_
	b.focus_mode = Control.FOCUS_NONE
	b.pressed.connect(cb)
	return b


static func label(text_: String, size: int = 13, color: Color = TEXT) -> Label:
	var l := Label.new()
	l.text = text_
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	return l
