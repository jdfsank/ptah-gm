extends Node2D

## Source binding for main-scene, exit, win, fall-restart, manual-reset,
## and level-state. All player simulation is stepped here after reset intent.
const OBJECT_IDS := [
	"main-scene", "exit", "win", "fall-restart", "manual-reset", "level-state"
]
const SPAWN := Vector2(100.0, 414.0)
const FALL_LIMIT := 600.0

enum LevelState { PLAYING, WON }

var state: LevelState = LevelState.PLAYING
var _exit_contact_ready: bool = false

@onready var player = $Player
@onready var player_collision: CollisionShape2D = $Player/CollisionShape2D
@onready var input_actions = $InputActions
@onready var exit_area: Area2D = $Exit
@onready var exit_collision: CollisionShape2D = $Exit/CollisionShape2D
@onready var hud = $HUD


func _ready() -> void:
	restart_level()


func _physics_process(delta: float) -> void:
	# manual-reset has priority over simulation and every other transition.
	if input_actions.reset_requested():
		restart_level()
		return
	if state == LevelState.WON:
		return
	player.simulate(
		delta, input_actions.horizontal_intent(), input_actions.jump_requested()
	)
	if player.global_position.y > FALL_LIMIT:
		restart_level()
		return
	if not _exit_contact_ready:
		# Rearm only once physics has cleared any pre-teleport Area2D overlap.
		_exit_contact_ready = not exit_area.overlaps_body(player)
		return
	if exit_area.overlaps_body(player) and _has_current_exit_contact():
		_win_level()


func restart_level() -> void:
	# fall-restart and manual-reset share this complete restoration path.
	_exit_contact_ready = false
	state = LevelState.PLAYING
	player.reset_to(SPAWN)
	hud.show_playing()


func _has_current_exit_contact() -> bool:
	# Area2D caches contacts; confirm the shapes at their current transforms.
	# No body_entered callback can latch a contact from before a restart.
	return player_collision.shape.collide(
		player_collision.global_transform, exit_collision.shape, exit_collision.global_transform
	)


func _win_level() -> void:
	state = LevelState.WON
	_exit_contact_ready = false
	player.stop_motion()
	hud.show_won()
