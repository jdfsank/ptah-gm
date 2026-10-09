class_name EffectSystem extends System

@export var runtime: Node = null

func setup() -> void:
	assert(is_instance_valid(runtime))

func sub_systems() -> Array[Array]:
	return [[q.with_all([C_Effect, C_Visual]).enabled(), _effects], [q.with_all([C_Projectile]).enabled(), _projectiles], [q.with_all([C_Hitbox]).enabled(), _hitboxes]]

func _effects(entities: Array[Entity], _components: Array, delta: float) -> void:
	for entity in entities:
		if not entity.enabled:
			continue
		var effect: C_Effect = entity.get_component(C_Effect)
		effect.remaining = maxf(0.0, effect.remaining - delta)
		var visual: C_Visual = entity.get_component(C_Visual)
		var ratio: float = effect.remaining / maxf(effect.duration, 0.001)
		visual.tint.a = effect.color.a * (1.0 if effect.kind.ends_with("warning") else ratio)
		if is_instance_valid(visual.node):
			if effect.kind == "ghost_hand":
				visual.node.position.y = lerpf(-25.0, 150.0, pow(1.0 - ratio, 4.0))
				visual.node.rotation = sin((1.0 - ratio) * PI) * 0.16
			elif not effect.kind.ends_with("warning"):
				visual.node.scale = Vector2.ONE * (1.0 + (1.0 - ratio) * 0.25)
		if effect.remaining <= 0.0:
			runtime.request_removal(entity.id)

func _projectiles(entities: Array[Entity], _components: Array, delta: float) -> void:
	for entity in entities:
		if not entity.enabled:
			continue
		var projectile: C_Projectile = entity.get_component(C_Projectile)
		projectile.remaining = maxf(0.0, projectile.remaining - delta)
		if projectile.consumed or projectile.remaining <= 0.0:
			runtime.request_removal(entity.id)

func _hitboxes(entities: Array[Entity], _components: Array, delta: float) -> void:
	for entity in entities:
		if not entity.enabled:
			continue
		var hitbox: C_Hitbox = entity.get_component(C_Hitbox)
		hitbox.active_left = maxf(0.0, hitbox.active_left - delta)
		if hitbox.active_left <= 0.0:
			runtime.request_removal(entity.id)
