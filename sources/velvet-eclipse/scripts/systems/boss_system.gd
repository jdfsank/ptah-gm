class_name BossSystem extends System

@export var runtime: Node = null

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_Boss, C_Health, C_Transform]).enabled()

func process(entities: Array[Entity], _components: Array, delta: float) -> void:
	for entity in entities:
		if not entity.enabled:
			continue
		var boss: C_Boss = entity.get_component(C_Boss)
		var health: C_Health = entity.get_component(C_Health)
		var combat: C_Combat = entity.get_component(C_Combat)
		boss.arena_active = runtime.session.mode == "playing" and runtime.session.room_id == "house_throne" and entity.get_component(C_RoomMember).room_id == "house_throne" and not health.dead
		if not boss.arena_active:
			combat.requested_attack = ""
			continue
		var motion: C_Motion = entity.get_component(C_Motion)
		var player_position: Vector2 = runtime.player.get_component(C_Transform).position
		var position: Vector2 = entity.get_component(C_Transform).position
		motion.facing = -1 if player_position.x < position.x else 1
		if health.current <= health.maximum / 2 and not boss.phase_changed:
			boss.phase = 2
			boss.phase_changed = true
			boss.state = "phase_change"
			boss.time_left = 1.4
			combat.state = "idle"
			combat.requested_attack = ""
			runtime.discard_transients()
			runtime.session.message = "第二阶段 · 绯月狂宴"
			for background in runtime.world.query.with_all([C_Visual, C_RoomMember]).enabled().execute():
				if background.enabled and background.get_component(C_Visual).asset_id == "bg_throne":
					background.get_component(C_Visual).tint = Color(0.88, 0.38, 0.66, 1.0)
			_warning(entity, "phase_warning", position + Vector2(0, -145), Vector2(380, 290), 1.4)
			continue
		boss.time_left = maxf(0.0, boss.time_left - delta)
		if boss.time_left > 0.0:
			continue
		match boss.state:
			"idle", "recovery", "phase_change":
				if boss.phase == 2 and boss.attack_index % 3 == 2:
					_begin_slam(entity, player_position)
				elif boss.attack_index % 2 == 0:
					boss.state = "fan_warning"
					boss.time_left = 0.65 if boss.phase == 1 else 0.55
					_warning(entity, "fan_warning", position + Vector2(0, -100), Vector2(220, 140), boss.time_left + 0.35)
				else:
					_begin_slam(entity, player_position)
			"fan_warning":
				combat.requested_attack = "boss_fan"
				boss.state = "fan_attack"
				boss.time_left = 0.75
			"slam_warning":
				combat.requested_attack = "boss_slam"
				boss.state = "slam_attack"
				boss.time_left = 0.75
			"fan_attack":
				if boss.phase == 2:
					_begin_slam(entity, player_position)
				else:
					_recover(boss)
			"slam_attack":
				_recover(boss)

func _recover(boss: C_Boss) -> void:
	boss.state = "recovery"
	boss.time_left = 2.0 if boss.phase == 1 else 1.45
	boss.attack_index += 1

func _begin_slam(entity: Entity, target: Vector2) -> void:
	var boss: C_Boss = entity.get_component(C_Boss)
	boss.slam_center = Vector2(clampf(target.x, 120.0, 1480.0), 592.0)
	boss.state = "slam_warning"
	boss.time_left = 0.90 if boss.phase == 1 else 0.75
	_warning(entity, "slam_warning", boss.slam_center, Vector2(220, 56), boss.time_left + 0.35)
	runtime.request_spawn("effect", "house_throne", {"position": boss.slam_center + Vector2(0, -215), "kind": "ghost_hand", "duration": boss.time_left + 0.65, "size": Vector2(180, 240), "color": Color(0.8, 0.68, 1.0, 0.9), "owner_id": entity.id})

func _warning(entity: Entity, kind: String, position: Vector2, size: Vector2, duration: float) -> void:
	runtime.request_spawn("effect", "house_throne", {"position": position, "kind": kind, "duration": duration, "size": size, "color": Color(1.0, 0.48, 0.68, 1.0) if kind != "phase_warning" else Color(0.7, 0.4, 1.0, 1.0), "owner_id": entity.id})
