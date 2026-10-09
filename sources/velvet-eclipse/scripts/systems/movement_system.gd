class_name MovementSystem extends System

@export var runtime: Node = null
var _placements: Dictionary = {}
var _last_tick: int = -1
var _room_epoch: int = -1

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_Transform, C_RoomMember]).enabled()

func process(entities: Array[Entity], _components: Array, delta: float) -> void:
	if _room_epoch != runtime.room_epoch:
		_room_epoch = runtime.room_epoch
		_placements.clear()
	if _last_tick != runtime.tick_index:
		_last_tick = runtime.tick_index
		_placements.merge(runtime.take_placements(), true)
		for entity_id in _placements.keys():
			if not runtime.world.entity_id_registry.has(entity_id):
				_placements.erase(entity_id)
	for entity in entities:
		if not entity.enabled:
			continue
		var transform: C_Transform = entity.get_component(C_Transform)
		var body: C_Body = entity.get_component(C_Body)
		var motion: C_Motion = entity.get_component(C_Motion)
		var hitbox: C_Hitbox = entity.get_component(C_Hitbox)
		var visual: C_Visual = entity.get_component(C_Visual)
		var root: Node2D = body.root if body != null else (visual.node.get_parent() if visual != null and is_instance_valid(visual.node) else null)
		if body != null and (not body.ready or not is_instance_valid(root)):
			continue
		if body == null and visual != null and not is_instance_valid(root):
			continue
		var projectile: C_Projectile = entity.get_component(C_Projectile)
		if _placements.has(entity.id):
			var placement: Dictionary = _placements[entity.id]
			transform.position = placement.position
			transform.rotation = placement.rotation
			transform.scale = placement.scale
			if is_instance_valid(root):
				root.global_position = transform.position
				root.rotation = transform.rotation
				root.scale = transform.scale
				root.visible = true
				if root is CollisionObject2D:
					root.set_deferred("collision_layer", body.layer)
					root.set_deferred("collision_mask", body.mask)
				if body != null and is_instance_valid(body.shape):
					body.shape.set_deferred("disabled", false)
			if motion != null:
				motion.velocity = Vector2.ZERO
				motion.grounded = false
				motion.jumps_used = 0
				motion.coyote_left = 0.0
				motion.buffer_left = 0.0
				motion.placement_pending = false
			if projectile != null:
				projectile.previous_position = transform.position
			_placements.erase(entity.id)
			runtime.placement_completed(entity.id)
			continue
		if hitbox != null and hitbox.follows_owner:
			var owner: Entity = runtime.world.entity_id_registry.get(hitbox.owner_id)
			if is_instance_valid(owner):
				transform.position = owner.get_component(C_Transform).position + hitbox.offset
			continue
		if delta <= 0.0 or motion == null or motion.placement_pending or not root is CharacterBody2D:
			continue
		var character: CharacterBody2D = root
		if projectile != null:
			if projectile.consumed:
				continue
			projectile.previous_position = transform.position
			motion.velocity = projectile.direction.normalized() * projectile.speed
			character.velocity = motion.velocity
			var collision: KinematicCollision2D = character.move_and_collide(motion.velocity * delta)
			transform.position = character.global_position
			if collision != null:
				var collider_entity: Node = collision.get_collider().get_parent()
				runtime.record_projectile_contact(entity.id, collider_entity.id if collider_entity is GameEntity else "")
			elif not runtime.room_bounds.grow(80.0).has_point(transform.position):
				runtime.record_projectile_contact(entity.id)
			continue
		var input: C_Input = entity.get_component(C_Input)
		var health: C_Health = entity.get_component(C_Health)
		var combat: C_Combat = entity.get_component(C_Combat)
		var axis: float = input.axis if input != null else 0.0
		var controlled: bool = input != null and input.source == "player"
		if controlled:
			motion.desired_velocity.x = axis * motion.speed
		if health != null and (health.dead or health.hurt_left > 0.0):
			motion.desired_velocity = Vector2.ZERO
			axis = 0.0
		var dodging: bool = combat != null and combat.state == "dodge"
		if dodging:
			motion.velocity.x = motion.facing * 720.0
		else:
			if controlled:
				motion.velocity.x = clampf(motion.velocity.x, -motion.speed, motion.speed)
			motion.velocity.x = move_toward(motion.velocity.x, motion.desired_velocity.x, motion.acceleration * delta)
		if absf(axis) > 0.01 and (combat == null or combat.state == "idle"):
			motion.facing = 1 if axis > 0 else -1
		if motion.gravity == 0.0:
			motion.velocity.y = move_toward(motion.velocity.y, motion.desired_velocity.y, motion.acceleration * delta)
		else:
			motion.buffer_left = maxf(0.0, motion.buffer_left - delta)
			motion.coyote_left = motion.coyote_duration if motion.grounded else maxf(0.0, motion.coyote_left - delta)
			if input != null and input.jump_pressed and (health == null or not health.dead):
				motion.buffer_left = motion.buffer_duration
			motion.velocity.y = minf(motion.velocity.y + motion.gravity * delta, motion.max_fall_speed)
			var first_jump: bool = motion.grounded or (motion.coyote_left > 0.0 and motion.jumps_used == 0)
			var air_jump: bool = controlled and runtime.progression.moonstep and motion.jumps_used < 2
			if motion.buffer_left > 0.0 and (first_jump or air_jump):
				motion.velocity.y = -motion.jump_speed
				motion.buffer_left = 0.0
				motion.coyote_left = 0.0
				motion.jumps_used = 1 if first_jump else 2
				motion.grounded = false
		character.velocity = motion.velocity
		character.move_and_slide()
		motion.velocity = character.velocity
		var was_grounded: bool = motion.grounded
		motion.grounded = character.is_on_floor()
		if motion.grounded:
			motion.jumps_used = 0
			if not was_grounded and controlled:
				runtime.landing_count += 1
		var bounds: Rect2 = runtime.room_bounds
		var edge: float = maxf(body.size.x * 0.5, 64.0 if controlled else 24.0)
		var clamped_x: float = clampf(character.global_position.x, bounds.position.x + edge, bounds.end.x - edge)
		if clamped_x != character.global_position.x:
			character.global_position.x = clamped_x
			motion.velocity.x = 0.0
			character.velocity.x = 0.0
		transform.position = character.global_position
