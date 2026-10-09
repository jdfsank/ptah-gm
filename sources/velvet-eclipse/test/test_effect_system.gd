extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_effect_is_materialized_once_fades_then_frees() -> void:
	var id: String = runtime.request_spawn("effect", "grand_lobby", {"position": Vector2(300, 500), "kind": "impact", "duration": 0.3})
	await runner.simulate_frames(4, 17)
	var entity: Entity = runtime.world.entity_id_registry[id]
	var visual: C_Visual = entity.get_component(C_Visual)
	assert_that(visual.node).is_instanceof(Line2D)
	assert_bool(visual.node.get_parent().visible).is_true()
	assert_vector(entity.get_component(C_Transform).position).is_equal(Vector2(300, 500))
	var node_id: int = visual.node.get_instance_id()
	var alpha: float = visual.tint.a
	await runner.simulate_frames(5, 17)
	assert_int(visual.node.get_instance_id()).is_equal(node_id)
	assert_float(visual.tint.a).is_less(alpha)
	await runner.simulate_frames(18, 17)
	assert_dict(runtime.get_entity_snapshot(id)).is_empty()

func test_projectile_lifetime_and_modal_effect_clocks_are_bounded() -> void:
	var id: String = runtime.request_spawn("projectile", "grand_lobby", {"position": Vector2(300, 300), "owner_id": "player", "team": "player", "direction": Vector2.RIGHT, "remaining": 0.2})
	var effect_id: String = runtime.request_spawn("effect", "grand_lobby", {"position": Vector2(300, 400), "kind": "slash", "duration": 0.5})
	await runner.simulate_frames(4, 17)
	runtime.session.mode = "paused"
	var effect: C_Effect = runtime.world.entity_id_registry[effect_id].get_component(C_Effect)
	var remaining: float = effect.remaining
	await runner.simulate_frames(20, 17)
	assert_float(effect.remaining).is_equal(remaining)
	assert_dict(runtime.get_entity_snapshot(id)).is_not_empty()
	runtime.session.mode = "playing"
	await runner.simulate_frames(35, 17)
	assert_dict(runtime.get_entity_snapshot(id)).is_empty()
	assert_dict(runtime.get_entity_snapshot(effect_id)).is_empty()
