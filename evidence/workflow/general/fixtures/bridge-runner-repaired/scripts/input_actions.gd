extends Node

## Object input-actions: keyboard bindings and intent only.
const OBJECT_ID := "input-actions"


func _ready() -> void:
	_bind_key(&"move_left", KEY_LEFT)
	_bind_key(&"move_right", KEY_RIGHT)
	_bind_key(&"jump", KEY_SPACE)
	_bind_key(&"reset_level", KEY_R)


func horizontal_intent() -> float:
	# Equal opposing inputs cancel, including while airborne.
	return Input.get_axis(&"move_left", &"move_right")


func jump_requested() -> bool:
	return Input.is_action_just_pressed(&"jump")


func reset_requested() -> bool:
	return Input.is_action_just_pressed(&"reset_level")


func _bind_key(action: StringName, key: Key) -> void:
	if not InputMap.has_action(action):
		InputMap.add_action(action)
	var event := InputEventKey.new()
	event.keycode = key
	if not InputMap.action_has_event(action, event):
		InputMap.action_add_event(action, event)
