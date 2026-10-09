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

## Local Submit v0.3 — 2026-10-07

Round 1 retained the existing domain editor and added only a small React shell;
no router, global state library, source rewrite, or generic platform was added.
Round 2 independent review found and corrected uncertain-delivery recovery,
source/draft provenance, cwd pinning, JSON-RPC request ID collisions and restart
lease issues. Round 3 independently re-reviewed the final contract with no
remaining blocking protocol/state/security findings.

- Existing 13 DOM and 14 semantic checks remain in the aggregate suite.
- 14 React integration checks use built JS, real domain scripts and mocked fetch.
- Python unit tests mock app-server and HTTP transport; test names document the
  durable storage, source/revision, protocol and security cases.
- Actual installed codex-cli 0.159.2 generated the experimental JSON schemas.
  `TurnStartParams` exposes `input` and `toolOutput`; output accepts the implemented
  name/namespace/output shape. This proves schema capability, not a completed turn.
- Actual uv invocation reaches the CLI help. This restricted executor needs
  `UV_CACHE_DIR=/tmp/dna-uv-cache`; ordinary writable local installs use default uv cache.
- `npm run build`, `npm run check`, `npm test`, Python compile and `git diff --check`
  are the local release checks. Generated reports distinguish mocked evidence.

No real Codex inference, automatic Godot writeback test, rendered-browser visual
QA, public deploy, Site update or push was performed. Previous browser localhost
policy restrictions were respected. Day/night contrast is implementation/static
review evidence, not a rendered accessibility certification.
