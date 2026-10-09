extends Control

## main-scene: coordinates the model and views; input is routed separately.

const RulesModel = preload("res://scripts/rules.gd")
const BoardView = preload("res://scripts/puzzle_board.gd")
const HudView = preload("res://scripts/hud.gd")
const InputRouter = preload("res://scripts/puzzle_input.gd")

@onready var _rules: RulesModel = $Rules
@onready var _board: BoardView = $PuzzleBoard
@onready var _hud: HudView = $HUD
@onready var _input_router: InputRouter = $PuzzleInput


func _ready() -> void:
	_input_router.cell_requested.connect(_on_cell_requested)
	_input_router.reset_requested.connect(_reset_puzzle)
	_input_router.bind_controls(_board, _hud)
	_reset_puzzle()


func _on_cell_requested(row: int, column: int) -> void:
	if _rules.activate_cell(row, column):
		_refresh_views()


func _reset_puzzle() -> void:
	_rules.reset()
	_refresh_views()


func _refresh_views() -> void:
	_board.render_state(_rules.get_cells(), _rules.is_solved())
	_hud.render_progress(_rules.get_move_count(), _rules.is_solved())
