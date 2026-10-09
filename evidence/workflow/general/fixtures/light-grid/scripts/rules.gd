extends Node

## rules: simulation only. Coordinates are zero-based (row, column).
## Start and documented solution: (0, 0), (1, 1), (2, 2).

const GRID_SIZE: int = 3
const CELL_COUNT: int = GRID_SIZE * GRID_SIZE
const START_SEQUENCE = [Vector2i(0, 0), Vector2i(1, 1), Vector2i(2, 2)]
const CROSS_OFFSETS = [
	Vector2i.ZERO,
	Vector2i.UP,
	Vector2i.DOWN,
	Vector2i.LEFT,
	Vector2i.RIGHT,
]

var _cells: Array[bool] = []
var _move_count: int = 0
var _solved: bool = false


func _init() -> void:
	reset()


func reset() -> void:
	_cells.resize(CELL_COUNT)
	_cells.fill(false)
	_move_count = 0
	_solved = false
	# Seed through the same cross rule without recording player moves.
	for selection in START_SEQUENCE:
		_toggle_cross(selection.x, selection.y)


func activate_cell(row: int, column: int) -> bool:
	if _solved or not _is_in_bounds(row, column):
		return false
	_toggle_cross(row, column)
	_move_count += 1
	_solved = not _cells.has(true)
	return true


func get_cells() -> Array[bool]:
	# A snapshot prevents views or input code from mutating the model's array.
	return _cells.duplicate()


func get_move_count() -> int:
	return _move_count


func is_solved() -> bool:
	return _solved


func _toggle_cross(row: int, column: int) -> void:
	for offset in CROSS_OFFSETS:
		var neighbor_row: int = row + offset.y
		var neighbor_column: int = column + offset.x
		if _is_in_bounds(neighbor_row, neighbor_column):
			var index: int = neighbor_row * GRID_SIZE + neighbor_column
			_cells[index] = not _cells[index]


func _is_in_bounds(row: int, column: int) -> bool:
	return row >= 0 and row < GRID_SIZE and column >= 0 and column < GRID_SIZE
