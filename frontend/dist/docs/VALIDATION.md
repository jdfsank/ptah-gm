# Validation · semantic v2

27 focused checks passed: 13 preserved DOM journeys and 14 semantic/model/DOM checks. All 38 behavior views and D/N/A facets render through tested DOM paths.

21 objects; 38 behaviors; 93 source instances/entrance markers (14 markers, 7 ordinary enemy placements); 9 spawn rules; 13 actual SpriteFrames clips (7 player, 4 dealer, 2 boss), represented only by first-frame thumbnails.

Source manifest: 69 text files, hashes rechecked unchanged. 338 source references and 455 ledger records, including semantic reverse entries. Counts are not independent discovery counts or a claim of full game completeness. Within the declared finite inventory, 0 unassigned ownership records. Component/file ownership is coarser than writable field-level mapping.

Ledger denominators:
- animation-resource: 13
- code: 46
- declared-state: 138
- design-document: 5
- input: 15
- resource-binding: 23
- scene-data: 5
- scene-ui-resource: 9
- scope-exclusion: 5
- semantic-reverse: 161
- state-assignment: 35

## Execution checklist result
A: Scope, exclusions, source lock and no-writeback claim recorded.
B: Design, code, components, input, bound resources, room data and UI scenes/theme surveyed; automatic/default/failure paths represented. Engine tests not run.
C: Actors (including all enemies), environment/transients, session/progression/UI/rules separated. Definitions/instances/spawn rules are distinct.
D: Stable IDs, source hashes/line links, independent implementation/mapping/editability/verification fields.
E: Bidirectional finite inventory validated; exclusions remain visible.
F: Original rooms retained, existing journeys preserved, old draft migration/backup tested, puzzle/story fixtures pass. Source writeback round trip: N/A, unsupported.

## Remaining verification limits
No new Godot engine run, browser rendering screenshot, real touch-device test or live WebMCP execution. Prior local browser access was blocked, so DOM tests are not presented as rendered QA. First-frame thumbnails and timing/velocity diagrams are visual explanations only.
