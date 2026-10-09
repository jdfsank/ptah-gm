extends GridContainer

## puzzle-board: procedural buttons that render supplied state and emit choices.
## The editable accent has a single authority: design/game.json.

signal cell_selected(row: int, column: int)

const StudioRuntimeSource = preload("res://studio/runtime.gd")
const GRID_SIZE: int = 3
const CELL_SIDE: float = 88.0
const CELL_GAP: int = 10
const OFF_FILL: Color = Color("#1E293B")
const OFF_BORDER: Color = Color("#475569")
const LIT_TEXT: Color = Color("#0B1220")
const OFF_TEXT: Color = Color("#E2E8F0")

var _buttons: Array[Button] = []
var _lit_styles: Dictionary = {}
var _off_styles: Dictionary = {}


func _ready() -> void:
	var runtime := StudioRuntimeSource.new()
	var accent_hex: String = str(runtime.object_value("puzzle-board", "accent-color", ""))
	if not Color.html_is_valid(accent_hex):
		push_error("Light Grid: puzzle-board.accent-color must be a valid design color.")
	var accent: Color = Color.from_string(accent_hex, Color.WHITE)
	_lit_styles = _make_styles(accent, accent.darkened(0.18))
	_off_styles = _make_styles(OFF_FILL, OFF_BORDER)
	columns = GRID_SIZE
	add_theme_constant_override("h_separation", CELL_GAP)
	add_theme_constant_override("v_separation", CELL_GAP)
	for row in range(GRID_SIZE):
		for column in range(GRID_SIZE):
			_create_cell(row, column)


func render_state(cells: Array[bool], solved: bool) -> void:
	for index in range(_buttons.size()):
		var button: Button = _buttons[index]
		var lit: bool = cells[index]
		var styles: Dictionary = _lit_styles if lit else _off_styles
		var text_color: Color = LIT_TEXT if lit else OFF_TEXT
		button.text = "ON" if lit else "OFF"
		button.disabled = solved
		button.mouse_default_cursor_shape = (
			Control.CURSOR_ARROW if solved else Control.CURSOR_POINTING_HAND
		)
		for style_name in styles:
			button.add_theme_stylebox_override(style_name, styles[style_name])
		for color_name in [
			&"font_color", &"font_hover_color", &"font_pressed_color",
			&"font_focus_color", &"font_disabled_color", &"font_hover_pressed_color",
		]:
			button.add_theme_color_override(color_name, text_color)


func _create_cell(row: int, column: int) -> void:
	var button := Button.new()
	button.name = "Cell_%d_%d" % [row, column]
	button.custom_minimum_size = Vector2(CELL_SIDE, CELL_SIDE)
	button.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	button.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	button.focus_mode = Control.FOCUS_ALL
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.text = "OFF"
	button.add_theme_font_size_override("font_size", 20)
	button.tooltip_text = "Row %d, column %d: toggle this square and its orthogonal neighbors." % [
		row + 1, column + 1,
	]
	button.pressed.connect(_on_cell_pressed.bind(row, column))
	_buttons.append(button)
	add_child(button)


func _on_cell_pressed(row: int, column: int) -> void:
	cell_selected.emit(row, column)


func _make_styles(fill: Color, border: Color) -> Dictionary:
	var focus := _make_style(Color.TRANSPARENT, Color.WHITE, 2)
	focus.draw_center = false
	focus.expand_margin_left = 3.0
	focus.expand_margin_top = 3.0
	focus.expand_margin_right = 3.0
	focus.expand_margin_bottom = 3.0
	return {
		&"normal": _make_style(fill, border, 2),
		&"hover": _make_style(fill.lightened(0.14), Color.WHITE, 3),
		&"pressed": _make_style(fill.darkened(0.14), Color.WHITE, 3),
		&"disabled": _make_style(fill, border, 2),
		&"focus": focus,
	}


func _make_style(fill: Color, border: Color, border_width: int) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(border_width)
	style.set_corner_radius_all(10)
	return style
