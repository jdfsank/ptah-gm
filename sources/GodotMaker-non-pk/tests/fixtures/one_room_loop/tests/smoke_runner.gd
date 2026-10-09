extends SceneTree

# This runner is identical for the baseline and every game-code fault.
# State is observed, never injected. Movement uses the input/physics pipeline;
# buttons are clicked through viewport mouse events, not signal emission.
var cases: Array[Dictionary] = []
var report_path: String = ""
var game: Node2D
var player: CharacterBody2D
var finished: bool = false


func _initialize() -> void:
	var arguments := OS.get_cmdline_user_args()
	for index in range(arguments.size() - 1):
		if arguments[index] == "--report":
			report_path = arguments[index + 1]
	if report_path.is_empty():
		push_error("Required user argument: --report /absolute/path/report.json")
		quit(2)
		return
	call_deferred("_run")


func _run() -> void:
	# Script entry points start with a small headless window; use the project viewport.
	root.size = Vector2i(800, 480)
	create_timer(45.0, true, false, true).timeout.connect(_on_timeout)
	var scene: PackedScene = load("res://one_room_loop.tscn")
	game = scene.instantiate()
	root.add_child(game)
	current_scene = game
	player = game.get_node("World/Player")
	await _frames(3)

	_check("FX-M1.start_menu", "FX-M1",
		_visible("UI/Root/StartMenu") and _text("UI/Root/StartMenu/Title") == "One-Room Loop"
		and _visible("UI/Root/StartMenu/StartButton") and not _visible("UI/Root/HUD"),
		"The visible start menu has a title and Start button; gameplay HUD is hidden.")
	var initial_position := player.position
	await _drive("move_right", 8)
	_check("FX-M1.start_blocks_movement", "FX-M1", player.position.distance_to(initial_position) < 0.1,
		"Movement input cannot move the player before Start.")
	await _click_button("UI/Root/StartMenu/StartButton")
	_check("FX-M1.start_button", "FX-M1", not _visible("UI/Root/StartMenu") and _visible("UI/Root/HUD"),
		"A real GUI click starts gameplay and exposes the HUD.")

	var before_movement := player.position
	await _drive("move_right", 12)
	_check("FX-M2.input_movement", "FX-M2", player.position.x > before_movement.x + 30.0,
		"Right input advances the CharacterBody2D through physics frames.")
	await _drive("move_left", 45)
	_check("FX-M2.wall_collision", "FX-M2", player.position.x >= 49.0 and player.position.x <= 51.0,
		"Sustained left input stops at the real wall collider; x=%.2f." % player.position.x)
	await _move_axis(0, 120.0)

	await _click_button("UI/Root/HUD/PauseButton")
	_check("FX-M4.pause_menu", "FX-M4", paused and _visible("UI/Root/PauseMenu")
		and _text("UI/Root/PauseMenu/Title") == "Paused",
		"The Pause button pauses the SceneTree and shows the pause controls.")
	var paused_position := player.position
	Input.action_press("move_right")
	await _frames(12)
	_check("FX-M4.paused_movement", "FX-M4", player.position.distance_to(paused_position) < 0.1,
		"Held movement cannot change position while paused; drift=%.2f." % player.position.distance_to(paused_position))
	await _key_event(KEY_DOWN)
	var restart_button: Button = game.get_node("UI/Root/PauseMenu/RestartButton")
	_check("FX-M4.pause_navigation", "FX-M4", restart_button.has_focus(),
		"Keyboard focus can move from Resume to Restart while gameplay is paused.")
	await _key_event(KEY_UP)
	var resume_button: Button = game.get_node("UI/Root/PauseMenu/ResumeButton")
	_check("FX-M4.pause_navigation_back", "FX-M4", resume_button.has_focus(),
		"Keyboard focus returns to Resume while gameplay is paused.")
	Input.action_release("move_right")
	await _frames(2)
	var resume_position := player.position
	await _click_button("UI/Root/PauseMenu/ResumeButton")
	await _frames(8)
	_check("FX-M4.resume_no_stuck_input", "FX-M4", not paused and not _visible("UI/Root/PauseMenu")
		and player.position.distance_to(resume_position) < 0.1,
		"Resume closes the menu and a released movement key does not remain stuck.")
	var before_resume_input := player.position
	await _drive("move_right", 5)
	_check("FX-M4.resume_movement", "FX-M4", player.position.x > before_resume_input.x + 10.0,
		"Fresh movement input works after Resume.")

	_check("FX-M3.initial_hud", "FX-M3", _text("UI/Root/HUD/KeyLabel") == "Key: 0/1"
		and _text("UI/Root/HUD/GateLabel") == "Gate: locked",
		"HUD visibly reports an empty inventory and a locked gate at the start.")
	await _drive("move_right", 92)
	_check("FX-M3.locked_gate_collision", "FX-M3", player.position.x <= 458.1
		and int(game.get("key_count")) == 0 and not bool(game.get("won")),
		"Before the key, sustained right input cannot cross the gate; x=%.2f." % player.position.x)
	_check("FX-M3.locked_feedback", "FX-M3", _text("UI/Root/HUD/HintLabel") == "Gate locked. Find the key."
		and not bool(game.get("gate_open")),
		"Entering the locked gate sensor produces visible locked feedback.")

	await _move_axis(0, 240.0)
	await _move_axis(1, 176.0)
	await _frames(3)
	_check("FX-M3.key_trigger", "FX-M3", int(game.get("key_count")) == 1
		and not _visible("World/Key"),
		"Walking into the key Area2D collects exactly one key and hides its sprite.")
	_check("FX-M3.pickup_hud", "FX-M3", _text("UI/Root/HUD/KeyLabel") == "Key: 1/1",
		"The visible key HUD updates to Key: 1/1 after the actual pickup; observed '%s'." % _text("UI/Root/HUD/KeyLabel"))
	await _move_axis(1, 228.0)
	await _move_axis(1, 176.0)
	_check("FX-M3.no_duplicate_pickup", "FX-M3", int(game.get("key_count")) == 1,
		"Leaving and re-entering the collected key area cannot duplicate the key.")

	await _move_axis(0, 548.0)
	_check("FX-M3.key_opens_gate", "FX-M3", bool(game.get("gate_open")) and player.position.x > 510.0,
		"With the key, the gate sensor opens its collider and the player physically crosses it.")
	_check("FX-M3.gate_hud", "FX-M3", _text("UI/Root/HUD/GateLabel") == "Gate: open",
		"The visible gate HUD reports the opened gate.")
	_check("FX-M5.no_early_win", "FX-M5", not bool(game.get("won")) and not _visible("UI/Root/ResultMenu"),
		"Opening the gate alone does not win; the exit must still be reached.")
	await _move_axis(1, 320.0)
	await _drive("move_right", 42)
	_check("FX-M5.exit_result", "FX-M5", bool(game.get("won")) and _visible("UI/Root/ResultMenu")
		and _text("UI/Root/ResultMenu/Title") == "Room complete!"
		and _visible("UI/Root/ResultMenu/RestartButton") and not _visible("UI/Root/HUD"),
		"Walking into the exit Area2D shows the result title and Play again button.")
	var result_position := player.position
	Input.action_press("move_left")
	await _frames(8)
	_check("FX-M5.result_blocks_movement", "FX-M5", player.position.distance_to(result_position) < 0.1,
		"Gameplay movement stops while the result screen is shown.")

	await _click_button("UI/Root/ResultMenu/RestartButton")
	_check("FX-M6.restart_ui", "FX-M6", not _visible("UI/Root/ResultMenu") and _visible("UI/Root/HUD")
		and not paused and not bool(game.get("won")),
		"A real Play again GUI click returns to live gameplay and clears the result.")
	_check("FX-M6.restart_spawn", "FX-M6", player.position.distance_to(Vector2(96.0, 320.0)) < 0.1,
		"Restart restores the original spawn position.")
	await _frames(8)
	_check("FX-M6.restart_input", "FX-M6", not Input.is_action_pressed("move_left")
		and player.position.distance_to(Vector2(96.0, 320.0)) < 0.1,
		"Restart clears a movement action held on the result screen and leaves no stale velocity.")
	Input.action_release("move_left")
	_check("FX-M6.restart_inventory", "FX-M6", int(game.get("key_count")) == 0 and _visible("World/Key")
		and _text("UI/Root/HUD/KeyLabel") == "Key: 0/1" and not bool(game.get("gate_open")),
		"Restart clears the key inventory and HUD, restores the pickup, and closes the gate.")
	await _drive("move_right", 120)
	_check("FX-M6.restart_gate_collision", "FX-M6", player.position.x <= 458.1 and not bool(game.get("won")),
		"A restarted round once again physically blocks the gate before its new key pickup; x=%.2f." % player.position.x)
	var restored_key_available: bool = int(game.get("key_count")) == 0 and _visible("World/Key")
	await _move_axis(0, 240.0)
	await _move_axis(1, 176.0)
	_check("FX-M6.restart_recollect", "FX-M6", restored_key_available and int(game.get("key_count")) == 1
		and not _visible("World/Key") and _text("UI/Root/HUD/KeyLabel") == "Key: 1/1",
		"The restarted round can collect its restored key through the Area2D again.")
	_finish()


func _frames(count: int) -> void:
	for _frame in range(count):
		await physics_frame
		await process_frame


func _drive(action: String, frames: int) -> void:
	Input.action_press(action)
	await _frames(frames)
	Input.action_release(action)
	await _frames(2)


func _move_axis(axis: int, target: float) -> void:
	# Bounded input steering cannot teleport through a broken collider.
	for _step in range(180):
		var distance: float = target - player.position[axis]
		if absf(distance) <= 4.1:
			break
		var action := "move_right" if distance > 0.0 else "move_left"
		if axis == 1:
			action = "move_down" if distance > 0.0 else "move_up"
		Input.action_press(action)
		await _frames(1)
		Input.action_release(action)
	await _frames(2)


func _click_button(path: String) -> void:
	var button: Button = game.get_node(path)
	var center := button.get_global_rect().get_center()
	for pressed_state in [true, false]:
		var event := InputEventMouseButton.new()
		event.position = center
		event.global_position = center
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed_state
		Input.parse_input_event(event)
		await _frames(2)


func _key_event(keycode: Key) -> void:
	for pressed_state in [true, false]:
		var event := InputEventKey.new()
		event.keycode = keycode
		event.pressed = pressed_state
		Input.parse_input_event(event)
		await _frames(2)


func _visible(path: String) -> bool:
	var item: CanvasItem = game.get_node(path)
	return item.is_visible_in_tree()


func _text(path: String) -> String:
	var label: Label = game.get_node(path)
	return label.text


func _check(case_id: String, mechanic: String, passed: bool, detail: String) -> void:
	var status := "PASS" if passed else "FAIL"
	cases.append({"id": case_id, "mechanic": mechanic, "required": true, "status": status, "detail": detail})
	print("[%s] %s: %s" % [status, case_id, detail])


func _on_timeout() -> void:
	if finished:
		return
	_check("runner.timeout", "FX-M1", false, "The in-engine smoke journey exceeded 45 seconds.")
	_finish()


func _finish() -> void:
	if finished:
		return
	finished = true
	for action in ["move_left", "move_right", "move_up", "move_down"]:
		Input.action_release(action)
	paused = false
	var failed: bool = cases.is_empty()
	for item in cases:
		if item["status"] != "PASS":
			failed = true
	var report := {"schema_version": 1, "cases": cases, "result": "FAIL" if failed else "PASS"}
	var file := FileAccess.open(report_path, FileAccess.WRITE)
	if file == null:
		push_error("Cannot write assertion report: %s (error %s)" % [report_path, FileAccess.get_open_error()])
		quit(2)
		return
	file.store_string(JSON.stringify(report, "\t") + "\n")
	file.close()
	print("SMOKE_RESULT=%s REPORT=%s" % [report["result"], report_path])
	quit(1 if failed else 0)
