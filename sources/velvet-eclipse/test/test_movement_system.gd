extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_run_accelerates_reverses_and_stops_on_real_floor() -> void:
	var start: Vector2 = runtime.get_player_snapshot().position
	runtime.simulate_action("move_right", true)
	await runner.simulate_frames(12, 17)
	var moving: Dictionary = runtime.get_player_snapshot()
	assert_float(moving.position.x).is_greater(start.x + 20.0)
	assert_float(moving.velocity.x).is_equal(300.0)
	assert_bool(moving.grounded).is_true()
	runtime.simulate_action("move_right", false)
	runtime.simulate_action("move_left", true)
	await runner.simulate_frames(20, 17)
	assert_int(runtime.get_player_snapshot().facing).is_equal(-1)
	assert_float(runtime.get_player_snapshot().velocity.x).is_equal(-300.0)
	runtime.simulate_action("move_left", false)
	await runner.simulate_frames(10, 17)
	assert_float(runtime.get_player_snapshot().velocity.x).is_zero()
	assert_float(runtime.get_player_snapshot().position.y).is_equal_approx(620.0, 0.15)

func test_jump_apex_single_jump_and_land_through_action_queue() -> void:
	var minimum_y: float = 620.0
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(2, 17)
	runtime.simulate_action("jump", false)
	for frame in 50:
		if frame == 10:
			runtime.simulate_action("jump", true)
		if frame == 11:
			runtime.simulate_action("jump", false)
		await runner.simulate_frames(1, 17)
		minimum_y = minf(minimum_y, runtime.get_player_snapshot().position.y)
	assert_float(620.0 - minimum_y).is_between(108.0, 120.0)
	assert_bool(runtime.get_player_snapshot().grounded).is_true()
	assert_int(runtime.get_player_snapshot().jumps_used).is_zero()
	print("R1 measured single-jump rise: ", 620.0 - minimum_y, "; reserved balcony rise: 190")

func test_ceiling_stops_jump_and_player_lands() -> void:
	# Isolated collision fixture; never used to establish normal route completion.
	runtime.factory.create_platform("grand_lobby", {"id": "test_ceiling", "rect": [0, 440, 640, 40]})
	await runner.simulate_frames(4, 17)
	runtime.simulate_action("jump", true)
	var minimum_y: float = 620.0
	for frame in 30:
		await runner.simulate_frames(1, 17)
		minimum_y = minf(minimum_y, runtime.get_player_snapshot().position.y)
	assert_float(minimum_y).is_greater(575.0)
	assert_bool(runtime.get_player_snapshot().grounded).is_true()

func test_buffered_jump_fires_after_landing() -> void:
	await _place(Vector2(260, 460))
	for frame in 40:
		if runtime.get_player_snapshot().position.y > 595.0:
			break
		await runner.simulate_frames(1, 17)
	assert_bool(runtime.get_player_snapshot().grounded).is_false()
	assert_float(runtime.get_player_snapshot().velocity.y).is_greater(0.0)
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(5, 17)
	assert_float(runtime.get_player_snapshot().velocity.y).is_less(0.0)
	assert_bool(runtime.get_player_snapshot().grounded).is_false()

func test_expired_buffer_does_not_jump_on_landing() -> void:
	await _place(Vector2(260, 240))
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(2, 17)
	runtime.simulate_action("jump", false)
	await runner.simulate_frames(65, 17)
	assert_bool(runtime.get_player_snapshot().grounded).is_true()
	assert_float(runtime.get_player_snapshot().buffer_left).is_zero()

func test_coyote_jump_after_edge_and_expiration_negative() -> void:
	await _ledge_fixture()
	await _leave_ledge()
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(1, 17)
	assert_float(runtime.get_player_snapshot().velocity.y).is_less(-400.0)
	runtime.simulate_action("jump", false)
	runtime.simulate_action("move_right", false)
	await _place(Vector2(412, 500))
	await runner.simulate_frames(4, 17)
	await _leave_ledge()
	await runner.simulate_frames(9, 17)
	assert_float(runtime.get_player_snapshot().coyote_left).is_zero()
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(2, 17)
	assert_float(runtime.get_player_snapshot().velocity.y).is_greater(0.0)

func test_upper_balcony_remains_unreachable_before_moonstep() -> void:
	await _place(Vector2(1020, 620))
	await runner.simulate_frames(4, 17)
	runtime.simulate_action("move_right", true)
	runtime.simulate_action("jump", true)
	var minimum_y: float = 620.0
	for frame in 65:
		await runner.simulate_frames(1, 17)
		minimum_y = minf(minimum_y, runtime.get_player_snapshot().position.y)
	assert_float(minimum_y).is_greater(430.0)
	assert_float(runtime.get_player_snapshot().position.y).is_equal_approx(620.0, 0.15)

func _place(position: Vector2) -> void:
	runtime.request_placement("player", position)
	await runner.simulate_frames(4, 17)

func _ledge_fixture() -> void:
	runtime.request_removal("grand_lobby:floor")
	runtime.request_removal("grand_lobby:upper_balcony")
	runtime.factory.create_platform("grand_lobby", {"id": "test_ledge", "rect": [100, 500, 320, 80]})
	await _place(Vector2(412, 500))
	await runner.simulate_frames(4, 17)

func _leave_ledge() -> void:
	runtime.simulate_action("move_right", true)
	for frame in 30:
		await runner.simulate_frames(1, 17)
		if not runtime.get_player_snapshot().grounded:
			return
	fail("Fixture did not leave ledge")

func test_padded_hero_stays_inside_both_room_edges() -> void:
	for entity in runtime.world.query.with_all([C_EnemyAI]).execute():
		entity.enabled = false
	await _place(Vector2(70, 620))
	runtime.simulate_action("move_left", true)
	await runner.simulate_frames(15, 17)
	assert_float(runtime.get_player_snapshot().position.x).is_equal(64.0)
	runtime.simulate_action("move_left", false)
	await _place(Vector2(2330, 620))
	runtime.simulate_action("move_right", true)
	await runner.simulate_frames(15, 17)
	assert_float(runtime.get_player_snapshot().position.x).is_equal(2336.0)

func test_moonstep_allows_one_second_jump_and_rejects_a_third() -> void:
	# Isolated ability-state fixture; the ordinary route separately earns Moonstep.
	runtime.progression.moonstep = true
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(2, 17)
	runtime.simulate_action("jump", false)
	await runner.simulate_frames(18, 17)
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(2, 17)
	assert_int(runtime.get_player_snapshot().jumps_used).is_equal(2)
	assert_float(runtime.get_player_snapshot().velocity.y).is_less(-500.0)
	runtime.simulate_action("jump", false)
	await runner.simulate_frames(6, 17)
	var before: float = runtime.get_player_snapshot().velocity.y
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(2, 17)
	assert_int(runtime.get_player_snapshot().jumps_used).is_equal(2)
	assert_float(runtime.get_player_snapshot().velocity.y).is_greater(before)
	assert_float(runtime.get_player_snapshot().position.y).is_less(430.0)

func test_walking_off_with_moonstep_consumes_only_air_jump_after_coyote_expires() -> void:
	runtime.progression.moonstep = true
	await _ledge_fixture()
	await _leave_ledge()
	await runner.simulate_frames(9, 17)
	assert_float(runtime.get_player_snapshot().coyote_left).is_zero()
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(2, 17)
	assert_int(runtime.get_player_snapshot().jumps_used).is_equal(2)
	runtime.simulate_action("jump", false)
	await runner.simulate_frames(8, 17)
	var before: float = runtime.get_player_snapshot().velocity.y
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(2, 17)
	assert_float(runtime.get_player_snapshot().velocity.y).is_greater(before)
	assert_int(runtime.get_player_snapshot().jumps_used).is_equal(2)
