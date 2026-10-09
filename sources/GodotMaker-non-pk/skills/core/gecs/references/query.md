# Query, Relationship & Observer API Reference

This file covers three interconnected systems: QueryBuilder for finding entities,
Relationships for entity linking, and Observers for reactive component events.

## Table of Contents

- [QueryBuilder](#querybuilder)
  - [Chain Methods](#chain-methods)
  - [Execution](#execution)
  - [iterate() Batch Access](#iterate-batch-access)
  - [Component Property Queries](#component-property-queries)
  - [Query Performance](#query-performance)
- [Relationship](#relationship)
  - [Creating Relationships](#creating-relationships)
  - [Target Types](#target-types)
  - [Querying Relationships](#querying-relationships)
  - [Relationship Factory Pattern](#relationship-factory-pattern)
- [Observer](#observer)
  - [Defining an Observer](#defining-an-observer)
  - [Observer Callbacks](#observer-callbacks)

---

## QueryBuilder

QueryBuilder provides chain-based entity filtering. Access via `q` in Systems or
`ECS.world.query` anywhere. Results are automatically cached at the archetype level.

### Chain Methods

#### with_all(components: Array) -> QueryBuilder

Entities must have ALL specified components.

```gdscript
q.with_all([C_Health, C_Position])  # must have both
```

#### with_any(components: Array) -> QueryBuilder

Entities must have at least ONE of the specified components.

```gdscript
q.with_any([C_Player, C_Enemy])  # player OR enemy
```

#### with_none(components: Array) -> QueryBuilder

Entities must NOT have any of the specified components.

```gdscript
q.with_none([C_Dead, C_Invulnerable])  # exclude dead and invulnerable
```

#### enabled() -> QueryBuilder

Only enabled entities (default includes all).

```gdscript
q.with_all([C_Health]).enabled()  # skip disabled entities
```

#### disabled() -> QueryBuilder

Only disabled entities.

```gdscript
q.with_all([C_Health]).disabled()  # only disabled entities
```

#### with_relationship(relationships: Array) -> QueryBuilder

Entities must have ALL specified relationships.

```gdscript
q.with_relationship([Relationship.new(R_ChildOf.new(), parent)])
```

#### without_relationship(relationships: Array) -> QueryBuilder

Entities must NOT have any of the specified relationships.

```gdscript
q.without_relationship([Relationship.new(R_Poisoned.new(), null)])
```

#### with_group(groups: Array[String]) -> QueryBuilder

Filter by Godot groups. **Avoid in performance-critical code** — uses SceneTree
traversal (~50x slower than component queries).

```gdscript
q.with_group(["player"])  # SLOW — prefer q.with_all([C_Player])
```

#### without_group(groups: Array[String]) -> QueryBuilder

Exclude entities in specified Godot groups.

#### iterate(components: Array) -> QueryBuilder

Specifies component order for batch processing. The `components` array in `process()`
will contain arrays of components in the same order.

```gdscript
q.with_all([C_Velocity, C_Health]).iterate([C_Velocity, C_Health])
# components[0] = C_Velocity array, components[1] = C_Health array
```

#### combine(other: QueryBuilder) -> QueryBuilder

Merge another query's criteria into this one.

### Execution

#### execute() -> Array

Returns all matching entities. Results are cached and reused until a structural change
invalidates the cache.

```gdscript
var enemies = ECS.world.query.with_all([C_Enemy, C_Health]).execute()
```

#### execute_one() -> Entity

Returns the first matching entity or `null`. Convenience for singleton-like entities.

```gdscript
var player = ECS.world.query.with_all([C_Player]).execute_one()
```

#### matches(entities: Array) -> Array

Filters a provided entity array against the query criteria. Does not query the world,
just applies filters to the given list.

```gdscript
var alive_enemies = q.with_none([C_Dead]).matches(all_enemies)
```

#### archetypes() -> Array[Archetype]

Returns matching archetypes directly — skip entity flattening for column-based iteration.
Advanced usage for maximum performance.

### iterate() Batch Access

`iterate()` enables cache-friendly column access — components are read directly from
archetype storage instead of per-entity dictionary lookups.

```gdscript
class_name TransformSyncSystem extends System

func query() -> QueryBuilder:
    return q.with_all([C_Transform]).iterate([C_Transform])

func process(entities: Array[Entity], components: Array, delta: float):
    var transforms = components[0]  # Array of C_Transform
    for i in entities.size():
        entities[i].global_transform = transforms[i].transform
```

When the query matches multiple archetypes, `process()` is called once per archetype.
This is transparent — just iterate as normal.

### Component Property Queries

Filter entities by component property values using dictionary syntax:

```gdscript
# Health >= 50
var healthy = ECS.world.query.with_all([
    {C_Health: {'current': {"_gte": 50}}}
]).execute()

# Speed exactly 100
var fast = ECS.world.query.with_all([
    {C_Speed: {'value': {"_eq": 100}}}
]).execute()
```

#### Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `_eq` | Equal | `{"_eq": 100}` |
| `_ne` | Not equal | `{"_ne": 0}` |
| `_gt` | Greater than | `{"_gt": 50}` |
| `_lt` | Less than | `{"_lt": 10}` |
| `_gte` | Greater than or equal | `{"_gte": 50}` |
| `_lte` | Less than or equal | `{"_lte": 100}` |
| `_in` | Value in array | `{"_in": [1, 2, 3]}` |
| `_nin` | Value not in array | `{"_nin": ["dead", "disabled"]}` |
| `func` | Custom Callable | `{"func": my_filter_func}` |

Component queries are post-filter operations — the archetype cache narrows candidates,
then property checks run per-entity.

### Query Performance

Performance ranking (10K entities, Godot 4.6):

| Method | Time | Notes |
|--------|------|-------|
| `.enabled()` / `.disabled()` | ~0.11ms | Constant time (bitset) |
| `.with_all([Components])` | ~0.24ms | Archetype indexed, excellent |
| `.with_any([Components])` | ~0.31ms | Slightly more work |
| Component property queries | Varies | Post-filter per entity |
| `.with_group(["name"])` | ~13.6ms | SceneTree traversal, avoid! |

**Rules of thumb:**
- Use tag components (`C_Player`, `C_Enemy`) instead of Godot groups for queries
- Use `iterate()` for systems processing many entities
- Queries are automatically cached — don't worry about calling `query()` each frame

---

## Relationship

Relationships link entities together as typed pairs: `(relation_component, target)`.
They are stored on the source entity and indexed at the archetype level for efficient queries.

### Creating Relationships

```gdscript
# Relationship component (just a tag component with R_ prefix)
class_name R_ChildOf extends Component
class_name R_Attacks extends Component
class_name R_Equips extends Component

# Add to entity
entity.add_relationship(Relationship.new(R_ChildOf.new(), parent_entity))
entity.add_relationship(Relationship.new(R_Attacks.new(), target_entity))
```

### Target Types

| Target | Example | Matching |
|--------|---------|----------|
| Entity | `Relationship.new(R_ChildOf.new(), parent)` | Exact entity match |
| Component type | `Relationship.new(R_Buff.new(), C_Fire)` | Type-level matching |
| Script | `Relationship.new(R_Targets.new(), C_Enemy)` | Script reference |
| `null` (wildcard) | `Relationship.new(R_ChildOf.new(), null)` | Any target |

### Querying Relationships

```gdscript
# Query entities with a specific relationship
var children = ECS.world.query.with_relationship([
    Relationship.new(R_ChildOf.new(), parent_entity)
]).execute()

# Wildcard — any entity with R_ChildOf, regardless of target
var all_children = ECS.world.query.with_relationship([
    Relationship.new(R_ChildOf.new(), null)
]).execute()

# Exclude relationships
var orphans = ECS.world.query.without_relationship([
    Relationship.new(R_ChildOf.new(), null)
]).execute()

# Component property queries on relationships
var high_damage = ECS.world.query.with_relationship([
    Relationship.new({C_Damage: {'amount': {"_gte": 50}}}, target)
]).execute()

# Query both relation AND target properties
var strong_buffs = ECS.world.query.with_relationship([
    Relationship.new(
        {C_Buff: {'duration': {"_gt": 10}}},
        {C_Player: {'level': {"_gte": 5}}}
    )
]).execute()
```

### Limited removal

Remove a specific number of matching relationships:

```gdscript
entity.remove_relationship(Relationship.new(R_Buff.new(), null), 1)   # remove 1
entity.remove_relationship(Relationship.new(R_Buff.new(), null), 3)   # remove up to 3
entity.remove_relationship(Relationship.new(R_Buff.new(), null))      # remove all (default)

# Remove with property matching
entity.remove_relationship(
    Relationship.new({C_Damage: {'amount': {"_gt": 20}}}, null),
    2  # remove up to 2 high-damage effects
)
```

### Relationship Factory Pattern

Centralize relationship construction in a static class:

```gdscript
# rels.gd
class_name Rels

static var child_of := Relationship.new(R_ChildOf.new(), null)
static var attacks := Relationship.new(R_Attacks.new(), null)
static var equips := Relationship.new(R_Equips.new(), null)

static func child_of_entity(parent: Entity) -> Relationship:
    return Relationship.new(R_ChildOf.new(), parent)

static func attacks_target(target: Entity) -> Relationship:
    return Relationship.new(R_Attacks.new(), target)
```

```gdscript
# Usage in systems — clean, no inline Relationship construction
func process(entities: Array[Entity], components: Array, delta: float):
    for entity in entities:
        if entity.has_relationship(Rels.attacks):
            apply_attack(entity)
        entity.remove_relationship(Rels.child_of, 1)
```

### Relationship best practices

- **Use R_ prefix** for relationship components: `R_ChildOf`, `R_Attacks`, `R_Equips`
- **Cache relationship patterns** in a Rels factory class to avoid inline `Relationship.new()`
- **Watch for archetype explosion** — each unique `(RelationType, Target)` pair creates an archetype.
  If you have 1000 entities each with `R_Targets(unique_enemy)`, that's 1000 archetypes.
  Use wildcard queries when exact target matching isn't needed.
- **Validate before removal** — check `get_relationships()` count before partial removal

---

## Observer

Observers are reactive systems that trigger on component lifecycle events — add, remove,
or property change. Unlike Systems that run every frame, Observers fire only when
the watched event occurs.

### Defining an Observer

```gdscript
class_name HealthUIObserver extends Observer

# Which component to watch
func watch() -> Resource:
    return C_Health

# Optional: only fire for entities matching this query
func match() -> QueryBuilder:
    return q.with_all([C_Health, C_UIHealthBar])

# Callbacks
func on_component_added(entity: Entity, component: Resource) -> void:
    # C_Health was added to an entity with C_UIHealthBar
    update_health_bar(entity)

func on_component_removed(entity: Entity, component: Resource) -> void:
    # C_Health was removed — hide health bar
    hide_health_bar(entity)

func on_component_changed(entity: Entity, component: Resource,
        property: String, new_value: Variant, old_value: Variant) -> void:
    # A property on C_Health changed
    if property == "current":
        update_health_bar_value(entity, new_value)
```

### Observer Callbacks

| Callback | When it fires | Entity state |
|----------|--------------|--------------|
| `on_component_added` | Component added to entity | Entity has the component |
| `on_component_removed` | Component removed or entity destroyed | Entity still valid, component accessible |
| `on_component_changed` | `@export` property value changes | Entity and component valid |

### watch() -> Resource

Returns the Component class to observe. Called once at registration, result is cached.

### match() -> QueryBuilder

Optional query filter. If provided, callbacks only fire for entities that match
this query at the time of the event. If not overridden, fires for all entities.

### Registration

Observers are registered with the World, either via scene tree (auto-discovered under
`system_nodes_root`) or programmatically:

```gdscript
var observer = HealthUIObserver.new()
ECS.world.add_observer(observer)

# Later:
ECS.world.remove_observer(observer)
```

### Observer vs System

| Aspect | System | Observer |
|--------|--------|----------|
| Execution | Every frame (or tick rate) | Only on component events |
| Query | Runs query each frame | Caches watch() at registration |
| Use case | Continuous processing | React to state changes |
| Example | Movement, AI, rendering | UI updates, sound triggers, logging |

Use Observers when you need to react to specific component changes rather than
polling every frame. This is more efficient for events that happen infrequently.
