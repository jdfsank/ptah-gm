extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/main.tscn")
	runtime = runner.scene().get_node("GameWorld")
	runtime.save_repository = SaveRepository.new("user://m03_session_fixture.json")
	DirAccess.remove_absolute(runtime.save_repository.path)
	await runner.simulate_frames(8, 17)

func after_test() -> void:
	DirAccess.remove_absolute("user://m03_session_fixture.json")

func _key(keycode: Key, pressed: bool) -> void:
	var event := InputEventKey.new()
	event.keycode = keycode
	event.physical_keycode = 0
	event.pressed = pressed
	Input.parse_input_event(event)

func _start() -> void:
	_key(KEY_ENTER, true)
	_key(KEY_ENTER, false)
	await runner.simulate_frames(12, 17)

func test_logical_enter_arrows_escape_activate_real_controls_once() -> void:
	assert_str(runtime.session.mode).is_equal("title")
	await _start()
	assert_str(runtime.session.mode).is_equal("playing")
	var x: float = runtime.get_player_snapshot().position.x
	_key(KEY_RIGHT, true)
	await runner.simulate_frames(10, 17)
	_key(KEY_RIGHT, false)
	await runner.simulate_frames(8, 17)
	assert_float(runtime.get_player_snapshot().position.x).is_greater(x + 20.0)
	_key(KEY_ESCAPE, true)
	_key(KEY_ESCAPE, false)
	await runner.simulate_frames(5, 17)
	assert_str(runtime.session.mode).is_equal("paused")
	# Actual GUI arrow focus then Enter activates the Map button.
	_key(KEY_DOWN, true)
	_key(KEY_DOWN, false)
	await runner.simulate_frames(2, 17)
	assert_str(get_viewport().gui_get_focus_owner().name).is_equal("MapButton")
	_key(KEY_ENTER, true)
	_key(KEY_ENTER, false)
	await runner.simulate_frames(5, 17)
	assert_str(runtime.session.mode).is_equal("map")
	_key(KEY_ESCAPE, true)
	_key(KEY_ESCAPE, false)
	await runner.simulate_frames(5, 17)
	assert_str(runtime.session.mode).is_equal("playing")

func test_pause_and_map_freeze_gameplay_and_stale_attack_does_not_replay() -> void:
	await _start()
	runtime.request_session_action("pause")
	await runner.simulate_frames(4, 17)
	var before: Dictionary = runtime.get_run_snapshot()
	runtime.simulate_action("sword", true)
	runtime.simulate_action("card", true)
	await runner.simulate_frames(20, 17)
	var after: Dictionary = runtime.get_run_snapshot()
	assert_vector(after.player.position).is_equal(before.player.position)
	assert_int(after.player.frame).is_equal(before.player.frame)
	assert_float(after.player.frame_progress).is_equal(before.player.frame_progress)
	assert_array(after.enemies).is_equal(before.enemies)
	assert_array(after.projectiles).is_equal(before.projectiles)
	assert_array(after.effects).is_equal(before.effects)
	runtime.request_session_action("resume")
	await runner.simulate_frames(4, 17)
	assert_str(runtime.get_player_snapshot().attack_state).is_equal("idle")
	assert_int(runtime.get_player_snapshot().attack_serial).is_equal(before.player.attack_serial)
	runtime.simulate_action("sword", false)
	runtime.simulate_action("card", false)
	runtime.request_session_action("map")
	await runner.simulate_frames(4, 17)
	before = runtime.get_run_snapshot()
	await runner.simulate_frames(15, 17)
	after = runtime.get_run_snapshot()
	assert_vector(after.player.position).is_equal(before.player.position)
	assert_array(after.enemies).is_equal(before.enemies)

func test_title_continue_is_validated_and_new_game_does_not_overwrite_save() -> void:
	assert_bool(runner.scene().screens.title.continue_button.disabled).is_true()
	var payload: Dictionary = runtime.checkpoint.payload.duplicate(true)
	assert_bool(runtime.save_repository.write_save(payload, runtime.rooms, runtime.resources)).is_true()
	await _start()
	runtime.request_session_action("title")
	await runner.simulate_frames(5, 17)
	assert_bool(runner.scene().screens.title.continue_button.disabled).is_false()
	_key(KEY_DOWN, true)
	_key(KEY_DOWN, false)
	await runner.simulate_frames(2, 17)
	assert_str(get_viewport().gui_get_focus_owner().name).is_equal("ContinueButton")
	_key(KEY_ENTER, true)
	_key(KEY_ENTER, false)
	await runner.simulate_frames(12, 17)
	assert_str(runtime.session.mode).is_equal("playing")
	assert_dict(runtime.save_repository.read_save(runtime.rooms, runtime.resources)).is_equal(payload)

func test_death_retry_and_ending_restart_use_normal_session_requests() -> void:
	await _start()
	# Damage fixture tests the modal route; no UI assigns health or ending state.
	runtime.request_spawn("hitbox", runtime.session.room_id, {"position": runtime.get_player_snapshot().position + Vector2(0, -48), "owner_id": "grand_lobby:skeletal_dealer", "team": "enemy", "attack_serial": 801, "damage": 100, "size": Vector2(120, 120), "follows_owner": false})
	await runner.simulate_frames(8, 17)
	assert_str(runtime.session.mode).is_equal("dead")
	assert_bool(runner.scene().screens.dead.visible).is_true()
	_key(KEY_ENTER, true)
	_key(KEY_ENTER, false)
	await runner.simulate_frames(12, 17)
	assert_str(runtime.session.mode).is_equal("playing")
	assert_int(runtime.get_player_snapshot().health).is_equal(100)
	# Presentation-only ending fixture. Legitimate boss victory is covered by BossSystem tests.
	runtime.session.mode = "ending"
	runtime.clear_gameplay_input()
	await runner.simulate_frames(3, 17)
	_key(KEY_ENTER, true)
	_key(KEY_ENTER, false)
	await runner.simulate_frames(12, 17)
	assert_str(runtime.session.mode).is_equal("playing")
	assert_bool(runtime.progression.boss_defeated).is_false()
	assert_bool(runtime.progression.moonstep).is_false()
