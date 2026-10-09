extends Camera2D

## Object fixed-view: this camera remains at the scene's fixed center.
const OBJECT_ID := "fixed-view"
const LOGICAL_SIZE := Vector2i(960, 540)


func _ready() -> void:
	enabled = true
	position_smoothing_enabled = false
	var window := get_window()
	window.content_scale_size = LOGICAL_SIZE
	window.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	window.content_scale_aspect = Window.CONTENT_SCALE_ASPECT_KEEP
