extends GdUnitTestSuite

func test_all_r1_resources_match_actual_declared_types() -> void:
	var catalog := ResourceCatalog.new()
	for asset_id in ResourceCatalog.BINDINGS:
		var resource: Resource = catalog.resolve(asset_id)
		assert_that(resource).is_not_null()
		assert_bool(resource.is_class(ResourceCatalog.BINDINGS[asset_id][0])).is_true()
	assert_that(catalog.resolve("heroine_frames")).is_instanceof(SpriteFrames)
	assert_that(catalog.resolve("platform_middle")).is_instanceof(AtlasTexture)
	assert_that(catalog.resolve("ui_cjk_font")).is_instanceof(FontFile)

func test_unknown_asset_fails_without_invented_fallback_and_cache_reuses_resources() -> void:
	var catalog := ResourceCatalog.new()
	assert_that(catalog.resolve("not_a_real_asset")).is_null()
	assert_str(catalog.last_error).contains("Unknown required asset")
	assert_that(catalog.resolve("heroine_frames")).is_same(catalog.resolve("heroine_frames"))
