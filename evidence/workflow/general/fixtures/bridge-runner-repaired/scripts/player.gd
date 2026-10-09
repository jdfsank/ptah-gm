extends CharacterBody2D

## Object player; mechanisms horizontal-movement, jump, platform-collision.
## The controller supplies intent and owns the timing of each simulation step.
const OBJECT_ID := "player"
const MECHANISM_IDS := ["horizontal-movement", "jump", "platform-collision"]
const GRAVITY := 1000.0
const RuntimeSource = preload("res://studio/runtime.gd")

var speed: float = 0.0
var jump_speed: float = 0.0
var controls_enabled: bool = false
var _studio_runtime = RuntimeSource.new()


func reset_to(spawn: Vector2) -> void:
	global_position = spawn
	velocity = Vector2.ZERO
	# Read the authoritative fields on startup and on both restart paths.
	# Do not duplicate their defaults or ranges in game source.
	var speed_value: Variant = _studio_runtime.object_value(OBJECT_ID, "speed")
	var jump_value: Variant = _studio_runtime.object_value(OBJECT_ID, "jump-speed")
	controls_enabled = (
		(speed_value is int or speed_value is float)
		and (jump_value is int or jump_value is float)
	)
	if not controls_enabled:
		push_error("Player requires numeric speed and jump-speed fields in design/game.json.")
		return
	speed = float(speed_value)
	jump_speed = float(jump_value)


func simulate(delta: float, direction: float, jump_pressed: bool) -> void:
	if not controls_enabled:
		return
	# horizontal-movement: immediate start/stop, with no residual drift.
	velocity.x = direction * speed
	# jump: only a fresh press on a supporting platform starts a jump.
	velocity.y += GRAVITY * delta
	if jump_pressed and is_on_floor():
		velocity.y = -jump_speed
	# platform-collision: use the scene's matching solid collision rectangles.
	move_and_slide()


func stop_motion() -> void:
	controls_enabled = false
	velocity = Vector2.ZERO
