class_name C_Motion extends Component

@export var velocity: Vector2 = Vector2.ZERO
@export var desired_velocity: Vector2 = Vector2.ZERO
@export var speed: float = 300.0
@export var acceleration: float = 2400.0
@export var gravity: float = 1500.0
@export var jump_speed: float = 580.0
@export var max_fall_speed: float = 900.0
@export var grounded: bool = false
@export var facing: int = 1
@export var jumps_used: int = 0
@export var coyote_left: float = 0.0
@export var buffer_left: float = 0.0
@export var coyote_duration: float = 0.10
@export var buffer_duration: float = 0.12
@export var placement_pending: bool = true
