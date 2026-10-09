extends Node2D

const VariantConfig = preload("res://variant.gd")
const SPAWN: Vector2 = Vector2(96.0, 320.0)

var key_count: int = 0
var gate_open: bool = false
var won: bool = false
var rounds_started: int = 0

@onready var world: Node2D = $World
@onready var player: CharacterBody2D = $World/Player
@onready var key: Area2D = $World/Key
@onready var gate: StaticBody2D = $World/Gate
@onready var gate_shape: CollisionShape2D = $World/Gate/CollisionShape2D
@onready var gate_visual: Polygon2D = $World/Gate/Visual
@onready var hud: Control = $UI/Root/HUD
@onready var key_label: Label = $UI/Root/HUD/KeyLabel
@onready var gate_label: Label = $UI/Root/HUD/GateLabel
@onready var hint_label: Label = $UI/Root/HUD/HintLabel
@onready var start_menu: Control = $UI/Root/StartMenu
@onready var pause_menu: Control = $UI/Root/PauseMenu
@onready var result_menu: Control = $UI/Root/ResultMenu


func _ready() -> void:
	# The pause fault changes game processing, not the test oracle.
	if VariantConfig.NAME == "pause_input_leak":
		player.process_mode = Node.PROCESS_MODE_ALWAYS
	$UI/Root/StartMenu/StartButton.grab_focus()


func start_round() -> void:
	for action in ["move_left", "move_right", "move_up", "move_down"]:
		Input.action_release(action)
	get_tree().paused = false
	var preserve_inventory := VariantConfig.NAME == "dirty_restart" and rounds_started > 0
	if not preserve_inventory:
		key_count = 0
		gate_open = VariantConfig.NAME == "always_open_door"
	won = false
	rounds_started += 1
	player.position = SPAWN
	player.velocity = Vector2.ZERO
	player.enabled = true
	key.visible = key_count == 0
	key.set_deferred("monitoring", key_count == 0)
	gate_shape.set_deferred("disabled", gate_open)
	gate_visual.color = Color(0.15, 0.75, 0.45) if gate_open else Color(0.85, 0.35, 0.2)
	key_label.text = "Key: %d/1" % key_count
	gate_label.text = "Gate: open" if gate_open else "Gate: locked"
	hint_label.text = "Find the gold key, pass the gate, reach the exit."
	start_menu.hide()
	pause_menu.hide()
	result_menu.hide()
	hud.show()
	$UI/Root/HUD/PauseButton.release_focus()


func pause_round() -> void:
	if not player.enabled or won:
		return
	player.velocity = Vector2.ZERO
	get_tree().paused = true
	pause_menu.show()
	$UI/Root/PauseMenu/ResumeButton.grab_focus()


func resume_round() -> void:
	player.velocity = Vector2.ZERO
	pause_menu.hide()
	get_tree().paused = false
	$UI/Root/PauseMenu/ResumeButton.release_focus()


func _on_key_body_entered(body: Node2D) -> void:
	if body != player or key_count != 0 or not player.enabled:
		return
	key_count += 1
	key.hide()
	key.set_deferred("monitoring", false)
	if VariantConfig.NAME != "stale_hud":
		key_label.text = "Key: %d/1" % key_count
	hint_label.text = "Key collected. Walk into the gate to unlock it."


func _on_gate_body_entered(body: Node2D) -> void:
	if body != player or gate_open or not player.enabled:
		return
	if key_count == 0:
		hint_label.text = "Gate locked. Find the key."
		return
	gate_open = true
	gate_shape.set_deferred("disabled", true)
	gate_visual.color = Color(0.15, 0.75, 0.45)
	gate_label.text = "Gate: open"
	hint_label.text = "Gate unlocked. Reach the green exit."


func _on_exit_body_entered(body: Node2D) -> void:
	if body != player or won or not player.enabled:
		return
	if key_count == 0 or not gate_open:
		return
	won = true
	player.enabled = false
	player.velocity = Vector2.ZERO
	hud.hide()
	pause_menu.hide()
	result_menu.show()
	$UI/Root/ResultMenu/RestartButton.grab_focus()
