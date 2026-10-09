extends "res://scripts/ui/title_screen.gd"

func _ready() -> void:
	var content := build_modal("你已倒下", "命运尚未终结 · 返回检查点再战")
	detail = add_label(content, "", 24)
	add_button(content, "返回检查点", "retry", "RetryButton")
	add_button(content, "返回标题", "title", "TitleButton")
	add_label(content, "重试恢复生命，重新迎战。", 22)

func refresh(snapshot: Dictionary) -> void:
	var checkpoint: Dictionary = snapshot.get("checkpoint", {})
	detail.text = "检查点：静谧存档室 · 神龛" if checkpoint.get("id", "start") == "quiet_shrine" else "检查点：大厅 · 起点"
