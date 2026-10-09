extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_three_enemies_spawn_safe_with_distinct_real_presentations() -> void:
	assert_int(runtime.get_run_snapshot().enemies.size()).is_equal(3)
	for enemy in runtime.get_run_snapshot().enemies:
		assert_str(enemy.ai_state).is_equal("spawning")
		assert_int(enemy.health).is_equal(60)
	assert_array(runtime.get_run_snapshot().projectiles).is_empty()
	var melee: Entity = runtime.world.entity_id_registry["grand_lobby:skeletal_dealer"]
	var ranged: Entity = runtime.world.entity_id_registry["grand_lobby:spectral_dealer"]
	var flying: Entity = runtime.world.entity_id_registry["grand_lobby:flying_card"]
	assert_that(melee.get_component(C_Visual).node).is_instanceof(AnimatedSprite2D)
	assert_float(melee.get_component(C_Visual).node.scale.x).is_equal(1.0)
	assert_that(ranged.get_component(C_Body).root.get_node("SpectralCard")).is_instanceof(Sprite2D)
	assert_that(flying.get_component(C_Visual).node).is_instanceof(Sprite2D)
	assert_that(flying.get_component(C_Visual).node.texture).is_instanceof(AtlasTexture)
	assert_float(flying.get_component(C_Motion).gravity).is_zero()

func test_melee_approaches_telegraphs_before_damage_and_disabled_ai_stays_idle() -> void:
	# Isolated proximity fixture validates AI timing without claiming traversal.
	runtime.request_placement("player", Vector2(700, 620))
	await runner.simulate_frames(4, 17)
	assert_int(runtime.get_player_snapshot().health).is_equal(100)
	var melee: Entity = runtime.world.entity_id_registry["grand_lobby:skeletal_dealer"]
	var original_x: float = melee.get_component(C_Transform).position.x
	await runner.simulate_frames(68, 17)
	assert_float(melee.get_component(C_Transform).position.x).is_less(original_x)
	var states: Dictionary = {}
	for frame in 60:
		states[melee.get_component(C_EnemyAI).state] = true
		await runner.simulate_frames(1, 17)
	assert_bool(states.has("telegraph")).is_true()
	assert_bool(states.has("recover")).is_true()
	assert_int(runtime.get_player_snapshot().health).is_less(100)
	melee.enabled = false
	var ai: C_EnemyAI = melee.get_component(C_EnemyAI)
	var remaining: float = ai.time_left
	await runner.simulate_frames(6, 17)
	assert_float(ai.time_left).is_equal(remaining)

func test_ranged_retreats_then_telegraphs_cast_and_flying_lunges() -> void:
	# Isolated placements keep each AI experiment separate from route evidence.
	runtime.world.entity_id_registry["grand_lobby:skeletal_dealer"].enabled = false
	runtime.request_placement("player", Vector2(1350, 620))
	await runner.simulate_frames(80, 17)
	var ranged: Entity = runtime.world.entity_id_registry["grand_lobby:spectral_dealer"]
	assert_float(ranged.get_component(C_Transform).position.x).is_greater(1510.0)
	var states: Dictionary = {}
	var shots_seen: bool = false
	for frame in 130:
		states[ranged.get_component(C_EnemyAI).state] = true
		shots_seen = shots_seen or not runtime.get_run_snapshot().projectiles.is_empty()
		await runner.simulate_frames(1, 17)
	assert_bool(states.has("telegraph")).is_true()
	assert_bool(shots_seen).is_true()
	ranged.enabled = false
	runtime.request_placement("player", Vector2(1900, 620))
	await runner.simulate_frames(4, 17)
	var flying: Entity = runtime.world.entity_id_registry["grand_lobby:flying_card"]
	states.clear()
	for frame in 100:
		states[flying.get_component(C_EnemyAI).state] = true
		await runner.simulate_frames(1, 17)
	assert_bool(states.has("telegraph")).is_true()
	assert_bool(states.has("lunge")).is_true()
