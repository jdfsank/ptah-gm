# Reviewed Game Specification

A small Godot 4 GDScript side-view jump game. Move the cyan player at 300 px/s with the left/right arrow keys and jump with Space to cross three visible platforms and reach a green exit. Preserve the existing platforms and controls. Falling restarts the level, and R resets it during play or after winning. Restart must clear stale exit contact so the player remains in the playing state at spawn and can complete another attempt. Use a fixed 960x540 view, procedural shapes, one level, and no sound, external assets, plugins, or network access. Keep simulation, input actions, rendering, and interface responsibilities separate.

- Object protocol: `studio.objects.v1`
- Dimension: 2D
- Tag: `v0.1.0`
- Normative plan: `PLAN.md`
