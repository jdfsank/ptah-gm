extends Node2D

## Object procedural-rendering: drawing only, with no collision or input logic.
## Visual children inherit their entity's transform from scenes/main.tscn.
const OBJECT_ID := "procedural-rendering"

@export_enum("background", "platform", "player", "exit")
var shape_kind: String = "platform"
@export var shape_size: Vector2 = Vector2.ZERO
@export var fill_color: Color = Color.WHITE
@export var accent_color: Color = Color.WHITE


func _draw() -> void:
	match shape_kind:
		"background":
			_draw_background()
		"platform":
			_draw_platform()
		"player":
			_draw_player()
		"exit":
			_draw_exit()


func _draw_background() -> void:
	draw_rect(Rect2(Vector2.ZERO, shape_size), fill_color)
	var grid_color := Color(0.35, 0.5, 0.65, 0.07)
	for x in range(40, 961, 40):
		draw_line(Vector2(x, 210), Vector2(x, 540), grid_color)
	for y in range(210, 541, 40):
		draw_line(Vector2(0, y), Vector2(960, y), grid_color)
	draw_circle(Vector2(795, 240), 44.0, Color(0.12, 0.2, 0.29, 0.5))
	draw_circle(Vector2(795, 240), 31.0, fill_color)


func _draw_platform() -> void:
	draw_rect(Rect2(Vector2.ZERO, shape_size), fill_color)
	draw_rect(Rect2(Vector2.ZERO, Vector2(shape_size.x, 4.0)), accent_color)
	draw_rect(Rect2(Vector2.ZERO, shape_size), accent_color.darkened(0.5), false, 1.0)
	var bolt_color := accent_color.darkened(0.4)
	draw_circle(Vector2(12.0, 14.0), 2.0, bolt_color)
	draw_circle(Vector2(shape_size.x - 12.0, 14.0), 2.0, bolt_color)


func _draw_player() -> void:
	draw_rect(Rect2(Vector2.ZERO, shape_size), fill_color)
	draw_rect(Rect2(Vector2.ZERO, shape_size), accent_color, false, 1.0)
	draw_rect(Rect2(4.0, 8.0, shape_size.x - 8.0, 6.0), Color(0.13, 0.19, 0.25))
	draw_rect(Rect2(4.0, 25.0, 5.0, 7.0), fill_color.darkened(0.25))
	draw_rect(Rect2(shape_size.x - 9.0, 25.0, 5.0, 7.0), fill_color.darkened(0.25))


func _draw_exit() -> void:
	draw_rect(Rect2(Vector2.ZERO, shape_size), fill_color)
	draw_rect(Rect2(Vector2.ZERO, shape_size), accent_color, false, 2.0)
	draw_rect(Rect2(6.0, 7.0, shape_size.x - 12.0, shape_size.y - 7.0), fill_color.darkened(0.3))
	draw_circle(Vector2(shape_size.x - 11.0, shape_size.y * 0.55), 2.5, accent_color)
