class_name CollectLoopGame
extends Node2D

signal game_state_changed(new_state: String)

const RULES_PATH := "res://config/rules.json"
const PICKUP_RADIUS := 23.0
const START_POSITION := Vector2(60.0, 180.0)
const WORLD_RECT := Rect2(Vector2.ZERO, Vector2(640.0, 360.0))

var rules: Dictionary = {}
var game_state := "uninitialized"
var remaining_time := 0.0
var collected_count := 0
var pickup_positions: Array[Vector2] = []
var collected: Array[bool] = []
var player: CollectLoopPlayer

func _ready() -> void:
	if not _load_rules():
		return
	if not bool(rules["initialized"]):
		queue_redraw()
		return
	player = CollectLoopPlayer.new()
	player.name = "Player"
	player.add_to_group("player")
	player.move_speed = float(rules["player_speed"])
	player.position = START_POSITION
	add_child(player)
	_start_round()

func _process(_delta: float) -> void:
	if game_state in ["won", "lost"] and Input.is_action_just_pressed("retry"):
		_start_round()

func _physics_process(delta: float) -> void:
	if game_state != "playing":
		return
	remaining_time = maxf(0.0, remaining_time - delta)
	if remaining_time <= 0.0:
		_finish_round("lost")
		return
	for index in pickup_positions.size():
		if collected[index]:
			continue
		if player.position.distance_to(pickup_positions[index]) <= PICKUP_RADIUS:
			collected[index] = true
			collected_count += 1
			if collected_count >= int(rules["target_count"]):
				_finish_round("won")
			break
	queue_redraw()

func _load_rules() -> bool:
	var file := FileAccess.open(RULES_PATH, FileAccess.READ)
	if file == null:
		push_error("Cannot read %s" % RULES_PATH)
		return false
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		push_error("Rules must contain a JSON object")
		return false
	rules = parsed
	for key in ["initialized", "target_count", "time_limit", "player_speed"]:
		if not rules.has(key):
			push_error("Rules are missing %s" % key)
			return false
	if typeof(rules["initialized"]) != TYPE_BOOL:
		push_error("initialized must be a boolean")
		return false
	if typeof(rules["target_count"]) not in [TYPE_INT, TYPE_FLOAT] or not is_equal_approx(float(rules["target_count"]), roundf(float(rules["target_count"]))) or int(rules["target_count"]) < 1 or int(rules["target_count"]) > 8:
		push_error("target_count must be an integer from 1 to 8")
		return false
	if typeof(rules["time_limit"]) not in [TYPE_INT, TYPE_FLOAT] or float(rules["time_limit"]) < 10.0 or float(rules["time_limit"]) > 300.0:
		push_error("time_limit must be between 10 and 300 seconds")
		return false
	if typeof(rules["player_speed"]) not in [TYPE_INT, TYPE_FLOAT] or float(rules["player_speed"]) < 60.0 or float(rules["player_speed"]) > 400.0:
		push_error("player_speed must be between 60 and 400")
		return false
	return true

func _start_round() -> void:
	collected_count = 0
	remaining_time = float(rules["time_limit"])
	collected.clear()
	pickup_positions.clear()
	var target_count := int(rules["target_count"])
	for index in target_count:
		var x_position := 320.0 if target_count == 1 else 100.0 + 440.0 * float(index) / float(target_count - 1)
		pickup_positions.append(Vector2(x_position, 180.0))
		collected.append(false)
	player.position = START_POSITION
	player.velocity = Vector2.ZERO
	game_state = "playing"
	game_state_changed.emit(game_state)
	queue_redraw()

func _finish_round(result: String) -> void:
	if game_state != "playing":
		return
	game_state = result
	player.velocity = Vector2.ZERO
	game_state_changed.emit(game_state)
	queue_redraw()

func _draw() -> void:
	draw_rect(WORLD_RECT, Color("#101c2c"))
	for x_position in range(20, 640, 40):
		draw_line(Vector2(x_position, 0), Vector2(x_position, 360), Color("#17283a"), 1.0)
	for y_position in range(20, 360, 40):
		draw_line(Vector2(0, y_position), Vector2(640, y_position), Color("#17283a"), 1.0)
	var font := ThemeDB.fallback_font
	if game_state == "uninitialized":
		font.draw_string(get_canvas_item(), Vector2(28, 172), "MVP TEMPLATE · NOT INITIALIZED", HORIZONTAL_ALIGNMENT_LEFT, -1, 22, Color("#f2c66d"))
		font.draw_string(get_canvas_item(), Vector2(28, 205), "Initialize through the approved rules packet to play", HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color("#d1d9e4"))
		return
	for index in pickup_positions.size():
		if not collected[index]:
			draw_circle(pickup_positions[index], 10.0, Color("#f2c66d"))
			draw_circle(pickup_positions[index], 15.0, Color(0.95, 0.78, 0.35, 0.28))
	if player != null:
		draw_circle(player.position, 13.0, Color("#57d6c5"))
		draw_arc(player.position, 16.0, 0.0, TAU, 32, Color("#d8fff8"), 2.0)
	font.draw_string(get_canvas_item(), Vector2(22, 30), "COLLECT  %d / %d" % [collected_count, int(rules["target_count"])], HORIZONTAL_ALIGNMENT_LEFT, -1, 16, Color("#eef4fb"))
	font.draw_string(get_canvas_item(), Vector2(490, 30), "TIME  %04.1f" % remaining_time, HORIZONTAL_ALIGNMENT_LEFT, -1, 16, Color("#eef4fb"))
	font.draw_string(get_canvas_item(), Vector2(22, 345), "MOVE: WASD / ARROWS", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color("#9fb1c5"))
	if game_state in ["won", "lost"]:
		var headline := "ALL COLLECTED!" if game_state == "won" else "TIME UP"
		font.draw_string(get_canvas_item(), Vector2(205, 165), headline, HORIZONTAL_ALIGNMENT_CENTER, 230, 25, Color("#f2c66d"))
		font.draw_string(get_canvas_item(), Vector2(220, 195), "Press R to retry", HORIZONTAL_ALIGNMENT_CENTER, 200, 14, Color("#eef4fb"))
