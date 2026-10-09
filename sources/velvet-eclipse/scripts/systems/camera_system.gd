class_name CameraSystem extends System

@export var runtime: Node = null
var _positioned: bool = false

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_CameraTarget, C_Transform]).enabled()

func process(entities: Array[Entity], _components: Array, delta: float) -> void:
	if not is_instance_valid(runtime.camera):
		return
	for entity in entities:
		if not entity.enabled:
			continue
		var target: C_CameraTarget = entity.get_component(C_CameraTarget)
		if not target.enabled:
			continue
		var body: C_Body = entity.get_component(C_Body)
		var motion: C_Motion = entity.get_component(C_Motion)
		if body == null or not body.ready or (motion != null and motion.placement_pending):
			continue
		var transform: C_Transform = entity.get_component(C_Transform)
		var bounds: Rect2 = runtime.room_bounds
		var half: Vector2 = Vector2(640, 360)
		var desired: Vector2 = transform.position + target.offset
		desired.x = clampf(desired.x, bounds.position.x + half.x, maxf(bounds.position.x + half.x, bounds.end.x - half.x))
		desired.y = clampf(desired.y, bounds.position.y + half.y, maxf(bounds.position.y + half.y, bounds.end.y - half.y))
		var camera: Camera2D = runtime.camera
		camera.limit_left = int(bounds.position.x)
		camera.limit_top = int(bounds.position.y)
		camera.limit_right = int(bounds.end.x)
		camera.limit_bottom = int(bounds.end.y)
		camera.position = desired if not _positioned else camera.position.lerp(desired, 1.0 - exp(-target.smoothing * delta))
		camera.position.x = clampf(camera.position.x, bounds.position.x + half.x, maxf(bounds.position.x + half.x, bounds.end.x - half.x))
		camera.position.y = clampf(camera.position.y, bounds.position.y + half.y, maxf(bounds.position.y + half.y, bounds.end.y - half.y))
		camera.reset_smoothing()
		_positioned = true
