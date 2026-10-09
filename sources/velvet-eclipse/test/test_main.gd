extends GdUnitTestSuite

func test_main_scene_starts_at_title_and_normal_enter_starts_lobby() -> void:
	var runner := scene_runner("res://scenes/main.tscn")
	await runner.simulate_frames(8, 17)
	var runtime: GameRuntime = runner.scene().get_node("GameWorld")
	assert_str(runtime.get_run_snapshot().mode).is_equal("title")
	assert_bool(runner.scene().screens.title.visible).is_true()
	runner.simulate_key_press(KEY_ENTER)
	runner.simulate_key_release(KEY_ENTER)
	await runner.simulate_frames(12, 17)
	assert_str(runtime.session.mode).is_equal("playing")
	assert_bool(runtime.get_player_snapshot().grounded).is_true()
	assert_int(runtime.world.query.with_all([C_CameraTarget]).execute().size()).is_equal(1)

func test_screen_anchored_truthful_labels_use_provided_font() -> void:
	var runner := scene_runner("res://scenes/main.tscn")
	await runner.simulate_frames(5, 17)
	runner.simulate_key_press(KEY_ENTER)
	runner.simulate_key_release(KEY_ENTER)
	await runner.simulate_frames(12, 17)
	var hud: Control = runner.scene().screens.hud
	assert_str(hud.room_name.text).contains("大厅")
	assert_str(hud.objective.text).contains("月步")
	assert_that(hud.room_name.get_theme_font("font")).is_instanceof(FontFile)
	assert_that(runner.scene().get_node("Overlay")).is_instanceof(CanvasLayer)
