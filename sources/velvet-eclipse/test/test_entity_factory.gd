extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_components_are_fresh_and_transform_placement_is_deferred() -> void:
	var first := runtime.factory.create_prop("grand_lobby", {"id": "fresh_a", "asset_id": "chip", "position": [700, 500], "size": [24, 12], "z": 0})
	var second := runtime.factory.create_prop("grand_lobby", {"id": "fresh_b", "asset_id": "chip", "position": [800, 500], "size": [24, 12], "z": 0})
	assert_that(first.get_component(C_Transform)).is_not_same(second.get_component(C_Transform))
	assert_vector(first.get_component(C_Transform).position).is_equal(Vector2.ZERO)
	await runner.simulate_frames(4, 17)
	assert_vector(first.get_component(C_Transform).position).is_equal(Vector2(700, 500))
	assert_vector(second.get_component(C_Transform).position).is_equal(Vector2(800, 500))

func test_player_identity_shape_and_persistent_membership() -> void:
	assert_str(runtime.player.name).is_equal("Player")
	assert_str(runtime.player.id).is_equal("player")
	assert_bool(runtime.player.get_component(C_RoomMember).persistent).is_true()
	assert_vector(runtime.player.get_component(C_Body).size).is_equal(Vector2(40, 96))
	assert_vector(runtime.player.get_component(C_Body).offset).is_equal(Vector2(0, -48))

func test_tall_room_background_is_one_aspect_preserving_cover_plate() -> void:
	runtime.session.mode = "transition"
	runtime.session.loading = true
	runtime.session.transition = {"room_id": "roulette_clocktower", "spawn_id": "start", "reason": "unit_fixture", "applied": false}
	runtime.schedule_flush()
	await runner.simulate_frames(10, 17)
	var count: int = 0
	for entity in runtime.world.query.with_all([C_Visual, C_Transform]).execute():
		var visual: C_Visual = entity.get_component(C_Visual)
		if visual.asset_id != "bg_tower":
			continue
		count += 1
		assert_float(visual.draw_size.x).is_greater_equal(runtime.room_bounds.size.x)
		assert_float(visual.draw_size.y).is_greater_equal(runtime.room_bounds.size.y)
		var texture: Texture2D = runtime.resources.resolve("bg_tower")
		assert_float(visual.draw_size.x / visual.draw_size.y).is_equal_approx(float(texture.get_width()) / texture.get_height(), 0.001)
		assert_vector(entity.get_component(C_Transform).position).is_equal(runtime.room_bounds.get_center())
	assert_int(count).is_equal(1)
