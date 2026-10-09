extends Control

## hud: displays supplied progress and emits reset requests without model access.

signal reset_requested

const TEXT_COLOR: Color = Color("#E2E8F0")
const MUTED_COLOR: Color = Color("#B8C5D6")
const WIN_COLOR: Color = Color("#6EE7B7")

var _moves_label: Label
var _win_label: Label
var _reset_button: Button
var _showing_win: bool = false


func _ready() -> void:
	# The HUD spans the window; only the Reset control receives mouse events.
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_make_label("Title", "Light Grid", Rect2(0, 18, 960, 48), 38, TEXT_COLOR)
	_make_label(
		"Instructions",
		"Click a square to toggle it and its orthogonal neighbors.\n"
		+ "Turn every light OFF. Press R to reset.",
		Rect2(140, 71, 680, 40),
		16,
		MUTED_COLOR
	)
	_moves_label = _make_label(
		"Moves", "Moves: 0", Rect2(332, 484, 164, 40), 20, TEXT_COLOR, false
	)
	_win_label = _make_label(
		"WinMessage", "", Rect2(160, 440, 640, 34), 24, WIN_COLOR
	)
	_win_label.visible = false
	_create_reset_button()


func render_progress(moves: int, solved: bool) -> void:
	_moves_label.text = "Moves: %d" % moves
	_win_label.text = "All lights out!" if solved else ""
	_win_label.visible = solved
	if solved and not _showing_win:
		_reset_button.grab_focus()
	_showing_win = solved


func _make_label(
	node_name: String,
	text: String,
	bounds: Rect2,
	font_size: int,
	text_color: Color,
	centered: bool = true
) -> Label:
	var label := Label.new()
	label.name = node_name
	label.text = text
	label.position = bounds.position
	label.size = bounds.size
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER if centered else HORIZONTAL_ALIGNMENT_LEFT
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", text_color)
	add_child(label)
	return label


func _create_reset_button() -> void:
	_reset_button = Button.new()
	_reset_button.name = "Reset"
	_reset_button.position = Vector2(508, 484)
	_reset_button.size = Vector2(120, 40)
	_reset_button.text = "Reset"
	_reset_button.focus_mode = Control.FOCUS_ALL
	_reset_button.mouse_filter = Control.MOUSE_FILTER_STOP
	_reset_button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	_reset_button.tooltip_text = "Reset the fixed puzzle (R)"
	_reset_button.add_theme_font_size_override("font_size", 18)
	_reset_button.add_theme_color_override("font_color", TEXT_COLOR)
	_reset_button.add_theme_color_override("font_hover_color", Color.WHITE)
	_reset_button.add_theme_color_override("font_pressed_color", Color.WHITE)
	_reset_button.add_theme_color_override("font_focus_color", TEXT_COLOR)
	_reset_button.add_theme_stylebox_override("normal", _button_style(Color("#334155")))
	_reset_button.add_theme_stylebox_override("hover", _button_style(Color("#475569")))
	_reset_button.add_theme_stylebox_override("pressed", _button_style(Color("#1E293B")))
	var focus := _button_style(Color.TRANSPARENT)
	focus.draw_center = false
	focus.border_color = Color.WHITE
	focus.set_border_width_all(2)
	_reset_button.add_theme_stylebox_override("focus", focus)
	_reset_button.pressed.connect(_on_reset_pressed)
	add_child(_reset_button)


func _button_style(fill: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = Color("#64748B")
	style.set_border_width_all(1)
	style.set_corner_radius_all(8)
	return style


func _on_reset_pressed() -> void:
	reset_requested.emit()
