class_name SaveSystem extends System

@export var runtime: Node = null

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_Session, C_Progression, C_Checkpoint]).enabled()

func process(entities: Array[Entity], _components: Array, _delta: float) -> void:
	for entity in entities:
		if not entity.enabled:
			continue
		var checkpoint: C_Checkpoint = entity.get_component(C_Checkpoint)
		var session: C_Session = entity.get_component(C_Session)
		var progression: C_Progression = entity.get_component(C_Progression)
		if not checkpoint.save_requested:
			if session.save_status == "pending" and runtime.save_repository.uses_browser_storage() and runtime.save_repository.last_read_acknowledged:
				session.save_status = "saved"
				session.message = "已读取本浏览器检查点"
			continue
		checkpoint.save_requested = false
		var payload: Dictionary = {"version": 1, "checkpoint_id": checkpoint.checkpoint_id, "room_id": checkpoint.room_id, "spawn_id": checkpoint.spawn_id, "moonstep": progression.moonstep, "visited_rooms": progression.visited_rooms.duplicate(), "boss_defeated": progression.boss_defeated, "ending_seen": progression.ending_seen}
		var valid: Dictionary = runtime.save_repository.validate(payload, runtime.rooms, runtime.resources)
		if valid.is_empty():
			session.save_status = "failed"
			session.message = runtime.save_repository.last_error
			continue
		checkpoint.payload = valid.duplicate(true)
		checkpoint.valid = true
		session.save_status = "pending"
		if not runtime.save_repository.write_save(valid, runtime.rooms, runtime.resources):
			session.save_status = "failed"
			session.message = runtime.save_repository.last_error + " · 本次可从检查点重试"
		elif runtime.save_repository.uses_browser_storage():
			session.save_status = "saved"
			session.message = "已存入本浏览器 · 请保留此站点数据"
		else:
			session.save_status = "saved"
			session.message = "绯月消散 · 赌城的诅咒已被斩断 · 进度已保存" if session.mode == "ending" else "存档成功"
