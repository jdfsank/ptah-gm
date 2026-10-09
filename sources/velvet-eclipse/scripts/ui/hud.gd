extends "res://scripts/ui/title_screen.gd"

const HEART = preload("res://assets/generated/compact-prop-pack/casino_small_props/heart_gem.tres")
const MOON = preload("res://assets/generated/compact-prop-pack/casino_small_props/moonstep.tres")
var health: ProgressBar
var energy: ProgressBar
var health_text: Label
var energy_text: Label
var room_name: Label
var objective: Label
var moonstep: HBoxContainer
var notice: Label
var notice_panel: PanelContainer
var boss_panel: PanelContainer
var boss_bar: ProgressBar
var boss_text: Label
var save_label: Label

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var top := HBoxContainer.new()
	top.name = "Top"
	add_child(top)
	top.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE)
	top.offset_left = 24
	top.offset_right = -24
	top.offset_top = 18
	top.offset_bottom = 143
	var resources := PanelContainer.new()
	resources.custom_minimum_size.x = 320
	top.add_child(resources)
	var stack := VBoxContainer.new()
	stack.add_theme_constant_override("separation", 3)
	resources.add_child(stack)
	var row := HBoxContainer.new()
	stack.add_child(row)
	add_icon(row, HEART, 28)
	health_text = add_label(row, "生命", 22)
	health_text.name = "HealthValue"
	health = add_bar(stack, "HealthBar")
	energy_text = add_label(stack, "飞牌能量", 20)
	energy = add_bar(stack, "EnergyBar")
	var fill: StyleBoxFlat = energy.get_theme_stylebox("fill").duplicate()
	fill.bg_color = Color(0.54, 0.36, 0.85)
	energy.add_theme_stylebox_override("fill", fill)
	var info := PanelContainer.new()
	info.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(info)
	var text_stack := VBoxContainer.new()
	text_stack.add_theme_constant_override("separation", 2)
	info.add_child(text_stack)
	room_name = add_label(text_stack, "", 26, Color(1, 0.84, 0.51))
	room_name.name = "RoomName"
	room_name.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT
	objective = add_label(text_stack, "", 22)
	objective.name = "Objective"
	objective.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT
	objective.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	moonstep = HBoxContainer.new()
	text_stack.add_child(moonstep)
	add_icon(moonstep, MOON, 30)
	add_label(moonstep, "月步已觉醒 · 空中再按 Space / W", 20)
	save_label = add_label(text_stack, "", 20)
	save_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT
	var footer := PanelContainer.new()
	add_child(footer)
	footer.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	footer.offset_left = 24
	footer.offset_right = -24
	footer.offset_top = -64
	footer.offset_bottom = -16
	add_label(footer, "A/D ←/→ 移动   Space/W 跳跃   J 剑   K 飞牌   Shift/L 闪避   E 互动   M 地图   Esc 暂停", 20)
	notice_panel = PanelContainer.new()
	add_child(notice_panel)
	notice_panel.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	notice_panel.offset_left = -460
	notice_panel.offset_right = 460
	notice_panel.offset_top = 171
	notice = add_label(notice_panel, "", 22)
	notice.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	boss_panel = PanelContainer.new()
	boss_panel.name = "BossPanel"
	add_child(boss_panel)
	boss_panel.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	boss_panel.offset_left = -385
	boss_panel.offset_right = 385
	boss_panel.offset_top = 250
	boss_panel.offset_bottom = 320
	var boss_style: StyleBoxFlat = boss_panel.get_theme_stylebox("panel").duplicate()
	boss_style.content_margin_top = 8.0
	boss_style.content_margin_bottom = 8.0
	boss_panel.add_theme_stylebox_override("panel", boss_style)
	var boss_stack := VBoxContainer.new()
	boss_stack.add_theme_constant_override("separation", 4)
	boss_panel.add_child(boss_stack)
	boss_text = add_label(boss_stack, "", 22, Color(1, 0.8, 0.55))
	boss_bar = add_bar(boss_stack, "BossHealth")
	top.resized.connect(_layout_status_panels.call_deferred)
	notice_panel.minimum_size_changed.connect(_layout_status_panels.call_deferred)
	ignore_mouse(self)

func add_icon(parent: Node, texture: Texture2D, dimension: int) -> void:
	var icon := TextureRect.new()
	icon.texture = texture
	icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	icon.custom_minimum_size = Vector2(dimension, dimension)
	parent.add_child(icon)

func add_bar(parent: Node, node_name: String) -> ProgressBar:
	var bar := ProgressBar.new()
	bar.name = node_name
	bar.custom_minimum_size = Vector2(0, 12)
	bar.show_percentage = false
	parent.add_child(bar)
	return bar

func ignore_mouse(node: Node) -> void:
	if node is Control:
		node.mouse_filter = Control.MOUSE_FILTER_IGNORE
	for child in node.get_children():
		ignore_mouse(child)

func refresh(snapshot: Dictionary) -> void:
	var player: Dictionary = snapshot.get("player", {})
	health.max_value = player.get("max_health", 100)
	health.value = player.get("health", 0)
	health_text.text = "生命  %d / %d" % [health.value, health.max_value]
	energy.max_value = player.get("max_energy", 100)
	energy.value = player.get("energy", 0)
	energy_text.text = "飞牌能量  %d / %d" % [energy.value, energy.max_value]
	room_name.text = snapshot.get("room_name", "")
	objective.text = "目标：" + snapshot.get("objective", "")
	moonstep.visible = snapshot.get("moonstep", false)
	var status: String = snapshot.get("save_status", "none")
	var statuses: Dictionary = {"none": "尚未在神龛存档", "saved": "已存入本浏览器" if OS.has_feature("web") else "进度已保存", "failed": "保存失败 · 本次仍可重试", "pending": "正在保存…", "unavailable": "浏览器存储不可用"}
	save_label.text = statuses.get(status, "")
	save_label.add_theme_color_override("font_color", Color(1, 0.55, 0.55) if status in ["failed", "unavailable"] else Color(0.77, 0.72, 0.85))
	notice.text = snapshot.get("notice", "")
	notice_panel.visible = not notice.text.is_empty()
	boss_panel.visible = false
	for boss in snapshot.get("bosses", []):
		if not boss.get("dead", false) and boss.get("arena_active", false):
			boss_panel.visible = true
			boss_bar.max_value = boss.max_health
			boss_bar.value = boss.health
			boss_text.text = "皇家庄家 · 第%d阶段   %d / %d" % [boss.phase, boss.health, boss.max_health]
			break
	_layout_status_panels.call_deferred()

func _layout_status_panels() -> void:
	# Container heights can grow with Moonstep/objective wrapping. Keep the status
	# panels below that real height and clear of the grounded melee lane.
	var next_y: float = $Top.get_rect().end.y + 10.0
	notice_panel.offset_top = next_y
	notice_panel.offset_bottom = next_y + notice_panel.get_combined_minimum_size().y
	if notice_panel.visible:
		next_y = notice_panel.offset_bottom + 8.0
	boss_panel.offset_top = next_y
	boss_panel.offset_bottom = next_y + boss_panel.get_combined_minimum_size().y
