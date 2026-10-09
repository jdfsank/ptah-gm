# gecs Gotchas

**Read before writing ECS code.** Each gotcha has a one-line rule and fix. For code examples, grep `gotchas-examples.md` by ID (e.g. `## G1.`).

| ID | Gotcha | Rule |
|----|--------|------|
| G1 | Entity extends Node, not Node2D — no `position` property | Store position in a Component. Never use `entity.position`. |
| G2 | `get_component()` returns null before `add_entity()` | Always call `add_entity()` before `get_component()`. Also applies to `on_ready()` — if `add_child(entity)` triggers `on_ready()` before component values are set, components will have default values. Set component values AFTER `add_entity()`, not in `on_ready()`. |
| G3 | World only scans systems once at `_ready` | Add systems to World **before** `add_child(world)`, or use `add_system()`. |
| G4 | `system_nodes_root` unset → systems silently skip | Set `system_nodes_root = NodePath(".")` and `entity_nodes_root = NodePath(".")` on World. |
| G5 | `process()` called once per archetype, not once total | Never use local vars for cross-entity state. Use instance vars + `_process()` cleanup. |
| G6 | `add_entity()` overrides manual `add_child()` placement | Don't manually place entities. Let World own the node tree. |
| G7 | `ECS.world = $Node` silently assigns null (type check) | Use `ECS.set("world", node)` then `assert(ECS.world != null)`. |
| G8 | Entity subclasses need `@tool` if Entity base has it | Every `extends Entity` script needs `@tool` at the top. |
| G9 | New `class_name` not recognized until import | Run `godot --headless --import` after creating any `.gd` with `class_name`. |
| G10 | `system.process()` in tests: Array[Entity] type error + CommandBuffer not flushed | Use `ECS.world.process(delta)` in tests, or test static functions only. Never call `process()` directly. **DO NOT write `test_system_has_query`** — this test pattern always crashes because `q` is null outside World. |
| G11 | Autoload name collision crashes gecs or misroutes `get_node()` | Never use `World`, `Entity`, `Component`, `System` as autoload names. Scene root node names must also differ from all autoload names — Godot resolves `/root/Name` to the autoload first. |
| G12 | `find_children` misses code-added nodes (owned=true default) | Pass `owned=false`: `find_children("*", "System", true, false)`. May need to patch gecs `world.gd`. |
| G13 | Entity auto-names (`@Node@2`) break E2E paths | Set `entity.name = "MyName"` before `add_entity()`. |
| G14 | `system.q` is null when System not attached to World | QueryBuilder `q` is only initialized when the System enters the World scene tree. **DO NOT write `test_system_has_query` tests** — they always crash. Test systems via `ECS.world.process()` or test static helper functions. |
| G15 | `World.add_system()` second param is `bool`, not group name | `add_system(system, true)` enables topological sort. To set group: `system.group = "gameplay"` BEFORE `add_system()`. |
| G16 | `world.process(delta)` without group silently skips grouped systems | If systems have a `group` property set, you MUST call `world.process(delta, "group_name")`. Calling without group only processes ungrouped systems. |
| G17 | NodePath `@export` in `.tscn` unreliable for gecs World | `entity_nodes_root` and `system_nodes_root` set via `.tscn` `node_paths=PackedStringArray(...)` may not apply before `_ready()`. Set them in `_init()` instead. |
| G18 | Area2D overlap data only updates in `_physics_process` | `get_overlapping_bodies()`/`get_overlapping_areas()` return stale data in `_process`. Systems using Area2D overlap MUST run in the `physics` group. |
| G19 | GDScript `:=` type inference fails with ternary + null | `var x := expr if cond else fallback` fails when types are ambiguous. Use explicit type: `var x: Vector2 = expr if cond else fallback`. |
| G20 | `@export var x: Node` on Component fails to parse | Component extends Resource; Node fields cannot be `@export`-ed on Resource-derived classes. Use `var x: Node = null` (runtime ref, not serialized) and resolve via NodeRef component or system query. |
