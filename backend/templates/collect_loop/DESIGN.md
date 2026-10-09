# Systems Design

## Rules and lifecycle
`config/rules.json` is the runtime authority for `initialized`, `target_count`, `time_limit`, and `player_speed`. The uninitialized state renders a preparation message and does not start a round. The producer may change these values only to the exact coordinator-approved values.

## Round states
The round moves from `playing` to exactly one terminal state, `won` or `lost`. Terminal states stop movement and countdown. Retry restores the starting position, timer, and all tokens before returning to `playing`.

## Movement and collection
Mapped directional input drives a `CharacterBody2D` with normalized vector movement. A player `Area2D` overlaps token areas; each token is removed after one collection. Player and token collision layers and masks are explicit.

## Verification boundary
The fixed headless harness exercises movement, collision collection, timer loss, and both retries. It does not establish visual quality, release packaging, or human acceptance.
