class_name ProgressionSystem extends System

@export var runtime: Node = null

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_Session, C_Progression, C_Checkpoint]).enabled()

func process(entities: Array[Entity], _components: Array, _delta: float) -> void:
	for entity in entities:
		if not entity.enabled:
			continue
		var session: C_Session = entity.get_component(C_Session)
		var progress: C_Progression = entity.get_component(C_Progression)
		var checkpoint: C_Checkpoint = entity.get_component(C_Checkpoint)
		var actions: Array[String] = runtime.take_session_actions()
		for action in entity.get_component(C_Input).ui_actions:
			if not action in actions:
				actions.append(action)
		# Escape is mapped to both pause and ui_cancel; consume it once.
		if "pause" in actions and "ui_cancel" in actions:
			actions.erase("ui_cancel")
		for action in actions:
			match action:
				"new_run":
					_new_run(progress, checkpoint)
					return
				"continue_run":
					var payload: Dictionary = runtime.save_repository.read_save(runtime.rooms, runtime.resources)
					if payload.is_empty():
						session.save_status = "failed"
						session.message = runtime.save_repository.last_error + " · 可以开始新游戏"
					else:
						session.save_status = "pending" if OS.has_feature("web") else "saved"
						session.message = "已读取检查点"
						checkpoint.payload = payload
						checkpoint.restore_requested = true
				"retry":
					if session.mode == "dead":
						checkpoint.restore_requested = true
				"pause", "map":
					if session.mode == "playing":
						session.mode = "paused" if action == "pause" else "map"
						runtime.clear_gameplay_input()
					elif session.mode in ["paused", "map"]:
						session.mode = "playing"
						runtime.clear_gameplay_input()
				"resume", "ui_cancel":
					if session.mode in ["paused", "map"]:
						session.mode = "playing"
						runtime.clear_gameplay_input()
				"title":
					session.mode = "title"
					runtime.clear_gameplay_input()
		if checkpoint.restore_requested:
			checkpoint.restore_requested = false
			var payload: Dictionary = runtime.save_repository.validate(checkpoint.payload, runtime.rooms, runtime.resources)
			if payload.is_empty():
				session.save_status = "failed"
				session.message = runtime.save_repository.last_error + " · 可以开始新游戏"
				return
			progress.moonstep = payload.moonstep
			progress.visited_rooms.assign(payload.visited_rooms)
			progress.boss_defeated = payload.boss_defeated
			progress.ending_seen = payload.ending_seen
			checkpoint.checkpoint_id = payload.checkpoint_id
			checkpoint.room_id = payload.room_id
			checkpoint.spawn_id = payload.spawn_id
			checkpoint.valid = true
			runtime.player.get_component(C_Health).heal_requested = true
			_reset_combat()
			_transition(payload.room_id, payload.spawn_id, "restore")
			return
		if session.mode == "transition":
			if session.transition.get("applied", false) and runtime.placements_complete():
				session.loading = false
				session.mode = "ending" if progress.ending_seen else "playing"
				session.transition.clear()
				if not session.room_id in progress.visited_rooms:
					progress.visited_rooms.append(session.room_id)
				_objective(progress)
				runtime.announce_ready()
			return
		if session.mode != "playing":
			return
		if runtime.player.get_component(C_Health).dead:
			session.mode = "dead"
			session.message = "命运尚未终结 · 返回检查点再战"
			runtime.clear_gameplay_input()
			runtime.discard_transients()
			_reset_combat()
			return
		for boss in runtime.world.query.with_all([C_Boss, C_Health]).enabled().execute():
			if boss.enabled and boss.get_component(C_Health).dead and session.room_id == "house_throne":
				progress.boss_defeated = true
				progress.ending_seen = true
				session.mode = "ending"
				session.message = "绯月消散 · 赌城的诅咒已被斩断"
				runtime.clear_gameplay_input()
				runtime.discard_transients()
				_reset_combat()
				checkpoint.save_requested = true
				return
		for target in runtime.world.query.with_all([C_Interaction, C_RoomMember]).enabled().execute():
			if not target.enabled or target.get_component(C_RoomMember).room_id != session.room_id:
				continue
			var interaction: C_Interaction = target.get_component(C_Interaction)
			if not interaction.available or not interaction.requested:
				continue
			interaction.requested = false
			match interaction.kind:
				"door":
					_transition(interaction.target_room, interaction.target_spawn, "door")
				"relic":
					if not progress.moonstep:
						progress.moonstep = true
						interaction.available = false
						runtime.request_removal(target.id)
						session.message = "获得月步！空中再按 Space/W 二段跳 · 返回大厅上层"
						_objective(progress)
				"checkpoint":
					checkpoint.checkpoint_id = interaction.interaction_id
					checkpoint.room_id = session.room_id
					checkpoint.spawn_id = interaction.target_spawn
					checkpoint.save_requested = true
					runtime.player.get_component(C_Health).heal_requested = true
			return

func _new_run(progress: C_Progression, checkpoint: C_Checkpoint) -> void:
	progress.moonstep = false
	progress.visited_rooms.assign(["grand_lobby"])
	progress.boss_defeated = false
	progress.ending_seen = false
	checkpoint.checkpoint_id = "start"
	checkpoint.room_id = "grand_lobby"
	checkpoint.spawn_id = "start"
	checkpoint.valid = true
	checkpoint.restore_requested = false
	checkpoint.save_requested = false
	checkpoint.payload = {"version": 1, "checkpoint_id": "start", "room_id": "grand_lobby", "spawn_id": "start", "moonstep": false, "visited_rooms": ["grand_lobby"], "boss_defeated": false, "ending_seen": false}
	runtime.session.save_status = "none"
	runtime.session.message = "前往轮盘钟楼寻找月步"
	runtime.player.get_component(C_Health).heal_requested = true
	_reset_combat()
	_transition("grand_lobby", "start", "new_run")

func _transition(room_id: String, spawn_id: String, reason: String) -> void:
	var room: Dictionary = runtime.rooms.load_room(room_id, runtime.resources)
	if room.is_empty() or not room.spawns.has(spawn_id):
		runtime.session.message = "无法前往未知地点"
		return
	runtime.session.mode = "transition"
	runtime.session.loading = true
	runtime.session.transition = {"room_id": room_id, "spawn_id": spawn_id, "reason": reason, "applied": false}
	runtime.clear_gameplay_input()
	_reset_combat()
	runtime.schedule_flush()

func _reset_combat() -> void:
	for actor in runtime.world.query.with_all([C_Combat]).enabled().execute():
		if not actor.enabled:
			continue
		var combat: C_Combat = actor.get_component(C_Combat)
		combat.state = "idle"
		combat.time_left = 0.0
		combat.requested_attack = ""
		combat.dodge_invulnerable = false
		combat.sword_cooldown = 0.0
		combat.card_cooldown = 0.0
		combat.dodge_cooldown = 0.0
		combat.energy = combat.max_energy
		var boss: C_Boss = actor.get_component(C_Boss)
		if boss != null:
			boss.arena_active = false
			boss.state = "idle"
			boss.time_left = 1.2

func _objective(progress: C_Progression) -> void:
	runtime.session.objective = "前往轮盘钟楼寻找月步" if not progress.moonstep else "用二段跳登上大厅高台，前往庄家王座"
	if runtime.session.room_id == "quiet_save_room":
		runtime.session.objective = "在神龛恢复生命并存档，再进入王座"
	elif runtime.session.room_id == "house_throne":
		runtime.session.objective = "看清预警，闪避卡牌与落掌，击败皇家庄家"
