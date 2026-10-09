# Debug Tools Reference

gecs includes an editor debugger plugin and runtime performance monitoring. These tools
help inspect entities, profile systems, and diagnose query performance.

## Table of Contents

- [ECS Singleton](#ecs-singleton)
- [Debug Mode](#debug-mode)
- [Editor Debugger Plugin](#editor-debugger-plugin)
- [Performance Monitoring](#performance-monitoring)
- [Cache Statistics](#cache-statistics)
- [Logging](#logging)
- [Entity Pre/Post-Processors](#entity-prepost-processors)

## ECS Singleton

The `ECS` autoload singleton (`_ECS extends Node`) is the global entry point:

| Property/Method | Type | Description |
|----------------|------|-------------|
| `ECS.world` | `World` | The currently active World instance |
| `ECS.debug` | `bool` | Debug mode flag (from project settings) |
| `ECS.process(delta, group)` | `void` | Shorthand for `ECS.world.process(delta, group)` |
| `ECS.entity_preprocessors` | `Array` | Callables run after entity is added |
| `ECS.entity_postprocessors` | `Array` | Callables run before entity is removed |

### Setting the active world

```gdscript
func _ready():
    ECS.world = $World  # triggers finalize_system_setup()
```

When you assign `ECS.world`, it calls `finalize_system_setup()` on the World, which
executes all deferred system `setup()` methods.

## Debug Mode

Enable via Project Settings: `gecs/settings/debug_mode = true`

When debug mode is active:
- Systems record execution timing in `lastRunData`
- Performance metrics are collected per frame
- The editor debugger plugin receives live data
- Archetype explosion warning triggers at 500+ archetypes
- Cache statistics are tracked

Debug overhead is negligible in release builds — most debug code is behind `if ECS.debug:` guards.

### System debug data

When `ECS.debug` is true, each system's `lastRunData` dictionary is populated:

```gdscript
# Auto-populated by framework:
lastRunData = {
    "system_name": "MovementSystem",
    "frame_delta": 0.016,
    "entity_count": 150,
    "archetype_count": 3,
    "execution_time_ms": 0.45,
    "execution_order": 2,
    "parallel": false,
    "fallback_execute": false
}

# You can add custom debug data in your system:
func process(entities: Array[Entity], components: Array, delta: float):
    if ECS.debug:
        lastRunData["custom_metric"] = compute_metric()
        lastRunData["entities_processed"] = entities.size()
```

All keys in `lastRunData` automatically appear in the GECS debugger tab.

## Editor Debugger Plugin

gecs ships an editor debugger plugin (`debug/gecs_editor_debugger.gd`) that captures
real-time ECS data during play mode.

### What it shows

The debugger tab receives these message types:

| Message | Data |
|---------|------|
| `WORLD_INIT` | World initialization (entity/system counts) |
| `SYSTEM_METRIC` | Per-system performance (time, entity count) |
| `SYSTEM_LAST_RUN_DATA` | Full `lastRunData` dictionary from each system |
| `ENTITY_ADDED` / `ENTITY_REMOVED` | Entity lifecycle events |
| `ENTITY_ENABLED` / `ENTITY_DISABLED` | Entity enable/disable events |
| `COMPONENT_ADDED` / `COMPONENT_REMOVED` / `COMPONENT_CHANGED` | Component lifecycle |
| `RELATIONSHIP_ADDED` / `RELATIONSHIP_REMOVED` | Relationship changes |
| `POLL_ENTITY` | Request fresh component data for a specific entity |
| `SELECT_ENTITY` | Navigate to entity in scene tree |

### Enabling

The debugger plugin activates automatically when the GECS plugin is enabled in
Project Settings > Plugins. No additional setup needed.

### Entity polling

The editor can request fresh component data for any entity:

```gdscript
# Triggered from editor — polls entity and sends serialized component data
GECSEditorDebuggerMessages.poll_entity(entity)
```

## Performance Monitoring

World provides frame-level and accumulated performance metrics (debug mode only).

### perf_mark(key, duration_usec, extra = {})

Record a performance measurement:

```gdscript
if ECS.debug:
    var start = Time.get_ticks_usec()
    # ... work ...
    ECS.world.perf_mark("my_operation", Time.get_ticks_usec() - start, {
        "entities": count
    })
```

### perf_get_frame_metrics() -> Dictionary

Returns current frame's aggregated metrics. Reset at start of each `World.process()`.

```gdscript
var metrics = ECS.world.perf_get_frame_metrics()
# { "query_total": { "count": 5, "time_usec": 120, "returned": 500 }, ... }
```

### perf_get_accum_metrics() -> Dictionary

Returns lifetime accumulated metrics.

### perf_reset_accum()

Reset accumulated metrics.

### Built-in metric keys

The World automatically tracks:

| Key | What it measures |
|-----|-----------------|
| `query_cache_key` | Time to compute query hash |
| `query_cache_hit` | Cache hit (with archetype count) |
| `query_archetype_scan` | Time to scan archetypes for cache miss |
| `query_flatten` | Time to flatten archetype entities into result array |
| `query_total` | Total query time including all steps |
| `query_all_entities` | Time for unfiltered "return all" query |
| `archetypes_cache_hit` | Archetype-level cache hit |
| `archetypes_scan` | Archetype scan time |

## Cache Statistics

### get_cache_stats() -> Dictionary

```gdscript
var stats = ECS.world.get_cache_stats()
# {
#   "cache_hits": 1523,
#   "cache_misses": 12,
#   "hit_rate": 0.992,
#   "cached_queries": 8,
#   "total_archetypes": 15,
#   "invalidation_count": 45,
#   "invalidation_reasons": {
#     "entity_component_added": 20,
#     "entity_component_removed": 15,
#     "new_archetype_created": 10
#   }
# }
```

### reset_cache_stats()

Reset hit/miss counters and invalidation tracking.

### Interpreting cache stats

- **High hit rate (>0.95)** — normal operation, queries are well-cached
- **Low hit rate** — frequent structural changes (component add/remove) invalidating cache
- **High archetype count** — possible archetype explosion from high-cardinality relationships
- **Frequent invalidation reasons** — shows what operations are causing cache churn

## Logging

gecs uses `GECSLogger` for internal logging. Controlled via project settings:

- `gecs/settings/log_level`: TRACE (0), DEBUG (1), INFO (2), WARNING (3), ERROR (4)
- Default: ERROR only

Logger is disabled by default (`const disabled := true` in logger.gd). To enable
during development, set the log level in Project Settings.

Domain-tagged loggers:

```gdscript
# Internal usage (already set up in each class):
var _worldLogger = GECSLogger.new().domain("World")
var _entityLogger = GECSLogger.new().domain("Entity")
var systemLogger = GECSLogger.new().domain("System")
```

## Entity Pre/Post-Processors

Register callbacks that run on every entity add/remove:

```gdscript
# Run after every entity is added to the world
ECS.entity_preprocessors.append(func(entity: Entity):
    print("Entity added: ", entity.name)
    # Tag entities, inject components, etc.
)

# Run before every entity is removed from the world
ECS.entity_postprocessors.append(func(entity: Entity):
    print("Entity removing: ", entity.name)
    # Cleanup, logging, etc.
)
```

These are useful for cross-cutting concerns like debug logging, analytics, or
automatic component injection.
