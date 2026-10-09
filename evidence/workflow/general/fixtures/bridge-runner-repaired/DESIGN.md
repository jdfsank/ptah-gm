# Design Notes

A small Godot 4 GDScript side-view jump game. Move the cyan player at 300 px/s with the left/right arrow keys and jump with Space to cross three visible platforms and reach a green exit. Preserve the existing platforms and controls. Falling restarts the level, and R resets it during play or after winning. Restart must clear stale exit contact so the player remains in the playing state at spawn and can complete another attempt. Use a fixed 960x540 view, procedural shapes, one level, and no sound, external assets, plugins, or network access. Keep simulation, input actions, rendering, and interface responsibilities separate.

## Object Relationships
- `bridge-runner` parent `none`; relations: none
- `main-scene` parent `bridge-runner`; relations: none
- `input-actions` parent `main-scene`; relations: none
- `player` parent `main-scene`; relations: none
- `horizontal-movement` parent `player`; relations: reads-input → input-actions
- `jump` parent `player`; relations: reads-input → input-actions
- `platform-one` parent `main-scene`; relations: none
- `platform-two` parent `main-scene`; relations: none
- `platform-three` parent `main-scene`; relations: none
- `platform-collision` parent `main-scene`; relations: supports → player
- `exit` parent `main-scene`; relations: none
- `win` parent `main-scene`; relations: triggered-by → exit, updates → hud
- `fall-restart` parent `main-scene`; relations: none
- `manual-reset` parent `main-scene`; relations: reads-input → input-actions
- `level-state` parent `main-scene`; relations: none
- `fixed-view` parent `main-scene`; relations: none
- `procedural-rendering` parent `main-scene`; relations: none
- `hud` parent `main-scene`; relations: none

## Field and Feedback Changes
- Feedback for `main-scene` (bug): Backend independent gameplay probe reaches the exit using actual input. After winning, R teleports player to x=100 but state immediately becomes WON again (state=1, exitOverlap=false). Fix reset/exit-contact handling so stale Area2D overlap/contact state after teleport cannot retrigger win at spawn. Preserve speed 300, cyan player, platforms, controls, jump, HUD and normal win behavior. No optional questions; use the existing object/source bindings and add an explicit manual reset-after-win requirement..
