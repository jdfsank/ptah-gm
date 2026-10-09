extends CharacterBody2D

const SPEED: float = 240.0
var enabled: bool = false


func _physics_process(_delta: float) -> void:
	if not enabled:
		velocity = Vector2.ZERO
		return
	var direction := Input.get_vector("move_left", "move_right", "move_up", "move_down")
	velocity = direction * SPEED
	move_and_slide()
