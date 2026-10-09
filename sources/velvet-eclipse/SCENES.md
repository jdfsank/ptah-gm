# Scene Descriptions: Velvet Eclipse / 绯月赌城

**Tag:** v0.1.0

PLAN.md supplies every task, mechanic, scene path and resource mapping; STRUCTURE.md supplies the room schema and ECS ownership. All scene/resource paths below are planned end-of-tag contracts unless already present, not a readiness claim. Resolution reference for every scene: 1280×720, with a 32 px outer UI safe margin. Native and actual Web output must preserve readable framing.

The five rooms are JSON compositions inside `scenes/game_world.tscn`, not new gameplay controller scenes. Coordinates in Elements describe viewport composition, not physics guarantees. Choose room dimensions and final ledge coordinates using measured movement envelopes: the unchanged Lobby upper gap must exceed every permitted pre-relic jump/dodge trajectory but remain reachable with a normal second jump. Bind visible art independently of collision.

Source-only anchors use the exact existing paths below/under individual scenes. They are never runtime textures or completed screen-reference results; no additional screen-reference generation is needed. Screenshot criteria describe visible states; mechanics, timing, reachability, pause and persistence still require PLAN execution evidence.

## Scene: Main Bootstrap
- **Path / composition:** `scenes/main.tscn`
- **Type:** menu host; **Layout:** full viewport
- **Background:** No additional artwork; hosts title/world/UI.
- **Mood:** Immediate clear entry.

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Title/world host | full viewport | 100%w × 100%h | Owns wiring, not an extra playable room. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Host | procedural; child-scene bindings below | 1280×720 | No additional asset row or duplicate World |

### Acceptance criteria

- [v0.1.0-M7] Final release launch visibly reaches Title Screen; no blank/error scene, unrequested debug UI or simultaneous modal screens.

### Transitions
- Boot → Title Screen; ordinary Start/Continue requests → GameWorld.

## Scene: Title Screen
- **Path / composition:** `scenes/ui/title_screen.tscn`
- **Type:** menu; **Layout:** vertical-center
- **Background:** Dark indigo procedural surface with gold/purple framing; no portrait.
- **Mood:** Moonlit and welcoming.
- **Source-only visual anchor:** `/workspace/scratch/36a9e7700087/references/E897F5B8-404F-4E59-B758-4D054CBA2F38.PNG`

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Title | upper-center | 70%w × 18%h | 绯月赌城, optional Velvet Eclipse subtitle. |
| Actions | center | 30%w × 25%h | 开始游戏 / 继续游戏; visible selected and disabled states. |
| Controls / browser focus | bottom-center | 85%w × 17%h | Chinese concise controls and keyboard-focus hint. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Background | procedural | 1280×720 | Dark indigo surface; no extra raster UI requirement |
| Frames / bars / controls | procedural `resources/ui/casino_theme.tres`; UI text | 1280×720 safe area; 20–28 px body | Gold/purple style, visible selection and disabled state |
| Chinese labels | `ui_cjk_font / assets/fonts/NotoSansCJK-Regular.ttc` | 20–28 px body; 40–64 px title | Complete Chinese glyph coverage native and Web |

### Acceptance criteria

- [v0.1.0-M7] Title and Start are fully readable; selected action is distinct.
- [v0.1.0-M5] Continue is visibly disabled when save is missing/corrupt/unsupported; a safe Start path and honest notice remain.
- No heroine portrait, inventory, shop or costume menu is present.

### Transitions
- Start → Lobby fresh run; Continue → validated checkpoint room; failed load → Title with notice.

## Scene: GameWorld
- **Path / composition:** `scenes/game_world.tscn`
- **Type:** gameplay host; **Layout:** freeform world + edge-anchored HUD
- **Background:** Current room background behind independent ECS materialization.
- **Mood:** Readable side-on action.

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Room layers | full viewport | 100%w × 100%h | Distant plate → props/terrain → actors/effects; room-bound camera. |
| HUD | screen edges | safe margins | CanvasLayer remains separate from camera. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Room content | Bindings in each of five composition sections below | 1280×720 camera view | All visible objects resolve to those local tables |
| HUD projection | Bindings in Gameplay HUD below | Screen-space | No duplicate HUD/world or unplanned art |

### Acceptance criteria

- [v0.1.0-M1] Feet meet the lit solid surface; camera shows no area outside current room bounds.
- [v0.1.0-M4] Exactly one current room composition and room name are displayed; distant art never contains duplicate actors.
- [v0.1.0-M7] HUD remains screen-anchored; gameplay is not a full-screen concept image.

### Transitions
- Room E interactions → connected room composition; Escape → Pause; M → Map; player death → Death; legitimate boss defeat → Ending.

## Scene: Grand Lobby / 大厅
- **Path / composition:** `data/rooms/grand_lobby.json`
- **Type:** gameplay; **Layout:** broad lower corridor + visible upper balcony
- **Background:** bg_lobby; cool indigo/moonlight with warm lower candles.
- **Mood:** Grand entrance with a visible future route.
- **Source-only visual anchor:** `/workspace/scratch/36a9e7700087/references/7F9F5E38-C424-49BC-AF6B-F70A5BFC768E.PNG`

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Player / initial safe ground | lower-left | body 92–108 px | First landing area clear of immediate enemy contact. |
| Upper balcony / Save entrance | upper-middle or upper-right | repeatable terrain; arch 240×360 | Clearly visible but geometrically unreachable before Moonstep. |
| Gallery route / melee encounter | lower-right; enemy beyond initial safety | door surround and dealer scale | E exit remains reachable with ordinary first jump. |
| Foreground layers | sides and overhead | curtain/chandelier/railing contract | Open center keeps the balcony easy to identify. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Backdrop | `bg_lobby / assets/generated/background-map/bg_lobby/bg_lobby.png` | 1280×720 | Distant architecture only |
| Heroine | `heroine_frames / assets/generated/character-bundle/heroine_frames/heroine_frames.tres` | 92–108 px body; 12.8–15% view height | Feet-aligned genuine action frames; full silhouette visible |
| Floors / ledges | `platform_left / assets/generated/platform-strip/casino_platforms/platform_left.tres`; `platform_middle / assets/generated/platform-strip/casino_platforms/platform_middle.tres`; `platform_right / assets/generated/platform-strip/casino_platforms/platform_right.tres` | 160×80 px repeated segments | Lit tops coincide with collision; no stretched prop substitute |
| Door surround | `arch / assets/generated/scene-prop-set/casino_props/arch.tres` | 240×360 px | Independent noncolliding art; E trigger/highlight separate |
| Curtains | `curtain / assets/generated/scene-prop-set/casino_props/curtain.tres` | 260×420 px | Independent framing outside the playable corridor |
| Chandeliers | `chandelier / assets/generated/scene-prop-set/casino_props/chandelier.tres` | 200×180 px | Independent overhead dressing |
| Railing | `railing / assets/generated/scene-prop-set/casino_props/railing.tres` | 256×96 px | Layer behind actor; no false landing surface |
| Chips / candles | `chip / assets/generated/compact-prop-pack/casino_small_props/chip.tres`; `candle / assets/generated/compact-prop-pack/casino_small_props/candle.tres` | 24×12 / 24×56 px | Decorative only; no pickups/currency |
| Melee/ranged dealers | `dealer_frames / assets/generated/character-bundle/dealer_frames/dealer_frames.tres` | 105–130 px body; 14.6–18.1% view height | Distinct role equipment/silhouette and spectral treatment; real attack/cast poses |
| Player/hostile projectiles | `player_card / assets/generated/compact-prop-pack/casino_small_props/player_card.tres`; `enemy_card / assets/generated/compact-prop-pack/casino_small_props/enemy_card.tres` | 24×36 / 28×42 px | Separate visible objects; spawned only by actual attacks |
| Combat / landing / interaction feedback | procedural; UI text | Bounded local effects; 20–28 px prompts | Slash/impact/hurt/defeat expire; eligible E prompt and transition fade only |

### Acceptance criteria

- [v0.1.0-M1] Initial frame shows a complete heroine on a clear lower platform and readable route ahead.
- [v0.1.0-M4] High balcony and its independent arch are visibly higher than the ordinary lower route; no decorative bridge appears to bypass it.
- [v0.1.0-M3] The first dealer is beyond safe spawn, visible ahead or deliberately off-screen to the right; no boss or relic is present.
- [v0.1.0-M7] Room label 大厅 and initial movement/jump guidance appear without covering landing tops; Moonstep badge is absent in a fresh run.

### Transitions
- Lower exit ↔ Gallery; upper balcony exit ↔ Quiet Save Room; return from Gallery preserves geometry/discovery.

## Scene: Card Banquet Gallery / 牌宴回廊
- **Path / composition:** `data/rooms/card_banquet_gallery.json`
- **Type:** gameplay; **Layout:** horizontal combat lanes with separated ledges
- **Background:** Shared bg_lobby; burgundy curtain rhythm, clustered chandeliers and rails.
- **Mood:** Ornate, hostile banquet passage.
- **Source-only visual anchor:** `/workspace/scratch/36a9e7700087/references/E2A8941A-8B11-4F84-88DB-541A3D301892.PNG`

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Player entry | lower-left | body contract | Safe arrival from Lobby. |
| Melee/ranged combat | middle/right on separate platforms | dealer contract | Roles readable before their attack windows. |
| Flying card | open upper-mid flight lane | 46×68 px | Silhouette distinct from projectiles; not decoration. |
| Doors | left/right ends | arch contract | Lobby return and Tower exit; no room menu shortcuts. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Backdrop | `bg_lobby / assets/generated/background-map/bg_lobby/bg_lobby.png` | 1280×720 | Shared plate differentiated by foreground/light |
| Heroine | `heroine_frames / assets/generated/character-bundle/heroine_frames/heroine_frames.tres` | 92–108 px body; 12.8–15% view height | Feet-aligned genuine action frames; full silhouette visible |
| Floors / ledges | `platform_left / assets/generated/platform-strip/casino_platforms/platform_left.tres`; `platform_middle / assets/generated/platform-strip/casino_platforms/platform_middle.tres`; `platform_right / assets/generated/platform-strip/casino_platforms/platform_right.tres` | 160×80 px repeated segments | Lit tops coincide with collision; no stretched prop substitute |
| Door surround | `arch / assets/generated/scene-prop-set/casino_props/arch.tres` | 240×360 px | Independent noncolliding art; E trigger/highlight separate |
| Curtains | `curtain / assets/generated/scene-prop-set/casino_props/curtain.tres` | 260×420 px | Independent framing outside the playable corridor |
| Chandeliers | `chandelier / assets/generated/scene-prop-set/casino_props/chandelier.tres` | 200×180 px | Independent overhead dressing |
| Railing | `railing / assets/generated/scene-prop-set/casino_props/railing.tres` | 256×96 px | Layer behind actor; no false landing surface |
| Chips / candles | `chip / assets/generated/compact-prop-pack/casino_small_props/chip.tres`; `candle / assets/generated/compact-prop-pack/casino_small_props/candle.tres` | 24×12 / 24×56 px | Decorative only; no pickups/currency |
| Melee/ranged dealers | `dealer_frames / assets/generated/character-bundle/dealer_frames/dealer_frames.tres` | 105–130 px body; 14.6–18.1% view height | Distinct role equipment/silhouette and spectral treatment; real attack/cast poses |
| Flying cursed card | `enemy_card / assets/generated/compact-prop-pack/casino_small_props/enemy_card.tres` | 46×68 px; 9.4% view height | Rigid flight/flip actor, distinct from smaller projectiles |
| Player/hostile projectiles | `player_card / assets/generated/compact-prop-pack/casino_small_props/player_card.tres`; `enemy_card / assets/generated/compact-prop-pack/casino_small_props/enemy_card.tres` | 24×36 / 28×42 px | Separate visible objects; spawned only by actual attacks |
| Combat / landing / interaction feedback | procedural; UI text | Bounded local effects; 20–28 px prompts | Slash/impact/hurt/defeat expire; eligible E prompt and transition fade only |

### Acceptance criteria

- [v0.1.0-M3] Encounter captures show melee, ranged and flying-card forms distinctly; not three recolored identical actors.
- [v0.1.0-M2] At combat capture, attack pose and local effect are separate from the backdrop and HUD health/energy remains visible.
- [v0.1.0-M4] Curtain/chandelier/rail arrangement differs from Lobby; room label is 牌宴回廊.
- Spawn frame may keep later enemies off-screen to the right, but entry landing and first encounter lane remain unobstructed.

### Transitions
- Left exit ↔ Lobby; right exit ↔ Roulette Clocktower.

## Scene: Roulette Clocktower / 轮盘钟楼
- **Path / composition:** `data/rooms/roulette_clocktower.json`
- **Type:** gameplay; **Layout:** rising staggered platforms around roulette motif
- **Background:** bg_tower; blue-purple height with gold roulette and warm candles.
- **Mood:** Vertical discovery and a clear reward.
- **Source-only visual anchor:** `/workspace/scratch/36a9e7700087/references/282B3BB0-116D-4D36-81DB-FAE4161498F3.PNG`

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Entry / ascent | lower-left toward upper-middle | reachable first-jump ledges | Pre-relic climb is genuinely possible. |
| Roulette feature | mid/back layer | 260×260 px | Independent decorative wheel, not a moving-platform or gambling mechanic. |
| Moonstep relic | upper landing | 48×48 px | Approachable E prompt after traversal. |
| Exit teaching ledge | return path near relic | measured double-jump gap | After pickup, a safe visible landing demonstrates new reach. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Backdrop | `bg_tower / assets/generated/background-map/bg_tower/bg_tower.png` | 1280×720 | Distant clocktower architecture |
| Heroine | `heroine_frames / assets/generated/character-bundle/heroine_frames/heroine_frames.tres` | 92–108 px body; 12.8–15% view height | Feet-aligned genuine action frames; full silhouette visible |
| Floors / ledges | `platform_left / assets/generated/platform-strip/casino_platforms/platform_left.tres`; `platform_middle / assets/generated/platform-strip/casino_platforms/platform_middle.tres`; `platform_right / assets/generated/platform-strip/casino_platforms/platform_right.tres` | 160×80 px repeated segments | Lit tops coincide with collision; no stretched prop substitute |
| Door surround | `arch / assets/generated/scene-prop-set/casino_props/arch.tres` | 240×360 px | Independent noncolliding art; E trigger/highlight separate |
| Railing | `railing / assets/generated/scene-prop-set/casino_props/railing.tres` | 256×96 px | Layer behind actor; no false landing surface |
| Chips / candles | `chip / assets/generated/compact-prop-pack/casino_small_props/chip.tres`; `candle / assets/generated/compact-prop-pack/casino_small_props/candle.tres` | 24×12 / 24×56 px | Decorative only; no pickups/currency |
| Melee/ranged dealers | `dealer_frames / assets/generated/character-bundle/dealer_frames/dealer_frames.tres` | 105–130 px body; 14.6–18.1% view height | Distinct role equipment/silhouette and spectral treatment; real attack/cast poses |
| Flying cursed card | `enemy_card / assets/generated/compact-prop-pack/casino_small_props/enemy_card.tres` | 46×68 px; 9.4% view height | Rigid flight/flip actor, distinct from smaller projectiles |
| Player/hostile projectiles | `player_card / assets/generated/compact-prop-pack/casino_small_props/player_card.tres`; `enemy_card / assets/generated/compact-prop-pack/casino_small_props/enemy_card.tres` | 24×36 / 28×42 px | Separate visible objects; spawned only by actual attacks |
| Roulette feature | `roulette / assets/generated/scene-prop-set/casino_props/roulette.tres` | 260×260 | Decorative independent prop, collision elsewhere |
| Moonstep | `moonstep / assets/generated/compact-prop-pack/casino_small_props/moonstep.tres` | 48×48 | World relic separate from HUD badge; disappears after valid pickup |
| Combat / landing / interaction feedback | procedural; UI text | Bounded local effects; 20–28 px prompts | Slash/impact/hurt/defeat expire; eligible E prompt and transition fade only |

### Acceptance criteria

- [v0.1.0-M4] Spawn shows upward stepping platforms and the roulette motif; the upper relic may be intentionally off-screen until ascent.
- [v0.1.0-M4] Relic capture shows the separate luminous object and eligible E prompt; post-pickup capture removes it and displays Moonstep badge.
- [v0.1.0-M1] Landing tops remain clearly lit throughout vertical camera travel; no fake platform silhouette baked into the plate.
- [v0.1.0-M7] Room label 轮盘钟楼 and return objective are readable; the new-jump explanation states a second airborne Space/W press.

### Transitions
- Door ↔ Gallery; relic pickup updates current room/HUD; ordinary backtrack → Lobby upper route.

## Scene: Quiet Save Room / 静谧存档室
- **Path / composition:** `data/rooms/quiet_save_room.json`
- **Type:** gameplay; **Layout:** quiet symmetric shrine center with open walkable floor
- **Background:** Shared bg_lobby; subdued purple, concentrated warm shrine/candle pools.
- **Mood:** Safe breathing space.
- **Source-only visual anchor:** `/workspace/scratch/36a9e7700087/references/E897F5B8-404F-4E59-B758-4D054CBA2F38.PNG`

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Shrine | center near floor | 180×180 px | Primary independent focal object. |
| Arrival / checkpoint spawn | lower-left of shrine | safe player footprint | No enemies, projectiles or damaging zones. |
| Door pair | left/right sides | arch 240×360 px | Lobby upper return and Throne approach. |
| Save notice | near shrine / HUD notice area | 20–28 px text | Pending, success and failure are visually distinct. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Backdrop | `bg_lobby / assets/generated/background-map/bg_lobby/bg_lobby.png` | 1280×720 | Different sparse arrangement/light from Lobby/Gallery |
| Heroine | `heroine_frames / assets/generated/character-bundle/heroine_frames/heroine_frames.tres` | 92–108 px body; 12.8–15% view height | Feet-aligned genuine action frames; full silhouette visible |
| Floors / ledges | `platform_left / assets/generated/platform-strip/casino_platforms/platform_left.tres`; `platform_middle / assets/generated/platform-strip/casino_platforms/platform_middle.tres`; `platform_right / assets/generated/platform-strip/casino_platforms/platform_right.tres` | 160×80 px repeated segments | Lit tops coincide with collision; no stretched prop substitute |
| Door surround | `arch / assets/generated/scene-prop-set/casino_props/arch.tres` | 240×360 px | Independent noncolliding art; E trigger/highlight separate |
| Curtains | `curtain / assets/generated/scene-prop-set/casino_props/curtain.tres` | 260×420 px | Independent framing outside the playable corridor |
| Chandeliers | `chandelier / assets/generated/scene-prop-set/casino_props/chandelier.tres` | 200×180 px | Independent overhead dressing |
| Chips / candles | `chip / assets/generated/compact-prop-pack/casino_small_props/chip.tres`; `candle / assets/generated/compact-prop-pack/casino_small_props/candle.tres` | 24×12 / 24×56 px | Decorative only; no pickups/currency |
| Shrine | `shrine / assets/generated/scene-prop-set/casino_props/shrine.tres` | 180×180 | Independent illustrated checkpoint |
| Combat / landing / interaction feedback | procedural; UI text | Bounded local effects; 20–28 px prompts | Slash/impact/hurt/defeat expire; eligible E prompt and transition fade only |

### Acceptance criteria

- [v0.1.0-M5] Spawn frame shows shrine, safe ground and no hostile entity; checkpoint position is not inside a prop or doorway.
- [v0.1.0-M5] Interaction capture shows a readable E save/heal prompt; success capture shows restored health and confirmed save text, while pending/failure are never labeled saved.
- [v0.1.0-M4] Room label 静谧存档室, sparse shrine composition and two exits distinguish this room from the shared-backdrop rooms.

### Transitions
- Left exit ↔ Lobby upper balcony; right exit ↔ House Throne; shrine E → validated save/heal without a room change.

## Scene: House Throne / 庄家王座
- **Path / composition:** `data/rooms/house_throne.json`
- **Type:** gameplay; **Layout:** wide readable arena; boss right, heroine left
- **Background:** bg_throne; regal purple/gold; phase-two light shift.
- **Mood:** Final confrontation.
- **Source-only visual anchor:** `/workspace/scratch/36a9e7700087/references/D50535A2-C0BD-41B0-BDC5-27E6510686B5.PNG`

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Heroine entry | lower-left | 92–108 px body | Safe initial separation from boss. |
| Royal Dealer | right-middle above arena floor | 260–320 px body | Complete regal silhouette, no head/feet clipping. |
| Attack lane / slam warning | center and floor | matches true hit region | Clear space for cards and dodges. |
| Boss bar | lower-center screen space | about 60%w × 4%h | Name/phase/health without hiding landing edges. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Backdrop | `bg_throne / assets/generated/background-map/bg_throne/bg_throne.png` | 1280×720 | No baked boss or ghost hand |
| Heroine | `heroine_frames / assets/generated/character-bundle/heroine_frames/heroine_frames.tres` | 92–108 px body; 12.8–15% view height | Feet-aligned genuine action frames; full silhouette visible |
| Floors / ledges | `platform_left / assets/generated/platform-strip/casino_platforms/platform_left.tres`; `platform_middle / assets/generated/platform-strip/casino_platforms/platform_middle.tres`; `platform_right / assets/generated/platform-strip/casino_platforms/platform_right.tres` | 160×80 px repeated segments | Lit tops coincide with collision; no stretched prop substitute |
| Door surround | `arch / assets/generated/scene-prop-set/casino_props/arch.tres` | 240×360 px | Independent noncolliding art; E trigger/highlight separate |
| Curtains | `curtain / assets/generated/scene-prop-set/casino_props/curtain.tres` | 260×420 px | Independent framing outside the playable corridor |
| Chandeliers | `chandelier / assets/generated/scene-prop-set/casino_props/chandelier.tres` | 200×180 px | Independent overhead dressing |
| Railing | `railing / assets/generated/scene-prop-set/casino_props/railing.tres` | 256×96 px | Layer behind actor; no false landing surface |
| Chips / candles | `chip / assets/generated/compact-prop-pack/casino_small_props/chip.tres`; `candle / assets/generated/compact-prop-pack/casino_small_props/candle.tres` | 24×12 / 24×56 px | Decorative only; no pickups/currency |
| Player/hostile projectiles | `player_card / assets/generated/compact-prop-pack/casino_small_props/player_card.tres`; `enemy_card / assets/generated/compact-prop-pack/casino_small_props/enemy_card.tres` | 24×36 / 28×42 px | Separate visible objects; spawned only by actual attacks |
| Royal Dealer | `boss_frames / assets/generated/character-bundle/boss_frames/boss_frames.tres` | 260–320 px; 36.1–44.4% view height | Genuine idle/attack body frames |
| Ghost hand | `ghost_hand / assets/generated/fx-bundle/ghost_hand/ghost_hand.png` | 180×240 px | Independent static source with timed rigid motion/fade |
| Warnings / phase glow | procedural | Slam warning matches hit area; bounded card-fan warning | Precedes damage; phase two visibly changes light |
| Combat / landing / interaction feedback | procedural; UI text | Bounded local effects; 20–28 px prompts | Slash/impact/hurt/defeat expire; eligible E prompt and transition fade only |

### Acceptance criteria

- [v0.1.0-M6] Entry shows full heroine and boss at their contract scales with readable arena and boss health bar.
- [v0.1.0-M6] Warning-state capture distinguishes floor slam region or fan windup from damaging cards; ghost hand is independently visible during its effect state.
- [v0.1.0-M6] Phase-two capture visibly changes arena lighting while keeping both actor silhouettes and warning contrast.
- [v0.1.0-M7] Boss bar and room label 庄家王座 do not cover the heroine or landing edge; no normal enemies obscure the final fight.

### Transitions
- Entry connection ↔ Quiet Save Room as permitted by live encounter state; ordinary boss defeat → Ending; player death → Death.

## Scene: Gameplay HUD
- **Path / composition:** `scenes/ui/hud.tscn`
- **Type:** hud; **Layout:** edge-anchored
- **Background:** Transparent world view with compact dark/gold panels.
- **Mood:** Clear and restrained.
- **Source-only visual anchor:** `/workspace/scratch/36a9e7700087/references/E897F5B8-404F-4E59-B758-4D054CBA2F38.PNG`

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Health / energy | top-left | ~28%w × 11%h | Heart emblem, health bar/value and separate energy bar/value. |
| Room / objective | top-center to top-right | ~58%w × 10%h | Short Chinese labels; wrap safely. |
| Moonstep badge | near resource panel | 30×30 px | Hidden until ownership is true. |
| Prompt / onboarding / notice | near interaction or bottom safe area | 20–28 px text | One eligible prompt; control bindings match input. |
| Boss health | bottom-center only in Throne encounter | ~60%w × 4%h | 庄家 health/phase from authoritative state. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Frames / bars / controls | procedural `resources/ui/casino_theme.tres`; UI text | 1280×720 safe area; 20–28 px body | Gold/purple style, visible selection and disabled state |
| Chinese labels | `ui_cjk_font / assets/fonts/NotoSansCJK-Regular.ttc` | 20–28 px body; 40–64 px title | Complete Chinese glyph coverage native and Web |
| Health emblem / Moonstep badge | `heart_gem / assets/generated/compact-prop-pack/casino_small_props/heart_gem.tres`; `moonstep / assets/generated/compact-prop-pack/casino_small_props/moonstep.tres` | 28×28 / 30×30 px | No portrait; reflects real state |
| Interaction / feedback labels | UI text; procedural highlight | 20–28 px; bounded screen-safe position | E, objective, onboarding, saved/pending/failed messages stay readable |

### Acceptance criteria

- [v0.1.0-M7] Health, energy, objective and current room name are visible; no clipped Chinese or miniature unreadable labels.
- [v0.1.0-M2] Combat captures visibly show corresponding health/energy changes; empty energy remains legible.
- [v0.1.0-M4] Fresh run has no Moonstep badge; acquired state shows it and updates objective.
- [v0.1.0-M5] Failed/pending/saved notices are distinct; [v0.1.0-M6] boss bar appears only for the live encounter.

### Transitions
- Escape → Pause; M → Map; nearby E prompt → ordinary interaction request; death/ending → corresponding modal.

## Scene: Pause Overlay
- **Path / composition:** `scenes/ui/pause_overlay.tscn`
- **Type:** overlay; **Layout:** vertical-center
- **Background:** Dimmed frozen current room/HUD.
- **Mood:** Calm interruption.
- **Source-only visual anchor:** `/workspace/scratch/36a9e7700087/references/E897F5B8-404F-4E59-B758-4D054CBA2F38.PNG`

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Pause panel | center | 38%w × 56%h | 暂停, 继续, 返回标题 and concise controls. |
| Selection | inside panel | readable button bounds | Keyboard focus remains visible. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Frames / bars / controls | procedural `resources/ui/casino_theme.tres`; UI text | 1280×720 safe area; 20–28 px body | Gold/purple style, visible selection and disabled state |
| Chinese labels | `ui_cjk_font / assets/fonts/NotoSansCJK-Regular.ttc` | 20–28 px body; 40–64 px title | Complete Chinese glyph coverage native and Web |
| Veil | procedural | 100%w × 100%h | World remains identifiable under dimming |

### Acceptance criteria

- [v0.1.0-M7] 暂停 and highlighted Continue appear above a recognizable frozen room; no overlapping map/death/ending panel.
- Instructions show actual A/D or arrows, Space/W, J, K, Shift/L, E and M bindings; consecutive captures, not a single screenshot, prove freeze.

### Transitions
- Continue / Escape → same playing state with fresh-input requirement; Return to title → Title Screen.

## Scene: Discovered-Room Map
- **Path / composition:** `scenes/ui/map_overlay.tscn`
- **Type:** overlay; **Layout:** centered schematic
- **Background:** Dimmed frozen room; dark gold/purple map panel.
- **Mood:** Readable exploration record.
- **Source-only visual anchor:** `/workspace/scratch/36a9e7700087/references/E897F5B8-404F-4E59-B758-4D054CBA2F38.PNG`

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Map panel | center | 76%w × 68%h | Only discovered-room rectangles and known connections. |
| Current room | within schematic | clear highlight | Label and emphasis, not color alone. |
| Close hint | panel bottom | 20–28 px | M / Escape 关闭. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Frames / bars / controls | procedural `resources/ui/casino_theme.tres`; UI text | 1280×720 safe area; 20–28 px body | Gold/purple style, visible selection and disabled state |
| Chinese labels | `ui_cjk_font / assets/fonts/NotoSansCJK-Regular.ttc` | 20–28 px body; 40–64 px title | Complete Chinese glyph coverage native and Web |
| Map rooms / connectors / current marker | procedural | Room boxes ~140×64 px; bounded within panel | No baked reference minimap; discovered subset of actual five-room graph |

### Acceptance criteria

- [v0.1.0-M7] Fresh-run map shows Lobby and current marker, without undiscovered named rooms or the reference map.
- [v0.1.0-M4] Progressed map reflects visited rooms and their actual connections; labels fit boxes without overlap.
- Map and HUD do not present contradictory current-room labels; modal appearance is distinct from Pause.

### Transitions
- M / Escape → same playing state; map is read-only, no teleport interaction.

## Scene: Death Screen
- **Path / composition:** `scenes/ui/death_screen.tscn`
- **Type:** overlay; **Layout:** vertical-center
- **Background:** Darkened frozen room; existing heroine hurt pose plus fade, no new death animation claim.
- **Mood:** Clear recoverable failure.
- **Source-only visual anchor:** `/workspace/scratch/36a9e7700087/references/E897F5B8-404F-4E59-B758-4D054CBA2F38.PNG`

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Failure title | upper-center | 55%w × 14%h | 本局未终 or clear equivalent death wording. |
| Retry / title actions | center | 34%w × 22%h | 返回存档点 / 返回标题. |
| Checkpoint label | below actions | 60%w × 10%h | Actual safe checkpoint; initial Lobby when no shrine save. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Frames / bars / controls | procedural `resources/ui/casino_theme.tres`; UI text | 1280×720 safe area; 20–28 px body | Gold/purple style, visible selection and disabled state |
| Chinese labels | `ui_cjk_font / assets/fonts/NotoSansCJK-Regular.ttc` | 20–28 px body; 40–64 px title | Complete Chinese glyph coverage native and Web |
| World / heroine treatment | `heroine_frames / assets/generated/character-bundle/heroine_frames/heroine_frames.tres`; procedural fade | Existing 92–108 px body behind veil | Reuse hurt pose, no claimed separate death bundle |

### Acceptance criteria

- [v0.1.0-M5] Clear death message, Retry and Return to title appear; checkpoint label is readable and truthful.
- [v0.1.0-M7] One selected actionable control remains visible; no active combat/menu mixture or false save confirmation.

### Transitions
- Retry → validated checkpoint with full health/fresh encounters; Return to title → Title Screen.

## Scene: Ending Screen
- **Path / composition:** `scenes/ui/ending_screen.tscn`
- **Type:** overlay; **Layout:** vertical-center
- **Background:** Throne distant plate or frozen cleared arena with procedural veil.
- **Mood:** Release after victory.
- **Source-only visual anchor:** `/workspace/scratch/36a9e7700087/references/D50535A2-C0BD-41B0-BDC5-27E6510686B5.PNG`

### Elements

| Element | Position | Size | Description |
|---|---|---|---|
| Ending title / message | upper-center | 70%w × 30%h | 庄家已败; brief Chinese curse-broken resolution. |
| Restart / title | lower-center | 34%w × 22%h | 重新开始 / 返回标题; unambiguous selection. |

### Asset bindings

| Element | Asset Row / Path | Runtime Size | Visual Contract |
|---|---|---|---|
| Backdrop | `bg_throne / assets/generated/background-map/bg_throne/bg_throne.png` | 1280×720 | No new cinematic/portrait resource |
| Frames / bars / controls | procedural `resources/ui/casino_theme.tres`; UI text | 1280×720 safe area; 20–28 px body | Gold/purple style, visible selection and disabled state |
| Chinese labels | `ui_cjk_font / assets/fonts/NotoSansCJK-Regular.ttc` | 20–28 px body; 40–64 px title | Complete Chinese glyph coverage native and Web |

### Acceptance criteria

- [v0.1.0-M6] Victory resolution is legible; hostile boss/attacks are absent from the cleared end state.
- [v0.1.0-M7] Restart and Return to title are readable and reachable; no extra shop, credits asset or new content is implied.
- A screenshot establishes visible ending only; PLAN ordinary-combat evidence establishes that legitimate boss defeat caused it.

### Transitions
- Restart → fresh Lobby run without Moonstep; Return to title → Title Screen.
