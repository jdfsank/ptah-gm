extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_camera_starts_inside_bounds_and_does_not_mutate_player() -> void:
	var before: Vector2 = runtime.player.get_component(C_Transform).position
	runtime.world.process(1.0 / 60.0, "camera")
	assert_vector(runtime.player.get_component(C_Transform).position).is_equal(before)
	assert_vector(runtime.camera.position).is_equal(Vector2(640, 360))
	assert_int(runtime.camera.limit_right).is_equal(2400)

func test_camera_follows_and_clamps_both_edges() -> void:
	# Placement is isolated fixture setup via the sole MovementSystem writer.
	runtime.request_placement("player", Vector2(2370, 620))
	await runner.simulate_frames(35, 17)
	assert_float(runtime.camera.position.x).is_between(1720.0, 1760.0)
	assert_float(runtime.camera.position.y).is_equal(360.0)
	runtime.simulate_action("move_right", true)
	await runner.simulate_frames(15, 17)
	assert_float(runtime.get_player_snapshot().position.x).is_less_equal(2380.0)
	assert_float(runtime.camera.position.x).is_less_equal(1760.0)
	runtime.simulate_action("move_right", false)
	runtime.request_placement("player", Vector2(20, 620))
	await runner.simulate_frames(45, 17)
	assert_float(runtime.camera.position.x).is_between(640.0, 642.0)
