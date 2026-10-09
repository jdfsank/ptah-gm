extends GdUnitTestSuite

var runner: GdUnitSceneRunner
var runtime: GameRuntime

func before_test() -> void:
	runner = scene_runner("res://scenes/game_world.tscn")
	runtime = runner.scene() as GameRuntime
	await runner.simulate_frames(8, 17)

func test_semantic_input_reaches_player_and_ui_archetypes_once() -> void:
	runtime.set_physics_process(false)
	runtime.simulate_action("move_right", true)
	runtime.simulate_action("jump", true)
	runtime.simulate_action("map", true)
	runtime.tick_index += 1
	runtime.world.process(1.0 / 60.0, "input")
	var player_input: C_Input = runtime.player.get_component(C_Input)
	var ui_input: C_Input = runtime.world.entity_id_registry.session.get_component(C_Input)
	assert_float(player_input.axis).is_equal(1.0)
	assert_bool(player_input.jump_pressed).is_true()
	assert_array(player_input.ui_actions).contains(["map"])
	assert_array(ui_input.ui_actions).contains(["map"])
	runtime.tick_index += 1
	runtime.world.process(1.0 / 60.0, "input")
	assert_bool(player_input.jump_pressed).is_false()
	assert_bool(player_input.jump_held).is_true()
	assert_array(ui_input.ui_actions).is_empty()

func test_repeat_release_unknown_and_disabled_input() -> void:
	runtime.set_physics_process(false)
	assert_bool(runtime.simulate_action("debug_win", true)).is_false()
	runtime.simulate_action("jump", true)
	runtime.tick_index += 1
	runtime.world.process(1.0 / 60.0, "input")
	runtime.simulate_action("jump", true)
	runtime.tick_index += 1
	runtime.world.process(1.0 / 60.0, "input")
	assert_bool(runtime.player.get_component(C_Input).jump_pressed).is_false()
	runtime.simulate_action("jump", false)
	runtime.tick_index += 1
	runtime.world.process(1.0 / 60.0, "input")
	assert_bool(runtime.player.get_component(C_Input).jump_held).is_false()
	runtime.player.enabled = false
	runtime.simulate_action("move_right", true)
	runtime.tick_index += 1
	runtime.world.process(1.0 / 60.0, "input")
	assert_float(runtime.player.get_component(C_Input).axis).is_zero()

func test_input_map_events_use_the_same_queue() -> void:
	var start: float = runtime.get_player_snapshot().position.x
	runner.simulate_key_press(KEY_D)
	await runner.simulate_frames(12, 17)
	runner.simulate_key_release(KEY_D)
	await runner.simulate_frames(8, 17)
	assert_float(runtime.get_player_snapshot().position.x).is_greater(start + 20.0)
	assert_float(runtime.get_player_snapshot().velocity.x).is_zero()

func test_special_keys_accept_logical_events_and_letter_bindings_remain_physical() -> void:
	for entry in [[KEY_LEFT, "move_left"], [KEY_RIGHT, "move_right"], [KEY_SPACE, "jump"], [KEY_SHIFT, "dodge"], [KEY_ESCAPE, "pause"], [KEY_ENTER, "ui_accept"]]:
		var event := InputEventKey.new()
		event.keycode = entry[0]
		event.physical_keycode = 0
		event.pressed = true
		assert_bool(event.is_action_pressed(entry[1])).is_true()
	assert_int(InputMap.action_get_events("sword")[0].physical_keycode).is_equal(KEY_J)
	assert_int(InputMap.action_get_events("move_left")[0].physical_keycode).is_equal(KEY_A)
