class_name C_Body extends Component

@export var kind: String = "none"
@export var size: Vector2 = Vector2(40, 96)
@export var offset: Vector2 = Vector2(0, -48)
@export var layer: int = 0
@export var mask: int = 0
@export var ready: bool = false
var root: Node2D = null
var shape: CollisionShape2D = null
