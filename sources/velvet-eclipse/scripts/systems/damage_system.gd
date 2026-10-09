class_name DamageSystem extends System

@export var runtime: Node = null
var _contact_tick: int = -1
var _contacts: Dictionary = {}

func setup() -> void:
	assert(is_instance_valid(runtime))

func sub_systems() -> Array[Array]:
	return [[q.with_all([C_Health, C_Transform, C_Body]).enabled(), _health], [q.with_all([C_Hitbox, C_Transform]).enabled(), _hitboxes], [q.with_all([C_Projectile, C_Transform, C_Body]).enabled(), _projectiles]]

func _health(entities: Array[Entity], _components: Array, delta: float) -> void:
	for entity in entities:
		if not entity.enabled:
			continue
		var health: C_Health = entity.get_component(C_Health)
		health.hurt_left = maxf(0.0, health.hurt_left - delta)
		health.invulnerable_left = maxf(0.0, health.invulnerable_left - delta)
		if health.heal_requested:
			health.current = health.maximum
			health.dead = false
			health.hurt_left = 0.0
			health.invulnerable_left = 0.0
			health.heal_requested = false
		if health.dead and health.hurt_left <= 0.0 and entity.id != runtime.session.player_id:
			runtime.request_removal(entity.id)

func _hitboxes(entities: Array[Entity], _components: Array, _delta: float) -> void:
	if runtime.session.mode != "playing":
		return
	var targets: Array = runtime.world.query.with_all([C_Health, C_Transform, C_Body, C_RoomMember]).enabled().execute()
	for entity in entities:
		if not entity.enabled:
			continue
		var hitbox: C_Hitbox = entity.get_component(C_Hitbox)
		if hitbox.active_left <= 0.0 or not _owner_can_hit(hitbox.owner_id):
			continue
		var position: Vector2 = entity.get_component(C_Transform).position
		var rectangle := Rect2(position - hitbox.size * 0.5, hitbox.size)
		for target in targets:
			if not _eligible(entity, target, hitbox.owner_id, hitbox.team) or target.id in hitbox.hit_ids:
				continue
			if rectangle.intersects(_body_rect(target)) and _apply_hit(target, hitbox.damage):
				hitbox.hit_ids.append(target.id)

func _projectiles(entities: Array[Entity], _components: Array, _delta: float) -> void:
	if runtime.session.mode != "playing":
		return
	if _contact_tick != runtime.tick_index:
		_contact_tick = runtime.tick_index
		_contacts = runtime.take_projectile_contacts()
	var targets: Array = runtime.world.query.with_all([C_Health, C_Transform, C_Body, C_RoomMember]).enabled().execute()
	for entity in entities:
		if not entity.enabled:
			continue
		var projectile: C_Projectile = entity.get_component(C_Projectile)
		var body: C_Body = entity.get_component(C_Body)
		var motion: C_Motion = entity.get_component(C_Motion)
		if projectile.consumed or not body.ready or motion.placement_pending:
			continue
		var end: Vector2 = entity.get_component(C_Transform).position
		var nearest: Entity = null
		var nearest_t: float = INF
		for target in targets:
			if not _eligible(entity, target, projectile.owner_id, projectile.team):
				continue
			var rect: Rect2 = _body_rect(target).grow_individual(body.size.x * 0.5 + 0.15, body.size.y * 0.5 + 0.15, body.size.x * 0.5 + 0.15, body.size.y * 0.5 + 0.15)
			var fraction: float = _sweep_fraction(projectile.previous_position, end, rect)
			if fraction >= 0.0 and fraction < nearest_t:
				nearest = target
				nearest_t = fraction
		if nearest == null and _contacts.has(entity.id):
			var contacted: Entity = runtime.world.entity_id_registry.get(_contacts[entity.id])
			if is_instance_valid(contacted) and contacted.get_component(C_Health) != null and _eligible(entity, contacted, projectile.owner_id, projectile.team):
				nearest = contacted
		if nearest != null:
			_apply_hit(nearest, projectile.damage)
			projectile.consumed = true
		elif _contacts.has(entity.id):
			projectile.consumed = true
		if projectile.consumed:
			runtime.request_spawn("effect", entity.get_component(C_RoomMember).room_id, {"position": end, "kind": "impact", "duration": 0.18, "color": Color(0.7, 0.8, 1.0), "size": Vector2(28, 28)})
			runtime.request_removal(entity.id)

func _eligible(source: Entity, target: Entity, owner_id: String, team: String) -> bool:
	if not target.enabled or target.id == owner_id:
		return false
	var health: C_Health = target.get_component(C_Health)
	var body: C_Body = target.get_component(C_Body)
	return not health.dead and health.team != team and body.ready and source.get_component(C_RoomMember).room_id == target.get_component(C_RoomMember).room_id

func _owner_can_hit(owner_id: String) -> bool:
	var owner: Entity = runtime.world.entity_id_registry.get(owner_id)
	if not is_instance_valid(owner) or not owner.enabled:
		return false
	var health: C_Health = owner.get_component(C_Health)
	return health == null or (not health.dead and (health.hurt_left <= 0.0 or owner.get_component(C_Boss) != null))

func _body_rect(entity: Entity) -> Rect2:
	var body: C_Body = entity.get_component(C_Body)
	return Rect2(entity.get_component(C_Transform).position + body.offset - body.size * 0.5, body.size)

func _apply_hit(target: Entity, amount: int) -> bool:
	var health: C_Health = target.get_component(C_Health)
	var combat: C_Combat = target.get_component(C_Combat)
	if health.dead or health.invulnerable_left > 0.0 or (combat != null and combat.dodge_invulnerable):
		return false
	health.current = maxi(0, health.current - maxi(amount, 0))
	health.hurt_left = 0.28
	health.invulnerable_left = 0.45 if health.team == "player" else 0.16
	health.dead = health.current <= 0
	var body: C_Body = target.get_component(C_Body)
	runtime.request_spawn("effect", target.get_component(C_RoomMember).room_id, {"position": target.get_component(C_Transform).position + body.offset, "kind": "defeat" if health.dead else "impact", "duration": 0.38 if health.dead else 0.2, "size": Vector2(86, 86) if health.dead else Vector2(36, 36), "color": Color(1, 0.73, 0.4) if health.dead else Color(1, 0.85, 0.8)})
	return true

func _sweep_fraction(start: Vector2, end: Vector2, rectangle: Rect2) -> float:
	var low: float = 0.0
	var high: float = 1.0
	var displacement: Vector2 = end - start
	for axis in 2:
		if absf(displacement[axis]) < 0.00001:
			if start[axis] < rectangle.position[axis] or start[axis] > rectangle.end[axis]:
				return -1.0
		else:
			var a: float = (rectangle.position[axis] - start[axis]) / displacement[axis]
			var b: float = (rectangle.end[axis] - start[axis]) / displacement[axis]
			low = maxf(low, minf(a, b))
			high = minf(high, maxf(a, b))
			if low > high:
				return -1.0
	return low
