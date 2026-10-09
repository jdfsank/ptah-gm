# Project Structure

- `project.godot`: Godot project settings, main scene, and mapped keyboard actions.
- `scenes/main.tscn`: the sole game scene.
- `scripts/main.gd`: lifecycle, arena, timer, token collection, terminal states, and retry.
- `scripts/player.gd`: bounded keyboard-driven player movement and collision shape.
- `config/rules.json`: the only implementation-stage editable document.
- `initialization.json`: server-assigned preparation manifest, editable only during initialization.
- `tests/closed_loop.gd`: deterministic headless gameplay harness.
- `SPEC.md`, `PLAN.md`, `GDD.md`, `DESIGN.md`, `SCENES.md`, and `ASSETS.md`: immutable normative template documents.
