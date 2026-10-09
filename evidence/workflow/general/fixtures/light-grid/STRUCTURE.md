# Project Structure

- `main-scene` (scene): Light Grid Main Scene. Owns scene composition and coordinates input, puzzle state, board rendering, and HUD updates. Input actions are handled separately in puzzle_input.gd. Sources: scenes/main.tscn, scripts/main.gd, scripts/puzzle_input.gd.
- `puzzle-board` (entity): Puzzle Board. Renders nine square buttons in three rows and three columns. Emits cell selections and displays state supplied by the rules. Lit squares use the chosen accent; unlit squares use a dark neutral fill. ON and OFF labels distinguish states independently of color. Sources: scripts/puzzle_board.gd.
- `puzzle-board.accent-color` (choice): Accent color; current value `"#38BDF8"`; editable `true`.
- `rules` (rule): Lights Out Rules. Owns the nine light states, legal toggles, deterministic start generation, move count, solved detection, and reset. Contains no rendering or input handling. Sources: scripts/rules.gd.
- `hud` (interface): Puzzle HUD. Displays Light Grid, instructions, move count, Reset, and the win message. Emits reset requests without mutating puzzle state. Sources: scripts/hud.gd.

Backend-owned protocol files: `design/game.json` and `studio/runtime.gd`. Producer-owned paths remain subject to the frozen scope audit.
