class_name C_Combat extends Component

@export var state: String = "idle"
@export var time_left: float = 0.0
@export var sword_cooldown: float = 0.0
@export var card_cooldown: float = 0.0
@export var dodge_cooldown: float = 0.0
@export var energy: float = 100.0
@export var max_energy: float = 100.0
@export var energy_regen: float = 18.0
@export var card_cost: float = 25.0
@export var attack_serial: int = 0
@export var requested_attack: String = ""
@export var dodge_invulnerable: bool = false
