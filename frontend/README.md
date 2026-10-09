# DNA · Reviewed workbench v0.6

Existing private DNA frontend regenerated from a reusable semantic object method and a reviewed Velvet Eclipse source adapter. The native editor is retained inside a simplified collapsible navigation / working surface / current-target detail layout. Scene composition, transitions, bounded proposal sandbox, local drafts and undo remain available.

## v0.6 comments and simplified workspace

All 183 addressable model targets support per-target natural-language comments: project, scenes, backgrounds, instances (including entries/exits), transitions, shared definitions, behaviors, both shared transition presets and nine spawn rules. The current detail contains one comment editor; the separate submission dialog reviews every nonempty comment and net content change. Read-only values still accept comments. Unknown executable mappings remain explicitly blocked.

Comments auto-save locally; domain drafts retain explicit Save / Reopen semantics. A missing draft target leaves an explicit orphan comment, never an implicit project instruction. V2 is the supported default; preset/rule/transition comments cannot silently downgrade to v1 project authority.

See [v6 coverage, workflow and verification limits](docs/VALIDATION-v6.md). Rendered browser QA was blocked by the cloud preview connection; DOM/contract tests are not a visual pass.

## v0.5 bounded transition integration

Every existing directed exit now derives an addressable Transition target with `sourceExitRef`. Its destination remains resolved from the existing door; no duplicate destination is saved. `unset`, `none`, and a read-only shared `black_fade` / `mask_wipe` preset reference remain separate. Initial import is zero-diff. Mask has no bound engine resource; previews are browser-only effect illustrations.

Transition edits require v2 and exact server-reviewed source/target mappings. New draft exits have no executable mapping. Legacy v1 remains available for existing target types, without falling back to project-wide authority for transitions.

See [v5 validation and self-review](docs/VALIDATION-v5.md) and [remaining real chain boundaries](docs/chain-boundaries-v5.md). The new integration exercises the actual domain editor and React shell through frozen v2, the Python-owned baseline validator, and the exact browser-demo receipt. It uses no model calls and does not certify Codex, GM, or Godot execution.

## Reviewed workflow

Scene-first navigation, explicit instance/shared targets, name/ID search and history, mandatory immutable submission preview, and versioned fail-closed GM routing are described in [the workflow](docs/REVIEWED-WORKFLOW.md). V1 stays compatible; v2 is negotiated and does not widen authorization to the full snapshot.

## Local Submit

The reusable React shell preserves the existing domain editor. Black/white day/night chrome, scoped notes, durable Submit and a loopback uv/Python bridge are implemented. See [local setup, recovery and security](docs/LOCAL-SUBMIT.md). Default bridge mode is demo; real Codex requires an explicit existing thread and matching source directory. The original owner-private Site remains a labeled browser-only simulation; the local source includes the bridge.

中文本地启动与交付边界见 [交付说明](docs/交付说明.md)。GM v2 见 [adapter contract](docs/GM-ADAPTER-V2.md)。

## Start and verify

Serve `dist/` with a static HTTP server. Development: `npm ci` then `npm run check && npm test` (Node 22+).

Regenerate from the current read-only game source: `python3 tools/extract-velvet.py /absolute/path/to/velvet-eclipse`. The adapter checks its reviewed source hash lock. If source changes, review the mappings before intentionally using `--accept-reviewed-source`. This is an explicit project adapter, not a universal source-code parser.

## Included work

- `docs/SEMANTIC-OBJECT-METHOD.md`: general methodology, boundaries, optional DNA facets and honest capability claims
- `docs/EXECUTION-CHECKLIST.md`: reusable A–F execution checklist
- `docs/semantic-model.schema.json` and `dist/semantic-model.js`: engine-neutral schema, cross-reference validator and local draft migration
- `fixtures/puzzle.json` and `fixtures/story.json`: small noncombat model examples, not extra games
- `dist/semantic-data.json`: 21 semantic objects, 38 behaviors, 93 placed records/entrance markers, 9 spawn rules, complete raw five-room snapshot
- `dist/evidence/`: source-text snapshots with line anchors and hashes
- `dist/assets/clips/`: 13 authentic clip first-frame thumbnails; no animation playback claim
- `tests/`: 13 preserved DOM journeys + 14 semantic/model/DOM checks, all passing

## Truthful boundaries

Objects are based on meaningful recognition/editing/reuse/verification, not files, nodes or artwork counts. Player definition is distinct from room entrances; three enemy archetypes include AI, motion, states and presentation. Flying cards have movement with no frame animation. The boss has no locomotion strategy and only idle/attack clips. Session/map/pause are separate from actor animation.

Behavior views distinguish continuous motion, actions, passive responses, interactions and rules. Known editable fields remain browser-local shared drafts; other values are read-only. Sword VFX is 0.20 seconds while hitbox active lifetime is 0.14 seconds. The independent VFX start field is a conceptual derived value, not a native engine timeline.

The browser editor itself performs no Godot writeback or actual AI calls. Only explicit Submit in configured local Codex mode may ask Codex to change source. There is no physics, live runtime instances, resource generation, cloud synchronization or engine certification. First-frame thumbnails and a parameter velocity curve are not live engine previews. Source statements are static evidence, not fresh game tests. Native WebMCP registration was tested only with a mock context.

## Persistence

The storage key remains `dna-velvet-concept-v1` for discoverability; saved schema is v2. Existing v1 drafts migrate on explicit reopening, preserving layout, overrides, unknown data and prior sword values. Page load never overwrites the stored draft. Saving over an existing draft requires confirmation and retains a first-overwrite backup. Raw original/backup export is available. An incompatible version leaves the current workspace and stored bytes untouched.

## Validation limits

See `docs/VALIDATION.md` and JSON test reports. Core model and all 38 behavior views were checked with jsdom. Rendered desktop/mobile browser QA was unavailable because the earlier local preview/browser access was blocked. No screenshots were fabricated. The source game and archived framework were not edited.

## Private hosted browser demo (2026-10-08)

The private `*.chatgpt.site` publication uses an explicitly labeled browser-local
Submit simulation. Receipts and notes are stored only in that browser's local
storage; it makes no API/model requests and never edits a Godot project. A refresh
restores the same receipt without resubmission. Browser storage is not a backup or
cloud sync. Local hosting retains the original bridge flow by default; `?demo=1`
is an explicit local UI-test option. The model's snapshot contents are not applied
by this simulation, and “演示验证” does not certify game behavior or source changes.

The original 41 DOM/model/React checks and 24 Python tests pass. The additional
hosted demo DOM test covers theme/notes, typed edits, instant receipt, duplicate
click suppression, refresh recovery and zero network calls. These are DOM tests,
not rendered-browser or mobile-layout certification. The cloud browser could not
reach the sandbox-local preview; this environment has no managed preview service.

## Reviewed v0.4 delivery (2026-10-08)

Mandatory preview, unified scene/instance/shared targets and explicitly negotiated
GM v2 are implemented. Independent review regressions cover drag scope, canceled
or invalidated previews, reviewed authority races, contradictory diffs, and
out-of-scope evidence. See [current validation](docs/VALIDATION-2026-10-08-v4.md)
and [GM contract and limits](docs/GM-ADAPTER-V2.md). Global formal-run verification
is separate from request-specific implementation and item coverage; absent the
latter evidence, item results remain BLOCKED. No real Codex/GM/Godot cycle or
human acceptance was performed here.
