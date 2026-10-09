extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func _arena_fixture() -> void:
	# Explicit location fixture for boss timing tests; the separate route test earns access.
	runtime.session.mode = "transition"
	runtime.session.loading = true
	runtime.session.transition = {"room_id": "house_throne", "spawn_id": "from_save", "reason": "unit_fixture", "applied": false}
	runtime.schedule_flush()
	await runner.simulate_frames(10, 17)

func test_fan_and_slam_warn_before_real_damage_and_bind_independent_hand(_timeout := 20000) -> void:
	await _arena_fixture()
	var first_fan_warning: int = -1
	var first_fan_shot: int = -1
	var first_slam_warning: int = -1
	var first_slam_hit: int = -1
	var saw_hand: bool = false
	for frame in 490:
		await runner.simulate_frames(1, 17)
		var run: Dictionary = runtime.get_run_snapshot()
		var boss: Dictionary = run.bosses[0]
		if boss.boss_state == "fan_warning" and first_fan_warning < 0:
			first_fan_warning = run.tick
		if not run.projectiles.is_empty() and first_fan_shot < 0:
			first_fan_shot = run.tick
		if boss.boss_state == "slam_warning" and first_slam_warning < 0:
			first_slam_warning = run.tick
		for effect in run.effects:
			if effect.effect_kind == "ghost_hand":
				saw_hand = true
		for hit in runtime.world.query.with_all([C_Hitbox]).execute():
			if hit.get_component(C_Hitbox).owner_id == "house_throne:royal_dealer":
				first_slam_hit = run.tick
		if first_slam_hit > 0:
			break
	assert_int(first_fan_warning).is_greater(0)
	assert_int(first_fan_shot - first_fan_warning).is_greater_equal(58)
	assert_int(first_slam_hit - first_slam_warning).is_greater_equal(72)
	assert_bool(saw_hand).is_true()
	var boss_entity: Entity = runtime.world.entity_id_registry["house_throne:royal_dealer"]
	var visual: C_Visual = boss_entity.get_component(C_Visual)
	assert_that(visual.node.sprite_frames).is_same(runtime.resources.resolve("boss_frames"))
	assert_bool(visual.node.flip_h).is_false()
	assert_that(visual.node.get_parent().get_node("BossHealth")).is_instanceof(ProgressBar)

func test_phase_changes_once_on_damage_and_clears_pending_attacks_on_retry() -> void:
	await _arena_fixture()
	var boss_entity: Entity = runtime.world.entity_id_registry["house_throne:royal_dealer"]
	# A legitimate hitbox through DamageSystem isolates the threshold rule.
	runtime.request_spawn("hitbox", "house_throne", {"position": Vector2(1160, 500), "owner_id": "player", "team": "player", "attack_serial": 1, "damage": 720, "size": Vector2(160, 200), "follows_owner": false})
	await runner.simulate_frames(8, 17)
	assert_int(boss_entity.get_component(C_Boss).phase).is_equal(2)
	assert_bool(boss_entity.get_component(C_Boss).phase_changed).is_true()
	var phase_time: float = boss_entity.get_component(C_Boss).time_left
	await runner.simulate_frames(10, 17)
	assert_float(boss_entity.get_component(C_Boss).time_left).is_less(phase_time)
	var background: Entity = runtime.world.entity_id_registry["house_throne:background_0_0"]
	assert_float(background.get_component(C_Visual).tint.g).is_equal_approx(0.38, 0.001)
	runtime.start_new_run()
	await runner.simulate_frames(12, 17)
	assert_str(runtime.session.room_id).is_equal("grand_lobby")
	assert_array(runtime.get_run_snapshot().bosses).is_empty()
	assert_array(runtime.get_run_snapshot().projectiles).is_empty()
	assert_array(runtime.get_run_snapshot().effects).is_empty()

func test_off_room_boss_never_attacks() -> void:
	var boss: Entity = runtime.factory.create_boss("grand_lobby", {"id": "offroom_fixture", "position": [1200, 620]})
	await runner.simulate_frames(120, 17)
	assert_bool(boss.get_component(C_Boss).arena_active).is_false()
	assert_int(boss.get_component(C_Combat).attack_serial).is_zero()

func test_ordinary_sword_and_warning_response_can_defeat_boss(_timeout := 150000) -> void:
	await _arena_fixture()
	var previous_health: int = 100
	for frame in 7200:
		var run: Dictionary = runtime.get_run_snapshot()
		if run.mode == "ending":
			print("M02 isolated arena normal attacks WON at ", frame, " ticks HP=", run.player.health)
			return
		if run.player.dead:
			fail("Ordinary attack/avoidance route died at boss HP " + str(run.bosses[0].health))
			return
		var boss: Dictionary = run.bosses[0]
		if run.player.health != previous_health:
			print("M02 injury frame=", frame, " HP=", run.player.health, " pos=", run.player.position, " vel=", run.player.velocity, " state=", boss.boss_state, " clock=", boss.boss_time_left, " attack=", boss.attack_state)
			previous_health = run.player.health
		var dx: float = boss.position.x - run.player.position.x
		runtime.simulate_action("move_right", dx > 115.0)
		runtime.simulate_action("move_left", dx < 85.0)
		var slam: bool = boss.boss_state == "slam_attack" and boss.boss_time_left > 0.66
		var fan: bool = boss.boss_state == "fan_attack" and boss.boss_time_left > 0.66
		runtime.simulate_action("jump", (slam or fan) and run.player.grounded)
		runtime.simulate_action("sword", frame % 27 == 0)
		runtime.simulate_action("card", frame % 90 == 0 and absf(dx) > 180.0)
		await runner.simulate_frames(1, 17)
	fail("Ordinary boss route timed out")
