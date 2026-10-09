class_name RoomCatalog extends RefCounted

const ROOM_PATHS: Dictionary = {
	"grand_lobby": "res://data/rooms/grand_lobby.json",
	"card_banquet_gallery": "res://data/rooms/card_banquet_gallery.json",
	"roulette_clocktower": "res://data/rooms/roulette_clocktower.json",
	"quiet_save_room": "res://data/rooms/quiet_save_room.json",
	"house_throne": "res://data/rooms/house_throne.json"
}
var last_error: String = ""

func load_room(room_id: String, resources: ResourceCatalog) -> Dictionary:
	if not ROOM_PATHS.has(room_id):
		last_error = "Unknown room: " + room_id
		return {}
	var parser := JSON.new()
	if parser.parse(FileAccess.get_file_as_string(ROOM_PATHS[room_id])) != OK:
		last_error = "Corrupt room JSON: " + room_id
		return {}
	var parsed: Variant = parser.data
	if not parsed is Dictionary or not validate_room(parsed, resources):
		if last_error.is_empty():
			last_error = "Room JSON is not an object: " + room_id
		return {}
	return parsed

func validate_room(room: Dictionary, resources: ResourceCatalog) -> bool:
	last_error = ""
	var version: Variant = room.get("version")
	if not (version is int or version is float) or version != 1 or not ROOM_PATHS.has(room.get("id", "")) or not room.get("name") is String or room.name.is_empty():
		return _reject("Invalid room identity/version")
	if not _vector(room.get("bounds"), 4) or room.bounds[2] <= 0 or room.bounds[3] <= 0:
		return _reject("Invalid room bounds")
	if not resources.has_asset(room.get("background", "")):
		return _reject("Unknown room background")
	if not _vector(room.get("light"), 4):
		return _reject("Invalid room light")
	for value in room.light:
		if value < 0 or value > 1:
			return _reject("Light outside 0..1")
	if not room.get("spawns") is Dictionary or not room.spawns.has("start"):
		return _reject("Missing start spawn")
	for value in room.spawns.values():
		if not _vector(value, 2):
			return _reject("Invalid spawn position")
	var ids: Dictionary = {}
	for collection in ["platforms", "props", "doors"]:
		if not room.get(collection) is Array:
			return _reject("Missing room array: " + collection)
		for record in room[collection]:
			if not record is Dictionary or not record.get("id") is String or record.id.is_empty() or ids.has(record.id):
				return _reject("Missing or duplicate room record id")
			ids[record.id] = true
			if collection == "platforms":
				if not _vector(record.get("rect"), 4) or record.rect[2] < 320 or int(record.rect[2]) % 160 != 0 or record.rect[3] <= 0:
					return _reject("Invalid platform rectangle or segment width")
			else:
				if not _vector(record.get("position"), 2):
					return _reject("Invalid object position")
				if collection == "props" and (not resources.has_asset(record.get("asset_id", "")) or not _vector(record.get("size"), 2) or record.size[0] <= 0 or record.size[1] <= 0):
					return _reject("Invalid prop asset or size")
				if collection == "doors" and (not record.get("target_room") is String or not record.get("target_spawn") is String or not record.get("prompt") is String or record.target_room.is_empty() or record.target_spawn.is_empty()):
					return _reject("Invalid door destination")
	for spawn in room.spawns.values():
		if not _safe_spawn(spawn, room):
			return _reject("Spawn has no safe standing surface")
	if not room.get("enemies", []) is Array:
		return _reject("Invalid enemy array")
	for enemy in room.get("enemies", []):
		if not enemy is Dictionary or not enemy.get("kind", "") in ["melee", "ranged", "flying"] or not _vector(enemy.get("position"), 2):
			return _reject("Invalid enemy record")
		if not enemy.get("id") is String or enemy.id.is_empty() or ids.has(enemy.id):
			return _reject("Missing or duplicate enemy id")
		ids[enemy.id] = true
	for kind in ["relic", "checkpoint", "boss"]:
		var record: Variant = room.get(kind)
		if record == null:
			continue
		if not record is Dictionary or not _vector(record.get("position"), 2) or not record.get("id") is String or record.id.is_empty() or ids.has(record.id):
			return _reject("Invalid interaction/boss record")
		ids[record.id] = true
		if kind != "boss" and not record.get("prompt") is String:
			return _reject("Missing interaction prompt")
		if kind == "relic" and (room.id != "roulette_clocktower" or record.id != "moonstep"):
			return _reject("Invalid relic location")
		if kind == "checkpoint" and (room.id != "quiet_save_room" or not room.spawns.has(record.get("spawn_id", ""))):
			return _reject("Invalid checkpoint spawn")
		if kind == "boss":
			if room.id != "house_throne" or record.id != "royal_dealer" or not _vector(record.get("arena"), 4):
				return _reject("Invalid boss arena")
			var area := Rect2(record.arena[0], record.arena[1], record.arena[2], record.arena[3])
			var bounds := Rect2(room.bounds[0], room.bounds[1], room.bounds[2], room.bounds[3])
			if not bounds.encloses(area) or not area.has_area():
				return _reject("Boss arena outside room")
	return true

func validate_graph(resources: ResourceCatalog) -> bool:
	var catalog: Dictionary = {}
	for room_id in ROOM_PATHS:
		var room: Dictionary = load_room(room_id, resources)
		if room.is_empty():
			return false
		catalog[room_id] = room
	for room in catalog.values():
		for door in room.doors:
			if not catalog.has(door.target_room) or not catalog[door.target_room].spawns.has(door.target_spawn):
				return _reject("Dangling door destination: " + room.id + "/" + door.id)
	var reached: Array[String] = ["grand_lobby"]
	var index: int = 0
	while index < reached.size():
		for door in catalog[reached[index]].doors:
			if not door.target_room in reached:
				reached.append(door.target_room)
		index += 1
	return true if reached.size() == ROOM_PATHS.size() else _reject("Disconnected room graph")

func _safe_spawn(value: Array, room: Dictionary) -> bool:
	var bounds := Rect2(room.bounds[0], room.bounds[1], room.bounds[2], room.bounds[3])
	var feet := Vector2(value[0], value[1])
	if not bounds.has_point(feet) or feet.y - 96 < bounds.position.y:
		return false
	var supported: bool = false
	var actor := Rect2(feet - Vector2(20, 96), Vector2(40, 95))
	for platform in room.platforms:
		var r: Array = platform.rect
		if absf(feet.y - r[1]) < 0.1 and feet.x - 24 >= r[0] and feet.x + 24 <= r[0] + r[2]:
			supported = true
		if actor.intersects(Rect2(r[0], r[1], r[2], r[3])):
			return false
	return supported

func _vector(value: Variant, count: int) -> bool:
	if not value is Array or value.size() != count:
		return false
	for part in value:
		if not (part is int or part is float) or not is_finite(float(part)):
			return false
	return true

func _reject(message: String) -> bool:
	last_error = message
	return false
