# Patterns, Conventions & ECS_DESIGN Cross-Reference

Cross-cutting patterns that span multiple gecs classes, project organization conventions,
and how gecs maps to our ECS_DESIGN.md architectural decisions.

## Table of Contents

- [Naming Conventions](#naming-conventions)
- [File Organization](#file-organization)
- [Main Scene Architecture](#main-scene-architecture)
- [PendingDelete Pattern](#pendingdelete-pattern)
- [Transform Synchronization](#transform-synchronization)
- [Relationship Factory](#relationship-factory)
- [Pure-Static Helpers and Test Seams](#pure-static-helpers-and-test-seams)
- [ECS_DESIGN.md Cross-Reference](#ecs_designmd-cross-reference)

## Naming Conventions

| Type | Class Name | File Name | Example |
|------|-----------|-----------|---------|
| Component | `C_PascalCase` | `c_snake_case.gd` | `C_Health` / `c_health.gd` |
| System | `PascalCaseSystem` | `s_snake_case.gd` | `MovementSystem` / `s_movement.gd` |
| Entity | `PascalCase` | `e_snake_case.gd` | `Player` / `e_player.gd` |
| Observer | `PascalCaseObserver` | `o_snake_case.gd` | `HealthUIObserver` / `o_health_ui.gd` |
| Relationship comp | `R_PascalCase` | `r_snake_case.gd` | `R_ChildOf` / `r_child_of.gd` |
| Relationship factory | `Rels` | `rels.gd` | Static helper class |

## File Organization

Organize ECS files by domain/theme, not by ECS type:

```
project/
+-- components/
|   +-- ai/              # AI-related components
|   +-- combat/          # Combat components (C_Health, C_Damage, C_Armor)
|   +-- gameplay/        # Core gameplay (C_Transform, C_Velocity)
|   +-- rendering/       # Visual (C_Sprite, C_Animation)
|   +-- relationships/   # Relationship components (R_ChildOf, R_Equips)
|   +-- ui/              # UI components
+-- entities/
|   +-- enemies/         # Enemy entity scripts + scenes
|   +-- gameplay/        # Core entities (Player, Projectile)
|   +-- items/           # Item entities
+-- systems/
|   +-- combat/          # Combat systems
|   +-- core/            # Core systems (TransformSync, PendingDelete)
|   +-- input/           # Input handling systems
|   +-- physics/         # Physics systems
|   +-- ui/              # UI systems
+-- observers/
|   +-- o_health_ui.gd   # Reactive systems
```

## Main Scene Architecture

The recommended scene tree structure:

```
Main.tscn
+-- World (World node)
+-- DefaultSystems (instantiated from default_systems.tscn)
|   +-- run-first (SystemGroup)
|   |   +-- InitSystem
|   +-- input (SystemGroup)
|   |   +-- PlayerControlsSystem
|   |   +-- AIDecisionSystem
|   +-- gameplay (SystemGroup)
|   |   +-- HealthSystem
|   |   +-- CombatSystem
|   |   +-- SpawnerSystem
|   +-- physics (SystemGroup)
|   |   +-- MovementSystem
|   |   +-- CollisionSystem
|   |   +-- TransformSyncSystem
|   +-- ui (SystemGroup)
|   |   +-- UIVisibilitySystem
|   +-- debug (SystemGroup)
|   |   +-- DebugLabelSystem
|   +-- run-last (SystemGroup)
|       +-- PendingDeleteSystem
+-- Level (Node3D — level geometry)
+-- Entities (Node3D — spawned entities go here)
```

### main.gd

```gdscript
extends Node

@onready var world: World = $World

func _ready():
    ECS.world = world  # triggers system setup

func _process(delta):
    if ECS.world:
        ECS.process(delta, "run-first")
        ECS.process(delta, "input")
        ECS.process(delta, "gameplay")
        ECS.process(delta, "ui")

func _physics_process(delta):
    if ECS.world:
        ECS.process(delta, "physics")
        ECS.process(delta, "debug")
        ECS.process(delta, "run-last")
```

### SystemGroup

`SystemGroup extends Node` is a `@tool` script that auto-assigns its name as the
`group` property of all child System nodes. Just name the node and add Systems as children.

## PendingDelete Pattern

Deferred entity deletion — mark for delete, then a dedicated system handles actual
removal. Allows death animations, sound effects, loot drops before the entity disappears.

### Components

```gdscript
# c_is_pending_delete.gd
class_name C_IsPendingDelete extends Component
@export var delete_delay: float = 0.0  # 0 = next frame, >0 = timed delay
```

### System (runs in "run-last" group)

```gdscript
# s_pending_delete.gd
class_name PendingDeleteSystem extends System

func query():
    return q.with_all([C_IsPendingDelete])

func process(entities: Array[Entity], components: Array, delta: float):
    for entity in entities:
        var pending = entity.get_component(C_IsPendingDelete)
        if pending.delete_delay <= 0.0:
            cmd.remove_entity(entity)
        else:
            pending.delete_delay -= delta
```

### Usage from any system

```gdscript
func process(entities: Array[Entity], components: Array, delta: float):
    for entity in entities:
        var health = entity.get_component(C_Health)
        if health.current <= 0:
            cmd.add_component(entity, C_IsPendingDelete.new())
            # Optionally set delay for death animation:
            # entity.get_component(C_IsPendingDelete).delete_delay = 0.5
```

### Excluding pending-delete entities from queries

Other systems should ignore entities marked for deletion:

```gdscript
func query():
    return q.with_all([C_Health, C_Enemy]).with_none([C_IsPendingDelete])
```

## Transform Synchronization

Two common patterns for syncing Godot scene transforms with ECS components:

### Scene -> Component (on entity creation)

```gdscript
# In Entity.on_ready()
func on_ready():
    if has_component(C_Transform):
        var t = get_component(C_Transform)
        t.transform = global_transform
```

### Component -> Scene (every frame via System)

```gdscript
class_name TransformSyncSystem extends System

func query():
    return q.with_all([C_Transform]).iterate([C_Transform])

func process(entities: Array[Entity], components: Array, delta: float):
    var transforms = components[0]
    for i in entities.size():
        entities[i].global_transform = transforms[i].transform
```

## Relationship Factory

Centralize relationship construction:

```gdscript
# rels.gd
class_name Rels

# Wildcard patterns (for has_relationship / query matching)
static var child_of := Relationship.new(R_ChildOf.new(), null)
static var attacks := Relationship.new(R_Attacks.new(), null)
static var equips := Relationship.new(R_Equips.new(), null)

# Targeted constructors
static func child_of_entity(parent: Entity) -> Relationship:
    return Relationship.new(R_ChildOf.new(), parent)

static func attacks_target(target: Entity) -> Relationship:
    return Relationship.new(R_Attacks.new(), target)

static func equips_item(item: Entity) -> Relationship:
    return Relationship.new(R_Equips.new(), item)
```

Benefits:
- Single place to rename/adjust relationships
- System code reads cleanly: `entity.has_relationship(Rels.attacks)`
- Avoids inline `Relationship.new()` construction scattered across systems

## Pure-Static Helpers and Test Seams

Factor non-trivial math out of Systems into pure-static `*_math.gd` / `*_logic.gd` siblings. The System keeps the ECS glue (queries, component IO, Node side effects); the helper holds the rule.

```gdscript
# jump_math.gd — pure functions, no Node, no Component, no ECS
class_name JumpMath

static func gravity(jump_height: float, time_to_apex: float) -> float:
    return 2.0 * jump_height / (time_to_apex * time_to_apex)
```

Expose each System's rule through a `simulate_*` static method. Unit tests and e2e drivers call it directly instead of driving the full input → physics → component pipeline.

```gdscript
class_name PlayerPhysicsSystem extends System

static func simulate_input(entity: Entity, dir: Vector2, pressed: bool, held: bool) -> void:
    var intent = entity.get_component(C_MovementIntent)
    intent.dir = dir
    intent.jump_pressed = pressed
    intent.jump_held = held
```

---

## ECS_DESIGN.md Cross-Reference

How our architectural decisions (ECS_DESIGN.md) map to gecs's actual API.

### D2: Entity-Node Relationship

**Our design:** Each entity gets a root Node for debug display; systems dynamically
add/remove child nodes based on component composition.

**gecs:** Entity **extends Node** directly. This is a natural fit — Entity IS the root
Node. Systems can call `entity.add_child(sprite)` directly since Entity is a Node.

**Adaptation:** No wrapper needed. Our "root Node per entity" design is built into gecs.

### D3: Scene Markers

**Our design:** Scenes contain marker nodes (metadata only), runtime converts markers
to ECS entities.

**gecs:** Uses `.tscn` files as entity prefabs directly — Entity node as scene root
with components assigned in Inspector or via `define_components()`.

**Adaptation:** Our marker system can instantiate gecs Entity prefabs. The marker-to-entity
conversion creates a gecs Entity and calls `ECS.world.add_entity()`.

### D4: No Authority Enum

**Our design:** Different movement types use different components + systems. Only one
system writes Transform per entity, enforced by static DAG checker.

**gecs:** Supports this via component composition + query filtering. However, gecs
**does not have** a built-in reads/writes tracking or static DAG checker. The `deps()`
system only declares Before/After ordering, not data-flow dependencies.

**Adaptation:** Static DAG checker must be implemented as a separate tool (T3.3) that
analyzes system source code for `get_component` / property writes. The gecs `deps()` API
handles execution ordering, but data conflict detection needs custom tooling.

### D5: Bulk Entities

**Our design:** BulletManager singleton with MultiMesh + PhysicsServer direct API.

**gecs:** No built-in bulk entity optimization. Standard entities use archetype storage
which is efficient but not designed for 10K+ homogeneous entities.

**Adaptation:** Our BulletManager singleton approach still applies. The singleton lives
outside gecs as a Godot autoload. ECS entities hold `C_BulletEmitter` components, and
a `BulletEmitterSystem` interfaces with the singleton.

### D6: System Dependencies (DAG)

**Our design:** `@system_meta({"reads": [], "writes": [], "creates_node": [], "requires_node": []})`

**gecs:** Uses `deps()` returning `{Runs.Before: [Systems], Runs.After: [Systems]}`.
Systems are topologically sorted within groups. No built-in reads/writes/creates_node tracking.

**Adaptation:** Use gecs `deps()` for execution ordering. The `creates_node`/`requires_node`
concept maps to System ordering within groups (place node-creating systems before
node-requiring systems). Static DAG checker (T3.3) adds data-flow verification on top.

### D7: Node Lifecycle (disable not free)

**Our design:** on_destroy disables child nodes; on_construct reuses existing disabled nodes.

**gecs:** `World.disable_entity()` sets `entity.enabled = false`, stops processing,
disconnects signals. `World.enable_entity()` re-enables. PendingDelete pattern handles
deferred destruction.

**Adaptation:** Our disable/enable lifecycle maps to gecs's entity enable/disable.
For child node management (adding Sprite2D when SpriteComp is added), use Observers:
`on_component_added` adds child node, `on_component_removed` disables it.

### D8: Testing

**Our design:** Pure logic systems: registry + components + system call + assertions.
Materialization systems: minimal scene fixture.

**gecs:** Same approach works. Create a World programmatically, add entities with
components, run the system, assert state.

```gdscript
# Pure logic test
func test_movement_system():
    var world = World.new()
    add_child(world)
    ECS.world = world

    var entity = Entity.new()
    world.add_entity(entity, [C_Position.new(), C_Velocity.new(Vector3.RIGHT, 10.0)])

    var system = MovementSystem.new()
    system.group = "test"
    world.add_system(system)

    world.process(1.0, "test")  # 1 second delta

    var pos = entity.get_component(C_Position)
    assert_eq(pos.value, Vector3(10, 0, 0))
```

### Summary: What Needs Custom Implementation

| Feature | gecs Coverage | Custom Work Needed |
|---------|--------------|-------------------|
| Entity-Node relationship | Built-in (Entity extends Node) | None |
| Component as Resource | Built-in | None |
| Query DSL | Built-in (QueryBuilder) | None |
| System ordering | Built-in (deps + groups) | None |
| Reactive callbacks | Built-in (Observer) | None |
| CommandBuffer | Built-in | None |
| Static DAG checker (reads/writes) | Not built-in | T3.3 custom tool |
| Bulk entity optimization | Not built-in | T3.5 BulletManager singleton |
| Scene marker conversion | Not built-in | T3.2 marker skill |
| Serialization | Built-in (GECSIO) | None |
| Debug tools | Built-in (editor debugger) | None |
