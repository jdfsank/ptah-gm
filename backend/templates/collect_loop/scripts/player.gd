class_name CollectLoopPlayer
extends CharacterBody2D

var move_speed: float = 220.0

func _ready() -> void:
	collision_layer = 1
	collision_mask = 1
	var collision := CollisionShape2D.new()
	var shape := CircleShape2D.new()
	shape.radius = 12.0
	collision.shape = shape
	add_child(collision)

func _physics_process(_delta: float) -> void:
	var direction := Input.get_vector("move_left", "move_right", "move_up", "move_down")
	velocity = direction * move_speed
	move_and_slide()
	position.x = clampf(position.x, 20.0, 620.0)
	position.y = clampf(position.y, 20.0, 340.0)
