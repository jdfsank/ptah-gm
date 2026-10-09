extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/main.tscn")
	runtime = runner.scene().get_node("GameWorld")
	await runner.simulate_frames(8, 17)

func test_registered_ui_projects_authoritative_state_without_changing_gameplay() -> void:
	var ui: C_UIState = runtime.world.entity_id_registry.session.get_component(C_UIState)
	assert_int(runtime.world.systems.size()).is_equal(14)
	assert_str(ui.visible_screen).is_equal("title")
	var health: int = runtime.get_player_snapshot().health
	runtime.set_physics_process(false)
	runtime.world.process(0.1, "ui")
	assert_int(ui.snapshot.player.health).is_equal(health)
	ui.snapshot.player.health = 1
	assert_int(runtime.get_player_snapshot().health).is_equal(health)
	assert_bool(runtime.progression.boss_defeated).is_false()

func test_hud_health_energy_moonstep_and_map_are_read_only_projections() -> void:
	runtime.start_new_run()
	await runner.simulate_frames(12, 17)
	var hud: Control = runner.scene().screens.hud
	assert_int(int(hud.health.value)).is_equal(runtime.get_player_snapshot().health)
	assert_int(int(hud.energy.value)).is_equal(int(runtime.get_player_snapshot().energy))
	assert_bool(hud.moonstep.visible).is_false()
	runtime.request_session_action("map")
	await runner.simulate_frames(4, 17)
	var map: Control = runner.scene().screens.map
	assert_bool(map.room_boxes.grand_lobby.visible).is_true()
	assert_str(map.room_boxes.grand_lobby.get_node("RoomLabel").text).contains("当前位置")
	assert_bool(map.room_boxes.roulette_clocktower.visible).is_false()
	assert_bool(map.room_boxes.house_throne.visible).is_false()
	assert_array(runtime.progression.visited_rooms).is_equal(["grand_lobby"])

func test_hidden_screens_cannot_steal_focus_and_bound_font_covers_displayed_chinese() -> void:
	var main: Control = runner.scene()
	for screen_id in main.screens:
		for button in main.screens[screen_id].buttons:
			if screen_id != "title":
				assert_int(button.focus_mode).is_equal(Control.FOCUS_NONE)
	var font: Font = main.screens.title.get_theme_default_font()
	for character in "绯月赌城开始继续生命能量神龛庄家轮盘钟楼闪避":
		assert_bool(font.has_char(character.unicode_at(0))).is_true()
	for screen in main.screens.values():
		for control in screen.find_children("*", "Control", true, false):
			if control is Label or control is Button:
				for character in control.text:
					if character.unicode_at(0) > 127:
						assert_bool(font.has_char(character.unicode_at(0))).is_true()

func test_boss_bar_and_death_ending_screens_only_reflect_given_snapshot() -> void:
	# Isolated presentation fixtures do not advance progression or cause victory.
	var snapshot: Dictionary = runtime.get_run_snapshot()
	snapshot.bosses = [{"id": "fixture", "arena_active": true, "dead": false, "health": 75, "max_health": 100, "phase": 2}]
	var hud: Control = runner.scene().screens.hud
	hud.refresh(snapshot)
	assert_bool(hud.boss_panel.visible).is_true()
	assert_str(hud.boss_text.text).contains("第2阶段")
	assert_float(hud.boss_bar.value).is_equal(75.0)
	snapshot.bosses[0].dead = true
	hud.refresh(snapshot)
	assert_bool(hud.boss_panel.visible).is_false()
	var death: Control = runner.scene().screens.dead
	death.refresh(snapshot)
	assert_str(death.detail.text).contains("大厅")
	assert_str(runner.scene().screens.ending.buttons[0].text).is_equal("重新开始")
	assert_bool(runtime.progression.boss_defeated).is_false()

func test_boss_panel_clears_ground_lane_top_hud_and_notice() -> void:
	# Presentation fixture uses the real Throne HUD strings and acquired-ability row.
	runtime.set_physics_process(false)
	await runner.simulate_frames(2, 17)
	var snapshot: Dictionary = runtime.get_run_snapshot()
	snapshot.room_name = "庄家王座"
	snapshot.objective = "看清预警，闪避卡牌与落掌，击败皇家庄家"
	snapshot.moonstep = true
	snapshot.notice = "第二阶段 · 绯月狂宴"
	snapshot.bosses = [{"id": "fixture", "arena_active": true, "dead": false, "health": 700, "max_health": 1400, "phase": 2}]
	var hud: Control = runner.scene().screens.hud
	hud.size = Vector2(1280, 720)
	hud.set_active(true)
	hud.refresh(snapshot)
	await runner.simulate_frames(3, 17)
	var ground_lane := Rect2(0, 480, 1280, 180)
	var boss_bounds: Rect2 = hud.boss_panel.get_global_rect()
	var notice_bounds: Rect2 = hud.notice_panel.get_global_rect()
	var top_bounds: Rect2 = hud.get_node("Top").get_global_rect()
	print("M03 v2 bounds: top=", top_bounds, " notice=", notice_bounds, " boss=", boss_bounds, " hud=", hud.size)
	assert_bool(boss_bounds.intersects(ground_lane)).is_false()
	assert_bool(boss_bounds.intersects(notice_bounds)).is_false()
	assert_bool(boss_bounds.intersects(top_bounds)).is_false()
	assert_bool(notice_bounds.intersects(top_bounds)).is_false()
	assert_float(boss_bounds.position.y).is_greater_equal(notice_bounds.end.y + 7.0)
	assert_float(boss_bounds.end.y).is_less_equal(360.0)
	snapshot.notice = ""
	hud.refresh(snapshot)
	await runner.simulate_frames(3, 17)
	boss_bounds = hud.boss_panel.get_global_rect()
	assert_bool(boss_bounds.intersects(ground_lane)).is_false()
	assert_bool(boss_bounds.intersects(top_bounds)).is_false()
	assert_float(boss_bounds.position.y).is_equal_approx(top_bounds.end.y + 10.0, 1.0)
