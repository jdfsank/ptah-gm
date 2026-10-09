# Current Tag Plan

**Tag:** v0.1.0

## Game Description
Collect every token in one arena before the countdown expires. The game is a single-screen 2D Godot project with procedural visuals and no external service.

## Iteration Intent
Prepare an immutable, playable-closed-loop collect-and-retry MVP whose only producer-controlled implementation values are the four rules in `config/rules.json`.

## Tag Mechanics
- [collect-loop-M1] Move with mapped keyboard controls, collect every configured token to win, lose when the timer expires, and retry either terminal result with R.

## Inherited Mechanics
None. This is the initial tag.

## Playable Unit
| Unit | Observable acceptance | Evidence |
|---|---|---|
| Single arena loop | Movement, collection, win, timeout loss, and retry after either result work. | Headless SceneTree harness and interactive desktop run. |

## Risk Tasks
- Verify actual mapped keyboard events and collision collection in the SceneTree harness.
- Verify terminal-state input lock and reset behavior for both win and loss.

## Main Build
- Preserve the scene and scripts as immutable template source.
- Read count, duration, speed, and lifecycle gate from the rules document.
- Keep preparation separate from enabling gameplay.

## Task Status

## Review Notes
The runtime harness provides mechanical evidence only. Visual quality and human acceptance require separate review.

## Platform Commitments
| Platform | Status | Profile | Evidence | Manual check |
|---|---|---|---|---|
| Desktop | required | collect-loop-desktop | Godot 4.6 headless import, automated closed-loop harness, and native launch evidence. | Confirm the arena is legible and keyboard controls work in a desktop window. |

## Component Coverage
- Rules and lifecycle gate: `config/rules.json`.
- Player movement and collisions: `scripts/player.gd` and `scripts/main.gd`.
- Input bindings: `project.godot`.
- Closed-loop harness: `tests/closed_loop.gd`.
