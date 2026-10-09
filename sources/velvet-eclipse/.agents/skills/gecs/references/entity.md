# Entity API Reference

Entity is the fundamental building block in gecs. An Entity **extends Node** —
it lives in the Godot scene tree and can have child nodes, transforms, groups, etc.
Entities hold Components (data) and Relationships (links to other entities).

## Table of Contents

- [Properties](#properties)
- [Component Methods](#component-methods)
- [Relationship Methods](#relationship-methods)
- [Lifecycle Hooks](#lifecycle-hooks)
- [Signals](#signals)
- [Entity Prefabs](#entity-prefabs)
- [Spawning Patterns](#spawning-patterns)
- [Best Practices](#best-practices)

## Properties

| Property | Type | Description |
|----------|------|-------------|
| `id` | `String` | Unique ID (auto-generated UUID if blank). Must be unique within a World |
| `enabled` | `bool` | Whether entity appears in queries (default `true`) |
| `component_resources` | `Array[Component]` | Components assigned in the editor Inspector |
| `components` | `Dictionary` | Runtime component storage `{script_instance_id: Component}` |
| `relationships` | `Array[Relationship]` | All relationships on this entity |
| `ecs_id` | `int` | Stable numeric ID assigned by World (0 until registered) |
| `serialize_config` | `GECSSerializeConfig` | Per-entity serialization override (optional) |

## Component Methods

### add_component(component: Resource) -> void

Adds a component instance. If a component of the same type already exists, removes
the old one first (replacement semantics).

```gdscript
entity.add_component(C_Health.new(100))
entity.add_component(C_Velocity.new(Vector3.UP))
```

### add_components(components: Array)

Batch add — single archetype transition instead of one per component. More efficient
for adding multiple components at once.

```gdscript
entity.add_components([C_Health.new(), C_Velocity.new(), C_Input.new()])
```

### remove_component(component: Resource) -> void

Removes a component instance. Pass the actual instance, not the class.

```gdscript
var health = entity.get_component(C_Health)
entity.remove_component(health)
```

### remove_components(components: Array)

Batch remove — single archetype transition. Accepts both instances and Script classes.

```gdscript
entity.remove_components([C_Health, C_Velocity])  # classes work too
```

### remove_all_components() -> void

Removes every component from the entity.

### get_component(component: Resource) -> Component

Returns the component instance or `null`. **Pass the class (Script), not an instance.**

```gdscript
var health = entity.get_component(C_Health)  # correct
if health:
    health.current -= 10
```

### has_component(component: Resource) -> bool

Fast existence check without retrieving the component. **Pass the class.**

```gdscript
if entity.has_component(C_Invulnerable):
    return  # skip damage
```

## Relationship Methods

### add_relationship(relationship: Relationship) -> void

```gdscript
entity.add_relationship(Relationship.new(R_ChildOf.new(), parent))
```

### add_relationships(relationships: Array)

Batch add — single archetype transition for all relationships.

### remove_relationship(relationship: Relationship, limit: int = -1) -> void

Removes matching relationships. `limit` controls how many:
- `-1` (default) = remove all matching
- `0` = remove none
- `>0` = remove up to that many

```gdscript
entity.remove_relationship(Relationship.new(R_Buff.new(), null), 1)  # remove 1 buff
entity.remove_relationship(Relationship.new(R_Effect.new(), null))   # remove all effects
```

### remove_relationships(relationships: Array, limit: int = -1)

Batch removal with per-type limit.

### get_relationship(relationship: Relationship) -> Relationship

Returns the first matching Relationship or `null`. Auto-cleans invalid relationships.

### get_relationships(relationship: Relationship) -> Array[Relationship]

Returns all matching Relationships.

### has_relationship(relationship: Relationship) -> bool

Fast check — skips validation/cleanup (use `get_relationship` when you need the value).

```gdscript
if entity.has_relationship(Relationship.new(R_Poisoned.new(), null)):
    apply_poison_damage(entity)
```

### remove_all_relationships() -> void

Removes all relationships from the entity.

## Lifecycle Hooks

Override these in your Entity subclass:

### define_components() -> Array

Return default components for this entity type. Called during `_initialize()`.
**Always return fresh `.new()` instances** — shared instances cause state leakage.

```gdscript
class_name Enemy extends Entity
func define_components() -> Array:
    return [C_Health.new(50), C_Transform.new(), C_AI.new()]
```

### on_ready() -> void

Called after all components are initialized. Use for post-init setup like syncing
scene transforms to components or adding to groups.

```gdscript
func on_ready():
    if has_component(C_Transform):
        var t = get_component(C_Transform)
        t.transform = global_transform
    add_to_group("enemies")
```

### on_destroy() -> void

Called right before the entity is freed. Use for cleanup.

### on_disable() -> void

Called when the entity is disabled via `World.disable_entity()`.

### on_enable() -> void

Called when the entity is re-enabled via `World.enable_entity()`.

## Signals

| Signal | Parameters | When |
|--------|-----------|------|
| `component_added` | `(entity: Entity, component: Resource)` | After a component is added |
| `component_removed` | `(entity: Entity, component: Resource)` | After a component is removed |
| `component_property_changed` | `(entity, component, property_name, old_value, new_value)` | When an @export property changes |
| `relationship_added` | `(entity: Entity, relationship: Relationship)` | After a relationship is added |
| `relationship_removed` | `(entity: Entity, relationship: Relationship)` | After a relationship is removed |
| `relationships_batch_added` | `(entity: Entity, relationships: Array)` | After batch add via `add_relationships()` |
| `relationships_batch_removed` | `(entity: Entity, relationships: Array)` | After batch remove via `remove_relationships()` |

## Entity Prefabs

Entities can be set up three ways, from most visual to most programmatic:

### Method 1: Inspector Assignment (Recommended for designers)

Create a `.tscn` with an Entity-derived root node. Add components to the
`component_resources` array in the Inspector. Components appear as editable Resources
with their `@export` properties visible.

```
e_player.tscn:
+-- Player (Entity root, script: e_player.gd)
    +-- MeshInstance3D
    +-- CollisionShape3D
    +-- AnimationPlayer
```

In Inspector: `component_resources = [C_Health(100, 100), C_Transform(), C_Input()]`

### Method 2: define_components() (Recommended for code-first)

```gdscript
class_name Player extends Entity
func define_components() -> Array:
    return [C_Health.new(100), C_Transform.new(), C_Input.new()]
```

### Method 3: Hybrid

Core components via Inspector, conditional components via code:

```gdscript
func on_ready():
    if has_component(C_Transform):
        get_component(C_Transform).transform = global_transform
    if GameState.is_multiplayer:
        add_component(C_NetworkSync.new())
```

**Priority order:** Components added before `_initialize()` are re-added via signals.
`component_resources` (Inspector) and `define_components()` (code) are merged.
Components passed to `World.add_entity(entity, [extra_components])` override everything.

## Spawning Patterns

### Basic spawning

```gdscript
const ENEMY_PREFAB = preload("res://entities/enemies/e_enemy.tscn")

func spawn_enemy(pos: Vector3) -> Entity:
    var enemy = ENEMY_PREFAB.instantiate() as Entity
    enemy.global_position = pos
    get_tree().current_scene.add_child(enemy)
    ECS.world.add_entity(enemy)
    return enemy
```

### Spawner System

```gdscript
class_name SpawnerSystem extends System
func query():
    return q.with_all([C_SpawnPoint])

func process(entities: Array[Entity], components: Array, delta: float):
    for entity in entities:
        var sp = entity.get_component(C_SpawnPoint)
        if sp.should_spawn():
            var spawned = sp.prefab.instantiate() as Entity
            spawned.global_position = entity.global_position
            get_tree().current_scene.add_child(spawned)
            ECS.world.add_entity(spawned)
            sp.mark_spawned()
```

### Prefab registry

```gdscript
class_name PrefabRegistry
static var prefabs = {
    "player": preload("res://entities/gameplay/e_player.tscn"),
    "enemy": preload("res://entities/enemies/e_enemy.tscn"),
}

static func spawn(name: String, pos: Vector3) -> Entity:
    var entity = prefabs[name].instantiate() as Entity
    entity.global_position = pos
    get_tree().current_scene.add_child(entity)
    ECS.world.add_entity(entity)
    return entity
```

## Best Practices

- **Keep Entity scripts thin** — `on_ready()` is glue code for initialization, not gameplay logic.
  Gameplay belongs in Systems.
- **Prefer `define_components()`** for components that every instance of this entity type needs.
  Use `component_resources` Inspector for designer-tweakable defaults.
- **Use `add_components()` / `remove_components()`** for batch operations to minimize archetype transitions.
- **Extend from CharacterBody3D trick**: Since Entity extends Node, you can create a scene
  with a CharacterBody3D root and attach your Entity script to it — you get both Entity features
  and CharacterBody3D physics.
