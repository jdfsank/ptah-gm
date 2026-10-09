extends SceneTree

var _failed := false

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var packed_scene := load("res://scenes/main.tscn") as PackedScene
	if packed_scene == null:
		_fail("main scene loads")
		quit(1)
		return
	var game := packed_scene.instantiate() as CollectLoopGame
	root.add_child(game)
	await process_frame
	if game.game_state == "uninitialized":
		_check(game.rules.get("initialized", true) == false, "trusted template keeps initialized gate false")
		_check(game.player == null, "uninitialized template creates no player")
		_check(game.pickup_positions.is_empty(), "uninitialized template creates no collectibles")
		if _failed:
			quit(1)
		else:
			print("COLLECT_LOOP_TEMPLATE_GATE_PASS")
			quit(0)
		return
	_check(game.game_state == "playing", "initialized game enters playing")
	if game.game_state != "playing":
		quit(1)
		return
	var initial_position := game.player.position
	var final_pickup_x := game.pickup_positions[-1].x
	var frame_budget := ceili((final_pickup_x - initial_position.x + 35.0) / game.player.move_speed * 60.0) + 20
	await _hold_key(KEY_RIGHT, frame_budget)
	_check(game.player.position.x > initial_position.x, "arrow input moves player right")
	_check(game.collected_count == int(game.rules["target_count"]), "movement collects every required token")
	_check(game.game_state == "won", "collecting target transitions to won")
	if game.game_state != "won":
		quit(1)
		return
	await _press_key(KEY_R, true)
	_check(game.game_state == "playing", "retry after win restarts the round")
	_check(game.collected_count == 0, "retry restores all tokens")
	_check(game.player.position.distance_to(initial_position) < 0.1, "retry restores player position")
	var before_up := game.player.position
	await _hold_key(KEY_W, 8, true)
	_check(game.player.position.y < before_up.y, "W input moves player upward")
	game.remaining_time = 0.01
	await physics_frame
	_check(game.game_state == "lost", "countdown expiry transitions to lost")
	await _press_key(KEY_R, true)
	_check(game.game_state == "playing", "retry after loss restarts the round")
	_check(game.collected_count == 0, "loss retry restores all tokens")
	_check(is_equal_approx(game.remaining_time, float(game.rules["time_limit"])), "loss retry restores configured timer")
	if _failed:
		quit(1)
	else:
		print("COLLECT_LOOP_SCENETREE_PASS")
		quit(0)

func _hold_key(keycode: Key, frame_count: int, physical: bool = false) -> void:
	var pressed := InputEventKey.new()
	if physical:
		pressed.physical_keycode = keycode
	else:
		pressed.keycode = keycode
	pressed.pressed = true
	Input.parse_input_event(pressed)
	for _frame in frame_count:
		await physics_frame
	var released := InputEventKey.new()
	if physical:
		released.physical_keycode = keycode
	else:
		released.keycode = keycode
	released.pressed = false
	Input.parse_input_event(released)
	await physics_frame

func _press_key(keycode: Key, physical: bool = false) -> void:
	var pressed := InputEventKey.new()
	if physical:
		pressed.physical_keycode = keycode
	else:
		pressed.keycode = keycode
	pressed.pressed = true
	Input.parse_input_event(pressed)
	await process_frame
	var released := InputEventKey.new()
	if physical:
		released.physical_keycode = keycode
	else:
		released.keycode = keycode
	released.pressed = false
	Input.parse_input_event(released)
	await physics_frame

func _check(condition: bool, description: String) -> void:
	if condition:
		print("PASS: " + description)
	else:
		_fail(description)

func _fail(description: String) -> void:
	_failed = true
	push_error("FAIL: " + description)
