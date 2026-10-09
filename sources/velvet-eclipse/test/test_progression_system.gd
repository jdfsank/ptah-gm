extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_modal_actions_freeze_same_tick_and_require_fresh_gameplay_input() -> void:
	runtime.simulate_action("move_right", true)
	runtime.simulate_action("sword", true)
	runtime.simulate_action("pause", true)
	var position: Vector2 = runtime.get_player_snapshot().position
	await runner.simulate_frames(4, 17)
	assert_str(runtime.session.mode).is_equal("paused")
	assert_vector(runtime.get_player_snapshot().position).is_equal(position)
	assert_int(runtime.get_player_snapshot().attack_serial).is_zero()
	runtime.request_session_action("resume")
	await runner.simulate_frames(5, 17)
	assert_str(runtime.session.mode).is_equal("playing")
	assert_vector(runtime.get_player_snapshot().position).is_equal(position)
	assert_int(runtime.get_player_snapshot().attack_serial).is_zero()
	runtime.request_session_action("map")
	await runner.simulate_frames(3, 17)
	assert_str(runtime.session.mode).is_equal("map")
	assert_bool(runtime.request_session_action("debug_win")).is_false()
	runtime.request_session_action("resume")
	await runner.simulate_frames(3, 17)
	runner.simulate_key_press(KEY_ESCAPE)
	await runner.simulate_frames(3, 17)
	assert_str(runtime.session.mode).is_equal("paused")
	runner.simulate_key_release(KEY_ESCAPE)
	await runner.simulate_frames(2, 17)
	runner.simulate_key_press(KEY_ESCAPE)
	await runner.simulate_frames(3, 17)
	assert_str(runtime.session.mode).is_equal("playing")
	runner.simulate_key_release(KEY_ESCAPE)

func test_death_stops_play_retry_uses_initial_checkpoint_and_new_run_is_fresh() -> void:
	# A real damage-path fixture establishes death; it is not a complete-route shortcut.
	var owner: Entity = runtime.world.entity_id_registry["grand_lobby:skeletal_dealer"]
	runtime.request_spawn("hitbox", "grand_lobby", {"position": Vector2(260, 570), "owner_id": owner.id, "team": "enemy", "attack_serial": 99, "size": Vector2(100, 100), "damage": 100, "follows_owner": false})
	await runner.simulate_frames(6, 17)
	assert_str(runtime.session.mode).is_equal("dead")
	assert_bool(runtime.get_player_snapshot().dead).is_true()
	var position: Vector2 = runtime.get_player_snapshot().position
	runtime.simulate_action("move_right", true)
	await runner.simulate_frames(8, 17)
	assert_vector(runtime.get_player_snapshot().position).is_equal(position)
	assert_array(runtime.get_run_snapshot().projectiles).is_empty()
	assert_bool(runtime.retry()).is_true()
	await runner.simulate_frames(10, 17)
	assert_str(runtime.session.mode).is_equal("playing")
	assert_int(runtime.get_player_snapshot().health).is_equal(100)
	assert_bool(runtime.get_player_snapshot().grounded).is_true()
	assert_float(runtime.get_player_snapshot().position.x).is_equal(260.0)
	assert_int(runtime.get_run_snapshot().enemies.size()).is_equal(3)
	assert_bool(runtime.start_new_run()).is_true()
	await runner.simulate_frames(10, 17)
	assert_bool(runtime.get_run_snapshot().moonstep).is_false()
	assert_array(runtime.get_run_snapshot().visited_rooms).is_equal(["grand_lobby"])
