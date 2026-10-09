class_name UISystem extends System

@export var runtime: Node = null

func setup() -> void:
	assert(is_instance_valid(runtime))

func query() -> QueryBuilder:
	return q.with_all([C_Session, C_UIState]).enabled()

func process(entities: Array[Entity], _components: Array, delta: float) -> void:
	for entity in entities:
		if not entity.enabled:
			continue
		var session: C_Session = entity.get_component(C_Session)
		var state: C_UIState = entity.get_component(C_UIState)
		state.visible_screen = session.mode
		state.snapshot = runtime.get_run_snapshot()
		state.prompt = ""
		for interaction in state.snapshot.interactions:
			if interaction.selected and interaction.available and session.mode == "playing":
				state.prompt = "E · " + interaction.prompt
		if state.notice != session.message:
			state.notice = session.message
			state.notice_left = 6.0
		elif session.mode == "playing":
			state.notice_left = maxf(0.0, state.notice_left - delta)
		if is_instance_valid(runtime.ui_root):
			runtime.ui_root.present(state.snapshot, state)
