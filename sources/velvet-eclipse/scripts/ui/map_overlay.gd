extends "res://scripts/ui/title_screen.gd"

const ROOM_NAMES: Dictionary = {"grand_lobby": "大厅", "card_banquet_gallery": "卡牌宴会长廊", "roulette_clocktower": "轮盘钟楼", "quiet_save_room": "静谧存档室", "house_throne": "庄家王座"}
const POSITIONS: Dictionary = {"grand_lobby": Vector2(40, 165), "card_banquet_gallery": Vector2(340, 165), "roulette_clocktower": Vector2(640, 165), "quiet_save_room": Vector2(40, 35), "house_throne": Vector2(340, 35)}
const CONNECTIONS: Array = [["grand_lobby", "card_banquet_gallery"], ["card_banquet_gallery", "roulette_clocktower"], ["grand_lobby", "quiet_save_room"], ["quiet_save_room", "house_throne"]]
var diagram: Control
var room_boxes: Dictionary = {}
var connectors: Array[Dictionary] = []

func _ready() -> void:
	var content := build_modal("已探索地图", "仅显示你亲自到访的房间", false, 980)
	diagram = Control.new()
	diagram.name = "DiscoveredRooms"
	diagram.custom_minimum_size = Vector2(920, 290)
	diagram.mouse_filter = Control.MOUSE_FILTER_IGNORE
	content.add_child(diagram)
	for pair in CONNECTIONS:
		var line := Line2D.new()
		line.width = 3.0
		line.default_color = Color(0.63, 0.47, 0.31)
		line.add_point(POSITIONS[pair[0]] + Vector2(110, 44))
		line.add_point(POSITIONS[pair[1]] + Vector2(110, 44))
		diagram.add_child(line)
		connectors.append({"rooms": pair, "node": line})
	for room_id in ROOM_NAMES:
		var panel := PanelContainer.new()
		panel.name = room_id
		panel.position = POSITIONS[room_id]
		panel.size = Vector2(220, 88)
		diagram.add_child(panel)
		var label := add_label(panel, ROOM_NAMES[room_id], 22)
		label.name = "RoomLabel"
		room_boxes[room_id] = panel
	add_button(content, "返回游戏", "resume", "CloseButton")
	add_label(content, "M / Esc 关闭 · 地图不能传送", 22)

func refresh(snapshot: Dictionary) -> void:
	var visited: Array = snapshot.get("visited_rooms", [])
	for room_id in room_boxes:
		var panel: PanelContainer = room_boxes[room_id]
		panel.visible = room_id in visited
		var current: bool = room_id == snapshot.get("room_id", "")
		var label: Label = panel.get_node("RoomLabel")
		label.text = ROOM_NAMES[room_id] + ("\n当前位置" if current else "")
		label.add_theme_color_override("font_color", Color(1.0, 0.84, 0.45) if current else Color(0.86, 0.80, 0.94))
	for connector in connectors:
		connector.node.visible = connector.rooms[0] in visited and connector.rooms[1] in visited
