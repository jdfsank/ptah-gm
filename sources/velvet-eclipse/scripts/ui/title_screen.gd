class_name CasinoScreen extends Control

signal action_requested(action: String)

const CONTROLS: String = "A / D 或 ← / → 移动    Space / W 跳跃    J 挥剑    K 飞牌\nShift / L 闪避    E 互动    M 地图    Esc 暂停"
var buttons: Array[Button] = []
var detail: Label
var continue_button: Button

func _ready() -> void:
	var content := build_modal("绯月赌城", "VELVET ECLIPSE", true, 940)
	add_label(content, "斩断赌城诅咒，夺回被庄家囚禁的命运。", 24)
	add_button(content, "开始游戏", "new_run", "StartButton")
	continue_button = add_button(content, "继续游戏", "continue_run", "ContinueButton")
	detail = add_label(content, "正在检查存档…", 20)
	add_label(content, CONTROLS, 22)
	add_label(content, "浏览器：先点击游戏画面取得键盘焦点\n↑ / ↓ 选择 · Enter 确认 · 也可直接点击按钮", 20)

func build_modal(heading: String, subtitle: String, opaque: bool = false, width: float = 860.0) -> VBoxContainer:
	mouse_filter = Control.MOUSE_FILTER_STOP
	var veil := ColorRect.new()
	veil.name = "Veil"
	veil.color = Color(0.028, 0.018, 0.057, 1.0 if opaque else 0.78)
	add_child(veil)
	veil.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	veil.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var center := CenterContainer.new()
	center.name = "Center"
	add_child(center)
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var panel := PanelContainer.new()
	panel.name = "Panel"
	panel.custom_minimum_size.x = width
	center.add_child(panel)
	var content := VBoxContainer.new()
	content.name = "Content"
	panel.add_child(content)
	add_label(content, heading, 48, Color(1.0, 0.82, 0.49))
	if not subtitle.is_empty():
		add_label(content, subtitle, 23, Color(0.79, 0.67, 0.95))
	return content

func add_label(parent: Node, text_value: String, font_size: int = 22, color: Color = Color(0.97, 0.92, 0.84)) -> Label:
	var label := Label.new()
	label.text = text_value
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(label)
	return label

func add_button(parent: Node, caption: String, action: String, node_name: String) -> Button:
	var button := Button.new()
	button.name = node_name
	button.text = caption
	button.custom_minimum_size = Vector2(340, 54)
	button.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	button.pressed.connect(func(): action_requested.emit(action))
	parent.add_child(button)
	buttons.append(button)
	return button

func set_active(active: bool) -> void:
	visible = active
	for button in buttons:
		button.focus_mode = Control.FOCUS_ALL if active and not button.disabled else Control.FOCUS_NONE
	if active:
		focus_first.call_deferred()

func focus_first() -> void:
	if not is_visible_in_tree():
		return
	for button in buttons:
		if not button.disabled:
			button.grab_focus()
			return

func refresh(snapshot: Dictionary) -> void:
	if continue_button == null:
		return
	continue_button.disabled = not snapshot.get("can_continue", false)
	continue_button.focus_mode = Control.FOCUS_ALL if visible and not continue_button.disabled else Control.FOCUS_NONE
	detail.text = snapshot.get("continue_notice", "")
	if snapshot.get("save_status", "") == "failed":
		detail.text = snapshot.get("message", detail.text)
