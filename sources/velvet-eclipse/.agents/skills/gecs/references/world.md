# World API Reference

World **extends Node** and manages all entities, systems, and observers. It provides
the query engine, archetype storage, and orchestrates system execution.

## Table of Contents

- [Properties](#properties)
- [Initialization](#initialization)
- [Entity Management](#entity-management)
- [System Management](#system-management)
- [Observer Management](#observer-management)
- [Processing](#processing)
- [Entity Lookup](#entity-lookup)
- [Signals](#signals)
- [Cleanup](#cleanup)

## Properties

| Property | Type | Description |
|----------|------|-------------|
| `entities` | `Array[Entity]` | All entities in the world |
| `systems` | `Array[System]` | All systems (flattened from all groups) |
| `observers` | `Array[Observer]` | All registered observers |
| `systems_by_group` | `Dictionary[String, Array]` | Systems organized by group name |
| `entity_nodes_root` | `NodePath` | Where entity nodes are placed in scene tree |
| `system_nodes_root` | `NodePath` | Where system nodes are placed in scene tree |
| `query` | `QueryBuilder` | Fresh QueryBuilder for ad-hoc queries |
| `entity_id_registry` | `Dictionary` | String ID -> Entity mapping |
| `default_serialize_config` | `GECSSerializeConfig` | Default serialization config |

## Initialization

World auto-initializes in `_ready()`:
1. Creates entity/system root nodes if not specified
2. Finds and registers all System children under `system_nodes_root`
3. Finds and registers all Observer children
4. Finds and registers all Entity children under `entity_nodes_root`

### Scene setup pattern

```
Main.tscn
+-- World (World node)
+-- DefaultSystems (Node, instantiated from default_systems.tscn)
|   +-- input (SystemGroup)
|   |   +-- PlayerControlsSystem
|   +-- gameplay (SystemGroup)
|       +-- HealthSystem
+-- Level (Node3D)
+-- Entities (Node3D)
```

```gdscript
# main.gd
@onready var world: World = $World

func _ready():
    ECS.world = world  # triggers finalize_system_setup()
```

### Deferred system setup

System `setup()` methods are deferred until `ECS.world` is assigned. This ensures
that `setup()` can safely access `ECS.world`. The sequence:

1. `World._ready()` calls `initialize()` -> registers systems with `_world` reference
2. User sets `ECS.world = world` -> triggers `finalize_system_setup()`
3. `finalize_system_setup()` calls `setup()` on all deferred systems

## Entity Management

### add_entity(entity: Entity, components = null, add_to_tree = true) -> void

Adds an entity to the world. Generates a UUID if `entity.id` is blank. If an entity
with the same ID exists, it replaces the old one.

```gdscript
var player = Player.new()
ECS.world.add_entity(player)

# With extra components
ECS.world.add_entity(player, [C_Buff.new(), C_Shield.new()])

# Skip auto-adding to scene tree (if already in tree)
ECS.world.add_entity(player, null, false)
```

The method:
1. Assigns UUID if needed, registers ID
2. Connects entity signals (component/relationship changes)
3. Adds to scene tree under `entity_nodes_root` (if `add_to_tree`)
4. Creates archetype entry
5. Calls `entity._initialize(components)` which runs `define_components()` + `on_ready()`
6. Runs entity preprocessors
7. Emits `entity_added` signal

### add_entities(entities: Array, components = null)

Batch add — suppresses cache invalidation until all entities are added.

### remove_entity(entity: Entity) -> void

Removes an entity completely:

1. Runs entity postprocessors
2. Cleans up relationships pointing TO this entity from other entities
3. Disconnects all signals
4. Notifies observers of each component removal (entity still valid during callbacks)
5. Emits `entity_removed`
6. Removes from entity list and archetype
7. Calls `entity.on_destroy()`
8. `queue_free()` (or `free()` if not in tree)

```gdscript
ECS.world.remove_entity(entity)
```

### remove_entities(entities: Array)

Batch remove with suppressed cache invalidation.

### disable_entity(entity) -> Entity

Disables without removing. Entity stays in world but excluded from default queries.
Disconnects signals, calls `on_disable()`, stops processing.

```gdscript
ECS.world.disable_entity(entity)
# entity.enabled == false
# Still in ECS.world.entities, but not in query results (unless using .disabled())
```

### enable_entity(entity: Entity, components = null) -> void

Re-enables a disabled entity. Reconnects signals, calls `on_enable()`, resumes processing.

```gdscript
ECS.world.enable_entity(entity)
# Optionally add components on enable:
ECS.world.enable_entity(entity, [C_Respawned.new()])
```

## System Management

### add_system(system: System, topo_sort: bool = false) -> void

Registers a system. If `ECS.world` is already set, calls `setup()` immediately.
Otherwise defers until `finalize_system_setup()`.

```gdscript
var combat = CombatSystem.new()
combat.group = "gameplay"
ECS.world.add_system(combat, true)  # true = topological sort after adding
```

### add_systems(systems: Array, topo_sort: bool = false)

Batch add. Topological sort runs once after all systems are added.

### remove_system(system, topo_sort: bool = false) -> void

Removes and `queue_free()`s the system.

### remove_systems(systems: Array, topo_sort: bool = false)

Batch remove.

### remove_system_group(group: String, topo_sort: bool = false)

Removes all systems in a group.

## Observer Management

### add_observer(observer: Observer) -> void

Registers an Observer. Initializes its QueryBuilder and caches its `watch()` result.

### add_observers(observers: Array)

Batch register.

### remove_observer(observer: Observer) -> void

Unregisters and `queue_free()`s the observer.

## Processing

### process(delta: float, group: String = "") -> void

Runs all active systems in the specified group. If `group` is empty, runs the default
(unnamed) group.

```gdscript
func _process(delta):
    ECS.process(delta, "input")      # or ECS.world.process(delta, "input")
    ECS.process(delta, "gameplay")

func _physics_process(delta):
    ECS.process(delta, "physics")
    ECS.process(delta, "run-last")
```

Processing sequence per group:
1. Reset frame performance metrics
2. Advance all unique SystemTimers for this group
3. For each active system: call `system._handle(delta)`
4. Flush PER_GROUP command buffers

### flush_command_buffers() -> void

Executes all pending commands from systems with `FlushMode.MANUAL`.

```gdscript
func _process(delta):
    ECS.process(delta, "physics")
    ECS.process(delta, "render")
    ECS.world.flush_command_buffers()  # flush all MANUAL commands
```

### update_pause_state(paused: bool) -> void

Updates pause behavior for all systems based on their `process_mode`.

## Entity Lookup

### get_entity_by_id(id: String) -> Entity

O(1) lookup by string ID. Returns `null` if not found.

```gdscript
var player = ECS.world.get_entity_by_id("player-uuid-here")
```

### has_entity_with_id(id: String) -> bool

Check if an entity with the given ID exists.

## Signals

| Signal | Parameters | When |
|--------|-----------|------|
| `entity_added` | `(entity: Entity)` | After entity is fully initialized |
| `entity_removed` | `(entity: Entity)` | During entity removal |
| `entity_enabled` | `(entity: Entity)` | After entity is re-enabled |
| `entity_disabled` | `(entity: Entity)` | After entity is disabled |
| `system_added` | `(system: System)` | After system registration |
| `system_removed` | `(system: System)` | After system removal |
| `component_added` | `(entity, component)` | When any entity gains a component |
| `component_removed` | `(entity, component)` | When any entity loses a component |
| `component_changed` | `(entity, component, property, new_value, old_value)` | Property change on any component |
| `relationship_added` | `(entity, relationship)` | When any entity gains a relationship |
| `relationship_removed` | `(entity, relationship)` | When any entity loses a relationship |
| `cache_invalidated` | — | When query cache is cleared (structural change) |

## Cleanup

### purge(should_free = true, keep := []) -> void

Removes all entities and systems. Optionally keeps specific entities.

```gdscript
# Full cleanup
ECS.world.purge()

# Keep player entity
ECS.world.purge(true, [player_entity])

# Clean but don't free the World node
ECS.world.purge(false)
```

The method:
1. Removes all entities (except `keep` list)
2. Clears archetype storage and relationship indexes
3. Removes all systems
4. Removes all observers
5. Invalidates all caches
6. `queue_free()` the World node (if `should_free`)

## Performance Notes

- World uses **archetype-based storage** — entities with the same component set share an archetype
- Query results are cached at the archetype level, not entity level — rarely invalidated
- Cache invalidation is suppressed during batch operations (`add_entities`, `remove_entities`)
- In debug mode, cache stats are available via `get_cache_stats()` / `reset_cache_stats()`
- Archetype count > 500 triggers an explosion warning (check for unintended relationship cardinality)
