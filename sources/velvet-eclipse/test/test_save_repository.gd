extends GdUnitTestSuite

var repository: SaveRepository
var rooms := RoomCatalog.new()
var resources := ResourceCatalog.new()

func before_test() -> void:
	repository = SaveRepository.new("user://m02_repository_fixture.json")
	DirAccess.remove_absolute(repository.path)

func after_test() -> void:
	DirAccess.remove_absolute(repository.path)
	DirAccess.remove_absolute(repository.path + ".tmp")

func _payload() -> Dictionary:
	return {"version": 1, "checkpoint_id": "quiet_shrine", "room_id": "quiet_save_room", "spawn_id": "shrine", "moonstep": true, "visited_rooms": ["grand_lobby", "card_banquet_gallery", "roulette_clocktower", "quiet_save_room"], "boss_defeated": false, "ending_seen": false}

func test_roundtrip_whitelists_fields_and_deduplicates_map() -> void:
	var payload: Dictionary = _payload()
	payload.visited_rooms.append("grand_lobby")
	payload["position"] = [999, 999]
	assert_bool(repository.write_save(payload, rooms, resources)).is_true()
	var restored: Dictionary = repository.read_save(rooms, resources)
	assert_int(restored.visited_rooms.size()).is_equal(4)
	assert_bool(restored.has("position")).is_false()
	assert_str(restored.spawn_id).is_equal("shrine")

func test_missing_corrupt_unknown_version_invalid_types_rooms_and_spawns_fail_closed() -> void:
	assert_dict(repository.read_save(rooms, resources)).is_empty()
	var file := FileAccess.open(repository.path, FileAccess.WRITE)
	file.store_string("{broken json")
	file.close()
	assert_dict(repository.read_save(rooms, resources)).is_empty()
	for patch in [{"version": 2}, {"version": "1"}, {"room_id": "outside"}, {"spawn_id": "missing"}, {"checkpoint_id": "to_throne"}, {"moonstep": 1}, {"moonstep": false}, {"visited_rooms": ["grand_lobby", "outside"]}, {"ending_seen": true}]:
		var payload: Dictionary = _payload()
		payload.merge(patch, true)
		assert_dict(repository.validate(payload, rooms, resources)).is_empty()
	assert_bool(SaveRepository.new("user://missing_directory/save.json").write_save(_payload(), rooms, resources)).is_false()

var bridge_response: Variant
var last_script: String = ""

func _bridge(script: String) -> Variant:
	last_script = script
	return bridge_response

func test_browser_string_status_write_read_and_validation() -> void:
	repository = SaveRepository.new("user://unused", _bridge)
	var encoded: String = JSON.stringify(_payload())
	bridge_response = JSON.stringify({"ok": true, "value": encoded})
	assert_bool(repository.write_save(_payload(), rooms, resources)).is_true()
	assert_str(last_script).contains("try { var storage = window.localStorage")
	assert_str(last_script).contains("storage.setItem(key, value)")
	assert_str(last_script).contains("readback !== value")
	assert_bool(last_script.contains("removeItem")).is_false()
	assert_bool(last_script.contains("FS.")).is_false()
	assert_dict(repository.read_save(rooms, resources)).is_equal(_payload())
	assert_bool(repository.last_read_acknowledged).is_true()
	bridge_response = JSON.stringify({"ok": true, "value": "{broken"})
	assert_dict(repository.read_save(rooms, resources)).is_empty()
	assert_bool(repository.last_read_acknowledged).is_false()

func test_browser_unavailable_malformed_quota_policy_and_readback_fail_closed() -> void:
	repository = SaveRepository.new("user://unused", _bridge)
	for response in [null, {}, "broken", "{}", '{"ok":"true"}', '{"ok":true}', '{"ok":false,"error":"QuotaExceededError"}', '{"ok":false,"error":"SecurityError"}', '{"ok":true,"value":"different"}']:
		bridge_response = response
		assert_bool(repository.write_save(_payload(), rooms, resources)).is_false()
		assert_str(repository.last_error).is_not_empty()
	bridge_response = JSON.stringify({"ok": true, "value": null})
	assert_dict(repository.read_save(rooms, resources)).is_empty()
	bridge_response = JSON.stringify({"ok": true, "value": "x".repeat(65537)})
	assert_dict(repository.read_save(rooms, resources)).is_empty()

func test_browser_embedded_content_is_json_encoded_and_only_one_stable_key() -> void:
	var content: String = "\";throw new Error('escape'); //\n中文"
	var script: String = repository.browser_script("write", content)
	assert_str(script).contains("var value = " + JSON.stringify(content) + ";")
	assert_str(script).contains(JSON.stringify(SaveRepository.BROWSER_KEY))
	assert_str(script).contains("return JSON.stringify")
	assert_bool(script.contains("OS.is_userfs_persistent")).is_false()
