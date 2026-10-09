# Scene Specification

## Main arena
`scenes/main.tscn` is the only scene and uses a 640×360 logical viewport. It contains the main controller, player, readable HUD, arena boundary, and runtime-created token positions. The controller draws the dark-blue grid and terminal feedback with procedural primitives.

## Player
The player is a teal circle with a fixed circular collision shape. It remains inside the arena bounds and responds to WASD and arrow-key actions while the round is active.

## Tokens and HUD
Tokens are warm-gold circles with collision areas. The HUD shows collected/required count and remaining time; terminal text distinguishes win, loss, and locked preparation state.
