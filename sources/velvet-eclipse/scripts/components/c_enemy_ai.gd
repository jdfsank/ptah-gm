class_name C_EnemyAI extends Component

@export var kind: String = "melee"
@export var state: String = "idle"
@export var time_left: float = 0.0
@export var home: Vector2 = Vector2.ZERO
@export var patrol_radius: float = 150.0
@export var aggro_range: float = 560.0
@export var attack_range: float = 85.0
@export var target_id: String = "player"
