class_name C_Projectile extends Component

@export var owner_id: String = ""
@export var team: String = "player"
@export var direction: Vector2 = Vector2.RIGHT
@export var speed: float = 660.0
@export var damage: int = 20
@export var remaining: float = 2.0
@export var consumed: bool = false
@export var previous_position: Vector2 = Vector2.ZERO
