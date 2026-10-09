extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_idle_and_run_advance_distinct_real_frames_without_restarting() -> void:
	var visual: C_Visual = runtime.player.get_component(C_Visual)
	var sprite: AnimatedSprite2D = visual.node
	var frames: Dictionary = {}
	for sample in 12:
		await runner.simulate_frames(2, 17)
		frames[sprite.frame] = true
	assert_int(frames.size()).is_greater(1)
	runtime.simulate_action("move_right", true)
	await runner.simulate_frames(12, 17)
	assert_str(visual.animation).is_equal("run")
	assert_bool(sprite.is_playing()).is_true()
	assert_int(sprite.sprite_frames.get_frame_count("run")).is_greater(1)
	assert_that(sprite.sprite_frames.get_frame_texture("run", 0)).is_not_same(sprite.sprite_frames.get_frame_texture("run", 1))

func test_jump_facing_pause_and_resume_keep_presentation_honest() -> void:
	runtime.simulate_action("move_left", true)
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(4, 17)
	assert_str(runtime.get_player_snapshot().animation).is_equal("jump")
	assert_bool(runtime.get_player_snapshot().flipped).is_true()
	var sprite: AnimatedSprite2D = runtime.player.get_component(C_Visual).node
	runtime.session.mode = "paused"
	await runner.simulate_frames(2, 17)
	var frozen_frame: int = sprite.frame
	var frozen_progress: float = sprite.frame_progress
	await runner.simulate_frames(12, 17)
	assert_int(sprite.frame).is_equal(frozen_frame)
	assert_float(sprite.frame_progress).is_equal(frozen_progress)
	runtime.session.mode = "playing"
	await runner.simulate_frames(3, 17)
	assert_bool(sprite.is_playing()).is_true()

func test_combat_frames_advance_and_hurt_uses_verified_offset() -> void:
	runtime.simulate_action("sword", true)
	var frames: Dictionary = {}
	for sample in 8:
		await runner.simulate_frames(2, 17)
		if runtime.get_player_snapshot().animation == "attack":
			frames[runtime.get_player_snapshot().frame] = true
	assert_int(frames.size()).is_greater(1)
	await runner.simulate_frames(18, 17)
	runtime.simulate_action("card", true)
	await runner.simulate_frames(2, 17)
	assert_float(runtime.get_player_snapshot().visual_offset.y).is_equal(-102.0)
	# Isolated injury presentation fixture; damage tests establish legitimate injury.
	runtime.player.get_component(C_Health).hurt_left = 0.28
	await runner.simulate_frames(2, 17)
	assert_str(runtime.get_player_snapshot().animation).is_equal("hurt")
	assert_float(runtime.get_player_snapshot().visual_offset.y).is_equal(-106.0)
