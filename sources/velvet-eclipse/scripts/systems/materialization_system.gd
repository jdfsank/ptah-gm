class_name MaterializationSystem extends System

@export var runtime: Node = null
var materialization_count: int = 0

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_Transform, C_RoomMember]).with_any([C_Body, C_Visual]).enabled()

func process(entities: Array[Entity], _components: Array, _delta: float) -> void:
	if not runtime.in_safe_flush:
		runtime.schedule_flush()
		return
	if not is_instance_valid(runtime.camera):
		var camera := Camera2D.new()
		camera.name = "RoomCamera"
		camera.position_smoothing_enabled = false
		runtime.add_child(camera)
		runtime.camera = camera
	for entity in entities:
		if not entity.enabled:
			continue
		var body: C_Body = entity.get_component(C_Body)
		var visual: C_Visual = entity.get_component(C_Visual)
		if (body != null and body.ready and is_instance_valid(body.root)) or (body == null and visual != null and is_instance_valid(visual.node)):
			continue
		var resource: Resource = null
		if visual != null and visual.kind != "effect":
			resource = runtime.resources.resolve(visual.asset_id)
			if resource == null:
				runtime.fail(runtime.resources.last_error)
				continue
		var root: Node2D
		match body.kind if body != null else "none":
			"character":
				root = CharacterBody2D.new()
				root.floor_snap_length = 8.0
				root.safe_margin = 0.05
			"static":
				root = StaticBody2D.new()
			_:
				root = Node2D.new()
		root.name = "Body" if body != null and body.kind != "none" else "VisualRoot"
		root.visible = false
		if root is CollisionObject2D:
			root.collision_layer = 0
			root.collision_mask = 0
			var shape := CollisionShape2D.new()
			shape.name = "Collision"
			var rectangle := RectangleShape2D.new()
			rectangle.size = body.size
			shape.shape = rectangle
			shape.position = body.offset
			shape.disabled = true
			root.add_child(shape)
			body.shape = shape
		entity.add_child(root)
		if body != null:
			body.root = root
		if visual != null:
			if not _make_visual(root, visual, resource):
				root.queue_free()
				if body != null:
					body.root = null
				continue
		var interaction: C_Interaction = entity.get_component(C_Interaction)
		if interaction != null:
			var prompt := Label.new()
			prompt.name = "InteractionPrompt"
			prompt.text = "E · " + interaction.prompt
			prompt.add_theme_font_override("font", runtime.resources.resolve("ui_cjk_font"))
			prompt.add_theme_font_size_override("font_size", 23)
			prompt.add_theme_color_override("font_color", Color(1.0, 0.90, 0.57))
			prompt.add_theme_color_override("font_outline_color", Color(0.06, 0.02, 0.12))
			prompt.add_theme_constant_override("outline_size", 8)
			prompt.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
			prompt.position = Vector2(-280, -150)
			prompt.size = Vector2(560, 50)
			prompt.z_index = 40
			prompt.visible = false
			root.add_child(prompt)
		if entity.get_component(C_Boss) != null:
			var bar := ProgressBar.new()
			bar.name = "BossHealth"
			bar.position = Vector2(-240, -330)
			bar.size = Vector2(480, 18)
			bar.show_percentage = false
			bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
			root.add_child(bar)
			var title := Label.new()
			title.name = "BossTitle"
			title.position = Vector2(-260, -370)
			title.size = Vector2(520, 36)
			title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
			title.add_theme_font_override("font", runtime.resources.resolve("ui_cjk_font"))
			title.add_theme_font_size_override("font_size", 24)
			title.add_theme_constant_override("outline_size", 6)
			root.add_child(title)
		if body != null:
			body.ready = true
		materialization_count += 1

func _make_visual(root: Node2D, visual: C_Visual, resource: Resource) -> bool:
	var node: Node2D
	if visual.kind == "animated":
		if not resource is SpriteFrames:
			runtime.fail("Animated visual requires SpriteFrames: " + visual.asset_id)
			return false
		var sprite := AnimatedSprite2D.new()
		sprite.sprite_frames = resource
		sprite.scale = Vector2.ONE * (0.49 if visual.asset_id == "heroine_frames" else 1.0)
		sprite.offset = visual.offset
		if visual.asset_id == "dealer_frames" and visual.tint.a < 1.0:
			var equipment := Sprite2D.new()
			equipment.name = "SpectralCard"
			equipment.texture = runtime.resources.resolve("enemy_card")
			equipment.scale = Vector2(28, 42) / equipment.texture.get_size()
			equipment.position = Vector2(32, -64)
			equipment.modulate = Color(0.65, 0.9, 1.0)
			root.add_child(equipment)
		node = sprite
	elif visual.kind == "effect":
		var line := Line2D.new()
		line.width = 3.0
		line.antialiased = true
		var effect: C_Effect = root.get_parent().get_component(C_Effect)
		var points := PackedVector2Array()
		if effect.kind == "slash":
			for i in 17:
				var angle: float = lerpf(-1.35, 1.35, float(i) / 16.0)
				points.append(Vector2(cos(angle), sin(angle)) * effect.size * 0.5)
		elif effect.kind == "slam_warning":
			var half: Vector2 = effect.size * 0.5
			points = PackedVector2Array([Vector2(-half.x, -half.y), Vector2(half.x, -half.y), half, Vector2(-half.x, half.y), -half])
		elif effect.kind == "telegraph" or effect.kind.ends_with("warning"):
			for i in 25:
				var angle: float = TAU * float(i) / 24.0
				points.append(Vector2(cos(angle), sin(angle)) * effect.size * 0.5)
		else:
			for i in 17:
				var angle: float = TAU * float(i) / 16.0
				var radius: float = 0.5 if i % 2 == 0 else 0.18
				points.append(Vector2(cos(angle), sin(angle)) * effect.size * radius)
		if effect.kind.ends_with("warning"):
			var warning := Label.new()
			warning.name = "AttackWarning"
			warning.z_index = 40
			warning.text = "落掌 · 跃起或闪避" if effect.kind == "slam_warning" else ("卡牌扇 · 准备闪避" if effect.kind == "fan_warning" else "绯月狂宴 · 第二阶段")
			warning.position = Vector2(-190, -90)
			warning.size = Vector2(380, 40)
			warning.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
			warning.add_theme_font_override("font", runtime.resources.resolve("ui_cjk_font"))
			warning.add_theme_font_size_override("font_size", 24)
			warning.add_theme_constant_override("outline_size", 8)
			root.add_child(warning)
		line.points = points
		node = line
	elif visual.kind == "platform":
		var strip := Node2D.new()
		var count: int = int(visual.draw_size.x / 160.0)
		for index in count:
			var asset: String = "platform_left" if index == 0 else ("platform_right" if index == count - 1 else "platform_middle")
			var texture: Resource = runtime.resources.resolve(asset)
			if not texture is AtlasTexture:
				strip.free()
				runtime.fail("Platform requires AtlasTexture: " + asset)
				return false
			var segment := Sprite2D.new()
			segment.name = "Segment%02d" % index
			segment.texture = texture
			segment.centered = false
			segment.position = Vector2(index * 160, -6)
			strip.add_child(segment)
		node = strip
	else:
		if not resource is Texture2D:
			runtime.fail("Sprite visual requires Texture2D: " + visual.asset_id)
			return false
		var sprite := Sprite2D.new()
		sprite.texture = resource
		if visual.draw_size != Vector2.ZERO:
			sprite.scale = visual.draw_size / sprite.texture.get_size()
		sprite.position = visual.offset
		node = sprite
	node.name = "Visual"
	node.z_index = visual.z_index
	node.modulate = visual.tint
	root.add_child(node)
	visual.node = node
	return true
