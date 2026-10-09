class_name InputSystem extends System

@export var runtime: Node = null
var _held: Dictionary = {}
var _edges: Dictionary = {}
var _last_tick: int = -1

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_Input]).enabled()

func process(entities: Array[Entity], _components: Array, _delta: float) -> void:
	if _last_tick != runtime.tick_index:
		_last_tick = runtime.tick_index
		_edges.clear()
		for event in runtime.take_actions():
			var action: String = event.action
			var pressed: bool = event.pressed
			if pressed and not _held.get(action, false):
				_edges[action] = true
			_held[action] = pressed
	var playing: bool = runtime.session.mode == "playing"
	for entity in entities:
		if not entity.enabled:
			continue
		var input: C_Input = entity.get_component(C_Input)
		if input.source == "ai":
			continue
		input.axis = float(_held.get("move_right", false)) - float(_held.get("move_left", false)) if playing else 0.0
		input.jump_pressed = playing and _edges.get("jump", false)
		input.jump_held = playing and _held.get("jump", false)
		input.sword_pressed = playing and _edges.get("sword", false)
		input.card_pressed = playing and _edges.get("card", false)
		input.dodge_pressed = playing and _edges.get("dodge", false)
		input.interact_pressed = playing and _edges.get("interact", false)
		input.ui_actions.clear()
		for action in ["pause", "map", "ui_accept", "ui_cancel", "ui_left", "ui_right", "ui_up", "ui_down"]:
			if _edges.get(action, false):
				input.ui_actions.append(action)

func clear_actions() -> void:
	_held.clear()
	_edges.clear()
