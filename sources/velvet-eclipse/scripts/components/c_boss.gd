class_name C_Boss extends Component

@export var phase: int = 1
@export var state: String = "idle"
@export var time_left: float = 1.2
@export var attack_index: int = 0
@export var phase_changed: bool = false
@export var arena_active: bool = false
@export var slam_center: Vector2 = Vector2.ZERO
