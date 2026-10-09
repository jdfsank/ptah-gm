extends "res://scripts/ui/title_screen.gd"

func _ready() -> void:
	var content := build_modal("暂停", "赌局暂歇 · 时间已冻结")
	add_button(content, "继续游戏", "resume", "ResumeButton")
	add_button(content, "查看地图", "map", "MapButton")
	add_button(content, "返回标题", "title", "TitleButton")
	add_label(content, CONTROLS, 21)
	add_label(content, "Esc 继续 · 返回标题前请在神龛存档", 20)

func refresh(_snapshot: Dictionary) -> void:
	pass
