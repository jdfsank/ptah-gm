extends "res://scripts/ui/title_screen.gd"

func _ready() -> void:
	var content := build_modal("庄家已败", "绯月消散 · 赌城的诅咒已被斩断")
	add_label(content, "你以剑与飞牌打破命运，走出了永夜的赌局。", 24)
	detail = add_label(content, "", 21)
	add_button(content, "重新开始", "new_run", "RestartButton")
	add_button(content, "返回标题", "title", "TitleButton")
	add_label(content, "感谢游玩 · VELVET ECLIPSE", 22)

func refresh(snapshot: Dictionary) -> void:
	detail.text = snapshot.get("message", "")
