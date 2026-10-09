extends Node

## main-scene input routing: forwards UI choices and the R reset action.
## No model data is mutated here. _input runs before focused controls handle keys.

signal cell_requested(row: int, column: int)
signal reset_requested

const BoardView = preload("res://scripts/puzzle_board.gd")
const HudView = preload("res://scripts/hud.gd")
const RESET_ACTION: StringName = &"reset_puzzle"


func bind_controls(board: BoardView, hud: HudView) -> void:
	board.cell_selected.connect(_on_cell_selected)
	hud.reset_requested.connect(_on_reset_requested)


func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.echo:
		return
	if event.is_action_pressed(RESET_ACTION):
		reset_requested.emit()
		get_viewport().set_input_as_handled()


func _on_cell_selected(row: int, column: int) -> void:
	cell_requested.emit(row, column)


func _on_reset_requested() -> void:
	reset_requested.emit()
