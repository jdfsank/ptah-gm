# Game Design Document: Velvet Eclipse / 绯月赌城

## 1. Game Overview

An original, reference-led gothic side-scrolling action-exploration game. A violet-haired sword hunter enters a cursed casino castle, finds the Moonstep relic, returns to a sealed upper route, and breaks the Royal Dealer's spell.

Target: Godot 4.6.3 WebAssembly/WebGL2, desktop browser keyboard. Source project remains runnable in the native engine. Target first-time session: 10–15 minutes (design goal, not yet measured).

## 2. Core Gameplay Loop

Read a room, traverse its platforms, fight telegraphed enemies, discover a route or relic, and return through the connected castle. The first route reaches the Roulette Clocktower and awards double jump. Returning to the Grand Lobby opens an upper balcony leading through the save room to the Royal Dealer. Defeating the two-phase boss yields a clear ending.

## 3. Mechanics

- Move with A/D or Left/Right; jump with Space or W. Coyote time and jump buffering support deliberate platforming.
- Sword with J, throwing magic card with K, dodge with Shift/L. Attacks have timing, visible effects, cooldown/resource limits, damage and recovery.
- Three enemy types: melee skeletal dealer, ranged spectral dealer, flying cursed card. All have distinct telegraphs, hit reactions and defeat feedback.
- Acquire the Moonstep relic through real exploration. Double jump then enables a previously unreachable route in the Grand Lobby; it is not merely a cosmetic lock/key.
- E interacts with doors, relic and checkpoint; all available interactions show a readable prompt.
- Checkpoint heals and saves room/relic state. Death offers a clear return to checkpoint. Browser reload can continue from a valid save. Corrupt/missing saves fail safely.
- A two-phase Royal Dealer boss uses telegraphed card fans and slam zones. Phase two visibly changes rhythm and arena lighting. Boss defeat leads to ending and restart.
- Escape pauses gameplay and all gameplay input, preserving menu input. M toggles discovered-room map.

## 4. World and Art Direction

Five connected rooms: Grand Lobby (大厅), Card Banquet Gallery (牌宴回廊), Roulette Clocktower (轮盘钟楼), Quiet Save Room (静谧存档室), House Throne (庄家王座).

Rich illustrated 2D raster assets, inspired by the eight supplied concepts: indigo stone, burgundy curtains, warm candlelight, fine aged-gold trim, purple moonlight, neon magenta playing cards. Use original generated art and actual animated SpriteFrames. The current asset skills produce illustrated/cel-shaded assets, not a claim of true pixel-art production or one-to-one concept rendering.

Viewport 1280×720. Heroine standing height 92–108 px; dealers 105–130 px; boss 260–320 px. Platforms have clear lit tops and deep architectural support. Backdrops are non-colliding distant architecture with no baked-in gameplay actors/UI. Moving actors, platform surfaces, doors, relics and projectiles are independent resources. Reference screenshots are never a full-screen substitute for a scene.

## 5. Characters

Heroine: silver-violet short hair, green eyes, dark fitted hunter costume, wine/violet cape or ribbons, gold-accented thin sword. Seven needed body actions: idle, run, jump, attack, cast, dodge, hurt. A fall may hold an appropriate jump pose. Death uses existing hurt pose plus scene treatment, not a claimed additional frame action.

Dealers share a coherent animated skeletal family (idle/move/melee attack/cast), with silhouette-equipment/color differences separating melee and ranged behavior. Flying card is a rigid illustrated card token with flight/flip motion. Boss has genuine idle/attack frames plus independently animated magical hand/attack effects.

## 6. Room Progression

Lobby -> Gallery -> Clocktower (Moonstep) -> Gallery -> Lobby upper balcony -> Save Room -> Throne. Returning between rooms preserves visited-room knowledge. The Clocktower teaches the new jump at its exit. The save room is safe and the final checkpoint is close to the boss. Each room has unique foreground composition and distinct lighting, even where the same distant architectural plate is reused.

## 7. UI and Feedback

Readable title/start/continue screen, control guide, health and card-energy HUD, objective text, ability badge, compact room map, interaction prompts, pause overlay, death/retry and ending. Gold/purple frames and card-suit motifs reinforce the references. No dense unreadable miniature text. Damage has flash and short invulnerability; sword impacts, projectile impacts and landing feedback have bounded lifetimes.

## 8. Audio

No supplied audio files. Music/recorded SFX are deferred per the framework asset rule; the release must remain understandable through visuals. No unsupported audio quality claim.

## 9. Scope and Approval

Source: user request “参考这些照片，使用这个系统制作一个恶魔城游戏”, eight uploaded references, and the scope/dependency question quoted in docs/USER-APPROVAL.md.

User reply on 2026-10-06: “许可，构建wasm”. This explicitly approves the five-room v0.1.0 scope and fixed official dependencies and requires a WebAssembly build. Provenance is a host-supplied exact chat transcript, not local TTY confirmation or final game acceptance.

Not in scope: real-money gambling, payments, store/equipment economy, 25 costumes, online service, long campaign, mobile/touch/controller certification, hosting/publication/push. No changes to the source GodotMaker system unless a genuine blocking bug is separately identified.
