class_name ResourceCatalog extends RefCounted

const BINDINGS: Dictionary = {
	"bg_throne": ["Texture2D", "res://assets/generated/background-map/bg_throne/bg_throne.png"],
	"bg_tower": ["Texture2D", "res://assets/generated/background-map/bg_tower/bg_tower.png"],
	"roulette": ["AtlasTexture", "res://assets/generated/scene-prop-set/casino_props/roulette.tres"],
	"shrine": ["AtlasTexture", "res://assets/generated/scene-prop-set/casino_props/shrine.tres"],
	"moonstep": ["AtlasTexture", "res://assets/generated/compact-prop-pack/casino_small_props/moonstep.tres"],
	"ghost_hand": ["Texture2D", "res://assets/generated/fx-bundle/ghost_hand/ghost_hand.png"],
	"boss_frames": ["SpriteFrames", "res://assets/generated/character-bundle/boss_frames/boss_frames.tres"],
	"heart_gem": ["AtlasTexture", "res://assets/generated/compact-prop-pack/casino_small_props/heart_gem.tres"],
	"enemy_card": ["AtlasTexture", "res://assets/generated/compact-prop-pack/casino_small_props/enemy_card.tres"],
	"player_card": ["AtlasTexture", "res://assets/generated/compact-prop-pack/casino_small_props/player_card.tres"],
	"dealer_frames": ["SpriteFrames", "res://assets/generated/character-bundle/dealer_frames/dealer_frames.tres"],
	"heroine_frames": ["SpriteFrames", "res://assets/generated/character-bundle/heroine_frames/heroine_frames.tres"],
	"bg_lobby": ["Texture2D", "res://assets/generated/background-map/bg_lobby/bg_lobby.png"],
	"platform_left": ["AtlasTexture", "res://assets/generated/platform-strip/casino_platforms/platform_left.tres"],
	"platform_middle": ["AtlasTexture", "res://assets/generated/platform-strip/casino_platforms/platform_middle.tres"],
	"platform_right": ["AtlasTexture", "res://assets/generated/platform-strip/casino_platforms/platform_right.tres"],
	"arch": ["AtlasTexture", "res://assets/generated/scene-prop-set/casino_props/arch.tres"],
	"curtain": ["AtlasTexture", "res://assets/generated/scene-prop-set/casino_props/curtain.tres"],
	"chandelier": ["AtlasTexture", "res://assets/generated/scene-prop-set/casino_props/chandelier.tres"],
	"railing": ["AtlasTexture", "res://assets/generated/scene-prop-set/casino_props/railing.tres"],
	"candle": ["AtlasTexture", "res://assets/generated/compact-prop-pack/casino_small_props/candle.tres"],
	"chip": ["AtlasTexture", "res://assets/generated/compact-prop-pack/casino_small_props/chip.tres"],
	"ui_cjk_font": ["FontFile", "res://assets/fonts/NotoSansCJK-Regular.ttc"]
}
var _cache: Dictionary = {}
var last_error: String = ""

func has_asset(asset_id: String) -> bool:
	return BINDINGS.has(asset_id)

func resolve(asset_id: String) -> Resource:
	if _cache.has(asset_id):
		return _cache[asset_id]
	if not BINDINGS.has(asset_id):
		last_error = "Unknown required asset: " + asset_id
		return null
	var binding: Array = BINDINGS[asset_id]
	if not ResourceLoader.exists(binding[1]):
		last_error = "Missing required asset: " + binding[1]
		return null
	var resource: Resource = load(binding[1])
	if resource == null or not resource.is_class(binding[0]):
		last_error = "Asset type mismatch: %s requires %s" % [asset_id, binding[0]]
		return null
	_cache[asset_id] = resource
	return resource
