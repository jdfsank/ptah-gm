extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	runtime.save_repository = SaveRepository.new("user://m02_save_system_fixture.json")
	DirAccess.remove_absolute(runtime.save_repository.path)
	await runner.simulate_frames(8, 17)

func after_test() -> void:
	DirAccess.remove_absolute("user://m02_save_system_fixture.json")

func test_validated_continue_places_through_movement_and_resets_encounter() -> void:
	# Explicit repository fixture for restoration, not evidence of the normal route.
	var payload: Dictionary = {"version": 1, "checkpoint_id": "quiet_shrine", "room_id": "quiet_save_room", "spawn_id": "shrine", "moonstep": true, "visited_rooms": ["grand_lobby", "card_banquet_gallery", "roulette_clocktower", "quiet_save_room"], "boss_defeated": false, "ending_seen": false}
	assert_bool(runtime.save_repository.write_save(payload, runtime.rooms, runtime.resources)).is_true()
	assert_bool(runtime.can_continue()).is_true()
	assert_bool(runtime.continue_run()).is_true()
	await runner.simulate_frames(10, 17)
	assert_str(runtime.session.room_id).is_equal("quiet_save_room")
	assert_bool(runtime.get_player_snapshot().grounded).is_true()
	assert_vector(runtime.get_player_snapshot().position).is_equal_approx(Vector2(550, 620), Vector2(0.2, 0.2))
	assert_int(runtime.get_player_snapshot().health).is_equal(100)
	assert_bool(runtime.progression.moonstep).is_true()
	assert_array(runtime.get_run_snapshot().enemies).is_empty()
	runtime.simulate_action("move_right", true)
	await runner.simulate_frames(10, 17)
	runtime.simulate_action("move_right", false)
	await runner.simulate_frames(7, 17)
	runtime.simulate_action("interact", true)
	await runner.simulate_frames(5, 17)
	assert_str(runtime.session.save_status).is_equal("saved")
	assert_str(runtime.checkpoint.checkpoint_id).is_equal("quiet_shrine")
	assert_int(runtime.save_repository.read_save(runtime.rooms, runtime.resources).version).is_equal(1)

func test_invalid_continue_is_safe_and_save_failure_is_honest() -> void:
	assert_bool(runtime.can_continue()).is_false()
	runtime.continue_run()
	await runner.simulate_frames(4, 17)
	assert_str(runtime.session.room_id).is_equal("grand_lobby")
	assert_str(runtime.session.save_status).is_equal("failed")
	runtime.save_repository = SaveRepository.new("user://nonexistent_m02_dir/save.json")
	runtime.checkpoint.save_requested = true
	await runner.simulate_frames(3, 17)
	assert_str(runtime.session.save_status).is_equal("failed")
	assert_bool(runtime.checkpoint.valid).is_true()
	assert_int(runtime.checkpoint.payload.version).is_equal(1)

func test_retry_restores_shrine_checkpoint_and_discards_boss_transients() -> void:
	# Validated save fixture isolates death/retry. The full route earns this payload normally.
	var payload: Dictionary = {"version": 1, "checkpoint_id": "quiet_shrine", "room_id": "quiet_save_room", "spawn_id": "shrine", "moonstep": true, "visited_rooms": ["grand_lobby", "card_banquet_gallery", "roulette_clocktower", "quiet_save_room"], "boss_defeated": false, "ending_seen": false}
	assert_bool(runtime.save_repository.write_save(payload, runtime.rooms, runtime.resources)).is_true()
	runtime.continue_run()
	await runner.simulate_frames(10, 17)
	runtime.session.mode = "transition"
	runtime.session.loading = true
	runtime.session.transition = {"room_id": "house_throne", "spawn_id": "from_save", "reason": "unit_fixture", "applied": false}
	runtime.schedule_flush()
	await runner.simulate_frames(12, 17)
	runtime.request_spawn("hitbox", "house_throne", {"position": Vector2(240, 570), "owner_id": "house_throne:royal_dealer", "team": "enemy", "attack_serial": 20, "damage": 100, "size": Vector2(120, 120), "follows_owner": false})
	await runner.simulate_frames(6, 17)
	assert_str(runtime.session.mode).is_equal("dead")
	runtime.retry()
	await runner.simulate_frames(12, 17)
	assert_str(runtime.session.room_id).is_equal("quiet_save_room")
	assert_str(runtime.session.mode).is_equal("playing")
	assert_bool(runtime.get_player_snapshot().grounded).is_true()
	assert_int(runtime.get_player_snapshot().health).is_equal(100)
	assert_bool(runtime.get_run_snapshot().moonstep).is_true()
	assert_array(runtime.get_run_snapshot().bosses).is_empty()
	assert_array(runtime.get_run_snapshot().projectiles).is_empty()
	assert_array(runtime.get_run_snapshot().effects).is_empty()
	assert_array(runtime.world.query.with_all([C_Hitbox]).execute()).is_empty()

var browser_response: Variant

func _browser_fixture(_script: String) -> Variant:
	return browser_response

func test_browser_save_requires_acknowledged_exact_readback() -> void:
	runtime.save_repository = SaveRepository.new("user://unused", _browser_fixture)
	browser_response = JSON.stringify({"ok": true, "value": JSON.stringify(runtime.checkpoint.payload)})
	runtime.checkpoint.save_requested = true
	await runner.simulate_frames(3, 17)
	assert_str(runtime.session.save_status).is_equal("saved")
	assert_str(runtime.session.message).contains("本浏览器")
	browser_response = null
	runtime.checkpoint.save_requested = true
	await runner.simulate_frames(3, 17)
	assert_str(runtime.session.save_status).is_equal("failed")
	assert_str(runtime.session.message).contains("本次可从检查点重试")
	assert_bool(runtime.checkpoint.valid).is_true()
