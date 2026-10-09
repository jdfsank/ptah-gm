# Component API Reference

A Component is a **pure data container** that extends Godot's `Resource` class.
Components hold properties but no logic — all behavior belongs in Systems.

## Table of Contents

- [Defining a Component](#defining-a-component)
- [Constructor Patterns](#constructor-patterns)
- [Properties](#properties)
- [Signals](#signals)
- [Duplication Contract](#duplication-contract)
- [Component Queries](#component-queries)
- [Best Practices](#best-practices)

## Defining a Component

Every component follows this pattern:

```gdscript
class_name C_Health extends Component

@export var current: float = 100.0
@export var maximum: float = 100.0
@export var regeneration_rate: float = 1.0
```

**Rules:**
1. Class name starts with `C_` prefix
2. File name uses `c_` prefix: `c_health.gd`
3. Extends `Component` (which extends `Resource`)
4. All `@export` properties **must** have default values — Godot errors without them
5. No methods that contain game logic

## Constructor Patterns

### Pattern 1: @export with defaults only (simplest, preferred)

```gdscript
class_name C_Health extends Component
@export var current: float = 100.0
@export var maximum: float = 100.0
```

Usage: `C_Health.new()` — properties use defaults. Override in Inspector or code:
```gdscript
var h = C_Health.new()
h.maximum = 200.0
h.current = 200.0
```

### Pattern 2: _init() with defaulted parameters

```gdscript
class_name C_Velocity extends Component
@export var direction: Vector3 = Vector3.ZERO
@export var speed: float = 0.0

func _init(dir: Vector3 = Vector3.ZERO, spd: float = 0.0) -> void:
    direction = dir
    speed = spd
```

Usage: `C_Velocity.new(Vector3.RIGHT, 100.0)` or `C_Velocity.new()`.

**Critical:** `_init()` parameters **must** have defaults so `Component.new()` works —
gecs calls parameterless `.new()` during entity duplication.

### Pattern 3: Tag component (no properties)

```gdscript
class_name C_Player extends Component
# Empty — acts as a type tag for queries
```

Usage: `q.with_all([C_Player])` to find all players.

## Properties

| Property | Type | Description |
|----------|------|-------------|
| `parent` | `Entity` | Reference to the owning entity (set by `add_component`) |

The `parent` property lets a component know which entity owns it, though this should
rarely be needed — Systems receive entities directly through queries.

## Signals

### property_changed(component, property_name, old_value, new_value)

Emitted when a property value changes. Bubbles up to `Entity.component_property_changed`
and then to `World.component_changed`. This is how Observers detect property changes.

Note: This signal fires from `@export` property setters. If you manually set a non-export
property, it won't emit unless you add a setter with `property_changed.emit()`.

## Duplication Contract

When an entity is added to the World, each component in `component_resources` is
**shallow-duplicated**: a new Resource is created and all top-level property values are
copied. This means:

- Each entity gets its own component instance (no shared state)
- Top-level values (including non-`@export` vars) are copied
- **Nested sub-resource references are shared** between entities
- If you need independent sub-resources per entity, duplicate them in `_init()`

```gdscript
# These will share the same inner_config between entities:
class_name C_AI extends Component
@export var inner_config: AIConfig = AIConfig.new()  # shared!

# Fix: duplicate in _init
func _init():
    inner_config = AIConfig.new()  # each entity gets its own
```

## Component Queries

Components can be queried by property values using dictionary syntax:

```gdscript
# Find entities with health >= 50
var healthy = ECS.world.query.with_all([
    {C_Health: {'current': {"_gte": 50}}}
]).execute()

# Operators: _eq, _ne, _gt, _lt, _gte, _lte, _in, _nin, func
# func operator takes a Callable for custom matching
```

See [query.md](query.md) for full component query syntax.

## Best Practices

### Keep components pure data

```gdscript
# GOOD — pure data
class_name C_Health extends Component
@export var current: float = 100.0
@export var maximum: float = 100.0

# BAD — logic in component
class_name C_Health extends Component
@export var current: float = 100.0
func take_damage(amount: float):  # belongs in a System!
    current -= amount
```

### Use composition over inheritance

Build entity behavior by combining simple components, not inheriting from complex bases:

```gdscript
# GOOD — composable
# Player = C_Health + C_Input + C_Movement + C_Inventory
# Enemy  = C_Health + C_AI + C_Movement + C_LootTable

# BAD — inheritance hierarchy
# class C_LivingThing extends Component  # too broad
```

### Design for configuration

Make components easily tweakable through `@export`:

```gdscript
class_name C_Movement extends Component
@export var speed: float = 100.0
@export var acceleration: float = 500.0
@export var friction: float = 800.0
@export var max_speed: float = 300.0
@export var can_fly: bool = false
```

This allows designers to tune values in the Inspector without touching code.

### Prefer small, focused components

One component per concept. Split large components into smaller ones:

```gdscript
# GOOD — focused
class_name C_Position extends Component
@export var value: Vector3 = Vector3.ZERO

class_name C_Velocity extends Component
@export var direction: Vector3 = Vector3.ZERO
@export var speed: float = 0.0

# BAD — too many concerns
class_name C_PhysicsBody extends Component
@export var position: Vector3 = Vector3.ZERO
@export var velocity: Vector3 = Vector3.ZERO
@export var mass: float = 1.0
@export var collision_layer: int = 1
# ... this should be 3-4 separate components
```
