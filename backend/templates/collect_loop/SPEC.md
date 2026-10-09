# Collect Loop MVP Specification

Version: 1.0. This file is part of the immutable template baseline.

## Player-facing loop

The player starts near the left side of a single 2D arena. Move with WASD or the arrow keys and touch each glowing token before the countdown reaches zero. Collecting the configured target wins the round. The timer reaching zero loses the round. Press R after either result to restart with a full timer and all tokens restored.

The MVP uses simple shapes drawn by Godot at runtime. It has no external art, audio, network services, exports, save data, enemies, or additional levels.

## Editable rules

- `target_count`: integer 1 through 8; number of tokens required and placed in the arena.
- `time_limit`: number from 10 through 300 seconds; round countdown.
- `player_speed`: number from 60 through 400 pixels per second.
- `initialized`: boolean lifecycle gate. The trusted template sets this to false. The implementation packet may set it to true only after the separately verified project preparation stage.

## Acceptance behavior

1. The uninitialized template displays a preparation message and does not enter the playable state.
2. An initialized game enters `playing`, reads all three gameplay rules, and moves in response to mapped keyboard input.
3. Contact with each token increments the count once. Reaching `target_count` transitions to `won` and stops movement/timing.
4. The countdown reaching zero transitions to `lost` and stops movement.
5. R after either terminal state restores the player, timer, and all tokens and transitions to `playing`.

## Visual direction

A compact top-down arena with a dark blue field and fine grid, a teal circular player, and warm gold circular tokens. All visuals are procedural primitives; the shapes are clear at the fixed 640×360 logical viewport.
