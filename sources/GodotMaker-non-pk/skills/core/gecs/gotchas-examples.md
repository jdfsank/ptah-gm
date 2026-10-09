# gecs Gotchas — Code Examples

Workers: grep this file by ID (G1, G2, ...) when you need the full example for a specific gotcha.

---

## G1. Entity extends Node, NOT Node2D

```gdscript
# WRONG:
entity.position = Vector2(100, 200)         # Node has no position — crashes!

# CORRECT:
class_name C_Position extends Component
@export var value: Vector2 = Vector2.ZERO

# In RenderSystem:
var sprite = entity.get_node_or_null("Visual")
if sprite:
    sprite.position = entity.get_component(C_Position).value
```

---

## G2. Components inaccessible before add_entity

```gdscript
# WRONG:
var entity = BirdEntity.new()
entity.get_component(C_Position).value = Vector2(100, 200)  # null crash!

# CORRECT:
var entity = BirdEntity.new()
ECS.world.add_entity(entity)                 # registers components first
entity.get_component(C_Position).value = Vector2(100, 200)
```

---

## G3. World only scans systems once at _ready

```gdscript
# WRONG:
add_child(_world)                    # _ready() scans — nothing found
_world.add_child(MovementSystem.new())  # too late

# CORRECT — Option A:
_world.add_child(MovementSystem.new())
add_child(_world)                    # _ready() finds the system

# CORRECT — Option B:
add_child(_world)
_world.add_system(MovementSystem.new())   # manual late registration
```

---

## G4. system_nodes_root default

```
# WRONG (.tscn):
[node name="GameWorld" type="Node"]
script = ExtResource("world_script")
# system_nodes_root not set → systems silently ignored

# CORRECT (.tscn):
[node name="GameWorld" type="Node"]
script = ExtResource("world_script")
system_nodes_root = NodePath(".")
entity_nodes_root = NodePath(".")
```

---

## G5. process() called per archetype

```gdscript
# WRONG — local var resets every archetype batch:
func process(entities, _c, _d):
    var alive_ids = {}                       # resets!
    for entity in entities:
        alive_ids[entity.get_instance_id()] = true

# CORRECT — instance var persists:
var _alive_ids: Dictionary = {}

func process(entities, _c, _d):
    for entity in entities:
        _alive_ids[entity.get_instance_id()] = true

func _process(_delta):
    _cleanup_dead_entities()
    _alive_ids.clear()
```

---

## G6. add_entity overrides manual add_child

```gdscript
# WRONG:
$Entities.add_child(entity)       # manual placement
ECS.world.add_entity(entity)      # World moves it to its own container

# CORRECT:
ECS.world.add_entity(entity)      # let World manage placement
```

---

## G7. ECS.world assignment silently null

```gdscript
# WRONG:
ECS.world = $GameWorld                # silently null if type check fails

# CORRECT:
ECS.set("world", $GameWorld)          # bypasses type check
assert(ECS.world != null, "ECS.world assignment failed")
```

---

## G8. Entity subclass @tool

```gdscript
# WRONG:
class_name BirdEntity extends Entity
func define_components() -> Array:
    return [C_Position.new()]

# CORRECT:
@tool
class_name BirdEntity extends Entity
func define_components() -> Array:
    return [C_Position.new()]
```

---

## G9. class_name cache rebuild

```bash
# After creating any .gd file with class_name:
godot --headless --import
```

---

## G10. system.process() in unit tests

```gdscript
# WRONG — type error + CommandBuffer not flushed:
var system = CleanupSystem.new()
system.process([entity], [], delta)

# CORRECT — Option A (recommended):
ECS.world.process(delta)               # full system execution

# CORRECT — Option B:
var result = CleanupSystem.should_cleanup(entity)  # test static functions
assert_true(result)
```

---

## G11. Autoload name collision

```ini
# WRONG — gecs reserved names as autoloads:
[autoload]
World="*res://src/world.gd"

# CORRECT:
[autoload]
GameWorld="*res://src/world.gd"
```

```gdscript
# WRONG — scene root node has same name as an autoload:
# project.godot has: GameWorld="*res://autoloads/game_world.gd"
# game_world.tscn root node is also named "GameWorld"
# → get_node("/root/GameWorld") resolves to the autoload, not the scene node
#   UI overlays under the scene node become unreachable

# CORRECT — scene root uses a distinct name:
# game_world.tscn root node named "GameLevel"
# → get_node("/root/GameLevel/PauseLayer/...") works as expected
```

---

## G12. find_children owned=false

```gdscript
# WRONG — code-added nodes have no owner:
var systems = world.find_children("*", "System")              # empty!

# CORRECT:
var systems = world.find_children("*", "System", true, false) # owned=false
```

---

## G13. Entity name for E2E paths

```gdscript
# WRONG — auto-name is "@GameBoardEntity@3":
var entity = GameBoardEntity.new()
ECS.world.add_entity(entity)

# CORRECT:
var entity = GameBoardEntity.new()
entity.name = "GameBoard"             # predictable for get_node() and E2E
ECS.world.add_entity(entity)
```

---

## G14. system.q is null outside World

```gdscript
# WRONG — system.q is null, crashes:
func test_system_has_query():
    var system = MovementSystem.new()
    assert_not_null(system.q)  # CRASH: q is null

# CORRECT — test via World:
func test_movement():
    var world = World.new()
    world.add_system(MovementSystem.new())
    add_child(world)
    # ... add entity, then:
    ECS.world.process(delta, "gameplay")
```

---

## G15. add_system second param is bool, not group

```gdscript
# WRONG:
world.add_system(system, "gameplay")  # second param is bool, not string!

# CORRECT:
system.group = "gameplay"
world.add_system(system)
```

---

## G16. Grouped systems skipped without group param

```gdscript
# WRONG — grouped systems silently skipped:
ECS.world.process(delta)

# CORRECT:
ECS.world.process(delta, "input")
ECS.world.process(delta, "gameplay")
ECS.world.process(delta, "physics")
```

---

## G17. NodePath export unreliable in .tscn

```gdscript
# WRONG — .tscn NodePath may not apply:
# [node name="World" ...] node_paths=PackedStringArray("entity_nodes_root:Entities")

# CORRECT — set in code:
extends World
func _init():
    entity_nodes_root = NodePath("Entities")
    system_nodes_root = NodePath("Systems")
```

---

## G18. Area2D overlap stale in _process

```gdscript
# WRONG — overlap data stale in _process:
# KeyCollectionSystem in "gameplay" group (runs in _process)
func process(entities, _c, _d):
    for e in entities:
        var area = e.get_node("Area2D")
        area.get_overlapping_bodies()  # empty! physics hasn't updated

# CORRECT — run in physics group:
# KeyCollectionSystem in "physics" group (runs in _physics_process)
```

---

## G19. Type inference fails with ternary

```gdscript
# WRONG — type inference fails:
var jump_pos := body.position if body else Vector2.ZERO

# CORRECT — explicit type:
var jump_pos: Vector2 = body.position if body else Vector2.ZERO
```

---

## G20. @export var x: Node fails on Component

```gdscript
# WRONG:
class_name C_NodeRef extends Component
@export var node: Node          # Parse Error: "Node export is only supported in Node-derived classes"
```

```gdscript
# CORRECT:
class_name C_NodeRef extends Component
var node: Node = null           # runtime reference, not serialized

# Set the ref after add_entity (e.g. inside a RenderSystem):
entity.get_component(C_NodeRef).node = sprite_node
```

Component extends Resource (for serialization). `@export` only works with Resource-compatible types — primitives, Vector*, Resource subclasses, etc. Node references must be assigned at runtime, not declared as exports.
