class_name EnemyAISystem extends System

@export var runtime: Node = null

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_EnemyAI, C_Transform, C_Health]).enabled()

func process(entities: Array[Entity], _components: Array, delta: float) -> void:
	for entity in entities:
		if not entity.enabled:
			continue
		var ai: C_EnemyAI = entity.get_component(C_EnemyAI)
		var health: C_Health = entity.get_component(C_Health)
		var input: C_Input = entity.get_component(C_Input)
		var motion: C_Motion = entity.get_component(C_Motion)
		input.sword_pressed = false
		input.card_pressed = false
		input.axis = 0.0
		motion.desired_velocity = Vector2.ZERO
		if health.dead or health.hurt_left > 0.0 or motion.placement_pending:
			continue
		var target: Entity = runtime.world.entity_id_registry.get(ai.target_id)
		if not is_instance_valid(target) or not target.enabled or target.get_component(C_Health).dead:
			continue
		if target.get_component(C_RoomMember).room_id != entity.get_component(C_RoomMember).room_id:
			continue
		ai.time_left = maxf(0.0, ai.time_left - delta)
		var position: Vector2 = entity.get_component(C_Transform).position
		var target_position: Vector2 = target.get_component(C_Transform).position
		var offset: Vector2 = target_position - position
		if ai.kind == "flying":
			offset.y -= 48.0
		if ai.state in ["spawning", "recover"]:
			if ai.time_left <= 0.0:
				ai.state = "idle"
			continue
		if ai.state == "telegraph":
			if ai.time_left <= 0.0:
				if ai.kind == "ranged":
					input.card_pressed = true
				else:
					input.sword_pressed = true
				ai.state = "lunge" if ai.kind == "flying" else "recover"
				ai.time_left = 0.32 if ai.kind == "flying" else 1.05
			continue
		if ai.state == "lunge":
			motion.desired_velocity = Vector2(motion.facing * 360.0, 0.0)
			if ai.time_left <= 0.0:
				ai.state = "recover"
				ai.time_left = 0.9
			continue
		if offset.length() > ai.aggro_range:
			ai.state = "idle"
			continue
		input.axis = signf(offset.x)
		if ai.kind == "ranged" and absf(offset.x) < 220.0:
			ai.state = "retreat"
			motion.desired_velocity.x = -signf(offset.x) * motion.speed
			continue
		var in_range: bool = absf(offset.x) <= ai.attack_range and absf(offset.y) < 75.0
		if in_range:
			ai.state = "telegraph"
			ai.time_left = 0.65 if ai.kind == "ranged" else 0.5
			runtime.request_spawn("effect", entity.get_component(C_RoomMember).room_id, {"kind": "telegraph", "position": position + Vector2(0, -55), "size": Vector2(85, 100), "color": Color(1, 0.35, 0.48, 0.85), "duration": ai.time_left, "owner_id": entity.id})
		else:
			ai.state = "approach"
			motion.desired_velocity = offset.normalized() * motion.speed if ai.kind == "flying" else Vector2(signf(offset.x) * motion.speed, 0)
