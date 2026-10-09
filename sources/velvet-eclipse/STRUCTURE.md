# Velvet Eclipse / 绯月赌城 — Runtime Architecture

**Tag:** v0.1.0

## Dimension: 2D

One local native/Web game, five data-driven rooms, 1280×720 Compatibility renderer. PLAN.md is authoritative for scope, files and acceptance. This is the end-of-tag contract, not a claim of implemented code or ready assets.

## Input Actions

| Action | Keys |
|---|---|
| move_left / move_right | A, Left / D, Right |
| jump | Space, W |
| sword / card / dodge | J / K / Shift, L |
| interact / map / pause | E / M / Escape |
| ui_accept / ui_cancel | Enter / Escape |
| ui_left / ui_right / ui_up / ui_down | Corresponding arrow |

InputSystem merges engine events and GameRuntime.simulate_action(action: String, pressed: bool) into one held/edge stream. Repeats never create extra press edges. Modal entry/exit clears gameplay edges, held intents and jump buffering; require a fresh press before replaying an attack. UI buttons submit ordinary actions through this same route.

## Component Registry

Every class extends Component in its PLAN `scripts/components/c_*.gd` file. All serialized fields below are `@export` with explicit defaults; no methods, callbacks, gameplay setters or node searches. Runtime Node references are ordinary `var`, NEVER exported from a Resource. Arrays/dictionaries and component instances are fresh per entity. Seconds, pixels and pixels/second are used throughout. Values below are initial tuning, with changes supported by tests rather than hard-coded assumptions in room geometry.

| Component (owner) | Fields: type = default |
|---|---|
| C_Transform (R1) | position: Vector2 = Vector2.ZERO; rotation: float = 0.0; scale: Vector2 = Vector2.ONE |
| C_Motion (R1) | velocity: Vector2 = Vector2.ZERO; desired_velocity: Vector2 = Vector2.ZERO; speed: float = 300.0; acceleration: float = 2400.0; gravity: float = 1500.0; jump_speed: float = 580.0; max_fall_speed: float = 900.0; grounded: bool = false; facing: int = 1; jumps_used: int = 0; coyote_left: float = 0.0; buffer_left: float = 0.0; coyote_duration: float = 0.10; buffer_duration: float = 0.12; placement_pending: bool = true |
| C_Body (R1) | kind: String = "none"; size: Vector2 = Vector2(40, 96); offset: Vector2 = Vector2(0, -48); layer: int = 0; mask: int = 0; ready: bool = false; runtime root: Node2D = null; runtime shape: CollisionShape2D = null |
| C_Visual (R1) | asset_id: String = ""; kind: String = "sprite"; offset: Vector2 = Vector2.ZERO; draw_size: Vector2 = Vector2.ZERO; tint: Color = Color.WHITE; z_index: int = 0; animation: String = "idle"; facing: int = 1; flash_left: float = 0.0; runtime node: Node2D = null |
| C_Input (R1) | source: String = "player"; axis: float = 0.0; jump_pressed: bool = false; jump_held: bool = false; sword_pressed: bool = false; card_pressed: bool = false; dodge_pressed: bool = false; interact_pressed: bool = false; ui_actions: Array[String] = [] |
| C_RoomMember (R1) | room_id: String = "grand_lobby"; persistent: bool = false |
| C_CameraTarget (R1) | offset: Vector2 = Vector2(0, -120); smoothing: float = 8.0; enabled: bool = true |
| C_Session (R1) | mode: String = "title"; room_id: String = "grand_lobby"; player_id: String = "player"; objective: String = ""; transition: Dictionary = {}; save_status: String = "none"; message: String = ""; loading: bool = false |
| C_Health (M01) | current: int = 100; maximum: int = 100; team: String = "player"; invulnerable_left: float = 0.0; hurt_left: float = 0.0; dead: bool = false; heal_requested: bool = false |
| C_Combat (M01) | state: String = "idle"; time_left: float = 0.0; sword_cooldown: float = 0.0; card_cooldown: float = 0.0; dodge_cooldown: float = 0.0; energy: float = 100.0; max_energy: float = 100.0; energy_regen: float = 18.0; card_cost: float = 25.0; attack_serial: int = 0; requested_attack: String = ""; dodge_invulnerable: bool = false |
| C_EnemyAI (M01) | kind: String = "melee"; state: String = "idle"; time_left: float = 0.0; home: Vector2 = Vector2.ZERO; patrol_radius: float = 150.0; aggro_range: float = 560.0; attack_range: float = 85.0; target_id: String = "player" |
| C_Projectile (M01) | owner_id: String = ""; team: String = "player"; direction: Vector2 = Vector2.RIGHT; speed: float = 660.0; damage: int = 20; remaining: float = 2.0; consumed: bool = false; previous_position: Vector2 = Vector2.ZERO |
| C_Hitbox (M01) | owner_id: String = ""; team: String = "player"; attack_serial: int = 0; offset: Vector2 = Vector2(54, -48); size: Vector2 = Vector2(100, 76); damage: int = 25; active_left: float = 0.12; hit_ids: Array[String] = []; follows_owner: bool = true |
| C_Effect (M01) | kind: String = "impact"; remaining: float = 0.25; duration: float = 0.25; size: Vector2 = Vector2(32, 32); color: Color = Color.WHITE; owner_id: String = "" |
| C_Interaction (M02) | kind: String = "door"; interaction_id: String = ""; prompt: String = ""; radius: float = 90.0; target_room: String = ""; target_spawn: String = ""; available: bool = true; selected: bool = false; requested: bool = false |
| C_Progression (M02) | moonstep: bool = false; visited_rooms: Array[String] = ["grand_lobby"]; boss_defeated: bool = false; ending_seen: bool = false |
| C_Checkpoint (M02) | checkpoint_id: String = "start"; room_id: String = "grand_lobby"; spawn_id: String = "start"; valid: bool = true; save_requested: bool = false; restore_requested: bool = false; payload: Dictionary = {} |
| C_Boss (M02) | phase: int = 1; state: String = "idle"; time_left: float = 1.2; attack_index: int = 0; phase_changed: bool = false; arena_active: bool = false; slam_center: Vector2 = Vector2.ZERO |
| C_UIState (M03) | visible_screen: String = "title"; focus_index: int = 0; prompt: String = ""; notice: String = ""; notice_left: float = 0.0 |

No extra tag components/files: identify player by session.player_id, AI by C_EnemyAI and boss by C_Boss. Optional components must be checked with get_component(CLASS), never required globally. UI/progression/checkpoint live on the named Session entity; C_Interaction identifies each world interaction, not the session singleton.

## World Registration and Runtime Host

Main (`scripts/main.gd`) boots GameWorld and owns UI wiring only. GameRuntime (`scripts/runtime/game_runtime.gd`) owns registration, action queues, room/catalog access, read-only snapshots and deferred service queues. It does not implement attacks, HP rules, AI, progression decisions or movement. Each System declares `@export var runtime: Node = null`, assigned to GameRuntime BEFORE registration; setup asserts it is valid. Components never hold a runtime/service host. No untyped `get_parent().runtime` assumptions or extra autoload.

1. In GameRuntime create `world = World.new()`, set `world.name = "GameECS"`, `entity_nodes_root = NodePath(".")` and `system_nodes_root = NodePath(".")` BEFORE `add_child(world)`. No reliance on `.tscn` exported root-path ordering or automatic scanning of code-added children.
2. `ECS.set("world", world)` and assert `ECS.world == world`. For each installed System, set `runtime`, `group` and `command_buffer_flush_mode = "MANUAL"`, then call `world.add_system(system)` exactly once. After all registrations call `world.finalize_system_setup()` explicitly: installed gecs defers setup even for later add_system calls. Its flush mode is a String, not the enum shown in some skill examples. Do not alter the addon.
3. GameEntity (`@tool extends Entity`) is a minimal identity/data carrier. Factory creates fresh components, sets non-transform initial values on those instances, and calls `world.add_entity(entity, components)` at the safe boundary. Name/id before registration; retrieve live components only afterward. `define_components()` returns fresh instances or an empty Array, never cached shared resources.
4. Named entities: Session and Player persist between rooms. Other IDs are `<room_id>:<record_id>` or unique attack/effect serials. There is one World and one Player. World owns Entity parenting. Systems are actual registered gecs Systems; calls go through `ECS.process(delta, group)`, never direct `System.process()`.
5. Deferred runtime queues contain data requests: placement `{entity_id: String, position: Vector2, rotation: float = 0.0, scale: Vector2 = Vector2.ONE}`; spawn `{archetype: String, room_id: String, fields: Dictionary}`; room transition `{room_id: String, spawn_id: String, reason: String}`. Runtime/factory dispatch these; the responsible system decides whether they are valid.

## System Schedule

Each row is a unique group, processed in this order; therefore no cross-group topological-sort assumptions. All query examples mean `q.with_all([...]).enabled()`. No `with_group()` scans. Systems may use sub_systems for the alternatives below; do not query an impossible union of every optional component. No parallel_processing.

| Group / order | System; primary query | Reads → writes / responsibility |
|---|---|---|
| input / 1 | InputSystem; C_Input | Session/UI mode and queued engine/semantic events → player input and session UI intents; AI source excluded |
| ai / 2 | EnemyAISystem; C_EnemyAI,C_Transform,C_Health | Player transform/room → AI state, AI C_Input, desired_velocity only |
| boss / 3 | BossSystem; C_Boss,C_Health,C_Transform | Session/health → phase/state, attack requests, effect requests; no direct HP or transform writes |
| combat / 4 | CombatSystem; C_Combat,C_Input,C_Transform | Health/AI/boss requests → attack timing, energy, dodge; hitbox/projectile spawn requests |
| movement / 5 | MovementSystem; C_Transform,C_RoomMember | Input/body/motion and optional progression/combat/projectile/hitbox → all authoritative transforms/body motion, placements, contacts and landing requests |
| damage / 6 | DamageSystem; C_Health,C_Transform,C_Body; separate hitbox/projectile queries | Current contacts/teams/hit IDs/dodge → HP, hurt/invulnerability, death, accepted hit IDs and consumed projectiles; feedback requests |
| interaction / 7 | InteractionSystem; C_Interaction,C_Transform | Player position/input/session → nearest eligible prompt and requested interaction |
| progression / 8 | ProgressionSystem; C_Session,C_Progression,C_Checkpoint | UI intents/interactions/player and boss health → session mode, discovery, Moonstep, transition/heal/save/restore requests |
| save / 9 | SaveSystem; C_Session,C_Progression,C_Checkpoint | Valid requests/repository results → validated checkpoint snapshot, persistence status, restore request to progression |
| effects / 10 | EffectSystem; C_Effect; separate C_Projectile query | Lifetime/contact state → effect age/presentation, projectile expiry and queued removal |
| materialize / 11 | MaterializationSystem; C_Transform,C_RoomMember with C_Body or C_Visual | Verified resources and room membership → node references/readiness only; creates nodes, never assigns gameplay positions |
| animation / 12 | AnimationSystem; C_Visual | Optional motion/input/combat/health/AI/boss → animation, facing, tint and local visual presentation |
| camera / 13 | CameraSystem; C_CameraTarget,C_Transform | Target/room bounds → Camera2D presentation only |
| ui / 14 | UISystem; C_Session,C_UIState | Authoritative health/combat/progression/interaction/checkpoint/boss → UI text/bars/modals and queued ordinary actions |

GameRuntime `_physics_process` runs input, then ai→effects in order when allowed. Progression/save also run with gameplay delta 0 in title, paused, map, dead, ending or transition so menu/restore work continues; their world-progression branches require playing mode. Check mode after progression before effects. Input's pending modal action blocks gameplay immediately that tick. Every installed group runs at most once per tick. R1 may auto-start its traversal fixture; M03 restores the title-first boot.

Main never pauses only the UI: skip ai/boss/combat/movement/damage/interaction/effects and gameplay animation clocks in non-playing modes. Both pause and map are modal. Stop AnimatedSprite2D advancement without resetting its frame; resume only on return to playing. UI navigation and save-completion notifications remain active. Do not use wall-clock timers or uncancelled gameplay Tweens that continue while modal.

After the physics batch, queue ONE deferred flush (guard against duplicate scheduling). Outside physics callbacks: flush MANUAL command buffers, apply validated room/spawn requests, run materialize, then animation/camera/ui presentation. A structural change requested during materialize uses `call_deferred` or its safe-boundary queue, never synchronous tree edits from physics. Queue effects/removals once; consumed/dead entities are ignored while awaiting flush.

## Node Projection and Single-Writer Rule

| Materialized entity | Nodes beneath Entity | Readiness / dependency |
|---|---|---|
| Player/dealer/boss | CharacterBody2D → CollisionShape2D and AnimatedSprite2D | C_Body.kind=character; frames resolved before visible; feet-anchored body |
| Solid platform | StaticBody2D → rectangular CollisionShape2D and illustrated cap/middle/cap Sprite2D children | C_Body.kind=static; collider top agrees with visible top |
| Projectile/flying card | CharacterBody2D → shape and Sprite2D | C_Body.kind=character; projectile/flying motion uses zero gravity |
| Door/relic/shrine | Node2D or Area2D plus independent Sprite2D | C_Interaction; proximity validated from transforms; optional area is presentation/contact aid |
| Background/prop/effect | Node2D → Sprite2D or explicitly planned procedural effect nodes | No collision except a separate explicit C_Body; no background-derived geometry |
| Room camera | Camera2D, created once by MaterializationSystem under GameWorld | CameraSystem requires it; normal UI stays in CanvasLayer |

Materialization is idempotent: reuse a valid existing node; otherwise create once, hidden, with collision disabled until placed. ResourceCatalog resolves only verified ASSETS.md IDs and types. Empty/unknown/mismatched required assets report an explicit load failure, including release builds; no invisible fallback or fabricated path. Root nodes remain children of Entity so ordinary deferred entity removal frees their subtree.

MovementSystem alone assigns C_Transform, root global position/rotation/scale, CharacterBody2D.velocity, and calls move_and_slide/move_and_collide. This includes initial static/prop placement, restore, room entry, enemy motion, sword hitbox following and projectile movement. On a new attached node it consumes placement first; it then enables visibility/collision safely and marks placement complete. During transition, allow only this initialization pass (delta 0, no movement integration) before switching to playing. Materialization never copies C_Transform into a root transform; Animation/Effect may change child-only scale/offset/alpha, never collision roots.

Body coordinates: actor position is foot-center; its default 40×96 rectangle center is (0,-48). Platform position is top-left, collider center is size/2. Props/background use center anchors declared by room data. Actor draw_size is the verified visible body envelope, not the frame canvas size; sprite offset compensates the asset's common feet origin. Default collision bits: world=1, player=2, enemy=4, player shot=8, hostile shot=16. Actors collide with world, projectiles with world and opposing actors. Melee uses active directional rectangles against C_Body world rectangles. Projectile collision sweeps previous→current position to avoid tunneling; overlap lists are not read from render `_process`.

Movement owns actual velocity/grounded/jump counters; AI may write desired_velocity only. Player max jumps is 1, or 2 if session progression.moonstep. Coyote permits the first jump only; it cannot mint a third jump. Double-jump and maximum pre-relic dodge must be measured against unchanged Lobby balcony geometry. DamageSystem owns HP/dead flags and applies each (owner, attack_serial, target) once; healing is a request consumed by it, including a safe delta-0 restore pass. Combat owns the bounded dodge window, not a persistent invulnerability flag.

## Scene Markers and Room JSON Contract

No extra marker script files: RoomCatalog validates JSON records, EntityFactory converts them to ECS archetypes. GameWorld holds the World, camera and room presentation; no room-local gameplay controller. Exact files are the five PLAN `data/rooms/*.json` paths.

| JSON field | Contract |
|---|---|
| version, id, name | version integer 1; id one of grand_lobby, card_banquet_gallery, roulette_clocktower, quiet_save_room, house_throne; name nonempty display string |
| bounds, background, light | bounds [x,y,width,height] finite numbers, positive dimensions; background verified ASSETS row ID; light [r,g,b,a] each 0..1 |
| spawns | Object mapping local spawn ID → [x,y] foot-center; must contain start; every door target references an existing destination spawn |
| platforms | Array of {id, rect:[x,y,w,h]}; unique ID, positive w/h; illustrated cap/middle/cap palette fixed to PLAN platform assets; solid rectangular collision |
| props | Array of {id, asset_id, position:[x,y], size:[w,h], z:int}; center anchored, collision-free; IDs resolve to planned verified props |
| enemies | Array of {id, kind:"melee"/"ranged"/"flying", position:[x,y], patrol_radius:number}; optional per-room array defaults [] |
| doors | Array of {id, position:[x,y], target_room, target_spawn, prompt}; E radius 90; independently illustrated surround/door highlight; no relic Boolean as a replacement for the jump gate |
| relic | null or {id:"moonstep", position:[x,y], prompt}; only Clocktower; removed by progression after legitimate interaction |
| checkpoint | null or {id, spawn_id, position:[x,y], prompt}; safe Quiet Save Room shrine; default start checkpoint is Session data |
| boss | null or {id:"royal_dealer", position:[x,y], arena:[x,y,w,h]}; only House Throne; arena contained within room bounds |

Required arrays props/platforms/doors may be empty only when appropriate; reject duplicate IDs, nonfinite vectors, unknown kinds/assets and dangling destinations. R1 validates the Lobby locally; M02 validates the completed five-room graph. Route: Lobby↔Gallery↔Clocktower, Lobby upper balcony↔Save Room↔Throne. Geometric access, not a fake locked-door check, gates the Lobby upper entrance. Clocktower exit teaches the second jump. Ordinary enemies reset consistently on room re-entry; projectiles, transient effects and boss attacks never survive a transition.

## Entity Archetypes

| Archetype | Components |
|---|---|
| Session | C_Session,C_Input(source=ui),C_Progression,C_Checkpoint,C_UIState; later-task components added only when installed |
| Player | C_Transform,C_Motion,C_Body,C_Visual,C_Input,C_RoomMember(persistent=true),C_CameraTarget,C_Health,C_Combat |
| Melee/ranged/flying enemy | C_Transform,C_Motion,C_Body,C_Visual,C_Input(source=ai),C_RoomMember,C_Health(team=enemy),C_Combat,C_EnemyAI |
| Royal Dealer | Enemy base without C_EnemyAI, plus C_Boss; large body/health/timing overrides |
| Platform / prop | C_Transform,C_RoomMember,C_Body,C_Visual; prop body kind=none |
| Door / Moonstep / shrine | Prop base plus C_Interaction; progression/checkpoint state stays on Session |
| Card projectile | C_Transform,C_Motion,C_Body,C_Visual,C_RoomMember,C_Projectile |
| Active sword/slam hitbox | C_Transform,C_RoomMember,C_Hitbox; optional matching C_Effect/C_Visual for planned procedural feedback |
| Effect | C_Transform,C_RoomMember,C_Effect,C_Visual; finite lifetime, no HP/collision authority |

## Persistence and Session Boundary

SaveRepository reads/writes `user://velvet_eclipse_save.json`, schema `{version:1, checkpoint_id:String, room_id:String, spawn_id:String, moonstep:bool, visited_rooms:Array[String], boss_defeated:bool, ending_seen:bool}`. Strictly validate version/types/catalog IDs/checkpoint membership and deduplicate discovered rooms. Never deserialize runtime nodes, arbitrary resource paths, positions, enemy state or executable content. Missing/corrupt/unsupported save yields Continue disabled plus a safe New Game path. Preserve an in-memory initial checkpoint for death before the shrine.

Shrine interaction requests healing and takes a progression snapshot. Native write errors and browser persistent-store availability/completion must be observed before success UI. `pending`, `saved`, `failed`, `unavailable` are distinct statuses. Browser reload evidence on the actual tested origin is mandatory; returning from FileAccess alone does not prove durable Web storage. Continue/retry use the same validated room transition and Movement placement path; checkpoint restores full health and fresh encounters, never hostile projectiles or a half-finished boss attack.

Session modes: title, playing, paused, map, transition, dead, ending, error. ProgressionSystem is the state-machine authority after M02. BossSystem changes phase on the tested health threshold once, requests ordinary Combat attacks and phase feedback, and cannot grant victory. Progression reaches ending only after legitimate boss death. New Game/restart clears the run through ordinary initialization; no gameplay test API edits relic/HP/position/victory.

## Build Order and Exact Ownership

One active writer. Planning/assets finish first; required verified resources precede R1 binding. R1 → reviewed checks → M01 → reviewed checks → M02 → reviewed checks → M03. PLAN's ownership lists are exhaustive; this document grants no additional files. All systems receive test/test_<name>_system.gd; use a real registered World and named group processing in tests, never direct System.process calls.

1. **R1:** Eight core component files; game_entity.gd; runtime game_runtime/entity_factory/room_catalog/resource_catalog; scripts/main.gd; input/movement/materialization/animation/camera systems; grand_lobby.json; scenes/main.tscn and game_world.tscn; InputMap only; matching runtime/system tests. Prove registration, safe materialization, body collision, frame animation, camera and single/double-jump envelopes before combat.
2. **M01:** Six combat component files; enemy_ai/combat/damage/effect systems and corresponding tests; card_banquet_gallery.json. Integration edits ONLY R1 game_runtime, entity_factory, resource_catalog, movement/materialization/animation systems, c_motion/c_visual/c_input/c_session, grand_lobby.json and matching tests. Prove all three AIs, timing, legitimate damage, resource/cooldown negatives and cleanup.
3. **M02:** Four progression component files; interaction/progression/save/boss systems; runtime save_repository; roulette_clocktower/quiet_save_room/house_throne JSON; corresponding system/repository tests and test_room_progression.gd. Integration edits ONLY game_runtime/entity_factory/room_catalog/resource_catalog, movement/materialization/animation/combat/damage/effect systems, c_session/c_motion/c_input/c_visual, Lobby/Gallery data and matching tests. Prove connected normal route, unchanged balcony gate, validated restore, two boss phases and legitimate ending state.
4. **M03:** c_ui_state, ui_system and test_ui_system/test_session_flow; title_screen/hud/pause_overlay/map_overlay/death_screen/ending_screen controllers and matching UI scenes; casino_theme.tres; export_presets.cfg; docs/BUILD-AND-PLAY.md; exporter-produced build/web bundle. Integration edits ONLY scripts/main, game_runtime/input_system/save_system/save_repository, interaction_system for edge-safe prompt positioning only, c_session/c_input, main/game_world scenes, project input/display/Web rendering/export configuration and matching tests. Preserve main_scene path, autoloads and plugins. Prove UI/modal clocks, native and real browser behavior, durable reload, bundle inventory.

Read-only reviewer checks data-writer ownership and the acyclic chain: registered data → deferred materialization → movement placement/physics → damage/progression → presentation. Every node consumer checks readiness. Evaluator alone owns e2e and final native/Web evidence. No edits to framework/addons, archived tags, root MEMORY/memory or reference images; no invented human confirmation or final acceptance.

## Asset Hints

Use PLAN Runtime Asset Assignments without new mappings: heroine_frames (92–108 px body, seven actions), dealer_frames (105–130 px, four actions), boss_frames (260–320 px, idle/attack), three distant plates, illustrated platform cap/middle/cap, casino_props, casino_small_props, ghost_hand and verified Chinese UI font. ResourceCatalog binds final ASSETS paths only after verification. Procedural UI and bounded slash/impact/telegraph effects are intentional; they cannot substitute for illustrated actors or terrain. No music/recorded SFX this tag.

## Web Persistence Adapter

For M03, SaveRepository keeps native FileAccess behavior and uses a single bounded, versioned localStorage value on Web through documented JavaScriptBridge.eval. The wrapper catches property-access, policy and quota errors; embeds JSON using safe serialization; and returns a JSON status string after exact readback. No guessed engine FS globals, timer-based durability claims or remote service. Startup retrieval goes through the same payload validator before any new-state write. Success means acknowledged storage in the tested browser/origin, not permanent backup; same-origin reload and reopen are verified independently.
