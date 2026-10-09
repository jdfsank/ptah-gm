# Assets: Velvet Eclipse / 绯月赌城

## Visual Style Source

DESIGN.md is the visual contract. The following existing user images are source-only anchors, inspected as pixels; provenance and hashes are recorded in `docs/reference-provenance.json`. They are not runtime assets, registered screen-reference results, or completed generated art. Do not copy them into a scene, crop them into runtime sprites, or mark a generation stage complete because they exist. Actual image attachments must accompany provider calls; pathname text alone is not reference use.

| Source alias | Exact existing canonical source path | Useful direction |
|---|---|---|
| ballroom | `/workspace/scratch/36a9e7700087/references/E2A8941A-8B11-4F84-88DB-541A3D301892.PNG` | Gallery composition, chandeliers, dealers and combat contrast |
| ui | `/workspace/scratch/36a9e7700087/references/E897F5B8-404F-4E59-B758-4D054CBA2F38.PNG` | UI gold/purple language, map and shrine vignette; extra reference menus are out of scope |
| lobby | `/workspace/scratch/36a9e7700087/references/7F9F5E38-C424-49BC-AF6B-F70A5BFC768E.PNG` | Lobby balcony hierarchy, platform edges and dealer silhouettes |
| royal | `/workspace/scratch/36a9e7700087/references/D50535A2-C0BD-41B0-BDC5-27E6510686B5.PNG` | Royal Dealer identity, independent ghost hand and throne arena mood |
| clocktower | `/workspace/scratch/36a9e7700087/references/282B3BB0-116D-4D36-81DB-FAE4161498F3.PNG` | Clocktower architecture, roulette motif and vertical layering |
| heroine | `/workspace/scratch/36a9e7700087/references/60237D29-0A26-46B7-A6CC-B1562F67EB40.PNG` | Heroine identity, hair/eyes, costume and sword; derive a clean full-body anchor if required |
| catacombs | `/workspace/scratch/36a9e7700087/references/3F95E05D-1F11-40EA-8F43-37CF90FC086B.PNG` | Stone material and foreground separation only; no additional room or enemy scope |
| costume | `/workspace/scratch/36a9e7700087/references/07ED2411-65F0-4C17-94F9-D30946D220C2.PNG` | Consistent heroine face/hair and dark hunter silhouette only; no costume system |

The existing user anchors satisfy the visual-anchor prerequisite. No new screen-reference generation is required for this tag. Scene compositions are specified in SCENES.md and evaluated against actual runtime captures; source pictures express direction, not pixel-perfect acceptance. Character canonical/action images produced later remain family evidence, not new Asset Table rows.

## Gameplay Actor Asset Rows

Only the final three SpriteFrames bundles are actor rows. Heroine actions: idle/run/jump/attack/cast/dodge/hurt. Dealer actions: idle/move/melee_attack/cast. Boss actions: idle/attack. The producer resolves cadence, counts, durations and source batches through the character-bundle contract. Animation requires genuinely distinct generated body poses, consistent feet origin and live frame advancement. Fall may reuse jump; death may use hurt plus scene treatment; dealer hurt may flash. The rigid flying-card enemy intentionally uses enemy_card with movement/flip. No large portrait slot is approved.

## Asset Table

The runtime resources below have been produced and checked in this project. Statuses reflect actual registration or provided-font validation. Workers bind only verified final resources after the asset stage updates their status.

| # | Tag | Name | Type | Size | Generation Params | Runtime Type | Runtime Path | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | v0.1.0 | heroine_frames | animation | 256×256 frame canvas; 92–108 px body | family=character-bundle; asset_id=heroine_frames; actions=idle/run/jump/attack/cast/dodge/hurt; cadence resolved by producer | SpriteFrames | res://assets/generated/character-bundle/heroine_frames/heroine_frames.tres | generated |
| 2 | v0.1.0 | dealer_frames | animation | 256×256 frame canvas; 105–130 px body | family=character-bundle; asset_id=dealer_frames; actions=idle/move/melee_attack/cast; cadence resolved by producer | SpriteFrames | res://assets/generated/character-bundle/dealer_frames/dealer_frames.tres | generated |
| 3 | v0.1.0 | boss_frames | animation | 512×512 frame canvas; 260–320 px body | family=character-bundle; asset_id=boss_frames; actions=idle/attack; cadence resolved by producer | SpriteFrames | res://assets/generated/character-bundle/boss_frames/boss_frames.tres | generated |
| 4 | v0.1.0 | bg_lobby | background | 1280×720 px | family=background-map; asset_id=bg_lobby; distant architecture only | Texture2D | res://assets/generated/background-map/bg_lobby/bg_lobby.png | generated |
| 5 | v0.1.0 | bg_tower | background | 1280×720 px | family=background-map; asset_id=bg_tower; distant architecture only | Texture2D | res://assets/generated/background-map/bg_tower/bg_tower.png | generated |
| 6 | v0.1.0 | bg_throne | background | 1280×720 px | family=background-map; asset_id=bg_throne; distant architecture only | Texture2D | res://assets/generated/background-map/bg_throne/bg_throne.png | generated |
| 7 | v0.1.0 | platform_left | terrain | 160×80 px | family=platform-strip; asset_id=casino_platforms; kind=atlas; role=left_cap | AtlasTexture | res://assets/generated/platform-strip/casino_platforms/platform_left.tres | generated |
| 8 | v0.1.0 | platform_middle | terrain | 160×80 px | family=platform-strip; asset_id=casino_platforms; kind=atlas; role=repeat_middle | AtlasTexture | res://assets/generated/platform-strip/casino_platforms/platform_middle.tres | generated |
| 9 | v0.1.0 | platform_right | terrain | 160×80 px | family=platform-strip; asset_id=casino_platforms; kind=atlas; role=right_cap | AtlasTexture | res://assets/generated/platform-strip/casino_platforms/platform_right.tres | generated |
| 10 | v0.1.0 | arch | scene prop | 256×384 px slot; ~240×360 px displayed | family=scene-prop-set; asset_id=casino_props; fixed slot below | AtlasTexture | res://assets/generated/scene-prop-set/casino_props/arch.tres | generated |
| 11 | v0.1.0 | curtain | scene prop | 288×448 px slot; ~260×420 px displayed | family=scene-prop-set; asset_id=casino_props; fixed slot below | AtlasTexture | res://assets/generated/scene-prop-set/casino_props/curtain.tres | generated |
| 12 | v0.1.0 | chandelier | scene prop | 224×192 px slot; ~200×180 px displayed | family=scene-prop-set; asset_id=casino_props; fixed slot below | AtlasTexture | res://assets/generated/scene-prop-set/casino_props/chandelier.tres | generated |
| 13 | v0.1.0 | railing | scene prop | 288×112 px slot; ~256×96 px displayed | family=scene-prop-set; asset_id=casino_props; fixed slot below | AtlasTexture | res://assets/generated/scene-prop-set/casino_props/railing.tres | generated |
| 14 | v0.1.0 | roulette | scene prop | 288×288 px slot; ~260×260 px displayed | family=scene-prop-set; asset_id=casino_props; fixed slot below | AtlasTexture | res://assets/generated/scene-prop-set/casino_props/roulette.tres | generated |
| 15 | v0.1.0 | shrine | scene prop | 192×192 px slot; ~180×180 px displayed | family=scene-prop-set; asset_id=casino_props; fixed slot below | AtlasTexture | res://assets/generated/scene-prop-set/casino_props/shrine.tres | generated |
| 16 | v0.1.0 | player_card | compact prop | 48×72 px slot; ~24×36 px displayed | family=compact-prop-pack; asset_id=casino_small_props; fixed slot below | AtlasTexture | res://assets/generated/compact-prop-pack/casino_small_props/player_card.tres | generated |
| 17 | v0.1.0 | enemy_card | compact prop | 64×96 px slot; ~28×42 projectile / 46×68 enemy px displayed | family=compact-prop-pack; asset_id=casino_small_props; fixed slot below | AtlasTexture | res://assets/generated/compact-prop-pack/casino_small_props/enemy_card.tres | generated |
| 18 | v0.1.0 | chip | compact prop | 48×32 px slot; ~24×12 px displayed | family=compact-prop-pack; asset_id=casino_small_props; fixed slot below | AtlasTexture | res://assets/generated/compact-prop-pack/casino_small_props/chip.tres | generated |
| 19 | v0.1.0 | heart_gem | compact prop | 48×48 px slot; ~28×28 px displayed | family=compact-prop-pack; asset_id=casino_small_props; fixed slot below | AtlasTexture | res://assets/generated/compact-prop-pack/casino_small_props/heart_gem.tres | generated |
| 20 | v0.1.0 | moonstep | compact prop | 64×64 px slot; ~48×48 relic / 30×30 badge px displayed | family=compact-prop-pack; asset_id=casino_small_props; fixed slot below | AtlasTexture | res://assets/generated/compact-prop-pack/casino_small_props/moonstep.tres | generated |
| 21 | v0.1.0 | candle | compact prop | 40×80 px slot; ~24×56 px displayed | family=compact-prop-pack; asset_id=casino_small_props; fixed slot below | AtlasTexture | res://assets/generated/compact-prop-pack/casino_small_props/candle.tres | generated |
| 22 | v0.1.0 | ghost_hand | effect | 256×320 px canvas; ~180×240 px visible | family=fx-bundle; asset_id=ghost_hand; mode=static; transparent isolated magical hand | Texture2D | res://assets/generated/fx-bundle/ghost_hand/ghost_hand.png | generated |
| 23 | v0.1.0 | ui_cjk_font | font | 20–28 px body; 40–64 px title | provided FontFile source=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc; native FontFile load and 65 Chinese glyphs verified; Web check pending | FontFile | res://assets/fonts/NotoSansCJK-Regular.ttc | provided |

## Production Grouping and Fixed Slots

Use the actual selected imagegen provider and first-class family contract; do not synthesize art with code. Keep one request/result per unit, with preserved source/reference/provider/curation and actual Godot validation evidence. Final output paths are exactly the Asset Table paths. These declarations are planned, not completed production metadata.

| Production unit | Family / complete logical output set | Source anchors | Contract |
|---|---|---|---|
| heroine_frames | character-bundle / heroine_frames | heroine, costume, lobby | 256 px frame canvas; preserve approved hunter identity; derive a clean full-body anchor only if supplied composition is unsuitable |
| dealer_frames | character-bundle / dealer_frames | lobby, ballroom | 256 px frame canvas; four genuine actions; equipment/silhouette plus spectral color distinguish melee and ranged use |
| boss_frames | character-bundle / boss_frames | royal | 512 px frame canvas; genuine idle/attack body poses, separate from ghost_hand |
| bg_lobby | background-map / bg_lobby | lobby, ballroom | 1280×720 distant architecture; reused in Gallery and Save Room with independent dressing |
| bg_tower | background-map / bg_tower | clocktower | 1280×720 distant clocktower architecture; no baked roulette prop or collision ledges |
| bg_throne | background-map / bg_throne | royal | 1280×720 throne architecture; no baked boss, ghost hand, projectiles or HUD |
| casino_platforms | platform-strip / platform_left, platform_middle, platform_right | lobby, clocktower | kind=atlas; fixed 3×1 grid, 160×80 px cells; roles left_cap/repeat_middle/right_cap; pivots [0.5,1.0]; shared lit top |
| casino_props | scene-prop-set / arch, curtain, chandelier, railing, roulette, shrine | lobby, ballroom, clocktower, ui | One separated real source sheet; explicit non-overlapping slots below; no actors or floor plane |
| casino_small_props | compact-prop-pack / player_card, enemy_card, chip, heart_gem, moonstep, candle | ui, lobby, clocktower | One separated real source sheet; explicit slots below; transparent padding, no unplanned economy |
| ghost_hand | fx-bundle / ghost_hand | royal | mode=static; isolated transparent magical hand; preserve disconnected glow as one effect; runtime animates position/scale/fade |
| ui_cjk_font | provided FontFile, no image generation | verified system font path in row | Copy the exact supplied font, then check Godot loading and every displayed Chinese glyph in native/Web; destination is not yet provided |

`casino_props`: planned atlas 1024×768. Normalized sources use `.godotmaker/asset-generation/normalized/casino_props/<name>.png`; the producer creates these, preserving aspect and padding rather than stretching. Slots `[x,y,width,height]`: arch `[0,0,256,384]`; curtain `[272,0,288,448]`; chandelier `[576,0,224,192]`; railing `[576,208,288,112]`; roulette `[0,464,288,288]`; shrine `[304,464,192,192]`. Use center pivots `[0.5,0.5]`, consistent with room-prop coordinates.

`casino_small_props`: planned atlas 512×128. Normalized sources use `assets/generated/compact-prop-pack/casino_small_props/normalized/<name>.png`. Slots: player_card `[0,0,48,72]`; enemy_card `[64,0,64,96]`; chip `[144,0,48,32]`; heart_gem `[208,0,48,48]`; moonstep `[272,0,64,64]`; candle `[352,0,40,80]`. Center pivots `[0.5,0.5]`; preserve enough detail for the enemy_card flying role.

Gold/purple UI frames, bars, buttons, map rectangles/connectors, selection highlights, fade overlays and bounded combat/landing/telegraph effects are explicitly procedural. Their planned implementation resource is `resources/ui/casino_theme.tres`; this is a code-built Theme under M03, not an unregistered generated UI-kit output. Labels are UI text using ui_cjk_font.

## Visual Asset Contract

| Tag | Scene / Mechanic | Visible Object | Asset Row / Path | Runtime Size | Visual Role | Readability Requirement | Source |
|---|---|---|---|---|---|---|---|
| v0.1.0 | All rooms / [v0.1.0-M1], [v0.1.0-M2] | Heroine | `heroine_frames / assets/generated/character-bundle/heroine_frames/heroine_frames.tres` | 92–108 px body / 12.8–15% viewport height | Controllable hunter | Distinct action poses, common feet origin; do not scale by padded frame canvas | heroine, costume |
| v0.1.0 | Lobby/Gallery/Tower / [v0.1.0-M3] | Melee and ranged dealer | `dealer_frames / assets/generated/character-bundle/dealer_frames/dealer_frames.tres` | 105–130 px body / 14.6–18.1% viewport height | Telegraphed enemies | Equipment/silhouette and spectral treatment identify roles; attack/cast advance real frames | lobby, ballroom |
| v0.1.0 | Throne / [v0.1.0-M6] | Royal Dealer | `boss_frames / assets/generated/character-bundle/boss_frames/boss_frames.tres` | 260–320 px body / 36.1–44.4% viewport height | Two-phase boss | Full readable body fits camera and has actual idle/attack frames | royal |
| v0.1.0 | Lobby/Gallery/Save / [v0.1.0-M4] | Distant plate | `bg_lobby / assets/generated/background-map/bg_lobby/bg_lobby.png` | 1280×720 px | Noncolliding depth | Distinct room foreground/light; no baked actors, UI or playable surfaces | lobby, ballroom |
| v0.1.0 | Tower / [v0.1.0-M4] | Distant plate | `bg_tower / assets/generated/background-map/bg_tower/bg_tower.png` | 1280×720 px | Tower depth | Roulette-tower identity without interactive art baked in | clocktower |
| v0.1.0 | Throne / [v0.1.0-M6] | Distant plate | `bg_throne / assets/generated/background-map/bg_throne/bg_throne.png` | 1280×720 px | Arena depth | Leave clear silhouette and warning space | royal |
| v0.1.0 | All rooms / [v0.1.0-M1], [v0.1.0-M4] | Floors and ledges | `platform_left / assets/generated/platform-strip/casino_platforms/platform_left.tres`; `platform_middle / assets/generated/platform-strip/casino_platforms/platform_middle.tres`; `platform_right / assets/generated/platform-strip/casino_platforms/platform_right.tres` | 160×80 px per segment | Colliding surfaces | No seams at shared top; collider matches visible surface; unchanged balcony passes pre/post-relic reach tests | lobby, clocktower |
| v0.1.0 | All rooms / [v0.1.0-M4] | Architecture and door surrounds | `arch / assets/generated/scene-prop-set/casino_props/arch.tres`; `curtain / assets/generated/scene-prop-set/casino_props/curtain.tres`; `chandelier / assets/generated/scene-prop-set/casino_props/chandelier.tres`; `railing / assets/generated/scene-prop-set/casino_props/railing.tres` | 240×360; 260×420; 200×180; 256×96 px | Independent depth layers | No prop stretched into terrain; door trigger remains separate | lobby, ballroom |
| v0.1.0 | Tower/Save / [v0.1.0-M4], [v0.1.0-M5] | Roulette and shrine | `roulette / assets/generated/scene-prop-set/casino_props/roulette.tres`; `shrine / assets/generated/scene-prop-set/casino_props/shrine.tres` | 260×260; 180×180 px | Room identity and checkpoint | Roulette is decoration; shrine has eligible prompt and honest save feedback | clocktower, ui |
| v0.1.0 | Combat / [v0.1.0-M2], [v0.1.0-M3], [v0.1.0-M6] | Player/hostile cards and flying enemy | `player_card / assets/generated/compact-prop-pack/casino_small_props/player_card.tres`; `enemy_card / assets/generated/compact-prop-pack/casino_small_props/enemy_card.tres` | 24×36 player; 28×42 hostile; 46×68 enemy / 9.4% viewport height | Projectiles and rigid flying actor | Independent contacts/lifetimes; flying enemy distinguished by scale, flight and telegraph, no false body-animation claim | lobby, clocktower |
| v0.1.0 | All rooms / [v0.1.0-M4] | Casino dressing | `chip / assets/generated/compact-prop-pack/casino_small_props/chip.tres`; `candle / assets/generated/compact-prop-pack/casino_small_props/candle.tres` | 24×12; 24×56 px | Environmental detail | Decorative only; no currency/pickup semantics | lobby, ballroom |
| v0.1.0 | Tower/HUD / [v0.1.0-M4], [v0.1.0-M7] | Moonstep and health | `moonstep / assets/generated/compact-prop-pack/casino_small_props/moonstep.tres`; `heart_gem / assets/generated/compact-prop-pack/casino_small_props/heart_gem.tres` | 48×48 relic; 30×30 badge; 28×28 heart | Relic, ability and health emblems | Relic removed only on pickup; badge and health match ECS state | ui |
| v0.1.0 | Throne / [v0.1.0-M6] | Ghost hand | `ghost_hand / assets/generated/fx-bundle/ghost_hand/ghost_hand.png` | 180×240 px | Detached magical attack effect | Timed rigid motion/fade matches warning; not a replacement for boss body frames | royal |
| v0.1.0 | All UI / [v0.1.0-M7] | Chinese text | `ui_cjk_font / assets/fonts/NotoSansCJK-Regular.ttc` | 20–28 px body; 40–64 px headings | Readable UI | Native and Web glyph coverage; no missing-glyph boxes | verified provided font |
| v0.1.0 | All UI / [v0.1.0-M7] | Frames, bars, buttons, map, modals | procedural `resources/ui/casino_theme.tres` plus UI text | 1280×720 safe area; 20–28 px labels | State/flow feedback | No overlap, stale HUD or undiscovered map reveal; see SCENES | GDD §7, ui |
| v0.1.0 | Combat / [v0.1.0-M2], [v0.1.0-M3], [v0.1.0-M6] | Slash, impact, landing, hurt, defeat, fan/slam telegraphs, phase glow | procedural | Local bounded effects; slam region matches actual hit area | Timing/readability | Expire correctly, precede damage where required, remain clear while paused | PLAN Runtime Asset Assignments |
| v0.1.0 | Interactions / [v0.1.0-M4], [v0.1.0-M5], [v0.1.0-M7] | Prompts, objectives, room names, onboarding, save messages | UI text plus procedural highlight/fade | 20–28 px; within screen margins | Guidance | Distance/eligibility and bindings truthful; failed/pending/saved distinct | PLAN Runtime Asset Assignments |
| v0.1.0 | All scene references | Source-only visual direction | Exact existing source paths above; no runtime binding | Original dimensions, never scaled into runtime | Production/evaluation anchor | Existing sources are not generated scene outputs; no image copied or registered here | docs/reference-provenance.json |

## 2D Animation Sources

| Runtime bundle | Planned actions | Identity/source relationship | Timing / curation state |
|---|---|---|---|
| heroine_frames | idle, run, jump, attack, cast, dodge, hurt | heroine/costume anchors; family result retains accepted full-body identity | NOT PRODUCED; producer resolves frame count/FPS/durations/loops and action batches |
| dealer_frames | idle, move, melee_attack, cast | lobby/ballroom anchors; coherent skeletal dealer family | NOT PRODUCED; preserve real poses and role-specific presentation |
| boss_frames | idle, attack | royal anchor; body animation independent of ghost_hand | NOT PRODUCED; preserve real poses and common origin |

## Visual Curation Records

None yet. Source sheets, accepted/rejected candidates, identities and reports belong under `.godotmaker/asset-generation/` and the family result, not additional runtime rows. Do not claim a selected candidate, frame count or passing validation before it exists.

## Audio

No supplied audio. Music and recorded SFX are deferred for v0.1.0 under GDD §8; no missing audio file paths or ready-audio claims are introduced. Visual cues must carry the complete game.

## Budget Tracking

No production calls have been made by this package. Costs are unreported, not assumed zero; the asset stage records actual available usage evidence.

## Post-Processing Notes

- Process only actual provider/user source images using the controlled family tools; preserve sources and provenance. No placeholder or ad hoc drawn replacement for missing art.
- Validate exact Godot resource types, frame inventory, dimensions, transparency, slot names, pivots, seams and runtime scale before registration.
- The font source exists; destination remains MISSING until copied and verified. A documented fontTools subset is permitted by PLAN only if every binding/manifest path is updated and all displayed Chinese glyphs survive.
- Asset readiness does not prove scene composition, animation at runtime, native/Web play, or browser persistence; those require implementation and current captures.

## Verified Runtime Binding Measurements

These measurements describe verified output geometry; the binding code must account for transparent padding rather than scaling the entire padded canvas to the desired actor height.

- heroine_frames: 256 px canvas; idle visible body median 202 px. Use approximately 0.49 scale for a 100 px body. Centered sprite offsets before scale: y=-105 for idle/run/jump/attack/dodge, -102 for cast, -106 for hurt. These compensate measured baseline y=233/230/234 respectively; minor per-frame one-pixel variation remains subject to runtime visual review.
- dealer_frames: 256 px canvas, approximately 110 px visible body at scale 1.0. Centered sprite y offsets: idle/move -54, melee_attack -88, cast -56. Preserve these action-specific padding offsets; do not rescale all frames per action.
- boss_frames: 512 px canvas, idle body approximately 270 px at scale 1.0. Centered sprite y offsets: idle -136, attack -186. Attack release frame index 3 occurs at 0.35 seconds; attack ends at 0.7 seconds. The original padding difference is compensated in presentation binding, not hidden as a common-canvas-origin claim.
- casino_platforms: joining walk edge is y=6 in every 160×80 texture cell. Draw image top at collision top minus 6 px. Closed cap ornaments reach y=4; these are a 2 px cosmetic overhang, not an extra collision ledge.
- ui_cjk_font: native FontFile loading and all 65 distinct Chinese characters in current GDD/SCENES passed. The supplied TTC defaults to Noto Sans CJK JP; browser glyph rendering still requires actual Web verification.
