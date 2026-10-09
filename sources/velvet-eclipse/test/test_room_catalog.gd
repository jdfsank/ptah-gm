extends GdUnitTestSuite

func test_lobby_geometry_and_local_schema_are_valid() -> void:
	var catalog := RoomCatalog.new()
	var room: Dictionary = catalog.load_room("grand_lobby", ResourceCatalog.new())
	assert_str(room.id).is_equal("grand_lobby")
	assert_float(room.bounds[2]).is_equal(2400.0)
	assert_float(room.platforms[0].rect[1] - room.platforms[1].rect[1]).is_equal(190.0)
	assert_array(room.enemies).has_size(3)

func test_invalid_vectors_ids_assets_and_platform_widths_are_rejected() -> void:
	var catalog := RoomCatalog.new()
	var resources := ResourceCatalog.new()
	var good: Dictionary = catalog.load_room("grand_lobby", resources)
	var duplicate: Dictionary = good.duplicate(true)
	duplicate.props.append(duplicate.props[0].duplicate(true))
	assert_bool(catalog.validate_room(duplicate, resources)).is_false()
	var bad_asset: Dictionary = good.duplicate(true)
	bad_asset.props[0].asset_id = "missing"
	assert_bool(catalog.validate_room(bad_asset, resources)).is_false()
	var bad_vector: Dictionary = good.duplicate(true)
	bad_vector.spawns.start = [INF, 0]
	assert_bool(catalog.validate_room(bad_vector, resources)).is_false()
	var bad_platform: Dictionary = good.duplicate(true)
	bad_platform.platforms[0].rect[2] = 401
	assert_bool(catalog.validate_room(bad_platform, resources)).is_false()

func test_wrong_version_and_record_types_are_clean_rejections() -> void:
	var catalog := RoomCatalog.new()
	var resources := ResourceCatalog.new()
	var good: Dictionary = catalog.load_room("grand_lobby", resources)
	for patch in [{"version": "1"}, {"version": true}, {"name": 23}, {"enemies": null}]:
		var bad: Dictionary = good.duplicate(true)
		bad.merge(patch, true)
		assert_bool(catalog.validate_room(bad, resources)).is_false()
	var bad_id: Dictionary = good.duplicate(true)
	bad_id.props[0].id = 9
	assert_bool(catalog.validate_room(bad_id, resources)).is_false()
	var unsafe_spawn: Dictionary = good.duplicate(true)
	unsafe_spawn.spawns.start = [1390, 500]
	assert_bool(catalog.validate_room(unsafe_spawn, resources)).is_false()
