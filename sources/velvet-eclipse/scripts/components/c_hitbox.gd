class_name C_Hitbox extends Component

@export var owner_id: String = ""
@export var team: String = "player"
@export var attack_serial: int = 0
@export var offset: Vector2 = Vector2(54, -48)
@export var size: Vector2 = Vector2(100, 76)
@export var damage: int = 25
@export var active_left: float = 0.12
@export var hit_ids: Array[String] = []
@export var follows_owner: bool = true
