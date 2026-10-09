# Architecture and Constraints

- Current release is v0.1.0. PLAN.md is scope/task authority; GDD.md and ROADMAP.md carry the user's approved intent.
- The game is original, uses Godot 4.6.3 Compatibility + real gecs 7.1.0, and targets local WebAssembly/WebGL2 desktop keyboard play. Exact offline Web templates live in /workspace/shared/velvet-export-tools/4.6.3.stable.
- STRUCTURE.md owns ECS component schemas, explicit World registration, safe deferred materialization and the single MovementSystem transform writer.
- ASSETS.md owns verified runtime bindings. Rich illustrated imagegen actors/backgrounds/terrain/props are mandatory; procedural UI/effects are separately planned. User concepts are source-only.
- Only one active game/planning/asset writer. The Evaluator alone owns e2e/ tests. No public hosting/push is requested. A reproduced gdUnit report-path compatibility defect was separately authorized and narrowly fixed in system commit 21ab459; game tool sync is d7496f8. Original ERROR evidence is preserved.
- Exact scope approval is host-provided chat provenance in docs/USER-APPROVAL.md. Never represent it as local TTY confirmation or final game acceptance.

- Verified actor canvas/foot alignment and platform walk-edge offsets are recorded in ASSETS.md “Verified Runtime Binding Measurements”; binding must preserve those offsets.

- Browser persistence uses the application-owned, namespaced localStorage adapter documented in STRUCTURE.md; native FileAccess remains separate. Neither path stores account credentials or sends game progress to a remote service.

## Delivery state (2026-10-06)

- Implemented all approved five-room mechanics, UI, save/retry and two-phase ending loop. Final native unit regression is 78/78; independent ordinary-input native full loop, restart and process-relaunch persistence have visible evidence.
- Necessary final repair fa18ed5 moves the Boss bar out of the heroine ground-combat lane. Web v2 is a separate frozen export; fresh native replay verifies the repaired HUD through both phases, while full ending/restart evidence belongs to v1. v1 evidence remains immutable.
- Cloud browser navigation returned ERR_BLOCKED_BY_CLIENT before requesting the game; no Web runtime, input, rendering or browser persistence success is claimed. No alternate-host bypass or public upload was used.
- Full bound review and human acceptance remain incomplete. The supplied chat scope approval is not TTY confirm-spec/acceptance. Do not synthesize missing E2E, platform or user decisions.
- Audio remains intentionally absent; the 10–15 minute duration is a design target rather than a measured human completion time.
