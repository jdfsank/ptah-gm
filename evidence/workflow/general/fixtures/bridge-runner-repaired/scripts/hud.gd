extends CanvasLayer

## Object hud: present controls and outcomes without driving level state.
const OBJECT_ID := "hud"
const PLAYING_COLOR := Color(0.65, 0.74, 0.83)
const WON_COLOR := Color(0.45, 1.0, 0.65)

@onready var status_label: Label = $Panel/Status


func show_playing() -> void:
	status_label.text = "Falling restarts the level."
	status_label.add_theme_color_override("font_color", PLAYING_COLOR)


func show_won() -> void:
	status_label.text = "You win! Press R to restart."
	status_label.add_theme_color_override("font_color", WON_COLOR)
