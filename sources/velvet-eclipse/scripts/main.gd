extends Control

const SCREENS: Dictionary = {"title": preload("res://scenes/ui/title_screen.tscn"), "hud": preload("res://scenes/ui/hud.tscn"), "paused": preload("res://scenes/ui/pause_overlay.tscn"), "map": preload("res://scenes/ui/map_overlay.tscn"), "dead": preload("res://scenes/ui/death_screen.tscn"), "ending": preload("res://scenes/ui/ending_screen.tscn")}
@onready var runtime: GameRuntime = $GameWorld
var screens: Dictionary = {}
var current_mode: String = ""
var continue_available: bool = false
var continue_notice: String = ""

func _ready() -> void:
	for screen_id in SCREENS:
		var screen: CasinoScreen = SCREENS[screen_id].instantiate()
		screen.name = screen_id
		$Overlay/Controls.add_child(screen)
		screen.action_requested.connect(_on_action)
		screen.set_active(false)
		screens[screen_id] = screen
	runtime.ui_root = self
	present(runtime.get_run_snapshot(), runtime.world.entity_id_registry.session.get_component(C_UIState))

func _on_action(action: String) -> void:
	if action == "map" and runtime.session.mode == "paused":
		runtime.request_session_action("resume")
	runtime.request_session_action(action)

func present(snapshot: Dictionary, state: C_UIState) -> void:
	var mode: String = snapshot.get("mode", "title")
	if mode == "title" and current_mode != mode:
		continue_available = runtime.can_continue()
		continue_notice = "可继续上次的检查点" if continue_available else runtime.save_repository.last_error + " · 请选择开始游戏"
	if mode != current_mode:
		current_mode = mode
		get_viewport().gui_release_focus()
		for screen_id in screens:
			screens[screen_id].set_active(screen_id == mode or (screen_id == "hud" and mode in ["playing", "paused", "map", "transition"]))
	snapshot["can_continue"] = continue_available
	snapshot["continue_notice"] = continue_notice
	snapshot["notice"] = state.notice if state.notice_left > 0.0 or snapshot.get("save_status", "") == "failed" else ""
	for screen_id in screens:
		if screens[screen_id].visible:
			screens[screen_id].refresh(snapshot)
	var focus: Control = get_viewport().gui_get_focus_owner()
	if focus != null and mode in screens:
		state.focus_index = screens[mode].buttons.find(focus)
	# Existing world-space boss labels are replaced by the screen-safe authoritative HUD.
	for boss in snapshot.get("bosses", []):
		var entity: Entity = runtime.world.entity_id_registry.get(boss.id)
		if is_instance_valid(entity):
			var body: C_Body = entity.get_component(C_Body)
			if body != null and is_instance_valid(body.root):
				for node_name in ["BossHealth", "BossTitle"]:
					var label: CanvasItem = body.root.get_node_or_null(node_name)
					if label != null:
						label.hide()
