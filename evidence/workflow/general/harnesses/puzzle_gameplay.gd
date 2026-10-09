extends SceneTree

## Independent, fixture-specific probe: actual viewport mouse and keyboard input.
var scene: Control
var rules: Node
var board: GridContainer
var checks: Array[String] = []
const START := [true, false, false, false, true, false, false, false, true]

func _initialize() -> void:
	call_deferred("_run")

func _check(condition: bool, description: String) -> bool:
	if not condition:
		push_error("BACKEND_GAMEPLAY_PROBE_FAIL: " + description)
		quit(2)
		return false
	checks.append(description)
	return true

func _frames(count: int = 3) -> void:
	for index in range(count):
		await process_frame

func _click(control: Control) -> void:
	var point := control.get_global_rect().get_center()
	var motion := InputEventMouseMotion.new()
	motion.position = point
	root.push_input(motion)
	var event := InputEventMouseButton.new()
	event.position = point
	event.button_index = MOUSE_BUTTON_LEFT
	event.pressed = true
	root.push_input(event)
	await _frames(2)
	event = event.duplicate()
	event.pressed = false
	root.push_input(event)
	await _frames()

func _reset_key(echo: bool = false) -> void:
	var event := InputEventKey.new()
	event.physical_keycode = KEY_R
	event.keycode = KEY_R
	event.pressed = true
	event.echo = echo
	root.push_input(event)
	await _frames()
	event = event.duplicate()
	event.pressed = false
	event.echo = false
	root.push_input(event)
	await _frames()

func _changed(before: Array, after: Array) -> Array[int]:
	var indices: Array[int] = []
	for index in range(9):
		if before[index] != after[index]:
			indices.append(index)
	return indices

func _run() -> void:
	root.size = Vector2i(960, 540)
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	rules = scene.get_node("Rules")
	board = scene.get_node("PuzzleBoard")
	await _frames(8)
	if not _check(board.get_child_count() == 9 and rules.get_cells() == START and rules.get_move_count() == 0, "initial nine-button diagonal board has zero moves"):
		return
	var runtime = load("res://studio/runtime.gd").new()
	var accent := Color(str(runtime.object_value("puzzle-board", "accent-color")))
	if not _check(board.get_child(0).get_theme_stylebox("normal").bg_color.is_equal_approx(accent), "lit button uses frozen object accent"):
		return
	var selections := [0, 1, 4]
	var expected := [[0, 1, 3], [0, 1, 2, 4], [1, 3, 4, 5, 7]]
	for index in range(selections.size()):
		await _reset_key()
		var before: Array = rules.get_cells()
		await _click(board.get_child(selections[index]))
		if not _check(_changed(before, rules.get_cells()) == expected[index] and rules.get_move_count() == 1, "mouse selection %d toggles only its orthogonal cross and counts once" % selections[index]):
			return
	await _reset_key(true)
	if not _check(rules.get_move_count() == 1, "R echo does not reset the active board"):
		return
	await _click(scene.get_node("HUD/Reset"))
	if not _check(rules.get_cells() == START and rules.get_move_count() == 0, "Reset button restores initial board and move count"):
		return
	for cell in [0, 4, 8]:
		await _click(board.get_child(cell))
	if not _check(rules.is_solved() and not rules.get_cells().has(true) and rules.get_move_count() == 3, "documented mouse solution wins in three moves"):
		return
	if not _check(scene.get_node("HUD/WinMessage").visible and scene.get_node("HUD/WinMessage").text == "All lights out!", "win message renders after solving"):
		return
	await _click(board.get_child(1))
	if not _check(rules.get_move_count() == 3 and rules.is_solved(), "won board ignores further mouse selection"):
		return
	await _reset_key()
	if not _check(not rules.is_solved() and rules.get_cells() == START and rules.get_move_count() == 0 and not board.get_child(0).disabled, "R resets after win and restores enabled input"):
		return
	for cell in [0, 4, 8]:
		await _click(board.get_child(cell))
	await _click(scene.get_node("HUD/Reset"))
	if not _check(not rules.is_solved() and rules.get_cells() == START and rules.get_move_count() == 0 and not scene.get_node("HUD/WinMessage").visible, "Reset button clears a second win and its message"):
		return
	print("BACKEND_GAMEPLAY_PROBE_PASS " + JSON.stringify(checks))
	scene.queue_free()
	await _frames(2)
	quit(0)
