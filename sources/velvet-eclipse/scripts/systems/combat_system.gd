class_name CombatSystem extends System

@export var runtime: Node = null

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_Combat, C_Input, C_Transform]).enabled()

func process(entities: Array[Entity], _components: Array, delta: float) -> void:
	for entity in entities:
		if not entity.enabled:
			continue
		var combat: C_Combat = entity.get_component(C_Combat)
		var input: C_Input = entity.get_component(C_Input)
		var health: C_Health = entity.get_component(C_Health)
		combat.sword_cooldown = maxf(0.0, combat.sword_cooldown - delta)
		combat.card_cooldown = maxf(0.0, combat.card_cooldown - delta)
		combat.dodge_cooldown = maxf(0.0, combat.dodge_cooldown - delta)
		combat.energy = clampf(combat.energy + combat.energy_regen * delta, 0.0, combat.max_energy)
		combat.dodge_invulnerable = false
		if health != null and (health.dead or (health.hurt_left > 0.0 and entity.get_component(C_Boss) == null)):
			combat.state = "idle"
			combat.time_left = 0.0
			combat.requested_attack = ""
			continue
		combat.time_left = maxf(0.0, combat.time_left - delta)
		if combat.state != "idle":
			if combat.state == "dodge":
				combat.dodge_invulnerable = combat.time_left > 0.04
			if combat.time_left <= 0.0:
				match combat.state:
					"boss_fan_windup", "boss_slam_windup":
						_boss_attack(entity, combat, combat.state == "boss_slam_windup")
						combat.state = "boss_recovery"
						combat.time_left = 0.35
					"sword_windup":
						_sword(entity, combat)
						combat.state = "sword_active"
						combat.time_left = 0.14
					"cast_windup":
						_card(entity)
						combat.state = "cast_recovery"
						combat.time_left = 0.24
					"sword_active":
						combat.state = "sword_recovery"
						combat.time_left = 0.16
					_:
						combat.state = "idle"
			continue
		var requested: String = combat.requested_attack
		combat.requested_attack = ""
		if requested in ["boss_fan", "boss_slam"] and entity.get_component(C_Boss) != null:
			combat.state = requested + "_windup"
			combat.time_left = 0.35
			combat.attack_serial += 1
		elif input.dodge_pressed and combat.dodge_cooldown <= 0.0 and input.source == "player":
			combat.state = "dodge"
			combat.time_left = 0.22
			combat.dodge_cooldown = 0.85
			combat.dodge_invulnerable = true
		elif (input.sword_pressed or requested == "sword") and combat.sword_cooldown <= 0.0:
			combat.state = "sword_windup"
			combat.time_left = 0.1
			combat.sword_cooldown = 0.42
			combat.attack_serial += 1
		elif (input.card_pressed or requested == "card") and combat.card_cooldown <= 0.0 and combat.energy >= combat.card_cost:
			combat.state = "cast_windup"
			combat.time_left = 0.12
			combat.card_cooldown = 0.46
			combat.energy -= combat.card_cost
			combat.attack_serial += 1

func _sword(entity: Entity, combat: C_Combat) -> void:
	var motion: C_Motion = entity.get_component(C_Motion)
	var health: C_Health = entity.get_component(C_Health)
	var ai: C_EnemyAI = entity.get_component(C_EnemyAI)
	var offset := Vector2(54 * motion.facing, -48)
	var size := Vector2(100, 76)
	if ai != null and ai.kind == "flying":
		offset = Vector2(24 * motion.facing, 0)
		size = Vector2(72, 70)
	var position: Vector2 = entity.get_component(C_Transform).position
	var room_id: String = entity.get_component(C_RoomMember).room_id
	runtime.request_spawn("hitbox", room_id, {"position": position + offset, "owner_id": entity.id, "team": health.team, "attack_serial": combat.attack_serial, "offset": offset, "size": size, "damage": 25 if health.team == "player" else 12, "active_left": 0.14})
	runtime.request_spawn("effect", room_id, {"kind": "slash", "position": position + offset, "size": size, "duration": 0.2, "color": Color(1, 0.8, 0.45) if health.team == "player" else Color(1, 0.25, 0.42), "owner_id": entity.id})

func _card(entity: Entity) -> void:
	var motion: C_Motion = entity.get_component(C_Motion)
	var health: C_Health = entity.get_component(C_Health)
	var position: Vector2 = entity.get_component(C_Transform).position + Vector2(30 * motion.facing, -48)
	runtime.request_spawn("projectile", entity.get_component(C_RoomMember).room_id, {"position": position, "owner_id": entity.id, "team": health.team, "direction": Vector2(motion.facing, 0), "speed": 660.0 if health.team == "player" else 320.0, "damage": 20 if health.team == "player" else 10})

func _boss_attack(entity: Entity, combat: C_Combat, slam: bool) -> void:
	var boss: C_Boss = entity.get_component(C_Boss)
	if not boss.arena_active or runtime.session.room_id != "house_throne" or runtime.session.mode != "playing":
		return
	if slam:
		runtime.request_spawn("hitbox", "house_throne", {"position": boss.slam_center, "owner_id": entity.id, "team": "enemy", "attack_serial": combat.attack_serial, "size": Vector2(220, 56), "damage": 22, "active_left": 0.18, "follows_owner": false})
		runtime.request_spawn("effect", "house_throne", {"position": boss.slam_center, "kind": "impact", "duration": 0.3, "size": Vector2(220, 56), "color": Color(1.0, 0.3, 0.65), "owner_id": entity.id})
	else:
		var motion: C_Motion = entity.get_component(C_Motion)
		var origin: Vector2 = entity.get_component(C_Transform).position + Vector2(85 * motion.facing, -65)
		var count: int = 3 if boss.phase == 1 else 5
		for index in count:
			var angle: float = (float(index) - float(count - 1) * 0.5) * 0.21
			var direction := Vector2(motion.facing, 0).rotated(angle)
			runtime.request_spawn("projectile", "house_throne", {"position": origin, "owner_id": entity.id, "team": "enemy", "direction": direction, "speed": 270.0 if boss.phase == 1 else 350.0, "damage": 12, "remaining": 4.5})
