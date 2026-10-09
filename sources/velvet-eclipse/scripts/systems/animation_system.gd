class_name AnimationSystem extends System

@export var runtime: Node = null

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_Visual]).enabled()

func process(entities: Array[Entity], _components: Array, _delta: float) -> void:
	for entity in entities:
		if not entity.enabled:
			continue
		var visual: C_Visual = entity.get_component(C_Visual)
		if not is_instance_valid(visual.node):
			continue
		var motion: C_Motion = entity.get_component(C_Motion)
		var combat: C_Combat = entity.get_component(C_Combat)
		var health: C_Health = entity.get_component(C_Health)
		var boss: C_Boss = entity.get_component(C_Boss)
		var ai: C_EnemyAI = entity.get_component(C_EnemyAI)
		var heroine: bool = visual.asset_id == "heroine_frames"
		if motion != null:
			visual.facing = motion.facing
			visual.animation = "run" if absf(motion.velocity.x) > 8.0 else "idle"
			if heroine and not motion.grounded:
				visual.animation = "jump"
			elif not heroine and visual.animation == "run":
				visual.animation = "move"
		if combat != null:
			if combat.state.begins_with("sword"):
				visual.animation = "attack" if heroine else "melee_attack"
			elif combat.state.begins_with("cast"):
				visual.animation = "cast"
			elif combat.state == "dodge" and heroine:
				visual.animation = "dodge"
		if boss != null:
			visual.animation = "attack" if combat.state.begins_with("boss_") else "idle"
		if health != null and health.hurt_left > 0.0 and boss == null:
			visual.animation = "hurt" if heroine else "idle"
		if visual.node is AnimatedSprite2D:
			var sprite: AnimatedSprite2D = visual.node
			sprite.flip_h = visual.facing > 0 if boss != null else visual.facing < 0
			if heroine:
				visual.offset.y = -102.0 if visual.animation == "cast" else (-106.0 if visual.animation == "hurt" else -105.0)
			elif visual.asset_id == "dealer_frames":
				visual.offset.y = -88.0 if visual.animation == "melee_attack" else (-56.0 if visual.animation == "cast" else -54.0)
			elif boss != null:
				visual.offset.y = -186.0 if visual.animation == "attack" else -136.0
			sprite.offset = visual.offset
			if runtime.session.mode != "playing":
				sprite.pause()
			elif sprite.animation != visual.animation or (not sprite.is_playing() and (sprite.sprite_frames.get_animation_loop(visual.animation) or sprite.frame < sprite.sprite_frames.get_frame_count(visual.animation) - 1)):
				if not sprite.sprite_frames.has_animation(visual.animation):
					runtime.fail("Missing animation: " + visual.asset_id + "/" + visual.animation)
					continue
				sprite.play(visual.animation)
		elif visual.node is Sprite2D and ai != null and ai.kind == "flying":
			visual.node.flip_h = visual.facing < 0
			visual.node.rotation = clampf(motion.velocity.x / 900.0, -0.4, 0.4)
		if boss != null:
			var root: Node = visual.node.get_parent()
			var bar: ProgressBar = root.get_node_or_null("BossHealth")
			var title: Label = root.get_node_or_null("BossTitle")
			if bar != null:
				bar.max_value = health.maximum
				bar.value = health.current
			if title != null:
				title.text = "皇家庄家 · 第%d阶段   %d / %d" % [boss.phase, health.current, health.maximum]
		var tint: Color = visual.tint
		if health != null and health.hurt_left > 0.0:
			tint = tint.lerp(Color(1.5, 0.65, 0.75, tint.a), 0.7)
			if health.dead:
				tint.a *= health.hurt_left / 0.28
		elif combat != null and combat.dodge_invulnerable:
			tint = Color(0.75, 0.85, 1.3, 0.7)
		visual.node.modulate = tint
