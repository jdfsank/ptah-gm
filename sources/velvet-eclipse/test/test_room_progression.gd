extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime
var route_log: Array[String] = []

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	runtime.save_repository = SaveRepository.new("user://m02_ordinary_route.json")
	await runner.simulate_frames(8, 17)

func after_test() -> void:
	DirAccess.remove_absolute("user://m02_ordinary_route.json")

func test_complete_catalog_has_safe_spawns_and_bidirectional_connections() -> void:
	assert_bool(runtime.rooms.validate_graph(runtime.resources)).is_true()
	assert_int(runtime.rooms.ROOM_PATHS.size()).is_equal(5)
	for id in runtime.rooms.ROOM_PATHS:
		var room: Dictionary = runtime.rooms.load_room(id, runtime.resources)
		assert_dict(room).is_not_empty()
		for door in room.doors:
			assert_bool(runtime.rooms.load_room(door.target_room, runtime.resources).spawns.has(door.target_spawn)).is_true()

func _tick(frames: int = 1) -> void:
	await runner.simulate_frames(frames, 17)

func _tap(action: String, frames: int = 1) -> void:
	runtime.simulate_action(action, false)
	await _tick()
	runtime.simulate_action(action, true)
	await _tick(frames)
	runtime.simulate_action(action, false)

func _walk(target_x: float, maximum: int = 700) -> bool:
	var previous_x: float = runtime.get_player_snapshot().position.x
	var stalled: int = 0
	for frame in maximum:
		var player: Dictionary = runtime.get_player_snapshot()
		if player.dead:
			return false
		var difference: float = target_x - player.position.x
		if absf(difference) < 12.0:
			runtime.simulate_action("move_right", false)
			runtime.simulate_action("move_left", false)
			await _tick(9)
			return true
		runtime.simulate_action("move_right", difference > 0.0)
		runtime.simulate_action("move_left", difference < 0.0)
		stalled = stalled + 1 if absf(player.position.x - previous_x) < 0.8 else 0
		previous_x = player.position.x
		runtime.simulate_action("jump", stalled > 9 and player.grounded)
		runtime.simulate_action("sword", frame % 30 == 0)
		runtime.simulate_action("card", frame % 80 == 0)
		await _tick()
	return false

func _clear_enemies(maximum: int = 1300) -> bool:
	var previous_x: float = runtime.get_player_snapshot().position.x
	var stalled: int = 0
	for frame in maximum:
		var run: Dictionary = runtime.get_run_snapshot()
		if run.player.dead:
			return false
		var target: Dictionary = {}
		var nearest: float = INF
		for enemy in run.enemies:
			if not enemy.dead and absf(enemy.position.x - run.player.position.x) < nearest:
				target = enemy
				nearest = absf(enemy.position.x - run.player.position.x)
		if target.is_empty():
			runtime.simulate_action("move_right", false)
			runtime.simulate_action("move_left", false)
			await _tick(12)
			return true
		var dx: float = target.position.x - run.player.position.x
		runtime.simulate_action("move_right", dx > 65.0)
		runtime.simulate_action("move_left", dx < -65.0)
		stalled = stalled + 1 if absf(run.player.position.x - previous_x) < 0.8 and absf(dx) > 130.0 else 0
		previous_x = run.player.position.x
		runtime.simulate_action("jump", stalled > 9 and run.player.grounded)
		runtime.simulate_action("sword", frame % 29 == 0 and absf(dx) < 110.0)
		runtime.simulate_action("card", frame % 45 == 0)
		await _tick()
	return false

func _door(x: float, expected: String) -> bool:
	if not await _walk(x):
		return false
	await _tap("interact")
	await _tick(10)
	print("M02 route: ", runtime.session.room_id, " HP=", runtime.get_player_snapshot().health, " pos=", runtime.get_player_snapshot().position)
	route_log.append(runtime.session.room_id)
	return runtime.session.room_id == expected

func _jump_to(start_x: float, end_x: float, expected_y: float, double_jump: bool = false) -> bool:
	if not await _walk(start_x):
		return false
	runtime.simulate_action("move_right", end_x > start_x)
	runtime.simulate_action("move_left", end_x < start_x)
	await _tap("jump")
	for frame in 110:
		if double_jump and frame == 19:
			await _tap("jump")
		var player: Dictionary = runtime.get_player_snapshot()
		if absf(player.position.x - end_x) < 15.0:
			runtime.simulate_action("move_right", false)
			runtime.simulate_action("move_left", false)
		if frame > 12 and player.grounded:
			return absf(player.position.y - expected_y) < 1.0
		await _tick()
	return false

func test_ordinary_route_earns_relic_backtracks_saves_and_defeats_both_phases(_timeout := 300000) -> void:
	# Every position/ability/HP change below comes from normal input and game rules.
	assert_bool(await _clear_enemies()).is_true()
	print("M02 cleared Lobby HP=", runtime.get_player_snapshot().health)
	assert_bool(await _walk(1060)).is_true()
	# A single jump cannot land on the unchanged 190-pixel balcony; E cannot bypass it.
	var gate_geometry: Array = runtime.room_data.platforms[1].rect.duplicate()
	runtime.simulate_action("move_right", true)
	await _tap("jump")
	for frame in 52:
		runtime.simulate_action("interact", frame % 2 == 0)
		await _tick()
	runtime.simulate_action("interact", false)
	runtime.simulate_action("move_right", false)
	assert_str(runtime.session.room_id).is_equal("grand_lobby")
	assert_float(runtime.get_player_snapshot().position.y).is_equal_approx(620.0, 0.2)
	assert_bool(await _door(2290, "card_banquet_gallery")).is_true()
	assert_bool(await _clear_enemies()).is_true()
	print("M02 cleared Gallery HP=", runtime.get_player_snapshot().health)
	assert_bool(await _door(2770, "roulette_clocktower")).is_true()
	assert_bool(await _jump_to(350, 540, 530)).is_true()
	assert_bool(await _jump_to(690, 910, 440)).is_true()
	assert_bool(await _jump_to(1090, 1320, 350)).is_true()
	assert_bool(await _walk(1440)).is_true()
	await _tap("interact")
	await _tick(4)
	assert_bool(runtime.progression.moonstep).is_true()
	assert_dict(runtime.get_entity_snapshot("roulette_clocktower:moonstep")).is_empty()
	print("M02 Moonstep earned through three single-jump ledges; HP=", runtime.get_player_snapshot().health)
	assert_bool(await _jump_to(1640, 1860, 160, true)).is_true()
	assert_bool(await _door(1920, "card_banquet_gallery")).is_true()
	assert_bool(await _clear_enemies()).is_true()
	assert_bool(await _door(110, "grand_lobby")).is_true()
	assert_bool(await _clear_enemies()).is_true()
	assert_array(runtime.room_data.platforms[1].rect).is_equal(gate_geometry)
	assert_bool(await _jump_to(1670, 1450, 430, true)).is_true()
	assert_bool(await _door(1390, "quiet_save_room")).is_true()
	assert_bool(await _walk(640)).is_true()
	await _tap("interact")
	await _tick(5)
	assert_str(runtime.session.save_status).is_equal("saved")
	assert_int(runtime.get_player_snapshot().health).is_equal(100)
	assert_bool(runtime.can_continue()).is_true()
	assert_str(runtime.checkpoint.checkpoint_id).is_equal("quiet_shrine")
	# Native Continue reads the save just earned through this ordinary route.
	runtime.start_new_run()
	await _tick(12)
	assert_bool(runtime.progression.moonstep).is_false()
	runtime.continue_run()
	await _tick(12)
	assert_str(runtime.session.room_id).is_equal("quiet_save_room")
	assert_bool(runtime.progression.moonstep).is_true()
	assert_bool(runtime.get_player_snapshot().grounded).is_true()
	assert_int(runtime.get_player_snapshot().health).is_equal(100)
	assert_bool(await _door(1180, "house_throne")).is_true()
	var won: bool = await _fight_boss()
	assert_bool(won).is_true()
	if not won:
		return
	assert_str(runtime.session.mode).is_equal("ending")
	assert_bool(runtime.progression.boss_defeated).is_true()
	assert_bool(runtime.progression.ending_seen).is_true()
	assert_array(runtime.progression.visited_rooms).has_size(5)
	print("M02 COMPLETE ORDINARY ROUTE: ", route_log, " ending HP=", runtime.get_player_snapshot().health)

func _fight_boss() -> bool:
	var phases: Array[int] = []
	for frame in 9000:
		var run: Dictionary = runtime.get_run_snapshot()
		if run.mode == "ending":
			print("M02 boss fight ticks=", frame, " phases=", phases)
			return phases.has(1) and phases.has(2)
		if run.player.dead:
			print("M02 boss death at frame ", frame, " boss=", run.bosses)
			return false
		if run.bosses.is_empty():
			return false
		var boss: Dictionary = run.bosses[0]
		if not boss.phase in phases:
			phases.append(boss.phase)
		var dx: float = boss.position.x - run.player.position.x
		# Stay in sword reach and time a jump from each visible warning before impact.
		runtime.simulate_action("move_right", dx > 115.0)
		runtime.simulate_action("move_left", dx < 85.0)
		var slam: bool = boss.boss_state == "slam_attack" and boss.boss_time_left > 0.66
		var fan: bool = boss.boss_state == "fan_attack" and boss.boss_time_left > 0.66
		runtime.simulate_action("jump", (slam or fan) and run.player.grounded)
		runtime.simulate_action("sword", frame % 27 == 0)
		runtime.simulate_action("card", frame % 90 == 0 and absf(dx) > 180.0)
		await _tick()
	return false
