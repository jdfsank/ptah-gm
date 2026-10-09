extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)
	for entity in runtime.world.query.with_all([C_EnemyAI]).execute():
		entity.enabled = false

func _target(position: Vector2, kind: String = "melee") -> Entity:
	var entity: Entity = runtime.factory.create_enemy("grand_lobby", {"id": "target", "kind": kind, "position": [position.x, position.y], "patrol_radius": 10})
	entity.get_component(C_EnemyAI).time_left = 100.0
	await runner.simulate_frames(4, 17)
	return entity

func test_directional_sword_hits_once_per_swing_and_ignores_disabled_target() -> void:
	var target: Entity = await _target(Vector2(335, 620))
	runtime.simulate_action("sword", true)
	await runner.simulate_frames(20, 17)
	assert_int(target.get_component(C_Health).current).is_equal(35)
	await runner.simulate_frames(12, 17)
	assert_int(target.get_component(C_Health).current).is_equal(35)
	runtime.simulate_action("sword", false)
	runtime.simulate_action("move_left", true)
	await runner.simulate_frames(2, 17)
	runtime.simulate_action("move_left", false)
	runtime.simulate_action("sword", true)
	await runner.simulate_frames(30, 17)
	assert_int(target.get_component(C_Health).current).is_equal(35)
	target.enabled = false
	runtime.simulate_action("sword", false)
	runtime.simulate_action("move_right", true)
	await runner.simulate_frames(2, 17)
	runtime.simulate_action("move_right", false)
	runtime.simulate_action("sword", true)
	await runner.simulate_frames(20, 17)
	assert_int(target.get_component(C_Health).current).is_equal(35)

func test_real_card_spends_energy_hits_target_and_sweeps_fast_projectile() -> void:
	var target: Entity = await _target(Vector2(510, 620))
	runtime.simulate_action("card", true)
	await runner.simulate_frames(35, 17)
	assert_int(target.get_component(C_Health).current).is_equal(40)
	assert_float(runtime.get_player_snapshot().energy).is_less(90.0)
	assert_array(runtime.get_run_snapshot().projectiles).is_empty()
	await runner.simulate_frames(12, 17)
	var shot: String = runtime.request_spawn("projectile", "grand_lobby", {"position": Vector2(300, 570), "owner_id": "player", "team": "player", "direction": Vector2.RIGHT, "speed": 20000.0})
	await runner.simulate_frames(6, 17)
	assert_int(target.get_component(C_Health).current).is_equal(20)
	assert_dict(runtime.get_entity_snapshot(shot)).is_empty()

func test_dodge_and_hurt_invulnerability_expire_and_heal_is_damage_owned() -> void:
	# Materialize the target before starting the short invulnerability window.
	var owner: Entity = await _target(Vector2(340, 620))
	runtime.simulate_action("dodge", true)
	await runner.simulate_frames(1, 17)
	var hit: String = runtime.request_spawn("hitbox", "grand_lobby", {"position": Vector2(400, 570), "owner_id": owner.id, "team": "enemy", "attack_serial": 1, "follows_owner": false, "size": Vector2(700, 200), "active_left": 0.08})
	await runner.simulate_frames(5, 17)
	assert_int(runtime.get_player_snapshot().health).is_equal(100)
	await runner.simulate_frames(18, 17)
	assert_dict(runtime.get_entity_snapshot(hit)).is_empty()
	runtime.request_spawn("hitbox", "grand_lobby", {"position": Vector2(400, 570), "owner_id": owner.id, "team": "enemy", "attack_serial": 2, "follows_owner": false, "size": Vector2(700, 200), "active_left": 0.12})
	await runner.simulate_frames(6, 17)
	assert_int(runtime.get_player_snapshot().health).is_equal(75)
	runtime.request_spawn("hitbox", "grand_lobby", {"position": Vector2(400, 570), "owner_id": owner.id, "team": "enemy", "attack_serial": 3, "follows_owner": false, "size": Vector2(700, 200), "active_left": 0.12})
	await runner.simulate_frames(10, 17)
	assert_int(runtime.get_player_snapshot().health).is_equal(75)
	runtime.player.get_component(C_Health).heal_requested = true
	await runner.simulate_frames(2, 17)
	assert_int(runtime.get_player_snapshot().health).is_equal(100)

func test_projectile_wall_blocks_damage_behind_it() -> void:
	var target: Entity = await _target(Vector2(800, 620))
	runtime.factory.create_platform("grand_lobby", {"id": "shot_wall", "rect": [390, 480, 320, 140]})
	# Solid wall lies between the muzzle and target along the exact shot height.
	await runner.simulate_frames(4, 17)
	runtime.request_spawn("projectile", "grand_lobby", {"position": Vector2(300, 570), "owner_id": "player", "team": "player", "direction": Vector2.RIGHT, "speed": 20000.0})
	await runner.simulate_frames(6, 17)
	assert_int(target.get_component(C_Health).current).is_equal(60)
	assert_array(runtime.get_run_snapshot().projectiles).is_empty()
