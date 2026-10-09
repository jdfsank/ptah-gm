extends RefCounted
class_name StudioRuntime

## Protected bridge from game code to the server-owned object document.
## Generated game scripts should read declared values through this API.

static func value(document: Dictionary, object_id: String, field_id: String, default_value: Variant = null) -> Variant:
	for object_value in document.get("objects", []):
		if not object_value is Dictionary or object_value.get("id") != object_id:
			continue
		for field_value in object_value.get("fields", []):
			if field_value is Dictionary and field_value.get("id") == field_id:
				return field_value.get("value", default_value)
	return default_value


func object_value(object_id: String, field_id: String, default_value: Variant = null) -> Variant:
	var file := FileAccess.open("res://design/game.json", FileAccess.READ)
	if file == null:
		return default_value
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		return default_value
	return value(parsed, object_id, field_id, default_value)
