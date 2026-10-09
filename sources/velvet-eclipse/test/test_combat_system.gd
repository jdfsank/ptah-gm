extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_sword_timing_repeat_and_card_energy_negative_paths() -> void:
	runtime.simulate_action("sword", true)
	await runner.simulate_frames(1, 17)
	assert_str(runtime.get_player_snapshot().attack_state).is_equal("sword_windup")
	assert_array(runtime.world.query.with_all([C_Hitbox]).execute()).is_empty()
	await runner.simulate_frames(9, 17)
	assert_int(runtime.get_player_snapshot().attack_serial).is_equal(1)
	assert_str(runtime.get_player_snapshot().animation).is_equal("attack")
	runtime.simulate_action("sword", true)
	await runner.simulate_frames(24, 17)
	assert_int(runtime.get_player_snapshot().attack_serial).is_equal(1)
	var combat: C_Combat = runtime.player.get_component(C_Combat)
	combat.energy = 24.0
	combat.energy_regen = 0.0
	runtime.simulate_action("card", true)
	await runner.simulate_frames(3, 17)
	assert_int(runtime.get_player_snapshot().attack_serial).is_equal(1)
	assert_float(combat.energy).is_equal(24.0)
	assert_array(runtime.get_run_snapshot().projectiles).is_empty()

func test_card_cost_cooldown_and_dodge_have_bounded_windows() -> void:
	runtime.simulate_action("card", true)
	await runner.simulate_frames(2, 17)
	var spent: float = runtime.get_player_snapshot().energy
	assert_float(spent).is_between(75.0, 77.0)
	assert_str(runtime.get_player_snapshot().animation).is_equal("cast")
	runtime.simulate_action("card", false)
	await runner.simulate_frames(1, 17)
	runtime.simulate_action("card", true)
	await runner.simulate_frames(8, 17)
	assert_int(runtime.get_player_snapshot().attack_serial).is_equal(1)
	assert_int(runtime.get_run_snapshot().projectiles.size()).is_equal(1)
	await runner.simulate_frames(22, 17)
	var start_x: float = runtime.get_player_snapshot().position.x
	runtime.simulate_action("dodge", true)
	await runner.simulate_frames(2, 17)
	assert_bool(runtime.get_player_snapshot().dodge_invulnerable).is_true()
	assert_str(runtime.get_player_snapshot().animation).is_equal("dodge")
	runtime.simulate_action("dodge", false)
	await runner.simulate_frames(18, 17)
	assert_bool(runtime.get_player_snapshot().dodge_invulnerable).is_false()
	assert_float(runtime.get_player_snapshot().position.x - start_x).is_between(145.0, 190.0)
	runtime.simulate_action("dodge", true)
	await runner.simulate_frames(2, 17)
	assert_str(runtime.get_player_snapshot().attack_state).is_equal("idle")

func test_normal_lobby_encounter_takes_damage_and_defeats_with_real_sword() -> void:
	runtime.simulate_action("move_right", true)
	for frame in 140:
		await runner.simulate_frames(1, 17)
		var enemy: Dictionary = runtime.get_entity_snapshot("grand_lobby:skeletal_dealer")
		if enemy.position.x - runtime.get_player_snapshot().position.x <= 70.0:
			break
	runtime.simulate_action("move_right", false)
	await runner.simulate_frames(75, 17)
	assert_int(runtime.get_player_snapshot().health).is_less(100)
	for swing in 8:
		runtime.simulate_action("sword", true)
		await runner.simulate_frames(2, 17)
		runtime.simulate_action("sword", false)
		await runner.simulate_frames(30, 17)
		if runtime.get_entity_snapshot("grand_lobby:skeletal_dealer").is_empty():
			break
	assert_dict(runtime.get_entity_snapshot("grand_lobby:skeletal_dealer")).is_empty()
	assert_bool(runtime.get_player_snapshot().dead).is_false()
	print("M01 normal lobby sword encounter: real injury and skeletal dealer defeat; hero HP=", runtime.get_player_snapshot().health)

func test_normal_actions_clear_all_three_encounters_using_sword_and_cards() -> void:
	var saw_energy_spend: bool = false
	var saw_projectile: bool = false
	var saw_projectile_damage: bool = false
	for step in 120:
		var enemies: Array = runtime.get_run_snapshot().enemies
		var target: Dictionary = {}
		for enemy in enemies:
			if not enemy.dead:
				target = enemy
				break
		if target.is_empty():
			break
		var offset: float = target.position.x - runtime.get_player_snapshot().position.x
		runtime.simulate_action("move_right", offset > 65.0)
		runtime.simulate_action("move_left", offset < -65.0)
		if step % 6 == 0:
			runtime.simulate_action("card", true)
			runtime.simulate_action("sword", absf(offset) < 105.0)
		else:
			runtime.simulate_action("card", false)
			runtime.simulate_action("sword", false)
		await runner.simulate_frames(5, 17)
		var snapshot: Dictionary = runtime.get_run_snapshot()
		saw_energy_spend = saw_energy_spend or snapshot.player.energy < 90.0
		saw_projectile = saw_projectile or not snapshot.projectiles.is_empty()
		for enemy in snapshot.enemies:
			saw_projectile_damage = saw_projectile_damage or enemy.health == 40 or enemy.health == 20
	runtime.simulate_action("move_right", false)
	runtime.simulate_action("move_left", false)
	await runner.simulate_frames(20, 17)
	assert_bool(saw_energy_spend).is_true()
	assert_bool(saw_projectile).is_true()
	assert_bool(saw_projectile_damage).is_true()
	assert_array(runtime.get_run_snapshot().enemies).is_empty()
	assert_bool(runtime.get_player_snapshot().dead).is_false()
	print("M01 ordinary action route: all three Lobby encounters defeated; cards spent energy and hit; hero HP=", runtime.get_player_snapshot().health)
