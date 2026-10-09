extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_materializes_real_body_frames_and_joined_atlas_once() -> void:
	var body: C_Body = runtime.player.get_component(C_Body)
	var visual: C_Visual = runtime.player.get_component(C_Visual)
	assert_that(body.root).is_instanceof(CharacterBody2D)
	assert_that(body.shape.shape).is_instanceof(RectangleShape2D)
	assert_that(visual.node).is_instanceof(AnimatedSprite2D)
	assert_that(visual.node.sprite_frames).is_instanceof(SpriteFrames)
	assert_float(visual.node.scale.x).is_equal_approx(0.49, 0.001)
	assert_float(visual.node.offset.y).is_equal(-105.0)
	var floor_entity: Entity = runtime.world.entity_id_registry["grand_lobby:floor"]
	var floor_body: C_Body = floor_entity.get_component(C_Body)
	var strip: Node2D = floor_entity.get_component(C_Visual).node
	assert_that(floor_body.root).is_instanceof(StaticBody2D)
	assert_int(strip.get_child_count()).is_equal(15)
	assert_that(strip.get_child(0).texture).is_instanceof(AtlasTexture)
	assert_float(strip.get_child(0).position.y).is_equal(-6.0)
	var system: MaterializationSystem = runtime.world.systems_by_group.materialize[0]
	var count: int = system.materialization_count
	var root_id: int = body.root.get_instance_id()
	await runner.simulate_frames(10, 17)
	assert_int(system.materialization_count).is_equal(count)
	assert_int(body.root.get_instance_id()).is_equal(root_id)

func test_cleanup_is_deferred_and_frees_subtree_once() -> void:
	var entity: Entity = runtime.world.entity_id_registry["grand_lobby:chips_0"]
	var root: Node2D = entity.get_component(C_Body).root
	runtime.request_removal(entity.id)
	runtime.request_removal(entity.id)
	assert_bool(is_instance_valid(root)).is_true()
	await runner.simulate_frames(3, 17)
	assert_bool(runtime.world.entity_id_registry.has("grand_lobby:chips_0")).is_false()
	assert_bool(is_instance_valid(root)).is_false()

func test_materialization_waits_for_safe_boundary_then_movement_places() -> void:
	runtime.set_physics_process(false)
	var entity := runtime.factory.create_prop("grand_lobby", {"id": "late_candle", "asset_id": "candle", "position": [500, 500], "size": [24, 56], "z": 0})
	var body: C_Body = entity.get_component(C_Body)
	runtime.world.process(0.0, "materialize")
	assert_bool(body.ready).is_false()
	await runner.simulate_frames(2, 17)
	assert_bool(body.ready).is_true()
	assert_bool(body.root.visible).is_false()
	assert_vector(body.root.position).is_equal(Vector2.ZERO)
	runtime.tick_index += 1
	runtime.world.process(0.0, "movement")
	assert_vector(entity.get_component(C_Transform).position).is_equal(Vector2(500, 500))
	assert_bool(body.root.visible).is_true()
