extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_main_boots_one_real_world_player_and_ordered_groups() -> void:
	var snapshot: Dictionary = runtime.get_run_snapshot()
	assert_str(snapshot.mode).is_equal("playing")
	assert_str(snapshot.room_id).is_equal("grand_lobby")
	assert_int(snapshot.system_count).is_equal(14)
	assert_int(snapshot.pending_placements).is_zero()
	assert_bool(snapshot.player.body_ready).is_true()
	assert_bool(snapshot.player.grounded).is_true()
	assert_str(snapshot.player.body_type).is_equal("CharacterBody2D")
	assert_array(snapshot.groups).is_equal(["input", "ai", "boss", "combat", "movement", "damage", "interaction", "progression", "save", "effects", "materialize", "animation", "camera", "ui"])
	assert_that(ECS.world).is_same(runtime.world)

func test_snapshots_are_detached_and_actions_use_real_simulation() -> void:
	var snapshot: Dictionary = runtime.get_run_snapshot()
	var initial_x: float = snapshot.player.position.x
	snapshot.player.position = Vector2(999, 999)
	snapshot.groups.clear()
	assert_float(runtime.get_player_snapshot().position.x).is_equal(initial_x)
	assert_array(runtime.get_run_snapshot().groups).is_not_empty()
	assert_bool(runtime.simulate_action("move_right", true)).is_true()
	await runner.simulate_frames(15, 17)
	assert_float(runtime.get_player_snapshot().position.x).is_greater(initial_x)

func test_entity_snapshot_is_read_only_and_unknown_entity_is_empty() -> void:
	var snapshot: Dictionary = runtime.get_entity_snapshot("grand_lobby:skeletal_dealer")
	assert_str(snapshot.enemy_kind).is_equal("melee")
	snapshot.health = 0
	assert_int(runtime.get_entity_snapshot("grand_lobby:skeletal_dealer").health).is_equal(60)
	assert_dict(runtime.get_entity_snapshot("missing_entity")).is_empty()
	var run: Dictionary = runtime.get_run_snapshot()
	run.enemies.clear()
	assert_int(runtime.get_run_snapshot().enemies.size()).is_equal(3)

func test_progression_and_scene_snapshots_are_detached() -> void:
	var run: Dictionary = runtime.get_run_snapshot()
	assert_bool(run.moonstep).is_false()
	assert_str(run.checkpoint.id).is_equal("start")
	assert_str(run.scene_state.background).is_equal("bg_lobby")
	assert_int(run.scene_state.door_count).is_equal(2)
	run.visited_rooms.clear()
	run.scene_state.platforms[1].rect[1] = 620
	assert_array(runtime.get_run_snapshot().visited_rooms).is_equal(["grand_lobby"])
	assert_float(runtime.get_run_snapshot().scene_state.platforms[1].rect[1]).is_equal(430.0)
	assert_array(runtime.get_run_snapshot().interactions).has_size(2)
