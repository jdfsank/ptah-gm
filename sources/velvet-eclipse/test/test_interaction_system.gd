extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_nearest_grounded_interaction_has_visible_prompt_and_no_remote_activation() -> void:
	# Local interaction fixture tests eligibility, not route completion.
	var near: Entity = runtime.factory.create_interaction("grand_lobby", {"id": "near_fixture", "position": [310, 620], "prompt": "检查", "target_room": "card_banquet_gallery", "target_spawn": "from_lobby"}, "door")
	var far: Entity = runtime.factory.create_interaction("grand_lobby", {"id": "far_fixture", "position": [520, 620], "prompt": "远方", "target_room": "card_banquet_gallery", "target_spawn": "from_lobby"}, "door")
	await runner.simulate_frames(5, 17)
	assert_bool(near.get_component(C_Interaction).selected).is_true()
	assert_bool(far.get_component(C_Interaction).selected).is_false()
	assert_bool(near.get_component(C_Body).root.get_node("InteractionPrompt").visible).is_true()
	near.enabled = false
	runtime.simulate_action("interact", true)
	await runner.simulate_frames(3, 17)
	assert_str(runtime.session.room_id).is_equal("grand_lobby")

func test_airborne_and_wrong_foot_level_cannot_activate_even_inside_radius() -> void:
	var high: Entity = runtime.factory.create_interaction("grand_lobby", {"id": "high_fixture", "position": [260, 542], "prompt": "高门", "target_room": "quiet_save_room", "target_spawn": "from_lobby"}, "door")
	await runner.simulate_frames(5, 17)
	assert_bool(high.get_component(C_Interaction).selected).is_false()
	runtime.simulate_action("jump", true)
	await runner.simulate_frames(10, 17)
	runtime.simulate_action("interact", true)
	await runner.simulate_frames(2, 17)
	assert_str(runtime.session.room_id).is_equal("grand_lobby")
	assert_bool(high.get_component(C_Interaction).selected).is_false()

func test_left_edge_prompt_stays_inside_canvas_safe_area() -> void:
	# Ordinary nearest-interaction selection after a placement fixture at the left door.
	runtime.session.mode = "transition"
	runtime.session.loading = true
	runtime.session.transition = {"room_id": "card_banquet_gallery", "spawn_id": "from_lobby", "reason": "unit_fixture", "applied": false}
	runtime.schedule_flush()
	await runner.simulate_frames(12, 17)
	var checked: bool = false
	for entity in runtime.world.query.with_all([C_Interaction, C_Body]).execute():
		var prompt: Label = entity.get_component(C_Body).root.get_node_or_null("InteractionPrompt")
		if prompt != null and prompt.visible:
			var rect: Rect2 = prompt.get_global_transform_with_canvas() * Rect2(Vector2.ZERO, prompt.size)
			assert_float(rect.position.x).is_greater_equal(19.0)
			assert_float(rect.end.x).is_less_equal(runtime.get_viewport_rect().size.x - 19.0)
			checked = true
	assert_bool(checked).is_true()
