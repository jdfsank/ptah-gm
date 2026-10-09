class_name EntityFactory extends RefCounted

var runtime: Node

func _init(host: Node = null) -> void:
	runtime = host

func register(entity_id: String, entity_name: String, components: Array, placement: Variant = null) -> GameEntity:
	var entity := GameEntity.new()
	entity.id = entity_id
	entity.name = entity_name
	runtime.world.add_entity(entity, components)
	if placement is Vector2:
		runtime.request_placement(entity_id, placement)
	return entity

func create_session() -> GameEntity:
	var session := C_Session.new()
	session.mode = "transition"
	session.loading = true
	session.objective = "探索大厅"
	var input := C_Input.new()
	input.source = "ui"
	return register("session", "Session", [session, input, C_Progression.new(), C_Checkpoint.new()])

func create_player(position: Vector2) -> GameEntity:
	var body := C_Body.new()
	body.kind = "character"
	body.layer = 2
	body.mask = 1
	var visual := C_Visual.new()
	visual.asset_id = "heroine_frames"
	visual.kind = "animated"
	visual.draw_size = Vector2(100, 100)
	visual.offset = Vector2(0, -105)
	visual.z_index = 20
	var member := C_RoomMember.new()
	member.persistent = true
	return register("player", "Player", [C_Transform.new(), C_Motion.new(), body, visual, C_Input.new(), member, C_CameraTarget.new(), C_Health.new(), C_Combat.new()], position)

func create_platform(room_id: String, record: Dictionary) -> GameEntity:
	var rect: Array = record.rect
	var body := C_Body.new()
	body.kind = "static"
	body.size = Vector2(rect[2], rect[3])
	body.offset = body.size / 2.0
	body.layer = 1
	body.mask = 0
	var visual := C_Visual.new()
	visual.kind = "platform"
	visual.asset_id = "platform_middle"
	visual.draw_size = body.size
	visual.z_index = 10
	var member := C_RoomMember.new()
	member.room_id = room_id
	return register(room_id + ":" + record.id, record.id, [C_Transform.new(), body, visual, member], Vector2(rect[0], rect[1]))

func create_prop(room_id: String, record: Dictionary) -> GameEntity:
	var visual := C_Visual.new()
	visual.asset_id = record.asset_id
	visual.draw_size = Vector2(record.size[0], record.size[1])
	visual.z_index = int(record.get("z", 0))
	var member := C_RoomMember.new()
	member.room_id = room_id
	return register(room_id + ":" + record.id, record.id, [C_Transform.new(), C_Body.new(), visual, member], Vector2(record.position[0], record.position[1]))

func create_room(room: Dictionary) -> void:
	var bounds: Array = room.bounds
	if float(bounds[3]) > 720.0:
		# Tall rooms use one aspect-preserving plate; the illustrated art is not tileable.
		var texture: Texture2D = runtime.resources.resolve(room.background)
		var factor: float = maxf(float(bounds[2]) / texture.get_width(), float(bounds[3]) / texture.get_height())
		var dimensions: Vector2 = texture.get_size() * factor
		var background := create_prop(room.id, {"id": "background_0_0", "asset_id": room.background, "position": [bounds[0] + bounds[2] / 2.0, bounds[1] + bounds[3] / 2.0], "size": [dimensions.x, dimensions.y], "z": -100})
		background.get_component(C_Visual).tint = Color(room.light[0], room.light[1], room.light[2], room.light[3])
	else:
		var plate_count: int = ceili(float(bounds[2]) / 1280.0)
		for i in plate_count:
			var background := create_prop(room.id, {"id": "background_%d_0" % i, "asset_id": room.background, "position": [bounds[0] + 640 + i * 1280, bounds[1] + 360], "size": [1280, 720], "z": -100})
			background.get_component(C_Visual).tint = Color(room.light[0], room.light[1], room.light[2], room.light[3])
	for record in room.platforms:
		create_platform(room.id, record)
	for record in room.props:
		create_prop(room.id, record)
	for record in room.get("enemies", []):
		create_enemy(room.id, record)
	for record in room.doors:
		create_interaction(room.id, record, "door")
	if room.get("relic") != null and not runtime.progression.moonstep:
		create_interaction(room.id, room.relic, "relic")
	if room.get("checkpoint") != null:
		create_interaction(room.id, room.checkpoint, "checkpoint")
	if room.get("boss") != null and not runtime.progression.boss_defeated:
		create_boss(room.id, room.boss)

func create_interaction(room_id: String, record: Dictionary, kind: String) -> GameEntity:
	var visual := C_Visual.new()
	visual.asset_id = "arch" if kind == "door" else ("moonstep" if kind == "relic" else "shrine")
	visual.draw_size = Vector2(240, 360) if kind == "door" else (Vector2(48, 48) if kind == "relic" else Vector2(180, 180))
	visual.offset.y = -visual.draw_size.y * 0.5
	visual.z_index = -4 if kind == "door" else 12
	var interaction := C_Interaction.new()
	interaction.kind = kind
	interaction.interaction_id = record.id
	interaction.prompt = record.prompt
	interaction.target_room = record.get("target_room", "")
	interaction.target_spawn = record.get("target_spawn", record.get("spawn_id", ""))
	var member := C_RoomMember.new()
	member.room_id = room_id
	return register(room_id + ":" + record.id, record.id, [C_Transform.new(), C_Body.new(), visual, member, interaction], Vector2(record.position[0], record.position[1]))

func create_boss(room_id: String, record: Dictionary) -> GameEntity:
	var body := C_Body.new()
	body.kind = "character"
	body.layer = 4
	body.mask = 1
	body.size = Vector2(134, 250)
	body.offset = Vector2(0, -125)
	var visual := C_Visual.new()
	visual.kind = "animated"
	visual.asset_id = "boss_frames"
	visual.offset = Vector2(0, -136)
	visual.draw_size = Vector2(270, 270)
	visual.z_index = 19
	var health := C_Health.new()
	health.team = "enemy"
	health.maximum = 1400
	health.current = 1400
	var input := C_Input.new()
	input.source = "ai"
	var motion := C_Motion.new()
	motion.speed = 0.0
	motion.facing = -1
	var member := C_RoomMember.new()
	member.room_id = room_id
	return register(room_id + ":" + record.id, record.id, [C_Transform.new(), body, visual, health, input, motion, member, C_Combat.new(), C_Boss.new()], Vector2(record.position[0], record.position[1]))

func create_enemy(room_id: String, record: Dictionary) -> GameEntity:
	var body := C_Body.new()
	body.kind = "character"
	body.layer = 4
	body.mask = 1
	body.size = Vector2(42, 100)
	body.offset = Vector2(0, -50)
	var visual := C_Visual.new()
	visual.asset_id = "dealer_frames"
	visual.kind = "animated"
	visual.offset = Vector2(0, -54)
	visual.draw_size = Vector2(110, 110)
	visual.z_index = 19
	var motion := C_Motion.new()
	motion.speed = 105.0
	var ai := C_EnemyAI.new()
	ai.kind = record.kind
	ai.home = Vector2(record.position[0], record.position[1])
	ai.patrol_radius = float(record.get("patrol_radius", 150.0))
	ai.aggro_range = 430.0
	ai.state = "spawning"
	ai.time_left = 1.0
	var health := C_Health.new()
	health.team = "enemy"
	health.maximum = 60
	health.current = 60
	var input := C_Input.new()
	input.source = "ai"
	var member := C_RoomMember.new()
	member.room_id = room_id
	if ai.kind == "ranged":
		ai.attack_range = 380.0
		motion.speed = 90.0
		visual.tint = Color(0.5, 0.88, 1.0, 0.82)
	elif ai.kind == "flying":
		ai.attack_range = 190.0
		motion.gravity = 0.0
		motion.speed = 125.0
		visual.asset_id = "enemy_card"
		visual.kind = "sprite"
		visual.draw_size = Vector2(46, 68)
		visual.offset = Vector2.ZERO
		body.size = Vector2(40, 60)
		body.offset = Vector2.ZERO
	return register(room_id + ":" + record.id, record.id, [C_Transform.new(), motion, body, visual, input, member, health, C_Combat.new(), ai], ai.home)

func create_transient(archetype: String, room_id: String, fields: Dictionary) -> GameEntity:
	var member := C_RoomMember.new()
	member.room_id = room_id
	var components: Array = [C_Transform.new(), member]
	if archetype == "projectile":
		var projectile := C_Projectile.new()
		projectile.owner_id = fields.owner_id
		projectile.team = fields.team
		projectile.direction = fields.direction
		projectile.speed = fields.get("speed", 660.0)
		projectile.damage = fields.get("damage", 20)
		projectile.remaining = fields.get("remaining", 2.0)
		var motion := C_Motion.new()
		motion.gravity = 0.0
		var body := C_Body.new()
		body.kind = "character"
		body.size = Vector2(18, 28)
		body.offset = Vector2.ZERO
		body.layer = 8 if projectile.team == "player" else 16
		body.mask = 1 | (4 if projectile.team == "player" else 2)
		var visual := C_Visual.new()
		visual.asset_id = "player_card" if projectile.team == "player" else "enemy_card"
		visual.draw_size = Vector2(24, 36) if projectile.team == "player" else Vector2(28, 42)
		visual.z_index = 25
		components.append_array([projectile, motion, body, visual])
	elif archetype == "hitbox":
		var hitbox := C_Hitbox.new()
		hitbox.owner_id = fields.owner_id
		hitbox.team = fields.team
		hitbox.attack_serial = fields.attack_serial
		hitbox.offset = fields.get("offset", hitbox.offset)
		hitbox.size = fields.get("size", hitbox.size)
		hitbox.damage = fields.get("damage", hitbox.damage)
		hitbox.active_left = fields.get("active_left", hitbox.active_left)
		hitbox.follows_owner = fields.get("follows_owner", true)
		components.append(hitbox)
	elif archetype == "effect":
		var effect := C_Effect.new()
		effect.kind = fields.get("kind", "impact")
		effect.duration = fields.get("duration", 0.25)
		effect.remaining = effect.duration
		effect.size = fields.get("size", Vector2(32, 32))
		effect.color = fields.get("color", Color.WHITE)
		effect.owner_id = fields.get("owner_id", "")
		var visual := C_Visual.new()
		visual.kind = "sprite" if effect.kind == "ghost_hand" else "effect"
		visual.asset_id = "ghost_hand" if effect.kind == "ghost_hand" else ""
		visual.draw_size = effect.size
		visual.tint = effect.color
		visual.z_index = 30
		components.append_array([effect, visual])
	else:
		runtime.fail("Unknown transient archetype: " + archetype)
		return null
	return register(fields.id, fields.id, components, fields.position)
