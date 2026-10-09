# Design Notes

A small 2D puzzle in a fixed 960×540 window. Clicking a square toggles its light and its orthogonal neighbors. Turn every light off to win. Display moves, concise instructions, a Reset button, and a win message. Use procedural squares and labels without external assets, plugins, network, or audio.

## Object Relationships
- `main-scene` parent `none`; relations: contains → puzzle-board, contains → rules, contains → hud
- `puzzle-board` parent `main-scene`; relations: displays-state-of → rules
- `rules` parent `main-scene`; relations: none
- `hud` parent `main-scene`; relations: displays-progress-of → rules

## Field and Feedback Changes
- No structured field changes or feedback were attached to this planning turn.
