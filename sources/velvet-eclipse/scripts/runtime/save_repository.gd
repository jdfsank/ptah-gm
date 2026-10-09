class_name SaveRepository extends RefCounted

const VERSION: int = 1
const BROWSER_KEY: String = "velvet_eclipse_save_v1"
const MAX_SAVE_BYTES: int = 65536
var bridge_evaluator: Callable
var last_read_acknowledged: bool = false
var path: String = "user://velvet_eclipse_save.json"
var last_error: String = ""

func _init(save_path: String = "user://velvet_eclipse_save.json", evaluator: Callable = Callable()) -> void:
	path = save_path
	bridge_evaluator = evaluator

func validate(payload: Variant, rooms: RoomCatalog, resources: ResourceCatalog) -> Dictionary:
	last_error = ""
	if not payload is Dictionary:
		return _reject("存档格式无效")
	var version: Variant = payload.get("version")
	if not (version is int or version is float) or version != VERSION:
		return _reject("存档版本不受支持或文件已损坏")
	for key in ["checkpoint_id", "room_id", "spawn_id"]:
		if not payload.get(key) is String or payload[key].is_empty():
			return _reject("存档地点格式无效")
	for key in ["moonstep", "boss_defeated", "ending_seen"]:
		if not payload.get(key) is bool:
			return _reject("存档进度格式无效")
	if not payload.get("visited_rooms") is Array:
		return _reject("存档地图格式无效")
	var discovered: Array[String] = []
	for room_id in payload.visited_rooms:
		if not room_id is String or not rooms.ROOM_PATHS.has(room_id):
			return _reject("存档包含未知房间")
		if not room_id in discovered:
			discovered.append(room_id)
	var room: Dictionary = rooms.load_room(payload.room_id, resources)
	if room.is_empty() or not room.spawns.has(payload.spawn_id):
		return _reject("存档出生点无效")
	var initial: bool = payload.checkpoint_id == "start" and payload.room_id == "grand_lobby" and payload.spawn_id == "start"
	var shrine: Variant = room.get("checkpoint")
	if not initial and (not shrine is Dictionary or shrine.id != payload.checkpoint_id or shrine.spawn_id != payload.spawn_id):
		return _reject("存档检查点无效")
	if not payload.room_id in discovered or not "grand_lobby" in discovered:
		return _reject("存档地图缺少检查点")
	if payload.moonstep and not "roulette_clocktower" in discovered:
		return _reject("存档月步发现记录无效")
	if payload.boss_defeated and (not payload.moonstep or not "house_throne" in discovered):
		return _reject("存档胜利记录无效")
	if payload.ending_seen and not payload.boss_defeated:
		return _reject("存档结局状态无效")
	if payload.room_id == "quiet_save_room" and not payload.moonstep:
		return _reject("存档缺少月步能力")
	return {"version": VERSION, "checkpoint_id": payload.checkpoint_id, "room_id": payload.room_id, "spawn_id": payload.spawn_id, "moonstep": payload.moonstep, "visited_rooms": discovered, "boss_defeated": payload.boss_defeated, "ending_seen": payload.ending_seen}

func read_save(rooms: RoomCatalog, resources: ResourceCatalog) -> Dictionary:
	last_read_acknowledged = false
	if uses_browser_storage():
		var response: Dictionary = _browser_result(browser_script("read"))
		if response.is_empty():
			return {}
		var stored: Variant = response.get("value")
		if stored == null:
			return _reject("暂无存档")
		if not stored is String or stored.to_utf8_buffer().size() > MAX_SAVE_BYTES:
			return _reject("浏览器存档大小或格式无效")
		var payload: Dictionary = _decode(stored, rooms, resources)
		last_read_acknowledged = not payload.is_empty()
		return payload
	if not FileAccess.file_exists(path):
		return _reject("暂无存档")
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return _reject("无法读取存档")
	if file.get_length() > MAX_SAVE_BYTES:
		file.close()
		return _reject("存档大小无效")
	var text: String = file.get_as_text()
	file.close()
	return _decode(text, rooms, resources)

func write_save(payload: Dictionary, rooms: RoomCatalog, resources: ResourceCatalog) -> bool:
	var valid: Dictionary = validate(payload, rooms, resources)
	if valid.is_empty():
		return false
	if uses_browser_storage():
		var encoded: String = JSON.stringify(valid)
		if encoded.to_utf8_buffer().size() > MAX_SAVE_BYTES:
			last_error = "存档大小无效"
			return false
		var response: Dictionary = _browser_result(browser_script("write", encoded))
		if response.is_empty():
			return false
		if not response.get("value") is String or response.value != encoded:
			last_error = "浏览器存档写入校验失败"
			return false
		return true
	var temporary: String = path + ".tmp"
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		last_error = "无法写入存档：" + error_string(FileAccess.get_open_error())
		return false
	file.store_string(JSON.stringify(valid))
	file.flush()
	var error: Error = file.get_error()
	file.close()
	if error != OK:
		last_error = "写入存档失败：" + error_string(error)
		return false
	var rename_error: Error = DirAccess.rename_absolute(temporary, path)
	if rename_error != OK:
		last_error = "保存存档失败：" + error_string(rename_error)
		return false
	var readback: Dictionary = read_save(rooms, resources)
	if readback != valid:
		last_error = "存档写入校验失败"
		return false
	return true

func _reject(message: String) -> Dictionary:
	last_error = message
	return {}

func uses_browser_storage() -> bool:
	return OS.has_feature("web") or bridge_evaluator.is_valid()

func _decode(text: String, rooms: RoomCatalog, resources: ResourceCatalog) -> Dictionary:
	var parser := JSON.new()
	if parser.parse(text) != OK:
		return _reject("存档文件已损坏")
	return validate(parser.data, rooms, resources)

func browser_script(operation: String, encoded: String = "") -> String:
	# JSON.stringify encodes the JSON string again before embedding it in JS source.
	var body: String
	if operation == "read":
		body = "var value = storage.getItem(key); if (value !== null && value.length > 65536) { return JSON.stringify({ok:false,error:'size'}); } return JSON.stringify({ok:true,value:value});"
	elif operation == "write":
		body = "var value = %s; if (value.length > 65536) { return JSON.stringify({ok:false,error:'size'}); } storage.setItem(key, value); var readback = storage.getItem(key); if (readback !== value) { return JSON.stringify({ok:false,error:'readback'}); } return JSON.stringify({ok:true,value:readback});" % JSON.stringify(encoded)
	else:
		return "JSON.stringify({ok:false,error:'operation'})"
	return "(function(){ try { var storage = window.localStorage; var key = %s; %s } catch (error) { return JSON.stringify({ok:false,error:String(error && error.name || 'storage')}); } })()" % [JSON.stringify(BROWSER_KEY), body]

func _browser_result(script: String) -> Dictionary:
	var raw: Variant = bridge_evaluator.call(script) if bridge_evaluator.is_valid() else JavaScriptBridge.eval(script)
	if not raw is String or raw.to_utf8_buffer().size() > MAX_SAVE_BYTES * 3:
		return _reject("浏览器存储不可用或未确认")
	var parser := JSON.new()
	if parser.parse(raw) != OK or not parser.data is Dictionary or not parser.data.get("ok") is bool:
		return _reject("浏览器存储响应无效")
	var response: Dictionary = parser.data
	if not response.ok:
		return _reject("浏览器无法保存或读取进度（配额、权限或校验失败）")
	if not response.has("value"):
		return _reject("浏览器存储响应缺少数据")
	last_error = ""
	return response
