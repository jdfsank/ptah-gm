class_name InteractionSystem extends System

@export var runtime: Node = null
var _last_tick: int = -1

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_Interaction, C_Transform]).enabled()

func process(_entities: Array[Entity], _components: Array, _delta: float) -> void:
	if _last_tick == runtime.tick_index:
		return
	_last_tick = runtime.tick_index
	var interactions: Array = runtime.world.query.with_all([C_Interaction, C_Transform, C_RoomMember]).enabled().execute()
	var nearest: Entity = null
	var best_distance: float = INF
	var player: Entity = runtime.player
	var feet: Vector2 = player.get_component(C_Transform).position
	var motion: C_Motion = player.get_component(C_Motion)
	for entity in interactions:
		if not entity.enabled:
			continue
		var interaction: C_Interaction = entity.get_component(C_Interaction)
		interaction.selected = false
		interaction.requested = false
		if not interaction.available or runtime.session.mode != "playing" or not motion.grounded or motion.placement_pending:
			continue
		if entity.get_component(C_RoomMember).room_id != runtime.session.room_id:
			continue
		var position: Vector2 = entity.get_component(C_Transform).position
		var distance: float = feet.distance_to(position)
		# Feet-level and grounded checks prevent reaching a high door from a jump below it.
		if absf(feet.y - position.y) > 35.0 or distance > interaction.radius or distance >= best_distance:
			continue
		var ray := PhysicsRayQueryParameters2D.create(feet + Vector2(0, -48), position + Vector2(0, -48), 1)
		if not runtime.get_world_2d().direct_space_state.intersect_ray(ray).is_empty():
			continue
		nearest = entity
		best_distance = distance
	if nearest != null:
		var chosen: C_Interaction = nearest.get_component(C_Interaction)
		chosen.selected = true
		chosen.requested = player.get_component(C_Input).interact_pressed
	for entity in interactions:
		if not entity.enabled:
			continue
		var body: C_Body = entity.get_component(C_Body)
		if body != null and is_instance_valid(body.root):
			var prompt: Label = body.root.get_node_or_null("InteractionPrompt")
			if prompt != null:
				prompt.visible = entity.get_component(C_Interaction).selected
				if prompt.visible:
					var canvas: Transform2D = body.root.get_global_transform_with_canvas()
					var viewport_size: Vector2 = runtime.get_viewport_rect().size
					var desired: Vector2 = canvas * Vector2(-280, -150)
					var scaled_size: Vector2 = prompt.size * canvas.get_scale().abs()
					desired.x = clampf(desired.x, 20.0, maxf(20.0, viewport_size.x - scaled_size.x - 20.0))
					desired.y = clampf(desired.y, 160.0, maxf(160.0, viewport_size.y - scaled_size.y - 80.0))
					prompt.position = canvas.affine_inverse() * desired
