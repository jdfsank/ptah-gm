class_name C_Visual extends Component

@export var asset_id: String = ""
@export var kind: String = "sprite"
@export var offset: Vector2 = Vector2.ZERO
@export var draw_size: Vector2 = Vector2.ZERO
@export var tint: Color = Color.WHITE
@export var z_index: int = 0
@export var animation: String = "idle"
@export var facing: int = 1
@export var flash_left: float = 0.0
var node: Node2D = null
