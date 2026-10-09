extends SceneTree

## Backend-authored probe for the generated test fixture, not a product adapter.
## It observes actual input/physics changes and never approves gameplay quality.
var scene: Node
var player: CharacterBody2D
var checks: Array[String] = []

func _initialize() -> void:
	call_deferred("_run")

func _check(condition: bool, description: String) -> bool:
	if not condition:
		push_error("BACKEND_GAMEPLAY_PROBE_FAIL: " + description)
		quit(2)
		return false
	checks.append(description)
	return true

func _frames(count: int) -> void:
	for index in range(count):
		await physics_frame

func _walk_to(target_x: float) -> void:
	Input.action_press("move_right")
	for index in range(200):
		await physics_frame
		if player.position.x >= target_x or scene.state == 1:
			break
	Input.action_release("move_right")
	await _frames(2)

func _jump_right(frames: int) -> void:
	Input.action_press("move_right")
	Input.action_press("jump")
	await _frames(2)
	Input.action_release("jump")
	await _frames(frames - 2)
	Input.action_release("move_right")
	await _frames(2)

func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	player = scene.get_node("Player")
	await _frames(8)
	var runtime = load("res://studio/runtime.gd").new()
	var expected_speed := float(runtime.object_value("player", "speed"))
	if not _check(is_equal_approx(player.speed, expected_speed), "player speed uses the frozen object field"):
		return
	if not _check(is_equal_approx(player.speed, 300.0) and player.get_node("Visual").fill_color.is_equal_approx(Color.CYAN), "speed 300 and cyan feedback survive the reset repair"):
		return
	var start_x := player.position.x
	Input.action_press("move_right")
	await _frames(10)
	Input.action_release("move_right")
	await _frames(2)
	if not _check(player.position.x > start_x, "right input moves player"):
		return
	await _walk_to(275.0)
	var before_jump_y := player.position.y
	Input.action_press("jump")
	await _frames(3)
	Input.action_release("jump")
	if not _check(player.position.y < before_jump_y, "jump input lifts player"):
		return
	# Restore with an actual reset action before walking the full playable route.
	Input.action_press("reset_level")
	await _frames(2)
	Input.action_release("reset_level")
	await _frames(4)
	if not _check(scene.state == 0 and absf(player.position.x - 100.0) < 1.0, "R reset restores spawn and playing state"):
		return
	await _walk_to(275.0)
	await _jump_right(45)
	if not _check(player.position.x > 370.0 and player.position.y < 350.0 and player.is_on_floor(), "first jump lands on the raised second platform"):
		return
	await _walk_to(555.0)
	await _jump_right(60)
	if not _check(player.position.x > 650.0 and player.is_on_floor(), "second jump lands on third platform"):
		return
	await _walk_to(880.0)
	if not _check(scene.state == 1 and not player.controls_enabled, "actual route reaches exit and locks the won state"):
		return
	Input.action_press("reset_level")
	await _frames(2)
	Input.action_release("reset_level")
	await _frames(4)
	if not _check(scene.state == 0 and absf(player.position.x - 100.0) < 1.0, "R restarts after winning; observed state=" + str(scene.state) + " x=" + str(player.position.x) + " exitOverlap=" + str(scene.exit_area.overlaps_body(player))):
		return
	if not _check(player.controls_enabled and scene.hud.status_label.text == "Falling restarts the level.", "restart restores active controls and the playing HUD"):
		return
	await _walk_to(275.0)
	await _jump_right(45)
	await _walk_to(555.0)
	await _jump_right(60)
	await _walk_to(880.0)
	if not _check(scene.state == 1 and not player.controls_enabled, "the full route can win again after restarting"):
		return
	Input.action_press("reset_level")
	await _frames(2)
	Input.action_release("reset_level")
	await _frames(4)
	player.position.y = 700.0
	await _frames(4)
	if not _check(scene.state == 0 and absf(player.position.x - 100.0) < 1.0 and player.position.y < 600.0, "fall threshold restores spawn"):
		return
	print("BACKEND_GAMEPLAY_PROBE: " + JSON.stringify({"status":"PASS", "checks":checks, "observedSpeed":player.speed, "humanAcceptance":"NOT PERFORMED"}))
	quit(0)
