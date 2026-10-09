# System API Reference

A System **extends Node** and contains game logic. Systems query for entities with
specific components and process them each frame. Systems are placed in the scene tree
under a World's system root, organized by groups.

## Table of Contents

- [Core Methods](#core-methods)
- [Properties](#properties)
- [CommandBuffer](#commandbuffer)
- [SystemTimer](#systemtimer)
- [Sub-Systems](#sub-systems)
- [System Dependencies](#system-dependencies)
- [System Groups](#system-groups)
- [Parallel Processing](#parallel-processing)
- [Best Practices](#best-practices)

## Core Methods

### query() -> QueryBuilder

Override to define which entities this system processes. Use `q` (shorthand for
`_world.query` / `ECS.world.query`).

```gdscript
class_name MovementSystem extends System

func query() -> QueryBuilder:
    return q.with_all([C_Position, C_Velocity]).enabled()
```

If not overridden, the system runs with no entities and `process_empty` is set to true.

### process(entities: Array[Entity], components: Array, delta: float) -> void

Main processing function. Called each frame (or at tick rate if SystemTimer is set).

**Simple approach** — per-entity `get_component()`:

```gdscript
func process(entities: Array[Entity], components: Array, delta: float):
    for entity in entities:
        var vel = entity.get_component(C_Velocity)
        entity.position += vel.direction * vel.speed * delta
```

**Fast approach** — batch via `iterate()`:

```gdscript
func query() -> QueryBuilder:
    return q.with_all([C_Position, C_Velocity]).iterate([C_Position, C_Velocity])

func process(entities: Array[Entity], components: Array, delta: float):
    var positions = components[0]    # C_Position array
    var velocities = components[1]   # C_Velocity array
    for i in entities.size():
        positions[i].value += velocities[i].direction * velocities[i].speed * delta
```

`components` array order matches `iterate()` argument order.

### setup()

Called once after the system is added to the World. Use for one-time initialization
like setting tick rates or caching references.

```gdscript
func setup():
    set_tick_rate(0.5)  # run every 500ms
```

## Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `group` | `String` | `""` | System group for ordered processing |
| `active` | `bool` | `true` | Set to false to skip this system entirely |
| `paused` | `bool` | `false` | Paused state (separate from active) |
| `process_empty` | `bool` | `false` | Run even when query matches zero entities |
| `safe_iteration` | `bool` | `true` | Snapshot entities before iteration to guard against mutation. Set false when all changes go through `cmd` |
| `parallel_processing` | `bool` | `false` | Process entities in parallel threads |
| `parallel_threshold` | `int` | `50` | Min entities to trigger parallel processing |
| `command_buffer_flush_mode` | `FlushMode` | `PER_SYSTEM` | When to execute queued commands |
| `q` | `QueryBuilder` | — | Shorthand for world.query (read-only) |
| `cmd` | `CommandBuffer` | — | Command buffer for deferred structural changes |
| `tick_source` | `SystemTimer` | `null` | Tick source; null = every frame |
| `lastRunData` | `Dictionary` | `{}` | Debug data (auto-populated when `ECS.debug`) |

## CommandBuffer

The `cmd` property provides a CommandBuffer for safe structural changes during iteration.
Without it, adding/removing components or entities during `process()` modifies the
iteration array and causes entity skipping.

### API

```gdscript
# Component operations
cmd.add_component(entity, C_Burning.new())
cmd.remove_component(entity, C_Shield)
cmd.add_components(entity, [C_Burning.new(), C_Stunned.new()])
cmd.remove_components(entity, [C_Shield, C_Invulnerable])

# Entity operations
cmd.add_entity(new_entity)
cmd.remove_entity(entity)

# Relationship operations
cmd.add_relationship(entity, Relationship.new(R_Targets.new(), target))
cmd.remove_relationship(entity, Relationship.new(R_Buff.new(), null), 1)

# Custom operations (for complex multi-step logic)
cmd.add_custom(func(): do_complex_thing())

# Manual control (normally automatic)
cmd.execute()   # execute all queued commands
cmd.clear()     # discard all queued commands
```

### Flush Modes

| Mode | When commands execute | Use case |
|------|----------------------|----------|
| `FlushMode.PER_SYSTEM` | After each system completes (default) | Safest — later systems in same frame see changes |
| `FlushMode.PER_GROUP` | After all systems in the group complete | Good for spawn/cleanup within one `process()` call |
| `FlushMode.MANUAL` | Only on `ECS.world.flush_command_buffers()` | Maximum batching, cross-group coordination |

```gdscript
# PER_GROUP example
func setup():
    command_buffer_flush_mode = FlushMode.PER_GROUP

# MANUAL example — flush after multiple groups
func _process(delta):
    ECS.process(delta, "physics")    # systems may queue commands
    ECS.process(delta, "render")     # more queued commands
    ECS.world.flush_command_buffers()  # execute all MANUAL commands at once
```

### Migration from direct mutation

```gdscript
# BEFORE (backwards iteration to avoid skipping)
func process(entities: Array[Entity], components: Array, delta: float):
    for i in range(entities.size() - 1, -1, -1):
        if should_delete(entities[i]):
            ECS.world.remove_entity(entities[i])

# AFTER (CommandBuffer — safe forward iteration)
func process(entities: Array[Entity], components: Array, delta: float):
    for entity in entities:
        if should_delete(entity):
            cmd.remove_entity(entity)
```

### Performance benefits

- Single cache invalidation per `execute()` call (not per operation)
- No memory overhead from defensive array snapshots
- Commands execute in exact queued order
- Each lambda includes `is_instance_valid` guard for freed entities

## SystemTimer

Controls system tick rate. By default, systems run every frame. Use SystemTimer to
run at fixed intervals.

### set_tick_rate(interval_seconds: float, single_shot: bool = false) -> SystemTimer

Convenience method to create and assign a timer. Returns the timer so it can be shared.

```gdscript
func setup():
    set_tick_rate(0.5)  # run every 500ms
```

### Shared timers (synchronized execution)

Multiple systems sharing the same timer are guaranteed to execute on the same frame:

```gdscript
# In system A:
var timer = set_tick_rate(0.2)
# Pass to system B:
system_b.tick_source = timer  # both tick together every 200ms
```

### One-shot timer

```gdscript
func setup():
    set_tick_rate(3.0, true)  # fire once after 3 seconds, then stop
```

### SystemTimer properties

| Property | Type | Description |
|----------|------|-------------|
| `interval` | `float` | Seconds between ticks |
| `single_shot` | `bool` | Fire once and deactivate |
| `active` | `bool` | Can be paused independently |
| `ticked` | `bool` | Read-only: true on the frame the timer fired |
| `tick_count` | `int` | Total ticks since creation/reset |
| `time_elapsed` | `float` | Accumulated time since last tick |

`reset()` resets to initial state (active, zero elapsed).

Key behaviors:
- No timer = every frame (default)
- Timers advance in `World.process()` before any system in the group runs
- Overshoot is carried forward to prevent drift
- Paused systems don't block shared timers — the timer keeps ticking

## Sub-Systems

When a System needs multiple distinct queries, use `sub_systems()` instead of cramming
everything into one `query()` + `process()`.

```gdscript
class_name WeaponsSystem extends System

func sub_systems() -> Array[Array]:
    return [
        [q.with_all([C_Weapon, C_Firing]), handle_firing],
        [q.with_all([C_Weapon, C_Reloading]), handle_reloading],
        [q.with_all([C_Weapon]).disabled(), handle_holstered, _holster_timer],
    ]

func handle_firing(entities: Array[Entity], _components: Array, delta: float):
    for entity in entities:
        var weapon = entity.get_component(C_Weapon)
        weapon.fire_timer -= delta
        if weapon.fire_timer <= 0:
            cmd.add_component(entity, C_ProjectileSpawn.new(weapon.muzzle_position))
            weapon.fire_timer = weapon.fire_rate

func handle_reloading(entities: Array[Entity], _components: Array, delta: float):
    for entity in entities:
        var weapon = entity.get_component(C_Weapon)
        weapon.reload_timer -= delta
        if weapon.reload_timer <= 0:
            weapon.ammo = weapon.max_ammo
            cmd.remove_component(entity, C_Reloading)
```

Each sub-system is an `[QueryBuilder, Callable]` tuple. Optional third element is a
`SystemTimer` for per-subsystem tick rate control.

When a System defines `sub_systems()`, `query()` and `process()` are not called.

## System Dependencies

### deps() -> Dictionary[Runs, Array]

Declare execution ordering relative to other systems:

```gdscript
func deps() -> Dictionary[int, Array]:
    return {
        Runs.After: [InputSystem],     # run AFTER InputSystem
        Runs.Before: [RenderSystem],   # run BEFORE RenderSystem
    }
```

Systems are topologically sorted within each group based on `deps()`. If not overridden,
order follows scene tree child order.

## System Groups

Systems are organized into groups via the `group` property. The `SystemGroup` node
auto-assigns its name to all child Systems.

```
Systems (Node)
+-- input (SystemGroup)         # group = "input"
|   +-- PlayerControlsSystem
|   +-- AIDecisionSystem
+-- gameplay (SystemGroup)      # group = "gameplay"
|   +-- HealthSystem
|   +-- CombatSystem
+-- physics (SystemGroup)       # group = "physics"
|   +-- MovementSystem
|   +-- CollisionSystem
+-- run-last (SystemGroup)      # group = "run-last"
    +-- PendingDeleteSystem
```

Process each group explicitly in your main scene:

```gdscript
func _process(delta):
    ECS.process(delta, "input")
    ECS.process(delta, "gameplay")

func _physics_process(delta):
    ECS.process(delta, "physics")
    ECS.process(delta, "run-last")
```

## Parallel Processing

For systems processing many entities without scene tree access:

```gdscript
@export var parallel_processing := true
@export var parallel_threshold := 100  # only parallelize with 100+ entities

func process(entities: Array[Entity], components: Array, delta: float):
    # This runs on worker threads — NO scene tree access!
    for entity in entities:
        # Pure computation only
        var vel = entity.get_component(C_Velocity)
        vel.direction = calculate_direction(entity)
```

Uses `WorkerThreadPool` with batch sizes based on CPU core count.
Only use for pure computation — no `add_child`, no `get_tree()`, no signal emission.

## Best Practices

### Single responsibility

One system, one concern:

```gdscript
# GOOD
class_name MovementSystem extends System   # only movement
class_name HealthSystem extends System     # only health
class_name RenderSystem extends System     # only rendering

# BAD
class_name GameplaySystem extends System   # does everything
```

### Early exit

Skip entities that don't need processing:

```gdscript
func process(entities: Array[Entity], components: Array, delta: float):
    for entity in entities:
        var health = entity.get_component(C_Health)
        if health.current >= health.maximum:
            continue  # already full, skip regen
        health.current = min(health.current + health.regeneration_rate * delta, health.maximum)
```

### Use iterate() for hot paths

`iterate()` avoids per-entity `get_component()` dictionary lookups:

```gdscript
func query():
    return q.with_all([C_Transform, C_Velocity]).iterate([C_Transform, C_Velocity])

func process(entities: Array[Entity], components: Array, delta: float):
    var transforms = components[0]
    var velocities = components[1]
    for i in entities.size():
        transforms[i].position += velocities[i].direction * delta
```

### Defensive assertions

Fail loud, not silent. Systems that read component data should validate assumptions:

```gdscript
func process(entities: Array[Entity], components: Array, delta: float):
    for entity in entities:
        var sprite = entity.get_component(C_Sprite)
        # Unacceptable — will cause invisible entity. Crash early.
        assert(sprite.texture_path != "", "C_Sprite.texture_path is empty on %s" % entity.name)

        var health = entity.get_component(C_Health)
        # Acceptable but suspicious — warn and continue.
        if health.current > health.maximum:
            push_warning("%s: C_Health.current (%d) exceeds maximum (%d)" % [entity.name, health.current, health.maximum])
            health.current = health.maximum
```

- `assert` for states that indicate a bug (missing resource path, null reference) — crashes in debug, stripped in release
- `push_warning` for states that are recoverable but unexpected (out-of-range values, missing optional data)
- Never silently skip invalid data — the spawn system that forgot to set a field will go unnoticed for the entire session

### Prefer CommandBuffer over direct mutation

Always use `cmd` for structural changes inside `process()`. Set `safe_iteration = false`
when you're confident all structural changes go through `cmd` — this skips the
array snapshot and improves performance.
