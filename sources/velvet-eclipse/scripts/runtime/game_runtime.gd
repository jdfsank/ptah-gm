class_name GameRuntime extends Node2D

signal runtime_ready
signal runtime_failed(message: String)

const ACTIONS: Array[String] = ["move_left", "move_right", "jump", "sword", "card", "dodge", "interact", "map", "pause", "ui_accept", "ui_cancel", "ui_left", "ui_right", "ui_up", "ui_down"]
@export_enum("title", "gameplay") var entry_mode: String = "gameplay"
var ui_root: Node = null
var world: World
var progression: C_Progression
var checkpoint: C_Checkpoint
var save_repository := SaveRepository.new()
var room_epoch: int = 0
var _session_actions: Array[String] = []
var session: C_Session
var player: GameEntity
var camera: Camera2D
var resources := ResourceCatalog.new()
var rooms := RoomCatalog.new()
var factory: EntityFactory
var room_data: Dictionary = {}
var room_bounds := Rect2(0, 0, 2400, 720)
var tick_index: int = 0
var landing_count: int = 0
var in_safe_flush: bool = false
var executed_groups: Array[String] = []
var _actions: Array[Dictionary] = []
var _placements: Dictionary = {}
var _pending_placements: Dictionary = {}
var _removals: Array[String] = []
var _spawns: Array[Dictionary] = []
var _spawn_serial: int = 0
var _projectile_contacts: Dictionary = {}
var _flush_scheduled: bool = false
var _last_delta: float = 0.0
var _ready_emitted: bool = false

func _ready() -> void:
	world = World.new()
	world.name = "GameECS"
	world.entity_nodes_root = NodePath(".")
	world.system_nodes_root = NodePath(".")
	add_child(world)
	ECS.set("world", world)
	assert(ECS.world == world)
	for entry in [[InputSystem.new(), "input"], [EnemyAISystem.new(), "ai"], [BossSystem.new(), "boss"], [CombatSystem.new(), "combat"], [MovementSystem.new(), "movement"], [DamageSystem.new(), "damage"], [InteractionSystem.new(), "interaction"], [ProgressionSystem.new(), "progression"], [SaveSystem.new(), "save"], [EffectSystem.new(), "effects"], [MaterializationSystem.new(), "materialize"], [AnimationSystem.new(), "animation"], [CameraSystem.new(), "camera"], [UISystem.new(), "ui"]]:
		var system: System = entry[0]
		system.name = system.get_script().get_global_name()
		system.set("runtime", self)
		system.group = entry[1]
		system.command_buffer_flush_mode = "MANUAL"
		world.add_system(system)
	world.finalize_system_setup()
	factory = EntityFactory.new(self)
	var session_entity := factory.create_session()
	session_entity.add_component(C_UIState.new())
	session = session_entity.get_component(C_Session)
	progression = session_entity.get_component(C_Progression)
	checkpoint = session_entity.get_component(C_Checkpoint)
	checkpoint.payload = {"version": 1, "checkpoint_id": "start", "room_id": "grand_lobby", "spawn_id": "start", "moonstep": false, "visited_rooms": ["grand_lobby"], "boss_defeated": false, "ending_seen": false}
	if not rooms.validate_graph(resources):
		fail(rooms.last_error)
		return
	session.transition = {"applied": true}
	room_data = rooms.load_room("grand_lobby", resources)
	if room_data.is_empty():
		fail(rooms.last_error)
		return
	var bounds: Array = room_data.bounds
	room_bounds = Rect2(bounds[0], bounds[1], bounds[2], bounds[3])
	factory.create_room(room_data)
	var start: Array = room_data.spawns.start
	player = factory.create_player(Vector2(start[0], start[1]))
	if entry_mode == "title":
		session.mode = "title"
		session.loading = false
		session.transition.clear()
	schedule_flush()

func _unhandled_input(event: InputEvent) -> void:
	if event.is_echo():
		return
	for action in ACTIONS:
		# Godot GUI handles menu focus and Enter. Escape has one runtime action.
		if action.begins_with("ui_"):
			continue
		if event.is_action_pressed(action):
			simulate_action(action, true)
		elif event.is_action_released(action):
			simulate_action(action, false)

func simulate_action(action: String, pressed: bool) -> bool:
	if not action in ACTIONS:
		return false
	_actions.append({"action": action, "pressed": pressed})
	return true

func take_actions() -> Array[Dictionary]:
	var result: Array[Dictionary] = _actions
	_actions = []
	return result

func request_placement(entity_id: String, position: Vector2, rotation: float = 0.0, scale: Vector2 = Vector2.ONE) -> void:
	_placements[entity_id] = {"entity_id": entity_id, "position": position, "rotation": rotation, "scale": scale}
	_pending_placements[entity_id] = true

func take_placements() -> Dictionary:
	var result: Dictionary = _placements
	_placements = {}
	return result

func placement_completed(entity_id: String) -> void:
	_pending_placements.erase(entity_id)

func request_removal(entity_id: String) -> void:
	if not entity_id in _removals:
		_removals.append(entity_id)
	schedule_flush()

func _physics_process(delta: float) -> void:
	if session == null:
		return
	tick_index += 1
	_last_delta = delta
	executed_groups.clear()
	_run_group("input", delta)
	var modal_pending: bool = false
	var ui: C_Input = world.entity_id_registry["session"].get_component(C_Input)
	for action in ui.ui_actions + _session_actions:
		if action in ["pause", "map", "title", "new_run", "continue_run", "retry"]:
			modal_pending = true
	if session.mode == "playing" and not modal_pending:
		for group_name in ["ai", "boss", "combat", "movement", "damage", "interaction"]:
			_run_group(group_name, delta)
	elif session.loading and session.mode == "transition":
		_run_group("movement", 0.0)
		_run_group("damage", 0.0)
	_run_group("progression", delta if session.mode == "playing" else 0.0)
	_run_group("save", 0.0)
	if session.mode == "playing" and not modal_pending:
		_run_group("effects", delta)
	schedule_flush()

func _run_group(group_name: String, delta: float) -> void:
	executed_groups.append(group_name)
	ECS.process(delta, group_name)

func schedule_flush() -> void:
	if not _flush_scheduled:
		_flush_scheduled = true
		_deferred_flush.call_deferred()

func _deferred_flush() -> void:
	_flush_scheduled = false
	if not is_inside_tree() or not is_instance_valid(world):
		return
	in_safe_flush = true
	world.flush_command_buffers()
	for entity_id in _removals:
		var entity: Entity = world.entity_id_registry.get(entity_id)
		if is_instance_valid(entity):
			world.remove_entity(entity)
		_pending_placements.erase(entity_id)
		_placements.erase(entity_id)
	_removals.clear()
	_apply_room_transition()
	var spawns: Array[Dictionary] = _spawns
	_spawns = []
	for request in spawns:
		if request.room_id == session.room_id and request.epoch == room_epoch and session.mode == "playing":
			factory.create_transient(request.archetype, request.room_id, request.fields)
	_run_group("materialize", _last_delta)
	_run_group("animation", _last_delta if session.mode == "playing" else 0.0)
	_run_group("camera", _last_delta)
	_run_group("ui", _last_delta)
	in_safe_flush = false
	if entry_mode == "title" and placements_complete():
		announce_ready()

func fail(message: String) -> void:
	if session != null:
		session.mode = "error"
		session.loading = false
		session.message = message
	push_error(message)
	runtime_failed.emit(message)

func request_spawn(archetype: String, room_id: String, fields: Dictionary) -> String:
	_spawn_serial += 1
	var entity_id: String = "%s:%s:%d" % [room_id, archetype, _spawn_serial]
	var payload: Dictionary = fields.duplicate(true)
	payload["id"] = entity_id
	_spawns.append({"archetype": archetype, "room_id": room_id, "fields": payload, "epoch": room_epoch})
	schedule_flush()
	return entity_id

func record_projectile_contact(entity_id: String, target_id: String = "") -> void:
	_projectile_contacts[entity_id] = target_id

func take_projectile_contacts() -> Dictionary:
	var result: Dictionary = _projectile_contacts
	_projectile_contacts = {}
	return result

func get_entity_snapshot(entity_id: String) -> Dictionary:
	var entity: Entity = world.entity_id_registry.get(entity_id)
	if not is_instance_valid(entity):
		return {}
	var result: Dictionary = {"id": entity.id, "enabled": entity.enabled}
	var transform: C_Transform = entity.get_component(C_Transform)
	if transform != null:
		result.position = transform.position
	var health: C_Health = entity.get_component(C_Health)
	if health != null:
		result.merge({"health": health.current, "max_health": health.maximum, "dead": health.dead, "hurt_left": health.hurt_left, "invulnerable_left": health.invulnerable_left, "team": health.team})
	var combat: C_Combat = entity.get_component(C_Combat)
	if combat != null:
		result.merge({"energy": combat.energy, "max_energy": combat.max_energy, "attack_state": combat.state, "attack_serial": combat.attack_serial, "sword_cooldown": combat.sword_cooldown, "card_cooldown": combat.card_cooldown, "dodge_cooldown": combat.dodge_cooldown, "dodge_invulnerable": combat.dodge_invulnerable})
	var boss: C_Boss = entity.get_component(C_Boss)
	if boss != null:
		result.merge({"phase": boss.phase, "boss_state": boss.state, "boss_time_left": boss.time_left, "phase_changed": boss.phase_changed, "attack_index": boss.attack_index, "arena_active": boss.arena_active, "slam_center": boss.slam_center})
	var effect: C_Effect = entity.get_component(C_Effect)
	if effect != null:
		result.merge({"effect_kind": effect.kind, "remaining": effect.remaining, "duration": effect.duration, "effect_size": effect.size})
	var interaction: C_Interaction = entity.get_component(C_Interaction)
	if interaction != null:
		result.merge({"interaction_kind": interaction.kind, "prompt": interaction.prompt, "selected": interaction.selected, "available": interaction.available, "target_room": interaction.target_room, "target_spawn": interaction.target_spawn})
	var ai: C_EnemyAI = entity.get_component(C_EnemyAI)
	if ai != null:
		result.merge({"enemy_kind": ai.kind, "ai_state": ai.state, "ai_time_left": ai.time_left})
	var projectile: C_Projectile = entity.get_component(C_Projectile)
	if projectile != null:
		result.merge({"owner_id": projectile.owner_id, "remaining": projectile.remaining, "consumed": projectile.consumed, "previous_position": projectile.previous_position, "direction": projectile.direction})
	var visual: C_Visual = entity.get_component(C_Visual)
	if visual != null:
		result.merge({"animation": visual.animation, "visual_kind": visual.kind, "tint": visual.tint, "visual_offset": visual.offset})
		if visual.node is AnimatedSprite2D:
			result.frame = visual.node.frame
	return result

func get_player_snapshot() -> Dictionary:
	if not is_instance_valid(player):
		return {}
	var transform: C_Transform = player.get_component(C_Transform)
	var motion: C_Motion = player.get_component(C_Motion)
	var body: C_Body = player.get_component(C_Body)
	var visual: C_Visual = player.get_component(C_Visual)
	var sprite: AnimatedSprite2D = visual.node as AnimatedSprite2D
	var result: Dictionary = {"id": player.id, "position": transform.position, "velocity": motion.velocity, "grounded": motion.grounded, "facing": motion.facing, "jumps_used": motion.jumps_used, "coyote_left": motion.coyote_left, "buffer_left": motion.buffer_left, "body_ready": body.ready, "placement_pending": motion.placement_pending, "animation": visual.animation, "frame": sprite.frame if sprite != null else -1, "frame_progress": sprite.frame_progress if sprite != null else 0.0, "flipped": sprite.flip_h if sprite != null else false, "body_type": body.root.get_class() if is_instance_valid(body.root) else "", "body_size": body.size, "body_offset": body.offset}

	result.merge(get_entity_snapshot(player.id), true)
	return result

func get_run_snapshot() -> Dictionary:
	var enemies: Array[Dictionary] = []
	var projectiles: Array[Dictionary] = []
	var bosses: Array[Dictionary] = []
	var interactions: Array[Dictionary] = []
	var effects: Array[Dictionary] = []
	if is_instance_valid(world):
		for entity in world.query.with_all([C_EnemyAI]).enabled().execute():
			if entity.enabled:
				enemies.append(get_entity_snapshot(entity.id))
		for entity in world.query.with_all([C_Projectile]).enabled().execute():
			if entity.enabled:
				projectiles.append(get_entity_snapshot(entity.id))
		for entity in world.query.with_all([C_Boss]).enabled().execute():
			if entity.enabled:
				bosses.append(get_entity_snapshot(entity.id))
		for entity in world.query.with_all([C_Interaction]).enabled().execute():
			if entity.enabled:
				interactions.append(get_entity_snapshot(entity.id))
		for entity in world.query.with_all([C_Effect]).enabled().execute():
			if entity.enabled:
				effects.append(get_entity_snapshot(entity.id))
	var light: Color = Color.WHITE
	for entity in world.query.with_all([C_Visual, C_RoomMember]).enabled().execute():
		if entity.enabled and entity.get_component(C_Visual).asset_id == room_data.get("background", ""):
			light = entity.get_component(C_Visual).tint
			break
	var scene_state: Dictionary = {"background": room_data.get("background", ""), "light": light, "platforms": room_data.get("platforms", []).duplicate(true), "door_count": room_data.get("doors", []).size(), "transition_pending": session.loading if session != null else true}
	return {"scene_state": scene_state, "moonstep": progression.moonstep if progression != null else false, "visited_rooms": progression.visited_rooms.duplicate() if progression != null else [], "boss_defeated": progression.boss_defeated if progression != null else false, "ending_seen": progression.ending_seen if progression != null else false, "checkpoint": {"id": checkpoint.checkpoint_id, "room_id": checkpoint.room_id, "spawn_id": checkpoint.spawn_id, "valid": checkpoint.valid} if checkpoint != null else {}, "save_status": session.save_status if session != null else "none", "objective": session.objective if session != null else "", "room_epoch": room_epoch, "bosses": bosses, "interactions": interactions, "effects": effects, "mode": session.mode if session != null else "loading", "room_id": session.room_id if session != null else "", "room_name": room_data.get("name", ""), "loading": session.loading if session != null else true, "message": session.message if session != null else "", "tick": tick_index, "entity_count": world.entities.size() if is_instance_valid(world) else 0, "system_count": world.systems.size() if is_instance_valid(world) else 0, "groups": executed_groups.duplicate(), "pending_placements": _pending_placements.size(), "landing_count": landing_count, "camera_position": camera.position if is_instance_valid(camera) else Vector2.ZERO, "room_bounds": room_bounds, "player": get_player_snapshot(), "enemies": enemies, "projectiles": projectiles}

func placements_complete() -> bool:
	return _pending_placements.is_empty()

func announce_ready() -> void:
	if not _ready_emitted:
		_ready_emitted = true
		runtime_ready.emit()

# Bounded ordinary menu requests. These share the session queue used by UI controls.
func request_session_action(action: String) -> bool:
	if not action in ["new_run", "continue_run", "retry", "resume", "title", "pause", "map"]:
		return false
	_session_actions.append(action)
	return true

func start_new_run() -> bool:
	return request_session_action("new_run")

func continue_run() -> bool:
	return request_session_action("continue_run")

func retry() -> bool:
	return request_session_action("retry")

func take_session_actions() -> Array[String]:
	var actions: Array[String] = _session_actions
	_session_actions = []
	return actions

func clear_gameplay_input() -> void:
	_actions.clear()
	for system in world.systems:
		if system is InputSystem:
			system.clear_actions()
	for entity in world.query.with_all([C_Input]).enabled().execute():
		if not entity.enabled:
			continue
		var input: C_Input = entity.get_component(C_Input)
		input.axis = 0.0
		input.jump_pressed = false
		input.jump_held = false
		input.sword_pressed = false
		input.card_pressed = false
		input.dodge_pressed = false
		input.interact_pressed = false
		input.ui_actions.clear()
		var motion: C_Motion = entity.get_component(C_Motion)
		if motion != null:
			motion.buffer_left = 0.0
	for entity in world.query.with_all([C_Interaction]).enabled().execute():
		if not entity.enabled:
			continue
		entity.get_component(C_Interaction).selected = false
		var body: C_Body = entity.get_component(C_Body)
		if body != null and is_instance_valid(body.root):
			var prompt: Label = body.root.get_node_or_null("InteractionPrompt")
			if prompt != null:
				prompt.visible = false

func discard_transients() -> void:
	_spawns.clear()
	_projectile_contacts.clear()
	for entity in world.query.with_any([C_Projectile, C_Hitbox, C_Effect]).execute():
		request_removal(entity.id)

func _apply_room_transition() -> void:
	if session.mode != "transition" or session.transition.is_empty() or session.transition.get("applied", false):
		return
	var request: Dictionary = session.transition
	var next: Dictionary = rooms.load_room(request.room_id, resources)
	if next.is_empty() or not next.spawns.has(request.spawn_id):
		fail("Invalid room transition")
		return
	room_epoch += 1
	_spawns.clear()
	_removals.clear()
	_placements.clear()
	_pending_placements.clear()
	_projectile_contacts.clear()
	for entity in world.query.with_all([C_RoomMember]).execute():
		if not entity.get_component(C_RoomMember).persistent:
			world.remove_entity(entity)
	room_data = next
	var bounds: Array = next.bounds
	room_bounds = Rect2(bounds[0], bounds[1], bounds[2], bounds[3])
	session.room_id = next.id
	player.get_component(C_RoomMember).room_id = next.id
	factory.create_room(next)
	var spawn: Array = next.spawns[request.spawn_id]
	request_placement(player.id, Vector2(spawn[0], spawn[1]))
	player.get_component(C_Motion).placement_pending = true
	session.transition.applied = true

func can_continue() -> bool:
	return not save_repository.read_save(rooms, resources).is_empty()
