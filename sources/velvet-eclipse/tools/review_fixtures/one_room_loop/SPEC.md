# Fixed one-room loop smoke fixture

This source-controlled fixture exercises the local smoke infrastructure against
Godot 4.6.3. It is not an AI-generated game, a visual-quality review, a screenshot
capture, or evidence that a generated project's mechanics work.

## Required mechanics

- **FX-M1 — Start:** A visible start menu contains a title and a working Start
  button. Movement is inactive before Start. Activating Start enters the room
  and displays the gameplay HUD.
- **FX-M2 — Movement and collision:** WASD/arrow actions drive a
  `CharacterBody2D` using `move_and_slide()`. Solid boundary colliders stop it.
- **FX-M3 — Key, gate, and HUD:** Before key pickup, the closed gate physically
  blocks passage and its sensor displays locked feedback. Entering the key's
  `Area2D` collects one key, hides the pickup, and changes the visible key HUD
  from `Key: 0/1` to `Key: 1/1`. Re-entering cannot duplicate the key. After
  pickup, entering the gate's sensor opens its collision shape, updates the gate
  HUD, and allows the player to cross.
- **FX-M4 — Pause and resume:** The Pause button stops gameplay movement while a
  held movement action is active. The visible pause menu remains keyboard
  navigable between Resume and Restart. Resume restores gameplay without stuck
  movement after the action is released; fresh movement input still works.
- **FX-M5 — Exit and result:** Opening the gate alone cannot win. Walking through
  the exit `Area2D` with the key and an open gate displays the result title and
  Play again button, hides the HUD, and stops gameplay movement.
- **FX-M6 — Clean restart:** Activating Play again resets the win state, player
  spawn, key inventory and pickup, gate collision, HUD, pause, velocity, and
  held movement actions. The new round physically blocks the gate until its
  key is collected, and that key can be collected again via its trigger.

## Game-code variants

The baseline is `const NAME: String = "baseline"` in `variant.gd`. A launcher
copies this fixture and changes only that constant for a fault run. It must not
change the smoke tests or expected assertions.

| Variant | Actual game defect | Required detection |
| --- | --- | --- |
| `always_open_door` | Gate starts open with its collision shape disabled | FX-M3 locked-gate collision/feedback and initial HUD fail |
| `stale_hud` | Pickup changes inventory but does not update the key Label | FX-M3 pickup HUD fails |
| `pause_input_leak` | Player processes movement even while the SceneTree is paused | FX-M4 paused movement fails |
| `dirty_restart` | Restart preserves the collected key and open gate | FX-M6 clean inventory/gate reset fails |

## Oracle and scope

The same `tests/smoke_runner.gd` SceneTree runs every variant. It never reads the
variant configuration, never assigns inventory/gate/win state, never teleports
the player, and never calls game transition methods or emits button signals.
It injects movement actions and awaits real physics frames. UI interaction uses
viewport mouse events and keyboard focus navigation on real `Control`, `Label`,
and `Button` nodes. Assertions observe world state, physics positions, and UI
properties; they are behavioral assertions, not visual proof.

The report is UTF-8 JSON with `schema_version: 1`, a nonempty `cases` array, and
uppercase `result: PASS|FAIL`. Every case has a unique `id`, a `mechanic` from
FX-M1 through FX-M6, `required: true`, uppercase `status: PASS|FAIL`, and a
human-readable `detail`. Any failed required case produces exit code 1. Missing
or unwritable report output produces exit code 2. Exit code 0 requires every
assertion to pass and the report to have been written.

## Native virtual-key compatibility

WASD bindings retain physical key positions. Arrow bindings use their logical
keycodes, which are layout-independent directional keys and remain usable when
a virtual desktop sends a correct keycode with an absent or incorrect physical
field. This does not promote virtual-input evidence to physical-device proof.
